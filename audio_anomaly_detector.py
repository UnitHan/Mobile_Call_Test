"""
오디오 이상 구간 검출 스크립트 (Audio Anomaly Detector)
======================================================

ref(원본 전송음)와 dif(수신 녹음본) WAV 파일을 비교하여
사람이 느끼는 수준의 묵음(digital_zero)과 음깨짐(gain_drop)을 검출합니다.

이 파일 하나만으로 이상 검출 기능을 사용할 수 있습니다.
GUI, 스펙트럼 분석, 내보내기 등 부가 기능은 포함하지 않습니다.

■ 필수 라이브러리 (pip install)
  - numpy
  - scipy
  - soundfile

■ 핵심 함수
  detect_dif_only_events(ref_path, dif_path, **kwargs) -> list[dict]

■ 사용 예시
  from audio_anomaly_detector import detect_dif_only_events

  events = detect_dif_only_events("ref.wav", "dif.wav")
  for e in events:
      print(e)
  # 출력 예시:
  # {'index': 1, 'type': '묵음', 'duration_ms': 90.0, 'start_s': 1.020, 'end_s': 1.110}
  # {'index': 1, 'type': '깨짐', 'duration_ms': 90.0, 'start_s': 2.730, 'end_s': 2.820}

  이상이 없으면 빈 리스트를 반환합니다.
  events = detect_dif_only_events("ref.wav", "normal_dif.wav")
  # []

■ 파라미터 튜닝 예시
  events = detect_dif_only_events("ref.wav", "dif.wav",
      speech_strong_rms=0.05,     # 음성 판정 RMS 임계값 (기본 0.03)
      zero_peak_threshold=0.001,  # 묵음 판정 peak 임계값 (기본 0.0005)
      min_anomaly_ms=80,          # 최소 이상 지속 시간 (기본 50ms)
  )

■ 반환값 dict 필드 설명
  - index       : 이벤트 번호 (1부터 시작)
  - type        : "묵음" 또는 "깨짐"
  - duration_ms : 이상 구간 지속 시간 (ms)
  - start_s     : 이상 구간 시작 시간 (초)
  - end_s       : 이상 구간 종료 시간 (초)
  - gain_db     : 구간 평균 gain (dB). 묵음은 -100.0
  - correlation : 구간 평균 Pearson correlation

■ 조정 가능한 파라미터 (kwargs)
  - speech_strong_rms      (float, 0.03)  : ref 확실한 음성 판정 RMS 임계값
  - zero_peak_threshold    (float, 0.0005): dif 디지털 제로 판정 peak 임계값
  - gain_drop_ratio        (float, 0.4)   : 깨짐 A 주변 대비 ratio 임계값
  - gain_drop_ratio_strict (float, 0.30)  : 깨짐 B ratio 임계값 (더 엄격)
  - gain_drop_min_corr     (float, 0.3)   : 깨짐 A 최소 correlation
  - prior_activity_threshold (float, 0.01): 직전 dif 활성 판정 peak 임계값
  - min_anomaly_ms         (int, 50)      : 묵음 최소 지속 시간 (ms)
  - min_anomaly_a_ms       (int, 80)      : 깨짐 A 최소 지속 시간 (ms)
  - min_anomaly_b_ms       (int, 120)     : 깨짐 B 최소 지속 시간 (ms)
  - anomaly_gap_frames     (int, 3)       : 깨짐 B gap 허용 프레임 수

■ 알고리즘 요약
  1. WAV 로드 → float32 정규화 → 리샘플링(dif를 ref SR에 맞춤)
  2. Cross-correlation 기반 지연 추정 → DTW 세부 보정 → 정렬
  3. 프레임별 RMS/peak/correlation 계산 (20ms 프레임, 10ms 홉)
  4. 주변 1초 구간의 ratio 중앙값 대비 급격한 하락 검출
     - 묵음: dif_peak < zero_peak_threshold + ref 음성 구간, 최소 min_anomaly_ms
     - 깨짐 A: ratio < context_med * gain_drop_ratio + corr > gain_drop_min_corr, 최소 min_anomaly_a_ms
     - 깨짐 B: ratio < context_med * gain_drop_ratio_strict + min_anomaly_b_ms 이상
  5. 3단계 오탐 필터 (묵음/깨짐 공통):
     - 직전 dif 활성도 검사 (200ms + 50ms 이중 확인)
     - 직전 ref 음성 존재 검사 (직전 200ms에서 음성 프레임 비율)
     - 직전 안정 ratio 검사 (직전 150ms에서 ratio > 0.5인 프레임 수)
  6. 묵음 직후 200ms 이내의 distortion은 복구 과정으로 제외
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import scipy.signal as signal
import soundfile as sf


# ─── 데이터 모델 ───────────────────────────────────────────────────────────────

@dataclass
class _AudioData:
    samples: np.ndarray
    sample_rate: int
    n_channels: int

@dataclass
class _AnomalySegment:
    start_ms: float
    end_ms: float
    duration_ms: float
    anomaly_type: str       # "digital_zero" | "gain_drop"
    mean_gain_db: float
    mean_correlation: float


# ─── WAV I/O ──────────────────────────────────────────────────────────────────

def _load_wav(path: str) -> _AudioData:
    """WAV 파일을 float32 모노로 로드."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    try:
        samples, sr = sf.read(path, dtype="float32", always_2d=False)
    except Exception as e:
        raise ValueError(f"유효하지 않은 WAV 형식: {path} ({e})")
    n_ch = 1 if samples.ndim == 1 else samples.shape[1]
    samples = np.clip(samples, -1.0, 1.0).astype(np.float32)
    return _AudioData(samples=samples, sample_rate=sr, n_channels=n_ch)


