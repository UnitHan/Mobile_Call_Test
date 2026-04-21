#!/usr/bin/env python3
"""iOS 키패드 입력 — 장기 안정성 벤치마크.

4가지 조합을 N 라운드 반복하며 시간 경과별 성능 변화를 추적합니다:
  A) AID + click  / 세션 재사용
  B) AID + click  / 세션 매번 재생성
  C) XPath + click / 세션 재사용
  D) XPath + click / 세션 매번 재생성

각 라운드마다:
  - 전화번호 11자리 입력 → 정확도 검증 → 잔류번호 삭제
  - 응답 시간, 정확도, 에러 기록
  - 10라운드마다 중간 리포트 출력

사용법:
    python bench_stability.py [--rounds 50] [--wda-url URL] [--phone 01083330025]

50라운드 × 4방식 = 200회 입력 (약 20~30분 소요)
"""
from __future__ import annotations

import argparse
import json
import re
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

# ─── WDA HTTP 클라이언트 ──────────────────────────────────────────────────────

class WDA:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.sid: Optional[str] = None
        self.s = requests.Session()
        self.s.headers["Content-Type"] = "application/json"

    def status(self) -> dict:
        return self.s.get(f"{self.base}/status", timeout=5).json()

    def create_session(self, bundle_id: str) -> str:
        payload = {"capabilities": {"alwaysMatch": {"bundleId": bundle_id}}}
        r = self.s.post(f"{self.base}/session", json=payload, timeout=10)
        data = r.json()
        self.sid = data.get("sessionId") or data.get("value", {}).get("sessionId", "")
        return self.sid

    def delete_session(self):
        if self.sid:
            try:
                self.s.delete(f"{self.base}/session/{self.sid}", timeout=5)
            except Exception:
                pass
            self.sid = None

    def find_by_aid(self, aid: str) -> Optional[str]:
        try:
            r = self.s.post(
                f"{self.base}/session/{self.sid}/element",
                json={"using": "accessibility id", "value": aid}, timeout=10,
            )
            if r.status_code != 200:
                return None
            v = r.json().get("value", {})
            return v.get("ELEMENT") or v.get("element-6066-11e4-a52e-4f735466cecf")
        except Exception:
            return None

    def find_by_xpath(self, xpath: str) -> Optional[str]:
        try:
            r = self.s.post(
                f"{self.base}/session/{self.sid}/element",
                json={"using": "xpath", "value": xpath}, timeout=10,
            )
            if r.status_code != 200:
                return None
            v = r.json().get("value", {})
            return v.get("ELEMENT") or v.get("element-6066-11e4-a52e-4f735466cecf")
        except Exception:
            return None

    def click_element(self, elem_id: str) -> float:
        """클릭 후 소요 시간(초) 반환."""
        t0 = time.time()
        self.s.post(
            f"{self.base}/session/{self.sid}/element/{elem_id}/click",
            json={}, timeout=10,
        )
        return time.time() - t0

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

    def session_valid(self) -> bool:
        """현재 세션이 유효한지 확인."""
        if not self.sid:
            return False
        try:
            r = self.s.get(f"{self.base}/session/{self.sid}", timeout=5)
            return r.status_code == 200
        except Exception:
            return False


# ─── 유틸 ─────────────────────────────────────────────────────────────────────

def read_dial_value(xml_src: str) -> str:
    m = re.search(r'\bvalue="([\d\-\s]+)"', xml_src)
    return re.sub(r"\D", "", m.group(1)) if m else ""


def clear_dial(wda: WDA):
    del_id = wda.find_by_aid("지우기")
    if del_id:
        wda.touch_and_hold(del_id, 2.0)
        time.sleep(0.3)
    for _ in range(15):
        del_id = wda.find_by_aid("지우기")
        if not del_id:
            break
        try:
            src = wda.page_source()
            if not read_dial_value(src):
                break
        except Exception:
            pass
        wda.click_element(del_id)
        time.sleep(0.05)


def navigate_to_keypad(wda: WDA, bundle_id: str):
    wda.activate_app(bundle_id)
    time.sleep(0.5)
    for aid in ("키패드", "Keypad", "dialpad"):
        eid = wda.find_by_aid(aid)
        if eid:
            wda.click_element(eid)
            time.sleep(0.3)
            return


# ─── 라운드 결과 ──────────────────────────────────────────────────────────────

