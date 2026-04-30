"""
call_audio_collector.py
────────────────────────────────────────────────────────────────────────────
통화 종료 후 양쪽 녹음 파일을 수집하고 하나의 통화 음원으로 믹스합니다.

역할 분담:
  ① iOS (발신단)   — ixio 앱이 통화 중 녹음한 파일을 AppiumDriver 또는 AFC/SFTP로 pull
  ② Android (수신단) — 단말의 통화 녹음 파일 저장 경로에서 ADB로 최신 파일 pull
  ③ 믹스          — 두 트랙을 '통화 시작 시각' 기준으로 정렬 후 모노 믹스 → WAV 저장

설정 (config.py):
  ANDROID_CALL_RECORDING_PATH  str   Android 단말 내 통화 녹음 저장 경로
                                     예) '/sdcard/Recordings/Call/'
                                         '/storage/emulated/0/MIUI/sound_recorder/call_rec/'
  IOS_APP_RECORDING_ENABLED    bool  True면 iOS 앱 녹음 파일을 pull 시도
  IOS_APP_RECORDING_REMOTE_DIR str   iOS 앱 컨테이너 내 녹음 디렉토리
                                     (DocumentsProvider path, 기본 'Documents/recordings')
  MIXED_RECORDING_DIR          str   믹싱 결과 저장 디렉토리 (기본 RECORDING_DIR/mixed)

사용 예:
    collector = CallAudioCollector(
        android_udid="R3CN...",
        ios_driver=appium_driver,     # None이면 ios pull 건너뜀
        ios_udid="00008101-...",
        call_start_ts="20260317_090005",
    )
    result = collector.collect_and_mix()
    # result['ios_path']    — iOS 녹음 WAV (없으면 None)
    # result['android_path'] — Android 녹음 WAV (없으면 None)
    # result['mixed_path']  — 믹스 결과 WAV (양쪽 모두 없으면 None)
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

# ── 기본 상수 ──────────────────────────────────────────────────────────────────
SAMPLE_RATE = 48_000
APP_NAME    = 'ixiO'

# ── Android 통화 녹음 후보 경로 (제조사/OS 버전별 우선순위) ───────────────────
ANDROID_RECORDING_CANDIDATES = [
    # ixiO 앱 전용 경로 (확인된 실제 경로 — 최우선)
    '/sdcard/Recordings/ixiO/',
    '/storage/emulated/0/Recordings/ixiO/',
    # 삼성 One UI 기본 통화 녹음
    '/sdcard/Recordings/Call/',
    '/storage/emulated/0/Recordings/Call/',
    # MIUI / Xiaomi
    '/sdcard/MIUI/sound_recorder/call_rec/',
    '/storage/emulated/0/MIUI/sound_recorder/call_rec/',
    # LG / 기본 안드로이드
    '/sdcard/CallRecordings/',
    '/storage/emulated/0/CallRecordings/',
    # Google Pixel / AOSP
    '/sdcard/PhoneRecordings/',
    '/storage/emulated/0/PhoneRecordings/',
    # 이동통신사 커스텀 (LG U+ / LGT)
    '/sdcard/RecordCalls/',
    '/storage/emulated/0/Music/CallRecordings/',
]

# iOS ixio 앱 컨테이너 내 녹음 저장 위치 후보
IOS_RECORDING_CANDIDATES = [
    'Documents/recordings/',
    'Documents/',
    'Library/Application Support/recordings/',
]


# ─────────────────────────────────────────────────────────────────────────────
# WAV 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _load_wav_float(path: Path) -> tuple[np.ndarray, int]:
    """WAV 파일을 float32 mono 배열로 읽어 반환합니다. (sample_rate 포함)"""
    import wave
    with wave.open(str(path), 'rb') as wf:
        sr   = wf.getframerate()
        ch   = wf.getnchannels()
        sw   = wf.getsampwidth()
        data = wf.readframes(wf.getnframes())

    dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
    dtype = dtype_map.get(sw, np.int16)
    pcm = np.frombuffer(data, dtype=dtype).astype(np.float32)
    if dtype == np.int8:
        pcm /= 128.0
    elif dtype == np.int16:
        pcm /= 32768.0
    elif dtype == np.int32:
        pcm /= 2147483648.0

    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1)  # mono 믹스

    return pcm, sr


def _load_any_audio(path: Path) -> tuple[np.ndarray, int]:
    """m4a / mp4 / wav 등 모든 오디오 포맷을 float32 mono 배열로 읽습니다.

    우선순위:
      ① soundfile (wav/flac/ogg 등 네이티브 지원)
      ② ffmpeg subprocess → wav 임시 변환 후 로드
    """
    # ① soundfile 시도 (m4a는 보통 실패하지만 일부 환경에서 동작)
    try:
        import soundfile as sf
        data, sr = sf.read(str(path), always_2d=True)
        mono = data.mean(axis=1).astype(np.float32)
        return mono, sr
    except Exception:
        pass

    # ② ffmpeg 변환
    import tempfile, subprocess as _sp
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        r = _sp.run(
            ['ffmpeg', '-y', '-i', str(path), '-ac', '1', '-ar', '48000',
             '-sample_fmt', 's16', tmp_path],
            capture_output=True, timeout=60
        )
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 변환 실패: {r.stderr.decode(errors='replace')[-200:]}")
        return _load_wav_float(Path(tmp_path))
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass


def _resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """단순 선형 리샘플링 (scipy 없이 동작)."""
    if src_sr == dst_sr:
        return audio
    n_out = int(len(audio) * dst_sr / src_sr)
    indices = np.linspace(0, len(audio) - 1, n_out)
    i0 = np.floor(indices).astype(int)
    i1 = np.minimum(i0 + 1, len(audio) - 1)
    frac = (indices - i0).astype(np.float32)
    return audio[i0] * (1 - frac) + audio[i1] * frac


def _rms_normalize_for_platform(audio: np.ndarray, sr: int, path: Path) -> np.ndarray:
    """파일명에서 플랫폼을 감지하여 정답지 RMS에 맞춰 정규화.

    Android_ixiO_* → AUDIO_REFERENCE_ANDROID 정답지 사용
    iOS_ixiO_*     → AUDIO_REFERENCE_IOS 정답지 사용
    기타 (믹스 등) → 정규화 건너뜀
    """
    fname = path.name.lower()
    ref_path = None

    try:
        import sys as _sys
        # _hybrid_config.py에서 정답지 경로 로드
        _cfg_dir = Path(__file__).resolve().parent.parent.parent.parent
        if str(_cfg_dir) not in _sys.path:
            _sys.path.insert(0, str(_cfg_dir))
        from _hybrid_config import AUDIO_REFERENCE_ANDROID, AUDIO_REFERENCE_IOS
        if fname.startswith('android'):
            ref_path = AUDIO_REFERENCE_ANDROID.get(1)
        elif fname.startswith('ios'):
            ref_path = AUDIO_REFERENCE_IOS.get(1)
    except (ImportError, AttributeError):
        pass

    if ref_path is None or not Path(ref_path).is_file():
        return audio

    try:
        import soundfile as _sf
        ref_data, ref_sr = _sf.read(ref_path, dtype='float32')
        if ref_data.ndim > 1:
            ref_data = ref_data.mean(axis=1)
        ref_rms = float(np.sqrt(np.mean(ref_data**2)))
        rec_rms = float(np.sqrt(np.mean(audio**2)))

        if rec_rms < 1e-8 or ref_rms < 1e-8:
            return audio

        scale = ref_rms / rec_rms
        out = audio * scale

        # 클리핑 방지
        peak = float(np.max(np.abs(out)))
        if peak > 0.99:
            out = out * (0.99 / peak)

        platform = 'Android' if fname.startswith('android') else 'iOS'
        print(f"  📐 [{platform}] RMS 정규화: {rec_rms:.4f} → {ref_rms:.4f} "
              f"(×{scale:.2f}, peak={peak:.4f})")
        return out
    except Exception as e:
        print(f"  ⚠️ RMS 정규화 실패 ({e}) → 원본 유지")
        return audio


def _save_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    """float32 mono 배열을 16-bit PCM mono WAV로 저장합니다.
    파일명에서 플랫폼을 자동 감지하여 정답지 RMS 정규화를 적용합니다.
    """
    import wave
    audio = _rms_normalize_for_platform(audio, sr, path)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


# ─────────────────────────────────────────────────────────────────────────────
# Android 녹음 파일 수집
# ─────────────────────────────────────────────────────────────────────────────

def _parse_mtime_from_filename(fname: str) -> Optional[float]:
    """통화 녹음 파일명에서 날짜/시각을 파싱하여 epoch 초로 반환.

    지원 형식 (제조사별):
      ixiO 앱:           01022332512_20260320104440278.m4a  → {번호}_{YYYYMMDDHHMMSSMMM}
      삼성 One UI (한글): 통화 녹음 01012345678_250908_164929.m4a  → YYMMDD_HHMMSS
      삼성 One UI (영문): Call Recording 01012345678_250908_164929.m4a
      일반 8자리 날짜:   callrec_20260317_184904.m4a               → YYYYMMDD_HHMMSS
    """
    import re
    # 패턴 0: ixiO 전용 — {전화번호}_{YYYYMMDDHHMMSSMMM}.m4a
    #   예) 01022332512_20260320104440278.m4a
    m = re.match(r'^\d+_(\d{8})(\d{6})\d{0,3}\.', fname)
    if m:
        try:
            dt = datetime.strptime(f'{m.group(1)}_{m.group(2)}', '%Y%m%d_%H%M%S')
            return dt.timestamp()
        except ValueError:
            pass
    # 패턴 1: _YYMMDD_HHMMSS (6자리 날짜, 삼성 표준)
    m = re.search(r'_(\d{6})_(\d{6})(?:\.|$)', fname)
    if m:
        date_str, time_str = m.group(1), m.group(2)
        try:
            dt = datetime.strptime(f'20{date_str}_{time_str}', '%Y%m%d_%H%M%S')
            return dt.timestamp()
        except ValueError:
            pass
    # 패턴 2: _YYYYMMDD_HHMMSS (8자리 날짜)
    m = re.search(r'_(\d{8})_(\d{6})(?:\.|$)', fname)
    if m:
        date_str, time_str = m.group(1), m.group(2)
        try:
            dt = datetime.strptime(f'{date_str}_{time_str}', '%Y%m%d_%H%M%S')
            return dt.timestamp()
        except ValueError:
            pass
    return None


def _adb_list_files(udid: str, remote_dir: str) -> list[str]:
    """adb shell ls -t <remote_dir> 결과 (생성시간 역순) 반환."""
    try:
        out = subprocess.run(
            ['adb', '-s', udid, 'shell', 'ls', '-t', remote_dir],
            capture_output=True, text=True, timeout=10
        ).stdout
        return [f.strip() for f in out.splitlines() if f.strip() and not f.strip().startswith('ls:')]
    except Exception:
        return []


def _adb_dir_exists(udid: str, remote_dir: str) -> bool:
    """ADB로 디렉토리 존재 여부 확인."""
    try:
        r = subprocess.run(
            ['adb', '-s', udid, 'shell', 'test', '-d', remote_dir, '&&', 'echo', 'OK'],
            capture_output=True, text=True, timeout=5
        )
        return 'OK' in r.stdout
    except Exception:
        return False


def collect_android_recording(
    udid: str,
    call_start_ts: str,          # 'YYYYMMDD_HHMMSS' 통화 시작 시각
    custom_path: Optional[str],
    output_dir: Path,
    wait_sec: float = 5.0,       # 통화 종료 후 파일 저장 대기 시간
) -> Optional[Path]:
    """Android 단말에서 통화 녹음 파일을 ADB pull하여 로컬에 저장합니다.

    탐색 전략:
      1. custom_path가 설정된 경우 해당 경로만 탐색
      2. ANDROID_RECORDING_CANDIDATES 목록에서 존재하는 첫 번째 경로 탐색
      3. call_start_ts 이후에 생성된 파일 중 가장 최신 파일 선택
         (= 방금 끝난 통화의 녹음 파일)

    Returns:
        로컬에 저장된 WAV 경로 (없으면 None)
    """
    print(f"📥 [Android] 통화 녹음 파일 수집 중 (udid={udid[:12]}...)...")

    # 파일이 저장될 때까지 잠시 대기
    if wait_sec > 0:
        print(f"  ⏳ {wait_sec:.0f}초 대기 (단말 녹음 저장 완료 대기)...")
        time.sleep(wait_sec)

    # 탐색할 경로 목록 결정
    search_paths: list[str] = []
    if custom_path:
        search_paths = [custom_path]
        print(f"  📂 지정 경로 사용: {custom_path}")
    else:
        print(f"  📂 자동 탐색 경로: {len(ANDROID_RECORDING_CANDIDATES)}개 후보")
        search_paths = [p for p in ANDROID_RECORDING_CANDIDATES if _adb_dir_exists(udid, p)]
        if not search_paths:
            print(f"  ⚠️ Android 통화 녹음 디렉토리를 찾을 수 없습니다.")
            print(f"     config.py의 ANDROID_CALL_RECORDING_PATH를 설정하세요.")
            return None
        print(f"  ✓ 발견된 경로: {search_paths}")

    # call_start_ts를 epoch 초로 변환 (파일 시간 비교용)
    try:
        call_start_epoch = datetime.strptime(call_start_ts, '%Y%m%d_%H%M%S').timestamp()
    except ValueError:
        call_start_epoch = time.time() - 300  # fallback: 5분 전

    # iOS 방식과 동일 — 모든 오디오 파일의 (mtime, fname, rdir) 수집 후 최신순 정렬
    # ixiO Android는 발신/수신 구분 없이 전화번호+타임스탬프로만 저장되므로
    # 가장 최근 파일 = 방금 끝난 통화의 녹음 파일
    AUDIO_EXTS = ('.wav', '.mp4', '.m4a', '.amr', '.3gp')
    candidates: list[tuple[float, str, str]] = []  # (mtime, fname, rdir)

    for rdir in search_paths:
        files = _adb_list_files(udid, rdir)  # ls -t: 최신순
        for idx, fname in enumerate(files):
            if not any(fname.lower().endswith(ext) for ext in AUDIO_EXTS):
                continue

            # ① adb shell stat 으로 수정 시각 확인
            fmtime: Optional[float] = None
            try:
                stat_out = subprocess.run(
                    ['adb', '-s', udid, 'shell', 'stat', '-c', '%Y', f'{rdir}{fname}'],
                    capture_output=True, text=True, timeout=5
                ).stdout.strip()
                fmtime = float(stat_out)
            except Exception:
                pass

            # ② stat 실패 시 파일명에서 날짜 파싱 (ixiO / 삼성 형식)
            if fmtime is None:
                fmtime = _parse_mtime_from_filename(fname)

            # ③ 파일명 파싱도 실패 시: ls -t 순서 기반 가중치 (최신=0, 오래될수록 감소)
            if fmtime is None:
                fmtime = call_start_epoch - idx * 0.001  # ls-t 순서 보존용 더미값

            candidates.append((fmtime, fname, rdir))

    # 최신순 정렬 → 가장 최근 파일 우선
    candidates.sort(key=lambda x: x[0], reverse=True)

    # call_start_epoch 이후 파일 중 가장 최신 선택
    best: Optional[tuple[float, str, str]] = next(
        (c for c in candidates if c[0] >= call_start_epoch), None
    )

    if best is None:
        print(f"  ⚠️ 통화 시작 시각({call_start_ts}) 이후 녹음 파일을 찾지 못했습니다.")
        # 디버그: 디렉토리 현황 출력
        seen_dirs: set[str] = set()
        for _, fname, rdir in candidates:
            if rdir in seen_dirs:
                continue
            seen_dirs.add(rdir)
            audio = [f for _, f, d in candidates if d == rdir][:5]
            if audio:
                print(f"  📂 {rdir} 내 오디오 파일 목록 (최신 순):")
                for f in audio:
                    parsed = _parse_mtime_from_filename(f)
                    ts_str = datetime.fromtimestamp(parsed).strftime('%Y-%m-%d %H:%M:%S') if parsed else '날짜불명'
                    print(f"     {f}  ({ts_str})")
        return None

    best_mtime, best_file, best_dir = best

    remote_full = f'{best_dir}{best_file}'
    local_stem  = f'Android_{APP_NAME}_{call_start_ts}'
    suffix      = Path(best_file).suffix or '.wav'
    local_path  = output_dir / f'{local_stem}{suffix}'

    print(f"  📦 ADB pull: {remote_full}")
    try:
        result = subprocess.run(
            ['adb', '-s', udid, 'pull', remote_full, str(local_path)],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"  ❌ adb pull 실패: {result.stderr.strip()}")
            return None
        print(f"  ✅ Android 녹음 저장: {local_path}")
        return local_path
    except subprocess.TimeoutExpired:
        print(f"  ❌ adb pull 시간 초과")
        return None
    except Exception as e:
        print(f"  ❌ adb pull 오류: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# iOS 녹음 파일 수집
# ─────────────────────────────────────────────────────────────────────────────

def _pull_ios_via_devicectl(
    ios_udid: str,
    bundle_id: str,
    call_start_ts: str,
    output_dir: Path,
) -> Optional[Path]:
    """xcrun devicectl로 iOS 앱 컨테이너에서 통화 녹음 m4a를 pull하고 WAV로 변환합니다.

    파일명 패턴: {UUID}{YYYYMMDD}{HHMMSS}...mvoip...._0.m4a
    무선/유선 연결 모두 동작 (Appium/tidevice 불필요).
    """
    import re as _re, json as _json, tempfile as _tmp

    import datetime as _dt

    # lastModDate → epoch 변환 헬퍼
    # devicectl lastModDate 는 'YYYY-MM-DDTHH:MM:SS' (UTC, timezone-naive 형태로 반환되는 경우 많음)
    # → timezone-aware 변환 없이 .timestamp() 호출 시 로컬 시간(KST)으로 해석 → 9시간 오류 발생
    # → timezone 정보가 없으면 반드시 UTC로 강제 변환
    def _parse_mod_epoch(mod_str: str) -> 'float | None':
        if not mod_str:
            return None
        try:
            # 'Z' 또는 '+HH:MM' 포함 시 aware datetime
            if mod_str.endswith('Z') or '+' in mod_str[10:] or '-' in mod_str[10:]:
                mod_dt = _dt.datetime.fromisoformat(mod_str.replace('Z', '+00:00'))
                return mod_dt.timestamp()  # aware → 정확한 epoch
            else:
                # timezone-naive → UTC로 간주하여 직접 epoch 계산
                mod_dt = _dt.datetime.strptime(mod_str[:19], '%Y-%m-%dT%H:%M:%S')
                return mod_dt.replace(tzinfo=_dt.timezone.utc).timestamp()
        except Exception:
            return None

    _IOS_PAT = _re.compile(
        r'^[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}'
        r'(\d{8})(\d{6})\d+mvoip.*\.m4a$',
        _re.IGNORECASE,
    )
    # call_start_ts 기준 epoch (파일명 타임스탬프 비교용 — 60초 여유 허용)
    try:
        cs_epoch = _dt.datetime.strptime(call_start_ts, '%Y%m%d_%H%M%S').timestamp()
    except ValueError:
        cs_epoch = None

    # 1. 파일 목록 조회
    json_tmp = Path(_tmp.mktemp(suffix='.json'))
    try:
        r = subprocess.run(
            [
                'xcrun', 'devicectl', 'device', 'info', 'files',
                '--device', ios_udid,
                '--domain-type', 'appDataContainer',
                '--domain-identifier', bundle_id,
                '--json-output', str(json_tmp),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if r.returncode != 0:
            print(f"  ⚠️ [iOS] devicectl info files 실패: {r.stderr.decode(errors='ignore').strip()[:200]}")
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  ⚠️ [iOS] devicectl 없음/타임아웃: {e}")
        return None

    if not json_tmp.exists():
        return None

    try:
        data = _json.loads(json_tmp.read_text())
    except _json.JSONDecodeError:
        return None
    finally:
        json_tmp.unlink(missing_ok=True)

    result_data = data.get('result', data)
    entries     = result_data.get('files', result_data.get('entries', []))

    # 2. m4a 후보 목록 — lastModDate >= call_start - 60초인 모든 .m4a 수집
    #    발신단: UUID-mvoip-... 패턴   수신단: thhsdcyb-... 패턴
    #    두 패턴을 별도로 처리하면 "candidates 비어있을 때만 fallback" 로직에서
    #    오래된 mvoip 파일이 1개라도 통과하면 수신단 파일을 놓치는 버그 발생.
    #    → 모든 .m4a를 단일 후보 목록으로 처리하고 lastModDate 기준 정렬로 통일.
    candidates: list[tuple[float, str]] = []  # (mod_epoch, fname)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name  = entry.get('name', '')
        fname = Path(name).name
        if not fname.lower().endswith('.m4a'):
            continue

        mod_str   = entry.get('metadata', {}).get('lastModDate', '')
        mod_epoch = _parse_mod_epoch(mod_str)

        if cs_epoch is not None and mod_epoch is not None:
            # 파일 수정 시각이 통화 시작보다 60초 이상 이전이면 제외 (과거 통화 녹음 오수집 방지)
            if mod_epoch < cs_epoch - 60.0:
                continue
        elif cs_epoch is not None and mod_epoch is None:
            # lastModDate 없음 → 파일명 타임스탬프(mvoip 패턴 한정)로 시간 필터 적용
            # thhsdcyb 등 수신단 패턴은 파일명으로 시간 판단 불가 → 필터 없이 포함
            m_mvoip = _IOS_PAT.match(fname)
            if m_mvoip:
                try:
                    fname_epoch = _dt.datetime.strptime(
                        m_mvoip.group(1) + m_mvoip.group(2), '%Y%m%d%H%M%S'
                    ).timestamp()
                    if fname_epoch < cs_epoch - 60.0:
                        continue
                except Exception:
                    pass
            # else: thhsdcyb 등 — 시간 불명, 필터 건너뜀 (이전 else:continue 버그 수정)

        # sort_epoch 계산: 내림차순 정렬 시 최신 파일이 먼저 오도록
        if mod_epoch is not None:
            sort_epoch = mod_epoch
        else:
            m_mvoip = _IOS_PAT.match(fname)
            if m_mvoip:
                # mvoip 패턴 → 파일명 날짜로 대체
                try:
                    sort_epoch = _dt.datetime.strptime(
                        m_mvoip.group(1) + m_mvoip.group(2), '%Y%m%d%H%M%S'
                    ).timestamp()
                except Exception:
                    sort_epoch = 0.0
            else:
                # thhsdcyb 등: 파일명 내 10자리 숫자(epoch 초)로 추정
                em = _re.search(r'@\D*(\d{10})(?:_\d+)?\.m4a$', fname, _re.IGNORECASE)
                sort_epoch = float(em.group(1)) if em else 0.0

        candidates.append((sort_epoch, fname))

    if not candidates:
        all_m4a = [e.get('name', '') for e in entries
                   if isinstance(e, dict) and '.m4a' in e.get('name', '')]
        print(f"  ❌ [iOS] {call_start_ts} 근처 m4a 없음 (전체 m4a {len(all_m4a)}개)")
        return None

    # lastModDate 내림차순 → 가장 최근 파일 선택 (통화 직후에 쓰인 파일)
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, best_fname = candidates[0]
    role_hint = '발신단' if _IOS_PAT.match(best_fname) else '수신단'
    print(f"  📦 [iOS] devicectl pull ({role_hint}): {best_fname}")

    # 3. m4a pull
    local_m4a = output_dir / f'iOS_{APP_NAME}_{call_start_ts}.m4a'
    r = subprocess.run(
        [
            'xcrun', 'devicectl', 'device', 'copy', 'from',
            '--device', ios_udid,
            '--domain-type', 'appDataContainer',
            '--domain-identifier', bundle_id,
            '--source', f'Documents/{best_fname}',
            '--destination', str(local_m4a),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0 or not local_m4a.exists():
        print(f"  ❌ [iOS] devicectl copy 실패: {r.stderr.strip()[:200]}")
        return None

    print(f"  ✅ [iOS] m4a pull 완료: {local_m4a.name} ({local_m4a.stat().st_size // 1024}KB)")

    # 4. m4a → WAV 변환
    local_wav = output_dir / f'iOS_{APP_NAME}_{call_start_ts}.wav'
    try:
        audio, sr = _load_any_audio(local_m4a)
        _save_wav(local_wav, audio, sr)
        print(f"  ✅ [iOS] WAV 변환 완료: {local_wav.name} ({len(audio)/sr:.1f}s)")
        return local_wav
    except Exception as e:
        print(f"  ⚠️ [iOS] WAV 변환 실패 ({e}) → m4a 원본 반환")
        return local_m4a


def collect_ios_recording(
    ios_driver,           # Appium WebDriver (None이면 건너뜀)
    ios_udid: str,
    call_start_ts: str,
    output_dir: Path,
    bundle_id: str = 'com.lguplus.aicallagent',
    remote_dir_candidates: Optional[list[str]] = None,
) -> Optional[Path]:
    """iOS ixio 앱에서 통화 녹음 파일을 pull합니다.

    우선순위:
      ① Appium driver.pull_file() — 세션이 살아있을 때 가장 안정적
      ② ifuse / ideviceinstaller 마운트 — 드라이버 없을 때 fallback
      ③ tidevice 파일 pull        — ①② 모두 실패 시 최후 수단

    Returns:
        로컬에 저장된 WAV 경로 (없으면 None)
    """
    print(f"📥 [iOS] 통화 녹음 파일 수집 중 (udid={ios_udid[:12]}...)...")

    candidates = remote_dir_candidates or IOS_RECORDING_CANDIDATES
    local_path = output_dir / f'iOS_{APP_NAME}_{call_start_ts}.wav'

    # ── ① xcrun devicectl (무선/유선 모두 동작 — 최우선) ──────────────────────
    if ios_udid:
        _dc_result = _pull_ios_via_devicectl(
            ios_udid=ios_udid,
            bundle_id=bundle_id,
            call_start_ts=call_start_ts,
            output_dir=output_dir,
        )
        if _dc_result:
            return _dc_result

    # ── ② Appium driver.pull_file ────────────────────────────────────────────
    if ios_driver is not None:
        for remote_dir in candidates:
            try:
                # 디렉토리 내 파일 목록 조회 — WDA 연결 끊김 시 무한 대기 방지: 15초 타임아웃
                import threading as _th_pull
                _list_result: list = [None]
                _list_done = _th_pull.Event()
                def _do_list(_dir=remote_dir):
                    try:
                        _list_result[0] = ios_driver.execute_script(
                            'mobile: listDirectory',
                            {'bundleId': bundle_id, 'path': _dir}
                        )
                    except Exception as _le:
                        _list_result[0] = _le
                    finally:
                        _list_done.set()
                _th_pull.Thread(target=_do_list, daemon=True).start()
                if not _list_done.wait(timeout=15):
                    print(f"  ⚠️ [iOS] Appium listDirectory 15초 타임아웃 ({remote_dir}) — 건너뜀")
                    continue
                files = _list_result[0]
                if isinstance(files, Exception):
                    print(f"  ⚠️ Appium listDirectory 오류 ({remote_dir}): {files}")
                    continue
                if not isinstance(files, list):
                    continue
                # 가장 최신 WAV/m4a 파일 선택
                audio_files = sorted(
                    [f for f in files if f.lower().endswith(('.wav', '.m4a', '.caf'))],
                    reverse=True  # 이름 역순 (타임스탬프 포함 파일명 가정)
                )
                if not audio_files:
                    continue
                remote_file = f'@{bundle_id}/{remote_dir}{audio_files[0]}'
                print(f"  📦 Appium pull: {remote_file}")
                # pull_file도 WDA 연결 끊김 시 블로킹 — 30초 타임아웃
                _pull_result: list = [None]
                _pull_done = _th_pull.Event()
                def _do_pull(_rf=remote_file):
                    try:
                        _pull_result[0] = ios_driver.pull_file(_rf)
                    except Exception as _pe:
                        _pull_result[0] = _pe
                    finally:
                        _pull_done.set()
                _th_pull.Thread(target=_do_pull, daemon=True).start()
                if not _pull_done.wait(timeout=30):
                    print(f"  ⚠️ [iOS] Appium pull_file 30초 타임아웃 — 건너뜀")
                    continue
                data_b64 = _pull_result[0]
                if isinstance(data_b64, Exception):
                    print(f"  ⚠️ Appium pull_file 오류: {data_b64}")
                    continue
                import base64
                raw = base64.b64decode(data_b64)
                local_path.write_bytes(raw)
                print(f"  ✅ iOS 녹음 저장 (Appium): {local_path}")
                return local_path
            except Exception as e:
                print(f"  ⚠️ Appium pull 실패 ({remote_dir}): {e}")

    # ── ③ tidevice pull (드라이버 없을 때) ───────────────────────────────────
    for remote_dir in candidates:
        try:
            # tidevice 로 앱 컨테이너 내 파일 목록 조회
            list_cmd = ['tidevice', '-u', ios_udid, 'fsync', '--bundle-id', bundle_id,
                        'ls', remote_dir]
            list_out = subprocess.run(
                list_cmd, capture_output=True, text=True, timeout=15
            ).stdout
            audio_files = sorted(
                [f.strip() for f in list_out.splitlines()
                 if f.strip().lower().endswith(('.wav', '.m4a', '.caf'))],
                reverse=True
            )
            if not audio_files:
                continue
            target_file = f'{remote_dir}/{audio_files[0]}'
            pull_cmd = ['tidevice', '-u', ios_udid, 'fsync', '--bundle-id', bundle_id,
                        'pull', target_file, str(local_path)]
            r = subprocess.run(pull_cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and local_path.exists():
                print(f"  ✅ iOS 녹음 저장 (tidevice): {local_path}")
                return local_path
        except Exception as e:
            print(f"  ⚠️ tidevice pull 실패 ({remote_dir}): {e}")

    # ── ④ ideviceinstaller / AFC ─────────────────────────────────────────────
    # (향후 필요 시 확장 자리)

    print(f"  ⚠️ iOS 녹음 파일 수집 실패 — 앱이 녹음 기능을 지원하는지 확인하세요.")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 믹싱
# ─────────────────────────────────────────────────────────────────────────────

def mix_call_audio(
    ios_path: Optional[Path],
    android_path: Optional[Path],
    output_path: Path,
    target_sr: int = SAMPLE_RATE,
) -> Optional[Path]:
    """iOS 녹음 + Android 녹음을 시간 정렬 후 모노 믹스하여 단일 WAV로 저장합니다.

    믹스 전략:
      - 두 트랙을 같은 샘플레이트로 리샘플링
      - 짧은 쪽을 zero-pad해 길이를 맞춤 (통화 종료 시점 차이 보정)
      - 0.5 : 0.5 등분 믹스 (각 트랙 gain = 0.5)
      - 결과는 16-bit PCM mono WAV

    한쪽만 있으면 그쪽만 저장합니다.

    Returns:
        저장된 믹스 WAV 경로 (양쪽 모두 None이면 None)
    """
    available = [(p, label) for p, label in [
        (ios_path,     'iOS'),
        (android_path, 'Android'),
    ] if p is not None and p.exists()]

    if not available:
        print("  ⚠️ [Mix] 믹스할 파일이 없습니다.")
        return None

    # 단일 트랙
    if len(available) == 1:
        src_path, label = available[0]
        print(f"  ℹ️ [Mix] {label} 단일 트랙만 존재 → 변환 후 저장")
        try:
            # m4a / mp4 → soundfile 또는 ffmpeg 으로 디코딩
            if src_path.suffix.lower() in ('.m4a', '.mp4', '.aac', '.3gp', '.amr'):
                audio, sr = _load_any_audio(src_path)
            else:
                audio, sr = _load_wav_float(src_path)
            if sr != target_sr:
                audio = _resample(audio, sr, target_sr)
            _save_wav(output_path, audio, target_sr)
            print(f"  ✅ [Mix] 저장: {output_path} ({len(audio)/target_sr:.1f}s)")
            return output_path
        except Exception as e:
            print(f"  ❌ [Mix] 단일 트랙 저장 실패: {e}")
            return None

    # 두 트랙 믹스
    print(f"  🎛️ [Mix] iOS + Android 믹싱 중...")
    try:
        def _load(p: Path) -> tuple[np.ndarray, int]:
            if p.suffix.lower() in ('.m4a', '.mp4', '.aac', '.3gp', '.amr'):
                return _load_any_audio(p)
            return _load_wav_float(p)

        ios_audio, ios_sr = _load(ios_path)  # type: ignore[arg-type]
        and_audio, and_sr = _load(android_path)  # type: ignore[arg-type]

        # 리샘플링
        if ios_sr != target_sr:
            ios_audio = _resample(ios_audio, ios_sr, target_sr)
            print(f"    iOS 리샘플: {ios_sr}Hz → {target_sr}Hz")
        if and_sr != target_sr:
            and_audio = _resample(and_audio, and_sr, target_sr)
            print(f"    Android 리샘플: {and_sr}Hz → {target_sr}Hz")

        # 길이 맞춤 (zero-pad)
        max_len = max(len(ios_audio), len(and_audio))
        if len(ios_audio) < max_len:
            ios_audio = np.pad(ios_audio, (0, max_len - len(ios_audio)))
        if len(and_audio) < max_len:
            and_audio = np.pad(and_audio, (0, max_len - len(and_audio)))

        # 믹스
        mixed = (ios_audio * 0.5 + and_audio * 0.5)

        _save_wav(output_path, mixed, target_sr)
        print(f"  ✅ [Mix] 저장: {output_path} ({max_len/target_sr:.1f}s)")
        return output_path

    except Exception as e:
        print(f"  ❌ [Mix] 믹싱 실패: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────

class CallAudioCollector:
    """통화 종료 후 iOS/Android 녹음 파일을 수집하고 믹스합니다.

    Args:
        android_udid:       Android(수신단) ADB UDID
        ios_driver:         iOS Appium WebDriver (None이면 tidevice pull 시도)
        ios_udid:           iOS UDID (tidevice pull 시 필요)
        call_start_ts:      통화 시작 시각 'YYYYMMDD_HHMMSS'
        android_rec_path:   Android 단말 내 통화 녹음 저장 경로 (None = 자동 탐색)
        output_dir:         결과 파일 저장 디렉토리 (None = config.RECORDING_DIR/collected)
        android_wait_sec:   Android 녹음 파일 저장 완료 대기 (기본 5초)
    """

    def __init__(
        self,
        android_udid: str,
        ios_driver=None,
        ios_udid: str = '',
        call_start_ts: Optional[str] = None,
        android_rec_path: Optional[str] = None,
        output_dir: Optional[str | Path] = None,
        android_wait_sec: float = 5.0,
    ):
        self.android_udid    = android_udid
        self.ios_driver      = ios_driver
        self.ios_udid        = ios_udid
        self.call_start_ts   = call_start_ts or datetime.now().strftime('%Y%m%d_%H%M%S')
        self.android_rec_path = android_rec_path
        self.android_wait_sec = android_wait_sec

        # 출력 디렉토리 결정
        if output_dir is None:
            try:
                from config import RECORDING_DIR
                output_dir = Path(RECORDING_DIR) / 'collected'
            except (ImportError, AttributeError):
                output_dir = Path.home() / 'Documents' / 'sound' / 'audio_files' / 'collected'
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Android 녹음 경로 config 우선 결정
        if not self.android_rec_path:
            try:
                from config import ANDROID_CALL_RECORDING_PATH
                self.android_rec_path = ANDROID_CALL_RECORDING_PATH
            except (ImportError, AttributeError):
                self.android_rec_path = None   # 자동 탐색

    def collect_and_mix(self) -> dict[str, Optional[Path]]:
        """iOS + Android 녹음 수집 후 믹스.

        Returns:
            {
              'ios_path':     Path | None,   iOS 원본 WAV
              'android_path': Path | None,   Android 원본 WAV
            }
        """
        print(f"\n{'='*60}")
        print(f"🎙️  통화 녹음 수집 시작 (ts={self.call_start_ts})")
        print(f"{'='*60}")

        ios_path     = self._collect_ios()
        android_path = self._collect_android()

        print(f"{'='*60}")
        print(f"📋 수집 결과:")
        print(f"   iOS 앱:  {ios_path or '— (건너뜀)'}")
        print(f"   Android: {android_path or '— (없음)'}")
        print(f"{'='*60}\n")

        return {
            'ios_path':     ios_path,
            'android_path': android_path,
        }

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _collect_ios(self) -> Optional[Path]:
        """iOS 녹음 파일 수집 (config.IOS_APP_RECORDING_ENABLED 확인)."""
        try:
            from config import IOS_APP_RECORDING_ENABLED
            if not IOS_APP_RECORDING_ENABLED:
                print("  ℹ️ [iOS] IOS_APP_RECORDING_ENABLED=False → 수집 건너뜀")
                return None
        except (ImportError, AttributeError):
            pass  # 기본: 수집 시도

        if not self.ios_driver and not self.ios_udid:
            print("  ⚠️ [iOS] driver/udid 없음 → iOS 녹음 수집 건너뜀")
            return None

        try:
            from config import IOS_APP_RECORDING_REMOTE_DIR
            remote_dirs = [IOS_APP_RECORDING_REMOTE_DIR]
        except (ImportError, AttributeError):
            remote_dirs = None

        return collect_ios_recording(
            ios_driver=self.ios_driver,
            ios_udid=self.ios_udid,
            call_start_ts=self.call_start_ts,
            output_dir=self.output_dir,
            remote_dir_candidates=remote_dirs,
        )

    def _collect_android(self) -> Optional[Path]:
        """Android 통화 녹음 파일 수집. m4a이면 WAV로 변환 후 반환."""
        if not self.android_udid:
            print("  ⚠️ [Android] udid 없음 → Android 녹음 수집 건너뜀")
            return None

        raw_path = collect_android_recording(
            udid=self.android_udid,
            call_start_ts=self.call_start_ts,
            custom_path=self.android_rec_path,
            output_dir=self.output_dir,
            wait_sec=self.android_wait_sec,
        )

        if raw_path is None:
            return None

        # m4a / mp4 / aac 등 비WAV 포맷이면 FFmpeg으로 WAV 변환
        if raw_path.suffix.lower() not in ('.wav',):
            wav_path = raw_path.with_suffix('.wav')
            print(f"  🔄 [Android] {raw_path.suffix} → WAV 변환 중: {wav_path.name}")
            try:
                audio, sr = _load_any_audio(raw_path)
                _save_wav(wav_path, audio, sr)
                print(f"  ✅ [Android] WAV 변환 완료: {wav_path} ({len(audio)/sr:.1f}s)")
                return wav_path
            except Exception as e:
                print(f"  ❌ [Android] WAV 변환 실패: {e} → 원본 반환")
                return raw_path  # 변환 실패 시 원본 유지

        return raw_path
