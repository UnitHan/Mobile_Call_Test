#!/usr/bin/env python3
"""새 채널 매핑 테스트: CONNECT 6 × 2대, 둘 다 Mobile In (ch5-6)

CONNECT 6 #1 = Android, CONNECT 6 #2 = iOS
"""
import sounddevice as sd, numpy as np

# 모든 CONNECT 6 입력 장치 찾기
devices = []
for i, d in enumerate(sd.query_devices()):
    if 'CONNECT 6' in d.get('name','') and d['max_input_channels'] > 0:
        devices.append((i, d))

if len(devices) < 2:
    print(f'❌ CONNECT 6 {len(devices)}대만 발견됨 (2대 필요)')
    if devices:
        print(f'   발견: [{devices[0][0]}] {devices[0][1]["name"]}')
    exit(1)

print(f'CONNECT 6 #1 (Android): dev={devices[0][0]}')
print(f'CONNECT 6 #2 (iOS):     dev={devices[1][0]}')
print()
print('3초 테스트 녹음 (두 대 모두 Mobile In ch5-6)...')

# 각 장치에서 3초 녹음
rec_and = sd.rec(int(3*48000), samplerate=48000, channels=18, device=devices[0][0], dtype='float32')
sd.wait()
rec_ios = sd.rec(int(3*48000), samplerate=48000, channels=18, device=devices[1][0], dtype='float32')
sd.wait()

# Mobile In L/R = ch 4,5 (0-based)
and_data = rec_and[:, [4,5]].mean(axis=1)
and_rms = 20*np.log10(np.sqrt(np.mean(and_data**2))+1e-10)

ios_data = rec_ios[:, [4,5]].mean(axis=1)
ios_rms = 20*np.log10(np.sqrt(np.mean(ios_data**2))+1e-10)

print(f'Android (CONNECT6#1, Mobile In ch5-6):  RMS = {and_rms:.1f} dBFS')
print(f'iPhone  (CONNECT6#2, Mobile In ch5-6):   RMS = {ios_rms:.1f} dBFS')
print(f'차이: {and_rms - ios_rms:+.1f} dB')
print()
if and_rms > -60: print('✅ Android 신호 OK')
else: print('❌ Android 무신호')
if ios_rms > -60: print('✅ iPhone 신호 OK')
else: print('❌ iPhone 무신호')
