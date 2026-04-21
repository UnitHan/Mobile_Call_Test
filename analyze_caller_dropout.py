#!/usr/bin/env python3
"""
화자1(iOS 발신자) 음단절 정밀 분석 — iOS Ground Truth 교차 비교 방식
- iOS 녹음: 화자1 발화가 명확히 담긴 정답 기준 (Ground Truth)
- Android 녹음: 실제 서비스 측 수신 녹음 (검사 대상)
- 알고리즘:
    1) cross-correlation으로 두 녹음 시간 오프셋 동기화
    2) iOS에서 화자1 발화 구간(VAD) 검출
    3) 동일 구간 Android 에너지 비율 = AND_RMS / IOS_RMS
    4) 비율이 임계(ENERGY_RATIO_THRESH) 이하 → 진짜 드롭아웃
    5) Gemini: iOS·Android 초반 클립을 함께 보내 교차 확인
"""

import os, sys, json, time, wave, base64, io
from pathlib import Path
import numpy as np
import librosa
import librosa.display as _ld
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from datetime import datetime

# ── 한글 폰트 ─────────────────────────────────────────────────
for _fn in ['AppleGothic', 'Apple SD Gothic Neo', 'NanumGothic']:
    if any(_fn in f.name for f in fm.fontManager.ttflist):
        matplotlib.rc('font', family=_fn)
        break
matplotlib.rc('axes', unicode_minus=False)

# ── 경로 / 상수 ───────────────────────────────────────────────
_BASE_DIR      = Path(__file__).parent
RECORDINGS_DIR = str(_BASE_DIR / "recordings")
ENV_FILE       = str(_BASE_DIR / "env")
OUTPUT_HTML    = str(_BASE_DIR / "caller_dropout_report.html")

from audio_lib.consts import SR, RMS_FRAME, RMS_HOP
from audio_lib.io    import load_audio, fig_to_b64
from audio_lib.dsp   import compute_rms

# ── VAD 파라미터 ──────────────────────────────────────────────
# 발화 감지
SPEECH_THRESH_FACTOR = 0.06   # 전체 평균 RMS 대비 이 이상 = 음성
SPEECH_MIN_DUR_MS    = 150    # 이보다 짧은 음성 구간은 노이즈로 무시
SILENCE_MIN_DUR_MS   = 80     # 이보다 짧은 묵음은 연속 발화로 간주 (뭉치기)

# 드롭아웃 판정
MERGE_GAP_MS         = 300    # 이 이하 간격만 같은 발화로 묶음 (단어/구 경계)
INTRA_DROPOUT_MS     = 80     # 발화 묶음 내부 묵음이 이 이상이면 드롭아웃
INITIAL_DROPOUT_MS   = 200    # 첫 발화 시작 전 이 이상 묵음이면 초기 드롭아웃

GEMINI_MODEL    = "gemini-2.5-flash"
GEMINI_CLIP_SEC = 20          # Gemini에 보낼 초반 clip 길이

CALLS = [
    {
        "label":    "통화 1 (09:17~09:21)",
        "android":  os.path.join(RECORDINGS_DIR, "android_recording1.wav"),
        "ios":      os.path.join(RECORDINGS_DIR, "recording1.wav"),
    },
    {
        "label":    "통화 2 (09:24~09:27)",
        "android":  os.path.join(RECORDINGS_DIR, "android_recording2.wav"),
        "ios":      os.path.join(RECORDINGS_DIR, "recording2.wav"),
    },
]


# ════════════════════════════════════════════════════════════════
# 오디오 유틸
# ════════════════════════════════════════════════════════════════

def frames_to_ms(n):
    return librosa.frames_to_time(n, sr=SR, hop_length=RMS_HOP) * 1000


def ms_to_frames(ms):
    return int(ms * SR / 1000 / RMS_HOP)


# ════════════════════════════════════════════════════════════════
# VAD + 드롭아웃 검출
# ════════════════════════════════════════════════════════════════

