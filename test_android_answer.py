#!/usr/bin/env python3
"""Android 16 Samsung 수신 수락 진단 스크립트.

사용법:
  1. 다른 전화기에서 이 Android로 전화를 걸어 벨소리가 울리게 합니다.
  2. 벨소리가 울리는 동안 이 스크립트를 실행합니다:
     python3 test_android_answer.py
  3. 결과를 확인하여 어떤 수신/RINGING 감지 방법과 수락 전략이 동작하는지 봅니다.
"""
import subprocess
import time
import re
import sys

UDID = "192.168.219.105:5555"

def adb(cmd_args: list[str], timeout=5) -> tuple[str, str, int]:
    r = subprocess.run(
        ['adb', '-s', UDID, 'shell'] + cmd_args,
        capture_output=True, text=True, timeout=timeout
    )
    return r.stdout.strip(), r.stderr.strip(), r.returncode

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ── 0. 디바이스 확인 ──────────────────────────────────────────
section("0. 디바이스 정보")
model, _, _ = adb(['getprop', 'ro.product.model'])
sdk, _, _ = adb(['getprop', 'ro.build.version.sdk'])
rel, _, _ = adb(['getprop', 'ro.build.version.release'])
print(f"  모델: {model}")
print(f"  Android {rel} (API {sdk})")

# ── 1. RINGING 감지 방법 테스트 ──────────────────────────────
section("1. RINGING 감지 방법 테스트")

# 방법 1: gsm.call.state
v1, _, _ = adb(['getprop', 'gsm.call.state'])
print(f"  ① gsm.call.state       = '{v1}'  {'✅ RINGING' if v1 == 'RINGING' else ('⚠️ empty' if not v1 else v1)}")

# 방법 2: ril.call.state
v2, _, _ = adb(['getprop', 'ril.call.state'])
print(f"  ② ril.call.state       = '{v2}'  {'✅ RINGING' if v2 == 'RINGING' else ('⚠️ empty' if not v2 else v2)}")

# 방법 3: telephony.registry mCallState
out3, _, _ = adb(['dumpsys', 'telephony.registry'])
m3 = re.search(r'mCallState=(\d+)', out3)
cs = m3.group(1) if m3 else '?'
print(f"  ③ mCallState            = {cs}  {'✅ RINGING (1)' if cs == '1' else ('IDLE (0)' if cs == '0' else cs)}")

# 방법 4: telecom state
out4, _, _ = adb(['dumpsys', 'telecom'])
m4 = re.search(r'(?:mState|state):\s*(RINGING|ACTIVE|DIALING|IDLE)', out4)
tc_state = m4.group(1) if m4 else 'not found'
print(f"  ④ dumpsys telecom state = {tc_state}  {'✅ RINGING' if tc_state == 'RINGING' else tc_state}")

# 방법 5: dumpsys telecom 전체에서 "RINGING" 관련 문맥
ringing_lines = [line.strip() for line in out4.splitlines() if 'RINGING' in line and not line.strip().startswith('//')]
if ringing_lines:
    print(f"  ⑤ telecom RINGING 관련 라인 ({len(ringing_lines)}개):")
    for l in ringing_lines[:5]:
        print(f"     {l[:120]}")
else:
    print(f"  ⑤ telecom에서 RINGING 관련 라인 없음")

# 방법 6: dumpsys phone (삼성 전용)
out6, _, _ = adb(['dumpsys', 'phone'])
m6 = re.search(r'mState=(RINGING|OFFHOOK|IDLE)', out6)
phone_state = m6.group(1) if m6 else 'not found'
print(f"  ⑥ dumpsys phone mState = {phone_state}  {'✅ RINGING' if phone_state == 'RINGING' else phone_state}")

# 방법 7: call_state event log
out7, _, _ = adb(['logcat', '-d', '-b', 'events', '-t', '30', '-s', 'call_state'])
if 'RINGING' in out7 or 'ringing' in out7:
    print(f"  ⑦ event log call_state = ✅ RINGING 감지됨")
else:
    print(f"  ⑦ event log call_state = RINGING 미감지")

