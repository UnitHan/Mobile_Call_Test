"""
Android 통화 처리 Mixin — open_ixio_keypad, make_call
IxioAutomatedTest에서 분리 (SRP: Android 플랫폼 통화 UI 조작 전담)
"""

import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class AndroidCallHandlerMixin:
    """Android 통화 앱 키패드 오픈·발신을 담당하는 Mixin."""

    _IXIO_PKG = 'com.lguplus.aicallagent'  # 레거시 폴백 (인스턴스 속성 우선)
    _android_api_cache: dict[str, int] = {}         # udid → API level
    _getprop_available: dict[str, bool] = {}         # udid → gsm.call.state 사용 가능 여부

    # ── 앱별 수신 화면 판별 패턴 ────────────────────────────────────────────
    # key: android_app_package, value: {header_keywords, incoming_pkgs, settle_sec}
    #   header_keywords: dumpsys activity top 또는 UI에서 수신 화면 판별 키워드
    #   incoming_pkgs:   수신 화면에 표시되는 별도 패키지 (VoIP 앱만 해당)
    #   settle_sec:      RINGING 감지 후 UI 안정화 대기 시간 (초)
    #                    익시오는 'AI 전화 대신 받기' UI 방지를 위해 5초 필요
    #                    일반 전화 앱은 즉시 수신 수락 가능 (0초)
    ANDROID_INCOMING_PATTERNS = {
        'com.lguplus.aicallagent': {
            'header_keywords': ['익시오 음성통화', '익시오 전화'],
            'incoming_pkgs': ['com.lguplus.incomingcall'],
            'settle_sec': 5.0,
        },
        'com.samsung.android.dialer': {
            'header_keywords': ['Voice 수신전화', 'UHD Voice', '수신전화'],
            'incoming_pkgs': ['com.samsung.android.incallui'],
            'settle_sec': 0.0,
        },
        'com.skt.prod.dialer': {
            'header_keywords': ['에이닷', 'T전화', '수신전화'],
            'incoming_pkgs': ['com.skt.prod.dialer'],
            'settle_sec': 0.0,
        },
    }
    # 모든 앱 공통 수신 UI 패키지
    _COMMON_INCOMING_PKGS = ['com.android.incallui']

    @property
    def _android_pkg(self) -> str:
        """현재 테스트 대상 Android 앱 패키지명. IxioAutomatedTest에서 설정."""
        return getattr(self, 'android_app_package', self._IXIO_PKG)

    @property
    def _incoming_pattern(self) -> dict:
        """현재 테스트 대상 앱의 수신 화면 패턴."""
        pkg = self._android_pkg
        return self.ANDROID_INCOMING_PATTERNS.get(pkg, {
            'header_keywords': ['수신전화', '수신 전화'],
            'incoming_pkgs': [],
            'settle_sec': 1.0,
        })

    @property
    def _all_incoming_pkgs(self) -> list[str]:
        """수신 화면 감지에 사용할 패키지명 전체 목록."""
        pattern = self._incoming_pattern
        return pattern.get('incoming_pkgs', []) + self._COMMON_INCOMING_PKGS

    @classmethod
    def _get_android_api(cls, udid: str) -> int:
        """Android API 레벨을 캐시하여 반환합니다."""
        if udid not in cls._android_api_cache:
            try:
                v = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'getprop', 'ro.build.version.sdk'],
                    capture_output=True, text=True, timeout=3
                ).stdout.strip()
                cls._android_api_cache[udid] = int(v) if v.isdigit() else 0
            except Exception:
                cls._android_api_cache[udid] = 0
        return cls._android_api_cache[udid]

    def _clear_dial_field_android(self, driver) -> None:
        """Android 키패드 다이얼 필드에 잔류 번호가 있으면 삭제 버튼으로 모두 지웁니다.

        이전 테스트 실패 시 번호가 남아 오발신되는 문제 방지.
        최대 5자리까지 삭제 시도 (앱 재시작 후이므로 잔류가 적음).
        """
        _pkg = self._android_pkg
        delete_selectors = [
            'new UiSelector().description("삭제")',
            'new UiSelector().description("지우기")',
            'new UiSelector().description("Delete")',
            f'new UiSelector().resourceId("{_pkg}:id/deleteButton")',
            f'new UiSelector().resourceId("{_pkg}:id/btn_delete")',
        ]
        cleared = False
        for _ in range(5):
            deleted_once = False
            for sel in delete_selectors:
                try:
                    btn = driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, sel)
                    btn.click()
                    time.sleep(0.3)
                    deleted_once = True
                    cleared = True
                    break
                except Exception as _e:
                    _msg = str(_e)
                    if 'instrumentation' in _msg or 'not running' in _msg:
                        return  # UiAutomator2 죽음 → 즉시 중단
            if not deleted_once:
                break
        if cleared:
            print(f"  ✓ Android 키패드 잔류 번호 삭제 완료")

    def _adb_input_remaining(self, remaining: str, start_idx: int, total: int):
        """ADB keyevent로 남은 전화번호 숫자를 입력합니다.

        Wi-Fi ADB 연결 불안정 대응: timeout=10s, 실패 시 재시도 1회.
        """
        udid = getattr(self, 'speaker1_device', None)
        if not udid:
            print("    ⚠️ speaker1_device 없음 → ADB 입력 불가")
            return
        print(f"    ⚠️ Appium 버튼 미발견 → ADB keyevent 전환")
        print(f"    🔧 ADB 직접 입력 (남은 번호: {remaining})")
        for ri, rd in enumerate(remaining):
            if rd in '0123456789':
                keycode = 7 + int(rd)  # KEYCODE_0=7, KEYCODE_1=8, ...
                ok = False
                for _try in range(2):  # 최대 2회 시도 (Wi-Fi ADB 불안정 대비)
                    try:
                        subprocess.run(
                            ['adb', '-s', udid, 'shell', 'input', 'keyevent', str(keycode)],
                            capture_output=True, text=True, timeout=10
                        )
                        print(f"    ✓ {rd} ADB 입력 성공 ({start_idx+ri+1}/{total})")
                        time.sleep(0.3)
                        ok = True
                        break
                    except subprocess.TimeoutExpired:
                        if _try == 0:
                            print(f"    ⚠️ {rd} ADB 타임아웃 → 재시도")
                            time.sleep(1)
                        else:
                            print(f"    ❌ {rd} ADB 입력 실패: 타임아웃 (10초×2회)")
                    except Exception as ae:
                        print(f"    ❌ {rd} ADB 입력 실패: {ae}")
                        break

    def _tap_element_adb(self, udid: str, content_desc: str) -> bool:
        """ADB uiautomator dump로 content-desc가 일치하는 요소를 찾아 탭.

        UiAutomator2 크래시 시 폴백으로 사용.
        Returns True if tapped successfully.
        """
        try:
            subprocess.run(
                ['adb', '-s', udid, 'shell', 'uiautomator', 'dump', '/sdcard/ui_dump.xml'],
                capture_output=True, text=True, timeout=10
            )
            r = subprocess.run(
                ['adb', '-s', udid, 'shell', 'cat', '/sdcard/ui_dump.xml'],
                capture_output=True, text=True, timeout=5
            )
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.stdout)
            for node in root.iter('node'):
                desc = node.get('content-desc', '')
                text = node.get('text', '')
                if content_desc in desc or content_desc in text:
                    bounds = node.get('bounds', '')
                    # bounds="[x1,y1][x2,y2]" 형식 파싱
                    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                    if m:
                        cx = (int(m.group(1)) + int(m.group(3))) // 2
                        cy = (int(m.group(2)) + int(m.group(4))) // 2
                        subprocess.run(
                            ['adb', '-s', udid, 'shell', 'input', 'tap', str(cx), str(cy)],
                            capture_output=True, timeout=5
                        )
                        print(f"  ✓ ADB 폴백 탭: '{content_desc}' → ({cx}, {cy})")
                        time.sleep(1)
                        return True
            print(f"  ⚠️ ADB dump에서 '{content_desc}' 미발견")
        except Exception as e:
            print(f"  ⚠️ ADB 폴백 탭 실패: {e}")
        return False

    # ── verify-then-act 헬퍼: "보이면 누른다" ─────────────────────────

    def _adb_dump_ui(self, udid: str):
        """ADB uiautomator dump로 현재 화면 UI 트리를 반환합니다.

        Returns ET.Element (root) or None.
        """
        try:
            subprocess.run(
                ['adb', '-s', udid, 'shell', 'uiautomator', 'dump', '/sdcard/ui_dump.xml'],
                capture_output=True, text=True, timeout=10
            )
            r = subprocess.run(
                ['adb', '-s', udid, 'shell', 'cat', '/sdcard/ui_dump.xml'],
                capture_output=True, text=True, timeout=5
            )
            return ET.fromstring(r.stdout)
        except Exception as e:
            print(f"  ⚠️ UI dump 실패: {e}")
            return None

    @staticmethod
    def _adb_find_node(root, *, content_desc: str = None,
                       text: str = None, resource_id: str = None):
        """UI 트리에서 매칭 조건에 맞는 첫 노드의 중심 좌표를 반환합니다.

        Returns (cx, cy) or None.
        """
        for node in root.iter('node'):
            if content_desc is not None:
                if content_desc not in (node.get('content-desc') or ''):
                    continue
            if text is not None:
                if text not in (node.get('text') or ''):
                    continue
            if resource_id is not None:
                if resource_id not in (node.get('resource-id') or ''):
                    continue
            bounds = node.get('bounds', '')
            m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
            if m:
                cx = (int(m.group(1)) + int(m.group(3))) // 2
                cy = (int(m.group(2)) + int(m.group(4))) // 2
                return (cx, cy)
        return None

    def _adb_find_and_tap(self, udid: str, matchers: list,
                          *, timeout: float = 5.0, label: str = "요소",
                          fallback_coords: tuple = None) -> bool:
        """화면에서 요소를 찾아 보이면 탭합니다 (verify-then-act).

        matchers: [{"content_desc": "키패드"}, {"text": "전화"}] 등
        timeout 동안 요소가 나타날 때까지 UI 덤프를 재시도합니다.
        fallback_coords: 모든 matcher 실패 시 사용할 고정 좌표 (기존 호환).
        """
        deadline = time.time() + timeout
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            root = self._adb_dump_ui(udid)
            if root is None:
                time.sleep(1)
                continue
            for m_dict in matchers:
                coords = self._adb_find_node(root, **m_dict)
                if coords:
                    cx, cy = coords
                    subprocess.run(
                        ['adb', '-s', udid, 'shell', 'input', 'tap', str(cx), str(cy)],
                        capture_output=True, timeout=5
                    )
                    print(f"  ✓ {label} 발견 → 탭 ({cx}, {cy})")
                    return True
            # 아직 deadline 전이면 재시도
            if time.time() + 2 < deadline:
                time.sleep(1)
            else:
                break

        # fallback: 고정 좌표 (화면 구조가 변해도 기존 동작 유지)
        if fallback_coords:
            fx, fy = fallback_coords
            print(f"  ⚠️ {label} UI에서 미발견 → 고정 좌표 폴백 ({fx}, {fy})")
            subprocess.run(
                ['adb', '-s', udid, 'shell', 'input', 'tap', str(fx), str(fy)],
                capture_output=True, timeout=5
            )
            return True

        print(f"  ❌ {label} {timeout}초 내 미발견")
        return False

    def _adb_verify_dial_text(self, udid: str, expected: str,
                              timeout: float = 3.0) -> bool:
        """UI 덤프에서 다이얼 필드의 텍스트가 expected와 일치하는지 확인합니다.

        숫자만 추출하여 비교 (하이픈·공백 포매팅 무시).
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            root = self._adb_dump_ui(udid)
            if root is None:
                time.sleep(0.5)
                continue
            for node in root.iter('node'):
                cls_name = node.get('class', '')
                if 'EditText' in cls_name or 'TextView' in cls_name:
                    raw = node.get('text', '')
                    actual = re.sub(r'\D', '', raw)
                    if actual == expected:
                        print(f"  ✓ 다이얼 필드 검증 OK: {raw}")
                        return True
                    elif actual and len(actual) >= len(expected) * 0.5:
                        # 부분 일치이지만 다른 경우
                        print(f"  ⚠️ 다이얼 필드 불일치: 기대={expected}, 실제={actual} (원본: {raw})")
                        return False
            time.sleep(0.5)
        print(f"  ⚠️ 다이얼 필드 텍스트 {timeout}초 내 확인 불가")
        return False

    # ── Galaxy S22 Ultra 고정 좌표 (ADB-only 발신 폴백용) ─────────────
    _ADB_TAP_KEYPAD = (540, 2102)   # 키패드 탭
    _ADB_TAP_CALL   = (540, 1818)   # 발신(전화) 버튼

    def open_ixio_keypad(self, device_type='speaker1'):
        """익시오 앱에서 키패드 열기 (Android) — ADB-only.

        UiAutomator2 불안정 회피: ADB force-stop → monkey 실행 → tap 키패드 탭.
        """
        _udid = getattr(self, f'{device_type}_device', None)
        if not _udid:
            print(f"  ❌ {device_type} UDID 없음")
            return False

        print(f"📱 {device_type}: 익시오 앱 키패드 열기 (ADB)...")

        # Step 0: 화면 깨우기
        try:
            subprocess.run(
                ['adb', '-s', _udid, 'shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'],
                capture_output=True, text=True, timeout=5
            )
        except Exception:
            pass

        # Step 1: 앱 재시작 (잔류 번호 방지)
        try:
            subprocess.run(
                ['adb', '-s', _udid, 'shell', 'am', 'force-stop', self._android_pkg],
                capture_output=True, text=True, timeout=5
            )
        except Exception:
            pass
        time.sleep(1)

        try:
            subprocess.run(
                ['adb', '-s', _udid, 'shell', 'monkey', '-p', self._android_pkg,
                 '-c', 'android.intent.category.LAUNCHER', '1'],
                capture_output=True, text=True, timeout=5
            )
            print(f"  ✓ 익시오 앱 실행 완료")
        except Exception as e:
            print(f"  ❌ 앱 실행 실패: {e}")
            return False

        time.sleep(3)  # 앱 로딩 대기

        # Step 2: 키패드 탭 클릭 — "보이면 누른다" (verify-then-act)
        tapped = self._adb_find_and_tap(
            _udid,
            matchers=[
                {'content_desc': '키패드'},
                {'text': '키패드'},
                {'content_desc': 'Keypad'},
            ],
            timeout=5.0,
            label='키패드 탭',
            fallback_coords=self._ADB_TAP_KEYPAD,
        )
        time.sleep(1)

        if tapped:
            print(f"✅ 키패드 열기 완료\n")
        else:
            print(f"⚠️ 키패드 탭 클릭 불확실\n")
        return tapped
    def make_call(self, phone_number):
        """전화 걸기 (화자1에서) - Android 익시오 — ADB-only.

        ADB input text로 번호 입력 + ADB tap으로 발신 버튼 클릭.
        UiAutomator2를 사용하지 않아 Wi-Fi ADB 환경에서도 안정적.
        """
        _udid = getattr(self, 'speaker1_device', None)
        if not _udid:
            print(f"  ❌ speaker1_device UDID 없음")
            return False

        try:
            print(f"📞 전화번호 입력 중 (ADB input text): {phone_number}")
            time.sleep(1)

            # 번호 입력 (EditText가 자동 포커스 상태)
            r = subprocess.run(
                ['adb', '-s', _udid, 'shell', 'input', 'text', phone_number],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0:
                print(f"  ✓ 번호 입력 완료")
            else:
                print(f"  ⚠️ input text 실패: {r.stderr.strip()}")
                return False

            time.sleep(0.5)

            # 입력 결과 검증 — "보이면 누른다" 원칙: 입력된 값이 보여야 다음 단계
            if not self._adb_verify_dial_text(_udid, phone_number, timeout=3.0):
                print(f"  ⚠️ 다이얼 필드 검증 실패 — 번호 재입력 시도")
                # 필드 클리어 후 재입력
                subprocess.run(
                    ['adb', '-s', _udid, 'shell', 'input', 'keyevent', '--longpress', '67'],
                    capture_output=True, text=True, timeout=5
                )
                time.sleep(0.5)
                subprocess.run(
                    ['adb', '-s', _udid, 'shell', 'input', 'text', phone_number],
                    capture_output=True, text=True, timeout=10
                )
                time.sleep(0.5)
                if not self._adb_verify_dial_text(_udid, phone_number, timeout=3.0):
                    print(f"  ❌ 재입력 후에도 검증 실패 — 발신 중단")
                    return False

            # 발신 버튼 — "보이면 누른다" (verify-then-act)
            print(f"☎️ 발신 버튼 탐색 중...")
            call_tapped = self._adb_find_and_tap(
                _udid,
                matchers=[
                    {'content_desc': '전화'},
                    {'content_desc': '발신'},
                    {'content_desc': '통화'},
                    {'text': '전화'},
                    {'resource_id': f'{self._android_pkg}:id/callButton'},
                    {'resource_id': f'{self._android_pkg}:id/btn_call'},
                ],
                timeout=5.0,
                label='발신 버튼',
                fallback_coords=self._ADB_TAP_CALL,
            )
            if call_tapped:
                print(f"✅ 발신 완료\n")
            return call_tapped

        except Exception as e:
            print(f"❌ 전화 걸기 실패: {e}\n")
            return False

    # ── RINGING / OFFHOOK 감지 ────────────────────────────────────────────────

    @classmethod
    def _detect_android_ringing(cls, udid: str) -> bool:
        """단말 종류에 무관하게 RINGING 상태를 감지합니다.

        Android 16+(API 36) Samsung: gsm/ril.call.state가 빈 값이므로
        첫 호출에서 빈 값이면 이후 getprop을 건너뛰고 telephony.registry 직행.

        우선순위:
          1. getprop gsm.call.state   — 경량 ~50ms (일반 SIM 단말)
          2. getprop ril.call.state   — 일부 단말 대체 prop
          3. dumpsys telephony.registry → mCallState=1  (heavy fallback)
          4. dumpsys telecom → mState/state: RINGING    (업무 모드/MDM)
        """
        use_getprop = cls._getprop_available.get(udid, True)  # 첫 호출은 True

        if use_getprop:
            # 방법1: getprop gsm.call.state (가장 빠름 ~50ms)
            try:
                v1 = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'getprop', 'gsm.call.state'],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip()
                if v1 == 'RINGING':
                    return True
                if v1 in ('IDLE', 'OFFHOOK'):
                    return False
                # 빈 값 → 이 디바이스에서는 getprop 사용 불가 (Android 16+)
                if not v1:
                    cls._getprop_available[udid] = False
                    use_getprop = False
            except Exception:
                pass

        if use_getprop:
            # 방법2: ril.call.state
            try:
                v2 = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'getprop', 'ril.call.state'],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip()
                if v2 == 'RINGING':
                    return True
                if v2 in ('IDLE', 'OFFHOOK'):
                    return False
            except Exception:
                pass

        # 방법3: telephony.registry (Android 16+에서는 사실상 primary)
        # Wi-Fi ADB: grep -m1로 첫 매칭 후 즈시 pipe 중단 → dumpsys 출력 생성 중단 (~120ms)
        try:
            out = subprocess.run(
                ['adb', '-s', udid, 'shell',
                 'dumpsys', 'telephony.registry', '|', 'grep', '-m1', 'mCallState'],
                capture_output=True, text=True, timeout=3
            ).stdout
            if 'mCallState=1' in out:
                return True
            if 'mCallState=0' in out:
                return False  # IDLE → heavy telecom fallback 생략
        except Exception:
            pass

        # 방법4: telecom (업무 모드·MDM 단말)
        # ⚠️ 단순 'RINGING' 포함 체크 금지 — 변수명/잔류 텍스트로 오탐 발생
        try:
            out2 = subprocess.run(
                ['adb', '-s', udid, 'shell',
                 'dumpsys', 'telecom', '|', 'grep', '-E', 'mState|state:'],
                capture_output=True, text=True, timeout=3
            ).stdout
            if re.search(r'(?:mState|state):\s*RINGING', out2):
                return True
        except Exception:
            pass

        return False

    @classmethod
    def _detect_android_offhook(cls, udid: str) -> bool:
        """단말 종류에 무관하게 OFFHOOK(통화 연결) 상태를 감지합니다.

        Android 16+(API 36) Samsung: gsm/ril.call.state가 빈 값이므로
        캐시된 플래그(_getprop_available)로 빈 값인 경우 getprop 생략.

        우선순위:
          1. getprop gsm.call.state   — 경량, ~50ms (일반 SIM 단말)
          2. getprop ril.call.state   — 일부 단말 대체 prop
          3. dumpsys telephony.registry — 중량 fallback (~200ms)
          4. dumpsys telecom           — 업무 모드 단말 fallback (~200ms)
        """
        use_getprop = cls._getprop_available.get(udid, True)

        if use_getprop:
            # 방법1: getprop gsm.call.state (가장 빠름 ~50ms)
            try:
                v1 = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'getprop', 'gsm.call.state'],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip()
                if v1 == 'OFFHOOK':
                    return True
                if v1 in ('IDLE', 'RINGING'):
                    return False  # 명확히 아닌 경우 heavy fallback 생략
                if not v1:
                    cls._getprop_available[udid] = False
                    use_getprop = False
            except Exception:
                pass

        if use_getprop:
            # 방법2: ril.call.state (일부 업무용/MVNO 단말)
            try:
                v2 = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'getprop', 'ril.call.state'],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip()
                if v2 == 'OFFHOOK':
                    return True
                if v2 in ('IDLE', 'RINGING'):
                    return False
            except Exception:
                pass

        # 방법3: telephony.registry (Android 16+에서는 사실상 primary)
        # Wi-Fi ADB: grep -m1로 첫 매칭 후 pipe 중단 (~120ms)
        try:
            v3 = subprocess.run(
                ['adb', '-s', udid, 'shell',
                 'dumpsys', 'telephony.registry', '|', 'grep', '-m1', 'mCallState'],
                capture_output=True, text=True, timeout=3
            ).stdout
            if 'mCallState=2' in v3:
                return True
            if 'mCallState=0' in v3 or 'mCallState=1' in v3:
                return False  # IDLE/RINGING → heavy telecom fallback 생략
        except Exception:
            pass

        # 방법4: telecom (업무 모드 단말)
        try:
            v4 = subprocess.run(
                ['adb', '-s', udid, 'shell',
                 'dumpsys', 'telecom', '|', 'grep', '-E', 'mState|state:'],
                capture_output=True, text=True, timeout=3
            ).stdout
            if re.search(r'(?:mState|state):\s*(?:ACTIVE|DIALING)', v4):
                return True
        except Exception:
            pass

        return False

    @classmethod
    def _accept_android_ringing_call(cls, udid: str) -> float:
        """RINGING 상태인 단말에 수신 수락 명령을 순차적으로 시도합니다 (순수 ADB).

        ⚠️ GUI(Appium/UIAutomator) 조작은 일절 사용하지 않습니다.
           ixio 앱의 'AI 전화 대신 받기' 등 엉뚱한 버튼 클릭을 막기 위해
           ADB 명령어만으로 수신 수락합니다.

        ⚠️ KEYCODE_CALL(5) / KEYCODE_HEADSETHOOK(79) 는 수락/종료 토글키이므로
           이미 OFFHOOK 상태에서 전송하면 통화가 끊어집니다.
           각 전략 사이에 OFFHOOK 상태를 확인하고, 연결됐으면 즉시 중단합니다.

        전략 순서 (ADB only):
          API < 36:
            ① telecom accept-ringing-call — API 26+, 일반 단말 최우선
            ② KEYCODE_CALL (5)            — 수락/종료 토글
            ③ KEYCODE_ANSWER (164)        — 수신 전용 키
            ④ KEYCODE_HEADSETHOOK (79)    — 업무 모드 단말 fallback
            ⑤ am broadcast ANSWER         — 구형 단말 최후 수단
          API >= 36 (Android 16+):
            telecom accept-ringing-call 제거됨 → KEYCODE_CALL(5)부터 시작

        Returns:
            tuple[float, float]: (offhook_detected_ts, cmd_sent_ts)
              - offhook_detected_ts: OFFHOOK ADB 감지 시각. 미감지 시 0.0.
              - cmd_sent_ts: 성공한 strategy의 명령 전송 직전 시각.
                            Android는 명령 수신 후 수십 ms 내 OFFHOOK이므로
                            이 값이 실제 통화 연결 시각에 가장 가깝습니다.
                            미감지 시 0.0.
        """
        api_level = cls._get_android_api(udid)

        # ── 전략 목록 구성 (API 레벨에 따라 순서 조정) ─────────────────────
        strategies: list[tuple[str, list[str]]] = []

        if api_level < 36:
            # API < 36: telecom accept 먼저 시도 (가장 깨끗한 방법)
            strategies.append((
                '① telecom accept-ringing-call',
                ['telecom', 'accept-ringing-call'],
            ))
        else:
            print(f"  [워쳐]   ℹ️ API {api_level} — telecom accept-ringing-call 미지원, 건너뜀")

        # KEYCODE_CALL(5): Samsung Android 16에서 유일하게 동작하는 수락 전략
        # ⚠️ 토글키이므로 OFFHOOK 상태에서 보내면 통화 종료됨 →
        #    각 전략 사이 OFFHOOK 확인 후 이미 연결됐으면 즉시 중단
        strategies.append(('② KEYCODE_CALL(5)', ['input', 'keyevent', '5']))
        strategies.append(('③ KEYCODE_ANSWER(164)', ['input', 'keyevent', '164']))
        strategies.append(('④ KEYCODE_HEADSETHOOK(79)', ['input', 'keyevent', '79']))
        strategies.append(('⑤ am broadcast ANSWER',
                           ['am', 'broadcast', '-a', 'android.intent.action.ANSWER']))

        # ── 순차 실행 ─────────────────────────────────────────────────────
        _adb_reconnected = False
        for i, (label, cmd_args) in enumerate(strategies):
            # 토글키 안전장치: 이미 OFFHOOK이면 추가 명령 보내지 않음
            # ⚠️ 첫 번째 전략은 RINGING 직후이므로 OFFHOOK 불가능 → 체크 생략 (~200ms 절약)
            if i > 0 and cls._detect_android_offhook(udid):
                _ts = time.time()
                print(f"  [워쳐]   ✅ 이미 OFFHOOK — 추가 전략 생략")
                return _ts, _ts

            _cmd_ts = time.time()
            r = subprocess.run(
                ['adb', '-s', udid, 'shell'] + cmd_args,
                capture_output=True, text=True, timeout=5
            )
            extra = ''
            _stderr = r.stderr.strip()
            if _stderr:
                extra += f' stderr={_stderr}'
            out_s = r.stdout.strip()

            # ── Wi-Fi ADB 끊김 감지 → 즉시 재연결 후 OFFHOOK 확인 ──
            if 'not found' in _stderr or 'cannot connect' in _stderr:
                print(f"  [워쳐]   {label} → rc={r.returncode}{extra}")
                if not _adb_reconnected and ':' in udid:
                    _adb_reconnected = True
                    print(f"  [워쳐]   🔄 ADB 연결 끊김 감지 → 재연결 시도")
                    for _retry in range(3):
                        try:
                            _cr = subprocess.run(
                                ['adb', 'connect', udid],
                                capture_output=True, text=True, timeout=10
                            )
                            if 'connected' in _cr.stdout.lower():
                                print(f"  [워쳐]   ✅ ADB 재연결 성공: {_cr.stdout.strip()}")
                                # 재연결 후 OFFHOOK 확인 (이전 전략으로 이미 수락됐을 수 있음)
                                time.sleep(0.3)
                                if cls._detect_android_offhook(udid):
                                    _ts = time.time()
                                    print(f"  [워쳐]   ✅ 재연결 후 OFFHOOK 확인 — 이미 수락됨")
                                    return _ts, _cmd_ts
                                break
                            else:
                                print(f"  [워쳐]   ⚠️ ADB 재연결 응답: {_cr.stdout.strip()}")
                        except Exception as _ce:
                            print(f"  [워쳐]   ⚠️ ADB 재연결 실패: {_ce}")
                        if _retry < 2:
                            time.sleep(1)
                continue  # 다음 전략 시도

            if 'Unknown command' in out_s or 'Error:' in out_s:
                extra += f' ✗({out_s[:60]})'
                print(f"  [워쳐]   {label} → rc={r.returncode}{extra} — 건너뜀")
                continue  # 이 명령은 미지원 → OFFHOOK 대기 불필요, 즉시 다음

            print(f"  [워쳐]   {label} → rc={r.returncode}{extra}")

            # 첫 체크는 짧게 대기 (Samsung OFFHOOK 전이 ~50-100ms)
            for _wait in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
                time.sleep(_wait)
                if cls._detect_android_offhook(udid):
                    _ts = time.time()
                    print(f"  [워쳐]   ✅ {label} 성공 — 나머지 전략 생략")
                    return _ts, _cmd_ts

        return 0.0, 0.0

    # ── 수신 워쳐 스레드 ────────────────────────────────────────────────────────

    def _start_android_answer_watcher(self, answered_event: 'threading.Event',
                                      failed_event: 'threading.Event',
                                      accept_event: 'threading.Event | None' = None) -> None:
        """Android 수신 감지 백그라운드 워쳐 스레드 (하이브리드 방식).

        Primary:  logcat 실시간 스트림 — RINGING 즉시 감지 (~10ms)
        Fallback: dumpsys 폴링 — logcat 스트림 끊김 대비 (3초 간격)

        logcat 스트림은 ADB 연결 1회로 상태 변경을 실시간 수신하므로
        Wi-Fi ADB 환경에서도 안정적이며, 매번 프로세스를 생성하는 폴링보다 빠릅니다.
        """
        udid = self.speaker2_device  # type: ignore[attr-defined]
        print(f"  [워쳐] Android 수신 감지 시작 (logcat 스트림 + dumpsys 폴백)")
        print(f"  [워쳐] 대상 UDID: {udid}")

        # Wi-Fi ADB 연결 검증 (끊김 시 재연결)
        if ':' in udid:
            try:
                _chk = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'echo', 'ok'],
                    capture_output=True, text=True, timeout=5
                )
                if 'ok' not in _chk.stdout:
                    raise RuntimeError('ADB 응답 없음')
            except Exception:
                print(f"  [워쳐] ⚠️ ADB 끊김 감지 → 재연결 시도")
                _cr = subprocess.run(['adb', 'connect', udid], capture_output=True, text=True, timeout=10)
                print(f"  [워쳐] 🔄 ADB 재연결: {_cr.stdout.strip()}")

        ringing_detected = threading.Event()
        _diag_interval = 15.0
        _start_ts = time.time()

        # ── logcat 스트림 스레드 ──────────────────────────────────────────
        def _logcat_watcher():
            try:
                # 현재 logcat 버퍼 클리어 후 실시간 스트림 시작
                subprocess.run(
                    ['adb', '-s', udid, 'shell', 'logcat', '-c'],
                    capture_output=True, timeout=3
                )
                proc = subprocess.Popen(
                    ['adb', '-s', udid, 'shell', 'logcat', '-v', 'brief',
                     '-s', 'CAE:I', 'SemWifiBackOff.Sar:D'],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True
                )
                self._logcat_proc = proc  # cleanup용 참조 저장
                deadline = _start_ts + 120.0
                while time.time() < deadline and not ringing_detected.is_set():
                    line = proc.stdout.readline()
                    if not line:
                        break  # 스트림 끊김
                    if 'RINGING' in line or 'CALL_STATE_RINGING' in line:
                        ringing_detected.set()
                        return
                proc.terminate()
            except Exception as e:
                print(f"  [워쳐] ⚠️ logcat 스트림 오류: {e}")

        logcat_thread = threading.Thread(target=_logcat_watcher, daemon=True)
        logcat_thread.start()

        # ── 메인 루프: logcat 이벤트 대기 + dumpsys 폴백 ──────────────────
        deadline = _start_ts + 120.0
        _next_diag = _start_ts + _diag_interval
        _poll_count = 0
        _fallback_interval = 3.0  # dumpsys 폴백은 3초 간격 (logcat이 primary)
        _next_fallback = _start_ts + 1.0  # 첫 폴백은 1초 후

        while time.time() < deadline:
            # logcat 스트림에서 RINGING 감지됨
            if ringing_detected.wait(timeout=0.1):
                break

            # dumpsys 폴백: logcat 스트림이 끊겼을 경우 대비
            if time.time() >= _next_fallback:
                _poll_count += 1
                try:
                    if self._detect_android_ringing(udid):
                        ringing_detected.set()
                        break
                except Exception:
                    pass
                _next_fallback = time.time() + _fallback_interval

            # 진단 로그
            if time.time() >= _next_diag:
                _elapsed = int(time.time() - _start_ts)
                _logcat_alive = logcat_thread.is_alive()
                _gp = self._getprop_available.get(udid, True)
                try:
                    _diag_out = subprocess.run(
                        ['adb', '-s', udid, 'shell',
                         'dumpsys', 'telephony.registry', '|', 'grep', '-m1', 'mCallState'],
                        capture_output=True, text=True, timeout=3
                    ).stdout
                    import re as _re
                    _cs = _re.findall(r'mCallState=\d+', _diag_out)
                    print(f"  [워쳐] 📊 {_elapsed}초 경과 | logcat={'활성' if _logcat_alive else '끊김'} | 폴백 {_poll_count}회 | getprop={_gp} | {', '.join(_cs) if _cs else 'mCallState 없음'}")
                except Exception as _de:
                    print(f"  [워쳐] 📊 {_elapsed}초 경과 | logcat={'활성' if _logcat_alive else '끊김'} | 폴백 {_poll_count}회 | 진단 실패: {_de}")
                _next_diag = time.time() + _diag_interval

        # ── logcat 프로세스 정리 ──────────────────────────────────────────
        try:
            proc = getattr(self, '_logcat_proc', None)
            if proc and proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

        if not ringing_detected.is_set():
            print(f"  [워쳐] ❌ 120초 내 RINGING 미감지 (폴백 {_poll_count}회)")
            failed_event.set()
            return

        # ── RINGING 감지 → 수신 수락 ─────────────────────────────────────
        ringing_ts = time.time()
        _settle_sec = self._incoming_pattern.get('settle_sec', 1.0)
        _app_pkg = self._android_pkg
        if _settle_sec > 0:
            print(f"  [워쳐] ✅ RINGING 감지 → 수신 앱 UI 안정화 대기 ({_settle_sec:.0f}초) [{_app_pkg}]")
        else:
            print(f"  [워쳐] ✅ RINGING 감지 → 즉시 수신 수락 [{_app_pkg}]")

        # accept_event 즉시 set → 메인 스레드 타이밍 기준점
        if accept_event is not None:
            try:
                accept_event._accept_sent_ts = ringing_ts
                accept_event.set()
            except Exception:
                pass

        # 화면 꺼짐 → 수신 수락 실패 방지: RINGING 감지 즉시 화면 켜기
        try:
            _ds = getattr(self, 'device_setup', None)
            if _ds:
                _ds._adb_wake_screen(udid)
        except Exception:
            pass

        # ── 앱별 UI 안정화 대기 ──────────────────────────────────────────
        # 익시오: RINGING 직후 keyevent를 보내면 'AI 전화 대신 받기' UI가
        #         keyevent를 소비 → 5초 대기 필요
        # 삼성/에이닷/Apple 전화: 일반 telephony → 즉시 수신 수락 가능
        if _settle_sec > 0:
            _settle_deadline = time.time() + _settle_sec
            while time.time() < _settle_deadline:
                if self._detect_android_offhook(udid):
                    print(f"  [워쳐] ✅ 대기 중 OFFHOOK 감지 — 자동 수신")
                    offhook_ts = time.time()
                    try:
                        answered_event._offhook_ts = offhook_ts
                        answered_event._cmd_sent_ts = ringing_ts
                        answered_event._accept_sent_ts = ringing_ts
                    except Exception:
                        pass
                    answered_event.set()
                    return
                time.sleep(0.5)

        print(f"  [워쳐] 수신 수락 시도 [{_app_pkg}]")

        # 수신 수락 (ADB 명령어 순차 시도)
        offhook_ts, cmd_sent_ts = self._accept_android_ringing_call(udid)
        offhook_confirmed = offhook_ts > 0.0

        # OFFHOOK 미확인 시 ADB 재연결 후 추가 대기
        if not offhook_confirmed:
            # ADB 연결이 끊겼을 수 있음 → 재연결 시도
            if ':' in udid:
                try:
                    _cr = subprocess.run(
                        ['adb', 'connect', udid],
                        capture_output=True, text=True, timeout=10
                    )
                    if 'connected' in _cr.stdout.lower():
                        print(f"  [워쳐] 🔄 OFFHOOK 확인 전 ADB 재연결: {_cr.stdout.strip()}")
                        time.sleep(0.3)
                except Exception:
                    pass

            offhook_deadline = time.time() + 15.0
            while time.time() < offhook_deadline:
                if self._detect_android_offhook(udid):
                    offhook_ts = time.time()
                    offhook_confirmed = True
                    break
                time.sleep(0.1)

        if not offhook_confirmed:
            print(f"  [워쳐] ❌ OFFHOOK 미확인 → 수신 실패")
            failed_event.set()
            return

        elapsed = (offhook_ts - ringing_ts) * 1000
        print(f"  [워쳐] ✅ OFFHOOK 확인 — 통화 연결됨 (RINGING→OFFHOOK: {elapsed:.0f}ms)")

        try:
            answered_event._offhook_ts = offhook_ts
            answered_event._cmd_sent_ts = cmd_sent_ts if cmd_sent_ts > 0.0 else ringing_ts
            answered_event._accept_sent_ts = ringing_ts
        except Exception:
            pass
        answered_event.set()

        # Audio Mode 확인 (백그라운드)
        def _log_audio_mode(_udid=udid):
            _dl = time.time() + 5.0
            while time.time() < _dl:
                try:
                    a = subprocess.run(
                        ['adb', '-s', _udid, 'shell', 'dumpsys', 'audio'],
                        capture_output=True, text=True, timeout=3
                    ).stdout
                    if 'IN_CALL' in a or 'IN_COMMUNICATION' in a or 'mMode=3' in a:
                        print(f"  [워쳐] ✅ Audio Mode IN_CALL 확인")
                        return
                except Exception:
                    pass
                time.sleep(0.3)
        threading.Thread(target=_log_audio_mode, daemon=True).start()

    def _answer_call_android_adb(self) -> bool:
        """(deprecated) _start_android_answer_watcher 사용 권장."""
        answered = threading.Event()
        failed   = threading.Event()
        threading.Thread(
            target=self._start_android_answer_watcher,
            args=(answered, failed), daemon=True
        ).start()
        return answered.wait(timeout=60.0)

    def _ensure_android_idle(self, udid: str = None) -> bool:
        """발신 전 Android 잔류 ACTIVE 상태를 IDLE로 전환 (동기 실행).

        이전 통화 세션의 telephony/audio 상태가 아직 ACTIVE면
        워쳐가 오탐(false positive)하거나, ENDCALL이 새 통화를 끊을 수 있으므로
        반드시 make_call() 전에 호출해야 합니다.

        Returns True if IDLE confirmed.
        """
        if udid is None:
            udid = self.speaker1_device  # type: ignore[attr-defined]

        clear_deadline = time.time() + 15.0
        saw_idle = False
        while time.time() < clear_deadline:
            if not self._is_call_active_android(udid):
                saw_idle = True
                break
            print(f"  [IDLE확인] ⏳ 이전 통화 잔류 ACTIVE 대기 중...")
            time.sleep(0.3)

        if not saw_idle:
            print(f"  [IDLE확인] ⚠️ 15초 내 IDLE 미전환 → ENDCALL 강제 전송")
            try:
                subprocess.run(
                    ['adb', '-s', udid, 'shell', 'input', 'keyevent', 'KEYCODE_ENDCALL'],
                    capture_output=True, text=True, timeout=5
                )
                time.sleep(2)
            except Exception:
                pass
            idle_recheck = time.time() + 5.0
            while time.time() < idle_recheck:
                if not self._is_call_active_android(udid):
                    saw_idle = True
                    break
                time.sleep(0.3)
            if saw_idle:
                print(f"  [IDLE확인] ✅ ENDCALL 후 IDLE 확인 완료")
            else:
                print(f"  [IDLE확인] ⚠️ ENDCALL 후에도 ACTIVE 잔류 — 오탐 가능성 있음")
        return saw_idle

    def _start_android_caller_active_watcher(self, active_event: 'threading.Event') -> None:
        """Android 발신단이 ACTIVE 상태(상대방 수락)가 되면 active_event 설정.

        speaker1=Android 발신, speaker2=iOS 수신 케이스용 워처.
        발신 전에 미리 스레드를 시작해 두어야 ACTIVE 감지 지연을 최소화합니다.

        ⚠️ Phase 0(잔류 ACTIVE 정리)는 _ensure_android_idle()로 분리됨.
           반드시 이 워쳐 시작 전에 _ensure_android_idle()을 동기적으로 호출해야 합니다.

        ACTIVE 감지 시:
          active_event._active_ts = time.time()  ← 음원 재생 기준 타임스탬프
          active_event.set()
        120초 내 미감지 시 이벤트 없이 종료 (폴백: wait_for_call_connecting_state 사용).
        """
        udid = self.speaker1_device  # type: ignore[attr-defined]
        print(f"  [발신워쳐] Android 발신단 ACTIVE 감지 시작 (상대 수락 대기 중...)")

        # ── ACTIVE 전이 감지 (Phase 0은 _ensure_android_idle에서 처리됨) ──
        # VoIP(익시오): telephony/telecom에 ACTIVE가 반영되지 않으므로
        # audio mode(IN_COMMUNICATION) 변화를 추가 감지.
        # Phase 0 이후이므로 앱이 이미 포그라운드 → 초기 audio mode를 기준값으로 캡처.
        _initial_voip_active = self._is_call_active_android_voip(udid)
        _voip_transition_seen = False  # False→True 전이만 의미 있음
        deadline = time.time() + 120.0
        while time.time() < deadline:
            try:
                # ADB telephony/telecom 기반 감지 (일반 통화)
                if self._is_call_active_android(udid):
                    active_ts = time.time()
                    print(f"  [발신워쳐] ✅ Android ACTIVE 감지 (telephony) → 통화 연결됨")
                    try:
                        active_event._active_ts = active_ts  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    active_event.set()
                    return

                # VoIP 보완: audio mode 전이 감지 (False→True)
                if not _initial_voip_active and not _voip_transition_seen:
                    if self._is_call_active_android_voip(udid):
                        _voip_transition_seen = True
                        active_ts = time.time()
                        print(f"  [발신워쳐] ✅ Android ACTIVE 감지 (VoIP audio mode 전이) → 통화 연결됨")
                        try:
                            active_event._active_ts = active_ts  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        active_event.set()
                        return
                # VoIP: 이미 초기부터 active였으면 전이 감지 불가 → mCallState=2(OFFHOOK) 폴백
                if _initial_voip_active and not _voip_transition_seen:
                    try:
                        reg = subprocess.run(
                            ['adb', '-s', udid, 'shell', 'dumpsys', 'telephony.registry'],
                            capture_output=True, text=True, timeout=5
                        ).stdout
                        if 'mCallState=2' in reg:
                            # OFFHOOK = 발신/수신 중. VoIP에서는 상대 수락 후에만 2가 되므로
                            # IN_COMMUNICATION + OFFHOOK = 통화 연결로 판단
                            active_ts = time.time()
                            print(f"  [발신워쳐] ✅ Android ACTIVE 감지 (VoIP OFFHOOK+audio) → 통화 연결됨")
                            try:
                                active_event._active_ts = active_ts
                            except Exception:
                                pass
                            active_event.set()
                            return
                    except Exception:
                        pass
            except Exception:
                pass

            time.sleep(0.5)

        print(f"  [발신워쳐] ⚠️ 120초 내 ACTIVE 미감지 — 메인 스레드 폴백으로 처리")
