"""
tests/test_collect_recordings.py
──────────────────────────────────────────────────────────────────────────────
collect_recordings.py 핵심 함수 단위 테스트.

외부 프로세스(adb, xcrun, ffmpeg)를 전부 unittest.mock으로 패치하며
파일시스템은 tmp_path 픽스처 또는 NamedTemporaryFile을 사용한다.

커버 범위:
  - ts_key              : 타임스탬프 키 조합
  - detect_android      : adb devices 출력 파싱
  - detect_ios          : xcrun devicectl 출력 파싱
  - list_android_recordings : adb shell ls 결과 파싱
  - list_ios_recordings : devicectl JSON 결과 파싱
  - pull_android        : adb pull 성공/실패
  - convert_to_wav      : ffmpeg 변환 성공/실패
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# collect_recordings.py 가 있는 루트 경로 추가
_ROOT = Path(__file__).parent.parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from collect_recordings import (
    convert_to_wav,
    detect_android,
    detect_ios,
    list_android_recordings,
    list_ios_recordings,
    pull_android,
    ts_key,
)


# ─────────────────────────────────────────────────────────────────────────────
# TestTsKey
# ─────────────────────────────────────────────────────────────────────────────

class TestTsKey:
    def test_concatenates_date_and_time(self):
        assert ts_key("20260305", "091754") == "20260305091754"

    def test_length_is_14(self):
        assert len(ts_key("20261231", "235959")) == 14

    def test_different_inputs_produce_different_keys(self):
        assert ts_key("20260305", "091754") != ts_key("20260306", "091754")


# ─────────────────────────────────────────────────────────────────────────────
# TestDetectAndroid
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectAndroid:
    def test_returns_serial_when_device_connected(self):
        """'<serial>\tdevice' 줄이 있을 때 serial 반환."""
        fake_output = "List of devices attached\nABC12345\tdevice\n"
        with patch(
            "subprocess.check_output", return_value=fake_output
        ):
            result = detect_android()
        assert result == "ABC12345"

    def test_returns_none_when_no_device(self):
        """연결된 장치가 없으면 None 반환."""
        fake_output = "List of devices attached\n"
        with patch("subprocess.check_output", return_value=fake_output):
            result = detect_android()
        assert result is None

    def test_returns_none_when_adb_not_found(self):
        """adb 명령이 없을 때 None 반환 (FileNotFoundError)."""
        with patch("subprocess.check_output", side_effect=FileNotFoundError):
            result = detect_android()
        assert result is None

    def test_ignores_unauthorized_devices(self):
        """'unauthorized' 줄은 무시해야 한다."""
        fake_output = "List of devices attached\nXYZ789\tunauthorized\n"
        with patch("subprocess.check_output", return_value=fake_output):
            result = detect_android()
        assert result is None

    def test_returns_first_device_when_multiple(self):
        """여러 장치가 있을 때 첫 번째 device serial 반환."""
        fake_output = (
            "List of devices attached\n"
            "FIRST001\tdevice\n"
            "SECOND002\tdevice\n"
        )
        with patch("subprocess.check_output", return_value=fake_output):
            result = detect_android()
        assert result == "FIRST001"


# ─────────────────────────────────────────────────────────────────────────────
# TestDetectIos
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectIos:
    _UDID = "A1B2C3D4-1234-5678-ABCD-1234567890AB"

    def test_returns_udid_when_connected(self):
        """connected 라인에서 UDID 추출."""
        fake_output = (
            "Name   Identifier   State\n"
            "---    ----------   -----\n"
            f"MyPhone {self._UDID} connected\n"
        )
        with patch("subprocess.check_output", return_value=fake_output):
            result = detect_ios()
        assert result == self._UDID

    def test_returns_none_when_only_unavailable(self):
        """unavailable 장치만 있으면 None 반환."""
        fake_output = (
            "Name   Identifier   State\n"
            f"MyPhone {self._UDID} unavailable\n"
        )
        with patch("subprocess.check_output", return_value=fake_output):
            result = detect_ios()
        assert result is None

    def test_returns_none_when_xcrun_not_found(self):
        """xcrun 없을 때 None 반환."""
        with patch("subprocess.check_output", side_effect=FileNotFoundError):
            result = detect_ios()
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# TestListAndroidRecordings
# ─────────────────────────────────────────────────────────────────────────────

class TestListAndroidRecordings:
    def test_parses_matching_files(self):
        """패턴에 맞는 파일명을 (ts_key, fname) 으로 반환.

        _ANDROID_PAT 패턴: 언더스코어 + 날짜8자리 + 시간6자리 + 추가숫자 + .m4a
        예: caller_20260305091754123.m4a
        """
        ls_output = "caller_20260305091754123.m4a\ncaller_20260304120000456.m4a\n"
        with patch("subprocess.check_output", return_value=ls_output):
            results = list_android_recordings("ABC123")
        assert len(results) == 2
        # 오름차순 정렬: 20260304가 먼저
        assert results[0][0] < results[1][0]

    def test_ignores_non_matching_files(self):
        """패턴에 맞지 않는 파일은 무시."""
        ls_output = "some_random_file.mp3\nnotes.txt\n"
        with patch("subprocess.check_output", return_value=ls_output):
            results = list_android_recordings("ABC123")
        assert results == []

    def test_returns_empty_on_adb_error(self):
        """adb 오류 시 빈 목록 반환."""
        with patch(
            "subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "adb"),
        ):
            results = list_android_recordings("BAD")
        assert results == []

    def test_returns_list_of_tuples(self):
        """반환 타입은 (str, str) 튜플 목록."""
        ls_output = "caller_20260305091754123.m4a\n"
        with patch("subprocess.check_output", return_value=ls_output):
            results = list_android_recordings("ABC123")
        if results:
            ts, fname = results[0]
            assert isinstance(ts, str) and isinstance(fname, str)


# ─────────────────────────────────────────────────────────────────────────────
# TestListIosRecordings
# ─────────────────────────────────────────────────────────────────────────────

class TestListIosRecordings:
    _UUID = "A1B2C3D4-1234-5678-ABCD-1234567890AB"

    def _fake_json(self, filenames: list[str]) -> str:
        return json.dumps({
            "result": {
                "files": [{"name": f"Documents/{f}"} for f in filenames]
            }
        })

    def test_parses_ios_file_list(self, tmp_path: Path):
        """devicectl JSON 출력에서 .m4a 파일 파싱."""
        fname = f"{self._UUID}202603050917541190mvoip_test_0.m4a"
        fake_json = self._fake_json([fname])

        # subprocess.run 으로 JSON 파일 생성 흉내
        def fake_run(*args, **kwargs):
            # json_output 경로를 tmp 파일에 쓰기
            cmd = args[0] if args else kwargs.get("args", [])
            for i, part in enumerate(cmd):
                if part == "--json-output" and i + 1 < len(cmd):
                    Path(cmd[i + 1]).write_text(fake_json)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("subprocess.run", side_effect=fake_run):
            results = list_ios_recordings(self._UUID)

        assert len(results) == 1
        assert results[0][1] == fname

    def test_returns_empty_on_process_error(self):
        """devicectl 오류 시 빈 목록 반환."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "xcrun"),
        ):
            results = list_ios_recordings(self._UUID)
        assert results == []

    def test_ignores_non_m4a_files(self, tmp_path: Path):
        """iOS JSON에서 패턴 불일치 파일 무시."""
        fake_json = self._fake_json(["random_file.txt", "notes.docx"])

        def fake_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            for i, part in enumerate(cmd):
                if part == "--json-output" and i + 1 < len(cmd):
                    Path(cmd[i + 1]).write_text(fake_json)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            results = list_ios_recordings(self._UUID)
        assert results == []


