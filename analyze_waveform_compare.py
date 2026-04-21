#!/usr/bin/env python3
"""
iOS vs Android 통화 녹음 파형 비교 분석
- RMS 에너지 기반 음단절(Dropout) 구간 자동 검출
- 통화 초반 0~10초 구간 상세 분석
- iOS(Opus) vs Android(AAC) 동일 통화 비교
"""

import os
import sys
import base64
import io
from pathlib import Path
import numpy as np
import librosa
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# macOS 한글 폰트 설정
_korean_fonts = ['AppleGothic', 'Apple SD Gothic Neo', 'NanumGothic', 'Malgun Gothic']
_found_font = None
for _fn in _korean_fonts:
    if any(_fn in f.name for f in fm.fontManager.ttflist):
        _found_font = _fn
        break
if _found_font:
    matplotlib.rc('font', family=_found_font)
matplotlib.rc('axes', unicode_minus=False)
import matplotlib.gridspec as gridspec
from scipy.signal import find_peaks
from datetime import datetime

_BASE_DIR      = Path(__file__).parent
RECORDINGS_DIR = str(_BASE_DIR / "recordings")
OUTPUT_HTML    = str(_BASE_DIR / "waveform_compare_report.html")

CALLS = [
    {
        "label": "통화 1 (09:17~09:21)",
        "ios":     os.path.join(RECORDINGS_DIR, "recording1.wav"),
        "android": os.path.join(RECORDINGS_DIR, "android_recording1.wav"),
        "ios_codec":     "Opus",
        "android_codec": "AAC-LC 16kHz",
    },
    {
        "label": "통화 2 (09:24~09:27)",
        "ios":     os.path.join(RECORDINGS_DIR, "recording2.wav"),
        "android": os.path.join(RECORDINGS_DIR, "android_recording2.wav"),
        "ios_codec":     "Opus",
        "android_codec": "AAC-LC 16kHz",
    },
]

from audio_lib.consts import SR, RMS_FRAME, RMS_HOP
from audio_lib.io    import load_audio, fig_to_b64 as fig_to_base64
from audio_lib.dsp   import compute_rms as _compute_rms

DROPOUT_THRESH_FACTOR = 0.08   # 전체 RMS 평균 대비 이 비율 이하 = 무음
# RMS_HOP=128(8ms) 기준으로 MIN_DROPOUT_FRAMES=8 → 64ms 최소 dropout 유지
# (이전: RMS_HOP=256 × 4frames = 64ms, 현재: RMS_HOP=128 × 8frames = 64ms)
MIN_DROPOUT_FRAMES = 8
EARLY_SEC = 10       # 초반 분석 구간(초)


# ─────────────────────────────────────────────
def compute_rms(y):
    """RMS 계산. 드롭아웃 검출용이므로 스무딩 없이 raw RMS 반환."""
    return _compute_rms(y, smooth=False)


def detect_dropouts(rms, threshold_ratio=DROPOUT_THRESH_FACTOR, min_frames=MIN_DROPOUT_FRAMES):
    """무음/dropout 구간 검출 → list of (start_sec, end_sec, duration_ms)"""
    mean_rms = np.mean(rms)
    threshold = mean_rms * threshold_ratio
    silent = rms < threshold

    dropouts = []
    in_dropout = False
    start_idx = 0
    for i, s in enumerate(silent):
        if s and not in_dropout:
            in_dropout = True
            start_idx = i
        elif not s and in_dropout:
            in_dropout = False
            length = i - start_idx
            if length >= min_frames:
                t_start = librosa.frames_to_time(start_idx, sr=SR, hop_length=RMS_HOP)
                t_end   = librosa.frames_to_time(i, sr=SR, hop_length=RMS_HOP)
                dropouts.append((t_start, t_end, (t_end - t_start) * 1000))
    # 끝까지 이어진 경우
    if in_dropout:
        length = len(rms) - start_idx
        if length >= min_frames:
            t_start = librosa.frames_to_time(start_idx, sr=SR, hop_length=RMS_HOP)
            t_end   = librosa.frames_to_time(len(rms), sr=SR, hop_length=RMS_HOP)
            dropouts.append((t_start, t_end, (t_end - t_start) * 1000))
    return dropouts, threshold


