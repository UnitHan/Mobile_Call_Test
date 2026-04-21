"""수정된 anomaly detector 검증 — 기존 음단절 0건 리포트의 WAV로 테스트."""
from audio_anomaly_detector import detect_dif_only_events

base = "audio_files/recordings/collected/2026-04-01"
ref_base = "reference_audio"

tests = [
    ("Android (음단절0건 리포트)",
     f"{ref_base}/dating_SPEAKER_01.wav",
     f"{base}/Android_ixiO_TC_01_20260401_180444.wav"),
    ("iOS (음단절0건 리포트)",
     f"{ref_base}/dating_SPEAKER_00.wav",
     f"{base}/iOS_ixiO_TC_01_20260401_180444.wav"),
]

for label, ref, dif in tests:
    print(f"\n=== {label} ===")
    print(f"  ref: {ref}")
    print(f"  dif: {dif}")
    events = detect_dif_only_events(ref, dif)
    if events:
        for e in events:
            print(f"  #{e['index']} {e['type']} {e['duration_ms']:.0f}ms "
                  f"({e['start_s']:.3f}s~{e['end_s']:.3f}s) "
                  f"gain={e['gain_db']:.1f}dB corr={e['correlation']:.4f}")
    else:
        print("  이상 없음 ✅")
