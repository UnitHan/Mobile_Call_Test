#!/usr/bin/env python3
"""독립 통화 연결 테스트 — TC_01(iPhone→Android) / TC_02(Android→iPhone).

별도 Appium 포트(iOS=4730, Android=4731)를 사용하여 메인 앱과 완전히 독립적으로 실행.
20회 반복하여 성공률을 측정합니다.

Usage:
    # 먼저 별도 터미널에서 Appium 서버 2개 시작:
    appium -p 4730 --relaxed-security
    appium -p 4731 --relaxed-security

    # TC_01 테스트 (iPhone→Android):
    python test_call_connect.py --mode tc01 --runs 20

    # TC_02 테스트 (Android→iPhone):
    python test_call_connect.py --mode tc02 --runs 20

    # 둘 다 테스트:
    python test_call_connect.py --mode both --runs 20
"""

import argparse
import json
import re
import subprocess
import sys
import time

from appium import webdriver
from appium.options.common import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  설정값
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IOS_UDID = '00008150-00110C341E38401C'
IOS_NUMBER = '01022332512'
ANDROID_UDID = '192.168.219.103:5555'
ANDROID_NUMBER = '01083330025'
IXIO_BUNDLE_IOS = 'com.lguplus.aicallagent'
IXIO_PKG_ANDROID = 'com.lguplus.aicallagent'
APPIUM_PORT_IOS = 4730
APPIUM_PORT_ANDROID = 4731
POLL_INTERVAL = 1.0   # dumpsys 폴링 간격 (초)

# iOS UI 요소
CALL_BTN_IDS_IOS = ['전화걸기', '통화', '통화하기', '발신', 'Call', 'call', 'dialButton']
KEYPAD_TAB_IDS_IOS = ['키패드', 'Keypad', 'dialpad']
ALERT_DISMISS_IDS = ['아니요', '나중에', '무시', '취소', "Don't Allow", 'Cancel', 'Not Now']
IOS_ANSWER_IDS = ['응답', '받기', 'Accept', 'Answer']

