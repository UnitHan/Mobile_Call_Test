"""
mixer_recorder.py
────────────────────────────────────────────────────────────────────────────
CONNECT 6 × 2대 듀얼 장치 직접 녹음 모듈.

연결 구성:
  Android ── USB ──→ CONNECT 6 #1 Mobile In ──→ Mac USB
  iPhone  ── USB ──→ CONNECT 6 #2 Mobile In ──→ Mac USB

채널 매핑 (0-based):
  ch4  = Mobile In L (각 CONNECT 6)
  ch5  = Mobile In R (각 CONNECT 6)

녹음 흐름:
  1. CONNECT 6 #1, #2 각각 독립 InputStream 오픈
  2. 각 스트림에서 ch4-5(Mobile In) 캡처
  3. stop() 시 재생 시작 시점 기준 앞/뒤 트리밍 후 모노 WAV 저장

파일명 형식: {platform}_ixiO_{YYYYMMDD_HHMMSS}.wav
  예) iOS_ixiO_20260324_143000.wav
      Android_ixiO_20260324_143000.wav

사용 예:
    from mixer_recorder import MixerRecorder

    rec = MixerRecorder()
    rec.start()
    # ... 통화 진행 ...
    paths = rec.stop()  # {'ios': PosixPath(...), 'android': PosixPath(...)}
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import queue
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 48_000
DTYPE = 'float32'
APP_NAME = 'ixiO'

# CONNECT 6 장치/채널 설정 (2대 구성 — 각각 Mobile In 사용)
CONNECT6_DEVICE_NAMES = ('CONNECT 6',)
CONNECT6_OPEN_CHANNELS = 18         # 18ch 전체를 열어 Loopback 채널까지 캡처
CONNECT6_IOS_CHANNELS = (4, 5)      # Mobile In L/R ch5-6 (0-based: 4,5) — iPhone USB
CONNECT6_ANDROID_CHANNELS = (4, 5)  # Mobile In L/R ch5-6 (0-based: 4,5) — Android USB


def _find_input_device(patterns: tuple[str, ...], min_channels: int = 1) -> Optional[int]:
    """장치 이름 패턴으로 입력 장치 인덱스를 찾습니다 (첫 번째 매칭)."""
    for i, dev in enumerate(sd.query_devices()):
        if dev.get('max_input_channels', 0) < min_channels:
            continue
        name = dev.get('name', '')
        if any(p in name for p in patterns):
            return i
    return None


def _find_all_input_devices(patterns: tuple[str, ...], min_channels: int = 1) -> list[int]:
    """장치 이름 패턴으로 매칭되는 모든 입력 장치 인덱스를 반환합니다."""
    result = []
    for i, dev in enumerate(sd.query_devices()):
        if dev.get('max_input_channels', 0) < min_channels:
            continue
        name = dev.get('name', '')
        if any(p in name for p in patterns):
            result.append(i)
    return result


def _resolve_connect6_device_by_location_id(role: str) -> Optional[int]:
    """config.py의 AUDIO_DEVICES[role].location_id로 CONNECT 6 입력 장치 인덱스를 찾습니다."""
    try:
        from usb_audio_devices import resolve_usb_input_device_index
        from config import AUDIO_DEVICES
        cfg = AUDIO_DEVICES.get(role, {})
        if cfg.get('location_id') is not None:
            return resolve_usb_input_device_index(
                location_id=cfg['location_id'],
                usb_port_order=cfg.get('usb_port_order', 1),
                device_index_fallback=cfg.get('device_index'),
                role_label=f'MixerRecorder/{role}',
            )
    except (ImportError, AttributeError):
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# WAV 저장
# ─────────────────────────────────────────────────────────────────────────────

def _rms_normalize_for_platform(audio: np.ndarray, sr: int, path: Path,
                                tc_type: str = '') -> np.ndarray:
    """파일명에서 플랫폼을 감지하여 정답지 RMS에 맞춰 정규화."""
    fname = path.name.lower()
    ref_path = None

    try:
        import sys as _sys
        _cfg_dir = Path(__file__).resolve().parent.parent.parent.parent
        if str(_cfg_dir) not in _sys.path:
            _sys.path.insert(0, str(_cfg_dir))
        if tc_type in ('TC_03', 'TC_04'):
            from _hybrid_config import VISHING_REF_ANDROID, VISHING_REF_IOS
            if fname.startswith('android'):
                ref_path = VISHING_REF_ANDROID.get(1)
            elif fname.startswith('ios'):
                ref_path = VISHING_REF_IOS.get(1)
        else:
            from _hybrid_config import AUDIO_REFERENCE_ANDROID, AUDIO_REFERENCE_IOS
            if fname.startswith('android'):
                ref_path = AUDIO_REFERENCE_ANDROID.get(1)
            elif fname.startswith('ios'):
                ref_path = AUDIO_REFERENCE_IOS.get(1)
    except (ImportError, AttributeError):
        pass

    if ref_path is None or not Path(ref_path).is_file():
        return audio

    try:
        import soundfile as _sf
        ref_data, _ = _sf.read(ref_path, dtype='float32')
        if ref_data.ndim > 1:
            ref_data = ref_data.mean(axis=1)
        ref_rms = float(np.sqrt(np.mean(ref_data**2)))
        rec_rms = float(np.sqrt(np.mean(audio**2)))

        if rec_rms < 1e-8 or ref_rms < 1e-8:
            return audio

        scale = ref_rms / rec_rms
        out = audio * scale

        peak = float(np.max(np.abs(out)))
        if peak > 0.99:
            out = out * (0.99 / peak)

        platform = 'Android' if fname.startswith('android') else 'iOS'
        print(f"  📐 [{platform}] RMS 정규화: {rec_rms:.4f} → {ref_rms:.4f} "
              f"(×{scale:.2f}, peak={peak:.4f})")
        return out
    except Exception as e:
        print(f"  ⚠️ RMS 정규화 실패 ({e}) → 원본 유지")
        return audio


def _save_mono_wav(path: Path, audio: np.ndarray, sample_rate: int,
                   tc_type: str = '') -> None:
    """float32 모노 numpy 배열을 16-bit PCM WAV로 저장합니다.
    파일명에서 플랫폼을 자동 감지하여 정답지 RMS 정규화를 적용합니다.
    TC_03/TC_04일 때는 audiomass 정답지 기준으로 정규화합니다.
    """
    audio = _rms_normalize_for_platform(audio, sample_rate, path, tc_type=tc_type)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────

class MixerRecorder:
    """CONNECT 6 × 2대에서 Android + iOS 동시 녹음.

    각 CONNECT 6의 Mobile In(ch4-5) 스트림을 각각 열어 캡처:
      - CONNECT 6 #1 (android_a) → Android 녹음
      - CONNECT 6 #2 (ios_b)     → iOS 녹음

    Args:
        output_dir: WAV 저장 디렉토리. None = config.RECORDING_DIR 또는 기본 경로
        app_name: 파일명에 포함될 앱 이름 (기본 'ixiO')
        sample_rate: 녹음 샘플레이트 (기본 48000 Hz)
        device_index: CONNECT 6 #1(Android) 장치 인덱스. None = 자동 감지
        ios_channels: iOS 녹음 채널 (0-based 튜플). None = 기본값 (4,5)
        android_channels: Android 녹음 채널 (0-based 튜플). None = 기본값 (4,5)
        android_device_index: CONNECT 6 #2(iOS) 장치 인덱스. None = 자동 감지
    """

    def __init__(
        self,
        output_dir: Optional[str | Path] = None,
        app_name: str = APP_NAME,
        sample_rate: int = SAMPLE_RATE,
        device_index: Optional[int] = None,
        ios_channels: Optional[tuple[int, ...]] = None,
        android_channels: Optional[tuple[int, ...]] = None,
        android_device_index: Optional[int] = None,
        tc_type: str = '',
        carrier_tag: str = '',
        **_kwargs,
    ):
        self._tc_type = tc_type
        self._carrier_tag = carrier_tag
        # 출력 디렉토리 — app_scanner.py 의 COLLECTED_DIR 과 동일 경로 사용
        if output_dir is None:
            try:
                from config import RECORDING_DIR
                output_dir = Path(RECORDING_DIR) / 'collected'
            except (ImportError, AttributeError):
                output_dir = Path.home() / 'Documents' / 'sound' / 'audio_files' / 'recordings' / 'collected'
        # 날짜별 하위 폴더 (YYYY-MM-DD)
        self._output_dir = Path(output_dir) / datetime.now().strftime('%Y-%m-%d')
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._app_name = app_name
        self._sr = sample_rate

        # config.py 채널 매핑 (CONNECT6_REC_CHANNELS_*)
        try:
            from config import CONNECT6_REC_CHANNELS_ANDROID, CONNECT6_REC_CHANNELS_IOS
            cfg_android_ch = CONNECT6_REC_CHANNELS_ANDROID
            cfg_ios_ch = CONNECT6_REC_CHANNELS_IOS
        except (ImportError, AttributeError):
            cfg_android_ch = None
            cfg_ios_ch = None

        # 녹음 채널 (0-based 튜플) — 인자 > config > 모듈 기본값
        self._android_channels = android_channels or cfg_android_ch or CONNECT6_ANDROID_CHANNELS
        self._ios_channels = ios_channels or cfg_ios_ch or CONNECT6_IOS_CHANNELS

        # ── CONNECT 6 #1 (Android) 장치 인덱스 ──────────────────────────────
        if device_index is not None:
            self._device_idx = device_index
        else:
            resolved = _resolve_connect6_device_by_location_id('android_a')
            self._device_idx = resolved if resolved is not None else _find_input_device(CONNECT6_DEVICE_NAMES)

        # ── CONNECT 6 #2 (iOS) 장치 인덱스 ──────────────────────────────────
        if android_device_index is not None:
            self._ios_device_idx: Optional[int] = android_device_index
        else:
            resolved = _resolve_connect6_device_by_location_id('ios_b')
            if resolved is not None and resolved != self._device_idx:
                self._ios_device_idx = resolved
            else:
                # locationID 해석 실패 시 이름으로 두 번째 CONNECT 6 찾기
                all_devs = _find_all_input_devices(CONNECT6_DEVICE_NAMES)
                other = [d for d in all_devs if d != self._device_idx]
                self._ios_device_idx = other[0] if other else None

        # CONNECT 6 #1 (Android) 스트림 / 녹음 상태
        self._q: queue.SimpleQueue[np.ndarray] = queue.SimpleQueue()
        self._chunks: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._drain_thr: Optional[threading.Thread] = None
        self._start_ts: Optional[str] = None
        self._running = False

        # 재생 시작 동기화용 타임스탬프 (초 단위, time.time())
        self._rec_start_time: Optional[float] = None   # stream.start() 시각
        self._play_start_time: Optional[float] = None  # 재생 시작 시각 (외부에서 set)
        self._play_duration: Optional[float] = None    # 재생 음원 길이(초) (외부에서 set)

        # CONNECT 6 #2 (iOS) 스트림
        self._ios_q: queue.SimpleQueue[np.ndarray] = queue.SimpleQueue()
        self._ios_chunks: list[np.ndarray] = []
        self._ios_stream: Optional[sd.InputStream] = None
        self._ios_drain_thr: Optional[threading.Thread] = None

    def set_play_start_time(self, ts: float) -> None:
        """재생 시작 시각을 기록합니다 (녹음 트리밍에 사용)."""
        self._play_start_time = ts
        if self._rec_start_time:
            offset_ms = (ts - self._rec_start_time) * 1000
            print(f"🎯 [MixerRecorder] 재생 시작 등록: 녹음 시작 대비 +{offset_ms:.0f}ms", flush=True)

    def set_play_duration(self, duration_sec: float) -> None:
        """재생 음원 총 길이를 기록합니다 (trailing silence 제거에 사용)."""
        self._play_duration = duration_sec

    @property
    def is_recording(self) -> bool:
        return self._running

    def _callback(self, indata: np.ndarray, _frames: int, _time, status):
        if status:
            print(f"⚠️ [MixerRecorder/Android] {status}", flush=True)
        if self._running:
            self._q.put(indata.copy())

    def _drain(self):
        while self._running:
            try:
                self._chunks.append(self._q.get(timeout=0.5))
            except Exception:
                continue

    # ── CONNECT 6 #2 (iOS) 콜백 ──────────────────────────────────────────────

    def _ios_callback(self, indata: np.ndarray, _frames: int, _time, status):
        if status:
            print(f"⚠️ [MixerRecorder/iOS] {status}", flush=True)
        if self._running:
            self._ios_q.put(indata.copy())

    def _ios_drain(self):
        while self._running:
            try:
                self._ios_chunks.append(self._ios_q.get(timeout=0.5))
            except Exception:
                continue

    def start(self) -> bool:
        """녹음 시작. CONNECT 6 #1(Android)을 찾지 못하면 False 반환."""
        if self._device_idx is None:
            print("⚠️ [MixerRecorder] CONNECT 6 #1(Android) 장치를 찾을 수 없습니다 → 녹음 불가", flush=True)
            return False

        dev_info = sd.query_devices(self._device_idx)
        dev_name = dev_info.get('name', '?')
        avail_ch = dev_info.get('max_input_channels', 1)
        open_ch = min(CONNECT6_OPEN_CHANNELS, max(avail_ch, 1))

        self._chunks.clear()
        self._ios_chunks.clear()
        self._start_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._running = True
        import time as _time

        # ── CONNECT 6 #1 (Android) 스트림 ────────────────────────────────────
        self._stream = sd.InputStream(
            device=self._device_idx,
            channels=open_ch,
            samplerate=self._sr,
            dtype=DTYPE,
            callback=self._callback,
        )
        self._stream.start()
        self._rec_start_time = _time.time()  # 녹음 시작 시각 기록
        self._drain_thr = threading.Thread(target=self._drain, daemon=True)
        self._drain_thr.start()

        print(f"🎙️ [MixerRecorder] CONNECT 6 #1(Android) 녹음 시작 — '{dev_name}' (dev={self._device_idx}, {open_ch}ch)", flush=True)
        print(f"    Android: ch{','.join(str(c+1) for c in self._android_channels)} (0-based: {self._android_channels})", flush=True)

        # ── CONNECT 6 #2 (iOS) 스트림 ────────────────────────────────────────
        if self._ios_device_idx is not None:
            ios_info = sd.query_devices(self._ios_device_idx)
            ios_name = ios_info.get('name', '?')
            ios_avail = ios_info.get('max_input_channels', 1)
            ios_open_ch = min(CONNECT6_OPEN_CHANNELS, max(ios_avail, 1))
            self._ios_stream = sd.InputStream(
                device=self._ios_device_idx,
                channels=ios_open_ch,
                samplerate=self._sr,
                dtype=DTYPE,
                callback=self._ios_callback,
            )
            self._ios_stream.start()
            self._ios_drain_thr = threading.Thread(target=self._ios_drain, daemon=True)
            self._ios_drain_thr.start()
            print(f"🎙️ [MixerRecorder] CONNECT 6 #2(iOS) 녹음 시작 — '{ios_name}' (dev={self._ios_device_idx}, {ios_open_ch}ch)", flush=True)
            print(f"    iOS:     ch{','.join(str(c+1) for c in self._ios_channels)} (0-based: {self._ios_channels})", flush=True)
        else:
            print("⚠️ [MixerRecorder] CONNECT 6 #2(iOS) 장치를 찾을 수 없습니다 → iOS 녹음 불가", flush=True)

        return True

    def stop(self) -> dict[str, Optional[Path]]:
        """녹음 중단 → iOS / Android 각각 모노 WAV 저장.

        파일명 규칙: 발화자 기준
          - CONNECT 6 #1(Android) Mobile In 캡처 = Android가 수신한 상대방 음성 → Android_*.wav
          - CONNECT 6 #2(iOS) Mobile In 캡처 = iPhone이 수신한 상대방 음성 → iOS_*.wav

        Returns:
            {'ios': Path | None, 'android': Path | None}
        """
        result: dict[str, Optional[Path]] = {'ios': None, 'android': None}

        if not self._running:
            print("⚠️ [MixerRecorder] 녹음이 시작된 적 없습니다.", flush=True)
            return result

        self._running = False

        # ── CONNECT 6 #1 (Android) 스트림 정지 ───────────────────────────────
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._drain_thr:
            self._drain_thr.join(timeout=2.0)
        while not self._q.empty():
            try:
                self._chunks.append(self._q.get_nowait())
            except Exception:
                break

        # ── CONNECT 6 #2 (iOS) 스트림 정지 ───────────────────────────────────
        if self._ios_stream:
            self._ios_stream.stop()
            self._ios_stream.close()
            self._ios_stream = None
        if self._ios_drain_thr:
            self._ios_drain_thr.join(timeout=2.0)
        while not self._ios_q.empty():
            try:
                self._ios_chunks.append(self._ios_q.get_nowait())
            except Exception:
                break

        ts = self._start_ts or datetime.now().strftime('%Y%m%d_%H%M%S')

        # ── 재생 시작 오프셋 기반 트리밍 샘플 수 계산 ────────────────────────
        # 녹음은 재생보다 먼저 시작됨 → 앞부분 무음을 잘라냄
        trim_samples = 0
        if self._play_start_time and self._rec_start_time:
            offset_sec = self._play_start_time - self._rec_start_time
            if offset_sec > 0:
                trim_samples = int(offset_sec * self._sr)
                print(f"✂️ [MixerRecorder] 앞 트리밍: 녹음→재생 오프셋 {offset_sec*1000:.0f}ms = {trim_samples} samples", flush=True)

        # 재생 길이 기반 뒤 트리밍 — 녹음이 재생보다 오래 지속된 분량 제거
        # target_samples: 재생 음원 길이에 0.5초 여유를 더한 샘플 수
        target_samples: Optional[int] = None
        if self._play_duration is not None and self._play_duration > 0:
            target_samples = int((self._play_duration + 1.5) * self._sr)
            print(f"✂️ [MixerRecorder] 뒤 트리밍: 음원 길이 {self._play_duration:.1f}s + 1.5s 여유 = {target_samples} samples", flush=True)

        # 소프트웨어 게인 (디바이스별 / 글로벌 폴백)
        gain_global = 1.0
        gain_ios = None
        gain_android = None
        try:
            from config import RECORDING_GAIN
            gain_global = float(RECORDING_GAIN)
        except (ImportError, AttributeError, ValueError):
            pass
        try:
            from config import RECORDING_GAIN_IOS
            if RECORDING_GAIN_IOS is not None:
                gain_ios = float(RECORDING_GAIN_IOS)
        except (ImportError, AttributeError, ValueError):
            pass
        try:
            from config import RECORDING_GAIN_ANDROID
            if RECORDING_GAIN_ANDROID is not None:
                gain_android = float(RECORDING_GAIN_ANDROID)
        except (ImportError, AttributeError, ValueError):
            pass

        g_ios = gain_ios if gain_ios is not None else gain_global
        g_android = gain_android if gain_android is not None else gain_global

        if g_ios != 1.0 or g_android != 1.0:
            print(f"🔊 [MixerRecorder] 게인: Android(MobileIn)={g_android:.2f}x, iOS(MobileIn)={g_ios:.2f}x", flush=True)

        # ── CONNECT 6 #1 → Android_*.wav ─────────────────────────────────────
        if self._chunks:
            raw_android = np.concatenate(self._chunks, axis=0)
            if raw_android.shape[1] > max(self._android_channels):
                android_audio = raw_android[:, list(self._android_channels)]
                if android_audio.ndim > 1 and android_audio.shape[1] > 1:
                    android_audio = android_audio.mean(axis=1)
                else:
                    android_audio = android_audio.flatten()
                # 재생 시작 전 무음 트리밍 (앞)
                if trim_samples > 0 and trim_samples < len(android_audio):
                    android_audio = android_audio[trim_samples:]
                # 재생 끝 이후 무음 트리밍 (뒤)
                if target_samples is not None and len(android_audio) > target_samples:
                    android_audio = android_audio[:target_samples]
                if g_android != 1.0:
                    android_audio = np.clip(android_audio * g_android, -1.0, 1.0)
                tc_tag = f"_{self._tc_type}" if self._tc_type else ''
                carrier = f"_{self._carrier_tag}" if self._carrier_tag else ''
                path = self._output_dir / f"Android_{self._app_name}{carrier}{tc_tag}_{ts}.wav"
                _save_mono_wav(path, android_audio, self._sr, tc_type=self._tc_type)
                dur = len(android_audio) / self._sr
                print(f"✅ [MixerRecorder] Android 녹음 저장: {path}  ({dur:.1f}s)  src=CONNECT6#1 ch={self._android_channels}", flush=True)
                result['android'] = path
            else:
                print(f"⚠️ [MixerRecorder] Android 채널({self._android_channels}) 부족 (열린 채널: {raw_android.shape[1]})", flush=True)
        else:
            print("⚠️ [MixerRecorder] CONNECT 6 #1(Android) 녹음 데이터 없음", flush=True)

        # ── CONNECT 6 #2 → iOS_*.wav ────────────────────────────────────────
        if self._ios_chunks:
            raw_ios = np.concatenate(self._ios_chunks, axis=0)
            if raw_ios.shape[1] > max(self._ios_channels):
                ios_audio = raw_ios[:, list(self._ios_channels)]
                if ios_audio.ndim > 1 and ios_audio.shape[1] > 1:
                    ios_audio = ios_audio.mean(axis=1)
                else:
                    ios_audio = ios_audio.flatten()
                # 재생 시작 전 무음 트리밍 (앞)
                if trim_samples > 0 and trim_samples < len(ios_audio):
                    ios_audio = ios_audio[trim_samples:]
                # 재생 끝 이후 무음 트리밍 (뒤)
                if target_samples is not None and len(ios_audio) > target_samples:
                    ios_audio = ios_audio[:target_samples]
                if g_ios != 1.0:
                    ios_audio = np.clip(ios_audio * g_ios, -1.0, 1.0)
                tc_tag = f"_{self._tc_type}" if self._tc_type else ''
                carrier = f"_{self._carrier_tag}" if self._carrier_tag else ''
                path = self._output_dir / f"iOS_{self._app_name}{carrier}{tc_tag}_{ts}.wav"
                _save_mono_wav(path, ios_audio, self._sr, tc_type=self._tc_type)
                dur = len(ios_audio) / self._sr
                print(f"✅ [MixerRecorder] iOS 녹음 저장: {path}  ({dur:.1f}s)  src=CONNECT6#2 ch={self._ios_channels}", flush=True)
                result['ios'] = path
            else:
                print(f"⚠️ [MixerRecorder] iOS 채널({self._ios_channels}) 부족 (열린 채널: {raw_ios.shape[1]})", flush=True)
        else:
            print("⚠️ [MixerRecorder] CONNECT 6 #2(iOS) 녹음 데이터 없음", flush=True)

        return result


