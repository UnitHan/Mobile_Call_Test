#!/usr/bin/env python3
"""iOS 통화 타이머 00:00 기준점 측정 테스트.

TC_01 시나리오 (iPhone→Android):
  1. iOS Appium으로 iPhone에서 익시오 키패드 발신
  2. Android ADB RINGING 감지 → accept
  3. ADB OFFHOOK(수락 완료) 타임스탬프 기록
  4. iOS Appium page_source 고속 폴링 → 통화 타이머 \\d:\\d\\d 최초 등장 타임스탬프 기록
  5. 반복 → OFFHOOK 대비 iOS 타이머 00:00 표시까지 지연 분포 출력

사용 전 별도 터미널에서 Appium 서버 실행:
    appium -p 4732 --relaxed-security

실행:
    python measure_ios_call_timer.py [--runs 20] [--appium-port 4732] [--poll-ms 100]

출력:
    - 매 회 OFFHOOK_ts, ios_timer_ts, 지연(ms)
    - 전체 통계 (min/max/mean/median/stddev)
    - 결과 JSON 저장
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from appium import webdriver
from appium.options.common import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy

# ─────────────────────────────────────────────────────────────────────────────
#  설정 (test_call_connect.py 와 동일 디바이스)
# ─────────────────────────────────────────────────────────────────────────────
IOS_UDID         = '00008150-00110C341E38401C'
ANDROID_UDID     = '192.168.219.103:5555'
IOS_NUMBER       = '01022332512'
ANDROID_NUMBER   = '01083330025'
IXIO_BUNDLE_IOS  = 'com.lguplus.aicallagent'

KEYPAD_KR = {
    '0': '공', '1': '일', '2': '이', '3': '삼', '4': '사',
    '5': '오', '6': '육', '7': '칠', '8': '팔', '9': '구',
    '*': '별', '#': '#',
}
IOS_CALL_BTNS = ['끊기', 'End', '음소거', 'Mute', '스피커', 'Speaker', '보류', 'Hold']
# 통화 타이머는 00:xx 형식 (통화 직후 1분 이내) — 상태바 시각(04:29)·최근통화시간(04:29) 제외
_TIMER_RE = re.compile(r'\b(00:\d{2})\b')

# ─────────────────────────────────────────────────────────────────────────────
#  ADB 유틸
# ─────────────────────────────────────────────────────────────────────────────

def adb(args: list[str], timeout: int = 6) -> str:
    try:
        r = subprocess.run(
            ['adb', '-s', ANDROID_UDID, 'shell'] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip()
    except Exception:
        return ''


def adb_cmd(args: list[str], timeout: int = 6) -> str:
    """adb (shell 없이) 직접 명령."""
    try:
        r = subprocess.run(
            ['adb', '-s', ANDROID_UDID] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip()
    except Exception:
        return ''


def adb_ensure_connected() -> bool:
    try:
        if 'ok' in subprocess.run(
            ['adb', '-s', ANDROID_UDID, 'shell', 'echo', 'ok'],
            capture_output=True, text=True, timeout=5,
        ).stdout:
            return True
    except Exception:
        pass
    # 재연결 시도
    try:
        subprocess.run(['adb', 'connect', ANDROID_UDID], capture_output=True, timeout=10)
        time.sleep(0.5)
        res = subprocess.run(
            ['adb', '-s', ANDROID_UDID, 'shell', 'echo', 'ok'],
            capture_output=True, text=True, timeout=5,
        )
        return 'ok' in res.stdout
    except Exception:
        return False


def detect_call_state() -> int:
    """0=IDLE, 1=RINGING, 2=OFFHOOK."""
    out = adb(['dumpsys', 'telephony.registry', '|', 'grep', '-m1', 'mCallState'])
    m = re.search(r'mCallState=(\d+)', out)
    return int(m.group(1)) if m else -1


def wait_ringing(timeout: float = 40.0) -> float | None:
    """RINGING 최초 감지 시각(time.time()) 반환. 타임아웃 시 None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if detect_call_state() == 1:
            return time.time()
        time.sleep(0.3)
    return None


