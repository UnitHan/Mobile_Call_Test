"""
추출된 WAV 파일을 스테레오로 변환하거나
모노 → 스테레오 (L/R 동일), 스테레오 → 모노 등
"""

import wave
import numpy as np
from pathlib import Path


def convert_mono_to_stereo(mono_file, stereo_file):
    """
    모노 WAV를 스테레오로 변환 (L=R 동일)
    
    Args:
        mono_file: 입력 모노 WAV 파일
        stereo_file: 출력 스테레오 WAV 파일
    """
    print(f"🔊 모노 → 스테레오 변환")
    print(f"   입력: {mono_file}")
    print(f"   출력: {stereo_file}")
    
    with wave.open(mono_file, 'rb') as mono_wav:
        params = mono_wav.getparams()
        
        if params.nchannels != 1:
            print("⚠️ 이미 스테레오 또는 멀티채널입니다!")
            return False
        
        # 오디오 데이터 읽기
        frames = mono_wav.readframes(params.nframes)
        audio_data = np.frombuffer(frames, dtype=np.int16)
        
        # 스테레오로 복제 (L, R, L, R, ...)
        stereo_data = np.empty((audio_data.size * 2,), dtype=np.int16)
        stereo_data[0::2] = audio_data  # Left
        stereo_data[1::2] = audio_data  # Right
    
    # 스테레오 파일로 저장
    with wave.open(stereo_file, 'wb') as stereo_wav:
        stereo_wav.setnchannels(2)
        stereo_wav.setsampwidth(params.sampwidth)
        stereo_wav.setframerate(params.framerate)
        stereo_wav.writeframes(stereo_data.tobytes())
    
    print("✅ 변환 완료!")
    return True


def create_stereo_from_two_mono(left_file, right_file, stereo_file):
    """
    두 개의 모노 파일을 합쳐 스테레오 생성
    
    Args:
        left_file: L 채널 모노 WAV
        right_file: R 채널 모노 WAV
        stereo_file: 출력 스테레오 WAV
    """
    print(f"🔊 두 모노 파일 → 스테레오")
    print(f"   L: {left_file}")
    print(f"   R: {right_file}")
    print(f"   출력: {stereo_file}")
    
    # Left 채널 읽기
    with wave.open(left_file, 'rb') as left_wav:
        left_params = left_wav.getparams()
        left_data = np.frombuffer(
            left_wav.readframes(left_params.nframes),
            dtype=np.int16
        )
    
    # Right 채널 읽기
    with wave.open(right_file, 'rb') as right_wav:
        right_params = right_wav.getparams()
        right_data = np.frombuffer(
            right_wav.readframes(right_params.nframes),
            dtype=np.int16
        )
    
    # 길이 맞추기 (짧은 쪽에 맞춤)
    min_length = min(len(left_data), len(right_data))
    left_data = left_data[:min_length]
    right_data = right_data[:min_length]
    
    # 스테레오로 합치기
    stereo_data = np.empty((min_length * 2,), dtype=np.int16)
    stereo_data[0::2] = left_data
    stereo_data[1::2] = right_data
    
    # 스테레오 파일로 저장
    with wave.open(stereo_file, 'wb') as stereo_wav:
        stereo_wav.setnchannels(2)
        stereo_wav.setsampwidth(left_params.sampwidth)
        stereo_wav.setframerate(left_params.framerate)
        stereo_wav.writeframes(stereo_data.tobytes())
    
    print("✅ 스테레오 생성 완료!")
    return True


def convert_stereo_to_mono(stereo_file, mono_file, channel='mix'):
    """
    스테레오를 모노로 변환
    
    Args:
        stereo_file: 입력 스테레오 WAV
        mono_file: 출력 모노 WAV
        channel: 'left', 'right', 'mix' (평균)
    """
    print(f"🔊 스테레오 → 모노 변환 ({channel})")
    print(f"   입력: {stereo_file}")
    print(f"   출력: {mono_file}")
    
    with wave.open(stereo_file, 'rb') as stereo_wav:
        params = stereo_wav.getparams()
        
        if params.nchannels != 2:
            print("⚠️ 스테레오 파일이 아닙니다!")
            return False
        
        # 오디오 데이터 읽기
        frames = stereo_wav.readframes(params.nframes)
        stereo_data = np.frombuffer(frames, dtype=np.int16)
        
        # L/R 분리
        left = stereo_data[0::2]
        right = stereo_data[1::2]
        
        # 채널 선택
        if channel == 'left':
            mono_data = left
        elif channel == 'right':
            mono_data = right
        else:  # mix
            mono_data = ((left.astype(np.int32) + right.astype(np.int32)) // 2).astype(np.int16)
    
    # 모노 파일로 저장
    with wave.open(mono_file, 'wb') as mono_wav:
        mono_wav.setnchannels(1)
        mono_wav.setsampwidth(params.sampwidth)
        mono_wav.setframerate(params.framerate)
        mono_wav.writeframes(mono_data.tobytes())
    
    print("✅ 변환 완료!")
    return True


def get_audio_info(wav_file):
    """WAV 파일 정보 출력"""
    with wave.open(wav_file, 'rb') as wav:
        params = wav.getparams()
        
        channels = "모노" if params.nchannels == 1 else f"스테레오 ({params.nchannels}채널)"
        duration = params.nframes / params.framerate
        size_mb = Path(wav_file).stat().st_size / (1024 * 1024)
        
        print(f"\n📊 파일 정보: {wav_file}")
        print(f"   채널: {channels}")
        print(f"   샘플레이트: {params.framerate}Hz")
        print(f"   비트뎁스: {params.sampwidth * 8}bit")
        print(f"   길이: {duration:.1f}초")
        print(f"   크기: {size_mb:.2f}MB")


if __name__ == "__main__":
    import sys
    
    print("🔊 WAV 채널 변환기")
    print("="*60)
    
    if len(sys.argv) < 2:
        print("\n사용법:")
        print("  # 정보 확인")
        print("  python wav_converter.py info <file.wav>")
        print("\n  # 모노 → 스테레오")
        print("  python wav_converter.py mono2stereo <input.wav> <output.wav>")
        print("\n  # 스테레오 → 모노")
        print("  python wav_converter.py stereo2mono <input.wav> <output.wav> [left|right|mix]")
        print("\n  # 두 모노 → 스테레오")
        print("  python wav_converter.py merge <left.wav> <right.wav> <output.wav>")
        sys.exit(0)
    
    command = sys.argv[1]
    
    if command == "info":
        if len(sys.argv) < 3:
            print("❌ 파일 경로를 지정하세요!")
            sys.exit(1)
        get_audio_info(sys.argv[2])
    
    elif command == "mono2stereo":
        if len(sys.argv) < 4:
            print("❌ 입력/출력 파일을 지정하세요!")
            sys.exit(1)
        convert_mono_to_stereo(sys.argv[2], sys.argv[3])
    
    elif command == "stereo2mono":
        if len(sys.argv) < 4:
            print("❌ 입력/출력 파일을 지정하세요!")
            sys.exit(1)
        channel = sys.argv[4] if len(sys.argv) > 4 else 'mix'
        convert_stereo_to_mono(sys.argv[2], sys.argv[3], channel)
    
    elif command == "merge":
        if len(sys.argv) < 5:
            print("❌ L/R 파일과 출력 파일을 지정하세요!")
            sys.exit(1)
        create_stereo_from_two_mono(sys.argv[2], sys.argv[3], sys.argv[4])
    
    else:
        print(f"❌ 알 수 없는 명령어: {command}")
