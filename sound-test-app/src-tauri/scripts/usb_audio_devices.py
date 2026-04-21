"""
usb_audio_devices.py
──────────────────────────────────────────────────────────────────────────────
macOS USB 오디오 장치 감지 공통 모듈.

audio_handler.py와 core_audio_utils.py에 중복된 USB 장치 탐색 로직을
이 단일 모듈에 통합합니다.

공개 API:
  get_usb_audio_product_names() → set[str]
  get_usb_audio_output_indices() → list[int]
  get_usb_audio_input_indices()  → list[int]
  get_usb_location_ids()         → list[int]
  list_usb_status()              → None  (디버그 출력)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import re
import subprocess
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# ioreg 기반 장치 이름·LocationID 조회
# ─────────────────────────────────────────────────────────────────────────────

def get_usb_audio_product_names() -> set[str]:
    """ioreg에서 연결된 USB 오디오/사운드 장치의 제품명 집합 반환.

    제품명에 'audio', 'sound', 'connect'(대소문자 무관)가 포함된 장치를 모두 감지.
    예: 'USB Audio Device', 'Sound Blaster G8', 'CONNECT 6'
    """
    try:
        raw = subprocess.check_output(
            ['ioreg', '-r', '-c', 'IOUSBInterface', '-l'], timeout=5
        ).decode(errors='ignore')
        names: set[str] = set()
        for m in re.finditer(r'"USB Product Name" = "([^"]+)"', raw):
            name = m.group(1)
            low = name.lower()
            if 'audio' in low or 'sound' in low or 'connect' in low or 'lewitt' in low:
                names.add(name)
        return names
    except Exception:
        return set()


def get_usb_location_ids() -> list[int]:
    """ioreg에서 연결된 USB 오디오 장치의 locationID를 정렬된 리스트로 반환.

    장치가 추가/제거되면 순서가 바뀔 수 있으므로 매 호출 시 재조회합니다.
    """
    return [lid for lid, _ in get_usb_audio_device_info()]


def get_usb_audio_device_info() -> list[tuple[int, str]]:
    """ioreg에서 USB 오디오 장치의 (locationID, 제품명) 목록을 locationID 오름차순으로 반환.

    각 물리 포트(locationID)에 하나의 항목만 포함합니다.
    모니터/허브의 비-오디오 USB 장치는 제외됩니다.
    """
    try:
        raw = subprocess.check_output(
            ['ioreg', '-r', '-c', 'IOUSBInterface', '-l'], timeout=5
        ).decode(errors='ignore')
        seen: set[int] = set()
        result: list[tuple[int, str]] = []
        for m in re.finditer(
            r'"USB Product Name" = "([^"]*(?:audio|sound|connect|lewitt)[^"]*)"'
            r'[^}]*?"locationID" = (\d+)',
            raw, re.DOTALL | re.IGNORECASE
        ):
            name = m.group(1).strip()
            lid  = int(m.group(2))
            if lid not in seen:
                seen.add(lid)
                result.append((lid, name))
        result.sort()          # locationID 오름차순 = macOS Core Audio 등록 순서
        return result
    except Exception:
        return []


def build_locationid_sdindex_map(input_mode: bool = False) -> dict[int, int]:
    """locationID → sounddevice index 직접 매핑을 반환합니다.

    모니터/디스플레이 오디오 장치가 추가되어도 G8 등 실제 USB 오디오 장치의
    매핑이 깨지지 않도록 **이름 그룹별 정렬 순서**로 매핑합니다.

    macOS Core Audio는 같은 제품명을 가진 장치를 locationID 오름차순으로
    sounddevice에 등록하므로, 같은 이름 그룹 내에서 정렬 순서가 일치합니다.

    Args:
        input_mode: True → 입력 채널 기준, False → 출력 채널 기준

    Returns:
        {locationID: sd_index} — 매핑 불가 항목은 포함되지 않음
    """
    import sounddevice as sd
    from collections import defaultdict

    # ── 1. ioreg에서 (locationID, 이름) 목록 ─────────────────────────────────
    ioreg_devs = get_usb_audio_device_info()   # [(lid, name), ...] sorted by lid
    if not ioreg_devs:
        return {}

    # ioreg에 등재된 제품명 집합
    ioreg_names: set[str] = {name for _, name in ioreg_devs}

    # ── 2. sounddevice에서 후보 인덱스 수집 (이름으로 매칭) ──────────────────
    ch_key = 'max_input_channels' if input_mode else 'max_output_channels'
    all_sd = list(sd.query_devices())

    sd_by_name: dict[str, list[int]] = defaultdict(list)
    for sd_idx, dev in enumerate(all_sd):
        if dev[ch_key] == 0:
            continue
        matched_name: Optional[str] = None
        # 정확 매칭 우선
        if dev['name'] in ioreg_names:
            matched_name = dev['name']
        else:
            # 부분 포함 매칭 (예: 'Sound Blaster G8 USB-1' ↔ 'Sound Blaster G8 USB')
            for ioreg_name in ioreg_names:
                if ioreg_name in dev['name'] or dev['name'] in ioreg_name:
                    matched_name = ioreg_name
                    break
            else:
                # 이름 미매칭이지만 sounddevice 이름에 'USB Audio'가 있으면 generic 그룹
                if 'USB Audio' in dev['name']:
                    matched_name = '__usb_audio_generic__'
        if matched_name is not None:
            sd_by_name[matched_name].append(sd_idx)

    # 각 이름 그룹 내 sd_index 정렬 (Core Audio 등록 = locationID 순서와 일치)
    for name in sd_by_name:
        sd_by_name[name].sort()

    # ── 3. ioreg 순서 기준으로 (locationID → sd_index) 매핑 ──────────────────
    name_ptr: dict[str, int] = defaultdict(int)
    result: dict[int, int] = {}
    for lid, name in ioreg_devs:
        group = sd_by_name.get(name, [])
        ptr   = name_ptr[name]
        if ptr < len(group):
            result[lid] = group[ptr]
        name_ptr[name] += 1

    return result


# ─────────────────────────────────────────────────────────────────────────────
# sounddevice 기반 인덱스 조회
# ─────────────────────────────────────────────────────────────────────────────

def get_usb_audio_output_indices() -> list[int]:
    """현재 연결된 USB 오디오 출력 장치의 sounddevice index 목록(정렬).

    macOS Core Audio는 USB 포트 locationID 오름차순으로 장치를 등록하므로
    이 순서는 USB 포트 배치를 반영합니다.
    """
    try:
        import sounddevice as sd
        usb_names = get_usb_audio_product_names()
        return sorted([
            i for i, d in enumerate(sd.query_devices())
            if d['max_output_channels'] > 0
            and (d['name'] in usb_names or 'USB Audio' in d['name'])
        ])
    except Exception:
        return []


def get_usb_audio_input_indices() -> list[int]:
    """현재 연결된 USB 오디오 입력 장치의 sounddevice index 목록(정렬)."""
    try:
        import sounddevice as sd
        usb_names = get_usb_audio_product_names()
        return sorted([
            i for i, d in enumerate(sd.query_devices())
            if d['max_input_channels'] > 0
            and (d['name'] in usb_names or 'USB Audio' in d['name'])
        ])
    except Exception:
        return []


def resolve_usb_device_index(
    location_id: Optional[int] = None,
    usb_port_order: int = 1,
    device_index_fallback: Optional[int] = None,
    role_label: str = '?',
) -> Optional[int]:
    """USB 오디오 출력 장치의 sounddevice index를 결정합니다.

    모니터/디스플레이 오디오가 추가되어도 깨지지 않는 이름-그룹별 매핑 사용.

    우선순위:
      1. location_id → build_locationid_sdindex_map(출력 모드) 직접 조회
      2. usb_port_order → N번째 USB 출력 장치 (fallback)
      3. device_index_fallback → 설정값 그대로 사용
    """
    # ── 방법 1: name-aware locationID 직접 매핑 ─────────────────────────────
    if location_id is not None:
        mapping = build_locationid_sdindex_map(input_mode=False)
        if location_id in mapping:
            resolved = mapping[location_id]
            print(f"🔌 [{role_label}] locationID {location_id} → sd_out_index {resolved}")
            return resolved
        loc_ids = list(mapping.keys())
        print(f"⚠️  [{role_label}] locationID {location_id} 매핑 미발견 "
              f"(발견된 IDs: {loc_ids}) → port_order 폴백")

    # ── 방법 2: N번째 USB 출력 장치 ─────────────────────────────────────────
    usb_out = get_usb_audio_output_indices()
    if not usb_out:
        print(f"⚠️  [{role_label}] USB Audio 출력 장치 없음 → fallback={device_index_fallback}")
        return device_index_fallback
    idx = usb_port_order - 1
    if idx < len(usb_out):
        resolved = usb_out[idx]
        print(f"🔌 [{role_label}] usb_port_order={usb_port_order} → sd_out_index {resolved}")
        return resolved

    # ── 방법 3: fallback ─────────────────────────────────────────────────────
    print(f"⚠️  [{role_label}] fallback index={device_index_fallback} 사용")
    return device_index_fallback


def resolve_usb_input_device_index(
    location_id: Optional[int] = None,
    usb_port_order: int = 1,
    device_index_fallback: Optional[int] = None,
    role_label: str = '?',
) -> Optional[int]:
    """USB 오디오 입력 장치의 sounddevice index를 결정합니다.

    모니터/디스플레이 오디오가 추가되어도 깨지지 않는 이름-그룹별 매핑 사용.

    우선순위:
      1. location_id → build_locationid_sdindex_map(입력 모드) 직접 조회
      2. usb_port_order → N번째 USB 입력 장치 (fallback)
      3. device_index_fallback → 설정값 그대로 사용
    """
    # ── 방법 1: name-aware locationID 직접 매핑 ─────────────────────────────
    if location_id is not None:
        mapping = build_locationid_sdindex_map(input_mode=True)
        if location_id in mapping:
            resolved = mapping[location_id]
            print(f"🎙️ [{role_label}] locationID {location_id} → sd_in_index {resolved}")
            return resolved
        loc_ids = list(mapping.keys())
        print(f"⚠️  [{role_label}] locationID {location_id} 매핑 미발견 "
              f"(발견된 IDs: {loc_ids}) → port_order 폴백")

    # ── 방법 2: N번째 USB 입력 장치 ─────────────────────────────────────────
    usb_in = get_usb_audio_input_indices()
    if not usb_in:
        print(f"⚠️  [{role_label}] USB Audio 입력 장치 없음 → fallback={device_index_fallback}")
        return device_index_fallback
    idx = usb_port_order - 1
    if idx < len(usb_in):
        resolved = usb_in[idx]
        print(f"🎙️ [{role_label}] usb_port_order={usb_port_order} → sd_in_index {resolved}")
        return resolved

    # ── 방법 3: fallback ─────────────────────────────────────────────────────
    print(f"⚠️  [{role_label}] fallback input_index={device_index_fallback} 사용")
    return device_index_fallback


def list_usb_status(verbose: bool = True) -> dict:
    """현재 USB 오디오 장치 현황을 출력하고 dict로 반환합니다 (디버그용)."""
    try:
        import sounddevice as sd
        devices = list(sd.query_devices())
    except Exception:
        devices = []

    out_map = build_locationid_sdindex_map(input_mode=False)
    in_map  = build_locationid_sdindex_map(input_mode=True)
    ioreg_devs = get_usb_audio_device_info()

    if verbose:
        print("\n── USB Audio 장치 현황 (name-aware 매핑) ───────────────────")
        for lid, name in ioreg_devs:
            out_idx = out_map.get(lid)
            in_idx  = in_map.get(lid)
            sr_out = int(devices[out_idx]['default_samplerate']) if out_idx is not None and out_idx < len(devices) else '-'
            sr_in  = int(devices[in_idx]['default_samplerate'])  if in_idx  is not None and in_idx  < len(devices) else '-'
            print(f"  locationID={lid}  OUT=sd{out_idx}(sr={sr_out})  IN=sd{in_idx}(sr={sr_in})  '{name}'")
        print(f"  전체 sounddevice 장치:")
        for i, d in enumerate(devices):
            ch = f"in={d['max_input_channels']} out={d['max_output_channels']}"
            print(f"    idx={i:2d}  {ch}  '{d['name']}'")
        print("──────────────────────────────────────────────────────\n")

    return {
        'output_map': out_map,
        'input_map':  in_map,
        'ioreg_devs': ioreg_devs,
    }


def scan_audio_interfaces() -> list[dict]:
    """현재 연결된 USB 오디오 인터페이스 목록을 반환합니다.

    Returns:
        [
          {
            'location_id': int,     # ioreg locationID (USB 포트 고유 식별자)
            'name': str,            # 장치 이름 (예: 'CONNECT 6')
            'sd_out_index': int,    # sounddevice 출력 인덱스
            'sd_in_index': int,     # sounddevice 입력 인덱스
            'out_channels': int,    # 최대 출력 채널 수
            'in_channels': int,     # 최대 입력 채널 수
            'sample_rate': int,     # 기본 샘플레이트
          },
          ...
        ]
    """
    try:
        import sounddevice as sd
    except ImportError:
        return []

    devices = list(sd.query_devices())
    out_map = build_locationid_sdindex_map(input_mode=False)
    in_map  = build_locationid_sdindex_map(input_mode=True)
    ioreg_devs = get_usb_audio_device_info()

    result = []
    for lid, name in ioreg_devs:
        out_idx = out_map.get(lid)
        in_idx  = in_map.get(lid)
        ref_idx = out_idx if out_idx is not None else in_idx
        dev = devices[ref_idx] if ref_idx is not None and ref_idx < len(devices) else {}
        result.append({
            'location_id':  lid,
            'name':         name,
            'sd_out_index': out_idx,
            'sd_in_index':  in_idx,
            'out_channels': int(dev.get('max_output_channels', 0)),
            'in_channels':  int(dev.get('max_input_channels', 0)),
            'sample_rate':  int(dev.get('default_samplerate', 0)),
        })
    return result


def save_audio_interface_config(android_location_id: int, ios_location_id: int) -> dict:
    """config.py의 android_a / ios_b locationID와 device_index를 업데이트합니다.

    Args:
        android_location_id: android_a 슬롯에 할당할 CONNECT 6의 locationID
        ios_location_id:     ios_b 슬롯에 할당할 CONNECT 6의 locationID

    Returns:
        {'ok': bool, 'message': str, 'android': {...}, 'ios': {...}}
    """
    import re
    from pathlib import Path

    out_map = build_locationid_sdindex_map(input_mode=False)
    in_map  = build_locationid_sdindex_map(input_mode=True)

    android_out = out_map.get(android_location_id)
    android_in  = in_map.get(android_location_id)
    ios_out     = out_map.get(ios_location_id)
    ios_in      = in_map.get(ios_location_id)

    if android_out is None:
        return {'ok': False, 'message': f'android locationID {android_location_id} 를 찾을 수 없습니다.'}
    if ios_out is None:
        return {'ok': False, 'message': f'ios locationID {ios_location_id} 를 찾을 수 없습니다.'}

    # config.py 경로
    config_path = Path(__file__).resolve().parent / 'config.py'
    if not config_path.exists():
        return {'ok': False, 'message': f'config.py를 찾을 수 없습니다: {config_path}'}

    text = config_path.read_text(encoding='utf-8')

    def _replace_device_block(src: str, role: str, loc_id: int, dev_idx: int) -> str:
        """AUDIO_DEVICES[role] 블록의 location_id와 device_index를 교체합니다."""
        # role 블록 시작부터 닫는 중괄호까지를 탐색
        # 패턴: 'role': {\n ... 'location_id': NNNN, ... 'device_index': N, ...}
        block_pat = re.compile(
            r"('" + role + r"'\s*:\s*\{[^}]*?'location_id'\s*:\s*)\d+"
            r"([^}]*?'device_index'\s*:\s*)\d+",
            re.DOTALL,
        )
        if block_pat.search(src):
            return block_pat.sub(
                lambda m: m.group(1) + str(loc_id) + m.group(2) + str(dev_idx),
                src,
            )
        # device_index가 location_id보다 앞에 있는 경우
        block_pat2 = re.compile(
            r"('" + role + r"'\s*:\s*\{[^}]*?'device_index'\s*:\s*)\d+"
            r"([^}]*?'location_id'\s*:\s*)\d+",
            re.DOTALL,
        )
        if block_pat2.search(src):
            return block_pat2.sub(
                lambda m: m.group(1) + str(dev_idx) + m.group(2) + str(loc_id),
                src,
            )
        return src

    new_text = _replace_device_block(text, 'android_a', android_location_id, android_out)
    new_text = _replace_device_block(new_text, 'ios_b',     ios_location_id,     ios_out)

    if new_text == text:
        return {'ok': False, 'message': 'config.py 패턴 매칭 실패 — 수동 수정이 필요합니다.'}

    config_path.write_text(new_text, encoding='utf-8')

    return {
        'ok': True,
        'message': f'config.py 업데이트 완료',
        'android': {'location_id': android_location_id, 'sd_in': android_in, 'sd_out': android_out},
        'ios':     {'location_id': ios_location_id,     'sd_in': ios_in,     'sd_out': ios_out},
    }


def get_audio_interface_config() -> dict:
    """config.py에 저장된 android_a / ios_b locationID를 반환합니다.

    Returns:
        {'android_location_id': int, 'ios_location_id': int}
        또는 파일이 없거나 파싱 실패 시 None
    """
    import re
    from pathlib import Path

    config_path = Path(__file__).resolve().parent / 'config.py'
    if not config_path.exists():
        return None

    text = config_path.read_text(encoding='utf-8')

    def _extract(role: str) -> int | None:
        m = re.search(
            r"'" + role + r"'\s*:\s*\{[^}]*?'location_id'\s*:\s*(\d+)",
            text,
            re.DOTALL,
        )
        return int(m.group(1)) if m else None

    android_loc = _extract('android_a')
    ios_loc     = _extract('ios_b')

    if android_loc is None or ios_loc is None:
        return None

    return {'android_location_id': android_loc, 'ios_location_id': ios_loc}