def accept_android_call() -> float | None:
    """KEYCODE_CALL 전송 후 OFFHOOK 확인. OFFHOOK 시각 반환, 실패 시 None."""
    # ixio UI 안정화 대기 (5 초, 중간 자동수락 감지)
    settle_deadline = time.time() + 5.0
    while time.time() < settle_deadline:
        if detect_call_state() == 2:
            return time.time()
        time.sleep(0.3)

    # KEYCODE_CALL 전략들
    strategies = [
        (['input', 'keyevent', '5'],         'KEYCODE_CALL'),
        (['input', 'keyevent', 'KEYCODE_CALL'], 'KEYCODE_CALL(name)'),
    ]
    for cmd, label in strategies:
        adb(cmd)
        # OFFHOOK 대기 (3초)
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if detect_call_state() == 2:
                print(f"    ✅ OFFHOOK 확인 ({label})")
                return time.time()
            time.sleep(0.2)

    # 최후 확인
    if detect_call_state() == 2:
        return time.time()
    return None


def end_call_android():
    try:
        adb(['input', 'keyevent', 'KEYCODE_ENDCALL'])
    except Exception:
        pass


def ensure_android_idle():
    adb(['input', 'keyevent', 'KEYCODE_WAKEUP'])
    state = detect_call_state()
    if state in (1, 2):
        print(f"    ⚠️ Android idle 아님 ({state}) → ENDCALL 후 3초 대기")
        end_call_android()
        time.sleep(3)


# ─────────────────────────────────────────────────────────────────────────────
#  iOS Appium 유틸
# ─────────────────────────────────────────────────────────────────────────────

def find_wda_url() -> str | None:
    """실행 중인 WDA URL 탐지 (8100 포트 체크)."""
    import socket
    for ip in ['192.168.219.100', '192.168.219.1']:
        try:
            s = socket.create_connection((ip, 8100), timeout=1)
            s.close()
            return f'http://{ip}:8100'
        except Exception:
            pass
    return None


def get_ios_version() -> str:
    try:
        r = subprocess.run(
            ['xcrun', 'devicectl', 'list', 'devices', '--json-output', '/dev/stdout'],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(r.stdout)
        for dev in data.get('result', {}).get('devices', []):
            udid = (dev.get('hardwareProperties', {}).get('udid', '')
                    or dev.get('identifier', ''))
            if IOS_UDID.lower() in udid.lower():
                ver = (dev.get('deviceProperties', {}).get('osVersionNumber', '')
                       or dev.get('osVersion', ''))
                if ver:
                    return ver
    except Exception:
        pass
    try:
        r = subprocess.run(
            ['ideviceinfo', '-u', IOS_UDID, '-k', 'ProductVersion'],
            capture_output=True, text=True, timeout=5,
        )
        v = r.stdout.strip()
        if v:
            return v
    except Exception:
        pass
    return '18.0'


def create_ios_driver(appium_port: int) -> webdriver.Remote:
    wda_url = find_wda_url()
    ios_version = get_ios_version()
    print(f"  iOS 버전: {ios_version}")

    caps = {
        'platformName': 'iOS',
        'appium:deviceName': 'timer_iphone',
        'appium:udid': IOS_UDID,
        'appium:automationName': 'XCUITest',
        'appium:platformVersion': ios_version,
        'appium:noReset': True,
        'appium:newCommandTimeout': 300,
        'appium:shouldTerminateApp': False,
        'appium:waitForQuiescence': False,
    }
    if wda_url:
        caps['appium:webDriverAgentUrl'] = wda_url
        caps['appium:usePreinstalledWDA'] = True
        caps['appium:useNewWDA'] = False
        print(f"  WDA 재사용: {wda_url}")
    else:
        caps['appium:usePreinstalledWDA'] = True
        caps['appium:useNewWDA'] = False
        caps['appium:updatedWDABundleId'] = 'com.jjun.1.WebDriverAgentRunner'
        caps['appium:wdaLaunchTimeout'] = 180000
        caps['appium:wdaConnectionTimeout'] = 90000

    options = AppiumOptions()
    options.load_capabilities(caps)
    driver = webdriver.Remote(f'http://127.0.0.1:{appium_port}', options=options)
    return driver


_ALERT_DISMISS_IDS = ['아니요', '나중에', '무시', '취소', "Don't Allow", 'Cancel', 'Not Now', '닫기']


def dismiss_alerts(driver):
    """시스템 알림 닫기."""
    try:
        driver.switch_to.alert.dismiss()
    except Exception:
        pass
    for aid in _ALERT_DISMISS_IDS:
        try:
            driver.find_element(AppiumBy.ACCESSIBILITY_ID, aid).click()
            time.sleep(0.3)
        except Exception:
            pass


def _is_on_keypad(driver) -> bool:
    """iOS 키패드 화면 여부 확인 (한글 숫자 버튼 존재)."""
    for kr in ['일', '이', '삼']:
        try:
            driver.find_element(AppiumBy.XPATH, f'//*[contains(@name, "{kr}")]')
        except Exception:
            return False
    return True


def navigate_to_keypad(driver) -> bool:
    """익시오 앱 키패드 탭으로 이동."""
    try:
        driver.activate_app(IXIO_BUNDLE_IOS)
    except Exception:
        pass
    time.sleep(0.5)

    if _is_on_keypad(driver):
        return True

    # XPath contains 우선 (공백 패딩 대응)
    try:
        driver.find_element(AppiumBy.XPATH, '//*[contains(@name, "키패드")]').click()
        time.sleep(1)
        if _is_on_keypad(driver):
            return True
    except Exception:
        pass
    for tab_id in ['키패드', 'Keypad', 'dialpad']:
        try:
            driver.find_element(AppiumBy.ACCESSIBILITY_ID, tab_id).click()
            time.sleep(1)
            if _is_on_keypad(driver):
                return True
        except Exception:
            pass
    return False


def clear_dial_field(driver):
    """키패드 잔류 번호 삭제 (지우기 버튼 롱프레스)."""
    try:
        src = driver.page_source
        m = re.search(r'\bvalue="(\d[\d\-\s]{1,15})"', src)
        if not m:
            return
        btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, '지우기')
        driver.execute_script('mobile: touchAndHold', {
            'elementId': btn.id,
            'duration': 1.5,
        })
        time.sleep(0.3)
    except Exception:
        pass


