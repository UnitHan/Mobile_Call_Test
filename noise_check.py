#!/usr/bin/env python3
"""Android/iOS 녹음 노이즈 분석"""
import numpy as np, wave, os

def read_wav(path):
    with wave.open(path, 'rb') as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, sr

rec_dir = os.path.expanduser("~/Documents/sound/audio_files/recordings/collected")
and_files = sorted([f for f in os.listdir(rec_dir) if f.startswith("Android_") and f.endswith(".wav")])
ios_files = sorted([f for f in os.listdir(rec_dir) if f.startswith("iOS_") and f.endswith(".wav")])

and_path = os.path.join(rec_dir, and_files[-1])
ios_path = os.path.join(rec_dir, ios_files[-1])

print(f"Android: {and_files[-1]}")
print(f"iOS:     {ios_files[-1]}")

and_data, sr = read_wav(and_path)
ios_data, _ = read_wav(ios_path)

frame = int(0.02 * sr)

for label, data in [("Android", and_data), ("iOS", ios_data)]:
    silence = []
    active = []
    for i in range(0, len(data) - frame, frame):
        rms = np.sqrt(np.mean(data[i:i+frame]**2))
        db = 20 * np.log10(rms + 1e-10)
        if db < -60:
            silence.append(db)
        else:
            active.append(db)
    total = len(silence) + len(active)
    print(f"\n=== {label} 노이즈 분석 ===")
    print(f"  무음(<-60dBFS): {len(silence)} ({len(silence)/total*100:.1f}%)")
    print(f"  활성(>=-60dBFS): {len(active)} ({len(active)/total*100:.1f}%)")
    if silence:
        print(f"  무음 노이즈 평균: {np.mean(silence):.1f} dBFS")
        print(f"  무음 노이즈 최대: {max(silence):.1f} dBFS")
    if active:
        print(f"  활성 평균: {np.mean(active):.1f} dBFS")
    
    # 노이즈 플로어: 하위 10% 분석
    all_db = []
    for i in range(0, len(data) - frame, frame):
        rms = np.sqrt(np.mean(data[i:i+frame]**2))
        all_db.append(20 * np.log10(rms + 1e-10))
    all_db.sort()
    n10 = max(1, len(all_db) // 10)
    print(f"  노이즈 플로어 (하위 10%): {np.mean(all_db[:n10]):.1f} dBFS")
    print(f"  최저 레벨: {all_db[0]:.1f} dBFS")
