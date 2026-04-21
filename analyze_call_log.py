#!/usr/bin/env python3
"""
ixi-O 앱 통화 로그 분석기
Usage: python analyze_call_log.py [log_file] [--output report.html]
"""

import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from typing import Optional

# ──────────────────────────────────────────────
# 1. 데이터 구조
# ──────────────────────────────────────────────

@dataclass
class LogEntry:
    raw_line: str
    timestamp: Optional[str] = None
    dt: Optional[datetime] = None
    process: Optional[str] = None
    message: str = ""
    category: str = "misc"
    subcategory: str = ""
    importance: int = 0   # 0=noise, 1=low, 2=medium, 3=high, 4=critical

@dataclass
class CallSession:
    call_id: Optional[str] = None
    phase: str = "pre-call"   # pre-call | ringing | connecting | connected | stopping | post-call
    start_ts: Optional[datetime] = None
    connected_ts: Optional[datetime] = None
    bye_ts: Optional[datetime] = None
    audio_deact_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    call_number: Optional[str] = None

# ──────────────────────────────────────────────
# 2. 분류 규칙 (패턴 → category, subcategory, importance)
# ──────────────────────────────────────────────

RULES = [
    # SIP 시그널링 ──────────────────────────────
    (re.compile(r"---> INVOKE|메시지 전송.*INVITE|send.*INVITE|INVITE.*sendrecv", re.I),
     "sip", "INVITE_SENT", 4),
    (re.compile(r"메시지 수신 = INVITE|recv.*INVITE", re.I),
     "sip", "INVITE_RECV", 4),
    (re.compile(r"100 Trying", re.I),
     "sip", "100_TRYING", 3),
    (re.compile(r"183 Session Progress", re.I),
     "sip", "183_SESSION_PROGRESS", 3),
    (re.compile(r"200 OK.*INVITE|INVITE.*200 OK", re.I),
     "sip", "200_OK_INVITE", 4),
    (re.compile(r"<--- 200 OK|메시지 수신.*200|receiv.*200 OK", re.I),
     "sip", "200_OK", 3),
    (re.compile(r"---> ACK|PRACK", re.I),
     "sip", "ACK_PRACK", 2),
    (re.compile(r"메시지 수신 = BYE|receive.*BYE|BYE sip:", re.I),
     "sip", "BYE_RECV", 4),
    (re.compile(r"메시지 전송.*BYE|send.*BYE|MVOIPACK_SIP_BYE", re.I),
     "sip", "BYE_SENT", 4),
    (re.compile(r"CD_SIP_HISTORY.*히스토리", re.I),
     "sip", "SIP_HISTORY", 3),
    (re.compile(r"handleRequestTypeMessage.*BYE|receiveBye", re.I),
     "sip", "BYE_PROCESS", 3),

    # 통화 상태 ──────────────────────────────────
    (re.compile(r"CALL_STATUS_STOPPING"),
     "call_state", "CALL_STOPPING", 4),
    (re.compile(r"EVENT_CALL_END"),
     "call_state", "CALL_END_EVENT", 4),
    (re.compile(r"CALL_STATUS_ACTIVE|callState.*active"),
     "call_state", "CALL_ACTIVE", 4),
    (re.compile(r"callWithCallID.*현재 등록된 callId"),
     "call_state", "CALL_ALIVE_HEARTBEAT", 1),
    (re.compile(r"reportCallEnd"),
     "call_state", "REPORT_CALL_END", 4),
    (re.compile(r"reportCallStart|didActivate|CDCallConnected"),
     "call_state", "REPORT_CALL_START", 4),
    (re.compile(r"MultiCallManager.*CALL_STATUS"),
     "call_state", "MULTICALL_STATUS", 3),
    (re.compile(r"handleCallStateChanged"),
     "call_state", "CALL_STATE_CHANGED", 3),
    (re.compile(r"handleCallEvents"),
     "call_state", "CALL_EVENT_HANDLE", 2),
    (re.compile(r"callState: idle"),
     "call_state", "CALL_STATE_IDLE", 3),
    (re.compile(r"playEndCallSound"),
     "call_state", "PLAY_END_SOUND", 3),

    # 오디오 세션 ─────────────────────────────────
    (re.compile(r'\"action\":\"activate\".*ixi-O|Deactivated session|session.*activated', re.I),
     "audio", "AUDIO_SESSION_ACTIVATE", 3),
    (re.compile(r'\"action\":\"deactivate\".*ixi-O|stopAudio|Audio session deactivated', re.I),
     "audio", "AUDIO_SESSION_DEACTIVATE", 3),
    (re.compile(r"AVAudioSession.*setActive|setCategory|setMode", re.I),
     "audio", "AUDIO_SESSION_CONFIG", 2),
    (re.compile(r"callkitAudioAction|stopAudio|startAudio", re.I),
     "audio", "AUDIO_ACTION", 2),

    # CallKit ─────────────────────────────────────
    (re.compile(r"CXEndCallAction|CXAnswerCallAction|CXStartCallAction", re.I),
     "callkit", "CX_ACTION", 4),
    (re.compile(r"CallKitController|performEndCall|performAnswerCall", re.I),
     "callkit", "CALLKIT_CTRL", 2),
    (re.compile(r"InCallService|PHAudio|PHCall", re.I),
     "callkit", "IN_CALL_SERVICE", 2),

    # 엔진 DataDog 이벤트 ─────────────────────────
    (re.compile(r"ENGINE_sendReport"),
     "engine", "ENGINE_SEND_REPORT", 1),
    (re.compile(r"ENGINE_ReceiveReport"),
     "engine", "ENGINE_RECV_REPORT", 1),
    (re.compile(r"ENGINE_ReceiveHealthCheck"),
     "engine", "ENGINE_RECV_HEALTH", 1),
    (re.compile(r"ENGINE_sendLiveBuffer"),
     "engine", "ENGINE_LIVE_BUFFER", 1),
    (re.compile(r"ENGINE_micHe[ae]lthCheck"),
     "engine", "ENGINE_MIC_HEALTH", 1),
    (re.compile(r"ENGINE_monitoringRecord"),
     "engine", "ENGINE_MONITORING", 2),
    (re.compile(r"ENGINE_SendPackets"),
     "engine", "ENGINE_SEND_PKT", 1),
    (re.compile(r"ENGINE_ReceivePackets"),
     "engine", "ENGINE_RECV_PKT", 1),

    # WebSocket ──────────────────────────────────
    (re.compile(r"keepAlive Call \d+|KEEPALIVEOK 수신"),
     "websocket", "KEEPALIVE", 1),
    (re.compile(r"webSocketDidReceiveMessage"),
     "websocket", "WS_RECV", 1),
    (re.compile(r"webSocketDidSendMessage"),
     "websocket", "WS_SEND", 1),
    (re.compile(r"CD_SIP_DEINIT|deinit"),
     "websocket", "SIP_DEINIT", 2),

    # CallViewModel / UI ─────────────────────────
    (re.compile(r"CallViewModel deinit"),
     "app_ui", "CALLVM_DEINIT", 4),
    (re.compile(r"stopAiMessageObserver|stopAiCallTimer"),
     "app_ui", "AI_OBSERVER_STOP", 3),
    (re.compile(r"activeCall Changed"),
     "app_ui", "ACTIVE_CALL_NIL", 3),
    (re.compile(r"CallHistoryUseCase.*getSummary|통화 종료 직후"),
     "app_ui", "POST_CALL_SUMMARY", 3),
    (re.compile(r"SyncLocalDB|RefreshCallHistory"),
     "app_ui", "HISTORY_REFRESH", 2),
    (re.compile(r"CallHistoryDataGroup"),
     "app_ui", "HISTORY_DB", 1),
    (re.compile(r"AppsFlyerMananger.*logEvent"),
     "app_ui", "ANALYTICS_EVENT", 2),
]