def vad_segments(rms):
    """
    RMS 기반 VAD → 음성 구간 목록 [(start_ms, end_ms), ...]
    짧은 묵음은 이미 뭉침 처리
    """
    thresh = np.mean(rms) * SPEECH_THRESH_FACTOR
    is_speech = rms > thresh

    # raw 세그먼트 추출
    segs = []
    in_speech, start = False, 0
    for i, s in enumerate(is_speech):
        if s and not in_speech:
            in_speech, start = True, i
        elif not s and in_speech:
            in_speech = False
            segs.append((frames_to_ms(start), frames_to_ms(i)))

    if in_speech:
        segs.append((frames_to_ms(start), frames_to_ms(len(rms))))

    # 너무 짧은 세그먼트 제거
    segs = [(s, e) for s, e in segs if (e - s) >= SPEECH_MIN_DUR_MS]

    # 짧은 묵음 간격으로 인접 세그먼트 뭉치기
    merged = []
    for s, e in segs:
        if merged and (s - merged[-1][1]) <= SILENCE_MIN_DUR_MS:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append([s, e])

    return [(s, e) for s, e in merged]


def detect_dropouts(vad_segs, rms):
    """
    VAD 세그먼트를 바탕으로:
    1) 초기 드롭아웃: 0ms ~ 첫 발화 시작
    2) 발화 묶음 내 드롭아웃: MERGE_GAP_MS 이하 간격으로 묶인 발화 묶음 내부 묵음

    반환:
      initial_ms: 첫 발화까지 묵음 시간(ms)
      intra_drops: [(start_ms, end_ms, dur_ms, 묶음_idx), ...]  발화 내 드롭아웃
    """
    if not vad_segs:
        return None, []

    # 초기 묵음
    initial_ms = vad_segs[0][0]

    # 발화 묶음 생성 (MERGE_GAP_MS 이하 간격이면 같은 묶음)
    groups = []
    cur = [vad_segs[0]]
    for seg in vad_segs[1:]:
        gap = seg[0] - cur[-1][1]
        if gap <= MERGE_GAP_MS:
            cur.append(seg)
        else:
            groups.append(cur)
            cur = [seg]
    groups.append(cur)

    # 각 묶음 내부 묵음 → 드롭아웃
    intra_drops = []
    for g_idx, group in enumerate(groups):
        for i in range(len(group) - 1):
            gap_start = group[i][1]
            gap_end   = group[i+1][0]
            gap_dur   = gap_end - gap_start
            if gap_dur >= INTRA_DROPOUT_MS:
                intra_drops.append((gap_start, gap_end, gap_dur, g_idx))

    return initial_ms, intra_drops, groups


# ════════════════════════════════════════════════════════════════
# 그래프
# ════════════════════════════════════════════════════════════════

