#!/usr/bin/env python3
"""
iOS vs Android 통화 녹음 파형 비교 분석 + Gemini AI 음성 품질 평가
- librosa: RMS 에너지 기반 음단절 자동 검출
- Gemini 2.0 Flash: 실제 음성을 듣고 음질/음단절/발화 내용 해석
"""

import os
import sys
import base64
import io
import json
import time
import wave
from pathlib import Path
import numpy as np
import librosa
import librosa.display as _ld
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.gridspec as gridspec
from datetime import datetime

# ── 한글 폰트 설정 ──────────────────────────────────────────────
_korean_fonts = ['AppleGothic', 'Apple SD Gothic Neo', 'NanumGothic']
for _fn in _korean_fonts:
    if any(_fn in f.name for f in fm.fontManager.ttflist):
        matplotlib.rc('font', family=_fn)
        break
matplotlib.rc('axes', unicode_minus=False)

# ── 상수 ────────────────────────────────────────────────────────
_BASE_DIR      = Path(__file__).parent
RECORDINGS_DIR = str(_BASE_DIR / "recordings")
ENV_FILE       = str(_BASE_DIR / "env")
OUTPUT_HTML    = str(_BASE_DIR / "waveform_gemini_report.html")

from audio_lib.consts import SR, RMS_FRAME, RMS_HOP
from audio_lib.io    import load_audio, fig_to_b64
from audio_lib.dsp   import compute_rms as _compute_rms

# RMS_HOP=128(8ms) 기준: MIN_DROP_FRAMES=8 → 64ms 최소 dropout 유지
# (이전: RMS_HOP=256 × 4frames = 64ms, 현재: RMS_HOP=128 × 8frames = 64ms)
DROPOUT_RATIO   = 0.08   # 평균 RMS 대비 이 비율 이하 → 무음
MIN_DROP_FRAMES = 8      # 최소 8프레임(64ms @ hop=128)

GEMINI_MODEL   = "gemini-2.5-flash"
EARLY_SEC      = 10    # 초반 상세 분석 구간(초)
GEMINI_CLIP_SEC = 15   # Gemini에 보낼 클립 길이(초)

CALLS = [
    {
        "label":          "통화 1 (09:17~09:21)",
        "ios":            os.path.join(RECORDINGS_DIR, "recording1.wav"),
        "android":        os.path.join(RECORDINGS_DIR, "android_recording1.wav"),
        "ios_codec":      "Opus 48kHz",
        "android_codec":  "AAC-LC 16kHz",
    },
    {
        "label":          "통화 2 (09:24~09:27)",
        "ios":            os.path.join(RECORDINGS_DIR, "recording2.wav"),
        "android":        os.path.join(RECORDINGS_DIR, "android_recording2.wav"),
        "ios_codec":      "Opus 48kHz",
        "android_codec":  "AAC-LC 16kHz",
    },
]


# ════════════════════════════════════════════════════════════════
# 유틸
# ════════════════════════════════════════════════════════════════

