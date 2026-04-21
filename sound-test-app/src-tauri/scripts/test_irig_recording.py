#!/usr/bin/env python3
"""
test_irig_recording.py
──────────────────────────────────────────────────────────────────────────
iRig HD2 → G8 마이크 단자 → iPhone 통화음 녹음 경로 검증 스크립트

테스트 순서:
  1) 연결된 G8 입력 장치 목록 출력
  2) iPhone 연결 G8 (ios_b 슬롯, sd_index=0) 에서 N초 녹음
  3) RMS 레벨 / 피크 레벨 측정 (무음 판별)
  4) WAV 저장 후 경로 출력
  5) PASS / FAIL 결과 출력

사용법:
  python3 test_irig_recording.py              # 기본 5초 녹음
  python3 test_irig_recording.py --sec 10     # 10초 녹음
  python3 test_irig_recording.py --dev 1      # 장치 인덱스 직접 지정

iRig HD2 연결 확인 포인트:
  iPhone 헤드폰 잭 → iRig HD2 INPUT
  iRig HD2 OUTPUT  → G8 마이크 단자(External Mic)
  G8 USB          → Mac USB

──────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import sys
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd

# ── 설정 ─────────────────────────────────────────────────────────────────────

SAMPLE_RATE   = 48_000
CHANNELS      = 2
RECORD_SEC    = 5
SILENCE_DBFS  = -50.0   # 이 값 이하이면 무음으로 판정 (dBFS)

# config.RECORDING_GAIN 로드 (없으면 1.0)
def _load_recording_gain() -> float:
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from config import RECORDING_GAIN
        return float(RECORDING_GAIN)
    except Exception:
        return 1.0

# 스크립트 위치 기준으로 저장 디렉토리 결정
_SCRIPT_DIR = Path(__file__).parent
_DEFAULT_OUT_DIR = _SCRIPT_DIR.parent.parent.parent.parent / 'audio_files' / 'recordings'


# ── 유틸 ─────────────────────────────────────────────────────────────────────

def _dbfs(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    if rms < 1e-9:
        return -120.0
    return 20.0 * np.log10(rms)


def _peak_dbfs(audio: np.ndarray) -> float:
    peak = float(np.max(np.abs(audio.astype(np.float64))))
    if peak < 1e-9:
        return -120.0
    return 20.0 * np.log10(peak)


def _ascii_meter(dbfs: float, width: int = 40) -> str:
    """dBFS 값을 ASCII 레벨 미터로 표시."""
    # -60 ~ 0 dBFS 범위
    ratio = max(0.0, min(1.0, (dbfs + 60.0) / 60.0))
    filled = int(ratio * width)
    bar = '█' * filled + '░' * (width - filled)
    return f'[{bar}] {dbfs:+.1f} dBFS'


def _save_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    """float32 → 16-bit PCM WAV 저장."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    n_ch = 1 if audio.ndim == 1 else audio.shape[1]
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(n_ch)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _list_g8_devices() -> list[tuple[int, dict]]:
    """G8 USB 입력 장치 목록 반환."""
    result = []
    for i, d in enumerate(sd.query_devices()):
        if d['max_input_channels'] > 0 and 'Sound Blaster G8' in d['name']:
            result.append((i, d))
    return result


# ── 녹음 함수 ────────────────────────────────────────────────────────────────

def record_seconds(device_index: int, seconds: float) -> np.ndarray:
    """지정 장치에서 N초 녹음 후 float32 배열 반환."""
    dev_info = sd.query_devices(device_index)
    avail_ch = dev_info.get('max_input_channels', 1)
    open_ch  = min(CHANNELS, max(avail_ch, 1))

    frames = int(seconds * SAMPLE_RATE)
    print(f"  🎙️  녹음 중… (장치={device_index}, {open_ch}ch, {seconds:.0f}초)", flush=True)
    print(f"  ⚠️  지금 iPhone에서 소리가 나오고 있어야 합니다!", flush=True)

    data = sd.rec(frames, samplerate=SAMPLE_RATE, channels=open_ch,
                  dtype='float32', device=device_index)
    sd.wait()
    return data  # shape: (frames, channels)


# ── 분석 함수 ────────────────────────────────────────────────────────────────

