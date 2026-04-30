"""
TC 공통 베이스 클래스 — phase 메서드로 run()을 분해
TC_01~TC_04가 상속하여 각 시나리오에 맞게 phase를 조합.
"""

import time
import threading
from pathlib import Path
from datetime import datetime as _dt

from ixio_automated_test import IxioAutomatedTest

try:
    from core_audio_utils import lock_usb_output_for_test, restore_default_devices
except ImportError:
    def lock_usb_output_for_test(verbose=True): pass
    def restore_default_devices(verbose=True): pass

import subprocess


class TcBase(IxioAutomatedTest):
    """TC_01~TC_04 공통 베이스.

    run()은 하위 클래스에서 phase 메서드를 조합하여 구현.
    phase 간 공유 상태는 인스턴스 변수(_phase_*)에 저장.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ── phase 간 공유 상태 ──
        self._phase_answered_event = None
        self._phase_failed_event = None
        self._phase_accept_event = None
        self._phase_active_event = None        # Android caller ACTIVE
        self._phase_ios_answered_event = None   # iOS sp2 answered
        self._phase_vishing_stop = threading.Event()
        self._phase_vishing_result = {'detected': False, 'path': None}
        self._phase_vishing_threads = []
        self._phase_android_sp2_early = False   # Android sp2 Step1-Step2 경로 활성 여부

    # ═══════════════════════════════════════════════════════════════════════
    #  Phase 1: 공통 셋업
    # ═══════════════════════════════════════════════════════════════════════

    def phase_setup(self) -> bool:
        """오디오·디바이스 준비, 잔류 통화 정리, 익시오 앱 재실행.

        Returns True on success, False on failure.
        """
        # 0. macOS 기본 출력 고정
        lock_usb_output_for_test(verbose=True)

        # 1. 오디오 준비
        self.prepare_audio()

        # 2. 디바이스 연결
        if not self.setup_device(self.speaker1_device, 'speaker1', platform=self.speaker1_platform):
            return False
        if not self.setup_device(self.speaker2_device, 'speaker2', platform=self.speaker2_platform):
            # 자동화 모드: speaker2 없으면 수신 수락 불가 → 중단
            print("❌ 화자2 연결 실패 — 테스트 중단")
            return False

        # 잔류 통화 ENDCALL (이전 TC 미정리 방지)
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

        # Android 화면 상시 켜짐 (24시간 테스트 대비)
        for _udid_attr, _plat_attr in [
            ('speaker1_device', 'speaker1_platform'),
            ('speaker2_device', 'speaker2_platform'),
        ]:
            _plat = getattr(self, _plat_attr, None)
            _udid = getattr(self, _udid_attr, None)
            if _plat == 'Android' and _udid:
                try:
                    # 화면 깨우기 (Wi-Fi ADB는 충전 아님 → stay_on_while_plugged_in 무효할 수 있음)
                    subprocess.run(
                        ['adb', '-s', _udid, 'shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'],
                        capture_output=True, text=True, timeout=5
                    )
                    subprocess.run(
                        ['adb', '-s', _udid, 'shell', 'svc', 'power', 'stayon', 'true'],
                        capture_output=True, text=True, timeout=5
                    )
                    subprocess.run(
                        ['adb', '-s', _udid, 'shell', 'settings', 'put', 'system', 'screen_off_timeout', '2147483647'],
                        capture_output=True, text=True, timeout=5
                    )
                    subprocess.run(
                        ['adb', '-s', _udid, 'shell', 'settings', 'put', 'global', 'stay_on_while_plugged_in', '3'],
                        capture_output=True, text=True, timeout=5
                    )
                    print(f"  ✅ 화면 상시 켜짐 설정 ({_udid})")
                except Exception as _e:
                    print(f"  ⚠️ 화면 상시 켜짐 설정 실패 ({_udid}): {_e}")

        # Android Doze 화이트리스트 확인/등록
        _ixio_pkg = getattr(self, 'android_app_package', 'com.lguplus.aicallagent')
        for _udid_attr, _plat_attr in [
            ('speaker1_device', 'speaker1_platform'),
            ('speaker2_device', 'speaker2_platform'),
        ]:
            _plat = getattr(self, _plat_attr, None)
            _udid = getattr(self, _udid_attr, None)
            if _plat == 'Android' and _udid:
                try:
                    _wl = subprocess.run(
                        ['adb', '-s', _udid, 'shell', 'dumpsys', 'deviceidle', 'whitelist'],
                        capture_output=True, text=True, timeout=5
                    ).stdout
                    if _ixio_pkg in _wl:
                        print(f"  ✅ Doze 화이트리스트 확인 ({_udid})")
                    else:
                        subprocess.run(
                            ['adb', '-s', _udid, 'shell', 'cmd', 'deviceidle', 'whitelist', f'+{_ixio_pkg}'],
                            capture_output=True, text=True, timeout=5
                        )
                        print(f"  ✅ Doze 화이트리스트 등록 ({_udid})")
                except Exception as _e:
                    print(f"  ⚠️ Doze 화이트리스트 확인 실패 ({_udid}): {_e}")

        # 화자2 익시오 앱 재실행
        self._relaunch_ixio_speaker2()
        return True

    def _relaunch_ixio_speaker2(self):
        """화자2 디바이스에서 테스트 대상 앱을 종료 → 재실행."""
        _android_pkg = getattr(self, 'android_app_package', 'com.lguplus.aicallagent')
        _ios_bundle = getattr(self, 'ios_app_bundle_id', 'com.lguplus.aicallagent')

        if self.speaker2_platform == 'Android':
            _udid2 = self.speaker2_device
            try:
                print("  🔆 화자2(Android) 화면 상태 확인 중...")
                self.device_setup._adb_wake_screen(_udid2)
                print(f"  🔄 화자2(Android) 앱 종료 → 재실행 중... ({_android_pkg})")
                subprocess.run(
                    ['adb', '-s', _udid2, 'shell', 'am', 'force-stop', _android_pkg],
                    capture_output=True, text=True, timeout=5
                )
                time.sleep(1)
                subprocess.run(
                    ['adb', '-s', _udid2, 'shell', 'monkey', '-p', _android_pkg,
                     '-c', 'android.intent.category.LAUNCHER', '1'],
                    capture_output=True, text=True, timeout=5
                )
                time.sleep(2)
                print("  ✓ 화자2(Android) 앱 메인화면 진입 완료")
            except Exception as e:
                print(f"  ⚠️ 앱 재실행 실패: {e}")

        elif self.speaker2_platform == 'iOS' and 'speaker2' in self.drivers:
            sp2_drv = self.drivers['speaker2']
            try:
                print(f"  🔄 화자2(iOS) 앱 종료 → 재실행 중... ({_ios_bundle})")
                try:
                    sp2_drv.terminate_app(_ios_bundle)
                    time.sleep(1)
                    print("  ✓ 앱 종료 완료")
                except Exception:
                    print("  ℹ️ 앱이 실행 중이 아님 (종료 건너뜀)")
                try:
                    sp2_drv.execute_script('mobile: unlock')  # 화면 꺼진 경우 깨우기
                except Exception:
                    pass
                sp2_drv.activate_app(_ios_bundle)
                time.sleep(2)
                print("  ✓ 화자2(iOS) 앱 메인화면 진입 완료")
            except Exception as e:
                _emsg = str(e)
                if 'Session does not exist' in _emsg or 'invalid session id' in _emsg.lower():
                    print(f"  ⚠️ 화자2 Appium 세션 만료 — 세션 재생성 시도...")
                    try:
                        ok = self.setup_device(self.speaker2_device, 'speaker2', platform='iOS')
                        if ok:
                            print("  ✅ 화자2 Appium 세션 재생성 성공")
                            sp2_drv = self.drivers['speaker2']
                            try:
                                sp2_drv.execute_script('mobile: unlock')
                            except Exception:
                                pass
                            sp2_drv.activate_app(_ios_bundle)
                            time.sleep(2)
                            print("  ✓ 화자2(iOS) 앱 메인화면 진입 완료 (재세션)")
                        else:
                            print(f"  ❌ 화자2 세션 재생성 실패")
                    except Exception as re:
                        print(f"  ❌ 화자2 세션 재생성 중 오류: {re}")
                else:
                    print(f"  ⚠️ 앱 재실행 실패: {e}")

    def _relaunch_ixio_speaker1(self):
        """화자1 디바이스에서 테스트 대상 앱을 종료 → 재실행 (키패드 버튼 표시 보장)."""
        _android_pkg = getattr(self, 'android_app_package', 'com.lguplus.aicallagent')
        _ios_bundle = getattr(self, 'ios_app_bundle_id', 'com.lguplus.aicallagent')

        if self.speaker1_platform == 'Android':
            _udid1 = self.speaker1_device
            try:
                print(f"  🔄 화자1(Android) 앱 종료 → 재실행 중... ({_android_pkg})")
                subprocess.run(
                    ['adb', '-s', _udid1, 'shell', 'am', 'force-stop', _android_pkg],
                    capture_output=True, text=True, timeout=5
                )
                time.sleep(1)
                subprocess.run(
                    ['adb', '-s', _udid1, 'shell', 'monkey', '-p', _android_pkg,
                     '-c', 'android.intent.category.LAUNCHER', '1'],
                    capture_output=True, text=True, timeout=5
                )
                time.sleep(2)
                print("  ✓ 화자1(Android) 앱 메인화면 진입 완료")
            except Exception as e:
                print(f"  ⚠️ 앱 재실행 실패: {e}")

        elif self.speaker1_platform == 'iOS' and 'speaker1' in self.drivers:
            sp1_drv = self.drivers['speaker1']
            try:
                print(f"  🔄 화자1(iOS) 앱 종료 → 재실행 중... ({_ios_bundle})")
                try:
                    sp1_drv.terminate_app(_ios_bundle)
                    time.sleep(1)
                    print("  ✓ 앱 종료 완료")
                except Exception:
                    print("  ℹ️ 앱이 실행 중이 아님 (종료 건너뜀)")
                try:
                    sp1_drv.execute_script('mobile: unlock')  # 화면 꺼진 경우 깨우기
                except Exception:
                    pass
                sp1_drv.activate_app(_ios_bundle)
                time.sleep(2)
                print("  ✓ 화자1(iOS) 앱 메인화면 진입 완료")
            except Exception as e:
                _emsg = str(e)
                if 'Session does not exist' in _emsg or 'invalid session id' in _emsg.lower():
                    print(f"  ⚠️ 화자1 Appium 세션 만료 — 세션 재생성 시도...")
                    try:
                        ok = self.setup_device(self.speaker1_device, 'speaker1', platform='iOS')
                        if ok:
                            print("  ✅ 화자1 Appium 세션 재생성 성공")
                            sp1_drv = self.drivers['speaker1']
                            try:
                                sp1_drv.execute_script('mobile: unlock')
                            except Exception:
                                pass
                            sp1_drv.activate_app(_ios_bundle)
                            time.sleep(2)
                            print("  ✓ 화자1(iOS) 앱 메인화면 진입 완료 (재세션)")
                        else:
                            print(f"  ❌ 화자1 세션 재생성 실패")
                    except Exception as re:
                        print(f"  ❌ 화자1 세션 재생성 중 오류: {re}")
                else:
                    print(f"  ⚠️ 앱 재실행 실패: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    #  Phase 2: 발신 (Android / iOS)
    # ═══════════════════════════════════════════════════════════════════════

    def phase_call_from_android(self):
        """Android speaker1 → 키패드 + 번호 입력 + 발신.

        speaker2=iOS인 경우 android_caller_active_watcher도 시작.
        Returns: True | False
        """
        # 발신 전 익시오 앱 재실행 → 키패드 버튼 확실히 표시
        self._relaunch_ixio_speaker1()

        if not self.open_ixio_keypad('speaker1'):
            return False

        # 잔류 ACTIVE 정리 + ACTIVE 워쳐 시작 (sp2=iOS 시)
        if self.speaker2_platform == 'iOS':
            self._ensure_android_idle()
            self._phase_active_event = threading.Event()
            threading.Thread(
                target=self._start_android_caller_active_watcher,
                args=(self._phase_active_event,),
                daemon=True
            ).start()
            print("  ℹ️ Android 발신단 ACTIVE 워처 스레드 시작 (발신 직전)")

        if not self.make_call(self.speaker2_number):
            return False
        return True

    def phase_call_from_ios(self):
        """iOS speaker1 → 키패드 + 번호 입력 + 발신.

        Returns: True | False | 'crash'
        """
        # 발신 전 익시오 앱 재실행 → 키패드 버튼 확실히 표시
        self._relaunch_ixio_speaker1()

        if not self.open_keypad_iphone('speaker1'):
            return False
        # 발신 전 크래시 체크
        sp1_driver = self.drivers.get('speaker1')
        if sp1_driver and self.crash_reporter and self.crash_reporter.detect_crash(sp1_driver):
            self.crash_reporter.handle_crash(sp1_driver, extra_body="발신 전 단계에서 크래시 감지")
            return 'crash'
        if not self.make_call_iphone(self.speaker2_number):
            return False
        return True

    # ═══════════════════════════════════════════════════════════════════════
    #  Phase 2.5: Android sp2 수신 워쳐 (발신 전 시작)
    # ═══════════════════════════════════════════════════════════════════════

    def phase_start_android_sp2_watcher(self):
        """Android speaker2 수신 워쳐 — 발신 전에 미리 시작.

        Returns (answered_event, failed_event, accept_event).
        """
        self._phase_answered_event = threading.Event()
        self._phase_failed_event = threading.Event()
        self._phase_accept_event = threading.Event()
        threading.Thread(
            target=self._start_android_answer_watcher,
            args=(self._phase_answered_event, self._phase_failed_event, self._phase_accept_event),
            daemon=True
        ).start()
        print("  ℹ️ Android 수신 워처 스레드 시작 (발신 전)")

    # ═══════════════════════════════════════════════════════════════════════
    #  Phase 3: 수신 (Android sp2 / iOS sp2)
    # ═══════════════════════════════════════════════════════════════════════

    def _wait_ios_timer_00_for_trigger(self, driver, offhook_ts: float, timeout: float = 5.0) -> float:
        """OFFHOOK 이후 iOS 통화 타이머 00:xx 최초 감지 시각 반환.

        - 100ms 간격 폴링으로 page_source에서 00:\\d{2} 패턴 감지
        - 감지 성공: timer 등장 시각 반환 (이 시각을 _audio_ref_ts로 사용)
        - 감지 실패(timeout): offhook_ts 반환 (폴백)
        """
        import re as _re
        _CALL_TIMER_RE = _re.compile(r'\b(00:\d{2})\b')
        deadline = time.time() + timeout
        poll = 0
        while time.time() < deadline:
            try:
                src = driver.page_source
                poll += 1
                m = _CALL_TIMER_RE.search(src)
                if m:
                    ts = time.time()
                    print(f"  ✅ [iOS 타이머] '{m.group(1)}' 감지 → 기준점 확정 "
                          f"(OFFHOOK 후 {(ts - offhook_ts) * 1000:+.0f}ms, poll={poll}회)", flush=True)
                    return ts
            except Exception:
                pass
            # ⚠️ 100ms 폴링은 WDA에 ~50회/5s 요청 → CallKit PiP 활성 시 WDA 과부하.
            # 500ms로 줄여도 5초 내 충분히 감지 가능 (타이머는 연결 즉시 00:01부터 시작).
            time.sleep(0.5)
        print(f"  ⚠️ [iOS 타이머] {timeout:.0f}초 내 미감지 → OFFHOOK 기준으로 폴백 (poll={poll}회)")
        return offhook_ts

    def phase_answer_android_sp2(self) -> bool:
        """Android speaker2 수신: Step1(accept) → Step2(OFFHOOK) → 녹음+재생.

        self._phase_accept_event, self._phase_answered_event 사용.
        Returns True on success.
        """
        self._phase_android_sp2_early = True
        accept_event = self._phase_accept_event
        answered_event = self._phase_answered_event
        failed_event = self._phase_failed_event

        # [Step1] accept 명령 전송 확인 → 기준점 확보
        print("📱 화자2: 수신 대기...(Android RINGING+accept 감지 중)")

        # 워쳐 실패 신호를 먼저 체크 (120초 폴링 종료 등)
        if failed_event.is_set():
            print("❌ Android 수신 워쳐 이미 실패 — 오디오 재생 건너뜀\n")
            self.end_call()
            return False

        if not accept_event.wait(timeout=80.0):
            # 타임아웃: 워쳐 실패 여부 최종 확인
            if failed_event.is_set():
                print("❌ Android 수신 워쳐 실패 (RINGING 미감지 120초 타임아웃) — 오디오 재생 건너뜀\n")
            else:
                print("❌ Android accept 신호 없음 (80초 타임아웃) — 오디오 재생 건너뜀\n")
            self.end_call()
            return False
        accept_ts = getattr(accept_event, '_accept_sent_ts', time.time())
        _t0 = accept_ts
        print(f"  ✅ [Step1] accept 명령 확인 — T+{(time.time()-_t0)*1000:.0f}ms")

        # ⚡ Step1 직후: iOS sp1 팝업/타이머 확인 (백그라운드)
        if self.speaker1_platform == 'iOS' and 'speaker1' in self.drivers:
            _sp1_drv = self.drivers.get('speaker1')
            def _check_sp1(_drv=_sp1_drv):
                # ⚠️ CallKit PiP 활성 시 iOS WDA page_source가 각 호출마다 XCUITest
                # 전체 snapshot을 재생성하므로 200ms 간격이면 ~300회/60s 요청 → WDA 과부하.
                # poll_interval=1.5s + max_wait=20s → 최대 13회로 제한.
                ok = self.wait_for_call_connecting_state(
                    roles=['speaker1'], max_wait=20, poll_interval=1.5,
                )
                print(f"  [sp1 확인] {'✅ 발신단(iOS) 타이머 00:00 확인' if ok else '⚠️ 발신단(iOS) 연결 확인 불가'}")
                self._tap_video_call_popup(_drv, 'speaker1', 'iOS', timeout=15.0)
            threading.Thread(target=_check_sp1, daemon=True).start()

        print("  🔍 '보이는 전화' 팝업 감지 스레드 시작 (Step2 대기 전)")
        # Android sp2 팝업 감지
        _vpc_drv = self.drivers.get('speaker2')
        if _vpc_drv:
            threading.Thread(
                target=self._tap_video_call_popup,
                args=(_vpc_drv, 'speaker2', 'Android'),
                daemon=True,
            ).start()

        # [Step2] OFFHOOK 확인
        print("  ⏳ [Step2] OFFHOOK 확인 대기 (통화 연결 확인 중...)")
        if not answered_event.wait(timeout=20.0):
            print("  ⚠️ OFFHOOK 미확인 (20초 타임아웃) — accept 기준으로 재생 강행")
            offhook_ts = time.time()
            _cmd_sent_ts = accept_ts
        else:
            offhook_ts = getattr(answered_event, '_offhook_ts', time.time())
            _cmd_sent_ts = getattr(answered_event, '_cmd_sent_ts', accept_ts)
            print(f"  ✅ [Step2] OFFHOOK 확인 — T+{(offhook_ts-_t0)*1000:.0f}ms")

        # iOS 발신 시 OFFHOOK 직후 오디오 라우팅 강제 설정 (백그라운드)
        if self.speaker1_platform == 'iOS':
            threading.Thread(target=self.force_ios_external_mic, daemon=True).start()

        _now = time.time()
        print(f"  [TIMING] accept→지금: {(_now-_t0)*1000:.0f}ms | cmd_sent→지금: {(_now-_cmd_sent_ts)*1000:.0f}ms | offhook→지금: {(_now-offhook_ts)*1000:.0f}ms")

        # 기준점 설정: iOS sp1이면 00:xx 타이머 감지 시점 사용 (편차 ±365ms 최소화)
        # Android sp1이면 cmd_sent_ts 사용 (기존 동작)
        if self.speaker1_platform == 'iOS' and self.drivers.get('speaker1'):
            _ref = self._wait_ios_timer_00_for_trigger(
                self.drivers['speaker1'], offhook_ts, timeout=5.0,
            )
            print(f"  [TIMING] 기준점=iOS 타이머 00:xx 감지 시점 (OFFHOOK 후 {(_ref-offhook_ts)*1000:+.0f}ms)")
        else:
            _ref = _cmd_sent_ts
            print(f"  [TIMING] 기준점=cmd_sent_ts+0.0s (즉시)")
        self._audio_ref_ts = _ref
        self._audio_target_offset = 0.0

        # 녹음 + 재생 동시 시작
        self._start_recording_and_playback()
        return True

    def phase_answer_ios_sp2(self) -> bool:
        """iOS speaker2 수신: 클릭 워쳐 + answer_call + ACTIVE 대기 → 녹음+재생.

        self._phase_active_event 사용 (Android caller active event).
        Returns True on success.
        """
        self._phase_android_sp2_early = False

        if 'speaker2' not in self.drivers:
            # 드라이버 없음 → wait_for_call_connecting_state
            call_connected = self.wait_for_call_connecting_state()
            if not call_connected:
                print("❌ 통화 연결이 확인되지 않아 오디오 재생을 건너뜁니다.\n")
                self.end_call()
                return False
            self._start_recording_and_playback()
            return True

        active_event = self._phase_active_event

        if active_event is not None:
            # iOS 수신 완료를 별도 이벤트로 추적
            self._phase_ios_answered_event = threading.Event()
            _ios_ans_evt = self._phase_ios_answered_event
            self._ios_answer_btn_clicked_at = None

            def _click_watcher(_evt=_ios_ans_evt):
                deadline = time.time() + 35.0
                while time.time() < deadline:
                    ts = getattr(self, '_ios_answer_btn_clicked_at', None)
                    if ts is not None:
                        _evt._answer_ts = ts
                        _evt.set()
                        return
                    time.sleep(0.05)
                print("  [클릭워쳐] ⚠️ 35초 내 버튼 클릭 미감지 — 이벤트 미설정")

            _sp2_drv = self.drivers.get('speaker2')

            def _do_answer(_drv=_sp2_drv):
                result = self.answer_call_on_speaker2()
                if result:
                    self._tap_video_call_popup(_drv, 'speaker2', 'iOS', timeout=20.0)
                else:
                    print("  [수신워쳐] ⚠️ iOS 수신 실패")

            threading.Thread(target=_click_watcher, daemon=True).start()
            threading.Thread(target=_do_answer, daemon=True).start()
            print("📱 화자2: iOS 수신 처리 백그라운드 시작 (클릭 감지 워쳐 활성화)")

            # Android 발신단 ACTIVE 대기
            print("📱 화자1: 통화 연결 대기...(Android ACTIVE 감지 중)")
            if active_event.wait(timeout=60.0):
                active_ts = getattr(active_event, '_active_ts', time.time())
                print("✅ Android 발신단 통화 연결 확인 (ACTIVE 감지)")
                self._audio_ref_ts = active_ts
            else:
                print("❌ Android 발신단 ACTIVE 미감지 (60초 타임아웃)\n")
                self.end_call()
                return False

            # iOS 수신 완료 대기
            _ios_wait = 30.0
            if not _ios_ans_evt.wait(timeout=_ios_wait):
                print(f"  ⚠️ iOS 수신 확인 타임아웃({_ios_wait:.0f}초) — 음원 재생 강행")
            else:
                ios_ans_ts = getattr(_ios_ans_evt, '_answer_ts', time.time())
                self._audio_ref_ts = ios_ans_ts
                print("  ✅ iOS 수신 버튼 클릭 확인 — 500ms 후 음원 재생 시작")
        else:
            self.answer_call_on_speaker2()
            call_connected = self.wait_for_call_connecting_state()
            if not call_connected:
                print("❌ 통화 연결이 확인되지 않아 오디오 재생을 건너뜁니다.\n")
                self.end_call()
                return False

        # Post-connect: Android sp1 팝업 감지
        if self.speaker1_platform == 'Android':
            _vpc_drv = self.drivers.get('speaker1')
            if _vpc_drv:
                print("  🔍 '보이는 전화' 팝업 감지 스레드 시작")
                threading.Thread(
                    target=self._tap_video_call_popup,
                    args=(_vpc_drv, 'speaker1', 'Android'),
                    daemon=True,
                ).start()

        # 녹음 + 재생 시작
        self._start_recording_and_playback()
        return True

    # ═══════════════════════════════════════════════════════════════════════
    #  Phase 4: 보이스피싱 감지 (TC_03/TC_04 전용)
    # ═══════════════════════════════════════════════════════════════════════

    def phase_vishing(self):
        """보이스피싱 팝업 감지 스레드를 양쪽 디바이스에 시작."""
        _vishing_lock = threading.Lock()
        for _role, _plat in [
            ('speaker1', self.speaker1_platform),
            ('speaker2', self.speaker2_platform),
        ]:
            _drv = self.drivers.get(_role)
            if not _drv:
                continue

            def _vishing_worker(_drv=_drv, _role=_role, _plat=_plat):
                det, path = self._detect_vishing_popup(
                    _drv, _role, _plat,
                    self.screenshot_dir, self._phase_vishing_stop,
                    tc_type=self.tc_type,
                )
                if det:
                    with _vishing_lock:
                        self._phase_vishing_result['detected'] = True
                        if path and not self._phase_vishing_result['path']:
                            self._phase_vishing_result['path'] = path
                    self._phase_vishing_stop.set()

            _t = threading.Thread(target=_vishing_worker, daemon=True)
            _t.start()
            self._phase_vishing_threads.append(_t)
            print(f"  🔍 [{_role}/{_plat}] 보이스피싱 팝업 감지 시작")

    # ═══════════════════════════════════════════════════════════════════════
    #  Phase 5: 오디오 완료 대기 + 수집 + 결과
    # ═══════════════════════════════════════════════════════════════════════

    def phase_finalize(self):
        """오디오 재생 완료 대기, 녹음·통화 종료, 음원 수집, 결과 반환.

        Returns: dict (success) | 'retry' | 'crash' | False
        """
        # 7. 오디오 재생 완료 대기
        call_completed = self.wait_for_audio_completion()

        # 크래시 체크 — Appium 세션 만료 시 page_source 블로킹 방지: 10초 타임아웃
        sp1_driver = self.drivers.get('speaker1')
        _crash_detected = False
        if sp1_driver and self.crash_reporter:
            import threading as _th_cr2
            _cr2_result = [False]
            _cr2_done = _th_cr2.Event()
            def _run_crash_check2():
                try:
                    _cr2_result[0] = self.crash_reporter.detect_crash(sp1_driver)
                except Exception as _ce2:
                    print(f"⚠️ [CrashReporter] detect_crash 오류: {_ce2}")
                finally:
                    _cr2_done.set()
            _th_cr2.Thread(target=_run_crash_check2, daemon=True).start()
            if not _cr2_done.wait(timeout=10):
                print("⚠️ [CrashReporter] detect_crash 10초 타임아웃 — 크래시 없음으로 간주")
            else:
                _crash_detected = _cr2_result[0]
        if _crash_detected:
            self.crash_reporter.handle_crash(sp1_driver, extra_body="오디오 재생 완료 후 크래시 감지")
            self._stop_recording()
            self.end_call()
            return 'crash'

        # 7-1. 녹음 종료
        _rec_target2 = None
        if hasattr(self, '_mixer_recorder') and self._mixer_recorder and self._mixer_recorder.is_recording:
            _rec_target2 = self._mixer_recorder
        elif hasattr(self, '_call_recorder') and self._call_recorder and self._call_recorder.is_recording:
            _rec_target2 = self._call_recorder
        if _rec_target2:
            import threading as _th_rec2
            _rec2_result = [{}]
            _rec2_done = _th_rec2.Event()
            def _run_rec_stop2():
                try:
                    _rec2_result[0] = _rec_target2.stop()
                except Exception as _re2:
                    print(f"⚠️ [Recorder] stop() 오류: {_re2}")
                finally:
                    _rec2_done.set()
            print("⏹️ 녹음 종료 중...")
            _th_rec2.Thread(target=_run_rec_stop2, daemon=True).start()
            if not _rec2_done.wait(timeout=30):
                print("⚠️ [Recorder] stop() 30초 타임아웃 — 강제 진행")
            else:
                _recorder_paths = _rec2_result[0]
        else:
            _recorder_paths = self._stop_recording()

        # 8. 통화 종료
        self.end_call()

        # 8-1. 음원 수집
        self._collected_audio = self._collect_audio(_recorder_paths)

        # 8-2. 보이스피싱 결과 수집
        self._finalize_vishing()

        if not call_completed:
            print(f"\n{'='*60}")
            print("⚠️ 통화가 강제 종료되어 테스트가 조기 종료되었습니다.")
            print(f"{'='*60}\n")
            return 'retry'

        print(f"\n{'='*60}")
        print("✅ 테스트 완료!")
        print(f"{'='*60}\n")

        collected = getattr(self, '_collected_audio', {})
        return {
            'success': True,
            'ios_recording': str(collected.get('ios_path') or ''),
            'android_recording': str(collected.get('android_path') or ''),
            'mixed_recording': str(collected.get('mixed_path') or ''),
        }

    # ═══════════════════════════════════════════════════════════════════════
    #  내부 헬퍼
    # ═══════════════════════════════════════════════════════════════════════

    def _start_recording_and_playback(self):
        """녹음 시작 + 오디오 재생.

        self._pre_warmed=True 시 pre-warm된 subprocess에 trigger 전송 (즉시 재생).
        그렇지 않으면 기존 play_audio_after_delay (3.0초 sync 대기).
        """
        self._call_start_ts = _dt.now().strftime('%Y%m%d_%H%M%S')

        # pre-warm 모드에서는 prepare_audio_players()가 이미 정리함
        if not getattr(self, '_pre_warmed', False):
            self._clean_audio_started_ts_files()

        if self._mixer_recorder:
            threading.Thread(target=self._mixer_recorder.start, daemon=True).start()
        elif self._call_recorder:
            threading.Thread(target=self._call_recorder.start, daemon=True).start()
        print("  🎙️ 녹음 시작 (통화 00:00 기준)")

        if getattr(self, '_pre_warmed', False):
            # Pre-warm 모드: subprocess 이미 초기화 완료 → 100ms 여유 후 동시 재생
            _play_at = time.time() + 0.1
            _ref_ts = getattr(self, '_audio_ref_ts', None)
            if _ref_ts:
                print(f"  [TIMING] PRE-WARM 모드 — trigger {(_play_at - _ref_ts)*1000:.0f}ms after ref")
            self.trigger_audio_playback(_play_at)
            self._sync_play_start_time()
        else:
            # 기존 방식: subprocess 생성 + 3.0초 sync 대기
            _ref_ts = getattr(self, '_audio_ref_ts', None)
            _offset = getattr(self, '_audio_target_offset', 0.3)
            self.play_audio_after_delay(delay=0, ref_ts=_ref_ts, target_offset=_offset)
            self._sync_play_start_time()

    def _stop_recording(self) -> dict:
        """녹음 중지 후 녹음 파일 경로를 반환."""
        if self._mixer_recorder and self._mixer_recorder.is_recording:
            return self._mixer_recorder.stop()
        elif self._call_recorder and self._call_recorder.is_recording:
            return self._call_recorder.stop()
        return {}

    def _collect_audio(self, recorder_paths: dict) -> dict:
        """통화 종료 후 음원 수집."""
        try:
            from call_audio_collector import CallAudioCollector
            _available = True
        except ImportError:
            _available = False

        if self._recording_mode == 'direct' and recorder_paths:
            return {
                'android_path': str(recorder_paths.get('android') or ''),
                'ios_path': str(recorder_paths.get('ios') or ''),
            }

        if not _available:
            return {}

        android_udid = ""
        if self.speaker2_platform == 'Android':
            android_udid = self.speaker2_device
        elif self.speaker1_platform == 'Android':
            android_udid = self.speaker1_device

        ios_udid = ""
        ios_driver = None
        if self.speaker1_platform == 'iOS':
            ios_udid = self.speaker1_device
            ios_driver = self.drivers.get('speaker1')
        elif self.speaker2_platform == 'iOS':
            ios_udid = self.speaker2_device
            ios_driver = self.drivers.get('speaker2')

        _android_wait = 5.0
        try:
            from config import ANDROID_RECORDING_WAIT_SEC
            _android_wait = float(ANDROID_RECORDING_WAIT_SEC)
        except (ImportError, AttributeError):
            pass

        if not android_udid:
            print("  ⚠️ Android UDID 없음 → 통화 음원 수집 건너뜀")
            return {}

        collector = CallAudioCollector(
            android_udid=android_udid,
            ios_driver=ios_driver,
            ios_udid=ios_udid,
            call_start_ts=self._call_start_ts,
            android_wait_sec=_android_wait,
        )
        result = collector.collect_and_mix()
        ios_rec = result.get('ios_path')
        android_rec = result.get('android_path')
        if ios_rec:
            print(f"📱 iOS 앱 녹음: {ios_rec}")
        if android_rec:
            print(f"📱 Android 통화록: {android_rec}")
        if not ios_rec and not android_rec:
            print("  ⚠️ 수집된 통화 음원 없음")
        return result

    def _finalize_vishing(self):
        """보이스피싱 감지 스레드 종료 + 결과 수집."""
        self._phase_vishing_stop.set()
        for _t in self._phase_vishing_threads:
            _t.join(timeout=5.0)

        # fallback: TC ID / 최근 파일 탐색
        if self.tc_type in ('TC_03', 'TC_04') and not self._phase_vishing_result.get('path'):
            import glob as _glob
            import os as _os
            _pattern_tc = _os.path.join(self.screenshot_dir, f'vishing_popup_{self.tc_type}_*.png')
            _candidates = sorted(_glob.glob(_pattern_tc), key=lambda f: _os.path.getmtime(f), reverse=True)
            if not _candidates:
                _pattern_any = _os.path.join(self.screenshot_dir, 'vishing_popup_*.png')
                _candidates = [
                    f for f in sorted(_glob.glob(_pattern_any), key=lambda f: _os.path.getmtime(f), reverse=True)
                    if time.time() - _os.path.getmtime(f) < 300
                ]
            if _candidates:
                self._phase_vishing_result['path'] = _candidates[0]
                if not self._phase_vishing_result['detected']:
                    self._phase_vishing_result['detected'] = True
                print(f"  📦 fallback: 보이스피싱 스크린샷 확인 → {_candidates[0]}")

        self._screenshots = []
        self._vishing_detected = self._phase_vishing_result['detected']
        if self._phase_vishing_result['path']:
            self._screenshots.append(self._phase_vishing_result['path'])
        if self.tc_type in ('TC_03', 'TC_04'):
            _det_str = '✅ 감지됨' if self._vishing_detected else '❌ 미감지'
            print(f"  🛡 보이스피싱 팝업 감지 결과: {_det_str}")

    # ═══════════════════════════════════════════════════════════════════════
    #  run() 래퍼 — try/except/finally 공통 구조
    # ═══════════════════════════════════════════════════════════════════════

    def _run_phases(self):
        """하위 클래스가 오버라이드하여 phase 조합을 정의."""
        raise NotImplementedError("하위 TC 클래스에서 _run_phases()를 구현하세요.")

    def run(self):
        """전체 테스트 실행 (공통 try/except/finally 래퍼)."""
        try:
            return self._run_phases()
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"❌ 테스트 실패: {e}")
            print(f"{'='*60}\n")
            return False
        finally:
            time.sleep(2)
            self.teardown()
            restore_default_devices(verbose=True)
