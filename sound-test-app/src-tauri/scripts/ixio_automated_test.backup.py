"""
익시오 앱 자동화 테스트 - GUI용
통화 연결 후 "통화 종료" 버튼 감지 → 3초 대기 → 오디오 재생 → 통화 종료
"""

import sys
import time
import signal
import argparse
import subprocess
import threading
from pathlib import Path
from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.android import UiAutomator2Options
from appium.options.ios import XCUITestOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from audio_handler import AudioHandler, DeviceAudioPlayer
from ios_wda_manager import IosWdaManager
from appium_device_setup import AppiumDeviceSetup
from ios_call_handler import IosCallHandlerMixin
from android_call_handler import AndroidCallHandlerMixin
from answer_strategies import AnswerStrategiesMixin
try:
    from wda_auto_answer import WdaAnswerer
    _WDA_ANSWER_AVAILABLE = True
except ImportError:
    _WDA_ANSWER_AVAILABLE = False
try:
    from device_detector import auto_select_ios_udid, auto_select_android_udid, detect_all_devices
    _DEVICE_DETECTOR_AVAILABLE = True
except ImportError:
    _DEVICE_DETECTOR_AVAILABLE = False
    def auto_select_ios_udid(): return None
    def auto_select_android_udid(): return None
    def detect_all_devices(): return []
try:
    from config import WDA_IP_OVERRIDE, WDA_PORT as _WDA_PORT
except ImportError:
    WDA_IP_OVERRIDE = None
    _WDA_PORT = 8100
try:
    from core_audio_utils import lock_usb_output_for_test, restore_default_devices
    _CORE_AUDIO_AVAILABLE = True
except ImportError:
    _CORE_AUDIO_AVAILABLE = False
    def lock_usb_output_for_test(verbose=True): pass
    def restore_default_devices(verbose=True): pass

try:
    from crash_reporter import CrashReporter
    _CRASH_REPORTER_AVAILABLE = True
except ImportError:
    _CRASH_REPORTER_AVAILABLE = False

try:
    from call_recorder import CallRecorder
    _CALL_RECORDER_AVAILABLE = True
except ImportError:
    _CALL_RECORDER_AVAILABLE = False
    CallRecorder = None  # type: ignore

try:
    from call_audio_collector import CallAudioCollector
    _CALL_AUDIO_COLLECTOR_AVAILABLE = True
except ImportError:
    _CALL_AUDIO_COLLECTOR_AVAILABLE = False
    CallAudioCollector = None  # type: ignore

try:
    from tc01_ios_caller import Tc01IosCaller
    _TC01_IOS_CALLER_AVAILABLE = True
except ImportError:
    _TC01_IOS_CALLER_AVAILABLE = False
    Tc01IosCaller = None  # type: ignore


def wait_element(driver, locator, timeout: float = 30.0):
    """locator 에 해당하는 요소가 나타날 때까지 대기.

    Args:
        driver:  Appium WebDriver
        locator: (By, selector) 튜플
        timeout: 최대 대기 시간 (초, 기본 30)
    Returns:
        WebElement  — 발견 시
        None        — timeout 내 미발견
    """
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located(locator)
        )
    except Exception:
        return None


