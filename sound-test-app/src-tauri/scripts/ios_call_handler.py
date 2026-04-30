"""
iOS 통화 처리 Mixin — open_keypad_iphone, make_call_iphone,
_pre_call_ios_audio_setup, force_ios_external_mic
IxioAutomatedTest에서 분리 (SRP: iOS 플랫폼 통화 UI 조작 전담)
"""

import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class IosCallHandlerMixin:
    """iOS 키패드 오픈·발신·오디오 라우팅을 담당하는 Mixin."""

    _IXIO_BUNDLE_ID = 'com.lguplus.aicallagent'  # 레거시 폴백 (인스턴스 속성 우선)

    @property
    def _ios_bundle(self) -> str:
        """현재 테스트 대상 iOS 앱 번들 ID. IxioAutomatedTest에서 설정."""
        return getattr(self, 'ios_app_bundle_id', self._IXIO_BUNDLE_ID)

    # ── 앱별 수신 화면 판별 패턴 (iOS) ──────────────────────────────────
    # key: ios_app_bundle_id, value: {header_keywords, answer_labels}
    #   header_keywords: page_source에서 수신 화면 판별 키워드
    #   answer_labels:   수신 버튼 접근성 ID 후보 (추후 사용)
    IOS_INCOMING_PATTERNS = {
        'com.lguplus.aicallagent': {
            'header_keywords': ['익시오 음성통화', '익시오 전화 수신'],
            'answer_labels': ['받기'],
        },
        'com.apple.mobilephone': {
            'header_keywords': ['전화번호'],
            'answer_labels': ['응답'],
        },
        'com.sktelecom.tphone': {
            'header_keywords': ['에이닷', 'T전화', '수신'],
            'answer_labels': ['받기', '응답'],
        },
        # com.skt.prod.dialer = 에이닷 전화 다른 버전 (bundle ID 변형 대응)
        'com.skt.prod.dialer': {
            'header_keywords': ['에이닷', 'T전화', '수신'],
            'answer_labels': ['받기', '응답'],
        },
    }

    @property
    def _ios_incoming_pattern(self) -> dict:
        """현재 테스트 대상 iOS 앱의 수신 화면 패턴."""
        bundle = self._ios_bundle
        return self.IOS_INCOMING_PATTERNS.get(bundle, {
            'header_keywords': ['수신', '전화'],
            'answer_labels': ['받기', '응답', '수락'],
        })

    def _detect_ios_incoming_app(self, page_source: str) -> str:
        """page_source에서 어떤 앱의 수신 화면인지 판별합니다.

        Returns: 앱 이름 문자열 또는 '알 수 없음'
        """
        _APP_NAMES = {
            'com.lguplus.aicallagent': '익시오',
            'com.apple.mobilephone': 'Apple 전화',
            'com.sktelecom.tphone': '에이닷 전화',
            'com.skt.prod.dialer': '에이닷 전화',
        }
        for bundle_id, pattern in self.IOS_INCOMING_PATTERNS.items():
            for kw in pattern['header_keywords']:
                if kw in page_source:
                    return _APP_NAMES.get(bundle_id, bundle_id)
        # 일반 수신 버튼이 있으면 '기본 전화'
        if any(kw in page_source for kw in ['응답', '받기', '수락', 'Accept', 'Answer']):
            return '기본 전화'
        return '알 수 없음'

    # 숫자 → 한글 키패드 버튼 매핑 (익시오 앱 고유)
    _KEYPAD_KR = {
        '0': '공', '1': '일', '2': '이', '3': '삼', '4': '사',
        '5': '오', '6': '육', '7': '칠', '8': '팔', '9': '구',
        '*': '별', '#': '#',
    }

    # 키패드 화면 판별 기준: 숫자 버튼이 하나라도 있으면 키패드
    _KEYPAD_DIGIT_IDS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']
    # 키패드 탭 버튼 접근성 ID 후보
    # 에이닷 전화(com.skt.prod.dialer / com.sktelecom.tphone)는 탭 이름이 다를 수 있어 후보 확장
    _KEYPAD_TAB_IDS  = [
        '키패드', 'Keypad', 'dialpad', 'dial_pad',          # 익시오 / 일반
        '다이얼', 'Dial', 'dial', '번호판', '번호',           # 에이닷 전화 후보
        '전화걸기', '발신', 'Phone', 'phone', 'DialPad',      # 기타 후보
    ]

    # iMessage/FaceTime 등록 팝업 등 시스템 알림에서 '거절' 역할 버튼 후보
    _ALERT_DISMISS_IDS = ['아니요', '나중에', '무시', '취소', "Don't Allow", 'Cancel', 'Not Now']
    # 시스템 알림 존재 판별 키워드 (page_source 내 label에서 감지)
    _ALERT_KEYWORDS    = ['iMessage', 'FaceTime', '추가하겠습니까', '허용하시겠습니까', 'Apple']

    def _dismiss_ios_system_alerts(self, driver) -> bool:
        """화면에 떠 있는 iOS 시스템 알림(팝업)을 '아니요/취소' 버튼으로 닫습니다.

        iMessage·FaceTime 번호 추가 팝업처럼 앱 종료 후에도 잔류하는
        시스템 레벨 알림을 제거해 키패드 조작이 가능한 상태로 만듭니다.
        닫은 팝업이 1개 이상이면 True 반환.
        """
        dismissed = 0
        # 1) Appium alert API 시도 (가장 확실)
        try:
            alert = driver.switch_to.alert
            alert.dismiss()   # '취소/아니요' 계열 버튼 자동 선택
            print(f"  ✓ 시스템 알림 dismiss (Appium alert API)")
            time.sleep(0.5)
            dismissed += 1
        except Exception:
            pass

        # 2) 접근성 ID 직접 클릭 (Appium alert API가 실패하는 버전 대응)
        for aid in self._ALERT_DISMISS_IDS:
            try:
                btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, aid)
                btn.click()
                print(f"  ✓ 시스템 알림 닫음: '{aid}' 클릭")
                time.sleep(0.5)
                dismissed += 1
            except Exception:
                pass

        return dismissed > 0

    # 키패드 판정에 필요한 최소 숫자 버튼 (탭바 인덱스 등 false-positive 방지)
    _KEYPAD_REQUIRED_DIGITS = ['1', '2', '3']
    # 한글 키패드 판별용
    _KEYPAD_REQUIRED_KR = ['일', '이', '삼']

    def _is_on_keypad(self, driver, timeout: float = 0) -> bool:
        """키패드 화면 여부 확인.

        숫자 ID ('1','2','3') 또는 한글 name ('일','이','삼') 중 하나라도
        3개 모두 발견되면 키패드로 판정합니다.

        timeout=0: 즉시 확인
        timeout>0: 최대 timeout초 동안 나타날 때까지 대기
        """
        def _all_digits_present() -> bool:
            # 1) 숫자 AID 직접 매칭 (일반 앱)
            found = 0
            for d in self._KEYPAD_REQUIRED_DIGITS:
                try:
                    driver.find_element(AppiumBy.ACCESSIBILITY_ID, d)
                    found += 1
                except Exception:
                    pass
            if found >= 3:
                return True
            # 2) 한글 name 매칭 (XPath contains — 익시오 앱)
            found = 0
            for kr in self._KEYPAD_REQUIRED_KR:
                try:
                    driver.find_element(AppiumBy.XPATH, f'//*[contains(@name, "{kr}")]')
                    found += 1
                except Exception:
                    pass
            if found >= 3:
                return True
            # 3) 에이닷 전화: name='1, ㄱ ㅋ...' 형태 — starts-with 매칭
            found = 0
            for d in self._KEYPAD_REQUIRED_DIGITS:
                try:
                    driver.find_element(AppiumBy.XPATH, f'//*[starts-with(@name, "{d},")]')
                    found += 1
                except Exception:
                    pass
            return found >= 3

        try:
            if timeout > 0:
                WebDriverWait(driver, timeout).until(lambda _: _all_digits_present())
            else:
                return _all_digits_present()
            return True
        except Exception:
            return False

    def _navigate_to_keypad_tab(self, driver) -> bool:
        """하단 탭바에서 키패드 탭을 클릭합니다."""
        def _click_and_wait(el):
            el.click()
            # 키패드 화면 전환 대기: WebDriverWait (최대 2초)
            return self._is_on_keypad(driver, timeout=2.0)

        # 접근성 ID 시도 (전체 후보 순회)
        for label in self._KEYPAD_TAB_IDS:
            try:
                el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, label)
                if _click_and_wait(el):
                    return True
            except Exception:
                pass
        # XPath — 이름/레이블에 키패드 관련 키워드 포함한 버튼
        xpath_keyword_list = [
            '//XCUIElementTypeButton[contains(@name,"키패드") or contains(@label,"키패드")]',
            '//XCUIElementTypeButton[contains(@name,"다이얼") or contains(@label,"다이얼")]',
            '//XCUIElementTypeButton[contains(@name,"Keypad") or contains(@label,"Keypad")]',
            '//XCUIElementTypeButton[contains(@name,"Dial") or contains(@label,"Dial")]',
            '//XCUIElementTypeTabBar//XCUIElementTypeButton[contains(@name,"키패드")]',
            '//XCUIElementTypeTabBar//XCUIElementTypeButton[contains(@name,"다이얼")]',
        ]
        for xp in xpath_keyword_list:
            try:
                el = driver.find_element(AppiumBy.XPATH, xp)
                if _click_and_wait(el):
                    return True
            except Exception:
                pass

        # 마지막 폴백: 탭바의 모든 버튼을 순서대로 눌러보며 키패드 여부 확인
        # (무조건 첫 번째 탭을 클릭하는 대신 각 탭을 시도)
        try:
            tab_buttons = driver.find_elements(
                AppiumBy.XPATH, '//XCUIElementTypeTabBar//XCUIElementTypeButton'
            )
            if tab_buttons:
                btn_names = [b.get_attribute('name') or b.get_attribute('label') or '' for b in tab_buttons]
                print(f"  [키패드탭] 탭바 버튼 목록: {btn_names}")
                for btn in tab_buttons:
                    if _click_and_wait(btn):
                        return True
        except Exception:
            pass
        return False

    def _clear_dial_field_ios(self, driver) -> None:
        """iOS 키패드 다이얼 필드에 잔류 번호가 있으면 '지우기' 롱프레스로 한 번에 삭제합니다.

        롱프레스(1.5초) → 전체 삭제 후 단타 클릭으로 잔여 확인.
        """
        import re as _re
        try:
            src = driver.page_source
        except Exception:
            return
        # 다이얼 표시 값: value 속성에 2자리 이상 숫자열로 나타남
        m = _re.search(r'\bvalue="(\d[\d\-\s]{1,15})"', src)
        if not m:
            return  # 잔류 번호 없음
        digit_count = len(_re.sub(r'\D', '', m.group(1)))
        if digit_count == 0:
            return

        # 지우기 버튼 AID 후보: 익시오='지우기', 에이닷='입력된 전화번호 지우기'
        _DELETE_AIDS = ['지우기', '입력된 전화번호 지우기']
        delete_btn = None
        for aid in _DELETE_AIDS:
            try:
                delete_btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, aid)
                break
            except Exception:
                pass

        try:
            if delete_btn is None:
                raise RuntimeError('지우기 버튼 없음')
            # XCUITest mobile:touchAndHold — W3C Actions API 방식은 WDA에서
            # "Actions list cannot be empty" 오류 발생 가능하므로 사용하지 않음
            driver.execute_script('mobile: touchAndHold', {
                'elementId': delete_btn.id,
                'duration': 1.5,
            })
            time.sleep(0.3)
            print(f"  ✓ iOS 키패드 잔류 번호 롱프레스 삭제 완료 ({digit_count}자리)")
        except Exception as e:
            print(f"  ⚠️ 롱프레스 실패({e}), 단타 클릭으로 재시도")
            for _ in range(digit_count):
                found = False
                for aid in _DELETE_AIDS:
                    try:
                        driver.find_element(AppiumBy.ACCESSIBILITY_ID, aid).click()
                        found = True
                        break
                    except Exception:
                        pass
                if not found:
                    break
                time.sleep(0.05)
            print(f"  ✓ iOS 키패드 잔류 번호 단타 삭제 완료 ({digit_count}자리)")

        # ─── 삭제 후 키패드 이탈 방지 ──────────────────────────────────────
        # ixiO 앱: 필드가 비워지면 자동으로 최근통화 화면으로 이동하는 경우 있음
        # 삭제 직후 키패드가 사라졌으면 키패드 탭으로 재진입
        time.sleep(0.2)
        if not self._is_on_keypad(driver, timeout=0):
            print(f"  ↩️ 삭제 후 키패드 이탈 감지 → 키패드 탭 재진입")
            self._navigate_to_keypad_tab(driver)
            time.sleep(0.5)

    @staticmethod
    def _ios_wake_screen(driver) -> None:
        """iPhone 화면이 꺼져 있으면 깨웁니다 (activate_app 전 필수 호출).

        'mobile: unlock' 명령으로 잠금 해제 시도.
        장치가 이미 켜져 있으면 무해하게 통과.
        """
        try:
            driver.execute_script('mobile: unlock')
        except Exception:
            pass

    def open_keypad_iphone(self, device_type='speaker1'):
        """iPhone 익시오 앱에서 키패드 화면을 엽니다.

        전략 (빠른 순서):
          0. activate_app → 이미 키패드면 즉시 반환 (콜드 스타트 없음)
          1. 키패드 탭 클릭 → 확인
          2. 시스템 알림 닫기 후 재시도
          3. 위 모두 실패 시에만 terminate → 재실행 (최후 수단)
        """
        driver = self.drivers[device_type]
        bundle  = self._ios_bundle

        print(f"📱 {device_type}: 익시오 앱 키패드 열기...")

        # ── Step 0: 앱 포그라운드 전환 (terminate 없이 — 콜드 스타트 방지) ──
        self._ios_wake_screen(driver)  # 화면이 꺼진 경우 먼저 깨우기
        try:
            driver.activate_app(bundle)
            print(f"  ✓ 익시오 앱 활성화")
        except Exception as e:
            print(f"  ⚠️ activate_app 실패: {e}")

        # ── Step 1: 이미 키패드 화면이면 잔류 번호만 지우고 반환 ────────────
        if self._is_on_keypad(driver, timeout=3.0):
            self._clear_dial_field_ios(driver)  # 내부에서 이탈 시 자동 재진입
            if not self._is_on_keypad(driver, timeout=2.0):
                # _clear_dial_field_ios 내부 재진입 실패 시 한번 더 시도
                self._navigate_to_keypad_tab(driver)
            print(f"✅ 키패드 화면 확인\n")
            return True

        # ── Step 2: 키패드 탭 클릭 ────────────────────────────────────────
        if self._navigate_to_keypad_tab(driver):
            self._clear_dial_field_ios(driver)  # 내부에서 이탈 시 자동 재진입
            if not self._is_on_keypad(driver, timeout=2.0):
                self._navigate_to_keypad_tab(driver)
            print(f"✅ 키패드 열기 완료\n")
            return True

        # ── Step 3: 시스템 알림(iMessage/FaceTime 등)이 막고 있을 수 있음 ──
        self._dismiss_ios_system_alerts(driver)
        if self._is_on_keypad(driver, timeout=2.0) or self._navigate_to_keypad_tab(driver):
            self._clear_dial_field_ios(driver)  # 내부에서 이탈 시 자동 재진입
            if not self._is_on_keypad(driver, timeout=2.0):
                self._navigate_to_keypad_tab(driver)
            print(f"✅ 키패드 열기 완료 (알림 닫기 후)\n")
            return True

        # ── Step 4: 최후 수단 — 앱 재시작 (잔류 번호 초기화 포함) ──────────
        print(f"  🔄 키패드 진입 실패 → 앱 재시작")
        try:
            driver.terminate_app(bundle)
            print(f"  ✓ 앱 종료")
        except Exception as e:
            print(f"  ⚠️ terminate_app 실패: {e}")
        time.sleep(1)
        self._ios_wake_screen(driver)  # 재시작 전 화면 wake
        try:
            driver.activate_app(bundle)
            print(f"  ✓ 앱 재실행")
        except Exception as e:
            print(f"  ⚠️ activate_app 실패: {e}")
        self._dismiss_ios_system_alerts(driver)
        if self._is_on_keypad(driver, timeout=5.0):
            print(f"✅ 키패드 화면 확인 (재시작 후)\n")
            return True
        if self._navigate_to_keypad_tab(driver):
            print(f"✅ 키패드 열기 완료 (재시작 후)\n")
            return True

        # ── 완전 실패: 진단 출력 + 수동 대기 ────────────────────────────
        try:
            import re as _re
            src    = driver.page_source
            labels = _re.findall(r'(?:name|label)="([^"]+)"', src)
            print(f"  [진단] 현재 화면 name/label: {sorted(set(labels))[:30]}")
        except Exception:
            pass
        print(f"💡 수동으로 익시오 앱 키패드 탭을 열어주세요. (7초 대기)\n")
        time.sleep(7)
        # 7초 후 다시 확인 — 수동으로 열었으면 성공, 아니면 실패 전파
        if self._is_on_keypad(driver, timeout=1.0):
            return True
        return False

    def _build_digit_coords(self, driver) -> dict[str, tuple[int, int]]:
        """page_source 1회 파싱으로 모든 숫자 버튼의 중심 좌표를 추출합니다.

        기존 _find_digit_btn_ios()는 숫자 하나당 최대 4회 WDA HTTP 호출이
        필요했지만, 이 방식은 page_source 1회 호출로 전체 매핑을 완성합니다.
        반환: {'0': (cx, cy), '1': (cx, cy), ...}
        """
        import xml.etree.ElementTree as ET

        try:
            src = driver.page_source
        except Exception:
            return {}

        try:
            root = ET.fromstring(src)
        except ET.ParseError:
            return {}

        kr_to_digit = {v: k for k, v in self._KEYPAD_KR.items()}
        coords: dict[str, tuple[int, int]] = {}

        for elem in root.iter():
            name = (elem.get('name') or elem.get('label') or '').strip()
            if not name:
                continue

            digit = None
            if name in kr_to_digit:
                # 익시오: '공','일','이'...
                digit = kr_to_digit[name]
            elif len(name) == 1 and name in '0123456789*#':
                # 일반: 단일 숫자/기호
                digit = name
            else:
                # 에이닷 전화: '1, ㄱ ㅋ, 닷 Q Z' 형태 — 첫 문자가 숫자+쉼표
                for d in '0123456789':
                    if name.startswith(d + ','):
                        digit = d
                        break

            if digit is not None and digit not in coords:
                x = elem.get('x')
                y = elem.get('y')
                w = elem.get('width')
                h = elem.get('height')
                if x and y and w and h:
                    try:
                        cx = int(x) + int(w) // 2
                        cy = int(y) + int(h) // 2
                        coords[digit] = (cx, cy)
                    except ValueError:
                        pass

        return coords

    # ── verify-then-act 헬퍼: "보이면 누른다" ─────────────────────────

    def _visible_tap_ios(self, driver, locators: list, *,
                         timeout: float = 5.0, label: str = "요소") -> bool:
        """요소가 화면에 보이면 탭합니다 (verify-then-act).

        locators: [(AppiumBy.ACCESSIBILITY_ID, "전화걸기"), (AppiumBy.XPATH, "...")]
        각 locator에 대해 WebDriverWait로 visibility를 확인한 후 클릭합니다.
        """
        per_locator_timeout = max(1.0, timeout / max(len(locators), 1))
        for strategy, value in locators:
            try:
                el = WebDriverWait(driver, per_locator_timeout).until(
                    EC.visibility_of_element_located((strategy, value))
                )
                el.click()
                print(f"  ✓ {label} 발견 → 클릭 ('{value}')")
                return True
            except Exception:
                continue
        print(f"  ⚠️ {label} {timeout}초 내 미발견")
        return False

    def _verify_dial_field_ios(self, driver, expected: str) -> bool:
        """page_source에서 다이얼 필드에 입력된 번호가 expected와 일치하는지 확인합니다.

        숫자만 추출하여 비교 (하이픈·공백 포매팅 무시).
        - 익시오/일반: value="010..." 속성
        - 에이닷 전화: name='010, 입력된 전화번호, 텍스트필드' — name 앞 부분
        """
        import re as _re
        try:
            src = driver.page_source
        except Exception:
            return False
        expected_digits = _re.sub(r'\D', '', expected)
        # 1) value 속성에서 숫자 추출 (익시오/일반)
        for m in _re.finditer(r'\bvalue="([^"]*)"', src):
            actual = _re.sub(r'\D', '', m.group(1))
            if actual == expected_digits:
                print(f"  ✓ 다이얼 필드 검증 OK: {m.group(1)}")
                return True
            elif actual and len(actual) >= len(expected_digits) * 0.5:
                print(f"  ⚠️ 다이얼 필드 불일치: 기대={expected_digits}, 실제={actual}")
                return False
        # 2) 에이닷 전화: name='<숫자>, 입력된 전화번호, ...' 패턴
        m2 = _re.search(r'name="([\d\-\s]+),\s*입력된 전화번호', src)
        if m2:
            actual = _re.sub(r'\D', '', m2.group(1))
            if actual == expected_digits:
                print(f"  ✓ 다이얼 필드 검증 OK (에이닷): {m2.group(1)}")
                return True
            elif actual:
                print(f"  ⚠️ 다이얼 필드 불일치 (에이닷): 기대={expected_digits}, 실제={actual}")
                return False
        return False

    def _find_digit_btn_ios(self, driver, digit: str):
        """iOS 키패드에서 특정 숫자 버튼을 찾습니다.

        익시오 앱은 한글 accessibility ID(공/일/이/삼/...)를 사용하며
        name에 공백 패딩이 있으므로 XPath contains() 매칭을 우선합니다.
        """
        kr_name = self._KEYPAD_KR.get(digit)

        # 1) 한글 accessibility ID 정확 매칭
        if kr_name:
            try:
                return driver.find_element(AppiumBy.ACCESSIBILITY_ID, kr_name)
            except Exception:
                pass

        # 2) 한글 XPath contains — 공백 패딩 대응
        if kr_name:
            try:
                return driver.find_element(
                    AppiumBy.XPATH,
                    f'//*[contains(@name, "{kr_name}")]'
                )
            except Exception:
                pass

        # 3) 숫자 accessibility ID 폴백 (영문 iOS / 다른 앱)
        try:
            return driver.find_element(AppiumBy.ACCESSIBILITY_ID, digit)
        except Exception:
            pass

        # 4) 에이닷 전화: name='1, ㄱ...' 형태 — starts-with 매칭
        xpaths = [
            f'//XCUIElementTypeButton[starts-with(@name, "{digit},")]',
            f'//XCUIElementTypeButton[starts-with(@label, "{digit},")]',
            # 5) 탭바 외부 버튼 중 label 정확히 일치
            f'//XCUIElementTypeButton[not(ancestor::XCUIElementTypeTabBar) and @label="{digit}"]',
            f'//XCUIElementTypeKey[@label="{digit}"]',
        ]
        for xp in xpaths:
            try:
                return driver.find_element(AppiumBy.XPATH, xp)
            except Exception:
                pass
        return None

    # 에이닷 전화 bundle ID 목록
    _ADOT_BUNDLES = {'com.sktelecom.tphone', 'com.skt.prod.dialer'}

    def _build_digit_aid_map(self, driver) -> dict[str, str]:
        """page_source 1회 파싱으로 숫자 버튼의 full AID 문자열 매핑 반환.

        - 익시오: name='공','일','이'...
        - 에이닷 전화: name='1, ㄱ ㅋ, 닷 Q Z' (숫자+쉼표로 시작)
        - 일반: name='1','2'...
        반환: {'0': '0, ㅎ, 더하기', '1': '1, ㄱ ㅋ, 닷 Q Z', ...}
        """
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(driver.page_source)
        except Exception:
            return {}

        kr_to_digit = {v: k for k, v in self._KEYPAD_KR.items()}
        aid_map: dict[str, str] = {}

        for elem in root.iter():
            name = (elem.get('name') or '').strip()
            if not name:
                continue

            digit = None
            if name in kr_to_digit:
                digit = kr_to_digit[name]
            elif len(name) == 1 and name in '0123456789*#':
                digit = name
            else:
                for d in '0123456789*#':
                    if name.startswith(d + ','):
                        digit = d
                        break

            if digit is not None and digit not in aid_map:
                aid_map[digit] = name

        return aid_map

    def _dial_by_aid(self, driver, phone_number: str, aid_map: dict[str, str]) -> int:
        """AID 문자열로 숫자 버튼을 직접 찾아 클릭. 실패 자릿수 반환."""
        miss = 0
        for ch in phone_number:
            aid = aid_map.get(ch)
            if not aid:
                print(f"  ⚠️ '{ch}' AID 매핑 없음")
                miss += 1
                continue
            try:
                driver.find_element(AppiumBy.ACCESSIBILITY_ID, aid).click()
            except Exception:
                # stale → 재탐색
                new_map = self._build_digit_aid_map(driver)
                aid = new_map.get(ch)
                if aid:
                    try:
                        driver.find_element(AppiumBy.ACCESSIBILITY_ID, aid).click()
                    except Exception:
                        miss += 1
                else:
                    miss += 1
            time.sleep(0.06)
        return miss

    def make_call_iphone(self, phone_number):
        """iPhone에서 전화 걸기 — 숫자 버튼 하나씩 클릭."""
        driver = self.drivers['speaker1']

        try:
            print(f"📞 전화번호 입력 중 (iPhone): {phone_number}")

            # 혹시 남아있는 시스템 알림 닫기
            self._dismiss_ios_system_alerts(driver)

            # ── 키패드 화면 재확인 + 복구 ────────────────────────────────────
            if not self._is_on_keypad(driver, timeout=0):
                print(f"  ⚠️ 키패드 화면이 아님 감지 → 키패드 탭으로 이동 시도")
                if not self._navigate_to_keypad_tab(driver):
                    print(f"  🔄 탭 클릭 실패 → 앱 재시작")
                    try:
                        driver.terminate_app(self._ios_bundle)
                        time.sleep(1)
                        self._ios_wake_screen(driver)  # 재시작 전 화면 wake
                        driver.activate_app(self._ios_bundle)
                    except Exception:
                        pass
                    self._dismiss_ios_system_alerts(driver)
                    self._navigate_to_keypad_tab(driver)

                if not self._is_on_keypad(driver, timeout=5.0):
                    print(f"  ❌ 키패드 화면 진입 실패 — 현재 화면:")
                    try:
                        import re as _re
                        labels = _re.findall(r'(?:name|label)="([^"]+)"', driver.page_source)
                        print(f"     {sorted(set(labels))[:20]}")
                    except Exception:
                        pass
                    print(f"  💡 수동으로 키패드 탭을 열어주세요. (5초 대기)")
                    time.sleep(5)
                else:
                    print(f"  ✅ 키패드 화면 진입 완료")

            # ── 키패드 완전 로드 대기 (iOS XCUITest 레이아웃 완료 보장) ──────
            time.sleep(0.8)

            # ── 숫자 입력 (실패 시 최대 3회 재시도) ──────────────────────────
            MAX_DIAL_ATTEMPTS = 3
            miss_count = len(phone_number)  # 초기값: 전부 실패 가정

            for attempt in range(1, MAX_DIAL_ATTEMPTS + 1):
                if attempt > 1:
                    print(f"  🔄 재시도 {attempt}/{MAX_DIAL_ATTEMPTS} — 키패드 재진입 + 잔류번호 삭제")
                    self._navigate_to_keypad_tab(driver)
                    time.sleep(0.5)
                else:
                    # 첫 시도에도 잔류 번호 초기화 (이전 테스트 번호 누적 방지)
                    print(f"  🧹 입력 전 다이얼 필드 초기화...")
                self._clear_dial_field_ios(driver)  # 모든 시도에서 항상 초기화
                if not self._is_on_keypad(driver, timeout=2.0):
                    self._navigate_to_keypad_tab(driver)
                time.sleep(0.5)

                # ── 에이닷 전화: full AID 직접 클릭 (page_source 1회 파싱) ──
                if self._ios_bundle in self._ADOT_BUNDLES:
                    aid_map = self._build_digit_aid_map(driver)
                    needed = set(phone_number)
                    if aid_map and needed.issubset(aid_map.keys()):
                        print(f"  📲 에이닷 전화 AID 클릭 방식 ({len(aid_map)}개 버튼 감지)")
                        miss_count = self._dial_by_aid(driver, phone_number, aid_map)
                    else:
                        print(f"  ⚠️ 에이닷 AID 맵 불완전 ({sorted(aid_map.keys())} / 필요={sorted(needed)})")
                        miss_count = len(phone_number)

                # ── 익시오/일반: 좌표 기반 고속 입력 시도 (page_source 1회 파싱) ─
                else:
                    digit_coords = self._build_digit_coords(driver)
                    needed = set(phone_number)
                    if digit_coords and needed.issubset(digit_coords.keys()):
                        print(f"  📲 좌표 기반 고속 입력 ({len(digit_coords)}개 버튼 감지)")
                        miss_count = 0
                        for ch in phone_number:
                            cx, cy = digit_coords[ch]
                            try:
                                driver.execute_script('mobile: tap', {'x': cx, 'y': cy})
                            except Exception:
                                miss_count += 1
                            time.sleep(0.05)
                    else:
                        # ── 폴백: 요소 탐색 + 클릭 방식 ──────────────────────────
                        print(f"  📲 버튼 클릭 방식으로 입력 중... (좌표 {len(digit_coords)}/{len(needed)}개)")
                        digit_map: dict[str, object] = {}
                        for d in needed:
                            btn = self._find_digit_btn_ios(driver, d)
                            if btn is not None:
                                digit_map[d] = btn

                        if not digit_map:
                            print(f"  ⚠️ 숫자 버튼 전혀 감지 안 됨 → 키패드 재진입 시도")
                            self._navigate_to_keypad_tab(driver)
                            time.sleep(1)
                            for d in needed:
                                btn = self._find_digit_btn_ios(driver, d)
                                if btn is not None:
                                    digit_map[d] = btn

                        miss_count = 0
                        for i, ch in enumerate(phone_number):
                            btn = digit_map.get(ch)
                            if btn is None:
                                btn = self._find_digit_btn_ios(driver, ch)
                            if btn is None:
                                print(f"  ⚠️ '{ch}' 버튼을 찾을 수 없어 스킵 ({i+1}/{len(phone_number)})")
                                miss_count += 1
                                continue
                            try:
                                btn.click()
                            except Exception:
                                btn = self._find_digit_btn_ios(driver, ch)
                                if btn:
                                    btn.click()
                                else:
                                    miss_count += 1
                                    continue
                            time.sleep(0.05)

                if miss_count == 0:
                    break  # 전체 입력 성공
                # miss_count > 0 이어도 다이얼 필드가 올바르면 재시도하지 않음
                # (stale-element 오류로 miss로 계산됐지만 실제 입력은 성공한 경우)
                if self._verify_dial_field_ios(driver, phone_number):
                    print(f"  ✅ 다이얼 필드 검증 OK — miss 무시하고 진행")
                    miss_count = 0
                    break
                print(f"  ⚠️ 총 {miss_count}/{len(phone_number)}자리 입력 실패")
            # ── 입력 결과 검증 — "보이면 누른다" 원칙: 입력된 값이 맞는지 확인 ─
            if miss_count == 0:
                if not self._verify_dial_field_ios(driver, phone_number):
                    print(f"  ⚠️ 다이얼 필드 검증 실패 — 잔류 번호 누적 가능성, 초기화 후 재발신 필요")
                    # 잘못된 번호로 발신하면 RINGING 미감지 → 필드 초기화 후 abort
                    self._clear_dial_field_ios(driver)
                    print(f"  ❌ 다이얼 필드 불일치로 발신 취소 (번호 누적)")
                    return False
            if miss_count > 0:
                print(f"  ❌ {MAX_DIAL_ATTEMPTS}회 시도 후에도 {miss_count}자리 입력 실패")
                if miss_count > len(phone_number) // 2:
                    print(f"  ❌ 과반수 이상 입력 실패 — 발신 불가, 키패드 상태 확인 필요")
                    return False

            print(f"✅ 전화번호 입력 완료\n")
            time.sleep(0.3)
            
            # "전화걸기" 버튼 — "보이면 누른다" (verify-then-act)
            # ⚠️ Apple 전화 앱: 발신 버튼의 name="응답", label="통화하기"
            #    탭바 "통화" 버튼(최근 통화 탭)과 혼동 주의
            #    익시오: name="전화걸기" 또는 "통화"
            print(f"☎️ 발신 중 (iPhone)...")
            call_ok = self._visible_tap_ios(
                driver,
                locators=[
                    (AppiumBy.ACCESSIBILITY_ID, "전화걸기"),
                    # 에이닷 전화: 탭바 '통화'(최근통화탭)와 구분 — XCUIElementTypeTabBar 밖에 있는 '통화' 버튼
                    (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="통화" and not(ancestor::XCUIElementTypeTabBar)]'),
                    (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="응답" and @label="통화하기"]'),
                    (AppiumBy.ACCESSIBILITY_ID, "통화하기"),
                    (AppiumBy.ACCESSIBILITY_ID, "발신"),
                    (AppiumBy.ACCESSIBILITY_ID, "Call"),
                    (AppiumBy.ACCESSIBILITY_ID, "call"),
                    (AppiumBy.ACCESSIBILITY_ID, "dialButton"),
                    (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="전화걸기" or @name="Call"]'),
                ],
                timeout=5.0,
                label='발신 버튼',
            )

            if call_ok:
                # ── 에이닷 전화: '통화' 버튼 후 확인 팝업 처리 ─────────────
                # 키패드에서 [통화] 클릭 시 "{번호}에 통화 연결" 팝업이 추가로 뜸
                if self._ios_bundle in self._ADOT_BUNDLES:
                    time.sleep(1.0)   # 팝업 렌더링 대기
                    import re as _re
                    # 전화번호를 하이픈 포맷으로 변환: 01031349844 → 010-3134-9844
                    def _fmt(num: str) -> str:
                        n = _re.sub(r'\D', '', num)
                        if len(n) == 11:
                            return f"{n[:3]}-{n[3:7]}-{n[7:]}"
                        if len(n) == 10:
                            return f"{n[:3]}-{n[3:6]}-{n[6:]}"
                        return num
                    popup_aid = f"{_fmt(phone_number)}에 통화 연결"
                    popup_ok = self._visible_tap_ios(
                        driver,
                        locators=[
                            (AppiumBy.ACCESSIBILITY_ID, popup_aid),
                            (AppiumBy.ACCESSIBILITY_ID, f"{phone_number}에 통화 연결"),
                            (AppiumBy.XPATH, '//XCUIElementTypeButton[contains(@name,"에 통화 연결")]'),
                        ],
                        timeout=4.0,
                        label='에이닷 통화 확인 팝업',
                    )
                    if popup_ok:
                        print(f"  ✅ 에이닷 통화 확인 팝업 처리 완료 ('{popup_aid}')")
                    else:
                        print(f"  ⚠️ 에이닷 통화 확인 팝업 미감지")
                print(f"✅ 발신 완료\n")
                return True
            else:
                print(f"❌ 발신 버튼을 찾을 수 없습니다. 현재 화면 source 출력:")
                try:
                    src = driver.page_source
                    import re as _re
                    btns = _re.findall(r'name=\"([^\"]+)\"[^/]*/>', src)
                    print(f"   발견된 요소: {btns[:20]}")
                except Exception:
                    pass
                print(f"💡 수동으로 발신 버튼을 눌러주세요.\n")
                time.sleep(5)
                return False
                
        except Exception as e:
            print(f"❌ 전화 걸기 실패: {e}\n")
            return False

    def _pre_call_ios_audio_setup(self):
        """[사전] 통화 발신 전 iOS 오디오 라우팅 사전 설정.

        WDA 세션 초기화 시 AVAudioSession이 초기화되는 문제를 완화.
        iRig 2 HD / USB Audio 어댑터가 연결된 상태에서
        WDA 세션을 통화앱 컨텍스트로 활성화하고 AVAudioSession을 playAndRecord로 설정.
        실패 시 조용히 무시 (wait_for_call_connecting_state 후 force_ios_external_mic이 보완).
        """
        ios_role = None
        for role, platform in [('speaker1', self.speaker1_platform), ('speaker2', self.speaker2_platform)]:
            if platform == 'iOS' and role in self.drivers:
                ios_role = role
                break
        if not ios_role:
            return

        wda_url = getattr(self, '_ios_wda_url', None)
        if not wda_url:
            return

        print(f"   [사전 라우팅] WDA로 iOS 오디오 세션 playAndRecord 설정 시도...")
        try:
            import requests as _req
            caps = {"capabilities": {"alwaysMatch": {
                "bundleId": self._ios_bundle,
                "platformName": "iOS",
                "shouldTerminateApp": False,
                "forceAppLaunch": False,
                "shouldWaitForQuiescence": False,
            }}}
            sr = _req.post(f"{wda_url}/session", json=caps, timeout=8)
            val = sr.json().get("value") or {}
            sid = val.get("sessionId") or sr.json().get("sessionId")
            if sid:
                # XCUITest: mobile:runXCUITest 비돕없이 execute_script로 AVAudioSession 활성화
                _req.post(f"{wda_url}/session/{sid}/execute/sync",
                          json={"script": "return mobile: setPreferredAudioInputPort", "args": [{"port": "BuiltInMic"}]},
                          timeout=4)
                _req.delete(f"{wda_url}/session/{sid}", timeout=4)
            print(f"   [사전 라우팅] 완료 (실패 시는 통화 연결 후 재시도)")
        except Exception as e:
            print(f"   [사전 라우팅] 무시됨: {e}")
    def force_ios_external_mic(self):
        """[비활성화됨] iRig HD2 시절 오디오 라우팅 코드 — CONNECT 6 환경에서는 불필요.

        이전에는 익시오 앱의 call_speaker_off/on_24 버튼을 탭해서
        iRig 2 HD / USB Audio로 강제 라우팅했으나,
        CONNECT 6 환경에서 스피커 버튼을 누르면 오히려 내장 스피커로 전환되어 MOS 저하.
        통화 연결 후에는 '보이는 전화' 팝업(_tap_video_call_popup)만 처리하면 됨.
        """
        print(f"   ℹ️ force_ios_external_mic: CONNECT 6 환경 — 스피커 버튼 탭 비활성화 (스킵)")

        # ── iOS 수화기 통화 볼륨 자동 설정 ──────────────────────────────
        try:
            from config import IOS_CALL_VOLUME as _vol_target
        except ImportError:
            _vol_target = None

        if _vol_target is not None:
            driver = self.drivers.get('speaker1')  # type: ignore[attr-defined]
            if driver:
                _MAX_STEPS = 16  # iPhone 통화 볼륨 최대 단계
                _target_steps = max(0, min(_MAX_STEPS, round(float(_vol_target) * _MAX_STEPS)))
                print(f"   🔊 iOS 통화 볼륨 설정: {float(_vol_target)*100:.0f}% ({_target_steps}/{_MAX_STEPS}단계)")
                try:
                    # 1) 최대로 올리기 (현재 레벨 불확실하므로)
                    for _ in range(_MAX_STEPS):
                        driver.execute_script('mobile: pressButton', {'name': 'volumeup'})
                        time.sleep(0.08)
                    # 2) 목표 단계만큼 내리기
                    _down = _MAX_STEPS - _target_steps
                    for _ in range(_down):
                        driver.execute_script('mobile: pressButton', {'name': 'volumedown'})
                        time.sleep(0.08)
                    print(f"   ✅ iOS 통화 볼륨 조정 완료 (↑{_MAX_STEPS}→↓{_down})")
                except Exception as _e:
                    print(f"   ⚠️ iOS 통화 볼륨 조정 실패: {_e}")
        return
