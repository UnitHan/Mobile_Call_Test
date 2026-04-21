#!/usr/bin/env python3
"""녹음 파일을 정답지 RMS에 맞춰 정규화된 사본 저장.

사용법:
  python3 normalize_recordings.py <타임스탬프>
  python3 normalize_recordings.py 165020

결과:
  audio_files/recordings/collected/Android_ixiO_20260327_165020_normalized.wav
  audio_files/recordings/collected/iOS_ixiO_20260327_165020_normalized.wav
"""
import sys
import os
import numpy as np
import soundfile as sf
from audio_lib.io import load_audio

REF_AND = 'dating_SPEAKER_00.wav'
REF_IOS = 'dating_SPEAKER_01.wav'
BASE = 'audio_files/recordings/collected'
SR = 16000

def normalize_to_ref(rec_path: str, ref_path: str, out_path: str) -> dict:
    """녹음 파일 RMS를 정답지 RMS에 맞춰 저장. 원본 SR 유지."""
    # 원본 SR로 읽기
    rec_data, rec_sr = sf.read(rec_path)
    ref_y = load_audio(ref_path)  # 16kHz mono

    # RMS 계산 (16kHz mono 기준)
    rec_mono = load_audio(rec_path)
    rec_rms = float(np.sqrt(np.mean(rec_mono**2)))
    ref_rms = float(np.sqrt(np.mean(ref_y**2)))

    if rec_rms < 1e-8:
        print(f'  ⚠️ 녹음 무음 — 스킵')
        return {}

    scale = ref_rms / rec_rms
    out_data = rec_data * scale

    # 클리핑 방지
    peak = float(np.max(np.abs(out_data)))
    if peak > 0.99:
        out_data = out_data * (0.99 / peak)
        print(f'  ⚠️ 클리핑 방지 리미팅 적용 (peak {peak:.4f} → 0.99)')

    sf.write(out_path, out_data, rec_sr)

    out_rms = rec_rms * scale
    return {
        'before_rms': rec_rms,
        'after_rms': out_rms,
        'ref_rms': ref_rms,
        'scale': scale,
        'peak': peak,
    }


def main():
    if len(sys.argv) < 2:
        print('사용법: python3 normalize_recordings.py <타임스탬프>')
        print('예: python3 normalize_recordings.py 165020')
        sys.exit(1)

    ts = sys.argv[1]
    date_prefix = '20260330'  # 오늘 날짜 기본값
    if len(ts) == 15:  # 풀 타임스탬프 (YYYYMMDD_HHMMSS)
        date_prefix = ts[:8]
        ts = ts[9:]

    def _find_rec(platform, date, time):
        """TC 라벨 유무에 관계없이 녹음 파일 탐색."""
        import glob as _g
        for pat in [f'{BASE}/{platform}_ixiO_TC_*_{date}_{time}.wav',
                    f'{BASE}/{platform}_ixiO_{date}_{time}.wav']:
            hits = _g.glob(pat)
            if hits:
                return sorted(hits)[-1]
        return None

    and_rec = _find_rec('Android', date_prefix, ts)
    ios_rec = _find_rec('iOS', date_prefix, ts)

    pairs = [
        ('Android', and_rec, REF_AND),
        ('iOS',     ios_rec, REF_IOS),
    ]

    print(f'정답지 RMS:')
    ref_and_rms = float(np.sqrt(np.mean(load_audio(REF_AND)**2)))
    ref_ios_rms = float(np.sqrt(np.mean(load_audio(REF_IOS)**2)))
    print(f'  SPEAKER_00 (→Android): {ref_and_rms:.4f}')
    print(f'  SPEAKER_01 (→iOS):     {ref_ios_rms:.4f}')
    print()

    for label, rec_path, ref_path in pairs:
        if not rec_path or not os.path.exists(rec_path):
            print(f'{label}: 파일 없음')
            continue

        out_path = rec_path.replace('.wav', '_normalized.wav')
        print(f'{label}: {os.path.basename(rec_path)}')
        result = normalize_to_ref(rec_path, ref_path, out_path)
        if result:
            ratio_before = result['before_rms'] / result['ref_rms']
            ratio_after = result['after_rms'] / result['ref_rms']
            print(f'  RMS: {result["before_rms"]:.4f} → {result["after_rms"]:.4f}  '
                  f'(×{result["scale"]:.2f})')
            print(f'  정답지대비: {ratio_before:.2f}x → {ratio_after:.2f}x')
            print(f'  저장: {os.path.basename(out_path)}')
        print()


if __name__ == '__main__':
    main()
