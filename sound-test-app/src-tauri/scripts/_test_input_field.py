#!/usr/bin/env python3
"""익시오 키패드 입력 필드에 send_keys 가능 여부 테스트.

StaticText 영역을 tap 후 다양한 방법으로 전화번호를 한번에 입력하는 테스트.
"""

import json
import re
import subprocess
import sys
import time

import requests
from appium import webdriver
from appium.options.common import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy

# ── 설정 ──
IOS_UDID = '00008150-00110C341E38401C'
IXIO_BUNDLE = 'com.lguplus.aicallagent'
APPIUM_PORT = 4730
WDA_URL = 'http://192.168.219.100:8100'
TEST_NUMBER = '01083330025'


def get_ios_version() -> str:
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


def create_driver():
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
        'appium:webDriverAgentUrl': WDA_URL,
        'appium:usePrebuiltWDA': True,
        'appium:useNewWDA': False,
    }
    options = AppiumOptions()
    options.load_capabilities(caps)
    driver = webdriver.Remote(f'http://127.0.0.1:{APPIUM_PORT}', options=options)
    return driver


def main():
    print("=" * 60)
    print("🧪 익시오 키패드 입력 필드 테스트")
    print("=" * 60)

    driver = create_driver()
    print("✅ Appium 연결 OK\n")

    try:
        # 1) 익시오 앱 활성화
        driver.activate_app(IXIO_BUNDLE)
        time.sleep(1)

        # 키패드 탭 이동
        try:
            btn = driver.find_element(AppiumBy.XPATH, '//*[contains(@name, "키패드")]')
            btn.click()
            time.sleep(1)
        except Exception:
            pass

        # 2) 입력 필드 찾기 — StaticText with bounds near [0, 272, 402, 50]
        print("── 방법별 테스트 ──\n")

        # 기존 번호 지우기
        try:
            clear_btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, '지우기')
            driver.execute_script('mobile: touchAndHold', {
                'elementId': clear_btn.id,
                'duration': 2.0,
            })
            time.sleep(0.5)
            print("  🗑️ 기존 번호 삭제 완료")
        except Exception:
            print("  ℹ️ 지우기 버튼 없음 (입력 필드 비어있음)")

        # ── 방법 1: StaticText 영역 tap → send_keys ──
        print("\n📌 방법 1: StaticText tap → send_keys")
        try:
            # bounds [0, 272, 402, 50] 중앙 탭
            driver.execute_script('mobile: tap', {'x': 200, 'y': 297})
            time.sleep(0.5)
            
            # 입력 필드 요소 찾기
            field = driver.find_element(
                AppiumBy.XPATH,
                '//XCUIElementTypeStaticText[@x="0" and @y="272"]'
            )
            field.send_keys(TEST_NUMBER)
            time.sleep(1)
            print(f"  ✅ send_keys 성공!")
            # 결과 확인
            src = driver.page_source[:2000]
            if TEST_NUMBER in src or '010' in src:
                print(f"  ✅ 번호 입력 확인됨!")
            else:
                print(f"  ⚠️ 번호가 화면에 표시 안 됨")
        except Exception as e:
            print(f"  ❌ 실패: {e}")

        # 지우기
        try:
            clear_btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, '지우기')
            driver.execute_script('mobile: touchAndHold', {
                'elementId': clear_btn.id,
                'duration': 2.0,
            })
            time.sleep(0.5)
        except Exception:
            pass

        # ── 방법 2: mobile: type (포커스 없이 키 입력) ──
        print("\n📌 방법 2: mobile: type")
        try:
            # 입력 필드 영역 탭 먼저
            driver.execute_script('mobile: tap', {'x': 200, 'y': 297})
            time.sleep(0.3)
            driver.execute_script('mobile: type', {'text': TEST_NUMBER})
            time.sleep(1)
            print(f"  ✅ mobile: type 성공!")
        except Exception as e:
            print(f"  ❌ 실패: {e}")

        # 지우기
        try:
            clear_btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, '지우기')
            driver.execute_script('mobile: touchAndHold', {
                'elementId': clear_btn.id,
                'duration': 2.0,
            })
            time.sleep(0.5)
        except Exception:
            pass

        # ── 방법 3: WDA /wda/keys 직접 호출 ──
        print("\n📌 방법 3: WDA /wda/keys 직접 호출")
        try:
            # 입력 필드 탭
            driver.execute_script('mobile: tap', {'x': 200, 'y': 297})
            time.sleep(0.3)
            resp = requests.post(
                f'{WDA_URL}/wda/keys',
                json={'value': list(TEST_NUMBER)},
                timeout=5
            )
            print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
            time.sleep(1)
            if resp.status_code == 200:
                print(f"  ✅ WDA keys 성공!")
            else:
                print(f"  ❌ WDA keys 실패")
        except Exception as e:
            print(f"  ❌ 실패: {e}")

        # 지우기
        try:
            clear_btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, '지우기')
            driver.execute_script('mobile: touchAndHold', {
                'elementId': clear_btn.id,
                'duration': 2.0,
            })
            time.sleep(0.5)
        except Exception:
            pass

        # ── 방법 4: 클립보드 붙여넣기 ──
        print("\n📌 방법 4: 클립보드 붙여넣기")
        try:
            import base64
            # 클립보드에 번호 설정
            driver.set_clipboard_content(
                base64.b64encode(TEST_NUMBER.encode()).decode(),
                'plaintext'
            )
            time.sleep(0.3)
            # 입력 필드 탭
            driver.execute_script('mobile: tap', {'x': 200, 'y': 297})
            time.sleep(0.5)
            # 붙여넣기 시도 (Cmd+V)
            # XCUITest에서는 pasteboard 직접 접근 불가할 수 있음
            print(f"  ℹ️ 클립보드 설정 완료 — 수동 붙여넣기 필요할 수 있음")
        except Exception as e:
            print(f"  ❌ 실패: {e}")

        # ── 방법 5: 각 숫자를 개별 element 없이 active element에 send_keys ──
        print("\n📌 방법 5: active element send_keys")
        try:
            driver.execute_script('mobile: tap', {'x': 200, 'y': 297})
            time.sleep(0.3)
            active = driver.switch_to.active_element
            print(f"  active element: {active.tag_name}, text='{active.text}'")
            active.send_keys(TEST_NUMBER)
            time.sleep(1)
            print(f"  ✅ active element send_keys 성공!")
        except Exception as e:
            print(f"  ❌ 실패: {e}")

        print("\n" + "=" * 60)
        print("테스트 완료 — 화면에서 결과 확인")
        print("=" * 60)

    finally:
        driver.quit()


if __name__ == '__main__':
    main()
