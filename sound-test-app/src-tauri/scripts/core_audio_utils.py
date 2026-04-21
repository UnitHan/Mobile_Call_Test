"""
core_audio_utils.py
────────────────────────────────────────────────────────────────────────────
macOS 오디오 장치를 SwitchAudioSource CLI + sounddevice로 제어하는 유틸리티.

▶ ctypes/CoreAudio 직접 접근 대신 brew install switchaudio-osx 사용
  → macOS 버전 무관하게 안정적으로 동작

▶ 주요 기능:
  - 현재 macOS 기본 출력/입력 장치 조회·변경
  - 테스트 시작 전 USB 출력 장치 고정, 종료 후 복원
  - USB 장치 현황 + locationID(ioreg) 출력

▶ SwitchAudioSource 설치 확인:
    which SwitchAudioSource   # /opt/homebrew/bin/SwitchAudioSource
    (없으면: brew install switchaudio-osx)
────────────────────────────────────────────────────────────────────────────
"""

import subprocess
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# 공통 USB 감지 모듈 (DRY 제거 — audio_handler.py 와 중복 제거)
# ──────────────────────────────────────────────────────────────────────────────
from usb_audio_devices import (
    get_usb_audio_output_indices,
    get_usb_audio_input_indices,
    get_usb_location_ids as _get_ioreg_location_ids,  # 하위 호환 alias
)


