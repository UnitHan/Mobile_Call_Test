"""
스테레오 WAV 파일의 L/R 채널 분석
- 각 채널 분리
- 파형 시각화
- 채널 차이 분석
"""

import wave
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path


def analyze_stereo_channels(stereo_file, output_dir='channel_analysis'):
    """
    스테레오 파일의 L/R 채널 분석
    
    Args:
        stereo_file: 스테레오 WAV 파일
        output_dir: 분석 결과 저장 폴더
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    print(f"🔍 스테레오 채널 분석: {stereo_file}\n")
    
    # WAV 파일 읽기
    with wave.open(stereo_file, 'rb') as wav:
        params = wav.getparams()
        
        if params.nchannels != 2:
            print("❌ 스테레오 파일이 아닙니다!")
            return
        
        print(f"📊 기본 정보:")
        print(f"   채널: {params.nchannels}")
        print(f"   샘플레이트: {params.framerate}Hz")
        print(f"   길이: {params.nframes / params.framerate:.1f}초")
        
        # 오디오 데이터 읽기
        frames = wav.readframes(params.nframes)
        audio_data = np.frombuffer(frames, dtype=np.int16)
        
        # L/R 분리
        left = audio_data[0::2]
        right = audio_data[1::2]
    
    # 통계 분석
    print(f"\n📈 채널별 통계:")
    print(f"   L 채널 - 평균: {np.mean(np.abs(left)):.1f}, 최대: {np.max(np.abs(left))}, RMS: {np.sqrt(np.mean(left**2)):.1f}")
    print(f"   R 채널 - 평균: {np.mean(np.abs(right)):.1f}, 최대: {np.max(np.abs(right))}, RMS: {np.sqrt(np.mean(right**2)):.1f}")
    
    # 채널 차이 분석
    diff = np.abs(left.astype(np.float32) - right.astype(np.float32))
    correlation = np.corrcoef(left, right)[0, 1]
    
    print(f"\n🔬 채널 비교:")
    print(f"   상관계수: {correlation:.4f}")
    print(f"   평균 차이: {np.mean(diff):.1f}")
    print(f"   최대 차이: {np.max(diff):.0f}")
    
    if correlation > 0.95:
        print(f"\n⚠️  채널이 거의 동일합니다 (상관계수 {correlation:.2f})")
        print(f"   → L/R이 같은 오디오일 가능성이 높습니다.")
        print(f"   → 화자 분리가 안 되어 있을 수 있습니다.")
    elif correlation > 0.7:
        print(f"\n💡 채널이 유사하지만 차이가 있습니다 (상관계수 {correlation:.2f})")
        print(f"   → 일부 차이가 있을 수 있습니다.")
    else:
        print(f"\n✅ 채널이 독립적입니다 (상관계수 {correlation:.2f})")
        print(f"   → L/R에 다른 오디오가 녹음되어 있습니다!")
    
    # L/R 채널 분리 저장
    left_file = output_path / f"{Path(stereo_file).stem}_LEFT.wav"
    right_file = output_path / f"{Path(stereo_file).stem}_RIGHT.wav"
    
    print(f"\n💾 채널 분리 파일 저장:")
    
    # Left 저장
    with wave.open(str(left_file), 'wb') as left_wav:
        left_wav.setnchannels(1)
        left_wav.setsampwidth(params.sampwidth)
        left_wav.setframerate(params.framerate)
        left_wav.writeframes(left.tobytes())
    print(f"   L: {left_file}")
    
    # Right 저장
    with wave.open(str(right_file), 'wb') as right_wav:
        right_wav.setnchannels(1)
        right_wav.setsampwidth(params.sampwidth)
        right_wav.setframerate(params.framerate)
        right_wav.writeframes(right.tobytes())
    print(f"   R: {right_file}")
    
    # 간단한 파형 시각화 (처음 5초)
    try:
        sample_duration = min(5, params.nframes / params.framerate)
        sample_frames = int(sample_duration * params.framerate)
        
        time = np.linspace(0, sample_duration, sample_frames)
        
        plt.figure(figsize=(12, 6))
        
        # Left 채널
        plt.subplot(2, 1, 1)
        plt.plot(time, left[:sample_frames], linewidth=0.5)
        plt.title('L Channel (Left)', fontsize=12, fontweight='bold')
        plt.ylabel('Amplitude')
        plt.grid(True, alpha=0.3)
        plt.xlim(0, sample_duration)
        
        # Right 채널
        plt.subplot(2, 1, 2)
        plt.plot(time, right[:sample_frames], linewidth=0.5, color='orange')
        plt.title('R Channel (Right)', fontsize=12, fontweight='bold')
        plt.xlabel('Time (seconds)')
        plt.ylabel('Amplitude')
        plt.grid(True, alpha=0.3)
        plt.xlim(0, sample_duration)
        
        plt.tight_layout()
        
        plot_file = output_path / f"{Path(stereo_file).stem}_waveform.png"
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        print(f"\n📊 파형 그래프: {plot_file}")
        
    except Exception as e:
        print(f"\n⚠️  그래프 생성 실패: {e}")
        print(f"   matplotlib 설치: pip install matplotlib")
    
    return {
        'correlation': correlation,
        'left_file': str(left_file),
        'right_file': str(right_file),
        'is_separated': correlation < 0.7
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("사용법: python analyze_stereo.py <stereo.wav>")
        sys.exit(1)
    
    result = analyze_stereo_channels(sys.argv[1])
    
    print(f"\n{'='*60}")
    if result and result['is_separated']:
        print("✅ 결론: 화자가 2채널로 분리되어 있습니다!")
        print("   테스트에 바로 사용 가능합니다.")
    else:
        print("⚠️  결론: 채널이 거의 동일합니다.")
        print("   화자가 분리되어 있지 않을 수 있습니다.")
        print("   직접 L/R 파일을 재생해서 확인해보세요.")
    print(f"{'='*60}")
