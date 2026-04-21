"""
test_direct_recording.py
────────────────────────────────────────────────────────────────────────────
CONNECT 6 (iPhone) + Sound Blaster G8 (Android) 직접 녹음 테스트 스크립트.

연결 구성:
  iPhone ── USB-C ──→ CONNECT 6 MOBILE 포트 ──→ Mac USB
  Android ── 3.5mm/LineIn ──→ Sound Blaster G8 ──→ Mac USB

사용법:
  python test_direct_recording.py                  # 기본 30초 녹음
  python test_direct_recording.py --duration 60    # 60초 녹음
  python test_direct_recording.py --list           # 장치 목록만 표시

출력:
  audio_files/recordings/iOS_ixiO_{timestamp}.wav
  audio_files/recordings/Android_ixiO_{timestamp}.wav
────────────────────────────────────────────────────────────────────────────
"""

import argparse
import queue
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 48_000
DTYPE = 'float32'
OUTPUT_DIR = Path(__file__).parent / 'audio_files' / 'recordings'


# ─────────────────────────────────────────────────────────────────────────────
# 장치 탐색
# ─────────────────────────────────────────────────────────────────────────────

def find_input_device(name_pattern: str) -> int | None:
    """장치 이름에 패턴이 포함된 입력 장치 인덱스 반환."""
    for i, dev in enumerate(sd.query_devices()):
        if dev.get('max_input_channels', 0) > 0 and name_pattern in dev.get('name', ''):
            return i
    return None


