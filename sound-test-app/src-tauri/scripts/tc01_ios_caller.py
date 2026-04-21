"""
tc01_ios_caller.py
────────────────────────────────────────────────────────────────────────────
TC_01 — 일반 통화 테스트 | iOS 발신단 Appium 스크립트

시나리오:
  1. 익시오 앱 실행 → [키패드] 탭 진입
  2. 전화번호 입력 → [통화] 버튼으로 발신
  3. 통화 중 임의 시점에 스크린샷 ① (통화 종료 버튼이 있는 화면)
  4. "통화를 종료했어요" 화면 대기 → 스크린샷 ②
  5. [최근 기록] 버튼 → 오늘 첫 번째 항목 선택 → [통화 요약] → 스크린샷 ③

반환값:
  Tc01IosCallerResult(dataclass)
    .screenshots   : list[str]   — 저장된 PNG 절대 경로 목록 (최대 3개)
    .call_ended    : bool        — "통화를 종료했어요" 화면 감지 여부
    .summary_shown : bool        — 통화 요약 화면 진입 여부
    .error         : str | None  — 실패 원인 (정상이면 None)

CLI 사용 (단독 실행):
  python tc01_ios_caller.py \\
      --udid 00008101-XXXX \\
      --number 01012345678 \\
      --appium-url http://127.0.0.1:4724
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from appium import webdriver
from appium.options.ios import XCUITestOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# ── 상수 ───────────────────────────────────────────────────────────────────────
BUNDLE_ID              = 'com.lguplus.aicallagent'
CALL_ENDED_LABEL       = '통화를 종료했어요'
RECENT_LOG_LABEL       = '최근 기록'
CALL_SUMMARY_LABEL     = '통화 요약'
TODAY_LABEL            = '오늘'
DEFAULT_APPIUM_URL     = 'http://127.0.0.1:4724'
DEFAULT_SCREENSHOT_DIR = str(Path.home() / 'Documents' / 'sound' / 'audio_files' / 'screenshots')

# 키패드 탭 접근성 ID 후보
_KEYPAD_TAB_IDS = ['키패드', 'Keypad', 'dialpad', 'dial_pad']
# 발신 버튼 접근성 ID 후보
_CALL_BTN_IDS   = ['통화', '전화걸기', '통화하기', '발신', 'Call', 'call', 'dialButton']
# 시스템 알림 닫기 버튼
_ALERT_DISMISS  = ['아니요', '나중에', '무시', '취소', "Don't Allow", 'Cancel', 'Not Now']


# ── 결과 ───────────────────────────────────────────────────────────────────────
@dataclass
class Tc01IosCallerResult:
    screenshots:   list[str] = field(default_factory=list)
    call_ended:    bool      = False
    summary_shown: bool      = False
    error:         Optional[str] = None


# ── 내부 유틸 ──────────────────────────────────────────────────────────────────

def _dismiss_alerts(driver) -> None:
    """화면에 떠 있는 iOS 시스템 알림(iMessage/FaceTime 등)을 닫습니다."""
    try:
        driver.switch_to.alert.dismiss()
        time.sleep(0.4)
    except Exception:
        pass
    for aid in _ALERT_DISMISS:
        try:
            driver.find_element(AppiumBy.ACCESSIBILITY_ID, aid).click()
            time.sleep(0.3)
        except Exception:
            pass


def _find_any(driver, aids: list[str], timeout: float = 0):
    """aid 목록 중 찾을 수 있는 첫 번째 요소를 반환합니다. 없으면 None."""
    deadline = time.time() + max(timeout, 0)
    while True:
        for aid in aids:
            try:
                return driver.find_element(AppiumBy.ACCESSIBILITY_ID, aid)
            except Exception:
                pass
        if time.time() >= deadline:
            return None
        time.sleep(0.2)


def _keypad_digits_present(driver) -> bool:
    """'1', '2', '3' 버튼이 모두 있으면 키패드 화면으로 판정합니다."""
    for d in ('1', '2', '3'):
        try:
            driver.find_element(AppiumBy.ACCESSIBILITY_ID, d)
        except Exception:
            return False
    return True


def _wait_keypad(driver, timeout: float = 8.0) -> bool:
    """키패드 화면이 나타날 때까지 최대 timeout초 대기합니다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _keypad_digits_present(driver):
            return True
        time.sleep(0.3)
    return False


