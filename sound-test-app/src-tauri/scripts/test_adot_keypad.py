#!/usr/bin/env python3
"""에이닷 전화 (com.skt.prod.dialer) iOS 키패드 진단 테스트.

WDA HTTP 직접 사용 — Appium 서버 불필요.
에이닷 전화 앱의 키패드 탭 이름, 숫자 버튼 AID/label을 덤프하고
실제 번호 입력이 가능한지 검증합니다.

실행:
    python test_adot_keypad.py [--wda-url http://192.168.219.119:8100] [--phone 01083330025]

결과:
  1. 현재 화면 → 키패드 탭으로 이동 시도
  2. 숫자 버튼 AID / label / 좌표 덤프
  3. 전화번호 입력 시도 → 결과 검증
  4. ios_call_handler.py 수정 권장사항 출력
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests

# ── 기본값 ─────────────────────────────────────────────────────────────────────
BUNDLE_ID = 'com.sktelecom.tphone'
WDA_URL   = 'http://192.168.219.119:8100'
TEST_PHONE = '01083330025'

# 익시오 앱 한글 키패드 (비교용)
_IXIO_KR = {
    '0': '공', '1': '일', '2': '이', '3': '삼', '4': '사',
    '5': '오', '6': '육', '7': '칠', '8': '팔', '9': '구',
    '*': '별', '#': '#',
}
_IXIO_KR_REV = {v: k for k, v in _IXIO_KR.items()}


# ══════════════════════════════════════════════════════════════════════════════
# WDA HTTP 클라이언트
# ══════════════════════════════════════════════════════════════════════════════

class WDA:
    def __init__(self, base: str):
        self.base = base.rstrip('/')
        self.sid: Optional[str] = None
        self.s = requests.Session()
        self.s.headers['Content-Type'] = 'application/json'

    # ── 세션 ──────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        r = self.s.get(f'{self.base}/status', timeout=5)
        return r.json()

    def get_or_create_session(self, bundle_id: str) -> Optional[str]:
        """기존 활성 세션이 있으면 재사용, 없으면 새로 생성."""
        # 1) 기존 세션 목록 확인
        try:
            r = self.s.get(f'{self.base}/sessions', timeout=5)
            sessions = r.json().get('value', [])
            if sessions:
                first = sessions[0]
                self.sid = (first.get('id')
                            or first.get('sessionId')
                            or first.get('value', {}).get('sessionId', ''))
                if self.sid:
                    print(f"  ♻️  기존 WDA 세션 재사용: {self.sid[:8]}…")
                    return self.sid
        except Exception:
            pass

        # 2) 새 세션 생성 (앱 실행)
        caps = {'capabilities': {'alwaysMatch': {
            'bundleId': bundle_id,
            'platformName': 'iOS',
            'shouldTerminateApp': False,
            'forceAppLaunch': False,
            'shouldWaitForQuiescence': False,
        }}}
        r = self.s.post(f'{self.base}/session', json=caps, timeout=15)
        data = r.json()
        self.sid = (data.get('sessionId')
                    or data.get('value', {}).get('sessionId', ''))
        if self.sid:
            print(f"  ✅ WDA 세션 생성: {self.sid[:8]}…")
        else:
            print(f"  ❌ 세션 생성 실패: {data}")
        return self.sid

    def activate_app(self, bundle_id: str):
        self.s.post(
            f'{self.base}/session/{self.sid}/wda/apps/activate',
            json={'bundleId': bundle_id}, timeout=10,
        )

    # ── 화면 소스 ────────────────────────────────────────────────────────────

    def page_source(self) -> str:
        r = self.s.get(f'{self.base}/session/{self.sid}/source', timeout=15)
        val = r.json().get('value', '')
        return val if val else r.text

    # ── 요소 탐색 ────────────────────────────────────────────────────────────

    def find(self, using: str, value: str) -> Optional[str]:
        try:
            r = self.s.post(
                f'{self.base}/session/{self.sid}/element',
                json={'using': using, 'value': value}, timeout=10,
            )
            if r.status_code != 200:
                return None
            v = r.json().get('value', {})
            return v.get('ELEMENT') or v.get('element-6066-11e4-a52e-4f735466cecf')
        except Exception:
            return None

    def find_aid(self, aid: str) -> Optional[str]:
        return self.find('accessibility id', aid)

    def find_xpath(self, xpath: str) -> Optional[str]:
        return self.find('xpath', xpath)

    def find_all(self, using: str, value: str) -> list[str]:
        try:
            r = self.s.post(
                f'{self.base}/session/{self.sid}/elements',
                json={'using': using, 'value': value}, timeout=10,
            )
            if r.status_code != 200:
                return []
            vals = r.json().get('value', [])
            result = []
            for v in vals:
                eid = v.get('ELEMENT') or v.get('element-6066-11e4-a52e-4f735466cecf')
                if eid:
                    result.append(eid)
            return result
        except Exception:
            return []

    # ── 액션 ─────────────────────────────────────────────────────────────────

    def click(self, elem_id: str) -> bool:
        try:
            r = self.s.post(
                f'{self.base}/session/{self.sid}/element/{elem_id}/click',
                json={}, timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    def tap(self, x: int, y: int) -> bool:
        """mobile: tap (coordinate)"""
        try:
            r = self.s.post(
                f'{self.base}/session/{self.sid}/execute/sync',
                json={'script': 'mobile: tap', 'args': [{'x': x, 'y': y}]},
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    def touch_and_hold(self, elem_id: str, duration: float = 1.5) -> bool:
        try:
            r = self.s.post(
                f'{self.base}/session/{self.sid}/wda/element/{elem_id}/touchAndHold',
                json={'duration': duration}, timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════════════════
# UI 분석 유틸
# ══════════════════════════════════════════════════════════════════════════════

def parse_xml(src: str) -> Optional[ET.Element]:
    """page_source 문자열 → XML 루트. JSON 래핑도 처리."""
    if src.strip().startswith('{'):
        try:
            src = json.loads(src).get('value', src)
        except Exception:
            pass
    try:
        return ET.fromstring(src)
    except ET.ParseError as e:
        print(f"  ⚠️ XML 파싱 실패: {e}")
        return None


def dump_all_elements(src: str, save_path: str = '/tmp/adot_ui_dump.xml') -> None:
    """page_source 전체를 파일로 저장하고 주요 요소를 출력."""
    try:
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(src)
        print(f"  💾 UI 덤프 저장: {save_path} ({len(src):,} bytes)")
    except Exception as e:
        print(f"  ⚠️ 파일 저장 실패: {e}")

    root = parse_xml(src)
    if root is None:
        return

    print(f"\n{'─'*70}")
    print(f"  [탭바 버튼 목록]")
    print(f"{'─'*70}")
    tabbar_buttons: list[dict] = []
    for elem in root.iter():
        tag = elem.tag
        # 탭바 버튼 또는 그 자식
        parent_is_tabbar = False
        # ET는 부모 참조가 없으므로 XPath로 별도 처리 불가 → iter 전체에서 tabbar 내 버튼 수집
        if 'TabBar' in tag:
            for child in elem.iter():
                if 'Button' in child.tag:
                    name  = child.get('name', '')
                    label = child.get('label', '')
                    x, y, w, h = (child.get('x'), child.get('y'),
                                  child.get('width'), child.get('height'))
                    tabbar_buttons.append({'name': name, 'label': label,
                                           'x': x, 'y': y, 'w': w, 'h': h})

    if tabbar_buttons:
        for i, b in enumerate(tabbar_buttons):
            print(f"  탭 [{i}] name={b['name']!r:20s} label={b['label']!r:20s} "
                  f"bounds=[{b['x']},{b['y']} {b['w']}x{b['h']}]")
    else:
        print(f"  탭바 버튼 없음 (또는 탭바 구조가 다름)")

    print(f"\n{'─'*70}")
    print(f"  [숫자/키패드 관련 버튼 목록]")
    print(f"{'─'*70}")
    DIGIT_NAMES = set('0123456789*#') | set(_IXIO_KR.values())
    KEYPAD_KEYWORDS = {'키패드', 'keypad', 'dialpad', '전화', '통화', '걸기', 'call', 'dial',
                       '지우기', 'delete', '발신', '공', '일', '이', '삼', '사', '오', '육',
                       '칠', '팔', '구', '별'}
    seen: list[dict] = []
    for elem in root.iter():
        name  = (elem.get('name') or '').strip()
        label = (elem.get('label') or '').strip()
        value = (elem.get('value') or '').strip()
        tag   = elem.tag
        hit = (
            name in DIGIT_NAMES
            or label in DIGIT_NAMES
            or (len(name) == 1 and name in '0123456789*#')
            or any(k in name.lower() for k in KEYPAD_KEYWORDS)
            or any(k in label.lower() for k in KEYPAD_KEYWORDS)
        )
        if hit:
            x, y, w, h = (elem.get('x'), elem.get('y'),
                          elem.get('width'), elem.get('height'))
            seen.append({'tag': tag, 'name': name, 'label': label,
                         'value': value, 'x': x, 'y': y, 'w': w, 'h': h})

    if seen:
        for e in seen:
            print(f"  {e['tag']:<35} name={e['name']!r:<20} label={e['label']!r:<20} "
                  f"value={e['value']!r:<12} [{e['x']},{e['y']} {e['w']}x{e['h']}]")
    else:
        print(f"  키패드 관련 요소 없음")


def find_digit_coords(src: str) -> dict[str, tuple[int, int]]:
    """page_source에서 숫자 버튼 중심 좌표 추출. 에이닷/익시오 모두 대응."""
    root = parse_xml(src)
    if root is None:
        return {}
    coords: dict[str, tuple[int, int]] = {}
    for elem in root.iter():
        name  = (elem.get('name') or '').strip()
        label = (elem.get('label') or '').strip()

        digit = None
        # 1) 익시오 한글 AID
        if name in _IXIO_KR_REV:
            digit = _IXIO_KR_REV[name]
        elif label in _IXIO_KR_REV:
            digit = _IXIO_KR_REV[label]
        # 2) 숫자 직접 매칭 (단일 문자)
        elif len(name) == 1 and name in '0123456789*#':
            digit = name
        elif len(label) == 1 and label in '0123456789*#':
            digit = label
        # 3) 에이닷 전화: name='1, ㄱ ㅋ...' 형태 — 숫자+쉼표로 시작
        else:
            for d in '0123456789':
                if name.startswith(d + ',') or label.startswith(d + ','):
                    digit = d
                    break

        if digit is not None and digit not in coords:
            x, y, w, h = (elem.get('x'), elem.get('y'),
                          elem.get('width'), elem.get('height'))
            if all(v for v in (x, y, w, h)):
                try:
                    cx = int(x) + int(w) // 2
                    cy = int(y) + int(h) // 2
                    coords[digit] = (cx, cy)
                except ValueError:
                    pass
    return coords


def read_dial_value(src: str) -> str:
    """다이얼 필드에서 숫자 문자열 추출.

    - 익시오/일반: value="010..." 속성
    - 에이닷 전화: name='010, 입력된 전화번호, 텍스트필드' — name 앞 부분
    """
    # 1) value 속성에 2자리 이상 숫자
    for m in re.finditer(r'\bvalue="([^"]*)"', src):
        digits = re.sub(r'\D', '', m.group(1))
        if len(digits) >= 2:
            return digits
    # 2) 에이닷 전화: name="<숫자>, 입력된 전화번호, ..."
    m = re.search(r'name="([\d\-\s]+),\s*입력된 전화번호', src)
    if m:
        return re.sub(r'\D', '', m.group(1))
    return ''


# ══════════════════════════════════════════════════════════════════════════════
# 테스트 단계
# ══════════════════════════════════════════════════════════════════════════════

SECTION = '\n' + '═'*70 + '\n'

def step_check_wda(wda: WDA) -> bool:
    print(f"{SECTION}[STEP 1] WDA 연결 확인 ({wda.base})")
    try:
        st = wda.status()
        print(f"  ✅ WDA 응답: ready={st.get('value', {}).get('ready', '?')}")
        return True
    except Exception as e:
        print(f"  ❌ WDA 연결 실패: {e}")
        return False


def step_open_app(wda: WDA, bundle_id: str) -> bool:
    print(f"{SECTION}[STEP 2] 앱 열기 ({bundle_id})")
    sid = wda.get_or_create_session(bundle_id)
    if not sid:
        return False
    wda.activate_app(bundle_id)
    time.sleep(1.5)
    print(f"  ✅ 앱 활성화 완료")
    return True


def step_dump_initial_screen(wda: WDA) -> str:
    print(f"{SECTION}[STEP 3] 초기 화면 UI 덤프")
    src = wda.page_source()
    dump_all_elements(src, '/tmp/adot_initial_screen.xml')
    return src


def step_navigate_to_keypad(wda: WDA) -> tuple[bool, str]:
    """키패드 탭으로 이동. 이동 후 화면 소스 반환."""
    print(f"{SECTION}[STEP 4] 키패드 탭 이동 시도")

    # 에이닷 전화 키패드 화면 판별: 다이얼 필드 + 통화 버튼 + 지우기 버튼
    _ADOT_KEYPAD_INDICATORS = ['통화', '입력된 전화번호 지우기', '별, 쉼표']

    def _is_keypad_screen(src: str) -> bool:
        """숫자 버튼 좌표 OR 에이닷 전화 고유 버튼으로 키패드 화면 판별."""
        if len(find_digit_coords(src)) >= 7:
            return True
        # 에이닷 전화: 숫자 버튼 AID가 달라도 통화/지우기 버튼으로 판별
        hit = sum(1 for ind in _ADOT_KEYPAD_INDICATORS if ind in src)
        return hit >= 2

    # 탭 이름 후보 (에이닷 전화 + 일반) — '연락처' 등 키패드 아닌 탭 클릭 방지
    TAB_CANDIDATES = [
        '키패드', 'Keypad', 'keypad', 'dialpad', 'DialPad', 'Dialpad',
        '다이얼', 'Dial', 'dial', '번호판', '전화걸기', 'Phone',
    ]
    XPATH_CANDIDATES = [
        '//XCUIElementTypeButton[contains(@name,"키패드") or contains(@label,"키패드")]',
        '//XCUIElementTypeButton[contains(@name,"Keypad") or contains(@label,"Keypad")]',
        '//XCUIElementTypeButton[contains(@name,"다이얼") or contains(@label,"다이얼")]',
        '//XCUIElementTypeButton[contains(@name,"Dial") or contains(@label,"Dial")]',
        # ⚠️ [1] 폴백 제거 — 첫 번째 탭이 키패드라는 보장 없음 (에이닷: 연락처가 [0])
    ]

    src_before = wda.page_source()

    # 이미 키패드 화면이면 즉시 반환
    if _is_keypad_screen(src_before):
        print(f"  ✅ 이미 키패드 화면")
        dump_all_elements(src_before, '/tmp/adot_keypad_screen.xml')
        return True, src_before

    # AID 시도 — 클릭 후 키패드 화면 여부 확인
    for aid in TAB_CANDIDATES:
        eid = wda.find_aid(aid)
        if eid:
            print(f"  🔍 AID '{aid}' 발견 → 클릭")
            wda.click(eid)
            time.sleep(1.5)
            src_after = wda.page_source()
            if _is_keypad_screen(src_after):
                print(f"  ✅ 키패드 진입 성공 (AID='{aid}')")
                dump_all_elements(src_after, '/tmp/adot_keypad_screen.xml')
                return True, src_after
            else:
                print(f"  ⚠️ '{aid}' 클릭 후 키패드 미진입")

    # XPath 시도
    for xp in XPATH_CANDIDATES:
        eid = wda.find_xpath(xp)
        if eid:
            print(f"  🔍 XPath 발견 → 클릭: {xp[:60]}…")
            wda.click(eid)
            time.sleep(1.5)
            src_after = wda.page_source()
            if _is_keypad_screen(src_after):
                print(f"  ✅ 키패드 진입 성공 (XPath)")
                dump_all_elements(src_after, '/tmp/adot_keypad_screen.xml')
                return True, src_after
            else:
                print(f"  ⚠️ XPath 클릭 후 키패드 미진입")

    # 실패 — 현재 화면 덤프
    src_fail = wda.page_source()
    dump_all_elements(src_fail, '/tmp/adot_keypad_fail.xml')
    print(f"\n  ❌ 키패드 탭 진입 실패")
    return False, src_fail


def step_analyze_keypad_buttons(src: str) -> dict[str, tuple[int, int]]:
    print(f"{SECTION}[STEP 5] 키패드 버튼 분석")
    coords = find_digit_coords(src)
    if not coords:
        print(f"  ❌ 숫자 버튼 좌표 추출 실패 (한글 AID 없음 + 숫자 AID 없음)")
        print(f"     → /tmp/adot_keypad_screen.xml 또는 /tmp/adot_keypad_fail.xml 확인 필요")
    else:
        print(f"  ✅ 감지된 버튼 ({len(coords)}개):")
        for d in sorted(coords.keys()):
            cx, cy = coords[d]
            print(f"     '{d}' → ({cx}, {cy})")

    # 버튼 AID 종류 분석 (한글 vs 숫자)
    root = parse_xml(src)
    if root:
        kr_buttons = []
        num_buttons = []
        for elem in root.iter():
            name = (elem.get('name') or '').strip()
            if name in _IXIO_KR_REV:
                kr_buttons.append(name)
            elif len(name) == 1 and name in '0123456789':
                num_buttons.append(name)
        if kr_buttons:
            print(f"\n  📋 한글 AID 버튼 발견: {kr_buttons}")
            print(f"     → 익시오 스타일 키패드 (기존 코드 동작 가능)")
        elif num_buttons:
            print(f"\n  📋 숫자 AID 버튼 발견: {sorted(set(num_buttons))}")
            print(f"     → 일반 스타일 키패드 (ios_call_handler.py 3번 폴백에서 처리 가능)")
        else:
            print(f"\n  ⚠️ 한글 AID도 숫자 AID도 없음")
            print(f"     → ios_call_handler.py의 _find_digit_btn_ios() XPath 폴백 (4번) 또는 좌표 탭 필요")

    return coords


def _build_aid_map(wda: WDA, src: str) -> dict[str, str]:
    """page_source에서 digit → full AID 문자열 맵 빌드.

    에이닷 전화: '1, ㄱ ㅋ, 닷 Q Z', '0, ㅎ, 더하기' 형식
    일반:        '1', '0' 형식
    익시오:      '일', '공' 형식 (한글 → _IXIO_KR 역맵)
    """
    import xml.etree.ElementTree as ET
    aid_map: dict[str, str] = {}
    try:
        root = ET.fromstring(src)
    except Exception:
        return aid_map
    kr_rev = {v: k for k, v in _IXIO_KR.items()}
    for elem in root.iter():
        name = (elem.get('name') or '').strip()
        if not name:
            continue
        digit = None
        if name in kr_rev:
            digit = kr_rev[name]
        elif len(name) == 1 and name in '0123456789':
            digit = name
        else:
            for d in '0123456789':
                if name.startswith(d + ','):
                    digit = d
                    break
        if digit is not None and digit not in aid_map:
            aid_map[digit] = name
    return aid_map


def step_try_dial(wda: WDA, phone: str, coords: dict[str, tuple[int, int]]) -> bool:
    print(f"{SECTION}[STEP 6] 전화번호 입력 시도: {phone}")
    if not coords:
        print(f"  ⛔ 좌표 없음 — 입력 스킵")
        return False

    # 입력 전 기존 다이얼 필드 내용 지우기
    src_before = wda.page_source()
    before_val = re.sub(r'\D', '', read_dial_value(src_before))
    if before_val:
        print(f"  🧹 잔류 번호 '{before_val}' 지우는 중…")
        _DELETE_AIDS = ['입력된 전화번호 지우기', '지우기', 'delete', 'Delete']
        del_eid = None
        for da in _DELETE_AIDS:
            del_eid = wda.find_aid(da)
            if del_eid:
                break
        if del_eid:
            for _ in range(len(before_val) + 2):
                wda.click(del_eid)
                time.sleep(0.05)
        else:
            print(f"  ⚠️ 지우기 버튼 없음 — 잔류 번호 제거 불가")

    # AID 맵 빌드 (에이닷 전화: 'digit, ...' 형식)
    src_now = wda.page_source()
    aid_map = _build_aid_map(wda, src_now)
    if aid_map:
        print(f"  📋 AID 맵 빌드 성공 ({len(aid_map)}개): " +
              ", ".join(f"'{d}'→'{v[:12]}'" for d, v in sorted(aid_map.items())))

    needed = set(re.sub(r'\D', '', phone))
    if aid_map and needed.issubset(aid_map.keys()):
        # ─── 방법 A: full AID 직접 클릭 (에이닷 전화 preferred) ───
        print(f"  → 방법 A: AID 직접 클릭")
        for ch in re.sub(r'\D', '', phone):
            aid = aid_map[ch]
            eid = wda.find_aid(aid)
            if eid:
                wda.click(eid)
            else:
                print(f"  ⚠️ '{ch}' AID element 없음")
            time.sleep(0.08)
    else:
        # ─── 방법 B: 좌표 탭 (폴백) ───
        missing = needed - set(coords.keys())
        if missing:
            print(f"  ⚠️ 좌표 없음: {sorted(missing)} → 부분 입력만 가능")
        print(f"  → 방법 B: 좌표 탭 (폴백)")
        for ch in re.sub(r'\D', '', phone):
            if ch not in coords:
                print(f"  ⚠️ '{ch}' 스킵")
                continue
            cx, cy = coords[ch]
            wda.tap(cx, cy)
            time.sleep(0.08)

    time.sleep(0.8)
    src_after = wda.page_source()
    dialed = read_dial_value(src_after)
    dialed_clean = re.sub(r'\D', '', dialed)
    phone_clean  = re.sub(r'\D', '', phone)

    print(f"\n  입력 결과:")
    print(f"    입력 시도: {phone_clean} ({len(phone_clean)}자리)")
    print(f"    화면 표시: {dialed_clean or '(감지 안 됨)'}")
    if dialed_clean == phone_clean:
        print(f"  ✅ 입력 성공!")
        return True
    elif dialed_clean:
        ok_chars = sum(1 for i, c in enumerate(dialed_clean) if i < len(phone_clean) and c == phone_clean[i])
        ratio = ok_chars / max(len(phone_clean), 1)
        print(f"  ⚠️ 부분 성공 ({ratio*100:.0f}%): {dialed_clean}")
        return False
    else:
        print(f"  ❌ 다이얼 필드 값 읽기 실패 (또는 입력 미반영)")
        return False


def step_report_fix(wda: WDA, src_keypad: str) -> None:
    """ios_call_handler.py 수정 권장사항 출력."""
    print(f"{SECTION}[STEP 7] ios_call_handler.py 수정 권장사항")
    root = parse_xml(src_keypad)
    if root is None:
        print("  XML 파싱 실패 — 권장사항 생략")
        return

    # 탭바 버튼 수집
    tab_names: list[str] = []
    for elem in root.iter():
        if 'TabBar' in elem.tag:
            for child in elem.iter():
                if 'Button' in child.tag:
                    n = child.get('name', '') or child.get('label', '')
                    if n:
                        tab_names.append(n)

    # 키패드 탭 이름 추측
    keypad_tab = None
    for n in tab_names:
        if any(k in n.lower() for k in ('키패드', 'keypad', 'dial', '번호', 'phone')):
            keypad_tab = n
            break

    # 숫자 버튼 AID 방식 확인
    has_kr   = any(e.get('name', '') in _IXIO_KR_REV for e in root.iter())
    has_num  = any(len(e.get('name', '')) == 1 and e.get('name', '') in '0123456789' for e in root.iter())

    print(f"""
  📌 분석 결과:
     • 탭바 버튼: {tab_names or '(탭바 없음 또는 감지 실패)'}
     • 키패드 탭 이름: {keypad_tab or '(자동 감지 실패 — XML 직접 확인)'}
     • 한글 AID 버튼: {'있음 (익시오 스타일)' if has_kr else '없음'}
     • 숫자 AID 버튼: {'있음 (에이닷/일반 스타일)' if has_num else '없음'}

  🔧 ios_call_handler.py 수정 포인트:
     1. _KEYPAD_TAB_IDS 에 에이닷 전화 탭 이름 추가:
        현재: {['키패드', 'Keypad', 'dialpad', 'dial_pad']}
        추가 후보: {[keypad_tab] if keypad_tab else ['확인 필요']}

     2. _is_on_keypad() — 에이닷 전화는 한글 AID 없음:
        현재: '일','이','삼' XPath 검사
        수정: 에이닷 전화는 숫자 AID '1','2','3' 로만 판정 필요
        → _KEYPAD_REQUIRED_DIGITS = ['1','2','3'] 은 OK
          _KEYPAD_REQUIRED_KR (한글) 조건을 AND 가 아닌 OR 로 처리해야 함
          (현재 코드는 OR 이므로 OK — 실제 fail 원인 재확인 필요)

     3. _build_digit_coords() — 에이닷 전화 버튼 좌표 인식:
        현재: 한글 AID (kr_to_digit) 또는 단일 숫자 name/label
        에이닷: {'숫자 AID 있음 → 3번 항목 이미 처리됨' if has_num else '숫자 AID 없음 → XPath 좌표 탐색 필요'}

     4. 에이닷 전화 전용 _KEYPAD_KR 매핑이 필요하면:
        bundle_id 별 분기 추가 권장
        예: if self._ios_bundle == 'com.sktelecom.tphone': kr_map = {{}}  # 한글 매핑 없음
