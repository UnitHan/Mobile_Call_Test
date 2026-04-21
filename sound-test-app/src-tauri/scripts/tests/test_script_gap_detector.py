"""
tests/test_script_gap_detector.py
──────────────────────────────────────────────────────────────────────────────
script_gap_detector 핵심 함수 단위 테스트.

커버 범위:
  - load_wav_mono        : WAV 파일 로드 / 포맷 변환
  - energy_profile       : RMS 프레임 에너지 계산
  - vad_segments         : 발화 분절 (무음 기반 VAD)
  - parse_script         : 대본 텍스트 파싱
  - load_script_reference: analyze_hybrid.py SCRIPT_REFERENCE 추출
  - analyze_by_script    : 무음 입력 → 전체 음단절 판정 (통합)
"""

from __future__ import annotations

import struct
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

# scripts/ 를 import 경로에 추가 (conftest.py 에서도 수행하지만 명시적으로 보장)
_SCRIPTS_DIR = Path(__file__).parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from script_gap_detector import (
    analyze_by_script,
    energy_profile,
    load_script_reference,
    load_wav_mono,
    parse_script,
    vad_segments,
)


# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼: 임시 WAV 파일 생성
# ─────────────────────────────────────────────────────────────────────────────

def _write_wav(path: Path, audio: np.ndarray, sr: int = 16000) -> None:
    """float32 [-1, 1] 배열을 16-bit mono WAV 로 저장."""
    pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _sine_wav(freq: float = 440.0, duration: float = 1.0,
              sr: int = 16000, amplitude: float = 0.5) -> np.ndarray:
    """사인파 float32 샘플 생성."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * amplitude).astype(np.float32)


def _silent_wav(duration: float = 1.0, sr: int = 16000) -> np.ndarray:
    """무음(0) 샘플 생성."""
    return np.zeros(int(sr * duration), dtype=np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# load_wav_mono 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadWavMono:
    def test_returns_float32(self, tmp_path):
        audio = _sine_wav(duration=0.5)
        p = tmp_path / "test.wav"
        _write_wav(p, audio)
        pcm, sr = load_wav_mono(p)
        assert pcm.dtype == np.float32

    def test_sample_rate_preserved(self, tmp_path):
        audio = _sine_wav(sr=44100, duration=0.1)
        p = tmp_path / "sr44100.wav"
        _write_wav(p, audio, sr=44100)
        _, sr = load_wav_mono(p)
        assert sr == 44100

    def test_stereo_converted_to_mono(self, tmp_path):
        """2채널 WAV → 채널 평균 mono 변환 확인."""
        sr = 16000
        n = int(sr * 0.5)
        left  = (np.ones(n, dtype=np.float32) * 0.4)
        right = (np.ones(n, dtype=np.float32) * 0.2)
        stereo = np.column_stack([left, right])
        pcm16  = (stereo * 32767).clip(-32768, 32767).astype(np.int16)

        p = tmp_path / "stereo.wav"
        with wave.open(str(p), 'wb') as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm16.tobytes())

        mono, _ = load_wav_mono(p)
        assert mono.ndim == 1
        # 채널 평균 ≈ 0.3 (오차 허용 5%)
        assert abs(float(mono.mean()) - 0.3) < 0.05

    def test_amplitude_normalized(self, tmp_path):
        """최대 진폭 1.0 이하로 정규화 확인."""
        audio = _sine_wav(amplitude=0.9, duration=0.2)
        p = tmp_path / "norm.wav"
        _write_wav(p, audio)
        pcm, _ = load_wav_mono(p)
        assert float(np.abs(pcm).max()) <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# energy_profile 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestEnergyProfile:
    def test_silent_signal_very_low_db(self):
        """무음 신호의 에너지는 극히 낮은 dB 값이어야 한다."""
        silent = _silent_wav(duration=1.0)
        db, frame_sec = energy_profile(silent, sr=16000, frame_ms=20)
        assert np.all(db < -80.0)

    def test_loud_signal_high_db(self):
        """진폭 0.5 사인파의 에너지는 정상 범위 dB 이어야 한다."""
        audio = _sine_wav(amplitude=0.5, duration=1.0)
        db, _ = energy_profile(audio, sr=16000, frame_ms=20)
        # 0.5 진폭 RMS ≈ 0.35 → ~-9dB. 최소 -20dB 이상 기대
        assert float(db.mean()) > -20.0

    def test_frame_count_matches_duration(self):
        """프레임 수가 신호 길이 / frame_ms 와 일치해야 한다."""
        sr = 16000
        duration = 1.0
        frame_ms = 20
        audio = _sine_wav(duration=duration, sr=sr)
        db, frame_sec = energy_profile(audio, sr=sr, frame_ms=frame_ms)
        expected_frames = int(sr * duration) // int(sr * frame_ms / 1000)
        assert len(db) == expected_frames

    def test_frame_sec_value(self):
        """frame_sec 이 frame_ms / 1000 과 같아야 한다."""
        audio = _sine_wav(duration=0.5)
        _, frame_sec = energy_profile(audio, sr=16000, frame_ms=20)
        assert abs(frame_sec - 0.02) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# vad_segments 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestVadSegments:
    SR = 16000
    FRAME_MS = 20

    def _make_db(self, pattern: list[tuple[float, float, str]]) -> tuple[np.ndarray, float]:
        """pattern: [(start_s, end_s, 'voice'|'silent'), ...] → db 배열, frame_sec"""
        frame_sec = self.FRAME_MS / 1000
        total_sec = max(end for _, end, _ in pattern)
        n_frames = int(total_sec / frame_sec) + 1
        db = np.full(n_frames, -90.0, dtype=np.float32)
        for start, end, kind in pattern:
            s_f = int(start / frame_sec)
            e_f = int(end   / frame_sec)
            if kind == 'voice':
                db[s_f:e_f] = -20.0    # 유성음 수준
        return db, frame_sec

    def test_single_utterance(self):
        """단일 발화 구간 → 세그먼트 1개 반환."""
        db, fs = self._make_db([(0.0, 2.0, 'voice'), (2.0, 3.0, 'silent')])
        segs = vad_segments(db, fs, ref_min_db=-45.0,
                            silence_gap_ms=700, min_seg_ms=400)
        assert len(segs) == 1

    def test_two_utterances_separated_by_long_silence(self):
        """700ms 이상 묵음으로 분리된 두 발화 → 세그먼트 2개."""
        db, fs = self._make_db([
            (0.0, 1.0, 'voice'),
            (1.0, 2.0, 'silent'),   # 1000ms 묵음
            (2.0, 3.0, 'voice'),
        ])
        segs = vad_segments(db, fs, ref_min_db=-45.0,
                            silence_gap_ms=700, min_seg_ms=400)
        assert len(segs) == 2

    def test_short_silence_merged(self):
        """300ms 짧은 묵음 → 하나의 발화로 병합."""
        db, fs = self._make_db([
            (0.0, 1.0, 'voice'),
            (1.0, 1.3, 'silent'),   # 300ms 묵음 (gap기준 700ms 미만)
            (1.3, 2.5, 'voice'),
        ])
        segs = vad_segments(db, fs, ref_min_db=-45.0,
                            silence_gap_ms=700, min_seg_ms=400)
        assert len(segs) == 1

    def test_too_short_segment_excluded(self):
        """min_seg_ms(400ms) 미만 발화 → 제외."""
        db, fs = self._make_db([
            (0.0, 0.2, 'voice'),    # 200ms → 너무 짧음
            (1.5, 2.5, 'voice'),    # 1000ms → 정상
        ])
        segs = vad_segments(db, fs, ref_min_db=-45.0,
                            silence_gap_ms=700, min_seg_ms=400)
        assert len(segs) == 1

    def test_full_silent_returns_empty(self):
        """완전 무음 신호 → 세그먼트 없음."""
        db    = np.full(500, -90.0, dtype=np.float32)
        fs    = 0.02
        segs  = vad_segments(db, fs, ref_min_db=-45.0,
                             silence_gap_ms=700, min_seg_ms=400)
        assert segs == []

    def test_segment_times_are_positive(self):
        """반환된 구간 시각이 모두 0 이상이어야 한다."""
        db, fs = self._make_db([(0.5, 2.0, 'voice'), (2.0, 3.0, 'silent')])
        segs = vad_segments(db, fs, ref_min_db=-45.0,
                            silence_gap_ms=700, min_seg_ms=400)
        for start, end in segs:
            assert start >= 0.0
            assert end > start


# ─────────────────────────────────────────────────────────────────────────────
# parse_script 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestParseScript:
    SAMPLE_SCRIPT = """
