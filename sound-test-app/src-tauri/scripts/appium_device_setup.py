"""
appium_device_setup.py
──────────────────────────────────────────────────────────────────────────────
Appium 드라이버 연결/해제 담당 (SRP 분리 — IxioAutomatedTest God-Class에서 추출).

책임:
  - Android/iOS Appium capabilities 생성 및 드라이버 연결
  - adb connect 자동 재시도 (무선 Android 연결)
  - 사용 중인 포트 강제 해제
"""

import subprocess
import sys
import threading
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.options.ios import XCUITestOptions
from selenium.webdriver.support.ui import WebDriverWait


class AppiumDeviceSetup:
    """Appium 드라이버 생성/연결 단일 책임 클래스."""

    # WDA 포트 역할별 기본값 (iOS-iOS 시 두 기기가 포트 충돌하지 않도록)
    _WDA_PORTS = {
        'speaker1': {'wdaLocalPort': 8100, 'mjpegServerPort': 9100},
        'speaker2': {'wdaLocalPort': 8200, 'mjpegServerPort': 9200},
    }

    def __init__(
        self,
        appium_server_android: str = 'http://127.0.0.1:4723',
        appium_server_ios: str = 'http://127.0.0.1:4724',
        appium_server_ios_sp2: str | None = None,
        wda_manager=None,
        wda_manager_sp2=None,
        android_app_package: str = 'com.lguplus.aicallagent',
        android_app_activity: str = '.MainActivity',
        ios_app_bundle_id: str = 'com.lguplus.aicallagent',
    ):
        self.appium_server_android = appium_server_android
        self.appium_server_ios = appium_server_ios
        # iOS-iOS: sp2 전용 Appium 서버 (None이면 단일 서버 모드)
        self.appium_server_ios_sp2 = appium_server_ios_sp2
        self.wda_manager = wda_manager        # sp1 iOS / 단일 iOS WDA 관리자
        self.wda_manager_sp2 = wda_manager_sp2  # sp2 iOS 전용 WDA 관리자 (iOS-iOS만)
        self._target_android_pkg = android_app_package
        self._target_android_activity = android_app_activity
        self._target_ios_bundle = ios_app_bundle_id

    # ─────────────────────────────────────────────────────────────────────────

    def _wait_for_appium_server(self, server_url: str, timeout: float = 15) -> bool:
        """Appium 서버가 /status에 응답할 때까지 대기.

        Args:
            server_url: 예) 'http://127.0.0.1:4725'
            timeout: 최대 대기 시간(초)

        Returns:
            True if server is alive, False if timeout.
        """
        import time as _time
        import urllib.request
        status_url = f"{server_url}/status"
        deadline = _time.time() + timeout
        attempt = 0
        while _time.time() < deadline:
            attempt += 1
            try:
                req = urllib.request.urlopen(status_url, timeout=2)
                if req.status == 200:
                    if attempt > 1:
                        print(f"  ✅ Appium 서버 응답 확인 ({server_url}) — {attempt}번째 시도")
                    return True
            except Exception:
                pass
            if attempt == 1:
                print(f"  ⏳ Appium 서버 대기 중... ({server_url})")
            _time.sleep(1.0)
        return False

    def _adb_reset_uiautomator2(self, device_udid: str) -> None:
        """UiAutomator2 서버 프로세스를 강제 종료하여 깨끗한 상태에서 재시작.

        Appium 세션 생성 전에 호출하면, Appium이 UiAutomator2를 새로 기동한다.
        이전 세션의 좀비 프로세스나 크래시 잔류 상태를 원천 정리.
        """
        _UIA2_PKGS = [
            'io.appium.uiautomator2.server',
            'io.appium.uiautomator2.server.test',
        ]
        for pkg in _UIA2_PKGS:
            try:
                subprocess.run(
                    ['adb', '-s', device_udid, 'shell', 'am', 'force-stop', pkg],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
        # instrumentation 프로세스 직접 kill (force-stop 누락 대비)
        try:
            subprocess.run(
                ['adb', '-s', device_udid, 'shell',
                 'pkill', '-f', 'uiautomator'],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
        import time as _time
        _time.sleep(0.5)  # 프로세스 종료 대기
        print(f"  🔄 UiAutomator2 서버 초기화 완료 ({device_udid})")

    def _adb_keep_screen_on(self, device_udid: str) -> None:
        """ADB 시스템 설정으로 화면 꺼짐 방지 (UiAutomator2 세션 독립).

        블로킹 방지: adb 명령 3개를 백그라운드 daemon 스레드에서 실행.
        """
        def _run():
            cmds = [
                ['adb', '-s', device_udid, 'shell', 'settings', 'put', 'system', 'screen_off_timeout', '86400000'],
                ['adb', '-s', device_udid, 'shell', 'settings', 'put', 'global', 'stay_on_while_plugged_in', '7'],
                ['adb', '-s', device_udid, 'shell', 'svc', 'power', 'stayon', 'true'],
            ]
            _all_ok = True
            for cmd in cmds:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if result.returncode != 0 and result.stderr.strip():
                        _all_ok = False
                except Exception:
                    _all_ok = False
            if _all_ok:
                print(f"  🔒 화면 꺼짐 방지 설정 완료 ({device_udid})")
            # 화면이 꺼져 있으면 강제로 켜기
            self._adb_wake_screen(device_udid)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        # 최대 3초만 기다려 빠른 경우 즉시 완료, 느린 경우 백그라운드 계속 실행
        t.join(timeout=3)
        if t.is_alive():
            print(f"  🔒 화면 꺼짐 방지 설정 중... (백그라운드, {device_udid})")

    def _ios_keep_screen_on(self, device_udid: str, wda_url: str | None = None) -> None:
        """Appium 세션 생성 전 iPhone 화면을 깨우는 사전 단계.

        WDA가 실행 중이면 REST API로 Home 버튼 눌러 잠금 해제 유도.
        실패해도 테스트 진행에 영향 없음.
        """
        if not wda_url:
            return
        try:
            import urllib.request as _ur, json as _json
            # WDA REST: pressButton home → 화면 켜기 + 잠금화면 해제 유도
            body = _json.dumps({"name": "home"}).encode()
            req = _ur.Request(
                f"{wda_url.rstrip('/')}/wda/pressButton",
                data=body,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            _ur.urlopen(req, timeout=5)
            print(f"  📱 iPhone 화면 깨우기 완료 (WDA pressButton)")
        except Exception as e:
            print(f"  ⚠️ iPhone 화면 깨우기 실패 (무시): {e}")

    def _start_ios_keep_alive_thread(self, driver, device_type: str) -> None:
        """Appium 세션 동안 iPhone 화면 자동 꺼짐 방지 daemon 스레드 시작.

        - 30초마다 idleTimerDisabled=True 설정 유지
        - driver 세션이 종료되면 자동 중지 (daemon=True)
        """
        import threading as _threading
        import time as _time

        def _keep_alive():
            while True:
                _time.sleep(30)
                try:
                    # 세션 생존 여부 확인 (session_id 없으면 종료됨)
                    if not driver.session_id:
                        break
                    driver.update_settings({'idleTimerDisabled': True})
                except Exception:
                    # 세션 종료 시 예외 발생 → 루프 종료
                    break

        t = _threading.Thread(target=_keep_alive, daemon=True, name=f'ios_keep_alive_{device_type}')
        t.start()

    def _adb_wake_screen(self, device_udid: str) -> None:
        """화면이 꺼져 있으면 WAKEUP 키이벤트로 강제 켜기."""
        try:
            r = subprocess.run(
                ['adb', '-s', device_udid, 'shell', 'dumpsys', 'power'],
                capture_output=True, text=True, timeout=5
            )
            # "Display Power: state=OFF" 또는 "mScreenOn=false" 감지
            power_out = r.stdout
            screen_off = ('state=OFF' in power_out
                          or 'mScreenOn=false' in power_out
                          or 'mWakefulness=Asleep' in power_out
                          or 'mWakefulness=Dozing' in power_out)
            if screen_off:
                print(f"  🔆 화면 꺼짐 감지 → 강제 켜기 (WAKEUP)")
                subprocess.run(
                    ['adb', '-s', device_udid, 'shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'],
                    capture_output=True, timeout=5
                )
                import time as _time
                _time.sleep(0.5)
                # 잠금화면 해제 (swipe up)
                subprocess.run(
                    ['adb', '-s', device_udid, 'shell', 'input', 'swipe', '540', '2000', '540', '800', '300'],
                    capture_output=True, timeout=5
                )
                _time.sleep(0.3)
                # MENU 키이벤트로 추가 잠금화면 해제 시도
                subprocess.run(
                    ['adb', '-s', device_udid, 'shell', 'input', 'keyevent', 'KEYCODE_MENU'],
                    capture_output=True, timeout=5
                )
        except Exception as e:
            print(f"  ⚠️ 화면 켜기 실패: {e}")

    def ensure_adb_connected(self, device_udid: str) -> None:
        """Android 무선 연결 시 adb connect 자동 실행 + tcp:7779 포트 포워딩 설정.

        Wi-Fi ADB 연결 불안정 → 최대 3회 재시도.
        """
        if ':' not in device_udid:
            return  # USB 연결은 skip

        max_retries = 3
        connected = False
        for attempt in range(1, max_retries + 1):
            try:
                print(f"  📡 adb connect {device_udid} 실행 중...{f' (재시도 {attempt}/{max_retries})' if attempt > 1 else ''}")
                result = subprocess.run(
                    ['adb', 'connect', device_udid],
                    capture_output=True, text=True, timeout=10
                )
                output = result.stdout.strip()
                if 'connected' in output.lower():
                    print(f"  ✅ adb 연결: {output}")
                    connected = True
                    break
                else:
                    print(f"  ⚠️ adb 연결 응답: {output}")
            except Exception as e:
                print(f"  ⚠️ adb connect 실패: {e}")

            if attempt < max_retries:
                # 재시도 전 대기 (disconnect 금지 — Wi-Fi ADB 완전 끊김 방지)
                import time as _time
                _time.sleep(2)

        if not connected:
            print(f"  ❌ adb 연결 {max_retries}회 시도 모두 실패 ({device_udid})")
            return

        self._setup_adb_forward(device_udid)

    def _setup_adb_forward(self, device_udid: str) -> None:
        """adb forward tcp:7779 설정 (포트 포워딩 유지)."""
        try:
            fwd = subprocess.run(
                ['adb', '-s', device_udid, 'forward', 'tcp:7779', 'tcp:7779'],
                capture_output=True, text=True, timeout=5
            )
            if fwd.returncode == 0:
                print(f"  ✅ adb forward tcp:7779 설정 완료 ({device_udid})")
            else:
                print(f"  ⚠️ adb forward 실패: {fwd.stderr.strip()}")
        except Exception as fe:
            print(f"  ⚠️ adb forward 오류: {fe}")

    def _try_restart_appium_for_url(self, server_url: str) -> bool:
        """Connection refused 시 해당 포트의 Appium을 직접 재시작.

        Returns:
            True if Appium came up within 20 seconds, else False.
        """
        import re
        import shutil
        import time as _time

        m = re.search(r':(\d+)$', server_url.rstrip('/'))
        if not m:
            return False
        port = int(m.group(1))

        # 포트 점유 프로세스 강제 종료
        try:
            result = subprocess.run(['lsof', '-ti', f'tcp:{port}'],
                                    capture_output=True, text=True, timeout=5)
            pids = result.stdout.strip().split()
            if pids:
                subprocess.run(['kill', '-9'] + pids, capture_output=True, timeout=5)
                _time.sleep(0.5)
        except Exception:
            pass

        # Appium 바이너리 찾기 (npm global, homebrew, PATH 순)
        appium_bin = shutil.which('appium')
        if not appium_bin:
            import os
            for candidate in ['/usr/local/bin/appium', '/opt/homebrew/bin/appium']:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    appium_bin = candidate
                    break
        if not appium_bin:
            import os
            # npm global 경로 탐색
            try:
                npm_prefix = subprocess.run(['npm', 'root', '-g'],
                                             capture_output=True, text=True, timeout=5).stdout.strip()
                candidate = os.path.join(os.path.dirname(npm_prefix), 'bin', 'appium')
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    appium_bin = candidate
            except Exception:
                pass

        if not appium_bin:
            print(f"  ❌ Appium 바이너리를 찾을 수 없어 자동 재시작 불가 (포트 {port})")
            return False

        print(f"  🔄 Appium 자동 재시작 중... (포트 {port}, 바이너리: {appium_bin})")
        try:
            proc = subprocess.Popen(
                [appium_bin, '--port', str(port), '--log-level', 'error'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            print(f"  📡 Appium PID={proc.pid} 시작됨 (포트 {port})")
        except Exception as e:
            print(f"  ❌ Appium 재시작 실패: {e}")
            return False

        alive = self._wait_for_appium_server(server_url, timeout=20)
        if alive:
            print(f"  ✅ Appium 재시작 완료 (포트 {port})")
        else:
            print(f"  ❌ Appium 재시작 후 20초 대기에도 미응답 (포트 {port})")
        return alive

    def free_port(self, port: int) -> None:
        """점유된 포트를 강제 해제 — macOS/Linux: lsof, Windows: netstat+taskkill."""
        try:
            if sys.platform == 'win32':
                # Windows: netstat로 PID 추출 후 taskkill
                result = subprocess.run(
                    ['netstat', '-ano'],
                    capture_output=True, text=True, timeout=5
                )
                pids = set()
                for line in result.stdout.splitlines():
                    if f':{port}' in line and ('LISTENING' in line or 'ESTABLISHED' in line):
                        parts = line.split()
                        if parts:
                            pids.add(parts[-1])
                for pid in pids:
                    subprocess.run(['taskkill', '/F', '/PID', pid],
                                   capture_output=True, timeout=5)
                if pids:
                    print(f"  🧹 포트 {port} 점유 프로세스 정리: PID {', '.join(pids)}")
            else:
                # macOS / Linux: lsof
                result = subprocess.run(
                    ['lsof', '-ti', f'tcp:{port}'],
                    capture_output=True, text=True, timeout=5
                )
                pids = result.stdout.strip().split()
                if pids:
                    subprocess.run(['kill', '-9'] + pids, capture_output=True, timeout=5)
                    print(f"  🧹 포트 {port} 점유 프로세스 정리: PID {', '.join(pids)}")
        except Exception:
            pass

    def setup_device(
        self,
        device_udid: str,
        device_type: str = 'speaker1',
        platform: str = 'Android',
    ) -> tuple:
        """Appium 드라이버 연결.

        Returns:
            (driver, wait, wda_url) 튜플, 실패 시 (None, None, None)
        """
        print(f"🔌 {device_type} 연결 중... ({device_udid})")

        # ── Appium 서버 헬스체크 (연결 시도 전) ──────────────────────────────
        # iOS-iOS 모드: 역할별로 다른 Appium 서버 사용
        if platform == 'iOS':
            appium_url = (
                self.appium_server_ios_sp2
                if (device_type == 'speaker2' and self.appium_server_ios_sp2)
                else self.appium_server_ios
            )
        else:
            appium_url = self.appium_server_android
        # timeout=20: speaker1 세션 초기화(UiAutomator2 기동)로 Appium이 바쁠 수 있음
        if not self._wait_for_appium_server(appium_url, timeout=20):
            # 20초 대기 후에도 무응답이면 완전히 죽음 → 자동 재시작
            print(f"  ⚠️ {device_type}: Appium 미응답 ({appium_url}) → 자동 재시작 시도...")
            if not self._try_restart_appium_for_url(appium_url):
                print(f"❌ {device_type}: Appium 서버 재시작 실패 ({appium_url}) — 연결 불가")
                return None, None, None

        if platform == 'Android':
            self.free_port(8300)
            self.ensure_adb_connected(device_udid)

            # ADB 연결 상태 사전 검증 (Wi-Fi ADB 불안정 대비)
            try:
                _check = subprocess.run(
                    ['adb', '-s', device_udid, 'shell', 'echo', 'ok'],
                    capture_output=True, text=True, timeout=5
                )
                if 'ok' not in _check.stdout:
                    print(f"  ⚠️ ADB 응답 없음 → 재연결 시도")
                    self.ensure_adb_connected(device_udid)
            except Exception:
                print(f"  ⚠️ ADB 사전 검증 실패 → 재연결 시도")
                self.ensure_adb_connected(device_udid)

            self._adb_reset_uiautomator2(device_udid)
            # UiAutomator2 리셋 후 화면 꺼짐 방지 + 강제 켜기 (세션 생성 전 보호)
            self._adb_keep_screen_on(device_udid)

        wda_url = None  # Android일 때 NameError 방지
        try:
            if platform == 'iOS':
                # iOS-iOS 모드: sp2는 별도 WDA 관리자 사용
                wdm = (
                    self.wda_manager_sp2
                    if (device_type == 'speaker2' and self.wda_manager_sp2)
                    else self.wda_manager
                )
                # 역할별 WDA/mjpeg 포트 (두 iPhone 간 포트 충돌 방지)
                _wda_ports = self._WDA_PORTS.get(device_type, self._WDA_PORTS['speaker1'])

                # WDA 기존 포트 해제 (해당 역할 포트만)
                self.free_port(_wda_ports['wdaLocalPort'])

                ios_version = wdm.get_ios_version(device_udid) if wdm else '18.0'
                iphone_ip = wdm.get_iphone_ip(udid=device_udid) if wdm else None
                wda_url = wdm.find_wda_url(iphone_ip, udid=device_udid) if (wdm and iphone_ip) else None

                if not iphone_ip and not wda_url:
                    print(
                        f"  ℹ️  iPhone IP 미감지 (UDID: {device_udid[:8]}...) — "
                        "usePreinstalledWDA 모드로 Appium이 WDA 직접 기동합니다."
                    )

                if not wda_url and iphone_ip:
                    # WDA 실행 안 됨 → devicectl로 기동 (1회)
                    print(f"  🔌 WDA 기동 시도 (devicectl, IP={iphone_ip})...")
                    wda_url = wdm.launch_wda_via_devicectl(device_udid, iphone_ip)
                    if not wda_url:
                        print(f"  ⚠️  devicectl WDA 기동 실패 → usePreinstalledWDA로 Appium에 위임")

                device_config = {
                    'platformName': 'iOS',
                    'appium:deviceName': f'{device_type}_device',
                    'appium:udid': device_udid,
                    'appium:automationName': 'XCUITest',
                    'appium:platformVersion': ios_version,
                    'appium:noReset': True,
                    'appium:newCommandTimeout': 3600,
                    'appium:shouldTerminateApp': False,
                    'appium:waitForQuiescence': False,
                    # waitForIdleTimeout: quiescence 대기 최대 시간(ms) 제한
                    # "보이는 전화" CallKit PiP 오버레이가 accessibility tree를 계속 변경하여
                    # WDA snapshot blocking → ~47초 freeze 방지
                    'appium:waitForIdleTimeout': 3,
                    'appium:keepAlive': True,
                }
                if wda_url:
                    device_config['appium:webDriverAgentUrl'] = wda_url
                    print(f"  ✅ 실행 중인 WDA 재사용: {wda_url}")
                else:
                    device_config.update({
                        'appium:usePreinstalledWDA': True,   # xcodebuild 없이 설치된 WDA 직접 기동
                        'appium:useNewWDA': False,
                        'appium:updatedWDABundleId': 'com.jjun.1.WebDriverAgentRunner',
                        'appium:wdaLaunchTimeout': 180000,
                        'appium:wdaConnectionTimeout': 90000,
                        'appium:wdaLocalPort': _wda_ports['wdaLocalPort'],
                        'appium:mjpegServerPort': _wda_ports['mjpegServerPort'],
                    })
                    print(f"  📡 iPhone IP: {iphone_ip or '미감지'}, WDA Appium 자체 기동 "
                          f"(WDA={_wda_ports['wdaLocalPort']}, mjpeg={_wda_ports['mjpegServerPort']})")

                options = XCUITestOptions().load_capabilities(device_config)
                # iOS-iOS: 역할별 Appium 서버 선택
                appium_server = (
                    self.appium_server_ios_sp2
                    if (device_type == 'speaker2' and self.appium_server_ios_sp2)
                    else self.appium_server_ios
                )
                # 세션 연결 전 화면 깨우기 (자동 잠금 경고 포함)
                self._ios_keep_screen_on(device_udid, wda_url=wda_url)
            else:
                device_config = {
                    'platformName': 'Android',
                    'appium:deviceName': f'{device_type}_device',
                    'appium:udid': device_udid,
                    'appium:automationName': 'UiAutomator2',
                    'appium:appPackage': self._target_android_pkg,
                    'appium:noReset': True,
                    'appium:forceAppLaunch': False,
                    'appium:shouldTerminateApp': False,
                    'appium:newCommandTimeout': 3600,
                    'appium:systemPort': 8300,
                    'appium:disableWindowAnimation': True,
                    'appium:ignoreUnimportantViews': True,
                    'appium:skipUnlock': True,
                    'appium:autoGrantPermissions': False,
                    'appium:uiautomator2ServerLaunchTimeout': 120000,
                    'appium:uiautomator2ServerInstallTimeout': 120000,
                    'appium:adbExecTimeout': 120000,
                    'appium:skipServerInstallation': False,
                    'appium:skipDeviceInitialization': False,
                }
                # 액티비티 지정 시에만 caps에 추가 (미지정 시 Appium이 launcher 자동 탐지)
                if self._target_android_activity:
                    device_config['appium:appActivity'] = self._target_android_activity
                options = UiAutomator2Options().load_capabilities(device_config)
                appium_server = self.appium_server_android

            driver = webdriver.Remote(appium_server, options=options)

            try:
                if platform == 'iOS':
                    # WDA 세션이 활성화된 동안 화면 유지 (background keep-alive)
                    self._start_ios_keep_alive_thread(driver, device_type)
                    print(f"💡 {device_type}: iOS 화면 유지 활성화 (WDA keep-alive)")
                    # 무선 연결 끊김 자동 복구 Watchdog 시작
                    if wdm and device_udid:
                        wdm.start_connection_watchdog(device_udid, interval=15)
                else:
                    driver.update_settings({'keepScreenOn': True})
                    # ADB 시스템 레벨 화면 꺼짐 방지 (UiAutomator2 크래시에도 유지됨)
                    self._adb_keep_screen_on(device_udid)
                    print(f"💡 {device_type}: 화면 자동 꺼짐 방지 활성화")
            except Exception as e:
                print(f"⚠️ 화면 설정 실패 (계속 진행): {e}")

            wait = WebDriverWait(driver, 15)
            print(f"✅ {device_type} 연결 성공\n")
            return driver, wait, wda_url if platform == 'iOS' else None

        except Exception as e:
            err_msg = str(e)
            # iOS "Invalid URL" / WDA 프록시 오류 → WDA 재기동 후 1회 재시도
            if platform == 'iOS' and ('Invalid URL' in err_msg or 'proxy command' in err_msg):
                print(f"  ⚠️ WDA 연결 오류 → WDA 재기동 후 재시도...")
                wdm = self.wda_manager
                if wdm and iphone_ip:
                    wda_url_retry = wdm.launch_wda_via_devicectl(device_udid, iphone_ip)
                    if wda_url_retry:
                        try:
                            device_config['appium:webDriverAgentUrl'] = wda_url_retry
                            options = XCUITestOptions().load_capabilities(device_config)
                            driver = webdriver.Remote(self.appium_server_ios, options=options)
                            wait = WebDriverWait(driver, 15)
                            print(f"✅ {device_type} 재시도 연결 성공\n")
                            return driver, wait, wda_url_retry
                        except Exception as e2:
                            print(f"❌ {device_type} 재시도도 실패: {e2}")

            # Android instrumentation 오류 → UiAutomator2 APK 재설치 후 1회 재시도
            if platform == 'Android' and 'instrumentation' in err_msg.lower():
                print(f"  ⚠️ UiAutomator2 instrumentation 오류 → APK 재설치 후 재시도...")
                import time as _time
                # 기존 UiAutomator2 APK 완전 제거
                for pkg in ['io.appium.uiautomator2.server',
                             'io.appium.uiautomator2.server.test']:
                    try:
                        subprocess.run(
                            ['adb', '-s', device_udid, 'uninstall', pkg],
                            capture_output=True, timeout=10,
                        )
                    except Exception:
                        pass
                self._adb_reset_uiautomator2(device_udid)
                _time.sleep(2)
                try:
                    # Appium이 APK를 새로 설치하도록 설정
                    device_config['appium:skipServerInstallation'] = False
                    device_config['appium:skipDeviceInitialization'] = False
                    options = UiAutomator2Options().load_capabilities(device_config)
                    driver = webdriver.Remote(self.appium_server_android, options=options)
                    wait = WebDriverWait(driver, 15)
                    print(f"✅ {device_type} 재시도 연결 성공\n")
                    return driver, wait, None
                except Exception as e2:
                    print(f"❌ {device_type} 재시도도 실패: {e2}")

            # Connection refused → Appium 서버 죽음. 자동 재시작 후 재시도
            if 'Connection refused' in err_msg or 'NewConnectionError' in err_msg:
                print(f"  ⚠️ Appium 서버 미응답 ({appium_server}) → 자동 재시작 시도...")
                restarted = self._try_restart_appium_for_url(appium_server)
                if restarted:
                    try:
                        driver = webdriver.Remote(appium_server, options=options)
                        try:
                            if platform != 'iOS':
                                driver.update_settings({'keepScreenOn': True})
                                self._adb_keep_screen_on(device_udid)
                        except Exception:
                            pass
                        wait = WebDriverWait(driver, 15)
                        print(f"✅ {device_type} 재시도 연결 성공\n")
                        return driver, wait, wda_url if platform == 'iOS' else None
                    except Exception as e2:
                        print(f"❌ {device_type} 재시도도 실패: {e2}")
                else:
                    _port_hint = appium_server.rsplit(':', 1)[-1]
                    print(f"  ❌ Appium 자동 재시작 실패 ({appium_server})")
                    print(f"  💡 수동 조치: 'appium --port {_port_hint}' 또는 앱에서 Appium 재시작")

            print(f"❌ {device_type} 연결 실패: {e}\n")
            return None, None, None