class IxioAutomatedTest(IosCallHandlerMixin, AndroidCallHandlerMixin, AnswerStrategiesMixin):
    """익시오 앱 자동화 테스트 (GUI 버전)"""
    
    def __init__(self, speaker1_device, speaker2_device, speaker1_number, speaker2_number, speaker1_audio, speaker2_audio,
                 speaker1_output_device=None, speaker2_output_device=None,
                 speaker1_channel=None, speaker2_channel=None, monitor=False,
                 tc_type: str = 'TC_01', screenshot_dir: str = ''):
        # ── 1. UDID 자동 감지 ───────────────────────────────────────────────
        speaker1_device, speaker2_device = self._resolve_udids(speaker1_device, speaker2_device)
        self.speaker1_device = speaker1_device
        self.speaker2_device = speaker2_device

        # ── 2. 기본 속성 ─────────────────────────────────────────────────────
        self.speaker1_number = speaker1_number
        self.speaker2_number = speaker2_number
        self.speaker1_audio  = speaker1_audio
        self.speaker2_audio  = speaker2_audio

        # ── 3. 플랫폼 감지 (UDID 길이 기준: iOS >= 25자) ─────────────────────
        self.speaker1_platform = 'iOS' if len(speaker1_device) >= 25 else 'Android'
        self.speaker2_platform = 'iOS' if len(speaker2_device) >= 25 else 'Android'

        # ── 4. 오디오 출력 장치 해결 ──────────────────────────────────────────
        # ⚠️  USB 포트 배치 기준 (화자 플랫폼 무관):
        #     android_a = locationID USB 포트 1번, ios_b = locationID USB 포트 2번
        #     물리 케이블이 바뀌어 꽂혀 있으면 config.py의 location_id를 swap하세요.
        raw_s1 = int(speaker1_output_device) if speaker1_output_device not in (None, '', 'None') else None
        raw_s2 = int(speaker2_output_device) if speaker2_output_device not in (None, '', 'None') else None
        self.speaker1_output_device, self.speaker2_output_device = self._resolve_audio_devices(raw_s1, raw_s2)

        # ── 5. 채널·모니터 설정 ───────────────────────────────────────────────
        self.speaker1_channel = speaker1_channel if speaker1_channel in ('L', 'R') else None
        self.speaker2_channel = speaker2_channel if speaker2_channel in ('L', 'R') else None
        self.monitor_enabled  = monitor

        # ── 6. 런타임 상태 초기화 ─────────────────────────────────────────────
        self.drivers        = {}
        self.wait_objects   = {}
        self.audio_handler  = AudioHandler()
        self.audio_files    = {}
        self.tunnel_process = None       # pymobiledevice3 터널 프로세스
        self._ios_wda_url: str | None = None  # iOS WDA URL (동적 감지)
        self._audio_procs: list = []     # 재생 중인 audio_player_worker subprocess 목록

        self.appium_server_android = 'http://127.0.0.1:4723'
        self.appium_server_ios     = 'http://127.0.0.1:4724'

        self.wda_manager  = IosWdaManager()
        self.device_setup = AppiumDeviceSetup(
            appium_server_android=self.appium_server_android,
            appium_server_ios=self.appium_server_ios,
            wda_manager=self.wda_manager,
        )

        # ── 8. 크래시 리포터 초기화 ──────────────────────────────────────────
        ios_udid = speaker1_device if self.speaker1_platform == 'iOS' else (
                   speaker2_device if self.speaker2_platform == 'iOS' else "")
        and_udid = speaker1_device if self.speaker1_platform == 'Android' else (
                   speaker2_device if self.speaker2_platform == 'Android' else "")
        self.crash_reporter = (
            CrashReporter(ios_udid=ios_udid, android_udid=and_udid)
            if _CRASH_REPORTER_AVAILABLE else None
        )

        # ── 9. 통화 녹음기 초기화 ─────────────────────────────────────────────
        _recording_enabled = False
        try:
            from config import RECORDING_ENABLED
            _recording_enabled = bool(RECORDING_ENABLED)
        except (ImportError, AttributeError):
            pass
        self._call_recorder = (
            CallRecorder(
                speaker1_platform=self.speaker1_platform,
                speaker2_platform=self.speaker2_platform,
            )
            if (_CALL_RECORDER_AVAILABLE and _recording_enabled) else None
        )

        # ── 10. 통화 종료 후 수집 수단 초기화 ────────────────────────────────
        # iOS 앱 녹음 pull + Android 통화 녹음 ADB pull + 믹스
        self._call_audio_collector: object = None  # CallAudioCollector | None  (run() 에서 생성)
        # 통화 시작 타임스탬프 (수집 시 최신 파일 식별에 사용)
        self._call_start_ts: str = ""

        # ── 11. TC 타입 및 스크린샷 저장 경로 ─────────────────────────────────
        self.tc_type        = tc_type        # 'TC_01' | 'TC_02' | 'TC_03'
        import os as _os
        self.screenshot_dir = screenshot_dir or _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
            '..', 'audio_files', 'screenshots'
        )
        if self._call_recorder:
            print(f"🎙️ [CallRecorder] 통화 녹음 준비 완료 "
                  f"(S1={self.speaker1_platform}, S2={self.speaker2_platform})")

        # ── 7. 설정 요약 출력 ─────────────────────────────────────────────────
        self._print_config(raw_s1, raw_s2)

    # ── 생성자 헬퍼 메서드 ──────────────────────────────────────────────────────

    @staticmethod
    def _resolve_udids(speaker1_device: str, speaker2_device: str) -> tuple[str, str]:
        """'auto' 또는 빈 UDID를 연결된 단말에서 자동 선택합니다.

        플랫폼(iOS/Android) 편향 없이 연결된 순서대로 자동 선택합니다.
        사용자가 UDID를 직접 지정한 경우에는 그대로 사용합니다.
        """
        all_devs: list[dict] = []

        if not speaker1_device or speaker1_device.strip().lower() == 'auto':
            print("🔍 화자1 디바이스 자동 감지 중...")
            all_devs = detect_all_devices()
            chosen = all_devs[0] if all_devs else None
            if not chosen:
                raise RuntimeError("화자1 디바이스를 찾을 수 없습니다. USB/Wi-Fi 연결을 확인하세요.")
            speaker1_device = chosen['udid']
            print(f"  📱 화자1 자동 선택: {chosen.get('name', speaker1_device)} [{chosen['platform']}]")

        if not speaker2_device or speaker2_device.strip().lower() == 'auto':
            print("🔍 화자2 디바이스 자동 감지 중...")
            if not all_devs:
                all_devs = detect_all_devices()
            others = [d for d in all_devs if d['udid'] != speaker1_device]
            chosen = others[0] if others else None
            if not chosen:
                raise RuntimeError("화자2 디바이스를 찾을 수 없습니다. 두 번째 단말 연결을 확인하세요.")
            speaker2_device = chosen['udid']
            print(f"  📱 화자2 자동 선택: {chosen.get('name', speaker2_device)} [{chosen['platform']}]")

        return speaker1_device, speaker2_device

    @staticmethod
    def _usb_order_for_device(device_index: int | None) -> int | None:
        """사운드카드 device index가 USB 장치 목록에서 몇 번째인지(1-based)를 동적으로 반환.

        macOS 재열거로 index가 바뀌어도 usb_order 기반 복구가 올바르게 작동하도록
        항상 현재 sounddevice 목록을 기준으로 계산합니다.
        device_index가 None이거나 USB 목록에 없으면 None 반환.
        """
        if device_index is None:
            return None
        try:
            import sounddevice as sd
            usb_outputs = sorted([
                i for i, d in enumerate(sd.query_devices())
                if d['max_output_channels'] > 0 and 'USB' in d['name']
            ])
            if device_index in usb_outputs:
                return usb_outputs.index(device_index) + 1   # 1-based
        except Exception:
            pass
        return None

    def _resolve_audio_devices(self, raw_s1, raw_s2) -> tuple:
        """locationID 기반 config 매핑으로 오디오 출력 장치 index를 결정합니다.

        raw_s1/raw_s2가 명시된 경우 그대로 사용.
        미지정 시 config.py의 locationID 매핑(슬롯1=android_a, 슬롯2=ios_b)으로 자동 해결.
        슬롯 이름은 USB 포트 위치를 나타낼 뿐 화자 플랫폼과 무관합니다.
        """
        try:
            from audio_handler import resolve_audio_device_index, list_usb_audio_devices
            s1 = raw_s1 if raw_s1 is not None else resolve_audio_device_index('android_a')
            s2 = raw_s2 if raw_s2 is not None else resolve_audio_device_index('ios_b')
            if s1 == s2 and s1 is not None:
                print(f"⚠️  [경고] 화자1·화자2 출력 장치가 동일(index={s1})")
                print(f"   → config.py의 location_id 또는 USB 케이블 연결 포트를 확인하세요.")
            list_usb_audio_devices()
            return s1, s2
        except Exception as e:
            print(f"⚠️ 오디오 장치 자동 해결 실패: {e}")
            return raw_s1, raw_s2

    def _print_config(self, raw_s1, raw_s2) -> None:
        """테스트 설정 요약을 콘솔에 출력합니다."""
        auto_tag = ' (locationID 자동 해결)'
        print(f"\n{'='*60}")
        print(f"🎯 익시오 통화 테스트 설정")
        print(f"{'='*60}")
        print(f"화자1: {self.speaker1_device} ({self.speaker1_number})")
        print(f"  플랫폼: {self.speaker1_platform}")
        if self.speaker1_platform == 'iOS':
            _v1 = self._get_ios_ixio_app_version(self.speaker1_device)
            print(f"  ixio 앱 버전: {_v1}")
        print(f"  오디오: {self.speaker1_audio}")
        dev1 = self.speaker1_output_device if self.speaker1_output_device is not None else '기본'
        print(f"  출력장치: {dev1}" + ("" if raw_s1 is not None else auto_tag))
        print(f"  채널: {self.speaker1_channel or '양쪽'}")
        print(f"화자2: {self.speaker2_device} ({self.speaker2_number})")
        print(f"  플랫폼: {self.speaker2_platform}")
        if self.speaker2_platform == 'iOS':
            _v2 = self._get_ios_ixio_app_version(self.speaker2_device)
            print(f"  ixio 앱 버전: {_v2}")
        print(f"  오디오: {self.speaker2_audio}")
        dev2 = self.speaker2_output_device if self.speaker2_output_device is not None else '기본'
        print(f"  출력장치: {dev2}" + ("" if raw_s2 is not None else auto_tag))
        print(f"  채널: {self.speaker2_channel or '양쪽'}")
        print(f"{'='*60}\n")
    
    def start_remote_tunnel(self):
        """iOS 무선 터널 시작 (pymobiledevice3)"""
        if self.speaker1_platform != 'iOS' and self.speaker2_platform != 'iOS':
            return True  # iOS 디바이스 없음
        
        print(f"\n{'='*60}")
        print(f"📡 iOS 무선 터널 시작 중...")
        print(f"{'='*60}")
        print(f"💡 iPhone과 Mac이 같은 Wi-Fi에 연결되어 있어야 합니다.")
        print(f"💡 초기 1회는 USB로 페어링이 필요합니다.\n")
        
        try:
            # pymobiledevice3 remote start-tunnel 실행
            cmd = ['pymobiledevice3', 'remote', 'start-tunnel']
            
            # 백그라운드 프로세스로 시작
            self.tunnel_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            print(f"⏳ 터널 초기화 중... (10초 대기)")
            time.sleep(10)  # 터널 안정화 대기
            
            # 프로세스 상태 확인
            if self.tunnel_process.poll() is not None:
                # 프로세스가 종료됨
                stdout, stderr = self.tunnel_process.communicate()
                print(f"❌ 터널 시작 실패")
                print(f"   에러: {stderr}")
                print(f"\n💡 해결 방법:")
                print(f"   1. iPhone을 USB로 연결")
                print(f"   2. 터미널에서 실행: pymobiledevice3 remote tunneld")
                print(f"   3. 페어링 후 USB 제거")
                print(f"   4. 다시 테스트 시작\n")
                return False
            
            print(f"✅ iOS 무선 터널 시작 완료")
            print(f"   이제 USB 케이블을 제거해도 됩니다.")
            print(f"{'='*60}\n")
            return True
            
        except FileNotFoundError:
            print(f"❌ pymobiledevice3가 설치되지 않았습니다.")
            print(f"\n설치 명령어:")
            print(f"  pip install pymobiledevice3\n")
            return False
        except Exception as e:
            print(f"❌ 터널 시작 실패: {e}\n")
            return False
    
    def prepare_audio(self):
        """오디오 파일 준비"""
        print(f"🎵 오디오 파일 확인 중...")
        
        if not Path(self.speaker1_audio).exists():
            raise FileNotFoundError(f"화자1 오디오 파일을 찾을 수 없습니다: {self.speaker1_audio}")
        
        if not Path(self.speaker2_audio).exists():
            raise FileNotFoundError(f"화자2 오디오 파일을 찾을 수 없습니다: {self.speaker2_audio}")
        
        self.audio_files = {
            'speaker1': self.speaker1_audio,
            'speaker2': self.speaker2_audio,
        }
        
        print(f"✅ 화자1 오디오: {Path(self.speaker1_audio).name}")
        print(f"✅ 화자2 오디오: {Path(self.speaker2_audio).name}")
        print()
    
    @staticmethod
    def _get_ios_ixio_app_version(udid: str) -> str:
        """설치된 ixio 앱(com.lguplus.aicallagent) 버전 조회.

        우선순위:
          ① tidevice applist
          ② ideviceinstaller --list-apps
          ③ pymobiledevice3 Python API
        """
        import re as _re
        import json as _json
        bundle_id = 'com.lguplus.aicallagent'

        # ① tidevice applist
        try:
            cmd = ['tidevice']
            if udid:
                cmd += ['-u', udid]
            cmd += ['applist']
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            for line in r.stdout.splitlines():
                if bundle_id in line:
                    # 형식: com.xxx\tDisplayName\t1.2.3  또는 공백 구분
                    parts = line.strip().replace('\t', ' ').split()
                    ver = next(
                        (p for p in reversed(parts) if _re.match(r'^\d+\.\d+', p)),
                        None
                    )
                    if ver:
                        return ver
        except Exception:
            pass

        # ② ideviceinstaller --list-apps
        try:
            cmd = ['ideviceinstaller']
            if udid:
                cmd += ['-u', udid]
            cmd += ['--list-apps', '-o', 'list_user']
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            for line in r.stdout.splitlines():
                if bundle_id in line:
                    # 형식: com.xxx, "AppName", "1.2.3"
                    m = _re.search(r',\s*"[^"]+",\s*"([^"]+)"', line)
                    if m:
                        return m.group(1)
        except Exception:
            pass

        # ③ pymobiledevice3 Python API
        try:
            from pymobiledevice3.lockdown import create_using_usbmux  # type: ignore
            from pymobiledevice3.services.installation_proxy import InstallationProxyService  # type: ignore
            ld = create_using_usbmux(serial=udid if udid else None)
            apps = InstallationProxyService(lockdown=ld).get_apps('User')
            info = apps.get(bundle_id, {})
            ver = info.get('CFBundleShortVersionString') or info.get('CFBundleVersion', '')
            if ver:
                return ver
        except Exception:
            pass

        return '알 수 없음'

    def _get_ios_version_via_devicectl(self, udid):
        """xcrun xctrace로 iOS 버전 조회 → IosWdaManager에 위임."""
        return self.wda_manager.get_ios_version(udid)

    def _get_iphone_ip(self, device_name='JJ', udid=None):
        """iPhone IP 자동 조회 → IosWdaManager에 위임."""
        return self.wda_manager.get_iphone_ip(udid=udid)


    def _launch_wda_via_devicectl(self, udid, iphone_ip):
        """devicectl로 WDA 직접 기동 → IosWdaManager에 위임."""
        return self.wda_manager.launch_wda_via_devicectl(udid, iphone_ip)


    def _find_wda_url(self, iphone_ip, udid=None):
        """WDA 포트 확인 + 세션 정리 → IosWdaManager에 위임."""
        return self.wda_manager.find_wda_url(iphone_ip, udid=udid)


    def _clear_wda_sessions(self, wda_base_url):
        """WDA 세션 삭제 → IosWdaManager에 위임."""
        return self.wda_manager.clear_wda_sessions(wda_base_url)


    def _terminate_wda_process(self, udid):
        """WDA 프로세스 강제 종료 → IosWdaManager에 위임."""
        return self.wda_manager.terminate_wda_process(udid)


    def _free_port(self, port: int):
        """포트 강제 해제 → AppiumDeviceSetup에 위임."""
        return self.device_setup.free_port(port)


    def ensure_adb_connected(self, device_udid):
        """Android 무선 연결 시 adb connect 자동 실행 → AppiumDeviceSetup에 위임."""
        return self.device_setup.ensure_adb_connected(device_udid)

    def setup_device(self, device_udid, device_type='speaker1', platform='Android'):
        """Appium 드라이버 연결 → AppiumDeviceSetup에 위임."""
        driver, wait, wda_url = self.device_setup.setup_device(device_udid, device_type, platform)
        if driver:
            self.drivers[device_type] = driver
            self.wait_objects[device_type] = wait
            if platform == 'iOS' and wda_url:
                self._ios_wda_url = wda_url
            return True
        return False

    def _fast_poll_android_connected(self, udid: str,
                                      max_wait: float = 5.0,
                                      interval: float = 0.05,
                                      incoming_confirmed: bool = False) -> bool:
        """Android 통화 연결 상태를 고속 폴링 (기본 50ms 간격).

        incoming_confirmed=True: 이미 수신 감지 완료 → 초기 activity 확인 생략하고
                                  incomingcall dismiss 확인 즉시 시작.
        """
        deadline = time.time() + max_wait
        check_ixio_after = time.time() + 0.5  # incoming_confirmed면 0.5초 후 바로 확인

        seen_incoming_screen = incoming_confirmed  # 이미 수신 확인됐으면 True로 시작
        if not incoming_confirmed:
            check_ixio_after = time.time() + 1.0
            try:
                _init_top = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'dumpsys', 'activity', 'top'],
                    capture_output=True, text=True, timeout=2
                ).stdout
                seen_incoming_screen = 'com.lguplus.incomingcall' in _init_top
                if seen_incoming_screen:
                    print(f"  [fast_poll] 수신 화면 확인 → dismiss 대기 중")
                else:
                    print(f"  [fast_poll] 수신 화면 미확인 → telephony ACTIVE 폴링만 수행")
            except Exception:
                pass

        while time.time() < deadline:
            # ① telephony ACTIVE (일반 전화용)
            try:
                out = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'dumpsys', 'telephony.registry'],
                    capture_output=True, text=True, timeout=2
                ).stdout
                if 'mForegroundCallState=ACTIVE' in out:
                    return True
            except Exception:
                pass

            # ② 익시오 수신 화면 dismiss 확인 (VoIP — 1초 지연 후)
            if time.time() >= check_ixio_after:
                try:
                    top_out = subprocess.run(
                        ['adb', '-s', udid, 'shell', 'dumpsys', 'activity', 'top'],
                        capture_output=True, text=True, timeout=2
                    ).stdout
                    has_incoming = 'com.lguplus.incomingcall' in top_out
                    has_agent    = 'com.lguplus.aicallagent' in top_out

                    if has_incoming:
                        seen_incoming_screen = True  # 수신 화면 확인됨

                    if seen_incoming_screen and not has_incoming and has_agent:
                        # 수신 화면이 사라지고 aicallagent 가 포그라운드 = 통화 연결
                        return True
                    if seen_incoming_screen and not has_incoming and not has_agent:
                        # 수신 화면도 에이전트도 없음 = 거절/종료 → 연결 실패
                        return False
                except Exception:
                    pass

            time.sleep(interval)
        return False

    def _is_call_active_android(self, udid: str) -> bool:
        """ADB 다중 명령으로 Android 통화 연결 여부 확인.

        ⚠️ mCallState=2(OFFHOOK)는 발신자가 전화 거는 순간에도 2가 되므로 사용하지 않음.
           수신자가 수락해 양쪽 모두 연결됐을 때만 True 를 반환하도록:

        방법1: dumpsys telephony.registry  mForegroundCallState=ACTIVE (양쪽 연결 후만)
        방법2: dumpsys phone               mForegroundCall state: ACTIVE
        방법3: dumpsys telecom             mCallState: ACTIVE / STATE_ACTIVE
        """
        import re as _re

        # ① telephony.registry
        # mForegroundCallState=ACTIVE: 발신·수신 양쪽이 모두 연결됐을 때만 ACTIVE
        # mCallState=2(OFFHOOK)는 발신자가 전화 거는 순간에도 2가 되어 오감지 발생 → 사용 안 함
        try:
            out = subprocess.run(
                ['adb', '-s', udid, 'shell', 'dumpsys', 'telephony.registry'],
                capture_output=True, text=True, timeout=5
            ).stdout
            if 'mForegroundCallState=ACTIVE' in out:
                return True
        except Exception:
            pass

        # ② dumpsys phone (삼성 등 OEM 펌웨어 대응)
        # "mForegroundCall state: ACTIVE" 만 체크 — 통화 연결 후에만 나타남
        try:
            out2 = subprocess.run(
                ['adb', '-s', udid, 'shell', 'dumpsys', 'phone'],
                capture_output=True, text=True, timeout=5
            ).stdout
            if 'mForegroundCall state: ACTIVE' in out2:
                return True
            if 'Connection state: ACTIVE' in out2:
                return True
        except Exception:
            pass

        # ③ dumpsys telecom (Telecom 레이어 — 실제 통화 연결 상태)
        # CallState.ACTIVE = 1 로 표현되며 양쪽 연결 후에만 나타남
        # service call phone 3(0x00000002=OFFHOOK)은 발신자가 전화 거는 순간에도
        # 반환되므로 사용하지 않음
        try:
            out3 = subprocess.run(
                ['adb', '-s', udid, 'shell', 'dumpsys', 'telecom'],
                capture_output=True, text=True, timeout=5
            ).stdout
            if 'mCallState: ACTIVE' in out3 or 'STATE_ACTIVE' in out3:
                return True
        except Exception:
            pass

        return False

    def _is_call_active_ios(self, driver) -> bool:
        """Appium page_source 로 iOS 통화 연결 여부 확인.

        '끊기' 버튼만으로는 발신 중(RINGING) 상태에서도 True가 되어
        실제 연결(타이머 00:00 시작) 전에 오디오 재생이 시작됨.

        판별 조건 (AND):
          1. 통화 제어 버튼 (끊기 / 음소거 / 스피커 등) → 통화 화면임을 확인
          2. 통화 타이머 패턴 `\d{1,2}:\d{2}` 존재  → 실제 연결됨을 확인
             (전화번호는 하이픈 구분이므로 오탐 없음)
        """
        import re
        call_buttons = ['끊기', 'End', '음소거', 'Mute', '스피커', 'Speaker',
                        '통화 효음', '보류', 'Hold']
        timer_re = re.compile(r'\b\d{1,2}:\d{2}\b')
        try:
            src = driver.page_source
            has_call_button = any(
                f'name="{kw}"' in src or f'label="{kw}"' in src
                for kw in call_buttons
            )
            has_timer = bool(timer_re.search(src))
            return has_call_button and has_timer
        except Exception:
            pass
        return False

    def wait_for_call_connecting_state(self, roles: list[str] | None = None) -> bool:
        """통화 연결 확인 (수신자가 실제로 수락한 이후에만 True 반환).

        roles: 확인할 역할 목록. None이면 speaker1+speaker2 모두 확인.
               예) roles=['speaker1'] → 발신단만 확인.

        판별 전략:
          - Android(speaker1/2): mForegroundCallState=ACTIVE (양쪽 연결 후에만)
                                 ※ mCallState=2(OFFHOOK)는 발신자가 전화 거는
                                   순간에도 2가 되어 수신 전에도 True → 사용 안 함
          - iOS(speaker1/2):     Appium page_source에서 '끊기'/'음소거' 등
                                 통화 중에만 존재하는 UI 요소 확인

        타이머 패턴(\\d{2}:\\d{2})만으로는 키패드/전화번호 오탐 가능 → 사용 안 함.
        """
        print(f"⏳ 통화 연결 대기 중...")
        print(f"   통화 화면 UI 요소 확인 중...\n")

        max_wait_time = 60
        start_time    = time.time()

        # 확인에 사용할 단말·플랫폼 정보
        target_roles = roles if roles is not None else ['speaker1', 'speaker2']
        checks: list[tuple[str, str, object]] = []
        for role, platform in [('speaker1', self.speaker1_platform),
                                ('speaker2', self.speaker2_platform)]:
            if role not in target_roles:
                continue
            udid   = self.speaker1_device if role == 'speaker1' else self.speaker2_device
            driver = self.drivers.get(role)
            checks.append((role, platform, udid if platform == 'Android' else driver))

        while time.time() - start_time < max_wait_time:
            for role, platform, target in checks:
                if platform == 'Android' and target:
                    if self._is_call_active_android(target):
                        print(f"✅ 통화 연결 확인 [{role} / Android ADB]\n")
                        return True
                elif platform == 'iOS' and target:
                    if self._is_call_active_ios(target):
                        print(f"✅ 통화 연결 확인 [{role} / iOS UI]\n")
                        return True

            elapsed = int(time.time() - start_time)
            if elapsed > 0 and elapsed % 5 == 0:
                print(f"  ⏳ {elapsed}초 경과, 통화 연결 대기 중...")
            time.sleep(1)

        print(f"⚠️ {max_wait_time}초 내 통화 연결을 확인하지 못함 (통화가 실제로 연결되지 않았을 수 있음)\n")
        return False



    def play_audio_after_delay(self, delay=3):
        """지정된 시간 후 오디오 재생 (화자1·화자2 동시 시작)"""
        import threading
        print(f"⏰ {delay}초 대기 후 오디오 재생...")
        time.sleep(delay)

        print(f"\n{'='*60}")
        print(f"🔊 오디오 재생 시작")
        print(f"{'='*60}\n")

        s1_usb_order = self._usb_order_for_device(self.speaker1_output_device)
        s2_usb_order = self._usb_order_for_device(self.speaker2_output_device)

        # config.py PLAYBACK_VOLUME 읽기 (없으면 0.95 기본값)
        try:
            from config import PLAYBACK_VOLUME as _vol
            playback_volume = float(_vol)
        except (ImportError, AttributeError, ValueError):
            playback_volume = 0.95

        def _play_s1():
            try:
                audio_file = self.audio_files.get('speaker1')
                if audio_file:
                    proc = DeviceAudioPlayer.play_audio_to_device(
                        audio_file,
                        device=self.speaker1_output_device,
                        channel=self.speaker1_channel,
                        speaker_id='speaker1',
                        monitor=self.monitor_enabled,
                        usb_order=s1_usb_order,
                        volume=playback_volume,
                    )
                    if proc is not None:
                        self._audio_procs.append(proc)
                    print(f"✅ 화자1 오디오 재생 시작 "
                          f"(장치={self.speaker1_output_device if self.speaker1_output_device is not None else '기본'}, "
                          f"usb_order={s1_usb_order}, "
                          f"채널={self.speaker1_channel or '양쪽'}, "
                          f"volume={playback_volume:.2f}, "
                          f"모니터={'ON' if self.monitor_enabled else 'OFF'})\n")
                else:
                    print(f"⚠️ 화자1 오디오 파일이 설정되지 않음\n")
            except Exception as e:
                print(f"⚠️ 화자1 오디오 재생 실패: {e}\n")

        def _play_s2():
            try:
                audio_file2 = self.audio_files.get('speaker2')
                if audio_file2:
                    proc = DeviceAudioPlayer.play_audio_to_device(
                        audio_file2,
                        device=self.speaker2_output_device,
                        channel=self.speaker2_channel,
                        speaker_id='speaker2',
                        monitor=self.monitor_enabled,
                        usb_order=s2_usb_order,
                        volume=playback_volume,
                    )
                    if proc is not None:
                        self._audio_procs.append(proc)
                    print(f"✅ 화자2 오디오 재생 시작 "
                          f"(장치={self.speaker2_output_device if self.speaker2_output_device is not None else '기본'}, "
                          f"usb_order={s2_usb_order}, "
                          f"채널={self.speaker2_channel or '양쪽'}, "
                          f"volume={playback_volume:.2f}, "
                          f"모니터={'ON' if self.monitor_enabled else 'OFF'})\n")
                else:
                    print(f"⚠️ 화자2 오디오 파일이 설정되지 않음\n")
            except Exception as e:
                print(f"⚠️ 화자2 오디오 재생 실패: {e}\n")

        # 화자1·화자2 동시 재생 시작
        t1 = threading.Thread(target=_play_s1, daemon=True)
        t2 = threading.Thread(target=_play_s2, daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    
    def _play_audio_via_adb(self, udid: str, local_wav: str, speaker_id: str = 'speaker2') -> None:
        """wav 파일을 ADB로 Android 기기에 push 후 재생합니다.

        1. adb push  <local_wav>  /sdcard/Music/ixio_test_<speaker_id>.wav
        2. adb shell am start -a android.intent.action.VIEW (미디어 플레이어 기동)
        3. 스피커폰 ON (통화 중 상대방이 오디오를 들을 수 있도록)
        """
        remote_path = f'/sdcard/Music/ixio_test_{speaker_id}.wav'
        local_path  = Path(local_wav).resolve()

        print(f"📤 [{speaker_id}] ADB push: {local_path.name} → {remote_path}")
        try:
            push = subprocess.run(
                ['adb', '-s', udid, 'push', str(local_path), remote_path],
                capture_output=True, text=True, timeout=60
            )
            if push.returncode != 0:
                print(f"⚠️ [{speaker_id}] ADB push 실패: {push.stderr.strip()}")
                return
            print(f"  ✓ push 완료")
        except subprocess.TimeoutExpired:
            print(f"⚠️ [{speaker_id}] ADB push 시간 초과")
            return
        except Exception as e:
            print(f"⚠️ [{speaker_id}] ADB push 오류: {e}")
            return

        # 미디어 스캔 (MediaStore 갱신)
        try:
            subprocess.run(
                ['adb', '-s', udid, 'shell', 'am', 'broadcast',
                 '-a', 'android.intent.action.MEDIA_SCANNER_SCAN_FILE',
                 '-d', f'file://{remote_path}'],
                capture_output=True, text=True, timeout=10
            )
        except Exception:
            pass

        # 스피커폰 ON (통화 중 재생음이 상대방 마이크로 입력되도록)
        try:
            subprocess.run(
                ['adb', '-s', udid, 'shell', 'input', 'keyevent', 'KEYCODE_HEADSETHOOK'],
                capture_output=True, text=True, timeout=5
            )
        except Exception:
            pass

        # 재생: Intent로 기본 미디어 플레이어 실행
        print(f"▶️  [{speaker_id}] ADB 재생 시작: {remote_path}")
        try:
            play = subprocess.run(
                ['adb', '-s', udid, 'shell', 'am', 'start',
                 '-a', 'android.intent.action.VIEW',
                 '-d', f'file://{remote_path}',
                 '-t', 'audio/x-wav',
                 '--activity-clear-top'],
                capture_output=True, text=True, timeout=10
            )
            if play.returncode == 0:
                print(f"✅ [{speaker_id}] Android ADB 재생 시작\n")
            else:
                print(f"⚠️ [{speaker_id}] ADB 재생 Intent 실패: {play.stderr.strip()}")
                # fallback: ringtone 명령
                subprocess.run(
                    ['adb', '-s', udid, 'shell', 'media', 'play',
                     '--uri', f'file://{remote_path}'],
                    capture_output=True, text=True, timeout=10
                )
                print(f"  ↩️ [{speaker_id}] media play fallback 실행\n")
        except Exception as e:
            print(f"⚠️ [{speaker_id}] ADB 재생 실패: {e}\n")

    def _stop_audio_procs(self):
        """실행 중인 audio_player_worker subprocess를 모두 강제 종료합니다."""
        for proc in self._audio_procs:
            try:
                if proc.poll() is None:   # 아직 살아있으면
                    proc.terminate()
                    proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._audio_procs.clear()
        print("⏹️ 오디오 재생 subprocess 강제 종료 완료\n")

    def wait_for_audio_completion(self):
        """오디오 재생 완료 대기 (통화 강제 종료 감지 포함)"""
        import wave

        duration = 60.0  # fallback
        try:
            audio_file = self.audio_files.get('speaker1')
            if audio_file and Path(audio_file).exists():
                with wave.open(audio_file, 'rb') as wav:
                    frames = wav.getnframes()
                    rate = wav.getframerate()
                    duration = frames / float(rate)
        except Exception as e:
            print(f"⚠️ 오디오 길이 확인 실패: {e}, 기본 {duration:.0f}초 사용\n")

        print(f"⏰ 오디오 재생 시간: {duration:.1f}초")
        print(f"   재생 완료 대기 중 (통화 상태 감시)...\n")

        total_wait = duration + 2
        POLL_INTERVAL = 1.0
        start = time.time()
        call_miss_count = 0          # 통화 미감지 연속 횟수
        CALL_MISS_THRESHOLD = 4      # 4회 연속(4초) 미감지 시에만 강제 종료 처리

        while time.time() - start < total_wait:
            time.sleep(POLL_INTERVAL)

            # Android 통화 상태 폴링 (OFFHOOK/ACTIVE 유지 확인)
            # telephony.registry: mCallState=2 → 일반 단말
            # telecom: mState/state=ACTIVE → 업무 모드(Work Profile/MDM) 단말
            # ⚠️ telephony.registry 권한 제한 단말: 빈 출력 → 무조건 '미감지'로 오판 가능
            #   → 양쪽 모두 미감지일 때만 종료 처리
            if self.speaker2_platform == 'Android' and self.speaker2_device:
                try:
                    udid = self.speaker2_device
                    # 방법1: telephony.registry
                    reg_active = False
                    try:
                        reg_out = subprocess.run(
                            ['adb', '-s', udid, 'shell', 'dumpsys', 'telephony.registry'],
                            capture_output=True, text=True, timeout=3
                        ).stdout
                        reg_active = 'mCallState=2' in reg_out
                    except Exception:
                        pass

                    # 방법2: telecom (업무 모드 단말 대응)
                    telecom_active = False
                    if not reg_active:
                        import re as _re
                        try:
                            tel_out = subprocess.run(
                                ['adb', '-s', udid, 'shell', 'dumpsys', 'telecom'],
                                capture_output=True, text=True, timeout=3
                            ).stdout
                            telecom_active = bool(_re.search(
                                r'(?:mState|state):\s*(?:ACTIVE|DIALING)', tel_out
                            ))
                        except Exception:
                            pass

                    if not reg_active and not telecom_active:
                        call_miss_count += 1
                        if call_miss_count >= CALL_MISS_THRESHOLD:
                            print(f"\n⚠️ [통화 강제 종료 감지] telephony+telecom {call_miss_count}회 연속 미감지 → 오디오 중단 후 조기 종료\n")
                            self._stop_audio_procs()
                            return False
                        # 일시적 미감지는 무시하고 계속
                    else:
                        call_miss_count = 0  # 정상 감지되면 카운터 초기화
                except Exception:
                    pass  # adb 일시 오류는 무시하고 계속

            # iOS 통화 상태 폴링
            elif self.speaker2_platform == 'iOS':
                driver = self.drivers.get('speaker2')
                if driver:
                    try:
                        src = driver.page_source
                        if '끊기' not in src and '통화' not in src:
                            call_miss_count += 1
                            if call_miss_count >= CALL_MISS_THRESHOLD:
                                print(f"\n⚠️ [통화 강제 종료 감지] iOS 통화화면 {call_miss_count}회 연속 없음 → 오디오 중단 후 조기 종료\n")
                                self._stop_audio_procs()
                                return False
                        else:
                            call_miss_count = 0
                    except Exception:
                        pass

        print(f"✅ 오디오 재생 완료\n")
        return True
    
    # ── answer_call_on_speaker2: 전략 분리 (각 strategy를 별도 메서드로) ──────

    def answer_call_on_speaker2(self):
        """화자2에서 전화 받기.

        - Android(화자2): ADB KEYCODE_CALL 로 수신 → _answer_call_android_adb()
        - iOS(화자2):     5단계 전략 (기존 유지)
        """
        if self.speaker2_platform == 'Android':
            return self._answer_call_android_adb()

        # ── iOS 수신 (5단계 전략) ──────────────────────────────────────────
        driver = self.drivers.get('speaker2')
        if not driver:
            print(f"⚠️ 화자2 디바이스가 연결되지 않음\n")
            return False

        print(f"📱 화자2: 수신 대기 중...(iPhone)")
        max_wait_time = 30
        start_time = time.time()
        _source_dumped = False

        while time.time() - start_time < max_wait_time:
            try:
                if not _source_dumped:
                    try:
                        src = driver.page_source
                        dump_path = '/tmp/speaker2_incoming_source.xml'
                        with open(dump_path, 'w', encoding='utf-8') as f:
                            f.write(src)
                        import re as _re
                        labels = _re.findall(r'(?:label|name)="([^"]+)"', src)
                        print(f"  [진단] page_source 덤프 → {dump_path}")
                        print(f"  [진단] 감지된 label/name: {sorted(set(labels))[:20]}")
                    except Exception as _e:
                        print(f"  [진단] page_source 덤프 실패: {_e}")
                    finally:
                        _source_dumped = True

                if self._answer_strategy_answer_btn(driver):
                    return True
                if self._answer_strategy_lockscreen(driver):
                    return True
                if self._answer_strategy_accept_btn(driver):
                    return True
                if self._answer_strategy_coordinate_tap(driver, start_time):
                    return True

            except Exception as e:
                if int(time.time() - start_time) % 5 == 0:
                    try:
                        src = driver.page_source
                        if any(kw in src for kw in ["응답", "알림", "받기"]):
                            print(f"  페이지에 수신 관련 텍스트 존재 — 계속 시도 중...")
                    except Exception:
                        pass
            time.sleep(1)

        print(f"⚠️ 수신 버튼을 찾지 못했습니다.")
        if self._answer_strategy_wda_fallback(max_wait_time):
            return True
        print(f"❌ 화자2 수신 실패\n")
        return False

    @staticmethod
    def _detect_android_ringing(udid: str) -> bool:
        """단말 종류에 무관하게 RINGING 상태를 감지합니다.

        일반 단말: dumpsys telephony.registry → mCallState=1
        업무 모드(Work Profile/MDM) 단말: telephony.registry 권한 제한 가능 →
          dumpsys telecom 으로 추가 감지 (RINGING / STATE_RINGING)
        """
        # 방법1: telephony.registry (일반 단말 / 대부분)
        try:
            out = subprocess.run(
                ['adb', '-s', udid, 'shell', 'dumpsys', 'telephony.registry'],
                capture_output=True, text=True, timeout=3
            ).stdout
            if 'mCallState=1' in out:
                return True
        except Exception:
            pass

        # 방법2: telecom (업무 모드·MDM 단말 — telephony.registry 응답 없을 때)
        # ⚠️ 단순 'RINGING' 포함 체크는 금지
        #   telecom 출력에는 변수명(isRinging, mIsRinging 등)·이전 통화 잔류 텍스트로
        #   RINGING 문자열이 항상 포함될 수 있어 꺼짓 감지(false positive) 발생
        # → 실제 Call 객체의 상태값으로 한정 체크
        import re as _re
        try:
            out2 = subprocess.run(
                ['adb', '-s', udid, 'shell', 'dumpsys', 'telecom'],
                capture_output=True, text=True, timeout=3
            ).stdout
            # 'mState: RINGING' 또는 'state: RINGING' 형태만 인정
            if _re.search(r'(?:mState|state):\s*RINGING', out2):
                return True
        except Exception:
            pass

        return False

    @staticmethod
    def _detect_android_offhook(udid: str) -> bool:
        """단말 종류에 무관하게 OFFHOOK(통화 연결) 상태를 감지합니다."""
        # 방법1: telephony.registry
        try:
            v = subprocess.run(
                ['adb', '-s', udid, 'shell', 'dumpsys', 'telephony.registry'],
                capture_output=True, text=True, timeout=3
            ).stdout
            if 'mCallState=2' in v:
                return True
        except Exception:
            pass

        # 방법2: telecom (업무 모드 단말)
        import re as _re
        try:
            v2 = subprocess.run(
                ['adb', '-s', udid, 'shell', 'dumpsys', 'telecom'],
                capture_output=True, text=True, timeout=3
            ).stdout
            # 'mState: ACTIVE' 또는 'state: ACTIVE/DIALING' 형태만 인정
            if _re.search(r'(?:mState|state):\s*(?:ACTIVE|DIALING)', v2):
                return True
        except Exception:
            pass

        return False

    @classmethod
    def _accept_android_ringing_call(cls, udid: str) -> None:
        """RINGING 상태인 단말에 수신 수락 명령을 순차적으로 시도합니다.

        ⚠️ KEYCODE_CALL(5) / KEYCODE_HEADSETHOOK(79) 는 수락/종료 토글키이므로
           이미 OFFHOOK(통화 연결) 상태에서 전송하면 통화가 끊어집니다.
           각 전략 사이에 OFFHOOK 상태를 확인하고, 연결됐으면 즉시 중단합니다.

        전략 (단말 호환성 순서):
          ① telecom accept-ringing-call      — API 26+, 일반 단말 최우선
          ② input keyevent KEYCODE_CALL (5)  — 범용 fallback (①실패 시에만)
          ③ input keyevent KEYCODE_HEADSETHOOK (79) — 업무 모드 단말 (②실패 시에만)
          ④ am broadcast ANSWER intent       — 구형 단말 (③실패 시에만)
        """
        # ① telecom accept-ringing-call
        r1 = subprocess.run(
            ['adb', '-s', udid, 'shell', 'telecom', 'accept-ringing-call'],
            capture_output=True, text=True, timeout=5
        )
        print(f"  [워쳐]   ① telecom accept-ringing-call → rc={r1.returncode}"
              + (f" stderr={r1.stderr.strip()}" if r1.stderr.strip() else ""))
        time.sleep(0.5)
        if cls._detect_android_offhook(udid):
            print(f"  [워쳐]   ✅ ① 성공 — 나머지 전략 생략 (토글키 중복 방지)")
            return

        # ② KEYCODE_CALL — ①이 실패했을 때만 시도
        subprocess.run(
            ['adb', '-s', udid, 'shell', 'input', 'keyevent', '5'],
            capture_output=True, text=True, timeout=5
        )
        print(f"  [워쳐]   ② keyevent KEYCODE_CALL(5) 전송")
        time.sleep(0.5)
        if cls._detect_android_offhook(udid):
            print(f"  [워쳐]   ✅ ② 성공 — 나머지 전략 생략")
            return

        # ③ KEYCODE_HEADSETHOOK — ②도 실패했을 때만 시도
        subprocess.run(
            ['adb', '-s', udid, 'shell', 'input', 'keyevent', '79'],
            capture_output=True, text=True, timeout=5
        )
        print(f"  [워쳐]   ③ keyevent KEYCODE_HEADSETHOOK(79) 전송")
        time.sleep(0.5)
        if cls._detect_android_offhook(udid):
            print(f"  [워쳐]   ✅ ③ 성공 — 나머지 전략 생략")
            return

        # ④ am broadcast ANSWER — 구형·일부 업무 모드 단말 최후 수단
        subprocess.run(
            ['adb', '-s', udid, 'shell', 'am', 'broadcast',
             '-a', 'android.intent.action.ANSWER'],
            capture_output=True, text=True, timeout=5
        )
        print(f"  [워쳐]   ④ am broadcast ANSWER intent 전송")

    def _start_android_answer_watcher(self, answered_event: 'threading.Event',
                                       failed_event: 'threading.Event') -> None:
        """Android 수신 감지 백그라운드 워쳐 스레드.

        발신 전에 시작하여 RINGING 신호를 기다림.
        일반 단말 / 업무 모드(Work Profile/MDM) 단말 모두 지원.
        60초 내 미수신 시 failed_event 설정.
        """
        import threading
        udid = self.speaker2_device
        print(f"  [워쳐] Android 수신 감지 시작 (RINGING 폴링 중...)")

        deadline = time.time() + 60.0
        while time.time() < deadline:
            try:
                if self._detect_android_ringing(udid):
                    print(f"  [워쳐] ✅ RINGING 감지 → 수신 수락 시도")

                    # ── Step 1. 수락 명령 실행 ───────────────────────────────
                    self._accept_android_ringing_call(udid)

                    # ── Step 2. OFFHOOK 확인 (최대 15초) ────────────────────
                    # OFFHOOK = 수신단이 실제로 연결됨 = iPhone 타이머 00:00 시점
                    # 이 시점 이후에만 음원 재생.
                    # telephony.registry + telecom 이중 확인 (업무 모드 단말 대응)
                    offhook_deadline = time.time() + 15.0
                    offhook_confirmed = False
                    offhook_detected_at: float = 0.0
                    while time.time() < offhook_deadline:
                        try:
                            if self._detect_android_offhook(udid):
                                offhook_detected_at = time.time()
                                print(f"  [워쳐] ✅ OFFHOOK 확인 — 통화 연결됨 (타이머 00:00 기준)")
                                offhook_confirmed = True
                                break
                        except Exception:
                            pass
                        time.sleep(0.1)

                    if not offhook_confirmed:
                        print(f"  [워쳐] ❌ OFFHOOK 미확인(15초 초과) → 수신 실패로 처리")
                        failed_event.set()
                        return

                    # ── Step 3. answered_event 설정 → run()에서 음원 재생 ───
                    # 음원은 워쳐가 아닌 run()에서 OFFHOOK 확인 직후에 재생
                    # (타이밍: OFFHOOK 확인 = iPhone 00:00 = 음원 재생 시점)
                    try:
                        answered_event._offhook_ts = offhook_detected_at  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    answered_event.set()

                    def _log_audio_mode():
                        _dl = time.time() + 5.0
                        while time.time() < _dl:
                            try:
                                a = subprocess.run(
                                    ['adb', '-s', udid, 'shell', 'dumpsys', 'audio'],
                                    capture_output=True, text=True, timeout=3
                                ).stdout
                                if 'IN_CALL' in a or 'IN_COMMUNICATION' in a or 'mMode=3' in a:
                                    print(f"  [워쳐] ✅ Audio Mode IN_CALL 확인 (백그라운드 로그)")
                                    return
                            except Exception:
                                pass
                            time.sleep(0.3)
                        print(f"  [워쳐] ⚠️ Audio Mode IN_CALL 미확인 (5초 초과) — 참고용")
                    threading.Thread(target=_log_audio_mode, daemon=True).start()
                    return
            except Exception:
                pass
            time.sleep(0.3)

        print(f"  [워쳐] ❌ 60초 내 RINGING 미감지")
        failed_event.set()

    def _answer_call_android_adb(self) -> bool:
        """(deprecated - run()에서 더 이상 쟁접 호출안 함)
        백워드 워쳐는 _start_android_answer_watcher 사용.
        """
        import threading
        answered = threading.Event()
        failed   = threading.Event()
        threading.Thread(
            target=self._start_android_answer_watcher,
            args=(answered, failed), daemon=True
        ).start()
        if answered.wait(timeout=60.0):
            return True
        return False

    def end_call(self):
        """통화 종료

        화자1(iPhone)  → Appium '끊기' 버튼
        화자2(Android) → ADB KEYCODE_ENDCALL
        """
        print(f"📵 통화 종료 중...\n")

        # ── 화자1 종료 ────────────────────────────────────────────────────
        if self.speaker1_platform == 'iOS':
            driver1 = self.drivers.get('speaker1')
            if driver1:
                try:
                    hang_up_btn = driver1.find_element(AppiumBy.ACCESSIBILITY_ID, "끊기")
                    hang_up_btn.click()
                    print(f"✅ 화자1(iPhone): 통화 종료 완료\n")
                except Exception as e:
                    print(f"⚠️ 화자1(iPhone): '끊기' 버튼을 찾을 수 없습니다: {e}")
                    try:
                        driver1.execute_script("mobile: tap", {"x": 195, "y": 720})
                        print(f"  ✓ 좌표 탭으로 종료 시도\n")
                    except Exception:
                        print(f"💡 수동으로 통화를 종료해주세요.\n")
                    time.sleep(3)
        elif self.speaker1_platform == 'Android':
            try:
                result = subprocess.run(
                    ['adb', '-s', self.speaker1_device, 'shell', 'input', 'keyevent', 'KEYCODE_ENDCALL'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    print(f"✅ 화자1(Android): 통화 종료 완료 (ADB)\n")
                else:
                    print(f"⚠️ 화자1(Android): ADB 통화 종료 실패: {result.stderr}\n")
            except Exception as e:
                print(f"⚠️ 화자1(Android): ADB 통화 종료 실패: {e}\n")

        # ── 화자2 종료 ────────────────────────────────────────────────────
        if self.speaker2_platform == 'Android':
            try:
                result = subprocess.run(
                    ['adb', '-s', self.speaker2_device, 'shell', 'input', 'keyevent', 'KEYCODE_ENDCALL'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    print(f"✅ 화자2(Android): 통화 종료 완료 (ADB)\n")
                else:
                    print(f"⚠️ 화자2(Android): ADB 통화 종료 실패: {result.stderr}\n")
            except subprocess.TimeoutExpired:
                print(f"⚠️ 화자2(Android): ADB 명령어 시간 초과\n")
            except Exception as e:
                print(f"⚠️ 화자2(Android): ADB 통화 종료 실패: {e}\n")
        elif self.speaker2_platform == 'iOS':
            driver2 = self.drivers.get('speaker2')
            if driver2:
                try:
                    hang_up_btn = driver2.find_element(AppiumBy.ACCESSIBILITY_ID, "끊기")
                    hang_up_btn.click()
                    print(f"✅ 화자2(iPhone): 통화 종료 완료\n")
                except Exception as e:
                    print(f"⚠️ 화자2(iPhone): '끊기' 버튼을 찾을 수 없습니다: {e}")
                    print(f"💡 수동으로 통화를 종료해주세요.\n")
                    time.sleep(3)

        return True
    
    def teardown(self):
        """정리"""
        print(f"🔌 디바이스 연결 종료 중...\n")
        
        for key, driver in self.drivers.items():
            try:
                driver.quit()
                print(f"✅ {key} 연결 종료")
            except:
                pass
        
        # HTTP 서버 중지 (iOS용)
        try:
            if self.speaker1_platform == 'iOS' or self.speaker2_platform == 'iOS':
                self.audio_handler.stop_http_server()
        except:
            pass
        
        # 무선 터널 종료
        if self.tunnel_process:
            try:
                self.tunnel_process.terminate()
                self.tunnel_process.wait(timeout=5)
                print(f"✅ iOS 무선 터널 종료")
            except:
                try:
                    self.tunnel_process.kill()
                except:
                    pass
        
        # 포트 정리 (다음 테스트 실행 준비)
        for port in [8100, 8200, 8300]:
            self._free_port(port)

        print(f"\n{'='*60}\n")
    
    def run(self):
        """전체 테스트 실행"""
        try:
            # 0. macOS 기본 출력을 USB Audio Device로 고정
            #    (iOS Appium 세션 초기화 시 Core Audio 기본 장치 재배치 방지)
            lock_usb_output_for_test(verbose=True)

            # 1. 오디오 준비
            self.prepare_audio()
            
            # 2. 디바이스 연결
            # 화자1 (발신자)
            if not self.setup_device(self.speaker1_device, 'speaker1', platform=self.speaker1_platform):
                return False
            
            # 화자2 (수신자)
            if not self.setup_device(self.speaker2_device, 'speaker2', platform=self.speaker2_platform):
                print(f"⚠️ 화자2 연결 실패, 수동으로 전화를 받아주세요.")

            # Android 화자2: 홈 화면으로 이동 → 수신 시 전체화면 표시 보장
            if self.speaker2_platform == 'Android':
                try:
                    subprocess.run(
                        ['adb', '-s', self.speaker2_device, 'shell', 'input', 'keyevent', 'KEYCODE_HOME'],
                        capture_output=True, text=True, timeout=5
                    )
                    print(f"  ✓ 화자2(Android) 홈 화면으로 이동 완료")
                except Exception as e:
                    print(f"  ⚠️ 홈 화면 이동 실패: {e}")
            
            # 3. Android 화자2: 발신 전에 미리 수신 감지 워처 스레드 시작
            #    (발신 → 수신까지 3~5초 걸리므로 발신과 동시에 폴링 시작해야 RINGING 놓치지 않음)
            answered_event: 'threading.Event | None' = None
            failed_event:   'threading.Event | None' = None
            if self.speaker2_platform == 'Android':
                answered_event = threading.Event()
                failed_event   = threading.Event()
                threading.Thread(
                    target=self._start_android_answer_watcher,
                    args=(answered_event, failed_event),
                    daemon=True
                ).start()
                print(f"  ℹ️ Android 수신 워처 스레드 시작 (발신 전)")

            # 3-2. 키패드 열기 + 발신 (플랫폼별)
            if self.speaker1_platform == 'iOS':
                if not self.open_keypad_iphone('speaker1'):
                    return False
                # 발신 전 크래시 체크 (앱 재시작 직후 충돌 팝업 가능)
                sp1_driver = self.drivers.get('speaker1')
                if sp1_driver and self.crash_reporter and self.crash_reporter.detect_crash(sp1_driver):
                    self.crash_reporter.handle_crash(sp1_driver, extra_body="발신 전 단계에서 크래시 감지")
                    return 'crash'
                if not self.make_call_iphone(self.speaker2_number):
                    return False
            else:
                if not self.open_ixio_keypad('speaker1'):
                    return False
                if not self.make_call(self.speaker2_number):
                    return False

            # 4. 화자2에서 전화 받기
            call_connected = False
            if self.speaker2_platform == 'Android':
                # 워처 스레드가 RINGING 감지 → telecom accept → mCallState=2 → Audio IN_CALL
                # → answered_event 설정까지 대기 (최대 60초)
                print(f"📱 화자2: 수신 대기...(Android 워처 폴링 중)")
                if answered_event.wait(timeout=60.0):
                    # OFFHOOK 확인 완료 = iPhone 타이머 00:00 = 음원 재생 시점
                    # 음원은 항상 run()에서 재생 (워처 선행 예약 없음)
                    offhook_ts = getattr(answered_event, '_offhook_ts', time.time())
                    elapsed_since_offhook = time.time() - offhook_ts
                    print(f"✅ Android 수신 확인 완료 "
                          f"(OFFHOOK 기준 {elapsed_since_offhook * 1000:.0f}ms 경과 — 음원 재생 시작)")
                    call_connected = True
                else:
                    print(f"❌ Android 수신 실패 (60초 타임아웃) — 오디오 재생 건너뜀\n")
                    self.end_call()
                    return False

                # 발신단(iOS) 타이머 00:00 확인 — 백그라운드 (음원 재생 타이밍에 영향 없음)
                if self.speaker1_platform == 'iOS' and 'speaker1' in self.drivers:
                    def _check_sp1():
                        ok = self.wait_for_call_connecting_state(roles=['speaker1'])
                        print(f"  [sp1 확인] {'✅ 발신단(iOS) 타이머 00:00 확인' if ok else '⚠️ 발신단(iOS) 연결 확인 불가 (이미 재생 중)'}")
                    threading.Thread(target=_check_sp1, daemon=True).start()
            else:
                # iOS 화자2: 수신 시도 후 wait_for_call_connecting_state 로 확인
                if 'speaker2' in self.drivers:
                    self.answer_call_on_speaker2()
                call_connected = self.wait_for_call_connecting_state()
                if not call_connected:
                    print(f"❌ 통화 연결이 확인되지 않아 오디오 재생을 건너뜁니다.")
                    print(f"   통화 종료 후 테스트를 종료합니다.\n")
                    self.end_call()
                    return False

            # 5-1. iOS 오디오 라우팅 (USB-C iPhone은 iRig HD2 자동 라우팅)
            # Lightning iPhone의 경우에만 수동 라우팅 필요할 수 있음

            # 6-0. 통화 녹음 시작 (통화 연결 직후, 음원 재생 전)
            # 통화 시작 타임스탬프 기록 (수집 시 최신 파일 식별용)
            from datetime import datetime as _dt
            self._call_start_ts = _dt.now().strftime('%Y%m%d_%H%M%S')
            if self._call_recorder:
                self._call_recorder.start()            # 6. 오디오 재생 — OFFHOOK 확인 직후 (= iPhone 타이머 00:00 기준)
            # 워처에서 선행 예약 없이 항상 여기서 재생
            self.play_audio_after_delay(delay=0)
            
            # 7. 오디오 재생 완료 대기 (통화 강제 종료 감지 포함)
            call_completed = self.wait_for_audio_completion()

            # 발신단(iOS) 크래시 체크 — 통화/재생 중 충돌 발생 여부 확인
            sp1_driver = self.drivers.get('speaker1')
            if sp1_driver and self.crash_reporter and self.crash_reporter.detect_crash(sp1_driver):
                self.crash_reporter.handle_crash(sp1_driver, extra_body="오디오 재생 완료 후 크래시 감지")
                if self._call_recorder and self._call_recorder.is_recording:
                    self._call_recorder.stop()
                self.end_call()
                return 'crash'

            # 7-1. 통화 녹음 종료 (오디오 완료 후, 통화 종료 전)
            if self._call_recorder and self._call_recorder.is_recording:
                self._call_recorder.stop()

            # 8. 통화 종료
            self.end_call()

            # 8-1. 통화 종료 후 음원 수집 + 믹스
            #   ① iOS(발신): ixio 앱 녹음 파일 pull
            #   ② Android(수신): 통화 녹음 파일 ADB pull
            #   ③ 두 파일 믹스 → 단일 통화 음원 WAV
            self._collected_audio: dict = {}
            if _CALL_AUDIO_COLLECTOR_AVAILABLE:
                # Android UDID 결정 (speaker1/speaker2 중 Android 쪽)
                android_udid = ""
                if self.speaker2_platform == 'Android':
                    android_udid = self.speaker2_device
                elif self.speaker1_platform == 'Android':
                    android_udid = self.speaker1_device

                # iOS UDID / driver 결정
                ios_udid   = ""
                ios_driver = None
                if self.speaker1_platform == 'iOS':
                    ios_udid   = self.speaker1_device
                    ios_driver = self.drivers.get('speaker1')
                elif self.speaker2_platform == 'iOS':
                    ios_udid   = self.speaker2_device
                    ios_driver = self.drivers.get('speaker2')

                # Android 녹음 대기 시간 config 읽기
                _android_wait = 5.0
                try:
                    from config import ANDROID_RECORDING_WAIT_SEC
                    _android_wait = float(ANDROID_RECORDING_WAIT_SEC)
                except (ImportError, AttributeError):
                    pass

                if android_udid:
                    collector = CallAudioCollector(
                        android_udid=android_udid,
                        ios_driver=ios_driver,
                        ios_udid=ios_udid,
                        call_start_ts=self._call_start_ts,
                        android_wait_sec=_android_wait,
                    )
                    self._collected_audio = collector.collect_and_mix()
                    mixed = self._collected_audio.get('mixed_path')
                    if mixed:
                        print(f"🎧 통화 믹스 음원: {mixed}")
                else:
                    print("  ⚠️ Android UDID 없음 → 통화 음원 수집 건너뜀")

            if not call_completed:
                print(f"\n{'='*60}")
                print(f"⚠️ 통화가 강제 종료되어 테스트가 조기 종료되었습니다.")
                print(f"{'='*60}\n")
                return 'retry'  # 동일 회차 재시작 신호 (exit code 2)

            print(f"\n{'='*60}")
            print(f"✅ 테스트 완료!")
            print(f"{'='*60}\n")

            # 수집된 음원 경로를 결과에 포함하여 반환
            collected = getattr(self, '_collected_audio', {})
            return {
                'success': True,
                'ios_recording':     str(collected.get('ios_path')     or ''),
                'android_recording': str(collected.get('android_path') or ''),
                'mixed_recording':   str(collected.get('mixed_path')   or ''),
            }
            
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"❌ 테스트 실패: {e}")
            print(f"{'='*60}\n")
            return False
            
        finally:
            time.sleep(2)
            self.teardown()
            restore_default_devices(verbose=True)


def main():
    """메인 실행"""
    parser = argparse.ArgumentParser(description='익시오 통화 자동화 테스트')
    parser.add_argument('--speaker1-device', default='auto', help='화자1 디바이스 UDID (기본: auto 자동감지)')
    parser.add_argument('--speaker2-device', default='auto', help='화자2 디바이스 UDID (기본: auto 자동감지)')
    parser.add_argument('--speaker1-number', required=True, help='화자1 전화번호')
    parser.add_argument('--speaker2-number', required=True, help='화자2 전화번호')
    parser.add_argument('--speaker1-audio', required=True, help='화자1 오디오 파일 경로')
    parser.add_argument('--speaker2-audio', required=True, help='화자2 오디오 파일 경로')
    parser.add_argument('--speaker1-output-device', default=None, help='화자1 오디오 출력 장치 ID (정수) - list_audio_devices로 확인')
    parser.add_argument('--speaker2-output-device', default=None, help='화자2 오디오 출력 장치 ID (정수) - list_audio_devices로 확인')
    parser.add_argument('--speaker1-channel', default=None, choices=['L', 'R'], help='화자1 스테레오 채널 분리: L=왼쪽, R=오른쪽 (생략 시 양쪽)')
    parser.add_argument('--speaker2-channel', default=None, choices=['L', 'R'], help='화자2 스테레오 채널 분리: L=왼쪽, R=오른쪽 (생략 시 양쪽)')
    parser.add_argument('--monitor', action='store_true', help='통화 중 맥북 스피커로 실시간 모니터링 활성화')
    
    args = parser.parse_args()
    
    tester = IxioAutomatedTest(
        speaker1_device=args.speaker1_device,
        speaker2_device=args.speaker2_device,
        speaker1_number=args.speaker1_number,
        speaker2_number=args.speaker2_number,
        speaker1_audio=args.speaker1_audio,
        speaker2_audio=args.speaker2_audio,
        speaker1_output_device=args.speaker1_output_device,
        speaker2_output_device=args.speaker2_output_device,
        speaker1_channel=args.speaker1_channel,
        speaker2_channel=args.speaker2_channel,
        monitor=args.monitor,
    )

    # SIGTERM 핸들러: 종료 버튼 → end_call() 먼저 실행하여 기기 통화를 끊고 종료
    def _sigterm_handler(signum, frame):
        print("\n🛑 SIGTERM 수신 → 오디오 중지 + 통화 종료 후 프로세스 종료 중...")
        try:
            tester._stop_audio_procs()   # ← 오디오 worker subprocess 즉시 종료
        except Exception as e:
            print(f"  ⚠️ _stop_audio_procs 중 오류: {e}")
        try:
            tester.end_call()
        except Exception as e:
            print(f"  ⚠️ end_call 중 오류: {e}")
        try:
            tester.teardown()
        except Exception:
            pass
        print("✅ 정상 종료됨")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm_handler)

    result = tester.run()
    if result == 'retry':
        sys.exit(2)   # 통화 강제 종료 → 동일 회차 재시작
    elif result == 'crash':
        sys.exit(3)   # 앱 크래시 감지 → 재시작 (로그/메일 이미 처리됨)
    elif result:
        sys.exit(0)   # 정상 완료
    else:
        sys.exit(1)   # 실패


if __name__ == '__main__':
    main()
