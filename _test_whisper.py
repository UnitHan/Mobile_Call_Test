"""Whisper multi-pair test"""
import os, glob, librosa
from whisper_layer import WhisperDetector

RECORDINGS_DIR = "recordings"
ios_files = sorted(glob.glob(os.path.join(RECORDINGS_DIR, "recording_iOS_*.wav")))
pairs = []
for ios in ios_files:
    parts = os.path.basename(ios).split("_")
    date_part = parts[2]
    cands = sorted(glob.glob(os.path.join(RECORDINGS_DIR, f"recording_android_{date_part}_*.wav")))
    if cands:
        used = [p[1] for p in pairs]
        for a in cands:
            if a not in used:
                pairs.append((ios, a))
                break

print(f"pairs: {len(pairs)}")
det = WhisperDetector()
SEP = "=" * 60
for idx, (ios_path, and_path) in enumerate(pairs, 1):
    label = os.path.basename(ios_path)
    print("")
    print(SEP)
    print(" [" + str(idx) + "/" + str(len(pairs)) + "] " + label)
    print(SEP)
    ios_y, _ = librosa.load(ios_path, sr=16000, mono=True)
    and_y, _ = librosa.load(and_path, sr=16000, mono=True)
    print(f"  {len(ios_y)/16000:.1f}s / {len(and_y)/16000:.1f}s")
    res = det.detect(ios_y, and_y)
    if res.error:
        print(f"  ERR: {res.error}")
        continue
    confirmed = [d for d in res.dropouts if d.confirmed]
    print(f"  local : {res.local_text[:120]}")
    print(f"  remote: {res.remote_text[:120]}")
    print(f"  candidates={len(res.dropouts)}  confirmed={len(confirmed)}")
    if confirmed:
        for d in confirmed:
            print(f"    {d.start_ms}~{d.end_ms}ms ({d.duration_ms}ms) ratio={d.energy_ratio:.3f} [{d.confidence}] {repr(d.missing_text[:55])}")
    else:
        print("  -> no confirmed dropout")
        for d in sorted(res.dropouts, key=lambda x: x.energy_ratio)[:5]:
            print(f"    {d.start_ms}ms ratio={d.energy_ratio:.3f} {repr(d.missing_text[:50])}")
print("DONE")