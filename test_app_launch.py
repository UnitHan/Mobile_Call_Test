#!/usr/bin/env python3
"""
앱 실행 테스트 — 삼성 전화 / 에이닷 전화 / Apple 전화 앱이
Appium/ADB를 통해 정상 실행되는지 확인하는 스크립트.

사용법:
  python test_app_launch.py

각 앱별로:
  1. ADB monkey로 앱 실행 시도 (Android)
  2. Appium caps 자동 탐지 (activity 미지정) 가능 여부 확인
  3. 결과 요약 출력
"""

import subprocess
import sys
import time

# ── 테스트 대상 앱 목록 ──────────────────────────────────────────────────
ANDROID_APPS = [
    {
        'name': '익시오 (LG U+)',
        'package': 'com.lguplus.aicallagent',
        'activity': '.MainActivity',  # 명시
    },
    {
        'name': '삼성 전화',
        'package': 'com.samsung.android.dialer',
        'activity': '',  # 자동 탐지
    },
    {
        'name': '에이닷 전화 (SKT)',
        'package': 'com.skt.prod.dialer',
        'activity': '',  # 자동 탐지
    },
]

IOS_APPS = [
    {
        'name': '익시오 (LG U+)',
        'bundle_id': 'com.lguplus.aicallagent',
    },
    {
        'name': 'Apple 전화',
        'bundle_id': 'com.apple.mobilephone',
    },
    {
        'name': '에이닷 전화 (SKT)',
        'bundle_id': 'com.sktelecom.tphone',
    },
]

# ── 디바이스 정보 ─────────────────────────────────────────────────────────
ANDROID_UDID = '192.168.219.125:5555'
IOS_UDID = '00008150-00110C341E38401C'