# ─────────────────────────────────────────────
def plot_full_comparison(call, ios_y, and_y, ios_rms, and_rms,
                          ios_drops, and_drops, ios_thresh, and_thresh):
    """전체 파형 + RMS 비교 그래프"""
    duration = max(len(ios_y), len(and_y)) / SR
    fig = plt.figure(figsize=(18, 10))
    fig.suptitle(f"{call['label']} — 전체 파형 비교", fontsize=14, fontweight='bold')
    gs = gridspec.GridSpec(4, 2, hspace=0.55, wspace=0.25)

    t_ios = np.linspace(0, len(ios_y)/SR, len(ios_y))
    t_and = np.linspace(0, len(and_y)/SR, len(and_y))
    t_rms_ios = librosa.frames_to_time(np.arange(len(ios_rms)), sr=SR, hop_length=RMS_HOP)
    t_rms_and = librosa.frames_to_time(np.arange(len(and_rms)), sr=SR, hop_length=RMS_HOP)

    # iOS 파형
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(t_ios, ios_y, color='steelblue', linewidth=0.4, alpha=0.7)
    ax1.set_title(f"iOS 파형  ({call['ios_codec']})", fontsize=11)
    ax1.set_xlabel("Time (s)"); ax1.set_ylabel("Amplitude")
    ax1.set_xlim(0, duration)
    _mark_dropouts(ax1, ios_drops, ios_y.min(), ios_y.max())

    # Android 파형
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(t_and, and_y, color='darkorange', linewidth=0.4, alpha=0.7)
    ax2.set_title(f"Android 파형  ({call['android_codec']})", fontsize=11)
    ax2.set_xlabel("Time (s)"); ax2.set_ylabel("Amplitude")
    ax2.set_xlim(0, duration)
    _mark_dropouts(ax2, and_drops, and_y.min(), and_y.max())

    # iOS RMS
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.plot(t_rms_ios, ios_rms, color='steelblue', linewidth=0.8)
    ax3.axhline(ios_thresh, color='red', linestyle='--', linewidth=1, label=f'임계값 ({ios_thresh:.5f})')
    ax3.set_title("iOS RMS 에너지", fontsize=11)
    ax3.set_xlabel("Time (s)"); ax3.set_ylabel("RMS")
    ax3.set_xlim(0, duration); ax3.legend(fontsize=8)
    _mark_dropouts(ax3, ios_drops, 0, ios_rms.max())

    # Android RMS
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.plot(t_rms_and, and_rms, color='darkorange', linewidth=0.8)
    ax4.axhline(and_thresh, color='red', linestyle='--', linewidth=1, label=f'임계값 ({and_thresh:.5f})')
    ax4.set_title("Android RMS 에너지", fontsize=11)
    ax4.set_xlabel("Time (s)"); ax4.set_ylabel("RMS")
    ax4.set_xlim(0, duration); ax4.legend(fontsize=8)
    _mark_dropouts(ax4, and_drops, 0, and_rms.max())

    # iOS 스펙트로그램
    ax5 = fig.add_subplot(gs[2:, 0])
    S_ios = librosa.feature.melspectrogram(y=ios_y, sr=SR, n_mels=64, fmax=8000)
    S_db_ios = librosa.power_to_db(S_ios, ref=np.max)
    librosa.display.specshow(S_db_ios, sr=SR, x_axis='time', y_axis='mel',
                              fmax=8000, ax=ax5, cmap='coolwarm')
    ax5.set_title("iOS 멜 스펙트로그램", fontsize=11)
    _mark_dropouts_spec(ax5, ios_drops)

    # Android 스펙트로그램
    ax6 = fig.add_subplot(gs[2:, 1])
    S_and = librosa.feature.melspectrogram(y=and_y, sr=SR, n_mels=64, fmax=8000)
    S_db_and = librosa.power_to_db(S_and, ref=np.max)
    librosa.display.specshow(S_db_and, sr=SR, x_axis='time', y_axis='mel',
                              fmax=8000, ax=ax6, cmap='coolwarm')
    ax6.set_title("Android 멜 스펙트로그램", fontsize=11)
    _mark_dropouts_spec(ax6, and_drops)

    return fig_to_base64(fig)


