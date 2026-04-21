#!/usr/bin/env python3
"""원본 vs 녹음 파일 정밀 볼륨/품질 비교 분석"""
import numpy as np
import wave
import os
import sys

def read_wav(path):
    with wave.open(path, 'rb') as wf:
        n_ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sw}")
    if n_ch > 1:
        data = data.reshape(-1, n_ch).mean(axis=1)
    return data, sr, n_ch, sw

def analyze(path, label):
    data, sr, n_ch, sw = read_wav(path)
    duration = len(data) / sr
    rms = np.sqrt(np.mean(data**2))
    rms_db = 20 * np.log10(rms + 1e-10)
    peak = np.max(np.abs(data))
    peak_db = 20 * np.log10(peak + 1e-10)
    clip_samples = int(np.sum(np.abs(data) >= 0.99))
    clip_pct = clip_samples / len(data) * 100
    seg_len = int(3 * sr)
    segments = []
    for i in range(0, len(data) - seg_len, seg_len):
        seg_rms = np.sqrt(np.mean(data[i:i+seg_len]**2))
        seg_db = 20 * np.log10(seg_rms + 1e-10)
        segments.append(seg_db)
    frame_size = int(0.02 * sr)
    silence_frames = 0
    total_frames = 0
    active_frames_db = []
    for i in range(0, len(data) - frame_size, frame_size):
        frame_rms = np.sqrt(np.mean(data[i:i+frame_size]**2))
        frame_db = 20 * np.log10(frame_rms + 1e-10)
        total_frames += 1
        if frame_db < -60:
            silence_frames += 1
        else:
            active_frames_db.append(frame_db)
    silence_pct = silence_frames / total_frames * 100 if total_frames > 0 else 0
    if active_frames_db:
        dynamic_range = max(active_frames_db) - min(active_frames_db)
        avg_active_db = np.mean(active_frames_db)
    else:
        dynamic_range = 0
        avg_active_db = -100

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  {os.path.basename(path)}")
    print(f"{'='*60}")
    print(f"  포맷: {sr} Hz, {sw*8}bit, {n_ch}ch")
    print(f"  길이: {duration:.2f}초 ({len(data):,} samples)")
    print(f"  ------------------------------------")
    print(f"  RMS:           {rms_db:+.2f} dBFS")
    print(f"  Peak:          {peak_db:+.2f} dBFS")
    print(f"  Crest Factor:  {peak_db - rms_db:.1f} dB")
    print(f"  ------------------------------------")
    print(f"  클리핑(>=0.99): {clip_samples:,} samples ({clip_pct:.3f}%)")
    print(f"  무음 비율(<-60dBFS): {silence_pct:.1f}%")
    print(f"  활성 구간 평균: {avg_active_db:+.1f} dBFS")
    print(f"  다이나믹 레인지: {dynamic_range:.1f} dB")
    print(f"  ------------------------------------")
    print(f"  구간별 RMS (3초 단위):")
    for i, seg_db in enumerate(segments):
        bar_len = max(1, int((seg_db + 60) / 2))
        bar = '#' * bar_len
        print(f"    {i*3:3d}-{(i+1)*3:3d}s: {seg_db:+.1f} dBFS {bar}")
    return data, sr, rms_db, peak_db

