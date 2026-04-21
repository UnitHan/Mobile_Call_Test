#!/usr/bin/env python3
"""ixio 수신 화면 UI dump 도구.

ixio 앱에서 통화가 수신되는 순간 이 스크립트를 실행하면
현재 화면의 버튼/텍스트 좌표를 출력합니다.

사용법:
    python3 dump_ixio_ui.py [adb_serial]

예시:
    python3 dump_ixio_ui.py                       # 연결된 첫 번째 기기
    python3 dump_ixio_ui.py XXXXXXXXXXXXX         # 특정 시리얼
"""

import subprocess
import sys
import xml.etree.ElementTree as ET

def get_udid(arg=None):
    if arg:
        return arg
    result = subprocess.run(['adb', 'devices'], capture_output=True, text=True)
    for line in result.stdout.splitlines()[1:]:
        if '\tdevice' in line:
            return line.split('\t')[0]
    return None

def dump_ui(udid):
    print(f"📱 기기: {udid}")
    print("  uiautomator dump 실행 중...")
    subprocess.run(
        ['adb', '-s', udid, 'shell', 'uiautomator', 'dump', '/sdcard/ui_check.xml'],
        capture_output=True, text=True, timeout=10
    )
    result = subprocess.run(
        ['adb', '-s', udid, 'shell', 'cat', '/sdcard/ui_check.xml'],
        capture_output=True, text=True, timeout=5
    )
    xml = result.stdout.strip()
    if not xml:
        print("  ❌ UI dump 실패 (빈 결과)")
        return

    root = ET.fromstring(xml)
    print("\n  [클릭 가능한 요소 목록]")
    print(f"  {'텍스트':<30} {'content-desc':<30} {'bounds'}")
    print(f"  {'-'*80}")
    for node in root.iter():
        text = node.get('text', '').strip()
        desc = node.get('content-desc', '').strip()
        bounds = node.get('bounds', '')
        clickable = node.get('clickable', 'false')
        if (text or desc) and (clickable == 'true' or text or desc):
            label = text or desc
            print(f"  {label:<30} {desc:<30} {bounds}  clickable={clickable}")

    print("\n  [수신 관련 키워드 탐색]")
    keywords = ['받기', '응답', 'Accept', 'Answer', '수락', '전화받기', 'Receive', '거절', 'Decline', 'Reject']
    found = False
    for node in root.iter():
        node_text = (node.get('text', '') + ' ' + node.get('content-desc', '')).strip()
        for kw in keywords:
            if kw.lower() in node_text.lower():
                bounds = node.get('bounds', '')
                import re
                coords = re.findall(r'\d+', bounds)
                if len(coords) == 4:
                    cx = (int(coords[0]) + int(coords[2])) // 2
                    cy = (int(coords[1]) + int(coords[3])) // 2
                    print(f"  ✅ '{node_text}' → 중심좌표 ({cx}, {cy})  bounds={bounds}")
                    found = True
                    break
    if not found:
        print("  ⚠️ 수신/거절 관련 버튼 미발견 — ixio 수신 화면이 표시된 상태에서 실행하세요.")

if __name__ == '__main__':
    udid = get_udid(sys.argv[1] if len(sys.argv) > 1 else None)
    if not udid:
        print("❌ adb 연결된 기기가 없습니다.")
        sys.exit(1)
    dump_ui(udid)