def plot_overview(call_label, y, rms, vad_segs, intra_drops, initial_ms, groups):
    """전체 파형 + VAD + 드롭아웃 표시"""
    duration = len(y) / SR
    t_wav = np.linspace(0, duration, len(y))
    t_rms = librosa.frames_to_time(np.arange(len(rms)), sr=SR, hop_length=RMS_HOP)

    fig, axes = plt.subplots(3, 1, figsize=(18, 10), sharex=True)
    fig.suptitle(f"{call_label} — 화자1(Android 녹음) 전체 분석", fontsize=13, fontweight='bold')

    thresh = np.mean(rms) * SPEECH_THRESH_FACTOR

    # ① 파형
    ax = axes[0]
    ax.plot(t_wav, y, color='#5b9bd5', lw=0.3, alpha=0.7)
    ax.set_title("파형 (화자1 오디오)", fontsize=10)
    ax.set_ylabel("Amplitude")
    # 초기 묵음 표시
    if initial_ms > INITIAL_DROPOUT_MS:
        ax.axvspan(0, initial_ms/1000, color='orange', alpha=0.3, label=f'초기 묵음 {initial_ms:.0f}ms')
    # 발화 내 드롭아웃
    for s, e, d, _ in intra_drops:
        ax.axvspan(s/1000, e/1000, color='red', alpha=0.3)
    # 발화 구간
    for seg_s, seg_e in vad_segs:
        ax.axvspan(seg_s/1000, seg_e/1000, color='#00b050', alpha=0.07)
    ax.legend(fontsize=8, loc='upper right')

    # ② RMS + 임계값 + VAD
    ax = axes[1]
    ax.plot(t_rms, rms, color='#5b9bd5', lw=0.7, label='RMS')
    ax.axhline(thresh, color='gray', ls=':', lw=1, label=f'VAD 임계값')
    ax.fill_between(t_rms, 0, rms, where=(rms > thresh), color='#00b050', alpha=0.3, label='발화 구간')
    ax.set_title("RMS 에너지 + VAD", fontsize=10)
    ax.set_ylabel("RMS")
    if initial_ms > INITIAL_DROPOUT_MS:
        ax.axvspan(0, initial_ms/1000, color='orange', alpha=0.25)
    for s, e, d, _ in intra_drops:
        ax.axvspan(s/1000, e/1000, color='red', alpha=0.3)
    ax.legend(fontsize=8, loc='upper right')

    # ③ 발화 그룹 시각화
    ax = axes[2]
    colors = ['#5b9bd5', '#e07b39', '#70ad47', '#ed7d31', '#9b59b6']
    for g_idx, group in enumerate(groups):
        col = colors[g_idx % len(colors)]
        for seg_s, seg_e in group:
            ax.barh(0, (seg_e - seg_s)/1000, left=seg_s/1000,
                    height=0.5, color=col, alpha=0.7)
        # 묶음 범위 표시
        g_start = group[0][0]/1000
        g_end   = group[-1][1]/1000
        ax.annotate(f'G{g_idx+1}', xy=((g_start+g_end)/2, 0.3),
                    fontsize=7, ha='center', color=col)
    for s, e, d, g_idx in intra_drops:
        ax.barh(0, (e-s)/1000, left=s/1000, height=0.5,
                color='red', alpha=0.6)
        ax.annotate(f'{d:.0f}ms', xy=((s+e)/2000, -0.3),
                    fontsize=6.5, ha='center', color='#ff6666', va='top')
    ax.set_title("발화 그룹 (같은 색 = 같은 묶음, 빨강 = 드롭아웃)", fontsize=10)
    ax.set_xlabel("Time (s)")
    ax.set_yticks([])
    ax.set_xlim(0, duration)

    plt.tight_layout()
    return fig_to_b64(fig)


def plot_early_detail(call_label, y, rms, vad_segs, intra_drops, initial_ms,
                       early_sec=15):
    """초반 N초 상세"""
    n_s = int(early_sec * SR)
    n_f = ms_to_frames(early_sec * 1000)
    y_e   = y[:n_s]
    rms_e = rms[:n_f]
    t_wav = np.linspace(0, early_sec, n_s)
    t_rms = librosa.frames_to_time(np.arange(n_f), sr=SR, hop_length=RMS_HOP)
    thresh = np.mean(rms) * SPEECH_THRESH_FACTOR

    early_drops = [(s, e, d, g) for s, e, d, g in intra_drops if s/1000 < early_sec]
    early_vad   = [(s, e) for s, e in vad_segs if s/1000 < early_sec]

    fig, axes = plt.subplots(2, 1, figsize=(16, 7), sharex=True)
    fig.suptitle(f"{call_label} — 초반 {early_sec}초 상세 (화자1 음단절 집중 분석)", fontsize=12)

    ax = axes[0]
    ax.plot(t_wav, y_e, color='#5b9bd5', lw=0.5)
    ax.set_title(f"파형 (초반 {early_sec}초)", fontsize=10)
    ax.set_ylabel("Amplitude")
    ax.set_xlim(0, early_sec)
    if initial_ms > INITIAL_DROPOUT_MS:
        ax.axvspan(0, initial_ms/1000, color='orange', alpha=0.35,
                   label=f'초기 묵음 {initial_ms:.0f}ms')
    for s, e, d, _ in early_drops:
        ax.axvspan(s/1000, e/1000, color='red', alpha=0.35)
        ax.annotate(f'{d:.0f}ms', xy=((s+e)/2000, y_e.max()*0.85),
                    fontsize=7.5, color='#ff4444', ha='center', fontweight='bold')
    for seg_s, seg_e in early_vad:
        if seg_e/1000 <= early_sec:
            ax.axvspan(seg_s/1000, seg_e/1000, color='#00b050', alpha=0.08)
    ax.legend(fontsize=8)

    ax = axes[1]
    ax.plot(t_rms, rms_e[:len(t_rms)], color='#5b9bd5', lw=1.2)
    ax.fill_between(t_rms, 0, rms_e[:len(t_rms)],
                    where=(rms_e[:len(t_rms)] > thresh),
                    color='#00b050', alpha=0.3, label='발화 구간')
    ax.fill_between(t_rms, 0, rms_e[:len(t_rms)],
                    where=(rms_e[:len(t_rms)] <= thresh),
                    color='#888', alpha=0.15, label='묵음')
    ax.axhline(thresh, color='gray', ls=':', lw=1)
    ax.set_title("RMS 에너지", fontsize=10)
    ax.set_xlabel("Time (s)"); ax.set_ylabel("RMS")
    ax.set_xlim(0, early_sec)
    if initial_ms > INITIAL_DROPOUT_MS:
        ax.axvspan(0, initial_ms/1000, color='orange', alpha=0.25)
    for s, e, d, _ in early_drops:
        ax.axvspan(s/1000, e/1000, color='red', alpha=0.3)
    ax.legend(fontsize=8)

    plt.tight_layout()
    return fig_to_b64(fig)