# ─────────────────────────────────────────────────────────────────────────────
# TestPullAndroid
# ─────────────────────────────────────────────────────────────────────────────

class TestPullAndroid:
    def test_returns_true_on_success(self, tmp_path: Path):
        """adb pull 성공 → True 반환."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = pull_android("ABC123", "rec.m4a", tmp_path / "out.m4a")
        assert result is True

    def test_returns_false_on_failure(self, tmp_path: Path):
        """adb pull 실패 → False 반환."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "adb"),
        ):
            result = pull_android("ABC123", "rec.m4a", tmp_path / "out.m4a")
        assert result is False

    def test_uses_correct_remote_path(self, tmp_path: Path):
        """adb pull 명령에 올바른 원격 경로가 포함되어야 한다."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            pull_android("S1", "myfile.m4a", tmp_path / "out.m4a")
        call_args = mock_run.call_args[0][0]
        assert any("myfile.m4a" in str(a) for a in call_args)


# ─────────────────────────────────────────────────────────────────────────────
# TestConvertToWav
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertToWav:
    def test_returns_true_on_success(self, tmp_path: Path):
        """ffmpeg 성공 → True 반환."""
        src = tmp_path / "input.m4a"
        dst = tmp_path / "output.wav"
        src.touch()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = convert_to_wav(src, dst)
        assert result is True

    def test_returns_false_on_ffmpeg_error(self, tmp_path: Path):
        """ffmpeg 실패(CalledProcessError) → False 반환."""
        src = tmp_path / "input.m4a"
        dst = tmp_path / "output.wav"
        src.touch()
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
        ):
            result = convert_to_wav(src, dst)
        assert result is False

    def test_returns_false_when_ffmpeg_not_found(self, tmp_path: Path):
        """ffmpeg 명령이 없을 때 → False 반환."""
        src = tmp_path / "input.m4a"
        dst = tmp_path / "output.wav"
        src.touch()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = convert_to_wav(src, dst)
        assert result is False

    def test_ffmpeg_called_with_16k_mono(self, tmp_path: Path):
        """ffmpeg 명령에 -ar 16000 과 -ac 1 이 포함돼야 한다."""
        src = tmp_path / "input.m4a"
        dst = tmp_path / "output.wav"
        src.touch()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            convert_to_wav(src, dst)
        cmd = mock_run.call_args[0][0]
        assert "-ar" in cmd and "16000" in cmd
        assert "-ac" in cmd and "1" in cmd