def _try_direct_input(driver, number: str) -> bool:
    """TextField가 있으면 직접 send_keys로 번호 입력 시도 (빠름, ~100ms).
    성공 시 True, 없으면 False."""
    try:
        field = driver.find_element(AppiumBy.CLASS_NAME, 'XCUIElementTypeTextField')
        field.clear()
        field.send_keys(number)
        print(f"    ✅ TextField 직접 입력 성공")
        return True
    except Exception:
        pass
    # iOS 클립보드 붙여넣기 방식
    try:
        # 입력 필드 영역 tap (StaticText 입력창 위치 — bounds [0,272,402,50])
        driver.execute_script('mobile: setPasteboard', {'content': number, 'encoding': 'plaintext'})
        # 입력 필드 더블탭 → 붙여넣기 메뉴
        field = driver.find_element(
            AppiumBy.XPATH,
            '//XCUIElementTypeStaticText[string-length(@name) > 3 and string-length(@name) < 16'
            ' and translate(@name, "0123456789-", "") = ""]',
        )
        field.tap(count=2)
        time.sleep(0.5)
        driver.find_element(AppiumBy.ACCESSIBILITY_ID, '붙여넣기').click()
        print(f"    ✅ 클립보드 붙여넣기 입력 성공")
        return True
    except Exception:
        pass
    return False


