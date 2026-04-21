"""
120Hz 험 노이즈 노치 필터 제거
kimbug_1에서 발견된 120Hz 전원 간섭 및 배음(240Hz, 360Hz) 제거
"""
import soundfile as sf
import numpy as np
from scipy import signal

src = 'audio_files/kimbug_1_48k_24bit_mono.wav'
dst = 'audio_files/kimbug_1_48k_24bit_notch.wav'

raw, sr = sf.read(src, dtype='float32')
print(f'입력: {src}  sr={sr}Hz')

filtered = raw.copy()

# 스펙트럼 분석에서 확인된 실제 주파수: 116Hz, 234Hz 및 배음
# Q값을 낮출수록 넓은 대역 제거 (노이즈 흡수력 ↑, 음성 영향 ↑)
notch_freqs = [
    (116, 15),   # 주 험 (120Hz 근접)
    (234, 15),   # 2배음 (240Hz 근접)
    (352, 20),   # 3배음
    (470, 20),   # 4배음
]
for freq, Q in notch_freqs:
    b, a = signal.iirnotch(freq, Q=Q, fs=sr)
    filtered = signal.filtfilt(b, a, filtered).astype('float32')
    print(f'  → {freq}Hz 노치 필터 적용 (Q={Q})')

sf.write(dst, filtered, sr, subtype='PCM_24')

# 효과 측정
orig_quiet_rms    = np.sqrt(np.mean(raw[int(2.7*sr):int(3.2*sr)]**2))
filtered_quiet_rms = np.sqrt(np.mean(filtered[int(2.7*sr):int(3.2*sr)]**2))
reduction_db = 20 * np.log10(filtered_quiet_rms / (orig_quiet_rms + 1e-12))

print()
print(f'무음 구간 RMS: {orig_quiet_rms:.6f} → {filtered_quiet_rms:.6f}')
print(f'노이즈 감소: {reduction_db:.1f}dB')
print(f'저장: {dst}')
print('✅ 완료')

# 스테레오 버전도 생성
dst_stereo = 'audio_files/kimbug_1_48k_24bit_notch_stereo.wav'
stereo = np.stack([filtered, filtered], axis=1)
sf.write(dst_stereo, stereo, sr, subtype='PCM_24')
print(f'저장: {dst_stereo} (스테레오)')
