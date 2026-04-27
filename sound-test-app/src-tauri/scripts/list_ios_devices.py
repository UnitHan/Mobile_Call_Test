"""
list_ios_devices.py
──────────────────────────────────────────────────────────────────────────────
xcrun devicectl JSON을 파싱해 연결된 iOS 기기를 stdout으로 출력합니다.
device_cmd.rs의 list_ios_devices() 에서 호출됩니다.

출력 형식 (한 줄 = 한 기기):
    {udid}|{표시 이름}

사용법:
    python list_ios_devices.py <devicectl_json_path>
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed


def _get_local_ip(hostnames: list[str]) -> str:
    """`.coredevice.local` 호스트명에서 LAN IP를 dns-sd로 조회합니다."""
    candidates = []
    for h in hostnames:
        if h.endswith('.coredevice.local'):
            base = h[: -len('.coredevice.local')]
            candidates.append(base + '.local')

    for h in candidates:
        try:
            r = subprocess.run(
                ['dns-sd', '-G', 'v4', h],
                capture_output=True,
                timeout=3,
            )
            out = (r.stdout or b'').decode(errors='ignore')
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b'').decode(errors='ignore')
        except Exception:
            continue

        for m in re.finditer(r'(\d+\.\d+\.\d+\.\d+)', out):
            ip = m.group(1)
            parts = ip.split('.')
            if (
                ip.startswith('192.168.')
                or ip.startswith('10.')
                or (ip.startswith('172.') and 16 <= int(parts[1]) <= 31)
            ):
                return ip
    return ''


def _process_device(dev: dict) -> tuple[str, str] | None:
    """단일 기기를 처리해 (udid, label) 반환. 유효하지 않으면 None."""
    conn      = dev.get('connectionProperties', {})
    udid      = dev.get('hardwareProperties', {}).get('udid', '')
    name      = dev.get('deviceProperties', {}).get('name', 'iPhone')
    transport = conn.get('transportType', '')
    hostnames = conn.get('localHostnames', conn.get('potentialHostnames', []))
    if not udid:
        return None

    if transport == 'localNetwork':
        ip = _get_local_ip(hostnames)
        label = f'{name} ({ip})' if ip else f'{name} (무선)'
    elif transport == 'wired':
        label = f'{name} (유선)'
    else:
        label = name

    return udid, label


def parse_devicectl_json(json_path: str) -> None:
    """devicectl JSON을 파싱해 `{udid}|{label}` 형식으로 stdout에 출력합니다."""
    try:
        with open(json_path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'ERR:{e}', file=sys.stderr)
        return

    devs = data.get('result', {}).get('devices', [])
    # dns-sd 조회를 병렬 실행해 전체 대기 시간을 줄입니다 (기기 수 × 3초 → 3초)
    results: dict[int, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=len(devs) or 1) as pool:
        futures = {pool.submit(_process_device, dev): i for i, dev in enumerate(devs)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                result = fut.result()
                if result:
                    results[idx] = result
            except Exception:
                pass
    # 원래 순서대로 출력
    for idx in sorted(results):
        udid, label = results[idx]
        print(f'{udid}|{label}', flush=True)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('사용법: python list_ios_devices.py <devicectl_json_path>', file=sys.stderr)
        sys.exit(1)
    parse_devicectl_json(sys.argv[1])