def run_cmd(cmd, timeout=10):
    """커맨드 실행 후 (returncode, stdout, stderr) 반환."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, '', 'TIMEOUT'
    except Exception as e:
        return -1, '', str(e)


def check_android_connected():
    """ADB에 Android 디바이스가 연결되어 있는지 확인."""
    rc, out, _ = run_cmd(['adb', 'devices'])
    if ANDROID_UDID in out and 'device' in out:
        return True
    # Wi-Fi 재연결 시도
    run_cmd(['adb', 'connect', ANDROID_UDID], timeout=5)
    time.sleep(1)
    rc, out, _ = run_cmd(['adb', 'devices'])
    return ANDROID_UDID in out and 'device' in out


def check_ios_connected():
    """iOS 디바이스가 연결되어 있는지 확인 (WDA 응답 기준)."""
    import urllib.request
    try:
        with urllib.request.urlopen('http://192.168.219.119:8100/status', timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Android 테스트
# ═══════════════════════════════════════════════════════════════════════════

def resolve_android_activity(package):
    """Android 앱의 launcher activity 조회."""
    rc, out, _ = run_cmd([
        'adb', '-s', ANDROID_UDID, 'shell',
        'cmd', 'package', 'resolve-activity', '--brief', package
    ])
    if rc == 0:
        for line in out.splitlines():
            if package in line and '/' in line:
                return line.strip().split('/')[-1]
    return None


def test_android_app_launch(app):
    """Android 앱 실행 테스트 (ADB monkey → force-stop)."""
    name = app['name']
    pkg = app['package']
    activity = app.get('activity', '')

    print(f"\n  🤖 [{name}] package={pkg}")

    # 1) 앱 설치 확인
    rc, out, _ = run_cmd([
        'adb', '-s', ANDROID_UDID, 'shell',
        'pm', 'list', 'packages', pkg
    ])
    if pkg not in out:
        print(f"     ❌ 앱 미설치")
        return False, '미설치'

    # 2) Launcher activity 조회
    resolved = resolve_android_activity(pkg)
    print(f"     📋 Launcher activity: {resolved or '(조회 실패)'}")
    if activity:
        print(f"     📋 설정된 activity: {activity}")

    # 3) force-stop
    run_cmd(['adb', '-s', ANDROID_UDID, 'shell', 'am', 'force-stop', pkg])
    time.sleep(0.5)

    # 4) monkey로 앱 실행
    rc, out, err = run_cmd([
        'adb', '-s', ANDROID_UDID, 'shell',
        'monkey', '-p', pkg, '-c', 'android.intent.category.LAUNCHER', '1'
    ])
    if rc != 0:
        print(f"     ❌ monkey 실행 실패: {err}")
        return False, 'monkey 실패'

    time.sleep(2)

    # 5) 앱이 포그라운드에 있는지 확인
    rc, out, _ = run_cmd([
        'adb', '-s', ANDROID_UDID, 'shell',
        'dumpsys', 'activity', 'activities'
    ], timeout=8)

    if pkg in out:
        # 실제 실행 중인 activity 추출
        import re
        m = re.search(rf'{pkg}/([^\s}}]+)', out)
        running_activity = m.group(1) if m else '?'
        print(f"     ✅ 앱 실행 성공 (activity={running_activity})")

        # Appium caps 호환성 체크
        if activity:
            if activity == running_activity or activity.lstrip('.') in running_activity:
                print(f"     ✅ Appium activity 매칭 OK")
            else:
                print(f"     ⚠️  Appium activity 불일치: 설정={activity}, 실제={running_activity}")
        else:
            print(f"     ℹ️  activity 미지정 → Appium 자동 탐지 모드 (resolved={resolved})")

        # 정리
        run_cmd(['adb', '-s', ANDROID_UDID, 'shell', 'am', 'force-stop', pkg])
        return True, running_activity
    else:
        print(f"     ❌ 앱이 포그라운드에 없음")
        run_cmd(['adb', '-s', ANDROID_UDID, 'shell', 'am', 'force-stop', pkg])
        return False, '포그라운드 아님'


# ═══════════════════════════════════════════════════════════════════════════
# iOS 테스트
# ═══════════════════════════════════════════════════════════════════════════

def test_ios_app_launch(app):
    """iOS 앱 실행 테스트 (WDA 세션 생성 → terminate → 정리)."""
    import urllib.request
    import json

    name = app['bundle_id']
    bundle_id = app['bundle_id']
    display_name = app['name']
    wda_url = 'http://192.168.219.119:8100'

    print(f"\n  🍎 [{display_name}] bundleId={bundle_id}")

    # 1) WDA 세션 생성 (빈 capabilities)
    session_id = None
    try:
        payload = json.dumps({
            'capabilities': {
                'alwaysMatch': {
                    'bundleId': bundle_id
                }
            }
        }).encode()
        req = urllib.request.Request(
            f'{wda_url}/session',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
            session_id = resp.get('sessionId') or resp.get('value', {}).get('sessionId')
            if session_id:
                print(f"     ✅ WDA 세션 생성 OK (sessionId={session_id[:8]}...)")
            else:
                print(f"     ✅ 세션 응답 수신 (sessionId 미포함)")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='ignore')[:200]
        # 세션 생성 실패해도 앱 활성화 시도
        print(f"     ⚠️  세션 생성 HTTP {e.code} — 앱 활성화 직접 시도")
    except Exception as e:
        print(f"     ⚠️  세션 생성 실패: {e} — 앱 활성화 직접 시도")

    # 2) 앱 활성화 (세션 있으면 사용, 없으면 기존 세션에서 시도)
    if not session_id:
        # 기존 세션 재사용
        try:
            with urllib.request.urlopen(f'{wda_url}/status', timeout=3) as r:
                data = json.loads(r.read())
                session_id = data.get('sessionId')
        except Exception:
            pass

    if session_id:
        try:
            payload = json.dumps({'bundleId': bundle_id}).encode()
            req = urllib.request.Request(
                f'{wda_url}/session/{session_id}/wda/apps/activate',
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                print(f"     ✅ 앱 활성화 성공")
                time.sleep(1)

                # 정리: 앱 종료
                try:
                    term_payload = json.dumps({'bundleId': bundle_id}).encode()
                    term_req = urllib.request.Request(
                        f'{wda_url}/session/{session_id}/wda/apps/terminate',
                        data=term_payload,
                        headers={'Content-Type': 'application/json'},
                        method='POST'
                    )
                    urllib.request.urlopen(term_req, timeout=5)
                except Exception:
                    pass

                return True, 'OK'
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors='ignore')[:200]
            print(f"     ❌ 앱 활성화 실패: HTTP {e.code}: {body}")
            return False, f'HTTP {e.code}'
        except Exception as e:
            print(f"     ❌ 앱 활성화 실패: {e}")
            return False, str(e)
    else:
        print(f"     ❌ WDA 세션 없음 — 테스트 불가")
        return False, '세션 없음'


# ═══════════════════════════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🧪 앱 실행 테스트")
    print("=" * 60)

    results = []

    # ── Android 테스트 ──
    print(f"\n{'─'*60}")
    print(f"📱 Android 테스트 (UDID: {ANDROID_UDID})")
    print(f"{'─'*60}")

    if check_android_connected():
        print("  ✅ Android 디바이스 연결됨")
        for app in ANDROID_APPS:
            ok, detail = test_android_app_launch(app)
            results.append(('Android', app['name'], ok, detail))
    else:
        print("  ❌ Android 디바이스 미연결 — 스킵")
        for app in ANDROID_APPS:
            results.append(('Android', app['name'], False, '디바이스 미연결'))

    # ── iOS 테스트 ──
    print(f"\n{'─'*60}")
    print(f"📱 iOS 테스트 (UDID: {IOS_UDID})")
    print(f"{'─'*60}")

    if check_ios_connected():
        print("  ✅ iOS 디바이스 연결됨")
        for app in IOS_APPS:
            ok, detail = test_ios_app_launch(app)
            results.append(('iOS', app['name'], ok, detail))
    else:
        print("  ❌ iOS 디바이스 미연결 — 스킵")
        for app in IOS_APPS:
            results.append(('iOS', app['name'], False, '디바이스 미연결'))

    # ── 결과 요약 ──
    print(f"\n{'='*60}")
    print(f"📊 결과 요약")
    print(f"{'='*60}")
    print(f"{'플랫폼':<10} {'앱':<20} {'결과':<6} {'상세'}")
    print(f"{'─'*60}")
    for platform, name, ok, detail in results:
        mark = '✅' if ok else '❌'
        print(f"{platform:<10} {name:<20} {mark:<6} {detail}")
    print(f"{'='*60}")

    passed = sum(1 for _, _, ok, _ in results if ok)
    total = len(results)
    print(f"\n총 {total}건 중 {passed}건 성공, {total - passed}건 실패")

    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
