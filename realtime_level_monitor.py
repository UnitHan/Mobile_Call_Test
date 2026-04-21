#!/usr/bin/env python3
"""
CONNECT 6 실시간 레벨 모니터 + 튜닝 도우미
═══════════════════════════════════════════════════════════════
두 채널(iPhone ch1, Android ch2)의 실시간 RMS/Peak를 비교하며
하드웨어 게인을 조정하여 양쪽 레벨을 맞추는 작업용 스크립트.

목표: 양쪽 RMS가 서로 ±2dB 이내 + RMS -25~-15 dBFS 범위 도달
     → 자동 "튜닝 완료" 판정 후 종료

사용법:
  1. 양쪽 폰에서 동일한 유튜브 영상 재생
  2. python3 realtime_level_monitor.py 실행
  3. iRig 게인 다이얼 / CONNECT 6 Input Gain / 폰 볼륨 조절
  4. 양쪽 레벨이 맞으면 자동으로 종료됨 (또는 Ctrl+C)
"""

import sys
import time
import signal
import threading
from collections import deque

import numpy as np
import sounddevice as sd

# ─────────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────────
SAMPLE_RATE = 48000
BLOCK_SIZE = 4800          # 100ms 블록
HISTORY_SEC = 3            # 3초 평균으로 안정적 판정
UPDATE_INTERVAL = 0.15     # 화면 갱신 주기 (초)

# 채널 설정 (0-based) — 2대 구성: 두 대 모두 Mobile In 사용
CH_IOS = 4                 # Mobile In L ch5 (0-based: 4) = iPhone USB  (CONNECT 6 #2)
CH_ANDROID = 4             # Mobile In L ch5 (0-based: 4) = Android USB (CONNECT 6 #1)

# 튜닝 목표
TARGET_RMS_MIN = -25.0     # dBFS
TARGET_RMS_MAX = -15.0     # dBFS
BALANCE_THRESHOLD = 2.0    # 양쪽 RMS 차이 허용범위 (dB)
STABLE_SECONDS = 5         # 이 시간 동안 연속 "OK" → 튜닝 완료

# ─────────────────────────────────────────────────────────────────────────────
# CONNECT 6 장치 찾기
# ─────────────────────────────────────────────────────────────────────────────
def find_connect6():
    for i, d in enumerate(sd.query_devices()):
        if 'CONNECT 6' in d.get('name', '') and d['max_input_channels'] > 0:
            return i, d
    return None, None

dev_idx, dev_info = find_connect6()
if dev_idx is None:
    print("❌ CONNECT 6 장치를 찾을 수 없습니다.")
    sys.exit(1)

n_ch = dev_info['max_input_channels']
open_ch = min(18, n_ch)

# ─────────────────────────────────────────────────────────────────────────────
# 공유 상태
# ─────────────────────────────────────────────────────────────────────────────
history_len = int(HISTORY_SEC / (BLOCK_SIZE / SAMPLE_RATE))
ios_rms_history = deque(maxlen=history_len)
and_rms_history = deque(maxlen=history_len)
ios_peak_history = deque(maxlen=history_len)
and_peak_history = deque(maxlen=history_len)

# 현재 블록 값 (실시간 표시용)
current = {
    'ios_rms': -100.0, 'ios_peak': -100.0,
    'and_rms': -100.0, 'and_peak': -100.0,
    'ios_rms_avg': -100.0, 'and_rms_avg': -100.0,
}
lock = threading.Lock()
running = True
stable_start = 0.0

def _db(val):
    return 20 * np.log10(val + 1e-10)

# ─────────────────────────────────────────────────────────────────────────────
# 콜백
# ─────────────────────────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    global stable_start
    if status:
        pass  # 오버런 등 무시

    ios_data = indata[:, CH_IOS]
    and_data = indata[:, CH_ANDROID]

    ios_rms = np.sqrt(np.mean(ios_data ** 2))
    and_rms = np.sqrt(np.mean(and_data ** 2))
    ios_peak = np.max(np.abs(ios_data))
    and_peak = np.max(np.abs(and_data))

    with lock:
        ios_rms_history.append(ios_rms)
        and_rms_history.append(and_rms)
        ios_peak_history.append(ios_peak)
        and_peak_history.append(and_peak)

        current['ios_rms'] = _db(ios_rms)
        current['ios_peak'] = _db(ios_peak)
        current['and_rms'] = _db(and_rms)
        current['and_peak'] = _db(and_peak)

        if len(ios_rms_history) > 2:
            current['ios_rms_avg'] = _db(np.mean(list(ios_rms_history)))
            current['and_rms_avg'] = _db(np.mean(list(and_rms_history)))

