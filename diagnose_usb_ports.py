#!/usr/bin/env python3
"""
USB 오디오 포트 → 폰 연결 진단 스크립트
────────────────────────────────────────────────────────
각 USB 출력 장치로 순서대로 비프음을 재생합니다.
소리가 나는 폰 쪽에서 통화로 들리는지 확인하세요.

실행:
  python3 diagnose_usb_ports.py
────────────────────────────────────────────────────────
"""

import subprocess, time, sys
from pathlib import Path
import numpy as np

# .venv/bin/python (이 스크립트와 동일 venv 내 실행 중이므로 sys.executable 재사용)
VENV_PYTHON = sys.executable

def beep_script(device_index: int, freq: int = 1000, duration: float = 1.5,
                label: str = '') -> str:
    """지정 device로 비프음을 재생하는 인라인 Python 스크립트."""
    return f"""
import sounddevice as sd, numpy as np, sys
sr = 48000
t  = np.linspace(0, {duration}, int(sr * {duration}))
tone = (np.sin(2 * np.pi * {freq} * t) * 0.8).astype('float32')
stereo = np.column_stack([tone, tone])
try:
    print("▶  [{label}] device={device_index}  {freq}Hz {duration}s 재생 중...", flush=True)
    sd.play(stereo, samplerate=sr, device={device_index}, blocking=True)
    print("   완료", flush=True)
except Exception as e:
    print(f"   오류: {{e}}", flush=True)
""".replace('{label}', label)


def play_beep(device_index: int, freq: int = 1000, duration: float = 1.5, label: str = ''):
    script = beep_script(device_index, freq, duration, label)
    subprocess.run([VENV_PYTHON, '-c', script])


def get_usb_output_indices():
    """현재 연결된 USB 출력 장치 index 목록 (sounddevice 기준)."""
    import importlib, sys
    try:
        import sounddevice as sd
    except ImportError:
        return []
    return sorted([
        i for i, d in enumerate(sd.query_devices())
        if 'USB Audio' in d['name'] and d['max_output_channels'] > 0
    ])


def get_ioreg_location_ids():
    """ioreg으로 USB Audio Device locationID 순서 조회."""
    try:
        raw = subprocess.check_output(
            ['ioreg', '-r', '-c', 'IOUSBInterface', '-l'], timeout=5
        ).decode(errors='ignore')
        import re
        locs = []
        for m in re.finditer(
            r'"USB Product Name" = "USB Audio Device".*?"locationID" = (\d+)',
            raw, re.DOTALL
        ):
            lid = int(m.group(1))
            if lid not in locs:
                locs.append(lid)
        return sorted(locs)
    except Exception:
        return []


def main():
    print("=" * 58)
    print("  USB 오디오 포트 → 폰 연결 진단")
    print("=" * 58)

    usb_out = get_usb_output_indices()
    locs    = get_ioreg_location_ids()

    print(f"\n연결된 USB 출력 장치: {len(usb_out)}개")
    for order, (idx, loc) in enumerate(zip(usb_out, locs + [None] * len(usb_out)), 1):
        loc_hex = hex(loc) if loc else 'N/A'
        print(f"  [{order}] sounddevice index={idx}  locationID={loc_hex}")

    if not usb_out:
        print("❌ USB 출력 장치를 찾을 수 없습니다. USB 사운드카드를 연결하세요.")
        sys.exit(1)

    print()
    print("각 USB 장치로 순서대로 비프음을 재생합니다.")
    print("소리가 나는 폰(또는 사운드카드의 출력)을 확인하세요.")
    print()

    freq_list = [800, 1200]  # 장치 1=낮은음, 장치 2=높은음
    results = {}

    for order, idx in enumerate(usb_out, 1):
        loc = locs[order - 1] if order - 1 < len(locs) else None
        freq = freq_list[order - 1] if order - 1 < len(freq_list) else 1000 + order * 200
        loc_hex = hex(loc) if loc else 'N/A'
        print(f"─── 장치 {order} | index={idx} | locationID={loc_hex} | {freq}Hz ───")
        play_beep(idx, freq=freq, duration=1.5, label=f"USB포트{order}")
        print()
        time.sleep(0.5)

    print("=" * 58)
    print("  진단 결과 → config.py 설정 가이드")
    print("=" * 58)
    print()
    for order, (idx, loc) in enumerate(zip(usb_out, locs + [None] * len(usb_out)), 1):
        freq = freq_list[order - 1] if order - 1 < len(freq_list) else 1000 + order * 200
        loc_hex = hex(loc) if loc else 'N/A'
        print(f"  장치 {order}: index={idx}, locationID={loc} ({loc_hex}), 주파수={freq}Hz")

    print()
    print("config.py 수정 기준:")
    print("  낮은음(800Hz)이 들린 폰 쪽이 'android_a' (USB포트1)")
    print("  높은음(1200Hz)이 들린 폰 쪽이 'ios_b'     (USB포트2)")
    print()

    # SwitchAudioSource로 현재 기본 장치 표시
    try:
        cur_out = subprocess.check_output(
            ['SwitchAudioSource', '-c', '-t', 'output'], text=True
        ).strip()
        cur_in = subprocess.check_output(
            ['SwitchAudioSource', '-c', '-t', 'input'], text=True
        ).strip()
        print(f"현재 macOS 기본 출력: {cur_out}")
        print(f"현재 macOS 기본 입력: {cur_in}")
    except Exception:
        pass

    print()
    print("순서가 뒤바뀐 경우 config.py의 location_id를 swap하거나")
    print("GUI에서 출력 장치 번호를 직접 입력하세요.")


if __name__ == '__main__':
    main()
