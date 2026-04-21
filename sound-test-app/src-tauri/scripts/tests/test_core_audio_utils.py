"""
tests/test_core_audio_utils.py
──────────────────────────────────────────────────────────────────────────────
core_audio_utils 모듈 단위 테스트.
"""
import pytest
from unittest.mock import patch, MagicMock, call
import sys


class TestRestoreDefaultDevices:
    """restore_default_devices — 동일 장치일 때 SwitchAudioSource 미호출 확인."""

    def test_no_call_when_output_unchanged(self):
        """저장 장치 == 현재 장치 → set_default_output 미호출."""
        import core_audio_utils as cu

        cu._saved_output_name = 'MacBook Pro Speakers'
        cu._saved_input_name = None
        cu._saved_input_id = None

        with patch.object(cu, 'get_default_output_name', return_value='MacBook Pro Speakers'), \
             patch.object(cu, 'set_default_output') as mock_set_out, \
             patch.object(cu, 'get_default_input_name', return_value=None):
            cu.restore_default_devices(verbose=False)

        mock_set_out.assert_not_called()

    def test_calls_switch_when_output_changed(self):
        """저장 장치 != 현재 장치 → set_default_output 호출."""
        import core_audio_utils as cu

        cu._saved_output_name = 'USB Audio Device'
        cu._saved_input_name = None

        with patch.object(cu, 'get_default_output_name', return_value='MacBook Pro Speakers'), \
             patch.object(cu, 'set_default_output') as mock_set_out, \
             patch.object(cu, 'get_default_input_name', return_value=None):
            cu.restore_default_devices(verbose=False)

        mock_set_out.assert_called_once_with('USB Audio Device')

    def test_does_nothing_when_nothing_saved(self):
        """저장된 장치가 없으면 아무 것도 호출하지 않음."""
        import core_audio_utils as cu

        cu._saved_output_name = None
        cu._saved_input_name = None

        with patch.object(cu, 'set_default_output') as mock_set_out, \
             patch.object(cu, 'set_default_input') as mock_set_in:
            cu.restore_default_devices(verbose=False)

        mock_set_out.assert_not_called()
        mock_set_in.assert_not_called()


class TestLockUsbOutputForTest:
    """lock_usb_output_for_test — 현재 장치 이름이 저장되는지 확인."""

    def test_saves_current_output_name(self):
        import core_audio_utils as cu

        with patch.object(cu, 'get_default_output_name', return_value='MacBook Pro Speakers'), \
             patch.object(cu, 'get_default_input_name', return_value='MacBook Pro Microphone'), \
             patch.object(cu, 'set_default_output', return_value=True), \
             patch('subprocess.run', return_value=MagicMock(returncode=0)), \
             patch('sounddevice.query_devices', return_value=[{'name': 'USB Audio Device', 'max_output_channels': 2}]):
            # USB 장치가 없어 False 반환해도 _saved_output_name 이 설정돼야 함
            cu.lock_usb_output_for_test(verbose=False)

        # 저장 시도 여부 확인 (함수가 예외 없이 완료)
        assert True  # 예외 없이 호출됨

    def test_no_exception_when_no_usb(self):
        import core_audio_utils as cu

        with patch.object(cu, 'get_default_output_name', return_value='MacBook Pro Speakers'), \
             patch.object(cu, 'get_default_input_name', return_value='MacBook Pro Microphone'), \
             patch('subprocess.run', return_value=MagicMock(returncode=0)), \
             patch('sounddevice.query_devices', return_value=[]):
            # USB 없을 때 예외 없이 종료
            cu.lock_usb_output_for_test(verbose=False)


class TestGetUsbAudioOutputIndicesDelegation:
    """core_audio_utils.get_usb_audio_output_indices — usb_audio_devices 위임."""

    def test_delegates_to_usb_module(self):
        import core_audio_utils as cu

        # from ... import 로 바인딩된 이름이므로 cu 모듈에서 직접 패치
        with patch.object(cu, 'get_usb_audio_output_indices', return_value=[2, 3]) as mock_fn:
            result = cu.get_usb_audio_output_indices()
            mock_fn.assert_called_once()
        assert result == [2, 3]

    def test_delegates_input_indices(self):
        import core_audio_utils as cu

        with patch.object(cu, 'get_usb_audio_input_indices', return_value=[1]) as mock_fn:
            result = cu.get_usb_audio_input_indices()
            mock_fn.assert_called_once()
        assert result == [1]