# 저수준 노이즈 필터 (중요도 0 강제)
NOISE_PATTERN = re.compile(
    r"ENGINE_LOG|emitPakcet|RTPReceiver|AmrwbDecod|AmrwbEncod|"
    r"audio_mixer|hw_audio_render|hw_audio_record|TransmittingCtrl|"
    r"RtpDepacketizer|CudoVoipMonitor|renderCallback|SRTP Packet|AMR-WB|"
    r"copy buffer|loop start|Fill SID|buffer size|nw_protocol\|"
    r"\[C[0-9]\s|Task <"
)

# ──────────────────────────────────────────────
# 3. 파서
# ──────────────────────────────────────────────

TS_PATTERN = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d+)\+\d{4}")
CALLID_PATTERN = re.compile(r"[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}\S+mvoip", re.I)
NUMBER_PATTERN = re.compile(r"sip:(\d{8,11})@")


def classify(message: str) -> tuple[str, str, int]:
    if NOISE_PATTERN.search(message):
        return "noise", "", 0
    for pat, cat, sub, imp in RULES:
        if pat.search(message):
            return cat, sub, imp
    return "misc", "", 1


def parse_line(raw: str) -> LogEntry:
    entry = LogEntry(raw_line=raw.strip())
    parts = raw.split("\t", 3)
    if len(parts) >= 3:
        ts_match = TS_PATTERN.search(parts[1] if len(parts) > 1 else "")
        if ts_match:
            entry.timestamp = ts_match.group(1)
            try:
                entry.dt = datetime.strptime(
                    f"2026-03-04 {ts_match.group(1)}", "%Y-%m-%d %H:%M:%S.%f"
                )
            except ValueError:
                pass
        entry.process = parts[2].strip() if len(parts) > 2 else ""
        entry.message = parts[3].strip() if len(parts) > 3 else ""
    else:
        entry.message = raw.strip()

    entry.category, entry.subcategory, entry.importance = classify(entry.message)
    return entry


