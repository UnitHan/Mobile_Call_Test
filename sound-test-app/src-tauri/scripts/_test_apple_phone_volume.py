"""
Apple 전화 앱 통화 볼륨 측정 테스트

순서:
  1. WDA를 통해 iPhone 볼륨을 목표값(20)으로 설정
  2. "수동으로 발신하세요" 안내 후 대기
  3. CONNECT 6 Mobile In (ch4,5) 실시간 레벨 측정
  4. 결과 요약 출력

사용법:
  python _test_apple_phone_volume.py [--wda-url http://IP:8100] [--target-volume 20]
"""

import argparse
import time
import sys
import threading

import requests
import sounddevice as sd
import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_WDA_URL      = 'http://192.168.219.119:8100'
CONNECT6_DEV_INDEX   = 1        # CONNECT 6 #2 (iOS용) sounddevice index
REC_CHANNELS         = (4, 5)   # Mobile In ch5/ch6 (0-based)
SR                   = 48000
MEASURE_SEC          = 60       # 측정 최대 시간(초)
TARGET_VOLUME        = 20       # 목표 볼륨 (0~100, iOS 시스템 볼륨)


# ─────────────────────────────────────────────────────────────────────────────
# WDA 볼륨 제어
# ─────────────────────────────────────────────────────────────────────────────
def _wda_session(wda_url: str) -> str | None:
    """Apple 전화 앱 WDA 세션을 생성하고 session ID를 반환합니다."""
    # 기존 세션 정리
    try:
        sr = requests.get(f'{wda_url}/sessions', timeout=5)
        for s in sr.json().get('value', []):
            sid = s.get('id') or s.get('sessionId')
            if sid:
                requests.delete(f'{wda_url}/session/{sid}', timeout=3)
    except Exception:
        pass

    caps = {'capabilities': {'alwaysMatch': {
        'bundleId': 'com.apple.mobilephone',
        'platformName': 'iOS',
        'shouldTerminateApp': False,
        'forceAppLaunch': False,
        'shouldWaitForQuiescence': False,
    }}}
    try:
        r = requests.post(f'{wda_url}/session', json=caps, timeout=15)
        val = r.json().get('value') or {}
        sid = val.get('sessionId') or r.json().get('sessionId')
        return sid
    except Exception as e:
        print(f'  ⚠️  세션 생성 실패: {e}')
        return None


def _close_session(wda_url: str, sid: str):
    try:
        requests.delete(f'{wda_url}/session/{sid}', timeout=4)
    except Exception:
        pass


def set_volume_via_wda(wda_url: str, target: int) -> bool:
    """WDA pressButton(volumeUp/volumeDown)을 반복해 목표 볼륨에 근접시킵니다.

    iOS는 시스템 볼륨을 직접 읽을 수 없으므로 최대에서 완전히 내린 후
    target 단계만큼 올리는 방식을 사용합니다. (iOS 볼륨 단계: 약 16단계)
    """
    TOTAL_STEPS = 16   # iOS 볼륨 총 단계 수
    target_steps = round(target / 100 * TOTAL_STEPS)

    sid = _wda_session(wda_url)
    if not sid:
        return False

    print(f'  세션 ID: {sid}')
    print(f'  볼륨 최소(0)로 먼저 내립니다 ({TOTAL_STEPS}회)...')

    # 1. 최소로 내리기
    for i in range(TOTAL_STEPS):
        requests.post(
            f'{wda_url}/session/{sid}/wda/pressButton',
            json={'name': 'volumeDown'},
            timeout=3,
        )
        time.sleep(0.15)

    time.sleep(0.3)

    # 2. target 단계만큼 올리기
    print(f'  볼륨 {target_steps}단계 올립니다 (목표: ~{target}/100)...')
    for i in range(target_steps):
        requests.post(
            f'{wda_url}/session/{sid}/wda/pressButton',
            json={'name': 'volumeUp'},
            timeout=3,
        )
        time.sleep(0.15)

    _close_session(wda_url, sid)
    print(f'  ✅ 볼륨 설정 완료 (목표: {target}/100, {target_steps}/{TOTAL_STEPS} 단계)')
    return True


