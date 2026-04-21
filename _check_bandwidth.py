#!/usr/bin/env python3
"""녹음 파일별 실질 주파수 대역폭 비교"""
import numpy as np
import wave

files = {
    "Extract iOS (16kHz)": "recordings/recording_iOS_20260318_150644_1.wav",
    "Extract Android (16kHz)": "recordings/recording_android_20260318_150645_1.wav",
    "Direct Android (48kHz)": "음빠짐 정상_Android_ixiO_20260320_170219.wav",
    "Direct Android2 (48kHz)": "음빠짐_Android_ixiO_20260320_165651.wav",
    "Reference (44.1kHz)": "reference_audio/dating_SPEAKER_00.wav",
}

for label, path in files.items():
    try:
        w = wave.open(path)
        sr = w.getframerate()
        n = w.getnframes()
        raw = np.frombuffer(w.readframes(n), dtype=np.int16).astype(float)
        w.close()

        fft = np.abs(np.fft.rfft(raw))
        freqs = np.fft.rfftfreq(len(raw), 1 / sr)

        cum_energy = np.cumsum(fft ** 2)
        total = cum_energy[-1]
        idx_995 = np.searchsorted(cum_energy, total * 0.995)
        bw_995 = freqs[idx_995]

        peak = np.max(fft)
        threshold = peak * 0.001
        above = np.where(fft > threshold)[0]
        max_freq = freqs[above[-1]] if len(above) > 0 else 0

        print(f"{label}:")
        print(f"  파일 SR: {sr} Hz | 99.5%% 에너지 대역: {bw_995:.0f} Hz | 최대 신호 주파수: {max_freq:.0f} Hz")
    except Exception as e:
        print(f"{label}: ERROR - {e}")
    print()