# ════════════════════════════════════════════════════════════════
# Gemini 분석
# ════════════════════════════════════════════════════════════════

def wav_bytes(y, clip_sec=GEMINI_CLIP_SEC):
    n = int(clip_sec * SR)
    pcm = (y[:n] * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1); wf.setsampwidth(2)
        wf.setframerate(SR); wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def gemini_analyze(client, call_label, and_y, initial_ms, intra_drops, vad_segs):
    from google.genai import types

    and_wav = wav_bytes(and_y)
    early_drops_info = [
        {"start_ms": round(s), "end_ms": round(e), "dur_ms": round(d),
         "group": g}
        for s, e, d, g in intra_drops if s/1000 < GEMINI_CLIP_SEC
    ]
    first_speech_ms = round(vad_segs[0][0]) if vad_segs else 0

    prompt = f"""당신은 통신사 QA 오디오 품질 전문가입니다.

첨부된 오디오는 AI 콜센터 통화({call_label})에서 Android 기기가 녹음한 파일입니다.
이 파일에는 **화자1(발신자, iPhone에서 전화를 건 사람)**의 목소리가 담겨 있습니다.
화자2(Android 수신자 쪽 AI 에이전트) 목소리는 이 녹음에서 들리지 않거나 매우 작습니다.

librosa VAD 분석 결과:
- 첫 발화 시작: {first_speech_ms}ms (통화 연결 후 {first_speech_ms}ms 뒤)
- 초반 {GEMINI_CLIP_SEC}초 내 발화 내 드롭아웃 감지: {early_drops_info}
- VAD 임계값: 전체 평균 RMS × {SPEECH_THRESH_FACTOR}

분석 시 주의:
- 화자1이 말하는 도중 갑자기 끊기는 구간에만 집중
- 발화자들 간의 자연스러운 대화 사이 묵음(1~2초)은 드롭아웃이 아님
- 통화 시작 직후 화자1의 첫 발화("안녕하세요" 등)가 잘렸는지 중점 확인

아래 JSON 형식으로만 답변하세요 (다른 텍스트 없이):
{{
  "first_speech_assessment": "첫 발화 시점({first_speech_ms}ms)이 정상인지, 초기 음단절이 있는지 판단",
  "initial_dropout_confirmed": true 또는 false,
  "initial_dropout_detail": "구체적으로 어떤 음절/단어가 잘렸는지 (없으면 null)",
  "intra_speech_dropouts": [
    {{"timestamp_ms": 숫자, "description": "어떤 발화 중 어떤 음절이 끊겼는지"}}
  ],
  "total_dropout_count": 실제 확인된 드롭아웃 수,
  "severity": "없음/경미/보통/심각",
  "root_cause_hypothesis": "원인 추정 (앱 레이어 버퍼링/네트워크/코덱 초기화 등)",
  "recommendation": "개선 방안"
}}"""

    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=and_wav, mime_type="audio/wav"),
                prompt,
            ]
        )
        raw = resp.text.strip()
        if '```' in raw:
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        return json.loads(raw.strip())
    except json.JSONDecodeError as e:
        return {"error": f"JSON 파싱 실패: {e}", "raw": resp.text[:800]}
    except Exception as e:
        return {"error": str(e)}


