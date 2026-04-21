"""
wda_auto_answer.py
──────────────────
WDA HTTP API를 직접 호출하여 아이폰 수신 전화를 자동 응답.

주요 기능:
- 서브넷 자동 스캔으로 WDA IP 동적 탐색
- 연결 끊기면 자동 재탐색 (IP 변경 대응)
- com.apple.springboard / com.lguplus.aicallagent 두 화면 모두 대응
- accessibility id + XPath 이중 폴백으로 버튼 탐색
"""

import re
import time
import socket
import requests
from requests.exceptions import ConnectionError, Timeout
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── 받기 버튼 후보 (accessibility id) ────────────────────────────
ACCEPT_LABELS = [
    "수락", "받기", "응답",
    "Accept", "Answer", "answer",
]

# ── 받기 버튼 XPath 후보 (label/name 기반) ───────────────────────
ACCEPT_XPATHS = [
    '//*[@label="수락"]',
    '//*[@label="받기"]',
    '//*[@label="응답"]',
    '//*[@name="수락"]',
    '//*[@name="받기"]',
    '//*[@name="응답"]',
    '//*[@label="Accept"]',
    '//*[@label="Answer"]',
    '//XCUIElementTypeButton[contains(@label,"수락")]',
    '//XCUIElementTypeButton[contains(@label,"받기")]',
    '//XCUIElementTypeButton[contains(@label,"응답")]',
]

# 수신 전화가 표시되는 번들ID
INCOMING_BUNDLES = {
    "com.apple.springboard",    # 잠금화면/홈화면 수신
    "com.lguplus.aicallagent",  # LG U+ AI 전화 에이전트 (익시오)
    "com.apple.mobilephone",    # Apple 전화
    "com.sktelecom.tphone",     # 에이닷 전화
    "com.skt.prod.dialer",      # 에이닷 전화 (bundle ID 변형)
}

# springboard는 WDA가 세션 생성을 거부하므로 대체 번들ID 사용
SPRINGBOARD_FALLBACK_BUNDLES = [
    "com.lguplus.aicallagent",
    "com.apple.mobilephone",
    "com.sktelecom.tphone",
    "com.skt.prod.dialer",
    "",  # bundleId 없이 시도
]


# ─────────────────────────────────────────────────────────────────────────────
# 서브넷 스캔
# ─────────────────────────────────────────────────────────────────────────────

def _scan_wda(ip: str, port: int = 8100, timeout: float = 1.0) -> str | None:
    try:
        r = requests.get(f"http://{ip}:{port}/status", timeout=timeout)
        if r.status_code == 200:
            return ip
    except Exception:
        pass
    return None


def find_wda_ip(port: int = 8100, verbose: bool = True) -> str | None:
    """
    1) mDNS .local / coredevice.local 호스트명으로 직접 시도 (빠름)
    2) 실패 시 서브넷 전체 병렬 스캔 (타임아웃 1.5초)
    """
    import re as _re, subprocess as _sp, json as _json, tempfile, os

    # ── 1단계: devicectl로 연결된 iPhone mDNS 호스트명 수집 ─────────────────
    mdns_candidates = []
    try:
        tmp = tempfile.mktemp(suffix='.json')
        _sp.run(
            ['xcrun', 'devicectl', 'list', 'devices', '--json-output', tmp],
            capture_output=True, timeout=8
        )
        if os.path.exists(tmp):
            with open(tmp) as f:
                data = _json.load(f)
            for dev in data.get('result', {}).get('devices', []):
                conn = dev.get('connectionProperties', {})
                # localHostnames 는 배열, localHostname 은 단일 문자열 (버전별 상이)
                hostnames = conn.get('localHostnames', [])
                if isinstance(hostnames, str):
                    hostnames = [hostnames]
                single = conn.get('localHostname', '')
                if single:
                    hostnames = [single] + list(hostnames)
                for hostname in hostnames:
                    if '.local' not in hostname:
                        continue
                    if hostname not in mdns_candidates:
                        mdns_candidates.append(hostname)
            os.unlink(tmp)
    except Exception:
        pass

    # 호스트명 → IP 변환 후 WDA 확인
    for host in mdns_candidates:
        try:
            res = _sp.run(['ping', '-c', '1', '-W', '1000', host],
                          capture_output=True, text=True, timeout=3)
            m = _re.search(r'PING [^(]+\((\d+\.\d+\.\d+\.\d+)\)', res.stdout)
            if m:
                ip = m.group(1)
                if _scan_wda(ip, port, timeout=2):
                    if verbose:
                        print(f"✅ WDA 발견 (mDNS {host}): http://{ip}:{port}")
                    return ip
        except Exception:
            pass

    # ── 2단계: 서브넷 전체 스캔 ──────────────────────────────────────────────
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        if verbose:
            print("⚠️  Mac IP 조회 실패")
        return None

    subnet = ".".join(local_ip.split(".")[:3])
    if verbose:
        print(f"🔍 WDA 스캔 중... ({subnet}.1~254, 포트={port})")

    found = None
    with ThreadPoolExecutor(max_workers=60) as pool:
        futs = {pool.submit(_scan_wda, f"{subnet}.{i}", port, 1.5): i for i in range(1, 255)}
        for fut in as_completed(futs):
            ip = fut.result()
            if ip:
                found = ip
                for f in futs:
                    f.cancel()
                break

    if verbose:
        if found:
            print(f"✅ WDA 발견: http://{found}:{port}")
        else:
            print(f"❌ WDA 를 찾지 못했습니다 (포트 {port})")
    return found