[박편육]
안녕하세요 테스트입니다.

[김버그]
네 안녕하세요.
잘 들립니까?

[임채팅]
네 잘 들립니다.
"""

    def test_returns_list(self):
        result = parse_script(self.SAMPLE_SCRIPT)
        assert isinstance(result, list)

    def test_speaker_names_extracted(self):
        result = parse_script(self.SAMPLE_SCRIPT)
        speakers = {r['speaker'] for r in result}
        assert '박편육' in speakers
        assert '김버그' in speakers
        assert '임채팅' in speakers

    def test_texts_not_empty(self):
        result = parse_script(self.SAMPLE_SCRIPT)
        for r in result:
            assert r['text'].strip() != ''

    def test_line_idx_sequential(self):
        result = parse_script(self.SAMPLE_SCRIPT)
        for i, r in enumerate(result):
            assert r['line_idx'] == i

    def test_empty_script_returns_empty(self):
        assert parse_script("") == []
        assert parse_script("   \n\n   ") == []


# ─────────────────────────────────────────────────────────────────────────────
# load_script_reference 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadScriptReference:
    def test_returns_string(self):
        result = load_script_reference()
        assert isinstance(result, str)

    def test_not_empty_when_analyze_hybrid_exists(self):
        """analyze_hybrid.py 가 존재하면 SCRIPT_REFERENCE 가 비어 있으면 안 된다."""
        hybrid_path = Path(__file__).parent.parent.parent.parent.parent / "analyze_hybrid.py"
        if not hybrid_path.exists():
            pytest.skip("analyze_hybrid.py 를 찾을 수 없어 건너뜀")
        result = load_script_reference()
        assert len(result) > 10, "SCRIPT_REFERENCE 가 너무 짧거나 비어 있음"

    def test_contains_speaker_tag(self):
        """결과에 [화자명] 형식의 태그가 포함되어야 한다."""
        hybrid_path = Path(__file__).parent.parent.parent.parent.parent / "analyze_hybrid.py"
        if not hybrid_path.exists():
            pytest.skip("analyze_hybrid.py 를 찾을 수 없어 건너뜀")
        result = load_script_reference()
        import re
        assert re.search(r'\[[^\]]+\]', result), "[화자] 태그를 찾을 수 없음"


# ─────────────────────────────────────────────────────────────────────────────
# analyze_by_script 통합 테스트 (무음 파일 → 전체 음단절)
# ─────────────────────────────────────────────────────────────────────────────

SIMPLE_SCRIPT = """
[화자A]
안녕하세요 첫 번째 대사입니다.

