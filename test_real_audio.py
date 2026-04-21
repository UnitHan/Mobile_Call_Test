#!/usr/bin/env python3
"""
실제 음원 기반 진단 테스트 — energy_align_layer 설계 검증
목적:
  1. 단어/문장 사이 자연 묵음이 음단절으로 오탐되는지 확인
  2. 대본 마지막 이후 trailing 묵음이 오탐되는지 확인
  3. 실제 score 분포로 임계값(ENERGY_SCORE_TH) 적절성 검증
  4. center_ms 버그(inter-word 침묵 구간 측정) 진단
"""
import sys, os
from pathlib import Path
import numpy as np
import librosa

_BASE_DIR = Path(__file__).parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

REF_PATH  = str(_BASE_DIR / 'audiomass-output_mono.wav')
RECV_PATH = str(_BASE_DIR / 'recordings' / 'recording_android_20260311_183627_1.wav')

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
INFO = "\033[94mINFO\033[0m"
results = []

def check(name, cond, detail=""):
    tag = PASS if cond else FAIL
    print(f"  [{tag}] {name}")
    if detail:
        print(f"         {detail}")
    results.append((name, cond))

def info(msg):
    print(f"  [{INFO}] {msg}")

def section(title):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print('='*65)

# ════════════════════════════════════════════════════════════════
# 음원 로딩
# ════════════════════════════════════════════════════════════════
section("0. 음원 로딩")
print()

ref_y,  _ = librosa.load(REF_PATH,  sr=16000, mono=True)
recv_y, _ = librosa.load(RECV_PATH, sr=16000, mono=True)

info(f"ref  {len(ref_y)/16000:.1f}s  RMS={float(np.sqrt(np.mean(ref_y**2))):.4f}")
info(f"recv {len(recv_y)/16000:.1f}s  RMS={float(np.sqrt(np.mean(recv_y**2))):.4f}")


# ════════════════════════════════════════════════════════════════
# SECTION 1: 대본 파싱 & onset 분포
# ════════════════════════════════════════════════════════════════
section("1. 대본 파싱 & ref onset 탐지")

from energy_align_layer import (
    parse_script_chars, detect_onsets_in_ref, assign_chars_to_onsets,
    dtw_build_mapping, ref_ms_to_recv_ms, score_chars, group_dropouts,
    _rms_at, ENERGY_SCORE_TH, CHAR_WINDOW_MS,
    ONSET_DELTA, ONSET_WAIT_SEC, MIN_DROPOUT_MS, MERGE_GAP_MS,
)
from analyze_hybrid import SCRIPT_REFERENCE

# 음원1 대본 (--- 이전)
script = SCRIPT_REFERENCE.split("---")[0].strip()
chars  = parse_script_chars(script)
info(f"대본 글자 수: {len(chars)}자")
info(f"대본 앞 10자: {''.join(chars[:10])}")
info(f"대본 끝 10자: {''.join(chars[-10:])}")

onsets = detect_onsets_in_ref(ref_y)
total_sec = len(ref_y) / 16000
info(f"onset 수: {len(onsets)}개  (ref {total_sec:.1f}초)")
info(f"onset 밀도: {len(onsets)/total_sec:.1f}개/초")

check("1a 글자 수 > 0",   len(chars) > 0)
check("1b onset 수 > 50", len(onsets) > 50, f"got {len(onsets)}")
check("1c onset/글자 비율 0.7~3.0",
      0.7 <= len(onsets)/max(len(chars),1) <= 3.0,
      f"ratio={len(onsets)/len(chars):.2f}")

# onset 간격 분포
gaps = np.diff(onsets) * 1000  # ms
info(f"onset 간격: min={gaps.min():.0f}ms  mean={gaps.mean():.0f}ms  max={gaps.max():.0f}ms")
info(f"  >500ms 간격 수 (자연 문장 pause 후보): {(gaps > 500).sum()}개")
info(f"  >1000ms 간격 수 (문단 pause 후보):    {(gaps > 1000).sum()}개")

check("1d onset 평균 간격 < 400ms", gaps.mean() < 400,
      f"평균={gaps.mean():.0f}ms (TTS 음절 간격 60~200ms 예상)")


# ════════════════════════════════════════════════════════════════
# SECTION 2: 글자-onset 배정 진단
# ════════════════════════════════════════════════════════════════
section("2. 글자-onset 배정 진단 (inter-word 침묵 구간 탐지)")

char_segs = assign_chars_to_onsets(chars, onsets, total_sec)

# ── 각 글자의 window 크기 분포 ───────────────────────────────
window_sizes = [s['end_ms'] - s['start_ms'] for s in char_segs]
ws_arr = np.array(window_sizes)
info(f"글자 window 크기: min={ws_arr.min():.0f}ms  mean={ws_arr.mean():.0f}ms  max={ws_arr.max():.0f}ms")
large_windows = [(s['char'], s['start_ms'], s['end_ms'], s['end_ms']-s['start_ms'])
                 for s in char_segs if s['end_ms'] - s['start_ms'] > 500]
