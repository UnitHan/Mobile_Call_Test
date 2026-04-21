"""
tests/test_gap_detector.py
──────────────────────────────────────────────────────────────────────────────
gap_detector.py 핵심 함수 단위 테스트.

커버 범위:
  - find_offset_frames     : FFT cross-correlation 오프셋 추정
  - detect_gaps_envelope   : 에너지 엔벨로프 비교 음단절 검출
  - detect_gaps_correlation: sample-level correlation 음단절 검출
  - compute_energy_profile : 프레임별 dB 프로파일 (audio_lib.dsp 공유)
  - analyze                : 전체 파이프라인 (WAV 파일 기반)
"""
from __future__ import annotations

import struct
import sys
import tempfile
import wave
from pathlib import Path
from typing import List

import numpy as np
import pytest

# scripts/ 를 import 경로에 추가
_SCRIPTS_DIR = Path(__file__).parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# audio_lib (루트 폴더) 경로 추가
_ROOT = _SCRIPTS_DIR.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gap_detector import (
    analyze,
    detect_gaps_correlation,
    detect_gaps_envelope,
    find_offset_frames,
)
from audio_lib.dsp import energy_profile as compute_energy_profile


# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼: WAV 파일 생성
# ─────────────────────────────────────────────────────────────────────────────

