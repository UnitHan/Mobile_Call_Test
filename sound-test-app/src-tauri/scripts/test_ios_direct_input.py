#!/usr/bin/env python3
"""iOS 익시오 키패드 직접 입력 가능 여부 테스트.

실행:
    python test_ios_direct_input.py
"""
import json
import re
import subprocess
import time
from xml.etree import ElementTree as ET

from appium import webdriver
from appium.options.common import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy

IOS_UDID        = '00008150-00110C341E38401C'
IXIO_BUNDLE_IOS = 'com.lguplus.aicallagent'
TEST_NUMBER     = '01022332512'
APPIUM_PORT     = 4732

# ─────────────────────────────────────────────────────────────────────────────

def find_wda_url():
    import socket
    for ip in ['192.168.219.100', '192.168.219.1']:
        try:
            s = socket.create_connection((ip, 8100), timeout=1)
            s.close()
            return f'http://{ip}:8100'
        except Exception:
            pass
    return None


def create_driver():
    wda_url = find_wda_url()
    caps = {
        'platformName': 'iOS',
        'appium:deviceName': 'test_iphone',
        'appium:udid': IOS_UDID,
        'appium:automationName': 'XCUITest',
        'appium:platformVersion': '18.0',
        'appium:noReset': True,
        'appium:newCommandTimeout': 300,
        'appium:shouldTerminateApp': False,
        'appium:waitForQuiescence': False,
    }
    if wda_url:
        caps['appium:webDriverAgentUrl'] = wda_url
        caps['appium:usePrebuiltWDA'] = True
        caps['appium:useNewWDA'] = False
        print(f"WDA 재사용: {wda_url}")
    options = AppiumOptions()
    options.load_capabilities(caps)
    return webdriver.Remote(f'http://127.0.0.1:{APPIUM_PORT}', options=options)


def dump_all_elements(driver):
    """page_source XML 파싱 후 모든 interactive/input 요소 출력."""
    src = driver.page_source

    # 파일로 저장
    with open('/tmp/ios_ui_dump.xml', 'w') as f:
        f.write(src)
    print(f"  📄 UI 덤프 저장: /tmp/ios_ui_dump.xml ({len(src)} bytes)")

    # XML 파싱
    root = ET.fromstring(src)

    print("\n" + "="*70)
    print("  🔍 입력 가능한 요소 분석")
    print("="*70)

    # 1. TextField / SecureTextField
    textfields = root.findall('.//*[@type="XCUIElementTypeTextField"]') + \
                 root.findall('.//*[@type="XCUIElementTypeSecureTextField"]')
    print(f"\n[TextField / SecureTextField] {len(textfields)}개")
    for el in textfields:
        print(f"  type={el.get('type')}")
        print(f"  name={el.get('name')!r}  label={el.get('label')!r}  value={el.get('value')!r}")
        print(f"  enabled={el.get('enabled')}  visible={el.get('visible')}")
        print(f"  bounds={el.get('x')},{el.get('y')} {el.get('width')}x{el.get('height')}")
        print()

    # 2. StaticText (입력창으로 쓰이는 경우)
    print(f"\n[StaticText — 숫자/번호 포함 가능성]")
    for el in root.findall('.//*[@type="XCUIElementTypeStaticText"]'):
        val = el.get('value') or el.get('name') or ''
        # 빈 값이거나 숫자/전화번호 패턴
        if val == '' or re.search(r'[\d\-\s]{3,}', val) or el.get('name') == '':
            print(f"  name={el.get('name')!r}  value={el.get('value')!r}  "
                  f"bounds={el.get('x')},{el.get('y')} {el.get('width')}x{el.get('height')}")

    # 3. 발신 버튼 탐색
    print(f"\n[발신 관련 버튼]")
    for el in root.iter():
        name = (el.get('name') or '') + (el.get('label') or '')
        if any(k in name for k in ['전화', '걸기', 'dial', 'call', 'Call']):
            print(f"  type={el.get('type')}  name={el.get('name')!r}  "
                  f"bounds={el.get('x')},{el.get('y')} {el.get('width')}x{el.get('height')}")

    # 4. 전체 요소 타입 통계
    print(f"\n[전체 요소 타입 통계]")
    type_counts: dict[str, int] = {}
    for el in root.iter():
        t = el.get('type') or 'unknown'
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"  {t}: {cnt}개")

    return src


def test_textfield_input(driver):
    """TextField send_keys 시도."""
    print("\n" + "="*70)
    print("  🧪 TEST 1: TextField send_keys")
    print("="*70)
    try:
        field = driver.find_element(AppiumBy.CLASS_NAME, 'XCUIElementTypeTextField')
        print(f"  ✅ TextField 발견: name={field.get_attribute('name')!r}")
        field.clear()
        t0 = time.time()
        field.send_keys(TEST_NUMBER)
        elapsed = (time.time() - t0) * 1000
        val = field.get_attribute('value')
        print(f"  입력 후 value={val!r}  소요={elapsed:.0f}ms")
        return True
    except Exception as e:
        print(f"  ❌ TextField 없음: {e}")
        return False


