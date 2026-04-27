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
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.options.ios import XCUITestOptions
from selenium.webdriver.support.ui import WebDriverWait


class AppiumDeviceSetup:
    """Appium 드라이버 생성/연결 단일 책임 클래스."""

    def __init__(
        self,
        appium_server_android: str = 'http://127.0.0.1:4723',
        appium_server_ios: str = 'http://127.0.0.1:4724',
        wda_manager=None,
        android_app_package: str = 'com.lguplus.aicallagent',
        android_app_activity: str = '.MainActivity',
        ios_app_bundle_id: str = 'com.lguplus.aicallagent',
    ):
        self.appium_server_android = appium_server_android
        self.appium_server_ios = appium_server_ios
        self.wda_manager = wda_manager   # IosWdaManager 인스턴스
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

        1. screen_off_timeout = 24시간 (86400000ms)
        2. stay_on_while_plugged_in = 7 (USB+AC+무선 충전 모두)
        3. svc power stayon true (USB 연결 여부와 무관하게 화면 유지)
        4. 화면이 꺼져 있으면 WAKEUP + MENU 로 강제 켜기
        """
        cmds = [
            ['adb', '-s', device_udid, 'shell', 'settings', 'put', 'system', 'screen_off_timeout', '86400000'],
            ['adb', '-s', device_udid, 'shell', 'settings', 'put', 'global', 'stay_on_while_plugged_in', '7'],
            ['adb', '-s', device_udid, 'shell', 'svc', 'power', 'stayon', 'true'],
        ]
        _all_ok = True
        for cmd in cmds:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if result.returncode != 0 and result.stderr.strip():
                    print(f"  ⚠️ 화면유지 명령 실패: {' '.join(cmd[-3:])} → {result.stderr.strip()}")
                    _all_ok = False
            except Exception as e:
                print(f"  ⚠️ 화면유지 명령 오류: {e}")
                _all_ok = False
        if _all_ok:
            print(f"  🔒 화면 꺼짐 방지 설정 완료 ({device_udid})")

        # 화면이 꺼져 있으면 강제로 켜기
        self._adb_wake_screen(device_udid)

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

        # 포트 포워딩 설정 (USB 시 adb forward 로 등록된 포워딩을 무선에서도 유지)
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
        appium_url = self.appium_server_ios if platform == 'iOS' else self.appium_server_android
        if not self._wait_for_appium_server(appium_url, timeout=15):
            print(f"❌ {device_type}: Appium 서버 미응답 ({appium_url}) — 연결 불가")
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
                self.free_port(8100)
                self.free_port(8200)

                wdm = self.wda_manager
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
                    'appium:newCommandTimeout': 300,
                    'appium:shouldTerminateApp': False,
                    'appium:waitForQuiescence': False,
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
                        'appium:wdaLocalPort': 8200,
                        'appium:mjpegServerPort': 9200,
                    })
                    print(f"  📡 iPhone IP: {iphone_ip or '미감지'}, WDA Appium 자체 기동 (포트 8200)")

                options = XCUITestOptions().load_capabilities(device_config)
                appium_server = self.appium_server_ios
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
                    'appium:newCommandTimeout': 300,
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
                    print(f"💡 {device_type}: iOS - WebDriverAgent가 화면 유지 자동 처리")
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

            # Connection refused → Appium 서버 죽음. 헬스체크 대기 후 재시도
            if 'Connection refused' in err_msg or 'NewConnectionError' in err_msg:
                import time as _time
                print(f"  ⚠️ Appium 서버 미응답 ({appium_server}) → 15초 대기 후 재시도...")
                if self._wait_for_appium_server(appium_server, timeout=15):
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
                    print(f"  ❌ Appium 서버 15초 대기 후에도 미응답")

            print(f"❌ {device_type} 연결 실패: {e}\n")
            return None, None, None
