#!/usr/bin/env python3
"""
iOS 오디오 라우팅 동적 탐지 테스트
====================================
iPhone에서 익시오 앱이 통화 중인 상태에서
WDA /source XML을 파싱하여 라우팅 버튼 → iRig 2 HD 항목을 찾아 탭합니다.

사용법:
  # 통화 연결 후 실행
  python test_ios_audio_routing.py

  # WDA URL 직접 지정
  python test_ios_audio_routing.py --wda http://192.168.219.130:8100

  # 탭 없이 라벨 덤프만 (--dry-run)
  python test_ios_audio_routing.py --dry-run
"""

import argparse
import sys
import time
import xml.etree.ElementTree as ET

# ── WDA URL 기본값 ──────────────────────────────────────────────────────────
DEFAULT_WDA = "http://192.168.219.130:8100"
BUNDLE_ID   = "com.lguplus.aicallagent"

# ── 탐지 키워드 (force_ios_external_mic 와 동일) ────────────────────────────
AUDIO_BTN_KEYWORDS = [
    'audio', 'route', 'speaker', 'mic', 'microphone',
    'earphone', 'headset', 'irig', 'usb',
]
BTN_ELEM_TYPES = [
    'XCUIElementTypeButton',
    'XCUIElementTypeOther',
    'XCUIElementTypeImage',
]
DEVICE_KEYWORDS = [
    'irig 2 hd', 'irig hd 2', 'ik multimedia', 'irig',
    'usb audio', 'usb 오디오', 'external microphone',
    'headset', 'wired microphone',
]


def get_session(req, wda_url: str) -> str | None:
    """익시오 앱 컨텍스트로 WDA 세션 생성 (앱 재시작 없음)."""
    caps = {"capabilities": {"alwaysMatch": {
        "bundleId": BUNDLE_ID,
        "platformName": "iOS",
        "shouldTerminateApp": False,
        "forceAppLaunch": False,
        "shouldWaitForQuiescence": False,
    }}}
    try:
        r = req.post(f"{wda_url}/session", json=caps, timeout=15)
        val = r.json().get("value") or {}
        return val.get("sessionId") or r.json().get("sessionId")
    except Exception as e:
        print(f"[세션 생성 실패] {e}")
        return None


def get_source_root(req, wda_url: str, sid: str):
    """WDA /source?format=xml 응답을 ElementTree root로 반환.
    WDA는 XML을 JSON {"value": "<xml...>"} 형태로 래핑해서 반환하므로 언래핑 처리.
    """
    import json as _json
    r = req.get(f"{wda_url}/session/{sid}/source",
                params={"format": "xml"}, timeout=10)
    text = r.text
    # JSON 래핑 여부 확인 후 XML 추출
    if text.strip().startswith("{"):
        try:
            text = _json.loads(text).get("value", text)
        except Exception:
            pass
    return ET.fromstring(text)


def dump_labels(root, title="[전체 레이블]"):
    """source XML에서 모든 name/label 속성값 출력 (진단용)."""
    labels = sorted(set(
        (el.get('name') or el.get('label') or '')
        for el in root.iter()
        if (el.get('name') or el.get('label') or '').strip()
    ))
    print(f"\n{title}")
    for i, lbl in enumerate(labels, 1):
        print(f"  {i:3}. {lbl!r}")
    return labels


def find_coords(root, keywords, elem_types=None):
    """키워드로 요소를 탐색, (cx, cy, element_name) 반환."""
    kw_lower = [k.lower() for k in keywords]
    for el in root.iter():
        if elem_types and el.tag not in elem_types:
            continue
        label = (el.get('name') or el.get('label') or el.get('value') or '').lower()
        if not label:
            continue
        matched = next((k for k in kw_lower if k in label), None)
        if matched:
            x = el.get('x'); y = el.get('y')
            w = el.get('width'); h = el.get('height')
            if x and y and w and h:
                cx = int(x) + int(w) // 2
                cy = int(y) + int(h) // 2
                orig = el.get('name') or el.get('label') or ''
                return cx, cy, orig
    return None


def tap(req, wda_url: str, sid: str, x: int, y: int):
    """WDA를 통해 지정 좌표 탭."""
    return req.post(f"{wda_url}/session/{sid}/wda/tap/0",
                    json={"x": x, "y": y}, timeout=5)


