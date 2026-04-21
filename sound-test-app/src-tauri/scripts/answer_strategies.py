"""
수신 전략 Mixin — _answer_strategy_* 5종
IxioAutomatedTest에서 분리 (SRP: iOS/Android 수신 UI 전략 전담)
"""

import time

from appium.webdriver.common.appiumby import AppiumBy

try:
    from wda_auto_answer import WdaAnswerer
    _WDA_ANSWER_AVAILABLE = True
except ImportError:
    _WDA_ANSWER_AVAILABLE = False

try:
    from config import WDA_IP_OVERRIDE, WDA_PORT as _WDA_PORT
except ImportError:
    WDA_IP_OVERRIDE = None
    _WDA_PORT = 8100


class AnswerStrategiesMixin:
    """5단계 수신 전략을 담당하는 Mixin."""

    def _answer_strategy_answer_btn(self, driver) -> bool:
        """수신 전략 1: '응답' 접근성 버튼."""
        try:
            btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, "응답")
            if btn.is_displayed():
                print(f"  ✓ '응답' 버튼 발견")
                self._ios_answer_btn_clicked_at = time.time()  # 클릭 시각 = 00:00 기준
                btn.click()
                print(f"✅ 화자2: 전화 수신 완료 (응답)\n")
                time.sleep(2)
                return True
        except Exception:
            pass
        return False
    def _answer_strategy_lockscreen(self, driver) -> bool:
        """수신 전략 2: 잠금화면 알림 배너 → 패스코드 → 받기.

        비활성화: 알림을 잘못 건드려 수신 UI를 방해하는 문제 방지.
        """
        return False
        try:
            notification_btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, "알림")
            if not notification_btn.is_displayed():
                return False
            src = driver.page_source
            home_indicators = ['Home screen icons', 'Dock', 'App\xa0Store', 'Safari', 'Chrome', 'Page control']
            if any(ind in src for ind in home_indicators):
                print(f"  ℹ️ '알림' 발견됐으나 홈화면 → 잠금 해제 생략")
                return False
            print(f"  ✓ '알림' 버튼 발견 (잠금화면)")
            notification_btn.click()
            time.sleep(1.5)
            # 패스코드 키패드 확인
            try:
                driver.find_element(AppiumBy.ACCESSIBILITY_ID, "0")
                print(f"  ✓ 패스코드 키패드 → 000000 입력 중")
                for digit in ['0', '0', '0', '0', '0', '0']:
                    try:
                        driver.find_element(AppiumBy.ACCESSIBILITY_ID, digit).click()
                        time.sleep(0.3)
                    except Exception as e:
                        print(f"    ⚠️ 숫자 {digit} 입력 실패: {e}")
                time.sleep(1)
            except Exception:
                print(f"  ℹ️ 패스코드 키패드 없음")
            # 받기 버튼 ('AI 전화 대신 받기' 제외)
            try:
                recv_btns = driver.find_elements(AppiumBy.ACCESSIBILITY_ID, "받기")
                for recv_btn in recv_btns:
                    if not recv_btn.is_displayed():
                        continue
                    lbl = recv_btn.get_attribute('name') or recv_btn.get_attribute('label') or ''
                    if 'AI' in lbl or '대신' in lbl:
                        continue
                    self._ios_answer_btn_clicked_at = time.time()
                    recv_btn.click()
                    print(f"✅ 화자2: 전화 수신 완료 (알림→잠금해제→받기)\n")
                    time.sleep(2)
                    return True
            except Exception as e:
                print(f"    ⚠️ '받기' 버튼 클릭 실패: {e}")
        except Exception:
            pass
        return False
    def _answer_strategy_accept_btn(self, driver) -> bool:
        """수신 전략 3: 기본 '받기' 버튼 ('AI 전화 대신 받기' 제외)."""
        try:
            btns = driver.find_elements(AppiumBy.ACCESSIBILITY_ID, "받기")
            for btn in btns:
                if not btn.is_displayed():
                    continue
                lbl = btn.get_attribute('name') or btn.get_attribute('label') or ''
                if 'AI' in lbl or '대신' in lbl:
                    continue
                print(f"  ✓ '받기' 버튼 발견")
                self._ios_answer_btn_clicked_at = time.time()
                btn.click()
                print(f"✅ 화자2: 전화 수신 완료 (받기)\n")
                time.sleep(2)
                return True
        except Exception:
            pass
        return False

    def _answer_strategy_notification_banner(self, driver, start_time: float) -> bool:
        """수신 전략 3.5: 앱스토어 릴리스 — 알림 배너 탭 → 전체화면 진입 → 수신.

        비활성화: 알림을 잘못 건드려 수신 UI를 방해하는 문제 방지.

        스토어 앱에서는 수신 시 화면 상단에 '익시오 전화 수신 중' 알림 배너가 표시됨.
        이 배너를 탭해야 전체화면 통화 UI가 열리고, 거기서 통화 버튼을 누를 수 있음.

        GroundView 기준 배너 UI 요소:
          - Button  text: "지금, 공공이오, 익시오 전화 수신 중..."  (386x66, 배너 전체)
          - StaticText  name: "TextContent.Primary"  label: "익시오 전화 수신 중..."
            bounds: [72, 142, 305, 18]
        전체화면 수신 UI:
          - Button  name: "받기"  label: "받기"  bounds: [282, 720, 70, 70]
        """
        return False
        elapsed = time.time() - start_time
        if elapsed < 1 or elapsed > 25:
            return False  # 너무 이르거나 늦으면 스킵

        # ── 1단계: 접근성 ID / XPath로 배너 탐색 ──
        # iOS 알림 배너의 name 속성은 "TextContent.Primary" (label과 다름에 주의)
        banner_selectors = [
            (AppiumBy.ACCESSIBILITY_ID, "TextContent.Primary"),   # 실제 name 속성
            (AppiumBy.ACCESSIBILITY_ID, "익시오 전화 수신 중..."),  # label 매칭 시도
            (AppiumBy.ACCESSIBILITY_ID, "익시오 전화 수신 중"),
            (AppiumBy.ACCESSIBILITY_ID, "전화 수신 중"),
        ]
        banner_xpaths = [
            '//XCUIElementTypeButton[contains(@label,"전화 수신")]',       # 배너 버튼 직접
            '//XCUIElementTypeStaticText[contains(@label,"전화 수신")]',   # 배너 텍스트
            '//*[contains(@label,"전화 수신")]',                           # 모든 요소
            '//*[@name="TextContent.Primary"]',                            # name으로 검색
        ]

        banner_clicked = False

        # 접근성 ID 시도
        for by, selector in banner_selectors:
            try:
                el = driver.find_element(by, selector)
                if el.is_displayed():
                    # TextContent.Primary는 범용 name이므로 label 검증 필요
                    if selector == "TextContent.Primary":
                        lbl = el.get_attribute("label") or ""
                        if "전화" not in lbl and "수신" not in lbl:
                            continue  # 다른 앱 알림 — 스킵
                    print(f"  ✓ 알림 배너 발견: '{selector}' (label={el.get_attribute('label')})")
                    el.click()
                    banner_clicked = True
                    break
            except Exception:
                pass

        # XPath 시도
        if not banner_clicked:
            for xpath in banner_xpaths:
                try:
                    el = driver.find_element(AppiumBy.XPATH, xpath)
                    if el.is_displayed():
                        print(f"  ✓ 알림 배너 발견 (XPath): {xpath}")
                        el.click()
                        banner_clicked = True
                        break
                except Exception:
                    pass

        # ── 2단계: 접근성 실패 시 좌표 탭으로 배너 영역 터치 ──
        if not banner_clicked:
            # 화면 상단 알림 배너 영역 (iPhone 14/15 기준)
            # 실제 배너 bounds: y≈142 부근 (Dynamic Island 아래)
            banner_coords = [
                (195, 140),   # 배너 중앙 영역
                (195, 155),   # 배너 하단 영역
                (195, 120),   # 배너 상단 영역
                (195, 170),   # 배너 아래쪽
            ]
            for bx, by in banner_coords:
                try:
                    driver.execute_script("mobile: tap", {"x": bx, "y": by})
                    print(f"  📲 알림 배너 좌표 탭 ({bx}, {by})")
                    time.sleep(1.0)
                    # 전체화면 전환 확인
                    try:
                        src = driver.page_source
                        if any(kw in src for kw in ["응답", "받기", "수락", "거절"]):
                            banner_clicked = True
                            print(f"  ✓ 전체화면 통화 UI 진입 확인")
                            break
                    except Exception:
                        pass
                except Exception:
                    pass

        if not banner_clicked:
            return False

        # ── 3단계: 전체화면 통화 UI에서 수신 버튼 탭 ──
        time.sleep(1.5)  # 전체화면 전환 대기
        answer_labels = ["받기", "응답", "수락", "Accept", "Answer"]
        for aid in answer_labels:
            try:
                btns = driver.find_elements(AppiumBy.ACCESSIBILITY_ID, aid)
                for btn in btns:
                    if not btn.is_displayed():
                        continue
                    lbl = btn.get_attribute('name') or btn.get_attribute('label') or ''
                    if 'AI' in lbl or '대신' in lbl:
                        continue
                    self._ios_answer_btn_clicked_at = time.time()
                    btn.click()
                    print(f"✅ 화자2: 전화 수신 완료 (배너→{aid})\n")
                    time.sleep(2)
                    return True
            except Exception:
                pass

        # 버튼 못 찾으면 하단 좌표 탭 시도 (전체화면 통화 UI '받기' 버튼 위치)
        # 실제 '받기' 버튼 bounds: [282, 720, 70, 70] → center (317, 755)
        fullscreen_coords = [(317, 755), (290, 720), (195, 720), (195, 680)]
        for tx, ty in fullscreen_coords:
            try:
                self._ios_answer_btn_clicked_at = time.time()
                driver.execute_script("mobile: tap", {"x": tx, "y": ty})
                time.sleep(1.0)
                try:
                    src = driver.page_source
                    if any(kw in src for kw in ["종료", "End", "음소거", "Mute"]):
                        print(f"✅ 화자2: 전화 수신 완료 (배너→좌표탭 {tx},{ty})\n")
                        return True
                except Exception:
                    pass
            except Exception:
                pass

        return False

    def _answer_strategy_coordinate_tap(self, driver, start_time: float) -> bool:
        """수신 전략 4: accessible=false 하이브리드 앱 대응 — 좌표 탭."""
        elapsed = time.time() - start_time
        if elapsed < 3:
            return False
        # 익시오 '받기' 버튼 bounds: [282, 720, 70, 70] → center (317, 755)
        tap_candidates = [(317, 755), (290, 720), (195, 720), (195, 680)]
        for tx, ty in tap_candidates:
            try:
                self._ios_answer_btn_clicked_at = time.time()  # 클릭 시각 = 00:00 기준
                driver.execute_script("mobile: tap", {"x": tx, "y": ty})
                time.sleep(0.8)
                try:
                    src = driver.page_source
                    if any(kw in src for kw in ["종료", "End", "음소거", "Mute"]):
                        print(f"✅ 화자2: 전화 수신 완료 (좌표 탭 {tx},{ty})\n")
                        return True
                except Exception:
                    pass
            except Exception:
                pass
        return False
    def _answer_strategy_wda_fallback(self, max_wait_time: int) -> bool:
        """수신 전략 5 (fallback): WDA 직접 호출."""
        if not _WDA_ANSWER_AVAILABLE:
            print(f"⚠️ wda_auto_answer 모듈 없음 (wda_auto_answer.py 확인)")
            return False
        if WDA_IP_OVERRIDE:
            wda_url = f"http://{WDA_IP_OVERRIDE}:{_WDA_PORT}"
            print(f"\n  📌 config.py WDA_IP_OVERRIDE 사용: {wda_url}")
        elif self._ios_wda_url:
            wda_url = self._ios_wda_url
        elif getattr(self.wda_manager, '_cached_iphone_ip', None):
            wda_url = f"http://{self.wda_manager._cached_iphone_ip}:{_WDA_PORT}"
        else:
            wda_url = None
        print(f"\n🔄 WDA 직접 수신 시도 (url={wda_url or '자동스캔'})")
        try:
            answerer = WdaAnswerer(wda_url)
            ok = answerer.wait_and_answer(timeout=max_wait_time, poll=1.0)
            self._ios_wda_url = answerer.wda
            answerer.close()
            if ok:
                print(f"✅ 화자2: WDA 직접 수신 완료\n")
                # WDA fallback은 클릭 시각 추정이 어려우므로 완료 시각 사용
                self._ios_answer_btn_clicked_at = time.time()
                time.sleep(2)
                return True
        except Exception as e:
            print(f"⚠️ WDA fallback 실패: {e}")
        return False
