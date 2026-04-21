"""
html_report.py
─────────────────────────────────────────────────────────────────────────────
HTML 보고서 생성 유틸리티.

analyze_hybrid.py 에서 분리된 모듈.
"""
from __future__ import annotations

import re
from datetime import datetime

from _hybrid_config import TEST_ENV
from audio_plots import dropout_clip_b64, ms_label, wall_time
from audio_quality import _mos_grade, build_mos_html  # noqa: F401 (re-export)

# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
body{font-family:"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
     background:#0f1117;color:#e8eaf0;margin:0}
.header{background:linear-gradient(135deg,#1a2535,#2a3561);
        padding:28px 36px;border-bottom:2px solid #3a5070}
.header h1{margin:0;font-size:1.5em;color:#7eb8f7}
.header p{margin:5px 0 0;color:#9aa5c4;font-size:.88em;line-height:1.6}
.section{max-width:1700px;margin:28px auto;padding:0 28px}
.call-block{background:#1a1f2e;border-radius:12px;padding:22px 26px;
             margin-bottom:44px;border:1px solid #2d3561}
.call-block h2{color:#f0c040;margin:0 0 16px;font-size:1.15em}
.plot-label{color:#9aa5c4;font-size:.83em;font-weight:bold;margin:16px 0 5px}
img{width:100%;border-radius:8px;border:1px solid #2d3561;margin-bottom:10px}
hr{border:0;border-top:1px solid #2d3561;margin:20px 0}
.g-card{background:#0d1a2e;border:1px solid #2a5080;border-radius:10px;
         padding:20px 24px;margin:14px 0 20px}
.g-card-title{color:#7eb8f7;font-weight:bold;font-size:1em;margin-bottom:16px}
.g-section{margin-bottom:18px}
.g-section-title{color:#9aa5c4;font-size:.82em;text-transform:uppercase;
                  letter-spacing:.05em;margin-bottom:8px;font-weight:bold}
.g-row{display:flex;gap:10px;margin-bottom:8px;font-size:.875em;line-height:1.7}
.g-key{color:#8090b0;white-space:nowrap;width:170px;flex-shrink:0}
.g-val{color:#e8eaf0}
.d-table{width:100%;border-collapse:collapse;font-size:.84em;margin-top:8px;
         table-layout:fixed}
.d-table th{background:#2d3561;padding:6px 10px;text-align:left;font-weight:600;
            overflow:hidden;text-overflow:ellipsis}
.d-table td{padding:5px 10px;border-bottom:1px solid #1e2540;vertical-align:top;
            overflow:hidden;text-overflow:ellipsis}
.d-table col.col-num{width:36px}
.d-table col.col-speaker{width:56px}
.d-table col.col-range{width:96px}
.d-table col.col-dur{width:62px}
.d-table col.col-text{width:auto}
.d-table col.col-corr{width:72px}
.d-table col.col-verdict{width:68px}
.d-table tr:hover td{background:#1a2040}
.tag{display:inline-block;padding:1px 7px;border-radius:3px;font-size:.75em;
     font-weight:bold}
.tag-high{background:#3a0010;color:#ff5252}
.tag-med{background:#3a2a00;color:#ffb300}
.tag-low{background:#1a2a3a;color:#7eb8f7}
.tag-ok{background:#1a3a1a;color:#4caf50}
.wall-time{font-family:monospace;color:#7eb8f7;font-size:.85em}
.env-block{background:#111827;border:1px solid #2d4060;border-radius:10px;
            padding:20px 24px;margin-bottom:26px}
.env-block h3{color:#7eb8f7;margin:0 0 14px;font-size:1em}
.env-table{width:100%;border-collapse:collapse;font-size:.85em}
.env-table td{padding:5px 12px;border-bottom:1px solid #1e2a3a;vertical-align:top}
.env-table td:first-child{color:#8090b0;width:160px;white-space:nowrap}
.env-table tr:last-child td{border-bottom:none}
.total-block{background:#0d1a2e;border:1px solid #3a5070;border-radius:10px;
              padding:20px 24px;margin-bottom:32px}
.total-block h3{color:#f0c040;margin:0 0 14px;font-size:1em}
.total-table{width:100%;border-collapse:collapse;font-size:.86em}
.total-table th{background:#1e2d4a;padding:7px 12px;text-align:left;
                 font-weight:600;white-space:nowrap}
.total-table td{padding:6px 12px;border-bottom:1px solid #1e2540;vertical-align:middle}
.total-table tr:hover td{background:#1a2040}
.total-table tfoot td{background:#1a2a3a;font-weight:bold;color:#f0c040}
.badge-num{display:inline-block;background:#3a2a00;color:#ffd54f;
            border-radius:4px;padding:1px 8px;font-weight:bold;font-size:.9em}
.mos-section{background:#0d1a2e;border:1px solid #2a5080;border-radius:10px;
              padding:22px 26px;margin:28px 0}
.mos-section h3{color:#7eb8f7;margin:0 0 16px;font-size:1em;display:flex;
                 align-items:center;gap:12px;flex-wrap:wrap}
.mos-method{font-size:.76em;color:#607090;font-weight:normal;font-style:italic}
.mos-table{width:100%;border-collapse:collapse;font-size:.86em}
.mos-table th{background:#1e2d4a;padding:8px 12px;text-align:left;
               font-weight:600;white-space:nowrap}
.mos-table td{padding:9px 12px;border-bottom:1px solid #1e2540;vertical-align:middle}
.mos-table tr:hover td{background:#1a2040}
.mos-label{font-weight:600;color:#c8d0f0;white-space:nowrap;min-width:120px}
.mos-os-badge{display:inline-block;padding:1px 7px;border-radius:3px;
               font-size:.75em;font-weight:bold;margin-right:6px}
.ios-badge{background:#1a3a5a;color:#64b5f6}
.and-badge{background:#1a3a1a;color:#81c784}
.mos-bar-wrap{background:#1a2030;border-radius:4px;height:8px;width:160px;
               display:inline-block;vertical-align:middle;margin-right:10px;
               border:1px solid #2d3561}
.mos-bar{height:8px;border-radius:4px;
          background:linear-gradient(90deg,#e53935 0%,#ff9800 40%,#4caf50 80%)}
.mos-bar-visqol{background:linear-gradient(90deg,#880e4f 0%,#ab47bc 40%,#00bcd4 80%)}
.mos-bar-visqol-ios{background:linear-gradient(90deg,#0d47a1 0%,#1976d2 40%,#4fc3f7 80%)}
.mos-score{font-size:1.1em;font-weight:bold;color:#f0c040;margin-right:8px;
            vertical-align:middle;font-family:monospace}
.mos-grade{display:inline-block;padding:2px 9px;border-radius:4px;
            font-size:.78em;font-weight:bold;vertical-align:middle}
.mos-grade-ex  {background:#0d2a0d;color:#4caf50}
.mos-grade-good{background:#1a2a00;color:#8bc34a}
.mos-grade-fair{background:#1a2a10;color:#cddc39}
.mos-grade-avg {background:#2a1a00;color:#ffb300}
.mos-grade-poor{background:#2a1000;color:#ff7043}
.mos-grade-bad {background:#2a0000;color:#ff5252}
.mos-range{font-size:.75em;color:#607090;font-weight:normal}
.mos-note{font-size:.81em;color:#607090;margin:12px 0 0;line-height:1.7}
.anomaly-section{background:#1a0d0d;border:1px solid #5c2020;border-radius:10px;
                  padding:22px 26px;margin:28px 0}
.anomaly-section h3{color:#ff8a80;margin:0 0 16px;font-size:1em;display:flex;
                     align-items:center;gap:12px;flex-wrap:wrap}
.anomaly-method{font-size:.76em;color:#907060;font-weight:normal;font-style:italic}
.anomaly-table{width:100%;border-collapse:collapse;font-size:.86em}
.anomaly-table th{background:#2a1a1a;padding:7px 12px;text-align:left;
                   font-weight:600;white-space:nowrap}
.anomaly-table td{padding:6px 12px;border-bottom:1px solid #2e1a1a;vertical-align:middle}
.anomaly-table tr:hover td{background:#2a1515}
.anomaly-badge{display:inline-block;padding:2px 9px;border-radius:4px;
                font-size:.78em;font-weight:bold}
.anomaly-badge-silence{background:#2a0000;color:#ff5252}
.anomaly-badge-distort{background:#2a1a00;color:#ffb300}
.anomaly-ok{color:#4caf50;font-weight:bold;font-size:.95em}
.anomaly-note{font-size:.81em;color:#907060;margin:12px 0 0;line-height:1.7}
.footer{background:#0a0e1a;border-top:1px solid #2d3561;
        padding:16px 36px;display:flex;align-items:center;justify-content:space-between;
        flex-wrap:wrap;gap:12px;margin-top:40px}
.footer-versions{display:flex;gap:20px;flex-wrap:wrap}
.footer-vitem{display:flex;align-items:center;gap:8px;font-size:.82em;
               color:#8090b0}
.footer-vitem .v-label{color:#6070a0;white-space:nowrap}
.footer-vitem .v-val{font-family:monospace;color:#c8d0e0;font-weight:bold;
                      background:#1a2035;padding:1px 8px;border-radius:3px;
                      border:1px solid #2d3561}
.footer-vitem .v-status{font-size:.75em;color:#4d6080}
.footer-brand{font-size:1em;font-weight:700;letter-spacing:.12em;
               color:#7eb8f7;opacity:.7}
.rec-list{margin:4px 0 0 0;padding-left:18px;font-size:.875em;line-height:1.9;
           color:#e8eaf0}
.rec-list li{margin-bottom:4px}
.recommendation{flex:1}
.sev-none{color:#4caf50}.sev-light{color:#8bc34a}
.sev-mid{color:#ffb300}.sev-high{color:#ff5252}
.meta-row{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:16px}
.meta-card{flex:1;min-width:200px;background:#0f1520;border-radius:8px;
            padding:12px 16px;border:1px solid #2a3050}
.meta-card h4{margin:0 0 8px;color:#7eb8f7;font-size:.88em}
.meta-card ul{margin:0;padding-left:16px;font-size:.83em;line-height:1.9}
.platform-row{display:flex;gap:18px;flex-wrap:wrap;margin:16px 0}
.platform-panel{flex:1;min-width:420px;background:#0f1520;border-radius:10px;
                padding:16px;border:1px solid #2a3050}
.platform-panel h3{margin:0 0 12px;font-size:.95em;color:#7eb8f7}
.platform-panel img{width:100%;border-radius:6px;margin-top:10px}
.summary-box{background:#1a2235;border:1px solid #2d5080;border-radius:8px;
              padding:16px 20px;margin-bottom:24px}
.summary-box h3{color:#7eb8f7;margin:0 0 10px;font-size:1em}
.summary-box ul{margin:0;padding-left:16px;font-size:.88em;line-height:1.9}
"""


# ─────────────────────────────────────────────────────────────────────────────
# HTML 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def sev_class(s: str) -> str:
    return {'없음': 'sev-none', '경미': 'sev-light',
            '보통': 'sev-mid', '심각': 'sev-high'}.get(s, 'sev-mid')


# ─────────────────────────────────────────────────────────────────────────────
# 대본 기반 음단절 탐지 카드 HTML
# ─────────────────────────────────────────────────────────────────────────────

def dropout_card_html(result: dict, start_time: str = "",
                      platform: str = "Android",
                      speaker_filter: 'str | list[str] | None' = None,
                      test_y: 'np.ndarray | None' = None) -> str:  # noqa: ARG001
    """script_gap_detector.analyze_by_script() 복규조 결과 → HTML 카드.

    speaker_filter: 지정 시 해당 화자의 대사만 표시 (예: '철수' 또는 ['박편육', '임채팅']).
    test_y: 수신 녹음 오디오 배열 — 지정 시 각 대사 행에 ±1.5초 오디오 플레이어 표시.
    """
    import numpy as np
    if not result:
        return ''

    lines          = result.get('lines', [])

    # 화자 필터링: 해당 화자의 대사만 표시하여 가독성 향상
    if speaker_filter:
        if isinstance(speaker_filter, str):
            speaker_filter = [speaker_filter]
        _filter_set = set(speaker_filter)
        lines = [l for l in lines if l.get('speaker') in _filter_set]

    # 필터링된 결과로 요약 재계산
    if speaker_filter:
        n_compared = len(lines)
        n_dropped  = sum(1 for l in lines if l.get('dropped', False))
        drop_rate  = round(n_dropped / n_compared * 100, 1) if n_compared else 0.0
    else:
        n_compared = result.get('compared', 0)
        n_dropped  = result.get('dropped_count', 0)
        drop_rate  = result.get('drop_rate_pct', 0.0)

    sev            = result.get('severity', '없음')
    offset_sec     = result.get('offset_sec', 0.0)
    corr_th        = result.get('corr_threshold', 0.30)
    ref_name       = result.get('ref', '정답지')
    test_name      = result.get('test', f'{platform} 수신파일')

    # 대사별 테이블
    if lines:
        rows = ""
        for row_num, r in enumerate(lines, 1):
            is_drop  = r.get('dropped', False)
            badge    = ('<span class="tag tag-high">❌ 음단절</span>' if is_drop
                        else '<span class="tag tag-ok">✅ 정상</span>')
            txt      = r.get('text', '')
            txt_s    = txt[:60] + ('…' if len(txt) > 60 else '')
            corr_val = r.get('max_corr', 0.0)
            corr_col = '#ff5252' if is_drop else ('#ffb300' if corr_val < 0.6 else '#4caf50')

            # 오디오 클립: test_best_s 기준 ±1.5초 (수신 녹음 오디오)
            audio_cell = '<td></td>'
            audio_subrow = ''
            if test_y is not None and isinstance(test_y, np.ndarray) and len(test_y) > 0:
                try:
                    best_s   = r.get('test_best_s', r.get('ref_start_s', 0.0))
                    dur_ms   = r.get('ref_dur_ms', 0.0)
                    start_ms = int(best_s * 1000)
                    end_ms   = start_ms + int(dur_ms)
                    b64 = dropout_clip_b64(test_y, start_ms, end_ms, pad_ms=1500)
                    color = '#64b5f6' if platform == 'iOS' else '#ef9a9a'
                    audio_cell = (
                        f'<td style="text-align:center">'
                        f'<button onclick="this.nextElementSibling.style.display='
                        f"'block';this.style.display='none'\" "
                        f'style="background:none;border:none;cursor:pointer;font-size:1.2em">🔊</button>'
                        f'<audio controls style="width:140px;height:28px;display:none">'
                        f'<source src="data:audio/wav;base64,{b64}" type="audio/wav"></audio>'
                        f'</td>'
                    )
                    audio_subrow = (
                        f'<tr style="background:#0e1720">'
                        f'<td colspan="8" style="padding:6px 16px">'
                        f'<span style="font-size:.76em;color:{color};font-weight:600">'
                        f'🔊 {platform} — {best_s:.3f}s ~ {best_s + dur_ms/1000:.3f}s ±1.5초</span>'
                        f'</td></tr>'
                    )
                except Exception:
                    pass

            rows += (
                f'<tr>'
                f'<td style="text-align:center">{row_num}</td>'
                f'<td style="color:#c8d0f0">{r["speaker"]}</td>'
                f'<td style="font-family:monospace">'
                f'{r["ref_start_s"]:.1f}–{r["ref_end_s"]:.1f}s</td>'
                f'<td style="text-align:center">{r["ref_dur_ms"]:.0f}ms</td>'
                f'<td style="font-size:.85em;color:#a0b0d0;font-style:italic">{txt_s}</td>'
                f'<td style="text-align:center;font-family:monospace;'
                f'color:{corr_col}">{corr_val:+.3f}</td>'
                f'<td style="text-align:center">{badge}</td>'
                f'{audio_cell}'
                f'</tr>'
            )

        has_audio = test_y is not None and isinstance(test_y, np.ndarray) and len(test_y) > 0
        audio_th = '<th>청취</th>' if has_audio else ''
        table_html = (
            '<table class="d-table">'
            '<colgroup>'
            '<col class="col-num"><col class="col-speaker"><col class="col-range">'
            '<col class="col-dur"><col class="col-text"><col class="col-corr">'
            '<col class="col-verdict">'
            + ('<col style="width:60px">' if has_audio else '') +
            '</colgroup>'
            '<thead><tr><th>#</th><th>화자</th><th>정답지 구간</th>'
            '<th>길이</th><th>대사</th><th>상관계수</th><th>판정</th>'
            f'{audio_th}'
            '</tr></thead>'
            f'<tbody>{rows}</tbody>'
            '</table>'
        )
    else:
        table_html = ('<p style="color:#888">정답지 파일 또는 대본 구간이 없어 분석을 건너뜁니다.</p>')

    sev_color = {
        '없음': '#4caf50', '경미': '#8bc34a', '보통': '#ffb300', '심각': '#ff5252',
    }.get(sev, '#aaa')

    _icon = '🤖' if platform == 'Android' else '🍎'
    return f"""<div class="g-card">
      <div class="g-card-title">{_icon} {platform} — 대본 기반 문장 단위 음단절 탐지</div>

      <div class="g-section">
        <div class="g-section-title">🔍 탐지 방식</div>
        <div style="font-size:.87em;color:#9aa5c4;line-height:1.9">
          정답지 TTS(audiomass) WAV를 VAD로 발화 구간으로 분절하고,<br>
          {platform} 수신파일에서 해당 구간을 에너지 엔벨로프 cross-correlation으로 탐색합니다.<br>
          <b>음단절 조건</b>: 정답지가 발화 중일 때 {platform} 수신기에 해당 음성이 보이지 않음 (corr &lt; {corr_th:.2f})<br>
          <span style="color:#ff9800"><b>⚠ 음질 저하(볼륨 감소/잃음/지연)는 음단절로 판정하지 않습니다.</b></span>
        </div>
      </div>

      <div class="g-section">
        <div class="g-section-title">📋 분석 요약</div>
        <div class="g-row"><div class="g-key">정답지</div>
          <div class="g-val" style="font-family:monospace;font-size:.9em">{ref_name}</div></div>
        <div class="g-row"><div class="g-key">검사 대상</div>
          <div class="g-val" style="font-family:monospace;font-size:.9em">{test_name}</div></div>
        <div class="g-row"><div class="g-key">전역 정렬 오프셋</div>
          <div class="g-val"><span style="font-family:monospace">{offset_sec:+.3f}s</span></div></div>
        {"" if not speaker_filter else f'''<div class="g-row"><div class="g-key">대상 화자</div>
          <div class="g-val"><b style="color:#c8d0f0">{", ".join(speaker_filter) if isinstance(speaker_filter, list) else speaker_filter}</b></div></div>'''}
        <div class="g-row"><div class="g-key">비교 대사 수</div>
          <div class="g-val"><b>{n_compared}</b> 개</div></div>
        <div class="g-row"><div class="g-key">음단절 탐지</div>
          <div class="g-val"><b style="color:{sev_color}">{n_dropped}건</b>
          &nbsp;({drop_rate:.1f}%)</div></div>
        <div class="g-row"><div class="g-key">심각도</div>
          <div class="g-val"><b class="{sev_class(sev)}">{sev}</b></div></div>
      </div>

      <div class="g-section">
        <div class="g-section-title">🎤 대사별 판정 결과</div>
        {table_html}
      </div>
    </div>"""


def conf_tag(c: str) -> str:
    cls   = {'high': 'tag-high', 'medium': 'tag-med', 'low': 'tag-low'}.get(c, 'tag-low')
    label = {'high': '확신', 'medium': '의심', 'low': '가능성'}.get(c, c)
    return f'<span class="tag {cls}">{label}</span>'


def format_recommendation(text: str) -> str:
    """'1. ... 2. ... 3. ...' 형태 텍스트를 줄바꿈된 HTML로 변환."""
    if not text or text == '—':
        return text
    parts = re.split(r'(?=\d+\.\s)', text.strip())
    items = [p.strip() for p in parts if p.strip()]
    if len(items) <= 1:
        return text
    return '<ol class="rec-list">' + "".join(
        f'<li>{item[item.index(".")+1:].strip()}</li>'
        if re.match(r'^\d+\.', item) else f'<li>{item}</li>'
        for item in items
    ) + '</ol>'


def _platform_badge(p: str) -> str:
    colors = {
        "수신만": "#e53935", "Android수신": "#e53935",
        "로컬만": "#607d8b", "iPhone로컬":  "#607d8b",
        "양쪽":  "#ff6b35",
        "iOS":   "#607d8b", "Android": "#e53935",
    }
    labels = {
        "수신만": "수신(Android)", "Android수신": "수신(Android)",
        "로컬만": "로컬(iPhone)",  "iPhone로컬":  "로컬(iPhone)",
        "양쪽":  "양쪽",
        "iOS":   "로컬(iPhone)",  "Android": "수신(Android)",
    }
    c     = colors.get(p, "#888")
    label = labels.get(p, p)
    return (f'<span style="background:{c};color:#fff;font-size:.75em;'
            f'padding:1px 7px;border-radius:10px;font-weight:600">{label}</span>')


# ─────────────────────────────────────────────────────────────────────────────
# Gemini 카드 HTML
# ─────────────────────────────────────────────────────────────────────────────

def gemini_card_html(result: dict, start_time: str = "",
                     ios_y=None, and_y=None) -> str:
    if "error" in result:
        return (f'<div style="color:#ff5252;padding:12px;background:#200;'
                f'border-radius:6px">⚠️ Gemini 오류: {result["error"]}</div>')

    init = result.get("initial_dropout", {})
    mid  = result.get("mid_call_dropouts", [])
    sev  = result.get("severity", "확인불가")

    local_det  = init.get("local_detected",
                          init.get("ios_detected", init.get("detected", False)))
    remote_det = init.get("remote_detected",
                          init.get("android_detected", init.get("detected", False)))
    if local_det or remote_det:
        loc_ms  = init.get('local_first_ms',
                           init.get('ios_first_audible_ms',
                           init.get('first_audible_in_ios_ms', 0)))
        rem_ms  = init.get('remote_first_ms',
                           init.get('android_first_audible_ms',
                           init.get('first_audible_in_android_ms', 0)))
        drop_ms = init.get('duration_ms', 0)
        wt_loc  = wall_time(start_time, loc_ms)
        wt_rem  = wall_time(start_time, rem_ms)
        loc_tag = ('<span class="tag tag-high">음단절</span>' if local_det
                   else '<span class="tag tag-ok">정상</span>')
        rem_tag = ('<span class="tag tag-high">음단절</span>' if remote_det
                   else '<span class="tag tag-ok">정상</span>')
        init_audio_html = ""
        if ios_y is not None and and_y is not None:
            end_ms   = max(loc_ms, rem_ms) + 2000
            ios_ib64 = dropout_clip_b64(ios_y, 0, end_ms, pad_ms=0)
            and_ib64 = dropout_clip_b64(and_y, 0, end_ms, pad_ms=0)
            init_audio_html = f"""
        <div class="g-row"><div class="g-key">🔊 직접 청취<br>\
<small style="color:#aaa;font-weight:normal">통화 시작 구간</small></div>
          <div class="g-val" style="padding:8px 0">
            <div style="display:flex;gap:16px;flex-wrap:wrap">
              <div style="min-width:220px;flex:1">
                <div style="font-size:.76em;color:#64b5f6;font-weight:600;margin-bottom:4px">\
📱 로컬(iPhone) — 기준</div>
                <audio controls style="width:100%;height:36px">\
<source src="data:audio/wav;base64,{ios_ib64}" type="audio/wav"></audio>
              </div>
              <div style="min-width:220px;flex:1">
                <div style="font-size:.76em;color:#ef9a9a;font-weight:600;margin-bottom:4px">\
🤖 수신(Android) — 진단대상</div>
                <audio controls style="width:100%;height:36px">\
<source src="data:audio/wav;base64,{and_ib64}" type="audio/wav"></audio>
              </div>
            </div>
          </div></div>"""
        init_html = f"""
        <div class="g-row">
          <div class="g-key">로컬(iPhone)<br>\
<small style="color:#aaa;font-weight:normal">기준 파일</small></div>
          <div class="g-val">{loc_tag}&nbsp; {ms_label(loc_ms)}
            <span class="wall-time">≈ {wt_loc}</span></div></div>
        <div class="g-row">
          <div class="g-key">수신(Android)<br>\
<small style="color:#e57373;font-weight:normal">진단 대상 · iOS ixi-O 발화</small></div>
          <div class="g-val">{rem_tag}&nbsp; {ms_label(rem_ms)}
            <span class="wall-time">≈ {wt_rem}</span></div></div>
        <div class="g-row"><div class="g-key">누락 발화</div>
          <div class="g-val"><b>{init.get('cut_content', '?')}</b></div></div>
        <div class="g-row"><div class="g-key">수신측 손실</div>
          <div class="g-val"><b>{drop_ms:.0f}ms</b></div></div>
        {init_audio_html}"""
    else:
        init_html = ('<div class="g-val">'
                     '<span class="tag tag-ok">초기 음단절 없음 (로컬·수신 모두)</span>'
                     '</div>')

    if mid:
        rows = ""
        for i, d in enumerate(mid, 1):
            ts_ms      = d.get('timestamp_ref_ms', d.get('timestamp_ios_ms', 0))
            dur_ms     = d.get('duration_ms', 0)
            wt         = wall_time(start_time, ts_ms)
            dropout_in = d.get('dropout_in', d.get('platform', '—'))
            loc_txt    = d.get('local_actual',  d.get('ios_actual',     d.get('ios_content', '—')))
            rem_txt    = d.get('remote_actual', d.get('android_actual', d.get('android_content', '—')))
            expected   = d.get('script_expected', '—')
            verdict    = d.get('gemini_verdict', '')
            reason     = d.get('gemini_reason', '')
            if verdict == 'confirmed':
                verdict_badge = (
                    f'<span title="{reason}" style="cursor:help;font-size:.75em;'
                    'font-weight:700;background:#1b4332;color:#6ee7b7;'
                    'padding:2px 7px;border-radius:10px">✅ 확인</span>')
            elif verdict == 'false_positive':
                verdict_badge = (
                    f'<span title="{reason}" style="cursor:help;font-size:.75em;'
                    'font-weight:700;background:#3b1515;color:#fca5a5;'
                    'padding:2px 7px;border-radius:10px">❌ 오탐</span>')
            elif verdict == 'uncertain':
                verdict_badge = (
                    f'<span title="{reason}" style="cursor:help;font-size:.75em;'
                    'font-weight:700;background:#292524;color:#fcd34d;'
                    'padding:2px 7px;border-radius:10px">❓ 불확실</span>')
            else:
                verdict_badge = '<span style="color:#555;font-size:.75em">—</span>'

            audio_row_html = ""
            if ios_y is not None and and_y is not None:
                end_ms   = ts_ms + max(dur_ms, 100)
                ios_cb64 = dropout_clip_b64(ios_y, ts_ms, end_ms)
                and_cb64 = dropout_clip_b64(and_y, ts_ms, end_ms)
                uid = f"arow-{abs(id(result))}-{i}"
                audio_row_html = (
                    f'<tr id="{uid}" style="background:#0e1720">'
                    '<td colspan="9" style="padding:10px 20px">'
                    '<div style="display:flex;gap:16px;flex-wrap:wrap">'
                    '<div style="min-width:220px;flex:1">'
                    '<div style="font-size:.76em;color:#64b5f6;font-weight:600;margin-bottom:4px">'
                    '📱 로컬(iPhone) — 기준 · ±2초 컨텍스트</div>'
                    f'<audio controls style="width:100%;height:36px">'
                    f'<source src="data:audio/wav;base64,{ios_cb64}" type="audio/wav"></audio></div>'
                    '<div style="min-width:220px;flex:1">'
                    '<div style="font-size:.76em;color:#ef9a9a;font-weight:600;margin-bottom:4px">'
                    '🤖 수신(Android) — 진단대상 · ±2초 컨텍스트</div>'
                    f'<audio controls style="width:100%;height:36px">'
                    f'<source src="data:audio/wav;base64,{and_cb64}" type="audio/wav"></audio></div>'
                    '</div></td></tr>'
                )
            rows += f"""<tr>
              <td style="text-align:center">{i}</td>
              <td style="font-family:monospace">{ms_label(ts_ms)}</td>
              <td><span class="wall-time">{wt}</span></td>
              <td style="text-align:center">{dur_ms:.0f}ms</td>
              <td style="color:#a0c4ff;font-style:italic">{expected}</td>
              <td>{loc_txt}</td>
              <td>{rem_txt}</td>
              <td style="text-align:center">{_platform_badge(dropout_in)}</td>
              <td>{conf_tag(d.get('confidence','low'))}</td>
              <td style="text-align:center">{verdict_badge}</td>
            </tr>{audio_row_html}"""
        mid_html = f"""<table class="d-table">
          <thead><tr><th>#</th><th>오프셋</th><th>발생시각</th><th>손실길이</th>
            <th>대본(예상)</th>
            <th>로컬(iPhone) · 기준</th>
            <th>수신(Android) · 진단대상</th>
            <th>음단절 위치</th><th>확신도</th><th>Gemini 검증</th></tr></thead>
          <tbody>{rows}</tbody></table>"""
    else:
        mid_html = '<p style="color:#4caf50;margin:4px 0">✅ 발화 중 드롭아웃 없음</p>'

    pain_points = result.get('dev_pain_points', [])
    if pain_points:
        pp_items = "".join(
            f'<li style="margin-bottom:6px">{p}</li>' for p in pain_points
        )
        pain_html = (
            f'<ul style="margin:4px 0;padding-left:18px;font-size:.86em;line-height:1.8">'
            f'{pp_items}</ul>'
        )
    else:
        pain_html = '<span style="color:#888">—</span>'

    src = result.get("detection_source", "gemini-only")
    if src == "energy_align+gemini(audio)":
        src_badge = (
            '<span style="font-size:.72em;font-weight:600;background:#1a3a2a;'
            'color:#69f0ae;padding:2px 8px;border-radius:12px;margin-left:8px;'
            'vertical-align:middle">⚡ EnergyAlign+Gemini청음</span>')
    elif src in ("whisper+librosa+gemini(audio)", "whisper+librosa+gemini"):
        src_badge = (
            '<span style="font-size:.72em;font-weight:600;background:#1a3a5c;'
            'color:#64b5f6;padding:2px 8px;border-radius:12px;margin-left:8px;'
            'vertical-align:middle">🎙️ Whisper+librosa+Gemini청음</span>')
    else:
        src_badge = (
            '<span style="font-size:.72em;font-weight:600;background:#2a2a2a;'
            'color:#aaa;padding:2px 8px;border-radius:12px;margin-left:8px;'
            'vertical-align:middle">Gemini 단독</span>')

    return f"""<div class="g-card">
      <div class="g-card-title">⚡ EnergyAlign + librosa — iOS ixi-O 앱 진단 결과{src_badge}</div>

      <div class="g-section">
        <div class="g-section-title">📋 iOS ixi-O 앱 진단 요약</div>
        <div style="font-size:.88em;line-height:1.7;color:#c8d0e0">
          {result.get('listening_summary','—')}</div>
      </div>

      <div class="g-section">
        <div class="g-section-title">🕐 통화 시작 초기 음단절</div>
        {init_html}
      </div>

      <div class="g-section">
        <div class="g-section-title">🎙️ 발화 중 드롭아웃 ({len(mid)}건)</div>
        {mid_html}
      </div>

      <div class="g-section">
        <div class="g-row"><div class="g-key">기술적 원인</div>
          <div class="g-val">{result.get('root_cause','—')}</div></div>
        <div class="g-row"><div class="g-key">심각도</div>
          <div class="g-val"><b class="{sev_class(sev)}">{sev}</b></div></div>
      </div>

      <div class="g-section">
        <div class="g-section-title">🔧 개발팀 점검 항목 (Pain Points)</div>
        {pain_html}
      </div>
    </div>"""


# ─────────────────────────────────────────────────────────────────────────────
# 환경 / 요약 / HTML 빌드
# ─────────────────────────────────────────────────────────────────────────────

def build_env_html(now: str) -> str:
    env = dict(TEST_ENV)
    if not env.get("테스트 일시"):
        env["테스트 일시"] = now
    rows = "".join(
        f'<tr><td>{k}</td><td><b>{v}</b></td></tr>'
        for k, v in env.items() if v
    )
    return f"""
    <div class="env-block">
      <h3>🛠️ 테스트 환경 정보</h3>
      <table class="env-table"><tbody>{rows}</tbody></table>
    </div>"""


def _dropout_time_cell(lines: list, start_time: str) -> str:
    """음단절 발생 대사의 정답지 시간 → '녹음 시작+offset' 추정 시각 태그 HTML."""
    dropped = [ln for ln in lines if ln.get('dropped')]
    if not dropped:
        return '<span style="color:#4caf50;font-size:.85em">없음</span>'
    parts = []
    for ln in dropped:
        ref_s = ln.get('ref_start_s', 0)
        ref_e = ln.get('ref_end_s', 0)
        # 정답지 기준 시간 (녹음 내 상대시간)
        rel = f"{ref_s:.1f}~{ref_e:.1f}s"
        # 녹음 시작 시각 + offset → 추정 발생 시각
        abs_t = _wall_time(start_time, ref_s)
        txt_snip = (ln.get('text', '')[:20] + '…') if len(ln.get('text', '')) > 20 else ln.get('text', '')
        parts.append(
            f'<span class="tag tag-high" title="{txt_snip}">'
            f'{abs_t} ({rel})</span>'
        )
    return ' '.join(parts)


def _wall_time(start_hms: str, offset_sec: float) -> str:
    """start_hms('HH:MM:SS') + offset_sec → 'HH:MM:SS'."""
    if not start_hms:
        return "—"
    try:
        parts = start_hms.replace('.', ':').split(':')
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
        total = h * 3600 + m * 60 + s + offset_sec
        th = int(total // 3600)
        tm = int((total % 3600) // 60)
        ts = int(total % 60)
        return f"{th:02d}:{tm:02d}:{ts:02d}"
    except Exception:
        return "—"


def build_total_table(all_results: list) -> str:
    """음원별 드롭아웃 집계 + 전체 합계 테이블."""
    total_and_dropped = 0
    total_ios_dropped = 0
    rows = ""
    for call, result in all_results:
        if "error" in result:
            continue

        if result.get('_type') == 'script_corr':
            # 대본 cross-correlation 방식
            and_n     = result.get('and_dropped_count', result.get('dropped_count', 0))
            and_comp  = result.get('compared', 0)
            and_sev   = result.get('and_severity', result.get('severity', '—'))
            ios_n     = result.get('ios_dropped_count', 0)
            ios_comp  = result.get('ios_compared', 0)
            ios_sev   = result.get('ios_severity', '—')
            total_and_dropped += and_n
            total_ios_dropped += ios_n
            and_cell = f'<span class="badge-num">{and_n}/{and_comp}</span>'
            ios_cell = (f'<span class="badge-num">{ios_n}/{ios_comp}</span>'
                        if ios_comp else '<span style="color:#607090;font-size:.85em">—</span>')
            # 음단절 발생 시간 (정답지 기준 sec → HH:MM:SS)
            and_times = _dropout_time_cell(
                result.get('lines', []), call.get('start_time', ''))
            ios_times = _dropout_time_cell(
                result.get('ios_lines', []), call.get('start_time', ''))
        else:
            # 구형 포맷 (gemini/energy_align)
            init  = result.get("initial_dropout", {})
            mid   = result.get("mid_call_dropouts", [])
            has_init = bool(init.get("detected"))
            and_n = (1 if has_init else 0) + len(mid)
            and_sev = result.get("severity", "—")
            ios_n = 0
            ios_sev = '—'
            total_and_dropped += and_n
            and_cell = f'<span class="badge-num">{and_n}</span>'
            ios_cell = '<span style="color:#607090;font-size:.85em">—</span>'
            and_times = '<span style="color:#607090;font-size:.85em">—</span>'
            ios_times = '<span style="color:#607090;font-size:.85em">—</span>'

        rows += f"""<tr>
          <td>{call['label']}</td>
          <td>{call.get('speakers','—')}</td>
          <td style="font-family:monospace">{call.get('start_time','—')}</td>
          <td style="text-align:center">{and_cell}</td>
          <td style="font-size:.85em">{and_times}</td>
          <td><b class="{sev_class(and_sev)}">{and_sev}</b></td>
          <td style="text-align:center">{ios_cell}</td>
          <td style="font-size:.85em">{ios_times}</td>
          <td><b class="{sev_class(ios_sev)}">{ios_sev}</b></td>
        </tr>"""
    tfoot = f"""<tr>
      <td colspan="3">합계</td>
      <td style="text-align:center"><span class="badge-num">{total_and_dropped}</span></td>
      <td></td><td>—</td>
      <td style="text-align:center"><span class="badge-num">{total_ios_dropped}</span></td>
      <td></td><td>—</td>
    </tr>"""
    return f"""
    <div class="total-block">
      <h3>📋 전체 음단절 발생 현황 요약</h3>
      <table class="total-table">
        <thead><tr>
          <th>음원</th><th>화자</th><th>녹음 시작</th>
          <th>🤖 Android</th><th>발생 시간</th><th>심각도</th>
          <th>🍎 iOS</th><th>발생 시간</th><th>심각도</th>
        </tr></thead>
        <tbody>{rows}</tbody>
        <tfoot>{tfoot}</tfoot>
      </table>
    </div>"""


def build_anomaly_html(anomaly_rows: list) -> str:
    """오디오 이상 검출(묵음/깨짐) 결과 HTML 섹션 생성.
    anomaly_rows: [(label, ios_events, and_events[, ios_y, and_y]), ...]
    """
    import numpy as np
    if not anomaly_rows:
        return ''

    # 이상이 하나라도 있는지 확인
    has_any = any(item[1] or item[2] for item in anomaly_rows)

    rows_html = ''
    for item in anomaly_rows:
        label, ios_events, and_events = item[0], item[1], item[2]
        ios_y = item[3] if len(item) > 3 else None
        and_y = item[4] if len(item) > 4 else None

        def _audio_subrow(y, ev, platform_label, colspan=8):
            """이상 구간 ±0.5초 오디오 클립 서브행 생성."""
            if y is None or not isinstance(y, np.ndarray) or len(y) == 0:
                return ''
            try:
                start_ms = int(ev['start_s'] * 1000)
                end_ms   = int(ev['end_s']   * 1000)
                b64 = dropout_clip_b64(y, start_ms, end_ms, pad_ms=500)
                color = '#64b5f6' if platform_label == 'iOS' else '#ef9a9a'
                return (
                    f'<tr style="background:#0e1720">'
                    f'<td colspan="{colspan}" style="padding:8px 16px">'
                    f'<div style="font-size:.76em;color:{color};font-weight:600;margin-bottom:4px">'
                    f'🔊 {platform_label} — {ev["start_s"]:.3f}s ~ {ev["end_s"]:.3f}s ±0.5초 컨텍스트</div>'
                    f'<audio controls style="width:100%;max-width:520px;height:36px">'
                    f'<source src="data:audio/wav;base64,{b64}" type="audio/wav"></audio>'
                    f'</td></tr>'
                )
            except Exception:
                return ''

        # iOS 이벤트 행 — 이벤트 행 먼저 rowspan으로 묶고, 오디오 플레이어는 이벤트 행 이후 전부 배치(colspan=8)
        if ios_events:
            ios_rowspan = len(ios_events)
            for i_ev, ev in enumerate(ios_events):
                badge_cls = 'anomaly-badge-silence' if ev['type'] == '묵음' else 'anomaly-badge-distort'
                label_cell = (
                    f'<td class="mos-label" rowspan="{ios_rowspan}" style="vertical-align:middle">{label}</td>'
                    f'<td rowspan="{ios_rowspan}" style="vertical-align:middle"><span class="mos-os-badge ios-badge">iOS</span></td>'
                    if i_ev == 0 else ''
                )
                rows_html += f"""<tr>
                  {label_cell}
                  <td><span class="anomaly-badge {badge_cls}">{ev['type']}</span></td>
                  <td style="font-family:monospace">{ev['duration_ms']:.0f} ms</td>
                  <td style="font-family:monospace">{ev['start_s']:.3f}s ~ {ev['end_s']:.3f}s</td>
                  <td style="font-family:monospace">{ev['gain_db']:.1f} dB</td>
                  <td style="font-family:monospace">{ev['correlation']:.4f}</td>
                  <td></td>
                </tr>"""
            for ev in ios_events:
                rows_html += _audio_subrow(ios_y, ev, 'iOS')
        else:
            rows_html += f"""<tr>
              <td class="mos-label">{label}</td>
              <td><span class="mos-os-badge ios-badge">iOS</span></td>
              <td colspan="6"><span class="anomaly-ok">✅ 이상 없음</span></td>
            </tr>"""

        # Android 이벤트 행 — 이벤트 행 먼저 rowspan으로 묶고, 오디오 플레이어는 이벤트 행 이후 전부 배치(colspan=8)
        if and_events:
            and_rowspan = len(and_events)
            for i_ev, ev in enumerate(and_events):
                badge_cls = 'anomaly-badge-silence' if ev['type'] == '묵음' else 'anomaly-badge-distort'
                label_cell = (
                    f'<td class="mos-label" rowspan="{and_rowspan}" style="vertical-align:middle">{label}</td>'
                    f'<td rowspan="{and_rowspan}" style="vertical-align:middle"><span class="mos-os-badge and-badge">Android</span></td>'
                    if i_ev == 0 else ''
                )
                rows_html += f"""<tr>
                  {label_cell}
                  <td><span class="anomaly-badge {badge_cls}">{ev['type']}</span></td>
                  <td style="font-family:monospace">{ev['duration_ms']:.0f} ms</td>
                  <td style="font-family:monospace">{ev['start_s']:.3f}s ~ {ev['end_s']:.3f}s</td>
                  <td style="font-family:monospace">{ev['gain_db']:.1f} dB</td>
                  <td style="font-family:monospace">{ev['correlation']:.4f}</td>
                  <td></td>
                </tr>"""
            for ev in and_events:
                rows_html += _audio_subrow(and_y, ev, 'Android')
        else:
            rows_html += f"""<tr>
              <td class="mos-label">{label}</td>
              <td><span class="mos-os-badge and-badge">Android</span></td>
              <td colspan="6"><span class="anomaly-ok">✅ 이상 없음</span></td>
            </tr>"""

    total_ios = sum(len(item[1]) for item in anomaly_rows)
    total_and = sum(len(item[2]) for item in anomaly_rows)
    summary = f"iOS {total_ios}건 · Android {total_and}건" if has_any else "이상 없음"

    return f"""
<div class="anomaly-section">
  <h3>🔎 오디오 이상 구간 검출 ({summary})
    <span class="anomaly-method">ref(정답지) ↔ dif(수신 녹음) cross-correlation 기반 묵음/깨짐 자동 검출</span>
  </h3>
  <table class="anomaly-table">
    <thead>
      <tr>
        <th>음원</th>
        <th>플랫폼</th>
        <th>구분</th>
        <th>지속 시간</th>
        <th>발생 구간</th>
        <th>Gain (dB)</th>
        <th>Correlation</th>
        <th>청취</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p class="anomaly-note">
    ⓘ &nbsp;묵음(digital_zero): 수신음이 완전 무음인 구간 &nbsp;|&nbsp;
    깨짐(gain_drop): 원본 대비 볼륨이 급격히 하락한 구간 &nbsp;|&nbsp;
    최소 검출 길이: 50ms &nbsp;|&nbsp; ref 음성 구간에서만 검출
  </p>
</div>"""


def build_benchmark_pin_html() -> str:
    """음단절 감지 알고리즘 Ground Truth 검증 결과 고정 배너 (시연용)."""
    return """
<div style="background:#0a1a0a;border:2px solid #2e7d32;border-radius:12px;
            padding:20px 28px;margin-bottom:28px;position:relative">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap">
    <span style="font-size:1.1em;font-weight:700;color:#66bb6a;letter-spacing:.05em">
      📊 음단절 감지 알고리즘 정확도 검증 결과
    </span>
    <span style="font-size:.72em;font-weight:600;background:#1b5e20;color:#a5d6a7;
                 padding:2px 10px;border-radius:12px;white-space:nowrap">
      ✅ Ground Truth 100% 달성 · 2026-04-06
    </span>
    <span style="font-size:.72em;color:#607090;margin-left:auto">
      수동 생성 음원(철수/영희 각 4~5건 묵음 삽입) 기준
    </span>
  </div>

  <div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px">
    <!-- 철수 방법1 -->
    <div style="flex:1;min-width:200px;background:#0d1f0d;border:1px solid #2e7d32;
                border-radius:8px;padding:14px 18px">
      <div style="font-size:.8em;color:#81c784;font-weight:600;margin-bottom:8px">
        🤖 철수(Android) — 방법1 프레임 스캔
      </div>
      <div style="font-size:1.6em;font-weight:800;color:#69f0ae;font-family:monospace">
        5/5 &nbsp;<span style="font-size:.65em;color:#4caf50">100%</span>
      </div>
      <div style="font-size:.75em;color:#607090;margin-top:6px">Recall 100% · Precision 100%</div>
      <div style="font-size:.72em;color:#546e7a;margin-top:8px;line-height:1.7">
        여보(170ms) · 거기 · 하다 · 그럼 · 걷자(end)
      </div>
    </div>
    <!-- 철수 방법2 -->
    <div style="flex:1;min-width:200px;background:#0d1f0d;border:1px solid #2e7d32;
                border-radius:8px;padding:14px 18px">
      <div style="font-size:.8em;color:#81c784;font-weight:600;margin-bottom:8px">
        🤖 철수(Android) — 방법2 대본 구간 스캔
      </div>
      <div style="font-size:1.6em;font-weight:800;color:#69f0ae;font-family:monospace">
        5/5 &nbsp;<span style="font-size:.65em;color:#4caf50">100%</span>
      </div>
      <div style="font-size:.75em;color:#607090;margin-top:6px">Recall 100% · Precision 100%</div>
      <div style="font-size:.72em;color:#546e7a;margin-top:8px;line-height:1.7">
        VAD 분절 자동 병합 → 60.0~75.8s 구간 통합 검출
      </div>
    </div>
    <!-- 영희 방법1 -->
    <div style="flex:1;min-width:200px;background:#0d1f0d;border:1px solid #2e7d32;
                border-radius:8px;padding:14px 18px">
      <div style="font-size:.8em;color:#81c784;font-weight:600;margin-bottom:8px">
        🍎 영희(iOS) — 방법1 프레임 스캔
      </div>
      <div style="font-size:1.6em;font-weight:800;color:#69f0ae;font-family:monospace">
        4/4 &nbsp;<span style="font-size:.65em;color:#4caf50">100%</span>
      </div>
      <div style="font-size:.75em;color:#607090;margin-top:6px">Recall 100% · Precision 100% · FP 0건</div>
      <div style="font-size:.72em;color:#546e7a;margin-top:8px;line-height:1.7">
        철수 · 거기 · 응(문장시작) · 봐(end) — 정상구간 오탐 없음
      </div>
    </div>
    <!-- 영희 방법2 -->
    <div style="flex:1;min-width:200px;background:#0d1f0d;border:1px solid #2e7d32;
                border-radius:8px;padding:14px 18px">
      <div style="font-size:.8em;color:#81c784;font-weight:600;margin-bottom:8px">
        🍎 영희(iOS) — 방법2 대본 구간 스캔
      </div>
      <div style="font-size:1.6em;font-weight:800;color:#69f0ae;font-family:monospace">
        4/4 &nbsp;<span style="font-size:.65em;color:#4caf50">100%</span>
      </div>
      <div style="font-size:.75em;color:#607090;margin-top:6px">Recall 100% · Precision 100%</div>
      <div style="font-size:.72em;color:#546e7a;margin-top:8px;line-height:1.7">
        ref 정렬 기반 대사 구간 내 에너지 직접 스캔
      </div>
    </div>
  </div>

  <!-- 검출 케이스 타임라인 표 -->
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:.82em">
      <thead>
        <tr style="background:#1b3a1b">
          <th style="padding:7px 12px;text-align:left;color:#81c784">#</th>
          <th style="padding:7px 12px;text-align:left;color:#81c784">화자</th>
          <th style="padding:7px 12px;text-align:left;color:#81c784">묵음 단어</th>
          <th style="padding:7px 12px;text-align:left;color:#81c784">ref 구간</th>
          <th style="padding:7px 12px;text-align:left;color:#81c784">실제 검출 위치</th>
          <th style="padding:7px 12px;text-align:left;color:#81c784">지속 시간</th>
          <th style="padding:7px 12px;text-align:center;color:#81c784">방법1</th>
          <th style="padding:7px 12px;text-align:center;color:#81c784">방법2</th>
          <th style="padding:7px 12px;text-align:left;color:#81c784">비고</th>
        </tr>
      </thead>
      <tbody>
        <tr style="border-bottom:1px solid #1b3a1b">
          <td style="padding:6px 12px;color:#78909c">S1-1</td>
          <td style="padding:6px 12px">🤖 철수</td>
          <td style="padding:6px 12px;font-weight:600">여보</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em">0.0–6.3s</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em;color:#69f0ae">0.07–0.24s</td>
          <td style="padding:6px 12px;font-family:monospace">170ms</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;font-size:.78em;color:#607090">문장 시작 · 10ms peak scan으로 검출</td>
        </tr>
        <tr style="border-bottom:1px solid #1b3a1b">
          <td style="padding:6px 12px;color:#78909c">S1-2</td>
          <td style="padding:6px 12px">🤖 철수</td>
          <td style="padding:6px 12px;font-weight:600">거기</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em">12.8–22.0s</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em;color:#69f0ae">15.58–16.00s</td>
          <td style="padding:6px 12px;font-family:monospace">420ms</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;font-size:.78em;color:#607090">문장 중간</td>
        </tr>
        <tr style="border-bottom:1px solid #1b3a1b">
          <td style="padding:6px 12px;color:#78909c">S1-3</td>
          <td style="padding:6px 12px">🤖 철수</td>
          <td style="padding:6px 12px;font-weight:600">하다</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em">32.2–35.1s</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em;color:#69f0ae">34.60–34.71s</td>
          <td style="padding:6px 12px;font-family:monospace">110ms</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;font-size:.78em;color:#607090">문장 끝 근접</td>
        </tr>
        <tr style="border-bottom:1px solid #1b3a1b">
          <td style="padding:6px 12px;color:#78909c">S1-4</td>
          <td style="padding:6px 12px">🤖 철수</td>
          <td style="padding:6px 12px;font-weight:600">그럼</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em">42.0–47.4s</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em;color:#69f0ae">44.00–44.20s</td>
          <td style="padding:6px 12px;font-family:monospace">200ms</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;font-size:.78em;color:#607090">문장 중간</td>
        </tr>
        <tr style="border-bottom:1px solid #1b3a1b">
          <td style="padding:6px 12px;color:#78909c">S1-5</td>
          <td style="padding:6px 12px">🤖 철수</td>
          <td style="padding:6px 12px;font-weight:600">걷자</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em">60.0–75.8s</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em;color:#69f0ae">70.64–71.06s</td>
          <td style="padding:6px 12px;font-family:monospace">420ms</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;font-size:.78em;color:#607090">문장 끝 · VAD 분절 병합 후 검출</td>
        </tr>
        <tr style="border-bottom:1px solid #1b3a1b;background:#0f180f">
          <td style="padding:6px 12px;color:#78909c">S2-1</td>
          <td style="padding:6px 12px">🍎 영희</td>
          <td style="padding:6px 12px;font-weight:600">철수</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em">7.0–12.4s</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em;color:#69f0ae">7.49–7.87s</td>
          <td style="padding:6px 12px;font-family:monospace">380ms</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;font-size:.78em;color:#607090">문장 초반</td>
        </tr>
        <tr style="border-bottom:1px solid #1b3a1b;background:#0f180f">
          <td style="padding:6px 12px;color:#78909c">S2-2</td>
          <td style="padding:6px 12px">🍎 영희</td>
          <td style="padding:6px 12px;font-weight:600">거기</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em">22.5–31.8s</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em;color:#69f0ae">29.43–29.56s</td>
          <td style="padding:6px 12px;font-family:monospace">130ms</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;font-size:.78em;color:#607090">문장 중간</td>
        </tr>
        <tr style="border-bottom:1px solid #1b3a1b;background:#0f180f">
          <td style="padding:6px 12px;color:#78909c">S2-3</td>
          <td style="padding:6px 12px">🍎 영희</td>
          <td style="padding:6px 12px;font-weight:600">응</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em">35.7–41.7s</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em;color:#69f0ae">35.68–35.94s</td>
          <td style="padding:6px 12px;font-family:monospace">260ms</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;font-size:.78em;color:#607090">문장 시작 · 직전 포즈 예외 처리로 검출</td>
        </tr>
        <tr style="border-bottom:1px solid #1b3a1b;background:#0f180f">
          <td style="padding:6px 12px;color:#78909c">S2-4</td>
          <td style="padding:6px 12px">🍎 영희</td>
          <td style="padding:6px 12px;font-weight:600;color:#4caf50">— (정상)</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em">48.7–59.7s</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em;color:#4caf50">미검출 (정상)</td>
          <td style="padding:6px 12px;font-family:monospace">—</td>
          <td style="padding:6px 12px;text-align:center">✅ FP없음</td>
          <td style="padding:6px 12px;text-align:center">✅ FP없음</td>
          <td style="padding:6px 12px;font-size:.78em;color:#4caf50">정상 구간 오탐 없음 확인</td>
        </tr>
        <tr style="background:#0f180f">
          <td style="padding:6px 12px;color:#78909c">S2-5</td>
          <td style="padding:6px 12px">🍎 영희</td>
          <td style="padding:6px 12px;font-weight:600">봐</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em">71.8–75.5s</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:.9em;color:#69f0ae">75.33–75.51s</td>
          <td style="padding:6px 12px;font-family:monospace">180ms</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;text-align:center">✅</td>
          <td style="padding:6px 12px;font-size:.78em;color:#607090">문장 끝 1음절</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div style="margin-top:14px;font-size:.78em;color:#546e7a;line-height:1.8">
    ⓘ &nbsp;방법1: <code>audio_anomaly_detector</code> 슬라이딩 윈도우 CC + 10ms peak scan &nbsp;|&nbsp;
    방법2: <code>script_gap_detector</code> VAD 발화 구간 정렬 + 에너지 스캔 &nbsp;|&nbsp;
    최소 검출 길이 80ms · speech_strong_rms 0.02 · 문장 시작 직전 포즈 예외 포함 &nbsp;|&nbsp;
    VAD 과분절 자동 병합(최소 갭 우선)
  </div>
</div>"""


def build_html(sections: list, all_results: list | None = None,
               mos_rows: list | None = None,
               anomaly_rows: list | None = None) -> str:
    now         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_html  = build_total_table(all_results) if all_results else ""
    anomaly_html = build_anomaly_html(anomaly_rows) if anomaly_rows else ""
    mos_html    = build_mos_html(mos_rows) if mos_rows else ""
    env         = TEST_ENV
    and_ver = env.get("Android 앱 버전") or "—"
    ios_ver = env.get("iOS 앱 버전") or "—"
    and_dev = env.get("Android 단말", "")
    ios_dev = env.get("iOS 단말", "")
    and_os  = env.get("Android OS 버전", "")
    ios_os  = env.get("iOS OS 버전", "")
    footer_html = f"""
<div class="footer">
  <div class="footer-versions">
    <div class="footer-vitem">
      <span class="v-label">🤖 Android ixi-O</span>
      <span class="v-val">{and_ver}</span>
      <span class="v-status">{and_dev} &middot; {and_os}</span>
    </div>
    <div class="footer-vitem">
      <span class="v-label">🐍 iOS ixi-O</span>
      <span class="v-val">{ios_ver}</span>
      <span class="v-status">{ios_dev} &middot; {ios_os}</span>
    </div>
  </div>
  <div class="footer-brand">QA BULLS</div>
</div>"""
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<title>익시오 음성통화 묵음 현상 테스트 결과서</title>
<style>{CSS}</style>
</head><body>
<div class="header">
  <h1>🎙️ 익시오 음성통화 묵음 현상 테스트 결과서</h1>
  <p>생성: {now} &nbsp;|&nbsp; EnergyAlign(DTW) + librosa{' &nbsp;|&nbsp; 📁 ' + env.get('테스트 시나리오') if env.get('테스트 시나리오') else ''}</p>
</div>
<div class="section">
  {build_env_html(now)}
  {total_html}
  <div class="summary-box">
    <h3>📌 분석 방법</h3><ul>
      <li><b>대본 cross-correlation (주 분석)</b>: 정답지 TTS(audiomass) WAV를 VAD로
          발화 단위 분절 → Android 수신 파일에서 에너지 엔벨로프 cross-correlation 탐색
          → 정답지 발화 구간에서 Android 수신음이 묵음(상관계수 &lt; 0.30)이면 음단절 판정</li>
      <li><b>librosa (보조)</b>: 0.5초 윈도우 에너지 비율 시각화 — 파형 그래프 참고용</li>
      <li><span style="color:#ff9800"><b>⚠ 음질 저하(볼륨 감소·잡음·지연)는 음단절으로 판정하지 않습니다.</b></span></li>
    </ul>
  </div>
  {"".join(sections)}
  {anomaly_html}
  {mos_html}
</div>
{footer_html}
</body></html>"""
