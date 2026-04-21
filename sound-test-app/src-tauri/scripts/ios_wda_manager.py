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

    def find_wda_url(self, iphone_ip: str, udid: str | None = None) -> str | None:
        """WDA 실행 중인 포트 확인 + 세션 정리 + 없으면 devicectl로 기동.

        IPv6 주소로 WDA 통신이 되더라도, Appium xcuitest 드라이버가
        bracket IPv6 URL을 "Invalid URL"로 거부할 수 있으므로
        WDA /status에서 IPv4 주소를 추출하여 URL을 재구성합니다.
        """
        import urllib.request, json as _json
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
        if udid and iphone_ip:
            print(f"  📡 WDA 없음 → devicectl로 WDA 직접 기동 시도...")
            return self.launch_wda_via_devicectl(udid, iphone_ip)
        print(f"  ⚠️ 실행 중인 WDA 없음 → Appium이 직접 시작")
        return None

    def launch_wda_via_devicectl(self, udid: str, iphone_ip: str) -> str | None:
        """WDA 앱 기동 (macOS: devicectl, Windows/Linux: tidevice fallback)."""
        import json as _json, urllib.request

        # ── Windows / Linux: tidevice로 WDA 기동 ─────────────────────────
        if sys.platform != 'darwin':
            return self._launch_wda_via_tidevice(udid, iphone_ip)

        try:
            tmp = os.path.join(_TMP, '_devicectl_wda.json')
            subprocess.run(
                ['xcrun', 'devicectl', 'list', 'devices', '--json-output', tmp],
                capture_output=True, timeout=8
            )
            device_uuid = None
            try:
                with open(tmp) as f:
                    data = _json.load(f)
                for dev in data.get('result', {}).get('devices', []):
                    if dev.get('hardwareProperties', {}).get('udid', '') == udid:
                        device_uuid = dev.get('identifier', '')
                        break
            except Exception as e:
                print(f"  ⚠️ devicectl JSON 파싱 실패: {e}")
            if not device_uuid:
                print(f"  ⚠️ devicectl UUID 조회 실패 (udid={udid})")
                return None
            bundle_id = 'com.jjun.1.WebDriverAgentRunner'
            print(f"  🚀 WDA 앱 실행 중 (devicectl uuid={device_uuid[:8]}...)...")
            subprocess.Popen(
                ['xcrun', 'devicectl', 'device', 'process', 'launch',
                 '--device', device_uuid, bundle_id],
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
        except Exception as e:
            print(f"  ⚠️ WDA 실행 실패: {e}")
        return None

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

        bundle_id = 'com.jjun.1.WebDriverAgentRunner'
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