# ──────────────────────────────────────────────
# 4. 통화 세션 추론
# ──────────────────────────────────────────────

def infer_session(entries: list[LogEntry]) -> CallSession:
    session = CallSession()
    for e in entries:
        if e.importance == 0:
            continue
        # call_id 추출
        if not session.call_id:
            m = CALLID_PATTERN.search(e.message)
            if m:
                session.call_id = m.group(0)
        # 전화번호
        if not session.call_number:
            m = NUMBER_PATTERN.search(e.message)
            if m:
                session.call_number = m.group(1)
        # BYE 수신 시각
        if e.subcategory in ("BYE_RECV", "BYE_SENT") and not session.bye_ts:
            session.bye_ts = e.dt
        # 오디오 해제 시각
        if e.subcategory == "AUDIO_SESSION_DEACTIVATE" and not session.audio_deact_ts:
            session.audio_deact_ts = e.dt
        # CALL_END 이후
        if e.subcategory == "POST_CALL_SUMMARY" and not session.end_ts:
            session.end_ts = e.dt

    # 로그 범위
    dts = [e.dt for e in entries if e.dt]
    if dts:
        session.start_ts = min(dts)
        if not session.end_ts:
            session.end_ts = max(dts)

    return session


# ──────────────────────────────────────────────
# 5. 분석 집계
# ──────────────────────────────────────────────

def analyze(entries: list[LogEntry], session: CallSession) -> dict:
    # 구간 정의 (BYE 기준)
    bye_ts = session.bye_ts

    phase_counts = defaultdict(lambda: defaultdict(int))
    timeline_events = []   # importance >= 3
    engine_stats = defaultdict(int)
    keepalive_count = 0
    heartbeat_count = 0
    category_totals = Counter()
    subcategory_totals = Counter()

    for e in entries:
        if e.importance == 0:
            continue

        # 구간 분류
        if bye_ts and e.dt:
            if e.dt < bye_ts - timedelta(seconds=5):
                ph = "connected"
            elif e.dt <= bye_ts + timedelta(seconds=1):
                ph = "terminating"
            else:
                ph = "post-call"
        else:
            ph = "connected"

        category_totals[e.category] += 1
        subcategory_totals[e.subcategory] += 1
        phase_counts[ph][e.category] += 1

        # 고중요도 타임라인
        if e.importance >= 3:
            timeline_events.append(e)

        # 엔진 집계
        if e.category == "engine":
            engine_stats[e.subcategory] += 1

        # keepalive
        if e.subcategory == "KEEPALIVE":
            keepalive_count += 1
        if e.subcategory == "CALL_ALIVE_HEARTBEAT":
            heartbeat_count += 1

    # 이벤트 간격 분석
    sip_events = [(e.dt, e.subcategory) for e in timeline_events if e.category == "sip" and e.dt]
    call_events = [(e.dt, e.subcategory) for e in timeline_events if e.category == "call_state" and e.dt]

    return {
        "phase_counts": {k: dict(v) for k, v in phase_counts.items()},
        "timeline_events": timeline_events,
        "engine_stats": dict(engine_stats),
        "keepalive_count": keepalive_count,
        "heartbeat_count": heartbeat_count,
        "category_totals": dict(category_totals),
        "subcategory_totals": dict(subcategory_totals),
        "sip_events": sip_events,
        "call_events": call_events,
    }


# ──────────────────────────────────────────────
# 6. Appium 시나리오 추천 생성
# ──────────────────────────────────────────────

