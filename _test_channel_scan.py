"""
Connect 6 출력 채널 스캔 — 어떤 채널 쌍이 Mobile Out으로 가는지 확인
각 채널 쌍(Out 1/2, 3/4, 5/6, 7/8)에 1kHz 톤을 순서대로 보냅니다.
Android 녹음 앱에서 어떤 쌍에서 소리가 나는지 확인하세요.
"""
import sys
import time
import numpy as np
import sounddevice as sd

# ── 대상 장치 (기본: device=2, 인자로 변경 가능) ──
device = int(sys.argv[1]) if len(sys.argv) > 1 else 2

info = sd.query_devices(device)
sr = int(info['default_samplerate'])
max_ch = int(info['max_output_channels'])
print(f'장치: [{device}] {info["name"]}  sr={sr}  max_out_ch={max_ch}')
print()

dur = 2.0
t = np.linspace(0, dur, int(sr * dur), endpoint=False)
tone = (np.sin(2 * np.pi * 1000 * t) * 0.6).astype('float32')

for pair_start in range(0, max_ch, 2):
    pair = (pair_start, pair_start + 1)
    mapped = np.zeros((len(tone), max_ch), dtype='float32')
    mapped[:, pair[0]] = tone
    mapped[:, pair[1]] = tone
    label = f'Out {pair[0]+1}/{pair[1]+1}  (ch {pair[0]},{pair[1]})'
    print(f'▶ {label} 재생 중... 폰 녹음기에서 소리 확인!', flush=True)
    sd.play(mapped, samplerate=sr, device=device, blocking=True)
    time.sleep(1.5)

print()
print('✅ 전체 채널 스캔 완료')
print('   → 소리가 들린 채널 쌍을 설정 > 출력 채널 쌍에 지정하세요')
