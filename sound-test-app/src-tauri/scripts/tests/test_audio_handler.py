"""
tests/test_audio_handler.py
──────────────────────────────────────────────────────────────────────────────
audio_handler 모듈 단위 테스트.
"""
import pytest
from unittest.mock import patch, MagicMock
import sys


class TestResolveAudioDeviceIndex:
    """resolve_audio_device_index — usb_audio_devices로 위임되는지 확인."""

    def test_delegates_to_usb_module(self):
        with patch('audio_handler.resolve_usb_device_index', return_value=3) as mock_resolve:
            import audio_handler
            result = audio_handler.resolve_audio_device_index('speaker1')
            mock_resolve.assert_called_once()
            assert result == 3

    def test_returns_none_when_no_usb(self):
        with patch('audio_handler.resolve_usb_device_index', return_value=None):
            import audio_handler
            result = audio_handler.resolve_audio_device_index('speaker1')
            assert result is None


class TestListUsbAudioDevices:
    """list_usb_audio_devices — list_usb_status로 위임 확인."""

    def test_delegates_to_usb_module(self):
        fake_status = {
            'output_indices': [1, 2],
            'input_indices': [1],
            'location_ids': [0x2120000],
        }
        with patch('audio_handler.list_usb_status', return_value=fake_status) as mock_status:
            import audio_handler
            result = audio_handler.list_usb_audio_devices()
            mock_status.assert_called_once()
            assert result == fake_status


class TestPlayAudioToDevice:
    """DeviceAudioPlayer.play_audio_to_device — audio_player_worker.py subprocess 호출 확인."""

    def _run(self, wav_path='/tmp/test.wav', device=2,
             channel=None, speaker_id='speaker1', usb_order=1):
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        with patch('subprocess.Popen', return_value=mock_proc) as mock_popen:
            from audio_handler import DeviceAudioPlayer
            DeviceAudioPlayer.play_audio_to_device(
                wav_path,
                device=device,
                channel=channel,
                speaker_id=speaker_id,
                usb_order=usb_order,
            )
        return mock_popen, mock_proc

    def test_spawns_subprocess(self):
        mock_popen, _ = self._run()
        assert mock_popen.called

    def test_worker_script_in_command(self):
        mock_popen, _ = self._run()
        cmd = mock_popen.call_args[0][0]
        cmd_str = ' '.join(str(c) for c in cmd)
        assert 'audio_player_worker.py' in cmd_str

    def test_device_arg_passed(self):
        mock_popen, _ = self._run(device=5)
        cmd = mock_popen.call_args[0][0]
        assert '--device' in cmd
        idx = cmd.index('--device')
        assert str(cmd[idx + 1]) == '5'

    def test_channel_arg_passed_when_given(self):
        mock_popen, _ = self._run(channel='R')
        cmd = mock_popen.call_args[0][0]
        assert '--channel' in cmd
        idx = cmd.index('--channel')
        assert cmd[idx + 1] == 'R'

    def test_usb_order_arg_passed(self):
        mock_popen, _ = self._run(usb_order=2)
        cmd = mock_popen.call_args[0][0]
        assert '--usb-order' in cmd
        idx = cmd.index('--usb-order')
        assert str(cmd[idx + 1]) == '2'

    def test_speaker_id_passed(self):
        mock_popen, _ = self._run(speaker_id='speaker2')
        cmd = mock_popen.call_args[0][0]
        assert '--speaker-id' in cmd
        idx = cmd.index('--speaker-id')
        assert cmd[idx + 1] == 'speaker2'


class TestGetUsbAudioOutputIndicesViaHandler:
    """audio_handler 를 통한 get_usb_audio_output_indices 위임 확인."""

    def test_returns_usb_indices(self):
        import audio_handler
        with patch.object(audio_handler, 'get_usb_audio_output_indices', return_value=[1, 2]) as mock_fn:
            result = audio_handler.get_usb_audio_output_indices()
            mock_fn.assert_called_once()
            assert result == [1, 2]
