"""
wda_installer.py
──────────────────────────────────────────────────────────────────────────────
WDA.ipa 빌드·설치 관리 (크로스플랫폼: macOS / Windows / Linux)

설치 우선순위:
  1. tidevice (pip install tidevice) — macOS / Windows / Linux 모두 지원
  2. ideviceinstaller (libimobiledevice) — macOS 전용
  3. pymobiledevice3 (pip install pymobiledevice3) — macOS / Windows / Linux
"""

import subprocess
import sys
import os
import tempfile


def _run(cmd: list, timeout: int = 180) -> tuple[bool, str]:
    """명령어를 실행하고 (성공여부, 출력) 반환."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, f"타임아웃 ({timeout}초)"
    except FileNotFoundError:
        return False, f"명령어 없음: {cmd[0]}"
    except Exception as e:
        return False, str(e)


def install_wda(ipa_path: str, udid: str | None = None) -> tuple[bool, str]:
    """WDA.ipa를 iPhone에 설치합니다.

    Args:
        ipa_path: WDA.ipa 파일 경로
        udid:     설치할 디바이스 UDID (None이면 연결된 첫 번째 기기 사용)

    Returns:
        (success, message) 튜플
    """
    if not os.path.exists(ipa_path):
        return False, f"❌ IPA 파일을 찾을 수 없습니다: {ipa_path}"

    print(f"📦 WDA 설치 시작: {ipa_path}")

    # ── 1. tidevice (크로스플랫폼 최우선) ─────────────────────────────────
    ok, msg = _try_tidevice(ipa_path, udid)
    if ok:
        return True, f"✅ WDA 설치 완료 (tidevice): {msg}"
    if _tool_exists('tidevice') and msg and '없음' not in msg:
        # tidevice 있는데 실패 → 다른 방법 시도 전 로그
        print(f"  ⚠️ tidevice 오류: {msg[:120]}")

    # ── 2. ideviceinstaller (macOS + libimobiledevice) ─────────────────────
    if sys.platform == 'darwin':
        ok, msg2 = _try_ideviceinstaller(ipa_path, udid)
        if ok:
            return True, f"✅ WDA 설치 완료 (ideviceinstaller): {msg2}"

    # ── 3. pymobiledevice3 ────────────────────────────────────────────────
    ok, msg3 = _try_pymobiledevice3(ipa_path, udid)
    if ok:
        return True, f"✅ WDA 설치 완료 (pymobiledevice3): {msg3}"

    return False, (
        "❌ WDA 설치 실패. 아래 중 하나를 설치하세요:\n"
        "  pip install tidevice          ← 크로스플랫폼 권장\n"
        "  pip install pymobiledevice3\n"
        "  (macOS) brew install libimobiledevice"
    )


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _tool_exists(name: str) -> bool:
    """PATH에 해당 툴이 있는지 확인."""
    import shutil
    return shutil.which(name) is not None


def _try_tidevice(ipa_path: str, udid: str | None) -> tuple[bool, str]:
    if not _tool_exists('tidevice'):
        # Python 모듈로도 시도
        try:
            import tidevice  # noqa: F401
        except ImportError:
            return False, "tidevice 미설치"

    cmd = ['tidevice']
    if udid:
        cmd += ['-u', udid]
    cmd += ['install', ipa_path]
    print(f"  🔧 tidevice install 실행 중...")
    ok, msg = _run(cmd, timeout=300)
    # tidevice 성공 메시지 판별
    if ok or 'Install Success' in msg or 'Complete' in msg or 'installing' in msg.lower():
        return True, msg
    return False, msg


def _try_ideviceinstaller(ipa_path: str, udid: str | None) -> tuple[bool, str]:
    if not _tool_exists('ideviceinstaller'):
        return False, "ideviceinstaller 미설치"

    cmd = ['ideviceinstaller']
    if udid:
        cmd += ['-u', udid]
    cmd += ['-i', ipa_path]
    print(f"  🔧 ideviceinstaller 실행 중...")
    ok, msg = _run(cmd, timeout=300)
    return ok or 'Complete' in msg, msg


def _try_pymobiledevice3(ipa_path: str, udid: str | None) -> tuple[bool, str]:
    try:
        import pymobiledevice3  # noqa: F401
    except ImportError:
        return False, "pymobiledevice3 미설치"

    cmd = [sys.executable, '-m', 'pymobiledevice3', 'apps', 'install', ipa_path]
    if udid:
        cmd += ['--udid', udid]
    print(f"  🔧 pymobiledevice3 install 실행 중...")
    ok, msg = _run(cmd, timeout=300)
    return ok, msg


def check_wda_installed(udid: str | None = None) -> bool:
    """WDA 번들이 iPhone에 설치되어 있는지 확인."""
    bundle_id = 'com.jjun.1.WebDriverAgentRunner'

    # tidevice applist
    if _tool_exists('tidevice'):
        cmd = ['tidevice']
        if udid:
            cmd += ['-u', udid]
        cmd += ['applist']
        ok, msg = _run(cmd, timeout=15)
        if ok and bundle_id in msg:
            return True

    # ideviceinstaller (macOS)
    if sys.platform == 'darwin' and _tool_exists('ideviceinstaller'):
        cmd = ['ideviceinstaller', '--list-apps', '-o', 'list_user']
        if udid:
            cmd[1:1] = ['-u', udid]
        ok, msg = _run(cmd, timeout=15)
        if ok and bundle_id in msg:
            return True

    return False


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='WDA.ipa 설치')
    parser.add_argument('ipa_path', help='WDA.ipa 파일 경로')
    parser.add_argument('--udid', '-u', default=None, help='디바이스 UDID (선택)')
    args = parser.parse_args()

    success, message = install_wda(args.ipa_path, args.udid)
    print(message)
    sys.exit(0 if success else 1)
