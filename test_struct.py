#!/usr/bin/env python3
"""
실제 음원 구조 검증 (DTW 없음, 빠른 실행)
  - Sec 1: 대본 파싱 & onset 탐지 결과
  - Sec 2: assign_chars_to_onsets 버그 수정 여부 (np.interp + end_ms cap)
  - Sec 3: score_chars center 위치 개선 확인
"""
import sys, numpy as np, librosa
from pathlib import Path

_BASE_DIR = Path(__file__).parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

REF_PATH  = str(_BASE_DIR / 'audiomass-output_mono.wav')
RECV_PATH = str(_BASE_DIR / 'recordings' / 'recording_android_20260311_183627_1.wav')

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[94mINFO\033[0m"
results = []

def check(name, cond, detail=""):
    tag = PASS if cond else FAIL
    print(f"  [{tag}] {name}")
    if detail:
        print(f"         {detail}")
    results.append((name, cond))

def info(msg): print(f"  [{INFO}] {msg}")
def section(t): print(f"\n{'='*65}\n  {t}\n{'='*65}")

# ── 음원 로딩 ────────────────────────────────────────────────
section("0. 음원 로딩")
ref_y,  _ = librosa.load(REF_PATH,  sr=16000, mono=True)
recv_y, _ = librosa.load(RECV_PATH, sr=16000, mono=True)
info(f"ref  {len(ref_y)/16000:.1f}s  RMS={float(np.sqrt(np.mean(ref_y**2))):.4f}")
info(f"recv {len(recv_y)/16000:.1f}s  RMS={float(np.sqrt(np.mean(recv_y**2))):.4f}")

# ── 대본 로딩 & 파싱 ─────────────────────────────────────────
from energy_align_layer import (
    parse_script_chars, detect_onsets_in_ref, assign_chars_to_onsets,
    _rms_at, score_chars, group_dropouts,
    ENERGY_SCORE_TH, CHAR_WINDOW_MS, MAX_CHAR_DURATION_MS,
    ONSET_DELTA, ONSET_WAIT_SEC, MIN_DROPOUT_MS, MERGE_GAP_MS,
)
from analyze_hybrid import SCRIPT_REFERENCE

script = SCRIPT_REFERENCE.split("---")[0].strip()
chars  = parse_script_chars(script)
onsets = detect_onsets_in_ref(ref_y)
total_sec = len(ref_y) / 16000


# ════════════════════════════════════════════════════════════════
# SECTION 1: onset 탐지 결과 (DELTA=0.04 적용 여부 확인)
# ════════════════════════════════════════════════════════════════
section("1. onset 탐지 결과")
info(f"ONSET_DELTA={ONSET_DELTA}  ONSET_WAIT_SEC={ONSET_WAIT_SEC}")
info(f"대본 글자 수: {len(chars)}자")
info(f"ref onset 수: {len(onsets)}개  ({len(onsets)/total_sec:.1f}개/초)")
ratio = len(onsets) / max(len(chars), 1)
info(f"onset/글자 비율: {ratio:.2f}")

gaps = np.diff(onsets) * 1000
info(f"onset 간격: min={gaps.min():.0f}ms  mean={gaps.mean():.0f}ms  max={gaps.max():.0f}ms")
info(f"  >500ms 자연 pause: {(gaps > 500).sum()}개  >1000ms 문단 pause: {(gaps > 1000).sum()}개")

check("1a 글자 수 > 0",   len(chars) > 0)
check("1b onset 수 > 100", len(onsets) > 100, f"got {len(onsets)}")
check("1c onset/글자 비율 ≥ 0.9  (DELTA=0.04로 개선)",
      ratio >= 0.9,
      f"ratio={ratio:.2f}  ← 1.0 미만이면 일부 글자는 onset 사이 보간 위치 → 침묵 측정 위험")
check("1d onset 평균 간격 < 300ms (더 조밀한 탐지)", gaps.mean() < 300,
      f"avg={gaps.mean():.0f}ms")


# ════════════════════════════════════════════════════════════════
# SECTION 2: assign_chars_to_onsets — out-of-bounds 수정 확인
# ════════════════════════════════════════════════════════════════
section("2. assign_chars_to_onsets — out-of-bounds 수정 확인")

char_segs = assign_chars_to_onsets(chars, onsets, total_sec)
total_ms  = total_sec * 1000

# 범위 검사
oob_start = [s for s in char_segs if s['start_ms'] > total_ms]
oob_end   = [s for s in char_segs if s['end_ms']   > total_ms + 1000]  # 1초 여유
info(f"글자 수: {len(char_segs)}  (대본: {len(chars)}자)")
info(f"start_ms > total ({total_ms:.0f}ms) 초과: {len(oob_start)}개")
info(f"end_ms   > total+1s 초과: {len(oob_end)}개")

if oob_start:
    info(f"  오류 예시: '{oob_start[0]['char']}' start={oob_start[0]['start_ms']}ms (total={total_ms:.0f}ms)")

check("2a 모든 start_ms ≤ total_ms", len(oob_start) == 0,
      f"{len(oob_start)}개 글자가 음원 길이 초과 (np.interp 수정 미적용)")
check("2b 모든 end_ms ≤ total_ms+1s", len(oob_end) == 0,
      f"{len(oob_end)}개 글자 end_ms 초과")

# end_ms cap 확인
window_sizes = np.array([s['end_ms'] - s['start_ms'] for s in char_segs])
info(f"\nwindow 크기: min={window_sizes.min():.0f}ms  mean={window_sizes.mean():.0f}ms  max={window_sizes.max():.0f}ms")
info(f"  > MAX_CHAR_DURATION_MS({MAX_CHAR_DURATION_MS}ms) 초과: {(window_sizes > MAX_CHAR_DURATION_MS).sum()}개")
check("2c window 최대값 ≤ MAX_CHAR_DURATION_MS",
      window_sizes.max() <= MAX_CHAR_DURATION_MS,
      f"max={window_sizes.max():.0f}ms > cap={MAX_CHAR_DURATION_MS}ms")

# 마지막 글자 검사
last = char_segs[-1]
info(f"\n마지막 글자 '{last['char']}': start={last['start_ms']}ms  end={last['end_ms']}ms")
check("2d 마지막 글자 start_ms 음원 내", last['start_ms'] <= total_ms,
      f"start={last['start_ms']}ms > total={total_ms:.0f}ms")

# 단조증가 확인
starts = np.array([s['start_ms'] for s in char_segs])
check("2e start_ms 단조증가", bool(np.all(np.diff(starts) >= 0)),
      f"비단조 위치: {np.where(np.diff(starts) < 0)[0][:3].tolist()}")


# ════════════════════════════════════════════════════════════════
# SECTION 3: score_chars center 위치 검증
# ════════════════════════════════════════════════════════════════
section("3. score_chars center 위치 검증")

REF_SILENCE_TH = 0.003

# 새 방식: start + CHAR_WINDOW_MS//2
n_silence_new = 0
n_speech_new  = 0
examples_silence = []
for seg in char_segs:
    center_new = seg['start_ms'] + CHAR_WINDOW_MS // 2
    rms = _rms_at(ref_y, center_new, CHAR_WINDOW_MS)
    if rms < REF_SILENCE_TH:
        n_silence_new += 1
        if len(examples_silence) < 5:
            examples_silence.append((seg['char'], seg['start_ms'], center_new))
    else:
        n_speech_new += 1

speech_ratio = n_speech_new / max(len(char_segs), 1) * 100
info(f"수정 center=start+{CHAR_WINDOW_MS//2}ms:")
info(f"  ref 발화 구간 측정: {n_speech_new}자 ({speech_ratio:.1f}%)")
info(f"  ref 침묵 구간 측정: {n_silence_new}자 ({100-speech_ratio:.1f}%)  ← onset 보간 위치")
if examples_silence:
    info(f"  침묵 측정 예시:")
    for ch, st, c in examples_silence:
        info(f"    '{ch}' onset={st}ms  center={c}ms  → ref_rms<0.003 (보간 위치)")
check("3a 발화 구간 측정 비율 ≥ 70%", speech_ratio >= 70.0,
      f"speech_ratio={speech_ratio:.1f}%  (onset 개수 부족 시 낮아짐)")

# onset 수가 충분할 때는 대부분 발화 구간 측정이어야 함
if ratio >= 1.0:
    check("3b onset≥chars 시 발화 구간 ≥ 90%", speech_ratio >= 90.0,
          f"speech_ratio={speech_ratio:.1f}% (onset이 충분한데 침묵 측정이 많으면 이상)")
else:
    info(f"  [SKIP] onset < chars → 일부 보간 위치는 침묵 측정 불가피 (ratio={ratio:.2f})")


# ════════════════════════════════════════════════════════════════
# SECTION 4: 자연 pause 구간 분리 검증 (group_dropouts gap 계산)
# ════════════════════════════════════════════════════════════════
section("4. end_ms cap → group_dropouts 자연 pause 분리 검증")

# 자연 pause 위치 찾기
large_gap_positions = [
    (float(onsets[i]), float(onsets[i+1]))
    for i in range(len(onsets)-1) if onsets[i+1]-onsets[i] > 0.5
]
info(f"자연 pause(>500ms) 위치: {len(large_gap_positions)}개")

# pause 양쪽 글자의 end_ms vs start_ms gap 확인
n_gap_ok = 0
n_gap_fail = 0
fail_examples = []
for (pt_end, pt_start) in large_gap_positions[:20]:  # 앞 20개만 검사
    before = next((s for s in reversed(char_segs) if s['start_ms'] <= pt_end * 1000), None)
    after  = next((s for s in char_segs if s['start_ms'] >= pt_start * 1000), None)
    if before and after:
        gap_ms = after['start_ms'] - before['end_ms']
        if gap_ms > MERGE_GAP_MS:
            n_gap_ok += 1
        else:
            n_gap_fail += 1
            fail_examples.append((before['char'], before['end_ms'],
                                   after['char'], after['start_ms'], gap_ms,
                                   pt_end, pt_start))

info(f"pause 양쪽 gap > MERGE_GAP_MS({MERGE_GAP_MS}ms): {n_gap_ok}개 ✓ (올바르게 분리)")
info(f"pause 양쪽 gap ≤ MERGE_GAP_MS: {n_gap_fail}개 ✗ (잘못 병합될 수 있음)")
if fail_examples:
    info(f"  병합 오류 예시:")
    for b_ch, b_end, a_ch, a_st, g, pe, ps in fail_examples[:3]:
        info(f"    '{b_ch}'(end={b_end}ms) → '{a_ch}'(start={a_st}ms)  gap={g}ms  pause={pe:.1f}~{ps:.1f}s")

check("4a 자연 pause 양쪽 gap > MERGE_GAP_MS (올바른 분리)",
      n_gap_fail == 0,
      f"{n_gap_fail}개의 자연 pause가 MERGE_GAP_MS 이하로 합쳐질 위험")


# ════════════════════════════════════════════════════════════════
# SECTION 5: ref trailing 침묵 진단
# ════════════════════════════════════════════════════════════════
section("5. ref trailing 침묵 진단")

RMS_FRAME = 1600
frame_rms = [float(np.sqrt(np.mean(ref_y[i:i+RMS_FRAME]**2)))
             for i in range(0, len(ref_y)-RMS_FRAME, RMS_FRAME)]
last_active_frame = max(
    (i for i, r in enumerate(frame_rms) if r > 0.005),
    default=0
)
last_active_ms = last_active_frame * 100
info(f"ref 실제 발화 종료: {last_active_ms/1000:.1f}s  (전체 {total_sec:.1f}s)")
info(f"trailing 침묵: {(total_sec - last_active_ms/1000):.1f}초")

# 마지막 N개 글자들이 발화 종료 이전에 위치하는지 확인
last_10 = char_segs[-10:]
after_speech = [s for s in last_10 if s['start_ms'] + CHAR_WINDOW_MS//2 > last_active_ms]
info(f"마지막 10자 중 발화 종료({last_active_ms/1000:.1f}s) 이후에 center가 있는 글자: {len(after_speech)}자")
for s in after_speech:
    center = s['start_ms'] + CHAR_WINDOW_MS // 2
    rms    = _rms_at(ref_y, center, CHAR_WINDOW_MS)
    info(f"  '{s['char']}' center={center}ms  ref_rms={rms:.5f}"
         f"  {'← 침묵 (score=1.0 중립 처리됨)' if rms < REF_SILENCE_TH else '← 발화 OK'}")

check("5a 마지막 글자 start_ms ≤ 발화 종료 시각",
      last['start_ms'] <= last_active_ms + 2000,  # 2초 여유
      f"last start={last['start_ms']}ms  last_active={last_active_ms}ms")


# ════════════════════════════════════════════════════════════════
# 최종 요약
# ════════════════════════════════════════════════════════════════
section("최종 결과 요약")
total   = len(results)
passed  = sum(1 for _, ok in results if ok)
failed  = total - passed

for name, ok in results:
    tag = PASS if ok else FAIL
    print(f"  [{tag}] {name}")

print(f"\n  총 {total}건 — 통과 {passed}건 / 실패 {failed}건")
if failed:
    sys.exit(1)
else:
    print("\n  ✅ 모든 검증 통과")