def load_env_key():
    """env 파일에서 GEMINI_API_KEY 로드"""
    if not os.path.exists(ENV_FILE):
        return None
    with open(ENV_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('GEMINI_API_KEY'):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    return parts[1].strip().strip('"').strip("'")
    return None


def compute_rms(y):
    """RMS 계산. 드롭아웃 검출용이므로 스무딩 없이 raw RMS 반환."""
    return _compute_rms(y, smooth=False)


def detect_dropouts(rms, ratio=DROPOUT_RATIO, min_frames=MIN_DROP_FRAMES):
    """무음/dropout 구간 → list of (start_sec, end_sec, duration_ms)"""
    threshold = np.mean(rms) * ratio
    silent = rms < threshold
    dropouts, in_drop, start_i = [], False, 0
    for i, s in enumerate(silent):
        if s and not in_drop:
            in_drop, start_i = True, i
        elif not s and in_drop:
            in_drop = False
            if (i - start_i) >= min_frames:
                ts = librosa.frames_to_time(start_i, sr=SR, hop_length=RMS_HOP)
                te = librosa.frames_to_time(i,       sr=SR, hop_length=RMS_HOP)
                dropouts.append((ts, te, (te - ts) * 1000))
    if in_drop:
        length = len(rms) - start_i
        if length >= min_frames:
            ts = librosa.frames_to_time(start_i,   sr=SR, hop_length=RMS_HOP)
            te = librosa.frames_to_time(len(rms),  sr=SR, hop_length=RMS_HOP)
            dropouts.append((ts, te, (te - ts) * 1000))
    return dropouts, threshold


def wav_slice_to_bytes(y_array, clip_sec=GEMINI_CLIP_SEC):
    """numpy array → WAV bytes (Gemini 전송용)"""
    n = int(clip_sec * SR)
    clip = y_array[:n]
    pcm = (clip * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


# ════════════════════════════════════════════════════════════════
# Gemini 분석
# ════════════════════════════════════════════════════════════════

def gemini_analyze(client, call_label, ios_y, and_y, ios_drops, and_drops):
    """
    Gemini에게 iOS/Android 초반 클립을 보내고 음질 비교 + 음단절 판단 요청.
    반환: dict {ios_feedback, android_feedback, comparison, dropout_verdict}
    """
    ios_wav_bytes = wav_slice_to_bytes(ios_y)
    and_wav_bytes = wav_slice_to_bytes(and_y)

    # 초반 드롭아웃 요약
    early_ios  = [(round(s,2), round(e,2), round(d)) for s,e,d in ios_drops  if s < GEMINI_CLIP_SEC]
    early_and  = [(round(s,2), round(e,2), round(d)) for s,e,d in and_drops  if s < GEMINI_CLIP_SEC]

    prompt = f"""당신은 통신사 QA 음성 품질 전문가입니다.
아래 두 오디오 파일은 동일한 AI 상담 전화통화({call_label})를 iOS와 Android 양쪽에서 각각 녹음한 것입니다.
첫 번째 파일은 iOS(iPhone 17 Pro, Opus 코덱), 두 번째 파일은 Android(Samsung S22, AAC-LC 코덱)입니다.
두 파일 모두 통화 시작부터 {GEMINI_CLIP_SEC}초를 담고 있습니다.

librosa RMS 분석 결과:
- iOS 무음 구간(0~{GEMINI_CLIP_SEC}초): {early_ios}  (start_sec, end_sec, ms)
- Android 무음 구간(0~{GEMINI_CLIP_SEC}초): {early_and}

아래 항목을 JSON으로 답해주세요 (다른 텍스트 없이 순수 JSON만):
{{
  "ios_quality": "iOS 음질 설명 (선명도, 노이즈, 울림, 코덱 특성 등 2~3문장)",
  "android_quality": "Android 음질 설명 (2~3문장)",
  "better_quality": "ios 또는 android 중 어느 쪽이 더 좋은지와 이유",
  "dropout_analysis": "통화 시작 시 음단절 여부 — iOS와 Android 각각 실제로 '안녕하세요' 첫 음절이 잘렸는지 판단",
  "dropout_cause": "음단절이 있다면 iOS 단독/Android 단독/양쪽 동시 발생인지 — 원인 추정 (네트워크, 앱 레이어, 코덱 초기화 등)",
  "recommendation": "개선 권고사항 1~2가지"
}}"""

    try:
        from google import genai
        from google.genai import types

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=ios_wav_bytes,  mime_type="audio/wav"),
                types.Part.from_bytes(data=and_wav_bytes,  mime_type="audio/wav"),
                prompt,
            ]
        )
        raw = response.text.strip()
        # JSON 블록 추출
        if '```' in raw:
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        return json.loads(raw.strip())
    except json.JSONDecodeError as e:
        return {"error": f"JSON 파싱 실패: {e}", "raw": response.text[:500]}
    except Exception as e:
        return {"error": str(e)}


