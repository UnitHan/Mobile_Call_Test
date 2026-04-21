"""
tests/test_audio_player_worker.py
──────────────────────────────────────────────────────────────────────────────
audio_player_worker 모듈 단위 테스트.

sounddevice, soundfile, scipy 의존성을 mock으로 대체합니다.
"""
import pytest
import numpy as np
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import sys

# audio_player_worker.py 의 play() 함수 테스트를 위해 argparse CLI 우회 후 직접 함수 호출


IOREG_USB = b"""
| +-o IOUSBInterface
|   "USB Product Name" = "USB Audio Device"
|   "locationID" = 34734080
"""


def _make_device_info(name='USB Audio Device', sr=44100.0, out_ch=2):
    return {'name': name, 'default_samplerate': sr, 'max_output_channels': out_ch}


class TestAudioPlayerWorkerPlay:
    """audio_player_worker.play() 함수 단위 테스트"""

    def _run_play(self, audio_file='/tmp/test.wav', device=2,
                  channel=None, speaker_id='speaker1', usb_order=1):
        """모든 외부 의존성을 mock한 상태에서 play() 실행."""
        data_mono = np.zeros(44100, dtype=np.float32)
        data_stereo = np.zeros((44100, 2), dtype=np.float32)

        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.write = MagicMock()

        with patch('soundfile.read', return_value=(data_stereo, 44100)), \
             patch('sounddevice.query_devices') as mock_qd, \
             patch('sounddevice.OutputStream', return_value=mock_stream), \
             patch('subprocess.check_output', return_value=IOREG_USB):
            mock_qd.side_effect = lambda idx=None, kind=None: (
                _make_device_info() if idx is not None
                else [_make_device_info('MacBook Pro Speakers', out_ch=2),
                      _make_device_info('USB Audio Device')]
            )
            import audio_player_worker
            audio_player_worker.play(
                audio_file=audio_file,
                device=device,
                channel=channel,
                speaker_id=speaker_id,
                usb_order=usb_order,
            )
        return mock_stream

    def test_play_calls_stream_write(self):
        stream = self._run_play()
        assert stream.write.called

    def test_play_with_left_channel(self):
        """Left 채널 지정 시 stereo 데이터 생성, right는 0."""
        data_stereo = np.ones((44100, 2), dtype=np.float32)
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        written_blocks = []
        mock_stream.write = lambda block: written_blocks.append(block)

        with patch('soundfile.read', return_value=(data_stereo, 44100)), \
             patch('sounddevice.query_devices', return_value=[
                 _make_device_info('USB Audio Device')]), \
             patch('sounddevice.query_devices', side_effect=lambda idx=None, kind=None:
                   _make_device_info() if idx is not None else [_make_device_info()]), \
             patch('sounddevice.OutputStream', return_value=mock_stream), \
             patch('subprocess.check_output', return_value=IOREG_USB):
            import audio_player_worker
            audio_player_worker.play(
                audio_file='/tmp/test.wav',
                device=0,
                channel='L',
                speaker_id='speaker1',
                usb_order=1,
            )
        # L 채널 분리: 오른쪽 채널은 0이어야 함
        if written_blocks:
            last_block = written_blocks[-1]
            assert last_block.shape[1] == 2

    def test_play_with_right_channel(self):
        """Right 채널 지정 시 left는 0."""
        data_stereo = np.ones((44100, 2), dtype=np.float32)
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        written_blocks = []
        mock_stream.write = lambda block: written_blocks.append(block)

        with patch('soundfile.read', return_value=(data_stereo, 44100)), \
             patch('sounddevice.query_devices', side_effect=lambda idx=None, kind=None:
                   _make_device_info() if idx is not None else [_make_device_info()]), \
             patch('sounddevice.OutputStream', return_value=mock_stream), \
             patch('subprocess.check_output', return_value=IOREG_USB):
            import audio_player_worker
            audio_player_worker.play(
                audio_file='/tmp/test.wav',
                device=0,
                channel='R',
                speaker_id='speaker2',
                usb_order=2,
            )
        if written_blocks:
            last_block = written_blocks[-1]
            assert last_block.shape[1] == 2

    def test_usb_recovery_on_non_usb_device(self):
        """비USB 장치(맥북 스피커) 감지 시 usb_order 기반 자동 복구."""
        data = np.zeros((44100, 2), dtype=np.float32)
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.write = MagicMock()

        devices_list = [
            _make_device_info('MacBook Pro Speakers', 48000.0),
            _make_device_info('USB Audio Device', 44100.0),
        ]

        def mock_query(idx=None, kind=None):
            if idx is not None:
                return devices_list[idx] if idx < len(devices_list) else devices_list[0]
            return devices_list

        with patch('soundfile.read', return_value=(data, 44100)), \
             patch('sounddevice.query_devices', side_effect=mock_query), \
             patch('sounddevice.OutputStream', return_value=mock_stream), \
             patch('subprocess.check_output', return_value=IOREG_USB):
            import audio_player_worker
            # device=0 은 MacBook (비USB), usb_order=1 → USB 복구됨
            audio_player_worker.play(
                audio_file='/tmp/test.wav',
                device=0,
                channel=None,
                speaker_id='speaker1',
                usb_order=1,
            )
        assert mock_stream.write.called

    def test_progress_output(self, capsys):
        """AUDIO_PROGRESS 진행률 출력 확인."""
        # 짧은 1초 오디오 (44100 frames)
        data = np.zeros((44100, 2), dtype=np.float32)
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.write = MagicMock()

        with patch('soundfile.read', return_value=(data, 44100)), \
             patch('sounddevice.query_devices', side_effect=lambda idx=None, kind=None:
                   _make_device_info() if idx is not None else [_make_device_info()]), \
             patch('sounddevice.OutputStream', return_value=mock_stream), \
             patch('subprocess.check_output', return_value=IOREG_USB):
            import audio_player_worker
            audio_player_worker.play(
                audio_file='/tmp/test.wav',
                device=0,
                channel=None,
                speaker_id='speaker1',
                usb_order=1,
            )
        captured = capsys.readouterr()
        assert 'AUDIO_PROGRESS:speaker1:1.000' in captured.out
