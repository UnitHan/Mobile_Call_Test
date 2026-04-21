#!/usr/bin/env python3
"""
디바이스 연결 진단 스크립트
Android와 iOS 디바이스의 Appium 연결 상태를 자세히 테스트합니다.
"""

import sys
import time
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.options.ios import XCUITestOptions


def print_section(title):
    """섹션 제목 출력"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def test_android_connection(udid, appium_port=4723):
    """Android 디바이스 연결 테스트"""
    print_section(f"📱 Android 디바이스 연결 테스트 (UDID: {udid})")
    
    try:
        print(f"1️⃣ Appium 서버: http://127.0.0.1:{appium_port}")
        print(f"2️⃣ 디바이스 UDID: {udid}")
        print(f"3️⃣ systemPort: 8300")
        print(f"\n⏳ 연결 시도 중...\n")
        
        device_config = {
            'platformName': 'Android',
            'appium:deviceName': 'test_device',
            'appium:udid': udid,
            'appium:automationName': 'UiAutomator2',
            'appium:noReset': True,
            'appium:newCommandTimeout': 60,
            'appium:systemPort': 8300,
            'appium:uiautomator2ServerLaunchTimeout': 120000,
            'appium:uiautomator2ServerInstallTimeout': 120000,
        }
        
        options = UiAutomator2Options().load_capabilities(device_config)
        driver = webdriver.Remote(f'http://127.0.0.1:{appium_port}', options=options)
        
        print(f"✅ 연결 성공!")
        print(f"\n📊 세션 정보:")
        print(f"  - 세션 ID: {driver.session_id}")
        print(f"  - 플랫폼 버전: {driver.capabilities.get('platformVersion', 'N/A')}")
        print(f"  - 디바이스 모델: {driver.capabilities.get('deviceModel', 'N/A')}")
        
        # 화면 켜짐 유지 설정 테스트
        try:
            driver.update_settings({"keepScreenOn": True})
            print(f"  - 화면 유지: ✅ 설정 완료")
        except Exception as e:
            print(f"  - 화면 유지: ⚠️ 실패 ({e})")
        
        # 현재 패키지 확인
        try:
            current_package = driver.current_package
            print(f"  - 현재 패키지: {current_package}")
        except Exception as e:
            print(f"  - 현재 패키지: ⚠️ 확인 실패 ({e})")
        
        driver.quit()
        print(f"\n✅ 세션 종료 완료")
        return True
        
    except Exception as e:
        print(f"\n❌ 연결 실패!")
        print(f"\n🔍 에러 상세:")
        print(f"  타입: {type(e).__name__}")
        print(f"  메시지: {str(e)}")
        
        # 스택 트레이스 출력
        import traceback
        print(f"\n📋 스택 트레이스:")
        traceback.print_exc()
        
        return False


def test_ios_connection(udid, appium_port=4724):
    """iOS 디바이스 연결 테스트"""
    print_section(f"📱 iOS 디바이스 연결 테스트 (UDID: {udid})")
    
    try:
        print(f"1️⃣ Appium 서버: http://127.0.0.1:{appium_port}")
        print(f"2️⃣ 디바이스 UDID: {udid}")
        print(f"3️⃣ wdaLocalPort: 8200")
        print(f"4️⃣ WebDriverAgent Bundle: com.jjun.1.WebDriverAgentRunner")
        print(f"\n⏳ 연결 시도 중 (최대 120초)...\n")
        
        device_config = {
            'platformName': 'iOS',
            'appium:deviceName': 'test_device',
            'appium:udid': udid,
            'appium:automationName': 'XCUITest',
            'appium:noReset': True,
            'appium:newCommandTimeout': 60,
            'appium:usePrebuiltWDA': True,
            'appium:useNewWDA': False,
            'appium:updatedWDABundleId': 'com.jjun.1.WebDriverAgentRunner',
            'appium:wdaLaunchTimeout': 120000,
            'appium:wdaConnectionTimeout': 120000,
            'appium:wdaLocalPort': 8200,
            'appium:mjpegServerPort': 9200,
            'appium:waitForQuiescence': False,
        }
        
        options = XCUITestOptions().load_capabilities(device_config)
        
        start_time = time.time()
        driver = webdriver.Remote(f'http://127.0.0.1:{appium_port}', options=options)
        elapsed_time = time.time() - start_time
        
        print(f"✅ 연결 성공! (소요 시간: {elapsed_time:.1f}초)")
        print(f"\n📊 세션 정보:")
        print(f"  - 세션 ID: {driver.session_id}")
        print(f"  - iOS 버전: {driver.capabilities.get('platformVersion', 'N/A')}")
        print(f"  - 디바이스 이름: {driver.capabilities.get('deviceName', 'N/A')}")
        print(f"  - WDA 포트: {driver.capabilities.get('wdaLocalPort', 'N/A')}")
        
        # 디바이스 정보 확인
        try:
            device_info = driver.execute_script('mobile: deviceInfo')
            print(f"  - 디바이스 모델: {device_info.get('name', 'N/A')}")
            print(f"  - 시뮬레이터: {device_info.get('isSimulator', 'N/A')}")
        except Exception as e:
            print(f"  - 디바이스 정보: ⚠️ 확인 실패 ({e})")
        
        # 번들 ID 확인
        try:
            bundle_id = driver.execute_script('mobile: activeAppInfo')
            print(f"  - 활성 앱: {bundle_id.get('bundleId', 'N/A')}")
        except Exception as e:
            print(f"  - 활성 앱: ⚠️ 확인 실패")
        
        driver.quit()
        print(f"\n✅ 세션 종료 완료")
        return True
        
    except Exception as e:
        print(f"\n❌ 연결 실패!")
        print(f"\n🔍 에러 상세:")
        print(f"  타입: {type(e).__name__}")
        print(f"  메시지: {str(e)}")
        
        # 스택 트레이스 출력
        import traceback
        print(f"\n📋 스택 트레이스:")
        traceback.print_exc()
        
        # 일반적인 문제 해결 방법 제안
        print(f"\n💡 문제 해결 방법:")
        print(f"  1. iPhone이 USB로 연결되어 있는지 확인")
        print(f"  2. Xcode에서 디바이스가 보이는지 확인")
        print(f"  3. idevice_id -l 명령으로 UDID 확인")
        print(f"  4. WebDriverAgent가 Xcode에서 빌드되었는지 확인")
        print(f"  5. Appium 서버 로그 확인 (포트 {appium_port})")
        
        return False


def main():
    """메인 함수"""
    print_section("🔧 디바이스 연결 진단 도구")
    
    # 사용자 입력 받기
    print("테스트할 디바이스를 선택하세요:")
    print("  1. Android만")
    print("  2. iOS만")
    print("  3. Android + iOS 모두")
    print()
    
    choice = input("선택 (1/2/3): ").strip()
    
    results = {}
    
    if choice in ['1', '3']:
        android_udid = input("\nAndroid UDID (예: 192.168.219.115:5555): ").strip()
        if android_udid:
            results['android'] = test_android_connection(android_udid)
    
    if choice in ['2', '3']:
        ios_udid = input("\niOS UDID (예: 00008101-00164D3C0CE0001E): ").strip()
        if ios_udid:
            results['ios'] = test_ios_connection(ios_udid)
    
    # 최종 결과 요약
    print_section("📊 테스트 결과 요약")
    
    for platform, success in results.items():
        status = "✅ 성공" if success else "❌ 실패"
        print(f"  {platform.upper()}: {status}")
    
    print()
    
    # 종료 코드 반환
    all_success = all(results.values())
    sys.exit(0 if all_success else 1)


if __name__ == '__main__':
    main()