# ════════════════════════════════════════════════════════════════
# 그래프
# ════════════════════════════════════════════════════════════════

def _mark_drops(ax, drops, ymin, ymax):
    for s, e, d in drops:
        ax.axvspan(s, e, color='red', alpha=0.22)
        ax.annotate(f'{d:.0f}ms', xy=((s+e)/2, ymax * 0.92),
                    fontsize=6, color='#ff6666', ha='center')


def plot_rms_overlay(call, ios_rms, and_rms):
    t_ios = librosa.frames_to_time(np.arange(len(ios_rms)), sr=SR, hop_length=RMS_HOP)
    t_and = librosa.frames_to_time(np.arange(len(and_rms)), sr=SR, hop_length=RMS_HOP)
    fig, ax = plt.subplots(figsize=(16, 3.5))
    ax.plot(t_ios, ios_rms, color='#5b9bd5', lw=0.8, alpha=0.85, label='iOS (Opus)')
    ax.plot(t_and, and_rms, color='#e07b39', lw=0.8, alpha=0.85, label='Android (AAC)')
    ax.set_title(f"{call['label']} — iOS vs Android RMS 오버레이")
    ax.set_xlabel("Time (s)"); ax.set_ylabel("RMS")
    ax.set_xlim(0, max(t_ios[-1], t_and[-1]))
    ax.legend(fontsize=9)
    plt.tight_layout()
    return fig_to_b64(fig)


def plot_early_detail(call, ios_y, and_y, ios_rms, and_rms,
                       ios_drops, and_drops, ios_thresh, and_thresh):
    n_s = int(EARLY_SEC * SR)
    n_f = int(EARLY_SEC * SR / RMS_HOP)

    fig, axes = plt.subplots(2, 2, figsize=(16, 7))
    fig.suptitle(f"{call['label']} — 초반 {EARLY_SEC}초 상세 (빨간 음영 = 음단절)", fontsize=12)

    t_w  = np.linspace(0, EARLY_SEC, n_s)
    t_r  = librosa.frames_to_time(np.arange(n_f), sr=SR, hop_length=RMS_HOP)

    early_id = [(s,e,d) for s,e,d in ios_drops  if s < EARLY_SEC]
    early_ad = [(s,e,d) for s,e,d in and_drops  if s < EARLY_SEC]

    # 파형
    for ax, y, drops, color, title in [
        (axes[0,0], ios_y[:n_s], early_id, '#5b9bd5', f"iOS 파형 ({call['ios_codec']})"),
        (axes[0,1], and_y[:n_s], early_ad, '#e07b39', f"Android 파형 ({call['android_codec']})"),
    ]:
        ax.plot(t_w[:len(y)], y, color=color, lw=0.5)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Time (s)"); ax.set_ylabel("Amplitude")
        ax.set_xlim(0, EARLY_SEC)
        _mark_drops(ax, drops, y.min(), y.max())

    # RMS
    for ax, rms, thresh, drops, color, title in [
        (axes[1,0], ios_rms[:n_f], ios_thresh, early_id, '#5b9bd5', "iOS RMS 에너지"),
        (axes[1,1], and_rms[:n_f], and_thresh, early_ad, '#e07b39', "Android RMS 에너지"),
    ]:
        ax.plot(t_r[:len(rms)], rms, color=color, lw=1.2)
        ax.fill_between(t_r[:len(rms)], 0, rms, color=color, alpha=0.25)
        ax.axhline(thresh, color='red', ls='--', lw=1, label='무음 임계값')
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Time (s)"); ax.set_ylabel("RMS")
        ax.set_xlim(0, EARLY_SEC)
        ax.legend(fontsize=8)
        _mark_drops(ax, drops, 0, rms.max() * 1.1)

    plt.tight_layout()
    return fig_to_b64(fig)