# 숫자 → 키패드 버튼 한글 name 매핑 (익시오 앱 고유)
KEYPAD_KR = {
    '0': '공', '1': '일', '2': '이', '3': '삼', '4': '사',
    '5': '오', '6': '육', '7': '칠', '8': '팔', '9': '구',
    '*': '별', '#': '#',
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ADB 헬퍼
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def adb_reconnect(max_retries: int = 3, verbose: bool = True) -> bool:
    """Wi-Fi ADB 재연결. connect → 검증. (disconnect 금지 — Wi-Fi에서 완전 끊김)"""
    for attempt in range(1, max_retries + 1):
        try:
            # 재연결
            r = subprocess.run(
                ['adb', 'connect', ANDROID_UDID],
                capture_output=True, text=True, timeout=10
            )
            conn_out = r.stdout.strip()

            # 연결 확인
            time.sleep(0.5)
            check = subprocess.run(
                ['adb', '-s', ANDROID_UDID, 'shell', 'echo', 'ok'],
                capture_output=True, text=True, timeout=5
            )
            if 'ok' in check.stdout:
                if verbose:
                    print(f"    🔄 ADB 재연결 성공 (시도 {attempt}/{max_retries})")
                return True
        except Exception:
            pass
        if verbose:
            print(f"    ⚠️ ADB 재연결 시도 {attempt}/{max_retries} 실패")
        time.sleep(1)
    return False


def adb_shell(cmd_args: list[str], timeout: int = 5, retry_on_disconnect: bool = True) -> str:
    """ADB shell 명령 실행 후 stdout 반환. 끊김 시 자동 재연결 1회 재시도."""
    r = subprocess.run(
        ['adb', '-s', ANDROID_UDID, 'shell'] + cmd_args,
        capture_output=True, text=True, timeout=timeout
    )
    # device not found → 재연결 후 재시도
    if retry_on_disconnect and r.returncode != 0 and 'not found' in r.stderr:
        if adb_reconnect(max_retries=2, verbose=True):
            r = subprocess.run(
                ['adb', '-s', ANDROID_UDID, 'shell'] + cmd_args,
                capture_output=True, text=True, timeout=timeout
            )
    return r.stdout.strip()


def adb_ensure_connected():
    """Wi-Fi ADB 연결 보장."""
    try:
        check = subprocess.run(
            ['adb', '-s', ANDROID_UDID, 'shell', 'echo', 'ok'],
            capture_output=True, text=True, timeout=5
        )
        if 'ok' in check.stdout:
            return True
    except Exception:
        pass
    return adb_reconnect(max_retries=3, verbose=True)


def detect_call_state() -> int:
    """dumpsys telephony.registry mCallState 값. (0=IDLE, 1=RINGING, 2=OFFHOOK)"""
    try:
        out = adb_shell(['dumpsys', 'telephony.registry', '|', 'grep', '-m1', 'mCallState'])
        m = re.search(r'mCallState=(\d+)', out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return -1


def wait_for_ringing(timeout: float) -> bool:
    """dumpsys 폴링으로 RINGING(mCallState=1) 대기."""
    deadline = time.time() + timeout
    poll_count = 0
    while time.time() < deadline:
        poll_count += 1
        state = detect_call_state()
        if state == 1:
            print(f"    ✅ RINGING 감지 (폴링 {poll_count}회, {timeout - (deadline - time.time()):.1f}초)")
            return True
        if state == 2:
            print(f"    ⚠️ 이미 OFFHOOK 상태 (폴링 {poll_count}회)")
            return True
        time.sleep(POLL_INTERVAL)
    print(f"    ❌ RINGING 미감지 ({timeout:.0f}초 타임아웃, 폴링 {poll_count}회)")
    return False


def wait_for_offhook(timeout: float) -> bool:
    """dumpsys 폴링으로 OFFHOOK(mCallState=2) 대기. (Android 발신 시 사용)"""
    deadline = time.time() + timeout
    poll_count = 0
    while time.time() < deadline:
        poll_count += 1
        state = detect_call_state()
        if state == 2:
            print(f"    ✅ OFFHOOK 감지 (폴링 {poll_count}회)")
            return True
        time.sleep(POLL_INTERVAL)
    print(f"    ❌ OFFHOOK 미감지 ({timeout:.0f}초 타임아웃, 폴링 {poll_count}회)")
    return False


def accept_call_android() -> bool:
    """RINGING 상태의 통화를 ADB 명령으로 수락하고 OFFHOOK 확인.

    전략 순서 (메인 앱 android_call_handler.py 동일):
      ① telecom accept-ringing-call (API 26+, API 36에서 제거 가능)
      ② KEYCODE_CALL (5) — 수락/종료 토글
      ③ KEYCODE_ANSWER (164) — 수신 전용 키
      ④ KEYCODE_HEADSETHOOK (79) — 헤드셋 토글
      ⑤ am broadcast ANSWER — 구형 단말 최후 수단
    각 전략 사이 OFFHOOK 확인 → 이미 연결됐으면 즉시 반환.
    """
    strategies = [
        ('① telecom accept', ['cmd', 'telecom', 'accept-ringing-call']),
        ('② KEYCODE_CALL(5)', ['input', 'keyevent', '5']),
        ('③ KEYCODE_ANSWER(164)', ['input', 'keyevent', '164']),
        ('④ HEADSETHOOK(79)', ['input', 'keyevent', '79']),
        ('⑤ am broadcast', ['am', 'broadcast', '-a', 'android.intent.action.ANSWER']),
    ]

    # 즉시 OFFHOOK 체크 — ixio 자동 수신 대응
    pre_state = detect_call_state()
    print(f"    📌 수락 전 상태: {pre_state} (0=IDLE, 1=RINGING, 2=OFFHOOK)")
    if pre_state == 2:
        print(f"    ✅ 이미 OFFHOOK — 자동 수신된 것으로 판단")
        return True
    if pre_state == 0:
        print(f"    ⚠️ IDLE 상태 — 통화 이미 종료")
        return False

    for idx, (label, cmd_args) in enumerate(strategies):
        # 토글키 안전: 이미 OFFHOOK이면 추가 명령 보내지 않음
        if idx > 0:
            state = detect_call_state()
            if state == 2:
                print(f"    ✅ 이미 OFFHOOK — {label} 건너뜀")
                return True
            if state == 0:
                print(f"    ⚠️ 상태 IDLE(0) — 통화 종료됨 (전략 {label} 전)")
                return False
            print(f"    📌 상태={state} → {label} 시도")

        try:
            r = subprocess.run(
                ['adb', '-s', ANDROID_UDID, 'shell'] + cmd_args,
                capture_output=True, text=True, timeout=5
            )
            out = r.stdout.strip()
            err = r.stderr.strip()
            rc = r.returncode

            # ADB 끊김 감지 → 재연결 후 재시도
            if rc != 0 and 'not found' in err:
                print(f"    ⚠️ {label}: ADB 끊김 감지 → 재연결 시도...")
                if adb_reconnect(max_retries=2):
                    r = subprocess.run(
                        ['adb', '-s', ANDROID_UDID, 'shell'] + cmd_args,
                        capture_output=True, text=True, timeout=5
                    )
                    out = r.stdout.strip()
                    err = r.stderr.strip()
                    rc = r.returncode

            extra = f" (stdout={out})" if out else ""
            extra += f" (stderr={err})" if err else ""
            print(f"    📤 {label} → rc={rc}{extra}")
        except Exception as e:
            print(f"    ⚠️ {label} 실행 실패: {e}")
            continue

        # OFFHOOK 대기 (각 전략당 3초)
        for poll in range(15):
            time.sleep(0.2)
            state = detect_call_state()
            if state == 2:
                print(f"    ✅ OFFHOOK 확인 ({label} 후 {(poll+1)*0.2:.1f}초)")
                return True
            if state == 0:
                print(f"    ⚠️ IDLE 전환됨 ({label} 후 {(poll+1)*0.2:.1f}초) — 통화 종료")
                # 토글키가 통화를 끊었을 수 있음 → 다음 전략은 무의미
                return False

    # 모든 전략 실패
    final_state = detect_call_state()
    print(f"    ❌ 모든 전략 실패 (최종 상태={final_state})")
    return False


def end_call_android():
    """Android ADB KEYCODE_ENDCALL."""
    try:
        adb_shell(['input', 'keyevent', 'KEYCODE_ENDCALL'])
    except Exception:
        pass


def ensure_android_idle():
    """Android가 IDLE 상태가 아니면 ENDCALL 후 대기. 화면도 깨움."""
    # 화면 깨우기 (Wi-Fi ADB는 충전 아님 → stay_on_while_plugged_in 무효)
    try:
        adb_shell(['input', 'keyevent', 'KEYCODE_WAKEUP'])
    except Exception:
        pass
    state = detect_call_state()
    if state in (1, 2):
        label = 'RINGING' if state == 1 else 'OFFHOOK'
        print(f"    ⚠️ Android이 {label} → ENDCALL 후 3초 대기")
        end_call_android()
        time.sleep(3)


def end_call_ios(driver):
    """iOS '끊기' 버튼 클릭."""
    try:
        btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, "끊기")
        btn.click()
    except Exception:
        try:
            driver.execute_script("mobile: tap", {"x": 195, "y": 720})
        except Exception:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Appium 연결
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 하드코딩 WDA URL (tunnelIPAddress 감지 실패 시 폴백)
WDA_FALLBACK_URL = 'http://192.168.219.100:8100'


def find_wda_url() -> str | None:
    """실행 중인 WDA URL 탐지."""
    # 1) devicectl JSON 파싱 시도
    try:
        r = subprocess.run(
            ['xcrun', 'devicectl', 'list', 'devices', '--json-output', '/dev/stdout'],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(r.stdout)
        devices = data.get('result', {}).get('devices', [])
        for d in devices:
            cp = d.get('connectionProperties', {})
            ip = cp.get('tunnelIPAddress')
            if ip:
                import requests
                try:
                    resp = requests.get(f'http://{ip}:8100/status', timeout=3)
                    if resp.status_code == 200:
                        return f'http://{ip}:8100'
                except Exception:
                    pass
    except Exception:
        pass

    # 2) 하드코딩 폴백
    try:
        import requests
        resp = requests.get(f'{WDA_FALLBACK_URL}/status', timeout=3)
        if resp.status_code == 200:
            return WDA_FALLBACK_URL
    except Exception:
        pass
    return None


def get_ios_version() -> str:
    """iOS 버전 감지."""
    try:
        r = subprocess.run(
            ['xcrun', 'devicectl', 'list', 'devices'],
            capture_output=True, text=True, timeout=10
        )
        m = re.search(r'(\d+\.\d+(?:\.\d+)?)', r.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return '18.0'


def create_ios_driver(appium_port: int) -> webdriver.Remote:
    """Appium iOS 세션 생성."""
    wda_url = find_wda_url()
    ios_version = get_ios_version()

    caps = {
        'platformName': 'iOS',
        'appium:deviceName': 'test_iphone',
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

    appium_url = f'http://127.0.0.1:{appium_port}'
    print(f"  iOS Appium 연결: {appium_url}")
    driver = webdriver.Remote(appium_url, options=options)
    return driver


def create_android_driver(appium_port: int) -> webdriver.Remote:
    """Appium Android 세션 생성."""
    caps = {
        'platformName': 'Android',
        'appium:deviceName': 'test_android',
        'appium:udid': ANDROID_UDID,
        'appium:automationName': 'UiAutomator2',
        'appium:noReset': True,
        'appium:newCommandTimeout': 300,
    }
    options = AppiumOptions()
    options.load_capabilities(caps)

    appium_url = f'http://127.0.0.1:{appium_port}'
    print(f"  Android Appium 연결: {appium_url}")
    driver = webdriver.Remote(appium_url, options=options)
    return driver


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  iOS 키패드 조작 (TC_01: iOS → Android 발신용)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def dismiss_alerts(driver):
    """시스템 알림 닫기."""
    try:
        driver.switch_to.alert.dismiss()
    except Exception:
        pass
    for aid in ALERT_DISMISS_IDS:
        try:
            driver.find_element(AppiumBy.ACCESSIBILITY_ID, aid).click()
            time.sleep(0.3)
        except Exception:
            pass


def is_on_keypad_ios(driver) -> bool:
    """iOS 키패드 화면 여부 확인 (한글 name 매칭)."""
    for kr in ['일', '이', '삼']:
        try:
            driver.find_element(AppiumBy.XPATH, f'//*[contains(@name, "{kr}")]')
        except Exception:
            return False
    return True


def navigate_to_keypad_ios(driver) -> bool:
    """iOS 익시오 앱 키패드 탭으로 이동."""
    try:
        driver.activate_app(IXIO_BUNDLE_IOS)
    except Exception:
        pass
    time.sleep(0.5)

    if is_on_keypad_ios(driver):
        return True

    # 키패드 탭 (공백 패딩 대응: XPath contains 우선)
    try:
        btn = driver.find_element(AppiumBy.XPATH, '//*[contains(@name, "키패드")]')
        btn.click()
        time.sleep(1)
        if is_on_keypad_ios(driver):
            return True
    except Exception:
        pass
    for tab_id in KEYPAD_TAB_IDS_IOS:
        try:
            driver.find_element(AppiumBy.ACCESSIBILITY_ID, tab_id).click()
            time.sleep(1)
            if is_on_keypad_ios(driver):
                return True
        except Exception:
            pass
    return False


def clear_dial_field_ios(driver):
    """iOS 다이얼 필드 잔류 번호 삭제."""
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


def dial_from_ios(driver, number: str) -> bool:
    """iOS에서 번호 입력 + 발신.

    익시오 앱 키패드 버튼은 한글 accessibility ID를 사용 (공/일/이/삼/...).
    name에 공백 패딩이 있으므로 XPath contains() 매칭 사용.
    """
    dismiss_alerts(driver)

    if not navigate_to_keypad_ios(driver):
        print("    ❌ iOS 키패드 진입 실패")
        return False
    clear_dial_field_ios(driver)
    time.sleep(0.5)

    # 번호 입력 (한글 매핑)
    for ch in number:
        if ch in ('-', ' '):
            continue
        kr_name = KEYPAD_KR.get(ch)
        if not kr_name:
            print(f"    ⚠️ 알 수 없는 문자: '{ch}'")
            return False
        # 1차: accessibility ID (정확 매칭)
        found = False
        try:
            btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, kr_name)
            btn.click()
            found = True
        except Exception:
            pass
        # 2차: XPath contains (공백 패딩 대응)
        if not found:
            try:
                btn = driver.find_element(
                    AppiumBy.XPATH,
                    f'//*[contains(@name, "{kr_name}")]'
                )
                btn.click()
                found = True
            except Exception:
                pass
        # 3차: 숫자 직접 시도 (폴백)
        if not found:
            try:
                btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, ch)
                btn.click()
                found = True
            except Exception:
                pass
        if not found:
            print(f"    ⚠️ '{ch}'(={kr_name}) 버튼 못 찾음")
            return False
        time.sleep(0.05)

    time.sleep(0.3)

    # 발신 버튼 (XPath contains 우선 — 공백 패딩 대응)
    try:
        btn = driver.find_element(
            AppiumBy.XPATH,
            '//*[contains(@name, "전화걸기")]'
        )
        btn.click()
        print(f"    ✅ iOS 발신 ('전화걸기')")
        return True
    except Exception:
        pass
    for aid in CALL_BTN_IDS_IOS:
        try:
            btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, aid)
            btn.click()
            print(f"    ✅ iOS 발신 ('{aid}')")
            return True
        except Exception:
            pass

    print("    ❌ iOS 발신 버튼 못 찾음")
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Android 키패드 조작 (TC_02: Android → iPhone 발신용)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def navigate_to_keypad_android(driver) -> bool:
    """Android 익시오 앱 키패드 열기 (앱 재시작 → 키패드 탭)."""
    # 앱 재시작 (잔류 번호 초기화)
    try:
        driver.terminate_app(IXIO_PKG_ANDROID)
    except Exception:
        try:
            adb_shell(['am', 'force-stop', IXIO_PKG_ANDROID])
        except Exception:
            pass
    time.sleep(1)

    try:
        driver.activate_app(IXIO_PKG_ANDROID)
    except Exception:
        try:
            adb_shell(['monkey', '-p', IXIO_PKG_ANDROID,
                        '-c', 'android.intent.category.LAUNCHER', '1'])
        except Exception:
            pass
    time.sleep(5)  # 앱 로딩 대기

    # 키패드 탭 클릭
    for selector in [
        'new UiSelector().description("키패드")',
        'new UiSelector().text("키패드")',
    ]:
        try:
            btn = driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)
            btn.click()
            time.sleep(1)
            return True
        except Exception:
            pass

    # ADB xpath 폴백
    try:
        btn = driver.find_element(
            AppiumBy.XPATH,
            "//*[contains(@content-desc, '키패드') or contains(@text, '키패드')]"
        )
        btn.click()
        time.sleep(1)
        return True
    except Exception:
        pass

    print("    ⚠️ Android 키패드 탭 못 찾음")
    return False


