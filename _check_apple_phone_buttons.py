"""Apple 전화 앱 키패드에서 발신 버튼 접근성 ID를 확인합니다."""
import requests
import xml.etree.ElementTree as ET

WDA_URL = 'http://192.168.219.119:8100'

# 기존 세션 정리
try:
    sr = requests.get(f'{WDA_URL}/sessions', timeout=5)
    for s in sr.json().get('value', []):
        sid = s.get('id') or s.get('sessionId')
        if sid:
            requests.delete(f'{WDA_URL}/session/{sid}', timeout=3)
except Exception:
    pass

# Apple 전화 앱 세션 시작
caps = {'capabilities': {'alwaysMatch': {
    'bundleId': 'com.apple.mobilephone',
    'platformName': 'iOS',
    'shouldTerminateApp': False,
    'forceAppLaunch': False,
    'shouldWaitForQuiescence': False,
}}}
r = requests.post(f'{WDA_URL}/session', json=caps, timeout=15)
val = r.json().get('value') or {}
sid = val.get('sessionId') or r.json().get('sessionId')
print(f'Session: {sid}')

# page_source 가져오기
src_r = requests.get(f'{WDA_URL}/session/{sid}/source', timeout=15)
src = src_r.json().get('value', '')

# 전체 page_source를 파일로 저장
with open('/tmp/apple_phone_keypad_source.xml', 'w', encoding='utf-8') as f:
    f.write(src)
print(f'page_source 저장: /tmp/apple_phone_keypad_source.xml')

# 버튼 요소 중 전화/통화/call 관련 추출
root = ET.fromstring(src)
print('\n=== 전화/통화/call 관련 요소 ===')
for el in root.iter():
    etype = el.tag
    name = el.get('name', '')
    label = el.get('label', '')
    value = el.get('value', '')
    combined = (name + label).lower()
    if any(kw in combined for kw in ['전화', '통화', 'call', 'dial', '발신', '걸기']):
        print(f'  type={etype}  name="{name}"  label="{label}"  value="{value}"')

# 모든 버튼 요소 출력
print('\n=== 모든 Button 요소 ===')
for el in root.iter():
    if 'Button' in el.tag:
        name = el.get('name', '')
        label = el.get('label', '')
        x = el.get('x', '')
        y = el.get('y', '')
        w = el.get('width', '')
        h = el.get('height', '')
        print(f'  name="{name}"  label="{label}"  pos=({x},{y},{w},{h})')

# 세션 정리
requests.delete(f'{WDA_URL}/session/{sid}', timeout=3)
print('\nDone.')