def dial_number_ios(driver, number: str) -> bool:
    """키패드에서 번호 입력 후 발신 (XPath contains 우선 — 공백 패딩 대응)."""
    dismiss_alerts(driver)

    if not navigate_to_keypad(driver):
        print('    ❌ iOS 키패드 진입 실패')
        return False
    clear_dial_field(driver)
    time.sleep(0.3)

    # ── 빠른 입력 먼저 시도 (TextField 또는 클립보드) ─────────────────────
    if _try_direct_input(driver, number):
        # 발신 버튼 클릭만 수행
        try:
            driver.find_element(AppiumBy.XPATH, '//*[contains(@name, "전화걸기")]').click()
            print('    ✅ iOS 발신 (전화걸기) [직접입력 후]')
            return True
        except Exception:
            pass
        for btn_id in ['전화걸기', '통화', '통화하기', 'Call', 'call']:
            try:
                driver.find_element(AppiumBy.ACCESSIBILITY_ID, btn_id).click()
                print(f"    ✅ iOS 발신 ('{btn_id}') [직접입력 후]")
                return True
            except Exception:
                pass
        print('    ⚠️ 직접 입력 후 발신 버튼 못 찾음 → 버튼 클릭 방식으로 폴백')
        clear_dial_field(driver)
        time.sleep(0.3)

    # ── 폴백: 키패드 버튼 클릭 ───────────────────────────────────────────
    for ch in number:
        if ch in ('-', ' '):
            continue
        kr_name = KEYPAD_KR.get(ch)
        if not kr_name:
            print(f"    ⚠️ 알 수 없는 문자: '{ch}'")
            return False
        found = False
        # 1차: accessibility ID
        try:
            driver.find_element(AppiumBy.ACCESSIBILITY_ID, kr_name).click()
            found = True
        except Exception:
            pass
        # 2차: XPath contains (공백 패딩 대응)
        if not found:
            try:
                driver.find_element(
                    AppiumBy.XPATH,
                    f'//*[contains(@name, "{kr_name}")]',
                ).click()
                found = True
            except Exception:
                pass
        # 3차: 숫자 직접
        if not found:
            try:
                driver.find_element(AppiumBy.ACCESSIBILITY_ID, ch).click()
                found = True
            except Exception:
                pass
        if not found:
            print(f"    ⚠️ '{ch}'(={kr_name}) 버튼 못 찾음")
            return False
        time.sleep(0.05)

    time.sleep(0.3)

    # 발신 버튼 (XPath contains 우선)
    try:
        driver.find_element(AppiumBy.XPATH, '//*[contains(@name, "전화걸기")]').click()
        print('    ✅ iOS 발신 (전화걸기)')
        return True
    except Exception:
        pass
    for btn_id in ['전화걸기', '통화', '통화하기', 'Call', 'call', 'dialButton']:
        try:
            driver.find_element(AppiumBy.ACCESSIBILITY_ID, btn_id).click()
            print(f"    ✅ iOS 발신 ('{btn_id}')")
            return True
        except Exception:
            pass
    print('    ❌ iOS 발신 버튼 못 찾음')
    return False


def end_call_ios(driver):
    try:
        driver.find_element(AppiumBy.ACCESSIBILITY_ID, '끊기').click()
    except Exception:
        try:
            driver.execute_script('mobile: tap', {'x': 195, 'y': 720})
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
#  iOS 타이머 폴링 (고속)
# ─────────────────────────────────────────────────────────────────────────────

def poll_ios_call_timer(
    driver,
    poll_interval_ms: int,
    stop_event: threading.Event,
    result_holder: dict,
) -> None:
    """백그라운드 스레드: iOS page_source 고속 폴링 → 통화 타이머 최초 감지 시각 기록.

    result_holder keys (스레드 완료 후):
        'timer_ts'      : float  최초 타이머 감지 time.time()
        'timer_value'   : str    최초 감지된 타이머 값 (e.g. "0:00")
        'poll_count'    : int    총 폴링 횟수
        'first_call_btn': bool   통화 버튼(끊기 등) 최초 등장 여부
        'call_btn_ts'   : float | None  통화 버튼 최초 등장 시각
    """
    result_holder.update({
        'timer_ts': None,
        'timer_value': None,
        'poll_count': 0,
        'call_btn_ts': None,
    })
    interval = poll_interval_ms / 1000.0
    call_btn_found = False
    timer_found = False

    while not stop_event.is_set():
        t = time.time()
        try:
            src = driver.page_source
        except Exception:
            time.sleep(interval)
            continue

        result_holder['poll_count'] += 1

        # 통화 버튼 최초 등장
        if not call_btn_found:
            if any(f'name="{b}"' in src or f'label="{b}"' in src for b in IOS_CALL_BTNS):
                call_btn_found = True
                result_holder['call_btn_ts'] = t

        # 타이머 패턴 최초 등장
        if not timer_found:
            m = _TIMER_RE.search(src)
            if m:
                timer_found = True
                result_holder['timer_ts'] = t
                result_holder['timer_value'] = m.group(1)
                # 타이머 발견 후에도 stop_event 대기 (외부에서 종료)
        
        elapsed = time.time() - t
        sleep_t = max(0.0, interval - elapsed)
        time.sleep(sleep_t)


