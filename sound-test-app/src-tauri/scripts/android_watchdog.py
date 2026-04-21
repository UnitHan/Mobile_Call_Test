"""
android_watchdog.py
──────────────────────────────────────────────────────────────────────────────
Android 무선 ADB 연결을 365일 유지하는 Watchdog 데몬.

동작 원리:
  1. 주기적으로 'adb devices' 실행 → offline 감지
  2. offline 감지 시: disconnect → connect 재시도
  3. 재시도 실패 시: adb kill-server → start-server → connect
  4. keep-alive: 30초마다 'adb -s <udid> shell echo ping' 전송 (타임아웃 방지)
  5. 모든 상태 변화를 stdout으로 emit (Tauri event 수신 가능)

사용법:
  # 직접 실행 (디버그)
  python android_watchdog.py --devices 192.168.219.114:5555 [192.168.x.x:5555 ...]

  # subprocess로 실행 (Tauri에서 호출)
  python android_watchdog.py --devices <udid1> [udid2] [--interval 30] [--keepalive 30]
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
import threading
from datetime import datetime
from enum import Enum


# ── 상태 정의 ─────────────────────────────────────────────────────────────────
class DeviceState(Enum):
    ONLINE   = 'online'
    OFFLINE  = 'offline'
    MISSING  = 'missing'   # adb devices 목록에 아예 없음
    UNKNOWN  = 'unknown'


def _ts() -> str:
    return datetime.now().strftime('%H:%M:%S')


def _log(msg: str) -> None:
    print(f'[watchdog {_ts()}] {msg}', flush=True)


# ── ADB 헬퍼 ──────────────────────────────────────────────────────────────────
def _adb(*args, timeout: int = 10) -> tuple[int, str]:
    """adb 명령 실행 → (returncode, stdout+stderr)"""
    try:
        r = subprocess.run(
            ['adb', *args],
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, 'timeout'
    except FileNotFoundError:
        return -1, 'adb not found'
    except Exception as e:
        return -1, str(e)


def get_device_state(udid: str) -> DeviceState:
    """현재 ADB 연결 상태 반환."""
    code, out = _adb('devices', '-l')
    if code != 0:
        return DeviceState.UNKNOWN

    for line in out.splitlines():
        if line.startswith(udid):
            parts = line.split()
            if len(parts) < 2:
                return DeviceState.UNKNOWN
            state_word = parts[1]
            if state_word == 'device':
                return DeviceState.ONLINE
            elif state_word == 'offline':
                return DeviceState.OFFLINE
            else:
                return DeviceState.UNKNOWN  # e.g. unauthorized

    return DeviceState.MISSING


def keepalive(udid: str) -> bool:
    """기기에 경량 명령 전송 → 연결 유지."""
    code, _ = _adb('-s', udid, 'shell', 'echo', 'ping', timeout=5)
    return code == 0


def _ensure_forward(udid: str) -> None:
    """adb -s <udid> forward tcp:7779 tcp:7779 설정 (무선 연결 시마다 호출)."""
    try:
        r = _adb('-s', udid, 'forward', 'tcp:7779', 'tcp:7779', timeout=5)
        code = r[0] if isinstance(r, tuple) else r
        if code == 0:
            _log(f'  [{udid}] ✅ adb forward tcp:7779 설정 완료')
        else:
            _log(f'  [{udid}] ⚠️ adb forward 실패 (code={code})')
    except Exception as e:
        _log(f'  [{udid}] ⚠️ adb forward 오류: {e}')


def reconnect(udid: str, attempt: int = 1) -> bool:
    """
    offline/missing 기기 재연결 시도.

    단계:
      1차: disconnect → connect
      2차: kill-server → start-server → connect
      3차: (이후) 동일 반복
    """
    # ── 1단계: disconnect → connect ───────────────────────────────────────
    _log(f'  [{udid}] 재시도 #{attempt}: disconnect → connect ...')
    code, out = _adb('connect', udid, timeout=10)
    if 'connected' in out.lower() and 'unable' not in out.lower():
        _log(f'  [{udid}] ✅ 재연결 성공: {out}')
        _ensure_forward(udid)
        return True

    _log(f'  [{udid}] connect 응답: {out}')

    # ── 2단계 (2회 이상 실패 시): ADB 서버 재시작 ─────────────────────────
    if attempt % 2 == 0:
        _log(f'  [{udid}] ADB 서버 재시작 중...')
        _adb('kill-server', timeout=5)
        time.sleep(2)
        _adb('start-server', timeout=10)
        time.sleep(1)
        code2, out2 = _adb('connect', udid, timeout=10)
        if 'connected' in out2.lower() and 'unable' not in out2.lower():
            _log(f'  [{udid}] ✅ 서버 재시작 후 재연결 성공: {out2}')
            _ensure_forward(udid)
            return True
        _log(f'  [{udid}] 서버 재시작 후에도 실패: {out2}')

    return False


# ── 단일 기기 Watchdog ────────────────────────────────────────────────────────
class DeviceWatchdog(threading.Thread):
    """개별 Android 기기를 감시하는 백그라운드 스레드."""

    MAX_RETRY_INTERVAL = 60   # 최대 재시도 간격 (초)

    def __init__(self,
                 udid: str,
                 check_interval: int = 30,
                 keepalive_interval: int = 30):
        super().__init__(daemon=True, name=f'watchdog-{udid}')
        self.udid              = udid
        self.check_interval    = check_interval
        self.keepalive_interval = keepalive_interval
        self._stop_event       = threading.Event()
        self._fail_count       = 0
        self._last_keepalive   = 0.0

    def stop(self) -> None:
        self._stop_event.set()

    def _retry_interval(self) -> float:
        """지수 백오프 (최대 MAX_RETRY_INTERVAL초)."""
        return min(2 ** self._fail_count, self.MAX_RETRY_INTERVAL)

    def run(self) -> None:
        _log(f'[{self.udid}] 감시 시작 (check={self.check_interval}s, keepalive={self.keepalive_interval}s)')

        # 시작 시 일단 connect 시도
        code, out = _adb('connect', self.udid, timeout=10)
        if 'connected' in out.lower() and 'unable' not in out.lower():
            _ensure_forward(self.udid)
        time.sleep(1)

        while not self._stop_event.is_set():
            now   = time.time()
            state = get_device_state(self.udid)

            if state == DeviceState.ONLINE:
                self._fail_count = 0
                # keep-alive 주기가 됐으면 ping
                if now - self._last_keepalive >= self.keepalive_interval:
                    alive = keepalive(self.udid)
                    self._last_keepalive = now
                    if not alive:
                        _log(f'[{self.udid}] ⚠️  keep-alive 실패 (다음 주기에 재확인)')

            elif state in (DeviceState.OFFLINE, DeviceState.MISSING):
                self._fail_count += 1
                _log(f'[{self.udid}] 🔴 {state.value} 감지 (연속 {self._fail_count}회)')
                ok = reconnect(self.udid, attempt=self._fail_count)
                if not ok:
                    wait = self._retry_interval()
                    _log(f'[{self.udid}] ⏳ {wait:.0f}초 후 재시도 예정...')
                    self._stop_event.wait(wait)
                    continue
                else:
                    self._fail_count = 0

            else:  # UNKNOWN — ADB 데몬 크래시 가능성
                self._fail_count += 1
                _log(f'[{self.udid}] ❓ 상태 확인 불가 — ADB 서버 재시작 시도 (연속 {self._fail_count}회)')
                _adb('kill-server', timeout=5)
                time.sleep(2)
                _adb('start-server', timeout=10)
                time.sleep(1)
                code, out = _adb('connect', self.udid, timeout=10)
                if 'connected' in out.lower() and 'unable' not in out.lower():
                    _log(f'[{self.udid}] ✅ ADB 재시작 후 연결 복구: {out}')
                    _ensure_forward(self.udid)
                    self._fail_count = 0
                else:
                    wait = self._retry_interval()
                    _log(f'[{self.udid}] ⏳ ADB 복구 실패, {wait:.0f}초 후 재시도...')
                    self._stop_event.wait(wait)
                    continue

            self._stop_event.wait(self.check_interval)

        _log(f'[{self.udid}] 감시 종료')


# ── 멀티-기기 관리자 ──────────────────────────────────────────────────────────
class AndroidWatchdogManager:
    """여러 Android 기기를 동시에 감시."""

    def __init__(self, check_interval: int = 30, keepalive_interval: int = 30):
        self.check_interval    = check_interval
        self.keepalive_interval = keepalive_interval
        self._dogs: dict[str, DeviceWatchdog] = {}

    def add(self, udid: str) -> None:
        if udid in self._dogs:
            return
        dog = DeviceWatchdog(udid, self.check_interval, self.keepalive_interval)
        self._dogs[udid] = dog
        dog.start()

    def remove(self, udid: str) -> None:
        dog = self._dogs.pop(udid, None)
        if dog:
            dog.stop()

    def stop_all(self) -> None:
        for dog in self._dogs.values():
            dog.stop()
        self._dogs.clear()

    def status(self) -> dict[str, str]:
        return {udid: get_device_state(udid).value for udid in self._dogs}


# ── CLI 진입점 ────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Android 무선 ADB Watchdog')
    p.add_argument('--devices', nargs='+', required=True,
                   help='감시할 Android UDID 목록 (예: 192.168.219.114:5555)')
    p.add_argument('--interval', type=int, default=30,
                   help='연결 상태 체크 간격 (초, 기본 30)')
    p.add_argument('--keepalive', type=int, default=30,
                   help='keep-alive ping 간격 (초, 기본 30)')
    return p.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    manager = AndroidWatchdogManager(
        check_interval=args.interval,
        keepalive_interval=args.keepalive,
    )

    # SIGTERM / SIGINT 처리
    def _shutdown(signum, frame):
        _log('종료 신호 수신 → 모든 watchdog 정지 중...')
        manager.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    for udid in args.devices:
        manager.add(udid)

    _log(f'🐕 Watchdog 시작: {args.devices}')
    _log(f'   check={args.interval}s  keepalive={args.keepalive}s')
    _log('   Ctrl+C 또는 SIGTERM으로 종료')

    # 메인 스레드: 10초마다 전체 상태 출력
    try:
        while True:
            time.sleep(10)
            st = manager.status()
            icons = {
                'online': '🟢', 'offline': '🔴', 'missing': '⚫', 'unknown': '❓'
            }
            for udid, state in st.items():
                print(f'[status {_ts()}] {icons.get(state,"?")} {udid}  {state}',
                      flush=True)
    except KeyboardInterrupt:
        _shutdown(None, None)
