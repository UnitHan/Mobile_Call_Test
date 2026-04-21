"""
USB 사운드카드 2개 동시 재생 테스트
- USB Card 1 (index 0) → Android 단말 (발신) 에 음원 1번 재생
- USB Card 2 (index 2) → iPhone 단말 (수신) 에 음원 2번 재생
- 두 음원을 동시에 재생하여 각 단말 마이크 입력 테스트

사용법:
    python usb_dual_audio_test.py                          # 기본 테스트 톤 생성
    python usb_dual_audio_test.py audio1.wav audio2.wav    # WAV 파일 지정
    python usb_dual_audio_test.py --list                   # 장치 목록 출력
"""

import sys
import time
import threading
import wave
import struct
import math
import argparse
from pathlib import Path

try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    print("❌ 필요한 패키지가 없습니다. 설치 후 다시 실행하세요:")
    print("   pip install sounddevice numpy")
    sys.exit(1)


# ============================================================================
# 설정 (필요 시 수정)
# ============================================================================
# sounddevice 장치 인덱스
# .venv/bin/python usb_dual_audio_test.py --list  로 확인 가능
ANDROID_DEVICE_INDEX = 0   # Sound Blaster G8 USB-1 1번 포트 (Android 발신 단말)
IPHONE_DEVICE_INDEX  = 1   # Sound Blaster G8 USB-1 2번 포트 (iPhone 수신 단말)

SAMPLE_RATE = 48000         # 샘플레이트 (USB 카드 기본값)
TONE_DURATION = 5.0         # 테스트 톤 재생 시간 (초)
# ============================================================================


def list_devices():
    """현재 연결된 오디오 장치 목록 출력"""
    print("\n📋 연결된 오디오 장치 목록")
    print("=" * 60)
    print(f"{'인덱스':>4}  {'이름':<35} {'출력ch':>6} {'입력ch':>6}")
    print("-" * 60)
    for i, d in enumerate(sd.query_devices()):
        marker = ""
        if i == ANDROID_DEVICE_INDEX:
            marker = " ← Android용"
        elif i == IPHONE_DEVICE_INDEX:
            marker = " ← iPhone용"
        print(
            f"  {i:>2}  {d['name']:<35} {d['max_output_channels']:>6} {d['max_input_channels']:>6}{marker}"
        )
    print("=" * 60)
    print(f"\n현재 설정:")
    print(f"  Android → 인덱스 {ANDROID_DEVICE_INDEX}")
    print(f"  iPhone  → 인덱스 {IPHONE_DEVICE_INDEX}")
    print()


def generate_test_tone(frequency: float, duration: float, sample_rate: int, amplitude: float = 0.5) -> np.ndarray:
    """테스트 사인파 톤 생성"""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    tone = amplitude * np.sin(2 * np.pi * frequency * t).astype(np.float32)
    return tone.reshape(-1, 1)  # (samples, 1채널)


def load_wav(filepath: str) -> tuple[np.ndarray, int]:
    """WAV 파일 로드 → (numpy array float32, samplerate)"""
    with wave.open(filepath, 'rb') as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
    dtype = dtype_map.get(sample_width, np.int16)
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32)

    # 정규화 (-1.0 ~ 1.0)
    max_val = float(2 ** (8 * sample_width - 1))
    data /= max_val

    if channels > 1:
        data = data.reshape(-1, channels)
        data = data.mean(axis=1, keepdims=True)  # 모노로 합산
    else:
        data = data.reshape(-1, 1)

    return data, framerate


def play_audio_on_device(audio: np.ndarray, sample_rate: int, device_index: int,
                          label: str, done_event: threading.Event):
    """지정한 장치로 오디오 재생 (블로킹)"""
    try:
        print(f"  ▶ [{label}] 재생 시작 (device={device_index}, {len(audio)/sample_rate:.1f}초)")
        sd.play(audio, samplerate=sample_rate, device=device_index, blocking=True)
        print(f"  ✅ [{label}] 재생 완료")
    except Exception as e:
        print(f"  ❌ [{label}] 재생 오류: {e}")
    finally:
        done_event.set()


def run_dual_test(audio1: np.ndarray, sr1: int,
                  audio2: np.ndarray, sr2: int,
                  android_idx: int, iphone_idx: int):
    """두 사운드카드에 동시 재생"""
    print("\n🚀 동시 재생 시작...")
    print(f"   - Android (card idx={android_idx}): 음원 1 ({len(audio1)/sr1:.1f}초)")
    print(f"   - iPhone  (card idx={iphone_idx}): 음원 2 ({len(audio2)/sr2:.1f}초)")
    print()

    done1 = threading.Event()
    done2 = threading.Event()

    t1 = threading.Thread(
        target=play_audio_on_device,
        args=(audio1, sr1, android_idx, "Android/Card1", done1),
        daemon=True
    )
    t2 = threading.Thread(
        target=play_audio_on_device,
        args=(audio2, sr2, iphone_idx, "iPhone/Card2", done2),
        daemon=True
    )

    start = time.time()
    t1.start()
    t2.start()

    t1.join()
    t2.join()

    elapsed = time.time() - start
    print(f"\n✅ 동시 재생 완료 (총 {elapsed:.1f}초 소요)")


def main():
    parser = argparse.ArgumentParser(
        description="USB 사운드카드 2개 동시 오디오 재생 테스트"
    )
    parser.add_argument("audio1", nargs="?", help="Android용 WAV 파일 (없으면 테스트 톤 사용)")
    parser.add_argument("audio2", nargs="?", help="iPhone용 WAV 파일 (없으면 테스트 톤 사용)")
    parser.add_argument("--list", action="store_true", help="장치 목록만 출력")
    parser.add_argument("--android", type=int, default=ANDROID_DEVICE_INDEX,
                        help=f"Android용 장치 인덱스 (기본: {ANDROID_DEVICE_INDEX})")
    parser.add_argument("--iphone", type=int, default=IPHONE_DEVICE_INDEX,
                        help=f"iPhone용 장치 인덱스 (기본: {IPHONE_DEVICE_INDEX})")
    parser.add_argument("--duration", type=float, default=TONE_DURATION,
                        help=f"테스트 톤 재생 시간 (기본: {TONE_DURATION}초)")
    args = parser.parse_args()

    list_devices()

    if args.list:
        return

    android_idx = args.android
    iphone_idx  = args.iphone

    # ── 음원 1 (Android용) ──
    if args.audio1:
        p = Path(args.audio1)
        if not p.exists():
            print(f"❌ 파일 없음: {args.audio1}")
            sys.exit(1)
        print(f"📂 음원1 로드: {p.name}")
        audio1, sr1 = load_wav(str(p))
    else:
        print(f"🎵 음원1: 테스트 톤 440Hz (Android용, {args.duration}초)")
        sr1 = SAMPLE_RATE
        audio1 = generate_test_tone(440.0, args.duration, sr1)

    # ── 음원 2 (iPhone용) ──
    if args.audio2:
        p = Path(args.audio2)
        if not p.exists():
            print(f"❌ 파일 없음: {args.audio2}")
            sys.exit(1)
        print(f"📂 음원2 로드: {p.name}")
        audio2, sr2 = load_wav(str(p))
    else:
        print(f"🎵 음원2: 테스트 톤 880Hz (iPhone용, {args.duration}초)")
        sr2 = SAMPLE_RATE
        audio2 = generate_test_tone(880.0, args.duration, sr2)

    # ── 동시 재생 ──
    run_dual_test(audio1, sr1, audio2, sr2, android_idx, iphone_idx)


if __name__ == "__main__":
    main()
