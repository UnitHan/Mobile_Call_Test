"""
무음 구간 vs 발화 구간 노이즈 스펙트럼 분석
노이즈 종류: 화이트노이즈 / 험(60Hz) / 고주파 히스 판별
"""
import soundfile as sf
import numpy as np
import sys

fname = sys.argv[1] if len(sys.argv) > 1 else 'audio_files/kimbug_1_orig_44100_16bit_mono.wav'
raw, sr = sf.read(fname, dtype='float32')
print(f'파일: {fname}')
print(f'sr={sr}Hz  길이={len(raw)/sr:.1f}s  samples={len(raw)}')
print()

# 음량 기준으로 무음 구간 찾기 (앞 5초에서 가장 조용한 0.5초)
window  = int(sr * 0.5)
segment = raw[:sr * 5]
rms_per_window = [
    np.sqrt(np.mean(segment[i:i+window]**2))
    for i in range(0, len(segment)-window, window//4)
]
quiet_idx = int(np.argmin(rms_per_window)) * (window//4)
quiet     = raw[quiet_idx: quiet_idx + window]

# 발화 구간 (전체 RMS 기준 상위 구간)
rms_all = [
    np.sqrt(np.mean(raw[i:i+window]**2))
    for i in range(0, len(raw)-window, window)
]
loud_idx = int(np.argmax(rms_all)) * window
loud     = raw[loud_idx: loud_idx + window]

print(f'무음 구간: {quiet_idx/sr:.1f}s~{(quiet_idx+window)/sr:.1f}s  RMS={np.sqrt(np.mean(quiet**2)):.6f}')
print(f'발화 구간: {loud_idx/sr:.1f}s~{(loud_idx+window)/sr:.1f}s   RMS={np.sqrt(np.mean(loud**2)):.6f}')
print()

# FFT로 노이즈 주파수 분포 확인
def top_freqs(signal, sr, n=8):
    N    = len(signal)
    fft  = np.abs(np.fft.rfft(signal))
    freq = np.fft.rfftfreq(N, 1/sr)
    # 저주파(< 50Hz) 제외하고 상위 피크
    mask = freq > 50
    top  = np.argsort(fft[mask])[-n:][::-1]
    return [(f'{freq[mask][i]:.0f}Hz', f'{fft[mask][i]:.4f}') for i in top]

print('=== 무음 구간 주요 주파수 (노이즈 성분) ===')
for hz, amp in top_freqs(quiet, sr):
    print(f'  {hz:>8}  amp={amp}')

print()
print('=== 노이즈 종류 판단 ===')
q_fft  = np.abs(np.fft.rfft(quiet))
q_freq = np.fft.rfftfreq(len(quiet), 1/sr)

low_energy  = np.mean(q_fft[(q_freq >= 50)  & (q_freq <= 300)])
mid_energy  = np.mean(q_fft[(q_freq > 300)  & (q_freq <= 3000)])
high_energy = np.mean(q_fft[(q_freq > 3000) & (q_freq <= 8000)])

hum_60  = q_fft[(np.abs(q_freq - 60)  < 5).argmax()] if np.any(np.abs(q_freq - 60)  < 5) else 0
hum_120 = q_fft[(np.abs(q_freq - 120) < 5).argmax()] if np.any(np.abs(q_freq - 120) < 5) else 0

print(f'  저주파(50-300Hz):  {low_energy:.4f}')
print(f'  중주파(300-3kHz): {mid_energy:.4f}')
print(f'  고주파(3k-8kHz):  {high_energy:.4f}')
print(f'  60Hz 험:          {hum_60:.4f}')
print(f'  120Hz 험:         {hum_120:.4f}')
print()

if hum_60 > mid_energy * 2 or hum_120 > mid_energy * 2:
    print('→ 험(Hum) 노이즈: 전원 간섭 (notch 필터로 제거 가능)')
elif high_energy > mid_energy:
    print('→ 고주파 히스(Hiss): 마이크/프리앰프 노이즈 (고주파 LPF로 완화)')
elif low_energy > mid_energy:
    print('→ 저주파 럼블(Rumble): 진동/에어컨 (HPF로 제거 가능)')
else:
    print('→ 화이트/핑크 노이즈: 전 대역 균일 (스펙트럼 게이팅 필요)')
