"""
app_scanner.py
─────────────────────────────────────────────────────────────────────────────
녹음 파일 자동 탐지, Gemini API 키 로드, iOS·Android 앱 버전 조회 유틸리티.

analyze_hybrid.py 에서 분리된 모듈.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from _hybrid_config import (
    AUDIO_REFERENCE,
    CALL_META,
    COLLECTED_DIR,
    ENV_FILE,
    RECORDINGS_DIR,
)

# 화자별 정답지 (없으면 AUDIO_REFERENCE 폴백)
try:
    from _hybrid_config import AUDIO_REFERENCE_IOS, AUDIO_REFERENCE_ANDROID
except ImportError:
    AUDIO_REFERENCE_IOS: dict[int, str] = {}
    AUDIO_REFERENCE_ANDROID: dict[int, str] = {}

# ── 장치 패키지 ID ──────────────────────────────────────
ANDROID_PKG  = "com.lguplus.aicallagent"
iOS_PKG      = "com.lguplus.aicallagent"

_IOS_VER_CACHE = "/tmp/ixio_ios_ver.cache"
_AND_VER_CACHE = "/tmp/ixio_and_ver.cache"

# ── 파일명 패턴 ─────────────────────────────────────────
# recording_iOS_YYYYMMDD_HHMMSS_N.wav / recording_android_YYYYMMDD_HHMMSS_N.wav
_NEW_PAT = re.compile(
    r"recording_(iOS|android)_(\d{8})_(\d{6})_(\d+)\.wav$", re.IGNORECASE
)
# CallAudioCollector / MixerRecorder 수집 패턴:
#   iOS_ixiO_YYYYMMDD_HHMMSS.wav              (TC 라벨 없음, 앱명 ixiO)
#   iOS_ixiO_TC_01_YYYYMMDD_HHMMSS.wav        (TC 라벨, 앱명 ixiO)
#   iOS_Samsung_TC_00_YYYYMMDD_HHMMSS.wav      (앱명 Samsung)
#   iOS_Samsung_LGU+_TC_00_YYYYMMDD_HHMMSS.wav (앱명 + 캐리어 태그)
#   iOS_ixiO_LGU+_TC_00_YYYYMMDD_HHMMSS.wav   (앱명 ixiO + 캐리어 태그)
_COLLECTED_PAT = re.compile(
    r"^(iOS|Android)_[A-Za-z]+_(?:[A-Za-z+]+_)?(?:(TC_\d{2})_)?(\d{8})_(\d{6})\.wav$",
    re.IGNORECASE,
)
# 구형 패턴 fallback
_OLD_IOS_PAT     = re.compile(r"^recording(\d+)\.wav$")
_OLD_ANDROID_PAT = re.compile(r"^android_recording(\d+)\.wav$")


# ─────────────────────────────────────────────────────────────────────────────
# 파일 탐지
# ─────────────────────────────────────────────────────────────────────────────

def _hhmmss(s: str) -> str:
    """'091700' → '09:17:00'"""
    return f"{s[:2]}:{s[2:4]}:{s[4:6]}"


def find_collected_recordings() -> list:
    """COLLECTED_DIR(audio_files/recordings/collected/)에서 iOS_ixiO_*/Android_ixiO_* 파일 탐지.
    날짜별 서브폴더(YYYY-MM-DD/)도 재귀 탐색."""
    if not os.path.isdir(COLLECTED_DIR):
        return []
    # 최상위 + 날짜별 서브폴더를 모두 탐색
    scan_dirs = [COLLECTED_DIR]
    for entry in os.listdir(COLLECTED_DIR):
        sub = os.path.join(COLLECTED_DIR, entry)
        if os.path.isdir(sub):
            scan_dirs.append(sub)
    ios_ts:  dict = {}  # ts_key → path
    and_ts:  dict = {}  # ts_key → path
    for scan_dir in scan_dirs:
        for fname in sorted(os.listdir(scan_dir)):
            m = _COLLECTED_PAT.match(fname)
            if not m:
                continue
            os_tag, tc_label, date8, time6 = m.group(1), m.group(2), m.group(3), m.group(4)
            ts_key = f"{date8}_{time6}"
            path   = os.path.join(scan_dir, fname)
            if os_tag.lower() == 'ios':
                ios_ts[ts_key] = path
            else:
                and_ts[ts_key] = path
    all_ts = sorted(set(list(ios_ts.keys()) + list(and_ts.keys())))
    if not all_ts:
        return []
    calls = []
    for rank, ts in enumerate(all_ts, start=1):
        st = _hhmmss(ts.split('_')[1])
        meta = CALL_META.get(rank, {"label": f"음원 {rank} ({ts})", "speakers": ""})
        calls.append({
            "label":      meta["label"],
            "speakers":   meta.get("speakers", ""),
            "start_time": st,
            "ios":        ios_ts.get(ts, ""),
            "android":    and_ts.get(ts, ""),
            "ref":        AUDIO_REFERENCE.get(1, ""),  # 레거시 공통 정답지
            "ref_ios":    AUDIO_REFERENCE_IOS.get(1, ""),      # S1→iOS 정답지
            "ref_android": AUDIO_REFERENCE_ANDROID.get(1, ""),  # S2→Android 정답지
        })
    return calls


def find_recordings() -> list:
    """RECORDINGS_DIR에서 녹음 파일을 자동 탐지하여 CALLS 리스트를 반환.
    날짜별 서브폴더(YYYY-MM-DD/)도 재귀 탐색."""
    if not os.path.isdir(RECORDINGS_DIR):
        return []

    # 최상위 + 날짜별 서브폴더를 모두 탐색
    scan_dirs = [RECORDINGS_DIR]
    for entry in os.listdir(RECORDINGS_DIR):
        sub = os.path.join(RECORDINGS_DIR, entry)
        if os.path.isdir(sub):
            scan_dirs.append(sub)

    entries = []
    for scan_dir in scan_dirs:
        for fname in os.listdir(scan_dir):
            entries.append((scan_dir, fname))

    # ── 신규 패턴 수집 ──────────────────────────────────
    new_ios:     dict = {}
    new_android: dict = {}

    for scan_dir, fname in entries:
        m = _NEW_PAT.match(fname)
        if not m:
            continue
        os_tag, date8, time6, idx_s = m.group(1), m.group(2), m.group(3), m.group(4)
        idx  = int(idx_s)
        path = os.path.join(scan_dir, fname)
        st   = _hhmmss(time6)
        if os_tag.lower() == "ios":
            new_ios[idx] = (path, st)
        else:
            new_android[idx] = (path, st)

    if new_ios or new_android:
        all_idx = sorted(set(list(new_ios.keys()) + list(new_android.keys())))
        calls = []
        for idx in all_idx:
            ios_info = new_ios.get(idx)
            and_info = new_android.get(idx)
            st = (ios_info or and_info)[1] if (ios_info or and_info) else ""
            meta = CALL_META.get(idx, {"label": f"음원 {idx}", "speakers": ""})
            calls.append({
                "label":      meta["label"],
                "speakers":   meta["speakers"],
                "start_time": st,
                "ios":        ios_info[0] if ios_info  else "",
                "android":    and_info[0] if and_info else "",
                "ref":        AUDIO_REFERENCE.get(idx, ""),
                "ref_ios":    AUDIO_REFERENCE_IOS.get(idx, ""),
                "ref_android": AUDIO_REFERENCE_ANDROID.get(idx, ""),
            })
        return calls

    # ── 구형 패턴 fallback ──────────────────────────────
    old_ios:     dict = {}
    old_android: dict = {}
    for scan_dir, fname in entries:
        m = _OLD_IOS_PAT.match(fname)
        if m:
            old_ios[int(m.group(1))] = os.path.join(scan_dir, fname)
            continue
        m = _OLD_ANDROID_PAT.match(fname)
        if m:
            old_android[int(m.group(1))] = os.path.join(scan_dir, fname)

    if old_ios or old_android:
        _OLD_ST = {1: "09:17:00", 2: "09:24:00"}
        all_idx = sorted(set(list(old_ios.keys()) + list(old_android.keys())))
        calls = []
        for idx in all_idx:
            meta = CALL_META.get(idx, {"label": f"음원 {idx}", "speakers": ""})
            calls.append({
                "label":      meta["label"],
                "speakers":   meta["speakers"],
                "start_time": _OLD_ST.get(idx, ""),
                "ios":        old_ios.get(idx, ""),
                "android":    old_android.get(idx, ""),
                "ref":        AUDIO_REFERENCE.get(idx, ""),
                "ref_ios":    AUDIO_REFERENCE_IOS.get(idx, ""),
                "ref_android": AUDIO_REFERENCE_ANDROID.get(idx, ""),
            })
        return calls

    return []


# collected 디렉토리 우선, 없으면 recordings/ 폴백
CALLS = find_collected_recordings() or find_recordings()


# ─────────────────────────────────────────────────────────────────────────────
# API 키 로드
# ─────────────────────────────────────────────────────────────────────────────

def load_env_key() -> str | None:
    if not os.path.exists(ENV_FILE):
        return None
    with open(ENV_FILE) as f:
        for line in f:
            if 'GEMINI_API_KEY' in line:
                return line.split('=', 1)[1].strip().strip('"\'%')
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 앱 버전 캐시
# ─────────────────────────────────────────────────────────────────────────────

def _read_cache(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return ""


def _write_cache(path: str, val: str) -> None:
    try:
        with open(path, "w") as f:
            f.write(val)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 앱 버전 조회
# ─────────────────────────────────────────────────────────────────────────────

def fetch_android_app_version(pkg: str | None = None) -> str:
    """연결된 Android 디바이스에서 앱 버전 조회 → '01.22.00(12214)'"""
    target_pkg = pkg or ANDROID_PKG
    try:
        devs = subprocess.check_output(
            ["adb", "devices"], text=True, timeout=5, stderr=subprocess.DEVNULL
        )
        serials = [
            line.split()[0]
            for line in devs.splitlines()
            if line.endswith("\tdevice")
        ]
        if not serials:
            cached = _read_cache(_AND_VER_CACHE)
            if cached:
                print(f"    Android {target_pkg}: 캐시에서 읽음 (디바이스 미연결)")
            return cached
        serial = serials[0]
        out = subprocess.check_output(
            ["adb", "-s", serial, "shell", "dumpsys", "package", target_pkg],
            text=True, timeout=10, stderr=subprocess.DEVNULL
        )
        ver_name = re.search(r"versionName=(\S+)", out)
        ver_code = re.search(r"versionCode=(\d+)", out)
        if ver_name and ver_code:
            ver = f"{ver_name.group(1)}({ver_code.group(1)})"
            _write_cache(_AND_VER_CACHE, ver)
            return ver
        return ""
    except Exception:
        cached = _read_cache(_AND_VER_CACHE)
        if cached:
            print(f"    Android {target_pkg}: 캐시에서 읽음 (adb 오류)")
        return cached


def fetch_ios_app_version(pkg: str | None = None) -> str:
    """연결된 iOS 디바이스에서 앱 버전 조회.

    우선순위:
      ① pymobiledevice3 Python API
      ② ideviceinstaller -l -o xml
      ③ ideviceinstaller -l
      ④ xcrun devicectl --json-output
      ⑤ tidevice applist
      ⑥ /tmp 캐시
    """
    target_pkg = pkg or iOS_PKG

    def _found(ver: str) -> str:
        _write_cache(_IOS_VER_CACHE, ver)
        return ver

    # ① pymobiledevice3
    try:
        from pymobiledevice3.lockdown import create_using_usbmux  # type: ignore
        from pymobiledevice3.services.installation_proxy import InstallationProxyService  # type: ignore
        ld   = create_using_usbmux()
        apps = InstallationProxyService(lockdown=ld).get_apps('User')
        info = apps.get(target_pkg, {})
        short = info.get('CFBundleShortVersionString', '')
        build = info.get('CFBundleVersion', '')
        if short:
            return _found(f"{short}({build})" if build else short)
    except Exception:
        pass

    # ② ideviceinstaller -l -o xml
    try:
        import plistlib
        r = subprocess.run(
            ["ideviceinstaller", "-l", "-o", "xml"],
            capture_output=True, timeout=20
        )
        if r.returncode == 0 and r.stdout.strip().startswith(b"<?xml"):
            plist_data = plistlib.loads(r.stdout)
            for item in (plist_data if isinstance(plist_data, list) else []):
                if item.get('CFBundleIdentifier') == target_pkg:
                    short = item.get('CFBundleShortVersionString', '')
                    build = item.get('CFBundleVersion', '')
                    if short:
                        return _found(f"{short}({build})" if build else short)
    except Exception:
        pass

    # ③ ideviceinstaller -l
    build_fallback = ""
    try:
        r = subprocess.run(
            ["ideviceinstaller", "-l"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if target_pkg in line:
                    m = re.search(r'"([^"]+)"', line.split(target_pkg, 1)[1])
                    if m:
                        build_fallback = m.group(1)
                    break
    except Exception:
        pass

    # ④ xcrun devicectl
    try:
        tmp_dev = tempfile.mktemp(suffix=".json")
        subprocess.run(
            ["xcrun", "devicectl", "list", "devices", "--json-output", tmp_dev],
            capture_output=True, timeout=8
        )
        with open(tmp_dev) as f:
            ddata = json.load(f)
        try:
            os.unlink(tmp_dev)
        except Exception:
            pass
        uuid = None
        for dev in ddata.get("result", {}).get("devices", []):
            if dev.get("connectionProperties", {}).get("tunnelState") == "connected":
                uuid = dev.get("hardwareProperties", {}).get("udid", "")
                break
        if uuid:
            r = subprocess.run(
                ["xcrun", "devicectl", "device", "info", "apps",
                 "--device", uuid, "--include-all-apps"],
                capture_output=True, text=True, timeout=30
            )
            for line in r.stdout.splitlines():
                if target_pkg in line:
                    parts = line.split()
                    try:
                        bid_idx = next(i for i, p in enumerate(parts) if p == target_pkg)
                        ver  = parts[bid_idx + 1] if bid_idx + 1 < len(parts) else ""
                        bver = parts[bid_idx + 2] if bid_idx + 2 < len(parts) else ""
                        if ver:
                            return _found(f"{ver}({bver})" if bver else ver)
                    except (StopIteration, IndexError):
                        pass
    except Exception:
        pass

    # ⑤ tidevice applist
    try:
        r = subprocess.run(
            ["tidevice", "applist"], capture_output=True, text=True, timeout=15
        )
        for line in r.stdout.splitlines():
            if target_pkg in line:
                m = re.search(r'(\d+\.\d+[\.\d]*)', line.split(target_pkg, 1)[1])
                if m:
                    return _found(m.group(1))
    except Exception:
        pass

    # ⑥ 캐시
    cached = _read_cache(_IOS_VER_CACHE)
    if cached:
        print(f"    iOS {target_pkg}: 캐시에서 읽음 (디바이스 직접 접근 불가)")
        return cached

    return build_fallback


def get_app_versions(
    android_pkg: str | None = None,
    ios_pkg: str | None = None,
) -> tuple[str, str]:
    """두 플랫폼 앱 버전을 조회 → (android_ver, ios_ver)

    Args:
        android_pkg: Android 패키지명 (None이면 기본값 ixiO)
        ios_pkg: iOS 번들ID (None이면 기본값 ixiO)
    """
    a_pkg = android_pkg or ANDROID_PKG
    i_pkg = ios_pkg or iOS_PKG
    print(f"  플랫폼 앱 버전 조회 중... (Android={a_pkg}, iOS={i_pkg})")
    android_ver = fetch_android_app_version(android_pkg)
    ios_ver     = fetch_ios_app_version(ios_pkg)
    if android_ver:
        print(f"    Android [{a_pkg}]: {android_ver}")
    else:
        print(f"    Android [{a_pkg}]: 조회 실패 (디바이스 미연결 또는 앱 미설치)")
    if ios_ver:
        print(f"    iOS [{i_pkg}]:     {ios_ver}")
    else:
        print(f"    iOS [{i_pkg}]:     조회 실패 (디바이스 미연결 또는 앱 미설치)")
    return android_ver, ios_ver


# ─────────────────────────────────────────────────────────────────────────────
# 디바이스 정보 동적 조회
# ─────────────────────────────────────────────────────────────────────────────

_GALAXY_MODELS_PATH = Path(__file__).parent / "sound-test-app" / "src-tauri" / "scripts" / "galaxy_models.json"


def _load_galaxy_nickname(model: str) -> str:
    """ro.product.model → 마케팅명 (예: SM-F946N → Galaxy Z Fold5)."""
    if not model:
        return model
    try:
        db = json.loads(_GALAXY_MODELS_PATH.read_text(encoding="utf-8"))
        return db.get(model.strip(), model)
    except Exception:
        return model


def _detect_android_device() -> tuple[str, str]:
    """연결된 Android 디바이스 → (단말명, OS 버전)."""
    try:
        out = subprocess.check_output(
            ["adb", "devices"], text=True, timeout=5, stderr=subprocess.DEVNULL
        )
        serials = [
            line.split()[0]
            for line in out.splitlines()
            if line.endswith("\tdevice")
        ]
        if not serials:
            return "", ""
        serial = serials[0]
        model = subprocess.check_output(
            ["adb", "-s", serial, "shell", "getprop", "ro.product.model"],
            text=True, timeout=4, stderr=subprocess.DEVNULL
        ).strip()
        version = subprocess.check_output(
            ["adb", "-s", serial, "shell", "getprop", "ro.build.version.release"],
            text=True, timeout=4, stderr=subprocess.DEVNULL
        ).strip()
        manufacturer = subprocess.check_output(
            ["adb", "-s", serial, "shell", "getprop", "ro.product.manufacturer"],
            text=True, timeout=4, stderr=subprocess.DEVNULL
        ).strip().capitalize()
        nickname = _load_galaxy_nickname(model)
        # 닉네임이 모델코드와 같으면 제조사+모델 사용
        if nickname == model:
            name = f"{manufacturer} {model}" if manufacturer else model
        else:
            name = f"{manufacturer} {nickname}" if manufacturer else nickname
        os_ver = f"Android {version}" if version else ""
        return name, os_ver
    except Exception:
        return "", ""


def _detect_ios_device() -> tuple[str, str]:
    """연결된 iOS 디바이스 → (단말명, OS 버전)."""
    try:
        tmp = tempfile.mktemp(suffix=".json")
        r = subprocess.run(
            ["xcrun", "devicectl", "list", "devices", "--json-output", tmp],
            capture_output=True, timeout=10,
        )
        if r.returncode != 0 or not os.path.exists(tmp):
            return "", ""
        with open(tmp, encoding="utf-8") as f:
            data = json.load(f)
        os.unlink(tmp)

        for dev in data.get("result", {}).get("devices", []):
            hw   = dev.get("hardwareProperties", {})
            dp   = dev.get("deviceProperties", {})
            conn = dev.get("connectionProperties", {})
            # connected 상태인 디바이스만 (transportType이 있으면 연결됨)
            transport = conn.get("transportType", "")
            state = dev.get("connectionState", "")
            if not transport and state != "connected":
                continue
            marketing = hw.get("marketingName", "")
            version   = dp.get("osVersionNumber", "")
            if marketing:
                os_ver = f"iOS {version}" if version else ""
                return marketing, os_ver
        return "", ""
    except Exception:
        return "", ""


def get_device_info() -> dict[str, str]:
    """연결된 디바이스 정보를 동적 조회.

    Returns:
        {"Android 단말": ..., "Android OS 버전": ...,
         "iOS 단말": ..., "iOS OS 버전": ...}
    """
    print("  디바이스 정보 조회 중...")
    and_name, and_os = _detect_android_device()
    ios_name, ios_os = _detect_ios_device()

    if and_name:
        print(f"    Android: {and_name} / {and_os}")
    else:
        print("    Android: 조회 실패 (디바이스 미연결)")
    if ios_name:
        print(f"    iOS:     {ios_name} / {ios_os}")
    else:
        print("    iOS:     조회 실패 (디바이스 미연결)")

    return {
        "Android 단말":     and_name,
        "Android OS 버전": and_os,
        "iOS 단말":         ios_name,
        "iOS OS 버전":      ios_os,
    }
