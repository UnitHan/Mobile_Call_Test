#!/usr/bin/env python3
"""
CONNECT 6 녹음 볼륨 진단 스크립트
══════════════════════════════════════════════════════════════════
음원이 크거나 작게 녹음되는 원인을 체계적으로 분석합니다.

진단 항목:
  1. CONNECT 6 하드웨어 입력 채널별 실시간 레벨
  2. macOS 시스템 입력 볼륨 확인
  3. CONNECT 6 채널 라우팅 (Mix A/B vs Direct)
  4. 소프트웨어 게인 설정 (config.RECORDING_GAIN)
  5. 재생 볼륨 설정 (config.PLAYBACK_VOLUME)
  6. 기존 녹음 파일 레벨 분석
  7. float32→int16 변환 클리핑 검사
"""

import subprocess
import sys
import os
from pathlib import Path

import numpy as np
import sounddevice as sd

# ─────────────────────────────────────────────────────────────────────────────
# 1. CONNECT 6 장치 감지
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("  CONNECT 6 녹음 볼륨 진단")
print("=" * 70)

idx = None
for i, d in enumerate(sd.query_devices()):
    if 'CONNECT 6' in d.get('name', '') and d['max_input_channels'] > 0:
        idx = i
        break

if idx is None:
    print("\n❌ CONNECT 6 장치를 찾을 수 없습니다.")
    sys.exit(1)

dev = sd.query_devices(idx)
n_ch = dev['max_input_channels']
sr = int(dev['default_samplerate'])
print(f"\n🎛️  장치: {dev['name']}")
print(f"    인덱스: {idx}")
print(f"    입력 채널: {n_ch}ch")
print(f"    기본 SR: {sr} Hz")

# ─────────────────────────────────────────────────────────────────────────────
# 2. macOS 시스템 입력 볼륨 확인
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "─" * 70)
print("📊 [진단 1] macOS 시스템 입력/출력 볼륨")
print("─" * 70)

try:
    result = subprocess.run(
        ['osascript', '-e', 'get volume settings'],
        capture_output=True, text=True, timeout=5
    )
    vol_info = result.stdout.strip()
    print(f"  시스템 볼륨 설정: {vol_info}")

    # 입력 볼륨 파싱
    for part in vol_info.split(','):
        part = part.strip()
        if 'input volume' in part:
            val = part.split(':')[-1].strip()
            if val == '0' or val == 'missing value':
                print(f"  ⚠️ 입력 볼륨이 0 또는 미설정! → 녹음 레벨에 영향 가능")
            else:
                print(f"  ✅ 입력 볼륨: {val}")
