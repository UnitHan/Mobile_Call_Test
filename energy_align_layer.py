#!/usr/bin/env python3
"""
energy_align_layer.py — AI-free 순수 에너지 기반 음단절 탐지
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
전략 (Whisper·API 완전 제외):
  1. 정답지(ref) 음원에서 한국어 음절 onset 탐지 (librosa)
  2. 대본의 한글 글자를 onset에 1:1 배정 → 글자별 (start_ms, end_ms)
  3. DTW(MFCC)로 수신 음원을 정답지 타임라인에 정렬
  4. 각 글자 위치의 수신 에너지 점수 계산
     score = RMS(수신, DTW정렬위치) / RMS(정답지, 글자위치)
  5. score < ENERGY_SCORE_TH → 음단절
  6. 연속 dropout 글자를 DropoutSegment로 그루핑

Whisper 방식과 비교:
  - Whisper는 수신 음원을 '보정 전사'해 오탐 발생 가능
  - 이 방식은 언어모델 없음 → 물리적 신호만 비교 → 오탐 ↓
  - 단, 정답지 음원이 있을 때만 동작 (ref_y necessary)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import re
import numpy as np
import librosa

from audio_lib.consts import SR  # 16000 — 전파일 통일 (이전: SR = 16_000)

# ── 파라미터 ─────────────────────────────────────────────────
ONSET_DELTA         = 0.04    # onset 감도 (낮을수록 많이 탐지) — 0.07→0.04 (한국어 TTS 음절급 감도)
ONSET_WAIT_SEC      = 0.045   # 최소 onset 간격(초) — 한국어 1음절 ≈ 45~80ms
CHAR_WINDOW_MS      = 90      # 글자 에너지 측정 창(ms): ±45ms
ENERGY_SCORE_TH     = 0.05    # 수신/정답지 RMS 비율 < 이 값 → 음단절 (VoIP 에너지 감소≠음단절: 0.25→0.05)
IOS_SPEECH_MIN      = 0.008   # iOS(기준)가 발화 중으로 판단하는 최소 RMS — 미달 구간은 비교 제외
AND_SILENCE_MAX     = 0.004   # Android가 진짜 묵음인 최대 RMS (이 이하 = 신호 없음)
MIN_DROPOUT_MS      = 80      # 최소 음단절 길이(ms): 음절 단위 허용
MERGE_GAP_MS        = 300     # 인접 dropout 그루핑 최대 간격(ms)
MAX_CHAR_DURATION_MS= 250     # 1음절 최대 지속시간(ms) — 단어/문장 경계 pause가 window에 포함되지 않도록
DTW_HOP             = 512     # DTW MFCC hop 크기 (32ms @ 16kHz) — 256→512: O(n²)이므로 4배 빠름, 음단절 탐지 정확도 영향 미미
DTW_N_MFCC          = 13      # MFCC 차원 수
DTW_CHUNK_SEC       = 30      # 청크 길이(초) — 60→30: 각 청크 DTW 행렬 크기↓, 빠름
DTW_CHUNK_OVERLAP_S = 3       # 청크 간 오버랩(초)


# ═══════════════════════════════════════════════════════════
# 데이터 구조 (whisper_layer 의존성 없이 자체 정의)
# ═══════════════════════════════════════════════════════════

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class DropoutSegment:
    start_ms:       int   = 0
    end_ms:         int   = 0
    duration_ms:    int   = 0
    missing_text:   str   = ''
    dropout_in:     str   = '수신만'
    energy_ratio:   float = 0.0
    confirmed:      bool  = True
    confidence:     str   = 'medium'
    script_context: str   = ''

@dataclass
class WhisperResult:
    """EnergyAlign 결과를 감싸는 Gemini 호환 래퍼."""
    local_words:     list = field(default_factory=list)
    remote_words:    list = field(default_factory=list)
    local_text:      str  = ''
    remote_text:     str  = ''
    dropouts:        list = field(default_factory=list)  # list[DropoutSegment]
    local_first_ms:  int  = 0
    remote_first_ms: int  = 0
    error:           Optional[str] = None


# ═══════════════════════════════════════════════════════════
# 유틸
# ═══════════════════════════════════════════════════════════

def parse_script_chars(script: str) -> list[str]:
    """
    대본에서 한글 음절(글자)만 순서대로 추출.
    화자 태그([...], 【...】), 섹션 헤더, 주석(←), 구분선 제거 후 추출.
    한글 1자 = 1음절 기준.
    """
    text = re.sub(r'【.*?】', '', script)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'={2,}.*?={2,}', '', text)
    text = re.sub(r'←.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*-{3,}.*$', '', text, flags=re.MULTILINE)
    return re.findall(r'[\uAC00-\uD7A3]', text)


def parse_script_syllable_words(script: str) -> list[str]:
    """
    대본에서 단어(어절) 단위 한글 토큰 추출.
    음단절 텍스트 설명에 단어 단위로 사용.
    """
    text = re.sub(r'【.*?】|\[.*?\]|={2,}.*?={2,}', '', script)
    text = re.sub(r'←.*$', '', text, flags=re.MULTILINE)
    return re.findall(r'[\uAC00-\uD7A3a-zA-Z0-9]+', text)


def detect_onsets_in_ref(y: np.ndarray) -> np.ndarray:
    """
    정답지 음원에서 한국어 음절 onset 탐지.
    backtrack=True: onset을 에너지 상승점 직전으로 당겨 정확도 향상.
    반환: onset 시작 시각(초) 배열.
    """
    hop = int(SR * 0.008)   # 8ms hop — 음절 수준 해상도
    wait_frames = max(1, int(ONSET_WAIT_SEC * SR / hop))
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=SR, hop_length=hop,
        delta=ONSET_DELTA,
        wait=wait_frames,
        backtrack=True,
    )
    return librosa.frames_to_time(onset_frames, sr=SR, hop_length=hop)


def assign_chars_to_onsets(
    chars:     list[str],
    onsets:    np.ndarray,
    total_sec: float,
) -> list[dict]:
    """
    대본 글자를 onset에 배정.

    글자들을 onset 타임라인 위에 균등 보간(np.interp)으로 분산.
    - n_o >= n_c: onset에서 n_c개 균등 서브샘플 (기존과 동일)
    - n_o <  n_c: 부족한 onset을 선형 보간으로 채움
               → 일부 글자는 onset 사이 보간 위치에 배정됨 (반드시 발화 구간 보장 안됨)
               → score_chars의 ref_rms 체크가 침묵 구간 오측정 방지
    - onset == 0: 전체 음원을 글자 수로 균등 분할

    end_ms는 MAX_CHAR_DURATION_MS로 cap:
    → 단어/문장 경계 pause가 글자 window에 포함되지 않음
    → group_dropouts의 gap 계산이 자연 pause를 올바르게 분리함

    반환: [{'char', 'start_ms', 'end_ms'}, ...]
    """
    n_c = len(chars)
    n_o = len(onsets)
    total_ms = total_sec * 1000

    if n_o == 0:
        dur = total_ms / max(n_c, 1)
        return [
            {'char': ch, 'start_ms': int(i * dur), 'end_ms': int((i + 1) * dur)}
            for i, ch in enumerate(chars)
        ]

    # 글자 위치를 onset 타임라인에 균등 보간
    # linspace(0, n_o-1, n_c) → n_c개의 float 인덱스 → onsets에서 시각(초) 보간
    float_indices = np.linspace(0, n_o - 1, n_c)
    times = np.interp(float_indices, np.arange(n_o), onsets)  # float 초

    result: list[dict] = []
    for i, (ch, st) in enumerate(zip(chars, times)):
        et = float(times[i + 1]) if i + 1 < n_c else total_sec
        # end_ms cap: 단어/문장 경계 묵음이 글자 window에 들어오지 않도록
        end_capped = min(int(et * 1000), int(st * 1000) + MAX_CHAR_DURATION_MS)
        result.append({
            'char':     ch,
            'start_ms': int(st * 1000),
            'end_ms':   end_capped,
        })

    return result


def _rms_at(y: np.ndarray, center_ms: int, window_ms: int = CHAR_WINDOW_MS) -> float:
    """특정 ms 중심의 ±window/2 창에서 RMS 계산"""
    half = window_ms // 2
    s = max(0, int((center_ms - half) / 1000 * SR))
    e = min(len(y), int((center_ms + half) / 1000 * SR))
    if e <= s:
        return 0.0
    return float(np.sqrt(np.mean(y[s:e] ** 2) + 1e-12))


# ═══════════════════════════════════════════════════════════
# DTW 정렬
# ═══════════════════════════════════════════════════════════

def _build_mfcc(y: np.ndarray) -> np.ndarray:
    """MFCC 추출 (shape: n_mfcc × n_frames)"""
    return librosa.feature.mfcc(
        y=y.astype(np.float32),
        sr=SR,
        n_mfcc=DTW_N_MFCC,
        hop_length=DTW_HOP,
    )


def dtw_build_mapping(ref_y: np.ndarray, recv_y: np.ndarray) -> np.ndarray:
    """
    MFCC DTW로 ref ↔ recv 프레임 정렬 경로 구성.

    긴 음원 (>= DTW_CHUNK_SEC)은 오버랩 청크로 분할하여 메모리 절약.
    반환: shape (N, 2) — [[ref_frame, recv_frame], ...] 오름차순
    """
    total_ref_frames  = int(len(ref_y)  / DTW_HOP) + 1
    total_recv_frames = int(len(recv_y) / DTW_HOP) + 1
    chunk_samples     = int(DTW_CHUNK_SEC * SR)
    overlap_samples   = int(DTW_CHUNK_OVERLAP_S * SR)

    # 짧으면 전체 DTW
    if len(ref_y) <= chunk_samples:
        ref_mfcc  = _build_mfcc(ref_y)
        recv_mfcc = _build_mfcc(recv_y)
        _, wp = librosa.sequence.dtw(ref_mfcc, recv_mfcc, metric='euclidean')
        return wp[::-1].copy()

    # ── 청크 분할 DTW ────────────────────────────────────────
    global_wp: list[list[int]] = []
    ref_offset  = 0
    recv_offset = 0   # 누적 오프셋 추적 (이전 청크 end → 다음 청크 start 근사)

    while ref_offset < len(ref_y):
        ref_end  = min(ref_offset + chunk_samples, len(ref_y))
        # recv는 ref보다 1.5배 길이까지 탐색 (VoIP 지연 대응)
        recv_search_end = min(recv_offset + int(chunk_samples * 1.5), len(recv_y))

        ref_chunk  = ref_y[ref_offset:ref_end]
        recv_chunk = recv_y[recv_offset:recv_search_end]

        if len(ref_chunk) < 2048 or len(recv_chunk) < 2048:
            break

        ref_mfcc  = _build_mfcc(ref_chunk)
        recv_mfcc = _build_mfcc(recv_chunk)
        _, wp_local = librosa.sequence.dtw(ref_mfcc, recv_mfcc, metric='euclidean')
        wp_local    = wp_local[::-1]   # 오름차순

        # 글로벌 프레임 인덱스로 변환
        ref_frame_offset  = ref_offset  // DTW_HOP
        recv_frame_offset = recv_offset // DTW_HOP
        for r, c in wp_local:
            global_wp.append([r + ref_frame_offset, c + recv_frame_offset])

        # 다음 청크 시작: 오버랩 고려
        # recv 다음 시작점: 이 청크 마지막 recv 프레임 위치 (오버랩 제외)
        last_recv_local_frame = int(wp_local[-1][1])
        last_recv_global_ms   = (last_recv_local_frame + recv_frame_offset) * DTW_HOP / SR * 1000
        recv_offset = max(recv_offset + 1,
                          int(last_recv_global_ms / 1000 * SR) - overlap_samples)
        recv_offset = min(recv_offset, len(recv_y) - 512)

        ref_offset = ref_end - overlap_samples
        if ref_offset >= len(ref_y):
            break

    if not global_wp:
        # fallback: 1:1 매핑
        n = max(total_ref_frames, total_recv_frames)
        return np.array([[i, i] for i in range(n)], dtype=np.int32)

    return np.array(global_wp, dtype=np.int32)


def ref_ms_to_recv_ms(wp: np.ndarray, ref_ms: int) -> int:
    """DTW warp path로 ref 시각(ms) → recv 시각(ms) 변환"""
    ref_frame = int(ref_ms / 1000 * SR / DTW_HOP)
    diffs = np.abs(wp[:, 0] - ref_frame)
    idx = int(np.argmin(diffs))
    recv_frame = int(wp[idx, 1])
    return int(recv_frame * DTW_HOP / SR * 1000)


# ═══════════════════════════════════════════════════════════
# 글자별 점수화 & 그루핑
# ═══════════════════════════════════════════════════════════

def score_chars(
    char_segs: list[dict],
    ref_y:     np.ndarray,
    recv_y:    np.ndarray,
    wp:        np.ndarray,
) -> list[dict]:
    """
    각 글자의 에너지 점수 계산.
    score = RMS(recv, DTW매핑된 위치) / RMS(ref, 글자 중심)

    반환: [{char, start_ms, end_ms, recv_center_ms, ref_rms, recv_rms, score, dropout}, ...]
    """
    results = []
    for seg in char_segs:
        # center_ms: onset 직후에서 측정 (단어/문장 경계 묵음이 center에 들어오지 않도록)
        # midpoint=(start+end)//2 를 쓰면 inter-word pause 구간에서 오측정 발생
        center_ms      = seg['start_ms'] + CHAR_WINDOW_MS // 2
        recv_center_ms = ref_ms_to_recv_ms(wp, center_ms)

        ref_rms  = _rms_at(ref_y,  center_ms,      CHAR_WINDOW_MS)
        recv_rms = _rms_at(recv_y, recv_center_ms, CHAR_WINDOW_MS)

        # iOS(기준)가 발화 중이 아니면 비교 불가 → 중립 처리
        if ref_rms < IOS_SPEECH_MIN:
            score   = 1.0
            dropout = False
        else:
            score = recv_rms / (ref_rms + 1e-9)
            # 진짜 음단절 = Android가 절대적 묵음이거나 iOS의 5% 미만
            # VoIP 에너지 감소(60~80%)는 정상 — 비율만으로 판단하지 않음
            dropout = (recv_rms < AND_SILENCE_MAX) or (score < ENERGY_SCORE_TH)

        results.append({
            'char':          seg['char'],
            'start_ms':      seg['start_ms'],
            'end_ms':        seg['end_ms'],
            'recv_center_ms': recv_center_ms,
            'ref_rms':       round(ref_rms,  6),
            'recv_rms':      round(recv_rms, 6),
            'score':         round(score,    3),
            'dropout':       dropout,
        })
    return results


def group_dropouts(scored: list[dict]) -> list[dict]:
    """
    연속 dropout 글자 → 음단절 구간 그루핑.
    인접 글자 간격 > MERGE_GAP_MS 이면 별도 구간으로 분리.
    MIN_DROPOUT_MS 미만 구간은 제거.
    """
    dropouts: list[dict] = []
    i = 0
    while i < len(scored):
        if not scored[i]['dropout']:
            i += 1
            continue

        group = [scored[i]]
        j = i + 1
        while j < len(scored):
            gap = scored[j]['start_ms'] - scored[j - 1]['end_ms']
            if scored[j]['dropout'] and gap <= MERGE_GAP_MS:
                group.append(scored[j])
                j += 1
            else:
                break

        dur = group[-1]['end_ms'] - group[0]['start_ms']
        if dur >= MIN_DROPOUT_MS:
            min_score = min(g['score'] for g in group)
            text      = ''.join(g['char'] for g in group)

            if min_score < 0.10 or dur >= 500:
                conf = 'high'
            elif min_score < ENERGY_SCORE_TH:
                conf = 'medium'
            else:
                conf = 'low'

            dropouts.append({
                'start_ms':    group[0]['start_ms'],
                'end_ms':      group[-1]['end_ms'],
                'duration_ms': dur,
                'missing_text': text,
                'min_score':   round(min_score, 3),
                'confidence':  conf,
                'dropout_in':  '수신만',
                'energy_ratio': round(min_score, 3),
                'confirmed':   True,
                'source':      'energy_align',
                'char_scores': [round(g['score'], 3) for g in group],
            })
        i = j

    return dropouts


# ═══════════════════════════════════════════════════════════
# 공개 API
# ═══════════════════════════════════════════════════════════

class EnergyAlignDetector:
    """
    정답지 음원 + 대본 기반 순수 에너지 음단절 탐지기.
    Whisper 없음 — librosa onset detection + DTW + RMS 비교만 사용.

    사용:
      detector = EnergyAlignDetector()
      result   = detector.detect(recv_y=android_y, ref_y=ref_y, script=script)
    """

    def detect(
        self,
        recv_y: np.ndarray,    # 수신 음원 (Android 녹음)
        ref_y:  np.ndarray,    # 정답지 음원 (clean reference)
        script: str,           # 대본 원문
    ) -> dict:
        """
        반환 dict:
          dropouts    : list[dict]  — 확정 음단절 구간 목록
          scored      : list[dict]  — 글자별 점수 전체 목록
          char_count  : int         — 대본 글자 수
          onset_count : int         — 정답지 onset 탐지 수
          error       : str | None
        """
        try:
            # ① 대본 글자 추출
            chars = parse_script_chars(script)
            if not chars:
                return _err('대본에서 한글 글자를 찾을 수 없습니다')
            print(f"  [EnergyAlign] 대본 한글 글자: {len(chars)}자")

            # ② 정답지 음절 onset 탐지
            onsets = detect_onsets_in_ref(ref_y)
            total_sec = len(ref_y) / SR
            print(f"  [EnergyAlign] 정답지 onset 탐지: {len(onsets)}개 "
                  f"(글자 {len(chars)}자 / 길이 {total_sec:.1f}초)")

            # ③ 글자 → onset 배정
            char_segs = assign_chars_to_onsets(chars, onsets, total_sec)

            # ④ DTW 정렬 (수신 → 정답지)
            print("  [EnergyAlign] MFCC DTW 정렬 중...")
            wp = dtw_build_mapping(ref_y, recv_y)
            print(f"  [EnergyAlign] DTW 완료 — 경로 {len(wp)}포인트")

            # ⑤ 글자별 에너지 점수
            scored  = score_chars(char_segs, ref_y, recv_y, wp)
            n_drop  = sum(1 for s in scored if s['dropout'])
            avg_sc  = float(np.mean([s['score'] for s in scored]))
            print(f"  [EnergyAlign] 글자 점수 완료 — "
                  f"dropout {n_drop}/{len(scored)}자 / avg score={avg_sc:.3f}")

            # ⑥ 구간 그루핑
            dropouts = group_dropouts(scored)
            print(f"  [EnergyAlign] 음단절 구간: {len(dropouts)}건")
            for d in dropouts[:5]:
                from_s = d['start_ms'] / 1000
                print(f"    {from_s:.1f}s  {d['duration_ms']}ms  "
                      f"score={d['min_score']}  [{d['confidence']}]  \"{d['missing_text'][:20]}\"")

            return {
                'dropouts':    dropouts,
                'scored':      scored,
                'char_count':  len(chars),
                'onset_count': int(len(onsets)),
                'error':       None,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return _err(str(e))


def _err(msg: str) -> dict:
    return {'dropouts': [], 'scored': [], 'char_count': 0, 'onset_count': 0, 'error': msg}


# ═══════════════════════════════════════════════════════════
# 결과 → DropoutSegment 변환 (whisper_layer 호환)
# ═══════════════════════════════════════════════════════════

def to_dropout_segments(result: dict):
    """
    EnergyAlignDetector 결과를 DropoutSegment 리스트로 변환.
    analyze_hybrid.py의 기존 HTML 렌더링 코드와 호환.
    """
    out = []
    for d in result.get('dropouts', []):
        out.append(DropoutSegment(
            start_ms      = d['start_ms'],
            end_ms        = d['end_ms'],
            duration_ms   = d['duration_ms'],
            missing_text  = d['missing_text'],
            dropout_in    = '수신만',
            energy_ratio  = d['energy_ratio'],
            confirmed     = True,
            confidence    = d['confidence'],
            script_context= d['missing_text'],
        ))
    return out