def plot_early_comparison(call, ios_y, and_y, ios_rms, and_rms,
                           ios_drops, and_drops, ios_thresh, and_thresh,
                           early_sec=EARLY_SEC):
    """통화 초반 0~10초 상세 비교"""
    n_samples = int(early_sec * SR)
    ios_y_e  = ios_y[:n_samples]
    and_y_e  = and_y[:n_samples]
    n_frames = int(early_sec * SR / RMS_HOP)
    ios_rms_e = ios_rms[:n_frames]
    and_rms_e = and_rms[:n_frames]

    fig, axes = plt.subplots(2, 2, figsize=(16, 8))
    fig.suptitle(f"{call['label']} — 초반 {early_sec}초 상세 분석 (音빠짐 검출)", fontsize=13, fontweight='bold')

    t_e = np.linspace(0, len(ios_y_e)/SR, len(ios_y_e))
    t_e2 = np.linspace(0, len(and_y_e)/SR, len(and_y_e))
    t_rms_e = librosa.frames_to_time(np.arange(len(ios_rms_e)), sr=SR, hop_length=RMS_HOP)
    t_rms_e2 = librosa.frames_to_time(np.arange(len(and_rms_e)), sr=SR, hop_length=RMS_HOP)

    early_ios_drops = [(s,e,d) for s,e,d in ios_drops if s < early_sec]
    early_and_drops = [(s,e,d) for s,e,d in and_drops if s < early_sec]

    # iOS 파형 초반
    axes[0,0].plot(t_e, ios_y_e, color='steelblue', linewidth=0.6)
    axes[0,0].set_title(f"iOS 파형 초반 {early_sec}초  ({call['ios_codec']})", fontsize=10)
    axes[0,0].set_xlabel("Time (s)"); axes[0,0].set_ylabel("Amplitude")
    axes[0,0].set_xlim(0, early_sec)
    _mark_dropouts(axes[0,0], early_ios_drops, ios_y_e.min(), ios_y_e.max())

    # Android 파형 초반
    axes[0,1].plot(t_e2, and_y_e, color='darkorange', linewidth=0.6)
    axes[0,1].set_title(f"Android 파형 초반 {early_sec}초  ({call['android_codec']})", fontsize=10)
    axes[0,1].set_xlabel("Time (s)"); axes[0,1].set_ylabel("Amplitude")
    axes[0,1].set_xlim(0, early_sec)
    _mark_dropouts(axes[0,1], early_and_drops, and_y_e.min(), and_y_e.max())

    # iOS RMS 초반
    axes[1,0].plot(t_rms_e, ios_rms_e, color='steelblue', linewidth=1.2)
    axes[1,0].axhline(ios_thresh, color='red', linestyle='--', linewidth=1.2,
                       label=f'무음 임계값')
    axes[1,0].fill_between(t_rms_e, 0, ios_rms_e, alpha=0.3, color='steelblue')
    axes[1,0].set_title("iOS RMS 에너지 (초반)", fontsize=10)
    axes[1,0].set_xlabel("Time (s)"); axes[1,0].set_ylabel("RMS")
    axes[1,0].set_xlim(0, early_sec); axes[1,0].legend(fontsize=8)
    _mark_dropouts(axes[1,0], early_ios_drops, 0, ios_rms_e.max() * 1.1)

    # Android RMS 초반
    axes[1,1].plot(t_rms_e2, and_rms_e, color='darkorange', linewidth=1.2)
    axes[1,1].axhline(and_thresh, color='red', linestyle='--', linewidth=1.2,
                       label=f'무음 임계값')
    axes[1,1].fill_between(t_rms_e2, 0, and_rms_e, alpha=0.3, color='darkorange')
    axes[1,1].set_title("Android RMS 에너지 (초반)", fontsize=10)
    axes[1,1].set_xlabel("Time (s)"); axes[1,1].set_ylabel("RMS")
    axes[1,1].set_xlim(0, early_sec); axes[1,1].legend(fontsize=8)
    _mark_dropouts(axes[1,1], early_and_drops, 0, and_rms_e.max() * 1.1)

    plt.tight_layout()
    return fig_to_base64(fig)


