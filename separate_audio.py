"""
Spleeter를 사용한 음성 분리
스테레오에서 2명의 화자를 분리하거나, 보컬/반주 분리
"""

import os
import sys
from pathlib import Path


def separate_audio_with_spleeter(input_file, output_dir='separated', stems=2):
    """
    Spleeter로 오디오 분리
    
    Args:
        input_file: 입력 WAV 파일
        output_dir: 출력 디렉토리
        stems: 분리할 스템 수 (2, 4, 5)
            - 2stems: vocals / accompaniment
            - 4stems: vocals / drums / bass / other
            - 5stems: vocals / drums / bass / piano / other
    """
    print(f"🎵 Spleeter 음성 분리")
    print(f"   입력: {input_file}")
    print(f"   출력: {output_dir}")
    print(f"   모드: {stems}stems\n")
    
    # Spleeter 명령어
    cmd = f'spleeter separate -p spleeter:{stems}stems -o "{output_dir}" "{input_file}"'
    
    print(f"⚙️ 실행 중... (시간이 걸릴 수 있습니다)\n")
    
    # Python 모듈로 직접 실행
    try:
        from spleeter.separator import Separator
        
        # Separator 생성
        separator = Separator(f'spleeter:{stems}stems')
        
        # 분리 실행
        separator.separate_to_file(input_file, output_dir)
        result = 0
    except Exception as e:
        print(f"❌ 오류: {e}")
        result = 1
    
    if result == 0:
        print(f"\n✅ 분리 완료!")
        
        # 결과 파일 확인
        input_name = Path(input_file).stem
        result_dir = Path(output_dir) / input_name
        
        if result_dir.exists():
            files = list(result_dir.glob("*.wav"))
            print(f"\n📂 생성된 파일 ({len(files)}개):")
            for f in files:
                size_mb = f.stat().st_size / (1024 * 1024)
                print(f"   - {f.name} ({size_mb:.1f}MB)")
            
            return True
    else:
        print(f"\n❌ 분리 실패!")
        return False


def create_stereo_from_separated(vocals_file, accompaniment_file, output_file):
    """
    분리된 vocals와 accompaniment를 스테레오로 합성
    L = vocals, R = accompaniment
    """
    import wave
    import numpy as np
    
    print(f"\n🔊 스테레오 합성")
    print(f"   L 채널: {vocals_file}")
    print(f"   R 채널: {accompaniment_file}")
    print(f"   출력: {output_file}")
    
    # Vocals 읽기
    with wave.open(vocals_file, 'rb') as wav:
        params = wav.getparams()
        vocals_data = np.frombuffer(
            wav.readframes(params.nframes),
            dtype=np.int16
        )
        # 스테레오면 모노로 변환
        if params.nchannels == 2:
            vocals_data = vocals_data[0::2]
    
    # Accompaniment 읽기
    with wave.open(accompaniment_file, 'rb') as wav:
        acc_params = wav.getparams()
        acc_data = np.frombuffer(
            wav.readframes(acc_params.nframes),
            dtype=np.int16
        )
        if acc_params.nchannels == 2:
            acc_data = acc_data[0::2]
    
    # 길이 맞추기
    min_length = min(len(vocals_data), len(acc_data))
    vocals_data = vocals_data[:min_length]
    acc_data = acc_data[:min_length]
    
    # 스테레오로 합치기
    stereo_data = np.empty((min_length * 2,), dtype=np.int16)
    stereo_data[0::2] = vocals_data  # Left
    stereo_data[1::2] = acc_data     # Right
    
    # 저장
    with wave.open(output_file, 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(params.framerate)
        wav.writeframes(stereo_data.tobytes())
    
    print(f"✅ 스테레오 생성 완료: {output_file}")
    return output_file


def main():
    print("🎵 Spleeter 음성 분리기")
    print("="*60)
    
    if len(sys.argv) < 2:
        print("\n사용법:")
        print("  python separate_audio.py <input.wav> [2|4|5]")
        print("\n예제:")
        print("  python separate_audio.py test_audio.wav 2")
        print("\n모드:")
        print("  2stems: vocals / accompaniment (기본)")
        print("  4stems: vocals / drums / bass / other")
        print("  5stems: vocals / drums / bass / piano / other")
        return
    
    input_file = sys.argv[1]
    stems = int(sys.argv[2]) if len(sys.argv) >= 3 else 2
    
    if not os.path.exists(input_file):
        print(f"❌ 파일을 찾을 수 없습니다: {input_file}")
        return
    
    if stems not in [2, 4, 5]:
        print(f"❌ 잘못된 stems 값: {stems} (2, 4, 5 중 선택)")
        return
    
    print()
    
    # 분리 실행
    if separate_audio_with_spleeter(input_file, stems=stems):
        
        # 2stems인 경우 스테레오로 합성
        if stems == 2:
            input_name = Path(input_file).stem
            result_dir = Path('separated') / input_name
            
            vocals_file = result_dir / 'vocals.wav'
            accompaniment_file = result_dir / 'accompaniment.wav'
            
            if vocals_file.exists() and accompaniment_file.exists():
                output_stereo = f"{input_name}_separated_stereo.wav"
                create_stereo_from_separated(
                    str(vocals_file),
                    str(accompaniment_file),
                    output_stereo
                )
                
                print(f"\n💡 테스트에 사용하기:")
                print(f"   test = VoiceCallTest(stereo_audio_file='{output_stereo}')")
                print(f"   - L 채널: Vocals (화자 1)")
                print(f"   - R 채널: Accompaniment (화자 2)")


if __name__ == "__main__":
    main()
