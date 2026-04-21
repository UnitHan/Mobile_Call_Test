"""
call_recorder.py
────────────────────────────────────────────────────────────────────────────
통화 중 Sound Blaster G8 입력 채널에서 WAV를 실시간으로 녹음합니다.

양쪽 단말의 통화음을 PC에서 직접 녹음:
  G8[0] 입력 ← iPhone 통화음 (단말 헤드폰잭 → G8 마이크/라인인)
  G8[1] 입력 ← Android 통화음

파일명 형식: {platform}_ixiO_{YYYYMMDD_HHMMSS}.wav
  예) iOS_ixiO_20260313_143000.wav
      Android_ixiO_20260313_143000.wav

사용 예:
    from call_recorder import CallRecorder

    rec = CallRecorder(
        speaker1_platform="iOS",
        speaker2_platform="Android",
    )
    rec.start()          # 통화 연결 완료 직후 호출
    # ... 통화 진행 ...
    paths = rec.stop()   # {'speaker1': PosixPath(...), 'speaker2': PosixPath(...)}
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

from usb_audio_devices import resolve_usb_input_device_index

SAMPLE_RATE = 48_000
CHANNELS    = 2   # 2ch로 열어서 mono 믹스 → LINE IN이 ch0/ch1 어느 쪽이든 캡처
DTYPE       = 'float32'
APP_NAME    = 'ixiO'


# ─────────────────────────────────────────────────────────────────────────────
# 단일 채널 녹음기
# ─────────────────────────────────────────────────────────────────────────────

class _ChannelRecorder:
    """단일 USB 입력 채널 녹음기 (스레드 안전)."""

    def __init__(self, device: int, sample_rate: int = SAMPLE_RATE):
        self._device      = device
        self._sample_rate = sample_rate
        self._q: queue.SimpleQueue[np.ndarray] = queue.SimpleQueue()
        self._stream: Optional[sd.InputStream]  = None
        self._chunks: list[np.ndarray]          = []
        self._running   = False
        self._drain_thr: Optional[threading.Thread] = None

    # ── sounddevice 콜백 ──────────────────────────────────────────────────────

    def _callback(self, indata: np.ndarray, _frames: int, _time, status):
        if status:
            print(f"⚠️ [ChannelRecorder dev={self._device}] {status}", flush=True)
        if self._running:
            # 스테레오(2ch)로 열린 경우 mono 믹스 → LINE IN이 ch0/ch1 어느 쪽이든 손실 없이 캡처
            if indata.ndim > 1 and indata.shape[1] > 1:
                mono = indata.mean(axis=1, keepdims=True)
            else:
                mono = indata
            self._q.put(mono.copy())

    # ── API ──────────────────────────────────────────────────────────────────

    def start(self):
        self._chunks.clear()
        self._running = True
        # 장치의 실제 입력 채널 수가 CHANNELS보다 적으면 그 값으로 조정
        dev_info = sd.query_devices(self._device)
        avail_ch = dev_info.get('max_input_channels', 1) if dev_info else 1
        open_ch   = min(CHANNELS, max(avail_ch, 1))
        self._stream = sd.InputStream(
            device=self._device,
            channels=open_ch,
            samplerate=self._sample_rate,
            dtype=DTYPE,
            callback=self._callback,
        )
        self._stream.start()
        self._drain_thr = threading.Thread(target=self._drain, daemon=True)
        self._drain_thr.start()

    def stop(self) -> np.ndarray:
        """녹음 중단 → 누적 데이터 반환."""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._drain_thr:
            self._drain_thr.join(timeout=2.0)
        # 큐에 남은 나머지 수집
        while not self._q.empty():
            try:
                self._chunks.append(self._q.get_nowait())
            except Exception:
                break
        if not self._chunks:
            return np.zeros((0,), dtype=DTYPE)
        raw = np.concatenate([c.flatten() for c in self._chunks])

        # 소프트웨어 입력 게인 적용 (config.RECORDING_GAIN)
        gain = 1.0
        try:
            from config import RECORDING_GAIN
            gain = float(RECORDING_GAIN)
        except (ImportError, AttributeError, ValueError):
            pass
        if gain != 1.0:
            raw = np.clip(raw * gain, -1.0, 1.0)

        return raw

    def _drain(self):
        """백그라운드에서 큐를 소비하여 메모리에 누적."""
        while self._running:
            try:
                chunk = self._q.get()  # 블로킹, 다음 청크까지 대기
                self._chunks.append(chunk)
            except Exception:
                break


# ─────────────────────────────────────────────────────────────────────────────
# WAV 저장 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _save_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """float32 numpy 배열을 16-bit PCM WAV로 저장합니다."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)          # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


