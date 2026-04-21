"""
audio_plots.py
─────────────────────────────────────────────────────────────────────────────
파형/RMS 시각화, 음단절 클립 생성, 에너지 힌트 분석.

analyze_hybrid.py 에서 분리된 모듈.
"""
from __future__ import annotations

import base64
import io
import wave

import librosa
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as _fm
import numpy as np

# ── 한글 폰트 자동 설정 (macOS: Apple SD Gothic Neo, 범용: AppleGothic)
_KO_FONTS = ['Apple SD Gothic Neo', 'AppleGothic', 'NanumGothic', 'Malgun Gothic']
for _f in _KO_FONTS:
    try:
        _fm.findfont(_fm.FontProperties(family=_f), fallback_to_default=False)
        matplotlib.rcParams['font.family'] = _f
        break
    except Exception:
        pass
matplotlib.rcParams['axes.unicode_minus'] = False

from audio_lib.consts import SR, RMS_HOP
from audio_lib.dsp import compute_rms
from audio_lib.io import fig_to_b64
from _hybrid_config import MAX_CLIP_SEC


# ─────────────────────────────────────────────────────────────────────────────
# WAV 바이트 / 오디오 클립
# ─────────────────────────────────────────────────────────────────────────────

def to_wav_bytes(y: np.ndarray, clip_sec: float | None = None) -> bytes:
    """numpy float32 배열 → WAV bytes. clip_sec 지정 시 앞부분만."""
    if clip_sec:
        y = y[:int(clip_sec * SR)]
    pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def dropout_clip_b64(y: np.ndarray, start_ms: int, end_ms: int,
                     pad_ms: int = 2000) -> str:
    """드롭아웃 구간 ±pad_ms 클립을 base64 WAV 문자열로 반환."""
    s = max(0, int((start_ms - pad_ms) * SR / 1000))
    e = min(len(y), int((end_ms   + pad_ms) * SR / 1000))
    clip = y[s:e] if e > s else y[:int(0.1 * SR)]
    return base64.b64encode(to_wav_bytes(clip)).decode()


def ms_label(ms: float) -> str:
    """밀리초 → 'MM:SS.ss' 형식 문자열."""
    s = ms / 1000
    return f"{int(s//60):02d}:{s%60:05.2f}"