[화자B]
두 번째 대사입니다.

[화자A]
세 번째 대사입니다.
"""


class TestAnalyzeByScript:
    SR = 16000

    def _make_ref_with_speech(self, tmp_path: Path) -> Path:
        """정답지: 3개 발화 + 묵음으로 구성된 WAV."""
        sr = self.SR
        silence  = _silent_wav(duration=1.0, sr=sr)
        utterance = _sine_wav(freq=440, duration=2.0, sr=sr, amplitude=0.5)
        # 발화1 - 묵음 - 발화2 - 묵음 - 발화3
        audio = np.concatenate([
            utterance, silence,
            utterance, silence,
            utterance,
        ])
        p = tmp_path / "ref.wav"
        _write_wav(p, audio, sr=sr)
        return p

    def _make_test_silent(self, tmp_path: Path, duration: float = 15.0) -> Path:
        """테스트 파일: 완전 무음."""
        audio = _silent_wav(duration=duration, sr=self.SR)
        p = tmp_path / "test_silent.wav"
        _write_wav(p, audio, sr=self.SR)
        return p

    def _make_test_matching(self, tmp_path: Path) -> Path:
        """테스트 파일: 정답지와 동일한 패턴 (음단절 없음)."""
        sr = self.SR
        silence   = _silent_wav(duration=1.0, sr=sr)
        utterance = _sine_wav(freq=440, duration=2.0, sr=sr, amplitude=0.5)
        audio = np.concatenate([
            utterance, silence,
            utterance, silence,
            utterance,
        ])
        p = tmp_path / "test_match.wav"
        _write_wav(p, audio, sr=sr)
        return p

    def test_silent_test_file_all_dropped(self, tmp_path):
        """완전 무음 테스트 파일 → 모든 대사가 음단절 판정 되어야 한다."""
        ref  = self._make_ref_with_speech(tmp_path)
        test = self._make_test_silent(tmp_path)

        result = analyze_by_script(
            ref_path=str(ref),
            test_path=str(test),
            script_text=SIMPLE_SCRIPT,
            silence_gap_ms=700,
            min_seg_ms=400,
            corr_threshold=0.30,
            search_sec=3.0,
        )
        assert isinstance(result, dict)
        assert 'lines' in result
        assert 'dropped_count' in result
        # 무음 테스트 파일은 매칭되는 발화가 없으므로 dropped_count > 0 이어야 함
        assert result['dropped_count'] > 0

    def test_result_has_required_keys(self, tmp_path):
        """결과 딕셔너리에 필수 키가 모두 있어야 한다."""
        ref  = self._make_ref_with_speech(tmp_path)
        test = self._make_test_silent(tmp_path)

        result = analyze_by_script(
            ref_path=str(ref),
            test_path=str(test),
            script_text=SIMPLE_SCRIPT,
            silence_gap_ms=700,
            min_seg_ms=400,
        )
        for key in ('lines', 'dropped_count', 'drop_rate_pct', 'offset_sec'):
            assert key in result, f"결과에 '{key}' 키 없음"

    def test_each_line_has_required_fields(self, tmp_path):
        """각 라인 결과에 필수 필드가 포함되어야 한다."""
        ref  = self._make_ref_with_speech(tmp_path)
        test = self._make_test_silent(tmp_path)

        result = analyze_by_script(
            ref_path=str(ref),
            test_path=str(test),
            script_text=SIMPLE_SCRIPT,
        )
        for line in result['lines']:
            for field in ('speaker', 'text', 'ref_start_s', 'ref_end_s',
                          'max_corr', 'dropped', 'status'):
                assert field in line, f"라인에 '{field}' 필드 없음"

    def test_drop_rate_range(self, tmp_path):
        """drop_rate_pct 는 0~100 범위여야 한다."""
        ref  = self._make_ref_with_speech(tmp_path)
        test = self._make_test_silent(tmp_path)

        result = analyze_by_script(
            ref_path=str(ref),
            test_path=str(test),
            script_text=SIMPLE_SCRIPT,
        )
        assert 0.0 <= result['drop_rate_pct'] <= 100.0

    def test_matching_file_low_dropped(self, tmp_path):
        """정답지와 동일한 패턴의 테스트 파일 → dropped_count 가 0 이어야 한다."""
        ref  = self._make_ref_with_speech(tmp_path)
        test = self._make_test_matching(tmp_path)

        result = analyze_by_script(
            ref_path=str(ref),
            test_path=str(test),
            script_text=SIMPLE_SCRIPT,
            silence_gap_ms=700,
            min_seg_ms=400,
            corr_threshold=0.30,
            search_sec=3.0,
        )
        assert result['dropped_count'] == 0, (
            f"동일 패턴인데 {result['dropped_count']}개 음단절 판정됨")
