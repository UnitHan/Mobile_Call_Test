"""
audio_player_worker.py
──────────────────────────────────────────────────────────────────────────────
독립 subprocess로 실행되는 오디오 재생 워커.

macOS CoreAudio AUHAL 제약(동일 프로세스 내 두 USB 스트림 동시 불가)으로 인해
DeviceAudioPlayer가 독립 Python 프로세스로 이 스크립트를 실행합니다.
각 subprocess는 고유한 PortAudio 인스턴스를 보유해 두 USB 장치를 동시 재생할
수 있습니다.

사용법:
    python audio_player_worker.py \\
        --file /path/to/audio.wav \\
        --device 2 \\
        --channel L \\
        --speaker-id speaker1 \\
        [--usb-order 1]
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path


def _log(log_file, msg: str) -> None:
    """파일과 stdout 양쪽에 출력."""
    print(msg, flush=True)
    log_file.write(msg + '\n')
    log_file.flush()


def _recover_usb_device(device: int, usb_order: int | None) -> tuple[int, object]:
    """지정 index가 USB 장치가 아닌 경우(macOS 재열거) usb_order로 복구.

    USB 감지는 usb_audio_devices.get_usb_audio_output_indices() 에 위임합니다.
    """
    import sounddevice as sd
    from usb_audio_devices import get_usb_audio_output_indices

    devices = sd.query_devices()
    dev_info = devices[device]
    dev_name: str = dev_info['name']

    is_usb = 'USB' in dev_name or 'CONNECT 6' in dev_name
    if not is_usb and usb_order is not None:
        all_usb = get_usb_audio_output_indices()
        if all_usb:
            idx = usb_order - 1
            recovered = all_usb[idx] if idx < len(all_usb) else all_usb[0]
            return recovered, devices[recovered]

    return device, dev_info


def play(
    audio_file: str,
    device: int | None,
    channel: str | None,
    speaker_id: str | None,
    usb_order: int | None,
    volume: float = 0.95,
    output_pair: tuple[int, int] | None = None,
    play_at: float | None = None,
    play_at_file: str | None = None,
) -> None:
    """오디오 파일을 지정 장치로 재생합니다.

    output_pair: CONNECT 6 출력 채널 쌍 (0-based). 예: (2,3)=Out 3/4.
                 None이면 기존 방식(채널 0,1)으로 재생.
    """
    import sounddevice as sd
    import soundfile as sf
    import numpy as np

    log_label = device if device is not None else 'default'
    log_path = Path(f'/tmp/audio_play_device_{log_label}.log')
    log_file = open(log_path, 'w', buffering=1)

    def log(msg: str) -> None:
        _log(log_file, msg)

    try:
        raw, file_sr = sf.read(audio_file, always_2d=False)
        log(f"파일 로드: sr={file_sr}, shape={raw.shape}")

        # ── 장치 조회 및 USB 여부 검증 ──────────────────────────────────────
        if device is not None:
            from usb_audio_devices import get_usb_audio_output_indices
            dev_info = sd.query_devices(device, 'output')
            dev_name: str = dev_info['name']
            is_usb = 'USB' in dev_name or 'CONNECT 6' in dev_name

            if not is_usb and usb_order is not None:
                all_usb = get_usb_audio_output_indices()
                if all_usb:
                    log(f"⚠️  [macOS 재열거 감지] device={device} '{dev_name}' 는 USB가 아님")
                    device, dev_info = _recover_usb_device(device, usb_order)
                    dev_name = dev_info['name']
                    log(f"   → usb_order={usb_order} 기준 복구: device={device} '{dev_name}'")
            elif not is_usb:
                log(f"⚠️  device={device} '{dev_name}' 가 USB 장치가 아닙니다!")
        else:
            # device=None → USB 출력 우선; 없으면 시스템 기본 사용 (Background Music 회피)
            from usb_audio_devices import get_usb_audio_output_indices
            usb_out = get_usb_audio_output_indices()
            if usb_out:
                device = usb_out[0]
                dev_info = sd.query_devices(device, 'output')
                log(f"ℹ️ device 미지정 → USB 출력 자동선택: device={device}")
            else:
                dev_info = sd.query_devices(sd.default.device[1], 'output')
                log(f"⚠️ USB 장치 없음 → 시스템 기본 출력 사용 (비권장)")
            dev_name = dev_info['name']

        dev_sr = int(dev_info['default_samplerate'])
        log(f"🔊 [{speaker_id}] device={device} '{dev_name}' sr={dev_sr}Hz  재생 시작")

        # ── 채널 분리 ────────────────────────────────────────────────────────
        if channel in ('L', 'R'):
            if raw.ndim == 2:
                mono = raw[:, 0] if channel == 'L' else raw[:, 1]
            else:
                mono = raw
            data = np.zeros((len(mono), 2), dtype='float64')
            data[:, 0 if channel == 'L' else 1] = mono
        else:
            data = raw.reshape(len(raw), -1) if raw.ndim == 1 else raw

        # ── 샘플레이트 불일치 → 리샘플링 ────────────────────────────────────
        play_sr = dev_sr
        if file_sr != dev_sr:
            log(f"리샘플링: {file_sr} → {dev_sr}")
            try:
                from scipy.signal import resample_poly
                from math import gcd
                g = gcd(dev_sr, file_sr)
                data = resample_poly(data, dev_sr // g, file_sr // g, axis=0)
                log(f"scipy 리샘플링 완료: {data.shape}")
            except ImportError:
                n_new = int(len(data) * dev_sr / file_sr)
                x_old = np.linspace(0, 1, len(data))
                x_new = np.linspace(0, 1, n_new)
                data = np.stack(
                    [np.interp(x_new, x_old, data[:, c]) for c in range(data.shape[1])],
                    axis=1
                )
                log(f"numpy 리샘플링 완료: {data.shape}")

        # ── 음량 정규화 (최대 진폭을 volume 값으로 정규화) ──────────────────
        max_val = float(np.abs(data).max())
        if max_val > 0:
            data = data * (volume / max_val)
            log(f"음량 정규화: {max_val:.4f} → {volume:.2f}")

        # ── 모노 → 스테레오 확장 ────────────────────────────────────────────
        # iRig HD2 / HD X 는 모노 Hi-Z 입력(TS 소켓).
        # TRS 플러그의 Ring(R채널)이 TS 소켓 슬리브(GND)에 쇼트되므로
        # 모노 소스를 스테레오로 확장하면 R채널이 단락 → 왜곡 발생.
        # → 소스가 모노이면 channels=1로 Left(Tip)만 출력해 안전하게 전달.
        if data.shape[1] == 1:
            # 모노 그대로 유지 (channels=1 OutputStream 사용)
            pass
        # 스테레오 소스는 그대로 유지

        out_channels = data.shape[1]
        data = data.astype('float32')

        # ── output_pair 지정 시 멀티채널 매핑 ────────────────────────────────
        # CONNECT 6 출력 8ch: Out 1/2(ch0,1), Out 3/4(ch2,3), Out 5/6(ch4,5), Out 7/8(ch6,7)
        # output_pair=(2,3) → 8ch 스트림을 열고 ch2,3에만 데이터 배치
        if output_pair is not None:
            target_max = max(output_pair) + 1
            dev_max_out = int(dev_info.get('max_output_channels', 2))
            # 요청한 채널 쌍이 장치 최대 채널을 초과하면 ch0,1로 자동 폴백
            if target_max > dev_max_out:
                log(f"⚠️  output_pair={output_pair} 가 장치 최대 채널({dev_max_out})을 초과 → (0,1)로 자동 조정")
                output_pair = (0, 1)
                target_max = 2
            total_out_ch = max(target_max, dev_max_out)
            log(f"🎛 멀티채널 출력: output_pair={output_pair}, "
                f"total_out_ch={total_out_ch}, dev_max={dev_max_out}")

            # 데이터를 total_out_ch 폭 버퍼에 매핑
            mapped = np.zeros((len(data), total_out_ch), dtype='float32')
            if data.shape[1] >= 2:
                mapped[:, output_pair[0]] = data[:, 0]  # L
                mapped[:, output_pair[1]] = data[:, 1]  # R
            else:
                # 모노 소스 → 지정 첫 번째 채널에만
                mapped[:, output_pair[0]] = data[:, 0]
            data = mapped
            out_channels = total_out_ch

        total   = len(data)
        # blocksize 4096 : Python GIL 경쟁에 의한 버퍼 언더런 방지
        # (1024는 ~23ms 단위 → GIL/OS 스케줄러 지연으로 끊김 발생)
        chunk   = 4096
        # AUDIO_PROGRESS 출력 간격: 5초마다 1회 (0.5초→5초 변경)
        # 0.5초 간격 시 75초 오디오 × 2스피커 = ~350회 flush=True 출력 →
        # Tauri IPC 통해 UI 렌더러로 전달되어 장시간 테스트 시 화면 먹통 유발.
        report_every = max(1, int(play_sr * 5.0 / chunk))
        counter = 0

        # ── 재생 ────────────────────────────────────────────────────────────
        import time as _time
        with sd.OutputStream(
            samplerate=play_sr, channels=out_channels,
            device=device, blocksize=chunk,
            latency='high',   # PortAudio에 넌넌한 버퍼 허용 → 끊김 방지
        ) as stream:
            # ── play_at 결정: file 기반 신호 > 명령줄 인자 ─────────────────
            if play_at_file is not None and play_at is None:
                # Pre-warm 모드: 부모 프로세스가 OFFHOOK 시점에 파일을 생성
                log(f"⏱ [{speaker_id}] 초기화 완료 — play_at_file 신호 대기 중: {play_at_file}")
                _poll_deadline = _time.time() + 60.0
                while _time.time() < _poll_deadline:
                    try:
                        with open(play_at_file, 'r') as _pf:
                            _val = _pf.read().strip()
                            if _val:
                                play_at = float(_val)
                                log(f"⏱ [{speaker_id}] play_at_file 수신: {play_at:.6f}")
                                break
                    except (FileNotFoundError, ValueError):
                        pass
                    _time.sleep(0.01)  # 10ms 폴링
                else:
                    log(f"⚠️ [{speaker_id}] play_at_file 60초 타임아웃 — 즉시 재생")

            # play_at 동기 대기: 두 워커가 동일 시각에 재생 시작
            if play_at is not None:
                wait_sec = play_at - _time.time()
                if wait_sec > 0:
                    log(f"⏱ [{speaker_id}] play_at 동기 대기: {wait_sec*1000:.0f}ms")
                    _time.sleep(wait_sec)
                else:
                    log(f"⏱ [{speaker_id}] play_at 이미 {abs(wait_sec)*1000:.0f}ms 초과 — 즉시 재생")
            # 재생 시작 타임스탬프 마커 출력 (녹음 동기화용)
            _play_start = _time.time()
            if speaker_id:
                print(f"AUDIO_STARTED:{speaker_id}:{_play_start:.6f}", flush=True)
                # temp 파일에도 기록 → 부모 프로세스가 폴링으로 읽음
                try:
                    import tempfile, os
                    _ts_path = os.path.join(tempfile.gettempdir(), f"audio_started_{speaker_id}.ts")
                    with open(_ts_path, 'w') as _f:
                        _f.write(f"{_play_start:.6f}")
                except Exception:
                    pass
            log(f"🔔 [{speaker_id}] 실제 재생 시작: {_play_start:.6f}")
            offset = 0
            while offset < total:
                stream.write(data[offset:offset + chunk])
                offset += chunk
                counter += 1
                if speaker_id and counter % report_every == 0:
                    pct = min(1.0, offset / total)
                    print(f"AUDIO_PROGRESS:{speaker_id}:{pct:.3f}", flush=True)

        if speaker_id:
            print(f"AUDIO_PROGRESS:{speaker_id}:1.000", flush=True)
        log(f"✅ [{speaker_id}] 재생 완료 device={device} '{dev_name}'")

    except Exception as exc:
        log(f"❌ [{speaker_id}] 재생 오류 device={device}: {exc}")
        traceback.print_exc(file=log_file)
        sys.exit(1)
    finally:
        log_file.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Audio player worker process')
    p.add_argument('--file',       required=True, help='재생할 오디오 파일 경로')
    p.add_argument('--device',     type=int, default=None, help='sounddevice 출력 장치 index')
    p.add_argument('--channel',    default=None, choices=['L', 'R', None],
                   help='스테레오 채널 분리 (생략 시 양쪽)')
    p.add_argument('--speaker-id', dest='speaker_id', default=None,
                   help='진행률 출력용 ID (speaker1 / speaker2)')
    p.add_argument('--usb-order',  dest='usb_order', type=int, default=None,
                   help='USB 오디오 장치 순서(1-based) — 재열거 시 자동 복구에 사용')
    p.add_argument('--volume',     type=float, default=0.95,
                   help='출력 볼륨 0.0~1.0 (기본 0.95). iRig 과입력 방지 시 낮추세요.')
    p.add_argument('--output-pair', dest='output_pair', default=None,
                   help='CONNECT 6 출력 채널 쌍 (0-based, 콤마 구분). 예: "2,3" → Out 3/4')
    p.add_argument('--play-at', dest='play_at', type=float, default=None,
                   help='재생 시작 동기화 시각 (Unix timestamp). 두 워커가 동시에 재생을 시작합니다.')
    p.add_argument('--play-at-file', dest='play_at_file', default=None,
                   help='재생 시작 시각을 담은 파일 경로 (pre-warm 모드). 부모가 OFFHOOK 시점에 기록.')
    return p.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    # --output-pair "2,3" → (2, 3) 튜플 파싱
    op = None
    if args.output_pair:
        parts = [int(x.strip()) for x in args.output_pair.split(',')]
        if len(parts) == 2:
            op = (parts[0], parts[1])
        elif len(parts) == 1:
            op = (parts[0], parts[0])
    play(
        audio_file=args.file,
        device=args.device,
        channel=args.channel,
        speaker_id=args.speaker_id,
        usb_order=args.usb_order,
        volume=max(0.01, min(1.0, args.volume)),
        output_pair=op,
        play_at=args.play_at,
        play_at_file=args.play_at_file,
    )
