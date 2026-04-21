"""
노이즈 캔슬링 + 스테레오 변환 스크립트
stationary spectral gating 방식으로 하드웨어 노이즈(험/화이트노이즈) 제거 후
모노 → 스테레오(L=R) 변환
"""
import soundfile as sf
import noisereduce as nr
import numpy as np

files = [
    ('audio_files/kimbug_1_48k_24bit_mono.wav', 'audio_files/kimbug_1_48k_24bit_nr.wav', 'audio_files/kimbug_1_48k_24bit_nr_stereo.wav'),
    ('audio_files/kimbug_2_48k_24bit_mono.wav', 'audio_files/kimbug_2_48k_24bit_nr.wav', 'audio_files/kimbug_2_48k_24bit_nr_stereo.wav'),
]

for src, dst_mono, dst_stereo in files:
    raw, sr = sf.read(src, dtype='float32')
    print(f'처리 중: {src}  ({sr}Hz, {len(raw)/sr:.1f}s)')

    # stationary=True: 일정한 하드웨어 노이즈(험/화이트노이즈)에 최적
    # prop_decrease: 노이즈 억제 강도 (0.0~1.0, 높을수록 공격적)
    # n_fft: 주파수 해상도 (클수록 세밀)
    reduced = nr.reduce_noise(
        y=raw,
        sr=sr,
        stationary=True,
        prop_decrease=0.9,
        n_fft=2048,
        time_constant_s=2.0,
    )

    # 모노 NR 저장
    sf.write(dst_mono, reduced, sr, subtype='PCM_24')

    orig_rms = np.sqrt(np.mean(raw**2))
    diff_rms = np.sqrt(np.mean((raw - reduced)**2))
    print(f'  → 모노 NR 저장: {dst_mono}')
    print(f'  → 제거된 노이즈 레벨: {20*np.log10(diff_rms/orig_rms+1e-9):.1f}dB 감쇠')

    # 모노 → 스테레오 (L=R 동일)
    stereo = np.stack([reduced, reduced], axis=1)
    sf.write(dst_stereo, stereo, sr, subtype='PCM_24')
    print(f'  → 스테레오 NR 저장: {dst_stereo}  (shape={stereo.shape})')
    print()

print('✅ 완료')
