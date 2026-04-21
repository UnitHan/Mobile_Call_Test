#!/usr/bin/env python3
"""
녹음 파일 vs 원본 볼륨 품질 비교 스크립트
═════════════════════════════════════════════════════════════════
TC_01 테스트 후 생성된 녹음 파일의 볼륨이
원본 소스(dating_SPEAKER_00/01.wav)와 동일한지 확인합니다.

판정 기준:
  - RMS 차이 ±3dB 이내 = ✅ PASS
  - RMS 차이 ±6dB 이내 = 🟡 경고 (조정 필요)
  - RMS 차이 >6dB     = 🔴 FAIL (심각한 차이)
  - 클리핑 (Peak > -0.5dB) = ⚠️ 과입력

사용법:
  .venv/bin/python3 compare_recording_quality.py
  .venv/bin/python3 compare_recording_quality.py <녹음파일.wav>
"""

import sys
import os
import wave
import glob
from pathlib import Path

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# 원본 파일 경로
# ─────────────────────────────────────────────────────────────────────────────
SOURCE_FILES = {
    'SPEAKER_00': Path.home() / 'Downloads' / 'dating_SPEAKER_00.wav',
    'SPEAKER_01': Path.home() / 'Downloads' / 'dating_SPEAKER_01.wav',
}

RECORDING_DIR = Path.home() / 'Documents' / 'sound' / 'audio_files' / 'recordings' / 'collected'

# 판정 기준
RMS_TOLERANCE_PASS = 3.0   # dB
RMS_TOLERANCE_WARN = 6.0   # dB
PEAK_CLIP_THRESHOLD = -0.5 # dBFS

# ─────────────────────────────────────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────────────────────────────────────
def analyze_wav(path: str) -> dict:
    """WAV 파일의 볼륨 특성 분석."""
    with wave.open(str(path), 'rb') as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        fr = w.getframerate()
        nf = w.getnframes()
        raw = w.readframes(nf)

    if sw == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    elif sw == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float64) / 2147483648.0
    else:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0

    if nch > 1:
        audio = audio.reshape(-1, nch).mean(axis=1)

    peak = np.max(np.abs(audio))
    rms = np.sqrt(np.mean(audio ** 2))

    # 음성 구간만 RMS (무음 제외) — 더 정확한 비교
    # 임계값: -50dBFS 이상 구간
    threshold = 10 ** (-50 / 20)
    frame_size = int(fr * 0.02)  # 20ms 프레임
    n_frames_anal = len(audio) // frame_size
    voiced_power = []
    for i in range(n_frames_anal):
        frame = audio[i * frame_size:(i + 1) * frame_size]
        frame_rms = np.sqrt(np.mean(frame ** 2))
        if frame_rms > threshold:
            voiced_power.append(frame_rms ** 2)

    voiced_rms = np.sqrt(np.mean(voiced_power)) if voiced_power else rms
    voice_ratio = len(voiced_power) / max(n_frames_anal, 1) * 100

    # 클리핑 검사
    clip_count = int(np.sum(np.abs(audio) > 0.99))

    return {
        'peak': peak,
        'peak_db': 20 * np.log10(peak + 1e-10),
        'rms': rms,
        'rms_db': 20 * np.log10(rms + 1e-10),
        'voiced_rms_db': 20 * np.log10(voiced_rms + 1e-10),
        'voice_ratio': voice_ratio,
        'clip_count': clip_count,
        'duration': nf / fr,
        'channels': nch,
        'sample_rate': fr,
        'bit_depth': sw * 8,
    }

def compare_and_print(rec_path: str, src_info: dict, src_label: str):
    """녹음 파일과 원본 비교 출력."""
    rec_info = analyze_wav(rec_path)
    rec_name = os.path.basename(rec_path)

    rms_diff = rec_info['rms_db'] - src_info['rms_db']
    voiced_diff = rec_info['voiced_rms_db'] - src_info['voiced_rms_db']

    # 판정
    if abs(voiced_diff) <= RMS_TOLERANCE_PASS:
        verdict = '✅ PASS'
    elif abs(voiced_diff) <= RMS_TOLERANCE_WARN:
        verdict = '🟡 경고'
    else:
        verdict = '🔴 FAIL'

    if rec_info['clip_count'] > 100:
        verdict += ' ⚠️클리핑!'

    print(f"\n  📄 녹음: {rec_name}")
    print(f"     비교대상: {src_label}")
    print(f"     ┌───────────────┬────────────┬────────────┬──────────┐")
    print(f"     │               │   원본     │   녹음     │   차이   │")
    print(f"     ├───────────────┼────────────┼────────────┼──────────┤")
    print(f"     │ RMS (전체)    │ {src_info['rms_db']:7.1f} dB │ {rec_info['rms_db']:7.1f} dB │ {rms_diff:+6.1f} dB │")
    print(f"     │ RMS (음성만)  │ {src_info['voiced_rms_db']:7.1f} dB │ {rec_info['voiced_rms_db']:7.1f} dB │ {voiced_diff:+6.1f} dB │")
    print(f"     │ Peak          │ {src_info['peak_db']:7.1f} dB │ {rec_info['peak_db']:7.1f} dB │ {rec_info['peak_db']-src_info['peak_db']:+6.1f} dB │")
    print(f"     │ 음성비율      │ {src_info['voice_ratio']:6.1f} %  │ {rec_info['voice_ratio']:6.1f} %  │          │")
    print(f"     │ 클리핑        │ {0:>7d}    │ {rec_info['clip_count']:>7d}    │          │")
    print(f"     └───────────────┴────────────┴────────────┴──────────┘")
    print(f"     판정: {verdict}  (음성 RMS 차이: {voiced_diff:+.1f} dB, 허용: ±{RMS_TOLERANCE_PASS} dB)")

    # 조정 가이드
    if abs(voiced_diff) > RMS_TOLERANCE_PASS:
        if voiced_diff > 0:
            needed = voiced_diff
            print(f"     💡 조치: 녹음이 {needed:.1f}dB 큼 → iRig 게인↓ 또는 폰 볼륨↓")
        else:
            needed = abs(voiced_diff)
            print(f"     💡 조치: 녹음이 {needed:.1f}dB 작음 → iRig 게인↑ 또는 폰 볼륨↑")

    return verdict, voiced_diff, rec_info

# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("═" * 70)
    print("  🔍 녹음 볼륨 품질 비교 — 원본 vs TC_01 녹음")
    print("═" * 70)

    # 원본 분석
    src_infos = {}
    print("\n  📌 원본 파일:")
    for label, path in SOURCE_FILES.items():
        if path.exists():
            info = analyze_wav(str(path))
            src_infos[label] = info
            print(f"     {label}: RMS={info['rms_db']:.1f}dB (음성={info['voiced_rms_db']:.1f}dB)  Peak={info['peak_db']:.1f}dB  ({info['duration']:.1f}s)")
        else:
            print(f"     ❌ {label}: 파일 없음 ({path})")

    if not src_infos:
        print("\n  ❌ 원본 파일을 찾을 수 없습니다.")
        sys.exit(1)

    # 녹음 파일 결정
    if len(sys.argv) > 1:
        rec_files = sys.argv[1:]
    else:
        # 최근 녹음 파일 자동 탐색 (가장 최근 세션의 iOS/Android 쌍)
        all_recs = sorted(
            RECORDING_DIR.glob('*ixiO*.wav'),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        # normalized 제외, 최근 세션 2개
        recs = [r for r in all_recs if 'normalized' not in r.name][:2]
        rec_files = [str(r) for r in recs]

    if not rec_files:
        print("\n  ❌ 녹음 파일이 없습니다. TC_01 테스트를 먼저 실행하세요.")
        sys.exit(1)

    # 비교
    # 매핑: Android_*.wav → SPEAKER_00 (iPhone으로 재생→ Android iRig 녹음 = iPhone 발화)
    #        iOS_*.wav    → SPEAKER_01 (Android로 재생→ iPhone iRig 녹음 = Android 발화)
    # 실제로는 어느 채널이 어느 speaker인지 설정에 따라 다름
    # → 양쪽 원본 평균과 비교하는 것이 더 안전

    src_avg_rms = np.mean([info['rms_db'] for info in src_infos.values()])
    src_avg_voiced = np.mean([info['voiced_rms_db'] for info in src_infos.values()])
    src_avg_info = {
        'rms_db': src_avg_rms,
        'voiced_rms_db': src_avg_voiced,
        'peak_db': max(info['peak_db'] for info in src_infos.values()),
        'voice_ratio': np.mean([info['voice_ratio'] for info in src_infos.values()]),
    }

    print(f"\n  📌 원본 평균: RMS={src_avg_rms:.1f}dB  음성RMS={src_avg_voiced:.1f}dB")

    results = []
    for rec_path in rec_files:
        if not os.path.exists(rec_path):
            print(f"\n  ❌ 파일 없음: {rec_path}")
            continue

        rec_name = os.path.basename(rec_path)

        # 개별 원본과 비교 (Android 녹음 ↔ SPEAKER_00, iOS 녹음 ↔ SPEAKER_01)
        if 'Android' in rec_name and 'SPEAKER_00' in src_infos:
            src_label = 'dating_SPEAKER_00.wav'
            src_info = src_infos['SPEAKER_00']
        elif 'iOS' in rec_name and 'SPEAKER_01' in src_infos:
            src_label = 'dating_SPEAKER_01.wav'
            src_info = src_infos['SPEAKER_01']
        else:
            src_label = '원본 평균'
            src_info = src_avg_info

        verdict, diff, rec_info = compare_and_print(rec_path, src_info, src_label)
        results.append((rec_name, verdict, diff))

    # 종합 판정
    print(f"\n{'═' * 70}")
    print(f"  📋 종합 판정")
    print(f"{'═' * 70}")

    all_pass = True
    for name, verdict, diff in results:
        status = '✅' if 'PASS' in verdict else ('🟡' if '경고' in verdict else '🔴')
        print(f"  {status} {name}: {verdict} (차이: {diff:+.1f}dB)")
        if 'PASS' not in verdict:
            all_pass = False

    if all_pass:
        print(f"\n  ✅✅ 모든 녹음이 원본 레벨과 일치합니다 (±{RMS_TOLERANCE_PASS}dB 이내)")
        print(f"       녹음 볼륨 품질 확인 완료!")
    else:
        print(f"\n  ⚠️ 일부 녹음의 볼륨이 원본과 차이가 있습니다.")
        print(f"     위의 💡 조치 사항을 참고하여 하드웨어 조정 후 재테스트하세요.")
        print(f"     realtime_level_monitor.py로 실시간 모니터링하며 튜닝할 수 있습니다.")

    print()

if __name__ == '__main__':
    main()