def plot_full(call, ios_y, and_y, ios_rms, and_rms,
               ios_drops, and_drops, ios_thresh, and_thresh):
    duration = max(len(ios_y), len(and_y)) / SR
    fig = plt.figure(figsize=(18, 10))
    fig.suptitle(f"{call['label']} — 전체 파형 + 멜 스펙트로그램", fontsize=13)
    gs = gridspec.GridSpec(4, 2, hspace=0.55, wspace=0.25)

    t_ios = np.linspace(0, len(ios_y)/SR, len(ios_y))
    t_and = np.linspace(0, len(and_y)/SR, len(and_y))
    t_ri  = librosa.frames_to_time(np.arange(len(ios_rms)), sr=SR, hop_length=RMS_HOP)
    t_ra  = librosa.frames_to_time(np.arange(len(and_rms)), sr=SR, hop_length=RMS_HOP)

    pairs = [
        (gs[0,0], t_ios, ios_y, ios_drops, '#5b9bd5', f"iOS 파형 ({call['ios_codec']})"),
        (gs[0,1], t_and, and_y, and_drops, '#e07b39', f"Android 파형 ({call['android_codec']})"),
    ]
    for g, t, y, drops, col, title in pairs:
        ax = fig.add_subplot(g)
        ax.plot(t, y, color=col, lw=0.35, alpha=0.7)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Time (s)"); ax.set_ylabel("Amplitude")
        ax.set_xlim(0, duration)
        _mark_drops(ax, drops, y.min(), y.max())

    rms_pairs = [
        (gs[1,0], t_ri, ios_rms, ios_thresh, ios_drops, '#5b9bd5', "iOS RMS"),
        (gs[1,1], t_ra, and_rms, and_thresh, and_drops, '#e07b39', "Android RMS"),
    ]
    for g, t, rms, thresh, drops, col, title in rms_pairs:
        ax = fig.add_subplot(g)
        ax.plot(t, rms, color=col, lw=0.7)
        ax.axhline(thresh, color='red', ls='--', lw=0.9, label=f'임계({thresh:.5f})')
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Time (s)"); ax.set_ylabel("RMS")
        ax.set_xlim(0, duration)
        ax.legend(fontsize=7)
        _mark_drops(ax, drops, 0, rms.max())

    for g, y, drops, title in [
        (gs[2:,0], ios_y, ios_drops, "iOS 멜 스펙트로그램"),
        (gs[2:,1], and_y, and_drops, "Android 멜 스펙트로그램"),
    ]:
        ax = fig.add_subplot(g)
        S = librosa.feature.melspectrogram(y=y, sr=SR, n_mels=64, fmax=8000)
        _ld.specshow(librosa.power_to_db(S, ref=np.max),
                                  sr=SR, x_axis='time', y_axis='mel',
                                  fmax=8000, ax=ax, cmap='coolwarm')
        ax.set_title(title, fontsize=10)
        for s, e, _ in drops:
            ax.axvline(s, color='red', lw=1, alpha=0.6)
            ax.axvline(e, color='red', lw=1, alpha=0.6)

    return fig_to_b64(fig)


# ════════════════════════════════════════════════════════════════
# HTML 생성
# ════════════════════════════════════════════════════════════════

def gemini_card_html(result: dict) -> str:
    if "error" in result:
        return f'<div class="gemini-error">⚠️ Gemini 분석 실패: {result["error"]}</div>'

    def row(label, val, highlight=False):
        cls = ' class="highlight"' if highlight else ''
        return f'<tr{cls}><td class="key">{label}</td><td>{val}</td></tr>'

    verdict_color = {
        "ios": "#5b9bd5", "android": "#e07b39"
    }.get(result.get("better_quality","").lower().split()[0], "#aaa")

    rows = ""
    rows += row("🎧 iOS 음질",      result.get("ios_quality","—"))
    rows += row("🤖 Android 음질",  result.get("android_quality","—"))
    rows += row("🏆 더 좋은 쪽",    f'<span style="color:{verdict_color};font-weight:bold">{result.get("better_quality","—")}</span>', True)
    rows += row("🔇 음단절 분석",   result.get("dropout_analysis","—"), True)
    rows += row("🔍 원인 추정",     result.get("dropout_cause","—"))
    rows += row("💡 개선 권고",     result.get("recommendation","—"))

    return f'''
    <div class="gemini-card">
      <div class="gemini-header">🤖 Gemini {GEMINI_MODEL} 음성 품질 분석</div>
      <table class="gemini-table"><tbody>{rows}</tbody></table>
    </div>'''