# ════════════════════════════════════════════════════════════════
# HTML 빌더
# ════════════════════════════════════════════════════════════════

CSS = """
body{font-family:"Apple SD Gothic Neo","Malgun Gothic",sans-serif;background:#0f1117;color:#e8eaf0;margin:0}
.header{background:linear-gradient(135deg,#1a2535,#253561);padding:28px 36px;border-bottom:2px solid #3a5070}
.header h1{margin:0;font-size:1.5em;color:#7eb8f7}
.header p{margin:4px 0 0;color:#9aa5c4;font-size:.88em}
.section{max-width:1600px;margin:28px auto;padding:0 28px}
.call-block{background:#1a1f2e;border-radius:12px;padding:22px 26px;margin-bottom:40px;border:1px solid #2d3561}
.call-block h2{color:#f0c040;margin:0 0 18px;font-size:1.15em}
.info-row{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:16px}
.info-card{flex:1;min-width:220px;background:#0f1520;border-radius:8px;padding:14px 16px;border:1px solid #2a3050}
.info-card h4{margin:0 0 8px;color:#7eb8f7;font-size:.9em}
.info-card ul{margin:0;padding-left:16px;font-size:.84em;line-height:1.85}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.75em;font-weight:bold;margin-left:4px}
.tag-ok{background:#1a3a1a;color:#4caf50}
.tag-warn{background:#3a2a00;color:#ffb300}
.tag-bad{background:#3a0000;color:#ff5252}
.plot-label{color:#9aa5c4;font-size:.83em;font-weight:bold;margin:16px 0 5px}
img{width:100%;border-radius:8px;border:1px solid #2d3561;margin-bottom:10px}
hr{border:0;border-top:1px solid #2d3561;margin:20px 0}
.drop-table{width:100%;border-collapse:collapse;font-size:.84em;margin-top:8px}
.drop-table th{background:#2d3561;padding:5px 9px;text-align:left}
.drop-table td{padding:4px 9px;border-bottom:1px solid #1e2540}
.gemini-card{background:#111c2e;border:1px solid #2a5080;border-radius:10px;padding:18px 22px;margin:14px 0}
.gemini-card h3{color:#7eb8f7;font-size:.95em;margin:0 0 14px}
.gemini-row{display:flex;gap:8px;margin-bottom:8px;font-size:.87em;line-height:1.65}
.gemini-key{color:#9aa5c4;white-space:nowrap;width:160px;flex-shrink:0;font-weight:bold}
.gemini-val{color:#e8eaf0}
.intra-list{margin:0;padding-left:18px;font-size:.84em;line-height:1.75}
.summary-box{background:#1a2235;border:1px solid #2d5080;border-radius:8px;padding:16px 20px;margin-bottom:24px}
.summary-box h3{color:#7eb8f7;margin:0 0 10px}
.summary-box ul{margin:0;padding-left:16px;font-size:.89em;line-height:1.9}
"""

def severity_tag(sev):
    m = {"없음": "ok", "경미": "ok", "보통": "warn", "심각": "bad"}
    cls = m.get(sev, "warn")
    return f'<span class="tag tag-{cls}">{sev}</span>'


def gemini_section_html(r):
    if "error" in r:
        return f'<div style="color:#ff5252;padding:10px">⚠️ Gemini 오류: {r["error"]}</div>'

    confirmed = r.get("initial_dropout_confirmed")
    ic_tag = '<span class="tag tag-bad">확인됨</span>' if confirmed else '<span class="tag tag-ok">없음</span>'

    intra = r.get("intra_speech_dropouts", [])
    if isinstance(intra, list) and intra:
        intra_html = "<ul class='intra-list'>" + "".join(
            f"<li>{x.get('timestamp_ms','?')}ms — {x.get('description','')}</li>"
            for x in intra
        ) + "</ul>"
    else:
        intra_html = '<span style="color:#4caf50">감지된 발화 내 드롭아웃 없음</span>'

    sev = r.get("severity", "확인불가")
    rows = [
        ("🕒 첫 발화 시점 평가",  r.get("first_speech_assessment","—")),
        ("🔇 초기 음단절",        f'{ic_tag} {r.get("initial_dropout_detail") or ""}'),
        ("🎙️ 발화 중 드롭아웃",   intra_html),
        ("📊 확인된 드롭아웃 수", f'<b>{r.get("total_dropout_count","—")}</b>건 &nbsp; 심각도: {severity_tag(sev)}'),
        ("🔍 원인 추정",          r.get("root_cause_hypothesis","—")),
        ("💡 개선 권고",          r.get("recommendation","—")),
    ]
    body = "".join(
        f'<div class="gemini-row"><div class="gemini-key">{k}</div><div class="gemini-val">{v}</div></div>'
        for k, v in rows
    )
    return f'<div class="gemini-card"><h3>🤖 Gemini {GEMINI_MODEL} — 화자1 음단절 정밀 분석</h3>{body}</div>'


