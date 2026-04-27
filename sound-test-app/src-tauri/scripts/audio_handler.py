import os
import wave
import numpy as np
from pathlib import Path
import subprocess
import threading
import http.server
import socketserver
import socket

# ──────────────────────────────────────────────────────────────────────────────
# 공통 USB 감지 모듈 (DRY 제거 — core_audio_utils.py 와 중복 제거)
# ──────────────────────────────────────────────────────────────────────────────
from usb_audio_devices import (
    get_usb_audio_output_indices,
    get_usb_location_ids as _get_usb_location_ids,
    resolve_usb_device_index,
    list_usb_status,
)


def resolve_audio_device_index(role: str):
    """config.AUDIO_DEVICES[role] 설정을 읽어 USB 출력 장치 index를 반환.

    내부적으로 usb_audio_devices.resolve_usb_device_index() 에 위임합니다.
    하위 호환성을 위해 유지.
    """
    try:
        from config import AUDIO_DEVICES
        cfg = AUDIO_DEVICES.get(role, {})
    except ImportError:
        return None

    return resolve_usb_device_index(
        location_id=cfg.get('location_id'),
        usb_port_order=cfg.get('usb_port_order', 1),
        device_index_fallback=cfg.get('device_index'),
        role_label=role,
    )


def list_usb_audio_devices():
    """연결된 USB Audio 장치 목록과 현재 index, locationID를 출력 (디버그용).

    내부적으로 usb_audio_devices.list_usb_status() 에 위임합니다.
    """
    return list_usb_status(verbose=True)