def test_clipboard_input(driver):
    """클립보드 setPasteboard → 붙여넣기 시도."""
    print("\n" + "="*70)
    print("  🧪 TEST 2: 클립보드 setPasteboard + 붙여넣기")
    print("="*70)
    try:
        driver.execute_script('mobile: setPasteboard', {
            'content': TEST_NUMBER,
            'encoding': 'plaintext',
        })
        print(f"  클립보드 설정: {TEST_NUMBER!r}")

        # 입력 필드 영역 탭 (StaticText 입력창 찾기)
        # 1순위: 빈 StaticText (입력창)
        candidates = driver.find_elements(
            AppiumBy.XPATH,
            '//XCUIElementTypeStaticText[@name="" or not(@name)]',
        )
        if not candidates:
            # 2순위: bounds y≈272 (스크린샷 기준 입력창 위치)
            candidates = driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeStaticText',
            )
            candidates = [el for el in candidates
                          if el.get_attribute('y') and 250 < int(el.get_attribute('y') or 0) < 320]
        if candidates:
            el = candidates[0]
            print(f"  후보 StaticText: name={el.get_attribute('name')!r} "
                  f"y={el.get_attribute('y')}")
            # 더블탭
            el.tap(count=2)
            time.sleep(0.8)
            # 붙여넣기 메뉴 탭
            try:
                driver.find_element(AppiumBy.ACCESSIBILITY_ID, '붙여넣기').click()
                time.sleep(0.3)
                print(f"  ✅ 붙여넣기 완료")
                return True
            except Exception:
                print(f"  ⚠️ 붙여넣기 메뉴 없음 — 단순 탭 후 Ctrl+V 시도")
                el.tap()
                time.sleep(0.3)
                driver.execute_script('mobile: tap', {'x': 200, 'y': 200})  # 메뉴 닫기
        else:
            print("  ❌ 입력 필드 후보 없음")
    except Exception as e:
        print(f"  ❌ 클립보드 방식 실패: {e}")
    return False


def test_iossendkeys(driver):
    """mobile: typeText (XCUITest 직접 명령)."""
    print("\n" + "="*70)
    print("  🧪 TEST 3: mobile: typeText (XCUITest 직접)")
    print("="*70)
    try:
        # 입력창에 focus 주기 위해 먼저 탭
        candidates = driver.find_elements(
            AppiumBy.XPATH,
            '//XCUIElementTypeStaticText[@name="" or string-length(@name)=0]',
        )
        if candidates:
            candidates[0].tap()
            time.sleep(0.3)
            print(f"  입력창 탭 완료 — typeText 시도")

        t0 = time.time()
        driver.execute_script('mobile: typeText', {'text': TEST_NUMBER})
        elapsed = (time.time() - t0) * 1000
        print(f"  ✅ mobile: typeText 완료 ({elapsed:.0f}ms)")
        return True
    except Exception as e:
        print(f"  ❌ mobile: typeText 실패: {e}")
        return False


def test_button_speed(driver):
    """버튼 클릭 방식 속도 측정 (현재 방식)."""
    print("\n" + "="*70)
    print("  🧪 TEST 4: 버튼 클릭 속도 측정 (현재 방식)")
    print("="*70)
    KEYPAD_KR = {
        '0': '공', '1': '일', '2': '이', '3': '삼', '4': '사',
        '5': '오', '6': '육', '7': '칠', '8': '팔', '9': '구',
    }
    t0 = time.time()
    for ch in TEST_NUMBER:
        kr = KEYPAD_KR.get(ch)
        if not kr:
            continue
        try:
            driver.find_element(AppiumBy.XPATH, f'//*[contains(@name, "{kr}")]').click()
        except Exception:
            print(f"  ⚠️ '{ch}'={kr} 버튼 못 찾음")
        time.sleep(0.05)
    elapsed = (time.time() - t0) * 1000
    print(f"  버튼 클릭 11자리 소요: {elapsed:.0f}ms")

    # 입력된 값 확인
    time.sleep(0.2)
    src = driver.page_source
    m = re.search(r'value="([\d\-\s]{7,})"', src)
    if m:
        print(f"  입력 확인: {m.group(1)!r}")
    else:
        print("  ⚠️ 입력값 확인 불가")

    # 지우기
    try:
        btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, '지우기')
        driver.execute_script('mobile: touchAndHold', {'elementId': btn.id, 'duration': 1.5})
    except Exception:
        pass


def main():
    print("="*70)
    print("  iOS 익시오 키패드 직접 입력 가능성 테스트")
    print("="*70)

    driver = create_driver()
    print("✅ Appium 연결 성공\n")

    try:
        # 앱 활성화 + 키패드 진입
        driver.activate_app(IXIO_BUNDLE_IOS)
        time.sleep(0.5)

        # 키패드 탭
        try:
            driver.find_element(AppiumBy.XPATH, '//*[contains(@name, "키패드")]').click()
            time.sleep(1)
            print("✅ 키패드 탭 이동")
        except Exception:
            print("⚠️ 키패드 탭 이동 실패 (이미 키패드일 수 있음)")

        # ─── UI 덤프 & 분석 ───────────────────────────────────────────────
        src = dump_all_elements(driver)

        # ─── 입력 방법 테스트 ────────────────────────────────────────────
        ok1 = test_textfield_input(driver)

        # TextField 입력 성공했으면 값 초기화
        if ok1:
            driver.find_element(AppiumBy.XPATH, '//*[contains(@name, "키패드")]').click()
            time.sleep(0.5)
            try:
                btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, '지우기')
                driver.execute_script('mobile: touchAndHold', {'elementId': btn.id, 'duration': 1.5})
            except Exception:
                pass

        ok2 = test_clipboard_input(driver)
        ok3 = test_iossendkeys(driver)
        test_button_speed(driver)

        print("\n" + "="*70)
        print("  📊 테스트 결과 요약")
        print("="*70)
        print(f"  TextField send_keys:        {'✅ 성공' if ok1 else '❌ 실패'}")
        print(f"  클립보드 붙여넣기:            {'✅ 성공' if ok2 else '❌ 실패'}")
        print(f"  mobile: typeText:           {'✅ 성공' if ok3 else '❌ 실패'}")

    finally:
        driver.quit()


if __name__ == '__main__':
    main()
