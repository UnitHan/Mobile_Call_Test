"""
device_detector.py
──────────────────
현재 연결된 iOS / Android 디바이스를 자동 감지하는 유틸.

사용법:
    from device_detector import detect_all_devices, detect_ios_devices, detect_android_devices

    devices = detect_all_devices()
    # [{'udid': '...', 'name': '...', 'platform': 'iOS', 'version': '18.2', 'model': 'iPhone14,7'}, ...]

    ios   = detect_ios_devices()
    androids = detect_android_devices()
"""

import subprocess
import json
import re
import tempfile
import os
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# 쌓럭시 니콘임 DB
# ─────────────────────────────────────────────────────────────────────────────

_GALAXY_MODELS: dict[str, str] = {}

def _load_galaxy_models() -> dict[str, str]:
    """galaxy_models.json 로드 (동일 디렉토리 변경 시에도 동작)."""
    global _GALAXY_MODELS
    if _GALAXY_MODELS:
        return _GALAXY_MODELS
    json_path = Path(__file__).parent / 'galaxy_models.json'
    try:
        _GALAXY_MODELS = json.loads(json_path.read_text(encoding='utf-8'))
    except Exception:
        _GALAXY_MODELS = {}
    return _GALAXY_MODELS


def get_device_nickname(model: str) -> str:
    """ro.product.model 값으로 니콘임 반환.

    예) 'SM-S921N' → 'Galaxy S24'
    알 수 없는 모델이면 원본 model 문자열 반환.
    """
    if not model:
        return model
    db = _load_galaxy_models()
    return db.get(model.strip(), model)


# ─────────────────────────────────────────────────────────────────────────────
# iOS 감지
# ─────────────────────────────────────────────────────────────────────────────

def _fill_ios_versions_from_xctrace(devices: list[dict]):
    """ideviceinfo 또는 xcrun xctrace로 iOS 버전 보완"""
    for d in devices:
        if d.get('version'):
            continue
        # ideviceinfo 사용 (빠름)
        try:
            r = subprocess.run(
                ['ideviceinfo', '-u', d['udid'], '-k', 'ProductVersion'],
                capture_output=True, text=True, timeout=4
            )
            v = r.stdout.strip()
            if v:
                d['version'] = v
                continue
        except Exception:
            pass


def detect_ios_devices() -> list[dict]:
    """
    xcrun devicectl 로 연결된 iOS 디바이스 목록 반환.
    각 항목: {'udid', 'name', 'platform', 'version', 'model', 'state', 'hostname'}

    devicectl 없으면 ideviceinfo 로 fallback.
    """
    devices = []

    # ── 1차: xcrun devicectl ──────────────────────────────────────────────────
    try:
        tmp = tempfile.mktemp(suffix='.json')
        r = subprocess.run(
            ['xcrun', 'devicectl', 'list', 'devices', '--json-output', tmp],
            capture_output=True, timeout=10
        )
        if r.returncode == 0 and os.path.exists(tmp):
            with open(tmp, encoding='utf-8') as f:
                data = json.load(f)
            os.unlink(tmp)

            for dev in data.get('result', {}).get('devices', []):
                hw   = dev.get('hardwareProperties', {})
                dp   = dev.get('deviceProperties', {})
                conn = dev.get('connectionProperties', {})

                udid  = hw.get('udid', '')
                if not udid:
                    continue

                # pairingState == 'paired' 이면 tunnelState 무관하게 포함
                # (disconnected = 무선 등록됐지만 터널 미연결, unavailable = 비활성)
                pairing = conn.get('pairingState', '')
                if pairing != 'paired':
                    continue

                tunnel_state = conn.get('tunnelState', 'unknown')
                # state 표시: connected / disconnected / unavailable
                state = tunnel_state

                # 호스트명 수집 (mDNS용)
                hostnames = conn.get('localHostnames', [])
                if isinstance(hostnames, str):
                    hostnames = [hostnames]
                single = conn.get('localHostname', '')
                if single and single not in hostnames:
                    hostnames = [single] + list(hostnames)

                devices.append({
                    'udid':     udid,
                    'name':     dp.get('name', '') or hw.get('deviceName', ''),
                    'platform': 'iOS',
                    'version':  hw.get('osVersionNumber', ''),
                    'model':    hw.get('productType', ''),  # e.g. iPhone14,7
                    'state':    state,
                    'hostname': hostnames[0] if hostnames else '',
                })
            # xcrun xctrace 로 버전 보완 (devicectl JSON에 없을 때)
            _fill_ios_versions_from_xctrace(devices)
            return devices
    except Exception:
        pass

    # ── 2차: ideviceinfo fallback ─────────────────────────────────────────────
    try:
        r = subprocess.run(
            ['idevice_id', '-l'],
            capture_output=True, text=True, timeout=5
        )
        for udid in r.stdout.strip().splitlines():
            udid = udid.strip()
            if not udid:
                continue
            name = ''
            version = ''
            model = ''
            try:
                name_r = subprocess.run(
                    ['ideviceinfo', '-u', udid, '-k', 'DeviceName'],
                    capture_output=True, text=True, timeout=4
                )
                name = name_r.stdout.strip()
                ver_r = subprocess.run(
                    ['ideviceinfo', '-u', udid, '-k', 'ProductVersion'],
                    capture_output=True, text=True, timeout=4
                )
                version = ver_r.stdout.strip()
                model_r = subprocess.run(
                    ['ideviceinfo', '-u', udid, '-k', 'ProductType'],
                    capture_output=True, text=True, timeout=4
                )
                model = model_r.stdout.strip()
            except Exception:
                pass
            devices.append({
                'udid':     udid,
                'name':     name,
                'platform': 'iOS',
                'version':  version,
                'model':    model,
                'state':    'connected',
                'hostname': '',
            })
    except Exception:
        pass

    return devices