except Exception as e:
    print(f"  ❌ 볼륨 확인 실패: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. 소프트웨어 설정 확인 (config.py)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "─" * 70)
print("📊 [진단 2] 소프트웨어 설정 (config.py)")
print("─" * 70)

# config.py 경로 탐색
config_paths = [
    Path(__file__).parent / 'sound-test-app' / 'src-tauri' / 'scripts' / 'config.py',
    Path(__file__).parent / 'config.py',
]
config_found = False
for cp in config_paths:
    if cp.exists():
        sys.path.insert(0, str(cp.parent))
        config_found = True
        print(f"  config.py 위치: {cp}")
        break

recording_gain = 1.0
playback_volume = 1.0
if config_found:
    try:
        import config  # type: ignore[import-not-found]
        recording_gain = getattr(config, 'RECORDING_GAIN', 1.0)
        playback_volume = getattr(config, 'PLAYBACK_VOLUME', 1.0)
        print(f"  RECORDING_GAIN  = {recording_gain}  ({20*np.log10(max(recording_gain,1e-10)):+.1f} dB)")
        print(f"  PLAYBACK_VOLUME = {playback_volume}  ({20*np.log10(max(playback_volume,1e-10)):+.1f} dB)")

        if recording_gain > 2.0:
            print(f"  ⚠️ RECORDING_GAIN={recording_gain} — 과도한 증폭, 클리핑 위험")
        elif recording_gain < 0.5:
            print(f"  ⚠️ RECORDING_GAIN={recording_gain} — 과도한 감쇠, 소리 작을 수 있음")
        else:
            print(f"  ✅ RECORDING_GAIN 정상 범위")

        if playback_volume > 0.95:
            print(f"  ⚠️ PLAYBACK_VOLUME={playback_volume} — 재생 과입력 위험")
        elif playback_volume < 0.3:
            print(f"  ⚠️ PLAYBACK_VOLUME={playback_volume} — 재생 음량 과소")
        else:
            print(f"  ✅ PLAYBACK_VOLUME 정상 범위")
    except Exception as e:
        print(f"  ❌ config 로드 실패: {e}")
else:
    print(f"  ⚠️ config.py를 찾을 수 없음 — 기본값(1.0) 사용 중")

# ─────────────────────────────────────────────────────────────────────────────
# 4. CONNECT 6 채널별 실시간 레벨 측정 (5초)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "─" * 70)
print("📊 [진단 3] CONNECT 6 채널별 실시간 레벨 (5초 캡처)")
print("─" * 70)
print("  ※ 통화 중이거나 음원 재생 중이면 신호가 잡힙니다")
print("  5초 녹음 중...")

duration = 5
rec = sd.rec(int(duration * 48000), samplerate=48000, channels=n_ch, device=idx, dtype='float32')
sd.wait()

# CONNECT 6 채널 레이블
CH_LABELS = {
    1: 'Input 1 (iPhone iRig)',
    2: 'Input 2 (Android iRig)',
    3: 'Input 3',
    4: 'Input 4',
    5: 'Mobile In L (iPhone USB)',
    6: 'Mobile In R (iPhone USB)',
    7: 'Loopback 1 L (Mix A L)',
    8: 'Loopback 1 R (Mix A R)',
    9: 'Loopback 2 L',
    10: 'Loopback 2 R',
    11: 'Loopback 3 L',
    12: 'Loopback 3 R',
    13: 'Loopback 2 L (Mix B L)',
    14: 'Loopback 2 R (Mix B R)',
    15: 'Loopback 3 L',
    16: 'Loopback 3 R',
    17: 'Loopback 4 L',
    18: 'Loopback 4 R',
}

print(f'\n  {"채널":>4}  |  {"Peak(dBFS)":>11}  |  {"RMS(dBFS)":>11}  |  {"Crest":>6}  |  {"라벨":<30}  |  판정')
print('  ' + '─' * 95)

signal_info = {}
for ch in range(n_ch):
    data = rec[:, ch]
    peak = np.max(np.abs(data))
    rms = np.sqrt(np.mean(data ** 2))
    peak_db = 20 * np.log10(peak + 1e-10)
    rms_db = 20 * np.log10(rms + 1e-10)
    crest_db = peak_db - rms_db
    label = CH_LABELS.get(ch + 1, f'ch{ch+1}')

    # 판정
    if rms_db > -3:
        status = '🔴 클리핑 위험!'
    elif rms_db > -10:
        status = '🟡 과대입력'
    elif rms_db > -30:
        status = '✅ 정상'
    elif rms_db > -60:
        status = '🟡 약한신호'
    else:
        status = '⬜ 무음'

    print(f'  {ch+1:4d}  |  {peak_db:8.1f} dB  |  {rms_db:8.1f} dB  |  {crest_db:5.1f}  |  {label:<30s}  |  {status}')

    if rms_db > -60:
        signal_info[ch + 1] = {
            'peak_db': peak_db, 'rms_db': rms_db, 'crest_db': crest_db,
            'label': label, 'status': status
        }

# ─────────────────────────────────────────────────────────────────────────────
# 5. 현재 녹음 설정에 따른 예상 레벨 분석
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "─" * 70)
print("📊 [진단 4] MixerRecorder 설정 기준 예상 녹음 레벨")
print("─" * 70)

try:
    sys.path.insert(0, str(Path(__file__).parent / 'sound-test-app' / 'src-tauri' / 'scripts'))
    from mixer_recorder import CONNECT6_IOS_CHANNELS, CONNECT6_ANDROID_CHANNELS  # type: ignore[import-not-found]
    ios_ch = CONNECT6_IOS_CHANNELS
    and_ch = CONNECT6_ANDROID_CHANNELS
except Exception:
    ios_ch = (0,)
    and_ch = (1,)

print(f"  iOS 녹음 채널:     ch{tuple(c+1 for c in ios_ch)} (0-based: {ios_ch})")
print(f"  Android 녹음 채널: ch{tuple(c+1 for c in and_ch)} (0-based: {and_ch})")
print(f"  소프트웨어 게인:   {recording_gain}x ({20*np.log10(max(recording_gain,1e-10)):+.1f} dB)")