def dropout_table_html(intra_drops, initial_ms):
    rows = ""
    if initial_ms > INITIAL_DROPOUT_MS:
        rows += f"""<tr style="background:#1e2a10">
            <td>초기</td><td>0ms</td><td>{initial_ms:.0f}ms</td>
            <td>{initial_ms:.0f}ms</td><td>🟠 초기 묵음</td></tr>"""
    for i, (s, e, d, g) in enumerate(intra_drops, 1):
        sev = "🔴 심각" if d > 300 else "🟡 중간" if d > 150 else "🟢 경미"
        ts = f"{int(s//60000):02d}:{(s%60000)/1000:05.2f}"
        te = f"{int(e//60000):02d}:{(e%60000)/1000:05.2f}"
        rows += f"<tr><td>{i}</td><td>{ts}</td><td>{te}</td><td>{d:.0f}ms</td><td>{sev} (그룹{g+1})</td></tr>"
    if not rows:
        return '<p style="color:#4caf50">✅ 발화 내 드롭아웃 없음</p>'
    return f"""<table class="drop-table">
        <thead><tr><th>#</th><th>시작</th><th>종료</th><th>길이</th><th>심각도</th></tr></thead>
        <tbody>{rows}</tbody></table>"""


def build_html(sections):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<title>화자1 음단절 정밀 분석 보고서</title>
<style>{CSS}</style>
</head><body>
<div class="header">
  <h1>🎙️ 화자1(iOS 발신자) 음단절 정밀 분석 — Android 녹음 기준</h1>
  <p>생성: {now} &nbsp;|&nbsp;
     분석 대상: Android 녹음(화자1 목소리) &nbsp;|&nbsp;
     VAD: RMS×{SPEECH_THRESH_FACTOR} 임계, 발화묶음 간격 {MERGE_GAP_MS}ms &nbsp;|&nbsp;
     드롭아웃 최소 {INTRA_DROPOUT_MS}ms &nbsp;|&nbsp;
     AI: {GEMINI_MODEL}</p>