class AudioFileHttpServer:
    """오디오 파일을 iOS 기기에 제공하기 위한 HTTP 서버.

    AudioHandler에서 분리 — HTTP 서버 관리(네트워크 I/O)는
    오디오 파일 처리(WAV 분리/저장)와 별개의 책임입니다.
    """

    def __init__(self, port: int = 8800):
        self.port = port
        self._server = None
        self._thread = None
        self._serving_dir: 'str | None' = None

    @staticmethod
    def get_local_ip() -> str:
        """현재 활성 네트워크 인터페이스의 Mac IP 주소를 반환합니다."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def start(self, directory=None):
        """정적 파일 HTTP 서버를 시작합니다."""
        if self._server:
            print("⚠️ HTTP 서버가 이미 실행 중입니다.")
            return
        if directory is None:
            directory = os.getcwd()
        self._serving_dir = str(directory)
        os.chdir(directory)

        class _QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 로그 억제

        try:
            self._server = socketserver.TCPServer(("", self.port), _QuietHandler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            print(f"✅ HTTP 서버 시작됨: http://{self.get_local_ip()}:{self.port}")
            print(f"   제공 디렉토리: {directory}")
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"⚠️ 포트 {self.port}이(가) 이미 사용 중입니다.")
            else:
                print(f"❌ HTTP 서버 시작 실패: {e}")

    def stop(self):
        """HTTP 서버를 중지합니다."""
        if self._server:
            self._server.shutdown()
            self._server = None
            print("🛑 HTTP 서버 중지됨")


class AudioHandler:
    """스테레오 WAV 파일 분리 및 디바이스 파일 전송 담당.

    HTTP 서버 기능은 AudioFileHttpServer 에 위임합니다.
    start_http_server / stop_http_server / get_local_ip 는
    하위 호환성을 위해 위임 메서드로 유지됩니다.
    """

    def __init__(self, audio_dir='audio_files'):
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(exist_ok=True)
        self._http = AudioFileHttpServer(port=8800)

    @property
    def http_port(self) -> int:
        return self._http.port
        
    def split_stereo_wav(self, stereo_file):
        """
        스테레오 WAV 파일을 L/R 채널로 분리
        
        Args:
            stereo_file: 스테레오 WAV 파일 경로
            
        Returns:
            (left_file, right_file): 분리된 파일 경로 튜플
        """
        print(f"🎵 스테레오 파일 분리 중: {stereo_file}")
        
        # WAV 파일 읽기
        with wave.open(stereo_file, 'rb') as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            framerate = wav.getframerate()
            n_frames = wav.getnframes()
            
            if channels != 2:
                raise ValueError("스테레오 파일이 아닙니다!")
            
            # 오디오 데이터 읽기
            audio_data = wav.readframes(n_frames)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # 스테레오를 L/R로 분리
            left_channel = audio_array[0::2]  # 짝수 인덱스
            right_channel = audio_array[1::2]  # 홀수 인덱스
        
        # 분리된 파일 저장
        base_name = Path(stereo_file).stem
        left_file = self.audio_dir / f"{base_name}_LEFT.wav"
        right_file = self.audio_dir / f"{base_name}_RIGHT.wav"
        
        # Left 채널 저장
        with wave.open(str(left_file), 'wb') as left_wav:
            left_wav.setnchannels(1)  # 모노
            left_wav.setsampwidth(sample_width)
            left_wav.setframerate(framerate)
            left_wav.writeframes(left_channel.tobytes())
        
        # Right 채널 저장
        with wave.open(str(right_file), 'wb') as right_wav:
            right_wav.setnchannels(1)
            right_wav.setsampwidth(sample_width)
            right_wav.setframerate(framerate)
            right_wav.writeframes(right_channel.tobytes())
        
        print(f"✅ L 채널: {left_file}")
        print(f"✅ R 채널: {right_file}")
        
        return str(left_file), str(right_file)
    
    def prepare_audio_for_devices(self, stereo_file, device_a_name, device_b_name):
        """
        디바이스별 오디오 파일 준비
        
        Args:
            stereo_file: 스테레오 WAV 파일
            device_a_name: 디바이스 A 이름 (L 채널)
            device_b_name: 디바이스 B 이름 (R 채널)
            
        Returns:
            dict: {device_name: audio_file_path}
        """
        left_file, right_file = self.split_stereo_wav(stereo_file)
        
        return {
            device_a_name: left_file,
            device_b_name: right_file
        }
    
    def push_audio_to_android(self, audio_file, device_udid):
        """Android 디바이스에 오디오 파일 전송"""
        print(f"📲 {device_udid}에 오디오 전송 중...")
        
        # 디바이스 내부 저장소로 전송
        remote_path = "/sdcard/Download/test_audio.wav"
        result = subprocess.run(
            ['adb', '-s', device_udid, 'push', audio_file, remote_path],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"✅ 전송 완료: {remote_path}")
            return remote_path
        else:
            print(f"❌ 전송 실패")
            return None
    
    def push_audio_to_ios(self, audio_file, device_udid):
        """iOS 디바이스에 오디오 파일 전송 (idevice 사용)"""
        print(f"📲 {device_udid}에 오디오 전송 중...")
        
        # libimobiledevice 사용 (설치 필요: brew install libimobiledevice)
        # 또는 Xcode를 통한 파일 전송
        
        try:
            import subprocess
            
            # Documents 폴더로 전송
            remote_path = "Documents/test_audio.wav"
            cmd = [
                "ifuse",  # 또는 idevice 관련 도구
                "--udid", device_udid,
                "push", audio_file, remote_path
            ]
            
            # 실제로는 사전에 앱을 통해 파일을 전송해야 함
            print(f"⚠️ iOS는 사전에 파일을 iTunes/Finder로 전송하거나")
            print(f"   테스트 앱 번들에 포함시켜야 합니다.")
            
            return f"/var/mobile/Containers/Data/Application/.../Documents/test_audio.wav"
            
        except Exception as e:
            print(f"❌ iOS 전송 실패: {e}")
            return None
    
    # ── HTTP 서버 위임 메서드 (하위 호환성 유지) ────────────────────────────

    def get_local_ip(self) -> str:
        """Mac 로컬 IP 반환 — AudioFileHttpServer.get_local_ip()에 위임."""
        return self._http.get_local_ip()

    def start_http_server(self, directory=None):
        """HTTP 서버 시작 — AudioFileHttpServer.start()에 위임."""
        return self._http.start(directory)

    def stop_http_server(self):
        """HTTP 서버 중지 — AudioFileHttpServer.stop()에 위임."""
        return self._http.stop()


class DeviceAudioPlayer:
    """디바이스에서 오디오 재생"""
    
    @staticmethod
    def play_audio_android(driver, audio_file_path):
        """Android에서 오디오 재생"""
        try:
            print(f"🔊 Android 오디오 재생: {audio_file_path}")
            
            # ADB shell command로 재생
            udid = driver.capabilities.get('udid')

            # MediaPlayer 사용
            subprocess.run(
                ['adb', '-s', udid, 'shell', 'am', 'start',
                 '-a', 'android.intent.action.VIEW',
                 '-d', f'file://{audio_file_path}',
                 '-t', 'audio/wav'],
                capture_output=True, text=True
            )
            print("✅ Android 재생 시작")
            return True
            
        except Exception as e:
            print(f"❌ Android 재생 실패: {e}")
            return False
    
    @staticmethod
    def play_audio_ios(driver, audio_url):
        """iOS에서 오디오 재생 (HTTP URL 사용)"""
        try:
            print(f"🔊 iOS 오디오 재생: {audio_url}")
            
            # Safari로 오디오 URL 열기
            # Mobile Safari에서 오디오 파일을 열면 자동 재생됨
            driver.get(audio_url)
            
            print("✅ iOS 오디오 URL 열기 완료 (Safari에서 재생)")
            return True
            
        except Exception as e:
            print(f"❌ iOS 재생 실패: {e}")
            print(f"💡 대안: Mac 스피커로 직접 재생")
            return False
    
    @staticmethod
    def list_output_devices():
        """USB 오디오 출력 장치 목록만 반환 (맥북 내장 스피커 / Background Music 제외).

        sounddevice 인덱스는 macOS 재열거 시 변경될 수 있으므로
        매번 ioreg 기반 USB 제품명 집합으로 필터링합니다.
        """
        try:
            import sounddevice as sd
            from usb_audio_devices import get_usb_audio_product_names
            usb_names = get_usb_audio_product_names()
            devices = sd.query_devices()
            out = []
            for i, d in enumerate(devices):
                if d['max_output_channels'] > 0 and (
                    d['name'] in usb_names or 'USB Audio' in d['name']
                ):
                    out.append({
                        'id': i,
                        'name': d['name'],
                        'channels': d['max_output_channels'],
                    })
            return out
        except Exception as e:
            print(f"⚠️ 오디오 장치 목록 조회 실패: {e}")
            return []

    @staticmethod
    def play_audio_to_device(audio_file, device=None, channel=None, speaker_id=None, monitor=False, usb_order=None, volume=0.95, output_pair=None, play_at=None, play_at_file=None):
        """지정된 오디오 출력 장치로 재생 (audio_player_worker.py subprocess 사용, 비차단).

        macOS CoreAudio AUHAL 제약(동일 프로세스 내 두 USB 스트림 동시 불가)을
        회피하기 위해 audio_player_worker.py 를 독립 subprocess로 생성합니다.

        Args:
            audio_file: 재생할 오디오 파일 경로
            device: 장치 ID(int) 또는 이름 일부(str), None이면 시스템 기본 장치
            channel: None(양쪽), 'L'(왼쪽만), 'R'(오른쪽만)
            speaker_id: 'speaker1' 또는 'speaker2' — 진행률 stdout 출력용
            monitor: True 시 맥북 스피커로도 동시 미러링 재생
            usb_order: USB 오디오 장치 순서(1, 2, ...) — 인덱스 변경 시 자동 복구에 사용
            volume: 출력 볼륨 0.0~1.0 (기본 0.95). iRig 과입력 방지 시 낮추세요.
            output_pair: CONNECT 6 출력 채널 쌍 문자열(예: "2,3"). None이면 기본(Out 1/2).
        """
        import sys

        _WORKER = Path(__file__).parent / 'audio_player_worker.py'

        # 이미 venv 내에서 실행 중이면 sys.executable 그대로 사용.
        # 하드코딩 절대경로 금지 — 환경마다 venv 위치가 다를 수 있음.
        python_exe = sys.executable
        if 'venv' not in python_exe and '.venv' not in python_exe:
            # app support venv 폴백 (배포 설치 환경)
            app_venv = os.path.join(
                os.path.expanduser('~'),
                'Library/Application Support/com.qabulls.call/venv/bin/python',
            )
            if os.path.exists(app_venv):
                python_exe = app_venv

        cmd = [python_exe, str(_WORKER), '--file', audio_file]
        if device is not None:
            cmd += ['--device', str(device)]
        if channel in ('L', 'R'):
            cmd += ['--channel', channel]
        if speaker_id:
            cmd += ['--speaker-id', speaker_id]
        if usb_order is not None:
            cmd += ['--usb-order', str(usb_order)]
        if volume != 0.95:
            cmd += ['--volume', str(volume)]
        if monitor:
            cmd += ['--monitor']
        if output_pair:
            cmd += ['--output-pair', str(output_pair)]
        if play_at is not None:
            cmd += ['--play-at', f'{play_at:.6f}']
        if play_at_file is not None:
            cmd += ['--play-at-file', play_at_file]

        device_label = device if device is not None else '기본 장치'
        ch_label = f"{'Left' if channel == 'L' else 'Right'} 채널" if channel in ('L', 'R') else '양쪽 채널'
        op_label = f"Out {output_pair}" if output_pair else "기본(Out 1/2)"
        print(f"🎵 [{speaker_id}] 오디오 재생 요청 → device={device_label}  채널={ch_label}  출력쌍={op_label}  volume={volume:.2f}  usb_order={usb_order}", flush=True)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=None,   # 부모 stdout 상속 (진행률+장치명 출력 전달)
                stderr=None,   # 부모 stderr 상속
            )
            print(f"   subprocess PID={proc.pid} 시작됨", flush=True)
            return proc
        except Exception as e:
            print(f"⚠️ subprocess 재생 실패: {e}  →  afplay 폴백 사용", flush=True)
            fallback = subprocess.Popen(['afplay', audio_file],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            print(f"   afplay PID={fallback.pid} 시작됨", flush=True)
            return fallback

    @staticmethod
    def play_audio_on_mac(audio_file, device=None, channel=None, speaker_id=None):
        """Mac 오디오 출력 장치로 재생 (기본값: 시스템 기본 장치)"""
        return DeviceAudioPlayer.play_audio_to_device(audio_file, device=device, channel=channel, speaker_id=speaker_id)
    
    @staticmethod
    def play_audio_via_shortcuts(driver, audio_filename):
        """iOS Shortcuts로 오디오 재생 (Line-In 대체 방식)"""
        try:
            print(f"🔊 iOS Shortcuts로 재생: {audio_filename}")
            
            # URL Scheme으로 Shortcuts 트리거
            # 사전에 iPhone에 "Play Audio" 단축어 생성 필요
            shortcut_name = "Play Audio"
            shortcut_url = f"shortcuts://run-shortcut?name={shortcut_name.replace(' ', '%20')}"
            
            print(f"  → Shortcuts URL: {shortcut_url}")
            driver.get(shortcut_url)
            
            print("✅ Shortcuts 트리거 완료")
            return True
            
        except Exception as e:
            print(f"❌ Shortcuts 실행 실패: {e}")
            print(f"💡 대체 방법: Mac 스피커로 재생합니다.")
            return False
    
    @staticmethod
    def stop_audio_android(driver):
        """Android 오디오 정지"""
        try:
            udid = driver.capabilities.get('udid')
            # 미디어 정지
            subprocess.run(
                ['adb', '-s', udid, 'shell', 'input', 'keyevent', '86'],
                capture_output=True, text=True
            )  # KEYCODE_MEDIA_STOP
            print("⏹️ Android 재생 정지")
        except Exception as e:
            print(f"⚠️ 정지 실패: {e}")
    
    @staticmethod
    def stop_audio_ios(driver):
        """iOS 오디오 정지"""
        try:
            driver.execute_script("audio.pause();")
            print("⏹️ iOS 재생 정지")
        except Exception as e:
            print(f"⚠️ 정지 실패: {e}")