def main():
    parser = argparse.ArgumentParser(description="iOS 오디오 라우팅 동적 탐지 테스트")
    parser.add_argument("--wda", default=DEFAULT_WDA, help="WDA URL")
    parser.add_argument("--dry-run", action="store_true",
                        help="탭 없이 레이블 덤프만 수행")
    args = parser.parse_args()

    try:
        import requests
    except ImportError:
        print("requests 패키지 필요: pip install requests")
        sys.exit(1)

    wda_url = args.wda.rstrip("/")
    print(f"WDA URL: {wda_url}")

    # ── WDA 헬스 체크 ──────────────────────────────────────────────────────
    print("\n[1] WDA 상태 확인...")
    try:
        r = requests.get(f"{wda_url}/status", timeout=5)
        info = r.json()
        print(f"    WDA 응답 OK → {info.get('value', {}).get('message', 'OK')}")
    except Exception as e:
        print(f"    ❌ WDA 응답 없음: {e}")
        print(f"    → iPhone이 Mac에 연결되어 있고 WDA가 실행 중인지 확인하세요")
        print(f"    → 확인 명령: curl {wda_url}/status")
        sys.exit(1)

    # ── 세션 생성 ──────────────────────────────────────────────────────────
    print("\n[2] 익시오 앱 WDA 세션 생성...")
    sid = get_session(requests, wda_url)
    if not sid:
        print("    ❌ 세션 생성 실패 — 익시오 앱이 통화 중인 상태인지 확인하세요")
        sys.exit(1)
    print(f"    ✅ 세션 ID: {sid}")

    try:
        # ── STEP 1: 현재 화면 source 덤프 ─────────────────────────────────
        print("\n[3] 현재 화면 source 덤프 (오디오 라우트 버튼 탐색)...")
        root1 = get_source_root(requests, wda_url, sid)
        all_labels = dump_labels(root1, "[현재 화면 레이블 전체]")

        result = find_coords(root1, AUDIO_BTN_KEYWORDS, BTN_ELEM_TYPES)
        if result:
            bx, by, btn_name = result
            print(f"\n    ✅ 오디오 라우트 버튼 발견!")
            print(f"       레이블: {btn_name!r}")
            print(f"       좌표:   ({bx}, {by})")
        else:
            print(f"\n    ⚠️  AUDIO_BTN_KEYWORDS로 버튼을 찾지 못했습니다")
            print(f"    → 위 레이블 목록에서 오디오 라우트 버튼 이름을 찾아")
            print(f"      AUDIO_BTN_KEYWORDS 에 추가하세요")
            if not args.dry_run:
                print("\n탭할 버튼을 찾지 못해 테스트를 중단합니다.")
                sys.exit(1)

        if args.dry_run:
            print("\n[dry-run 모드] 탭은 실행하지 않습니다.")
            sys.exit(0)

        # ── STEP 2: 오디오 라우트 버튼 탭 ─────────────────────────────────
        print(f"\n[4] 오디오 라우트 버튼 탭 → ({bx}, {by})")
        tap(requests, wda_url, sid, bx, by)
        print(f"    탭 완료 — 1초 대기...")
        time.sleep(1.0)

        # ── STEP 3: 피커 팝업 source 덤프 ─────────────────────────────────
        print("\n[5] 피커 팝업 source 덤프 (장치 항목 탐색)...")
        root2 = get_source_root(requests, wda_url, sid)
        dump_labels(root2, "[피커 팝업 레이블 전체]")

        result2 = find_coords(root2, DEVICE_KEYWORDS)
        if result2:
            dx, dy, dev_name = result2
            print(f"\n    ✅ 장치 항목 발견!")
            print(f"       레이블: {dev_name!r}")
            print(f"       좌표:   ({dx}, {dy})")

            # ── STEP 4: 장치 항목 탭 ──────────────────────────────────
            print(f"\n[6] 장치 항목 탭 → ({dx}, {dy})")
            tap(requests, wda_url, sid, dx, dy)
            time.sleep(0.5)
            print(f"    ✅ 라우팅 선택 완료!")

        else:
            print(f"\n    ⚠️  DEVICE_KEYWORDS로 장치 항목을 찾지 못했습니다")
            print(f"    → 위 레이블 목록에서 iRig/USB Audio 항목 이름을 찾아")
            print(f"      DEVICE_KEYWORDS 에 추가하세요")
            # 피커 닫기
            cancel = find_coords(root2, ['cancel', '취소', 'close'])
            if cancel:
                cx, cy, _ = cancel
                print(f"    취소 버튼 탭 → ({cx}, {cy})")
                tap(requests, wda_url, sid, cx, cy)

    finally:
        try:
            requests.delete(f"{wda_url}/session/{sid}", timeout=5)
            print(f"\n[세션 종료] {sid}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