""")


# ══════════════════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='에이닷 전화 iOS 키패드 진단')
    parser.add_argument('--wda-url', default=WDA_URL)
    parser.add_argument('--bundle-id', default=BUNDLE_ID)
    parser.add_argument('--phone', default=TEST_PHONE)
    parser.add_argument('--no-dial', action='store_true', help='번호 입력 시도 스킵')
    args = parser.parse_args()

    print(f"\n{'═'*70}")
    print(f"  에이닷 전화 iOS 키패드 진단 테스트")
    print(f"  WDA: {args.wda_url}  앱: {args.bundle_id}")
    print(f"{'═'*70}")

    wda = WDA(args.wda_url)

    # STEP 1: WDA 연결
    if not step_check_wda(wda):
        sys.exit(1)

    # STEP 2: 앱 열기
    if not step_open_app(wda, args.bundle_id):
        sys.exit(1)

    # STEP 3: 초기 화면 덤프
    step_dump_initial_screen(wda)

    # STEP 4: 키패드 탭 이동
    keypad_ok, src_keypad = step_navigate_to_keypad(wda)

    # STEP 5: 버튼 분석
    coords = step_analyze_keypad_buttons(src_keypad)

    # STEP 6: 번호 입력 시도
    if not args.no_dial and keypad_ok:
        step_try_dial(wda, args.phone, coords)
    else:
        print(f"\n  ⏭  번호 입력 스킵 ({'--no-dial 지정' if args.no_dial else '키패드 진입 실패'})")

    # STEP 7: 수정 권장사항
    step_report_fix(wda, src_keypad)

    print(f"\n{'═'*70}")
    print(f"  진단 완료. XML 덤프 파일:")
    print(f"    /tmp/adot_initial_screen.xml  — 초기 화면")
    print(f"    /tmp/adot_keypad_screen.xml   — 키패드 화면 (성공 시)")
    print(f"    /tmp/adot_keypad_fail.xml     — 키패드 진입 실패 시 마지막 화면")
    print(f"{'═'*70}\n")


if __name__ == '__main__':
    main()