def make_scenarios(analysis: dict, session: CallSession) -> list[dict]:
    scenarios = []
    sub = analysis["subcategory_totals"]

    def add(title, priority, trigger, detection, appium_method, evidence, feasibility, notes=""):
        scenarios.append({
            "title": title, "priority": priority, "trigger": trigger,
            "detection": detection, "appium_method": appium_method,
            "evidence": evidence, "feasibility": feasibility, "notes": notes
        })

    # SIP BYE 감지 여부
    if sub.get("BYE_RECV", 0) > 0 or sub.get("BYE_SENT", 0) > 0:
        add(
            title="통화 종료 자동 감지 (BYE 시그널)",
            priority="P0",
            trigger="상대방 또는 로컬에서 통화 종료",
            detection="로그에서 'BYE sip:' 또는 'CALL_STATUS_STOPPING' 감지",
            appium_method=(
                "idevicesyslog 스트리밍 중 'CALL_STATUS_STOPPING' 또는 "
                "'EVENT_CALL_END' 패턴 매칭 → 종료 확인"
            ),
            evidence=f"BYE_RECV: {sub.get('BYE_RECV',0)}, CALL_STOPPING: {sub.get('CALL_STOPPING',0)}",
            feasibility="★★★★★",
            notes="BYE 수신 후 audio_deact까지 약 3.1초 지연 — 대기 로직 필요"
        )
        add(
            title="통화 종료 후 UI 상태 복원 검증",
            priority="P0",
            trigger="통화 종료 (BYE 수신 후 3~4초)",
            detection="'CallViewModel deinit 처리' + 'activeCall Changed: nil'",
            appium_method=(
                "통화 종료 후 전화 목록 화면(XCUIElement)이 표시되는지 확인 "
                "driver.find_element(By.ACCESSIBILITY_ID, '통화 목록')"
            ),
            evidence=f"CALLVM_DEINIT: {sub.get('CALLVM_DEINIT',0)}, ACTIVE_CALL_NIL: {sub.get('ACTIVE_CALL_NIL',0)}",
            feasibility="★★★★☆",
            notes="CallViewModel deinit 후 약 0~100ms 내 화면 전환"
        )

    # heartbeat
    if sub.get("CALL_ALIVE_HEARTBEAT", 0) > 10:
        add(
            title="통화 활성 상태 지속 확인 (Heartbeat)",
            priority="P1",
            trigger="통화 연결 후 N초 경과",
            detection="'callWithCallID.*현재 등록된 callId' 패턴 0.5~1초 주기로 반복",
            appium_method=(
                "로그 스트림에서 heartbeat 중断 감지 (5초 이상 미출현) → "
                "예상치 않은 통화 끊김 탐지"
            ),
            evidence=f"heartbeat 총 {sub.get('CALL_ALIVE_HEARTBEAT',0)}회 감지",
            feasibility="★★★★☆",
            notes="비정상 종료(crash/네트워크 단절)와 정상 BYE를 구별하는 데 유용"
        )

    # 오디오 세션
    if sub.get("AUDIO_SESSION_DEACTIVATE", 0) > 0:
        add(
            title="오디오 세션 생명주기 검증",
            priority="P1",
            trigger="통화 종료",
            detection="'🛑 Audio session deactivated' 로그 확인",
            appium_method=(
                "통화 종료 후 5초 내 AudioSession deactivate 로그 확인 + "
                "기기 볼륨/마이크 상태 AccessibilitySnapshot 비교"
            ),
            evidence=f"AUDIO_SESSION_DEACTIVATE: {sub.get('AUDIO_SESSION_DEACTIVATE',0)}",
            feasibility="★★★☆☆",
            notes="로그 미확인 시 오디오 세션 미해제(리소스 누수) 버그 탐지 가능"
        )

    # 엔진 패킷
    engine = analysis.get("engine_stats", {})
    if engine.get("ENGINE_LIVE_BUFFER", 0) > 0:
        add(
            title="RTP 패킷 정상 송수신 검증",
            priority="P1",
            trigger="통화 중 (연결 후 10초 이상)",
            detection="'ENGINE_sendLiveBuffer' tx_count/rx_count 값 증가 확인",
            appium_method=(
                "통화 중 3초 간격으로 sendLiveBuffer 로그 파싱 → "
                "tx_count, rx_count가 단조 증가하지 않으면 테스트 FAIL"
            ),
            evidence=f"ENGINE_sendLiveBuffer: {engine.get('ENGINE_LIVE_BUFFER',0)}회",
            feasibility="★★★★☆",
            notes="일방향 오디오(음소거/패킷 손실) 탐지에 활용 가능"
        )

    if engine.get("ENGINE_MONITORING", 0) > 0:
        add(
            title="통화 중 녹음/모니터링 상태 검증",
            priority="P2",
            trigger="통화 중 10초마다",
            detection="'ENGINE_monitoringRecord' callMode=sendrecv 확인",
            appium_method=(
                "10초마다 monitoringRecord 로그 파싱 → "
                "callMode가 'sendrecv'인지 확인 (sendonly/recvonly이면 단방향 문제)"
            ),
            evidence=f"ENGINE_monitoringRecord: {engine.get('ENGINE_MONITORING',0)}회",
            feasibility="★★★☆☆",
            notes="callMode 변화 감지 시 오디오 품질 문제 조기 탐지"
        )

    # WebSocket 안정성
    if analysis.get("keepalive_count", 0) > 5:
        add(
            title="WebSocket KeepAlive 안정성 검증",
            priority="P2",
            trigger="통화 연결 유지 중",
            detection="3초마다 KEEPALIVE → KEEPALIVEOK 페어 확인",
            appium_method=(
                "통화 중 10초 동안 keepAlive 로그 미출현 감지 → "
                "WebSocket 단절 탐지 → 자동 재연결 여부 확인"
            ),
            evidence=f"KEEPALIVE: {analysis['keepalive_count']}회",
            feasibility="★★★☆☆",
            notes="keepAlive 번호 Gap(67→68→72 식으로 건너뜀) 감지 시 패킷 손실 의심"
        )

    # 통화 후 히스토리
    if sub.get("POST_CALL_SUMMARY", 0) > 0:
        add(
            title="통화 종료 후 히스토리 저장 검증",
            priority="P2",
            trigger="통화 종료 후 3초",
            detection="'통화 종료 직후 3초 대기 후 getSummary' 로그 + callId 일치 확인",
            appium_method=(
                "통화 종료 후 통화 기록 화면에서 해당 callId 항목 표시 확인 "
                "driver.find_elements → 최신 항목 callId 비교"
            ),
            evidence=f"POST_CALL_SUMMARY: {sub.get('POST_CALL_SUMMARY',0)}, HISTORY_REFRESH: {sub.get('HISTORY_REFRESH',0)}",
            feasibility="★★★★☆",
            notes="getSummary 미실행 = 통화 기록 누락 버그"
        )

    # 통화 시작 시나리오 (log에 없지만 SIP 히스토리로 추론)
    if sub.get("SIP_HISTORY", 0) > 0:
        add(
            title="발신 통화 연결 흐름 검증 (INVITE→200 OK)",
            priority="P0",
            trigger="전화걸기 버튼 탭",
            detection="INVITE 전송 → 183 Session Progress → 200 OK 시퀀스 로그 확인",
            appium_method=(
                "driver.find_element(By.XPATH, '//XCUIElementTypeButton[@name=\"전화걸기\"]').click() → "
                "로그에서 'INVITE.*sendrecv' → '200 OK.*INVITE' 순서 확인"
            ),
            evidence=f"SIP_HISTORY에서 완전한 SIP 흐름 확인: INVITE→100→183→200OK→ACK→BYE",
            feasibility="★★★★★",
            notes="SIP 히스토리 로그(CD_SIP_HISTORY)로 전체 시그널링 사후 검증 가능"
        )
        add(
            title="착신 통화 수신 흐름 검증",
            priority="P0",
            trigger="착신 전화 수신 알림",
            detection="INVITE 수신 → CallKit 알림 UI 표시 → 수락/거절 버튼",
            appium_method=(
                "pymobiledevice3 또는 idevicesyslog로 INVITE 수신 감지 → "
                "XCUIElementTypeAlert에서 수락 버튼 탭"
            ),
            evidence="현재 로그는 발신 통화 (---> INVITE 패턴). 착신은 별도 캡처 필요",
            feasibility="★★★★☆",
            notes="착신 시 iOS 시스템 CallKit UI가 앱 위에 표시되므로 XCTest 없이는 제한적"
        )

    return scenarios


