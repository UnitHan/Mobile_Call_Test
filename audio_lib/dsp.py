"""audio_lib.dsp — RMS 연산 및 에너지 프로파일 유틸

공개 인터페이스:
    compute_rms(y, frame_length, hop_length, smooth)
        — librosa RMS. smooth=True(기본)이면 3프레임 균일 필터 스무딩.
    energy_profile(audio, sr, frame_ms)
        — stdlib 기반 dB 프로파일. librosa 불필요.
          (script_gap_detector.py / gap_detector.py 공유)
"""
from __future__ import annotations

import numpy as np

from .consts import RMS_FRAME, RMS_HOP, FRAME_MS

try:
    import librosa as _librosa
    from scipy.ndimage import uniform_filter1d as _ufd
except ImportError:
    _librosa = None  # type: ignore
    _ufd = None      # type: ignore


def compute_rms(
    y: np.ndarray,
    frame_length: int = RMS_FRAME,
    hop_length: int = RMS_HOP,
    smooth: bool = True,
) -> np.ndarray:
    """librosa RMS. smooth=True(기본)이면 3프레임 균일 필터로 스무딩.

    Parameters
    ----------
    smooth : bool
        True  → 3프레임 균일 필터 적용 (analyze_hybrid, analyze_caller_dropout 용)
        False → 생(raw) RMS 그대로 반환 (analyze_waveform_* 드롭아웃 검출용)
    """
    if _librosa is None:
        raise ImportError("librosa is required for compute_rms()")
    rms = _librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    if smooth and _ufd is not None:
        return _ufd(rms, size=3)
    return rms


def energy_profile(
    audio: np.ndarray,
    sr: int,
    frame_ms: int = FRAME_MS,
) -> tuple[np.ndarray, float]:
    """프레임별 RMS(dB) 배열과 프레임 길이(초)를 반환.

    stdlib만 사용 — librosa 불필요.
    script_gap_detector.py 및 gap_detector.py 양쪽에서 공유합니다.

    Returns
    -------
    db : np.ndarray (float32)
        프레임별 dB값. 무음 프레임은 -120 dB.
    frame_sec : float
        한 프레임의 실제 길이 (초).
    """
    flen = max(1, int(sr * frame_ms / 1000))
    n    = len(audio) // flen
    db   = np.full(n, -120.0, dtype=np.float32)
    for i in range(n):
        rms_val = float(np.sqrt(np.mean(audio[i * flen:(i + 1) * flen] ** 2)))
        if rms_val > 1e-10:
            db[i] = 20.0 * np.log10(rms_val)
    return db, flen / sr
