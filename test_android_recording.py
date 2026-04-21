#!/usr/bin/env python3
"""Android ixiO 앱 통화 녹음 파일 생성 여부 확인 테스트

사용법:
  1. Android 단말 USB 연결
  2. python3 test_android_recording.py
  3. 안내에 따라 ixiO 앱으로 통화 시작/종료
  4. 새 녹음 파일 생성 여부 + 경로 출력

자동 감시 모드:
  - 통화 종료 후 엔터 → 최대 60초간 새 파일 폴링
  - 모든 ANDROID_RECORDING_CANDIDATES + /sdcard/ 전체 탐색 병행
"""

import subprocess
import sys
import time
import os

# ─────────────────────────────────────────────────────────────────────────────
# 탐색 경로 목록 (call_audio_collector.py 와 동기화)
# ─────────────────────────────────────────────────────────────────────────────
SEARCH_PATHS = [
    '/sdcard/Recordings/ixiO/',
    '/storage/emulated/0/Recordings/ixiO/',
    '/sdcard/Recordings/Call/',
    '/storage/emulated/0/Recordings/Call/',
    '/sdcard/MIUI/sound_recorder/call_rec/',
    '/sdcard/CallRecordings/',
    '/storage/emulated/0/CallRecordings/',
    '/sdcard/PhoneRecordings/',
    '/sdcard/RecordCalls/',
    '/storage/emulated/0/Music/CallRecordings/',
]

AUDIO_EXTS = ('.m4a', '.wav', '.mp4', '.amr', '.3gp', '.aac')