@dataclass
class RoundResult:
    round_num: int
    method: str            # "AID" | "XPath"
    session_mode: str      # "reuse" | "recreate"
    input_time_s: float = 0.0
    per_digit_ms: float = 0.0
    digits_correct: int = 0
    digits_total: int = 0
    accuracy_pct: float = 0.0
    find_times: list[float] = field(default_factory=list)  # 요소 탐색 시간
    click_times: list[float] = field(default_factory=list)  # 클릭 시간
    error: str = ""
    session_create_ms: float = 0.0  # 세션 생성 시간
    timestamp: float = 0.0


# ─── 입력 엔진 ────────────────────────────────────────────────────────────────

def input_phone_aid(wda: WDA, phone: str) -> tuple[float, list[float], list[float], int]:
    """AID 방식으로 전화번호 입력. (총시간, find_times, click_times, miss_count) 반환."""
    find_times: list[float] = []
    click_times: list[float] = []
    miss = 0

    # 사전 캐싱
    digit_elems: dict[str, str] = {}
    for d in set(phone):
        kr = KEYPAD_KR.get(d, d)
        t0 = time.time()
        eid = wda.find_by_aid(kr)
        if not eid:
            eid = wda.find_by_aid(d)
        find_times.append(time.time() - t0)
        if eid:
            digit_elems[d] = eid

    t_start = time.time()
    for ch in phone:
        eid = digit_elems.get(ch)
        if not eid:
            miss += 1
            continue
        try:
            ct = wda.click_element(eid)
            click_times.append(ct)
        except Exception:
            # stale → 재탐색
            kr = KEYPAD_KR.get(ch, ch)
            eid = wda.find_by_aid(kr) or wda.find_by_aid(ch)
            if eid:
                ct = wda.click_element(eid)
                click_times.append(ct)
                digit_elems[ch] = eid
            else:
                miss += 1

    total = time.time() - t_start
    return total, find_times, click_times, miss


def input_phone_xpath(wda: WDA, phone: str) -> tuple[float, list[float], list[float], int]:
    """XPath 방식으로 전화번호 입력."""
    find_times: list[float] = []
    click_times: list[float] = []
    miss = 0

    digit_elems: dict[str, str] = {}
    for d in set(phone):
        kr = KEYPAD_KR.get(d)
        if not kr:
            continue
        t0 = time.time()
        eid = wda.find_by_xpath(f'//*[contains(@name, "{kr}")]')
        find_times.append(time.time() - t0)
        if eid:
            digit_elems[d] = eid

    t_start = time.time()
    for ch in phone:
        eid = digit_elems.get(ch)
        if not eid:
            miss += 1
            continue
        try:
            ct = wda.click_element(eid)
            click_times.append(ct)
        except Exception:
            kr = KEYPAD_KR.get(ch)
            if kr:
                eid = wda.find_by_xpath(f'//*[contains(@name, "{kr}")]')
                if eid:
                    ct = wda.click_element(eid)
                    click_times.append(ct)
                    digit_elems[ch] = eid
                else:
                    miss += 1
            else:
                miss += 1

    total = time.time() - t_start
    return total, find_times, click_times, miss


# ─── 테스트 실행기 ────────────────────────────────────────────────────────────

def run_round(
    wda: WDA,
    round_num: int,
    method: str,
    session_mode: str,
    phone: str,
    bundle_id: str,
) -> RoundResult:
    """1라운드 실행: 세션 준비 → 키패드 진입 → 입력 → 검증 → 삭제."""
    res = RoundResult(
        round_num=round_num, method=method,
        session_mode=session_mode, digits_total=len(phone),
        timestamp=time.time(),
    )

    try:
        # ── 세션 처리 ──
        if session_mode == "recreate":
            wda.delete_session()
            t0 = time.time()
            wda.create_session(bundle_id)
            res.session_create_ms = (time.time() - t0) * 1000
        else:
            # reuse: 세션 유효성 확인 → 무효 시 재생성
            if not wda.session_valid():
                t0 = time.time()
                wda.create_session(bundle_id)
                res.session_create_ms = (time.time() - t0) * 1000

        # ── 키패드 진입 + 잔류 삭제 ──
        navigate_to_keypad(wda, bundle_id)
        clear_dial(wda)
        time.sleep(0.2)

        # ── 입력 ──
        if method == "AID":
            total, find_t, click_t, miss = input_phone_aid(wda, phone)
        else:
            total, find_t, click_t, miss = input_phone_xpath(wda, phone)

        res.input_time_s = total
        res.per_digit_ms = (total / len(phone)) * 1000
        res.find_times = find_t
        res.click_times = click_t

        # ── 정확도 검증 ──
        time.sleep(0.3)
        src = wda.page_source()
        actual = read_dial_value(src)
        res.digits_correct = sum(1 for a, b in zip(phone, actual) if a == b)
        if len(actual) != len(phone):
            res.digits_correct = min(res.digits_correct, len(actual))
        res.accuracy_pct = res.digits_correct / res.digits_total * 100

        # ── 잔류 삭제 ──
        clear_dial(wda)

    except Exception as e:
        res.error = str(e)[:100]

    return res


