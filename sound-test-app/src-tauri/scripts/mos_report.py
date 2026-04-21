#!/usr/bin/env python3
"""
mos_report.py — MOS 측정 전용 보고서 생성기

ITU-T 국제 표준 기반 음성 품질 평가 보고서:
  - ITU-T P.800  : MOS (Mean Opinion Score) 5점 척도
  - ITU-T G.107  : E-model R-factor 변환
  - ITU-T P.863  : ViSQOL MOS-LQO (POLQA 대응)
  - ITU-T G.1010 : QoE 등급 매핑

사용법:
  python mos_report.py --input results.json --output report.html

--input JSON 형식:
  {
    "session_id": "...",
    "test_info": { "android_device": "...", "ios_device": "...", ... },
    "runs": [
      {
        "repeat_index": 1,
        "ios_visqol_mos": 3.85,
        "android_visqol_mos": 4.12,
        "voip_delay_ms": 45,
        "started_at": "2026-04-15T10:30:00",
        "duration_ms": 95000,
        "status": "PASS"
      },
      ...
    ]
  }
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ITU-T 표준 기반 지표 계산 함수
# ═══════════════════════════════════════════════════════════════════════════════

def mos_to_r_factor(mos: float) -> float:
    """MOS → R-factor 변환 (ITU-T G.107 E-model 역변환).

    G.107 정방향: MOS = 1 + 0.035R + R(R−60)(100−R)·7×10⁻⁶
    역변환은 수치 해석(Newton's method)으로 구합니다.
    """
    if mos <= 1.0:
        return 0.0
    if mos >= 4.5:
        return 100.0

    # Newton-Raphson: f(R) = 1 + 0.035R + R(R-60)(100-R)*7e-6 - MOS = 0
    def f(r):
        return 1.0 + 0.035 * r + r * (r - 60.0) * (100.0 - r) * 7e-6 - mos

    def fp(r):
        # d/dR [1 + 0.035R + 7e-6 * R(R-60)(100-R)]
        # = 0.035 + 7e-6 * [(R-60)(100-R) + R(100-R) + R(R-60)(-1)]
        # = 0.035 + 7e-6 * [(R-60)(100-R) + R(100-R) - R(R-60)]
        t1 = (r - 60.0) * (100.0 - r)
        t2 = r * (100.0 - r)
        t3 = r * (r - 60.0)
        return 0.035 + 7e-6 * (t1 + t2 - t3)

    r = 60.0  # 초기값
    for _ in range(50):
        fr = f(r)
        fpr = fp(r)
        if abs(fpr) < 1e-12:
            break
        r = r - fr / fpr
        r = max(0.0, min(100.0, r))
        if abs(fr) < 1e-8:
            break
    return round(r, 1)


def r_factor_grade(r: float) -> tuple:
    """R-factor → 사용자 만족도 등급 (ITU-T G.107).

    Returns: (등급명_ko, 등급명_en, CSS클래스, 설명)
    """
    if r >= 90:
        return ('최상', 'Excellent', 'grade-excellent', '대부분의 사용자 만족')
    elif r >= 80:
        return ('상', 'Good', 'grade-good', '일부 사용자 불만족 가능')
    elif r >= 70:
        return ('중상', 'Fair', 'grade-fair', '다수의 사용자 불만족 가능')
    elif r >= 60:
        return ('중', 'Poor', 'grade-poor', '거의 모든 사용자 불만족')
    elif r >= 50:
        return ('하', 'Bad', 'grade-bad', '모든 사용자 불만족')
    else:
        return ('최하', 'Very Bad', 'grade-vbad', '통화 불가 수준')


def mos_quality_band(mos: float) -> tuple:
    """MOS → ITU-T P.800 품질 등급.

    Returns: (등급명_ko, CSS클래스, 색상)
    """
    if mos >= 4.3:
        return ('우수 (Excellent)', 'band-ex', '#2ecc71')
    elif mos >= 4.0:
        return ('좋음 (Good)', 'band-good', '#27ae60')
    elif mos >= 3.6:
        return ('양호 (Fair)', 'band-fair', '#f39c12')
    elif mos >= 3.0:
        return ('보통 (Average)', 'band-avg', '#e67e22')
    elif mos >= 2.5:
        return ('미흡 (Poor)', 'band-poor', '#e74c3c')
    else:
        return ('불량 (Bad)', 'band-bad', '#c0392b')


def compute_gob(mos_list: list) -> float:
    """GoB% — Good or Better (MOS ≥ 3.6) 비율. ITU-T P.800 기반 KPI."""
    if not mos_list:
        return 0.0
    return round(sum(1 for m in mos_list if m >= 3.6) / len(mos_list) * 100, 1)


def compute_pow(mos_list: list) -> float:
    """PoW% — Poor or Worse (MOS < 2.6) 비율. ITU-T P.800 기반 KPI."""
    if not mos_list:
        return 0.0
    return round(sum(1 for m in mos_list if m < 2.6) / len(mos_list) * 100, 1)


def confidence_interval_95(values: list) -> tuple:
    """95% 신뢰구간 계산. Returns (lower, upper, margin)."""
    n = len(values)
    if n < 2:
        mean = values[0] if values else 0
        return (mean, mean, 0)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    std = math.sqrt(variance)
    margin = 1.96 * std / math.sqrt(n)
    return (round(mean - margin, 3), round(mean + margin, 3), round(margin, 3))


def compute_stats(values: list) -> dict:
    """기술통계 일괄 계산."""
    if not values:
        return {'mean': None, 'median': None, 'std': None, 'min': None, 'max': None,
                'cv': None, 'ci_lower': None, 'ci_upper': None, 'ci_margin': None,
                'gob': 0, 'pow': 0, 'r_factor': None, 'r_grade': None, 'count': 0}

    n = len(values)
    mean = sum(values) / n
    sorted_v = sorted(values)
    median = sorted_v[n // 2] if n % 2 else (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2
    variance = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0
    std = math.sqrt(variance)
    cv = (std / mean * 100) if mean > 0 else 0
    ci_lower, ci_upper, ci_margin = confidence_interval_95(values)
    r = mos_to_r_factor(mean)
    r_grade = r_factor_grade(r)

    return {
        'mean': round(mean, 3),
        'median': round(median, 3),
        'std': round(std, 3),
        'min': round(min(values), 3),
        'max': round(max(values), 3),
        'cv': round(cv, 1),
        'ci_lower': ci_lower,
        'ci_upper': ci_upper,
        'ci_margin': ci_margin,
        'gob': compute_gob(values),
        'pow': compute_pow(values),
        'r_factor': r,
        'r_grade': r_grade,
        'count': n,
    }


def detect_trend(values: list) -> tuple:
    """단순 선형 회귀로 MOS 추세 감지.

    Returns: (slope, direction_ko, direction_en)
      direction: '상승'/'안정'/'하락'
    """
    n = len(values)
    if n < 3:
        return (0.0, '판정불가', 'N/A')
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    slope = num / den if den > 0 else 0
    # 20회 경사: 기울기 × n / mean → 전체 변화율
    total_change = slope * (n - 1)
    pct = abs(total_change / y_mean * 100) if y_mean > 0 else 0

    if pct < 2:
        return (round(slope, 4), '안정', 'Stable')
    elif slope > 0:
        return (round(slope, 4), '상승', 'Improving')
    else:
        return (round(slope, 4), '하락', 'Degrading')


def quality_distribution(values: list) -> dict:
    """품질 등급별 분포 카운트."""
    dist = {'우수': 0, '좋음': 0, '양호': 0, '보통': 0, '미흡': 0, '불량': 0}
    for v in values:
        band, _, _ = mos_quality_band(v)
        key = band.split(' ')[0]
        dist[key] = dist.get(key, 0) + 1
    return dist


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SVG 차트 생성
# ═══════════════════════════════════════════════════════════════════════════════

def svg_trend_chart(values: list, label: str, color: str = '#3498db') -> str:
    """MOS 추세 라인 차트 (inline SVG)."""
    if not values:
        return '<p class="no-data">데이터 없음</p>'

    W, H = 700, 260
    PAD_L, PAD_R, PAD_T, PAD_B = 50, 20, 30, 40
    chart_w = W - PAD_L - PAD_R
    chart_h = H - PAD_T - PAD_B

    y_min, y_max = 1.0, 5.0
    n = len(values)
    x_step = chart_w / max(n - 1, 1)

    def px(i, v):
        x = PAD_L + i * x_step
        y = PAD_T + chart_h - (v - y_min) / (y_max - y_min) * chart_h
        return x, y

    # 품질 등급 배경 밴드
    bands = [
        (4.3, 5.0, '#2ecc7120'), (4.0, 4.3, '#27ae6020'),
        (3.6, 4.0, '#f39c1220'), (3.0, 3.6, '#e67e2220'),
        (2.5, 3.0, '#e74c3c20'), (1.0, 2.5, '#c0392b20'),
    ]
    bg_rects = ''
    for lo, hi, fill in bands:
        y1 = PAD_T + chart_h - (hi - y_min) / (y_max - y_min) * chart_h
        y2 = PAD_T + chart_h - (lo - y_min) / (y_max - y_min) * chart_h
        bg_rects += f'<rect x="{PAD_L}" y="{y1:.1f}" width="{chart_w}" height="{y2 - y1:.1f}" fill="{fill}"/>'

    # Y축 그리드 + 눈금
    y_labels = ''
    for v in [1.0, 2.0, 2.5, 3.0, 3.6, 4.0, 4.3, 5.0]:
        _, y = px(0, v)
        y_labels += f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" stroke="#555" stroke-dasharray="3,3" opacity="0.4"/>'
        y_labels += f'<text x="{PAD_L - 8}" y="{y:.1f}" text-anchor="end" fill="#aaa" font-size="11">{v:.1f}</text>'

    # 평균선
    mean_val = sum(values) / n
    _, mean_y = px(0, mean_val)
    mean_line = f'<line x1="{PAD_L}" y1="{mean_y:.1f}" x2="{W - PAD_R}" y2="{mean_y:.1f}" stroke="#e74c3c" stroke-dasharray="6,3" opacity="0.7"/>'
    mean_line += f'<text x="{W - PAD_R + 2}" y="{mean_y:.1f}" fill="#e74c3c" font-size="10">AVG {mean_val:.2f}</text>'

    # 데이터 라인 + 포인트
    points = [px(i, v) for i, v in enumerate(values)]
    polyline = ' '.join(f'{x:.1f},{y:.1f}' for x, y in points)
    dots = ''
    x_labels = ''
    for i, (x, y) in enumerate(points):
        dots += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" stroke="#fff" stroke-width="1.5">'
        dots += f'<title>#{i+1}: {values[i]:.3f}</title></circle>'
        if n <= 25 or i % max(1, n // 10) == 0 or i == n - 1:
            x_labels += f'<text x="{x:.1f}" y="{H - 5}" text-anchor="middle" fill="#aaa" font-size="10">#{i+1}</text>'

    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" class="mos-chart">
  {bg_rects}{y_labels}{mean_line}
  <polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>
  {dots}{x_labels}
  <text x="{W/2}" y="18" text-anchor="middle" fill="#eee" font-size="13" font-weight="bold">{label}</text>
</svg>'''


def svg_distribution_bar(dist: dict, total: int, label: str) -> str:
    """품질 등급 분포 가로 막대 차트."""
    if total == 0:
        return '<p class="no-data">데이터 없음</p>'

    W, H = 400, 200
    colors = {'우수': '#2ecc71', '좋음': '#27ae60', '양호': '#f39c12',
              '보통': '#e67e22', '미흡': '#e74c3c', '불량': '#c0392b'}
    keys = ['우수', '좋음', '양호', '보통', '미흡', '불량']
    bar_h = 22
    gap = 6
    y_start = 30

    bars = ''
    for i, k in enumerate(keys):
        count = dist.get(k, 0)
        pct = count / total * 100
        bar_w = max(pct / 100 * (W - 140), 0)
        y = y_start + i * (bar_h + gap)
        fill = colors.get(k, '#888')
        bars += f'<rect x="60" y="{y}" width="{bar_w:.1f}" height="{bar_h}" rx="3" fill="{fill}" opacity="0.85"/>'
        bars += f'<text x="55" y="{y + 16}" text-anchor="end" fill="#ccc" font-size="11">{k}</text>'
        if count > 0:
            bars += f'<text x="{65 + bar_w:.1f}" y="{y + 16}" fill="#eee" font-size="11">{count}회 ({pct:.0f}%)</text>'

    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" class="dist-chart">
  <text x="{W/2}" y="18" text-anchor="middle" fill="#eee" font-size="13" font-weight="bold">{label}</text>
  {bars}
</svg>'''


def svg_gauge(value: float, max_val: float, label: str, unit: str, color: str) -> str:
    """반원형 게이지 SVG."""
    pct = min(value / max_val, 1.0) if max_val > 0 else 0
    angle = 180 * pct
    r = 60
    cx, cy = 80, 85
    # 반원 경로
    end_x = cx + r * math.cos(math.radians(180 - angle))
    end_y = cy - r * math.sin(math.radians(180 - angle))
    large_arc = 1 if angle > 180 else 0
    # 배경 반원
    bg = f'M{cx - r},{cy} A{r},{r} 0 0,1 {cx + r},{cy}'
    arc = f'M{cx - r},{cy} A{r},{r} 0 {large_arc},1 {end_x:.1f},{end_y:.1f}'

    return f'''<svg viewBox="0 0 160 110" xmlns="http://www.w3.org/2000/svg" class="gauge">
  <path d="{bg}" fill="none" stroke="#333" stroke-width="12" stroke-linecap="round"/>
  <path d="{arc}" fill="none" stroke="{color}" stroke-width="12" stroke-linecap="round"/>
  <text x="{cx}" y="{cy - 15}" text-anchor="middle" fill="#fff" font-size="22" font-weight="bold">{value:.2f}</text>
  <text x="{cx}" y="{cy + 2}" text-anchor="middle" fill="#aaa" font-size="10">{unit}</text>
  <text x="{cx}" y="{cy + 22}" text-anchor="middle" fill="#ccc" font-size="11">{label}</text>
</svg>'''


# ═══════════════════════════════════════════════════════════════════════════════
# 3. HTML 보고서 생성
# ═══════════════════════════════════════════════════════════════════════════════

CSS = """
:root {
  --bg: #1a1a2e; --card: #16213e; --border: #0f3460;
  --text: #e0e0e0; --text2: #a0a0b0; --accent: #3498db;
  --ios: #007aff; --android: #34a853;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
  background: var(--bg); color: var(--text); padding: 24px; line-height: 1.6;
}
.container { max-width: 1100px; margin: 0 auto; }

/* ── Header ── */
.header {
  text-align: center; padding: 32px 24px; margin-bottom: 24px;
  background: linear-gradient(135deg, #0f3460, #1a1a2e);
  border-radius: 16px; border: 1px solid var(--border);
}
.header h1 { font-size: 26px; margin-bottom: 6px; }
.header .subtitle { color: var(--text2); font-size: 14px; }
.header .badge {
  display: inline-block; padding: 4px 16px; border-radius: 20px;
  font-weight: 700; font-size: 18px; margin-top: 12px;
}
.badge-pass { background: #27ae6030; color: #2ecc71; border: 1px solid #27ae6060; }
.badge-marginal { background: #f39c1230; color: #f39c12; border: 1px solid #f39c1260; }
.badge-fail { background: #e74c3c30; color: #e74c3c; border: 1px solid #e74c3c60; }

/* ── Section ── */
.section {
  background: var(--card); border-radius: 12px;
  border: 1px solid var(--border); padding: 20px 24px; margin-bottom: 20px;
}
.section h2 {
  font-size: 16px; color: var(--accent); margin-bottom: 14px;
  padding-bottom: 8px; border-bottom: 1px solid var(--border);
}
.section h3 { font-size: 14px; color: var(--text2); margin: 12px 0 8px; }

/* ── KPI Grid ── */
.kpi-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px; margin-bottom: 16px;
}
.kpi-card {
  background: #0f3460; border-radius: 10px; padding: 16px; text-align: center;
}
.kpi-value { font-size: 28px; font-weight: 800; }
.kpi-label { font-size: 11px; color: var(--text2); margin-top: 4px; }
.kpi-sub { font-size: 10px; color: var(--text2); margin-top: 2px; }

/* ── Tables ── */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { background: #0f3460; color: #a0c4ff; padding: 10px 8px; text-align: center; font-weight: 600; }
td { padding: 8px; text-align: center; border-bottom: 1px solid #1a2a4a; }
tr:hover { background: #1a2a4a40; }
.num-col { font-family: 'SF Mono', 'Fira Code', monospace; }

/* ── Grade Badges ── */
.band-ex { color: #2ecc71; } .band-good { color: #27ae60; }
.band-fair { color: #f39c12; } .band-avg { color: #e67e22; }
.band-poor { color: #e74c3c; } .band-bad { color: #c0392b; }
.grade-excellent { color: #2ecc71; } .grade-good { color: #27ae60; }
.grade-fair { color: #f39c12; } .grade-poor { color: #e67e22; }
.grade-bad { color: #e74c3c; } .grade-vbad { color: #c0392b; }

/* ── Chart Layout ── */
.chart-row { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; }
.chart-row > * { flex: 1; min-width: 350px; }
.gauge-row { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
svg.mos-chart, svg.dist-chart { width: 100%; max-width: 700px; }
svg.gauge { width: 160px; }
.no-data { color: var(--text2); text-align: center; padding: 20px; }

/* ── Verdict ── */
.verdict-box {
  display: flex; align-items: center; gap: 12px;
  padding: 16px; border-radius: 10px; margin-top: 12px;
}
.verdict-pass { background: #27ae6015; border: 1px solid #27ae6040; }
.verdict-marginal { background: #f39c1215; border: 1px solid #f39c1240; }
.verdict-fail { background: #e74c3c15; border: 1px solid #e74c3c40; }
.verdict-icon { font-size: 32px; }
.verdict-text { font-size: 14px; line-height: 1.5; }

/* ── Footer ── */
.footer {
  text-align: center; padding: 20px; color: var(--text2); font-size: 11px;
  margin-top: 24px;
}

/* ── Standards Reference ── */
.std-table { width: auto; margin: 0 auto; }
.std-table th { background: #0f346080; padding: 6px 16px; font-size: 12px; }
.std-table td { padding: 6px 16px; font-size: 12px; }

/* ── Platform Tabs ── */
.platform-label { font-weight: 600; margin-bottom: 4px; }
.platform-label.ios { color: var(--ios); }
.platform-label.android { color: var(--android); }

/* ── Responsive ── */
@media (max-width: 700px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .chart-row > * { min-width: 100%; }
}
"""


def _overall_verdict(ios_stats: dict, and_stats: dict) -> tuple:
    """종합 판정: PASS / MARGINAL / FAIL.

    기준 (ITU-T 권고 기반):
      PASS     : 양쪽 모두 평균 MOS ≥ 3.6 AND GoB ≥ 80%
      MARGINAL : 양쪽 모두 평균 MOS ≥ 3.0
      FAIL     : 그 외
    """
    stats = [s for s in [ios_stats, and_stats] if s.get('mean') is not None]
    if not stats:
        return ('N/A', 'badge-fail', '측정 데이터 없음')
    all_pass = all(s['mean'] >= 3.6 and s['gob'] >= 80 for s in stats)
    all_marginal = all(s['mean'] >= 3.0 for s in stats)
    if all_pass:
        return ('PASS', 'badge-pass', '통화 품질 우수 — ITU-T 권고 충족')
    elif all_marginal:
        return ('MARGINAL', 'badge-marginal', '통화 품질 주의 — 개선 검토 필요')
    else:
        return ('FAIL', 'badge-fail', '통화 품질 미달 — 즉각 조치 필요')


def _env_table(info: dict) -> str:
    """테스트 환경 정보 테이블."""
    rows = ''
    pairs = [
        ('통신사', info.get('carrier_name', '-')),
        ('Android 단말', info.get('android_device', '-')),
        ('Android OS', info.get('android_os_ver', '-')),
        ('Android 앱', info.get('android_app_name', '-')),
        ('Android 앱 버전', info.get('android_app_ver', '-')),
        ('iOS 단말', info.get('ios_device', '-')),
        ('iOS OS', info.get('ios_os_ver', '-')),
        ('iOS 앱', info.get('ios_app_name', '-')),
        ('iOS 앱 버전', info.get('ios_app_ver', '-')),
        ('프로파일', info.get('profile_name', '-')),
    ]
    for label, val in pairs:
        if val and val != '-':
            rows += f'<tr><td style="text-align:left;color:var(--text2)">{label}</td><td style="text-align:left">{val}</td></tr>'
    if not rows:
        return ''
    return f'<table class="std-table"><tbody>{rows}</tbody></table>'


def _per_call_table(runs: list, platform: str) -> str:
    """호별 MOS 상세 테이블."""
    key = f'{platform}_visqol_mos'
    rows = ''
    for i, r in enumerate(runs):
        mos = r.get(key)
        delay = r.get('voip_delay_ms', '-')
        dur = r.get('duration_ms', 0)
        dur_s = f'{dur / 1000:.0f}s' if dur else '-'
        status = r.get('status', '-')
        idx = r.get('repeat_index', i + 1) or (i + 1)
        if mos is not None:
            band_ko, band_cls, _ = mos_quality_band(mos)
            rf = mos_to_r_factor(mos)
            rows += f'''<tr>
          <td>{idx}</td>
          <td class="num-col">{mos:.3f}</td>
          <td class="{band_cls}">{band_ko.split(" ")[0]}</td>
          <td class="num-col">{rf:.1f}</td>
          <td class="num-col">{delay}</td>
          <td>{dur_s}</td>
          <td>{status}</td>
        </tr>'''
        else:
            rows += f'''<tr>
          <td>{idx}</td>
          <td class="num-col" style="color:var(--text2)">—</td>
          <td style="color:var(--text2)">—</td>
          <td class="num-col" style="color:var(--text2)">—</td>
          <td class="num-col">{delay}</td>
          <td>{dur_s}</td>
          <td style="color:#e74c3c">{status}</td>
        </tr>'''

    return f'''<table>
      <thead><tr>
        <th>#</th><th>MOS-LQO</th><th>등급</th>
        <th>R-factor</th><th>지연(ms)</th><th>소요</th><th>상태</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>'''


def _stats_summary_html(stats: dict, platform_label: str, platform_cls: str) -> str:
    """통계 요약 HTML 카드."""
    if stats['mean'] is None:
        return ''

    rg = stats['r_grade']
    r_color = {'grade-excellent': '#2ecc71', 'grade-good': '#27ae60', 'grade-fair': '#f39c12',
               'grade-poor': '#e67e22', 'grade-bad': '#e74c3c', 'grade-vbad': '#c0392b'}.get(rg[2], '#888')
    _, band_cls, mos_color = mos_quality_band(stats['mean'])

    return f'''
    <div class="platform-label {platform_cls}">{platform_label}</div>
    <div class="gauge-row">
      {svg_gauge(stats['mean'], 5.0, 'MOS 평균', 'MOS-LQO', mos_color)}
      {svg_gauge(stats['r_factor'], 100, 'R-factor', 'ITU-T G.107', r_color)}
      {svg_gauge(stats['gob'], 100, 'GoB%', '≥3.6 비율', '#2ecc71' if stats['gob'] >= 80 else '#e67e22')}
    </div>
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-value" style="color:{mos_color}">{stats['mean']:.3f}</div>
        <div class="kpi-label">평균 MOS</div>
        <div class="kpi-sub">95% CI: [{stats['ci_lower']:.2f}, {stats['ci_upper']:.2f}]</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="color:{r_color}">{stats['r_factor']:.1f}</div>
        <div class="kpi-label">R-factor</div>
        <div class="kpi-sub">{rg[0]} ({rg[1]})</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{stats['median']:.3f}</div>
        <div class="kpi-label">중앙값</div>
        <div class="kpi-sub">Min {stats['min']:.2f} / Max {stats['max']:.2f}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{stats['std']:.3f}</div>
        <div class="kpi-label">표준편차 (σ)</div>
        <div class="kpi-sub">CV: {stats['cv']:.1f}%</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="color:#2ecc71">{stats['gob']:.1f}%</div>
        <div class="kpi-label">GoB (Good or Better)</div>
        <div class="kpi-sub">MOS ≥ 3.6</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="color:#e74c3c">{stats['pow']:.1f}%</div>
        <div class="kpi-label">PoW (Poor or Worse)</div>
        <div class="kpi-sub">MOS &lt; 2.6</div>
      </div>
    </div>
    '''


def generate_report(data: dict, output_path: str) -> str:
    """MOS 측정 보고서 HTML 생성."""
    runs = data.get('runs', [])
    info = data.get('test_info', {})
    session_id = data.get('session_id', '')

    # 플랫폼별 MOS 추출
    ios_mos = [r['ios_visqol_mos'] for r in runs if r.get('ios_visqol_mos') is not None]
    and_mos = [r['android_visqol_mos'] for r in runs if r.get('android_visqol_mos') is not None]

    ios_stats = compute_stats(ios_mos)
    and_stats = compute_stats(and_mos)

    # 추세 분석
    ios_trend = detect_trend(ios_mos)
    and_trend = detect_trend(and_mos)

    # 품질 분포
    ios_dist = quality_distribution(ios_mos)
    and_dist = quality_distribution(and_mos)

    # 종합 판정
    verdict, verdict_cls, verdict_msg = _overall_verdict(ios_stats, and_stats)

    # VoIP 지연 통계
    delays = [r['voip_delay_ms'] for r in runs if r.get('voip_delay_ms') is not None]
    avg_delay = round(sum(delays) / len(delays)) if delays else 0
    max_delay = max(delays) if delays else 0

    total_calls = len(runs)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # ── HTML 조립 ──
    # 통신사명
    carrier_name = info.get('carrier_name', '')
    carrier_badge = f' · <span style="color:#f39c12;font-weight:700">{carrier_name}</span>' if carrier_name else ''

    html_parts = [f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MOS 측정 보고서{f" — {carrier_name}" if carrier_name else ""}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">

<!-- ═══ Header ═══ -->
<div class="header">
  <h1>📊 MOS 음성 품질 측정 보고서</h1>
  <div class="subtitle">ITU-T P.800 / G.107 기반 · ViSQOL MOS-LQO · {total_calls}회 측정{carrier_badge}</div>
  <div class="badge {verdict_cls}">{verdict}</div>
</div>
''']

    # ── 테스트 환경 ──
    env_html = _env_table(info)
    if env_html:
        html_parts.append(f'''
<div class="section">
  <h2>🔧 테스트 환경</h2>
  {env_html}
  <div style="margin-top:8px;font-size:12px;color:var(--text2)">
    세션: {session_id[:12]}… · 생성: {now_str}
  </div>
</div>''')

    # ── 종합 판정 ──
    verdict_icon = {'PASS': '✅', 'MARGINAL': '⚠️', 'FAIL': '❌'}.get(verdict, '❓')
    verdict_box_cls = {'PASS': 'verdict-pass', 'MARGINAL': 'verdict-marginal', 'FAIL': 'verdict-fail'}.get(verdict, 'verdict-fail')
    delay_status = '양호' if avg_delay < 150 else ('주의' if avg_delay < 400 else '불량')
    html_parts.append(f'''
<div class="section">
  <h2>📋 종합 판정</h2>
  <div class="verdict-box {verdict_box_cls}">
    <div class="verdict-icon">{verdict_icon}</div>
    <div class="verdict-text">
      <strong>{verdict}</strong> — {verdict_msg}<br>
      <span style="font-size:12px;color:var(--text2)">
        평균 VoIP 지연: {avg_delay}ms ({delay_status}) · 최대 지연: {max_delay}ms
        · 측정 횟수: {total_calls}회
      </span>
    </div>
  </div>
</div>''')

    # ── iOS 통계 ──
    if ios_stats['mean'] is not None:
        html_parts.append(f'''
<div class="section">
  <h2>📱 iOS 측정 결과</h2>
  {_stats_summary_html(ios_stats, 'iOS (Speaker 1 → Speaker 2 수신)', 'ios')}
  <h3>📈 MOS 추세 ({ios_trend[1]})</h3>
  {svg_trend_chart(ios_mos, f'iOS MOS 추세 — {ios_trend[1]} (기울기: {ios_trend[0]:+.4f})', '#007aff')}
  <h3>📊 품질 분포</h3>
  {svg_distribution_bar(ios_dist, len(ios_mos), 'iOS 품질 등급 분포')}
  <h3>📝 호별 상세</h3>
  {_per_call_table(runs, 'ios')}
</div>''')

    # ── Android 통계 ──
    if and_stats['mean'] is not None:
        html_parts.append(f'''
<div class="section">
  <h2>🤖 Android 측정 결과</h2>
  {_stats_summary_html(and_stats, 'Android (Speaker 2 → Speaker 1 수신)', 'android')}
  <h3>📈 MOS 추세 ({and_trend[1]})</h3>
  {svg_trend_chart(and_mos, f'Android MOS 추세 — {and_trend[1]} (기울기: {and_trend[0]:+.4f})', '#34a853')}
  <h3>📊 품질 분포</h3>
  {svg_distribution_bar(and_dist, len(and_mos), 'Android 품질 등급 분포')}
  <h3>📝 호별 상세</h3>
  {_per_call_table(runs, 'android')}
</div>''')

    # ── ITU-T 표준 참조 ──
    html_parts.append(f'''
<div class="section">
  <h2>📖 ITU-T 표준 참조</h2>
  <h3>MOS 품질 등급 (ITU-T P.800)</h3>
  <table class="std-table">
    <thead><tr><th>MOS 범위</th><th>등급</th><th>사용자 인식</th></tr></thead>
    <tbody>
      <tr><td>4.3 ~ 5.0</td><td class="band-ex">우수 (Excellent)</td><td>매우 만족</td></tr>
      <tr><td>4.0 ~ 4.3</td><td class="band-good">좋음 (Good)</td><td>만족</td></tr>
      <tr><td>3.6 ~ 4.0</td><td class="band-fair">양호 (Fair)</td><td>약간 만족</td></tr>
      <tr><td>3.0 ~ 3.6</td><td class="band-avg">보통 (Average)</td><td>보통</td></tr>
      <tr><td>2.5 ~ 3.0</td><td class="band-poor">미흡 (Poor)</td><td>불만족</td></tr>
      <tr><td>1.0 ~ 2.5</td><td class="band-bad">불량 (Bad)</td><td>매우 불만족</td></tr>
    </tbody>
  </table>

  <h3>R-factor → 사용자 만족도 매핑 (ITU-T G.107 E-model)</h3>
  <table class="std-table">
    <thead><tr><th>R-factor</th><th>등급</th><th>MOS 근사치</th><th>설명</th></tr></thead>
    <tbody>
      <tr><td>90 ~ 100</td><td class="grade-excellent">최상</td><td>≥ 4.34</td><td>대부분의 사용자 만족</td></tr>
      <tr><td>80 ~ 90</td><td class="grade-good">상</td><td>4.03 ~ 4.34</td><td>일부 사용자 불만족 가능</td></tr>
      <tr><td>70 ~ 80</td><td class="grade-fair">중상</td><td>3.60 ~ 4.03</td><td>다수 사용자 불만족 가능</td></tr>
      <tr><td>60 ~ 70</td><td class="grade-poor">중</td><td>3.10 ~ 3.60</td><td>거의 모든 사용자 불만족</td></tr>
      <tr><td>50 ~ 60</td><td class="grade-bad">하</td><td>2.58 ~ 3.10</td><td>모든 사용자 불만족</td></tr>
      <tr><td>0 ~ 50</td><td class="grade-vbad">최하</td><td>&lt; 2.58</td><td>통화 불가 수준</td></tr>
    </tbody>
  </table>

  <h3>핵심 지표 (KPI) 설명</h3>
  <table class="std-table">
    <thead><tr><th>지표</th><th>정의</th><th>ITU-T 기준</th></tr></thead>
    <tbody>
      <tr><td>MOS-LQO</td><td>ViSQOL 객관적 청취 품질 점수 (1~5)</td><td>P.863 대응</td></tr>
      <tr><td>R-factor</td><td>E-model 전송 등급 (0~100)</td><td>G.107</td></tr>
      <tr><td>GoB%</td><td>Good or Better — MOS ≥ 3.6 비율</td><td>P.800 해석</td></tr>
      <tr><td>PoW%</td><td>Poor or Worse — MOS &lt; 2.6 비율</td><td>P.800 해석</td></tr>
      <tr><td>CV%</td><td>변동계수 — 품질 안정성 지표</td><td>낮을수록 안정</td></tr>
      <tr><td>95% CI</td><td>신뢰구간 — 모평균 추정 범위</td><td>통계적 신뢰성</td></tr>
      <tr><td>VoIP 지연</td><td>단방향 전송 지연 (ms)</td><td>G.114: &lt;150ms 양호</td></tr>
    </tbody>
  </table>

  <div style="margin-top:12px;font-size:11px;color:var(--text2)">
    <p>※ MOS 점수는 ViSQOL v3.3.3 (speech mode) 으로 산출된 MOS-LQO 값입니다.</p>
    <p>※ R-factor는 MOS에서 ITU-T G.107 역변환(Newton-Raphson)으로 도출한 추정치입니다.</p>
    <p>※ 복수 측정 시 평균은 NSIM 공간에서의 변환이 아닌, 순수 산술 평균을 사용합니다 (MOS 개별값 기준).</p>
    <p>※ GoB/PoW 지표는 ITU-T P.800 권고에 기반한 실무 KPI로, 통신사 품질 관리에 널리 사용됩니다.</p>
  </div>
</div>
''')

    # ── 측정 방법론 ──
    html_parts.append(f'''
<div class="section">
  <h2>🔬 측정 방법론</h2>
  <table class="std-table">
    <tbody>
      <tr><td style="text-align:left;color:var(--text2);width:140px">측정 도구</td><td style="text-align:left">ViSQOL v3.3.3 (Virtual Speech Quality Objective Listener)</td></tr>
      <tr><td style="text-align:left;color:var(--text2)">모드</td><td style="text-align:left">Speech mode (wideband) · MOS-LQO 출력</td></tr>
      <tr><td style="text-align:left;color:var(--text2)">샘플링 레이트</td><td style="text-align:left">16,000 Hz (ITU-T P.863 권장)</td></tr>
      <tr><td style="text-align:left;color:var(--text2)">정규화</td><td style="text-align:left">ITU-T P.56 기반 −26 dBov 레벨 정규화</td></tr>
      <tr><td style="text-align:left;color:var(--text2)">시간 정렬</td><td style="text-align:left">교차상관(Cross-correlation) 기반 자동 정렬 (±3초)</td></tr>
      <tr><td style="text-align:left;color:var(--text2)">통화 방향</td><td style="text-align:left">S1 → S2 (정방향) 단일 방향</td></tr>
      <tr><td style="text-align:left;color:var(--text2)">반복 측정</td><td style="text-align:left">{total_calls}회 독립 통화</td></tr>
    </tbody>
  </table>
</div>
''')

    # ── Footer ──
    html_parts.append(f'''
<div class="footer">
  ixi-O 음성통화 MOS 측정 보고서 · 생성: {now_str}<br>
  Powered by ViSQOL v3.3.3 · ITU-T P.800 / G.107 / G.114 표준 기반
</div>
</div></body></html>''')

    html = '\n'.join(html_parts)
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CLI 진입점
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='MOS 측정 전용 보고서 생성기')
    parser.add_argument('--input', required=True, help='입력 JSON 파일 경로')
    parser.add_argument('--output', required=True, help='출력 HTML 파일 경로')
    args = parser.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)

    output_path = generate_report(data, args.output)
    # Rust 파싱용 결과 출력
    print(f'MOS_REPORT_PATH:{output_path}', flush=True)


if __name__ == '__main__':
    main()
