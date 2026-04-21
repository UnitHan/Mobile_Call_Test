#!/usr/bin/env python3
"""CONNECT 6 입력 채널별 신호 레벨 진단 + WAV 저장 테스트."""
import sounddevice as sd
import numpy as np
import wave
from pathlib import Path

# CONNECT 6 장치 찾기
idx = None
for i, d in enumerate(sd.query_devices()):
    if 'CONNECT 6' in d.get('name', '') and d['max_input_channels'] > 0:
        idx = i
        break

if idx is None:
    print('CONNECT 6 장치를 찾을 수 없습니다')
    exit(1)

dev = sd.query_devices(idx)
n_ch = dev['max_input_channels']
print(f'CONNECT 6: dev={idx}, {n_ch}ch 입력, sr={dev["default_samplerate"]:.0f}')
print(f'3초 녹음 중... (iPhone에서 유튜브/통화 중이면 음성 입력됨)')
print()

rec = sd.rec(int(3 * 48000), samplerate=48000, channels=n_ch, device=idx, dtype='float32')
sd.wait()

print(f'{"채널":>4}  |  {"peak(dBFS)":>11}  |  {"RMS(dBFS)":>11}  |  신호')
print('-' * 60)
signal_channels = []
for ch in range(n_ch):
    data = rec[:, ch]
    peak = np.max(np.abs(data))
    rms = np.sqrt(np.mean(data ** 2))
    peak_db = 20 * np.log10(peak + 1e-10)
    rms_db = 20 * np.log10(rms + 1e-10)
    has_signal = rms_db > -60
    label = '✅ 신호 있음' if has_signal else '❌ 무음'
    print(f'  {ch+1:2d}   |  {peak_db:8.1f} dB  |  {rms_db:8.1f} dB  |  {label}')
    if has_signal:
        signal_channels.append(ch)

# 신호가 있는 채널로 WAV 저장 테스트
if signal_channels:
    ch_idx = signal_channels[0]
    mono = rec[:, ch_idx]
    out_path = Path.home() / 'Documents' / 'sound' / 'audio_files' / 'recordings' / 'connect6_test.wav'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(out_path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(pcm.tobytes())
    print(f'\n🎵 테스트 WAV 저장: {out_path}  (ch{ch_idx+1}, {len(mono)/48000:.1f}s)')
    print('   → 이 파일을 재생해서 iPhone 음성이 들리는지 확인하세요')
else:
    print('\n⚠️ 신호가 있는 채널이 없습니다')