# ─────────────────────────────────────────────────────────────────────────────
# 입력 장치 결정 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_input_index(role: str) -> Optional[int]:
    """config.AUDIO_DEVICES[role] 설정으로 USB 입력 장치 index를 반환합니다."""
    try:
        from config import AUDIO_DEVICES
        cfg = AUDIO_DEVICES.get(role, {})
    except ImportError:
        cfg = {}

    return resolve_usb_input_device_index(
        location_id=cfg.get('location_id'),
        usb_port_order=cfg.get('usb_port_order', 1),
        device_index_fallback=cfg.get('device_index'),
        role_label=role,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────

class CallRecorder:
    """두 G8 USB 입력 채널에서 통화음을 동시 녹음합니다.

    Args:
        speaker1_platform: 화자1 OS 이름 (예: 'iOS', 'Android')
        speaker2_platform: 화자2 OS 이름
        input_device1: 화자1 녹음 입력 장치 인덱스. None = config 자동 결정
        input_device2: 화자2 녹음 입력 장치 인덱스. None = config 자동 결정
        output_dir: WAV 저장 디렉토리. None = config.RECORDING_DIR
        app_name: 파일명에 포함될 앱 이름 (기본 'ixiO')
        sample_rate: 녹음 샘플레이트 (기본 48000 Hz)
        record_speaker2: False면 화자2(Android) G8 녹음 생략 (단말 앱이 직접 저장할 때)
    """

    def __init__(
        self,
        speaker1_platform: str = 'iOS',
        speaker2_platform: str = 'Android',
        input_device1: Optional[int] = None,
        input_device2: Optional[int] = None,
        output_dir: Optional[str | Path] = None,
        app_name: str = APP_NAME,
        sample_rate: int = SAMPLE_RATE,
        record_speaker2: bool = True,        carrier_tag: str = '',    ):
        # ── 출력 디렉토리 ────────────────────────────────────────────────────
        if output_dir is None:
            try:
                from config import RECORDING_DIR
                output_dir = RECORDING_DIR
            except (ImportError, AttributeError):
                output_dir = Path.home() / 'Documents' / 'sound' / 'audio_files' / 'recordings'
        # 날짜별 하위 폴더 (YYYY-MM-DD)
        self._output_dir = Path(output_dir) / datetime.now().strftime('%Y-%m-%d')
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # ── 플랫폼 레이블 ────────────────────────────────────────────────────
        self._platform1      = speaker1_platform
        self._platform2      = speaker2_platform
        self._app_name       = app_name
        self._sr             = sample_rate
        self._record_spk2    = record_speaker2
        self._carrier_tag    = carrier_tag

        # ── 입력 장치 인덱스 결정 ────────────────────────────────────────────
        # speaker1 플랫폼에 맞는 config 슬롯 선택
        #   iOS    → 'ios_b'     슬롯 (G8 #0, locationID=1114112)
        #   Android→ 'android_a' 슬롯 (G8 #1, locationID=1179648)
        role1 = 'ios_b'     if 'ios' in speaker1_platform.lower() else 'android_a'
        role2 = 'android_a' if 'android' in speaker2_platform.lower() else 'ios_b'
        self._dev1: Optional[int] = (
            input_device1 if input_device1 is not None else _resolve_input_index(role1)
        )
        self._dev2: Optional[int] = (
            input_device2 if input_device2 is not None else _resolve_input_index(role2)
        )

        self._rec1: Optional[_ChannelRecorder] = None
        self._rec2: Optional[_ChannelRecorder] = None
        self._start_ts: Optional[str]          = None

    # ── 공개 메서드 ──────────────────────────────────────────────────────────

    def start(self) -> bool:
        """통화 연결 완료 직후 호출. 녹음 시작.

        record_speaker2=False 이면 화자1(iOS) 채널만 녹음합니다.

        Returns:
            True = 정상 시작, False = 장치 없음 (녹음 건너뜀)
        """
        if self._dev1 is None:
            print(f"⚠️ [CallRecorder] 화자1 입력 장치 미발견 (dev1={self._dev1}) → 녹음 건너뜀", flush=True)
            return False

        if self._record_spk2 and self._dev2 is None:
            print(f"⚠️ [CallRecorder] 화자2 입력 장치 미발견 (dev2={self._dev2}) → 녹음 건너뜀", flush=True)
            return False

        self._start_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        if self._record_spk2:
            print(f"🎙️ [CallRecorder] 녹음 시작 "
                  f"— {self._platform1}(dev={self._dev1})  "
                  f"{self._platform2}(dev={self._dev2})  "
                  f"ts={self._start_ts}", flush=True)
        else:
            print(f"🎙️ [CallRecorder] 녹음 시작 "
                  f"— {self._platform1}(dev={self._dev1}) 만 녹음 "
                  f"(speaker2 G8 녹음 생략)  ts={self._start_ts}", flush=True)

        self._rec1 = _ChannelRecorder(self._dev1, self._sr)
        self._rec1.start()

        if self._record_spk2 and self._dev2 is not None:
            self._rec2 = _ChannelRecorder(self._dev2, self._sr)
            self._rec2.start()

        return True

    def stop(self) -> dict[str, Optional[Path]]:
        """통화 종료 직전 호출. 녹음 중단 후 WAV 저장.

        Returns:
            {'speaker1': Path | None, 'speaker2': Path | None}
            record_speaker2=False 이면 speaker2는 항상 None 반환.
        """
        result: dict[str, Optional[Path]] = {'speaker1': None, 'speaker2': None}

        if self._rec1 is None:
            print("⚠️ [CallRecorder] 녹음이 시작된 적 없습니다.", flush=True)
            return result

        audio1 = self._rec1.stop()
        ts = self._start_ts or datetime.now().strftime('%Y%m%d_%H%M%S')
        carrier = f"_{self._carrier_tag}" if self._carrier_tag else ''
        path1 = self._output_dir / f"{self._platform1}_{self._app_name}{carrier}_{ts}.wav"
        _save_wav(path1, audio1, self._sr)
        dur1 = len(audio1) / self._sr
        print(f"✅ [CallRecorder] 저장 완료:", flush=True)
        print(f"   {path1}  ({dur1:.1f}s)", flush=True)
        result['speaker1'] = path1

        if self._rec2 is not None:
            audio2 = self._rec2.stop()
            path2 = self._output_dir / f"{self._platform2}_{self._app_name}{carrier}_{ts}.wav"
            _save_wav(path2, audio2, self._sr)
            dur2 = len(audio2) / self._sr
            print(f"   {path2}  ({dur2:.1f}s)", flush=True)
            result['speaker2'] = path2

        self._rec1 = self._rec2 = None
        return result

    @property
    def is_recording(self) -> bool:
        return self._rec1 is not None