# ─────────────────────────────────────────────────────────────────────────────
# 레벨 바 생성
# ─────────────────────────────────────────────────────────────────────────────
def level_bar(db_val, width=40, min_db=-60, max_db=0):
    """dBFS 값을 시각적 바로 변환."""
    if db_val <= min_db:
        filled = 0
    elif db_val >= max_db:
        filled = width
    else:
        filled = int((db_val - min_db) / (max_db - min_db) * width)

    bar = ''
    for i in range(width):
        db_at = min_db + (max_db - min_db) * i / width
        if i < filled:
            if db_at > -3:
                bar += '🔴'
            elif db_at > -10:
                bar += '🟡'
            elif db_at > -25:
                bar += '🟢'
            else:
                bar += '🔵'
        else:
            bar += '⬜'
    return bar

def level_bar_compact(db_val, width=30, min_db=-60, max_db=0):
    """간결한 ASCII 레벨 바."""
    if db_val <= min_db:
        filled = 0
    elif db_val >= max_db:
        filled = width
    else:
        filled = int((db_val - min_db) / (max_db - min_db) * width)

    bar = ''
    for i in range(width):
        db_at = min_db + (max_db - min_db) * i / width
        if i < filled:
            if db_at > -3:
                bar += '█'  # 클리핑 위험
            elif db_at > -15:
                bar += '▓'  # 높음
            elif db_at > -25:
                bar += '▒'  # 목표 범위
            else:
                bar += '░'  # 낮음
        else:
            bar += '·'
    return bar