info(f"window > 500ms 글자 수: {len(large_windows)}개")
if large_windows[:5]:
    info("  (앞 5개 표시):")
    for ch, st, et, w in large_windows[:5]:
        info(f"    '{ch}' {st}ms~{et}ms  (window={w}ms) ← 다음 onset까지 침묵 포함 가능")

# ── center_ms 계산: 현재 방식 vs 수정 방식 ───────────────────
n_center_in_silence = 0
n_center_in_speech  = 0
REF_SILENCE_TH = 0.003
for seg in char_segs:
    # 현재: midpoint
    center_old = (seg['start_ms'] + seg['end_ms']) // 2
    rms_old = _rms_at(ref_y, center_old, CHAR_WINDOW_MS)
    if rms_old < REF_SILENCE_TH:
        n_center_in_silence += 1
    else:
        n_center_in_speech += 1

info(f"\n현재 center_ms=(start+end)//2 방식:")
info(f"  ref에서 침묵 구간에 center가 놓인 글자: {n_center_in_silence}개 / {len(char_segs)}자")
info(f"  ref에서 발화 구간에 center가 놓인 글자: {n_center_in_speech}개 / {len(char_segs)}자")

# 수정 방식: start_ms + CHAR_WINDOW_MS//2
n_fixed_silence = 0
n_fixed_speech  = 0
for seg in char_segs:
    center_new = seg['start_ms'] + CHAR_WINDOW_MS // 2   # onset 직후
    rms_new = _rms_at(ref_y, center_new, CHAR_WINDOW_MS)
    if rms_new < REF_SILENCE_TH:
        n_fixed_silence += 1
    else:
        n_fixed_speech += 1

info(f"\n수정 center_ms=start+{CHAR_WINDOW_MS//2}ms 방식:")
info(f"  ref에서 침묵 구간에 center가 놓인 글자: {n_fixed_silence}개 / {len(char_segs)}자")
info(f"  ref에서 발화 구간에 center가 놓인 글자: {n_fixed_speech}개 / {len(char_segs)}자")

check("2a 수정 방식이 현재 방식보다 침묵 오측정 ≤ 절반",
      n_fixed_silence <= n_center_in_silence * 0.5,
      f"현재={n_center_in_silence}개 → 수정={n_fixed_silence}개")
check("2b 수정 방식에서 발화 구간 측정 글자 > 80%",
      n_fixed_speech / max(len(char_segs), 1) > 0.8,
      f"발화 측정 비율={n_fixed_speech/len(char_segs)*100:.1f}%")

# ── 대본 마지막 글자 trailing 침묵 진단 ─────────────────────
last_seg = char_segs[-1]
last_char_center_old = (last_seg['start_ms'] + last_seg['end_ms']) // 2
last_char_center_new = last_seg['start_ms'] + CHAR_WINDOW_MS // 2
rms_last_old = _rms_at(ref_y, last_char_center_old, CHAR_WINDOW_MS)
rms_last_new = _rms_at(ref_y, last_char_center_new, CHAR_WINDOW_MS)
info(f"\n마지막 글자 '{last_seg['char']}': "
     f"start={last_seg['start_ms']}ms  end={last_seg['end_ms']}ms")
info(f"  현재 center={last_char_center_old}ms → ref_rms={rms_last_old:.5f}"
     f"  {'← 침묵 오측정!' if rms_last_old < REF_SILENCE_TH else '← OK'}")
info(f"  수정 center={last_char_center_new}ms → ref_rms={rms_last_new:.5f}"
     f"  {'← 침묵 오측정!' if rms_last_new < REF_SILENCE_TH else '← OK'}")
check("2c 마지막 글자 수정 방식은 침묵 오측정 아님",
      rms_last_new >= REF_SILENCE_TH,
      f"마지막 글자 ref_rms(onset 기준)={rms_last_new:.5f}")


# ════════════════════════════════════════════════════════════════
# SECTION 3: DTW 실행 & 점수 분포
# ════════════════════════════════════════════════════════════════
section("3. DTW 정렬 & 점수 분포 (약 2~4분 소요)")
print("  ※ DTW 섹션은 별도 스크립트(test_real_dtw.py)로 분리 실행할 것")
print()

import time
t0 = time.time()
wp = dtw_build_mapping(ref_y, recv_y)
elapsed = time.time() - t0
info(f"DTW 완료: {elapsed:.1f}초  경로 {len(wp)}포인트")

# 글자별 점수 계산
scored_old = score_chars(char_segs, ref_y, recv_y, wp)
scores_arr = np.array([s['score'] for s in scored_old])
dropout_old = [s for s in scored_old if s['dropout']]