# ─────────────────────────────────────────────────────────────────────────────
#  단일 측정 실행
# ─────────────────────────────────────────────────────────────────────────────

def measure_single(
    ios_driver,
    run: int,
    poll_ms: int,
    ringing_timeout: float = 40.0,
) -> dict:
    """1회 측정. 반환 dict 키:
        run, success, error,
        dial_ts          : 발신 시각
        ringing_ts       : Android RINGING 감지 시각
        offhook_ts       : Android OFFHOOK 감지 시각
        call_btn_ts      : iOS 통화 버튼 최초 등장 시각
        timer_ts         : iOS 타이머 최초 감지 시각
        timer_value      : 최초 타이머 값 ("0:00" 등)
        poll_count        : 폴링 횟수
        # 지연값 (ms)
        ringing_delay_ms : dial → RINGING
        offhook_delay_ms : RINGING → OFFHOOK
        call_btn_delay_ms: OFFHOOK → iOS 통화버튼 등장
        timer_delay_ms   : OFFHOOK → iOS 타이머 등장
    """
    result = {
        'run': run, 'success': False, 'error': None,
        'dial_ts': None, 'ringing_ts': None, 'offhook_ts': None,
        'call_btn_ts': None, 'timer_ts': None, 'timer_value': None,
        'poll_count': 0,
    }

    # ── 준비 ──────────────────────────────────────────────────────────────
    if not adb_ensure_connected():
        result['error'] = 'ADB 연결 불가'
        return result

    ensure_android_idle()

    # 사전 키패드 진입 확인 (dial_number_ios 내부에서도 재시도하지만 명시적으로 먼저 확인)
    dismiss_alerts(ios_driver)
    if not navigate_to_keypad(ios_driver):
        print(f"  ⚠️ 키패드 진입 실패 — 2초 후 재시도")
        try:
            ios_driver.activate_app(IXIO_BUNDLE_IOS)
            time.sleep(2)
        except Exception:
            pass
        if not navigate_to_keypad(ios_driver):
            result['error'] = '키패드 진입 실패'
            return result

    clear_dial_field(ios_driver)

    # ── 1) iOS 발신 ────────────────────────────────────────────────────────
    dial_ts = time.time()
    if not dial_number_ios(ios_driver, ANDROID_NUMBER):
        result['error'] = 'iOS 발신 실패'
        return result
    result['dial_ts'] = dial_ts
    print(f"  📞 발신 완료 (t=0)")

    # ── 2) Android RINGING 대기 ─────────────────────────────────────────
    print(f"  ⏳ RINGING 대기 (최대 {ringing_timeout:.0f}초)...")
    ringing_ts = wait_ringing(ringing_timeout)
    if ringing_ts is None:
        stop_event.set()
        end_call_ios(ios_driver)
        end_call_android()
        time.sleep(2)
        result['error'] = f'RINGING 미감지 ({ringing_timeout:.0f}초)'
        return result
    result['ringing_ts'] = ringing_ts
    ringing_delay = (ringing_ts - dial_ts) * 1000
    print(f"  🔔 RINGING 감지! (발신 후 {ringing_delay:.0f}ms)")

    # ── 3) Android 수신 수락 → OFFHOOK ─────────────────────────────────
    offhook_ts = accept_android_call()
    if offhook_ts is None:
        stop_event.set()
        end_call_ios(ios_driver)
        end_call_android()
        time.sleep(2)
        result['error'] = 'OFFHOOK 미확인'
        return result
    result['offhook_ts'] = offhook_ts
    offhook_delay = (offhook_ts - ringing_ts) * 1000
    print(f"  ✅ OFFHOOK 확인! (RINGING 후 {offhook_delay:.0f}ms)")

    # ── 4) OFFHOOK 이후 타이머 폴링 시작 ────────────────────────────────
    # OFFHOOK 이후부터 폴링 → 발신 전/중 상태바 시각 오탐 차단
    stop_event = threading.Event()
    timer_result: dict = {}
    poll_thread = threading.Thread(
        target=poll_ios_call_timer,
        args=(ios_driver, poll_ms, stop_event, timer_result),
        daemon=True,
    )
    poll_thread.start()

    # ── 5) iOS 타이머 감지 대기 (최대 10초) ─────────────────────────────
    timer_deadline = offhook_ts + 10.0
    while time.time() < timer_deadline:
        ts = timer_result.get('timer_ts')
        if ts is not None:
            break
        time.sleep(0.05)

    stop_event.set()
    poll_thread.join(timeout=3.0)

    result['poll_count'] = timer_result.get('poll_count', 0)
    result['call_btn_ts'] = timer_result.get('call_btn_ts')
    result['timer_ts'] = timer_result.get('timer_ts')
    result['timer_value'] = timer_result.get('timer_value')

    timer_ts = result['timer_ts']
    if timer_ts is None:
        print(f"  ⚠️ iOS 타이머 미감지 (OFFHOOK 후 10초 초과, 폴링 {result['poll_count']}회)")
        result['error'] = 'iOS 타이머 미감지 (10초)'
        # 통화 정리는 계속
    else:
        timer_delay = (timer_ts - offhook_ts) * 1000
        call_btn_delay = (
            (result['call_btn_ts'] - offhook_ts) * 1000
            if result['call_btn_ts'] else None
        )
        print(
            f"  🕐 iOS 타이머 '{result['timer_value']}' 감지! "
            f"OFFHOOK → 타이머: {timer_delay:+.0f}ms "
            f"(폴링 {result['poll_count']}회, 간격 {poll_ms}ms)"
        )
        if call_btn_delay is not None:
            sign = '+' if call_btn_delay >= 0 else ''
            print(f"     └ OFFHOOK → 통화버튼 등장: {sign}{call_btn_delay:.0f}ms")
        result['success'] = True

    # ── 6) 통화 종료 ────────────────────────────────────────────────────
    time.sleep(1.5)
    end_call_ios(ios_driver)
    end_call_android()
    time.sleep(3)

    return result