def analyze(audio_2d: np.ndarray) -> dict:
    """녹음 데이터 분석 결과 반환."""
    # mono 믹스 (분석용)
    if audio_2d.ndim > 1 and audio_2d.shape[1] > 1:
        mono = audio_2d.mean(axis=1)
    else:
        mono = audio_2d.flatten()

    duration = len(mono) / SAMPLE_RATE

    # 전체 RMS / 피크
    rms_db   = _dbfs(mono)
    peak_db  = _peak_dbfs(mono)

    # 0.5초 윈도우별 RMS → 신호가 있는 구간 수 (전체의 몇 %)
    win = SAMPLE_RATE // 2
    windows = [mono[i:i+win] for i in range(0, len(mono) - win, win)]
    active_wins = [w for w in windows if _dbfs(w) > SILENCE_DBFS]
    active_ratio = len(active_wins) / max(len(windows), 1) * 100

    # 채널별 RMS
    ch_rms = []
    for c in range(audio_2d.shape[1] if audio_2d.ndim > 1 else 1):
        ch_data = audio_2d[:, c] if audio_2d.ndim > 1 else audio_2d
        ch_rms.append(_dbfs(ch_data))

    return {
        'duration': duration,
        'rms_db':   rms_db,
        'peak_db':  peak_db,
        'mono':     mono,
        'ch_rms':   ch_rms,
        'active_pct': active_ratio,
        'is_silent': rms_db < SILENCE_DBFS,
    }