# iOS 채널 레벨
for ch_set, platform in [(ios_ch, 'iOS→Android_*.wav'), (and_ch, 'Android→iOS_*.wav')]:
    print(f"\n  ── {platform} ──")
    for ch in ch_set:
        data = rec[:, ch]
        peak = np.max(np.abs(data))
        rms = np.sqrt(np.mean(data ** 2))
        peak_db = 20 * np.log10(peak + 1e-10)
        rms_db = 20 * np.log10(rms + 1e-10)

        # 소프트웨어 게인 적용 후 예상
        gained_peak = min(peak * recording_gain, 1.0)
        gained_rms = min(rms * recording_gain, 0.99)
        gained_peak_db = 20 * np.log10(gained_peak + 1e-10)
        gained_rms_db = 20 * np.log10(gained_rms + 1e-10)

        # int16 변환 후 유효 비트
        pcm_peak = int(gained_peak * 32767)
        pcm_rms = int(gained_rms * 32767)

        # 클리핑 검사
        clip_samples = np.sum(np.abs(data * recording_gain) >= 1.0)
        clip_pct = clip_samples / len(data) * 100

        print(f"    ch{ch+1} 원본:  Peak={peak_db:.1f} dB  RMS={rms_db:.1f} dB")
        print(f"    ch{ch+1} 게인 후: Peak={gained_peak_db:.1f} dB  RMS={gained_rms_db:.1f} dB")
        print(f"    ch{ch+1} PCM:   Peak={pcm_peak}/32767  RMS={pcm_rms}/32767")
        if clip_pct > 0:
            print(f"    ⚠️ 클리핑: {clip_samples}샘플 ({clip_pct:.3f}%) → 음질 저하 원인!")
        if gained_rms_db < -40:
            print(f"    ⚠️ RMS {gained_rms_db:.1f} dB — 너무 작음! 하드웨어 게인 확인 필요")
        elif gained_rms_db > -6:
            print(f"    ⚠️ RMS {gained_rms_db:.1f} dB — 너무 큼! 과입력→왜곡 위험")

# ─────────────────────────────────────────────────────────────────────────────
# 6. 기존 녹음 파일 레벨 분석
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "─" * 70)
print("📊 [진단 5] 기존 녹음 파일 레벨 분석")
print("─" * 70)

import wave

rec_dirs = [
    Path.home() / 'Documents' / 'sound' / 'audio_files' / 'recordings' / 'collected',
    Path.home() / 'Documents' / 'sound' / 'audio_files' / 'recordings',
]

wav_files = []
for d in rec_dirs:
    if d.exists():
        wavs = sorted(d.glob('*.wav'), key=lambda p: p.stat().st_mtime, reverse=True)
        wav_files.extend(wavs[:10])  # 최근 10개

if not wav_files:
    print("  녹음 파일 없음")
else:
    print(f"  최근 녹음 파일 {len(wav_files)}개 분석:\n")
    print(f"  {'파일명':<45s}  {'길이':>5s}  {'Peak':>9s}  {'RMS':>9s}  {'판정':<15s}")
    print('  ' + '─' * 90)

    for wf in wav_files[:10]:
        try:
            with wave.open(str(wf), 'rb') as wav:
                nch = wav.getnchannels()
                sw = wav.getsampwidth()
                fr = wav.getframerate()
                nf = wav.getnframes()
                raw = wav.readframes(nf)

            if sw == 2:
                audio = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
            elif sw == 4:
                audio = np.frombuffer(raw, dtype=np.int32).astype(np.float64) / 2147483648.0
            else:
                continue

            if nch > 1:
                audio = audio.reshape(-1, nch).mean(axis=1)

            peak = np.max(np.abs(audio))
            rms = np.sqrt(np.mean(audio ** 2))
            peak_db = 20 * np.log10(peak + 1e-10)
            rms_db = 20 * np.log10(rms + 1e-10)
            dur = nf / fr

            # 클리핑 검사 (±0.99 이상)
            clip_count = np.sum(np.abs(audio) > 0.99)

            if rms_db > -6:
                status = '🔴 과대 (클리핑)'
            elif rms_db > -30:
                status = '✅ 정상'
            elif rms_db > -45:
                status = '🟡 약간 작음'
            else:
                status = '🔵 매우 작음'

            if clip_count > 100:
                status += f' ⚠️클립{clip_count}'

            print(f"  {wf.name:<45s}  {dur:4.1f}s  {peak_db:7.1f}dB  {rms_db:7.1f}dB  {status}")
        except Exception as e:
            print(f"  {wf.name:<45s}  ❌ 분석 실패: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. 채널 간 레벨 차이 분석 (크로스톡/불균형)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "─" * 70)
print("📊 [진단 6] 채널 간 레벨 차이 분석")
print("─" * 70)

if len(signal_info) >= 2:
    active_chs = [(ch, info) for ch, info in sorted(signal_info.items()) if info['rms_db'] > -50]
    if len(active_chs) >= 2:
        rms_levels = [info['rms_db'] for _, info in active_chs]
        max_diff = max(rms_levels) - min(rms_levels)
        print(f"  활성 채널: {[ch for ch, _ in active_chs]}")
        print(f"  RMS 범위: {min(rms_levels):.1f} ~ {max(rms_levels):.1f} dB (차이: {max_diff:.1f} dB)")

        if max_diff > 12:
            print(f"  ⚠️ 채널 간 레벨 차이 {max_diff:.1f}dB — 심각한 불균형!")
            print(f"     원인 분석:")
            for ch, info in active_chs:
                print(f"       ch{ch} ({info['label']}): RMS={info['rms_db']:.1f} dB — {info['status']}")
        elif max_diff > 6:
            print(f"  🟡 채널 간 레벨 차이 {max_diff:.1f}dB — 약간 불균형")
        else:
            print(f"  ✅ 채널 간 레벨 차이 {max_diff:.1f}dB — 균형 양호")
    else:
        print("  활성 채널이 2개 미만 — 비교 불가")
else:
    print("  신호 있는 채널이 2개 미만 — 비교 불가")

# ─────────────────────────────────────────────────────────────────────────────
# 8. 종합 진단 결과
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "═" * 70)
print("📋 종합 진단 결과")
print("═" * 70)