info(f"\n[현재 방식] 글자별 score 분포:")
info(f"  avg={scores_arr.mean():.3f}  std={scores_arr.std():.3f}")
info(f"  min={scores_arr.min():.3f}  max={scores_arr.max():.3f}")
info(f"  <0.05구간: {(scores_arr<0.05).sum()}자  "
     f"0.05~0.25: {((0.05<=scores_arr)&(scores_arr<0.25)).sum()}자  "
     f">=0.25: {(scores_arr>=0.25).sum()}자")
info(f"  dropout(score<{ENERGY_SCORE_TH}) 글자: {len(dropout_old)}자")

# ── 침묵 구간에 center가 놓인 글자의 score 분포 확인 ─────────
center_silence_scores = []
for seg in scored_old:
    center_old = (seg['start_ms'] + seg['end_ms']) // 2
    rms = _rms_at(ref_y, center_old, CHAR_WINDOW_MS)
    if rms < REF_SILENCE_TH:
        center_silence_scores.append(seg['score'])

if center_silence_scores:
    info(f"\n  침묵 구간에 center가 놓인 글자들의 score:")
    info(f"  평균={np.mean(center_silence_scores):.3f}  "
         f"1.0(중립처리)인 것: {sum(1 for s in center_silence_scores if s==1.0)}개 / {len(center_silence_scores)}개")
    info(f"  dropout로 잘못 판정된 것: {sum(1 for s in center_silence_scores if s<ENERGY_SCORE_TH)}개 "
         f"← 오탐 예비 분석")


# ════════════════════════════════════════════════════════════════
# SECTION 4: 그루핑된 음단절 현황
# ════════════════════════════════════════════════════════════════
section("4. 현재 방식 — 그루핑된 음단절 목록")

drops_old = group_dropouts(scored_old)
info(f"탐지된 음단절: {len(drops_old)}건")
for i, d in enumerate(drops_old):
    conf_mark = "🔴" if d['confidence']=='high' else ("🟡" if d['confidence']=='medium' else "⚪")
    print(f"  [{i+1:2d}] {d['start_ms']/1000:6.1f}s  {d['duration_ms']:5.0f}ms  "
          f"score={d['min_score']:.3f}  [{d['confidence']}] {conf_mark} "
          f"'{d['missing_text'][:30]}'")

# 잠재 오탐 분류 (center가 침묵에 있던 글자가 포함된 dropout)
false_pos_candidates = []
for d in drops_old:
    # dropout에 포함된 글자들이 침묵 구간에 center가 있었다면 의심
    start, end = d['start_ms'], d['end_ms']
    matching_segs = [s for s in scored_old
                     if s['start_ms'] >= start and s['end_ms'] <= end and s['dropout']]
    center_silence_count = 0
    for ms in matching_segs:
        c = (ms['start_ms'] + ms['end_ms']) // 2
        if _rms_at(ref_y, c, CHAR_WINDOW_MS) < REF_SILENCE_TH:
            center_silence_count += 1
    if center_silence_count > 0:
        false_pos_candidates.append((d, center_silence_count))

if false_pos_candidates:
    info(f"\n침묵 center 오측정 영향 가능성이 있는 dropout:")
    for d, cnt in false_pos_candidates:
        info(f"  '{d['missing_text'][:20]}' @ {d['start_ms']/1000:.1f}s "
             f"— {cnt}자 침묵 구간 center 의심")

check("4a dropout 건수가 합리적 범위 (0~20건)",
      0 <= len(drops_old) <= 20,
      f"got {len(drops_old)}건 — 20건 초과면 오탐 의심")
check("4b 침묵 center 오탐 후보 0건", len(false_pos_candidates) == 0,
      f"{len(false_pos_candidates)}건의 dropout이 침묵 구간 center 오측정 의심")


# ════════════════════════════════════════════════════════════════
# SECTION 5: trailing 침묵 오탐 검증
# ════════════════════════════════════════════════════════════════
section("5. trailing 침묵 오탐 검증 (대본 끝 이후)")

# ref 음원에서 실제 발화 종료 시각 추정 (마지막 활성 sample 위치)
RMS_FRAME = 1600  # 100ms frame
frame_rms = [float(np.sqrt(np.mean(ref_y[i:i+RMS_FRAME]**2)))
             for i in range(0, len(ref_y)-RMS_FRAME, RMS_FRAME)]
last_active_frame = max(
    (i for i, r in enumerate(frame_rms) if r > 0.005),
    default=0
)
last_active_ms = last_active_frame * 100
info(f"ref 실제 발화 종료 추정: {last_active_ms/1000:.1f}s "
     f"(전체 {len(ref_y)/16000:.1f}s)")