def _to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio.astype(np.float32)
    return audio.mean(axis=1).astype(np.float32)


def _resample_to(samples: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """sr_from → sr_to로 리샘플링."""
    if sr_from == sr_to:
        return samples.copy()
    n_out = int(round(len(samples) * sr_to / sr_from))
    return signal.resample(samples, n_out).astype(np.float32)


# ─── 지연 추정/보정 ───────────────────────────────────────────────────────────

def _estimate_delay_cc(ref: np.ndarray, dif: np.ndarray, sr: int) -> float:
    """Cross-correlation 기반 지연 추정 (ms)."""
    corr = signal.correlate(dif, ref, mode="full")
    lags = signal.correlation_lags(len(dif), len(ref), mode="full")
    lag = int(lags[int(np.argmax(corr))])
    return float(lag / sr * 1000.0)


def _refine_delay_dtw(
    ref: np.ndarray, dif: np.ndarray, sr: int, coarse_ms: float,
) -> float:
    """DTW 기반 세부 지연 보정."""
    window = int(0.5 * sr)
    coarse_samp = int(coarse_ms / 1000.0 * sr)

    if coarse_samp >= 0:
        dc, rc = coarse_samp, 0
    else:
        dc, rc = 0, -coarse_samp

    ds = max(0, dc - window)
    de = min(len(dif), dc + window)
    rs = max(0, rc - window)
    re = min(len(ref), rc + window)
    if de <= ds or re <= rs:
        return coarse_ms

    wl = min(de - ds, re - rs)
    de, re = ds + wl, rs + wl
    rw, dw = ref[rs:re], dif[ds:de]
    if len(rw) < 2:
        return coarse_ms

    factor = max(1, sr // min(sr, 4000))
    rds, dds = rw[::factor], dw[::factor]
    ds_sr = sr // factor

    # DTW median lag
    n, m = len(rds), len(dds)
    mat = np.full((n + 1, m + 1), np.inf)
    mat[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(float(rds[i-1]) - float(dds[j-1]))
            mat[i, j] = cost + min(mat[i-1, j], mat[i, j-1], mat[i-1, j-1])
    i, j = n, m
    lags = []
    while i > 0 and j > 0:
        lags.append(j - i)
        cands = [(mat[i-1, j-1], i-1, j-1), (mat[i-1, j], i-1, j), (mat[i, j-1], i, j-1)]
        _, i, j = min(cands, key=lambda x: x[0])
    dtw_lag_ms = (int(np.median(lags)) if lags else 0) / ds_sr * 1000.0
    return float(coarse_ms + dtw_lag_ms)


def _apply_delay(dif: np.ndarray, delay_ms: float, sr: int) -> np.ndarray:
    """지연 보정 적용."""
    n = len(dif)
    shift = int(round(delay_ms / 1000.0 * sr))
    if shift == 0:
        return dif.copy()
    if abs(shift) >= n:
        return np.zeros_like(dif)
    result = np.zeros_like(dif)
    if shift > 0:
        result[:n - shift] = dif[shift:]
    else:
        s = -shift
        result[s:] = dif[:n - s]
    return result


def _align_signals(ref: np.ndarray, dif: np.ndarray, sr: int) -> np.ndarray:
    """지연 추정 + DTW 보정 + 정렬. MAE 기반 자동 선택."""
    coarse = _estimate_delay_cc(ref, dif, sr)
    refined = _refine_delay_dtw(ref, dif, sr, coarse)

    dif_c = _apply_delay(dif, coarse, sr)
    dif_r = _apply_delay(dif, refined, sr)

    n = min(len(ref), len(dif_c), len(dif_r))
    mae_c = float(np.mean(np.abs(ref[:n].astype(np.float64) - dif_c[:n].astype(np.float64))))
    mae_r = float(np.mean(np.abs(ref[:n].astype(np.float64) - dif_r[:n].astype(np.float64))))

    return dif_r if mae_r < mae_c else dif_c


# ─── 이상 검출 핵심 로직 ──────────────────────────────────────────────────────

def _detect_anomalies(
    ref: np.ndarray, dif: np.ndarray, sr: int,
    frame_ms: int = 20, hop_ms: int = 10,
    speech_strong_rms: float = 0.02,
    zero_peak_threshold: float = 0.001,
    gain_drop_ratio: float = 0.4,
    gain_drop_ratio_strict: float = 0.30,
    gain_drop_min_corr: float = 0.3,
    prior_activity_threshold: float = 0.01,
    min_anomaly_ms: int = 50,
    min_anomaly_a_ms: int = 80,
    min_anomaly_b_ms: int = 120,
    anomaly_gap_frames: int = 3,
    chunk_offset_ms: float = 0.0,
) -> list[_AnomalySegment]:
    """주변 대비 ratio 급변 + correlation 기반 이상 구간 검출.
    chunk_offset_ms: 이 청크의 원본 파일 내 절대 시작 시간(ms). 파일 초반 예외 처리용.
    """
    frame_len = int(sr * frame_ms / 1000)
    hop_len = int(sr * hop_ms / 1000)
    if frame_len <= 0 or hop_len <= 0:
        return []

    n = min(len(ref), len(dif))
    if n < frame_len:
        return []

    r = ref[:n].astype(np.float32)
    d = dif[:n].astype(np.float32)
    nf = (n - frame_len) // hop_len + 1
    if nf <= 0:
        return []

    # 프레임별 특성 계산
    ref_rms = np.zeros(nf)
    dif_rms = np.zeros(nf)
    dif_peak = np.zeros(nf)
    corr = np.zeros(nf)

    for i in range(nf):
        s = i * hop_len
        e = s + frame_len
        rf = r[s:e].astype(np.float64)
        df = d[s:e].astype(np.float64)
        ref_rms[i] = np.sqrt(np.mean(rf ** 2))
        dif_rms[i] = np.sqrt(np.mean(df ** 2))
        dif_peak[i] = np.max(np.abs(df))
        if np.std(rf) > 1e-8 and np.std(df) > 1e-8:
            corr[i] = np.corrcoef(rf, df)[0, 1]

    speech = ref_rms > 0.005
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(ref_rms > 0.005, dif_rms / ref_rms, 1.0)

    # 주변 ratio 중앙값 계산 (현재 ±200ms 제외한 ±1초)
    ctx_win = int(1000 / hop_ms)
    exc_half = int(200 / hop_ms)
    ctx_med = np.ones(nf)
    for i in range(nf):
        ls, le = max(0, i - ctx_win), max(0, i - exc_half)
        rs, re = min(nf, i + exc_half), min(nf, i + ctx_win)
        idx = list(range(ls, le)) + list(range(rs, re))
        if idx:
            vals = [ratio[j] for j in idx if speech[j]]
            if len(vals) > 5:
                ctx_med[i] = np.median(vals)

    strong = ref_rms > speech_strong_rms
    not_zero = dif_peak >= 0.001
    min_frames = max(1, min_anomaly_ms // hop_ms)
    min_frames_a = max(1, min_anomaly_a_ms // hop_ms)
    min_frames_b = max(1, min_anomaly_b_ms // hop_ms)

    # 묵음 검출
    zero_mask = strong & (dif_peak < zero_peak_threshold)
    sil_segs = _find_segs(zero_mask, hop_ms, min_frames)

    # 자연 묵음→음성 전환 구간 오탐 제외
    # 1000ms(1초) 룩백으로 확장: 짧은 자연 포즈(100-300ms) 직후 단어 음단절 검출 가능
    # ref_rms 전달: 문장 시작 음단절(직전 ref도 조용한 경우)도 검출 가능
    pre_check = int(1000 / hop_ms)
    sil_segs = [
        seg for seg in sil_segs
        if _has_prior_activity(seg[0], hop_ms, pre_check, dif_peak, prior_activity_threshold,
                               abs_start_ms=chunk_offset_ms,
                               ref_rms=ref_rms, speech_strong_rms=speech_strong_rms)
    ]

    # 깨짐 Type A: ratio 급락 + correlation 높음
    drop_a = ratio < ctx_med * gain_drop_ratio
    mask_a = strong & drop_a & not_zero & (corr > gain_drop_min_corr)
    segs_a = _find_segs(mask_a, hop_ms, min_frames_a)

    # 깨짐 Type A: 전환 구간 오탐 제외
    segs_a = [
        seg for seg in segs_a
        if _has_prior_activity(seg[0], hop_ms, pre_check, dif_peak, prior_activity_threshold,
                               abs_start_ms=chunk_offset_ms)
        and _has_prior_ref_speech(seg[0], hop_ms, pre_check, ref_rms, speech_strong_rms)
        and _has_stable_prior_ratio(seg[0], hop_ms, ratio, strong)
    ]

    # 깨짐 Type B: 더 엄격한 ratio + 장시간 지속
    drop_b = ratio < ctx_med * gain_drop_ratio_strict
    mask_b = strong & drop_b & not_zero & ~mask_a
    segs_b = _find_segs_gap(mask_b, hop_ms, min_frames_b, anomaly_gap_frames)

    # 깨짐 Type B: 전환 구간 오탐 제외
    segs_b = [
        seg for seg in segs_b
        if _has_prior_activity(seg[0], hop_ms, pre_check, dif_peak, prior_activity_threshold,
                               abs_start_ms=chunk_offset_ms)
        and _has_prior_ref_speech(seg[0], hop_ms, pre_check, ref_rms, speech_strong_rms)
        and _has_stable_prior_ratio(seg[0], hop_ms, ratio, strong)
    ]

    # 묵음 직후 200ms 이내 distortion 제외
    sil_ends = [em for _, em, _ in sil_segs]
    segs_b = [s for s in segs_b if not any(abs(s[0] - se) < 200 for se in sil_ends)]

    # 결과 조립
    results: list[_AnomalySegment] = []
    for sm, em, _ in sil_segs:
        is_, ie = int(sm / hop_ms), min(int(em / hop_ms), nf)
        results.append(_AnomalySegment(
            start_ms=float(sm), end_ms=float(em), duration_ms=float(em - sm),
            anomaly_type="digital_zero", mean_gain_db=-100.0,
            mean_correlation=float(np.mean(corr[is_:ie])) if ie > is_ else 0.0,
        ))
    for sm, em, _ in segs_a + segs_b:
        is_, ie = int(sm / hop_ms), min(int(em / hop_ms), nf)
        ar = float(np.mean(ratio[is_:ie])) if ie > is_ else 0.0
        results.append(_AnomalySegment(
            start_ms=float(sm), end_ms=float(em), duration_ms=float(em - sm),
            anomaly_type="gain_drop",
            mean_gain_db=float(20.0 * np.log10(ar + 1e-10)),
            mean_correlation=float(np.mean(corr[is_:ie])) if ie > is_ else 0.0,
        ))
    results.sort(key=lambda x: x.start_ms)
    return results


def _find_segs(mask: np.ndarray, hop_ms: int, min_f: int) -> list[tuple[int, int, int]]:
    segs = []
    in_s, start = False, 0
    for i in range(len(mask) + 1):
        act = i < len(mask) and mask[i]
        if act and not in_s:
            in_s, start = True, i
        elif not act and in_s:
            in_s = False
            if i - start >= min_f:
                segs.append((start * hop_ms, i * hop_ms, i - start))
    return segs


def _find_segs_gap(mask: np.ndarray, hop_ms: int, min_f: int, max_gap: int) -> list[tuple[int, int, int]]:
    segs = []
    in_s, start, gap, last = False, 0, 0, 0
    for i in range(len(mask)):
        if mask[i]:
            if not in_s:
                in_s, start = True, i
            gap, last = 0, i
        elif in_s:
            gap += 1
            if gap > max_gap:
                in_s = False
                ln = last - start + 1
                if ln >= min_f:
                    segs.append((start * hop_ms, (last + 1) * hop_ms, ln))
    if in_s:
        ln = last - start + 1
        if ln >= min_f:
            segs.append((start * hop_ms, (last + 1) * hop_ms, ln))
    return segs


def _has_prior_activity(
    seg_start_ms: int, hop_ms: int,
    pre_check_frames: int, dif_peak: np.ndarray,
    threshold: float = 0.01,
    abs_start_ms: float = 0.0,
    ref_rms: "np.ndarray | None" = None,
    speech_strong_rms: float = 0.02,
) -> bool:
    """묵음 구간 직전에 dif 활성 신호가 있었는지 확인.
    abs_start_ms: 이 청크의 파일 내 절대 시작 시간(ms). 파일 초반 이벤트 예외 처리용.
    ref_rms: 제공되면 문장 시작 음단절 예외 처리에 사용.
      직전 ref도 조용했다면(문장 간 포즈) → test 직전 활성 없어도 허용.
    """
    # 파일 시작 후 2초 이내의 이상은 직전 활성 없이도 검출 허용
    # (대화 첫 마디 음단절, 파일 시작부 이벤트 누락 방지)
    if abs_start_ms + seg_start_ms < 2000:
        return True
    seg_start_frame = int(seg_start_ms / hop_ms)
    pre_start = max(0, seg_start_frame - pre_check_frames)
    if pre_start >= seg_start_frame:
        return True
    prior_max = float(np.max(dif_peak[pre_start:seg_start_frame]))
    if prior_max >= threshold:
        return True
    # 문장 시작 음단절 예외:
    # 직전 ref도 주로 조용했다면(문장 간 자연 포즈) → test 직전 활성 조건 면제
    # → 어떤 문장의 첫 단어/글자 음단절도 검출 가능
    if ref_rms is not None:
        pre_ref = ref_rms[pre_start:seg_start_frame]
        if len(pre_ref) == 0 or float(np.mean(pre_ref > speech_strong_rms)) < 0.25:
            return True
    return False


def _has_prior_ref_speech(
    seg_start_ms: int, hop_ms: int,
    pre_check_frames: int, ref_rms: np.ndarray,
    speech_strong_rms: float,
) -> bool:
    """이상 구간 직전에 ref에 확실한 음성이 있었는지 확인."""
    seg_start_frame = int(seg_start_ms / hop_ms)
    pre_start = max(0, seg_start_frame - pre_check_frames)
    if pre_start >= seg_start_frame:
        return True
    prior_ref = ref_rms[pre_start:seg_start_frame]
    speech_count = int(np.sum(prior_ref > speech_strong_rms))
    return speech_count >= len(prior_ref) // 2


def _has_stable_prior_ratio(
    seg_start_ms: int, hop_ms: int,
    ratio: np.ndarray, speech_strong: np.ndarray,
) -> bool:
    """이상 구간 직전에 안정적인 ratio가 있었는지 확인."""
    seg_start_frame = int(seg_start_ms / hop_ms)
    pre_start = max(0, seg_start_frame - 15)
    if pre_start >= seg_start_frame:
        return True
    stable_count = 0
    for i in range(pre_start, seg_start_frame):
        if speech_strong[i] and ratio[i] > 0.5:
            stable_count += 1
    return stable_count >= 4


# ─── 슈라이딩 윈도우 기반 감지 (누적 드리프트 대응) ─────────────────────────────────────

def _merge_anomaly_events(events: list[_AnomalySegment]) -> list[_AnomalySegment]:
    """겹치거나 100ms 이내 인접한 이상 이벤트를 병합."""
    if not events:
        return []
    events.sort(key=lambda e: e.start_ms)
    merged = [events[0]]
    for ev in events[1:]:
        prev = merged[-1]
        if ev.start_ms <= prev.end_ms + 100:
            prev.end_ms = max(prev.end_ms, ev.end_ms)
            prev.duration_ms = prev.end_ms - prev.start_ms
            if ev.mean_gain_db < prev.mean_gain_db:  # 더 심각한 유형 유지
                prev.mean_gain_db = ev.mean_gain_db
                prev.anomaly_type = ev.anomaly_type
        else:
            merged.append(ev)
    return merged


def _windowed_detect(
    ref: np.ndarray,
    dif_orig: np.ndarray,
    sr: int,
    initial_delay_ms: float = 0.0,
    chunk_sec: float = 4.0,
    hop_sec: float = 2.0,
    max_local_drift_sec: float = 2.0,
    **detect_kwargs,
) -> list[_AnomalySegment]:
    """슈라이딩 윈도우 정렬 + 감지.

    ref를 chunk_sec 단위로 분할, 각 청크에 대해 dif_orig에서 로컈 CC로
    최적 정렬 위치를 상탄적으로 추적. 다중 음단절로 인한 누적 드리프트를
    자동 보정하며, 실제 VoIP 지연에도 강인.
    """
    chunk_n = int(chunk_sec * sr)
    hop_n   = int(hop_sec * sr)
    search_r = int(max_local_drift_sec * sr)

    init_offset = int(round(initial_delay_ms / 1000.0 * sr))
    dif_cursor  = init_offset   # dif에서 현재 예상 위치 (드리프트 추적)

    all_events: list[_AnomalySegment] = []

    for ref_start in range(0, len(ref), hop_n):
        ref_end   = min(len(ref), ref_start + chunk_n)
        ref_chunk = ref[ref_start:ref_end]
        if len(ref_chunk) < sr // 4:   # < 0.25초 → 스킵
            break

        # dif 탐색 범위: cursor ± search_r
        dif_s = max(0, dif_cursor - search_r)
        dif_e = min(len(dif_orig), dif_cursor + len(ref_chunk) + search_r)
        dif_search = dif_orig[dif_s:dif_e]

        if len(dif_search) < len(ref_chunk) // 4:
            continue

        # 로컈 CC (소험비용 FFT 활용)
        if len(dif_search) >= len(ref_chunk):
            c = signal.correlate(dif_search, ref_chunk, mode='valid')
            best_in_search = int(np.argmax(c))
        else:
            best_in_search = 0

        dif_cs = dif_s + best_in_search
        dif_ce = min(len(dif_orig), dif_cs + len(ref_chunk))
        dif_chunk = dif_orig[dif_cs:dif_ce].copy()
        if len(dif_chunk) < len(ref_chunk):
            dif_chunk = np.pad(dif_chunk, (0, len(ref_chunk) - len(dif_chunk)))

        chunk_offset_ms = ref_start * 1000.0 / sr
        chunk_events = _detect_anomalies(
            ref_chunk, dif_chunk, sr,
            chunk_offset_ms=chunk_offset_ms,
            **detect_kwargs,
        )
        # 쫑크 상대 시간 → 파일 절대 시간
        for ev in chunk_events:
            ev.start_ms += chunk_offset_ms
            ev.end_ms   += chunk_offset_ms

        all_events.extend(chunk_events)

        # cursor 업데이트: 이번 정렬 위치에서 hop_n 진행
        dif_cursor = dif_cs + hop_n

    return _merge_anomaly_events(all_events)


# ─── 슬라이딩 윈도우 기반 감지 (누적 드리프트 대응) ─────────────────────────────────────

def _merge_anomaly_events(events: list[_AnomalySegment]) -> list[_AnomalySegment]:
    """겹치거나 100ms 이내 인접한 이상 이벤트를 병합."""
    if not events:
        return []
    events.sort(key=lambda e: e.start_ms)
    merged = [events[0]]
    for ev in events[1:]:
        prev = merged[-1]
        if ev.start_ms <= prev.end_ms + 100:
            prev.end_ms = max(prev.end_ms, ev.end_ms)
            prev.duration_ms = prev.end_ms - prev.start_ms
            if ev.mean_gain_db < prev.mean_gain_db:
                prev.mean_gain_db = ev.mean_gain_db
                prev.anomaly_type = ev.anomaly_type
        else:
            merged.append(ev)
    return merged


def _windowed_detect(
    ref: np.ndarray,
    dif_orig: np.ndarray,
    sr: int,
    initial_delay_ms: float = 0.0,
    chunk_sec: float = 6.0,
    hop_sec: float = 3.0,
    max_local_drift_sec: float = 2.5,
    **detect_kwargs,
) -> list[_AnomalySegment]:
    """슬라이딩 윈도우 정렬 + 감지.

    ref를 chunk_sec 단위로 분할, 각 청크에 대해 dif_orig에서 로컬 CC로
    최적 정렬 위치를 상태적으로 추적. 다중 음단절로 인한 누적 드리프트를
    자동 보정하며, 실제 VoIP 환경(드리프트 없음)에서도 동일하게 동작.

    chunk_sec=6 / hop_sec=3: 더 넓은 컨텍스트로 정렬 안정성 향상.
    커서 연속성 제약: 직전 hop 대비 500ms 이상 급격히 튀면 이전 경로 유지.
    """
    chunk_n  = int(chunk_sec * sr)
    hop_n    = int(hop_sec * sr)
    search_r = int(max_local_drift_sec * sr)
    max_cursor_jump = int(0.5 * sr)  # 커서가 한 hop 내 500ms 이상 변화하면 보정

    init_offset = int(round(initial_delay_ms / 1000.0 * sr))
    dif_cursor  = init_offset   # dif에서 현재 예상 위치

    all_events: list[_AnomalySegment] = []

    for ref_start in range(0, len(ref), hop_n):
        ref_end   = min(len(ref), ref_start + chunk_n)
        ref_chunk = ref[ref_start:ref_end]
        if len(ref_chunk) < sr // 4:   # < 0.25초 → 스킵
            break

        # dif 탐색 범위: cursor ± search_r
        dif_s = max(0, dif_cursor - search_r)
        dif_e = min(len(dif_orig), dif_cursor + len(ref_chunk) + search_r)
        dif_search = dif_orig[dif_s:dif_e]

        if len(dif_search) < len(ref_chunk) // 4:
            continue

        # 로컬 CC (FFT 기반, scipy가 자동 선택)
        if len(dif_search) >= len(ref_chunk):
            c = signal.correlate(dif_search, ref_chunk, mode='valid')
            best_in_search = int(np.argmax(c))
        else:
            best_in_search = 0

        dif_cs = dif_s + best_in_search
        dif_ce = min(len(dif_orig), dif_cs + len(ref_chunk))
        dif_chunk = dif_orig[dif_cs:dif_ce].copy()
        if len(dif_chunk) < len(ref_chunk):
            dif_chunk = np.pad(dif_chunk, (0, len(ref_chunk) - len(dif_chunk)))

        chunk_offset_ms = ref_start * 1000.0 / sr
        chunk_events = _detect_anomalies(
            ref_chunk, dif_chunk, sr,
            chunk_offset_ms=chunk_offset_ms,
            **detect_kwargs,
        )
        for ev in chunk_events:
            ev.start_ms += chunk_offset_ms
            ev.end_ms   += chunk_offset_ms

        all_events.extend(chunk_events)

        # cursor 업데이트: 커서 급변 억제 (연속성 제약)
        new_cursor = dif_cs + hop_n
        expected_cursor = dif_cursor + hop_n
        if abs(new_cursor - expected_cursor) > max_cursor_jump:
            # 탐색에서 튄 경우: 예상 위치 사용 (점진적 추적)
            dif_cursor = expected_cursor
        else:
            dif_cursor = new_cursor

    return _merge_anomaly_events(all_events)


# ─── 공개 API ─────────────────────────────────────────────────────────────────

def detect_dif_only_events(
    ref_path: str,
    dif_path: str,
    *,
    speech_strong_rms: float = 0.02,
    zero_peak_threshold: float = 0.001,
    gain_drop_ratio: float = 0.4,
    gain_drop_ratio_strict: float = 0.30,
    gain_drop_min_corr: float = 0.3,
    prior_activity_threshold: float = 0.01,
    min_anomaly_ms: int = 80,
    min_anomaly_a_ms: int = 80,
    min_anomaly_b_ms: int = 120,
    anomaly_gap_frames: int = 3,
) -> list[dict]:
    """ref(원본)와 dif(수신본) WAV 파일을 비교하여 dif-only 이상 이벤트를 반환한다.

    GUI의 'dif-only 이벤트' 테이블과 동일한 결과를 dict 리스트로 반환합니다.
    이상이 없으면 빈 리스트를 반환합니다.

    매개변수:
        ref_path (str): 기준 WAV 파일 경로 (원본 전송음)
        dif_path (str): 비교 WAV 파일 경로 (수신 녹음본)
        speech_strong_rms (float): ref 확실한 음성 판정 RMS 임계값 (기본 0.03)
        zero_peak_threshold (float): dif 디지털 제로 판정 peak 임계값 (기본 0.0005)
        gain_drop_ratio (float): 깨짐 A 주변 대비 ratio 임계값 (기본 0.4)
        gain_drop_ratio_strict (float): 깨짐 B ratio 임계값 (기본 0.30)
        gain_drop_min_corr (float): 깨짐 A 최소 correlation (기본 0.3)
        prior_activity_threshold (float): 직전 dif 활성 판정 peak 임계값 (기본 0.01)
        min_anomaly_ms (int): 묵음 최소 지속 시간 ms (기본 50)
        min_anomaly_a_ms (int): 깨짐 A 최소 지속 시간 ms (기본 80)
        min_anomaly_b_ms (int): 깨짐 B 최소 지속 시간 ms (기본 120)
        anomaly_gap_frames (int): 깨짐 B gap 허용 프레임 수 (기본 3)

    반환값:
        list[dict]: 이상 이벤트 리스트. 각 dict는 다음 필드를 포함:
            - index       (int)   : 이벤트 번호 (1부터)
            - type        (str)   : "묵음" 또는 "깨짐"
            - duration_ms (float) : 지속 시간 (ms)
            - start_s     (float) : 시작 시간 (초, 소수점 3자리)
            - end_s       (float) : 종료 시간 (초, 소수점 3자리)
            - gain_db     (float) : 구간 평균 gain (dB). 묵음은 -100.0
            - correlation (float) : 구간 평균 Pearson correlation

    예외:
        FileNotFoundError: 파일이 존재하지 않는 경우
        ValueError: 유효하지 않은 WAV 형식인 경우

    사용 예시:
        >>> from audio_anomaly_detector import detect_dif_only_events
        >>> events = detect_dif_only_events("ref.wav", "dif.wav")
        >>> for e in events:
        ...     print(f"#{e['index']} {e['type']} {e['duration_ms']:.0f}ms "
        ...           f"({e['start_s']:.3f}s ~ {e['end_s']:.3f}s)")
    """
    # 1. WAV 로드
    ref_data = _load_wav(ref_path)
    dif_data = _load_wav(dif_path)

    ref_mono = _to_mono(ref_data.samples)
    dif_mono = _to_mono(dif_data.samples)

    # 2. 리샘플링 (dif를 ref SR에 맞춤)
    sr = ref_data.sample_rate
    if dif_data.sample_rate != sr:
        dif_mono = _resample_to(dif_mono, dif_data.sample_rate, sr)

    # 3. 전역 소컨 정렬로 초기 VoIP 지연 추정
    initial_delay_ms = _estimate_delay_cc(ref_mono, dif_mono, sr)

    # 4. 슬라이딩 윈도우 기반 감지
    #    - 청크별 로컬 CC 정렬 → 다중 음단절로 인한 누적 드리프트 처리
    #    - VoIP 환경(드리프트 없음)에서도 동일하게 동작
    detect_kwargs = dict(
        speech_strong_rms=speech_strong_rms,
        zero_peak_threshold=zero_peak_threshold,
        gain_drop_ratio=gain_drop_ratio,
        gain_drop_ratio_strict=gain_drop_ratio_strict,
        gain_drop_min_corr=gain_drop_min_corr,
        prior_activity_threshold=prior_activity_threshold,
        min_anomaly_ms=min_anomaly_ms,
        min_anomaly_a_ms=min_anomaly_a_ms,
        min_anomaly_b_ms=min_anomaly_b_ms,
        anomaly_gap_frames=anomaly_gap_frames,
    )
    anomalies = _windowed_detect(
        ref_mono, dif_mono, sr,
        initial_delay_ms=initial_delay_ms,
        **detect_kwargs,
    )

    # 6. dict 리스트로 변환
    events: list[dict] = []
    for i, a in enumerate(anomalies):
        label = "묵음" if a.anomaly_type == "digital_zero" else "깨짐"
        events.append({
            "index": i + 1,
            "type": label,
            "duration_ms": round(a.duration_ms, 1),
            "start_s": round(a.start_ms / 1000, 3),
            "end_s": round(a.end_ms / 1000, 3),
            "gain_db": round(a.mean_gain_db, 1),
            "correlation": round(a.mean_correlation, 4),
        })

    return events


# ─── CLI 실행 지원 ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("사용법: python audio_anomaly_detector.py <ref.wav> <dif.wav>")
        print("예시:   python audio_anomaly_detector.py sample_audio/B_iOS_ref.wav sample_audio/B_iOS_dif_1.wav")
        sys.exit(1)

    ref, dif = sys.argv[1], sys.argv[2]
    print(f"분석 중... ref={ref}, dif={dif}")

    events = detect_dif_only_events(ref, dif)

    if not events:
        print("이상 없음 (dif-only 이벤트 0건)")
    else:
        print(f"\ndif-only 이벤트: {len(events)}건")
        print(f"{'#':>3}  {'구분':>4}  {'길이(ms)':>8}  {'시작(s)':>8}  {'종료(s)':>8}")
        print("-" * 42)
        for e in events:
            print(f"{e['index']:>3}  {e['type']:>4}  {e['duration_ms']:>8.1f}  "
                  f"{e['start_s']:>8.3f}  {e['end_s']:>8.3f}")
