"""
Apple 전화 앱 통화 중 스피커 버튼 롱프레스 → 오디오 라우트 피커 테스트
사용법: 수동으로 통화 중 상태를 만든 뒤 이 스크립트 실행
"""
import time
import json
import requests
import xml.etree.ElementTree as ET
import threading

WDA_URL = 'http://192.168.219.119:8100'
PLAY_TONE = True   # Mac에서 1kHz 테스트 톤 재생 여부


def wda_get(path, **kw):
    return requests.get(f'{WDA_URL}{path}', timeout=10, **kw).json()


def wda_post(path, body=None, **kw):
    return requests.post(f'{WDA_URL}{path}', json=body or {}, timeout=10, **kw).json()


def get_or_create_session():
    """기존 Apple 전화 앱 세션을 재사용하거나 새로 생성."""
    try:
        sr = requests.get(f'{WDA_URL}/sessions', timeout=5).json()
        for s in sr.get('value', []):
            sid = s.get('id') or s.get('sessionId')
            cap = s.get('capabilities') or {}
            bundle = cap.get('bundleId', '') or cap.get('CFBundleIdentifier', '')
            if sid and 'mobilephone' in bundle:
                print(f'  기존 세션 재사용: {sid}')
                return sid
    except Exception:
        pass

    caps = {'capabilities': {'alwaysMatch': {
        'bundleId': 'com.apple.mobilephone',
        'platformName': 'iOS',
        'shouldTerminateApp': False,
        'forceAppLaunch': False,
        'shouldWaitForQuiescence': False,
    }}}
    r = requests.post(f'{WDA_URL}/session', json=caps, timeout=15).json()
    val = r.get('value') or {}
    sid = val.get('sessionId') or r.get('sessionId')
    print(f'  새 세션 생성: {sid}')
    return sid


def dump_labels(src_xml):
    """XML에서 name/label 있는 요소 목록 반환."""
    try:
        root = ET.fromstring(src_xml)
        items = []
        for el in root.iter():
            name = (el.get('name') or el.get('label') or '').strip()
            if name:
                x = el.get('x', '?')
                y = el.get('y', '?')
                w = el.get('width', '?')
                h = el.get('height', '?')
                items.append((name, el.tag, int(x) if x != '?' else 0,
                              int(y) if y != '?' else 0,
                              int(w) if w != '?' else 0,
                              int(h) if h != '?' else 0))
        return items
    except Exception as e:
        print(f'  [XML 파싱 오류] {e}')
        return []


def get_source(sid):
    r = requests.get(f'{WDA_URL}/session/{sid}/source', timeout=10).json()
    return r.get('value', '')


def find_element(sid, name):
    """name 또는 label로 요소 좌표 반환."""
    src = get_source(sid)
    items = dump_labels(src)
    for label, tag, x, y, w, h in items:
        if name in label and w > 0 and h > 0:
            return x + w // 2, y + h // 2, label
    return None


def tap(sid, x, y):
    wda_post(f'/session/{sid}/execute/sync', {
        'script': 'mobile: tap',
        'args': [{'x': x, 'y': y}]
    })


def long_press(sid, x, y, duration=1.5):
    wda_post(f'/session/{sid}/execute/sync', {
        'script': 'mobile: touchAndHold',
        'args': [{'x': x, 'y': y, 'duration': duration}]
    })


def play_tone_bg():
    """백그라운드에서 1kHz 테스트 톤 재생 (5초)."""
    try:
        import numpy as np
        import sounddevice as sd
        sr = 44100
        t = np.linspace(0, 5, sr * 5, endpoint=False)
        tone = 0.3 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        sd.play(tone, sr)
        sd.wait()
    except Exception as e:
        print(f'  [톤 재생 실패] {e}')


# ─── 메인 ───────────────────────────────────────────────────────────────────

print('=' * 60)
print('Apple 전화 앱 통화 중 오디오 라우트 피커 테스트')
print('=' * 60)

sid = get_or_create_session()
if not sid:
    print('❌ WDA 세션 획득 실패')
    exit(1)

# 1. 현재 화면 상태 확인
print('\n[STEP 1] 현재 통화 화면 요소 목록')
src = get_source(sid)
items = dump_labels(src)
for name, tag, x, y, w, h in items:
    print(f'  [{tag.replace("XCUIElementType","")}] "{name}"  @({x},{y}) {w}x{h}')