def run_adb(udid: str, *args, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            ['adb', '-s', udid, *args],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception as e:
        return f'ERROR: {e}'


def pick_usb_device() -> str | None:
    """USB 유선 연결 장치를 우선 선택 (IP 연결 제외)."""
    out = subprocess.run(['adb', 'devices', '-l'], capture_output=True, text=True).stdout
    usb_devices = []
    for line in out.splitlines()[1:]:
        if not line.strip() or 'offline' in line:
            continue
        udid = line.split()[0]
        if ':' in udid:          # IP:포트 형식 → Wi-Fi 연결
            continue
        if '._adb-tls' in udid:  # mDNS 연결
            continue
        usb_devices.append(udid)
    return usb_devices[0] if usb_devices else None


def list_audio_files(udid: str, path: str) -> list[str]:
    """지정 경로의 오디오 파일 목록 반환."""
    out = run_adb(udid, 'shell', f'ls -1 "{path}" 2>/dev/null')
    if not out or 'ERROR' in out or 'No such' in out:
        return []
    return [
        f for f in out.splitlines()
        if any(f.lower().endswith(ext) for ext in AUDIO_EXTS)
    ]


def snapshot_all(udid: str) -> dict[str, set[str]]:
    """모든 탐색 경로의 현재 파일 스냅샷 반환."""
    snap: dict[str, set[str]] = {}
    for path in SEARCH_PATHS:
        files = list_audio_files(udid, path)
        snap[path] = set(files)
    return snap


def find_new_files(
    udid: str,
    before: dict[str, set[str]]
) -> list[tuple[str, str]]:
    """스냅샷 이후 새로 생긴 파일 목록 반환: [(경로, 파일명), ...]."""
    new: list[tuple[str, str]] = []
    for path in SEARCH_PATHS:
        now = set(list_audio_files(udid, path))
        before_set = before.get(path, set())
        for fname in now - before_set:
            new.append((path, fname))
    return new


def find_with_find_cmd(udid: str, since_epoch: float) -> list[str]:
    """/sdcard/ 전체를 find 로 탐색하여 since_epoch 이후 생성된 오디오 파일 반환."""
    # find 로 newer 비교 (기준 파일 생성 후 find 실행)
    # -newer 대신 mmin(-1 = 최근 1분) 사용으로 단순화
    elapsed_min = max(1, int((time.time() - since_epoch) / 60) + 1)
    out = run_adb(
        udid,
        'shell', f'find /sdcard/ -mmin -{elapsed_min} -type f 2>/dev/null',
        timeout=20,
    )
    if not out or 'ERROR' in out:
        return []
    return [
        p for p in out.splitlines()
        if any(p.lower().endswith(ext) for ext in AUDIO_EXTS)
    ]


def get_file_size_kb(udid: str, full_path: str) -> str:
    out = run_adb(udid, 'shell', f'stat -c "%s" "{full_path}" 2>/dev/null')
    try:
        return f'{int(out) // 1024}KB'
    except Exception:
        return '?KB'


def poll_for_new_files(
    udid: str,
    before: dict[str, set[str]],
    call_end_time: float,
    poll_sec: int = 60,
) -> None:
    """통화 종료 후 poll_sec 초간 새 파일 등장 감시."""
    print(f'\n⏳ 최대 {poll_sec}초간 새 녹음 파일 감시 중...')
    deadline = time.time() + poll_sec
    found: list[tuple[str, str]] = []

    while time.time() < deadline:
        # 방법 1: 경로별 스냅샷 비교
        new = find_new_files(udid, before)
        if new:
            found = new
            break

        # 방법 2: find 전체 탐색 (5초마다)
        elapsed = time.time() - call_end_time
        if elapsed >= 5 and int(elapsed) % 5 < 1:
            found_by_find = find_with_find_cmd(udid, call_end_time - 30)
            if found_by_find:
                print(f'\n  🔍 find 광역탐색 발견:')
                for p in found_by_find:
                    sz = get_file_size_kb(udid, p)
                    print(f'     {p}  ({sz})')
                print()

        remaining = int(deadline - time.time())
        print(f'  [{remaining:02d}s 남음] 파일 없음...', end='\r', flush=True)
        time.sleep(1)

    print()  # 캐리지 리턴 정리

    if found:
        print(f'\n✅ 새 녹음 파일 발견! ({len(found)}개)')
        for path, fname in found:
            full = f'{path}{fname}'
            sz = get_file_size_kb(udid, full)
            print(f'  📄 {full}  ({sz})')
    else:
        print(f'\n❌ {poll_sec}초 내 새 녹음 파일 없음')
        print('   → ixiO 앱이 통화 녹음을 저장하지 않거나, 저장 경로가 다를 수 있음')

        # 광역 탐색 마지막 시도
        print('\n  🔍 /sdcard/ 전체 광역탐색 (최근 5분)...')
        found_all = find_with_find_cmd(udid, time.time() - 300)
        if found_all:
            print(f'  최근 5분 내 생성된 오디오 파일:')
            for p in found_all:
                sz = get_file_size_kb(udid, p)
                print(f'    {p}  ({sz})')
        else:
            print('  → /sdcard/ 전체에서 최근 5분 내 오디오 파일 없음')


def main() -> None:
    print('=' * 60)
    print('Android ixiO 통화 녹음 파일 생성 확인 테스트')
    print('=' * 60)

    # 1. 장치 선택
    udid = pick_usb_device()
    if not udid:
        print('❌ USB 연결된 Android 장치 없음')
        print('   adb devices 출력:')
        os.system('adb devices -l')
        sys.exit(1)

    model = run_adb(udid, 'shell', 'getprop ro.product.model')
    print(f'✅ 장치: {udid}  ({model})')

    # 2. 앱 실행 상태 확인
    app_running = run_adb(udid, 'shell', 'pidof com.lguplus.aicallagent')
    print(f'   ixiO 앱 PID: {app_running if app_running else "(실행 안됨)"}')

    # 3. 탐색 경로 존재 여부 사전 확인
    print('\n📂 탐색 대상 경로 존재 여부:')
    existing_paths = []
    for path in SEARCH_PATHS:
        out = run_adb(udid, 'shell', f'ls "{path}" 2>/dev/null && echo OK || echo NONE')
        exists = 'OK' in out
        status = '✅' if exists else '  '
        if exists:
            files = list_audio_files(udid, path)
            print(f'  {status} {path}  ({len(files)}개 파일)')
            existing_paths.append(path)
        else:
            print(f'  {status} {path}  (없음)')

    # 4. 현재 파일 스냅샷
    print('\n📸 통화 전 파일 스냅샷 저장 중...')
    before = snapshot_all(udid)
    snap_total = sum(len(v) for v in before.values())
    print(f'   스냅샷 완료 — 전체 {snap_total}개 파일 기록됨')

    # 기존 파일 목록 출력 (탐색 경로에서 발견된 것)
    for path, files in before.items():
        if files:
            print(f'\n   [{path}] 기존 파일 ({len(files)}개):')
            for fname in sorted(files)[-5:]:  # 최신 5개만
                print(f'     {fname}')

    # 5. 사용자 안내
    print('\n' + '─' * 60)
    print('📋 테스트 절차:')
    print('   1. ixiO 앱으로 통화 시작 (발신 또는 수신)')
    print('   2. 잠시 통화 (10초 이상)')
    print('   3. 통화 종료')
    print('   4. 아래에서 엔터 입력')
    print('─' * 60)

    # 6. 통화 시작 시각 기록
    print('\n통화를 시작하면 엔터를 눌러주세요 (통화 시작 기준점 기록용)')
    input('  → ')
    call_start_time = time.time()
    print(f'  📍 통화 시작 기준점 기록: {time.strftime("%H:%M:%S")}')

    print('\n통화를 종료한 후 엔터를 눌러주세요')
    input('  → ')
    call_end_time = time.time()
    duration = call_end_time - call_start_time
    print(f'  📍 통화 종료: {time.strftime("%H:%M:%S")}  (통화 시간 약 {duration:.0f}초)')

    # 7. 파일 감시 시작
    poll_for_new_files(udid, before, call_end_time, poll_sec=60)

    # 8. 전체 ixiO 경로 현황 재출력
    print('\n' + '─' * 60)
    print('📂 테스트 후 /sdcard/Recordings/ 전체 현황:')
    out = run_adb(udid, 'shell', 'find /sdcard/Recordings/ -type f 2>/dev/null', timeout=15)
    if out and 'ERROR' not in out:
        lines = [l for l in out.splitlines() if any(l.lower().endswith(ext) for ext in AUDIO_EXTS)]
        for l in sorted(lines)[-10:]:
            sz = get_file_size_kb(udid, l)
            print(f'  {l}  ({sz})')
    else:
        print('  (조회 실패 또는 경로 없음)')


if __name__ == '__main__':
    main()
