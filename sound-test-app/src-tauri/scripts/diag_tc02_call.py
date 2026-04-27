#!/usr/bin/env python3
"""
diag_tc02_call.py — TC_02 통화 단계별 진단 스크립트 (10회 반복)

Android(발신) → iPhone(수신) → 통화 확인 → 종료
각 단계 성공/실패/소요시간을 세밀하게 추적합니다.

실행:
    python3 diag_tc02_call.py
    python3 diag_tc02_call.py --runs 3  # 3회만
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ══════════════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════════════
ANDROID_UDID     = '192.168.219.143:5555'
ANDROID_PKG      = 'com.lguplus.aicallagent'
IOS_PHONE_NO     = '01022332512'    # iPhone 번호 (Android → iPhone 발신)
WDA_URL          = 'http://192.168.219.119:8110'
IOS_BUNDLE_ID    = 'com.lguplus.aicallagent'

# 좌표 폴백 (Galaxy Z Fold4 기준)
COORD_KEYPAD_TAB = (540, 2102)
COORD_CALL_BTN   = (540, 1818)

# ══════════════════════════════════════════════════════════════
# 결과 구조체
# ══════════════════════════════════════════════════════════════
@dataclass
class StepResult:
    name: str
    ok: bool
    elapsed: float
    detail: str = ''

@dataclass
class RunResult:
    run: int
    steps: list = field(default_factory=list)

    def add(self, name, ok, elapsed, detail=''):
        self.steps.append(StepResult(name, ok, elapsed, detail))
        icon = '✅' if ok else '❌'
        print(f"  {icon} [{elapsed:.2f}s] {name}" + (f" — {detail}" if detail else ''))

    @property
    def ok(self):
        return all(s.ok for s in self.steps)

    def first_fail(self):
        for s in self.steps:
            if not s.ok:
                return s
        return None


# ══════════════════════════════════════════════════════════════
# ADB 헬퍼
# ══════════════════════════════════════════════════════════════
def adb(*cmds, timeout=10):
    return subprocess.run(
        ['adb', '-s', ANDROID_UDID] + list(cmds),
        capture_output=True, text=True, timeout=timeout
    )


def dump_ui() -> tuple[Optional[ET.Element], Optional[str]]:
    """UI 덤프 시도. (root, error_msg) 반환."""
    r = adb('shell', 'uiautomator', 'dump', '/sdcard/window_dump.xml', timeout=12)
    stdout = r.stdout.strip()
    stderr = r.stderr.strip()

    # Samsung Android 16: 성공 시 "UI hierchary dumped to: /sdcard/window_dump.xml"
    if r.returncode != 0:
        return None, f"rc={r.returncode} stderr={stderr!r}"
    if 'dumped' not in stdout.lower() and 'hierarchy' not in stdout.lower():
        return None, f"예상 문구 없음: stdout={stdout!r} stderr={stderr!r}"

    r2 = adb('shell', 'cat', '/sdcard/window_dump.xml', timeout=5)
    raw = r2.stdout.strip()
    if not raw:
        return None, "cat 결과 빈 문자열"
    try:
        root = ET.fromstring(r2.stdout)
        return root, None
    except ET.ParseError as e:
        return None, f"XML 파싱 실패: {e} (앞 200자: {raw[:200]!r})"


def find_node(root, *, content_desc=None, text=None, resource_id=None):
    """매처 조건에 맞는 첫 노드 중심 좌표 반환."""
    for node in root.iter('node'):
        if content_desc and content_desc not in (node.get('content-desc') or ''):
            continue
        if text and text not in (node.get('text') or ''):
            continue
        if resource_id and resource_id not in (node.get('resource-id') or ''):
            continue
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if m:
            return (int(m.group(1)) + int(m.group(3))) // 2, \
                   (int(m.group(2)) + int(m.group(4))) // 2
    return None


def tap(x, y):
    adb('shell', 'input', 'tap', str(x), str(y), timeout=5)


def get_call_state() -> int:
    """mCallState 값 (0=IDLE, 1=RINGING, 2=OFFHOOK/-1=미감지)"""
    r = adb('shell', 'dumpsys', 'telephony.registry', timeout=10)
    m = re.search(r'mCallState[=:]\s*(\d)', r.stdout)
    return int(m.group(1)) if m else -1


def wait_call_state(target: int, timeout: float = 20.0) -> tuple[bool, float]:
    """target 상태 대기. (성공여부, 소요초)"""
    t0 = time.time()
    deadline = t0 + timeout
    while time.time() < deadline:
        if get_call_state() == target:
            return True, time.time() - t0
        time.sleep(0.4)
    return False, time.time() - t0


def wait_idle_call_state(timeout: float = 10.0) -> bool:
    ok, _ = wait_call_state(0, timeout)
    return ok


# ══════════════════════════════════════════════════════════════
# WDA 헬퍼 (urllib만 사용 — 외부 의존 없음)
# ══════════════════════════════════════════════════════════════
def _wda_req(method, path, body=None, timeout=8):
    url = f"{WDA_URL}{path}"
    data = json.dumps(body or {}).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'} if data else {}
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except Exception as e:
        return None


def wda_status():
    return _wda_req('GET', '/status')


def wda_sessions():
    r = _wda_req('GET', '/sessions')
    return r.get('value', []) if r else []


def wda_delete_session(sid):
    _wda_req('DELETE', f'/session/{sid}')


def wda_new_session() -> Optional[str]:
    r = _wda_req('POST', '/session', {
        'capabilities': {'alwaysMatch': {'bundleId': IOS_BUNDLE_ID}}
    })
    return (r or {}).get('sessionId')


def wda_page_source(sid) -> str:
    r = _wda_req('GET', f'/session/{sid}/source', timeout=15)
    return (r or {}).get('value', '')


def wda_find_element(sid, accessibility_id) -> Optional[str]:
    r = _wda_req('POST', f'/session/{sid}/element',
                 {'using': 'accessibility id', 'value': accessibility_id})
    return (r or {}).get('value', {}).get('ELEMENT')


def wda_click(sid, el_id):
    _wda_req('POST', f'/session/{sid}/element/{el_id}/click', {})


def wda_tap(sid, x, y):
    _wda_req('POST', f'/session/{sid}/wda/tap/0', {'x': x, 'y': y})


def wda_new_session_springboard() -> Optional[str]:
    """SpringBoard 세션 생성 — 시스템 전체 UI(CallKit 수신 화면 포함) 접근용."""
    r = _wda_req('POST', '/session', {
        'capabilities': {'alwaysMatch': {'bundleId': 'com.apple.springboard'}}
    })
    return (r or {}).get('sessionId')


def wda_get_or_create_session() -> Optional[str]:
    """기존 세션 재사용 또는 신규 생성.

    CallKit 수신 화면은 시스템 레벨 UI라서 com.apple.springboard 세션으로
    접근해야 page_source에서 '받기'/'거절' 버튼이 보임.
    springboard 세션 실패 시 ixiO 앱 세션으로 폴백.
    """
    for s in wda_sessions():
        sid = s.get('id')
        if sid:
            wda_delete_session(sid)
    # 1차: springboard (CallKit 시스템 UI 감지)
    sid = wda_new_session_springboard()
    if sid:
        print(f"    WDA 세션: springboard (시스템 UI 모드)")
        return sid
    # 2차 폴백: ixiO 앱 세션
    print(f"    WDA 세션: springboard 실패 → ixiO 앱 폴백")
    return wda_new_session()


# ══════════════════════════════════════════════════════════════
# 사전 진단
# ══════════════════════════════════════════════════════════════
def preflight():
    print("=" * 60)
    print("🔍 사전 진단")
    print("=" * 60)

    # 1. ADB 연결
    r = subprocess.run(['adb', '-s', ANDROID_UDID, 'get-state'],
                       capture_output=True, text=True, timeout=5)
    ok = r.stdout.strip() == 'device'
    print(f"  {'✅' if ok else '❌'} ADB 연결: {r.stdout.strip() or r.stderr.strip()}")
    if not ok:
        return False

    # 2. dump 5회 성공률
    print(f"  📋 uiautomator dump 5회 성공률 테스트...")
    dump_ok = 0
    for i in range(5):
        root, err = dump_ui()
        if root is not None:
            dump_ok += 1
            pkgs = set(n.get('package','') for n in root.iter('node') if n.get('package'))
            print(f"    [{i+1}] ✅ 성공 — 패키지: {list(pkgs)[:3]}")
        else:
            print(f"    [{i+1}] ❌ 실패 — {err}")
        time.sleep(0.5)
    print(f"  📊 dump 성공률: {dump_ok}/5")

    # 3. WDA 상태
    s = wda_status()
    wda_ok = s is not None
    print(f"  {'✅' if wda_ok else '❌'} WDA({WDA_URL}): {'응답' if wda_ok else '무응답'}")

    # 4. 현재 call state
    state = get_call_state()
    state_name = {0: 'IDLE', 1: 'RINGING', 2: 'OFFHOOK'}.get(state, f'미감지({state})')
    print(f"  📞 현재 mCallState: {state_name}")
    if state != 0:
        print(f"  ⚠️ IDLE이 아님 — 통화 강제 종료 시도")
        adb('shell', 'input', 'keyevent', 'KEYCODE_ENDCALL', timeout=5)
        time.sleep(2)

    print()
    return wda_ok


# ══════════════════════════════════════════════════════════════
# 단일 실행 (한 회)
# ══════════════════════════════════════════════════════════════
def run_once(run_no: int) -> RunResult:
    result = RunResult(run=run_no)
    print(f"\n{'─'*60}")
    print(f"🔁 Run {run_no:02d}  [{datetime.now().strftime('%H:%M:%S')}]")
    print(f"{'─'*60}")

    # ── Step 1: 앱 실행 ──────────────────────────────────────
    t0 = time.time()
    adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP', timeout=5)
    adb('shell', 'am', 'force-stop', ANDROID_PKG, timeout=5)
    time.sleep(0.5)
    r = adb('shell', 'monkey', '-p', ANDROID_PKG,
            '-c', 'android.intent.category.LAUNCHER', '1', timeout=8)
    app_ok = r.returncode == 0
    result.add('앱 실행', app_ok, time.time() - t0,
               r.stderr.strip() if not app_ok else '')
    if not app_ok:
        return result

    # ── Step 2: 앱 UI 준비 대기 (dump 폴링) ─────────────────
    t0 = time.time()
    ready = False
    attempts = 0
    for _ in range(20):  # 최대 20초
        attempts += 1
        root, err = dump_ui()
        if root is not None:
            pkgs = [n.get('package','') for n in root.iter('node') if ANDROID_PKG in (n.get('package') or '')]
            if pkgs:
                ready = True
                break
            else:
                print(f"    dump 성공이나 앱 패키지 없음 (시도 {attempts}회)")
        else:
            print(f"    dump 실패 (시도 {attempts}회): {err}")
        time.sleep(1.0)
    result.add('앱 UI 준비', ready, time.time() - t0,
               f'{attempts}회 시도' + ('' if ready else ' — 타임아웃'))

    # ── Step 3: 키패드 탭 ────────────────────────────────────
    t0 = time.time()
    keypad_found = False
    root, _ = dump_ui()
    if root is not None:
        for matcher in [{'content_desc': '키패드'}, {'text': '키패드'}, {'content_desc': 'Keypad'}]:
            coord = find_node(root, **matcher)
            if coord:
                tap(*coord)
                keypad_found = True
                print(f"    키패드 UI 발견 → 탭 {coord}")
                break
    if not keypad_found:
        tap(*COORD_KEYPAD_TAB)
        print(f"    키패드 UI 미발견 → 폴백 탭 {COORD_KEYPAD_TAB}")
    time.sleep(1.0)
    result.add('키패드 탭', True, time.time() - t0,
               'UI 발견' if keypad_found else '폴백 좌표')

    # ── Step 3.5: WDA 세션 사전 생성 + iPhone 잠금 ───────────────
    # springboard 세션이 iOS를 홈화면(foreground) 상태로 만들어
    # 전화 수신 시 CallKit 전체화면 대신 Dynamic Island로 표시됨.
    # → 세션 생성 후 즉시 /wda/lock 으로 잠금화면 전환.
    #   잠금화면에서 전화 오면 항상 전체화면 수신 UI 표시됨.
    t0 = time.time()
    sid = wda_get_or_create_session()
    if sid:
        # iPhone 잠금화면으로 전환 (세션 기반)
        lock_r = _wda_req('POST', f'/session/{sid}/wda/lock', {}, timeout=8)
        if lock_r is None:
            # 글로벌 lock 엔드포인트 폴백
            lock_r = _wda_req('POST', '/wda/lock', {}, timeout=8)
        locked = lock_r is not None
        print(f"    iPhone 잠금: {'✅' if locked else '❌'} (전체화면 수신 UI 유도)")
        time.sleep(1.0)  # 잠금 전환 대기
    result.add('WDA 세션+잠금', sid is not None, time.time() - t0,
               f'sid={sid[:8]}...' if sid else 'None')
    if not sid:
        return result

    # ── Step 4+5: CALL 인텐트 발신 ────────────────────────────
    # ixiO는 React Native 기반 — adb input text/tap으로는 앱 state가
    # 업데이트되지 않아 발신 버튼 비활성화. 인텐트로 직접 발신.
    t0 = time.time()
    r = adb('shell', 'am', 'start', '-a', 'android.intent.action.CALL',
            '-d', f'tel:{IOS_PHONE_NO}', timeout=10)
    intent_ok = r.returncode == 0
    detail = r.stdout.strip().split('\n')[0] if intent_ok else r.stderr.strip()
    print(f"    인텐트: {detail}")
    result.add('CALL 인텐트 발신', intent_ok, time.time() - t0, detail[:60])
    if not intent_ok:
        return result

    # ── Step 6: Android 발신 상태 확인 (RINGING 또는 OFFHOOK) ─
    t0 = time.time()
    dialing = False
    state_reached = -1
    for _ in range(30):  # 15초
        s = get_call_state()
        if s in (1, 2):
            dialing = True
            state_reached = s
            break
        time.sleep(0.5)
    state_name = {1: 'RINGING', 2: 'OFFHOOK'}.get(state_reached, f'({state_reached})')
    result.add('Android 발신 확인', dialing, time.time() - t0,
               f'mCallState={state_name}' if dialing else f'IDLE 유지 (mCallState={get_call_state()})')
    if not dialing:
        # 발신 안 됨 → 정리 후 종료
        adb('shell', 'input', 'keyevent', 'KEYCODE_ENDCALL', timeout=5)
        return result

    # ── Step 7: WDA 세션 유효성 확인 ──────────────────────────
    # 세션은 Step 3.5에서 이미 생성됨 — 살아있는지만 확인
    t0 = time.time()
    st = _wda_req('GET', f'/session/{sid}') if sid else None
    if not st:
        print(f"    세션 만료 → 재생성 시도")
        sid = wda_get_or_create_session()
        time.sleep(0.3)
    result.add('WDA 세션 확인', sid is not None, time.time() - t0,
               f'sid={sid[:8]}...' if sid else 'None')
    if not sid:
        adb('shell', 'input', 'keyevent', 'KEYCODE_ENDCALL', timeout=5)
        return result

    # ── Step 8: iPhone 수신 화면 대기 및 수락 ────────────────
    t0 = time.time()
    answered = False
    # 전체화면 수신 키워드 + Dynamic Island 전환 후 키워드
    incoming_kws = ['받기', '응답', '수락', '거절', 'Decline', 'Accept',
                    '전화 수신', '수신 중', 'Incoming', '통화', 'End', 'Mute']
    answer_kws   = ['받기', '응답', '수락', 'Accept']

    for attempt in range(35):
        src = wda_page_source(sid)
        has_incoming = any(kw in src for kw in incoming_kws)

        # Dynamic Island 수신 감지 (card: 또는 '님과 통화하기' 패턴)
        card_labels   = re.findall(r'label="(card:com\.apple\.InCallService:[^"]*)"', src)
        caller_labels = re.findall(r'label="([^"]*님과 통화하기)"', src)
        is_dynamic_island = bool(card_labels or caller_labels)

        if attempt == 0 or attempt % 5 == 0:
            labels = re.findall(r'(?:label|name)="([^"]+)"', src)
            uniq = sorted(set(l for l in labels if l.strip()))[:12]
            di_tag = ' [DI]' if is_dynamic_island else ''
            print(f"    [WDA {attempt+1}초] 수신화면={'✅' if has_incoming else '❌'}{di_tag} "
                  f"buttons={uniq}")

        if has_incoming or is_dynamic_island:
            # 1차: 직접 받기 버튼 탭
            for kw in answer_kws:
                el = wda_find_element(sid, kw)
                if el:
                    wda_click(sid, el)
                    answered = True
                    print(f"    ✅ '{kw}' 버튼 클릭 (attempt {attempt+1})")
                    break

            if not answered and is_dynamic_island:
                # 2차: Dynamic Island 카드 탭 → 전체화면 전환 후 받기
                di_label = next(iter(card_labels or caller_labels), None)
                if di_label:
                    el = wda_find_element(sid, di_label)
                    if el:
                        wda_click(sid, el)
                        print(f"    DI 탭: '{di_label[:60]}' → 전체화면 전환 대기")
                        time.sleep(1.5)
                        for kw in answer_kws:
                            el2 = wda_find_element(sid, kw)
                            if el2:
                                wda_click(sid, el2)
                                answered = True
                                print(f"    ✅ DI→전체화면 '{kw}' 클릭")
                                break

            if answered:
                break

        time.sleep(1.0)

    result.add('iPhone 수신', answered, time.time() - t0,
               '버튼 클릭' if answered else '수신 화면 미감지 또는 버튼 없음')
    if not answered:
        adb('shell', 'input', 'keyevent', 'KEYCODE_ENDCALL', timeout=5)
        wda_delete_session(sid)
        return result

    # ── Step 9: 통화 연결 확인 (OFFHOOK) ─────────────────────
    t0 = time.time()
    ok, elapsed = wait_call_state(2, timeout=15)
    result.add('통화 OFFHOOK', ok, elapsed,
               f'mCallState={get_call_state()}' if not ok else '')

    # ── Step 10: 2초 유지 후 종료 ─────────────────────────────
    time.sleep(2.0)
    t0 = time.time()
    adb('shell', 'input', 'keyevent', 'KEYCODE_ENDCALL', timeout=5)
    idle_ok = wait_idle_call_state(timeout=10)
    result.add('통화 종료', idle_ok, time.time() - t0,
               f'mCallState={get_call_state()}' if not idle_ok else '')

    wda_delete_session(sid)
    return result


# ══════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description='TC_02 통화 진단 스크립트')
    parser.add_argument('--runs', type=int, default=10, help='반복 횟수 (기본 10)')
    args = parser.parse_args()

    if not preflight():
        print("❌ 사전 진단 실패 — ADB 연결을 확인하세요")
        sys.exit(1)

    results: list[RunResult] = []
    for i in range(1, args.runs + 1):
        r = run_once(i)
        results.append(r)
        # 실패 시 2초 쉬고 다음 회차
        if not r.ok:
            time.sleep(2)

    # ── 최종 집계 ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"📊 최종 결과 ({args.runs}회)")
    print(f"{'='*60}")

    # 단계별 성공률
    all_steps = [s.name for s in results[0].steps] if results else []
    step_counts: dict[str, int] = {s: 0 for s in all_steps}
    for r in results:
        for s in r.steps:
            if s.ok:
                step_counts[s.name] = step_counts.get(s.name, 0) + 1

    for step, cnt in step_counts.items():
        pct = cnt / args.runs * 100
        bar = '█' * cnt + '░' * (args.runs - cnt)
        print(f"  {bar} {cnt:2d}/{args.runs} ({pct:5.1f}%)  {step}")

    total_ok = sum(1 for r in results if r.ok)
    print(f"\n  전체 성공: {total_ok}/{args.runs} ({total_ok/args.runs*100:.1f}%)")

    # 실패 패턴
    fails = [r for r in results if not r.ok]
    if fails:
        from collections import Counter
        fail_steps = Counter(r.first_fail().name for r in fails if r.first_fail())
        print(f"\n  실패 원인 분포:")
        for step, cnt in fail_steps.most_common():
            print(f"    [{cnt}회] 첫 실패 단계: {step}")


if __name__ == '__main__':
    main()