def mix_recording_with_source(
    recording_path: Path,
    source_audio_path: str | Path,
    output_path: Optional[Path] = None,
    source_channel: Optional[str] = None,
    sample_rate: int = SAMPLE_RATE,
    playback_offset_sec: float = 0.0,
) -> Path:
    """녹음(RX)에 원본 재생 파일(TX)을 믹스하여 양방향 통화 녹음을 생성합니다.

    Args:
        recording_path: 단방향 녹음 WAV (기기가 들은 음성 = RX)
        source_audio_path: 해당 기기에 재생한 원본 오디오 (TX)
        output_path: 저장 경로. None이면 recording_path를 덮어씀
        source_channel: 'L' | 'R' | None — 원본이 스테레오일 때 추출할 채널
        sample_rate: 샘플레이트
        playback_offset_sec: 녹음 시작 대비 재생 시작 오프셋 (초)

    Returns:
        저장된 파일 경로
    """
    import librosa

    if output_path is None:
        output_path = recording_path

    # RX 로드 (녹음: 기기가 들은 상대방 음성)
    rx, _ = librosa.load(str(recording_path), sr=sample_rate, mono=True)

    # TX 로드 (원본: Mac이 기기에 재생한 음성)
    tx, _ = librosa.load(str(source_audio_path), sr=sample_rate, mono=False)
    if tx.ndim > 1:
        if source_channel == 'L':
            tx = tx[0]
        elif source_channel == 'R':
            tx = tx[1]
        else:
            tx = tx.mean(axis=0)

    # 재생 볼륨 적용 (config.PLAYBACK_VOLUME과 동일하게)
    playback_vol = 0.70
    try:
        from config import PLAYBACK_VOLUME
        playback_vol = float(PLAYBACK_VOLUME)
    except (ImportError, AttributeError, ValueError):
        pass
    tx = tx * playback_vol

    # 오프셋 적용: 녹음 시작 이후 playback_offset_sec 위치에 TX 삽입
    offset_samples = int(playback_offset_sec * sample_rate)
    offset_samples = max(0, offset_samples)

    # 결과 배열: RX 길이 기준
    mixed = rx.copy()

    # TX를 RX 타임라인에 맞춰 삽입
    tx_start = offset_samples
    tx_end = tx_start + len(tx)
    if tx_end > len(mixed):
        mixed = np.pad(mixed, (0, tx_end - len(mixed)))
    avail_len = min(len(tx), len(mixed) - tx_start)
    mixed[tx_start:tx_start + avail_len] += tx[:avail_len]

    # 클리핑 방지 정규화
    peak = np.max(np.abs(mixed))
    if peak > 0.95:
        mixed = mixed * 0.90 / peak

    _save_mono_wav(output_path, mixed, sample_rate)
    dur = len(mixed) / sample_rate
    print(f"🎛️ [MixerRecorder] TX+RX 믹스 완료: {output_path}  ({dur:.1f}s)", flush=True)
    return output_path