# ─────────────────────────────────────────────────────────────────────────────
# CONNECT 6 레벨 측정
# ─────────────────────────────────────────────────────────────────────────────
def measure_level(duration: int = MEASURE_SEC, device: int = CONNECT6_DEV_INDEX):
    """CONNECT 6 Mobile In (ch4,5)을 실시간으로 측정합니다."""
    in_buf = []

    def callback(indata, outdata, frames, time_info, status):
        in_buf.append(indata[:, list(REC_CHANNELS)].copy())

    results = []

    print()
    print('=' * 68)
    print('CONNECT 6 Mobile In 레벨 측정 (Ctrl+C: 중단)')
    print('=' * 68)
    print(f'  {"sec":>4}  {"RMS ch5":>9}  {"RMS ch6":>9}  {"Peak":>9}  상태')
    print('-' * 68)

    try:
        with sd.Stream(device=device, samplerate=SR, dtype='float32',
                       channels=(6, 2), callback=callback):
            for sec in range(1, duration + 1):
                time.sleep(1)
                if not in_buf:
                    continue
                chunk = np.concatenate(in_buf, axis=0)
                in_buf.clear()

                ch5 = chunk[:, 0]
                ch6 = chunk[:, 1]
                rms5  = 20 * np.log10(np.sqrt(np.mean(ch5**2)) + 1e-12)
                rms6  = 20 * np.log10(np.sqrt(np.mean(ch6**2)) + 1e-12)
                peak5 = 20 * np.log10(np.max(np.abs(ch5)) + 1e-12)

                if peak5 > -1:
                    status = '🔴 클리핑!'
                elif rms5 > -20:
                    status = '🟡 레벨 높음'
                elif rms5 > -35:
                    status = '🟢 양호 ★'
                elif rms5 > -50:
                    status = '🔵 약함'
                else:
                    status = '⚪ 무음'

                results.append({'sec': sec, 'rms5': rms5, 'peak5': peak5})
                print(f'  {sec:4d}s  {rms5:9.1f}  {rms6:9.1f}  {peak5:9.1f}  {status}')
                sys.stdout.flush()

    except KeyboardInterrupt:
        print('\n  측정 중단됨')

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 결과 요약
# ─────────────────────────────────────────────────────────────────────────────
def summarize(results: list):
    if not results:
        print('  측정 데이터 없음')
        return

    # 무음(-80 이하) 구간 제외
    active = [r for r in results if r['rms5'] > -60]
    if not active:
        print('  통화 중 유효 신호 없음 (통화가 연결되지 않았을 수 있음)')
        return

    rms_vals  = [r['rms5']  for r in active]
    peak_vals = [r['peak5'] for r in active]

    rms_mean = np.mean(rms_vals)
    rms_min  = np.min(rms_vals)
    rms_max  = np.max(rms_vals)
    peak_max = np.max(peak_vals)
    clip_cnt = sum(1 for p in peak_vals if p > -1)

    print()
    print('=' * 50)
    print('측정 결과 요약')
    print('=' * 50)
    print(f'  유효 구간    : {len(active)}초 / 전체 {len(results)}초')
    print(f'  RMS 평균     : {rms_mean:.1f} dBFS', end='')
    if -35 <= rms_mean <= -20:
        print('  ✅ 적정')
    elif rms_mean > -20:
        print('  ⚠️  높음 (클리핑 위험)')
    else:
        print('  ⚠️  낮음')
    print(f'  RMS 범위     : {rms_min:.1f} ~ {rms_max:.1f} dBFS')
    print(f'  Peak 최대    : {peak_max:.1f} dBFS', end='')
    print('  🔴 클리핑 발생!' if peak_max > -1 else '')
    print(f'  클리핑 발생  : {clip_cnt}초')
    print('=' * 50)

    if clip_cnt == 0 and -35 <= rms_mean <= -20:
        print('  → 볼륨 설정 적절. 실제 테스트 적용 가능합니다.')
    elif clip_cnt > 0:
        print(f'  → 클리핑 {clip_cnt}회 발생. 볼륨을 더 낮추세요.')
        # 몇 단계 더 낮춰야 하는지 추정 (-6dB per 단계)
        excess = peak_max - (-6)
        extra_steps = max(1, int(excess / 6))
        print(f'     제안: target_volume을 {max(5, TARGET_VOLUME - extra_steps * 6)}으로 낮추세요')
    elif rms_mean < -35:
        print('  → 레벨이 낮습니다. 볼륨을 높이거나 CONNECT 6 노브를 조정하세요.')


# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Apple 전화 앱 통화 볼륨 테스트')
    parser.add_argument('--wda-url',       default=DEFAULT_WDA_URL, help='WDA URL')
    parser.add_argument('--target-volume', type=int, default=TARGET_VOLUME,
                        help='목표 볼륨 0~100 (기본: 20)')
    parser.add_argument('--device',        type=int, default=CONNECT6_DEV_INDEX,
                        help='CONNECT 6 sounddevice index (기본: 1)')
    parser.add_argument('--duration',      type=int, default=MEASURE_SEC,
                        help='측정 시간 초 (기본: 60)')
    parser.add_argument('--skip-volume',   action='store_true',
                        help='볼륨 설정 건너뛰고 측정만 수행')
    args = parser.parse_args()

    print('=' * 55)
    print('Apple 전화 앱 통화 볼륨 테스트')
    print('=' * 55)
    print(f'  WDA URL      : {args.wda_url}')
    print(f'  목표 볼륨    : {args.target_volume}/100')
    print(f'  CONNECT 6    : device={args.device}')
    print(f'  측정 시간    : {args.duration}초')
    print()

    # ── Step 1: WDA로 볼륨 설정 ──────────────────────────────────────────────
    if not args.skip_volume:
        print('[ Step 1 ] WDA를 통해 iPhone 볼륨 설정 중...')
        ok = set_volume_via_wda(args.wda_url, args.target_volume)
        if not ok:
            print('  ⚠️  볼륨 설정 실패. --skip-volume 옵션으로 측정만 진행 가능합니다.')
            sys.exit(1)
    else:
        print('[ Step 1 ] 볼륨 설정 건너뜀')

    print()

    # ── Step 2: 수동 발신 대기 ───────────────────────────────────────────────
    print('[ Step 2 ] 지금 iPhone에서 수동으로 전화를 발신하세요.')
    print('           통화가 연결되면 Enter 키를 눌러 측정을 시작합니다.')
    print('           (또는 10초 후 자동 시작)')
    print()

    # 10초 카운트다운 또는 Enter 대기
    start_event = threading.Event()

    def _wait_enter():
        input()
        start_event.set()

    t = threading.Thread(target=_wait_enter, daemon=True)
    t.start()

    for remaining in range(10, 0, -1):
        if start_event.is_set():
            break
        print(f'\r  {remaining}초 후 자동 시작... (Enter: 즉시 시작)', end='', flush=True)
        time.sleep(1)
    print('\r' + ' ' * 55 + '\r', end='')

    # ── Step 3: 레벨 측정 ────────────────────────────────────────────────────
    print('[ Step 3 ] 레벨 측정 시작...')
    results = measure_level(duration=args.duration, device=args.device)

    # ── Step 4: 결과 요약 ────────────────────────────────────────────────────
    summarize(results)


if __name__ == '__main__':
    main()