# ── SwitchAudioSource 경로 자동 탐색 ─────────────────────────────────────
def _find_sas() -> Optional[str]:
    for path in [
        '/opt/homebrew/bin/SwitchAudioSource',
        '/usr/local/bin/SwitchAudioSource',
    ]:
        try:
            subprocess.run([path, '-h'], capture_output=True, timeout=2)
            return path
        except Exception:
            pass
    try:
        result = subprocess.run(['which', 'SwitchAudioSource'],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


_SAS = _find_sas()


# ── SwitchAudioSource 기반 기본 장치 조회·변경 ───────────────────────────
def get_default_output_name() -> str:
    """현재 macOS 기본 출력 장치 이름."""
    if not _SAS:
        return ''
    try:
        return subprocess.check_output(
            [_SAS, '-c', '-t', 'output'], text=True, timeout=3
        ).strip()
    except Exception:
        return ''


def get_default_input_name() -> str:
    """현재 macOS 기본 입력 장치 이름."""
    if not _SAS:
        return ''
    try:
        return subprocess.check_output(
            [_SAS, '-c', '-t', 'input'], text=True, timeout=3
        ).strip()
    except Exception:
        return ''


def set_default_output(name: str) -> bool:
    """macOS 기본 출력 장치를 이름으로 설정."""
    if not _SAS:
        return False
    try:
        ret = subprocess.run(
            [_SAS, '-s', name, '-t', 'output'],
            capture_output=True, timeout=3
        )
        return ret.returncode == 0
    except Exception:
        return False


def set_default_input(name: str) -> bool:
    """macOS 기본 입력 장치를 이름으로 설정."""
    if not _SAS:
        return False
    try:
        ret = subprocess.run(
            [_SAS, '-s', name, '-t', 'input'],
            capture_output=True, timeout=3
        )
        return ret.returncode == 0
    except Exception:
        return False


# ── 테스트 전/후 장치 고정 ────────────────────────────────────────────────
_saved_output_name: Optional[str] = None
_saved_input_name:  Optional[str] = None
_saved_input_volume: Optional[int] = None


def _get_input_volume() -> int:
    """맥북 마이크 입력 볼륨(0-100) 반환."""
    try:
        result = subprocess.check_output(
            ['osascript', '-e', 'input volume of (get volume settings)'],
            text=True, timeout=3
        ).strip()
        return int(result)
    except Exception:
        return 50


def _set_input_volume(vol: int):
    """맥북 마이크 입력 볼륨(0-100) 설정."""
    try:
        subprocess.run(
            ['osascript', '-e', f'set volume input volume {vol}'],
            capture_output=True, timeout=3
        )
    except Exception:
        pass


def lock_usb_output_for_test(verbose: bool = True) -> bool:
    """
    테스트 시작 전 현재 macOS 기본 입출력 장치 상태를 저장만 함.
    맥북 내장 마이크가 기본 입력이고 USB 오디오 입력 장치가 없을 때만 볼륨 뮤트.

    ⚠️ USB 오디오 입력 장치(G8 등)가 연결된 경우에는 뮤트 스킵:
       macOS 'set volume input volume 0' 명령이 CoreAudio 전체에 영향을 줄 수 있어
       G8 녹음 레벨이 0이 되는 문제를 방지합니다.

    ⚠️ 순환 버그 방지:
       이전 실행에서 프로세스 강제 종료로 인해 input volume=0이 고착된 경우,
       0을 그대로 저장·복원하면 영구히 0에 갇히게 됩니다.
       저장값이 0이고 USB 녹음 장치가 있으면 분리 기본값(60)으로 복원합니다.

    - 출력(OUTPUT): 변경 없음
    - 입력(INPUT) : 변경 없음
    - 입력 볼륨   : USB 입력 장치 없는 내장 마이크 전용 환경에서만 0으로 뮤트
    """
    import atexit
    global _saved_output_name, _saved_input_name, _saved_input_volume

    _saved_output_name  = get_default_output_name()
    _saved_input_name   = get_default_input_name()
    current_vol         = _get_input_volume()

    # USB 오디오 입력 장치가 하나라도 연결되어 있으면 뮤트 스킵
    # (G8 등 USB 장치가 녹음에 사용되므로 시스템 입력 볼륨 변경 금지)
    _has_usb_input = bool(get_usb_audio_input_indices())
    _is_usb_default = (
        _saved_input_name is not None and
        any(kw in _saved_input_name for kw in ('Sound Blaster', 'G8', 'USB'))
    )
    _skip_mute = _has_usb_input or _is_usb_default

    if _skip_mute:
        if verbose:
            reason = 'USB 입력 장치 연결됨' if _has_usb_input else 'USB 기본 입력 감지'
            print(f"         macOS default output -> '{_saved_output_name}' (변경 없음)")
            print(f"         macOS default input  -> '{_saved_input_name}' ({reason})")
            print(f"ℹ️  USB 오디오 감지 → 입력 볼륨 뮤트 스킵 (녹음 레벨 보호, 현재값: {current_vol})")
        # 뮤트 안 함 → 복원 불필요
        _saved_input_volume = None
    else:
        # 내장 마이크만 있는 환경 → Siri 트리거 방지용 뮤트
        # 순환 버그 방지: 저장값이 0이면 고착 상태이므로 기본값 60 사용
        restore_vol = current_vol if current_vol > 0 else 60
        _saved_input_volume = restore_vol
        _set_input_volume(0)
        if verbose:
            print(f"         macOS default output -> '{_saved_output_name}' (변경 없음)")
            print(f"         macOS default input  -> '{_saved_input_name}' (변경 없음)")
            print(f"🔇 MacBook 마이크 입력 볼륨 뮤트 (0) — Siri 트리거 방지  (복원 예약: {restore_vol})")
        # atexit 등록: 프로세스 강제 종료 시에도 볼륨 복원 시도
        atexit.register(lambda: _set_input_volume(restore_vol))

    return True


def restore_default_devices(verbose: bool = True):
    """테스트 종료 후 원래 MacBook 스피커/마이크로 복원 + 마이크 볼륨 복원.

    저장된 값과 현재 값이 동일하면 SwitchAudioSource 호출을 생략합니다.
    → macOS Core Audio 불필요한 재열거 방지 (sounddevice index 변경 예방)
    """
    global _saved_output_name, _saved_input_name, _saved_input_volume

    if _saved_output_name:
        current_out = get_default_output_name()
        if current_out != _saved_output_name:
            ok = set_default_output(_saved_output_name)
            if verbose:
                status = 'OK' if ok else 'FAIL'
                print(f"restored macOS default output -> '{_saved_output_name}'  [{status}]")
        else:
            if verbose:
                print(f"macOS default output 변경 없음 ('{_saved_output_name}') → SwitchAudioSource 생략")

    if _saved_input_name:
        current_in = get_default_input_name()
        if current_in != _saved_input_name:
            set_default_input(_saved_input_name)

    if _saved_input_volume is not None:
        _set_input_volume(_saved_input_volume)
        if verbose:
            print(f"🔊 MacBook 마이크 입력 볼륨 복원: {_saved_input_volume}")
    elif verbose:
        print("ℹ️  입력 볼륨 변경 없었음 (USB 오디오 장치 사용 중) → 복원 스킵")

    _saved_output_name  = None
    _saved_input_name   = None
    _saved_input_volume = None


# ── 현황 출력 ─────────────────────────────────────────────────────────────
def print_status():
    """오디오 장치 현황 출력 (디버깅용)."""
    try:
        import sounddevice as sd
        devs = list(sd.query_devices())
    except Exception:
        devs = []

    locs    = _get_ioreg_location_ids()
    usb_out = get_usb_audio_output_indices()
    usb_in  = get_usb_audio_input_indices()
    cur_out = get_default_output_name()
    cur_in  = get_default_input_name()

    print(f"\n{'='*62}")
    print("  Core Audio / SwitchAudioSource 현황")
    print(f"{'='*62}")
    print(f"  macOS 기본 출력 : '{cur_out}'")
    print(f"  macOS 기본 입력 : '{cur_in}'")
    sas_info = ('설치됨  ' + _SAS) if _SAS else '미설치  (brew install switchaudio-osx)'
    print(f"  SwitchAudioSource: {sas_info}")

    print(f"\n  USB 출력 장치 ({len(usb_out)}개):")
    for order, idx in enumerate(usb_out, 1):
        loc    = locs[order - 1] if order - 1 < len(locs) else None
        name   = devs[idx]['name'] if idx < len(devs) else '?'
        sr     = int(devs[idx]['default_samplerate']) if idx < len(devs) else 0
        loc_s  = hex(loc) if loc else 'N/A'
        print(f"    [{order}] sd_index={idx:3d}  locationID={loc_s:12s}"
              f"  native_sr={sr:6d}Hz  '{name}'")

    print(f"\n  USB 입력 장치 ({len(usb_in)}개):")
    for order, idx in enumerate(usb_in, 1):
        name = devs[idx]['name'] if idx < len(devs) else '?'
        sr   = int(devs[idx]['default_samplerate']) if idx < len(devs) else 0
        print(f"    [{order}] sd_index={idx:3d}  native_sr={sr:6d}Hz  '{name}'")

    print(f"\n  ioreg locationIDs (정렬): {[hex(l) for l in locs]}")
    print(f"{'='*62}\n")


if __name__ == '__main__':
    print_status()

    print("잠금 테스트 실행 (5초 후 복원)...")
    lock_usb_output_for_test()
    import time
    time.sleep(5)
    restore_default_devices()
