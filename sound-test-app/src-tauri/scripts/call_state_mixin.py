"""
call_state_mixin.py
─────────────────────────────────────────────────────────────────
통화 연결 상태 감지 Mixin (IxioAutomatedTest에서 분리, SRP)

담당 기능:
  - _is_call_active_android : ADB dumpsys로 Android 연결 여부 확인
  - _is_call_active_ios      : Appium page_source로 iOS 연결 여부 확인
  - wait_for_call_connecting_state : 플랫폼 무관 통화 연결 대기

전제:
  self.speaker1_platform, self.speaker2_platform  ('iOS' | 'Android')
  self.speaker1_device, self.speaker2_device       (UDID / serial)
  self.drivers                                      (dict[str, WebDriver])
"""

import re
import subprocess
import time


class CallStateMixin:
    """통화 연결 상태 감지 전담 Mixin."""

    # ── Android ──────────────────────────────────────────────────────────────

    def _is_call_active_android(self, udid: str) -> bool:
        """ADB 다중 명령으로 Android 통화 연결 여부 확인.

        ⚠️ mCallState=2(OFFHOOK)는 발신자가 전화 거는 순간에도 2가 되므로 사용하지 않음.
           수신자가 수락해 양쪽 모두 연결됐을 때만 True 를 반환하도록:

        방법1: dumpsys telephony.registry  mForegroundCallState=ACTIVE (양쪽 연결 후만)
        방법2: dumpsys phone               mForegroundCall state: ACTIVE
        방법3: dumpsys telecom             mCallState: ACTIVE / STATE_ACTIVE

        ⚠️ dumpsys audio (IN_COMMUNICATION) 체크는 제거됨:
           익시오(VoIP) 앱이 포그라운드에 있기만 해도 IN_COMMUNICATION 설정 →
           통화 중이 아닌데도 ACTIVE 오탐 발생. wait_for_audio_completion()에서
           별도로 audio mode를 인라인 체크하므로 여기서는 telephony/telecom만 사용.
        """
        # ① telephony.registry
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

        # ③ dumpsys telecom (양쪽 연결 후에만 ACTIVE)
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

    def _is_call_active_android_voip(self, udid: str) -> bool:
        """VoIP(익시오) 통화 ACTIVE 감지 — dumpsys audio 기반.

        ⚠️ 이 메서드는 _ensure_android_idle()에서 사용 금지!
           익시오 앱이 포그라운드에 있기만 해도 IN_COMMUNICATION이 설정되므로
           잔류 ACTIVE 판정에는 부적합.
        워쳐 스레드에서 telephony/telecom 미감지 시 VoIP 보완용으로만 사용.
        """
        try:
            aud = subprocess.run(
                ['adb', '-s', udid, 'shell', 'dumpsys', 'audio'],
                capture_output=True, text=True, timeout=5
            ).stdout
            if re.search(r'(?:IN_CALL|IN_COMMUNICATION|mMode=3\b)', aud):
                return True
        except Exception:
            pass
        return False

    def _is_call_active_android_ui(self, driver) -> bool:
        """Appium page_source 로 Android 통화 연결 여부 확인 (VoIP 전용 보완).

        telephony API가 VoIP 연결을 반영하지 않는 경우를 대비해
        익시오 앱의 통화 화면 UI 요소로 연결 여부를 판단합니다.

        판별 조건:
          통화 중 표시나 타이머 패턴이 보이면 연결됨으로 판단.
        """
        _CALL_LABELS = ['끊기', '통화 종료', '음소거', '스피커', '키패드',
                        '마이크', '통화 녹음']
        _TIMER_RE = re.compile(r'\b\d{1,2}:\d{2}\b')
        _pkg = getattr(self, 'android_app_package', 'com.lguplus.aicallagent')
        _CALL_IDS = [
            f'{_pkg}:id/btn_end_call',
            f'{_pkg}:id/call_duration',
            f'{_pkg}:id/tv_call_time',
        ]
        try:
            src = driver.page_source
            # resource-id 기반 (가장 정확)
            for rid in _CALL_IDS:
                if rid in src:
                    return True
            # 타이머 패턴(XX:XX) 존재 확인
            if _TIMER_RE.search(src):
                return True
            # 끊기 버튼 text/content-desc
            if any(
                f'text="{lbl}"' in src
                or f'content-desc="{lbl}"' in src
                or f'>끊기<' in src
                for lbl in _CALL_LABELS
            ):
                return True
        except Exception:
            pass
        return False

    # ── iOS ──────────────────────────────────────────────────────────────────

    def _is_call_active_ios(self, driver) -> bool:
        """Appium page_source 로 iOS 통화 연결 여부 확인.

        판별 조건 (AND):
          1. 통화 제어 버튼 (끊기 / 음소거 / 스피커 등) → 통화 화면임을 확인
          2. 통화 타이머 패턴 00:xx 존재 (2자리:2자리) → 실제 연결됨을 확인
             ※ 상태바 시각(4:30 등, 1자리:2자리)과 구분하기 위해 \\d{2}:\\d{2} 사용
        """
        _CALL_BTNS = ['끊기', 'End', '음소거', 'Mute', '스피커', 'Speaker',
                      '통화 효음', '보류', 'Hold']
        _TIMER_RE  = re.compile(r'\b\d{2}:\d{2}\b')
        try:
            src = driver.page_source
            has_call_button = any(
                f'name="{kw}"' in src or f'label="{kw}"' in src
                for kw in _CALL_BTNS
            )
            return has_call_button and bool(_TIMER_RE.search(src))
        except Exception:
            pass
        return False

    # ── 공통 대기 ────────────────────────────────────────────────────────────

    def wait_for_call_connecting_state(self, roles: 'list[str] | None' = None,
                                       max_wait: int = 60,
                                       poll_interval: float = 0.2) -> bool:
        """통화 연결 확인 (수신자가 실제로 수락한 이후에만 True 반환).

        roles: 확인할 역할 목록. None이면 speaker1+speaker2 모두 확인.
               예) roles=['speaker1'] → 발신단만 확인.
        max_wait: 최대 대기 시간(초). Android OFFHOOK 확인 후 iOS 단독 확인 시 10~20초 적합.
        """
        print(f"⏳ 통화 연결 대기 중...")
        print(f"   통화 화면 UI 요소 확인 중...\n")

        max_wait_time = max_wait
        start_time    = time.time()

        target_roles = roles if roles is not None else ['speaker1', 'speaker2']
        checks: list = []
        for role, platform in [('speaker1', self.speaker1_platform),   # type: ignore[attr-defined]
                                ('speaker2', self.speaker2_platform)]:  # type: ignore[attr-defined]
            if role not in target_roles:
                continue
            udid   = self.speaker1_device if role == 'speaker1' else self.speaker2_device  # type: ignore[attr-defined]
            driver = self.drivers.get(role)                                                 # type: ignore[attr-defined]
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

            elapsed = time.time() - start_time
            if elapsed >= 5 and int(elapsed) % 5 == 0:
                print(f"  ⏳ {int(elapsed)}초 경과, 통화 연결 대기 중...")
            time.sleep(poll_interval)

        print(f"⚠️ {max_wait_time}초 내 통화 연결을 확인하지 못함\n")
        return False

    # ── idevicesyslog 기반 iOS 통화 연결 감지 ────────────────────────────────

    def wait_ios_call_active_via_syslog(
        self,
        udid: str,
        timeout: float = 30.0,
    ) -> bool:
        """idevicesyslog로 iOS 앱 syslog를 스트리밍해 CALL_STATUS_ACTIVE 감지.

        iPhone이 USB로 연결된 경우에만 동작합니다.
        감지 시 즉시 True 반환. timeout 초과 또는 idevicesyslog 사용 불가 시 False 반환.

        탐지 키워드 (CallView.swift 로그):
          - 'CALL_STATUS_ACTIVE'
          - 'handleActiveCallStatus'
        """
        import select
        import shutil

        if not shutil.which('idevicesyslog'):
            return False

        cmd = ['idevicesyslog', '-u', udid, '-m', 'CALL_STATUS_ACTIVE']
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except Exception:
            return False

        detected = False
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                ready, _, _ = select.select([proc.stdout], [], [], min(0.5, remaining))
                if ready:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if 'CALL_STATUS_ACTIVE' in line or 'handleActiveCallStatus' in line:
                        detected = True
                        break
        except Exception:
            pass
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        return detected

    def start_ios_syslog_watcher(
        self,
        udid: str,
        detected_event: 'threading.Event',
        stop_event: 'threading.Event',
    ) -> None:
        """백그라운드 스레드에서 idevicesyslog를 스트리밍해 CALL_STATUS_ACTIVE 감지 (USB 전용).

        USB 미연결 시 2초 내 출력이 없으면 조용히 종료합니다 (stop_event는 건드리지 않음).
        """
        import select
        import shutil

        if not shutil.which('idevicesyslog'):
            return

        cmd = ['idevicesyslog', '-u', udid, '-m', 'CALL_STATUS_ACTIVE']
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except Exception:
            return

        # USB 연결 확인: 2초 내 첫 출력이 없으면 연결 안 된 것 → 포기
        usb_confirmed = False
        try:
            ready, _, _ = select.select([proc.stdout], [], [], 2.0)
            if not ready:
                # 연결 안 됨 (무선 등) → 즉시 종료
                proc.terminate()
                proc.wait(timeout=2)
                return
            first_line = proc.stdout.readline()
            if not first_line:
                proc.terminate()
                proc.wait(timeout=2)
                return
            usb_confirmed = True
            # 첫 줄에 이미 키워드가 있을 수 있음
            if 'CALL_STATUS_ACTIVE' in first_line or 'handleActiveCallStatus' in first_line:
                detected_event.set()
                proc.terminate()
                proc.wait(timeout=2)
                return
        except Exception:
            pass

        if not usb_confirmed:
            return

        try:
            while not stop_event.is_set():
                ready, _, _ = select.select([proc.stdout], [], [], 0.2)
                if ready:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if 'CALL_STATUS_ACTIVE' in line or 'handleActiveCallStatus' in line:
                        detected_event.set()
                        break
        except Exception:
            pass
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def start_ios_appium_timer_watcher(
        self,
        driver,
        detected_event: 'threading.Event',
        stop_event: 'threading.Event',
    ) -> None:
        """백그라운드 스레드에서 Appium page_source를 폴링해 iOS 통화 타이머 0:00 감지.

        USB/무선 무관하게 동작합니다. 통화 타이머가 나타나면 detected_event.set().
        syslog 워처와 병렬로 실행하면 먼저 감지된 쪽이 트리거됩니다.
        """
        import re as _re

        # 통화 타이머 패턴 — 2자리:2자리 (00:01 등)
        # ※ 상태바 시각(4:30, 1자리:2자리)과 구분하기 위해 \b\d{2}:\d{2}\b 사용
        _TIMER_RE  = _re.compile(r'\b\d{2}:\d{2}\b')
        _CALL_BTNS = ['끊기', 'End', '음소거', 'Mute', '스피커', 'Speaker', '통화 효음']

        if driver is None:
            return

        poll_count = 0
        start_ts = time.time()
        while not stop_event.is_set():
            try:
                src = driver.page_source
                poll_count += 1
                has_call_btn = any(
                    f'name="{k}"' in src or f'label="{k}"' in src
                    for k in _CALL_BTNS
                )
                if has_call_btn:
                    if _TIMER_RE.search(src):
                        elapsed = time.time() - start_ts
                        print(f"  ✅ [Appium 타이머 워처] 0:00 감지 → 트리거 "
                              f"(elapsed={elapsed:.2f}s, poll={poll_count}회)", flush=True)
                        detected_event.set()
                        return
                    # 통화 화면은 감지되는데 타이머는 아직 없으면 더 짧은 간격으로
                    time.sleep(0.15)
                    continue
            except Exception:
                pass
            time.sleep(0.5)
