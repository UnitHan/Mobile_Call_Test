#!/usr/bin/env python3
"""기존 녹음 WAV 파일들을 날짜별 폴더로 정리합니다."""
import re, shutil
from pathlib import Path

date_re = re.compile(r'_(\d{4})(\d{2})(\d{2})_\d{6}(?:_\w+)?\.wav$')

moved = 0
skipped = 0

for base_dir in [
    '/Users/qabulls/Documents/sound/audio_files/recordings',
    '/Users/qabulls/Documents/sound/audio_files/recordings/collected',
    '/Users/qabulls/Documents/sound/audio_files/recordings/mixed',
]:
    base = Path(base_dir)
    if not base.exists():
        continue
    for f in sorted(base.iterdir()):
        if not f.is_file() or f.suffix.lower() != '.wav':
            continue
        m = date_re.search(f.name)
        if not m:
            print(f'  skip (no date): {f.name}')
            skipped += 1
            continue
        year, month, day = m.group(1), m.group(2), m.group(3)
        date_folder = base / f'{year}-{month}-{day}'
        date_folder.mkdir(exist_ok=True)
        dest = date_folder / f.name
        if dest.exists():
            print(f'  skip (exists): {f.name}')
            skipped += 1
            continue
        shutil.move(str(f), str(dest))
        moved += 1
        print(f'  moved: {f.name} -> {date_folder.name}/')

print(f'\nDone: {moved} moved, {skipped} skipped')