def wall_time(start_hms: str, offset_ms: float) -> str:
    """start_hms('HH:MM:SS') + offset_ms → 추정 발생시각 문자열."""
    if not start_hms:
        return "—"
    try:
        h, m, s = map(int, start_hms.split(":"))
        total_sec = h * 3600 + m * 60 + s + offset_ms / 1000
        th = int(total_sec // 3600)
        tm = int((total_sec % 3600) // 60)
        ts = total_sec % 60
        return f"{th:02d}:{tm:02d}:{ts:05.2f}"
    except Exception:
        return "—"


# ─────────────────────────────────────────────────────────────────────────────
# 에너지 힌트
# ─────────────────────────────────────────────────────────────────────────────

def compute_signal_hints(ref_y: np.ndarray, and_y: np.ndarray,
                         window_sec: float = 1.0,
                         offset_sec: float = 0.0) -> list[tuple]:
    """정답지 타임라인 기준으로 두 신호를 window 단위 비교.

    offset_sec: 양수 = Android 가 정답지보다 늦게 시작 (script_gap_detector 오프셋).
    반환: [(start_sec, end_sec, ref_rms, and_rms, ratio)]
    """
    step = int(window_sec * SR)
    offset_samples = int(offset_sec * SR)
    ref_len = len(ref_y)
    hints = []
    for i in range(0, ref_len - step, step // 2):
        r_chunk = ref_y[i:i + step]
        # Android 에서 대응 위치: ref 시간 i/SR → Android 시간 (i/SR - offset_sec)
        a_start = i - offset_samples
        a_end   = a_start + step
        if a_start < 0 or a_end > len(and_y):
            # 대응 구간 없음 → ratio=0
            a_chunk = np.zeros(step, dtype=np.float32)
        else:
            a_chunk = and_y[a_start:a_end]
        ref_r = float(np.sqrt(np.mean(r_chunk**2)))
        and_r = float(np.sqrt(np.mean(a_chunk**2)))
        ratio = and_r / (ref_r + 1e-9)
        hints.append((i / SR, (i + step) / SR, ref_r, and_r, ratio))
    return hints


def top_suspicious_windows(hints: list[tuple], top_n: int = 15,
                            ios_min_rms: float = 0.002) -> list[tuple]:
    """iOS 신호 있고 Android 에너지 비율 낮은 구간 상위 N개."""
    active = [(s, e, ir, ar, r) for s, e, ir, ar, r in hints if ir > ios_min_rms]
    return sorted(active, key=lambda x: x[4])[:top_n]


# ─────────────────────────────────────────────────────────────────────────────
# 마커 목록 생성
# ─────────────────────────────────────────────────────────────────────────────

def build_marker_list(result: dict) -> list[tuple]:
    """Gemini 결과에서 드롭아웃 마커 → [(start_ms, end_ms, label, type)]."""
    markers = []
    init = result.get("initial_dropout", {})
    if init.get("detected") and init.get("first_audible_in_ios_ms") is not None:
        s = 0
        e = init.get("duration_ms", 500)
        label = f"초기 음단절\n{init.get('cut_content','?')}\n{e:.0f}ms"
        markers.append((s, e, label, "initial"))

    for d in result.get("mid_call_dropouts", []):
        s   = d.get("timestamp_ref_ms", d.get("timestamp_ios_ms", 0))
        dur = d.get("duration_ms", 100)
        conf = d.get("confidence", "low")
        loc_c = d.get("local_actual", d.get("ios_content", "?"))
        label = f"{loc_c}\n{dur:.0f}ms [{conf}]"
        markers.append((s, s + dur, label, conf))

    return markers


# ─────────────────────────────────────────────────────────────────────────────
# 파형 비교 그래프
# ─────────────────────────────────────────────────────────────────────────────

def plot_comparison(call_label: str, ios_y: np.ndarray, and_y: np.ndarray,
                    ios_rms: np.ndarray, and_rms: np.ndarray,
                    markers: list, suspicious_hints: list,
                    ref_y: np.ndarray | None = None,
                    offset_sec: float = 0.0,
                    dropout_lines: list | None = None,
                    ios_markers: list | None = None,
                    ios_offset_sec: float = 0.0) -> str:
    """정답지(ref) 타임라인 기준 파형 비교 → base64 PNG.

    ref_y 가 주어지면 정답지 파형을 기준(상단)으로 사용하고,
    Android 파형을 offset_sec 만큼, iOS 파형을 ios_offset_sec 만큼
    이동해 정답지 타임라인에 정렬합니다.
    dropout_lines: script_gap_detector 결과의 lines (대사별 상관계수).
    """
    # ── 기준 오디오 선택: ref_y 있으면 정답지, 없으면 iOS ──────────────
    if ref_y is not None and len(ref_y) > 0:
        base_y    = ref_y
        base_rms  = compute_rms(ref_y)
        base_name = "정답지 음원 (TTS Ground Truth)"
        rms_name  = "정답지 RMS"
    else:
        base_y    = ios_y
        base_rms  = ios_rms
        base_name = "iPhone 로컬 녹음 (기준 · iOS ixi-O 발화)"
        rms_name  = "iOS RMS"

    # ── 정답지 타임라인 기준 클리핑 ────────────────────────────────────
    base_dur = len(base_y) / SR
    clip_dur = base_dur if MAX_CLIP_SEC is None else min(base_dur, MAX_CLIP_SEC)

    t_base = np.linspace(0, base_dur, len(base_y))
    # Android: offset 적용 (정답지 타임라인에 맞춤)
    t_and  = np.linspace(offset_sec, offset_sec + len(and_y) / SR, len(and_y))
    # iOS 파형 시간축 (offset 적용 — 정답지 타임라인 정렬)
    ios_dur = len(ios_y) / SR
    t_ios  = np.linspace(ios_offset_sec, ios_offset_sec + ios_dur, len(ios_y))
    ios_rms_arr = compute_rms(ios_y) if len(ios_y) > 0 else np.zeros(0, dtype=np.float32)
    t_ri   = librosa.frames_to_time(np.arange(len(ios_rms_arr)), sr=SR, hop_length=RMS_HOP) + ios_offset_sec
    t_rb   = librosa.frames_to_time(np.arange(len(base_rms)), sr=SR, hop_length=RMS_HOP)
    t_ra   = librosa.frames_to_time(np.arange(len(and_rms)),  sr=SR, hop_length=RMS_HOP) + offset_sec

    fig, axes = plt.subplots(5, 1, figsize=(20, 17), sharex=True)
    fig.suptitle(
        f"{call_label} — 정답지 기준 파형 정렬 (offset {offset_sec:+.3f}s)  ·  "
        f"파랑=정답지 / 초록=iOS / 주황=Android / 빨강=음단절 구간",
        fontsize=11, fontweight='bold',
    )

    def _mark_with(ax: plt.Axes, m_list: list, ymin: float, ymax: float) -> None:
        for s_ms, e_ms, label, mtype in m_list:
            s, e = s_ms / 1000, e_ms / 1000
            if s > clip_dur:
                continue
            color = {'initial': 'orange', 'high': '#ff4444',
                     'medium': '#ffaa00', 'low': '#88ccff',
                     'red': '#ff4444'}.get(mtype, '#ff4444')
            ax.axvspan(s, min(e, clip_dur), color=color, alpha=0.30)
            ax.annotate(label, xy=((s + min(e, clip_dur)) / 2, ymax * 0.88),
                        fontsize=6.5, color=color, ha='center', va='top',
                        fontweight='bold',
                        bbox=dict(boxstyle='round,pad=0.2', fc='#0f1520',
                                  ec=color, alpha=0.8))

    def _mark(ax: plt.Axes, ymin: float, ymax: float) -> None:
        _mark_with(ax, markers, ymin, ymax)

    def _draw_seg_boundaries(ax: plt.Axes) -> None:
        """대본 대사 구간 경계선 + 상관계수 표시."""
        if not dropout_lines:
            return
        for ln in dropout_lines:
            s = ln['ref_start_s']
            e = ln['ref_end_s']
            if s > clip_dur:
                continue
            corr = ln['max_corr']
            # 경계선
            ax.axvline(s, color='#666', lw=0.4, ls=':', alpha=0.5)
            # 상관계수 라벨 (등급별 색상)
            _qg = ln.get('quality_grade', '')
            if ln['dropped'] or _qg == 'poor':
                c = '#ff4444'   # 빨강: 음단절/심각
            elif _qg == 'degraded':
                c = '#ffaa00'   # 주황: 품질저하
            else:
                c = '#44cc44'   # 초록: 정상
            mid = (s + min(e, clip_dur)) / 2
            ax.text(mid, ax.get_ylim()[1] * 0.02,
                    f"{corr:.2f}", fontsize=5.5, ha='center', va='bottom',
                    color=c, alpha=0.8)

    # ── [1] 정답지(또는 iOS) 파형 ─────────────────────────────────────
    ax = axes[0]
    ax.plot(t_base, base_y, color='#5b9bd5', lw=0.25, alpha=0.8)
    ax.set_title(base_name, fontsize=10)
    ax.set_ylabel("Amplitude")
    ax.set_xlim(0, clip_dur)
    _mark(ax, float(base_y.min()), float(base_y.max()))
    _draw_seg_boundaries(ax)

    # ── [2] iOS 녹음 파형 ──────────────────────────────────────────────
    ax = axes[1]
    if len(ios_y) > 0:
        ax.plot(t_ios, ios_y, color='#50c878', lw=0.25, alpha=0.8)
    _ios_off_lbl = f"offset {ios_offset_sec:+.3f}s" if ios_offset_sec else "x=0"
    ax.set_title(f"iOS 녹음 (발신측 · iPhone ({_ios_off_lbl}))", fontsize=10)
    ax.set_ylabel("Amplitude")
    ax.set_xlim(0, clip_dur)
    _ios_m = ios_markers if ios_markers is not None else []
    _mark_with(ax, _ios_m, float(ios_y.min()) if len(ios_y) else -1, float(ios_y.max()) if len(ios_y) else 1)
    _draw_seg_boundaries(ax)

    # ── [3] Android 파형 (offset 정렬) ────────────────────────────────
    ax = axes[2]
    ax.plot(t_and, and_y, color='#e07b39', lw=0.25, alpha=0.8)
    ax.set_title(f"Android 녹음 — 정답지 타임라인 정렬 (offset {offset_sec:+.3f}s)", fontsize=10)
    ax.set_ylabel("Amplitude")
    ax.set_xlim(0, clip_dur)
    _mark(ax, float(and_y.min()), float(and_y.max()))
    _draw_seg_boundaries(ax)

    # ── [4] RMS 에너지 오버레이 ───────────────────────────────────────
    ax = axes[3]
    ax.plot(t_rb, base_rms, color='#5b9bd5', lw=0.7, alpha=0.85, label=rms_name)
    if len(ios_rms_arr) > 0:
        ax.plot(t_ri, ios_rms_arr, color='#50c878', lw=0.7, alpha=0.7, label='iOS RMS')
    ax.plot(t_ra, and_rms,  color='#e07b39', lw=0.7, alpha=0.85, label='Android RMS')
    ax.set_title(f"에너지 비교 ({rms_name} vs iOS vs Android — 정답지 타임라인)", fontsize=10)
    ax.set_ylabel("RMS")
    ax.set_xlim(0, clip_dur)
    ax.legend(fontsize=8, loc='upper right')
    rms_max = max(float(base_rms.max()) if len(base_rms) else 1.0,
                  float(and_rms.max())  if len(and_rms)  else 1.0,
                  float(ios_rms_arr.max()) if len(ios_rms_arr) else 0.0)
    _mark(ax, 0, rms_max)

    # ── [5] 에너지 비율 ───────────────────────────────────────────────
    ax = axes[4]
    all_hints_sorted = sorted([(s, r) for s, e, ir, ar, r in suspicious_hints],
                               key=lambda x: x[0])
    if all_hints_sorted:
        ax.plot([x[0] for x in all_hints_sorted],
                [x[1] for x in all_hints_sorted],
                color='#aaa', lw=0.6, alpha=0.5)
    for s, e, ir, ar, r in suspicious_hints:
        color = '#ff4444' if r < 0.2 else '#ffaa00' if r < 0.4 else '#88ccff'
        ax.bar(s, r, width=(e - s) * 0.9, color=color, alpha=0.6, align='edge')
    ax.axhline(0.3, color='red', ls='--', lw=1, label='음단절 임계 (30%)')
    ax.set_title("Android/정답지 에너지 비율 (낮을수록 음단절 의심 구간 — 정답지 타임라인)", fontsize=10)
    ax.set_xlabel(f"Time (s) — 정답지 기준 0~{clip_dur:.0f}초")
    ax.set_ylabel("Ratio")
    ax.set_xlim(0, clip_dur)
    ax.set_ylim(0, 1.5)
    ax.legend(fontsize=8)
    _mark(ax, 0, 1.5)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    return fig_to_b64(fig)


def plot_per_platform(call_label: str,
                      ref_y: np.ndarray, rec_y: np.ndarray,
                      ref_name: str, rec_name: str,
                      platform: str,
                      offset_sec: float = 0.0,
                      dropout_lines: list | None = None,
                      markers: list | None = None) -> str:
    """단일 플랫폼(Android 또는 iOS) 비교 그래프 → base64 PNG.

    3패널: [1] 정답지 파형  [2] 녹음 파형  [3] RMS 에너지 오버레이
    """
    if len(ref_y) == 0 and len(rec_y) == 0:
        fig, ax = plt.subplots(1, 1, figsize=(10, 3))
        ax.text(0.5, 0.5, f'{platform} — 음원 없음', ha='center', va='center',
                fontsize=14, color='#aaa', transform=ax.transAxes)
        plt.tight_layout()
        return fig_to_b64(fig)

    ref_dur = len(ref_y) / SR if len(ref_y) > 0 else 0
    rec_dur = len(rec_y) / SR if len(rec_y) > 0 else 0
    base_dur = max(ref_dur, rec_dur + abs(offset_sec))
    clip_dur = base_dur if MAX_CLIP_SEC is None else min(base_dur, MAX_CLIP_SEC)

    # 색상
    if platform == 'Android':
        ref_color, rec_color = '#5b9bd5', '#e07b39'
    else:
        ref_color, rec_color = '#5b9bd5', '#50c878'

    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    fig.suptitle(
        f"{call_label} — {platform} (offset {offset_sec:+.3f}s)",
        fontsize=10, fontweight='bold',
    )

    markers = markers or []

    def _mark(ax, ymin, ymax):
        for s_ms, e_ms, label, mtype in markers:
            s, e = s_ms / 1000, e_ms / 1000
            if s > clip_dur:
                continue
            color = {'red': '#ff4444', 'high': '#ff4444',
                     'medium': '#ffaa00', 'low': '#88ccff'}.get(mtype, '#ff4444')
            ax.axvspan(s, min(e, clip_dur), color=color, alpha=0.30)

    def _draw_seg(ax):
        if not dropout_lines:
            return
        for ln in dropout_lines:
            s = ln['ref_start_s']
            if s > clip_dur:
                continue
            e = ln['ref_end_s']
            corr = ln['max_corr']
            ax.axvline(s, color='#666', lw=0.4, ls=':', alpha=0.5)
            c = '#ff4444' if ln['dropped'] else '#44cc44'
            mid = (s + min(e, clip_dur)) / 2
            ax.text(mid, ax.get_ylim()[1] * 0.02,
                    f"{corr:.2f}", fontsize=5.5, ha='center', va='bottom',
                    color=c, alpha=0.8)

    # [1] 정답지 파형
    ax = axes[0]
    if len(ref_y) > 0:
        t_ref = np.linspace(0, ref_dur, len(ref_y))
        ax.plot(t_ref, ref_y, color=ref_color, lw=0.25, alpha=0.8)
    ax.set_title(f"정답지: {ref_name}", fontsize=9)
    ax.set_ylabel("Amplitude")
    ax.set_xlim(0, clip_dur)
    _mark(ax, -1, 1)
    _draw_seg(ax)

    # [2] 녹음 파형
    ax = axes[1]
    if len(rec_y) > 0:
        t_rec = np.linspace(offset_sec, offset_sec + rec_dur, len(rec_y))
        ax.plot(t_rec, rec_y, color=rec_color, lw=0.25, alpha=0.8)
    ax.set_title(f"{platform} 녹음: {rec_name} (offset {offset_sec:+.3f}s)", fontsize=9)
    ax.set_ylabel("Amplitude")
    ax.set_xlim(0, clip_dur)
    _mark(ax, -1, 1)
    _draw_seg(ax)

    # [3] RMS 오버레이
    ax = axes[2]
    if len(ref_y) > 0:
        ref_rms = compute_rms(ref_y)
        t_rr = librosa.frames_to_time(np.arange(len(ref_rms)), sr=SR, hop_length=RMS_HOP)
        ax.plot(t_rr, ref_rms, color=ref_color, lw=0.7, alpha=0.85, label='정답지 RMS')
    if len(rec_y) > 0:
        rec_rms = compute_rms(rec_y)
        t_rc = librosa.frames_to_time(np.arange(len(rec_rms)), sr=SR, hop_length=RMS_HOP) + offset_sec
        ax.plot(t_rc, rec_rms, color=rec_color, lw=0.7, alpha=0.85, label=f'{platform} RMS')
    ax.set_title(f"에너지 비교 — 정답지 vs {platform}", fontsize=9)
    ax.set_ylabel("RMS")
    ax.set_xlabel(f"Time (s) — 0~{clip_dur:.0f}초")
    ax.set_xlim(0, clip_dur)
    ax.legend(fontsize=7, loc='upper right')
    _mark(ax, 0, 1)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    return fig_to_b64(fig)


def plot_comparison_android_only(call_label: str, and_y: np.ndarray,
                                  and_rms: np.ndarray, markers: list) -> str:
    """Android 단독 파형 + RMS 그래프 (iOS 음원 미수집 시 사용)."""
    if len(and_y) == 0:
        fig, ax = plt.subplots(1, 1, figsize=(20, 4))
        ax.text(0.5, 0.5, '음원 없음', ha='center', va='center', fontsize=14,
                color='#aaa', transform=ax.transAxes)
        plt.tight_layout()
        return fig_to_b64(fig)

    duration = len(and_y) / SR
    clip_dur  = duration if MAX_CLIP_SEC is None else min(duration, MAX_CLIP_SEC)

    t_and = np.linspace(0, len(and_y) / SR, len(and_y))
    t_ra  = librosa.frames_to_time(np.arange(len(and_rms)), sr=SR, hop_length=RMS_HOP)

    fig, axes = plt.subplots(2, 1, figsize=(20, 8), sharex=True)
    fig.suptitle(
        f"{call_label} — Android 단독 분석 (iOS 음원 미수집)\n"
        "빨강=음단절 감지 구간",
        fontsize=12, fontweight='bold'
    )

    def _mark(ax: plt.Axes, ymin: float, ymax: float) -> None:
        for s_ms, e_ms, label, mtype in markers:
            s, e = s_ms / 1000, e_ms / 1000
            if s > clip_dur:
                continue
            ax.axvspan(s, min(e, clip_dur), color='#ff4444', alpha=0.30)
            ax.annotate(label, xy=((s + min(e, clip_dur)) / 2, ymax * 0.88),
                        fontsize=6.5, color='#ff4444', ha='center', va='top',
                        fontweight='bold',
                        bbox=dict(boxstyle='round,pad=0.2', fc='#0f1520',
                                  ec='#ff4444', alpha=0.8))

    ax = axes[0]
    ax.plot(t_and, and_y, color='#e07b39', lw=0.25, alpha=0.8)
    ax.set_title("Android 녹음 파형", fontsize=10)
    ax.set_ylabel("Amplitude")
    ax.set_xlim(0, clip_dur)
    _mark(ax, float(and_y.min()), float(and_y.max()))

    ax = axes[1]
    ax.plot(t_ra, and_rms, color='#e07b39', lw=0.7, alpha=0.85, label='Android RMS')
    ax.set_title("Android 에너지 (RMS)", fontsize=10)
    ax.set_ylabel("RMS")
    ax.set_xlabel(f"Time (s) — 분석 구간: 0~{clip_dur:.0f}초")
    ax.set_xlim(0, clip_dur)
    ax.legend(fontsize=8, loc='upper right')
    rms_max = float(and_rms.max()) if len(and_rms) > 0 else 1.0
    _mark(ax, 0, rms_max)

    plt.tight_layout()
    return fig_to_b64(fig)


def plot_zoom(call_label: str, ios_y: np.ndarray, and_y: np.ndarray,
              markers: list, zoom_sec: float = 20) -> str:
    """초반 zoom_sec초 상세 파형 → base64 PNG."""
    n = int(zoom_sec * SR)
    ios_c = ios_y[:n]
    and_c = and_y[:n]
    t = np.linspace(0, zoom_sec, n)

    fig, axes = plt.subplots(2, 1, figsize=(16, 7), sharex=True)
    fig.suptitle(
        f"{call_label} — 초반 {zoom_sec}초 상세\n"
        "(주황=초기음단절, 빨강=확신, 노랑=의심)",
        fontsize=11, fontweight='bold'
    )

    def _mark_zoom(ax: plt.Axes, ymin: float, ymax: float) -> None:
        for s_ms, e_ms, label, mtype in markers:
            s, e = s_ms / 1000, e_ms / 1000
            if s > zoom_sec:
                continue
            color = {'initial': 'orange', 'high': '#ff4444',
                     'medium': '#ffaa00', 'low': '#88ccff'}.get(mtype, '#ff4444')
            ax.axvspan(s, min(e, zoom_sec), color=color, alpha=0.35)
            ax.annotate(label, xy=((s+min(e, zoom_sec))/2, ymax*0.82),
                        fontsize=7.5, color=color, ha='center', va='top',
                        fontweight='bold',
                        bbox=dict(boxstyle='round,pad=0.25', fc='#0f1520',
                                  ec=color, alpha=0.85))

    ax = axes[0]
    ax.plot(t, ios_c, color='#5b9bd5', lw=0.6)
    ax.fill_between(t, ios_c, 0, where=(ios_c > 0), color='#5b9bd5', alpha=0.15)
    ax.set_title("iOS", fontsize=10)
    ax.set_ylabel("Amplitude")
    ax.set_xlim(0, zoom_sec)
    _mark_zoom(ax, float(ios_c.min()), float(ios_c.max()))

    ax = axes[1]
    ax.plot(t, and_c, color='#e07b39', lw=0.6)
    ax.fill_between(t, and_c, 0, where=(and_c > 0), color='#e07b39', alpha=0.15)
    ax.set_title("Android (검사 대상)", fontsize=10)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.set_xlim(0, zoom_sec)
    _mark_zoom(ax, float(and_c.min()), float(and_c.max()))

    plt.tight_layout()
    return fig_to_b64(fig)
