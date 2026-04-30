"""
ios_wda_manager.py
──────────────────────────────────────────────────────────────────────────────
iOS WebDriverAgent 수명주기 관리 (SRP 분리 — IxioAutomatedTest God-Class에서 추출).

책임:
  - iPhone IP 자동 탐색 (devicectl tunnelIP → 서브넷 스캔 → 캐시)
  - WDA 포트 탐색 + 기존 세션 정리 + devicectl WDA 직접 기동
  - WDA 프로세스 강제 종료 (teardown 용)
"""

import os
import subprocess
import sys
import tempfile
import threading
import time

_TMP = tempfile.gettempdir()


def _ip_host(ip: str) -> str:
    """IPv6 주소를 URL host 형식으로 변환. ex) fdcf::1 → [fdcf::1], 192.168.x.x → 192.168.x.x"""
    if ':' in ip and not ip.startswith('['):
        return f'[{ip}]'
    return ip


class IosWdaManager:
    """iPhone WDA URL 감지·기동·정리를 담당하는 단일 책임 클래스."""

    def __init__(self, wda_port: int = 8100):
        self._cached_iphone_ip: str | None = None
        self.wda_port = wda_port
        self._watchdog_stop: threading.Event | None = None
        self._watchdog_thread: threading.Thread | None = None

    # ─────────────────────────────────────────────────────────────────────────
    # 공용 API
    # ─────────────────────────────────────────────────────────────────────────

    def get_iphone_ip(self, udid: str | None = None) -> str | None:
        """iPhone IP 자동 조회.

        우선순위:
          1. devicectl tunnelIPAddress(IPv6) → WDA /status 내 ios.ip(IPv4) 추출
          2. 서브넷 병렬 스캔 (192.168.x.x)
          3. 캐시된 IP 재사용
        """
        import urllib.request
        import json as _json
        import concurrent.futures

        def _wda_ipv4_from_status(url: str) -> str | None:
            try:
                with urllib.request.urlopen(f'{url}/status', timeout=4) as r:
                    data = _json.loads(r.read())
                    val = data.get('value', data)
                    ip = val.get('ios', {}).get('ip', '')
                    if ip and ip.startswith(('10.', '172.', '192.')):
                        return ip
            except Exception:
                pass
            return None

        # ── 1. devicectl tunnelIPAddress ──────────────────────────────────
        if udid:
            try:
                tmp = os.path.join(_TMP, '_devicectl_ip.json')
                subprocess.run(
                    ['xcrun', 'devicectl', 'list', 'devices', '--json-output', tmp],
                    capture_output=True, timeout=8
                )
                with open(tmp) as f:
                    data = _json.load(f)
                for dev in data.get('result', {}).get('devices', []):
                    hw = dev.get('hardwareProperties', {})
                    if hw.get('udid', '') != udid:
                        continue
                    tunnel_ip = dev.get('connectionProperties', {}).get('tunnelIPAddress', '')
                    device_uuid = dev.get('identifier', '')
                    if tunnel_ip:
                        ipv6_url = f'http://[{tunnel_ip}]:8100'
                        ip = _wda_ipv4_from_status(ipv6_url)
                        if ip:
                            print(f"  📡 iPhone IP 감지 (tunnelIP→WDA): {ip}")
                            self._cached_iphone_ip = ip
                            return ip
                        # IPv6 자체로 WDA 통신 가능한지 확인
                        # → 단, IPv6 URL은 Appium이 거부하므로 IPv4 추출 필수
                        try:
                            with urllib.request.urlopen(f'{ipv6_url}/status', timeout=4) as _r6:
                                # IPv6 통신은 되지만, /status에서 IPv4를 다시 시도
                                try:
                                    _d6 = _json.loads(_r6.read())
                                    _v6 = _d6.get('value', _d6)
                                    _ip4 = _v6.get('ios', {}).get('ip', '')
                                    if _ip4 and '.' in _ip4 and _ip4.startswith(('10.', '172.', '192.')):
                                        print(f"  📡 iPhone IP 감지 (IPv6→IPv4): {_ip4}")
                                        self._cached_iphone_ip = _ip4
                                        return _ip4
                                except Exception:
                                    pass
                                # IPv4 추출 실패 → IPv6는 Appium에서 거부되므로 반환하지 않음
                                print(f"  ⚠️ IPv6 tunnel 통신 가능하나 IPv4 추출 실패 → 서브넷 스캔으로 전환")
                        except Exception:
                            pass

                        # ── WDA 미실행 상태 → setup_wda_iphone.sh 로 기동 ──
                        if device_uuid and udid:
                            wda_url = self._launch_wda_via_sh_script(udid)
                            if wda_url:
                                import re as _re
                                _m = _re.search(r'http://(\d+\.\d+\.\d+\.\d+):', wda_url)
                                ip = _m.group(1) if _m else None
                                if ip:
                                    print(f"  ✅ WDA sh 기동 완료 → IPv4: {ip}")
                                    self._cached_iphone_ip = ip
                                    return ip
                                # IPv6 URL → WDA 기동됐으므로 /status에서 ios.ip 재추출
                                ip = _wda_ipv4_from_status(wda_url)
                                if ip:
                                    print(f"  ✅ WDA sh 기동 완료 (IPv6→IPv4): {ip}")
                                    self._cached_iphone_ip = ip
                                    return ip
                                print(f"  ⚠️ sh 반환 URL에서 IPv4 추출 실패 ({wda_url}) → 서브넷 스캔")
                            else:
                                print(f"  ⚠️ setup_wda_iphone.sh 실패 → 서브넷 스캔으로 전환")

                    elif device_uuid and not tunnel_ip and udid:
                        # tunnelIPAddress 없음 (USB 신연결 등) → sh 스크립트로 WDA 기동
                        wda_url = self._launch_wda_via_sh_script(udid)
                        if wda_url:
                            import re as _re
                            _m = _re.search(r'http://(\d+\.\d+\.\d+\.\d+):', wda_url)
                            ip = _m.group(1) if _m else None
                            if ip:
                                print(f"  ✅ WDA sh 기동 완료 → IPv4: {ip}")
                                self._cached_iphone_ip = ip
                                return ip
                            # IPv6 URL → WDA 기동됐으므로 /status에서 ios.ip 재추출
                            ip = _wda_ipv4_from_status(wda_url)
                            if ip:
                                print(f"  ✅ WDA sh 기동 완료 (IPv6→IPv4): {ip}")
                                self._cached_iphone_ip = ip
                                return ip
                            print(f"  ⚠️ sh 반환 URL에서 IPv4 추출 실패 ({wda_url}) → 서브넷 스캔")
                        else:
                            print(f"  ⚠️ setup_wda_iphone.sh 실패 → 서브넷 스캔으로 전환")
            except Exception as e:
                print(f"  ⚠️ devicectl tunnelIP 조회 실패: {e}")

        # ── 2. 서브넷 병렬 스캔 ──────────────────────────────────────────
        cached = self._cached_iphone_ip
        subnets: list[str] = []
        if cached and '.' in str(cached):
            subnets.append(str(cached).rsplit('.', 1)[0])
        subnets += ['192.168.219', '192.168.0', '192.168.1', '10.0.0', '172.16.0']
        seen: set[str] = set()
        ordered_subnets = []
        for s in subnets:
            if s not in seen:
                seen.add(s)
                ordered_subnets.append(s)

        def probe(ip: str) -> str | None:
            try:
                with urllib.request.urlopen(f'http://{ip}:8100/status', timeout=1.5) as r:
                    data = _json.loads(r.read())
                    val = data.get('value', data)
                    if val.get('ready') or val.get('state') == 'success':
                        return ip
            except Exception:
                pass
            return None

        print(f"  🔍 iPhone WDA 서브넷 스캔 중...")
        for subnet in ordered_subnets:
            candidates = [f'{subnet}.{i}' for i in range(1, 255)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=80) as pool:
                futs = {pool.submit(probe, ip): ip for ip in candidates}
                for f in concurrent.futures.as_completed(futs):
                    ip = f.result()
                    if ip:
                        print(f"  📡 iPhone IP 감지 (서브넷 스캔): {ip}")
                        self._cached_iphone_ip = ip
                        return ip

        # ── 3. 캐시된 IP 재사용 ──────────────────────────────────────────
        if cached:
            print(f"  📡 iPhone IP 캐시 사용: {cached}")
            return cached

        print(f"  ⚠️ iPhone IP 조회 실패 (udid={udid})")
        return None

    def get_ios_version(self, udid: str) -> str:
        """iOS 버전 조회 (xcrun xctrace → tidevice 순서 시도, 크로스플랫폼)."""
        import re

        # ── macOS: xcrun xctrace ───────────────────────────────────────────
        if sys.platform == 'darwin':
            try:
                result = subprocess.run(
                    ['xcrun', 'xctrace', 'list', 'devices'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.splitlines():
                    if udid in line:
                        m = re.search(r'\((\d+\.\d+(?:\.\d+)?)\)', line)
                        if m:
                            version = m.group(1)
                            print(f"  📱 iOS 버전 감지 (xcrun): {version}")
                            return version
            except Exception as e:
                print(f"  ⚠️ xcrun xctrace 실패: {e}")

        # ── 크로스플랫폼: tidevice ─────────────────────────────────────────
        try:
            cmd = ['tidevice', '-u', udid, 'info'] if udid else ['tidevice', 'info']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            for line in result.stdout.splitlines():
                if 'ProductVersion' in line or 'SystemVersion' in line:
                    m = re.search(r'(\d+\.\d+(?:\.\d+)?)', line)
                    if m:
                        version = m.group(1)
                        print(f"  📱 iOS 버전 감지 (tidevice): {version}")
                        return version
        except Exception:
            pass

        print(f"  ⚠️ iOS 버전 자동 감지 실패 → 기본값 18.0 사용")
        return '18.0'

    def _sh_script_path(self) -> str:
        """setup_wda_iphone.sh 절대 경로 반환."""
        return os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'setup_wda_iphone.sh')
        )

    def _launch_wda_via_sh_script(self, udid: str) -> str | None:
        """setup_wda_iphone.sh 를 실행해 WDA 기동 → localhost:8100 반환.

        스크립트가 iproxy 포트포워딩까지 처리하므로
        성공 시 WDA URL = http://localhost:8100
        """
        import urllib.request
        sh = self._sh_script_path()
        if not os.path.isfile(sh):
            print(f"  ⚠️ setup_wda_iphone.sh 없음: {sh}")
            return None
        print(f"  🚀 setup_wda_iphone.sh 실행 중...")
        env = os.environ.copy()
        env['WDA_PORT'] = str(self.wda_port)
        if udid:
            env['TARGET_UDID'] = udid
        proc = subprocess.Popen(
            ['bash', sh],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env
        )
        # 실시간 출력 + localhost 응답 감지
        wda_url = None
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                print(f"  [sh] {line}")
            if 'WDA_URL' in line and 'http://' in line:
                import re
                m = re.search(r'http://[^\s]+', line)
                if m:
                    wda_url = m.group(0)
        proc.wait()
        if proc.returncode != 0 and wda_url is None:
            print(f"  ⚠️ setup_wda_iphone.sh 종료 코드: {proc.returncode}")
        # sh 출력의 WDA_URL이 IPv4이면 그 URL 직접 확인 후 반환
        if wda_url:
            import re as _re
            _m = _re.search(r'http://(\d+\.\d+\.\d+\.\d+)(:\d+)?', wda_url)
            if _m:
                ipv4_url = f'http://{_m.group(1)}{_m.group(2) or f":{self.wda_port}"}'
                try:
                    with urllib.request.urlopen(f'{ipv4_url}/status', timeout=3) as r:
                        if r.status == 200:
                            print(f"  ✅ WDA IPv4 응답 확인: {ipv4_url}")
                            self.clear_wda_sessions(ipv4_url)
                            return ipv4_url
                except Exception:
                    pass
            # IPv6 URL → WDA 기동됐으므로 /status 에서 ios.ip(IPv4) 추출
            if wda_url.startswith('http://['):
                try:
                    with urllib.request.urlopen(f'{wda_url}/status', timeout=4) as _r:
                        _d = __import__('json').loads(_r.read())
                        _ip4 = _d.get('value', _d).get('ios', {}).get('ip', '')
                        if _ip4 and _ip4.startswith(('10.', '172.', '192.')):
                            ipv4_url = f'http://{_ip4}:{self.wda_port}'
                            print(f"  ✅ WDA IPv6→IPv4: {wda_url} → {ipv4_url}")
                            self.clear_wda_sessions(ipv4_url)
                            return ipv4_url
                except Exception:
                    pass
                print(f"  ⚠️ sh 반환 URL이 IPv6 — Appium 비호환, 반환 안 함: {wda_url}")
                return None
        return wda_url  # 스크립트가 출력한 URL (IPv4인 경우)

    def find_wda_url(self, iphone_ip: str, udid: str | None = None) -> str | None:
        """WDA 실행 중인 포트 확인 + 세션 정리 + 없으면 setup_wda_iphone.sh 로 기동.

        IPv6 주소로 WDA 통신이 되더라도, Appium xcuitest 드라이버가
        bracket IPv6 URL을 "Invalid URL"로 거부할 수 있으므로
        WDA /status에서 IPv4 주소를 추출하여 URL을 재구성합니다.

        iproxy 포트포워딩이 활성화된 경우 localhost:WDA_PORT 에도 응답하므로
        먼저 localhost 를 프로브합니다.
        """
        import urllib.request, json as _json

        # ── 0. localhost(iproxy) 우선 확인 ───────────────────────────────
        local_url = f'http://localhost:{self.wda_port}'
        try:
            with urllib.request.urlopen(f'{local_url}/status', timeout=2) as r:
                if r.status == 200:
                    print(f"  ✅ WDA 실행 중인 WDA 재사용: {local_url}")
                    self.clear_wda_sessions(local_url)
                    return local_url
        except Exception:
            pass

        host = _ip_host(iphone_ip)
        for port in [8100, 8200, 27753]:
            try:
                url = f'http://{host}:{port}/status'
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        print(f"  ✅ WDA 포트 발견: {port}")
                        # IPv6 주소인 경우 WDA /status에서 IPv4 추출 시도
                        # → Appium이 bracket IPv6 URL을 "Invalid URL"로 거부하는 문제 방지
                        resolved_host = host
                        if ':' in iphone_ip:
                            try:
                                data = _json.loads(r.read())
                                val = data.get('value', data)
                                ipv4 = val.get('ios', {}).get('ip', '')
                                if ipv4 and '.' in ipv4 and ipv4.startswith(('10.', '172.', '192.')):
                                    resolved_host = ipv4
                                    print(f"  📡 IPv6→IPv4 변환: {iphone_ip} → {ipv4}")
                                else:
                                    # IPv4 추출 실패 → Appium에서 bracket IPv6 URL 거부하므로
                                    # 이 포트는 건너뛰고 다음 포트/서브넷 스캔으로 전환
                                    print(f"  ⚠️ WDA에서 IPv4 추출 실패 — Appium IPv6 비호환으로 이 포트 건너뜀")
                                    continue
                            except Exception:
                                print(f"  ⚠️ WDA /status 파싱 실패 — IPv6 URL 사용 불가, 건너뜀")
                                continue
                        base_url = f'http://{resolved_host}:{port}'
                        self.clear_wda_sessions(base_url)
                        return base_url
            except Exception:
                continue
        if udid:
            print(f"  📡 WDA 없음 → setup_wda_iphone.sh 로 WDA 기동 시도...")
            return self._launch_wda_via_sh_script(udid)
        print(f"  ⚠️ 실행 중인 WDA 없음 → Appium이 직접 시작")
        return None

    def launch_wda_via_devicectl(self, udid: str, iphone_ip: str) -> str | None:
        """WDA 앱 기동 — macOS: setup_wda_iphone.sh, Windows/Linux: tidevice fallback."""
        import urllib.request

        # ── Windows / Linux: tidevice로 WDA 기동 ─────────────────────────
        if sys.platform != 'darwin':
            return self._launch_wda_via_tidevice(udid, iphone_ip)

        # ── macOS: setup_wda_iphone.sh ────────────────────────────────────
        return self._launch_wda_via_sh_script(udid)

    def clear_wda_sessions(self, wda_base_url: str) -> None:
        """WDA 기존 세션 삭제 (Appium 연결 전 socket hang up 방지)."""
        import urllib.request, json as _json
        try:
            with urllib.request.urlopen(f'{wda_base_url}/status', timeout=3) as r:
                data = _json.loads(r.read())
            session_id = data.get('sessionId')
            if not session_id:
                print(f"  ℹ️ WDA 활성 세션 없음")
                return
            del_req = urllib.request.Request(
                f'{wda_base_url}/session/{session_id}',
                method='DELETE'
            )
            urllib.request.urlopen(del_req, timeout=3)
            print(f"  🗑️ WDA 기존 세션 삭제: {session_id[:8]}...")
        except Exception as e:
            print(f"  ⚠️ WDA 세션 정리 실패 (무시): {e}")

    def _launch_wda_via_tidevice(self, udid: str, iphone_ip: str) -> str | None:
        """tidevice로 WDA 실행 (Windows / Linux 크로스플랫폼 fallback)."""
        import urllib.request
        import shutil
        if not shutil.which('tidevice'):
            print(f"  ⚠️ tidevice 없음 → pip install tidevice 로 설치하세요")
            return None

        bundle_id = os.environ.get('WDA_BUNDLE_ID', 'com.jjun.1.WebDriverAgentRunner.xctrunner')
        cmd = ['tidevice']
        if udid:
            cmd += ['-u', udid]
        cmd += ['xctest', '-B', bundle_id]
        print(f"  🚀 tidevice xctest WDA 기동 중...")
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        host = _ip_host(iphone_ip)
        for i in range(30):
            time.sleep(1)
            try:
                url = f'http://{host}:8100/status'
                with urllib.request.urlopen(url, timeout=1) as r:
                    if r.status == 200:
                        print(f"  ✅ WDA 시작 완료 ({i+1}초 소요): http://{host}:8100")
                        self._cached_iphone_ip = iphone_ip
                        return f'http://{host}:8100'
            except Exception:
                if (i + 1) % 5 == 0:
                    print(f"  ⏳ WDA 대기 중... ({i+1}초)")
        print(f"  ⚠️ WDA 시작 타임아웃 (30초)")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # 무선 연결 Watchdog
    # ─────────────────────────────────────────────────────────────────────────

    def start_connection_watchdog(
        self, udid: str, interval: int = 15
    ) -> None:
        """백그라운드 daemon 스레드로 iPhone 무선 연결 상태를 감시한다.

        tunnelState != connected 감지 시:
          1. IPA install (devicectl) → 디바이스 wake-up + 재연결 트리거
          2. tunnelIP 재확보 대기 (최대 30초)
          3. WDA 재기동 (setup_wda_iphone.sh)
        """
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return  # 이미 실행 중
        self._watchdog_stop = threading.Event()
        self._watchdog_thread = threading.Thread(
            target=self._run_connection_watchdog,
            args=(udid, interval),
            daemon=True,
            name=f'wda-watchdog-{udid[:8]}',
        )
        self._watchdog_thread.start()
        print(f"  🐕 WDA 무선 연결 Watchdog 시작 (UDID: {udid[:8]}..., 간격: {interval}s)")

    def stop_connection_watchdog(self) -> None:
        """Watchdog 스레드 중지."""
        if self._watchdog_stop:
            self._watchdog_stop.set()

    def _run_connection_watchdog(
        self, udid: str, interval: int
    ) -> None:
        import json as _json
        import urllib.request

        stop = self._watchdog_stop
        consecutive_failures = 0

        while stop and not stop.wait(timeout=interval):
            try:
                tmp = os.path.join(_TMP, f'_wdog_{udid[:8]}.json')
                subprocess.run(
                    ['xcrun', 'devicectl', 'list', 'devices', '--json-output', tmp],
                    capture_output=True, timeout=8
                )
                with open(tmp) as f:
                    data = _json.load(f)
                os.unlink(tmp)

                for dev in data.get('result', {}).get('devices', []):
                    if dev.get('hardwareProperties', {}).get('udid', '') != udid:
                        continue
                    conn = dev.get('connectionProperties', {})
                    state = conn.get('tunnelState', '')
                    tunnel_ip = conn.get('tunnelIPAddress', '')

                    if state == 'connected' and tunnel_ip:
                        # 연결 정상 — WDA heartbeat
                        consecutive_failures = 0
                        wda_url = f'http://[{tunnel_ip}]:{self.wda_port}'
                        try:
                            with urllib.request.urlopen(
                                f'{wda_url}/status', timeout=3
                            ) as r:
                                if r.status != 200:
                                    raise Exception('WDA status not 200')
                        except Exception:
                            consecutive_failures += 1
                            if consecutive_failures >= 2:
                                print(
                                    f"  ⚠️ [Watchdog] WDA 응답 없음 ({consecutive_failures}회) "
                                    f"→ 재기동 시도"
                                )
                                self._watchdog_reconnect(udid)
                                consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                        print(
                            f"  ⚠️ [Watchdog] 무선 연결 끊김 (state={state}) "
                            f"— 재연결 시도 #{consecutive_failures}"
                        )
                        self._watchdog_reconnect(udid)
                        consecutive_failures = 0
                    break

            except Exception as e:
                print(f"  ⚠️ [Watchdog] 상태 확인 오류: {e}")

    def _watchdog_reconnect(self, udid: str) -> None:
        """연결 끊김 시 IPA install → tunnelIP 재확보 → WDA 재기동."""
        import json as _json

        sh = self._sh_script_path()
        if not os.path.isfile(sh):
            print("  [Watchdog] setup_wda_iphone.sh 없음 — 재연결 불가")
            return

        # IPA 재설치 → 디바이스 wake-up
        print("  🔄 [Watchdog] IPA install로 디바이스 재연결 트리거...")
        env = os.environ.copy()
        env['WDA_PORT'] = str(self.wda_port)
        env['TARGET_UDID'] = udid
        proc = subprocess.Popen(
            ['bash', sh],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env
        )
        import re as _re
        wda_url_found = None
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                print(f"  [wdog-sh] {line}")
            if 'WDA_URL' in line and 'http://' in line:
                m = _re.search(r'http://[^\s]+', line)
                if m:
                    wda_url_found = m.group(0)
        proc.wait()

        if wda_url_found:
            # IPv6이면 ios.ip 추출
            import urllib.request
            if wda_url_found.startswith('http://['):
                try:
                    with urllib.request.urlopen(
                        f'{wda_url_found}/status', timeout=4
                    ) as r:
                        val = __import__('json').loads(r.read()).get('value', {})
                        ipv4 = val.get('ios', {}).get('ip', '')
                        if ipv4:
                            self._cached_iphone_ip = ipv4
                            print(f"  ✅ [Watchdog] 재연결 성공: {ipv4}")
                            return
                except Exception:
                    pass
            else:
                m4 = _re.search(r'(\d+\.\d+\.\d+\.\d+)', wda_url_found)
                if m4:
                    self._cached_iphone_ip = m4.group(1)
                    print(f"  ✅ [Watchdog] 재연결 성공: {m4.group(1)}")
                    return
        print("  ❌ [Watchdog] 재연결 실패")

    def terminate_wda_process(self, udid: str) -> None:
        """devicectl로 iPhone WDA 프로세스 강제 종료."""
        import re, json
        try:
            result = subprocess.run(
                ['xcrun', 'devicectl', 'list', 'devices'],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if udid in line:
                    m = re.search(
                        r'([0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})',
                        line, re.IGNORECASE
                    )
                    if not m:
                        continue
                    device_uuid = m.group(1)
                    proc_list = subprocess.run(
                        ['xcrun', 'devicectl', 'device', 'process', 'list',
                         '--device', device_uuid, '--json-output', '/dev/stdout'],
                        capture_output=True, text=True, timeout=10
                    )
                    try:
                        data = json.loads(proc_list.stdout)
                        procs = data.get('result', {}).get('runningProcesses', [])
                        for proc in procs:
                            executable = proc.get('executable', '')
                            if 'WebDriverAgent' in executable:
                                pid = proc.get('processIdentifier')
                                if pid:
                                    subprocess.run(
                                        ['xcrun', 'devicectl', 'device', 'process',
                                         'terminate', '--device', device_uuid, '--pid', str(pid)],
                                        capture_output=True, timeout=5
                                    )
                                    print(f"  🛑 WDA 프로세스 종료: PID {pid}")
                    except Exception:
                        pass
                    return
        except Exception as e:
            print(f"  ⚠️ WDA 프로세스 종료 실패: {e}")