def dropout_table_html(drops, label, color):
    if not drops:
        return f'<p class="no-drop">✅ {label}: 감지된 음단절 없음</p>'
    rows = ""
    for i, (s, e, d) in enumerate(drops[:50], 1):
        sev = "🔴 심각" if d > 300 else "🟡 중간" if d > 100 else "🟢 경미"
        ts = f"{int(s//60):02d}:{s%60:05.2f}"
        te = f"{int(e//60):02d}:{e%60:05.2f}"
        rows += f"<tr><td>{i}</td><td>{ts}</td><td>{te}</td><td>{d:.1f}ms</td><td>{sev}</td></tr>"
    return f'''<div class="drop-wrap">
      <div class="drop-header" style="color:{color}">{label} — 음단절 목록 ({len(drops)}건)</div>
      <table class="drop-table">
        <thead><tr><th>#</th><th>시작</th><th>종료</th><th>길이</th><th>심각도</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>'''


def stats_html(y, rms, drops, label, color, codec):
    total_s = len(y) / SR
    drop_ms = sum(d for _, _, d in drops)
    avg_rms = float(np.mean(rms))
    peak_rms = float(np.max(rms))
    speech = rms > avg_rms * DROPOUT_RATIO
    snr = 20 * np.log10(np.mean(rms[speech]) / (np.mean(rms[~speech]) + 1e-9)) if speech.any() else 0
    return f'''<div class="stat-card" style="border-left:4px solid {color}">
      <div class="stat-title" style="color:{color}">{label} <span class="badge">{codec}</span></div>
      <ul>
        <li>길이: <b>{int(total_s//60)}분 {total_s%60:.1f}초</b></li>
        <li>RMS 평균: <b>{avg_rms:.5f}</b> / 최대: <b>{peak_rms:.5f}</b></li>
        <li>추정 SNR: <b>{snr:.1f} dB</b></li>
        <li>음단절: <b>{len(drops)}건</b> / 총 {drop_ms:.0f}ms ({drop_ms/(total_s*10):.2f}%)</li>
      </ul>
    </div>'''


