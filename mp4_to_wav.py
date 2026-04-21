"""
MP4 동영상에서 음성 추출 및 WAV 변환
FFmpeg 또는 MoviePy 사용
"""

import os
import sys
from pathlib import Path


def extract_audio_ffmpeg(video_file, output_wav, sample_rate=44100):
    """
    FFmpeg를 사용한 오디오 추출 (권장)
    
    Args:
        video_file: MP4 비디오 파일 경로
        output_wav: 출력 WAV 파일 경로
        sample_rate: 샘플링 레이트 (기본 44100Hz)
    """
    print(f"🎬 비디오 파일: {video_file}")
    print(f"🎵 출력 파일: {output_wav}")
    
    # FFmpeg 명령어
    cmd = f'ffmpeg -i "{video_file}" -vn -acodec pcm_s16le -ar {sample_rate} -ac 2 "{output_wav}"'
    
    print(f"\n⚙️ 실행 중...\n")
    result = os.system(cmd)
    
    if result == 0:
        # 파일 크기 확인
        size_mb = os.path.getsize(output_wav) / (1024 * 1024)
        print(f"\n✅ 추출 완료!")
        print(f"📦 파일 크기: {size_mb:.2f} MB")
        print(f"📂 저장 위치: {output_wav}")
        return True
    else:
        print(f"\n❌ 추출 실패!")
        print(f"💡 FFmpeg가 설치되어 있는지 확인하세요:")
        print(f"   Windows: https://ffmpeg.org/download.html")
        print(f"   Mac: brew install ffmpeg")
        return False


def extract_audio_moviepy(video_file, output_wav):
    """
    MoviePy를 사용한 오디오 추출 (대안)
    
    Args:
        video_file: MP4 비디오 파일 경로
        output_wav: 출력 WAV 파일 경로
    """
    try:
        from moviepy.editor import VideoFileClip  # type: ignore
        
        print(f"🎬 비디오 파일: {video_file}")
        print(f"🎵 출력 파일: {output_wav}")
        print(f"\n⚙️ 비디오 로딩 중...")
        
        # 비디오 파일 로드
        video = VideoFileClip(video_file)
        
        print(f"⏱️ 길이: {video.duration:.1f}초")
        
        # 오디오 추출
        print(f"🔊 오디오 추출 중...")
        audio = video.audio
        
        if audio is None:
            print("❌ 오디오 트랙이 없습니다!")
            video.close()
            return False
        
        # WAV로 저장
        audio.write_audiofile(output_wav, fps=44100, nbytes=2, codec='pcm_s16le')
        
        # 정리
        video.close()
        
        # 파일 크기 확인
        size_mb = os.path.getsize(output_wav) / (1024 * 1024)
        print(f"\n✅ 추출 완료!")
        print(f"📦 파일 크기: {size_mb:.2f} MB")
        print(f"📂 저장 위치: {output_wav}")
        
        return True
        
    except ImportError:
        print("❌ MoviePy가 설치되어 있지 않습니다!")
        print("💡 설치: pip install moviepy")
        return False
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        return False


def compress_audio_if_needed(wav_file, max_size_mb=50):
    """
    WAV 파일이 너무 크면 압축
    
    Args:
        wav_file: WAV 파일 경로
        max_size_mb: 최대 크기 (MB)
    """
    size_mb = os.path.getsize(wav_file) / (1024 * 1024)
    
    if size_mb > max_size_mb:
        print(f"\n⚠️ 파일이 큽니다 ({size_mb:.1f}MB > {max_size_mb}MB)")
        print(f"🔧 압축 옵션:")
        
        compressed_file = wav_file.replace('.wav', '_compressed.wav')
        
        # 샘플링 레이트 낮추기 (44100 -> 16000)
        cmd = f'ffmpeg -i "{wav_file}" -ar 16000 -ac 1 "{compressed_file}"'
        
        print(f"   1. 샘플링 레이트 낮추기 (16kHz, 모노)")
        print(f"   2. MP3로 변환 (손실 압축)")
        print(f"\n   실행: {cmd}")
        
        result = os.system(cmd)
        if result == 0:
            new_size_mb = os.path.getsize(compressed_file) / (1024 * 1024)
            print(f"✅ 압축 완료: {new_size_mb:.2f}MB")
            return compressed_file
    
    return wav_file


def batch_convert(video_folder, output_folder="audio_files"):
    """
    폴더 내 모든 MP4 파일을 일괄 변환
    
    Args:
        video_folder: 비디오 파일들이 있는 폴더
        output_folder: 출력 폴더
    """
    video_path = Path(video_folder)
    output_path = Path(output_folder)
    output_path.mkdir(exist_ok=True)
    
    # MP4 파일 찾기
    video_files = list(video_path.glob("*.mp4")) + list(video_path.glob("*.MP4"))
    
    if not video_files:
        print(f"❌ {video_folder}에 MP4 파일이 없습니다!")
        return
    
    print(f"📹 찾은 비디오 파일: {len(video_files)}개\n")
    
    success_count = 0
    for i, video_file in enumerate(video_files, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(video_files)}] 변환 중...")
        print(f"{'='*60}")
        
        output_wav = output_path / f"{video_file.stem}.wav"
        
        if extract_audio_ffmpeg(str(video_file), str(output_wav)):
            success_count += 1
    
    print(f"\n{'='*60}")
    print(f"✅ 완료: {success_count}/{len(video_files)} 성공")
    print(f"{'='*60}")


def main():
    print("🎬 MP4 → WAV 음성 추출기")
    print("="*60)
    
    if len(sys.argv) < 2:
        print("\n사용법:")
        print("  python mp4_to_wav.py <video_file.mp4>")
        print("  python mp4_to_wav.py <video_file.mp4> <output.wav>")
        print("  python mp4_to_wav.py --batch <video_folder>")
        print("\n예제:")
        print("  python mp4_to_wav.py recording.mp4")
        print("  python mp4_to_wav.py recording.mp4 test_audio.wav")
        print("  python mp4_to_wav.py --batch ./videos")
        return
    
    # 일괄 변환 모드
    if sys.argv[1] == "--batch":
        if len(sys.argv) < 3:
            print("❌ 폴더 경로를 지정하세요!")
            print("   예: python mp4_to_wav.py --batch ./videos")
            return
        
        batch_convert(sys.argv[2])
        return
    
    # 단일 파일 변환
    video_file = sys.argv[1]
    
    # 파일 존재 확인
    if not os.path.exists(video_file):
        print(f"❌ 파일을 찾을 수 없습니다: {video_file}")
        return
    
    # 출력 파일명 결정
    if len(sys.argv) >= 3:
        output_wav = sys.argv[2]
    else:
        output_wav = Path(video_file).stem + ".wav"
    
    print()
    
    # FFmpeg 우선 시도
    if extract_audio_ffmpeg(video_file, output_wav):
        # 크기 확인 및 압축 제안
        compress_audio_if_needed(output_wav)
    else:
        # FFmpeg 실패 시 MoviePy 시도
        print("\n📝 MoviePy로 재시도...")
        extract_audio_moviepy(video_file, output_wav)


if __name__ == "__main__":
    main()
