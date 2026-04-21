"""
tests/test_usb_audio_devices.py
──────────────────────────────────────────────────────────────────────────────
usb_audio_devices 모듈 단위 테스트.

모든 외부 의존성(ioreg subprocess, sounddevice)을 mock으로 대체합니다.
"""
import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# 테스트용 ioreg 출력 샘플
# ─────────────────────────────────────────────────────────────────────────────
IOREG_TWO_USB_AUDIO = b"""
| +-o IOUSBInterface
|   "USB Product Name" = "USB Audio Device"
|   "locationID" = 34734080
| +-o IOUSBInterface
|   "USB Product Name" = "USB Audio Device"
|   "locationID" = 34799616
"""

IOREG_ONE_USB_AUDIO = b"""
| +-o IOUSBInterface
|   "USB Product Name" = "USB Audio Device"
|   "locationID" = 34734080
"""

IOREG_NO_USB_AUDIO = b"""
| +-o IOUSBInterface
|   "USB Product Name" = "Apple Keyboard"
|   "locationID" = 12345678
"""


def _make_sd_devices(usb_count=2):
    """sounddevice.query_devices() 반환값 시뮬레이션."""
    devices = [
        {'name': 'MacBook Pro Speakers', 'max_output_channels': 2,
         'max_input_channels': 0, 'default_samplerate': 48000.0},
        {'name': 'MacBook Pro Microphone', 'max_output_channels': 0,
         'max_input_channels': 1, 'default_samplerate': 48000.0},
    ]
    for i in range(usb_count):
        devices.append({
            'name': 'USB Audio Device',
            'max_output_channels': 2,
            'max_input_channels': 1,
            'default_samplerate': 44100.0,
        })
    return devices


# ─────────────────────────────────────────────────────────────────────────────
# get_usb_audio_product_names
# ─────────────────────────────────────────────────────────────────────────────
class TestGetUsbAudioProductNames:
    def test_returns_usb_audio_names(self):
        with patch('subprocess.check_output', return_value=IOREG_TWO_USB_AUDIO):
            from usb_audio_devices import get_usb_audio_product_names
            names = get_usb_audio_product_names()
        assert 'USB Audio Device' in names

    def test_ignores_non_audio_devices(self):
        with patch('subprocess.check_output', return_value=IOREG_NO_USB_AUDIO):
            from usb_audio_devices import get_usb_audio_product_names
            names = get_usb_audio_product_names()
        assert len(names) == 0

    def test_subprocess_failure_returns_empty_set(self):
        with patch('subprocess.check_output', side_effect=Exception("ioreg failed")):
            from usb_audio_devices import get_usb_audio_product_names
            names = get_usb_audio_product_names()
        assert names == set()


# ─────────────────────────────────────────────────────────────────────────────
# get_usb_location_ids
# ─────────────────────────────────────────────────────────────────────────────
class TestGetUsbLocationIds:
    def test_returns_sorted_location_ids(self):
        with patch('subprocess.check_output', return_value=IOREG_TWO_USB_AUDIO):
            from usb_audio_devices import get_usb_location_ids
            ids = get_usb_location_ids()
        assert ids == sorted(ids)
        assert len(ids) == 2

    def test_returns_empty_on_no_audio_devices(self):
        with patch('subprocess.check_output', return_value=IOREG_NO_USB_AUDIO):
            from usb_audio_devices import get_usb_location_ids
            ids = get_usb_location_ids()
        assert ids == []

    def test_returns_empty_on_subprocess_error(self):
        with patch('subprocess.check_output', side_effect=OSError("no ioreg")):
            from usb_audio_devices import get_usb_location_ids
            ids = get_usb_location_ids()
        assert ids == []


# ─────────────────────────────────────────────────────────────────────────────
# get_usb_audio_output_indices
# ─────────────────────────────────────────────────────────────────────────────
class TestGetUsbAudioOutputIndices:
    def test_returns_usb_output_indices(self):
        devices = _make_sd_devices(usb_count=2)
        with patch('subprocess.check_output', return_value=IOREG_TWO_USB_AUDIO), \
             patch('sounddevice.query_devices', return_value=devices):
            from usb_audio_devices import get_usb_audio_output_indices
            indices = get_usb_audio_output_indices()
        assert len(indices) == 2
        # USB devices are at index 2, 3; MacBook at 0, 1
        assert 0 not in indices  # MacBook Pro Speakers는 USB가 아님
        assert 1 not in indices  # MacBook Pro Microphone는 출력 아님

    def test_returns_empty_on_no_usb(self):
        devices = _make_sd_devices(usb_count=0)
        with patch('subprocess.check_output', return_value=IOREG_NO_USB_AUDIO), \
             patch('sounddevice.query_devices', return_value=devices):
            from usb_audio_devices import get_usb_audio_output_indices
            indices = get_usb_audio_output_indices()
        assert indices == []

    def test_returns_sorted_indices(self):
        devices = _make_sd_devices(usb_count=2)
        with patch('subprocess.check_output', return_value=IOREG_TWO_USB_AUDIO), \
             patch('sounddevice.query_devices', return_value=devices):
            from usb_audio_devices import get_usb_audio_output_indices
            indices = get_usb_audio_output_indices()
        assert indices == sorted(indices)


