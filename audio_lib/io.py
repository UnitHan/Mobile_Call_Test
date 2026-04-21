"""audio_lib.io — WAV 로드 및 그래프 직렬화 유틸

공개 인터페이스:
    load_audio(path, sr)         — librosa 기반 mono float32 로드
    load_wav_mono(path)          — stdlib wave 기반 로드 (librosa 불필요)
    resample(audio, src, dst)    — scipy polyphase 또는 linear 보간
    fig_to_b64(fig)              — matplotlib Figure → base64 PNG 문자열
"""
from __future__ import annotations

import base64
import io
import wave
from pathlib import Path

import numpy as np

try:
    import librosa as _librosa
except ImportError:
    _librosa = None  # type: ignore


def load_audio(path, sr: int = 16000) -> np.ndarray:
    """음원을 mono float32 배열로 로드. librosa 사용."""
    if _librosa is None:
        raise ImportError("librosa is required for load_audio()")
    y, _ = _librosa.load(path, sr=sr, mono=True)
    return y


def load_wav_mono(path: str | Path) -> tuple[np.ndarray, int]:
    """WAV → mono float32 [-1, 1]. stdlib만 사용 — librosa 불필요."""
    with wave.open(str(path), 'rb') as wf:
        sr  = wf.getframerate()
        n   = wf.getnframes()
        nch = wf.getnchannels()
        sw  = wf.getsampwidth()
        raw = wf.readframes(n)
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(sw, np.int16)
    pcm   = np.frombuffer(raw, dtype=dtype)
    if nch > 1:
        pcm = pcm.reshape(-1, nch).mean(axis=1)
    return pcm.astype(np.float32) / float(2 ** (sw * 8 - 1)), sr


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    """샘플레이트 변환. scipy polyphase 가능하면 사용, 없으면 linear 보간."""
    if src == dst:
        return audio
    try:
        import scipy.signal as _sig
        return _sig.resample_poly(audio, dst, src).astype(np.float32)
    except ImportError:
        n_out = int(len(audio) * dst / src)
        return np.interp(
            np.linspace(0, len(audio) - 1, n_out),
            np.arange(len(audio)), audio
        ).astype(np.float32)


def fig_to_b64(fig) -> str:
    """matplotlib Figure → base64 PNG 문자열. Figure를 닫고 반환."""
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return b64