def _make_wav(samples: np.ndarray, sr: int, path: str) -> None:
    """mono float32 배열 → WAV 파일로 저장."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _tone(freq: float, duration_sec: float, sr: int = 16000, amp: float = 0.5) -> np.ndarray:
    """단일 사인파 생성."""
    t = np.arange(int(duration_sec * sr)) / sr
    return (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)


def _silence(duration_sec: float, sr: int = 16000) -> np.ndarray:
    """무음 배열 생성."""
    return np.zeros(int(duration_sec * sr), dtype=np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# TestFindOffsetFrames
# ─────────────────────────────────────────────────────────────────────────────

class TestFindOffsetFrames:
    """find_offset_frames: FFT cross-correlation 오프셋 추정"""

    def _make_db_profile(self, audio: np.ndarray, sr: int = 16000) -> tuple[np.ndarray, float]:
        return compute_energy_profile(audio, sr, frame_ms=20)

    def test_zero_offset_same_signal(self):
        """동일 신호 → 오프셋 0 반환."""
        audio = _tone(440, 3.0)
        db, _ = self._make_db_profile(audio)
        offset = find_offset_frames(db, db, max_offset_frames=50)
        assert offset == 0

    def test_positive_offset_delayed_test(self):
        """test가 0.1초 늦게 시작 → 오프셋 ≤ 0 반환 (test가 ref보다 늦음)."""
        sr = 16000
        ref_audio = _tone(440, 3.0, sr)
        # test = 100ms 무음 + ref 신호 (test가 5프레임 늦게 시작)
        test_audio = np.concatenate([_silence(0.1, sr), ref_audio])

        ref_db, frame_sec = self._make_db_profile(ref_audio, sr)
        test_db, _ = self._make_db_profile(test_audio, sr)
        offset = find_offset_frames(ref_db, test_db, max_offset_frames=20)
        # test가 늦게 시작 → detect_gaps_envelope에서 test_a = test_db[-offset:] 로 보정됨
        # 반환값이 0 이하 (test 지연)
        assert offset <= 0, f"expected offset <= 0 for delayed test, got {offset}"

    def test_returns_integer(self):
        """반환값이 int 타입이어야 한다."""
        audio = _tone(440, 2.0)
        db, _ = self._make_db_profile(audio)
        result = find_offset_frames(db, db, max_offset_frames=10)
        assert isinstance(result, int)

    def test_short_signal_no_crash(self):
        """짧은 신호에서도 크래시 없이 동작해야 한다."""
        db = np.array([-50.0, -45.0, -40.0, -45.0, -50.0], dtype=np.float32)
        result = find_offset_frames(db, db, max_offset_frames=2)
        assert isinstance(result, int)


# ─────────────────────────────────────────────────────────────────────────────
# TestDetectGapsEnvelope
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectGapsEnvelope:
    """detect_gaps_envelope: 에너지 엔벨로프 비교 음단절 검출"""

    def _profiles(
        self, ref: np.ndarray, test: np.ndarray, sr: int = 16000
    ) -> tuple[np.ndarray, np.ndarray, float]:
        ref_db, frame_sec = compute_energy_profile(ref, sr, frame_ms=20)
        test_db, _ = compute_energy_profile(test, sr, frame_ms=20)
        return ref_db, test_db, frame_sec

    def test_identical_audio_no_gaps(self):
        """동일 음원 비교 → 음단절 없음."""
        audio = _tone(440, 2.0)
        ref_db, test_db, frame_sec = self._profiles(audio, audio)
        gaps, _ = detect_gaps_envelope(ref_db, test_db, frame_sec)
        assert gaps == []

    def test_silent_test_full_gap(self):
        """ref=신호, test=무음 → 전체 음단절 검출."""
        ref = _tone(440, 1.0)
        test = _silence(1.0)
        ref_db, test_db, frame_sec = self._profiles(ref, test)
        gaps, _ = detect_gaps_envelope(ref_db, test_db, frame_sec, min_gap_ms=100)
        assert len(gaps) >= 1
        total_ms = sum(g['duration_ms'] for g in gaps)
        assert total_ms > 800  # 거의 전체 구간이 갭

    def test_gap_fields_present(self):
        """각 gap dict에 필수 필드가 있어야 한다."""
        ref = _tone(440, 1.0)
        test = _silence(1.0)
        ref_db, test_db, frame_sec = self._profiles(ref, test)
        gaps, offset = detect_gaps_envelope(ref_db, test_db, frame_sec, min_gap_ms=100)
        assert isinstance(offset, float)
        if gaps:
            g = gaps[0]
            for key in ('start_sec', 'end_sec', 'duration_ms', 'ref_db_avg', 'test_db_avg'):
                assert key in g, f"field '{key}' missing in gap dict"

    def test_short_silence_filtered_by_min_gap_ms(self):
        """min_gap_ms보다 짧은 무음은 갭으로 판정되지 않아야 한다."""
        sr = 16000
        # ref: 1초 신호. test: 40ms만 무음인 신호 (중간에 2 frames = ~40ms)
        ref = _tone(440, 1.0, sr)
        test = ref.copy()
        # 0.2초~0.24초 구간 무음 (약 40ms)
        test[int(0.2 * sr):int(0.24 * sr)] = 0.0

        ref_db, test_db, frame_sec = self._profiles(ref, test, sr)
        # min_gap_ms=200 이상으로 설정하면 40ms 갭은 무시돼야 한다
        gaps, _ = detect_gaps_envelope(ref_db, test_db, frame_sec, min_gap_ms=200)
        assert gaps == []

    def test_silent_ref_not_counted_as_gap(self):
        """ref에 소리가 없는 구간(무음 정답지)은 갭으로 판정 제외해야 한다."""
        sr = 16000
        # ref = 1초 무음, test = 1초 무음
        ref = _silence(1.0, sr)
        test = _silence(1.0, sr)
        ref_db, test_db, frame_sec = self._profiles(ref, test, sr)
        gaps, _ = detect_gaps_envelope(ref_db, test_db, frame_sec, ref_min_db=-45.0)
        # ref 자체가 무음이므로 판정 대상이 없음 → 갭 없음
        assert gaps == []

    def test_gap_duration_ms_positive(self):
        """검출된 gap의 duration_ms는 양수여야 한다."""
        ref = _tone(440, 2.0)
        test = _silence(2.0)
        ref_db, test_db, frame_sec = self._profiles(ref, test)
        gaps, _ = detect_gaps_envelope(ref_db, test_db, frame_sec, min_gap_ms=50)
        for g in gaps:
            assert g['duration_ms'] > 0


# ─────────────────────────────────────────────────────────────────────────────
# TestDetectGapsCorrelation
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectGapsCorrelation:
    """detect_gaps_correlation: sample-level correlation 음단절 검출"""

    def test_identical_audio_no_gaps(self):
        """동일 음원 비교 → 상관계수 1.0 → 음단절 없음."""
        sr = 16000
        audio = _tone(440, 2.0, sr)
        gaps, _ = detect_gaps_correlation(
            audio, audio, sr, frame_ms=50, hop_ms=25, min_corr=0.4,
            ref_min_db=-45.0, min_gap_ms=200,
        )
        assert gaps == []

    def test_silent_test_all_gaps(self):
        """ref=신호, test=무음 → 전체 음단절."""
        sr = 16000
        ref = _tone(440, 1.0, sr)
        test = _silence(1.0, sr)
        gaps, _ = detect_gaps_correlation(
            ref, test, sr, frame_ms=50, hop_ms=25, min_corr=0.4,
            ref_min_db=-45.0, min_gap_ms=100,
        )
        assert len(gaps) >= 1

    def test_offset_sec_is_float(self):
        """반환된 offset_sec가 float이어야 한다."""
        sr = 16000
        audio = _tone(440, 1.0, sr)
        _, offset = detect_gaps_correlation(
            audio, audio, sr, frame_ms=50, hop_ms=25, min_corr=0.4,
            ref_min_db=-45.0, min_gap_ms=100,
        )
        assert isinstance(offset, float)


# ─────────────────────────────────────────────────────────────────────────────
# TestAnalyze
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyze:
    """analyze: WAV 파일 기반 전체 파이프라인"""

    def test_envelope_mode_returns_required_keys(self):
        """analyze() 결과에 필수 키들이 있어야 한다."""
        sr = 16000
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            ref_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            test_path = f.name

        try:
            _make_wav(_tone(440, 1.0, sr), sr, ref_path)
            _make_wav(_tone(440, 1.0, sr), sr, test_path)
            result = analyze(ref_path, test_path, mode='envelope')
            for key in ('ref', 'test', 'mode', 'offset_sec', 'duration_sec',
                        'gaps', 'total_gap_ms', 'gap_rate_pct'):
                assert key in result, f"key '{key}' missing"
        finally:
            Path(ref_path).unlink(missing_ok=True)
            Path(test_path).unlink(missing_ok=True)

    def test_silent_test_gaps_detected(self):
        """test가 전부 무음일 때 gaps가 1개 이상 검출돼야 한다."""
        sr = 16000
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            ref_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            test_path = f.name

        try:
            _make_wav(_tone(440, 1.0, sr), sr, ref_path)
            _make_wav(_silence(1.0, sr), sr, test_path)
            result = analyze(ref_path, test_path, mode='envelope', min_gap_ms=100)
            assert len(result['gaps']) >= 1
            assert result['total_gap_ms'] > 0
        finally:
            Path(ref_path).unlink(missing_ok=True)
            Path(test_path).unlink(missing_ok=True)

    def test_identical_files_zero_gaps(self):
        """ref == test일 때 갭이 없어야 한다."""
        sr = 16000
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            ref_path = f.name

        try:
            _make_wav(_tone(440, 1.0, sr), sr, ref_path)
            result = analyze(ref_path, ref_path, mode='envelope')
            assert result['gaps'] == []
            assert result['total_gap_ms'] == 0
        finally:
            Path(ref_path).unlink(missing_ok=True)

    def test_duration_sec_positive(self):
        """duration_sec는 ref 파일 길이와 근사해야 한다 (±0.1s)."""
        sr = 16000
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            ref_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            test_path = f.name

        try:
            _make_wav(_tone(440, 2.0, sr), sr, ref_path)
            _make_wav(_tone(440, 2.0, sr), sr, test_path)
            result = analyze(ref_path, test_path, mode='envelope')
            assert abs(result['duration_sec'] - 2.0) < 0.1
        finally:
            Path(ref_path).unlink(missing_ok=True)
            Path(test_path).unlink(missing_ok=True)

    def test_gap_rate_pct_range(self):
        """gap_rate_pct는 0 이상이어야 한다."""
        sr = 16000
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            ref_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            test_path = f.name

        try:
            _make_wav(_tone(440, 1.0, sr), sr, ref_path)
            _make_wav(_tone(440, 1.0, sr), sr, test_path)
            result = analyze(ref_path, test_path, mode='envelope')
            assert result['gap_rate_pct'] >= 0.0
        finally:
            Path(ref_path).unlink(missing_ok=True)
            Path(test_path).unlink(missing_ok=True)

    def test_mode_field_matches_argument(self):
        """result['mode']가 전달한 mode 인수와 일치해야 한다."""
        sr = 16000
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            ref_path = f.name

        try:
            _make_wav(_tone(440, 1.0, sr), sr, ref_path)
            result = analyze(ref_path, ref_path, mode='envelope')
            assert result['mode'] == 'envelope'
        finally:
            Path(ref_path).unlink(missing_ok=True)
