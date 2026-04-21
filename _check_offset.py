import soundfile as sf
import numpy as np

BASE = "audio_files/recordings/collected/2026-04-02"
files = {
    "Android (영희 수신)": f"{BASE}/Android_ixiO_TC_01_20260402_094258.wav",
    "iOS (철수 수신)":     f"{BASE}/iOS_ixiO_TC_01_20260402_094258.wav",
}
ref_files = {
    "ref 영희 (SPEAKER_01)": "reference_audio/dating_SPEAKER_01.wav",
    "ref 철수 (SPEAKER_00)": "reference_audio/dating_SPEAKER_00.wav",
}

all_files = {**files, **ref_files}
print(f"{'파일':<30} {'길이(s)':>10} {'SR':>7}")
print("-" * 55)
for label, path in all_files.items():
    info = sf.info(path)
    print(f"{label:<30} {info.duration:>10.3f} {info.samplerate:>7}")

print()
print("=== 수신 파일 앞 6초 에너지 (500ms 단위) ===")
for label, path in files.items():
    data, sr = sf.read(path)
    seg_len = sr // 2
    print(f"\n[{label}]  총 {len(data)/sr:.2f}s")
    for i in range(12):
        s = i * seg_len
        e = s + seg_len
        if s >= len(data):
            break
        seg = data[s:e]
        rms = float(np.sqrt(np.mean(seg**2)))
        db = 20 * np.log10(rms + 1e-10)
        bar = "█" * int(max(0, (db + 60) / 3))
        print(f"  {i*0.5:.1f}~{(i+1)*0.5:.1f}s  {db:6.1f} dBFS  {bar}")

print()
print("=== cross-correlation 오프셋 검증 (첫 20s) ===")
from numpy.fft import fft, ifft

def xcorr_offset(a, b, sr, max_lag_s=5.0):
    """a 기준으로 b의 오프셋 추정 (양수 = b가 늦음)"""
    max_lag = int(max_lag_s * sr)
    n = len(a) + len(b)
    fa = fft(a, n=n)
    fb = fft(b, n=n)
    corr = np.real(ifft(fa * np.conj(fb)))
    corr = np.concatenate([corr[-max_lag:], corr[:max_lag+1]])
    peak = np.argmax(np.abs(corr)) - max_lag
    return peak / sr

# ref vs recording 오프셋
sr_ref = 44100
ref1, _ = sf.read("reference_audio/dating_SPEAKER_01.wav")
ref0, _ = sf.read("reference_audio/dating_SPEAKER_00.wav")
and_data, sr_a = sf.read(f"{BASE}/Android_ixiO_TC_01_20260402_094258.wav")
ios_data, sr_i = sf.read(f"{BASE}/iOS_ixiO_TC_01_20260402_094258.wav")

# 첫 20초만 사용
n20 = sr_ref * 20
off_and = xcorr_offset(ref1[:n20], and_data[:n20], sr_ref, max_lag_s=5)
off_ios = xcorr_offset(ref0[:n20], ios_data[:n20], sr_ref, max_lag_s=5)
print(f"Android vs ref 영희: 추정 오프셋 {off_and:+.3f}s  (양수=Android가 늦음)")
print(f"iOS     vs ref 철수: 추정 오프셋 {off_ios:+.3f}s  (양수=iOS가 늦음)")
