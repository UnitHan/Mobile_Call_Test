#!/usr/bin/env python3
"""WDA page source에서 키패드 버튼 accessibility ID 덤프."""
import json
import subprocess
import xml.etree.ElementTree as ET
import requests

# iPhone IP — 여러 방법 시도
ip = None

# 방법1: devicectl JSON
try:
    r = subprocess.run(
        ['xcrun', 'devicectl', 'list', 'devices', '--json-output', '/dev/stdout'],
        capture_output=True, text=True, timeout=10
    )
    if r.stdout.strip():
        data = json.loads(r.stdout)
        devices = data.get('result', {}).get('devices', [])
        for d in devices:
            cp = d.get('connectionProperties', {})
            if cp.get('tunnelIPAddress'):
                ip = cp['tunnelIPAddress']
                break
except Exception as e:
    print(f'devicectl JSON 실패: {e}')

# 방법2: 하드코딩된 IP
if not ip:
    ip = '192.168.219.100'
    print(f'devicectl 실패 → 하드코딩 IP 사용: {ip}')

print(f'iPhone IP: {ip}')
wda_url = f'http://{ip}:8100'

# WDA 상태 확인
try:
    status = requests.get(f'{wda_url}/status', timeout=5)
    print(f'WDA status: {status.status_code}')
except Exception as e:
    print(f'WDA 연결 실패: {e}')
    raise SystemExit(1)

# page source
resp = requests.get(f'{wda_url}/source?format=xml', timeout=15)
content = resp.text

# JSON 래핑일 수 있음
if content.strip().startswith('{'):
    data = json.loads(content)
    xml_str = data.get('value', content)
else:
    xml_str = content

root = ET.fromstring(xml_str)

# 전체 저장
with open('/tmp/ios_keypad_source.xml', 'w') as f:
    f.write(resp.text)
print('Full source saved to /tmp/ios_keypad_source.xml')

# 키패드 관련 요소 필터링
MATCH = set('0123456789*#')
MATCH_NAMES = {'키패드', '전화걸기', '지우기', '통화', '발신',
               '공','일','이','삼','사','오','육','칠','팔','구',
               'Keypad', 'Call', 'Delete'}

print('\n=== keypad-related elements ===')
for elem in root.iter():
    name = elem.get('name', '')
    label = elem.get('label', '')
    value = elem.get('value', '')
    etype = elem.tag
    if name in MATCH or name in MATCH_NAMES or label in MATCH or \
       any(k in name for k in ('키패드','전화','지우')):
        x = elem.get('x', '?')
        y = elem.get('y', '?')
        w = elem.get('width', '?')
        h = elem.get('height', '?')
        print(f'  {etype:30s}  name="{name:12s}"  label="{label:12s}"  value="{value}"  [{x},{y} {w}x{h}]')

# 다이얼 필드 후보 (TextField/StaticText with value containing digits)
print('\n=== dial field candidates (value with digits) ===')
import re
for elem in root.iter():
    value = elem.get('value', '')
    if re.search(r'\d{2,}', value):
        name = elem.get('name', '')
        etype = elem.tag
        x = elem.get('x', '?')
        y = elem.get('y', '?')
        w = elem.get('width', '?')
        h = elem.get('height', '?')
        print(f'  {etype:30s}  name="{name}"  value="{value}"  [{x},{y} {w}x{h}]')