# ─────────────────────────────────────────────────────────────────────────────
# 화면 출력 루프
# ─────────────────────────────────────────────────────────────────────────────
def display_loop():
    global running, stable_start

    print("\033[2J\033[H", end='')  # 화면 클리어
    print("═" * 72)
    print("  🎛️  CONNECT 6 실시간 레벨 모니터 — 튜닝 도우미")
    print("═" * 72)
    print(f"  ch{CH_IOS+1} = iPhone (Mobile In)  |  ch{CH_ANDROID+1} = Android (Input 1)")
    print(f"  목표: RMS {TARGET_RMS_MIN}~{TARGET_RMS_MAX} dBFS | 양쪽 차이 < {BALANCE_THRESHOLD} dB")
    print(f"  {STABLE_SECONDS}초 연속 OK → 자동 종료  |  Ctrl+C = 수동 종료")
    print("─" * 72)

    header_lines = 7
    stable_start = 0.0

    while running:
        time.sleep(UPDATE_INTERVAL)

        with lock:
            ios_rms = current['ios_rms']
            ios_peak = current['ios_peak']
            and_rms = current['and_rms']
            and_peak = current['and_peak']
            ios_avg = current['ios_rms_avg']
            and_avg = current['and_rms_avg']

        diff = abs(ios_avg - and_avg)

        # 판정
        ios_in_range = TARGET_RMS_MIN <= ios_avg <= TARGET_RMS_MAX
        and_in_range = TARGET_RMS_MIN <= and_avg <= TARGET_RMS_MAX
        balanced = diff <= BALANCE_THRESHOLD
        all_ok = ios_in_range and and_in_range and balanced

        # 안정 시간 추적
        now = time.time()
        if all_ok:
            if stable_start == 0.0:
                stable_start = now
            stable_elapsed = now - stable_start
        else:
            stable_start = 0.0
            stable_elapsed = 0.0

        # iOS 판정 메시지
        if ios_avg < -60:
            ios_hint = '❌ 무신호 — iRig 연결·폰 재생 확인'
        elif ios_avg < TARGET_RMS_MIN:
            ios_hint = f'⬆️  게인 올리세요 ({TARGET_RMS_MIN-ios_avg:+.1f}dB 부족)'
        elif ios_avg > TARGET_RMS_MAX:
            ios_hint = f'⬇️  게인 낮추세요 ({ios_avg-TARGET_RMS_MAX:+.1f}dB 초과)'
        else:
            ios_hint = '✅ 범위 OK'

        # Android 판정 메시지
        if and_avg < -60:
            and_hint = '❌ 무신호 — iRig 연결·폰 재생 확인'
        elif and_avg < TARGET_RMS_MIN:
            and_hint = f'⬆️  게인 올리세요 ({TARGET_RMS_MIN-and_avg:+.1f}dB 부족)'
        elif and_avg > TARGET_RMS_MAX:
            and_hint = f'⬇️  게인 낮추세요 ({and_avg-TARGET_RMS_MAX:+.1f}dB 초과)'
        else:
            and_hint = '✅ 범위 OK'

        # 밸런스
        if diff > BALANCE_THRESHOLD and ios_avg > -60 and and_avg > -60:
            if ios_avg > and_avg:
                bal_hint = f'⚖️  iPhone이 {diff:.1f}dB 큼 → iPhone↓ 또는 Android↑'
            else:
                bal_hint = f'⚖️  Android가 {diff:.1f}dB 큼 → Android↓ 또는 iPhone↑'
        elif ios_avg <= -60 or and_avg <= -60:
            bal_hint = '⚖️  양쪽 모두 신호 필요'
        else:
            bal_hint = f'✅ 밸런스 OK (차이: {diff:.1f}dB)'

        # 화면 갱신 (커서 이동으로 깜빡임 방지)
        lines = []
        lines.append('')
        lines.append(f'  📱 iPhone  (ch{CH_IOS+1})')
        lines.append(f'     RMS:  {ios_rms:7.1f} dB  │ {level_bar_compact(ios_rms)}│')
        lines.append(f'     Peak: {ios_peak:7.1f} dB  │ {level_bar_compact(ios_peak)}│')
        lines.append(f'     평균:  {ios_avg:7.1f} dB  → {ios_hint}')
        lines.append('')
        lines.append(f'  📱 Android (ch{CH_ANDROID+1})')
        lines.append(f'     RMS:  {and_rms:7.1f} dB  │ {level_bar_compact(and_rms)}│')
        lines.append(f'     Peak: {and_peak:7.1f} dB  │ {level_bar_compact(and_peak)}│')
        lines.append(f'     평균:  {and_avg:7.1f} dB  → {and_hint}')
        lines.append('')
        lines.append(f'  ────────────────────────────────────────────────────────')
        lines.append(f'  ⚖️  밸런스: iPhone − Android = {ios_avg - and_avg:+.1f} dB  │  {bal_hint}')
        lines.append('')

        # 범례
        lines.append(f'     ░░ 약함(<-25dB)  ▒▒ 목표(-25~-15)  ▓▓ 강함(-15~-3)  ██ 클리핑(>-3)')
        lines.append('')

        # 종합 상태
        if all_ok:
            remaining = max(0, STABLE_SECONDS - stable_elapsed)
            if remaining > 0:
                lines.append(f'  🟢 튜닝 양호! → {remaining:.1f}초 후 자동 종료...')
            else:
                lines.append(f'  ✅✅✅ 튜닝 완료! 양쪽 레벨 매칭 확인됨 ✅✅✅')
        elif ios_avg > -60 or and_avg > -60:
            lines.append(f'  🔧 조정 중... (iRig 게인 / 폰 볼륨 / CONNECT 6 Input Gain)')
        else:
            lines.append(f'  ⏳ 대기 중... (양쪽 폰에서 유튜브 재생 시작해주세요)')

        # 커서를 데이터 시작 위치로 이동 후 덮어쓰기
        print(f"\033[{header_lines + 1};1H", end='')
        for line in lines:
            print(f"\033[K{line}")

        # 안정 시간 경과 → 종료
        if all_ok and stable_elapsed >= STABLE_SECONDS:
            print(f"\n\n  🎉 튜닝 완료! {STABLE_SECONDS}초간 안정 확인.")
            print(f"     iPhone  평균 RMS: {ios_avg:.1f} dBFS")
            print(f"     Android 평균 RMS: {and_avg:.1f} dBFS")
            print(f"     차이: {diff:.1f} dB (허용: ±{BALANCE_THRESHOLD} dB)")
            print(f"\n  퇴근합니다 🫡\n")
            running = False
            return

# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────
def main():
    global running

    def sigint_handler(sig, frame):
        global running
        running = False
        print("\n\n  ⏹️  수동 종료 (Ctrl+C)")

        with lock:
            ios_avg = current['ios_rms_avg']
            and_avg = current['and_rms_avg']

        if ios_avg > -60 and and_avg > -60:
            diff = abs(ios_avg - and_avg)
            print(f"     최종 iPhone  RMS: {ios_avg:.1f} dBFS")
            print(f"     최종 Android RMS: {and_avg:.1f} dBFS")
            print(f"     차이: {diff:.1f} dB")
            if diff <= BALANCE_THRESHOLD:
                print(f"     ✅ 밸런스 OK")
            else:
                print(f"     ⚠️ 밸런스 미달 (차이 {diff:.1f}dB > 허용 {BALANCE_THRESHOLD}dB)")
        print()
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)

    stream = sd.InputStream(
        device=dev_idx,
        channels=open_ch,
        samplerate=SAMPLE_RATE,
        dtype='float32',
        blocksize=BLOCK_SIZE,
        callback=audio_callback,
    )

    with stream:
        display_loop()

if __name__ == '__main__':
    main()