CSS = """
body{font-family:"Apple SD Gothic Neo","Malgun Gothic",sans-serif;background:#0f1117;color:#e8eaf0;margin:0;padding:0}
.header{background:linear-gradient(135deg,#1a1f35,#2d3561);padding:32px 40px;border-bottom:2px solid #3a4070}
.header h1{margin:0;font-size:1.6em;color:#7eb8f7}
.header p{margin:4px 0 0;color:#9aa5c4;font-size:.9em}
.section{max-width:1600px;margin:30px auto;padding:0 30px}
.call-block{background:#1a1f2e;border-radius:12px;padding:24px 28px;margin-bottom:44px;border:1px solid #2d3561}
.call-block h2{color:#f0c040;margin:0 0 20px;font-size:1.2em}
.stat-row{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px}
.stat-card{flex:1;min-width:250px;background:#0f1520;border-radius:8px;padding:14px 16px;border:1px solid #2a3050}
.stat-title{font-weight:bold;margin-bottom:8px}
.stat-card ul{margin:0;padding-left:16px;font-size:.86em;line-height:1.85}
.badge{background:#2d3561;color:#7eb8f7;padding:2px 7px;border-radius:4px;font-size:.72em;margin-left:5px}
.plot-label{color:#9aa5c4;font-size:.84em;font-weight:bold;margin:18px 0 6px}
img{width:100%;border-radius:8px;border:1px solid #2d3561;margin-bottom:12px}
hr{border:0;border-top:1px solid #2d3561;margin:22px 0}
.drop-wrap{margin:10px 0 18px}
.drop-header{font-weight:bold;font-size:.88em;margin-bottom:6px}
.drop-table{width:100%;border-collapse:collapse;font-size:.84em}
.drop-table th{background:#2d3561;padding:5px 9px;text-align:left}
.drop-table td{padding:4px 9px;border-bottom:1px solid #1e2540}
.drops-row{display:flex;gap:20px;flex-wrap:wrap}
.drops-row>div{flex:1;min-width:300px}
.no-drop{color:#4caf50;font-size:.88em;margin:8px 0}
.gemini-card{background:#111c2e;border:1px solid #2a5080;border-radius:10px;padding:20px 24px;margin:18px 0 22px}
.gemini-header{color:#7eb8f7;font-weight:bold;font-size:1em;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.gemini-table{width:100%;border-collapse:collapse;font-size:.88em}
.gemini-table td{padding:8px 12px;border-bottom:1px solid #1e3050;vertical-align:top;line-height:1.65}
.gemini-table td.key{color:#9aa5c4;white-space:nowrap;width:130px;font-weight:bold}
.gemini-table tr.highlight td{background:#0d1e30}
.gemini-error{color:#ff6666;padding:10px;background:#200;border-radius:6px;margin:12px 0}
.summary-box{background:#1a2235;border:1px solid #2d5080;border-radius:8px;padding:18px 22px;margin-bottom:28px}
.summary-box h3{color:#7eb8f7;margin:0 0 12px}
.summary-box ul{margin:0;padding-left:18px;font-size:.9em;line-height:1.9}
"""

def build_html(sections):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>iOS vs Android 파형 + Gemini AI 분석 보고서</title>
<style>{CSS}</style>
</head>
<body>
<div class="header">
  <h1>📊 iOS vs Android 통화 녹음 — 파형 + Gemini AI 비교 분석</h1>
  <p>생성: {now} &nbsp;|&nbsp; 기기: iPhone 17 Pro (Opus) vs Samsung SM-S908N (AAC-LC)
     &nbsp;|&nbsp; 앱: com.lguplus.aicallagent &nbsp;|&nbsp; AI: {GEMINI_MODEL}</p>