issues = []

# 채널별 문제
for ch_set, name in [(ios_ch, 'iOS(ch→Android_*.wav)'), (and_ch, 'Android(ch→iOS_*.wav)')]:
    for ch in ch_set:
        data = rec[:, ch]
        peak = np.max(np.abs(data))
        rms = np.sqrt(np.mean(data ** 2))
        rms_db = 20 * np.log10(rms + 1e-10)
        gained_peak = peak * recording_gain

        if rms_db < -60:
            issues.append(f"❌ {name} ch{ch+1}: 무신호 (RMS={rms_db:.0f}dB) — iRig 연결/입력 확인")
        elif rms_db < -40:
            issues.append(f"⚠️ {name} ch{ch+1}: 신호 약함 (RMS={rms_db:.0f}dB) — iRig 게인↑ 또는 CONNECT 6 Input Gain↑")
        elif gained_peak >= 0.99:
            issues.append(f"⚠️ {name} ch{ch+1}: 게인 적용 후 클리핑 — RECORDING_GAIN 낮추거나 iRig 게인↓")
        elif rms_db > -10:
            issues.append(f"⚠️ {name} ch{ch+1}: 과입력 (RMS={rms_db:.0f}dB) — iRig 게인↓ 또는 CONNECT 6 Input Gain↓")

if not issues:
    print("\n  ✅ 현재 설정에서 심각한 문제 없음")
else:
    for issue in issues:
        print(f"\n  {issue}")

print(f"""
┌─────────────────────────────────────────────────────────────────────┐
│  녹음 볼륨에 영향을 주는 6가지 요소 (신호 경로 순서)               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ① 휴대폰 통화 볼륨        스피커 아이콘 → 볼륨 조절               │
│     → 단말의 이어피스/스피커 출력 레벨 결정                         │
│                                                                     │
│  ② iRig HD2 하드웨어 게인   iRig 본체의 게인 다이얼                │
│     → XLR/TRS 출력 레벨 결정 (CONNECT 6 입력 전 마지막 조절점)     │
│                                                                     │
│  ③ CONNECT 6 Input Gain    Native Control 앱 또는 하드웨어 노브    │
│     → Input 1/2의 프리앰프 게인 (CONNECT 6 하드웨어 자체 증폭)     │
│                                                                     │
│  ④ CONNECT 6 Mix A/B 볼륨  Native Control 앱                       │
│     → Mix A/B(Loopback) 경로 사용 시 해당 채널의 볼륨 페이더       │
│                                                                     │
│  ⑤ RECORDING_GAIN (SW)     config.py → 현재: {recording_gain}x ({20*np.log10(max(recording_gain,1e-10)):+.1f}dB)     │
│     → 녹음 데이터에 곱하는 소프트웨어 증폭 배율                     │
│                                                                     │
│  ⑥ PLAYBACK_VOLUME (SW)    config.py → 현재: {playback_volume}x ({20*np.log10(max(playback_volume,1e-10)):+.1f}dB)    │
│     → Mac에서 CONNECT 6 Output으로 재생하는 음원 볼륨               │
│     → 상대 폰에서 수신되는 소리 크기에 영향                         │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  권장 녹음 레벨: RMS -25 ~ -15 dBFS  |  Peak < -3 dBFS            │
│  현재 채널 레벨은 위 진단 결과 참조                                 │
└─────────────────────────────────────────────────────────────────────┘
""")

print("✅ 진단 완료")