def print_level_timeline(mono: np.ndarray, n_blocks: int = 40) -> None:
    """시간축 레벨 변화를 ASCII로 출력."""
    block_size = len(mono) // n_blocks
    if block_size == 0:
        return
    print("\n  시간축 레벨 (왼쪽=녹음 시작, 오른쪽=녹음 끝):")
    bars = ""
    for i in range(n_blocks):
        seg = mono[i * block_size:(i + 1) * block_size]
        db = _dbfs(seg)
        if db > -10:
            bars += '█'
        elif db > -20:
            bars += '▇'
        elif db > -30:
            bars += '▅'
        elif db > -40:
            bars += '▃'
        elif db > SILENCE_DBFS:
            bars += '▁'
        else:
            bars += '·'
    print(f"  |{bars}|")
    print(f"   0s{' ' * (n_blocks - 6)}{len(mono)/SAMPLE_RATE:.1f}s")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description='iRig HD2 → G8 녹음 경로 검증')
    parser.add_argument('--sec',  type=float, default=RECORD_SEC,
                        help=f'녹음 시간 (초, 기본 {RECORD_SEC})')
    parser.add_argument('--dev',  type=int,   default=None,
                        help='sounddevice 입력 장치 인덱스 (미지정 시 ios_b 슬롯 자동 결정)')
    parser.add_argument('--out',  type=str,   default=None,
                        help='WAV 저장 경로 (미지정 시 자동 결정)')
    parser.add_argument('--list', action='store_true',
                        help='장치 목록만 출력 후 종료')
    args = parser.parse_args()

    # ── 1. 장치 목록 출력 ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  G8 USB 입력 장치 목록")
    print("=" * 60)
    g8_devices = _list_g8_devices()
    all_inputs  = [(i, d) for i, d in enumerate(sd.query_devices())
                   if d['max_input_channels'] > 0]

    print("  [전체 입력 장치]")
    for idx, d in all_inputs:
        marker = " ←"  if 'Sound Blaster G8' in d['name'] else ""
        print(f"    [{idx:2d}] {d['name']}{marker}  (in_ch={d['max_input_channels']})")

    if args.list:
        sys.exit(0)

    # ── 2. 녹음 장치 결정 ─────────────────────────────────────────────────
    if args.dev is not None:
        device_index = args.dev
        print(f"\n  → 사용자 지정 장치 인덱스: {device_index}")
    else:
        # config에서 ios_b 슬롯 자동 결정
        device_index = None
        try:
            sys.path.insert(0, str(_SCRIPT_DIR))
            from usb_audio_devices import resolve_usb_input_device_index
            from config import AUDIO_DEVICES
            cfg = AUDIO_DEVICES.get('ios_b', {})
            device_index = resolve_usb_input_device_index(
                location_id=cfg.get('location_id'),
                usb_port_order=cfg.get('usb_port_order', 1),
                device_index_fallback=cfg.get('device_index'),
                role_label='ios_b (iPhone용 G8)',
            )
        except Exception as e:
            print(f"  ⚠️ config 로드 실패: {e}")

        if device_index is None:
            # G8 첫 번째 장치로 fallback
            if g8_devices:
                device_index = g8_devices[0][0]
                print(f"  ⚠️ ios_b 슬롯 미결정 → G8 첫 번째({device_index}) 사용")
            else:
                print("  ❌ G8 장치를 찾을 수 없습니다. USB 연결을 확인하세요.")
                sys.exit(1)
        else:
            print(f"\n  → ios_b 슬롯 자동 결정: 장치 인덱스 {device_index}")

    dev_name = sd.query_devices(device_index).get('name', '?')
    print(f"  → 녹음 장치: [{device_index}] {dev_name}")

    # ── 3. 녹음 ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  📱 녹음 시작: {args.sec:.0f}초")
    print("=" * 60)
    print("  ※ iPhone에서 소리(영상/음악)가 재생 중인지 확인하세요")
    print("  ※ iRig HD2 → G8 External Mic 연결 경로로 녹음합니다\n")

    try:
        audio_2d = record_seconds(device_index, args.sec)
    except Exception as e:
        print(f"\n  ❌ 녹음 실패: {e}")
        sys.exit(1)

    # 소프트웨어 게인 적용
    gain = _load_recording_gain()
    if gain != 1.0:
        audio_2d = np.clip(audio_2d * gain, -1.0, 1.0)
        print(f"  🔊 소프트웨어 게인 적용: x{gain:.1f} (+{20*__import__('math').log10(gain):.1f} dB)")

    # ── 4. 분석 ────────────────────────────────────────────────────────────
    result = analyze(audio_2d)

    print("\n" + "=" * 60)
    print("  📊 녹음 결과 분석")
    print("=" * 60)
    print(f"  녹음 시간:   {result['duration']:.2f}초")
    print(f"  RMS 레벨:    {_ascii_meter(result['rms_db'])}")
    print(f"  피크 레벨:   {result['peak_db']:+.1f} dBFS")
    print(f"  활성 구간:   {result['active_pct']:.0f}% (>{SILENCE_DBFS:.0f} dBFS 기준)")

    if len(result['ch_rms']) > 1:
        print(f"  채널 RMS:    CH0={result['ch_rms'][0]:+.1f} dBFS  |  "
              f"CH1={result['ch_rms'][1]:+.1f} dBFS")

    print_level_timeline(result['mono'])

    # ── 5. WAV 저장 ────────────────────────────────────────────────────────
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    if args.out:
        out_path = Path(args.out)
    else:
        out_dir = _DEFAULT_OUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f'irig_test_{ts}.wav'

    try:
        _save_wav(out_path, audio_2d, SAMPLE_RATE)
        size_kb = out_path.stat().st_size / 1024
        print(f"\n  💾 WAV 저장: {out_path}")
        print(f"     파일 크기: {size_kb:.0f} KB")
    except Exception as e:
        print(f"\n  ❌ WAV 저장 실패: {e}")

    # ── 6. 최종 판정 ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if result['is_silent']:
        print("  ❌  FAIL — 무음 감지 (신호 없음)")
        print()
        print("  확인 사항:")
        print("  1) iPhone 볼륨이 올라가 있는지 확인")
        print("  2) iRig HD2 → G8 External Mic 케이블 연결 확인")
        print("  3) iRig HD2 GAIN 노브가 적절한지 확인 (너무 낮으면 무음)")
        print("  4) macOS 시스템 설정 > 사운드 > 입력이")
        print("     'Sound Blaster G8 USB-1: External Mic' 선택됐는지 확인")
        print("  5) 장치 인덱스가 올바른지: --dev 0 또는 --dev 1 으로 직접 시도")
        print("=" * 60)
        sys.exit(2)
    elif result['active_pct'] < 30:
        print(f"  ⚠️  WARNING — 신호 약함 (활성 구간 {result['active_pct']:.0f}%)")
        print("     iRig GAIN 노브나 iPhone 볼륨을 높여보세요.")
        print("=" * 60)
        # exit(0)으로 처리 — 신호는 있음
    else:
        print(f"  ✅  PASS — 정상 녹음 확인!")
        print(f"     RMS={result['rms_db']:+.1f} dBFS  /  "
              f"피크={result['peak_db']:+.1f} dBFS  /  "
              f"활성={result['active_pct']:.0f}%")
        print("=" * 60)

    print()


if __name__ == '__main__':
    main()