def _save_screenshot(driver, tag: str, out_dir: str) -> Optional[str]:
    """스크린샷을 PNG로 저장하고 절대 경로를 반환합니다."""
    # 날짜별 하위 폴더 (YYYY-MM-DD)
    date_dir = Path(out_dir) / datetime.now().strftime('%Y-%m-%d')
    date_dir.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:21]
    path = str(date_dir / f'tc01_ios_{tag}_{ts}.png')
    try:
        driver.save_screenshot(path)
        print(f'  📸 스크린샷 저장: {path}')
        return path
    except Exception as e:
        print(f'  ⚠️ 스크린샷 실패 ({tag}): {e}')
        return None


# ── 핵심 로직 ──────────────────────────────────────────────────────────────────

class Tc01IosCaller:
    """TC_01 iOS 발신단 시나리오 실행기.

    외부에서 Appium driver를 전달받거나, run() 호출 시 내부적으로 생성할 수 있습니다.
    IxioAutomatedTest.run() 과 통합할 때는 driver를 전달해 사용하세요.
    """

    def __init__(
        self,
        udid: str,
        phone_number: str,
        appium_url: str = DEFAULT_APPIUM_URL,
        screenshot_dir: str = DEFAULT_SCREENSHOT_DIR,
        driver=None,                      # 외부에서 이미 연결된 driver 전달 시
        call_ended_timeout: float = 120,  # "통화를 종료했어요" 대기 최대 시간(초)
    ):
        self.udid                = udid
        self.phone_number        = phone_number
        self.appium_url          = appium_url
        self.screenshot_dir      = screenshot_dir
        self._ext_driver         = driver
        self.call_ended_timeout  = call_ended_timeout
        self._driver             = None
        self._result             = Tc01IosCallerResult()

    # ── 공개 API ────────────────────────────────────────────────────────────

    def run(self) -> Tc01IosCallerResult:
        """TC_01 전체 시나리오 실행 후 결과 반환."""
        owned = self._ext_driver is None
        try:
            self._driver = self._ext_driver or self._connect()
            self._step1_open_keypad()
            self._step2_dial_and_call()
            self._step3_screenshot_in_call()
            self._step4_wait_call_ended()
            self._step5_recent_log_and_summary()
        except Exception as e:
            self._result.error = str(e)
            print(f'❌ [TC_01 iOS] 오류: {e}')
        finally:
            if owned and self._driver:
                try:
                    self._driver.quit()
                except Exception:
                    pass
        return self._result

    # ── 내부 단계 ────────────────────────────────────────────────────────────

    def _connect(self):
        """Appium iOS 드라이버 신규 연결."""
        print(f'🔌 [TC_01 iOS] Appium 연결 중 ({self.appium_url}) ...')
        opts = XCUITestOptions()
        opts.udid                       = self.udid
        opts.bundle_id                  = BUNDLE_ID
        opts.automation_name            = 'XCUITest'
        opts.no_reset                   = True
        opts.new_command_timeout        = 300
        opts.set_capability('shouldTerminateApp', False)
        opts.set_capability('forceAppLaunch',     True)
        opts.set_capability('shouldWaitForQuiescence', False)
        driver = webdriver.Remote(self.appium_url, options=opts)
        print(f'  ✅ 드라이버 연결 완료')
        return driver

    def _step1_open_keypad(self) -> None:
        """Step 1: 익시오 앱 실행 → 키패드 탭 진입."""
        driver = self._driver
        print(f'\n[Step 1] 익시오 앱 키패드 탭 진입')

        # 앱 재시작 (잔류 번호 초기화)
        try:
            driver.terminate_app(BUNDLE_ID)
            print(f'  ✓ 앱 종료')
        except Exception:
            pass
        time.sleep(0.8)

        try:
            driver.activate_app(BUNDLE_ID)
            print(f'  ✓ 앱 실행')
        except Exception as e:
            raise RuntimeError(f'앱 실행 실패: {e}')

        # 시스템 알림 닫기
        _dismiss_alerts(driver)

        # 이미 키패드면 바로 진행
        if _wait_keypad(driver, timeout=5.0):
            print(f'  ✅ 키패드 화면 진입 완료')
            return

        # 키패드 탭 클릭 시도
        tab = _find_any(driver, _KEYPAD_TAB_IDS, timeout=3.0)
        if tab:
            tab.click()
            if _wait_keypad(driver, timeout=5.0):
                print(f'  ✅ 키패드 탭 클릭으로 진입')
                return

        # 실패 → 앱 재시작 1회 더
        print(f'  🔄 키패드 진입 실패 → 앱 재시작 재시도')
        try:
            driver.terminate_app(BUNDLE_ID)
            time.sleep(1.2)
            driver.activate_app(BUNDLE_ID)
        except Exception:
            pass
        _dismiss_alerts(driver)
        tab = _find_any(driver, _KEYPAD_TAB_IDS, timeout=5.0)
        if tab:
            tab.click()
        if not _wait_keypad(driver, timeout=7.0):
            # 최후 수단: 진단 출력 + 수동 대기
            try:
                labels = re.findall(r'(?:name|label)="([^"]+)"', driver.page_source)
                print(f'  [진단] 현재 화면: {sorted(set(labels))[:20]}')
            except Exception:
                pass
            print(f'  💡 수동으로 키패드 탭을 열어주세요. (8초 대기)')
            time.sleep(8)

    def _step2_dial_and_call(self) -> None:
        """Step 2: 전화번호 입력 → 통화 버튼 클릭."""
        driver = self._driver
        print(f'\n[Step 2] 전화번호 입력 및 발신: {self.phone_number}')

        _dismiss_alerts(driver)

        # 키패드 완전 로드 대기
        time.sleep(0.8)

        # 숫자 버튼 캐싱 (탭바 제외 XPath 우선)
        def _find_digit(d: str):
            try:
                return driver.find_element(AppiumBy.ACCESSIBILITY_ID, d)
            except Exception:
                pass
            for xp in [
                f'//XCUIElementTypeButton[not(ancestor::XCUIElementTypeTabBar) and @label="{d}"]',
                f'//XCUIElementTypeKey[@label="{d}"]',
                f'//*[not(ancestor::XCUIElementTypeTabBar) and @label="{d}"]',
            ]:
                try:
                    return driver.find_element(AppiumBy.XPATH, xp)
                except Exception:
                    pass
            return None

        digit_map: dict[str, object] = {}
        for d in set(self.phone_number):
            btn = _find_digit(d)
            if btn is not None:
                digit_map[d] = btn

        # 캐싱 실패 시 키패드 재진입
        if not digit_map:
            print(f'  ⚠️ 숫자 버튼 캐싱 실패 → 키패드 탭 재시도')
            tab = _find_any(driver, _KEYPAD_TAB_IDS, timeout=3.0)
            if tab:
                tab.click()
                time.sleep(0.8)
            for d in set(self.phone_number):
                btn = _find_digit(d)
                if btn is not None:
                    digit_map[d] = btn

        # 번호 입력 (클릭 사이 50ms — iOS UIKit 입력 등록 보장)
        miss = 0
        for i, ch in enumerate(self.phone_number):
            btn = digit_map.get(ch)
            if btn is None:
                btn = _find_digit(ch)
            if btn is None:
                print(f'  ⚠️ 버튼 "{ch}" 없음 → 스킵 ({i+1}/{len(self.phone_number)})')
                miss += 1
                continue
            try:
                btn.click()
            except Exception:
                btn = _find_digit(ch)
                if btn:
                    btn.click()
                else:
                    miss += 1
                    continue
            time.sleep(0.05)  # iOS 입력 등록 대기

        if miss:
            print(f'  ⚠️ {miss}/{len(self.phone_number)}자리 입력 실패')
        print(f'  ✅ 전화번호 입력 완료')
        time.sleep(0.3)

        # 발신 버튼 클릭
        call_btn = _find_any(driver, _CALL_BTN_IDS)
        if call_btn is None:
            # XPath fallback: 키패드 하단 녹색 원형 버튼 계열
            xpaths = [
                '//XCUIElementTypeButton[@name="통화" or @name="전화걸기" or @name="Call"]',
                '//XCUIElementTypeButton[contains(@name,"통화")]',
            ]
            for xp in xpaths:
                try:
                    call_btn = driver.find_element(AppiumBy.XPATH, xp)
                    break
                except Exception:
                    pass

        if call_btn:
            call_btn.click()
            print(f'  ✅ 발신 완료')
        else:
            try:
                labels = re.findall(r'name="([^"]+)"', driver.page_source)
                print(f'  [진단] 화면 요소: {labels[:20]}')
            except Exception:
                pass
            print(f'  💡 수동으로 통화 버튼을 눌러주세요. (5초 대기)')
            time.sleep(5)

    def _step3_screenshot_in_call(self) -> None:
        """Step 3: 통화 중 스크린샷 ① (통화 종료 버튼이 있는 화면)."""
        driver = self._driver
        print(f'\n[Step 3] 통화 중 스크린샷 대기')

        # "끊기" 버튼이 나타날 때까지 최대 60초 대기
        deadline = time.time() + 60.0
        captured = False
        while time.time() < deadline:
            try:
                src = driver.page_source
                has_end_btn = any(
                    f'name="{k}"' in src or f'label="{k}"' in src
                    for k in ('끊기', 'End', '통화 종료')
                )
                has_timer = bool(re.search(r'\b\d{1,2}:\d{2}\b', src))
                if has_end_btn and has_timer:
                    path = _save_screenshot(driver, '01_in_call', self.screenshot_dir)
                    if path:
                        self._result.screenshots.append(path)
                    print(f'  ✅ 통화 중 스크린샷 완료')
                    captured = True
                    break
            except Exception:
                pass
            time.sleep(1.0)

        if not captured:
            print(f'  ⚠️ 통화 중 화면 감지 실패 — 강제 스크린샷')
            path = _save_screenshot(driver, '01_in_call_force', self.screenshot_dir)
            if path:
                self._result.screenshots.append(path)

    def _step4_wait_call_ended(self) -> None:
        """Step 4: "통화를 종료했어요" 화면 대기 → 스크린샷 ②."""
        driver = self._driver
        print(f'\n[Step 4] 통화 종료 감지 대기 (최대 {self.call_ended_timeout:.0f}초)')

        deadline = time.time() + self.call_ended_timeout
        found    = False
        while time.time() < deadline:
            try:
                driver.find_element(AppiumBy.ACCESSIBILITY_ID, CALL_ENDED_LABEL)
                found = True
                break
            except Exception:
                pass
            # 수신단(Android)이 통화를 종료하면 iOS에도 종료 화면이 표시됨
            # page_source 텍스트 검색으로 보완
            try:
                if CALL_ENDED_LABEL in driver.page_source:
                    found = True
                    break
            except Exception:
                pass
            time.sleep(0.8)

        if found:
            print(f'  ✅ 통화 종료 화면 감지: "{CALL_ENDED_LABEL}"')
            # 화면 안정화 대기
            time.sleep(0.5)
            path = _save_screenshot(driver, '02_call_ended', self.screenshot_dir)
            if path:
                self._result.screenshots.append(path)
            self._result.call_ended = True
        else:
            print(f'  ⚠️ {self.call_ended_timeout:.0f}초 내 종료 화면 미감지 — 강제 스크린샷')
            path = _save_screenshot(driver, '02_call_ended_force', self.screenshot_dir)
            if path:
                self._result.screenshots.append(path)

    def _step5_recent_log_and_summary(self) -> None:
        """Step 5: [최근 기록] → 오늘 첫 번째 항목 → [통화 요약] → 스크린샷 ③."""
        driver = self._driver
        print(f'\n[Step 5] 통화 요약 화면 진입')

        # ── 5-1. [최근 기록] 버튼 ──────────────────────────────────────────
        recent_btn = _find_any(driver, [RECENT_LOG_LABEL], timeout=8.0)
        if recent_btn is None:
            # XPath fallback
            try:
                recent_btn = driver.find_element(
                    AppiumBy.XPATH,
                    f'//XCUIElementTypeButton[contains(@name,"{RECENT_LOG_LABEL}")]',
                )
            except Exception:
                pass
        if recent_btn is None:
            print(f'  ⚠️ [최근 기록] 버튼을 찾지 못했습니다.')
            return
        recent_btn.click()
        print(f'  ✓ [최근 기록] 클릭')
        time.sleep(1.5)

        # ── 5-2. [오늘] 문구 바로 아래 첫 번째 항목 선택 ─────────────────
        # [오늘] 텍스트 요소를 찾아 그 다음 형제/인접 요소를 선택합니다.
        # XCUIElementTypeStaticText  name="오늘" 기준으로 뒤에 오는 첫 cell 클릭
        first_item = self._find_first_item_after_today(driver)
        if first_item is None:
            print(f'  ⚠️ [오늘] 이후 통화 항목을 찾지 못했습니다.')
            return
        first_item.click()
        print(f'  ✓ 오늘 이후 첫 번째 항목 클릭')
        time.sleep(1.0)

        # ── 5-3. [통화 요약] 버튼 ──────────────────────────────────────────
        summary_btn = _find_any(driver, [CALL_SUMMARY_LABEL], timeout=5.0)
        if summary_btn is None:
            try:
                summary_btn = driver.find_element(
                    AppiumBy.XPATH,
                    f'//*[contains(@name,"{CALL_SUMMARY_LABEL}") or contains(@label,"{CALL_SUMMARY_LABEL}")]',
                )
            except Exception:
                pass
        if summary_btn is None:
            print(f'  ⚠️ [통화 요약] 버튼을 찾지 못했습니다.')
            # 현재 화면 진단
            try:
                labels = re.findall(r'(?:name|label)="([^"]+)"', driver.page_source)
                print(f'  [진단] 현재 화면: {sorted(set(labels))[:20]}')
            except Exception:
                pass
            return
        summary_btn.click()
        print(f'  ✓ [통화 요약] 클릭')
        time.sleep(1.5)  # 요약 화면 로딩 대기

        # ── 5-4. 통화 요약 스크린샷 ③ ────────────────────────────────────
        path = _save_screenshot(driver, '03_call_summary', self.screenshot_dir)
        if path:
            self._result.screenshots.append(path)
        self._result.summary_shown = True
        print(f'  ✅ 통화 요약 스크린샷 완료')

    def _find_first_item_after_today(self, driver):
        """[오늘] 레이블 직후 나타나는 첫 번째 통화 항목 요소를 반환합니다.

        전략:
          ① XCUIElementTypeTable 내 섹션 헤더("오늘") 다음 셀 (가장 정확)
          ② [오늘] StaticText 의 y좌표보다 큰 가장 첫 번째 전화번호 형식 요소
          ③ page_source XML 파싱으로 "오늘" 직후 XCUIElementTypeCell 탐색
        """
        # ── 전략 ①: XCUIElementTypeCell + y좌표 기반 ──────────────────────
        try:
            today_el = driver.find_element(
                AppiumBy.XPATH,
                '//XCUIElementTypeStaticText[@name="오늘" or @label="오늘"]',
            )
            today_y = today_el.location.get('y', 0)

            # "오늘"보다 y 좌표가 큰 첫 번째 행 (셀 또는 버튼)
            candidates = driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeCell | //XCUIElementTypeButton[contains(@name,"-")]',
            )
            for el in candidates:
                try:
                    if el.location.get('y', 0) > today_y:
                        return el
                except Exception:
                    pass
        except Exception:
            pass

        # ── 전략 ②: page_source XML 파싱 ─────────────────────────────────
        try:
            src = driver.page_source
            root = __import__('xml.etree.ElementTree', fromlist=['ElementTree']).fromstring(src)
            today_found = False
            for el in root.iter():
                if not today_found:
                    nm = el.get('name', '') or el.get('label', '')
                    if nm == TODAY_LABEL:
                        today_found = True
                    continue
                # 오늘 이후 요소 — 전화번호 패턴(숫자-숫자)이 있거나 XCUIElementTypeCell
                nm = el.get('name', '') or el.get('label', '')
                if re.search(r'\d{3,4}[-–]\d{3,4}', nm) or el.tag == 'XCUIElementTypeCell':
                    # 접근성 ID 또는 XPath로 실제 요소 탐색
                    if nm:
                        try:
                            return driver.find_element(AppiumBy.ACCESSIBILITY_ID, nm)
                        except Exception:
                            pass
        except Exception:
            pass

        # ── 전략 ③: 첫 번째 XCUIElementTypeCell fallback ─────────────────
        try:
            cells = driver.find_elements(AppiumBy.XPATH, '//XCUIElementTypeCell')
            if cells:
                return cells[0]
        except Exception:
            pass

        return None