# 방법 8: 포그라운드 Activity 확인 (ixio incomingcall)
out8, _, _ = adb(['dumpsys', 'activity', 'top'])
has_incall = 'com.samsung.android.incallui' in out8 or 'com.android.incallui' in out8
has_ixio_incoming = 'com.lguplus.incomingcall' in out8
has_ixio_agent = 'com.lguplus.aicallagent' in out8
print(f"  ⑧ 포그라운드 Activity:")
print(f"     Samsung InCallUI: {'✅ 있음' if has_incall else '없음'}")
print(f"     ixio incomingcall: {'✅ 있음' if has_ixio_incoming else '없음'}")
print(f"     ixio aicallagent: {'✅ 있음' if has_ixio_agent else '없음'}")

# ── 판정 ──────────────────────────────────────────────────────
is_ringing = any([
    v1 == 'RINGING', v2 == 'RINGING', cs == '1',
    tc_state == 'RINGING', phone_state == 'RINGING',
    has_incall, has_ixio_incoming
])

section("2. 판정")
if is_ringing:
    print("  📞 현재 수신 중 (RINGING) — 수신 수락 전략 테스트를 진행합니다.\n")
else:
    print("  ❌ 현재 수신 중이 아닙니다.")
    print("     → 다른 전화기에서 이 Android로 전화를 건 후 다시 실행하세요.")
    print("     (벨소리가 울리는 동안 실행해야 합니다)")
    sys.exit(0)

# ── 3. 수신 수락 전략 테스트 ──────────────────────────────────
section("3. 수신 수락 전략 테스트 (순차 시도)")

def check_offhook():
    """OFFHOOK/ACTIVE 상태 확인"""
    try:
        v, _, _ = adb(['getprop', 'gsm.call.state'])
        if v == 'OFFHOOK': return True
    except: pass
    try:
        v, _, _ = adb(['getprop', 'ril.call.state'])
        if v == 'OFFHOOK': return True
    except: pass
    try:
        out, _, _ = adb(['dumpsys', 'telephony.registry'])
        if 'mCallState=2' in out: return True
    except: pass
    try:
        out, _, _ = adb(['dumpsys', 'telecom'])
        if re.search(r'(?:mState|state):\s*(?:ACTIVE|DIALING)', out):
            return True
    except: pass
    return False

strategies = [
    ("① telecom accept-ringing-call", ['telecom', 'accept-ringing-call']),
    ("② cmd telecom accept-ringing-call", ['cmd', 'telecom', 'accept-ringing-call']),
    ("③ keyevent KEYCODE_ANSWER (164)", ['input', 'keyevent', '164']),
    ("④ keyevent KEYCODE_CALL (5)", ['input', 'keyevent', '5']),
    ("⑤ keyevent KEYCODE_HEADSETHOOK (79)", ['input', 'keyevent', '79']),
    ("⑥ keyevent KEYCODE_MEDIA_PLAY_PAUSE (85)", ['input', 'keyevent', '85']),
    ("⑦ am broadcast ANSWER", ['am', 'broadcast', '-a', 'android.intent.action.ANSWER']),
    ("⑧ service call telecom 5 i32 0", ['service', 'call', 'telecom', '5', 'i32', '0']),
]

for name, cmd in strategies:
    try:
        out, err, rc = adb(cmd)
        print(f"  {name}")
        print(f"     rc={rc} out='{out[:80]}' err='{err[:80]}'")
        # 각 전략 후 잠깐 대기 → OFFHOOK 확인
        time.sleep(0.5)
        if check_offhook():
            print(f"     ✅ 성공! OFFHOOK 확인됨 — 통화 연결됨")
            print(f"\n  🎉 이 전략을 사용하면 됩니다: {name}")
            break
        else:
            print(f"     ❌ OFFHOOK 미확인 — 다음 전략 시도")
    except Exception as e:
        print(f"  {name}")
        print(f"     ❌ 예외: {e}")

else:
    print(f"\n  ❌ 모든 전략 실패 — Appium UI 터치 방식이 필요할 수 있습니다.")

print()
