#!/usr/bin/env python3
"""
_test_dropout_ground_truth.py
─────────────────────────────────────────────────────────────────────────────
수동 생성 음단절 음원에 대한 감지 정확도 검증

정답지: 음원 묵음 구간 정보_20260401.txt 기반
  - 철수(SPEAKER_00): 5개 대사 × 각 1 묵음
  - 영희(SPEAKER_01): 4개 묵음 + 1개 클린(4번 대사)

검증 방법:
  1) 프레임 방식  — audio_anomaly_detector.detect_dif_only_events()
     ref/test 정렬 → 20ms 프레임 단위 에너지·상관 비교
  2) 특화 방식    — 대본 구간별 내부 묵음 프레임 직접 스캔
     ref의 speech 구간 내에서 test 에너지가 급락하는 구간 탐색

판정 기준: 정답 구간 ±2초 내에 이상 이벤트가 1개 이상 있으면 검출 성공

사용:
    python _test_dropout_ground_truth.py
    python _test_dropout_ground_truth.py --verbose
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import scipy.signal as ss
import soundfile as sf

# ─── 경로 설정 ────────────────────────────────────────────────────────────────

BASE_DIR  = Path(__file__).parent
_REF_DIR  = BASE_DIR / "reference_audio"
REF_DIR   = _REF_DIR

REF_S1  = REF_DIR  / "dating_SPEAKER_00.wav"   # 철수 정답지 (클린)
REF_S2  = REF_DIR  / "dating_SPEAKER_01.wav"   # 영희 정답지 (클린)
TEST_S1 = BASE_DIR / "S1 철수_fixed.wav"        # 철수 음단절 버전
TEST_S2 = BASE_DIR / "S2 영희_fixed.wav"        # 영희 음단절 버전

# ─── 정답지 ── "음원 묵음 구간 정보_20260401.txt" 기반 ──────────────────────
# 각 항목: (화자, 대사번호, 구간_시작s, 구간_끝s, 묵음처리_단어, 예상_묵음_위치)
#   예상 묵음 위치: 'start'=구간 앞, 'mid'=중간, 'end'=구간 끝
GROUND_TRUTH = [
    # ── 철수 (SPEAKER_00) ──
    dict(speaker="철수", idx=1, seg_s=0.0,  seg_e=6.3,  word="여보",    pos="start",
         has_dropout=True,
         note="'여보세요'에서 '여보' 묵음 → 구간 시작부에 묵음 발생 예상"),
    dict(speaker="철수", idx=2, seg_s=12.8, seg_e=22.0, word="거기",    pos="mid",
         has_dropout=True,
         note="'만나자. (거기) 애플하우스' 사이 묵음 → 중간"),
    dict(speaker="철수", idx=3, seg_s=32.2, seg_e=35.1, word="하다",    pos="end",
         has_dropout=True,
         note="'중요(하다)며?' 에서 '하다' 묵음 → 구간 끝에 가까운 위치"),
    dict(speaker="철수", idx=4, seg_s=42.0, seg_e=47.4, word="그럼",    pos="mid",
         has_dropout=True,
         note="'완료. (그럼) 커피' 사이 묵음"),
    dict(speaker="철수", idx=5, seg_s=60.0, seg_e=75.8, word="걷자",    pos="end",
         has_dropout=True,
         note="'같이 걷자!' 에서 '걷자' 묵음 → 구간 끝부 (실제 대사 범위 60.0~75.8s)"),

    # ── 영희 (SPEAKER_01) ──
    dict(speaker="영희", idx=1, seg_s=7.0,  seg_e=12.4, word="철수",   pos="start",
         has_dropout=True,
         note="'응, (철수)야!' 에서 '철수' 묵음 → 구간 초반"),
    dict(speaker="영희", idx=2, seg_s=22.5, seg_e=31.8, word="거기",   pos="mid",
         has_dropout=True,
         note="'넘어가서 태양커피... (거기) 아인슈페너' 중간 묵음"),
    dict(speaker="영희", idx=3, seg_s=35.7, seg_e=41.7, word="응",     pos="start",
         has_dropout=True,
         note="'(응,) 무조건 우유랑' 에서 '응' 묵음 → 구간 시작"),
    dict(speaker="영희", idx=4, seg_s=48.7, seg_e=59.7, word=None,     pos=None,
         has_dropout=False,
         note="음단절 없음 — 정상 구간 (False Positive 검증용)"),
    dict(speaker="영희", idx=5, seg_s=71.8, seg_e=75.5, word="봐",     pos="end",
         has_dropout=True,
         note="'이수역에서 봐.' 에서 '봐' 묵음 → 구간 끝"),
]

# 화자별 정답 묵음 건수
N_S1 = sum(1 for g in GROUND_TRUTH if g["speaker"] == "철수" and g["has_dropout"])
N_S2 = sum(1 for g in GROUND_TRUTH if g["speaker"] == "영희" and g["has_dropout"])

# ─── 유틸리티 ─────────────────────────────────────────────────────────────────

def load_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    samples, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return np.clip(samples, -1.0, 1.0), sr


def resample(data: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return data.copy()
    n_out = int(round(len(data) * dst / src))
    return ss.resample(data, n_out).astype(np.float32)


def align_dif(ref: np.ndarray, dif: np.ndarray, sr: int) -> np.ndarray:
    """Cross-correlation 기반 정렬 (dif를 ref에 맞춤)."""
    max_lag = int(sr * 15)
    r_part  = ref[:min(len(ref), sr * 30)]
    d_part  = dif[:min(len(dif), sr * 30)]
    corr    = ss.correlate(d_part, r_part, mode="full")
    lags    = ss.correlation_lags(len(d_part), len(r_part), mode="full")
    lag     = int(lags[int(np.argmax(corr))])
    lag     = max(-max_lag, min(max_lag, lag))

    n   = len(dif)
    out = np.zeros(n, dtype=np.float32)
    if lag >= 0:
        out[:n - lag] = dif[lag:]
    else:
        s = -lag
        out[s:] = dif[:n - s]
    return out


def energy_rms(data: np.ndarray, sr: int, frame_ms: int = 20, hop_ms: int = 10
               ) -> np.ndarray:
    """프레임별 RMS 에너지 계산."""
    fl = int(sr * frame_ms / 1000)
    hl = int(sr * hop_ms  / 1000)
    n   = len(data)
    nf  = (n - fl) // hl + 1
    rms = np.zeros(nf, dtype=np.float64)
    for i in range(nf):
        s = i * hl
        rms[i] = np.sqrt(np.mean(data[s:s + fl].astype(np.float64) ** 2))
    return rms


# ─── 방법 1: 프레임 방식 ─────────────────────────────────────────────────────

def run_frame_method(ref_path: Path, test_path: Path) -> list[dict]:
    """
    audio_anomaly_detector.detect_dif_only_events 사용.
    반환: [{'start_s', 'end_s', 'type', 'duration_ms', 'gain_db'}]
    """
    sys.path.insert(0, str(BASE_DIR))
    from audio_anomaly_detector import detect_dif_only_events
    events = detect_dif_only_events(str(ref_path), str(test_path))
    # 필드 통일
    return [dict(
        start_s=e["start_s"], end_s=e["end_s"],
        type=e["type"], duration_ms=e["duration_ms"],
        gain_db=e.get("gain_db", 0.0),
    ) for e in events]


# ─── 방법 2: 특화 방식 (Segment-Level Internal Silence Scan) ─────────────────

def run_specialized_method(
    ref_path: Path, test_path: Path,
    frame_ms: int = 20, hop_ms: int = 10,
    speech_rms_thr: float = 0.01,   # ref에서 '발화 중'으로 보는 최소 RMS
    dropout_ratio_thr: float = 0.12, # ref_rms 대비 test_rms 비율 임계 (이하면 음단절)
    min_dropout_ms: int = 80,        # 음단절로 보는 최소 지속 길이 (ms)
    search_margin_s: float = 2.0,    # 구간 양쪽 확장 탐색 (s)
) -> list[dict]:
    """
    정답지(ref) 발화 구간 안에서 test 에너지가 급락하는 위치를 직접 스캔.
    전체 파일 정렬 후, 각 발화 구간 내 프레임별로 ref RMS vs test RMS 비교.

    반환: [{'start_s', 'end_s', 'type', 'duration_ms', 'ratio_med'}]
    """
    ref,  sr_r = load_wav_mono(ref_path)
    test, sr_t = load_wav_mono(test_path)
    if sr_t != sr_r:
        test = resample(test, sr_t, sr_r)
    sr = sr_r

    # 전역 정렬
    test_aligned = align_dif(ref, test, sr)

    # 프레임 에너지
    ref_rms  = energy_rms(ref,          sr, frame_ms, hop_ms)
    test_rms = energy_rms(test_aligned, sr, frame_ms, hop_ms)

    hop_sec = hop_ms / 1000.0
    nf      = min(len(ref_rms), len(test_rms))
    ref_rms  = ref_rms[:nf]
    test_rms = test_rms[:nf]

    min_f = max(1, int(min_dropout_ms / hop_ms))
    events: list[dict] = []

    # 각 발화 구간별 스캔 (정답지 발화 시간대 기준)
    for gt in GROUND_TRUTH:
        seg_s = max(0.0, gt["seg_s"] - search_margin_s)
        seg_e = gt["seg_e"] + search_margin_s

        fi_s = int(seg_s / hop_sec)
        fi_e = min(nf, int(seg_e / hop_sec))
        if fi_s >= fi_e:
            continue

        r_seg = ref_rms[fi_s:fi_e]
        t_seg = test_rms[fi_s:fi_e]

        # 정규화 비율 (ref 발화 구간에서 test가 얼마나 살아있는지)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(r_seg > speech_rms_thr, t_seg / r_seg, 1.0)

        # 발화 강도 기준
        speech_mask = r_seg > speech_rms_thr

        # 음단절 후보 프레임: 발화 중이고 test 에너지가 급락
        dropout_mask = speech_mask & (ratio < dropout_ratio_thr)

        # 연속 구간 병합
        in_seg = False
        d_start = 0
        for i in range(len(dropout_mask) + 1):
            active = i < len(dropout_mask) and dropout_mask[i]
            if active and not in_seg:
                in_seg, d_start = True, i
            elif not active and in_seg:
                in_seg = False
                dur_f = i - d_start
                if dur_f >= min_f:
                    abs_start = (fi_s + d_start) * hop_sec
                    abs_end   = (fi_s + i)       * hop_sec
                    events.append(dict(
                        start_s=round(abs_start, 3),
                        end_s=round(abs_end, 3),
                        type="특화_묵음",
                        duration_ms=round((abs_end - abs_start) * 1000, 1),
                        ratio_med=round(float(np.median(ratio[d_start:i])), 4),
                        seg_label=f"{gt['speaker']}#{gt['idx']}",
                    ))

    # 중복 제거 (겹치는 구간 병합)
    events.sort(key=lambda e: e["start_s"])
    merged: list[dict] = []
    for ev in events:
        if merged and ev["start_s"] < merged[-1]["end_s"] + 0.1:
            prev = merged[-1]
            prev["end_s"]      = max(prev["end_s"], ev["end_s"])
            prev["duration_ms"]= round((prev["end_s"] - prev["start_s"]) * 1000, 1)
        else:
            merged.append(ev)
    return merged


# ─── 정답 매칭 평가 ──────────────────────────────────────────────────────────

def evaluate(events: list[dict], gt_list: list[dict],
             window_s: float = 2.0) -> dict:
    """
    events에서 각 정답 구간을 검출했는지 평가.
    정답 구간 ±window_s 내에 이벤트가 하나 이상 있으면 검출 성공.

    반환:
      per_gt    : 각 GT 항목별 검출 여부
      tp, fn    : 총 TP(묵음 구간 검출 성공), FN(미검출)
      fp        : 정상 구간(has_dropout=False)에서 잘못 검출된 수
      recall    : tp / (tp + fn)
      precision : tp / (tp + fp + detected_in_clean)
    """
    per_gt = []
    tp = fn = fp_clean = 0

    for gt in gt_list:
        lo = gt["seg_s"] - window_s
        hi = gt["seg_e"] + window_s
        hits = [e for e in events if e["end_s"] >= lo and e["start_s"] <= hi]
        detected = len(hits) > 0

        if gt["has_dropout"]:
            if detected:
                tp += 1
            else:
                fn += 1
        else:
            if detected:
                fp_clean += 1

        per_gt.append(dict(
            speaker=gt["speaker"], idx=gt["idx"],
            has_dropout=gt["has_dropout"], detected=detected,
            word=gt.get("word", "—"),
            seg=f"{gt['seg_s']:.1f}–{gt['seg_e']:.1f}s",
            hits=[f"{e['start_s']:.2f}s-{e['end_s']:.2f}s" for e in hits[:3]],
        ))

    total_dropout = sum(1 for g in gt_list if g["has_dropout"])
    recall    = tp / total_dropout if total_dropout else 0.0
    precision = tp / (tp + fp_clean) if (tp + fp_clean) > 0 else 1.0

    return dict(
        per_gt=per_gt, tp=tp, fn=fn, fp_clean=fp_clean,
        recall=recall, precision=precision,
    )


# ─── 출력 ────────────────────────────────────────────────────────────────────

def print_events(events: list[dict], verbose: bool = False) -> None:
    if not events:
        print("   (검출된 이벤트 없음)")
        return
    for i, e in enumerate(events, 1):
        base = f"   [{i:02d}] {e['start_s']:.2f}s–{e['end_s']:.2f}s  {e['duration_ms']:.0f}ms  [{e['type']}]"
        if verbose:
            extra = ""
            if "gain_db" in e:
                extra += f"  gain={e['gain_db']:.1f}dB"
            if "ratio_med" in e:
                extra += f"  ratio={e['ratio_med']:.4f}"
            if "seg_label" in e:
                extra += f"  ← {e['seg_label']}"
            print(base + extra)
        else:
            print(base)


def print_eval(result: dict, method_name: str) -> None:
    print(f"\n── {method_name} 평가 결과 ─────────────────────────────────────")
    print(f"   TP={result['tp']}  FN={result['fn']}  FP(정상구간)={result['fp_clean']}")
    print(f"   Recall   : {result['recall']:.1%}  ({result['tp']}/{result['tp']+result['fn']})")
    print(f"   Precision: {result['precision']:.1%}")
    print()
    print(f"   {'화자':^6} {'#':^3} {'묵음단어':^8} {'구간':^16} {'검출':^6}  히트")
    print(f"   {'-'*6} {'-'*3} {'-'*8} {'-'*16} {'-'*6}  {'-'*30}")
    for g in result["per_gt"]:
        icon = ("✅" if g["detected"] else "❌") if g["has_dropout"] else ("⚠️ FP" if g["detected"] else "✔ FP없음")
        word = g.get("word") or "—"
        hits = ", ".join(g["hits"]) if g["hits"] else "-"
        print(f"   {g['speaker']:^6} {g['idx']:^3} {word:^8} {g['seg']:^16} {icon:^6}  {hits}")


# ─── 메인 ────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="음단절 감지 정확도 검증")
    ap.add_argument("--verbose", "-v", action="store_true", help="상세 이벤트 출력")
    ap.add_argument("--speaker", choices=["s1", "s2", "both"], default="both",
                    help="검증할 화자 (default: both)")
    args = ap.parse_args()

    # 파일 존재 확인
    for p in [REF_S1, REF_S2, TEST_S1, TEST_S2]:
        if not p.exists():
            print(f"❌ 파일 없음: {p}")
            sys.exit(1)

    print("=" * 70)
    print("  음단절 감지 정확도 검증")
    print(f"  ref_s1 : {REF_S1.name}")
    print(f"  ref_s2 : {REF_S2.name}")
    print(f"  test_s1: {TEST_S1.name}")
    print(f"  test_s2: {TEST_S2.name}")
    print("=" * 70)

    tasks = []
    if args.speaker in ("s1", "both"):
        tasks.append(("철수 (SPEAKER_00)", REF_S1, TEST_S1,
                      [g for g in GROUND_TRUTH if g["speaker"] == "철수"]))
    if args.speaker in ("s2", "both"):
        tasks.append(("영희 (SPEAKER_01)", REF_S2, TEST_S2,
                      [g for g in GROUND_TRUTH if g["speaker"] == "영희"]))

    summary = []

    for label, ref_p, test_p, gt_sub in tasks:
        print(f"\n{'─'*70}")
        print(f"  화자: {label}")
        print(f"  정답 음단절 {sum(1 for g in gt_sub if g['has_dropout'])}개 / 정상 구간 {sum(1 for g in gt_sub if not g['has_dropout'])}개")

        # ── 방법 1: 프레임 방식 ──
        print(f"\n[방법 1] 프레임 방식 (audio_anomaly_detector)")
        try:
            ev1 = run_frame_method(ref_p, test_p)
            print(f"   총 {len(ev1)}개 이벤트 검출")
            print_events(ev1, verbose=args.verbose)
            eval1 = evaluate(ev1, gt_sub)
            print_eval(eval1, "방법1 (프레임)")
        except Exception as e:
            print(f"   ⚠️ 실행 오류: {e}")
            eval1 = None

        # ── 방법 2: 특화 방식 ──
        print(f"\n[방법 2] 특화 방식 (구간 내부 에너지 스캔)")
        try:
            ev2 = run_specialized_method(ref_p, test_p)
            print(f"   총 {len(ev2)}개 이벤트 검출")
            print_events(ev2, verbose=args.verbose)
            eval2 = evaluate(ev2, gt_sub)
            print_eval(eval2, "방법2 (특화)")
        except Exception as e:
            print(f"   ⚠️ 실행 오류: {e}")
            eval2 = None

        summary.append((label, eval1, eval2))

    # ── 종합 비교 ──
    print(f"\n{'='*70}")
    print("  종합 비교")
    print(f"  {'화자':<20} {'방법1 Recall':>14} {'방법1 Pre':>12} {'방법2 Recall':>14} {'방법2 Pre':>12}")
    print(f"  {'-'*20} {'-'*14} {'-'*12} {'-'*14} {'-'*12}")
    for label, e1, e2 in summary:
        r1 = f"{e1['recall']:.1%}  ({e1['tp']}/{e1['tp']+e1['fn']})" if e1 else "—"
        p1 = f"{e1['precision']:.1%}" if e1 else "—"
        r2 = f"{e2['recall']:.1%}  ({e2['tp']}/{e2['tp']+e2['fn']})" if e2 else "—"
        p2 = f"{e2['precision']:.1%}" if e2 else "—"
        print(f"  {label:<20} {r1:>14} {p1:>12} {r2:>14} {p2:>12}")
    print(f"{'='*70}")
    print("\n💡 유의사항:")
    print("  - 검출 창 ±2s 내 이벤트 유무로 판정 (단어 위치 오프셋 허용)")
    print("  - 방법2는 ref 정렬 기반이므로 정렬 오차 클 경우 결과가 부정확할 수 있음")
    print("  - 결과 해석 후 임계값 조정 필요 여부를 검토하세요")


if __name__ == "__main__":
    main()