def list_input_devices():
    """모든 입력 장치 출력."""
    print("\n📋 입력(녹음) 장치 목록:")
    print("-" * 70)
    for i, dev in enumerate(sd.query_devices()):
        if dev.get('max_input_channels', 0) > 0:
            print(f"  [{i:2d}] {dev['name']:40s}  ch={dev['max_input_channels']}  sr={dev['default_samplerate']:.0f}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 단일 채널 녹음기
# ─────────────────────────────────────────────────────────────────────────────

class ChannelRecorder:
    """단일 USB 입력 장치에서 녹음 (스레드 안전)."""

    def __init__(self, device_index: int, label: str, channels: int = 2):
        self._device = device_index
        self._label = label
        self._channels = channels
        self._q: queue.SimpleQueue[np.ndarray] = queue.SimpleQueue()
        self._chunks: list[np.ndarray] = []
        self._running = False
        self._stream: sd.InputStream | None = None
        self._drain_thr: threading.Thread | None = None
        self._peak = 0.0

    def _callback(self, indata: np.ndarray, _frames, _time, status):
        if status:
            print(f"  ⚠️ [{self._label}] {status}", flush=True)
        if self._running:
            self._q.put(indata.copy())
            peak = np.max(np.abs(indata))
            if peak > self._peak:
                self._peak = peak

    def start(self):
        self._chunks.clear()
        self._peak = 0.0
        self._running = True

        dev_info = sd.query_devices(self._device)
        avail_ch = dev_info.get('max_input_channels', 1)
        open_ch = min(self._channels, max(avail_ch, 1))

        self._stream = sd.InputStream(
            device=self._device,
            channels=open_ch,
            samplerate=SAMPLE_RATE,
            dtype=DTYPE,
            callback=self._callback,
        )
        self._stream.start()
        self._drain_thr = threading.Thread(target=self._drain, daemon=True)
        self._drain_thr.start()
        print(f"  🎙️ [{self._label}] 녹음 시작 (dev={self._device}, ch={open_ch})")

    def stop(self) -> np.ndarray:
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._drain_thr:
            self._drain_thr.join(timeout=2.0)
        while not self._q.empty():
            try:
                self._chunks.append(self._q.get_nowait())
            except Exception:
                break
        if not self._chunks:
            return np.zeros((0,), dtype=DTYPE)
        raw = np.concatenate(self._chunks, axis=0)
        # 스테레오 → 모노 믹스다운
        if raw.ndim > 1 and raw.shape[1] > 1:
            raw = raw.mean(axis=1)
        return raw.flatten()

    def _drain(self):
        while self._running:
            try:
                self._chunks.append(self._q.get(timeout=0.5))
            except Exception:
                continue


# ─────────────────────────────────────────────────────────────────────────────
# WAV 저장
# ─────────────────────────────────────────────────────────────────────────────

def save_mono_wav(path: Path, audio: np.ndarray, sr: int = SAMPLE_RATE):
    """float32 모노 → 16-bit PCM WAV."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def rms_dbfs(audio: np.ndarray) -> float:
    """RMS를 dBFS로 변환."""
    rms = np.sqrt(np.mean(audio ** 2))
    if rms < 1e-10:
        return -120.0
    return 20 * np.log10(rms)


# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='CONNECT 6 + G8 직접 녹음 테스트')
    parser.add_argument('--duration', type=int, default=30, help='녹음 시간 (초, 기본 30)')
    parser.add_argument('--list', action='store_true', help='입력 장치 목록만 표시')
    parser.add_argument('--ios-device', type=int, default=None, help='iOS 녹음 장치 인덱스 (기본: CONNECT 6 자동감지)')
    parser.add_argument('--android-device', type=int, default=None, help='Android 녹음 장치 인덱스 (기본: G8 자동감지)')
    args = parser.parse_args()

    if args.list:
        list_input_devices()
        return

    # 장치 탐색
    ios_idx = args.ios_device if args.ios_device is not None else find_input_device('CONNECT 6')
    android_idx = args.android_device if args.android_device is not None else find_input_device('Sound Blaster G8')

    print("\n" + "=" * 60)
    print("  🎧 직접 녹음 테스트 (CONNECT 6 + G8)")
    print("=" * 60)

    if ios_idx is None:
        print("❌ CONNECT 6 장치를 찾을 수 없습니다.")
        print("   → Mac에 CONNECT 6가 USB로 연결되어 있는지 확인하세요.")
        list_input_devices()
        sys.exit(1)

    if android_idx is None:
        print("❌ Sound Blaster G8 장치를 찾을 수 없습니다.")
        print("   → Mac에 G8가 USB로 연결되어 있는지 확인하세요.")
        list_input_devices()
        sys.exit(1)

    ios_dev = sd.query_devices(ios_idx)
    android_dev = sd.query_devices(android_idx)
    print(f"\n  📱 iOS     → [{ios_idx}] {ios_dev['name']} ({ios_dev['max_input_channels']}ch)")
    print(f"  📱 Android → [{android_idx}] {android_dev['name']} ({android_dev['max_input_channels']}ch)")
    print(f"  ⏱️  녹음 시간: {args.duration}초")
    print(f"  📁 저장 경로: {OUTPUT_DIR}")
    print()

    # 출력 디렉토리 생성
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 녹음기 생성
    ios_rec = ChannelRecorder(ios_idx, 'iOS/CONNECT6', channels=2)
    android_rec = ChannelRecorder(android_idx, 'Android/G8', channels=2)

    # 동시 녹음 시작
    print("🔴 녹음 시작...")
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    ios_rec.start()
    android_rec.start()

    # 카운트다운 + 레벨 모니터링
    try:
        for remaining in range(args.duration, 0, -1):
            ios_peak_db = 20 * np.log10(max(ios_rec._peak, 1e-10))
            and_peak_db = 20 * np.log10(max(android_rec._peak, 1e-10))
            bar_ios = _level_bar(ios_rec._peak)
            bar_and = _level_bar(android_rec._peak)
            sys.stdout.write(
                f"\r  ⏱️ {remaining:3d}s 남음  "
                f"│ iOS {bar_ios} {ios_peak_db:+5.1f}dB  "
                f"│ And {bar_and} {and_peak_db:+5.1f}dB  "
            )
            sys.stdout.flush()
            ios_rec._peak = 0.0
            android_rec._peak = 0.0
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n⏹️ 사용자 중단")

    print("\n\n🟢 녹음 종료...")

    # 녹음 중단 + WAV 저장
    ios_audio = ios_rec.stop()
    android_audio = android_rec.stop()

    ios_path = OUTPUT_DIR / f"iOS_ixiO_{ts}.wav"
    android_path = OUTPUT_DIR / f"Android_ixiO_{ts}.wav"

    print(f"\n📊 녹음 결과:")
    print("-" * 60)

    if len(ios_audio) > 0:
        save_mono_wav(ios_path, ios_audio)
        dur = len(ios_audio) / SAMPLE_RATE
        dbfs = rms_dbfs(ios_audio)
        print(f"  ✅ iOS:     {ios_path.name}  ({dur:.1f}s, RMS {dbfs:+.1f} dBFS)")
    else:
        print(f"  ❌ iOS:     데이터 없음 — CONNECT 6 입력 확인 필요")

    if len(android_audio) > 0:
        save_mono_wav(android_path, android_audio)
        dur = len(android_audio) / SAMPLE_RATE
        dbfs = rms_dbfs(android_audio)
        print(f"  ✅ Android: {android_path.name}  ({dur:.1f}s, RMS {dbfs:+.1f} dBFS)")
    else:
        print(f"  ❌ Android: 데이터 없음 — G8 입력 확인 필요")

    print("-" * 60)
    print(f"  📁 {OUTPUT_DIR}")
    print()

    # 레벨 경고
    for label, audio in [('iOS', ios_audio), ('Android', android_audio)]:
        if len(audio) == 0:
            continue
        dbfs = rms_dbfs(audio)
        if dbfs < -50:
            print(f"  ⚠️ {label} 신호가 매우 약합니다 ({dbfs:+.1f} dBFS)")
            print(f"     → 단말 볼륨을 높이거나 장치 연결 상태를 확인하세요.")
        elif dbfs > -3:
            print(f"  ⚠️ {label} 클리핑 위험 ({dbfs:+.1f} dBFS)")
            print(f"     → 단말 볼륨을 낮추세요.")


def _level_bar(peak: float, width: int = 15) -> str:
    """피크 값을 시각적 레벨 바로 변환."""
    level = int(min(peak, 1.0) * width)
    return '█' * level + '░' * (width - level)


if __name__ == '__main__':
    main()