</div>
<div class="section">
{"".join(sections)}
</div>
</body>
</html>'''


# ════════════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════════════

def main():
    # API 키 로드
    api_key = load_env_key()
    if not api_key:
        print(f"❌ env 파일에서 GEMINI_API_KEY를 찾을 수 없습니다: {ENV_FILE}")
        print("   형식: GEMINI_API_KEY=AIza...")
        sys.exit(1)

    from google import genai
    client = genai.Client(api_key=api_key)
    print(f"✅ Gemini API 연결 완료 (모델: {GEMINI_MODEL})")

    sections = []

    # 전체 요약
    sections.append(f'''
    <div class="summary-box">
      <h3>🔍 분석 방법</h3>
      <ul>
        <li><b>librosa RMS</b>: 프레임 32ms / hop 16ms, 무음 임계 = 평균 RMS × {DROPOUT_RATIO} (64ms 이상 지속 시 드롭아웃)</li>
        <li><b>Gemini {GEMINI_MODEL}</b>: 통화 초반 {GEMINI_CLIP_SEC}초 WAV를 직접 청취 → 음질·음단절·원인 언어 분석</li>
        <li>iOS: Opus 48kHz (앱 내부 녹음, m4a) → 16kHz WAV 변환</li>
        <li>Android: AAC-LC 16kHz (외부 저장소 ixiO 폴더, m4a) → 16kHz WAV 변환</li>
      </ul>
    </div>''')

    total_ios_drops = 0
    total_and_drops = 0

    for call in CALLS:
        print(f"\n{'='*60}")
        print(f"[분석 중] {call['label']}")

        ios_y = load_audio(call['ios'])
        and_y = load_audio(call['android'])
        ios_rms = compute_rms(ios_y)
        and_rms = compute_rms(and_y)
        ios_drops, ios_thresh = detect_dropouts(ios_rms)
        and_drops, and_thresh = detect_dropouts(and_rms)

        print(f"  librosa — iOS: {len(ios_drops)}건, Android: {len(and_drops)}건")
        total_ios_drops += len(ios_drops)
        total_and_drops += len(and_drops)

        # Gemini 분석
        print(f"  Gemini 음성 분석 요청 중... (초반 {GEMINI_CLIP_SEC}초)")
        gemini_result = gemini_analyze(client, call['label'], ios_y, and_y, ios_drops, and_drops)
        if "error" in gemini_result:
            print(f"  ⚠️  Gemini 오류: {gemini_result['error']}")
        else:
            print(f"  ✅ Gemini 응답 완료")
        time.sleep(1)  # rate limit 여유

        # 그래프
        print("  그래프 생성 중...")
        b64_overlay = plot_rms_overlay(call, ios_rms, and_rms)
        b64_early   = plot_early_detail(call, ios_y, and_y, ios_rms, and_rms,
                                        ios_drops, and_drops, ios_thresh, and_thresh)
        b64_full    = plot_full(call, ios_y, and_y, ios_rms, and_rms,
                                ios_drops, and_drops, ios_thresh, and_thresh)

        # 통계 카드
        ios_stat = stats_html(ios_y, ios_rms, ios_drops, "iOS", "#5b9bd5", call['ios_codec'])
        and_stat = stats_html(and_y, and_rms, and_drops, "Android", "#e07b39", call['android_codec'])

        # 음단절 테이블
        ios_dt = dropout_table_html(ios_drops, "iOS", "#5b9bd5")
        and_dt = dropout_table_html(and_drops, "Android", "#e07b39")

        # Gemini 카드
        g_card = gemini_card_html(gemini_result)

        sections.append(f'''
        <div class="call-block">
          <h2>📞 {call["label"]}</h2>
          <div class="stat-row">{ios_stat}{and_stat}</div>
          {g_card}
          <hr>
          <p class="plot-label">▶ iOS vs Android RMS 오버레이</p>
          <img src="data:image/png;base64,{b64_overlay}" alt="RMS Overlay">
          <p class="plot-label">▶ 초반 {EARLY_SEC}초 상세 (빨간 음영 = librosa 감지 음단절)</p>
          <img src="data:image/png;base64,{b64_early}" alt="Early Detail">
          <p class="plot-label">▶ 전체 파형 + 멜 스펙트로그램</p>
          <img src="data:image/png;base64,{b64_full}" alt="Full Waveform">
          <hr>
          <div class="drops-row">
            <div>{ios_dt}</div>
            <div>{and_dt}</div>
          </div>
        </div>''')

    # 종합 결론
    sections.append(f'''
    <div class="summary-box">
      <h3>📝 종합 결론</h3>
      <ul>
        <li>iOS 전체 음단절: <b>{total_ios_drops}건</b> &nbsp;/&nbsp; Android 전체 음단절: <b>{total_and_drops}건</b></li>
        <li>양쪽 동시 발생 → 네트워크/서버 문제 &nbsp;|&nbsp; iOS 단독 → iOS 오디오 레이어 문제 &nbsp;|&nbsp; Android 단독 → Android 측 문제</li>
        <li>Gemini AI가 실제 음성을 듣고 음단절 원인을 언어로 해석 (위 각 통화 Gemini 카드 참조)</li>
      </ul>
    </div>''')

    html = build_html(sections)
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n✅ 보고서 저장 완료: {OUTPUT_HTML}")


if __name__ == '__main__':
    main()
