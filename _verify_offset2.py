"""
리포트 오프셋 vs 실제 xcorr 오프셋 비교 검증
"""
import soundfile as sf
import numpy as np
from scipy.signal import resample_poly

BASE = "audio_files/recordings/collected/2026-04-02"
AND_PATH = f"{BASE}/Android_ixiO_TC_01_20260402_094258.wav"
IOS_PATH = f"{BASE}/iOS_ixiO_TC_01_20260402_094258.wav"
REF1_PATH = "reference_audio/dating_SPEAKER_01.wav"
REF0_PATH = "reference_audio/dating_SPEAKER_00.wav"

TARGET_SR = 44100

def load_resamp(path):
    data, sr = sf.read(path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != TARGET_SR:
        g = np.gcd(sr, TARGET_SR)
        data = resample_poly(data, TARGET_SR // g, sr // g).astype(np.float32)
    return data.astype(np.float32)

ref1 = load_resamp(REF1_PATH)
ref0 = load_resamp(REF0_PATH)
and_d = load_resamp(AND_PATH)
ios_d = load_resamp(IOS_PATH)

sr = TARGET_SR

def seg_rms(data, start_s, end_s):
    s, e = int(start_s * sr), int(end_s * sr)
    if s >= len(data): return 0.0
    e = min(e, len(data))
    seg = data[s:e]
    return float(np.sqrt(np.mean(seg**2))) if len(seg) else 0.0

def seg_db(data, start_s, end_s):
    r = seg_rms(data, start_s, end_s)
    return 20 * np.log10(r + 1e-10)

def check(label, data, start_s, end_s, offset_s):
    ts, te = start_s + offset_s, end_s + offset_s
    db = seg_db(data, ts, te)
    verdict = "❌ 음단절" if db < -40 else "✅ 음성있음"
    print(f"  {label:<42} 탐색 {ts:5.1f}~{te:5.1f}s  {db:6.1f}dBFS  {verdict}")

# Android 음단절 탐지 구간: 22.5~31.8s, 35.7~41.7s, 48.7~59.7s
AND_DROPOUT = [(22.5, 31.8), (35.7, 41.7), (48.7, 59.7)]
AND_OK      = [(7.0, 12.4), (71.8, 75.5)]  # 정상 구간 2개

IOS_DROPOUT = [(42.0, 47.4), (64.7, 71.1)]
IOS_OK      = [(0.0, 6.3), (12.8, 22.0)]

REPORT_OFF_AND = +3.020
REPORT_OFF_IOS = -2.320
MY_OFF_AND     = -0.638
MY_OFF_IOS     = -1.427

print("=" * 75)
print(f"  Android — 리포트 오프셋 {REPORT_OFF_AND:+.3f}s 적용")
print("=" * 75)
for a, b in AND_DROPOUT:
    check(f"[DROPOUT] {a}~{b}s", and_d, a, b, REPORT_OFF_AND)
for a, b in AND_OK:
    check(f"[OK?]    {a}~{b}s", and_d, a, b, REPORT_OFF_AND)

print()
print("=" * 75)
print(f"  Android — 내 xcorr 오프셋 {MY_OFF_AND:+.3f}s 적용")
print("=" * 75)
for a, b in AND_DROPOUT:
    check(f"[DROPOUT] {a}~{b}s", and_d, a, b, MY_OFF_AND)
for a, b in AND_OK:
    check(f"[OK?]    {a}~{b}s", and_d, a, b, MY_OFF_AND)

print()
print("=" * 75)
print(f"  iOS — 리포트 오프셋 {REPORT_OFF_IOS:+.3f}s 적용")
print("=" * 75)
for a, b in IOS_DROPOUT:
    check(f"[DROPOUT] {a}~{b}s", ios_d, a, b, REPORT_OFF_IOS)
for a, b in IOS_OK:
    check(f"[OK?]    {a}~{b}s", ios_d, a, b, REPORT_OFF_IOS)

print()
print("=" * 75)
print(f"  iOS — 내 xcorr 오프셋 {MY_OFF_IOS:+.3f}s 적용")
print("=" * 75)
for a, b in IOS_DROPOUT:
    check(f"[DROPOUT] {a}~{b}s", ios_d, a, b, MY_OFF_IOS)
for a, b in IOS_OK:
    check(f"[OK?]    {a}~{b}s", ios_d, a, b, MY_OFF_IOS)

# Android 파일 10초 단위 에너지 프로파일 (리샘플 후)
print()
print("=" * 75)
print(f"  Android 수신 파일 에너지 프로파일 (10초 단위, 총 {len(and_d)/sr:.1f}s)")
print("=" * 75)
for i in range(0, int(len(and_d)/sr)+10, 5):
    db = seg_db(and_d, i, i+5)
    bar = "█" * int(max(0, (db + 60) / 2))
    print(f"  {i:3d}~{i+5:3d}s  {db:6.1f}dBFS  {bar}")
    if i + 5 >= len(and_d)/sr:
        break
