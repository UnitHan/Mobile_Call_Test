import time
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class CallStateDetector:
    """통화 상태 감지"""
    
    @staticmethod
    def is_call_active_android(driver, timeout=15):
        """
        Android에서 통화 활성 상태 감지
        
        Returns:
            bool: 통화 중이면 True
        """
        try:
            print("🔍 Android 통화 상태 확인 중...")
            
            # 통화 중 UI 요소 확인
            call_indicators = [
                (AppiumBy.ID, "com.android.incallui:id/callStateLabel"),
                (AppiumBy.ID, "com.android.incallui:id/elapsedTime"),
                (AppiumBy.XPATH, "//*[contains(@text, 'Call in progress')]"),
                (AppiumBy.XPATH, "//*[contains(@text, '통화 중')]"),
            ]
            
            wait = WebDriverWait(driver, timeout)
            
            for by, selector in call_indicators:
                try:
                    element = wait.until(
                        EC.presence_of_element_located((by, selector))
                    )
                    if element:
                        print("✅ Android 통화 활성 감지!")
                        return True
                except:
                    continue
            
            # ADB로 통화 상태 확인
            import subprocess
            udid = driver.capabilities.get('udid')
            result = subprocess.run(
                ['adb', '-s', udid, 'shell', 'dumpsys', 'telephony.registry'],
                capture_output=True,
                text=True
            )
            
            if 'mCallState=2' in result.stdout:  # 2 = OFFHOOK (통화 중)
                print("✅ Android 통화 활성 (ADB 확인)")
                return True
            
            print("⚠️ Android 통화 상태 확인 불가")
            return False
            
        except Exception as e:
            print(f"❌ Android 상태 확인 실패: {e}")
            return False
    
    @staticmethod
    def is_call_active_ios(driver, timeout=15):
        """
        iOS에서 통화 활성 상태 감지
        
        Returns:
            bool: 통화 중이면 True
        """
        try:
            print("🔍 iOS 통화 상태 확인 중...")
            
            # 통화 중 UI 요소 확인
            call_indicators = [
                (AppiumBy.XPATH, "//XCUIElementTypeStaticText[contains(@name, 'Call')]"),
                (AppiumBy.ACCESSIBILITY_ID, "End"),
                (AppiumBy.XPATH, "//XCUIElementTypeButton[@name='End']"),
            ]
            
            wait = WebDriverWait(driver, timeout)
            
            for by, selector in call_indicators:
                try:
                    element = wait.until(
                        EC.presence_of_element_located((by, selector))
                    )
                    if element:
                        print("✅ iOS 통화 활성 감지!")
                        return True
                except:
                    continue
            
            print("⚠️ iOS 통화 상태 확인 불가")
            return False
            
        except Exception as e:
            print(f"❌ iOS 상태 확인 실패: {e}")
            return False
    
    @staticmethod
    def wait_for_call_start(driver, platform, max_wait=20):
        """
        통화 시작 대기 (폴링 방식)
        
        Args:
            driver: Appium driver
            platform: 'android' or 'ios'
            max_wait: 최대 대기 시간 (초)
            
        Returns:
            bool: 통화 시작되면 True
        """
        print(f"⏳ {platform.upper()} 통화 시작 대기 중... (최대 {max_wait}초)")
        
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            if platform.lower() == 'android':
                if CallStateDetector.is_call_active_android(driver, timeout=1):
                    elapsed = time.time() - start_time
                    print(f"✅ 통화 시작 감지! ({elapsed:.1f}초 경과)")
                    return True
            else:  # iOS
                if CallStateDetector.is_call_active_ios(driver, timeout=1):
                    elapsed = time.time() - start_time
                    print(f"✅ 통화 시작 감지! ({elapsed:.1f}초 경과)")
                    return True
            
            time.sleep(0.5)  # 0.5초마다 확인
        
        print(f"⏱️ 타임아웃: {max_wait}초 내 통화 시작 감지 실패")
        return False
    
    @staticmethod
    def get_call_duration_android(driver):
        """Android 통화 시간 확인"""
        try:
            duration_element = driver.find_element(
                AppiumBy.ID, "com.android.incallui:id/elapsedTime"
            )
            duration = duration_element.text
            print(f"⏱️ 통화 시간: {duration}")
            return duration
        except:
            return "00:00"
    
    @staticmethod
    def get_call_duration_ios(driver):
        """iOS 통화 시간 확인"""
        try:
            # 상태표시줄의 통화 시간 요소 찾기
            duration_elements = driver.find_elements(
                AppiumBy.XPATH,
                "//XCUIElementTypeStaticText[matches(@name, '\\d{2}:\\d{2}')]"
            )
            if duration_elements:
                duration = duration_elements[0].text
                print(f"⏱️ 통화 시간: {duration}")
                return duration
        except:
            pass
        return "00:00"