def plot_rms_overlay(call, ios_rms, and_rms):
    """iOS vs Android RMS 오버레이 비교"""
    t_ios = librosa.frames_to_time(np.arange(len(ios_rms)), sr=SR, hop_length=RMS_HOP)
    t_and = librosa.frames_to_time(np.arange(len(and_rms)), sr=SR, hop_length=RMS_HOP)
    duration = max(t_ios[-1], t_and[-1]) if len(t_ios) and len(t_and) else 200

    fig, ax = plt.subplots(figsize=(16, 4))
    ax.plot(t_ios, ios_rms,  color='steelblue',  linewidth=0.8, alpha=0.8, label='iOS (Opus)')
    ax.plot(t_and, and_rms,  color='darkorange',  linewidth=0.8, alpha=0.8, label='Android (AAC)')
    ax.set_title(f"{call['label']} — iOS vs Android RMS 에너지 오버레이", fontsize=12)
    ax.set_xlabel("Time (s)"); ax.set_ylabel("RMS")
    ax.set_xlim(0, duration)
    ax.legend(fontsize=9)
    plt.tight_layout()
    return fig_to_base64(fig)


def _mark_dropouts(ax, dropouts, ymin, ymax):
    for s, e, d in dropouts:
        ax.axvspan(s, e, color='red', alpha=0.25)
        mid = (s + e) / 2
        ax.annotate(f'{d:.0f}ms', xy=(mid, ymax),
                    xytext=(mid, ymax),
                    fontsize=6, color='darkred', ha='center', va='top')


def _mark_dropouts_spec(ax, dropouts):
    for s, e, d in dropouts:
        ax.axvline(s, color='red', linewidth=1.2, alpha=0.7)
        ax.axvline(e, color='red', linewidth=1.2, alpha=0.7)


# ─────────────────────────────────────────────
def dropout_table_html(drops, label, color):
    if not drops:
        return f'<p style="color:green">✅ {label}: 감지된 음단절 없음</p>'
    rows = ""
    for i, (s, e, d) in enumerate(drops, 1):
        severity = "🔴 심각" if d > 300 else "🟡 중간" if d > 100 else "🟢 경미"
        # 초 → 분:초 형식
        ts_str = f"{int(s//60):02d}:{s%60:05.2f}"
        te_str = f"{int(e//60):02d}:{e%60:05.2f}"
        rows += f"<tr><td>{i}</td><td>{ts_str}</td><td>{te_str}</td><td>{d:.1f}ms</td><td>{severity}</td></tr>"
    return f'''
    <table class="dropout-table">
      <caption style="color:{color};font-weight:bold">{label} — 음단절 목록</caption>
      <thead><tr><th>#</th><th>시작</th><th>종료</th><th>길이</th><th>심각도</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>'''