# 1b. 키패드 화면이면 "통화" 탭으로 이동
labels = [name for name, *_ in items]
if '스피커' not in labels and '통화' in labels:
    print('\n  [키패드 화면 감지] → "통화" 탭 탭하여 통화 화면으로 이동')
    r = find_element(sid, '통화')
    if r:
        tap(sid, r[0], r[1])
        time.sleep(1.0)
        # 화면 갱신
        src = get_source(sid)
        items = dump_labels(src)
        print('  이동 후 요소:')
        for name, tag, x, y, w, h in items:
            print(f'    "{name}"')

# 2. '스피커' 버튼 위치 탐색
print('\n[STEP 2] 스피커 버튼 탐색')
result = find_element(sid, '스피커')
if not result:
    result = find_element(sid, 'speaker')
if not result:
    result = find_element(sid, 'audio')

if not result:
    print('  ❌ 스피커 버튼을 찾을 수 없습니다.')
    print('  현재 화면이 통화 중 상태인지 확인해주세요.')
    exit(1)

bx, by, blabel = result
print(f'  ✅ 스피커 버튼 발견: "{blabel}" @ ({bx}, {by})')

# 3. 테스트 톤 재생 시작
if PLAY_TONE:
    print('\n[STEP 3] 테스트 톤 재생 시작 (1kHz, 5초)')
    t = threading.Thread(target=play_tone_bg, daemon=True)
    t.start()
else:
    print('\n[STEP 3] 테스트 톤 재생 스킵')

time.sleep(0.5)

# 4. 스피커 단순 탭 → 현재 상태 확인
print('\n[STEP 4] 스피커 버튼 단순 탭 → 라우트 확인')
tap(sid, bx, by)
time.sleep(1.5)

src_after_tap = get_source(sid)
items_after = dump_labels(src_after_tap)
print('  탭 후 화면 요소:')
for name, tag, x, y, w, h in items_after:
    print(f'    "{name}"  @({x},{y})')

# 5. 롱프레스 → 라우트 피커 확인
print('\n[STEP 5] 스피커 버튼 롱프레스(1.5초) → 라우트 피커 오픈 시도')
# 현재 스피커 상태 재확인 (탭으로 바뀌었을 수 있으므로)
result2 = find_element(sid, '스피커')
if result2:
    bx2, by2, _ = result2
else:
    bx2, by2 = bx, by

long_press(sid, bx2, by2, duration=1.5)
time.sleep(1.0)

src_picker = get_source(sid)
items_picker = dump_labels(src_picker)
print('  롱프레스 후 화면 요소:')
for name, tag, x, y, w, h in items_picker:
    print(f'    [{tag.replace("XCUIElementType","")}] "{name}"  @({x},{y}) {w}x{h}')

# iRig / CONNECT 관련 항목 탐색
route_keywords = ['irig', 'connect', 'usb', 'external', 'headset', 'bluetooth',
                  'iphone', 'speaker', '스피커', '수화기', '헤드셋', '블루투스', '외부']
print('\n  [오디오 라우트 항목 탐색]')
found_routes = []
for name, tag, x, y, w, h in items_picker:
    nl = name.lower()
    if any(k in nl for k in route_keywords):
        print(f'    → "{name}"  @({x},{y})')
        found_routes.append((name, x + w // 2, y + h // 2))

if found_routes:
    print(f'\n  ✅ 라우트 피커 항목 {len(found_routes)}개 발견')
    print('  다음 중 iRig / CONNECT 6에 해당하는 항목을 선택하세요:')
    for i, (name, cx, cy) in enumerate(found_routes):
        print(f'    [{i}] "{name}"')

    # USB / External 항목 자동 탭
    for name, cx, cy in found_routes:
        nl = name.lower()
        if any(k in nl for k in ['usb', 'connect', 'irig', 'external']):
            print(f'\n  → "{name}" 자동 탭...')
            tap(sid, cx, cy)
            time.sleep(1.0)
            break
    else:
        print('\n  ℹ️ iRig/CONNECT 항목 없음 — 피커를 닫기 위해 뒤로가기')
        # 빈 영역 탭으로 닫기
        tap(sid, 200, 100)
else:
    print('\n  ℹ️ 라우트 피커가 열리지 않았거나 항목을 찾지 못함')
    print('  → 단순 탭만으로 스피커폰 토글되는 방식일 수 있음')

# 최종 화면 상태
print('\n[최종] 현재 화면 요소:')
src_final = get_source(sid)
for name, tag, x, y, w, h in dump_labels(src_final):
    print(f'  "{name}"')

if PLAY_TONE:
    print('\n톤 재생 완료 대기...')
    time.sleep(3)

print('\n✅ 테스트 완료')
