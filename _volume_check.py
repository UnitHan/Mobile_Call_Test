#!/usr/bin/env python3
"""녹음 볼륨 vs 정답지 비교 분석 — 반복 측정용"""
import sys
import numpy as np
from audio_lib.io import load_audio

REF_AND = 'dating_SPEAKER_00.wav'
REF_IOS = 'dating_SPEAKER_01.wav'
BASE = 'audio_files/recordings/collected'

# CLI: python3 _volume_check.py 162956   (타임스탬프만 입력)
#      python3 _volume_check.py          (전체 비교)
ts_filter = sys.argv[1] if len(sys.argv) > 1 else None

ref_and = load_audio(REF_AND)
ref_ios = load_audio(REF_IOS)
ref_and_rms = float(np.sqrt(np.mean(ref_and**2)))
ref_ios_rms = float(np.sqrt(np.mean(ref_ios**2)))

print('=' * 60)
print(f'정답지  SPEAKER_00 RMS={ref_and_rms:.4f} ({20*np.log10(ref_and_rms):.1f} dBFS)')
print(f'정답지  SPEAKER_01 RMS={ref_ios_rms:.4f} ({20*np.log10(ref_ios_rms):.1f} dBFS)')
print('=' * 60)

import glob, os, re
_VC_PAT = re.compile(r'^(iOS|Android)_ixiO_(?:TC_\d{2}_)?(\d{8})_(\d{6})\.wav$', re.IGNORECASE)
today = '20260330'  # 오늘 날짜

if ts_filter:
    timestamps = [ts_filter]
else:
    # 오늘자 파일에서 타임스탬프 추출 (TC 라벨 유무 모두 매칭)
    and_files = sorted(glob.glob(f'{BASE}/Android_ixiO_*_{today}_*.wav') +
                       glob.glob(f'{BASE}/Android_ixiO_{today}_*.wav'))
    timestamps = sorted(set(
        m.group(3) for f in and_files
        if (m := _VC_PAT.match(os.path.basename(f))) and m.group(2) == today
    ))

def _find_wav(platform, date, ts):
    """TC 라벨 유무에 관계없이 파일 탐색."""
    for pat in [f'{BASE}/{platform}_ixiO_TC_*_{date}_{ts}.wav',
                f'{BASE}/{platform}_ixiO_{date}_{ts}.wav']:
        hits = glob.glob(pat)
        if hits:
            return sorted(hits)[-1]  # 가장 최근 TC
    return None

for ts in timestamps:
    and_path = _find_wav('Android', today, ts)
    ios_path = _find_wav('iOS', today, ts)
    if not and_path and not ios_path:
        print(f'\n⚠️  {ts}: 파일 없음')
        continue

    print(f'\n── {ts} ──')
    for label, path, ref_rms in [('Android', and_path, ref_and_rms), ('iOS', ios_path, ref_ios_rms)]:
        if not path or not os.path.exists(path):
            print(f'  {label}: 파일 없음')
            continue
        y = load_audio(path)
        rms = float(np.sqrt(np.mean(y**2)))
        peak = float(np.max(np.abs(y)))
        ratio = rms / ref_rms
        db = 20 * np.log10(ratio) if ratio > 0 else -999
        clip = ' ⚠️클리핑!' if peak > 0.99 else ''
        print(f'  {label:7s}: RMS={rms:.4f} ({20*np.log10(rms):.1f}dBFS)  '
              f'Peak={peak:.4f}  정답지대비={ratio:.2f}x ({db:+.1f}dB){clip}')