def cross_correlate(ref, rec, sr, label):
    min_len = min(len(ref), len(rec))
    max_lag = min(2 * sr, min_len // 2)
    ref_seg = ref[:min_len]
    rec_seg = rec[:min_len]
    ref_norm = ref_seg / (np.sqrt(np.mean(ref_seg**2)) + 1e-10)
    rec_norm = rec_seg / (np.sqrt(np.mean(rec_seg**2)) + 1e-10)
    best_corr = -1
    best_lag = 0
    step = sr // 100  # 10ms
    for lag in range(-max_lag, max_lag, step):
        if lag >= 0:
            r = ref_norm[lag:min_len]
            c = rec_norm[:min_len - lag]
        else:
            r = ref_norm[:min_len + lag]
            c = rec_norm[-lag:min_len]
        n = min(len(r), len(c))
        if n < sr:
            continue
        corr = abs(np.mean(r[:n] * c[:n]))
        if corr > best_corr:
            best_corr = corr
            best_lag = lag
    lag_ms = best_lag / sr * 1000
    print(f"\n  >> {label}")
    print(f"     상관도: {best_corr:.4f}")
    print(f"     시간차: {lag_ms:+.0f}ms ({best_lag:+d} samples)")
    return best_corr, best_lag

if __name__ == '__main__':
    orig_00 = os.path.expanduser("~/Downloads/dating_SPEAKER_00.wav")
    orig_01 = os.path.expanduser("~/Downloads/dating_SPEAKER_01.wav")
    rec_dir = os.path.expanduser("~/Documents/sound/audio_files/recordings/collected")
    # 가장 최근 파일 자동 선택
    ios_files = sorted([f for f in os.listdir(rec_dir) if f.startswith("iOS_") and f.endswith(".wav")])
    and_files = sorted([f for f in os.listdir(rec_dir) if f.startswith("Android_") and f.endswith(".wav")])
    rec_ios = os.path.join(rec_dir, ios_files[-1])
    rec_and = os.path.join(rec_dir, and_files[-1])

    print("=" * 60)
    print("  원본 vs 녹음 파일 정밀 볼륨/품질 비교 분석")
    print("=" * 60)
    print(f"  iOS 녹음: {os.path.basename(rec_ios)}")
    print(f"  Android 녹음: {os.path.basename(rec_and)}")

    d00, sr00, rms00, pk00 = analyze(orig_00, "[원본] dating_SPEAKER_00.wav")
    d01, sr01, rms01, pk01 = analyze(orig_01, "[원본] dating_SPEAKER_01.wav")
    d_ios, sr_ios, rms_ios, pk_ios = analyze(rec_ios, "[녹음-iOS] iPhone 출력 (Mobile In ch5-6)")
    d_and, sr_and, rms_and, pk_and = analyze(rec_and, "[녹음-Android] Android 출력 (Input 1 ch1)")

    print("\n" + "=" * 60)
    print("  교차 상관 (원본-녹음 매핑 확인)")
    print("=" * 60)
    c1, _ = cross_correlate(d01, d_ios, sr_ios, "SPEAKER_01 <-> iOS녹음 (예상매치)")
    c2, _ = cross_correlate(d00, d_and, sr_and, "SPEAKER_00 <-> Android녹음 (예상매치)")
    c3, _ = cross_correlate(d00, d_ios, sr_ios, "SPEAKER_00 <-> iOS녹음")
    c4, _ = cross_correlate(d01, d_and, sr_and, "SPEAKER_01 <-> Android녹음")

    print("\n" + "=" * 60)
    print("  볼륨 차이 요약")
    print("=" * 60)

    if c1 > c3 and c2 > c4:
        map_label = "iOS녹음=SPEAKER_01, Android녹음=SPEAKER_00"
        ios_orig_rms, and_orig_rms = rms01, rms00
        ios_orig_label, and_orig_label = "SPEAKER_01", "SPEAKER_00"
    elif c3 > c1 and c4 > c2:
        map_label = "iOS녹음=SPEAKER_00, Android녹음=SPEAKER_01"
        ios_orig_rms, and_orig_rms = rms00, rms01
        ios_orig_label, and_orig_label = "SPEAKER_00", "SPEAKER_01"
    else:
        map_label = "불확실"
        ios_orig_rms, and_orig_rms = rms01, rms00
        ios_orig_label, and_orig_label = "SPEAKER_01(?)", "SPEAKER_00(?)"

    print(f"\n  매핑: {map_label}")

    diff_ios = rms_ios - ios_orig_rms
    diff_and = rms_and - and_orig_rms
    
    def grade(d):
        ad = abs(d)
        if ad <= 3: return "정상범위"
        elif ad <= 6: return "약간 차이"
        else: return "큼 (주의)"

    print(f"\n  [iPhone 경로] {ios_orig_label} -> 통화 -> iPhone 출력:")
    print(f"     원본 RMS:  {ios_orig_rms:+.2f} dBFS")
    print(f"     녹음 RMS:  {rms_ios:+.2f} dBFS")
    print(f"     차이:      {diff_ios:+.2f} dB  << {grade(diff_ios)}")

    print(f"\n  [Android 경로] {and_orig_label} -> 통화 -> Android 출력:")
    print(f"     원본 RMS:  {and_orig_rms:+.2f} dBFS")
    print(f"     녹음 RMS:  {rms_and:+.2f} dBFS")
    print(f"     차이:      {diff_and:+.2f} dB  << {grade(diff_and)}")

    print(f"\n  Peak 비교:")
    print(f"     {ios_orig_label} Peak: {pk00 if ios_orig_label.endswith('00') else pk01:+.2f} dBFS")
    print(f"     iOS 녹음 Peak:     {pk_ios:+.2f} dBFS")
    print(f"     {and_orig_label} Peak: {pk01 if and_orig_label.endswith('01') else pk00:+.2f} dBFS")
    print(f"     Android 녹음 Peak: {pk_and:+.2f} dBFS")

    print(f"\n{'='*60}")
    print("  게인 보정 제안")
    print("=" * 60)
    if abs(diff_ios) > 1:
        sg = 10 ** (-diff_ios / 20)
        print(f"  RECORDING_GAIN_IOS:     현재 1.0 -> 권장 {sg:.2f} ({-diff_ios:+.1f} dB 보정)")
    else:
        print(f"  RECORDING_GAIN_IOS:     1.0 유지 (차이 {diff_ios:+.1f} dB)")

    if abs(diff_and) > 1:
        sg = 10 ** (-diff_and / 20)
        print(f"  RECORDING_GAIN_ANDROID: 현재 1.0 -> 권장 {sg:.2f} ({-diff_and:+.1f} dB 보정)")
    else:
        print(f"  RECORDING_GAIN_ANDROID: 1.0 유지 (차이 {diff_and:+.1f} dB)")
    print()