# ─────────────────────────────────────────────────────────────────────────────
# resolve_usb_device_index
# ─────────────────────────────────────────────────────────────────────────────
class TestResolveUsbDeviceIndex:
    def _setup_two_usb(self):
        """USB 2개 연결 상황 mock."""
        devices = _make_sd_devices(usb_count=2)
        return devices

    def test_usb_port_order_1_returns_first_usb(self):
        devices = self._setup_two_usb()
        with patch('subprocess.check_output', return_value=IOREG_TWO_USB_AUDIO), \
             patch('sounddevice.query_devices', return_value=devices):
            from usb_audio_devices import resolve_usb_device_index
            idx = resolve_usb_device_index(
                location_id=None,
                usb_port_order=1,
                device_index_fallback=None,
                role_label='test_role',
            )
        assert idx == 2  # 첫 번째 USB 장치 (MacBook 장치들 제외)

    def test_usb_port_order_2_returns_second_usb(self):
        devices = self._setup_two_usb()
        with patch('subprocess.check_output', return_value=IOREG_TWO_USB_AUDIO), \
             patch('sounddevice.query_devices', return_value=devices):
            from usb_audio_devices import resolve_usb_device_index
            idx = resolve_usb_device_index(
                location_id=None,
                usb_port_order=2,
                device_index_fallback=None,
                role_label='test_role',
            )
        assert idx == 3  # 두 번째 USB 장치

    def test_fallback_when_no_usb_devices(self):
        devices = _make_sd_devices(usb_count=0)
        with patch('subprocess.check_output', return_value=IOREG_NO_USB_AUDIO), \
             patch('sounddevice.query_devices', return_value=devices):
            from usb_audio_devices import resolve_usb_device_index
            idx = resolve_usb_device_index(
                location_id=None,
                usb_port_order=1,
                device_index_fallback=5,
                role_label='test_role',
            )
        assert idx == 5  # fallback 반환

    def test_location_id_match_returns_correct_index(self):
        """정확한 locationID가 있을 때 해당 위치의 USB 장치 index 반환."""
        devices = self._setup_two_usb()
        with patch('subprocess.check_output', return_value=IOREG_TWO_USB_AUDIO), \
             patch('sounddevice.query_devices', return_value=devices):
            from usb_audio_devices import resolve_usb_device_index, get_usb_location_ids
            loc_ids = get_usb_location_ids()
            if loc_ids:
                idx = resolve_usb_device_index(
                    location_id=loc_ids[0],
                    usb_port_order=1,
                    device_index_fallback=None,
                    role_label='test',
                )
                assert idx == 2  # 첫 번째 USB 장치


# ─────────────────────────────────────────────────────────────────────────────
# list_usb_status
# ─────────────────────────────────────────────────────────────────────────────
class TestListUsbStatus:
    def test_returns_dict_with_expected_keys(self):
        devices = _make_sd_devices(usb_count=2)
        with patch('subprocess.check_output', return_value=IOREG_TWO_USB_AUDIO), \
             patch('sounddevice.query_devices', return_value=devices):
            from usb_audio_devices import list_usb_status
            result = list_usb_status(verbose=False)
        assert 'output_indices' in result
        assert 'input_indices' in result
        assert 'location_ids' in result

    def test_verbose_mode_prints_output(self, capsys):
        devices = _make_sd_devices(usb_count=1)
        with patch('subprocess.check_output', return_value=IOREG_ONE_USB_AUDIO), \
             patch('sounddevice.query_devices', return_value=devices):
            from usb_audio_devices import list_usb_status
            list_usb_status(verbose=True)
        captured = capsys.readouterr()
        assert 'USB' in captured.out or 'usb' in captured.out.lower()