# ── CLI 진입점 ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='TC_01 iOS 발신단 Appium 스크립트'
    )
    parser.add_argument('--udid',        required=True, help='iOS 디바이스 UDID')
    parser.add_argument('--number',      required=True, help='발신 전화번호 (예: 01012345678)')
    parser.add_argument('--appium-url',  default=DEFAULT_APPIUM_URL, help='Appium 서버 URL')
    parser.add_argument('--screenshot-dir', default=DEFAULT_SCREENSHOT_DIR, help='스크린샷 저장 경로')
    parser.add_argument('--call-ended-timeout', type=float, default=120,
                        help='통화 종료 화면 대기 최대 시간 (초, 기본 120)')
    args = parser.parse_args()

    caller = Tc01IosCaller(
        udid=args.udid,
        phone_number=args.number,
        appium_url=args.appium_url,
        screenshot_dir=args.screenshot_dir,
        call_ended_timeout=args.call_ended_timeout,
    )
    result = caller.run()

    print(f'\n{"="*60}')
    print(f'TC_01 iOS 발신단 결과')
    print(f'{"="*60}')
    print(f'  통화 종료 감지:  {"✅" if result.call_ended    else "❌"}')
    print(f'  통화 요약 확인:  {"✅" if result.summary_shown else "❌"}')
    print(f'  스크린샷 ({len(result.screenshots)}개):')
    for p in result.screenshots:
        print(f'    {p}')
    if result.error:
        print(f'  오류: {result.error}')
    print(f'{"="*60}\n')

    import sys
    sys.exit(0 if result.call_ended else 1)


if __name__ == '__main__':
    main()
