import soundfile as sf
import numpy as np

files = {
    '원본 44.1k/16bit': 'audio_files/kimbug_1_orig_44100_16bit_mono.wav',
    '변환 48k/24bit':   'audio_files/kimbug_1_48k_24bit_mono.wav',
    'NR 적용':          'audio_files/kimbug_1_48k_24bit_nr.wav',
}

print('=== 파일별 노이즈 플로어 비교 ===')
for label, f in files.items():
    raw, sr = sf.read(f, dtype='float32')
    rms   = np.sqrt(np.mean(raw**2))
    peak  = np.max(np.abs(raw))
    noise = np.percentile(np.abs(raw), 2)
    snr   = 20 * np.log10(rms / (noise + 1e-12))
    print(f'[{label}]')
    print(f'  sr={sr}Hz  peak={peak:.4f}  RMS={rms:.6f}  noise_floor={noise:.8f}  SNR≈{snr:.1f}dB')

print()
print('=== 종 버튼 테스트 톤 (참고값) ===')
sr = 48000
t    = np.linspace(0, 1.0, sr, endpoint=False)
tone = (np.sin(2 * np.pi * 1000 * t) * 0.6).astype('float32')
rms  = np.sqrt(np.mean(tone**2))
snr  = 20 * np.log10(rms / 1e-7)
print(f'  sr=48000Hz  수학적 사인파  SNR≈{snr:.0f}dB (이론상 무한대)')
print()
print('=== 결론 ===')
print('테스트 톤이 깨끗한 이유: 파일이 아닌 수학적으로 생성된 신호이기 때문 (노이즈 0)')
print('WAV 파일 노이즈는 원본 녹음 시 포함된 것으로 리샘플링으로는 제거 불가')