# ──────────────────────────────────────────────
# 7. HTML 생성
# ──────────────────────────────────────────────

IMPORTANCE_COLORS = {0: "#999", 1: "#aaa", 2: "#555", 3: "#e67e22", 4: "#c0392b"}
CATEGORY_COLORS = {
    "sip": "#2980b9",
    "call_state": "#8e44ad",
    "audio": "#27ae60",
    "callkit": "#16a085",
    "engine": "#7f8c8d",
    "websocket": "#2c3e50",
    "app_ui": "#d35400",
    "misc": "#95a5a6",
    "noise": "#ecf0f1",
}
PRIORITY_COLORS = {"P0": "#c0392b", "P1": "#e67e22", "P2": "#2980b9", "P3": "#27ae60"}


def fmt_dt(dt):
    if dt:
        return dt.strftime("%H:%M:%S.%f")[:-3]
    return "N/A"


def delta_ms(a, b):
    if a and b:
        return int((b - a).total_seconds() * 1000)
    return None


def build_html(entries: list[LogEntry], session: CallSession,
               analysis: dict, scenarios: list[dict], log_path: str) -> str:

    total = len(entries)
    noise_count = sum(1 for e in entries if e.importance == 0)
    meaningful_count = total - noise_count

    # ── 타임라인 이벤트 rows ──
    timeline_rows = ""
    prev_dt = None
    for e in analysis["timeline_events"]:
        delta = ""
        if prev_dt and e.dt:
            ms = delta_ms(prev_dt, e.dt)
            delta = f"+{ms}ms"
        prev_dt = e.dt
        color = CATEGORY_COLORS.get(e.category, "#555")
        imp_color = IMPORTANCE_COLORS.get(e.importance, "#555")
        msg = e.message[:180].replace("<", "&lt;").replace(">", "&gt;")
        timeline_rows += f"""
        <tr>
          <td style="color:#888;font-size:12px;white-space:nowrap">{e.timestamp or ''}</td>
          <td style="font-size:11px;color:#aaa">{delta}</td>
          <td><span class="badge" style="background:{color}">{e.category}</span></td>
          <td><span class="badge" style="background:{imp_color};font-size:10px">{e.subcategory}</span></td>
          <td style="font-size:12px;max-width:500px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
              title="{msg}">{msg}</td>
        </tr>"""

    # ── SIP 흐름 rows ──
    sip_rows = ""
    sip_seq = [e for e in analysis["timeline_events"] if e.category == "sip"]
    for e in sip_seq:
        msg = e.message[:200].replace("<", "&lt;").replace(">", "&gt;")
        sip_rows += f"""
        <tr>
          <td style="white-space:nowrap">{e.timestamp or ''}</td>
          <td><span class="badge" style="background:{CATEGORY_COLORS['sip']}">{e.subcategory}</span></td>
          <td style="font-size:12px">{msg}</td>
        </tr>"""

    # ── 엔진 통계 rows ──
    engine_rows = ""
    for k, v in sorted(analysis["engine_stats"].items(), key=lambda x: -x[1]):
        engine_rows += f"<tr><td>{k}</td><td><b>{v}</b></td></tr>"

    # ── 카테고리 집계 bars ──
    cat_total = sum(analysis["category_totals"].values())
    cat_bars = ""
    for cat, cnt in sorted(analysis["category_totals"].items(), key=lambda x: -x[1]):
        pct = cnt / cat_total * 100 if cat_total else 0
        color = CATEGORY_COLORS.get(cat, "#aaa")
        cat_bars += f"""
        <div style="display:flex;align-items:center;margin:4px 0">
          <span style="width:130px;font-size:13px;color:{color}">{cat}</span>
          <div style="flex:1;background:#eee;border-radius:4px;height:14px;max-width:300px">
            <div style="width:{pct:.1f}%;background:{color};height:14px;border-radius:4px"></div>
          </div>
          <span style="margin-left:8px;font-size:12px;color:#666">{cnt} ({pct:.1f}%)</span>
        </div>"""

    # ── 시나리오 카드 ──
    scenario_cards = ""
    for i, sc in enumerate(scenarios, 1):
        p_color = PRIORITY_COLORS.get(sc["priority"], "#888")
        scenario_cards += f"""
        <div class="card" style="border-left:4px solid {p_color}">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <h3 style="margin:0">#{i} {sc['title']}</h3>
            <span class="badge" style="background:{p_color};font-size:13px">{sc['priority']}</span>
          </div>
          <div class="scenario-grid">
            <div><b>트리거</b><p>{sc['trigger']}</p></div>
            <div><b>감지 방법</b><p>{sc['detection']}</p></div>
            <div><b>Appium 구현</b><p><code>{sc['appium_method']}</code></p></div>
            <div><b>로그 근거</b><p style="color:#2980b9">{sc['evidence']}</p></div>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px">
            <span style="font-size:12px;color:#888">구현 가능성: <b>{sc['feasibility']}</b></span>
            {'<span style="font-size:12px;color:#e67e22">⚠ ' + sc['notes'] + '</span>' if sc['notes'] else ''}
          </div>
        </div>"""

    # ── 주요 타이밍 ──
    timing_rows = ""
    timings = [
        ("로그 시작", session.start_ts, None),
        ("SIP BYE 수신", session.bye_ts, session.start_ts),
        ("오디오 세션 해제", session.audio_deact_ts, session.bye_ts),
        ("통화 후 DB 처리", session.end_ts, session.audio_deact_ts),
    ]
    for label, ts, ref in timings:
        delta_str = ""
        if ref and ts:
            ms = delta_ms(ref, ts)
            delta_str = f"(+{ms}ms from prev)"
        timing_rows += f"""
        <tr>
          <td><b>{label}</b></td>
          <td style="font-family:monospace">{fmt_dt(ts)}</td>
          <td style="color:#888;font-size:12px">{delta_str}</td>
        </tr>"""

    # ── 로그 노이즈 분석 ──
    noise_pct = noise_count / total * 100 if total else 0

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ixi-O 통화 로그 분석 보고서</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; background:#f5f7fa; color:#2c3e50; margin:0; padding:0; }}
  .header {{ background:linear-gradient(135deg,#1a1a2e,#16213e); color:#fff; padding:32px 40px; }}
  .header h1 {{ margin:0 0 8px; font-size:26px; }}
  .header p {{ margin:0; opacity:.7; font-size:14px; }}
  .container {{ max-width:1200px; margin:0 auto; padding:24px 20px; }}
  .section {{ background:#fff; border-radius:12px; padding:24px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,.06); }}
  .section h2 {{ margin:0 0 16px; font-size:18px; border-bottom:2px solid #f0f0f0; padding-bottom:10px; }}
  .card {{ background:#f9f9f9; border-radius:8px; padding:16px; margin-bottom:16px; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:12px; font-size:11px; color:#fff; font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ background:#f8f9fa; padding:8px 12px; text-align:left; border-bottom:1px solid #dee2e6; font-size:12px; color:#666; }}
  td {{ padding:7px 12px; border-bottom:1px solid #f0f0f0; vertical-align:top; }}
  tr:hover td {{ background:#fafbff; }}
  .stat-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:16px; }}
  .stat-box {{ background:#f8f9fa; border-radius:8px; padding:16px; text-align:center; }}
  .stat-box .num {{ font-size:28px; font-weight:700; color:#2980b9; }}
  .stat-box .lbl {{ font-size:12px; color:#888; margin-top:4px; }}
  .scenario-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px; }}
  code {{ background:#f0f0f0; padding:2px 6px; border-radius:4px; font-size:11px; word-break:break-all; }}
  .timeline-container {{ max-height:600px; overflow-y:auto; }}
  .phase-badge {{ padding:3px 10px; border-radius:12px; font-size:11px; font-weight:600; }}
  @media(max-width:700px) {{ .scenario-grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="header">
  <h1>📞 ixi-O 통화 로그 분석 보고서</h1>
  <p>파일: {log_path} &nbsp;|&nbsp; 생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp;
  Call ID: <code style="color:#7fb3d3">{session.call_id or 'N/A'}</code></p>
</div>

<div class="container">

  <!-- ① 요약 통계 -->
  <div class="section">
    <h2>📊 로그 요약</h2>
    <div class="stat-grid">
      <div class="stat-box"><div class="num">{total:,}</div><div class="lbl">전체 로그 줄</div></div>
      <div class="stat-box"><div class="num">{noise_count:,}</div><div class="lbl">저수준 노이즈 필터됨<br><small>({noise_pct:.1f}%)</small></div></div>
      <div class="stat-box"><div class="num">{meaningful_count:,}</div><div class="lbl">유의미한 로그</div></div>
      <div class="stat-box"><div class="num">{len(analysis['timeline_events'])}</div><div class="lbl">주요 이벤트 (중요도≥3)</div></div>
      <div class="stat-box"><div class="num">{analysis['keepalive_count']}</div><div class="lbl">WebSocket KeepAlive</div></div>
      <div class="stat-box"><div class="num">{analysis['heartbeat_count']}</div><div class="lbl">통화 활성 Heartbeat</div></div>
    </div>
  </div>

  <!-- ② 통화 타이밍 -->
  <div class="section">
    <h2>⏱ 통화 이벤트 타이밍</h2>
    <table>
      <thead><tr><th>이벤트</th><th>시각</th><th>이전 이벤트 대비</th></tr></thead>
      <tbody>
        {timing_rows}
        <tr>
          <td><b>통화번호</b></td>
          <td style="font-family:monospace">{session.call_number or '미감지'}</td>
          <td></td>
        </tr>
      </tbody>
    </table>
    <p style="color:#888;font-size:12px;margin-top:12px">
      * 이 로그는 통화 이미 연결된 상태에서 시작됩니다 (로그 범위: {fmt_dt(session.start_ts)} ~ {fmt_dt(session.end_ts)}).<br>
      * 통화 시작부터 캡처하려면 전화걸기 직전부터 idevicesyslog를 실행하세요.
    </p>
  </div>

  <!-- ③ 카테고리 분포 -->
  <div class="section">
    <h2>🗂 로그 카테고리 분포 (노이즈 제외)</h2>
    {cat_bars}
  </div>

  <!-- ④ SIP 시그널링 흐름 -->
  <div class="section">
    <h2>📡 SIP 시그널링 흐름</h2>
    {'<table><thead><tr><th>시각</th><th>이벤트</th><th>메시지</th></tr></thead><tbody>' + sip_rows + '</tbody></table>' if sip_rows else '<p style="color:#888">SIP 이벤트 없음</p>'}
    <div style="margin-top:16px;padding:12px;background:#eaf4fb;border-radius:8px;font-size:13px">
      <b>📌 확인된 SIP 흐름 (CD_SIP_HISTORY 재구성):</b><br>
      <code>--→ INVITE [sendrecv] → ←100 Trying → ←183 Session Progress [sendrecv] → --→ PRACK → ←200 OK (PRACK) → ←200 OK (INVITE) → --→ ACK → ... → ←BYE → 종료</code>
    </div>
  </div>

  <!-- ⑤ 엔진/DataDog 통계 -->
  <div class="section">
    <h2>📈 엔진(DataDog) 이벤트 통계</h2>
    <table style="max-width:400px">
      <thead><tr><th>이벤트 타입</th><th>발생 횟수</th></tr></thead>
      <tbody>{engine_rows}</tbody>
    </table>
    <p style="color:#888;font-size:12px;margin-top:8px">
      sendLiveBuffer = 3초 주기 | HealthCheck = 1초 주기 | monitoringRecord = 10초 주기
    </p>
  </div>

  <!-- ⑥ 주요 이벤트 타임라인 -->
  <div class="section">
    <h2>🕐 주요 이벤트 타임라인 (중요도 ≥ 3)</h2>
    <div class="timeline-container">
      <table>
        <thead><tr><th>시각</th><th>Δ</th><th>카테고리</th><th>이벤트</th><th>메시지</th></tr></thead>
        <tbody>{timeline_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- ⑦ Appium 시나리오 추천 -->
  <div class="section">
    <h2>🤖 Appium 테스트 자동화 시나리오 추천 ({len(scenarios)}개)</h2>
    <p style="color:#888;font-size:13px;margin-top:-8px">로그 분석 결과 기반으로 구현 가능한 자동화 시나리오입니다.</p>
    {scenario_cards}
  </div>

  <!-- ⑧ 데이터 수집 권장사항 -->
  <div class="section">
    <h2>📋 분석 한계 및 추가 캡처 권장사항</h2>
    <table>
      <thead><tr><th>필요 데이터</th><th>현재 상태</th><th>캡처 방법</th></tr></thead>
      <tbody>
        <tr>
          <td><b>통화 전 (앱 실행 후 전화걸기 전)</b></td>
          <td style="color:#c0392b">미캡처 — 로그가 통화 중부터 시작</td>
          <td><code>idevicesyslog -u UDID &gt; log.txt</code> 를 전화걸기 전부터 실행</td>
        </tr>
        <tr>
          <td><b>INVITE 전송 시점</b></td>
          <td style="color:#c0392b">미캡처 (SIP 히스토리에서 간접 확인만)</td>
          <td>전화걸기 버튼 탭 직전부터 로깅 시작</td>
        </tr>
        <tr>
          <td><b>착신 통화 수신 흐름</b></td>
          <td style="color:#c0392b">미캡처 (이 로그는 발신 통화)</td>
          <td>다른 기기에서 ixi-O로 전화 후 별도 캡처 필요</td>
        </tr>
        <tr>
          <td><b>통화 중 오디오 품질 지표</b></td>
          <td style="color:#e67e22">간접 확인 가능 (tx/rx count 값 필요)</td>
          <td>ENGINE_sendLiveBuffer 로그에서 tx_count, rx_count 파싱</td>
        </tr>
        <tr>
          <td><b>통화 연결 실패 케이스</b></td>
          <td style="color:#c0392b">미캡처</td>
          <td>네트워크 차단 상태에서 발신 시도 후 캡처</td>
        </tr>
        <tr>
          <td><b>상대방이 끊는 경우 vs 로컬 종료</b></td>
          <td style="color:#e67e22">BYE_RECV만 확인됨 (두 케이스 모두 캡처 필요)</td>
          <td>로컬 종료 시: BYE_SENT 패턴 확인 필요</td>
        </tr>
      </tbody>
    </table>
  </div>

</div>
</body>
</html>"""
    return html


# ──────────────────────────────────────────────
# 8. 메인
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ixi-O 통화 로그 → HTML 분석 보고서")
    parser.add_argument("log_file", nargs="?", default="log.txt", help="분석할 로그 파일")
    parser.add_argument("--output", "-o", default="call_log_report.html", help="출력 HTML 파일명")
    args = parser.parse_args()

    log_path = Path(args.log_file)
    if not log_path.exists():
        print(f"[ERROR] 파일 없음: {log_path}")
        sys.exit(1)

    print(f"[1/5] 로그 파싱 중: {log_path} ({log_path.stat().st_size // 1024:,} KB)")
    entries: list[LogEntry] = []
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            e = parse_line(raw)
            if e.process in ("ixi-O", "") or "ixi-O" in raw:
                entries.append(e)

    print(f"     → ixi-O 로그 {len(entries):,}줄 파싱 완료")

    print("[2/5] 통화 세션 추론 중")
    session = infer_session(entries)
    print(f"     → callId: {session.call_id}")
    print(f"     → 범위: {fmt_dt(session.start_ts)} ~ {fmt_dt(session.end_ts)}")
    print(f"     → BYE 수신: {fmt_dt(session.bye_ts)}")

    print("[3/5] 이벤트 분석 중")
    analysis = analyze(entries, session)
    print(f"     → 주요 이벤트: {len(analysis['timeline_events'])}개")
    print(f"     → 엔진 이벤트 종류: {len(analysis['engine_stats'])}개")

    print("[4/5] Appium 시나리오 생성 중")
    scenarios = make_scenarios(analysis, session)
    print(f"     → 시나리오: {len(scenarios)}개")

    print("[5/5] HTML 보고서 생성 중")
    html = build_html(entries, session, analysis, scenarios, str(log_path))
    out_path = Path(args.output)
    out_path.write_text(html, encoding="utf-8")
    print(f"\n✅ 보고서 생성 완료: {out_path.resolve()}")
    print(f"   브라우저에서 열기: open {out_path.resolve()}")


if __name__ == "__main__":
    main()