def dial_from_android_adb(number: str) -> bool:
    """ADB만으로 번호 입력 + 발신 (익시오 앱 키패드 EditText 직접 입력).

    UiAutomator2 없이 동작하는 완전 ADB 방식.
    앱 재시작 → 키패드 탭(tap 좌표) → EditText에 input text → 발신(tap 좌표).
    """
    # 화면 깨우기
    adb_shell(['input', 'keyevent', 'KEYCODE_WAKEUP'])
    time.sleep(0.3)

    # 앱 재시작 (잔류 번호 초기화)
    adb_shell(['am', 'force-stop', IXIO_PKG_ANDROID])
    time.sleep(1)
    adb_shell(['monkey', '-p', IXIO_PKG_ANDROID,
               '-c', 'android.intent.category.LAUNCHER', '1'])
    time.sleep(5)  # 앱 로딩 대기

    # 키패드 탭 (Galaxy S22 Ultra 좌표 — content-desc="키패드" bounds=[435,2026][645,2178])
    adb_shell(['input', 'tap', '540', '2102'])
    time.sleep(1)

    # EditText에 포커스가 자동으로 잡혀있음 → input text로 번호 한번에 입력
    adb_shell(['input', 'text', number])
    print(f"    ✅ Android 번호 입력 완료 (ADB input text)")
    time.sleep(1)

    # 발신 버튼 탭 (content-desc="전화" bounds=[493,1771][588,1866])
    adb_shell(['input', 'tap', '540', '1818'])
    print(f"    📞 Android 발신 시도 (ADB tap)")
    time.sleep(2)

    # OFFHOOK 확인
    for _ in range(5):
        state = detect_call_state()
        if state == 2:
            print(f"    ✅ Android 발신 완료 (ADB)")
            return True
        time.sleep(1)

    print(f"    ⚠️ ADB 발신 OFFHOOK 미확인 — 계속 진행")
    return True