def stats_card_html(y, rms, drops, label, color, codec,
                     ios_rms=None, and_rms=None):
    total_sec = len(y) / SR
    total_min = int(total_sec // 60)
    total_s   = total_sec % 60
    drop_total_ms = sum(d for _, _, d in drops)
    drop_ratio    = drop_total_ms / (total_sec * 1000) * 100
    avg_rms  = float(np.mean(rms))
    peak_rms = float(np.max(rms))

    # SNR 추정 (음성 구간 vs 무음 구간 비율)
    speech_mask = rms > (avg_rms * DROPOUT_THRESH_FACTOR)
    snr_est = 20 * np.log10(np.mean(rms[speech_mask]) / (np.mean(rms[~speech_mask]) + 1e-9)) if speech_mask.any() else 0

    # 코덱 레이턴시 참고
    codec_note = ""
    if ios_rms is not None and and_rms is not None:
        min_len = min(len(ios_rms), len(and_rms))
        corr = np.corrcoef(ios_rms[:min_len], and_rms[:min_len])[0, 1]
        codec_note = f'<li>iOS vs Android RMS 상관계수: <b>{corr:.4f}</b></li>'

    return f'''
    <div class="stats-card" style="border-left:4px solid {color}">
      <h3 style="color:{color}">{label} <span class="badge">{codec}</span></h3>
      <ul>
        <li>총 길이: <b>{total_min}분 {total_s:.1f}초</b></li>
        <li>RMS 평균: <b>{avg_rms:.5f}</b> / 최대: <b>{peak_rms:.5f}</b></li>
        <li>추정 SNR: <b>{snr_est:.1f} dB</b></li>
        <li>감지된 음단절: <b>{len(drops)}건</b> (총 {drop_total_ms:.0f}ms, 통화의 {drop_ratio:.2f}%)</li>
        {codec_note}
      </ul>
    </div>'''


# ─────────────────────────────────────────────
def build_html(sections):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = "\n".join(sections)
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>iOS vs Android 파형 비교 분석 보고서</title>
<style>
  body {{ font-family: "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
         background:#0f1117; color:#e8eaf0; margin:0; padding:0; }}
  .header {{ background:linear-gradient(135deg,#1a1f35,#2d3561);
             padding:32px 40px; border-bottom:2px solid #3a4070; }}
  .header h1 {{ margin:0; font-size:1.6em; color:#7eb8f7; }}
  .header p  {{ margin:4px 0 0; color:#9aa5c4; font-size:0.9em; }}
  .section   {{ max-width:1600px; margin:30px auto; padding:0 30px; }}
  .call-block {{ background:#1a1f2e; border-radius:12px; padding:24px 28px;
                 margin-bottom:40px; border:1px solid #2d3561; }}
  .call-block h2 {{ color:#f0c040; margin:0 0 20px; font-size:1.2em; }}
  .stats-row {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:20px; }}
  .stats-card {{ flex:1; min-width:260px; background:#0f1520; border-radius:8px;
                 padding:16px 18px; border:1px solid #2a3050; }}
  .stats-card h3 {{ margin:0 0 10px; font-size:1em; }}
  .stats-card ul {{ margin:0; padding-left:18px; font-size:0.88em; line-height:1.8; }}
  .badge {{ background:#2d3561; color:#7eb8f7; padding:2px 8px;
            border-radius:4px; font-size:0.75em; margin-left:6px; }}
  .plot-title {{ color:#9aa5c4; font-size:0.85em; margin:18px 0 6px; font-weight:bold; }}
  img {{ width:100%; border-radius:8px; border:1px solid #2d3561; margin-bottom:12px; }}
  .dropout-table {{ width:100%; border-collapse:collapse; font-size:0.85em;
                    margin:10px 0 20px; }}
  .dropout-table caption {{ text-align:left; margin-bottom:6px; }}
  .dropout-table th {{ background:#2d3561; padding:6px 10px; text-align:left; }}
  .dropout-table td {{ padding:5px 10px; border-bottom:1px solid #1e2540; }}
  .dropout-table tr:hover td {{ background:#1a2040; }}
  .divider {{ border:0; border-top:1px solid #2d3561; margin:24px 0; }}
  .summary-box {{ background:#1a2235; border:1px solid #2d5080; border-radius:8px;
                  padding:18px 22px; margin-bottom:24px; }}
  .summary-box h3 {{ color:#7eb8f7; margin:0 0 12px; }}
  .summary-box ul {{ margin:0; padding-left:18px; font-size:0.9em; line-height:1.9; }}
</style>
</head>
<body>
<div class="header">
  <h1>📊 iOS vs Android 통화 녹음 파형 비교 분석</h1>
  <p>생성 시각: {now} &nbsp;|&nbsp; 장치: iPhone 17 Pro (iOS · Opus) vs Samsung SM-S908N (Android · AAC-LC) &nbsp;|&nbsp; 앱: com.lguplus.aicallagent</p>
</div>
<div class="section">
{body}
</div>
</body>
</html>'''


# ─────────────────────────────────────────────
def main():
    import librosa.display
    sections = []

    # 전체 요약
    sections.append('''
    <div class="summary-box">
      <h3>🔍 분석 개요</h3>
      <ul>
        <li>동일 상대방 번호(01083330064)와의 통화를 iOS·Android 양쪽에서 녹음 비교</li>
        <li>RMS 프레임 크기: 32ms, hop: 16ms / 무음 임계: 전체 평균 RMS의 8% 이하</li>
        <li>음단절 최소 지속: 64ms 이상인 구간만 표시</li>
        <li>스펙트로그램: 멜 스케일 0~8kHz, 64 필터뱅크</li>
      </ul>
    </div>''')

    all_ios_drop_count = 0
    all_and_drop_count = 0

    for call in CALLS:
        print(f"\n{'='*60}")
        print(f"[분석] {call['label']}")
        print(f"  iOS:     {call['ios']}")
        print(f"  Android: {call['android']}")

        # 로드
        ios_y = load_audio(call['ios'])
        and_y = load_audio(call['android'])
        print(f"  iOS 길이: {len(ios_y)/SR:.1f}s / Android 길이: {len(and_y)/SR:.1f}s")

        # RMS 계산
        ios_rms = compute_rms(ios_y)
        and_rms = compute_rms(and_y)

        # 음단절 검출
        ios_drops, ios_thresh = detect_dropouts(ios_rms)
        and_drops, and_thresh = detect_dropouts(and_rms)

        # 초반(0~10초) 드롭아웃만 별도 추출
        early_ios_drops = [(s,e,d) for s,e,d in ios_drops if s < EARLY_SEC]
        early_and_drops = [(s,e,d) for s,e,d in and_drops if s < EARLY_SEC]

        print(f"  iOS 음단절: {len(ios_drops)}건 (초반 {EARLY_SEC}초 내: {len(early_ios_drops)}건)")
        print(f"  Android 음단절: {len(and_drops)}건 (초반 {EARLY_SEC}초 내: {len(early_and_drops)}건)")

        all_ios_drop_count += len(ios_drops)
        all_and_drop_count += len(and_drops)

        # 플롯 생성
        print("  [그래프] 전체 파형 비교 생성 중...")
        b64_full  = plot_full_comparison(call, ios_y, and_y,
                                          ios_rms, and_rms,
                                          ios_drops, and_drops,
                                          ios_thresh, and_thresh)

        print("  [그래프] 초반 상세 분석 생성 중...")
        b64_early = plot_early_comparison(call, ios_y, and_y,
                                           ios_rms, and_rms,
                                           ios_drops, and_drops,
                                           ios_thresh, and_thresh)

        print("  [그래프] RMS 오버레이 생성 중...")
        b64_overlay = plot_rms_overlay(call, ios_rms, and_rms)

        # 통계 카드
        ios_card = stats_card_html(ios_y, ios_rms, ios_drops,
                                    "iOS", "#5b9bd5", call['ios_codec'],
                                    ios_rms, and_rms)
        and_card = stats_card_html(and_y, and_rms, and_drops,
                                    "Android", "#e07b39", call['android_codec'])

        # 음단절 테이블
        ios_drop_html = dropout_table_html(ios_drops[:50], "iOS", "#5b9bd5")
        and_drop_html = dropout_table_html(and_drops[:50], "Android", "#e07b39")

        # 섹션 조립
        sections.append(f'''
        <div class="call-block">
          <h2>📞 {call["label"]}</h2>
          <div class="stats-row">{ios_card}{and_card}</div>
          <hr class="divider">
          <p class="plot-title">▶ iOS vs Android RMS 오버레이</p>
          <img src="data:image/png;base64,{b64_overlay}" alt="RMS Overlay">
          <p class="plot-title">▶ 초반 {EARLY_SEC}초 상세 (음단절 구간: 🔴 빨간 음영)</p>
          <img src="data:image/png;base64,{b64_early}" alt="Early Detail">
          <p class="plot-title">▶ 전체 파형 + 멜 스펙트로그램 비교</p>
          <img src="data:image/png;base64,{b64_full}" alt="Full Waveform">
          <hr class="divider">
          <div style="display:flex;gap:20px;flex-wrap:wrap">
            <div style="flex:1;min-width:320px">{ios_drop_html}</div>
            <div style="flex:1;min-width:320px">{and_drop_html}</div>
          </div>
        </div>''')

    # 최종 종합 요약
    sections.append(f'''
    <div class="summary-box">
      <h3>📝 최종 종합 결론</h3>
      <ul>
        <li>iOS 전체 음단절: <b>{all_ios_drop_count}건</b> &nbsp;|&nbsp; Android 전체 음단절: <b>{all_and_drop_count}건</b></li>
        <li>iOS와 Android 녹음의 RMS 오버레이로 어느 쪽에서 음단절이 발생했는지 구분 가능</li>
        <li>양쪽 동시 발생 → 네트워크/서버 측 문제 | iOS 단독 발생 → iOS 오디오 레이어 문제 | Android 단독 → Android 측 문제</li>
        <li>"안녕하세요~" 앞 음단절: 초반 {EARLY_SEC}초 상세 그래프에서 0~2초 구간 확인 권장</li>
      </ul>
    </div>''')

    html = build_html(sections)
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n✅ 보고서 저장 완료: {OUTPUT_HTML}")


if __name__ == '__main__':
    main()
