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
from audio_handler import AudioHandler
from ios_wda_manager import IosWdaManager
from appium_device_setup import AppiumDeviceSetup
from ios_call_handler import IosCallHandlerMixin
from android_call_handler import AndroidCallHandlerMixin
from answer_strategies import AnswerStrategiesMixin
from call_state_mixin import CallStateMixin
from audio_playback_mixin import AudioPlaybackMixin
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
    from mixer_recorder import MixerRecorder
    _MIXER_RECORDER_AVAILABLE = True
except ImportError:
    _MIXER_RECORDER_AVAILABLE = False
    MixerRecorder = None  # type: ignore

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


class IxioAutomatedTest(
        IosCallHandlerMixin,
        AndroidCallHandlerMixin,
        AnswerStrategiesMixin,
        CallStateMixin,
        AudioPlaybackMixin,
):
    """익시오 앱 자동화 테스트 (GUI 버전)"""
    
    def __init__(self, speaker1_device, speaker2_device, speaker1_number, speaker2_number, speaker1_audio, speaker2_audio,
                 speaker1_output_device=None, speaker2_output_device=None,
                 speaker1_channel=None, speaker2_channel=None,
                 speaker1_rec_channel=None, speaker2_rec_channel=None,
                 speaker1_output_pair=None, speaker2_output_pair=None,
                 monitor=False,
                 tc_type: str = '', screenshot_dir: str = '',
                 appium_port_android: int = 4723, appium_port_ios: int = 4724,
                 recording_mode: str = 'extract',
                 android_app_package: str = 'com.lguplus.aicallagent',
                 android_app_activity: str = '',
                 ios_app_bundle_id: str = 'com.lguplus.aicallagent',
                 carrier: str = ''):
        # ── 1. UDID 자동 감지 ───────────────────────────────────────────────
        speaker1_device, speaker2_device = self._resolve_udids(speaker1_device, speaker2_device)
        self.speaker1_device = speaker1_device
        self.speaker2_device = speaker2_device

        # ── 2. 기본 속성 ─────────────────────────────────────────────────────
        self.speaker1_number = speaker1_number
        self.speaker2_number = speaker2_number
        self.speaker1_audio  = speaker1_audio
        self.speaker2_audio  = speaker2_audio

        # ── 2b. 테스트 대상 앱 패키지/번들 ───────────────────────────────────
        self.android_app_package  = android_app_package
        self.android_app_activity = android_app_activity or ''
        self.ios_app_bundle_id    = ios_app_bundle_id

        # ── 2c. 앱 패키지 → 파일명 태그 매핑 ─────────────────────────────────
        _APP_TAG_MAP = {
            'com.lguplus.aicallagent': 'ixiO',
            'com.samsung.android.dialer': 'Samsung',
            'com.skt.prod.dialer': 'Adot',
            'com.apple.mobilephone': 'Apple',
            'com.sktelecom.tphone': 'Adot',
        }
        self.app_tag = _APP_TAG_MAP.get(android_app_package,
                       _APP_TAG_MAP.get(ios_app_bundle_id, 'ixiO'))

        # ── 2d. 통신사 태그 (파일명 접미사) ───────────────────────────────────
        _CARRIER_TAG_MAP = {
            'lguplus': 'LGU+',
            'skt': 'SKT',
            'kt': 'KT',
        }
        self.carrier_tag = _CARRIER_TAG_MAP.get(carrier, '')

        # ── 3. 플랫폼 감지 ────────────────────────────────────────────────────
        # iOS UDID: 8+16 헥스 문자 + 하이픈 (예: 00008150-00110C341E38401C)
        # Android : 그 외 모든 형태 (USB 시리얼, IP:port, TLS mDNS UDID 등)
        import re as _re
        _IOS_UDID_RE = _re.compile(r'^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}$')
        def _is_ios(udid: str) -> bool:
            return bool(_IOS_UDID_RE.match(udid))
        self.speaker1_platform = 'iOS' if _is_ios(speaker1_device) else 'Android'
        self.speaker2_platform = 'iOS' if _is_ios(speaker2_device) else 'Android'

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
        self.speaker1_rec_channel = speaker1_rec_channel  # CONNECT 6 녹음 채널 (예: "6,7")
        self.speaker2_rec_channel = speaker2_rec_channel
        self.speaker1_output_pair = speaker1_output_pair  # CONNECT 6 출력 채널 쌍 (예: "0,1")
        self.speaker2_output_pair = speaker2_output_pair
        self.monitor_enabled  = monitor

        # ── 6. 런타임 상태 초기화 ─────────────────────────────────────────────
        self.drivers        = {}
        self.wait_objects   = {}
        self.audio_handler  = AudioHandler()
        self.audio_files    = {}
        self.tunnel_process = None       # pymobiledevice3 터널 프로세스
        self._ios_wda_url: str | None = None  # iOS WDA URL (동적 감지)
        self._audio_procs: list = []     # 재생 중인 audio_player_worker subprocess 목록

        self.appium_server_android = f'http://127.0.0.1:{appium_port_android}'
        self.appium_server_ios     = f'http://127.0.0.1:{appium_port_ios}'

        self.wda_manager  = IosWdaManager()
        self.device_setup = AppiumDeviceSetup(
            appium_server_android=self.appium_server_android,
            appium_server_ios=self.appium_server_ios,
            wda_manager=self.wda_manager,
            android_app_package=self.android_app_package,
            android_app_activity=self.android_app_activity,
            ios_app_bundle_id=self.ios_app_bundle_id,
        )

        # ── 8. 크래시 리포터 초기화 ──────────────────────────────────────────
        ios_udid = speaker1_device if self.speaker1_platform == 'iOS' else (
                   speaker2_device if self.speaker2_platform == 'iOS' else "")
        and_udid = speaker1_device if self.speaker1_platform == 'Android' else (
                   speaker2_device if self.speaker2_platform == 'Android' else "")
        self.crash_reporter = (
            CrashReporter(ios_udid=ios_udid, android_udid=and_udid,
                         ios_bundle_id=self.ios_app_bundle_id)
            if _CRASH_REPORTER_AVAILABLE else None
        )

        # ── 9. 통화 녹음기 초기화 ─────────────────────────────────────────────
        self._recording_mode = recording_mode  # 'extract' | 'direct'
        self._mixer_recorder = None  # MixerRecorder (direct 모드용)

        if recording_mode == 'direct':
            # 직접 녹음 모드: iOS → CONNECT 6, Android → 별도 장치(Sound Blaster 등)
            if _MIXER_RECORDER_AVAILABLE:
                ios_rec_ch = self._parse_rec_channels(
                    speaker1_rec_channel if self.speaker1_platform == 'iOS' else speaker2_rec_channel
                )
                android_rec_ch = self._parse_rec_channels(
                    speaker1_rec_channel if self.speaker1_platform == 'Android' else speaker2_rec_channel
                )
                # Android 출력(재생) 장치
                android_out_dev = (
                    self.speaker1_output_device if self.speaker1_platform == 'Android'
                    else self.speaker2_output_device
                )
                # android_rec_channel이 명시된 경우(CONNECT 6 Loopback 사용) →
                # Sound Blaster를 별도 녹음 장치로 쓰지 않음 (CONNECT 6 단일 장치 모드)
                android_rec_dev = (
                    None if android_rec_ch is not None
                    else android_out_dev
                )
                self._mixer_recorder = MixerRecorder(
                    ios_channels=ios_rec_ch,
                    android_channels=android_rec_ch,
                    android_device_index=android_rec_dev,
                    tc_type=tc_type,
                    app_name=self.app_tag,
                    carrier_tag=self.carrier_tag,
                )
                if self._mixer_recorder._ios_device_idx is not None:
                    mode_desc = f"CONNECT 6 × 2대 (Android dev={self._mixer_recorder._device_idx}, iOS dev={self._mixer_recorder._ios_device_idx})"
                elif android_rec_ch is not None:
                    mode_desc = f"CONNECT 6 단일 장치 (iOS ch={ios_rec_ch}, Android ch={android_rec_ch})"
                else:
                    mode_desc = "CONNECT 6 단일 장치"
                print(f"🎛️ [MixerRecorder] 직접 녹음 모드 초기화 완료 ({mode_desc})", flush=True)
            else:
                print("⚠️ mixer_recorder 모듈 없음 → 직접 녹음 불가", flush=True)
            self._call_recorder = None
        else:
            # 기존 G8 녹음기 (extract 모드에서도 보조 녹음 가능)
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
                    record_speaker2=False,
                    app_name=self.app_tag,
                    carrier_tag=self.carrier_tag,
                )
                if (_CALL_RECORDER_AVAILABLE and _recording_enabled) else None
            )

        # ── 10. 통화 종료 후 수집 수단 초기화 ────────────────────────────────
        # iOS 앱 녹음 pull + Android 통화 녹음 ADB pull + 믹스
        self._call_audio_collector: object = None  # CallAudioCollector | None  (run() 에서 생성)
        # 통화 시작 타임스탬프 (수집 시 최신 파일 식별에 사용)
        self._call_start_ts: str = ""

        # ── 11. TC 타입 및 스크린샷 저장 경로 ─────────────────────────────────
        self.tc_type        = tc_type        # '' (일반) | 'TC_00' | 'TC_01' | 'TC_02' | 'TC_03' | 'TC_04'
        import os as _os
        from datetime import datetime as _dt_cls
        _base_ss_dir = screenshot_dir or _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
            '..', 'audio_files', 'screenshots'
        )
        # 날짜별 하위 폴더 (YYYY-MM-DD)
        self.screenshot_dir = _os.path.join(_base_ss_dir, _dt_cls.now().strftime('%Y-%m-%d'))
        if self._call_recorder:
            print(f"🎙️ [CallRecorder] 통화 녹음 준비 완료 "
                  f"(S1={self.speaker1_platform}, S2={self.speaker2_platform})")

        # ── 7. 설정 요약 출력 ─────────────────────────────────────────────────
        self._print_config(raw_s1, raw_s2)

    # ── 생성자 헬퍼 메서드 ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_rec_channels(raw: str | None) -> tuple[int, ...] | None:
        """녹음 채널 문자열("6,7")을 0-based 인덱스 튜플로 변환합니다.

        Returns:
            (6, 7) 같은 튜플 또는 None (자동 기본값 사용)
        """
        if not raw or not raw.strip():
            return None
        try:
            return tuple(int(x.strip()) for x in raw.split(','))
        except (ValueError, TypeError):
            return None

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
                print(f"ℹ️  화자1·화자2 출력 장치 동일(index={s1}) — CONNECT 6 단일 장치 모드")
            list_usb_audio_devices()
            return s1, s2
        except Exception as e:
            print(f"⚠️ 오디오 장치 자동 해결 실패: {e}")
            return raw_s1, raw_s2

    def _print_config(self, raw_s1, raw_s2) -> None:
        """테스트 설정 요약을 콘솔에 출력합니다."""
        from device_detector import get_device_nickname
        from device_detector import _adb_prop

        def _android_label(udid: str) -> str:
            model = _adb_prop(udid, 'ro.product.model') if udid else ''
            nick  = get_device_nickname(model)
            if nick and nick != model:
                return f"{nick} ({model})"
            return model or udid

        auto_tag = ' (locationID 자동 해결)'
        print(f"\n{'='*60}")
        print(f"🎯 익시오 통화 테스트 설정")
        if self.tc_type:
            print(f"  📋 TC 모드: {self.tc_type}")
        print(f"  📦 Android 앱: {self.android_app_package}")
        print(f"  📦 iOS 앱: {self.ios_app_bundle_id}")
        print(f"{'='*60}")

        s1_label = _android_label(self.speaker1_device) if self.speaker1_platform == 'Android' else self.speaker1_device
        print(f"화자1: {s1_label} ({self.speaker1_number})")
        print(f"  플랫폼: {self.speaker1_platform}")
        if self.speaker1_platform == 'iOS':
            _v1 = self._get_ios_ixio_app_version(self.speaker1_device)
            print(f"  ixio 앱 버전: {_v1}")
        print(f"  오디오: {self.speaker1_audio}")
        dev1 = self.speaker1_output_device if self.speaker1_output_device is not None else '기본'
        print(f"  출력장치: {dev1}" + ("" if raw_s1 is not None else auto_tag))
        print(f"  채널: {self.speaker1_channel or '양쪽'}")
        s2_label = _android_label(self.speaker2_device) if self.speaker2_platform == 'Android' else self.speaker2_device
        print(f"화자2: {s2_label} ({self.speaker2_number})")
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
    
    def _get_ios_ixio_app_version(self, udid: str) -> str:
        """설치된 테스트 앱 버전 조회.

        우선순위:
          ① tidevice applist
          ② ideviceinstaller --list-apps
          ③ pymobiledevice3 Python API
        """
        import re as _re
        import json as _json
        bundle_id = self.ios_app_bundle_id

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
        from thread_safe_driver import ThreadSafeDriver
        driver, wait, wda_url = self.device_setup.setup_device(device_udid, device_type, platform)
        if driver:
            driver = ThreadSafeDriver(driver)
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
        # 수신 화면 패키지: 앱별 패턴 + 공통 incallui
        _incoming_pkgs = self._all_incoming_pkgs
        def _has_incoming_screen(output: str) -> bool:
            return any(pkg in output for pkg in _incoming_pkgs)

        if not incoming_confirmed:
            check_ixio_after = time.time() + 1.0
            try:
                _init_top = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'dumpsys', 'activity', 'top'],
                    capture_output=True, text=True, timeout=2
                ).stdout
                seen_incoming_screen = _has_incoming_screen(_init_top)
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

            # ② 수신 화면 dismiss 확인 (VoIP / in-call UI — 1초 지연 후)
            if time.time() >= check_ixio_after:
                try:
                    top_out = subprocess.run(
                        ['adb', '-s', udid, 'shell', 'dumpsys', 'activity', 'top'],
                        capture_output=True, text=True, timeout=2
                    ).stdout
                    has_incoming = _has_incoming_screen(top_out)
                    has_agent    = self.android_app_package in top_out

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

    # ── 수신 오케스트레이터 ───────────────────────────────────────────────

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
                        _detected_app = self._detect_ios_incoming_app(src)
                        print(f"  [진단] page_source 덤프 → {dump_path}")
                        print(f"  [진단] 수신 앱 판별: {_detected_app}")
                        print(f"  [진단] 감지된 label/name: {sorted(set(labels))[:20]}")
                    except Exception as _e:
                        print(f"  [진단] page_source 덤프 실패: {_e}")
                    finally:
                        _source_dumped = True

                if self._answer_strategy_answer_btn(driver):
                    return True
                if self._answer_strategy_lockscreen(driver):
                    return True
                if self._answer_strategy_notification_banner(driver, start_time):
                    return True
                if self._answer_strategy_accept_btn(driver):
                    return True
                if self._answer_strategy_coordinate_tap(driver, start_time):
                    return True

            except Exception as e:
                if int(time.time() - start_time) % 5 == 0:
                    try:
                        src = driver.page_source
                        if any(kw in src for kw in ["응답", "알림", "받기", "전화 수신"]):
                            print(f"  페이지에 수신 관련 텍스트 존재 — 계속 시도 중...")
                    except Exception:
                        pass
            time.sleep(1)

        print(f"⚠️ 수신 버튼을 찾지 못했습니다.")
        if self._answer_strategy_wda_fallback(max_wait_time):
            return True
        print(f"❌ 화자2 수신 실패\n")
        return False


    def end_call(self):
        """통화 종료

        Android가 있으면 ADB KEYCODE_ENDCALL 먼저 실행 → iOS는 자동 종료됨.
        Android가 없는 경우에만 iOS Appium '끊기' 버튼 사용.
        """
        print(f"📵 통화 종료 중...\n")

        # ── Android 우선 종료 (ADB) ────────────────────────────────────────
        # ADB ENDCALL은 즉시 실행되며, 한쪽이 끊으면 상대방(iOS)도 자동 종료됨.
        # iOS의 find_element("끊기")는 Appium 타임아웃(30초)까지 블로킹될 수 있어
        # Android 보다 나중에 처리하거나 생략한다.
        android_ended = False
        for role, platform, device in [
            ('speaker1', self.speaker1_platform, self.speaker1_device),
            ('speaker2', self.speaker2_platform, self.speaker2_device),
        ]:
            if platform == 'Android':
                try:
                    result = subprocess.run(
                        ['adb', '-s', device, 'shell', 'input', 'keyevent', 'KEYCODE_ENDCALL'],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        print(f"✅ {role}(Android): 통화 종료 완료 (ADB)\n")
                        android_ended = True
                    else:
                        print(f"⚠️ {role}(Android): ADB 통화 종료 실패: {result.stderr}\n")
                except subprocess.TimeoutExpired:
                    print(f"⚠️ {role}(Android): ADB 명령어 시간 초과\n")
                except Exception as e:
                    print(f"⚠️ {role}(Android): ADB 통화 종료 실패: {e}\n")

        # ── iOS 종료 (Android로 이미 끊긴 경우 생략) ─────────────────────
        # Android ENDCALL 성공 시 iOS는 이미 통화 종료 상태이므로
        # Appium find_element 호출을 건너뛰어 불필요한 대기를 방지한다.
        if not android_ended:
            for role, platform in [
                ('speaker1', self.speaker1_platform),
                ('speaker2', self.speaker2_platform),
            ]:
                if platform == 'iOS':
                    driver = self.drivers.get(role)
                    if driver:
                        try:
                            hang_up_btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, "끊기")
                            hang_up_btn.click()
                            print(f"✅ {role}(iPhone): 통화 종료 완료\n")
                        except Exception as e:
                            print(f"⚠️ {role}(iPhone): '끊기' 버튼을 찾을 수 없습니다: {e}")
                            try:
                                driver.execute_script("mobile: tap", {"x": 195, "y": 720})
                                print(f"  ✓ 좌표 탭으로 종료 시도\n")
                            except Exception:
                                print(f"💡 수동으로 통화를 종료해주세요.\n")
                            time.sleep(3)

        return True

    # ── 재생 시작 타임스탬프 동기화 헬퍼 ─────────────────────────────────────

    @staticmethod
    def _clean_audio_started_ts_files():
        """이전 세션의 /tmp/audio_started_*.ts 파일을 삭제합니다."""
        import glob, tempfile, os
        for f in glob.glob(os.path.join(tempfile.gettempdir(), 'audio_started_*.ts')):
            try:
                os.remove(f)
            except OSError:
                pass

    def _sync_play_start_time(self, timeout: float = 10.0):
        """subprocess가 기록한 재생 시작 타임스탬프를 읽어 MixerRecorder에 전달합니다.

        /tmp/audio_started_{speaker_id}.ts 파일을 폴링하여,
        speaker1/speaker2 중 가장 빠른(earliest) 타임스탬프를 set_play_start_time()으로 설정합니다.
        """
        if not self._mixer_recorder:
            return
        import tempfile, os
        ts_dir = tempfile.gettempdir()
        targets = [
            os.path.join(ts_dir, 'audio_started_speaker1.ts'),
            os.path.join(ts_dir, 'audio_started_speaker2.ts'),
        ]
        deadline = time.time() + timeout
        earliest = None
        found = set()
        while time.time() < deadline and len(found) < len(targets):
            for p in targets:
                if p in found:
                    continue
                try:
                    with open(p, 'r') as f:
                        ts = float(f.read().strip())
                    found.add(p)
                    if earliest is None or ts < earliest:
                        earliest = ts
                except (FileNotFoundError, ValueError):
                    pass
            if len(found) < len(targets):
                time.sleep(0.1)
        if earliest is not None:
            self._mixer_recorder.set_play_start_time(earliest)
            # 음원 길이도 전달 → trailing silence 제거에 사용
            try:
                import wave
                audio_file = self.audio_files.get('speaker1')  # type: ignore[attr-defined]
                if audio_file and Path(audio_file).exists():
                    with wave.open(audio_file, 'rb') as wav:
                        dur = wav.getnframes() / float(wav.getframerate())
                    self._mixer_recorder.set_play_duration(dur)
            except Exception:
                pass
        else:
            print("⚠️ [TIMING] 재생 시작 타임스탬프를 감지하지 못했습니다 (트리밍 건너뜀)", flush=True)

    def _tap_video_call_popup_adb(self, udid: str, role: str, timeout: float = 5.0):
        """ADB uiautomator dump 로 '보이는 전화' 팝업을 탐색하여 input tap 으로 클릭.
        UiAutomator2 세션이 죽었을 때 폴백으로 사용."""
        import xml.etree.ElementTree as _ET
        import re as _re
        import subprocess
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                # UI hierarchy dump
                subprocess.run(
                    ['adb', '-s', udid, 'shell', 'uiautomator', 'dump', '/sdcard/window_dump.xml'],
                    capture_output=True, timeout=5,
                )
                result = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'cat', '/sdcard/window_dump.xml'],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode != 0 or not result.stdout.strip():
                    time.sleep(0.5)
                    continue
                root = _ET.fromstring(result.stdout.strip().encode('utf-8'))
                parent_bounds = None
                for node in root.iter():
                    for child in list(node):
                        if child.get('content-desc') == '보이는 전화':
                            parent_bounds = node.get('bounds')
                            break
                    if parent_bounds:
                        break
                if not parent_bounds:
                    time.sleep(0.5)
                    continue
                nums = list(map(int, _re.findall(r'\d+', parent_bounds)))
                cx = (nums[0] + nums[2]) // 2
                cy = (nums[1] + nums[3]) // 2
                subprocess.run(
                    ['adb', '-s', udid, 'shell', 'input', 'tap', str(cx), str(cy)],
                    capture_output=True, timeout=5,
                )
                print(f"  ✅ [{role}/Android] '보이는 전화' ADB 폴백 탭 완료 ({cx},{cy})")
                return True
            except Exception as _e:
                print(f"  ⚠️ [{role}/Android] '보이는 전화' ADB 폴백 실패: {_e}")
                time.sleep(0.5)
        print(f"  ℹ️ [{role}/Android] '보이는 전화' ADB 폴백 팝업 없음 (정상)")
        return False

    def _tap_video_call_popup(self, driver, role: str, platform: str, timeout: float = 8.0):
        """통화 연결 직후 '보이는 전화' 팝업이 나타나면 클릭합니다.

        iOS     : XCUITest — XPATH label/name 속성으로 탐색
        Android : UIAutomator2 — UiSelector().text() / UiSelector().description() 로 탐색
                  (XPATH @text 방식은 Android UIAutomator2에서 신뢰도 낮음)
        팝업이 없으면 조용히 종료 (정상 케이스).
        UiAutomator2 크래시 감지 시 ADB 폴백으로 자동 전환.
        """
        from appium.webdriver.common.appiumby import AppiumBy
        deadline = time.time() + timeout

        if platform == 'Android':
            # UIAutomator2는 XPath ".." (부모 탐색) 미지원 → page_source XML 파싱으로 우회
            # content-desc="보이는 전화" 자식을 가진 부모 View의 bounds 추출 후 좌표 탭
            import xml.etree.ElementTree as _ET
            import re as _re
            _uia2_dead = False
            while time.time() < deadline:
                try:
                    src = driver.page_source
                    root = _ET.fromstring(src.encode('utf-8'))
                    parent_bounds = None
                    for node in root.iter():
                        for child in list(node):
                            if child.get('content-desc') == '보이는 전화':
                                parent_bounds = node.get('bounds')
                                break
                        if parent_bounds:
                            break
                    if not parent_bounds:
                        time.sleep(0.5)
                        continue
                    # bounds 형식: "[x1,y1][x2,y2]"
                    nums = list(map(int, _re.findall(r'\d+', parent_bounds)))
                    cx = (nums[0] + nums[2]) // 2
                    cy = (nums[1] + nums[3]) // 2
                    driver.execute_script('mobile: clickGesture', {'x': cx, 'y': cy})
                    print(f"  ✅ [{role}/{platform}] '보이는 전화' 부모 좌표 탭 완료 ({cx},{cy})")
                    return True
                except Exception as _e:
                    _err_msg = str(_e)
                    if 'instrumentation process is not running' in _err_msg or 'ECONNRESET' in _err_msg or 'socket hang up' in _err_msg:
                        if not _uia2_dead:
                            print(f"  ⚠️ [{role}/{platform}] UiAutomator2 크래시 감지 → ADB 폴백 전환")
                            _uia2_dead = True
                        # ADB 폴백
                        _udid = self.speaker1_device if role == 'speaker1' else self.speaker2_device
                        _remaining = max(0, deadline - time.time())
                        return self._tap_video_call_popup_adb(_udid, role, timeout=_remaining)
                    print(f"  ⚠️ [{role}/{platform}] '보이는 전화' 탭 시도 실패: {_e}")
                    time.sleep(0.5)
        else:
            # iOS XCUITest: label / name / value 속성
            ios_xpath = '//*[@label="보이는 전화" or @name="보이는 전화" or @value="보이는 전화"]'
            while time.time() < deadline:
                try:
                    el = driver.find_element(AppiumBy.XPATH, ios_xpath)
                    el.click()
                    print(f"  ✅ [{role}/{platform}] '보이는 전화' 클릭 완료")
                    return True
                except Exception:
                    time.sleep(0.5)

        print(f"  ℹ️ [{role}/{platform}] '보이는 전화' 팝업 없음 (정상)")
        return False

    def _detect_vishing_popup(
        self, driver, role: str, platform: str,
        screenshot_dir: str, stop_event: threading.Event,
        timeout: float = 300.0,
        tc_type: str = '',
    ):
        """보이스피싱 팝업 감지 — AI가 분석한 위조 목소리 / 보이스피싱 위험 텍스트 탐색.

        stop_event 가 set 되거나 timeout 이 지나면 폴링 종료.
        감지 시 스크린샷 저장 후 즉시 종료.
        반환: (detected: bool, screenshot_path: str | None)
        """
        import xml.etree.ElementTree as _ET
        import os as _os

        _KEYWORDS = (
            'AI가 분석한 위조 목소리',
            '보이스피싱 위험',
            '보이스피싱',
            '통화 종료 및 차단',
        )
        _POLL_INTERVAL = 1.5
        deadline = time.time() + timeout

        while not stop_event.is_set() and time.time() < deadline:
            try:
                src = driver.page_source
                found = any(kw in src for kw in _KEYWORDS)
                if not found:
                    time.sleep(_POLL_INTERVAL)
                    continue

                # 팝업 감지 — 스크린샷 저장
                print(f"  🚨 [{role}/{platform}] 보이스피싱 팝업 감지!")
                ss_path = None
                try:
                    _os.makedirs(screenshot_dir, exist_ok=True)
                    import datetime as _dt_mod
                    ts = _dt_mod.datetime.now().strftime('%Y%m%d_%H%M%S')
                    # TC ID를 파일명에 포함 → 결과 매칭 시 누락 방지
                    _tc_tag = f'_{tc_type}' if tc_type else ''
                    ss_file = _os.path.join(screenshot_dir, f'vishing_popup{_tc_tag}_{role}_{ts}.png')
                    driver.save_screenshot(ss_file)
                    ss_path = ss_file
                    print(f"  📸 스크린샷 저장: {ss_file}")
                except Exception as _ss_e:
                    print(f"  ⚠️ 스크린샷 저장 실패: {_ss_e}")
                return True, ss_path

            except Exception as _e:
                _err_str = str(_e)
                if 'instrumentation' in _err_str or 'not running' in _err_str:
                    print(f"  ⚠️ [{role}/{platform}] UiAutomator2 크래시 → 보이스피싱 감지 중단")
                    return False, None
                print(f"  ⚠️ [{role}/{platform}] 보이스피싱 감지 폴링 오류: {_e}")
                time.sleep(_POLL_INTERVAL)

        if stop_event.is_set():
            print(f"  ℹ️ [{role}/{platform}] 보이스피싱 팝업 미감지 (통화 종료)")
        else:
            print(f"  ℹ️ [{role}/{platform}] 보이스피싱 팝업 미감지 (타임아웃)")
        return False, None

    def teardown(self):
        """정리"""
        print(f"🔌 디바이스 연결 종료 중...\n")
        
        for key, driver in self.drivers.items():
            try:
                driver.quit()
                print(f"✅ {key} 연결 종료")
            except Exception:
                pass
        
        # HTTP 서버 중지 (iOS용)
        try:
            if self.speaker1_platform == 'iOS' or self.speaker2_platform == 'iOS':
                self.audio_handler.stop_http_server()
        except Exception:
            pass
        
        # 무선 터널 종료
        if self.tunnel_process:
            try:
                self.tunnel_process.terminate()
                self.tunnel_process.wait(timeout=5)
                print(f"✅ iOS 무선 터널 종료")
            except Exception:
                try:
                    self.tunnel_process.kill()
                except Exception:
                    pass
        
        # 포트 정리 (다음 테스트 실행 준비)
        for port in [8100, 8200, 8300]:
            self._free_port(port)

        print(f"\n{'='*60}\n")
    
    def run(self):
        """전체 테스트 실행"""
        import datetime as _datetime_mod
        _run_start_wall = _datetime_mod.datetime.now().strftime('%H:%M:%S')
        _audio_sp1 = Path(self.speaker1_audio).name if hasattr(self, 'speaker1_audio') else '?'
        _audio_sp2 = Path(self.speaker2_audio).name if hasattr(self, 'speaker2_audio') else '?'
        print(f"\n{'#'*60}")
        print(f"▶  테스트 시작  [{_run_start_wall}]")
        print(f"   TC={self.tc_type or 'TC_00'}  |  통신사={self.carrier_tag or '?'}")
        print(f"   발신({self.speaker1_platform}:{self.speaker1_number}) → 수신({self.speaker2_platform}:{self.speaker2_number})")
        print(f"   음원 SP1={_audio_sp1}  SP2={_audio_sp2}")
        print(f"{'#'*60}")
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

            # 화자2 앱 상태 초기화 → 수신 시 전체화면 표시 보장
            # ── 잔류 통화 강제 종료 (이전 TC 미정리 방지) ──
            for _role, _udid_attr, _plat_attr in [
                ('speaker1', 'speaker1_device', 'speaker1_platform'),
                ('speaker2', 'speaker2_device', 'speaker2_platform'),
            ]:
                _plat = getattr(self, _plat_attr, None)
                _udid = getattr(self, _udid_attr, None)
                if _plat == 'Android' and _udid:
                    try:
                        subprocess.run(
                            ['adb', '-s', _udid, 'shell', 'input', 'keyevent', 'KEYCODE_ENDCALL'],
                            capture_output=True, text=True, timeout=5
                        )
                    except Exception:
                        pass

            if self.speaker2_platform == 'Android':
                _ixio_pkg = self.android_app_package
                _udid2 = self.speaker2_device
                try:
                    # 앱 재실행 전 화면 깨우기 (화면 OFF 상태에서 앱 실행 방지)
                    print(f"  🔆 화자2(Android) 화면 상태 확인 중...")
                    self.device_setup._adb_wake_screen(_udid2)
                    print(f"  🔄 화자2(Android) 익시오 앱 종료 → 재실행 중...")
                    # 앱 강제 종료
                    subprocess.run(
                        ['adb', '-s', _udid2, 'shell', 'am', 'force-stop', _ixio_pkg],
                        capture_output=True, text=True, timeout=5
                    )
                    time.sleep(1)
                    # 앱 재실행 (메인 액티비티 → 전체화면 수신 보장)
                    subprocess.run(
                        ['adb', '-s', _udid2, 'shell', 'monkey', '-p', _ixio_pkg,
                         '-c', 'android.intent.category.LAUNCHER', '1'],
                        capture_output=True, text=True, timeout=5
                    )
                    time.sleep(2)
                    print(f"  ✓ 화자2(Android) 익시오 앱 메인화면 진입 완료")
                except Exception as e:
                    print(f"  ⚠️ 익시오 앱 재실행 실패: {e}")
            elif self.speaker2_platform == 'iOS' and 'speaker2' in self.drivers:
                # iOS 화자2: 익시오 앱 종료 → 재실행 (포그라운드 메인화면 진입)
                # App Store 버전은 백그라운드 상태에서 착신 시 배너 알림만 표시되므로
                # 앱을 포그라운드에 띄워놓아야 전체화면 수신 UI가 표시됨
                _ixio_bundle = self.ios_app_bundle_id
                sp2_drv = self.drivers['speaker2']
                try:
                    print(f"  🔄 화자2(iOS) 익시오 앱 종료 → 재실행 중...")
                    try:
                        sp2_drv.terminate_app(_ixio_bundle)
                        time.sleep(1)
                        print(f"  ✓ 익시오 앱 종료 완료")
                    except Exception:
                        print(f"  ℹ️ 익시오 앱이 실행 중이 아님 (종료 건너뜀)")
                    sp2_drv.activate_app(_ixio_bundle)
                    time.sleep(2)
                    print(f"  ✓ 화자2(iOS) 익시오 앱 메인화면 진입 완료")
                except Exception as e:
                    print(f"  ⚠️ 익시오 앱 재실행 실패: {e}")
            
            # 3. Android 화자2: 발신 전에 미리 수신 감지 워처 스레드 시작
            #    (발신 → 수신까지 3~5초 걸리므로 발신과 동시에 폴링 시작해야 RINGING 놓치지 않음)
            answered_event: 'threading.Event | None' = None
            failed_event:   'threading.Event | None' = None
            if self.speaker2_platform == 'Android':
                answered_event           = threading.Event()
                failed_event             = threading.Event()
                android_sp2_accept_event = threading.Event()  # accept 명령 전송 즉시 set
                threading.Thread(
                    target=self._start_android_answer_watcher,
                    args=(answered_event, failed_event, android_sp2_accept_event),
                    daemon=True
                ).start()
                print(f"  ℹ️ Android 수신 워처 스레드 시작 (발신 전)")

            # 3-1. Android 발신단 ACTIVE 워처 — 키패드 열기 후 발신 직전 시작
            #      (speaker1=Android일 때 open_ixio_keypad()과 ADB 경합 방지)
            android_caller_active_event: 'threading.Event | None' = None

            # 3-2. 키패드 열기 + 발신 (플랫폼별)
            if self.speaker1_platform == 'iOS':
                if not self.open_keypad_iphone('speaker1'):
                    return False
                # 발신 전 크래시 체크 (앱 재시작 직후 충돌 팝업 가능)
                sp1_driver = self.drivers.get('speaker1')
                if sp1_driver and self.crash_reporter and self.crash_reporter.detect_crash(sp1_driver):
                    self.crash_reporter.handle_crash(sp1_driver, extra_body="발신 전 단계에서 크래시 감지")
                    return 'crash'
                # iOS 발신 시 Android ACTIVE 워처 불필요
                if not self.make_call_iphone(self.speaker2_number):
                    return False
            else:
                _keypad_result = self.open_ixio_keypad('speaker1')
                if not _keypad_result:
                    return False
                # 키패드 열기 완료 후: 잔류 ACTIVE 정리 (동기) → 워쳐 시작 → make_call
                if self.speaker2_platform == 'iOS':
                    # Phase 0: 잔류 ACTIVE → IDLE 확인 (make_call 전에 동기 실행)
                    # → ENDCALL이 새 통화를 끊는 것을 원천 차단
                    self._ensure_android_idle()
                    android_caller_active_event = threading.Event()
                    threading.Thread(
                        target=self._start_android_caller_active_watcher,
                        args=(android_caller_active_event,),
                        daemon=True
                    ).start()
                    print(f"  ℹ️ Android 발신단 ACTIVE 워처 스레드 시작 (발신 직전)")
                if not self.make_call(self.speaker2_number):
                    return False

            # 3-3. ⚡ 발신 직후 오디오 subprocess pre-warm (Android SP2 전용)
            #    → RINGING까지 5~15초 대기하는 동안 subprocess 초기화 완료
            #    → OFFHOOK 즉시 trigger만 보내면 ~200ms 내 재생 시작
            _pre_warmed = False
            if self.speaker2_platform == 'Android':
                self._clean_audio_started_ts_files()
                _pre_warmed = self.prepare_audio_players()
                if _pre_warmed:
                    print(f"  ⚡ [PRE-WARM] 발신 직후 subprocess 생성 — RINGING 대기 중 초기화 진행")

            # 4. 화자2에서 전화 받기
            call_connected = False
            if self.speaker2_platform == 'Android':
                # ─ 2단계 대기 구조 (재생 지연 최소화 버전) ─────────────────────
                # Step1: accept_event  — RINGING 감지 후 accept 명령 전송 즉시 set
                #        → accept_sent_ts ≈ Android 타이머 00:00 - 50ms (기준점)
                # Step2: answered_event — OFFHOOK ADB 확인 후 set (통화 실제 연결)
                #
                # ⚡ 최적화: Step1 직후 녹음·팝업 설정 → Step2 대기 → 즉시 재생
                #    (설정 시간이 Step2 대기와 겹치므로 재생 지연 ~250ms 절약)
                #
                # 재생 타이밍: ref_ts = cmd_sent_ts (keyevent 전송 직전 시각)
                #   → Android는 keyevent 수신 후 수십 ms 내 OFFHOOK
                #   → cmd_sent_ts ≈ 실제 Android 00:00 - 50ms
                #   → target_offset = 0.0 (OFFHOOK 확인 즉시 재생)
                # ─────────────────────────────────────────────────────────────

                # [Step1] accept 명령 전송 확인 → 기준점 확보
                print(f"📱 화자2: 수신 대기...(Android RINGING+accept 감지 중)")
                if not android_sp2_accept_event.wait(timeout=80.0):
                    print(f"❌ Android accept 신호 없음 (80초 타임아웃) — 오디오 재생 건너뜀\n")
                    self.end_call()
                    return False
                accept_ts = getattr(android_sp2_accept_event, '_accept_sent_ts', time.time())
                _t0 = accept_ts  # 공통 기준점
                print(f"  ✅ [Step1] accept 명령 확인 — T+{(time.time()-_t0)*1000:.0f}ms")

                # ⚡ Step1 직후: 팝업 설정을 Step2 대기 전에 수행
                #    → subprocess는 발신 직후(3-3)에서 이미 pre-warm 완료
                from datetime import datetime as _dt

                # 발신단(iOS) 타이머 00:00 확인 + '보이는 전화' 팝업 처리 — 백그라운드
                if self.speaker1_platform == 'iOS' and 'speaker1' in self.drivers:
                    _sp1_drv_ref = self.drivers.get('speaker1')
                    def _check_sp1(_drv=_sp1_drv_ref):
                        ok = self.wait_for_call_connecting_state(roles=['speaker1'])
                        print(f"  [sp1 확인] {'✅ 발신단(iOS) 타이머 00:00 확인' if ok else '⚠️ 발신단(iOS) 연결 확인 불가 (이미 재생 중)'}")
                        self._tap_video_call_popup(_drv, 'speaker1', 'iOS', timeout=15.0)
                    threading.Thread(target=_check_sp1, daemon=True).start()

                print(f"  🔍 '보이는 전화' 팝업 감지 스레드 시작 (Step2 대기 전)")
                # Android 수신단(speaker2)만 팝업 감지 실행 — 1개 스레드
                # iOS speaker1은 _check_sp1 에서 이미 처리
                if self.speaker2_platform == 'Android':
                    _vpc_drv = self.drivers.get('speaker2')
                    if _vpc_drv:
                        threading.Thread(
                            target=self._tap_video_call_popup,
                            args=(_vpc_drv, 'speaker2', 'Android'),
                            daemon=True,
                        ).start()

                # [Step2] OFFHOOK 확인 → 통화 실제 연결 보장 후 재생
                print(f"  ⏳ [Step2] OFFHOOK 확인 대기 (통화 연결 확인 중...)")
                if not answered_event.wait(timeout=20.0):
                    print(f"  ⚠️ OFFHOOK 미확인 (20초 타임아웃) — accept 기준으로 재생 강행")
                    offhook_ts = time.time()
                    _cmd_sent_ts = accept_ts
                else:
                    offhook_ts = getattr(answered_event, '_offhook_ts', time.time())
                    _cmd_sent_ts = getattr(answered_event, '_cmd_sent_ts', accept_ts)
                    print(f"  ✅ [Step2] OFFHOOK 확인 — T+{(offhook_ts-_t0)*1000:.0f}ms (event수신 T+{(time.time()-_t0)*1000:.0f}ms)")

                # iOS 발신 시 OFFHOOK 직후 오디오 라우팅 강제 설정 (백그라운드)
                if self.speaker1_platform == 'iOS':
                    threading.Thread(target=self.force_ios_external_mic, daemon=True).start()

                _now = time.time()
                print(f"  [TIMING] accept→지금: {(_now-_t0)*1000:.0f}ms | cmd_sent→지금: {(_now-_cmd_sent_ts)*1000:.0f}ms | offhook→지금: {(_now-offhook_ts)*1000:.0f}ms")

                call_connected = True
                print(f"\n{'━'*60}")
                print(f"✅ 통화 연결 확인  [{_datetime_mod.datetime.now().strftime('%H:%M:%S')}]")
                print(f"   발신({self.speaker1_platform}) → 수신(Android)  |  TC={self.tc_type or 'TC_00'}  |  {self.carrier_tag or ''}")
                print(f"   ▶ 음원 재생 예정: {Path(self.speaker1_audio).name}")
                print(f"{'━'*60}\n")

                # ⚡ 녹음 시작 (OFFHOOK 확인 = 통화 00:00)
                self._call_start_ts = _dt.now().strftime('%Y%m%d_%H%M%S')
                if self._mixer_recorder:
                    threading.Thread(target=self._mixer_recorder.start, daemon=True).start()
                elif self._call_recorder:
                    threading.Thread(target=self._call_recorder.start, daemon=True).start()
                print(f"  🎙️ 녹음 시작 (통화 00:00 = OFFHOOK 확인 시점)")

                # ⚡ 재생 트리거: pre-warm 완료 시 즉시 trigger, 미완료 시 기존 방식
                if _pre_warmed:
                    # Pre-warm 모드: subprocess는 발신 직후(3-3)에 생성 → 벨 울리는 동안 초기화 완료
                    # → 100ms 여유: 워커 파일 감지(10ms) + play_at 동기 대기 마진
                    _play_at = time.time() + 0.1
                    self._audio_ref_ts = _cmd_sent_ts
                    self._audio_target_offset = 0.0
                    print(f"  [TIMING] PRE-WARM 모드 — trigger {(_play_at - _cmd_sent_ts)*1000:.0f}ms after cmd_sent (play_at까지 100ms)")
                    self.trigger_audio_playback(_play_at)
                else:
                    # 폴백: 기존 방식 (subprocess 생성 + 3.0초 sync 대기)
                    _ref = _cmd_sent_ts
                    self._audio_ref_ts        = _ref
                    self._audio_target_offset = 0.0
                    print(f"  [TIMING] 기준점=cmd_sent_ts+0.0s (폴백)")
                    self.play_audio_after_delay(delay=0, ref_ts=_ref, target_offset=0.0)

                # 재생 시작 타임스탬프 수집 → MixerRecorder 동기화
                self._sync_play_start_time()
            else:
                # iOS 화자2: 수신 처리
                ios_sp2_answered_event: 'threading.Event | None' = None
                if 'speaker2' in self.drivers:
                    if android_caller_active_event is not None:
                        # iOS 수신 완료를 별도 이벤트로 추적.
                        # ─ 구조:
                        #   스레드A: _ios_answer_btn_clicked_at 세팅되는 즉시(클릭 직후) 이벤트 set
                        #   스레드B: answer_call_on_speaker2() 실행 (내부에 sleep(2) 있음)
                        # → 클릭 시각 기준으로 정확한 타이밍 계산 가능
                        ios_sp2_answered_event = threading.Event()
                        _ios_ans_evt = ios_sp2_answered_event
                        # 시작 전 이전 세션 잔류값 초기화
                        self._ios_answer_btn_clicked_at = None  # type: ignore[attr-defined]

                        def _click_watcher(_evt=_ios_ans_evt):
                            """_ios_answer_btn_clicked_at 세팅 감지 → 즉시 이벤트 set."""
                            deadline = time.time() + 35.0
                            while time.time() < deadline:
                                ts = getattr(self, '_ios_answer_btn_clicked_at', None)
                                if ts is not None:
                                    _evt._answer_ts = ts
                                    _evt.set()
                                    return
                                time.sleep(0.05)
                            print(f"  [클릭워쳐] ⚠️ 35초 내 버튼 클릭 미감지 — 이벤트 미설정")

                        _sp2_drv_ref = self.drivers.get('speaker2')

                        def _do_answer(_drv=_sp2_drv_ref):
                            result = self.answer_call_on_speaker2()
                            if result:
                                # 수신 직후 '보이는 전화' 팝업 처리 — TC_01 _check_sp1 패턴과 동일
                                # 4-1 루프보다 훨씬 빠른 시점에 실행되므로 팝업 놓침 방지
                                self._tap_video_call_popup(_drv, 'speaker2', 'iOS', timeout=20.0)
                            else:
                                print(f"  [수신워쳐] ⚠️ iOS 수신 실패")

                        threading.Thread(target=_click_watcher, daemon=True).start()
                        threading.Thread(target=_do_answer, daemon=True).start()
                        print(f"📱 화자2: iOS 수신 처리 백그라운드 시작 (클릭 감지 워쳐 활성화)")
                    else:
                        self.answer_call_on_speaker2()

                # 통화 연결 확인 — Android 발신단 ACTIVE 기준 (수신 케이스와 대칭)
                if android_caller_active_event is not None:
                    print(f"📱 화자1: 통화 연결 대기...(Android ACTIVE 감지 중)")
                    if android_caller_active_event.wait(timeout=60.0):
                        active_ts = getattr(android_caller_active_event, '_active_ts', time.time())
                        call_connected = True
                        self._audio_ref_ts = active_ts
                        print(f"\n{'━'*60}")
                        print(f"✅ 통화 연결 확인  [{_datetime_mod.datetime.now().strftime('%H:%M:%S')}]")
                        print(f"   발신(Android) → 수신({self.speaker2_platform})  |  TC={self.tc_type or 'TC_00'}  |  {self.carrier_tag or ''}")
                        print(f"   ▶ 음원 재생 예정: {Path(self.speaker1_audio).name}")
                        print(f"{'━'*60}\n")
                    else:
                        print(f"\n{'━'*60}")
                        print(f"❌ 통화 연결 실패  [{_datetime_mod.datetime.now().strftime('%H:%M:%S')}]")
                        print(f"   Android ACTIVE 미감지 (60초 타임아웃)")
                        print(f"   ⛔ 음원 재생 없이 종료")
                        print(f"{'━'*60}\n")
                        self.end_call()
                        return False

                    # iOS 수신 완료 대기 — Android ACTIVE 후에도 iOS가 아직 받기 전일 수 있음
                    # (최대 30초 추가 대기, 타임아웃 시 경고 후 재생 강행)
                    if ios_sp2_answered_event is not None:
                        _ios_wait_deadline = 30.0
                        if not ios_sp2_answered_event.wait(timeout=_ios_wait_deadline):
                            print(f"  ⚠️ iOS 수신 확인 타임아웃({_ios_wait_deadline:.0f}초) — 음원 재생 강행")
                        else:
                            ios_ans_ts = getattr(ios_sp2_answered_event, '_answer_ts', time.time())
                            self._audio_ref_ts = ios_ans_ts  # iOS 버튼 클릭 시각 기준으로 덮어씀
                            print(f"  ✅ iOS 수신 버튼 클릭 확인 — 500ms 후 음원 재생 시작")
                else:
                    call_connected = self.wait_for_call_connecting_state()
                    if not call_connected:
                        print(f"\n{'━'*60}")
                        print(f"❌ 통화 연결 실패  [{_datetime_mod.datetime.now().strftime('%H:%M:%S')}]")
                        print(f"   통화 연결 확인 불가 (wait_for_call_connecting_state 실패)")
                        print(f"   ⛔ 음원 재생 없이 종료")
                        print(f"{'━'*60}\n")
                        self.end_call()
                        return False
                    else:
                        print(f"\n{'━'*60}")
                        print(f"✅ 통화 연결 확인  [{_datetime_mod.datetime.now().strftime('%H:%M:%S')}]")
                        print(f"   발신({self.speaker1_platform}) → 수신({self.speaker2_platform})  |  TC={self.tc_type or 'TC_00'}  |  {self.carrier_tag or ''}")
                        print(f"   ▶ 음원 재생 예정: {Path(self.speaker1_audio).name}")
                        print(f"{'━'*60}\n")

            # 4-1. '보이는 전화' 팝업 처리 — 통화 연결 직후 (백그라운드)
            #   - speaker2=Android 경로: Step1-Step2 블록에서 이미 설정 완료 → 건너뜀
            #   - speaker1=iOS 발신단: _check_sp1 스레드에서 타이머 확인 후 처리 (위 코드)
            #   - speaker1=Android : 여기서 처리
            #   - speaker2=iOS : _do_answer() 내에서 수신 직후 처리 (TC_02/TC_04)
            _android_sp2_early_setup = (self.speaker2_platform == 'Android')
            if not _android_sp2_early_setup:
                # Android speaker1 발신단만 팝업 감지 — 1개 스레드
                # iOS speaker1은 _check_sp1에서 처리, iOS speaker2는 _do_answer에서 처리
                if self.speaker1_platform == 'Android':
                    _vpc_drv = self.drivers.get('speaker1')
                    if _vpc_drv:
                        print(f"  🔍 '보이는 전화' 팝업 감지 스레드 시작")
                        threading.Thread(
                            target=self._tap_video_call_popup,
                            args=(_vpc_drv, 'speaker1', 'Android'),
                            daemon=True,
                        ).start()

            # 5-1. iOS 오디오 라우팅 (USB-C iPhone은 iRig HD2 자동 라우팅)
            # Lightning iPhone의 경우에만 수동 라우팅 필요할 수 있음

            # 6-0. 통화 녹음 시작 (Android sp2 경로는 Step1-Step2에서 이미 시작)
            if not _android_sp2_early_setup:
                from datetime import datetime as _dt
                self._call_start_ts = _dt.now().strftime('%Y%m%d_%H%M%S')
                # temp 타임스탬프 파일 정리 (이전 세션 잔류분)
                self._clean_audio_started_ts_files()
                if self._mixer_recorder:
                    threading.Thread(target=self._mixer_recorder.start, daemon=True).start()
                elif self._call_recorder:
                    threading.Thread(target=self._call_recorder.start, daemon=True).start()

            # 6. 오디오 재생 — 통화 연결 기준 목표 시점 재생
            #    Android sp2 경로: Step2 블록에서 이미 play_audio_after_delay 호출됨
            if not _android_sp2_early_setup:
                _ref_ts  = getattr(self, '_audio_ref_ts',        None)
                _offset  = getattr(self, '_audio_target_offset', 0.3)
                print(f"\n🎵 음원 재생 시작  [{_datetime_mod.datetime.now().strftime('%H:%M:%S')}]  (통화 연결 후 iOS SP2 경로)")
                self.play_audio_after_delay(delay=0, ref_ts=_ref_ts, target_offset=_offset)
                # 재생 시작 타임스탬프 수집 → MixerRecorder 동기화
                self._sync_play_start_time()

            # 6-1. TC_03/TC_04 — 보이스피싱 팝업 감지 (양쪽 디바이스 동시 모니터링)
            _vishing_stop_event = threading.Event()
            _vishing_result: dict = {'detected': False, 'path': None}
            _vishing_threads: list = []
            if self.tc_type in ('TC_03', 'TC_04'):
                # 양쪽 디바이스 모두 감지 스레드 실행 → 먼저 감지된 쪽 채택
                _vishing_lock = threading.Lock()
                for _role, _plat in [
                    ('speaker1', self.speaker1_platform),
                    ('speaker2', self.speaker2_platform),
                ]:
                    _drv = self.drivers.get(_role)
                    if not _drv:
                        continue

                    def _vishing_worker(
                        _drv=_drv, _role=_role, _plat=_plat
                    ):
                        det, path = self._detect_vishing_popup(
                            _drv, _role, _plat,
                            self.screenshot_dir, _vishing_stop_event,
                            tc_type=self.tc_type,
                        )
                        if det:
                            with _vishing_lock:
                                _vishing_result['detected'] = True
                                if path and not _vishing_result['path']:
                                    _vishing_result['path'] = path
                            _vishing_stop_event.set()  # 감지 성공 → 다른 스레드 중단

                    _t = threading.Thread(target=_vishing_worker, daemon=True)
                    _t.start()
                    _vishing_threads.append(_t)
                    print(f"  🔍 [{_role}/{_plat}] 보이스피싱 팝업 감지 시작")

            # 7. 오디오 재생 완료 대기 (통화 강제 종료 감지 포함)
            call_completed = self.wait_for_audio_completion()

            # 발신단(iOS) 크래시 체크 — 통화/재생 중 충돌 발생 여부 확인
            sp1_driver = self.drivers.get('speaker1')
            if sp1_driver and self.crash_reporter and self.crash_reporter.detect_crash(sp1_driver):
                self.crash_reporter.handle_crash(sp1_driver, extra_body="오디오 재생 완료 후 크래시 감지")
                if self._mixer_recorder and self._mixer_recorder.is_recording:
                    self._mixer_recorder.stop()
                elif self._call_recorder and self._call_recorder.is_recording:
                    self._call_recorder.stop()
                self.end_call()
                return 'crash'

            # 7-1. 통화 녹음 종료 (오디오 완료 후, 통화 종료 전)
            _recorder_paths: dict = {}
            if self._mixer_recorder and self._mixer_recorder.is_recording:
                _recorder_paths = self._mixer_recorder.stop()
            elif self._call_recorder and self._call_recorder.is_recording:
                _recorder_paths = self._call_recorder.stop()

            # 8. 통화 종료
            self.end_call()

            # 8-1. 통화 종료 후 음원 수집 + 믹스
            #   직접 녹음 모드(direct): 단방향 녹음(RX)에 원본 재생(TX)을 믹스하여 양방향 통화 녹음 생성
            #   파일 추출 모드(extract): 기존 iOS pull + Android ADB pull
            self._collected_audio: dict = {}
            if self._recording_mode == 'direct' and _recorder_paths:
                # 직접 녹음 모드: 단방향 녹음 파일을 그대로 사용 (TX 믹스 생략)
                ios_rec_path = _recorder_paths.get('ios')
                android_rec_path = _recorder_paths.get('android')

                self._collected_audio = {
                    'android_path': str(android_rec_path) if android_rec_path else None,
                    'ios_path': str(ios_rec_path) if ios_rec_path else None,
                }
            elif _CALL_AUDIO_COLLECTOR_AVAILABLE:
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
                    ios_rec = self._collected_audio.get('ios_path')
                    android = self._collected_audio.get('android_path')
                    if ios_rec:
                        print(f"📱 iOS 앱 녹음: {ios_rec}")
                    if android:
                        print(f"📱 Android 통화록: {android}")
                    if not ios_rec and not android:
                        print("  ⚠️ 수집된 통화 음원 없음")
                    # mixed_path 없음 (믹싱 제거됨)
                else:
                    print("  ⚠️ Android UDID 없음 → 통화 음원 수집 건너뜀")

            # 8-2. 보이스피싱 감지 스레드 종료 + 결과 수집
            _vishing_stop_event.set()  # 통화 종료 → 폴링 중단 신호
            for _t in _vishing_threads:
                _t.join(timeout=5.0)  # 스레드 완료 대기 (race condition 방지)
            # fallback: join 후에도 path가 없으면 screenshot_dir에서 TC ID 또는 최근 5분 내 파일 탐색
            if self.tc_type in ('TC_03', 'TC_04') and not _vishing_result.get('path'):
                import glob as _glob
                import os as _os
                # 1순위: TC ID가 파일명에 포함된 파일 (가장 정확한 매칭)
                _pattern_tc = _os.path.join(self.screenshot_dir, f'vishing_popup_{self.tc_type}_*.png')
                _candidates = sorted(_glob.glob(_pattern_tc), key=lambda f: _os.path.getmtime(f), reverse=True)
                # 2순위: TC ID 없이 저장된 파일 중 최근 5분 이내 것 (이전 버전 호환)
                if not _candidates:
                    _pattern_any = _os.path.join(self.screenshot_dir, 'vishing_popup_*.png')
                    _candidates = [
                        f for f in sorted(_glob.glob(_pattern_any), key=lambda f: _os.path.getmtime(f), reverse=True)
                        if time.time() - _os.path.getmtime(f) < 300
                    ]
                if _candidates:
                    _vishing_result['path'] = _candidates[0]
                    if not _vishing_result['detected']:
                        _vishing_result['detected'] = True
                    print(f"  📦 fallback: 보이스피싱 스크린샷 확인 → {_candidates[0]}")
            self._screenshots: list = []
            self._vishing_detected: bool = _vishing_result['detected']
            if _vishing_result['path']:
                self._screenshots.append(_vishing_result['path'])
            if self.tc_type in ('TC_03', 'TC_04'):
                _det_str = '✅ 감지됨' if self._vishing_detected else '❌ 미감지'
                print(f"  🛡 보이스피싱 팝업 감지 결과: {_det_str}")

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
            import traceback
            print(f"\n{'='*60}")
            print(f"❌ 테스트 실패: {e}")
            print(f"{'='*60}\n")
            # stderr에도 출력 → Rust가 에러 메시지로 캐스트
            print(f"테스트 실패: {e}", file=sys.__stderr__)
            traceback.print_exc(file=sys.__stderr__)
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
    parser.add_argument('--speaker1-rec-channel', default=None, help='화자1 CONNECT 6 녹음 채널 (예: "6,7" = Loopback 1)')
    parser.add_argument('--speaker2-rec-channel', default=None, help='화자2 CONNECT 6 녹음 채널 (예: "12,13" = Loopback 2)')
    parser.add_argument('--speaker1-output-pair', default=None, help='화자1 CONNECT 6 출력 채널 쌍 (예: "0,1" = Out 1/2)')
    parser.add_argument('--speaker2-output-pair', default=None, help='화자2 CONNECT 6 출력 채널 쌍 (예: "2,3" = Out 3/4)')
    parser.add_argument('--appium-port-android', type=int, default=4723, help='Android Appium 서버 포트 (기본: 4723)')
    parser.add_argument('--appium-port-ios', type=int, default=4724, help='iOS Appium 서버 포트 (기본: 4724)')
    parser.add_argument('--monitor', action='store_true', help='통화 중 맥북 스피커로 실시간 모니터링 활성화')
    parser.add_argument('--tc-type', default='', help='TC 유형: TC_00 | TC_01 | TC_02 | TC_03 | TC_04 (생략 시 일반 테스트)')
    parser.add_argument('--recording-mode', default='extract', choices=['extract', 'direct'], help='녹음 방식: extract (파일 추출) | direct (AG03 믹서 직접 녹음)')
    parser.add_argument('--android-app-package', default='com.lguplus.aicallagent', help='Android 테스트 앱 패키지명 (기본: 익시오)')
    parser.add_argument('--android-app-activity', default='', help='Android 메인 액티비티 (생략 시 Appium 자동 탐지)')
    parser.add_argument('--ios-app-bundle-id', default='com.lguplus.aicallagent', help='iOS 테스트 앱 번들 ID (기본: 익시오)')
    parser.add_argument('--carrier', default='', help='통신사 ID: lguplus | skt | kt (파일명 태그용)')
    
    args = parser.parse_args()

    # ── 파일 로깅 설정 (logs/YYYY-MM-DD/ 폴더에 txt 저장) ─────────────────
    _log_file = None
    try:
        from datetime import datetime as _dt
        _log_root = Path(__file__).resolve().parent.parent.parent.parent / 'logs'
        _log_day_dir = _log_root / _dt.now().strftime('%Y-%m-%d')
        _log_day_dir.mkdir(parents=True, exist_ok=True)
        _tc_label = args.tc_type if args.tc_type else 'test'
        _log_name = f"{_tc_label}_{_dt.now().strftime('%H%M%S')}.txt"
        _log_path = _log_day_dir / _log_name
        _log_file = open(_log_path, 'w', encoding='utf-8', buffering=1)  # line-buffered

        class _TeeWriter:
            """stdout/stderr를 원본 스트림 + 파일에 동시 출력"""
            def __init__(self, original, log_file):
                self._original = original
                self._log_file = log_file
            def write(self, data):
                self._original.write(data)
                try:
                    self._log_file.write(data)
                except Exception:
                    pass
            def flush(self):
                self._original.flush()
                try:
                    self._log_file.flush()
                except Exception:
                    pass
            def fileno(self):
                return self._original.fileno()
            def isatty(self):
                return False

        sys.stdout = _TeeWriter(sys.__stdout__, _log_file)
        sys.stderr = _TeeWriter(sys.__stderr__, _log_file)
        print(f"📝 로그 파일: {_log_path}")
    except Exception as _le:
        print(f"⚠️ 로그 파일 생성 실패: {_le}")

    # ── TC 타입별 클래스 디스패치 ──────────────────────────────────────────
    _tc_classes = {}
    try:
        from tc_01 import Tc01
        _tc_classes['TC_01'] = Tc01
    except ImportError:
        pass
    try:
        from tc_02 import Tc02
        _tc_classes['TC_02'] = Tc02
    except ImportError:
        pass
    try:
        from tc_03 import Tc03
        _tc_classes['TC_03'] = Tc03
    except ImportError:
        pass
    try:
        from tc_04 import Tc04
        _tc_classes['TC_04'] = Tc04
    except ImportError:
        pass
    try:
        from tc_00 import Tc00
        _tc_classes['TC_00'] = Tc00
    except ImportError:
        pass

    TcClass = _tc_classes.get(args.tc_type, IxioAutomatedTest)
    if args.tc_type and args.tc_type in _tc_classes:
        print(f"📋 TC 모드: {args.tc_type} → {TcClass.__name__} 클래스 사용")
    
    tester = TcClass(
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
        speaker1_rec_channel=args.speaker1_rec_channel,
        speaker2_rec_channel=args.speaker2_rec_channel,
        speaker1_output_pair=args.speaker1_output_pair,
        speaker2_output_pair=args.speaker2_output_pair,
        monitor=args.monitor,
        tc_type=args.tc_type,
        appium_port_android=args.appium_port_android,
        appium_port_ios=args.appium_port_ios,
        recording_mode=args.recording_mode,
        android_app_package=args.android_app_package,
        android_app_activity=args.android_app_activity,
        ios_app_bundle_id=args.ios_app_bundle_id,
        carrier=args.carrier,
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

    try:
        result = tester.run()
        if result == 'retry':
            sys.exit(2)   # 통화 강제 종료 → 동일 회차 재시작
        elif result == 'crash':
            sys.exit(3)   # 앱 크래시 감지 → 재시작 (로그/메일 이미 처리됨)
        elif result:
            # 수집된 음원·스크린샷 경로를 Rust 파싱용 구조로 stdout 출력
            import json as _json_out
            _tc_result = {}
            if isinstance(result, dict):
                _tc_result['ios_recording']     = result.get('ios_recording', '')
                _tc_result['android_recording'] = result.get('android_recording', '')
            if hasattr(tester, '_screenshots'):
                _tc_result['screenshots'] = [str(p) for p in tester._screenshots if p]
            if hasattr(tester, '_vishing_detected'):
                _tc_result['vishing_detected'] = tester._vishing_detected
            print(f"TC_RESULT_JSON:{_json_out.dumps(_tc_result)}", flush=True)
            sys.exit(0)   # 정상 완료
        else:
            # run() 반환값 False — stderr에 진단 정보 출력 (Rust 캐스트용)
            print("테스트 실패: run() 반환값 False (디바이스 연결/통화 연결/녹음 등 실패)", file=sys.__stderr__)
            sys.exit(1)   # 실패
    finally:
        # 로그 파일 정리
        if _log_file:
            try:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
                _log_file.close()
            except Exception:
                pass


if __name__ == '__main__':
    main()