def dial_from_android(driver, number: str) -> bool:
    """Android에서 번호 입력 + 발신.

    ADB input text 방식을 기본으로 사용 (UiAutomator2 불안정 회피).
    TC_01과 동일하게 ADB만으로 동작하여 안정성 확보.
    """
    return dial_from_android_adb(number)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  iOS 수신 (TC_02용)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def answer_call_ios(driver, timeout: float = 30.0) -> bool:
    """iOS에서 수신 전화 응답 — 전체화면 하단 '받기' 버튼만 탭.

    'AI 전화 대신 받기' 버튼을 오탭하지 않도록
    accessibility ID 정확 매칭 우선, XPath는 'AI' 포함 버튼 제외.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # accessibility ID 정확 매칭 (정확히 '받기' 등만 매칭)
        for aid in IOS_ANSWER_IDS:
            try:
                btns = driver.find_elements(AppiumBy.ACCESSIBILITY_ID, aid)
                for btn in btns:
                    if not btn.is_displayed():
                        continue
                    # 'AI 전화 대신 받기' 제외: label/name에 'AI' 포함 시 건너뛰
                    lbl = btn.get_attribute('name') or btn.get_attribute('label') or ''
                    if 'AI' in lbl or '대신' in lbl:
                        continue
                    btn.click()
                    print(f"    ✅ iOS 수신 완료 ('{aid}')")
                    time.sleep(2)
                    return True
            except Exception:
                pass

        # XPath contains — 공백 패딩 대응, 'AI' 포함 버튼 제외
        for name in ['받기', '응답', 'Accept', 'Answer']:
            try:
                btns = driver.find_elements(
                    AppiumBy.XPATH,
                    f'//XCUIElementTypeButton[contains(@name, "{name}")]'
                )
                for btn in btns:
                    if not btn.is_displayed():
                        continue
                    lbl = btn.get_attribute('name') or btn.get_attribute('label') or ''
                    if 'AI' in lbl or '대신' in lbl:
                        continue
                    btn.click()
                    print(f"    ✅ iOS 수신 완료 ('{name}')")
                    time.sleep(2)
                    return True
            except Exception:
                pass

        time.sleep(1)
    print(f"    ❌ iOS 수신 실패 ({timeout:.0f}초 타임아웃)")
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TC_01: iPhone → Android 발신 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def tc01_single(ios_driver, run: int, ringing_timeout: float) -> dict:
    """TC_01: iPhone에서 발신 → Android ADB dumpsys RINGING 감지 → ADB 수신.

    Returns dict with: success, ringing_time, offhook_time, error
    """
    result = {'run': run, 'success': False, 'ringing_time': None, 'offhook_time': None, 'error': None}

    # 0) ADB 연결 확인 (각 run 시작 전)
    if not adb_ensure_connected():
        print(f"    ❌ ADB 연결 불가 — run {run} 건너뜀")
        result['error'] = 'ADB 연결 불가'
        return result

    ensure_android_idle()

    # 1) iOS 발신
    t0 = time.time()
    if not dial_from_ios(ios_driver, ANDROID_NUMBER):
        result['error'] = 'iOS 발신 실패'
        return result

    # 2) Android RINGING 대기
    print(f"    ⏳ RINGING 대기 (dumpsys {POLL_INTERVAL}초 간격, 최대 {ringing_timeout:.0f}초)...")
    if not wait_for_ringing(ringing_timeout):
        result['error'] = f'RINGING 미감지 ({ringing_timeout:.0f}초)'
        end_call_ios(ios_driver)
        end_call_android()
        time.sleep(2)
        return result

    ringing_t = time.time() - t0
    result['ringing_time'] = ringing_t

    # 2.5) ixio UI 안정화 대기 — RINGING 직후 keyevent 전송 시 ixio가 소비함
    #   RINGING 감지가 빠를수록 (1-3초) ixio UI가 아직 올라오는 중이므로
    #   keyevent가 native telephony에 도달하지 못함.
    #   5초 대기 동안 OFFHOOK이 되면 ixio 자동 수신으로 판단.
    SETTLE_DELAY = 5.0
    print(f"    ⏳ ixio UI 안정화 대기 ({SETTLE_DELAY}초)...")
    settle_deadline = time.time() + SETTLE_DELAY
    while time.time() < settle_deadline:
        state = detect_call_state()
        if state == 2:
            offhook_t = time.time() - t0 - ringing_t
            result['offhook_time'] = offhook_t
            print(f"    ✅ 대기 중 OFFHOOK 감지 — ixio 자동 수신")
            time.sleep(3)
            end_call_ios(ios_driver)
            end_call_android()
            time.sleep(2)
            result['success'] = True
            return result
        if state == 0:
            print(f"    ⚠️ 대기 중 IDLE 전환 — 통화 종료됨")
            result['error'] = '안정화 대기 중 IDLE'
            end_call_ios(ios_driver)
            time.sleep(2)
            return result
        time.sleep(0.5)

    # 3) Android 수신 수락
    print(f"    📞 Android 수신 수락 시도...")
    t1 = time.time()
    if not accept_call_android():
        result['error'] = 'OFFHOOK 미확인'
        end_call_ios(ios_driver)
        end_call_android()
        time.sleep(2)
        return result

    offhook_t = time.time() - t1
    result['offhook_time'] = offhook_t

    # 4) 통화 유지 3초
    print(f"    ✅ 통화 연결! (RINGING: {ringing_t:.1f}초, OFFHOOK: {offhook_t:.1f}초)")
    time.sleep(3)

    # 5) 종료
    end_call_ios(ios_driver)
    end_call_android()
    time.sleep(2)

    result['success'] = True
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TC_02: Android → iPhone 발신 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def tc02_single(android_driver, ios_driver, run: int, answer_timeout: float) -> dict:
    """TC_02: Android에서 발신 → iOS Appium 수신 → Android OFFHOOK 확인.

    Returns dict with: success, offhook_time, answer_time, error
    """
    result = {'run': run, 'success': False, 'ringing_time': None, 'offhook_time': None, 'error': None}

    # ADB 연결 확인 (각 run 시작 전)
    if not adb_ensure_connected():
        print(f"    ❌ ADB 연결 불가 — run {run} 건너뜀")
        result['error'] = 'ADB 연결 불가'
        return result

    # Android Appium 세션 생존 확인
    try:
        android_driver.current_package
    except Exception:
        print(f"    ⚠️ Android Appium 세션 끊김")
        result['error'] = 'Android 발신 실패'
        return result

    ensure_android_idle()

    # 0.5) iOS 익시오 앱 활성화 (통화 종료 시 앱이 강제종료될 수 있음)
    try:
        ios_driver.activate_app(IXIO_BUNDLE_IOS)
        time.sleep(1)
    except Exception as e:
        print(f"    ⚠️ iOS 익시오 앱 활성화 실패: {e}")

    # 1) Android 발신
    t0 = time.time()
    if not dial_from_android(android_driver, IOS_NUMBER):
        result['error'] = 'Android 발신 실패'
        return result

    # 2) iOS 수신 대기 + 수락
    print(f"    ⏳ iOS 수신 대기 (최대 {answer_timeout:.0f}초)...")
    if not answer_call_ios(ios_driver, timeout=answer_timeout):
        result['error'] = f'iOS 수신 실패 ({answer_timeout:.0f}초)'
        end_call_ios(ios_driver)
        end_call_android()
        time.sleep(2)
        return result

    answer_t = time.time() - t0
    result['ringing_time'] = answer_t  # 발신→수신 전체 시간

    # 3) Android OFFHOOK 확인
    print(f"    ⏳ Android OFFHOOK 확인 (최대 10초)...")
    t1 = time.time()
    if not wait_for_offhook(10.0):
        result['error'] = 'Android OFFHOOK 미확인'
        end_call_ios(ios_driver)
        end_call_android()
        time.sleep(2)
        return result

    offhook_t = time.time() - t1
    result['offhook_time'] = offhook_t

    # 4) 통화 유지 3초
    print(f"    ✅ 통화 연결! (수신: {answer_t:.1f}초, OFFHOOK: {offhook_t:.1f}초)")
    time.sleep(3)

    # 5) 종료
    end_call_android()
    end_call_ios(ios_driver)
    time.sleep(2)

    result['success'] = True
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  결과 출력
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def print_results(results: list[dict], mode: str):
    """결과 요약 출력."""
    print("\n" + "=" * 60)
    print(f"📊 최종 결과 [{mode.upper()}]")
    print("=" * 60)
    total = len(results)
    if total == 0:
        print("  결과 없음")
        return 0.0

    passed = sum(1 for r in results if r['success'])
    failed = total - passed

    for r in results:
        status = "✅" if r['success'] else "❌"
        ringing = f"ring={r['ringing_time']:.1f}s" if r['ringing_time'] else ""
        offhook = f"offhook={r['offhook_time']:.1f}s" if r['offhook_time'] else ""
        error = f"({r['error']})" if r['error'] else ""
        print(f"  [{r['run']:2d}] {status}  {ringing}  {offhook}  {error}")

    rate = passed / total * 100
    print(f"\n  성공: {passed}/{total} ({rate:.0f}%)")
    print(f"  실패: {failed}/{total} ({failed/total*100:.0f}%)")

    if passed > 0:
        ringing_times = [r['ringing_time'] for r in results if r['ringing_time']]
        offhook_times = [r['offhook_time'] for r in results if r['offhook_time']]
        if ringing_times:
            print(f"  감지 평균: {sum(ringing_times)/len(ringing_times):.1f}초 "
                  f"(min={min(ringing_times):.1f}, max={max(ringing_times):.1f})")
        if offhook_times:
            print(f"  OFFHOOK 평균: {sum(offhook_times)/len(offhook_times):.1f}초 "
                  f"(min={min(offhook_times):.1f}, max={max(offhook_times):.1f})")

    print("=" * 60)

    if rate >= 90:
        print(f"\n🎉 성공률 {rate:.0f}% — 채택 가능")
    elif rate >= 70:
        print(f"\n⚠️ 성공률 {rate:.0f}% — 개선 여지 있음")
    else:
        print(f"\n❌ 성공률 {rate:.0f}% — 근본 원인 추가 조사 필요")
    return rate


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  N회 반복 러너
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_tc01(args) -> list[dict]:
    """TC_01 반복 실행."""
    print("\n" + "=" * 60)
    print("🧪 TC_01: iPhone → Android 발신 테스트")
    print(f"   방식: ADB dumpsys 폴링 (간격 {POLL_INTERVAL}초)")
    print(f"   반복: {args.runs}회, RINGING 타임아웃: {args.ringing_timeout}초")
    print("=" * 60)

    print("\n🔌 iOS Appium 연결...")
    try:
        ios_driver = create_ios_driver(APPIUM_PORT_IOS)
        print("  ✅ iOS 연결 OK")
    except Exception as e:
        print(f"❌ iOS 연결 실패: {e}")
        print(f"💡 'appium -p {APPIUM_PORT_IOS} --relaxed-security' 실행 필요")
        return []

    results = []
    try:
        for i in range(1, args.runs + 1):
            print(f"\n{'─' * 50}")
            print(f"  TC_01 [{i}/{args.runs}]")
            print(f"{'─' * 50}")
            r = tc01_single(ios_driver, i, args.ringing_timeout)
            results.append(r)
            status = "✅ PASS" if r['success'] else f"❌ FAIL ({r['error']})"
            print(f"  결과: {status}")
            if i < args.runs:
                time.sleep(3)
    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자 중단")
    finally:
        try:
            end_call_ios(ios_driver)
            end_call_android()
        except Exception:
            pass
        try:
            ios_driver.quit()
        except Exception:
            pass
    return results


def run_tc02(args) -> list[dict]:
    """TC_02 반복 실행."""
    print("\n" + "=" * 60)
    print("🧪 TC_02: Android → iPhone 발신 테스트")
    print(f"   방식: ADB dumpsys 폴링 (간격 {POLL_INTERVAL}초)")
    print(f"   반복: {args.runs}회, 수신 타임아웃: {args.ringing_timeout}초")
    print("=" * 60)

    print("\n🔌 Android Appium 연결...")

    # UiAutomator2 잔류 프로세스 정리
    print("  🧹 UiAutomator2 잔류 프로세스 정리...")
    for pkg in ['io.appium.uiautomator2.server', 'io.appium.uiautomator2.server.test']:
        try:
            adb_shell(['am', 'force-stop', pkg])
        except Exception:
            pass
    time.sleep(1)

    try:
        android_driver = create_android_driver(APPIUM_PORT_ANDROID)
        print("  ✅ Android 연결 OK")
    except Exception as e:
        print(f"❌ Android 연결 실패: {e}")
        print(f"💡 'appium -p {APPIUM_PORT_ANDROID} --relaxed-security' 실행 필요")
        return []

    print("\n🔌 iOS Appium 연결...")
    try:
        ios_driver = create_ios_driver(APPIUM_PORT_IOS)
        print("  ✅ iOS 연결 OK")
    except Exception as e:
        print(f"❌ iOS 연결 실패: {e}")
        print(f"💡 'appium -p {APPIUM_PORT_IOS} --relaxed-security' 실행 필요")
        try:
            android_driver.quit()
        except Exception:
            pass
        return []

    results = []
    try:
        for i in range(1, args.runs + 1):
            print(f"\n{'─' * 50}")
            print(f"  TC_02 [{i}/{args.runs}]")
            print(f"{'─' * 50}")
            r = tc02_single(android_driver, ios_driver, i, args.ringing_timeout)
            results.append(r)
            status = "✅ PASS" if r['success'] else f"❌ FAIL ({r['error']})"
            print(f"  결과: {status}")

            # Android 발신 실패 시 UiAutomator2 세션 재생성
            if not r['success'] and r.get('error') == 'Android 발신 실패':
                print("    🔄 Android Appium 세션 재생성 중...")
                try:
                    android_driver.quit()
                except Exception:
                    pass
                for pkg in ['io.appium.uiautomator2.server', 'io.appium.uiautomator2.server.test']:
                    try:
                        adb_shell(['am', 'force-stop', pkg])
                    except Exception:
                        pass
                time.sleep(2)
                try:
                    android_driver = create_android_driver(APPIUM_PORT_ANDROID)
                    print("    ✅ Android Appium 세션 재생성 완료")
                except Exception as e:
                    print(f"    ❌ Android Appium 세션 재생성 실패: {e}")
                    break

            if i < args.runs:
                time.sleep(3)
    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자 중단")
    finally:
        try:
            end_call_android()
            end_call_ios(ios_driver)
        except Exception:
            pass
        try:
            android_driver.quit()
        except Exception:
            pass
        try:
            ios_driver.quit()
        except Exception:
            pass
    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(
        description='독립 통화 연결 테스트 (TC_01/TC_02)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python test_call_connect.py --mode tc01 --runs 20
  python test_call_connect.py --mode tc02 --runs 20
  python test_call_connect.py --mode both --runs 10

사전 준비:
  appium -p 4730 --relaxed-security   # iOS용
  appium -p 4731 --relaxed-security   # Android용 (TC_02 시)
"""
    )
    parser.add_argument('--mode', choices=['tc01', 'tc02', 'both'], default='tc01',
                        help='테스트 모드 (기본: tc01)')
    parser.add_argument('--runs', type=int, default=20, help='반복 횟수 (기본: 20)')
    parser.add_argument('--ringing-timeout', type=float, default=40.0,
                        help='RINGING/수신 대기 타임아웃 초 (기본: 40)')
    parser.add_argument('--appium-port-ios', type=int, default=APPIUM_PORT_IOS,
                        help=f'iOS Appium 포트 (기본: {APPIUM_PORT_IOS})')
    parser.add_argument('--appium-port-android', type=int, default=APPIUM_PORT_ANDROID,
                        help=f'Android Appium 포트 (기본: {APPIUM_PORT_ANDROID})')
    parser.add_argument('--poll-interval', type=float, default=POLL_INTERVAL,
                        help=f'dumpsys 폴링 간격 초 (기본: {POLL_INTERVAL})')
    args = parser.parse_args()

    _port_ios = args.appium_port_ios
    _port_android = args.appium_port_android
    _poll = args.poll_interval

    # 모듈 레벨 설정 갱신
    import test_call_connect as _self
    _self.APPIUM_PORT_IOS = _port_ios
    _self.APPIUM_PORT_ANDROID = _port_android
    _self.POLL_INTERVAL = _poll

    print("=" * 60)
    print("🧪 독립 통화 연결 테스트")
    print(f"   모드: {args.mode.upper()}")
    print(f"   iOS: {IOS_UDID} ({IOS_NUMBER})")
    print(f"   Android: {ANDROID_UDID} ({ANDROID_NUMBER})")
    print(f"   Appium: iOS={APPIUM_PORT_IOS}, Android={APPIUM_PORT_ANDROID}")
    print("=" * 60)

    # ADB 연결 확인
    print("\n🔌 ADB 연결 확인...")
    if not adb_ensure_connected():
        print("❌ ADB 연결 실패 — 종료")
        sys.exit(1)
    print("  ✅ ADB 연결 OK")

    # Android 화면 상시 켜짐 (24시간 테스트 대비)
    print("\n🔆 Android 화면 상시 켜짐 설정...")
    try:
        adb_shell(['svc', 'power', 'stayon', 'true'])
        adb_shell(['settings', 'put', 'system', 'screen_off_timeout', '2147483647'])
        adb_shell(['settings', 'put', 'global', 'stay_on_while_plugged_in', '3'])
        print("  ✅ 화면 상시 켜짐 설정 완료")
    except Exception as e:
        print(f"  ⚠️ 화면 상시 켜짐 설정 실패: {e}")

    # Doze 화이트리스트 확인/등록
    print("\n🔋 Doze 화이트리스트 확인...")
    try:
        wl = adb_shell(['dumpsys', 'deviceidle', 'whitelist'])
        if IXIO_PKG_ANDROID in wl:
            print(f"  ✅ {IXIO_PKG_ANDROID} 이미 등록됨")
        else:
            adb_shell(['cmd', 'deviceidle', 'whitelist', f'+{IXIO_PKG_ANDROID}'])
            print(f"  ✅ {IXIO_PKG_ANDROID} 화이트리스트 등록 완료")
    except Exception as e:
        print(f"  ⚠️ 화이트리스트 확인 실패: {e}")

    all_results = {}

    if args.mode in ('tc01', 'both'):
        results_tc01 = run_tc01(args)
        if results_tc01:
            all_results['TC_01'] = results_tc01

    if args.mode in ('tc02', 'both'):
        results_tc02 = run_tc02(args)
        if results_tc02:
            all_results['TC_02'] = results_tc02

    # 최종 요약
    print("\n\n" + "=" * 60)
    print("📊 전체 요약")
    print("=" * 60)
    for mode, results in all_results.items():
        rate = print_results(results, mode)

    if not all_results:
        print("  테스트 결과 없음")
        sys.exit(1)


if __name__ == '__main__':
    main()