# ─────────────────────────────────────────────────────────────────────────────
#  지연 계산 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def calc_delays(r: dict) -> dict:
    out = {}
    if r.get('dial_ts') and r.get('ringing_ts'):
        out['ringing_delay_ms'] = (r['ringing_ts'] - r['dial_ts']) * 1000
    if r.get('ringing_ts') and r.get('offhook_ts'):
        out['offhook_delay_ms'] = (r['offhook_ts'] - r['ringing_ts']) * 1000
    if r.get('offhook_ts') and r.get('call_btn_ts'):
        out['call_btn_delay_ms'] = (r['call_btn_ts'] - r['offhook_ts']) * 1000
    if r.get('offhook_ts') and r.get('timer_ts'):
        out['timer_delay_ms'] = (r['timer_ts'] - r['offhook_ts']) * 1000
    return out


def print_stats(label: str, values: list[float]):
    if not values:
        print(f"  {label}: 데이터 없음")
        return
    mn = min(values)
    mx = max(values)
    mean = statistics.mean(values)
    med = statistics.median(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    print(f"  {label}: min={mn:+.0f}ms  max={mx:+.0f}ms  mean={mean:+.0f}ms  "
          f"median={med:+.0f}ms  std={std:.0f}ms  (n={len(values)})")


# ─────────────────────────────────────────────────────────────────────────────
#  메인
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='TC_01 iOS 통화 타이머 00:00 기준점 측정 (20회 반복)',
    )
    parser.add_argument('--runs', type=int, default=20, help='반복 횟수 (기본 20)')
    parser.add_argument('--appium-port', type=int, default=4732,
                        help='Appium 포트 (기본 4732, 메인 앱 4725/4726 과 분리)')
    parser.add_argument('--poll-ms', type=int, default=100,
                        help='iOS page_source 폴링 간격 ms (기본 100)')
    parser.add_argument('--ringing-timeout', type=float, default=40.0,
                        help='RINGING 대기 최대 초 (기본 40)')
    args = parser.parse_args()

    print("=" * 70)
    print("  TC_01 iOS 통화 타이머 00:00 기준점 측정")
    print(f"  반복: {args.runs}회 | Appium 포트: {args.appium_port} | "
          f"폴링 간격: {args.poll_ms}ms")
    print("=" * 70)
    print()
    print(f"📌 Appium 서버가 포트 {args.appium_port}에서 실행 중이어야 합니다.")
    print(f"   appium -p {args.appium_port} --relaxed-security")
    print()

    # iOS Appium 드라이버 생성
    print("🔌 iOS Appium 드라이버 생성 중...")
    try:
        ios_driver = create_ios_driver(args.appium_port)
        print("✅ iOS Appium 연결 성공")
    except Exception as e:
        print(f"❌ iOS Appium 연결 실패: {e}")
        sys.exit(1)

    results = []

    try:
        for run in range(1, args.runs + 1):
            print()
            print(f"─── Run {run:02d}/{args.runs:02d} ────────────────────────────────────────────")
            r = measure_single(ios_driver, run, args.poll_ms, args.ringing_timeout)

            delays = calc_delays(r)
            r.update(delays)
            results.append(r)

            status = "✅ SUCCESS" if r['success'] else f"❌ FAIL ({r.get('error','?')})"
            print(f"  결과: {status}")
            if r.get('timer_delay_ms') is not None:
                sign = '+' if r['timer_delay_ms'] >= 0 else ''
                print(f"  ⏱  OFFHOOK → iOS 타이머: {sign}{r['timer_delay_ms']:.0f}ms")

    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자 중단 — 지금까지 결과로 통계 출력")
    finally:
        try:
            ios_driver.quit()
        except Exception:
            pass

    # ── 결과 통계 ──────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("  📊 측정 결과 통계")
    print("=" * 70)

    success_results = [r for r in results if r['success']]
    fail_results    = [r for r in results if not r['success']]
    print(f"  총 {len(results)}회 | 성공 {len(success_results)}회 | 실패 {len(fail_results)}회")
    if fail_results:
        from collections import Counter
        errs = Counter(r.get('error', '?') for r in fail_results)
        for err, cnt in errs.most_common():
            print(f"    실패 원인: {err} × {cnt}회")
    print()

    for key, label in [
        ('ringing_delay_ms',  '발신 → RINGING'),
        ('offhook_delay_ms',  'RINGING → OFFHOOK'),
        ('call_btn_delay_ms', 'OFFHOOK → iOS 통화버튼 (끊기 등)'),
        ('timer_delay_ms',    'OFFHOOK → iOS 타이머 00:00  ★'),
    ]:
        vals = [r[key] for r in success_results if r.get(key) is not None]
        print_stats(label, vals)

    # ── 개별 결과 표 ─────────────────────────────────────────────────────
    print()
    print("  개별 결과:")
    print(f"  {'Run':>3}  {'상태':10}  {'RINGING(ms)':>12}  {'OFFHOOK(ms)':>12}  "
          f"{'타이머(ms)':>10}  {'타이머값':>8}  폴링")
    for r in results:
        status = '✅' if r['success'] else '❌'
        ring  = f"{r.get('ringing_delay_ms', 0):>10.0f}" if r.get('ringing_delay_ms') else '         -'
        offh  = f"{r.get('offhook_delay_ms', 0):>10.0f}" if r.get('offhook_delay_ms') else '         -'
        timer = f"{r['timer_delay_ms']:>+9.0f}" if r.get('timer_delay_ms') is not None else '        -'
        tval  = r.get('timer_value', '-') or '-'
        poll  = r.get('poll_count', 0)
        print(f"  {r['run']:>3}  {status}  {r.get('error','') if not r['success'] else '':10}  "
              f"{ring}  {offh}  {timer}ms  {tval:>8}  {poll}")

    # ── JSON 저장 ──────────────────────────────────────────────────────────
    log_dir = Path(__file__).resolve().parent.parent.parent.parent / 'logs' / datetime.now().strftime('%Y-%m-%d')
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / f"ios_timer_measure_{datetime.now().strftime('%H%M%S')}.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print()
    print(f"💾 결과 저장: {out_path}")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    main()