# ─────────────────────────────────────────────────────────────────────────────
# Android 감지
# ─────────────────────────────────────────────────────────────────────────────

def detect_android_devices() -> list[dict]:
    """
    adb devices 로 연결된 Android 디바이스 목록 반환.
    각 항목: {'udid', 'name', 'platform', 'version', 'model', 'state'}
    """
    devices = []
    try:
        r = subprocess.run(
            ['adb', 'devices', '-l'],
            capture_output=True, text=True, timeout=8
        )
        for line in r.stdout.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            # adb devices 출력: "udid\tdevice" 또는 "udid    device" (공백/탭 혼용)
            parts = re.split(r'\s+', line, maxsplit=1)
            if len(parts) < 2:
                continue
            udid  = parts[0].strip()
            # Android 11+ 무선 디버깅 mDNS 자동발견 항목 제외
            # (adb-XXXX._adb-tls-connect._tcp → IP:port 항목과 중복)
            if '_adb-tls-connect' in udid:
                continue
            # -l 옵션: "device product:xx model:xx ...", 미옵션: "device"
            state_word = parts[1].strip().split()[0]
            if state_word != 'device':
                continue

            # 모델명/버전 조회
            model    = _adb_prop(udid, 'ro.product.model')
            version  = _adb_prop(udid, 'ro.build.version.release')
            nickname = get_device_nickname(model)
            name     = nickname or model or udid

            devices.append({
                'udid':     udid,
                'name':     name,
                'platform': 'Android',
                'version':  version,
                'model':    model,
                'nickname': nickname,
                'state':    'connected',
                'hostname': '',
            })
    except Exception:
        pass
    return devices


def _adb_prop(udid: str, prop: str) -> str:
    try:
        r = subprocess.run(
            ['adb', '-s', udid, 'shell', 'getprop', prop],
            capture_output=True, text=True, timeout=4
        )
        return r.stdout.strip()
    except Exception:
        return ''


# ─────────────────────────────────────────────────────────────────────────────
# 통합 감지
# ─────────────────────────────────────────────────────────────────────────────

def detect_all_devices() -> list[dict]:
    """iOS + Android 전체 연결 디바이스 반환"""
    return detect_ios_devices() + detect_android_devices()


def auto_select_ios_udid() -> str | None:
    """
    현재 연결된 iOS 디바이스 중 첫 번째 UDID 반환.
    UDID가 필요한데 사용자가 지정하지 않았을 때 사용.
    """
    devs = detect_ios_devices()
    connected = [d for d in devs if d.get('state', '') in ('connected', 'unknown', '')]
    if not connected:
        connected = devs  # state 필드 없는 버전 대비
    if connected:
        d = connected[0]
        print(f"  📱 iOS 자동 감지: {d['name']} ({d['udid'][:16]}...) iOS {d['version']}")
        return d['udid']
    return None


def auto_select_android_udid() -> str | None:
    """현재 연결된 Android 디바이스 중 첫 번째 UDID 반환."""
    devs = detect_android_devices()
    if devs:
        d = devs[0]
        print(f"  🤖 Android 자동 감지: {d['name']} ({d['udid']})")
        return d['udid']
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CLI 진단 출력
# ─────────────────────────────────────────────────────────────────────────────

def print_connected_devices():
    """연결된 모든 디바이스 출력 (진단용)"""
    print("\n📡 연결된 디바이스 목록")
    print("=" * 60)

    all_devs = detect_all_devices()
    if not all_devs:
        print("  ⚠️  연결된 디바이스 없음")
        return

    for i, d in enumerate(all_devs, 1):
        icon = "🍎" if d['platform'] == 'iOS' else "🤖"
        print(f"  {i}. {icon} [{d['platform']}] {d['name']}")
        print(f"       UDID   : {d['udid']}")
        print(f"       버전   : {d['version']}")
        print(f"       모델   : {d['model']}")
        print(f"       상태   : {d['state']}")
        if d.get('hostname'):
            print(f"       호스트 : {d['hostname']}")
    print("=" * 60)


if __name__ == '__main__':
    print_connected_devices()
