"""global_offset_sec 디버그 — 왜 +3.020s가 나오는지 추적"""
import sys
sys.path.insert(0, '/Users/qabulls/Documents/sound')
import numpy as np
from audio_lib.io  import load_wav_mono, resample
from audio_lib.dsp import energy_profile

FRAME_MS = 20
BASE = 'audio_files/recordings/collected/2026-04-02'

def global_offset_debug(ref_db, test_db, frame_sec, max_offset_sec=30.0):
    half = min(int(max_offset_sec / frame_sec), len(ref_db)//2, len(test_db)//2)
    cmp  = min(len(ref_db), len(test_db), half * 4)
    r = 10 ** (ref_db[:cmp] / 20.0)
    t = 10 ** (test_db[:cmp] / 20.0)
    r -= r.mean()
    t -= t.mean()
    n_fft = 1
    n_pad = len(r) + len(t) - 1
    while n_fft < n_pad:
        n_fft <<= 1
    corr = np.fft.irfft(np.fft.rfft(r, n_fft) * np.conj(np.fft.rfft(t, n_fft)))
    cands = np.concatenate([corr[:half+1], corr[-half:]])
    best = int(np.argmax(cands))
    offset_frames = best if best <= half else best - len(cands)

    top5 = np.argsort(cands)[-10:][::-1]
    return offset_frames * frame_sec, cands, top5, half, cmp

def xcorr_raw(ref, test, sr, max_lag_s=8.0):
    """raw waveform xcorr (reliable)"""
    from numpy.fft import fft, ifft
    max_lag = int(max_lag_s * sr)
    n = len(ref) + len(test)
    fa = fft(ref.astype(np.float64), n=n)
    fb = fft(test.astype(np.float64), n=n)
    corr = np.real(ifft(fa * np.conj(fb)))
    lags = np.concatenate([corr[-max_lag:], corr[:max_lag+1]])
    peak = int(np.argmax(lags)) - max_lag
    return peak / sr

for platform, ref_path, test_path, report_off in [
    ('Android', 'reference_audio/dating_SPEAKER_01.wav',
     f'{BASE}/Android_ixiO_TC_01_20260402_094258.wav', +3.020),
    ('iOS',     'reference_audio/dating_SPEAKER_00.wav',
     f'{BASE}/iOS_ixiO_TC_01_20260402_094258.wav',    -2.320),
]:
    print('=' * 65)
    print(f'{platform}')
    print('=' * 65)
    ref_a, ref_sr = load_wav_mono(ref_path)
    tst_a, tst_sr = load_wav_mono(test_path)
    print(f'  ref: {ref_sr}Hz {len(ref_a)/ref_sr:.2f}s')
    print(f'  tst: {tst_sr}Hz {len(tst_a)/tst_sr:.2f}s')

    if tst_sr != ref_sr:
        tst_a = resample(tst_a, tst_sr, ref_sr)
        print(f'  리샘플 → {ref_sr}Hz')

    ref_db, fsec = energy_profile(ref_a, ref_sr, FRAME_MS)
    tst_db, _    = energy_profile(tst_a, ref_sr, FRAME_MS)
    print(f'  frames: ref={len(ref_db)}  tst={len(tst_db)}  fsec={fsec:.4f}s')

    off, cands, top10, half, cmp = global_offset_debug(ref_db, tst_db, fsec)
    print(f'  energy_xcorr offset : {off:+.3f}s  (report: {report_off:+.3f}s)')
    print(f'  [Top-10 xcorr peaks]')
    for i, idx in enumerate(top10):
        fr = idx if idx <= half else idx - len(cands)
        print(f'    #{i+1}: cands[{idx:4d}]={cands[idx]:9.4f}  -> {fr*fsec:+.3f}s')

    # raw waveform xcorr
    n20 = ref_sr * 20
    rw = xcorr_raw(ref_a[:n20], tst_a[:n20], ref_sr, max_lag_s=8.0)
    print(f'  raw_waveform xcorr  : {rw:+.3f}s  (first 20s)')
    rw2 = xcorr_raw(ref_a, tst_a, ref_sr, max_lag_s=8.0)
    print(f'  raw_waveform xcorr  : {rw2:+.3f}s  (full signal)')
    print()
