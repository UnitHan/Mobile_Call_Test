"""
audio_playback_mixin.py
─────────────────────────────────────────────────────────────────
오디오 재생 Mixin (IxioAutomatedTest에서 분리, SRP)

담당 기능:
  - _usb_order_for_device   : soundcard index → USB 순서 변환
  - play_audio_after_delay  : 지연 후 화자1·화자2 동시 재생
  - _play_audio_via_adb     : ADB push + Intent로 Android 재생
  - _stop_audio_procs       : 재생 subprocess 전체 강제 종료
  - wait_for_audio_completion : 재생 완료 대기 + 통화 강제 종료 감지

전제:
  self.audio_files           (dict[str, str])
  self.speaker1_output_device, self.speaker2_output_device  (int | None)
  self.speaker1_channel,     self.speaker2_channel          (str | None)
  self.speaker1_output_pair, self.speaker2_output_pair      (str | None)  # "2,3" 등
  self.monitor_enabled       (bool)
  self._audio_procs          (list)
  self.speaker2_platform     ('iOS' | 'Android')
  self.speaker2_device       (UDID / serial)
  self.drivers               (dict[str, WebDriver])
"""

import subprocess
import threading
import time
import wave
from pathlib import Path

from audio_handler import DeviceAudioPlayer


class AudioPlaybackMixin:
    """오디오 재생 전담 Mixin."""

    # ── 유틸 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _usb_order_for_device(device_index: 'int | None') -> 'int | None':
        """사운드카드 device index가 USB 장치 목록에서 몇 번째(1-based)인지 반환.

        macOS 재열거로 index가 바뀌어도 usb_order 기반 복구가 올바르게 작동하도록
        항상 현재 sounddevice 목록을 기준으로 계산합니다.
        device_index가 None이거나 USB 목록에 없으면 None 반환.

        주의: 이름에 'USB'가 없는 CONNECT 6 같은 장치도 포함하기 위해
        usb_audio_devices.get_usb_audio_output_indices()를 사용합니다.
        """
        if device_index is None:
            return None
        try:
            from usb_audio_devices import get_usb_audio_output_indices
            usb_outputs = get_usb_audio_output_indices()
            if device_index in usb_outputs:
                return usb_outputs.index(device_index) + 1
        except Exception:
            pass
        return None

    # ── 재생 ─────────────────────────────────────────────────────────────────

    def play_audio_after_delay(
        self,
        delay: float = 3,
        ref_ts: 'float | None' = None,
        target_offset: float = 0.5,
    ) -> None:
        """지정된 시간 후 오디오 재생 (화자1·화자2 동시 시작).

        ref_ts 가 주어지면 delay 대신 'ref_ts + target_offset' 시각까지 대기합니다.
        ref_ts 는 통화 타이머 00:00 기준점 (accept 명령 전송 시각 등).
        """
        if ref_ts is not None:
            remaining = ref_ts + target_offset - time.time()
            elapsed_from_ref = time.time() - ref_ts
            if remaining > 0:
                print(f"⏱ [TIMING] ref 기준 {elapsed_from_ref*1000:.0f}ms 경과, "
                      f"목표 {target_offset*1000:.0f}ms → {remaining*1000:.0f}ms 대기 후 재생")
                time.sleep(remaining)
            else:
                print(f"⏱ [TIMING] ref 기준 {elapsed_from_ref*1000:.0f}ms 경과 "
                      f"(목표 {target_offset*1000:.0f}ms 이미 {abs(remaining)*1000:.0f}ms 초과) — 즉시 재생")
        else:
            print(f"⏰ {delay}초 대기 후 오디오 재생...")
            time.sleep(delay)

        print(f"\n{'='*60}")
        print(f"🔊 오디오 재생 시작")
        print(f"{'='*60}\n")

        s1_usb_order = self._usb_order_for_device(self.speaker1_output_device)  # type: ignore[attr-defined]
        s2_usb_order = self._usb_order_for_device(self.speaker2_output_device)  # type: ignore[attr-defined]

        try:
            from config import PLAYBACK_VOLUME as _vol
            playback_volume = float(_vol)
        except (ImportError, AttributeError, ValueError):
            playback_volume = 0.95

        # 화자별 재생 볼륨 (config에 지정 시 개별 적용)
        try:
            from config import PLAYBACK_VOLUME_S1, PLAYBACK_VOLUME_S2
            s1_volume = float(PLAYBACK_VOLUME_S1) if PLAYBACK_VOLUME_S1 is not None else playback_volume
            s2_volume = float(PLAYBACK_VOLUME_S2) if PLAYBACK_VOLUME_S2 is not None else playback_volume
        except (ImportError, AttributeError, ValueError):
            s1_volume = playback_volume
            s2_volume = playback_volume

        def _play_s1():
            try:
                audio_file = self.audio_files.get('speaker1')  # type: ignore[attr-defined]
                if audio_file:
                    s1_output_pair = getattr(self, 'speaker1_output_pair', None)  # type: ignore[attr-defined]
                    proc = DeviceAudioPlayer.play_audio_to_device(
                        audio_file,
                        device=self.speaker1_output_device,     # type: ignore[attr-defined]
                        channel=self.speaker1_channel,          # type: ignore[attr-defined]
                        speaker_id='speaker1',
                        monitor=self.monitor_enabled,           # type: ignore[attr-defined]
                        usb_order=s1_usb_order,
                        volume=s1_volume,
                        output_pair=s1_output_pair,
                        play_at=_play_at,
                    )
                    if proc is not None:
                        self._audio_procs.append(proc)          # type: ignore[attr-defined]
                    print(f"✅ 화자1 오디오 재생 시작 "
                          f"(장치={self.speaker1_output_device if self.speaker1_output_device is not None else '기본'}, "  # type: ignore[attr-defined]
                          f"usb_order={s1_usb_order}, "
                          f"채널={self.speaker1_channel or '양쪽'}, "                              # type: ignore[attr-defined]
                          f"출력쌍={s1_output_pair or '기본'}, "
                          f"volume={s1_volume:.2f}, "
                          f"모니터={'ON' if self.monitor_enabled else 'OFF'})\n")                  # type: ignore[attr-defined]
                else:
                    print(f"⚠️ 화자1 오디오 파일이 설정되지 않음\n")
            except Exception as e:
                print(f"⚠️ 화자1 오디오 재생 실패: {e}\n")

        def _play_s2():
            try:
                audio_file2 = self.audio_files.get('speaker2')  # type: ignore[attr-defined]
                if audio_file2:
                    s2_output_pair = getattr(self, 'speaker2_output_pair', None)  # type: ignore[attr-defined]
                    proc = DeviceAudioPlayer.play_audio_to_device(
                        audio_file2,
                        device=self.speaker2_output_device,     # type: ignore[attr-defined]
                        channel=self.speaker2_channel,          # type: ignore[attr-defined]
                        speaker_id='speaker2',
                        monitor=self.monitor_enabled,           # type: ignore[attr-defined]
                        usb_order=s2_usb_order,
                        volume=s2_volume,
                        output_pair=s2_output_pair,
                        play_at=_play_at,
                    )
                    if proc is not None:
                        self._audio_procs.append(proc)          # type: ignore[attr-defined]
                    print(f"✅ 화자2 오디오 재생 시작 "
                          f"(장치={self.speaker2_output_device if self.speaker2_output_device is not None else '기본'}, "  # type: ignore[attr-defined]
                          f"usb_order={s2_usb_order}, "
                          f"채널={self.speaker2_channel or '양쪽'}, "                              # type: ignore[attr-defined]
                          f"출력쌍={s2_output_pair or '기본'}, "
                          f"volume={s2_volume:.2f}, "
                          f"모니터={'ON' if self.monitor_enabled else 'OFF'})\n")                  # type: ignore[attr-defined]
                else:
                    print(f"⚠️ 화자2 오디오 파일이 설정되지 않음\n")
            except Exception as e:
                print(f"⚠️ 화자2 오디오 재생 실패: {e}\n")

        # ── 두 워커 동기화: play_at 시각을 계산하여 동시 재생 보장 ────────
        # subprocess 초기화(Python 기동 + import + 파일 로드)에 충분한 여유 시간 부여
        _SYNC_LEAD_SEC = 3.0
        _play_at = time.time() + _SYNC_LEAD_SEC
        self._play_at = _play_at  # type: ignore[attr-defined]
        print(f"⏱ [SYNC] 두 화자 동기 재생 예약: {_SYNC_LEAD_SEC:.1f}초 후 동시 시작")

        t1 = threading.Thread(target=_play_s1, daemon=True)
        t2 = threading.Thread(target=_play_s2, daemon=True)
        t1.start(); t2.start()
        t1.join();  t2.join()

    # ── Pre-warm 재생 (OFFHOOK 전 subprocess 초기화) ──────────────────────

    def prepare_audio_players(self) -> bool:
        """OFFHOOK 전에 오디오 subprocess를 미리 생성합니다 (pre-warm).

        subprocess는 Python 인터프리터 시작 → import → 오디오 파일 로드 →
        OutputStream 열기까지 완료한 후, play_at_file에 타임스탬프가 기록될 때까지
        10ms 간격으로 폴링 대기합니다.

        이 메서드를 Step1(accept) 시점에 호출하면, OFFHOOK(Step2) 시점에는
        subprocess가 이미 초기화되어 있으므로 trigger_audio_playback() 호출 즉시
        (~200ms 여유) 재생이 시작됩니다.

        Returns:
            True if at least one subprocess was spawned.
        """
        import os
        import tempfile

        s1_usb_order = self._usb_order_for_device(self.speaker1_output_device)  # type: ignore[attr-defined]
        s2_usb_order = self._usb_order_for_device(self.speaker2_output_device)  # type: ignore[attr-defined]

        try:
            from config import PLAYBACK_VOLUME as _vol
            playback_volume = float(_vol)
        except (ImportError, AttributeError, ValueError):
            playback_volume = 0.95
        try:
            from config import PLAYBACK_VOLUME_S1, PLAYBACK_VOLUME_S2
            s1_volume = float(PLAYBACK_VOLUME_S1) if PLAYBACK_VOLUME_S1 is not None else playback_volume
            s2_volume = float(PLAYBACK_VOLUME_S2) if PLAYBACK_VOLUME_S2 is not None else playback_volume
        except (ImportError, AttributeError, ValueError):
            s1_volume = playback_volume
            s2_volume = playback_volume

        # play_at_file: 각 워커가 폴링할 파일 경로
        ts_dir = tempfile.gettempdir()
        self._play_at_files = {}  # type: ignore[attr-defined]
        for sid in ('speaker1', 'speaker2'):
            path = os.path.join(ts_dir, f'play_at_{sid}.ts')
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            self._play_at_files[sid] = path

        spawned = False
        self._pre_warm_threads = []  # type: ignore[attr-defined]

        # speaker1
        audio_file_s1 = self.audio_files.get('speaker1')  # type: ignore[attr-defined]
        if audio_file_s1:
            s1_output_pair = getattr(self, 'speaker1_output_pair', None)
            def _spawn_s1():
                try:
                    proc = DeviceAudioPlayer.play_audio_to_device(
                        audio_file_s1,
                        device=self.speaker1_output_device,     # type: ignore[attr-defined]
                        channel=self.speaker1_channel,          # type: ignore[attr-defined]
                        speaker_id='speaker1',
                        monitor=self.monitor_enabled,           # type: ignore[attr-defined]
                        usb_order=s1_usb_order,
                        volume=s1_volume,
                        output_pair=s1_output_pair,
                        play_at_file=self._play_at_files['speaker1'],
                    )
                    if proc is not None:
                        self._audio_procs.append(proc)          # type: ignore[attr-defined]
                    print(f"✅ 화자1 오디오 pre-warm 완료 "
                          f"(장치={self.speaker1_output_device if self.speaker1_output_device is not None else '기본'}, "  # type: ignore[attr-defined]
                          f"usb_order={s1_usb_order}, "
                          f"채널={self.speaker1_channel or '양쪽'}, "                              # type: ignore[attr-defined]
                          f"출력쌍={s1_output_pair or '기본'}, "
                          f"volume={s1_volume:.2f})\n")
                except Exception as e:
                    print(f"⚠️ 화자1 pre-warm 실패: {e}\n")
            t = threading.Thread(target=_spawn_s1, daemon=True)
            t.start()
            self._pre_warm_threads.append(t)
            spawned = True

        # speaker2
        audio_file_s2 = self.audio_files.get('speaker2')  # type: ignore[attr-defined]
        if audio_file_s2:
            s2_output_pair = getattr(self, 'speaker2_output_pair', None)
            def _spawn_s2():
                try:
                    proc = DeviceAudioPlayer.play_audio_to_device(
                        audio_file_s2,
                        device=self.speaker2_output_device,     # type: ignore[attr-defined]
                        channel=self.speaker2_channel,          # type: ignore[attr-defined]
                        speaker_id='speaker2',
                        monitor=self.monitor_enabled,           # type: ignore[attr-defined]
                        usb_order=s2_usb_order,
                        volume=s2_volume,
                        output_pair=s2_output_pair,
                        play_at_file=self._play_at_files['speaker2'],
                    )
                    if proc is not None:
                        self._audio_procs.append(proc)          # type: ignore[attr-defined]
                    print(f"✅ 화자2 오디오 pre-warm 완료 "
                          f"(장치={self.speaker2_output_device if self.speaker2_output_device is not None else '기본'}, "  # type: ignore[attr-defined]
                          f"usb_order={s2_usb_order}, "
                          f"채널={self.speaker2_channel or '양쪽'}, "                              # type: ignore[attr-defined]
                          f"출력쌍={s2_output_pair or '기본'}, "
                          f"volume={s2_volume:.2f})\n")
                except Exception as e:
                    print(f"⚠️ 화자2 pre-warm 실패: {e}\n")
            t = threading.Thread(target=_spawn_s2, daemon=True)
            t.start()
            self._pre_warm_threads.append(t)
            spawned = True

        if spawned:
            print(f"⏱ [PRE-WARM] 오디오 subprocess {len(self._pre_warm_threads)}개 pre-warm 시작 "
                  f"(OFFHOOK 시 trigger_audio_playback 호출 필요)")
        return spawned

    def trigger_audio_playback(self, play_at: float) -> None:
        """Pre-warm된 워커에게 재생 시작 신호를 전송합니다.

        play_at_file에 타임스탬프를 기록하면 워커가 10ms 이내에 감지하여
        해당 시각에 맞춰 재생을 시작합니다.

        Args:
            play_at: 재생 시작 Unix timestamp (보통 time.time() + 0.2)
        """
        files = getattr(self, '_play_at_files', {})
        if not files:
            print(f"⚠️ [TRIGGER] pre-warm된 워커 없음 — play_audio_after_delay 사용 필요")
            return

        _now = time.time()
        _margin_ms = (play_at - _now) * 1000
        print(f"\n{'='*60}")
        print(f"🔊 오디오 재생 트리거 (play_at까지 {_margin_ms:.0f}ms)")
        print(f"{'='*60}\n")

        self._play_at = play_at  # type: ignore[attr-defined]

        for sid, path in files.items():
            with open(path, 'w') as f:
                f.write(f'{play_at:.6f}')

        print(f"⏱ [TRIGGER] play_at={play_at:.6f} 신호 전송 완료 → 워커 재생 대기 중")

        # 워커 스레드 완료 대기 (실제 재생 + join)
        for t in getattr(self, '_pre_warm_threads', []):
            t.join()

    def _play_audio_via_adb(self, udid: str, local_wav: str, speaker_id: str = 'speaker2') -> None:
        """wav 파일을 ADB로 Android 기기에 push 후 재생합니다."""
        remote_path = f'/sdcard/Music/ixio_test_{speaker_id}.wav'
        local_path  = Path(local_wav).resolve()

        print(f"📤 [{speaker_id}] ADB push: {local_path.name} → {remote_path}")
        try:
            push = subprocess.run(
                ['adb', '-s', udid, 'push', str(local_path), remote_path],
                capture_output=True, text=True, timeout=60
            )
            if push.returncode != 0:
                print(f"⚠️ [{speaker_id}] ADB push 실패: {push.stderr.strip()}")
                return
        except subprocess.TimeoutExpired:
            print(f"⚠️ [{speaker_id}] ADB push 시간 초과"); return
        except Exception as e:
            print(f"⚠️ [{speaker_id}] ADB push 오류: {e}"); return

        # 미디어 스캔
        try:
            subprocess.run(
                ['adb', '-s', udid, 'shell', 'am', 'broadcast',
                 '-a', 'android.intent.action.MEDIA_SCANNER_SCAN_FILE',
                 '-d', f'file://{remote_path}'],
                capture_output=True, text=True, timeout=10
            )
        except Exception:
            pass

        # Intent 재생
        print(f"▶️  [{speaker_id}] ADB 재생 시작: {remote_path}")
        try:
            play = subprocess.run(
                ['adb', '-s', udid, 'shell', 'am', 'start',
                 '-a', 'android.intent.action.VIEW',
                 '-d', f'file://{remote_path}',
                 '-t', 'audio/x-wav',
                 '--activity-clear-top'],
                capture_output=True, text=True, timeout=10
            )
            if play.returncode == 0:
                print(f"✅ [{speaker_id}] Android ADB 재생 시작\n")
            else:
                subprocess.run(
                    ['adb', '-s', udid, 'shell', 'media', 'play', '--uri', f'file://{remote_path}'],
                    capture_output=True, text=True, timeout=10
                )
                print(f"  ↩️ [{speaker_id}] media play fallback 실행\n")
        except Exception as e:
            print(f"⚠️ [{speaker_id}] ADB 재생 실패: {e}\n")

    def _stop_audio_procs(self) -> None:
        """실행 중인 audio_player_worker subprocess를 모두 강제 종료합니다."""
        for proc in self._audio_procs:  # type: ignore[attr-defined]
            try:
                if proc.poll() is None:
                    proc.kill()  # SIGKILL 직접 전송 (terminate+wait 불필요)
            except Exception:
                pass
        self._audio_procs.clear()  # type: ignore[attr-defined]
        # pkill 폴백: 스레드 경쟁으로 _audio_procs 에 아직 추가되지 못한 worker 까지 정리
        try:
            import subprocess as _sp
            _sp.run(['pkill', '-9', '-f', 'audio_player_worker.py'],
                    capture_output=True, timeout=2)
            _sp.run(['pkill', '-9', '-f', 'afplay'],
                    capture_output=True, timeout=2)
        except Exception:
            pass
        print("⏹️ 오디오 재생 subprocess 강제 종료 완료\n")

    def wait_for_audio_completion(self) -> bool:
        """오디오 재생 완료 대기 (통화 강제 종료 감지 포함)."""
        import re as _re

        duration = 60.0
        try:
            audio_file = self.audio_files.get('speaker1')  # type: ignore[attr-defined]
            if audio_file and Path(audio_file).exists():
                with wave.open(audio_file, 'rb') as wav:
                    duration = wav.getnframes() / float(wav.getframerate())
        except Exception as e:
            print(f"⚠️ 오디오 길이 확인 실패: {e}, 기본 {duration:.0f}초 사용\n")

        print(f"⏰ 오디오 재생 시간: {duration:.1f}초")
        print(f"   재생 완료 대기 중 (통화 상태 감시)...\n")

        total_wait       = duration + 2
        POLL_INTERVAL    = 1.0
        start            = time.time()
        call_miss_count  = 0
        CALL_MISS_THRESHOLD = 4

        while time.time() - start < total_wait:
            time.sleep(POLL_INTERVAL)

            if self.speaker2_platform == 'Android' and self.speaker2_device:  # type: ignore[attr-defined]
                udid = self.speaker2_device  # type: ignore[attr-defined]
                reg_active = False
                adb_reachable = True
                try:
                    reg_result = subprocess.run(
                        ['adb', '-s', udid, 'shell', 'dumpsys', 'telephony.registry'],
                        capture_output=True, text=True, timeout=3
                    )
                    # device not found / offline → ADB 연결 자체 실패
                    if reg_result.returncode != 0 and ('not found' in reg_result.stderr or 'offline' in reg_result.stderr):
                        adb_reachable = False
                    else:
                        reg_active = 'mCallState=2' in reg_result.stdout
                except Exception:
                    adb_reachable = False

                telecom_active = False
                if adb_reachable and not reg_active:
                    try:
                        tel_out = subprocess.run(
                            ['adb', '-s', udid, 'shell', 'dumpsys', 'telecom'],
                            capture_output=True, text=True, timeout=3
                        ).stdout
                        telecom_active = bool(_re.search(
                            r'(?:mState|state):\s*(?:ACTIVE|DIALING)', tel_out
                        ))
                    except Exception:
                        pass

                # ixio 는 VoIP — telephony/telecom 미감지 보완:
                # Audio Mode IN_CALL / IN_COMMUNICATION 으로 추가 확인
                audio_active = False
                if adb_reachable and not reg_active and not telecom_active:
                    try:
                        audio_out = subprocess.run(
                            ['adb', '-s', udid, 'shell', 'dumpsys', 'audio'],
                            capture_output=True, text=True, timeout=3
                        ).stdout
                        audio_active = bool(_re.search(
                            r'(?:IN_CALL|IN_COMMUNICATION|mMode=3\b)', audio_out
                        ))
                    except Exception:
                        pass

                # ADB 연결 자체가 끊긴 경우 → 통화 종료가 아닌 연결 불안정
                # → miss 카운트를 올리지 않고 통화 중으로 간주
                if not adb_reachable:
                    call_miss_count = 0
                elif not reg_active and not telecom_active and not audio_active:
                    call_miss_count += 1
                    if call_miss_count >= CALL_MISS_THRESHOLD:
                        print(f"\n⚠️ [통화 강제 종료 감지] telephony+telecom+audio {call_miss_count}회 연속 미감지 → 오디오 중단 후 조기 종료\n")
                        self._stop_audio_procs()
                        return False
                else:
                    call_miss_count = 0

            elif self.speaker2_platform == 'iOS':  # type: ignore[attr-defined]
                ios_call_visible = False
                driver = self.drivers.get('speaker2')  # type: ignore[attr-defined]
                if driver:
                    try:
                        src = driver.page_source
                        ios_call_visible = any(kw in src for kw in ('끊기', '통화', '음소거', '스피커', 'End', 'Mute'))
                    except Exception:
                        # WDA 통신 실패 시 통화 중으로 간주 (오탐 방지)
                        ios_call_visible = True

                # iOS page_source 미감지 시 speaker1(Android) 교차 확인
                android_cross_active = False
                if not ios_call_visible and getattr(self, 'speaker1_platform', None) == 'Android':
                    s1_udid = getattr(self, 'speaker1_device', None)
                    if s1_udid:
                        try:
                            audio_out = subprocess.run(
                                ['adb', '-s', s1_udid, 'shell', 'dumpsys', 'audio'],
                                capture_output=True, text=True, timeout=3
                            ).stdout
                            android_cross_active = bool(_re.search(
                                r'(?:IN_CALL|IN_COMMUNICATION|mMode=3\b)', audio_out
                            ))
                        except Exception:
                            pass
                        if not android_cross_active:
                            try:
                                reg_out = subprocess.run(
                                    ['adb', '-s', s1_udid, 'shell', 'dumpsys', 'telephony.registry'],
                                    capture_output=True, text=True, timeout=3
                                ).stdout
                                android_cross_active = 'mCallState=2' in reg_out
                            except Exception:
                                pass

                if ios_call_visible or android_cross_active:
                    call_miss_count = 0
                else:
                    call_miss_count += 1
                    if call_miss_count >= CALL_MISS_THRESHOLD:
                        print(f"\n⚠️ [통화 강제 종료 감지] iOS 통화화면+Android 교차확인 {call_miss_count}회 연속 없음 → 오디오 중단 후 조기 종료\n")
                        self._stop_audio_procs()
                        return False

        print(f"✅ 오디오 재생 완료\n")
        return True