# ─────────────────────────────────────────────────────────────────────────────
# 메인 클래스
# ─────────────────────────────────────────────────────────────────────────────

class WdaAnswerer:
    """
    WDA REST API로 수신 전화 자동 응답.

    Parameters
    ----------
    wda_url : str | None
        "http://192.168.x.x:8100" 형식. None 이면 자동 스캔.
    wda_port : int
        WDA HTTP 포트 (기본 8100).
    """

    def __init__(self, wda_url: str | None = None, wda_port: int = 8100):
        self._port = wda_port
        self._session_cache: dict[str, str] = {}

        if wda_url:
            self.wda = wda_url.rstrip("/")
            print(f"🌐 WdaAnswerer: {self.wda} (고정)")
        else:
            self.wda = self._scan_or_raise()

    def _scan_or_raise(self) -> str:
        """자동 스캔 → 실패 시 RuntimeError"""
        ip = find_wda_ip(self._port)
        if not ip:
            raise RuntimeError("WDA IP 자동 탐색 실패")
        return f"http://{ip}:{self._port}"

    def _reconnect(self) -> bool:
        """
        IP가 변경되었거나 연결이 끊겼을 때 재탐색.
        새 IP 발견 시 self.wda 업데이트 후 True 반환.
        """
        print(f"\n🔄 WDA 연결 끊김 → IP 재탐색 중...")
        self._clear_all_sessions()
        ip = find_wda_ip(self._port)
        if ip:
            self.wda = f"http://{ip}:{self._port}"
            print(f"✅ 새 WDA 주소: {self.wda}")
            return True
        print("❌ WDA 재탐색 실패")
        return False

    def _request(self, method: str, path: str, **kwargs) -> requests.Response | None:
        """
        WDA 요청 래퍼.
        ConnectionError / Timeout 발생 시 1회 재탐색 후 재시도.
        """
        url = f"{self.wda}{path}"
        try:
            return getattr(requests, method)(url, **kwargs)
        except (ConnectionError, Timeout):
            if self._reconnect():
                try:
                    return getattr(requests, method)(f"{self.wda}{path}", **kwargs)
                except Exception:
                    pass
        except Exception:
            pass
        return None

    # ── 세션 관리 ─────────────────────────────────────────────────────────────

    def _create_session(self, bundle_id: str) -> str | None:
        """bundleId로 세션 생성. springboard는 대체 bundleId 목록으로 재시도."""
        bundle_list = (
            SPRINGBOARD_FALLBACK_BUNDLES
            if bundle_id == "com.apple.springboard"
            else [bundle_id]
        )
        for bid in bundle_list:
            caps: dict = {"capabilities": {"alwaysMatch": {"platformName": "iOS"}}}
            if bid:
                caps["capabilities"]["alwaysMatch"]["bundleId"] = bid
            try:
                r = self._request("post", "/session", json=caps, timeout=30)
                if r is None:
                    continue
                data = r.json()
                sid = data.get("sessionId") or data.get("value", {}).get("sessionId")
                if sid:
                    label = bid or "(bundleId 없음)"
                    print(f"  ✅ WDA 세션 생성 [{label[:35]}] → {sid[:8]}...")
                    return sid
            except Exception as e:
                print(f"  ⚠️  세션 생성 실패 [{bid}]: {e}")
        return None

    def _delete_session(self, sid: str):
        try:
            self._request("delete", f"/session/{sid}", timeout=5)
        except Exception:
            pass

    def _clear_all_sessions(self):
        for sid in self._session_cache.values():
            self._delete_session(sid)
        self._session_cache.clear()

    # ── 활성 앱 ───────────────────────────────────────────────────────────────

    def _active_bundle(self) -> str | None:
        r = self._request("get", "/wda/activeAppInfo", timeout=4)
        if r is not None and r.status_code == 200:
            data = r.json()
            return (
                data.get("value", {}).get("bundleId")
                or data.get("bundleId")
            )
        return None

    # ── 버튼 클릭 ─────────────────────────────────────────────────────────────

    def _click_element(self, sid: str, eid: str) -> bool:
        r = self._request("post", f"/session/{sid}/element/{eid}/click", timeout=5)
        return r is not None and r.status_code == 200

    def _find_and_click(self, sid: str, using: str, value: str) -> bool:
        r = self._request(
            "post", f"/session/{sid}/element",
            json={"using": using, "value": value}, timeout=5,
        )
        if r is None:
            return False
        val = r.json().get("value", {})
        eid = val.get("ELEMENT") or val.get("elementId")
        if eid:
            if self._click_element(sid, eid):
                print(f"  ✅ WDA 클릭: {using}='{value}'")
                return True
        return False

    def _tap_coordinate(self, sid: str, x: int, y: int) -> bool:
        """WDA 좌표 탭 (accessible=false 앱 대응)"""
        r = self._request(
            "post", f"/session/{sid}/wda/tap/0",
            json={"x": x, "y": y}, timeout=5,
        )
        if r is None:
            # 구버전 WDA endpoint
            r = self._request(
                "post", f"/session/{sid}/actions",
                json={"actions": [{"type": "pointer", "id": "finger",
                      "parameters": {"pointerType": "touch"},
                      "actions": [
                          {"type": "pointerMove", "x": x, "y": y, "duration": 0},
                          {"type": "pointerDown", "button": 0},
                          {"type": "pause", "duration": 50},
                          {"type": "pointerUp", "button": 0},
                      ]}]},
                timeout=5,
            )
        ok = r is not None and r.status_code in (200, 204)
        if ok:
            print(f"  ✅ WDA 좌표 탭: ({x}, {y})")
        return ok

    def _try_click_in_session(self, sid: str) -> bool:
        """accessibility id → XPath → 좌표 탭 순서로 받기 버튼 탐색·클릭"""
        # page source 가져오기: WDA는 JSON {"value": "<xml...>"} 형태로 반환
        src_r = self._request("get", f"/session/{sid}/source", timeout=10)
        if not src_r:
            src = ""
        else:
            try:
                # JSON에서 실제 XML 문자열 추출
                src = src_r.json().get("value", "")
            except Exception:
                src = src_r.text

        # accessible 여부 진단
        all_inaccessible = src and 'accessible="false"' in src and 'accessible="true"' not in src
        if all_inaccessible:
            print(f"  ⚠️  모든 요소 accessible=false → 좌표 탭으로 전환")

        # 1차: accessibility id (accessible=true 요소가 있을 때만)
        if not all_inaccessible:
            for label in ACCEPT_LABELS:
                if label in src:
                    if self._find_and_click(sid, "accessibility id", label):
                        return True

            # 2차: XPath
            for xpath in ACCEPT_XPATHS:
                if self._find_and_click(sid, "xpath", xpath):
                    return True

            # 3차: source 버튼 이름 동적 매칭
            btn_labels = re.findall(
                r'XCUIElementTypeButton[^/]*?(?:label|name)="([^"]+)"', src
            )
            if btn_labels:
                print(f"  ℹ️  화면 버튼 목록: {btn_labels}")
                for bl in btn_labels:
                    for kw in ["수락", "받기", "응답", "accept", "answer"]:
                        if kw.lower() in bl.lower():
                            if self._find_and_click(sid, "accessibility id", bl):
                                return True

        # 4차: 좌표 탭 (accessible=false 하이브리드 앱 대응)
        # iPhone 수신 전화 받기 버튼 위치 후보 (iPhone 14 기준 390×844)
        # 익시오 수신 화면: '받기' 버튼 bounds [282, 720, 70, 70] → center (317, 755)
        tap_candidates = [
            (317, 755),  # 익시오 받기 버튼 (우측, GroundView 기준)
            (290, 720),  # 받기 버튼 영역 대체
            (195, 720),  # 중앙 하단 (구형 레이아웃 대비)
            (195, 680),
        ]
        for x, y in tap_candidates:
            if self._tap_coordinate(sid, x, y):
                time.sleep(0.5)
                # 탭 후 화면이 통화 화면으로 바뀌었는지 간단 확인
                bundle = self._active_bundle()
                if bundle not in INCOMING_BUNDLES:
                    print(f"  ✅ 좌표 탭 후 화면 전환 확인 ({x},{y}) → {bundle}")
                    return True

        return False

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def try_answer_once(self) -> bool:
        """활성 앱이 수신 화면이면 받기 버튼 클릭. 성공 시 True."""
        bundle = self._active_bundle()
        if not bundle or bundle not in INCOMING_BUNDLES:
            return False

        print(f"  📲 수신 전화 화면 감지: {bundle}")

        if bundle not in self._session_cache:
            self._clear_all_sessions()
            sid = self._create_session(bundle)
            if sid:
                self._session_cache[bundle] = sid
            else:
                return False

        sid = self._session_cache[bundle]
        clicked = self._try_click_in_session(sid)

        if clicked:
            self._clear_all_sessions()

        return clicked

    def wait_and_answer(self, timeout: int = 30, poll: float = 1.0) -> bool:
        """
        수신 전화를 기다렸다 자동 응답.
        IP가 바뀌어도 내부에서 재탐색 후 계속 시도합니다.
        """
        print(f"⏳ WDA 수신 대기 중... (최대 {timeout}초, WDA={self.wda})")
        deadline = time.time() + timeout

        while time.time() < deadline:
            if self.try_answer_once():
                return True
            print(".", end="", flush=True)
            time.sleep(poll)

        print(f"\n⏱️  WDA 수신 타임아웃 ({timeout}초)")
        return False

    def close(self):
        """열린 세션 모두 정리"""
        self._clear_all_sessions()
