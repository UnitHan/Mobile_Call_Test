#!/usr/bin/env python3
"""iOS 키패드 입력 방식 벤치마크 — 모든 경우의 수 비교 테스트.

사용법:
    python bench_ios_keypad.py [--wda-url URL] [--phone 01083330025] [--bundle-id BUNDLE]

WDA가 실행 중인 iPhone에 연결하여 7가지 입력 방식의 속도·정확도를 측정하고
점수표로 최적 방식을 결정합니다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import requests

# ─── 설정 ─────────────────────────────────────────────────────────────────────

WDA_URL = "http://192.168.219.119:8100"
BUNDLE_ID = "com.lguplus.aicallagent"
PHONE = "01083330025"

KEYPAD_KR = {
    "0": "공", "1": "일", "2": "이", "3": "삼", "4": "사",
    "5": "오", "6": "육", "7": "칠", "8": "팔", "9": "구",
}
KR_TO_DIGIT = {v: k for k, v in KEYPAD_KR.items()}

# ─── WDA 헬퍼 ─────────────────────────────────────────────────────────────────

class WDA:
    """WDA HTTP API 래퍼 (세션 관리 포함)."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.sid: Optional[str] = None
        self.s = requests.Session()
        self.s.headers["Content-Type"] = "application/json"

    # ── 세션 ──

    def status(self) -> dict:
        r = self.s.get(f"{self.base}/status", timeout=5)
        return r.json()

    def create_session(self, bundle_id: str) -> str:
        payload = {"capabilities": {"alwaysMatch": {"bundleId": bundle_id}}}
        r = self.s.post(f"{self.base}/session", json=payload, timeout=10)
        data = r.json()
        self.sid = data.get("sessionId") or data.get("value", {}).get("sessionId", "")
        return self.sid

    def delete_session(self):
        if self.sid:
            self.s.delete(f"{self.base}/session/{self.sid}", timeout=5)
            self.sid = None

    # ── 요소 탐색 ──

    def find_element(self, using: str, value: str) -> Optional[str]:
        """요소 ID 반환 (실패 시 None)."""
        r = self.s.post(
            f"{self.base}/session/{self.sid}/element",
            json={"using": using, "value": value},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        v = r.json().get("value", {})
        return v.get("ELEMENT") or v.get("element-6066-11e4-a52e-4f735466cecf")

    def find_by_aid(self, aid: str) -> Optional[str]:
        return self.find_element("accessibility id", aid)

    def find_by_xpath(self, xpath: str) -> Optional[str]:
        return self.find_element("xpath", xpath)

    # ── 동작 ──

    def click_element(self, elem_id: str):
        self.s.post(
            f"{self.base}/session/{self.sid}/element/{elem_id}/click",
            json={}, timeout=10,
        )

    def w3c_tap(self, x: int, y: int, duration_ms: int = 50):
        """W3C Actions API로 좌표 탭."""
        actions = [{
            "type": "pointer", "id": "finger",
            "parameters": {"pointerType": "touch"},
            "actions": [
                {"type": "pointerMove", "x": x, "y": y, "duration": 0},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": duration_ms},
                {"type": "pointerUp", "button": 0},
            ],
        }]
        self.s.post(
            f"{self.base}/session/{self.sid}/actions",
            json={"actions": actions}, timeout=10,
        )

    def w3c_multi_tap(self, coords: list[tuple[int, int]], interval_ms: int = 80):
        """W3C Actions API로 연속 좌표 탭 (1회 HTTP 호출)."""
        actions_list = []
        for i, (x, y) in enumerate(coords):
            actions_list.append({"type": "pointerMove", "x": x, "y": y, "duration": 0})
            actions_list.append({"type": "pointerDown", "button": 0})
            actions_list.append({"type": "pause", "duration": 30})
            actions_list.append({"type": "pointerUp", "button": 0})
            if i < len(coords) - 1:
                actions_list.append({"type": "pause", "duration": interval_ms})
        payload = {"actions": [{
            "type": "pointer", "id": "finger",
            "parameters": {"pointerType": "touch"},
            "actions": actions_list,
        }]}
        self.s.post(
            f"{self.base}/session/{self.sid}/actions",
            json=payload, timeout=30,
        )

    def touch_and_hold(self, elem_id: str, duration: float = 1.5):
        self.s.post(
            f"{self.base}/session/{self.sid}/wda/element/{elem_id}/touchAndHold",
            json={"duration": duration}, timeout=10,
        )

    def page_source(self) -> str:
        r = self.s.get(f"{self.base}/session/{self.sid}/source", timeout=15)
        return r.json().get("value", "")

    def activate_app(self, bundle_id: str):
        self.s.post(
            f"{self.base}/session/{self.sid}/wda/apps/activate",
            json={"bundleId": bundle_id}, timeout=10,
        )

    def mobile_scroll(self, direction: str = "down"):
        self.s.post(
            f"{self.base}/session/{self.sid}/wda/scroll",
            json={"direction": direction}, timeout=10,
        )


# ─── 좌표 추출 ────────────────────────────────────────────────────────────────

def extract_digit_coords(xml_src: str) -> dict[str, tuple[int, int]]:
    """page_source XML에서 숫자 버튼 중심 좌표 추출."""
    try:
        root = ET.fromstring(xml_src)
    except ET.ParseError:
        return {}
    coords: dict[str, tuple[int, int]] = {}
    for elem in root.iter():
        name = (elem.get("name") or elem.get("label") or "").strip()
        if not name:
            continue
        digit = KR_TO_DIGIT.get(name)
        if digit is None and len(name) == 1 and name in "0123456789":
            digit = name
        if digit is not None and digit not in coords:
            x, y, w, h = elem.get("x"), elem.get("y"), elem.get("width"), elem.get("height")
            if x and y and w and h:
                try:
                    coords[digit] = (int(x) + int(w) // 2, int(y) + int(h) // 2)
                except ValueError:
                    pass
    return coords


def extract_delete_btn(xml_src: str) -> Optional[tuple[int, int]]:
    """page_source XML에서 '지우기' 또는 'delete' 버튼 좌표 추출."""
    try:
        root = ET.fromstring(xml_src)
    except ET.ParseError:
        return None
    for elem in root.iter():
        name = (elem.get("name") or elem.get("label") or "").strip()
        if name in ("지우기", "delete", "Delete"):
            x, y, w, h = elem.get("x"), elem.get("y"), elem.get("width"), elem.get("height")
            if x and y and w and h:
                try:
                    return (int(x) + int(w) // 2, int(y) + int(h) // 2)
                except ValueError:
                    pass
    return None


# ─── 다이얼 필드 값 읽기 ──────────────────────────────────────────────────────

def read_dial_value(xml_src: str) -> str:
    """page_source에서 현재 다이얼 필드에 입력된 숫자 문자열 추출."""
    import re
    m = re.search(r'\bvalue="([\d\-\s]+)"', xml_src)
    if m:
        return re.sub(r"\D", "", m.group(1))
    return ""


# ─── 잔류 번호 삭제 ───────────────────────────────────────────────────────────

def clear_dial(wda: WDA):
    """키패드 다이얼 필드에 남은 번호를 삭제."""
    # '지우기' 버튼 롱프레스
    del_id = wda.find_by_aid("지우기")
    if del_id:
        wda.touch_and_hold(del_id, 2.0)
        time.sleep(0.3)
    # 추가 삭제 (짧은 탭 반복)
    for _ in range(15):
        del_id = wda.find_by_aid("지우기")
        if not del_id:
            break
        src = wda.page_source()
        if not read_dial_value(src):
            break
        wda.click_element(del_id)
        time.sleep(0.05)


# ─── 결과 ─────────────────────────────────────────────────────────────────────

@dataclass
class BenchResult:
    method: str
    total_time_s: float = 0.0
    per_digit_ms: float = 0.0
    digits_entered: int = 0
    digits_correct: int = 0
    accuracy_pct: float = 0.0
    score: float = 0.0
    error: str = ""
    detail_times: list[float] = field(default_factory=list)

    def calc_score(self):
        """점수 = 정확도(60%) + 속도(40%).  정확도 100% 기준 60점, 속도 점수는 가장 빠른 기준 상대 평가."""
        if self.digits_entered > 0:
            self.accuracy_pct = self.digits_correct / self.digits_entered * 100
        self.per_digit_ms = (self.total_time_s / max(self.digits_entered, 1)) * 1000


def calc_speed_scores(results: list[BenchResult]):
    """속도 점수(40점 만점) 상대 계산: 가장 빠른 방식 = 40점."""
    valid = [r for r in results if r.per_digit_ms > 0 and not r.error]
    if not valid:
        return
    fastest = min(r.per_digit_ms for r in valid)
    for r in results:
        if r.error:
            r.score = 0
            continue
        acc_score = r.accuracy_pct * 0.6  # 정확도 60점 만점
        if r.per_digit_ms > 0:
            speed_score = (fastest / r.per_digit_ms) * 40  # 속도 40점 만점
        else:
            speed_score = 0
        r.score = round(acc_score + speed_score, 1)


# ─── 벤치마크 메서드들 ────────────────────────────────────────────────────────

def bench_method1_aid_click(wda: WDA, phone: str) -> BenchResult:
    """방법 1: accessibility_id로 찾고 element.click()."""
    res = BenchResult(method="① AID + click()")
    clear_dial(wda)
    time.sleep(0.3)

    # 사전 캐싱
    digit_elems: dict[str, str] = {}
    for d in set(phone):
        kr = KEYPAD_KR.get(d, d)
        eid = wda.find_by_aid(kr)
        if not eid:
            eid = wda.find_by_aid(d)  # 숫자 폴백
        if eid:
            digit_elems[d] = eid

    t0 = time.time()
    entered = 0
    for ch in phone:
        eid = digit_elems.get(ch)
        if not eid:
            continue
        t1 = time.time()
        try:
            wda.click_element(eid)
            entered += 1
        except Exception:
            # stale → 재탐색
            kr = KEYPAD_KR.get(ch, ch)
            eid = wda.find_by_aid(kr) or wda.find_by_aid(ch)
            if eid:
                wda.click_element(eid)
                entered += 1
                digit_elems[ch] = eid
        res.detail_times.append(time.time() - t1)

    res.total_time_s = time.time() - t0
    res.digits_entered = len(phone)

    # 검증
    time.sleep(0.3)
    src = wda.page_source()
    actual = read_dial_value(src)
    res.digits_correct = sum(1 for a, b in zip(phone, actual) if a == b)
    if len(actual) != len(phone):
        res.digits_correct = min(res.digits_correct, len(actual))
    res.calc_score()
    return res


def bench_method2_xpath_click(wda: WDA, phone: str) -> BenchResult:
    """방법 2: XPath contains(한글) 찾고 click()."""
    res = BenchResult(method="② XPath + click()")
    clear_dial(wda)
    time.sleep(0.3)

    digit_elems: dict[str, str] = {}
    for d in set(phone):
        kr = KEYPAD_KR.get(d)
        if kr:
            eid = wda.find_by_xpath(f'//*[contains(@name, "{kr}")]')
            if eid:
                digit_elems[d] = eid

    t0 = time.time()
    entered = 0
    for ch in phone:
        eid = digit_elems.get(ch)
        if not eid:
            continue
        t1 = time.time()
        try:
            wda.click_element(eid)
            entered += 1
        except Exception:
            pass
        res.detail_times.append(time.time() - t1)

    res.total_time_s = time.time() - t0
    res.digits_entered = len(phone)

    time.sleep(0.3)
    src = wda.page_source()
    actual = read_dial_value(src)
    res.digits_correct = sum(1 for a, b in zip(phone, actual) if a == b)
    if len(actual) != len(phone):
        res.digits_correct = min(res.digits_correct, len(actual))
    res.calc_score()
    return res


def bench_method3_coord_w3c(wda: WDA, phone: str) -> BenchResult:
    """방법 3: page_source → 좌표 추출 → W3C Actions 개별 탭."""
    res = BenchResult(method="③ 좌표 + W3C tap (개별)")
    clear_dial(wda)
    time.sleep(0.3)

    src = wda.page_source()
    coords = extract_digit_coords(src)
    needed = set(phone)
    if not needed.issubset(coords.keys()):
        missing = needed - coords.keys()
        res.error = f"좌표 추출 실패: {missing}"
        res.digits_entered = len(phone)
        res.calc_score()
        return res

    t0 = time.time()
    entered = 0
    for ch in phone:
        cx, cy = coords[ch]
        t1 = time.time()
        try:
            wda.w3c_tap(cx, cy)
            entered += 1
        except Exception as e:
            res.error = str(e)
        res.detail_times.append(time.time() - t1)
        time.sleep(0.03)  # 최소 대기

    res.total_time_s = time.time() - t0
    res.digits_entered = len(phone)

    time.sleep(0.3)
    src = wda.page_source()
    actual = read_dial_value(src)
    res.digits_correct = sum(1 for a, b in zip(phone, actual) if a == b)
    if len(actual) != len(phone):
        res.digits_correct = min(res.digits_correct, len(actual))
    res.calc_score()
    return res


def bench_method4_coord_batch(wda: WDA, phone: str) -> BenchResult:
    """방법 4: page_source → 좌표 추출 → W3C Actions 일괄 탭 (1회 호출)."""
    res = BenchResult(method="④ 좌표 + W3C batch (1회)")
    clear_dial(wda)
    time.sleep(0.3)

    src = wda.page_source()
    coords = extract_digit_coords(src)
    needed = set(phone)
    if not needed.issubset(coords.keys()):
        missing = needed - coords.keys()
        res.error = f"좌표 추출 실패: {missing}"
        res.digits_entered = len(phone)
        res.calc_score()
        return res

    tap_coords = [coords[ch] for ch in phone]

    t0 = time.time()
    try:
        wda.w3c_multi_tap(tap_coords, interval_ms=100)
        res.digits_entered = len(phone)
    except Exception as e:
        res.error = str(e)
        res.digits_entered = len(phone)
    res.total_time_s = time.time() - t0

    time.sleep(0.5)
    src = wda.page_source()
    actual = read_dial_value(src)
    res.digits_correct = sum(1 for a, b in zip(phone, actual) if a == b)
    if len(actual) != len(phone):
        res.digits_correct = min(res.digits_correct, len(actual))
    res.calc_score()
    return res


def bench_method5_aid_w3c(wda: WDA, phone: str) -> BenchResult:
    """방법 5: AID로 좌표 얻기 → W3C tap (element 좌표 기반)."""
    res = BenchResult(method="⑤ AID좌표 → W3C tap")
    clear_dial(wda)
    time.sleep(0.3)

    # 요소 위치 일괄 수집 (rect API)
    elem_coords: dict[str, tuple[int, int]] = {}
    for d in set(phone):
        kr = KEYPAD_KR.get(d, d)
        eid = wda.find_by_aid(kr) or wda.find_by_aid(d)
        if eid:
            try:
                r = wda.s.get(f"{wda.base}/session/{wda.sid}/element/{eid}/rect", timeout=5)
                rect = r.json().get("value", {})
                cx = int(rect["x"]) + int(rect["width"]) // 2
                cy = int(rect["y"]) + int(rect["height"]) // 2
                elem_coords[d] = (cx, cy)
            except Exception:
                pass

    needed = set(phone)
    if not needed.issubset(elem_coords.keys()):
        missing = needed - elem_coords.keys()
        res.error = f"좌표 수집 실패: {missing}"
        res.digits_entered = len(phone)
        res.calc_score()
        return res

    t0 = time.time()
    entered = 0
    for ch in phone:
        cx, cy = elem_coords[ch]
        t1 = time.time()
        try:
            wda.w3c_tap(cx, cy)
            entered += 1
        except Exception:
            pass
        res.detail_times.append(time.time() - t1)
        time.sleep(0.03)

    res.total_time_s = time.time() - t0
    res.digits_entered = len(phone)

    time.sleep(0.3)
    src = wda.page_source()
    actual = read_dial_value(src)
    res.digits_correct = sum(1 for a, b in zip(phone, actual) if a == b)
    if len(actual) != len(phone):
        res.digits_correct = min(res.digits_correct, len(actual))
    res.calc_score()
    return res


def bench_method6_coord_batch_fast(wda: WDA, phone: str) -> BenchResult:
    """방법 6: 좌표 + W3C batch (간격 50ms — 최소 간격)."""
    res = BenchResult(method="⑥ 좌표 + batch 50ms")
    clear_dial(wda)
    time.sleep(0.3)

    src = wda.page_source()
    coords = extract_digit_coords(src)
    needed = set(phone)
    if not needed.issubset(coords.keys()):
        missing = needed - coords.keys()
        res.error = f"좌표 추출 실패: {missing}"
        res.digits_entered = len(phone)
        res.calc_score()
        return res

    tap_coords = [coords[ch] for ch in phone]

    t0 = time.time()
    try:
        wda.w3c_multi_tap(tap_coords, interval_ms=50)
        res.digits_entered = len(phone)
    except Exception as e:
        res.error = str(e)
        res.digits_entered = len(phone)
    res.total_time_s = time.time() - t0

    time.sleep(0.5)
    src = wda.page_source()
    actual = read_dial_value(src)
    res.digits_correct = sum(1 for a, b in zip(phone, actual) if a == b)
    if len(actual) != len(phone):
        res.digits_correct = min(res.digits_correct, len(actual))
    res.calc_score()
    return res


def bench_method7_coord_batch_200(wda: WDA, phone: str) -> BenchResult:
    """방법 7: 좌표 + W3C batch (간격 200ms — 안전 간격)."""
    res = BenchResult(method="⑦ 좌표 + batch 200ms")
    clear_dial(wda)
    time.sleep(0.3)

    src = wda.page_source()
    coords = extract_digit_coords(src)
    needed = set(phone)
    if not needed.issubset(coords.keys()):
        missing = needed - coords.keys()
        res.error = f"좌표 추출 실패: {missing}"
        res.digits_entered = len(phone)
        res.calc_score()
        return res

    tap_coords = [coords[ch] for ch in phone]

    t0 = time.time()
    try:
        wda.w3c_multi_tap(tap_coords, interval_ms=200)
        res.digits_entered = len(phone)
    except Exception as e:
        res.error = str(e)
        res.digits_entered = len(phone)
    res.total_time_s = time.time() - t0

    time.sleep(0.5)
    src = wda.page_source()
    actual = read_dial_value(src)
    res.digits_correct = sum(1 for a, b in zip(phone, actual) if a == b)
    if len(actual) != len(phone):
        res.digits_correct = min(res.digits_correct, len(actual))
    res.calc_score()
    return res


# ─── 메인 ─────────────────────────────────────────────────────────────────────

ALL_METHODS = [
    ("① AID + click()", bench_method1_aid_click),
    ("② XPath + click()", bench_method2_xpath_click),
    ("③ 좌표 + W3C 개별탭", bench_method3_coord_w3c),
    ("④ 좌표 + batch 100ms", bench_method4_coord_batch),
    ("⑤ AID좌표 → W3C tap", bench_method5_aid_w3c),
    ("⑥ 좌표 + batch 50ms", bench_method6_coord_batch_fast),
    ("⑦ 좌표 + batch 200ms", bench_method7_coord_batch_200),
]


def navigate_to_keypad(wda: WDA, bundle_id: str) -> bool:
    """앱 활성화 후 키패드 탭 진입."""
    wda.activate_app(bundle_id)
    time.sleep(1)
    # 키패드 탭 클릭 시도
    for aid in ("키패드", "Keypad", "dialpad"):
        eid = wda.find_by_aid(aid)
        if eid:
            wda.click_element(eid)
            time.sleep(0.5)
            return True
    return True  # 이미 키패드일 수 있음


def print_results(results: list[BenchResult]):
    """결과 테이블 출력."""
    calc_speed_scores(results)
    results.sort(key=lambda r: r.score, reverse=True)

    print("\n")
    print("=" * 90)
    print("                    📊 iOS 키패드 입력 벤치마크 결과")
    print("=" * 90)
    print(f"{'순위':<4} {'방법':<28} {'총시간':>7} {'자릿수':>5} {'정확도':>7} {'ms/자릿수':>9} {'점수':>6} {'비고'}")
    print("-" * 90)

    for i, r in enumerate(results, 1):
        rank = f"🥇" if i == 1 else f"🥈" if i == 2 else f"🥉" if i == 3 else f" {i}"
        err = r.error[:15] if r.error else ""
        acc = f"{r.accuracy_pct:.0f}%"
        per = f"{r.per_digit_ms:.0f}ms"
        total = f"{r.total_time_s:.2f}s"
        correct = f"{r.digits_correct}/{r.digits_entered}"
        print(f"{rank:<4} {r.method:<28} {total:>7} {correct:>5} {acc:>7} {per:>9} {r.score:>6.1f} {err}")

    if results and not results[0].error:
        print("-" * 90)
        winner = results[0]
        print(f"\n🏆 최적 방식: {winner.method}")
        print(f"   → 총 {winner.total_time_s:.2f}초, {winner.per_digit_ms:.0f}ms/자릿수, 정확도 {winner.accuracy_pct:.0f}%")
        if winner.detail_times:
            print(f"   → 자릿수별 시간: min={min(winner.detail_times)*1000:.0f}ms"
                  f"  avg={statistics.mean(winner.detail_times)*1000:.0f}ms"
                  f"  max={max(winner.detail_times)*1000:.0f}ms")
    print()


def main():
    parser = argparse.ArgumentParser(description="iOS 키패드 입력 벤치마크")
    parser.add_argument("--wda-url", default=WDA_URL)
    parser.add_argument("--phone", default=PHONE)
    parser.add_argument("--bundle-id", default=BUNDLE_ID)
    parser.add_argument("--methods", type=str, default="",
                        help="실행할 방법 번호 (예: 1,3,4). 비우면 전체")
    args = parser.parse_args()

    wda = WDA(args.wda_url)

    # ── 사전 점검 ──
    print("=" * 60)
    print("🔍 사전 점검")
    print("=" * 60)

    print(f"\n1) WDA 상태 확인... ", end="", flush=True)
    try:
        st = wda.status()
        ready = st.get("value", {}).get("ready", False)
        ver = st.get("value", {}).get("build", {}).get("version", "?")
        print(f"✅ ready={ready}, v{ver}")
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)

    print(f"2) WDA 세션 생성... ", end="", flush=True)
    try:
        sid = wda.create_session(args.bundle_id)
        print(f"✅ {sid[:12]}...")
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)

    print(f"3) 키패드 화면 진입... ", end="", flush=True)
    navigate_to_keypad(wda, args.bundle_id)
    time.sleep(1)
    print("✅")

    print(f"4) page_source 좌표 추출 테스트... ", end="", flush=True)
    t0 = time.time()
    src = wda.page_source()
    src_time = time.time() - t0
    coords = extract_digit_coords(src)
    print(f"✅ {len(coords)}개 버튼 ({src_time:.2f}s)")
    for d in sorted(coords.keys()):
        cx, cy = coords[d]
        print(f"   [{d}] → ({cx}, {cy})")

    dial_val = read_dial_value(src)
    if dial_val:
        print(f"5) ⚠️ 잔류 번호 감지: '{dial_val}' → 삭제 중...")
        clear_dial(wda)
    else:
        print(f"5) 다이얼 필드 비어있음 ✅")

    # ── 실행할 메서드 선택 ──
    if args.methods:
        selected = [int(x) for x in args.methods.split(",")]
        methods = [(name, fn) for i, (name, fn) in enumerate(ALL_METHODS, 1) if i in selected]
    else:
        methods = ALL_METHODS

    # ── 벤치마크 실행 ──
    results: list[BenchResult] = []
    total = len(methods)

    print(f"\n{'=' * 60}")
    print(f"🏁 벤치마크 시작 ({total}가지 방식, 전화번호: {args.phone})")
    print(f"{'=' * 60}")

    for i, (name, fn) in enumerate(methods, 1):
        print(f"\n[{i}/{total}] {name}...")
        try:
            r = fn(wda, args.phone)
            results.append(r)
            if r.error:
                print(f"   ⚠️ {r.error}")
            else:
                print(f"   ✅ {r.total_time_s:.2f}s | {r.digits_correct}/{r.digits_entered} 정확"
                      f" | {r.per_digit_ms:.0f}ms/digit")
        except Exception as e:
            err_r = BenchResult(method=name, error=str(e), digits_entered=len(args.phone))
            err_r.calc_score()
            results.append(err_r)
            print(f"   ❌ {e}")

        # 방법 간 쿨다운 — 앱 상태 안정화
        time.sleep(1)

    # ── 결과 출력 ──
    print_results(results)

    # ── 세션 정리 ──
    wda.delete_session()
    print("🧹 WDA 세션 정리 완료\n")


if __name__ == "__main__":
    main()