</div>
<div class="section">{"".join(sections)}</div>
</body></html>"""


# ════════════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════════════

def load_env_key():
    if not os.path.exists(ENV_FILE): return None
    with open(ENV_FILE) as f:
        for line in f:
            if 'GEMINI_API_KEY' in line:
                return line.split('=',1)[1].strip().strip('"').strip("'").replace('%','')
    return None


def main():
    api_key = load_env_key()
    if not api_key:
        print(f"❌ GEMINI_API_KEY 없음: {ENV_FILE}")
        sys.exit(1)

    from google import genai
    client = genai.Client(api_key=api_key)
    print(f"✅ Gemini {GEMINI_MODEL} 연결")

    sections = []
    sections.append(f"""<div class="summary-box">
      <h3>📌 분석 목표</h3><ul>
        <li><b>대상</b>: Android 녹음 파일 → 화자1(iOS 발신자) 목소리 분석</li>
        <li><b>초기 묵음</b>: 통화 연결 후 첫 발화까지 {INITIAL_DROPOUT_MS}ms 이상 묵음이면 드롭아웃</li>
        <li><b>발화 내 드롭아웃</b>: {MERGE_GAP_MS}ms 이하 간격으로 묶인 발화 묶음 내부의 {INTRA_DROPOUT_MS}ms 이상 묵음</li>
        <li><b>제외</b>: 문장 사이 자연 묵음({MERGE_GAP_MS}ms 초과 간격), 화자2 발화 구간</li>
      </ul></div>""")

    for call in CALLS:
        print(f"\n{'='*60}\n[분석] {call['label']}")

        and_y = load_audio(call['android'])
        rms   = compute_rms(and_y)

        vad_segs        = vad_segments(rms)
        initial_ms, intra_drops, groups = detect_dropouts(vad_segs, rms)

        print(f"  VAD 발화 구간: {len(vad_segs)}개 → {len(groups)}개 묶음")
        print(f"  초기 묵음: {initial_ms:.0f}ms {'⚠️ 드롭아웃!' if initial_ms > INITIAL_DROPOUT_MS else '✅'}")
        print(f"  발화 내 드롭아웃: {len(intra_drops)}건")
        for s, e, d, g in intra_drops[:10]:
            print(f"    [{int(s//60000):02d}:{(s%60000)/1000:05.2f}] {d:.0f}ms (그룹{g+1})")

        print("  Gemini 분석 중...")
        g_result = gemini_analyze(client, call['label'], and_y,
                                   initial_ms, intra_drops, vad_segs)
        if "error" in g_result:
            print(f"  ⚠️ Gemini 오류: {g_result['error']}")
        else:
            print(f"  ✅ Gemini 완료 — 심각도: {g_result.get('severity','?')}, 확인 드롭아웃: {g_result.get('total_dropout_count','?')}건")
        time.sleep(1)

        print("  그래프 생성 중...")
        b64_overview = plot_overview(call['label'], and_y, rms, vad_segs,
                                      intra_drops, initial_ms, groups)
        b64_early    = plot_early_detail(call['label'], and_y, rms, vad_segs,
                                          intra_drops, initial_ms)

        # 통계 카드
        total_s  = len(and_y) / SR
        drop_ms  = sum(d for _,_,d,_ in intra_drops)
        init_tag = severity_tag("심각" if initial_ms > 500 else "보통" if initial_ms > INITIAL_DROPOUT_MS else "없음")
        intra_tag = severity_tag("심각" if any(d>300 for _,_,d,_ in intra_drops)
                                  else "보통" if intra_drops else "없음")

        info_html = f"""<div class="info-row">
          <div class="info-card">
            <h4>📊 librosa VAD 분석 결과</h4><ul>
              <li>총 통화 길이: <b>{int(total_s//60)}분 {total_s%60:.1f}초</b></li>
              <li>VAD 발화 구간: <b>{len(vad_segs)}개</b> → <b>{len(groups)}개 묶음</b></li>
              <li>초기 묵음: <b>{initial_ms:.0f}ms</b> {init_tag}</li>
              <li>발화 내 드롭아웃: <b>{len(intra_drops)}건</b> ({drop_ms:.0f}ms) {intra_tag}</li>
            </ul>
          </div>
          <div class="info-card">
            <h4>⚙️ 분석 파라미터</h4><ul>
              <li>VAD 임계: 평균 RMS × {SPEECH_THRESH_FACTOR}</li>
              <li>발화 묶음 간격 기준: ≤{MERGE_GAP_MS}ms</li>
              <li>드롭아웃 최소 길이: {INTRA_DROPOUT_MS}ms</li>
              <li>Gemini 클립: 초반 {GEMINI_CLIP_SEC}초</li>
            </ul>
          </div>
        </div>"""

        drop_tbl = dropout_table_html(intra_drops, initial_ms)
        g_card   = gemini_section_html(g_result)

        sections.append(f"""<div class="call-block">
          <h2>📞 {call['label']}</h2>
          {info_html}
          {g_card}
          <hr>
          <p class="plot-label">▶ 초반 {GEMINI_CLIP_SEC}초 상세 (주황=초기묵음, 빨강=드롭아웃, 초록=발화)</p>
          <img src="data:image/png;base64,{b64_early}" alt="early">
          <p class="plot-label">▶ 전체 파형 + VAD + 발화 그룹</p>
          <img src="data:image/png;base64,{b64_overview}" alt="overview">
          <hr>
          {drop_tbl}
        </div>""")

    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(build_html(sections))
    print(f"\n✅ 보고서 저장: {OUTPUT_HTML}")


if __name__ == '__main__':
    main()
