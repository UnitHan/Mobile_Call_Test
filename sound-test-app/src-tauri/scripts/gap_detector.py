"""
gap_detector.py
────────────────────────────────────────────────────────────────────────────
녹음된 WAV에서 음단절 구간을 감지합니다.

【비교 방식 선택 가이드】
  --mode envelope (기본, 권장):
    RMS 에너지 엔벨로프 비교.
    정답지와 녹음본의 "소리가 있냐/없냐" 패턴을 비교합니다.
    스피커 → 공기 → MIC 경로처럼 파형 형태가 달라져도 동작합니다.

  --mode correlation:
    샘플 레벨 cross-correlation 비교.
    전기적 라인연결(직접 디지털 복사본)일 때만 의미 있습니다.
    MIC 녹음에서는 항상 상관계수 ≈ 0 이라 사용 불가.

동작 원리 (envelope 모드):
  1. 두 파일을 20ms 프레임 RMS 에너지(dB)로 변환
  2. 에너지 엔벨로프 cross-correlation으로 시간 오프셋 자동 보정
  3. 정답지 에너지 ≥ 기준dB (소리 있음)이고
     녹음본 에너지 < 기준dB (무음)인 구간 = 음단절

CLI 사용:
    python gap_detector.py --ref ref.wav --test rec.wav
    python gap_detector.py --ref ref.wav --test rec.wav --mode envelope
    python gap_detector.py --ref ref.wav \\
        --test "Android_ixiO_20260313_141522.wav,iOS_ixiO_20260313_141522.wav"
    python gap_detector.py --ref ref.wav --test rec.wav --output result.json
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path
from typing import Optional

import numpy as np

# 루트 폴더(순서: scripts/../../.. = sound/)  를 sys.path 에 추가
# → audio_lib (load_wav_mono, resample, energy_profile) 공유
_ROOT = Path(__file__).parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from audio_lib.consts import FRAME_MS, SILENCE_DB, REF_MIN_DB
from audio_lib.io    import load_wav_mono, resample as _resample_linear
from audio_lib.dsp   import energy_profile as compute_energy_profile


# ── 기본 파라미터 ───────────────────────────────────────
# FRAME_MS, SILENCE_DB, REF_MIN_DB → audio_lib.consts 에서 import
MIN_GAP_MS    = 200     # 최소 음단절 길이 (ms)
MAX_OFFSET_SEC = 10.0   # 오프셋 탐색 최대 범위 (초)


# ─────────────────────────────────────────────────────────────────────────────
# 공유 함수 (audio_lib.io / audio_lib.dsp 에서 import)
# load_wav_mono     → audio_lib.io.load_wav_mono
# _resample_linear  → audio_lib.io.resample (내부적으로 동일한 linear 보인 폴백 포함)
# compute_energy_profile → audio_lib.dsp.energy_profile
# ─────────────────────────────────────────────────────────────────────────────

def find_offset_frames(ref_audio: np.ndarray, test_audio: np.ndarray,
                       sr: int,
                       max_offset_sec: float = MAX_OFFSET_SEC) -> int:
    """Raw waveform FFT cross-correlation으로 test의 시작 오프셋(프레임)을 반환."""
    max_lag = int(max_offset_sec * sr)
    n = len(ref_audio) + len(test_audio)
    fa = np.fft.rfft(ref_audio.astype(np.float64), n=n)
    fb = np.fft.rfft(test_audio.astype(np.float64), n=n)
    corr = np.fft.irfft(fa * np.conj(fb), n=n)
    cands = np.concatenate([corr[-max_lag:], corr[:max_lag + 1]])
    peak = int(np.argmax(cands)) - max_lag
    return peak


# ─────────────────────────────────────────────────────────────────────────────
# 음단절 감지 (엔벨로프 방식)
# ─────────────────────────────────────────────────────────────────────────────

def detect_gaps_envelope(
    ref_db:       np.ndarray,
    test_db:      np.ndarray,
    frame_sec:    float,
    silence_db:   float = SILENCE_DB,
    ref_min_db:   float = REF_MIN_DB,
    min_gap_ms:   float = MIN_GAP_MS,
    max_offset_sec: float = MAX_OFFSET_SEC,
    ref_audio:    'np.ndarray | None' = None,
    test_audio:   'np.ndarray | None' = None,
    sr:           int = 44100,
) -> tuple[list[dict], float]:
    """
    에너지 엔벨로프 비교로 음단절 감지.

    판정 조건 (AND):
      - 정답지 에너지 ≥ ref_min_db   (원음에 소리가 있음)
      - 녹음본 에너지 < silence_db   (녹음에 소리 없음)

    Returns:
        (gaps, offset_sec)
    """
    max_offset_frames = int(max_offset_sec / frame_sec)
    if ref_audio is not None and test_audio is not None:
        offset_samples = find_offset_frames(ref_audio, test_audio, sr, max_offset_sec)
        offset = int(round(offset_samples / sr / frame_sec))
    else:
        # fallback: 에너지 기반 (raw audio 없을 때)
        offset = 0

    if offset >= 0:
        ref_a  = ref_db[offset:]
        test_a = test_db
    else:
        ref_a  = ref_db
        test_a = test_db[-offset:]

    min_len = min(len(ref_a), len(test_a))
    ref_a   = ref_a[:min_len]
    test_a  = test_a[:min_len]

    ref_has_sound = ref_a  >= ref_min_db
    test_silent   = test_a < silence_db
    drop_mask     = ref_has_sound & test_silent

    min_frames = max(1, int(min_gap_ms / 1000 / frame_sec))
    gaps: list[dict] = []
    start: Optional[int] = None

    for i, dropped in enumerate(drop_mask):
        if dropped and start is None:
            start = i
        elif not dropped and start is not None:
            length = i - start
            if length >= min_frames:
                gaps.append({
                    'start_sec':   round(start * frame_sec, 3),
                    'end_sec':     round(i * frame_sec, 3),
                    'duration_ms': round(length * frame_sec * 1000, 1),
                    'ref_db_avg':  round(float(ref_a[start:i].mean()), 1),
                    'test_db_avg': round(float(test_a[start:i].mean()), 1),
                })
            start = None

    if start is not None:
        length = min_len - start
        if length >= min_frames:
            gaps.append({
                'start_sec':   round(start * frame_sec, 3),
                'end_sec':     round(min_len * frame_sec, 3),
                'duration_ms': round(length * frame_sec * 1000, 1),
                'ref_db_avg':  round(float(ref_a[start:].mean()), 1),
                'test_db_avg': round(float(test_a[start:].mean()), 1),
            })

    return gaps, round(offset * frame_sec, 3)


# ─────────────────────────────────────────────────────────────────────────────
# 음단절 감지 (sample-level correlation 방식 — 라인연결 전용)
# ─────────────────────────────────────────────────────────────────────────────

def _rms_db(x: np.ndarray) -> float:
    """1D 배열의 RMS를 dBFS로 반환."""
    rms = float(np.sqrt(np.mean(x.astype(np.float32) ** 2)))
    return 20.0 * np.log10(max(rms, 1e-9))


def _local_corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean();  b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom > 1e-10 else 0.0


def detect_gaps_correlation(
    ref_audio:  np.ndarray,
    test_audio: np.ndarray,
    sr:         int,
    frame_ms:   int   = 20,
    hop_ms:     int   = 10,
    min_corr:   float = 0.4,
    ref_min_db: float = REF_MIN_DB,
    min_gap_ms: float = MIN_GAP_MS,
    max_offset_sec: float = MAX_OFFSET_SEC,
) -> tuple[list[dict], float]:
    """샘플 레벨 cross-correlation 방식 (라인연결 전용)."""
    max_s = int(max_offset_sec * sr)
    cmp   = min(len(ref_audio), len(test_audio), sr * 10)
    r = ref_audio[:cmp] - ref_audio[:cmp].mean()
    t = test_audio[:cmp] - test_audio[:cmp].mean()

    n_pad = len(r) + len(t) - 1
    n_fft = 1
    while n_fft < n_pad:
        n_fft <<= 1
    corr  = np.fft.irfft(np.fft.rfft(r, n_fft) * np.conj(np.fft.rfft(t, n_fft)))
    half  = min(max_s, len(corr) // 2)
    cands = np.concatenate([corr[:half + 1], corr[-half:]])
    best  = int(np.argmax(np.abs(cands)))
    offset_s = best if best <= half else best - len(cands)

    if offset_s >= 0:
        ref_a  = ref_audio[offset_s:]
        test_a = test_audio
    else:
        ref_a  = ref_audio
        test_a = test_audio[-offset_s:]
    min_len = min(len(ref_a), len(test_a))
    ref_a   = ref_a[:min_len];  test_a = test_a[:min_len]

    frame_len = max(1, int(sr * frame_ms / 1000))
    hop_len   = max(1, int(sr * hop_ms  / 1000))
    hop_sec   = hop_ms / 1000.0
    n_frames  = max(0, (min_len - frame_len) // hop_len + 1)

    frame_len_ = max(1, int(sr * FRAME_MS / 1000))
    ref_db_prof = np.array([
        _rms_db(ref_a[i * hop_len: i * hop_len + frame_len_])
        for i in range(n_frames)
    ], dtype=np.float32)

    corr_prof = np.array([
        _local_corr(ref_a[i * hop_len: i * hop_len + frame_len],
                    test_a[i * hop_len: i * hop_len + frame_len])
        for i in range(n_frames)
    ], dtype=np.float32)

    min_frames = max(1, int(min_gap_ms / 1000 / hop_sec))
    gap_mask   = (ref_db_prof >= ref_min_db) & (corr_prof < min_corr)
    gaps: list[dict] = [];  start: Optional[int] = None

    for i, g in enumerate(gap_mask):
        if g and start is None:
            start = i
        elif not g and start is not None:
            if (i - start) >= min_frames:
                gaps.append({
                    'start_sec':   round(start * hop_sec, 3),
                    'end_sec':     round(i * hop_sec, 3),
                    'duration_ms': round((i - start) * hop_sec * 1000, 1),
                    'avg_corr':    round(float(corr_prof[start:i].mean()), 3),
                    'ref_db_avg':  round(float(ref_db_prof[start:i].mean()), 1),
                })
            start = None
    if start is not None and (n_frames - start) >= min_frames:
        gaps.append({
            'start_sec':   round(start * hop_sec, 3),
            'end_sec':     round(n_frames * hop_sec, 3),
            'duration_ms': round((n_frames - start) * hop_sec * 1000, 1),
            'avg_corr':    round(float(corr_prof[start:].mean()), 3),
            'ref_db_avg':  round(float(ref_db_prof[start:].mean()), 1),
        })
    return gaps, round(offset_s / sr, 3)


# ─────────────────────────────────────────────────────────────────────────────
# 메인 분석
# ─────────────────────────────────────────────────────────────────────────────

def analyze(
    ref_path:     str | Path,
    test_path:    str | Path,
    mode:         str   = 'envelope',
    frame_ms:     int   = FRAME_MS,
    silence_db:   float = SILENCE_DB,
    ref_min_db:   float = REF_MIN_DB,
    min_gap_ms:   float = MIN_GAP_MS,
    min_corr:     float = 0.4,
    hop_ms:       int   = 10,
) -> dict:
    ref_audio,  ref_sr  = load_wav_mono(ref_path)
    test_audio, test_sr = load_wav_mono(test_path)

    if test_sr != ref_sr:
        try:
            import scipy.signal as _sig
            test_audio = _sig.resample_poly(test_audio, ref_sr, test_sr).astype(np.float32)
        except ImportError:
            test_audio = _resample_linear(test_audio, test_sr, ref_sr)
        print(f"ℹ️  {Path(test_path).name}: {test_sr}Hz → {ref_sr}Hz 리샘플")

    if mode == 'correlation':
        gaps, offset_sec = detect_gaps_correlation(
            ref_audio, test_audio, ref_sr,
            frame_ms=frame_ms, hop_ms=hop_ms,
            min_corr=min_corr, ref_min_db=ref_min_db, min_gap_ms=min_gap_ms,
        )
    else:
        ref_db,  frame_sec = compute_energy_profile(ref_audio,  ref_sr, frame_ms)
        test_db, _         = compute_energy_profile(test_audio, ref_sr, frame_ms)
        gaps, offset_sec = detect_gaps_envelope(
            ref_db, test_db, frame_sec,
            silence_db=silence_db, ref_min_db=ref_min_db, min_gap_ms=min_gap_ms,
            ref_audio=ref_audio, test_audio=test_audio, sr=ref_sr,
        )
        frame_sec = frame_ms / 1000.0

    ref_db_all, frame_sec = compute_energy_profile(ref_audio, ref_sr, frame_ms)
    duration_sec  = round(len(ref_audio) / ref_sr, 3)
    total_gap_ms  = sum(g['duration_ms'] for g in gaps)
    gap_rate_pct  = round(total_gap_ms / (duration_sec * 10) if duration_sec > 0 else 0.0, 2)

    return {
        'ref':          str(Path(ref_path).name),
        'test':         str(Path(test_path).name),
        'mode':         mode,
        'offset_sec':   offset_sec,
        'duration_sec': duration_sec,
        'gaps':         gaps,
        'total_gap_ms': total_gap_ms,
        'gap_rate_pct': gap_rate_pct,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 리포트 출력
# ─────────────────────────────────────────────────────────────────────────────

def print_report(result: dict) -> None:
    def _ts(sec: float) -> str:
        m = int(sec) // 60;  s = sec - m * 60
        return f"{m:02d}:{s:06.3f}"

    print(f"\n{'─' * 64}")
    print(f"[음단절 분석] {result['test']}  [{result['mode']} 모드]")
    print(f"  정답지     : {result['ref']}")
    print(f"  정렬 오프셋: {result['offset_sec']:+.3f}s")
    print(f"  비교 구간  : {result['duration_sec']:.1f}s")
    print(f"  음단절 비율: {result['gap_rate_pct']:.2f}%  (총 {result['total_gap_ms']:.0f}ms)")
    print(f"{'─' * 64}")

    if not result['gaps']:
        print("  ✅ 음단절 없음")
    else:
        print(f"  ⚠️  음단절 {len(result['gaps'])}건")
        for i, g in enumerate(result['gaps'], 1):
            extra = f"  상관계수={g['avg_corr']:+.3f}" if 'avg_corr' in g else \
                    f"  녹음={g['test_db_avg']:+.1f}dB"
            print(f"  [{i:3d}] {_ts(g['start_sec'])} ~ {_ts(g['end_sec'])}"
                  f"  ({g['duration_ms']:6.0f}ms)"
                  f"  정답지={g['ref_db_avg']:+.1f}dB{extra}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description='음단절 감지 — 정답지 vs 녹음본',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('--ref',  required=True, help='정답지(원음) WAV')
    ap.add_argument('--test', required=True, help='녹음본 WAV (콤마로 복수 지정)')
    ap.add_argument('--output', default=None, help='JSON 저장 경로')
    ap.add_argument('--mode', choices=['envelope', 'correlation'], default='envelope',
                    help='envelope=MIC녹음(기본), correlation=라인연결 전용')
    ap.add_argument('--silence-db', type=float, default=SILENCE_DB,
                    help=f'무음 판정 임계 dB (기본 {SILENCE_DB})')
    ap.add_argument('--ref-min-db', type=float, default=REF_MIN_DB,
                    help=f'정답지 소리 있음 기준 dB (기본 {REF_MIN_DB})')
    ap.add_argument('--min-gap-ms', type=float, default=MIN_GAP_MS,
                    help=f'최소 음단절 길이 ms (기본 {MIN_GAP_MS})')
    ap.add_argument('--min-corr', type=float, default=0.4,
                    help='[correlation 모드] 음단절 판정 임계 상관계수 (기본 0.4)')
    ap.add_argument('--frame-ms', type=int, default=FRAME_MS,
                    help=f'RMS 프레임 크기 ms (기본 {FRAME_MS})')
    return ap


def main() -> None:
    args    = _build_parser().parse_args()
    paths   = [p.strip() for p in args.test.split(',') if p.strip()]
    results: dict[str, dict] = {}

    for tp in paths:
        result = analyze(
            ref_path=args.ref, test_path=tp,
            mode=args.mode, frame_ms=args.frame_ms,
            silence_db=args.silence_db, ref_min_db=args.ref_min_db,
            min_gap_ms=args.min_gap_ms, min_corr=args.min_corr,
        )
        print_report(result)
        results[result['test']] = result

    if args.output:
        out = Path(args.output)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\n💾 JSON 저장: {out}")

    raise SystemExit(1 if any(r['gaps'] for r in results.values()) else 0)


if __name__ == '__main__':
    main()