# ─── 분석 및 리포트 ───────────────────────────────────────────────────────────

@dataclass
class GroupStats:
    label: str
    count: int = 0
    errors: int = 0
    accuracy_mean: float = 0.0
    accuracy_min: float = 0.0
    input_time_mean: float = 0.0
    input_time_p95: float = 0.0
    find_mean_ms: float = 0.0
    click_mean_ms: float = 0.0
    session_create_mean_ms: float = 0.0
    # 퇴화 지표: 후반 10라운드 vs 전반 10라운드 시간 증가율
    degradation_pct: float = 0.0
    score: float = 0.0


def analyze_group(label: str, results: list[RoundResult]) -> GroupStats:
    gs = GroupStats(label=label, count=len(results))
    if not results:
        return gs

    valid = [r for r in results if not r.error]
    gs.errors = len(results) - len(valid)

    if valid:
        accs = [r.accuracy_pct for r in valid]
        gs.accuracy_mean = statistics.mean(accs)
        gs.accuracy_min = min(accs)

        times = [r.input_time_s for r in valid]
        gs.input_time_mean = statistics.mean(times)
        gs.input_time_p95 = sorted(times)[int(len(times) * 0.95)] if len(times) >= 5 else max(times)

        all_finds = [t for r in valid for t in r.find_times]
        all_clicks = [t for r in valid for t in r.click_times]
        if all_finds:
            gs.find_mean_ms = statistics.mean(all_finds) * 1000
        if all_clicks:
            gs.click_mean_ms = statistics.mean(all_clicks) * 1000

        creates = [r.session_create_ms for r in valid if r.session_create_ms > 0]
        if creates:
            gs.session_create_mean_ms = statistics.mean(creates)

        # 퇴화율: 후반 절반 vs 전반 절반
        half = max(len(valid) // 2, 1)
        first_half = [r.input_time_s for r in valid[:half]]
        second_half = [r.input_time_s for r in valid[half:]]
        if first_half and second_half:
            f_avg = statistics.mean(first_half)
            s_avg = statistics.mean(second_half)
            if f_avg > 0:
                gs.degradation_pct = ((s_avg - f_avg) / f_avg) * 100

    return gs


def calc_group_scores(groups: list[GroupStats]):
    """종합 점수: 정확도(35) + 안정성(25) + 속도(20) + 퇴화율(20)."""
    valid = [g for g in groups if g.count > 0]
    if not valid:
        return

    fastest = min(g.input_time_mean for g in valid) if valid else 1
    for g in valid:
        # 정확도 (35점): 평균 정확도 기반
        acc_score = (g.accuracy_mean / 100) * 35

        # 안정성 (25점): 에러 0 = 25점, 에러율에 비례하여 감점
        err_rate = g.errors / max(g.count, 1)
        stability_score = max(0, 25 * (1 - err_rate * 5))  # 에러 20% 이상이면 0점

        # 속도 (20점): 가장 빠른 대비 상대
        if g.input_time_mean > 0:
            speed_score = (fastest / g.input_time_mean) * 20
        else:
            speed_score = 0

        # 퇴화율 (20점): 0%=20점, 50% 이상 증가=0점
        deg = abs(g.degradation_pct)
        degrade_score = max(0, 20 * (1 - deg / 50))

        g.score = round(acc_score + stability_score + speed_score + degrade_score, 1)


def print_progress(round_num: int, total: int, res: RoundResult):
    tag = f"[{res.method}/{res.session_mode}]"
    if res.error:
        print(f"  R{round_num:>3}/{total} {tag:<22} ❌ {res.error[:60]}")
    else:
        acc = f"{res.digits_correct}/{res.digits_total}"
        print(f"  R{round_num:>3}/{total} {tag:<22} {res.input_time_s:>5.2f}s  {acc}  "
              f"find:{statistics.mean(res.find_times)*1000:>5.0f}ms  "
              f"click:{statistics.mean(res.click_times)*1000 if res.click_times else 0:>5.0f}ms"
              f"{'  ⚡sess:'+str(int(res.session_create_ms))+'ms' if res.session_create_ms > 0 else ''}")


def print_interim(groups: dict[str, list[RoundResult]], round_done: int):
    print(f"\n  ── 중간 리포트 (R{round_done} 완료) ─────────────────")
    for key in sorted(groups.keys()):
        results = groups[key]
        valid = [r for r in results if not r.error]
        if not valid:
            print(f"  {key:<22} 데이터 없음")
            continue
        avg_t = statistics.mean([r.input_time_s for r in valid])
        avg_acc = statistics.mean([r.accuracy_pct for r in valid])
        errs = len(results) - len(valid)
        print(f"  {key:<22} avg:{avg_t:>5.2f}s  acc:{avg_acc:>5.1f}%  err:{errs}")
    print()


def print_final_report(groups: dict[str, list[RoundResult]]):
    stats: list[GroupStats] = []
    for key in sorted(groups.keys()):
        gs = analyze_group(key, groups[key])
        stats.append(gs)

    calc_group_scores(stats)
    stats.sort(key=lambda g: g.score, reverse=True)

    print("\n")
    print("=" * 100)
    print("              📊 iOS 키패드 입력 — 장기 안정성 벤치마크 최종 결과")
    print("=" * 100)

    print(f"\n{'순위':<4} {'조합':<24} {'라운드':>6} {'에러':>4} {'정확도':>8} {'평균':>7}"
          f" {'P95':>7} {'탐색':>7} {'클릭':>7} {'퇴화율':>7} {'세션':>8} {'점수':>6}")
    print("-" * 100)

    for i, g in enumerate(stats, 1):
        rank = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f" {i}"
        deg = f"{g.degradation_pct:+.1f}%"
        sess = f"{g.session_create_mean_ms:.0f}ms" if g.session_create_mean_ms > 0 else "—"
        print(f"{rank:<4} {g.label:<24} {g.count:>6} {g.errors:>4} "
              f"{g.accuracy_mean:>6.1f}%  {g.input_time_mean:>5.2f}s  "
              f"{g.input_time_p95:>5.2f}s  {g.find_mean_ms:>5.0f}ms {g.click_mean_ms:>5.0f}ms "
              f"{deg:>7}  {sess:>7}  {g.score:>5.1f}")

    print("-" * 100)

    # ── 상세 분석 ──
    print("\n📋 채점 기준:")
    print("   정확도(35점) + 안정성·에러율(25점) + 속도(20점) + 퇴화율(20점) = 100점")
    print("   퇴화율: 후반 절반 평균시간이 전반 대비 얼마나 증가했는지 (%)")

    if stats:
        winner = stats[0]
        print(f"\n🏆 최적 조합: {winner.label}")
        print(f"   점수 {winner.score}/100 | 정확도 {winner.accuracy_mean:.1f}%"
              f" | 퇴화율 {winner.degradation_pct:+.1f}%"
              f" | 에러 {winner.errors}회")

        # ── 세션 전략 결론 ──
        reuse_stats = [g for g in stats if "reuse" in g.label]
        recreate_stats = [g for g in stats if "recreate" in g.label]
        if reuse_stats and recreate_stats:
            reuse_avg = statistics.mean([g.score for g in reuse_stats])
            recreate_avg = statistics.mean([g.score for g in recreate_stats])
            print(f"\n📌 세션 전략 비교:")
            print(f"   재사용 평균 점수: {reuse_avg:.1f}")
            print(f"   매번재생성 평균 점수: {recreate_avg:.1f}")
            if reuse_avg > recreate_avg + 2:
                print(f"   → ✅ 세션 재사용이 {reuse_avg - recreate_avg:.1f}점 우세")
            elif recreate_avg > reuse_avg + 2:
                print(f"   → ✅ 세션 매번 재생성이 {recreate_avg - reuse_avg:.1f}점 우세")
            else:
                print(f"   → ⚖️ 실질적 차이 없음 (±2점 이내)")

        # ── 탐색 방식 결론 ──
        aid_stats = [g for g in stats if "AID" in g.label]
        xpath_stats = [g for g in stats if "XPath" in g.label]
        if aid_stats and xpath_stats:
            aid_avg = statistics.mean([g.score for g in aid_stats])
            xpath_avg = statistics.mean([g.score for g in xpath_stats])
            aid_deg = statistics.mean([g.degradation_pct for g in aid_stats])
            xpath_deg = statistics.mean([g.degradation_pct for g in xpath_stats])
            print(f"\n📌 탐색 방식 비교:")
            print(f"   AID   평균 점수: {aid_avg:.1f}  퇴화율: {aid_deg:+.1f}%")
            print(f"   XPath 평균 점수: {xpath_avg:.1f}  퇴화율: {xpath_deg:+.1f}%")
            if aid_avg > xpath_avg + 2:
                print(f"   → ✅ AID가 {aid_avg - xpath_avg:.1f}점 우세")
            elif xpath_avg > aid_avg + 2:
                print(f"   → ✅ XPath가 {xpath_avg - aid_avg:.1f}점 우세")
            else:
                print(f"   → ⚖️ 실질적 차이 없음 (±2점 이내)")

    print()


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="iOS 키패드 장기 안정성 벤치마크")
    parser.add_argument("--rounds", type=int, default=30,
                        help="각 조합당 반복 횟수 (기본 30)")
    parser.add_argument("--wda-url", default=WDA_URL)
    parser.add_argument("--phone", default=PHONE)
    parser.add_argument("--bundle-id", default=BUNDLE_ID)
    parser.add_argument("--skip", type=str, default="",
                        help="건너뛸 조합 (예: C,D)")
    args = parser.parse_args()

    # ── 조합 정의 ──
    combos = {
        "A: AID/reuse":      ("AID",   "reuse"),
        "B: AID/recreate":   ("AID",   "recreate"),
        "C: XPath/reuse":    ("XPath", "reuse"),
        "D: XPath/recreate": ("XPath", "recreate"),
    }
    if args.skip:
        skip = {s.strip().upper() for s in args.skip.split(",")}
        combos = {k: v for k, v in combos.items() if k[0] not in skip}

    # WDA × 세션 모드별 인스턴스
    # 재사용 모드는 세션을 유지, 재생성 모드는 매 라운드마다 새로 만듦
    wda_instances: dict[str, WDA] = {}
    for key, (method, session_mode) in combos.items():
        w = WDA(args.wda_url)
        wda_instances[key] = w

    # ── 사전 점검 ──
    print("=" * 70)
    print("🔍 사전 점검")
    print("=" * 70)

    w0 = WDA(args.wda_url)
    print(f"  WDA 상태... ", end="", flush=True)
    st = w0.status()
    ver = st.get("value", {}).get("build", {}).get("version", "?")
    print(f"✅ v{ver}")

    print(f"  네트워크 지연... ", end="", flush=True)
    t0 = time.time()
    w0.status()
    latency = (time.time() - t0) * 1000
    print(f"✅ {latency:.0f}ms")

    # 각 조합 초기 세션 준비
    for key, w in wda_instances.items():
        w.create_session(args.bundle_id)

    # ── 교차 실행 (라운드별로 모든 조합 순서대로) ──
    groups: dict[str, list[RoundResult]] = {k: [] for k in combos}
    combo_keys = list(combos.keys())
    total_rounds = args.rounds
    total_ops = total_rounds * len(combo_keys)

    print(f"\n{'=' * 70}")
    print(f"🏁 벤치마크 시작")
    print(f"   조합: {len(combo_keys)}개  |  라운드: {total_rounds}  |  총 {total_ops}회 입력")
    print(f"   예상 소요: ~{total_ops * 7 // 60}분")
    print(f"{'=' * 70}\n")

    for rnd in range(1, total_rounds + 1):
        for key in combo_keys:
            method, session_mode = combos[key]
            w = wda_instances[key]

            res = run_round(w, rnd, method, session_mode, args.phone, args.bundle_id)
            groups[key].append(res)
            print_progress(rnd, total_rounds, res)

        # 중간 리포트 (10라운드마다)
        if rnd % 10 == 0:
            print_interim(groups, rnd)

    # ── 최종 결과 ──
    print_final_report(groups)

    # ── 세션 정리 ──
    for w in wda_instances.values():
        w.delete_session()
    print("🧹 모든 WDA 세션 정리 완료\n")

    # ── JSON 저장 ──
    output_path = f"/Users/qabulls/Documents/sound/bench_stability_{int(time.time())}.json"
    export = {}
    for key, results in groups.items():
        export[key] = [{
            "round": r.round_num, "method": r.method, "session_mode": r.session_mode,
            "input_time_s": round(r.input_time_s, 3), "per_digit_ms": round(r.per_digit_ms, 1),
            "digits_correct": r.digits_correct, "accuracy_pct": round(r.accuracy_pct, 1),
            "find_mean_ms": round(statistics.mean(r.find_times) * 1000, 1) if r.find_times else 0,
            "click_mean_ms": round(statistics.mean(r.click_times) * 1000, 1) if r.click_times else 0,
            "session_create_ms": round(r.session_create_ms, 1),
            "error": r.error,
        } for r in results]
    with open(output_path, "w") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    print(f"📄 상세 결과 저장: {output_path}\n")


if __name__ == "__main__":
    main()