info(f"  ref trailing 침묵: {(len(ref_y)/16000 - last_active_ms/1000):.1f}초")

# trailing 침묵 내에 dropout이 있는지
trailing_drops = [d for d in drops_old if d['start_ms'] > last_active_ms]
info(f"trailing 침묵 구간 내 dropout 건수: {len(trailing_drops)}건")
for d in trailing_drops:
    info(f"  '{d['missing_text'][:20]}' @ {d['start_ms']/1000:.1f}s ← 오탐!")
check("5a trailing 침묵에서 dropout 없음", len(trailing_drops) == 0,
      f"{len(trailing_drops)}건 발견 — 대본 끝 이후 오탐")

# 대본 마지막 글자가 trailing 발화인지 확인
last_drop_end = max((d['end_ms'] for d in drops_old), default=0)
info(f"\n마지막 dropout end: {last_drop_end/1000:.1f}s / ref 발화 종료: {last_active_ms/1000:.1f}s")
check("5b 마지막 dropout은 실제 발화 종료 이전",
      last_drop_end <= last_active_ms * 1.1 if drops_old else True,
      f"last_drop_end={last_drop_end/1000:.1f}s > last_active={last_active_ms/1000:.1f}s")


# ════════════════════════════════════════════════════════════════
# SECTION 6: 단어 경계 오탐 진단 (자연 pause가 dropout으로 오탐되는 케이스)
# ════════════════════════════════════════════════════════════════
section("6. 자연 문장 pause 오탐 진단")

# gap > 500ms 인 onset 간격 (자연 문장 경계)
large_gap_positions = [(float(onsets[i]), float(onsets[i+1]), float(onsets[i+1]-onsets[i]))
                       for i in range(len(onsets)-1) if onsets[i+1]-onsets[i] > 0.5]
info(f"자연 pause (>500ms) {len(large_gap_positions)}개:")
for st, et, gap in large_gap_positions[:8]:
    # 이 pause 구간에 dropout이 포함됐는지
    pause_start_ms = st * 1000
    pause_end_ms   = et * 1000
    overlap_drops = [
        d for d in drops_old
        if d['start_ms'] < pause_end_ms and d['end_ms'] > pause_start_ms
    ]
    flag = f"← OVERLAP: {[d['missing_text'][:10] for d in overlap_drops]}" if overlap_drops else ""
    info(f"  {st:.1f}s ~ {et:.1f}s  ({gap*1000:.0f}ms pause)  {flag}")

# pause 구간과 겹치는 dropout 수
pause_overlap_count = 0
for st, et, gap in large_gap_positions:
    for d in drops_old:
        if d['start_ms'] < et*1000 and d['end_ms'] > st*1000:
            pause_overlap_count += 1
            break

check("6a 자연 pause 구간과 겹치는 dropout 없음",
      pause_overlap_count == 0,
      f"{pause_overlap_count}건의 dropout이 자연 pause 구간과 겹침 (오탐 의심)")


# ════════════════════════════════════════════════════════════════
# SECTION 7: 실제 탐지된 dropout의 품질 분류
# ════════════════════════════════════════════════════════════════
section("7. 탐지 dropout 품질 분류 (high/medium/low confidence)")

high   = [d for d in drops_old if d['confidence'] == 'high']
medium = [d for d in drops_old if d['confidence'] == 'medium']
low    = [d for d in drops_old if d['confidence'] == 'low']

info(f"high confidence:   {len(high)}건   (score<0.10 또는 500ms 이상)")
info(f"medium confidence: {len(medium)}건  (score 0.10~0.25)")
info(f"low confidence:    {len(low)}건    (score>=0.25인데 grouped)")

for d in high:
    info(f"  [high] {d['start_ms']/1000:.1f}s ~ {d['end_ms']/1000:.1f}s "
         f"({d['duration_ms']}ms) score={d['min_score']} '{d['missing_text'][:25]}'")

check("7a high confidence dropout이 전체의 50% 이상",
      len(high) >= len(drops_old) * 0.5 if drops_old else True,
      f"high={len(high)}/{len(drops_old)}")


# ════════════════════════════════════════════════════════════════
# 최종 요약
# ════════════════════════════════════════════════════════════════
section("최종 결과 요약")

total  = len(results)
passed = sum(1 for _, ok in results if ok)
failed = total - passed

for name, ok in results:
    tag = PASS if ok else FAIL
    print(f"  [{tag}] {name}")

print(f"\n  총 {total}건 — 통과 {passed}건 / 실패 {failed}건")

if failed > 0:
    print(f"\n  수정 필요 항목 {failed}건:")
    for name, ok in results:
        if not ok:
            print(f"    ✗ {name}")
    sys.exit(1)
else:
    print("\n  ✅ 모든 검증 통과")
    sys.exit(0)
