#!/usr/bin/env python3
"""
script_gap_detector.py
────────────────────────────────────────────────────────────────────────────
대본 기반 문장 단위 음단절 감지 (Android 전용, LINE IN 녹음 대응).

analyze_hybrid.py 의 SCRIPT_REFERENCE 대본을 이용해
정답지(ref WAV)에서 각 대사의 발화 구간을 VAD로 자동 탐지하고,
Android 녹음본에서 해당 발화가 존재하는지
에너지 엔벨로프 cross-correlation 으로 검사합니다.

분석 흐름:
  1. SCRIPT_REFERENCE 파싱  → [(화자, 대사), ...]
  2. 정답지 VAD 분절         → 묵음(< ref_min_db)이 silence_gap_ms 이상 지속되면
                               새 발화로 분리
  3. 발화 N개 ↔ 대본 L줄 매칭 → 순서 기반 자동 매핑 (min(N, L) 까지)
  4. 각 발화 구간의 에너지 프로파일을 Android 녹음의 기대 위치 ±search_sec 창으로
     슬라이딩 하여 최대 엔벨로프 상관계수 산출
  5. 최대 상관계수 < corr_threshold 이면 음단절 판정

사용:
    python script_gap_detector.py \\
        --ref  audiomass-output_mono.wav \\
        --test audio_files/recordings/Android_ixiO_20260313_171421.wav

    python script_gap_detector.py \\
        --ref  audiomass-output_mono.wav \\
        --test audio_files/recordings/Android_ixiO_20260313_171421.wav \\
        --output result_script.json \\
        --corr-threshold 0.3

옵션:
    --ref               정답지 WAV (기준 음원)
    --test              Android 녹음본 WAV
    --output            JSON 저장 경로 (생략 시 저장 안 함)
    --ref-min-db        정답지 발화 판정 기준 dB    (기본 -45)
    --silence-gap-ms    발화 분절 말묵음 최소 길이   (기본 800 ms)
    --min-seg-ms        발화 최소 길이               (기본 300 ms)
    --corr-threshold    음단절 판정 임계 상관계수    (기본 0.30)
    --search-sec        각 구간 탐색 창 ±초          (기본 8.0 s)
    --frame-ms          에너지 프레임 크기           (기본 20 ms)
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from audio_lib.consts import FRAME_MS, REF_MIN_DB, SILENCE_DB
from audio_lib.io    import load_wav_mono, resample
from audio_lib.dsp   import energy_profile

# ── 기본 파라미터 ──────────────────────────────────────
# FRAME_MS 와 REF_MIN_DB 는 audio_lib.consts 에서 import
SILENCE_GAP_MS  = 700     # 이 길이 이상 묵음이면 새 발화로 분절
MIN_SEG_MS      = 400     # 발화 최소 길이 (이보다 짧으면 노이즈로 제외)
CORR_THRESHOLD  = 0.30    # 최대 상관계수 < 이 값이면 음단절
SEARCH_SEC      = 8.0     # 각 구간 탐색 창 ±초
MAX_ALIGN_SEC   = 30.0    # 전체 오프셋 탐색 범위 (초)
# ── 품질 등급 임계값 ──────────────────────────────────────
# VoIP 코덱(AMR/EVS) 경로를 거치면 상관계수가 자연스럽게 떨어지지만,
# 0.75 이상이면 양호한 통화 품질로 판단.
CORR_GOOD            = 0.92    # ≥ 이 값 → ✅ 정상 (quality_grade 기준)
CORR_SKIP_FRAME_SCAN = 0.85    # ≥ 이 값 → frame-level partial scan 스킵
                               # 0.85+ 상관계수 = 오디오 명확히 존재 → 자연 포즈를 오탐하지 않음
CORR_DEGRADED   = 0.55    # ≥ 이 값 → ⚠️ 품질저하  (그 미만이면 ❌ 심각)

# ─────────────────────────────────────────────────────────────────────────────
# load_wav_mono, resample, energy_profile → audio_lib.io / audio_lib.dsp
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# 전역 오프셋 추정 (정답지 vs 녹음본 시작 시간 차이)
# ─────────────────────────────────────────────────────────────────────────────

def global_offset_sec(ref_audio: np.ndarray, test_audio: np.ndarray,
                      sr: int,
                      max_offset_sec: float = MAX_ALIGN_SEC) -> float:
    """Raw waveform FFT cross-correlation 으로 전역 시간 오프셋(초) 반환.
    양수 = test 가 ref 보다 해당 시간만큼 늦게 시작
    (즉, ref[offset:] ≈ test)
    """
    max_lag = int(max_offset_sec * sr)
    n = len(ref_audio) + len(test_audio)
    fa = np.fft.rfft(ref_audio.astype(np.float64), n=n)
    fb = np.fft.rfft(test_audio.astype(np.float64), n=n)
    corr = np.fft.irfft(fa * np.conj(fb), n=n)
    # lag 범위: [-max_lag, +max_lag]
    cands = np.concatenate([corr[-max_lag:], corr[:max_lag + 1]])
    peak = int(np.argmax(cands)) - max_lag
    return round(peak / sr, 3)


# ─────────────────────────────────────────────────────────────────────────────
# 정답지 VAD 분절
# ─────────────────────────────────────────────────────────────────────────────

def vad_segments(db: np.ndarray, frame_sec: float,
                 ref_min_db: float = REF_MIN_DB,
                 silence_gap_ms: float = SILENCE_GAP_MS,
                 min_seg_ms: float     = MIN_SEG_MS,
                 ) -> list[tuple[float, float]]:
    """묵음 기준 발화 구간 분절.

    Returns:
        [(start_sec, end_sec), ...] 정렬된 발화 구간 목록
    """
    voice      = db >= ref_min_db
    gap_frames = max(1, int(silence_gap_ms / 1000 / frame_sec))
    min_frames = max(1, int(min_seg_ms    / 1000 / frame_sec))

    # 짧은 묵음은 소음으로 보고 메워줌 (200ms 이하)
    fill_frames = max(1, int(200 / 1000 / frame_sec))
    filled = voice.copy()
    i = 0
    while i < len(filled):
        if not filled[i]:
            j = i
            while j < len(filled) and not filled[j]:
                j += 1
            if (j - i) <= fill_frames:
                filled[i:j] = True
            i = j
        else:
            i += 1

    segments: list[tuple[float, float]] = []
    start: Optional[int] = None
    i = 0

    while i < len(filled):
        v = filled[i]
        if v:
            if start is None:
                start = i
            i += 1
        else:
            if start is None:
                i += 1
                continue
            # 묵음 구간 끝 위치 탐색
            sil_end = i
            while sil_end < len(filled) and not filled[sil_end]:
                sil_end += 1
            sil_len = sil_end - i

            if sil_len >= gap_frames or sil_end >= len(filled):
                # 새 발화 경계
                length = i - start
                if length >= min_frames:
                    segments.append((start * frame_sec, i * frame_sec))
                start = None
                i = sil_end   # 묵음 구간 전체를 건너뜀
            else:
                # 짧은 묵음 → 발화 내 쉬어가기로 간주, 발화 지속
                i = sil_end   # 묵음 구간 건너뜀

    # 파일 끝까지 발화가 이어진 경우
    if start is not None:
        length = len(filled) - start
        if length >= min_frames:
            segments.append((start * frame_sec, len(filled) * frame_sec))

    return segments


# ─────────────────────────────────────────────────────────────────────────────
# 대본 파싱
# ─────────────────────────────────────────────────────────────────────────────

def parse_script(script_text: str) -> list[dict]:
    """SCRIPT_REFERENCE 텍스트를 파싱해 발화 목록 반환.

    Returns:
        [{'speaker': '박편육', 'text': '안녕하십니까...', 'line_idx': 0}, ...]
    """
    lines: list[dict] = []
    current_speaker = ''
    buf: list[str] = []

    def flush():
        t = ' '.join(buf).strip()
        if t and current_speaker:
            lines.append({'speaker': current_speaker, 'text': t,
                          'line_idx': len(lines)})
        buf.clear()

    for raw in script_text.splitlines():
        line = raw.strip()
        if not line or line.startswith('===') or line.startswith('---') \
                or line.startswith('【'):
            flush()
            continue
        # [화자명] 태그 (← 화자 전환 주석 제외)
        m = re.match(r'^\[([^\]]+)\]', line)
        if m:
            flush()
            current_speaker = m.group(1).split('←')[0].strip()
        else:
            # 일반 대사 라인
            if current_speaker:
                buf.append(line)

    flush()
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# 발화 구간 단위 엔벨로프 상관관계 탐색
# ─────────────────────────────────────────────────────────────────────────────

def _env_corr(a: np.ndarray, b: np.ndarray) -> float:
    """두 에너지 프로파일의 정규화 내적 (코사인 유사도)."""
    a = a - a.mean();  b = b - b.mean()
    na = float(np.linalg.norm(a));  nb = float(np.linalg.norm(b))
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def segment_max_correlation(
    ref_seg_db:  np.ndarray,      # 정답지 발화 구간 에너지 프로파일
    test_db:     np.ndarray,      # Android 녹음본 전체 에너지 프로파일
    expected_start_frame: int,    # 기대 시작 프레임 (전역 오프셋 보정 후)
    search_frames: int,           # 탐색 창 크기 (프레임)
) -> tuple[float, int]:
    """test_db 에서 ref_seg_db 와 가장 유사한 구간을 탐색.

    Returns:
        (max_corr, best_frame_start)
    """
    seg_len = len(ref_seg_db)
    if seg_len == 0 or len(test_db) < seg_len:
        return 0.0, 0

    lo = max(0, expected_start_frame - search_frames)
    hi = min(len(test_db) - seg_len, expected_start_frame + search_frames)

    if lo >= hi:
        # 탐색 창이 test 범위 밖 → 전체 범위에서 탐색
        lo, hi = 0, max(0, len(test_db) - seg_len)
    if lo >= hi:
        return 0.0, 0

    # ── 1단계: 빠른 탐색 (coarse) ──
    span = hi - lo
    hop  = max(1, span // 400)   # 최대 400스텝

    best_corr       = -2.0
    best_frame      = lo

    for pos in range(lo, hi, hop):
        window = test_db[pos: pos + seg_len]
        if len(window) < seg_len:
            break
        c = _env_corr(ref_seg_db, window)
        if c > best_corr:
            best_corr  = c
            best_frame = pos

    # ── 2단계: 정밀 탐색 (fine) — coarse 최적 위치 ±hop 범위를 1프레임 단위로 재탐색 ──
    if hop > 1:
        fine_lo = max(lo, best_frame - hop)
        fine_hi = min(hi, best_frame + hop + 1)
        for pos in range(fine_lo, fine_hi):
            window = test_db[pos: pos + seg_len]
            if len(window) < seg_len:
                break
            c = _env_corr(ref_seg_db, window)
            if c > best_corr:
                best_corr  = c
                best_frame = pos

    return round(float(best_corr), 4), best_frame


# ─────────────────────────────────────────────────────────────────────────────
# 메인 분석 함수
# ─────────────────────────────────────────────────────────────────────────────

def analyze_by_script(
    ref_path:        str | Path,
    test_path:       str | Path,
    script_text:     str,
    frame_ms:        int   = FRAME_MS,
    ref_min_db:      float = REF_MIN_DB,
    silence_gap_ms:  float = SILENCE_GAP_MS,
    min_seg_ms:      float = MIN_SEG_MS,
    corr_threshold:  float = CORR_THRESHOLD,
    search_sec:      float = SEARCH_SEC,
    speaker_filter:  'str | list[str] | None' = None,
) -> dict:
    # ── 로드 ──────────────────────────────────────────────────────────────
    ref_audio,  ref_sr  = load_wav_mono(ref_path)
    test_audio, test_sr = load_wav_mono(test_path)
    print(f"📂 정답지  : {Path(ref_path).name}  ({ref_sr}Hz, {len(ref_audio)/ref_sr:.1f}s)")
    print(f"📂 녹음본  : {Path(test_path).name}  ({test_sr}Hz, {len(test_audio)/test_sr:.1f}s)")

    if test_sr != ref_sr:
        test_audio = resample(test_audio, test_sr, ref_sr)
        print(f"ℹ️  리샘플: {test_sr}Hz → {ref_sr}Hz")

    sr = ref_sr

    # ── 에너지 프로파일 ──────────────────────────────────────────────────
    ref_db,  fsec = energy_profile(ref_audio,  sr, frame_ms)
    test_db, _    = energy_profile(test_audio, sr, frame_ms)

    # ── 전역 오프셋 ──────────────────────────────────────────────────────
    off_sec  = global_offset_sec(ref_audio, test_audio, sr)
    off_fr   = int(round(off_sec / fsec))
    print(f"🔀 전역 정렬 오프셋: {off_sec:+.3f}s  ({off_fr:+d} frames)")

    # ── VAD 분절 ─────────────────────────────────────────────────────────
    segments = vad_segments(ref_db, fsec,
                            ref_min_db=ref_min_db,
                            silence_gap_ms=silence_gap_ms,
                            min_seg_ms=min_seg_ms)
    print(f"🎙️  VAD 분절 결과: {len(segments)}개 발화 구간 감지")

    # ── 대본 파싱 ─────────────────────────────────────────────────────────
    script_lines = parse_script(script_text)
    print(f"📜 대본 파싱: {len(script_lines)}개 대사")

    # ── 화자 필터링 ─────────────────────────────────────────────────────
    # 정답지(ref)에 특정 화자만 포함된 경우, 해당 화자의 대사만 추출하여
    # VAD 구간과 1:1 매칭 (다른 화자 대사는 VAD 구간 소비 없이 건너뜀)
    if speaker_filter:
        if isinstance(speaker_filter, str):
            speaker_filter = [speaker_filter]
        _filter_set = set(speaker_filter)
        _before = len(script_lines)
        script_lines = [l for l in script_lines if l.get('speaker') in _filter_set]
        print(f"🔍 화자 필터: {', '.join(speaker_filter)} → {len(script_lines)}/{_before}개 대사")

    n_segs  = len(segments)
    n_lines = len(script_lines)
    total_dur_s = len(ref_db) * fsec

    # ── 세그먼트 수 ↔ 대본 줄수 불일치 보정 ──────────────────────────────
    # VAD가 대사 내 자연 포즈로 한 줄을 두 구간으로 분절하는 경우,
    # 인접 구간 사이 침묵 갭이 가장 짧은 쌍부터 병합하여 n_lines 개로 맞춤.
    # 반대로 VAD 구간이 부족하면 기존처럼 균등 분할 위치 추정 사용.
    if n_segs > n_lines:
        _segs = list(segments)
        while len(_segs) > n_lines:
            # 인접 구간 사이 갭이 가장 작은 쌍 탐색 → 병합
            _min_gap = float('inf')
            _min_i   = 0
            for _i in range(len(_segs) - 1):
                _gap = _segs[_i + 1][0] - _segs[_i][1]
                if _gap < _min_gap:
                    _min_gap = _gap
                    _min_i   = _i
            _merged = (_segs[_min_i][0], _segs[_min_i + 1][1])
            _segs = _segs[:_min_i] + [_merged] + _segs[_min_i + 2:]
        segments = _segs
        n_segs   = len(segments)
        print(f"🔀 VAD 세그먼트 병합: → {n_segs}개 (대본 {n_lines}개에 맞춤)")
    elif n_segs != n_lines:
        print(f"⚠️  발화 구간({n_segs}) ≠ 대본 줄수({n_lines}) "
              f"→ 균등 분할 위치로 부족한 {n_lines - n_segs}개 추정")

    n_total = max(n_segs, n_lines)

    # ── 탐색 창 크기 ─────────────────────────────────────────────────────
    search_frames = max(1, int(search_sec / fsec))

    # ── 각 발화 구간 분석 ─────────────────────────────────────────────────
    results: list[dict] = []

    for idx in range(n_total):
        # VAD 구간: 있으면 사용, 없으면 전체 길이를 n_total 등분하여 위치 추정
        if idx < n_segs:
            seg_start_s, seg_end_s = segments[idx]
        else:
            seg_start_s = (idx / n_total) * total_dur_s
            seg_end_s   = ((idx + 1) / n_total) * total_dur_s

        # 대본 줄: 있으면 사용, 없으면 플레이스홀더
        if idx < n_lines:
            line = script_lines[idx]
        else:
            line = {'speaker': '?', 'text': '(대본 없음)'}

        # 정답지에서 해당 발화 구간 에너지 프로파일
        f_start = int(seg_start_s / fsec)
        f_end   = int(seg_end_s   / fsec)
        ref_seg_db = ref_db[f_start:f_end]

        if len(ref_seg_db) < 2:
            continue

        # test에서 기대 시작 프레임 (전역 오프셋 적용)
        # off_sec > 0: test가 ref보다 off_sec 늦게 시작 → test_frame = ref_frame - off_fr
        expected_f = max(0, f_start - off_fr)

        max_corr, best_f = segment_max_correlation(
            ref_seg_db, test_db, expected_f, search_frames
        )

        # ── 에너지 확인: 녹음본에 실제 음성 에너지가 존재하면 음단절이 아님 ──
        # 통화 코덱(AMR/EVS) 경로를 거치면 파형 형태가 크게 변해
        # 상관계수가 낮아질 수 있지만, 실제로 소리가 들린다면 음단절이 아님.
        # 판정: corr < threshold AND 녹음본 해당 구간 평균 에너지 < silence_db
        test_seg_slice = test_db[best_f:best_f + len(ref_seg_db)]
        if len(test_seg_slice) > 0:
            test_avg_db = float(np.mean(test_seg_slice))
            test_has_sound = test_avg_db >= SILENCE_DB
        else:
            test_has_sound = False

        dropped = max_corr < corr_threshold and not test_has_sound
        # ── 품질 등급 판정 ───────────────────────────────────────────
        # 음단절이 아니더라도 VoIP 코덱 경유 후 품질 저하 판단
        if dropped:
            quality_grade = 'dropout'
        elif max_corr >= CORR_GOOD:
            quality_grade = 'good'
        elif max_corr >= CORR_DEGRADED:
            quality_grade = 'degraded'
        else:
            quality_grade = 'poor'  # < CORR_DEGRADED 이면서 음단절은 아닔
        # ── 프레임 레벨 피크 스캔 (audio_anomaly_detector 방식 차용) ─────────
        # 기존 200ms dB 평균 서브윈도우 방식의 한계를 극복:
        #   · 170ms 이하 짧은 묵음: 200ms 창 안에서 dB 평균이 묻혀 미검출
        #   · VAD 경계 dropout: 구간 끝에 걸친 묵음이 다음 세그먼트로 밀려남
        #
        # 개선 방식:
        #   · 10ms 프레임 단위 raw 샘플 peak 스캔 (audio_anomaly_detector 동일 기준)
        #   · peak < 0.001 인 연속 프레임 ≥ 100ms → 묵음 스팬으로 판정
        #   · VAD 구간 끝 +1.5초 연장 스캔 → 경계 걸친 dropout 포착 ("걷자" 등)
        #   · ref도 무음인 프레임은 자연 포즈로 건너뜀 (오탐 방지)
        partial_drop = False
        partial_drop_ms = 0.0

        # 녹음 끝부분 임계 완화 (통화 종료/트림으로 인한 자연 잘림 가능성)
        test_dur_s = len(test_db) * fsec
        _is_tail_seg = seg_end_s >= (test_dur_s - 5.0)
        _partial_min_ms = 300 if _is_tail_seg else 100

        # 상관계수가 충분히 높으면 오디오가 명확히 존재 → frame scan 스킵
        # CORR_SKIP_FRAME_SCAN(0.85) 이상이면 자연 발화 포즈를 묵음으로 오탐하지 않도록 건너뜀
        # (CORR_GOOD=0.92 와 분리: quality_grade 판정에만 0.92 사용)
        if not dropped and max_corr < CORR_SKIP_FRAME_SCAN:
            _FHOP_MS   = 10       # 10ms 프레임 — audio_anomaly_detector와 동일
            _ZERO_TH   = 0.001    # digital zero 판정 peak 임계값
            _SPAN_MIN  = 100      # 연속 묵음 최소 스팬 (ms)
            _PAD_S     = 1.5      # VAD 구간 끝 연장 스캔 (경계 dropout 포착)

            _fhop = int(sr * _FHOP_MS / 1000)
            _ref_s  = int(f_start * fsec * sr)
            _ref_e  = int(f_end   * fsec * sr)
            _test_s = int(best_f  * fsec * sr)
            _test_e = min(len(test_audio),
                          _test_s + (_ref_e - _ref_s) + int(_PAD_S * sr))
            _scan_len  = _test_e - _test_s
            _ref_span  = max(1, _ref_e - _ref_s)

            _sil_total_ms = 0.0
            _in_sil       = False
            _sil_start_ms = 0.0

            for _fi in range(0, _scan_len - _fhop, _fhop):
                # ref 대응 위치 (PAD 구간은 마지막 ref 프레임으로 clamp)
                _rfi = min(_fi, _ref_span - _fhop)
                _rs, _re = _ref_s + _rfi, _ref_s + _rfi + _fhop
                _ref_rms = float(np.sqrt(np.mean(
                    ref_audio[_rs:min(len(ref_audio), _re)].astype(np.float64) ** 2)))

                if _ref_rms < 0.005:   # ref 자연 묵음 → 스킵
                    if _in_sil:
                        _in_sil = False
                        _span = _fi * 1000.0 / sr - _sil_start_ms
                        if _span >= _SPAN_MIN:
                            _sil_total_ms += _span
                    continue

                _ts, _te = _test_s + _fi, _test_s + _fi + _fhop
                if _te > len(test_audio):
                    break
                _peak = float(np.max(np.abs(
                    test_audio[_ts:_te].astype(np.float64))))
                _off_ms = _fi * 1000.0 / sr

                # PAD 구간에서 새로 시작되는 묵음은 다음 화자 사이 자연 공백일 수 있음
                # → PAD 구간(ref segment 끝 이후)에서 묵음이 시작되면 무시
                _in_pad = (_fi >= _ref_span)

                if _peak < _ZERO_TH:
                    if not _in_sil and not _in_pad:
                        _in_sil       = True
                        _sil_start_ms = _off_ms
                else:
                    if _in_sil:
                        _in_sil = False
                        _span = _off_ms - _sil_start_ms
                        if _span >= _SPAN_MIN:
                            _sil_total_ms += _span

            # 스캔 끝에서 묵음 종료 처리 (PAD 내에서 시작된 묵음은 무시됨)
            if _in_sil:
                _span = (_scan_len - _fhop) * 1000.0 / sr - _sil_start_ms
                if _span >= _SPAN_MIN:
                    _sil_total_ms += _span

            if _sil_total_ms >= _partial_min_ms:
                partial_drop    = True
                partial_drop_ms = round(_sil_total_ms, 0)
                dropped         = True

        best_time_s = round(best_f * fsec, 3)

        results.append({
            'line_idx':       idx,
            'speaker':        line['speaker'],
            'text':           line['text'],
            'ref_start_s':    round(seg_start_s, 3),
            'ref_end_s':      round(seg_end_s,   3),
            'ref_dur_ms':     round((seg_end_s - seg_start_s) * 1000, 0),
            'test_best_s':    best_time_s,
            'max_corr':       max_corr,
            'dropped':        dropped,
            'partial_drop':   partial_drop,
            'partial_drop_ms': partial_drop_ms,
            'quality_grade':  quality_grade,
            'status':         '❌ 부분음단절' if partial_drop
                              else ('❌ 음단절' if dropped
                              else ('⚠️ 품질저하' if quality_grade == 'degraded'
                              else ('❌ 심각한 품질저하' if quality_grade == 'poor'
                              else '✅ 정상'))),
        })

    # ── 요약 ─────────────────────────────────────────────────────────────
    n_compared = len(results)
    n_dropped  = sum(1 for r in results if r['dropped'])
    n_degraded = sum(1 for r in results if r.get('quality_grade') == 'degraded')
    n_poor     = sum(1 for r in results if r.get('quality_grade') == 'poor')
    n_good     = sum(1 for r in results if r.get('quality_grade') == 'good')
    return {
        'ref':            str(Path(ref_path).name),
        'test':           str(Path(test_path).name),
        'offset_sec':     off_sec,
        'total_segments': n_segs,
        'total_script':   n_lines,
        'compared':       n_compared,
        'dropped_count':  n_dropped,
        'degraded_count': n_degraded,
        'poor_count':     n_poor,
        'good_count':     n_good,
        'drop_rate_pct':  round(n_dropped / n_compared * 100, 1) if n_compared else 0.0,
        'corr_threshold': corr_threshold,
        'lines':          results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 콘솔 리포트 출력
# ─────────────────────────────────────────────────────────────────────────────

_SPEAKER_COLOR = {
    '박편육': '\033[96m',   # 청록
    '임채팅': '\033[93m',   # 노랑
    '김버그': '\033[92m',   # 초록
}
_RESET  = '\033[0m'
_RED    = '\033[91m'
_YELLOW = '\033[93m'
_DIM    = '\033[2m'


def _ts(sec: float) -> str:
    m = int(sec) // 60;  s = sec - m * 60
    return f"{m:02d}:{s:06.3f}"


def print_report(result: dict) -> None:
    bar = '─' * 72
    print(f"\n{bar}")
    print(f"【 대본 기반 문장 단위 음단절 분석 】")
    print(f"  정답지  : {result['ref']}")
    print(f"  녹음본  : {result['test']}")
    print(f"  오프셋  : {result['offset_sec']:+.3f}s")
    print(f"  비교    : {result['compared']}개 대사  "
          f"(정답지 구간 {result['total_segments']}, 대본 {result['total_script']}줄)")
    print(f"  임계값  : 상관계수 ≥{CORR_GOOD:.2f} 정상 / ≥{CORR_DEGRADED:.2f} 품질저하 / <{CORR_DEGRADED:.2f} 심각 / <{result['corr_threshold']:.2f}+무음 음단절 / frame-scan 스킵 ≥{CORR_SKIP_FRAME_SCAN:.2f}")
    print(bar)

    prev_speaker = ''
    for r in result['lines']:
        sp   = r['speaker']
        col  = _SPEAKER_COLOR.get(sp, '')
        # 화자 바뀔 때 구분선
        if sp != prev_speaker:
            print(f"\n  {col}[{sp}]{_RESET}")
            prev_speaker = sp

        _qg = r.get('quality_grade', '')
        if r['dropped'] or _qg == 'poor':
            status_str = _RED + r['status'] + _RESET
        elif _qg == 'degraded':
            status_str = _YELLOW + r['status'] + _RESET
        else:
            status_str = r['status']
        text_short = r['text'][:55] + ('…' if len(r['text']) > 55 else '')
        extra = ''
        if r.get('partial_drop'):
            extra = f"  (부분 무음 {r['partial_drop_ms']:.0f}ms)"
        print(
            f"  {status_str}  "
            f"정답지 {_ts(r['ref_start_s'])}~{_ts(r['ref_end_s'])}"
            f"  상관계수={r['max_corr']:+.3f}"
            f"  최적위치={_ts(r['test_best_s'])}"
            f"{extra}"
        )
        print(f"      {_DIM}\"{text_short}\"{_RESET}")

    print(f"\n{bar}")
    n = result['dropped_count']
    n_deg  = result.get('degraded_count', 0)
    n_poor = result.get('poor_count', 0)
    n_good = result.get('good_count', 0)
    total = result['compared']
    rate  = result['drop_rate_pct']

    # 품질 요약
    _issue_count = n + n_poor + n_deg
    if _issue_count == 0:
        print(f"  ✅ 전체 정상  ({total}개 대사, 평균 상관계수 "
              f"{sum(r['max_corr'] for r in result['lines'])/max(total,1):+.3f})")
    else:
        if n > 0:
            print(f"  ❌ 음단절 {n}/{total}개 대사  ({rate:.1f}%)")
        if n_poor > 0:
            print(f"  ❌ 심각한 품질저하 {n_poor}/{total}개 대사  "
                  f"(상관계수 <{CORR_DEGRADED:.2f})")
        if n_deg > 0:
            print(f"  ⚠️  품질저하 {n_deg}/{total}개 대사  "
                  f"(상관계수 {CORR_DEGRADED:.2f}~{CORR_GOOD:.2f})")
        if n_good > 0:
            print(f"  ✅ 정상 {n_good}/{total}개 대사")

    # 문제 대사 목록
    _problem_lines = [r for r in result['lines']
                      if r['dropped'] or r.get('quality_grade') in ('poor', 'degraded')]
    if _problem_lines:
        print(f"\n  문제 대사 목록:")
        for r in _problem_lines:
            col  = _SPEAKER_COLOR.get(r['speaker'], '')
            text_short = r['text'][:60] + ('…' if len(r['text']) > 60 else '')
            print(f"    [{r['line_idx']+1:2d}] {col}{r['speaker']}{_RESET} "
                  f"{_RED}{_ts(r['ref_start_s'])}{_RESET}  "
                  f"\"{text_short}\"")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# SCRIPT_REFERENCE 로드 (analyze_hybrid.py 에서 직접 임포트)
# ─────────────────────────────────────────────────────────────────────────────

def load_script_reference() -> str:
    """analyze_hybrid.py 의 SCRIPT_REFERENCE 변수를 가져옵니다."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import importlib, importlib.util
        spec = importlib.util.spec_from_file_location(
            'analyze_hybrid',
            Path(__file__).parent / 'analyze_hybrid.py'
        )
        mod = importlib.util.module_from_spec(spec)
        # SCRIPT_REFERENCE 만 읽기 위해 exec_module 대신 파일 직접 파싱
        src = (Path(__file__).parent / 'analyze_hybrid.py').read_text(encoding='utf-8')
        m   = re.search(r'SCRIPT_REFERENCE\s*=\s*"""(.*?)"""', src, re.DOTALL)
        if m:
            return m.group(1)
    except Exception as e:
        print(f"⚠️  SCRIPT_REFERENCE 로드 실패: {e}", file=sys.stderr)
    return ''


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description='대본 기반 문장 단위 음단절 감지 (Android LINE IN 녹음용)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument('--ref',  required=True,
                    help='정답지(원음) WAV')
    ap.add_argument('--test', required=True,
                    help='Android 녹음본 WAV')
    ap.add_argument('--output', default=None,
                    help='결과 JSON 저장 경로')
    ap.add_argument('--ref-min-db',      type=float, default=REF_MIN_DB,
                    help=f'발화 판정 기준 dB (기본 {REF_MIN_DB})')
    ap.add_argument('--silence-gap-ms',  type=float, default=SILENCE_GAP_MS,
                    help=f'발화 분절 묵음 길이 ms (기본 {SILENCE_GAP_MS})')
    ap.add_argument('--min-seg-ms',      type=float, default=MIN_SEG_MS,
                    help=f'발화 최소 길이 ms (기본 {MIN_SEG_MS})')
    ap.add_argument('--corr-threshold',  type=float, default=CORR_THRESHOLD,
                    help=f'음단절 임계 상관계수 (기본 {CORR_THRESHOLD})')
    ap.add_argument('--search-sec',      type=float, default=SEARCH_SEC,
                    help=f'구간 탐색 창 ±초 (기본 {SEARCH_SEC})')
    ap.add_argument('--frame-ms',        type=int,   default=FRAME_MS,
                    help=f'에너지 프레임 ms (기본 {FRAME_MS})')
    return ap


def main() -> None:
    args   = _build_parser().parse_args()
    script = load_script_reference()
    if not script:
        print("❌ SCRIPT_REFERENCE 를 불러오지 못했습니다.", file=sys.stderr)
        sys.exit(2)

    result = analyze_by_script(
        ref_path       = args.ref,
        test_path      = args.test,
        script_text    = script,
        frame_ms       = args.frame_ms,
        ref_min_db     = args.ref_min_db,
        silence_gap_ms = args.silence_gap_ms,
        min_seg_ms     = args.min_seg_ms,
        corr_threshold = args.corr_threshold,
        search_sec     = args.search_sec,
    )

    print_report(result)

    if args.output:
        out = Path(args.output)
        out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        print(f"💾 JSON 저장: {out}")

    sys.exit(1 if result['dropped_count'] > 0 else 0)


if __name__ == '__main__':
    main()
