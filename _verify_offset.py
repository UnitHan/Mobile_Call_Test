"""
보고서 오프셋 검증 — Android/iOS 수신 파일 vs 정답지
"""
import soundfile as sf
import numpy as np
from scipy.signal import resample_poly

BASE = "audio_files/recordings/collected/2026-04-02"
AND_PATH = f"{BASE}/Android_ixiO_TC_01_20260402_094258.wav"
IOS_PATH = f"{BASE}/iOS_ixiO_TC_01_20260402_094258.wav"
REF1_PATH = "reference_audio/dating_SPEAKER_01.wav"  # 영희 → Android 수신
REF0_PATH = "reference_audio/dating_SPEAKER_00.wav"  # 철수 → iOS 수신

def load_and_resample(path, target_sr=44100):
    data, sr = sf.read(path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != target_sr:
        g = np.gcd(sr, target_sr)
        data = resample_poly(data, target_sr // g, sr // g).astype(np.float32)
        print(f"  리샘플: {sr}Hz → {target_sr}Hz")
    return data.astype(np.float32), target_sr

def xcorr_offset(ref, test, sr, max_lag_s=8.0):
    """ref 기준 test의 오프셋 (양수 = test가 늦음)"""
    n = len(ref) + len(test)
    max_lag = int(max_lag_s * sr)
    from numpy.fft import fft, ifft
    fa = fft(ref.astype(np.float64), n=n)
    fb = fft(test.astype(np.float64), n=n)
    corr = np.real(ifft(fa * np.conj(fb)))
    lags = np.concatenate([corr[-max_lag:], corr[:max_lag+1]])
    peak_idx = int(np.argmax(lags)) - max_lag
    return peak_idx / sr

TARGET_SR = 44100

print("=" * 60)
print("파일 정보")
print("=" * 60)
for label, path in [("Android", AND_PATH), ("iOS", IOS_PATH),
                    ("ref 영희", REF1_PATH), ("ref 철수", REF0_PATH)]:
    info = sf.info(path)
    print(f"  {label:<12} {info.samplerate}Hz  {info.duration:.3f}s")

print()
print("=" * 60)
print("전체 신호 기반 오프셋 추정 (48kHz→44.1kHz 리샘플 후)")
print("=" * 60)

ref1, sr = load_and_resample(REF1_PATH, TARGET_SR)
ref0, _  = load_and_resample(REF0_PATH, TARGET_SR)
and_data, _ = load_and_resample(AND_PATH, TARGET_SR)
ios_data, _ = load_and_resample(IOS_PATH, TARGET_SR)

off_and = xcorr_offset(ref1, and_data, TARGET_SR, max_lag_s=8.0)
off_ios = xcorr_offset(ref0, ios_data, TARGET_SR, max_lag_s=8.0)
print(f"  Android vs ref 영희: {off_and:+.3f}s  (report: +3.020s)")
print(f"  iOS     vs ref 철수: {off_ios:+.3f}s  (report: -2.320s)")

print()
print("=" * 60)
print("탐지된 음단절 구간 에너지 확인")
print("= Android: 22.5~31.8s / 35.7~41.7s / 48.7~59.7s")
print("= iOS:     42.0~47.4s / 64.7~71.1s")
print("=" * 60)

def check_segment(label, data, sr, ref, start_s, end_s, offset_s):
    """수신 파일에서 정답지 구간에 해당하는 에너지 확인 (오프셋 보정)"""
    # 정답지 구간 에너지
    rs = int(start_s * sr)
    re_ = int(end_s * sr)
    ref_seg = ref[rs:re_]
    ref_rms = float(np.sqrt(np.mean(ref_seg**2))) if len(ref_seg) else 0
    # 수신 파일 오프셋 보정 후 구간
    ts = int((start_s + offset_s) * sr)
    te = int((end_s + offset_s) * sr)
    if ts < 0: ts = 0
    if te > len(data): te = len(data)
    test_seg = data[ts:te]
    test_rms = float(np.sqrt(np.mean(test_seg**2))) if len(test_seg) > 0 else 0
    ratio = test_rms / (ref_rms + 1e-10)
    ref_db = 20*np.log10(ref_rms + 1e-10)
    test_db = 20*np.log10(test_rms + 1e-10)
    verdict = "✅ 음성있음" if ratio > 0.1 else "❌ 음단절"
    print(f"  {label:<35} ref={ref_db:6.1f}dBFS  rcv={test_db:6.1f}dBFS  ratio={ratio:.3f}  {verdict}")

# Android (영희 수신, offset=+3.020)
OFFSET_AND = off_and
check_segment("Android #2: 22.5~31.8s 영희", and_data, TARGET_SR, ref1, 22.5, 31.8, OFFSET_AND)
check_segment("Android #3: 35.7~41.7s 영희", and_data, TARGET_SR, ref1, 35.7, 41.7, OFFSET_AND)
check_segment("Android #4: 48.7~59.7s 영희", and_data, TARGET_SR, ref1, 48.7, 59.7, OFFSET_AND)
check_segment("Android #1: 7.0~12.4s  영희 (OK?)", and_data, TARGET_SR, ref1,  7.0, 12.4, OFFSET_AND)
check_segment("Android #5: 71.8~75.5s 영희 (OK?)", and_data, TARGET_SR, ref1, 71.8, 75.5, OFFSET_AND)

print()
OFFSET_IOS = off_ios
check_segment("iOS #4: 42.0~47.4s 철수",   ios_data, TARGET_SR, ref0, 42.0, 47.4, OFFSET_IOS)
check_segment("iOS #5: 64.7~71.1s 철수",   ios_data, TARGET_SR, ref0, 64.7, 71.1, OFFSET_IOS)
check_segment("iOS #1: 0.0~6.3s   철수 (OK?)", ios_data, TARGET_SR, ref0,  0.0,  6.3, OFFSET_IOS)
check_segment("iOS #2: 12.8~22.0s 철수 (OK?)", ios_data, TARGET_SR, ref0, 12.8, 22.0, OFFSET_IOS)
