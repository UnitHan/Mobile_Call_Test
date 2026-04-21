"""
AudioAgent 동작 검증 테스트
- Mac HTTP 서버(8800) → iPhone AudioAgent 폴링 → ringtone 재생 흐름 전체 검증

실행: python3 _test_audio_agent.py
종료: Ctrl+C
"""
import http.server
import socketserver
import threading
import time
import os
import struct
import math
import socket
from pathlib import Path
from datetime import datetime

AGENT_DIR = Path('/tmp/audio_agent')
PORT      = 8800
IPHONE_IP = None  # 자동 감지

# ── 요청 로그 수집 ──────────────────────────────────────────
request_log: list[dict] = []
log_lock = threading.Lock()


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def make_ringtone(path: Path) -> None:
    """1초 440Hz 링톤 WAV 생성"""
    if path.exists():
        print(f"  ✅ ringtone 이미 존재: {path}")
        return
    sample_rate = 44100
    freq = 440
    n_samples = sample_rate
    fade_n = int(sample_rate * 0.02)
    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        val = math.sin(2 * math.pi * freq * t)
        if i < fade_n:
            val *= i / fade_n
        elif i > n_samples - fade_n:
            val *= (n_samples - i) / fade_n
        samples.append(int(val * 32767))
    data_size = n_samples * 2
    with open(path, 'wb') as f:
        f.write(b'RIFF')
        f.write(struct.pack('<I', 36 + data_size))
        f.write(b'WAVE')
        f.write(b'fmt ')
        f.write(struct.pack('<IHHIIHH', 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b'data')
        f.write(struct.pack('<I', data_size))
        for s in samples:
            f.write(struct.pack('<h', s))
    print(f"  ✅ ringtone 생성: {path} ({data_size//1024}KB)")


class LoggingHandler(http.server.SimpleHTTPRequestHandler):
    """요청을 콘솔에 출력하고 log 리스트에 기록"""

    def log_message(self, format, *args):
        # 기본 로그 억제 (직접 처리)
        pass

    def do_GET(self):
        ts   = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        path = self.path
        client_ip = self.client_address[0]

        # 요청 기록
        entry = {'time': ts, 'ip': client_ip, 'path': path}
        with log_lock:
            request_log.append(entry)

        # 콘솔 출력
        icon = '📱' if client_ip != get_local_ip() else '💻'
        print(f"  {icon} [{ts}] {client_ip}  GET {path}")

        # command.txt 요청 시 현재 내용 보여주기
        if path == '/command.txt':
            cmd_path = AGENT_DIR / 'command.txt'
            content = cmd_path.read_text(encoding='utf-8').strip() if cmd_path.exists() else ''
            if content:
                print(f"       → 응답: '{content}'")
            else:
                print(f"       → 응답: (빈 파일)")

        super().do_GET()

    def do_HEAD(self):
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        entry = {'time': ts, 'ip': self.client_address[0], 'path': 'HEAD ' + self.path}
        with log_lock:
            request_log.append(entry)
        super().do_HEAD()


def start_server() -> socketserver.TCPServer:
    os.chdir(AGENT_DIR)
    # allow_reuse_address로 이전 서버 잔류 포트 재사용
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("", PORT), LoggingHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def print_summary():
    with log_lock:
        logs = list(request_log)

    if not logs:
        print("\n  ❌ 요청 없음 — iPhone이 Mac에 HTTP 요청을 보내지 않았습니다")
        print("     체크: AudioAgent 앱이 iPhone에서 실행 중인가?")
        print(f"     체크: AudioAgent IP 설정이 {get_local_ip()} 인가?")
        return

    mac_ip = get_local_ip()
    iphone_reqs = [r for r in logs if r['ip'] != mac_ip]
    cmd_reqs    = [r for r in iphone_reqs if '/command.txt' in r['path']]
    tone_reqs   = [r for r in iphone_reqs if 'ringtone' in r['path']]

    print(f"\n{'='*55}")
    print(f"📊 요청 요약")
    print(f"  총 요청:               {len(logs)}건")
    print(f"  iPhone → Mac 요청:     {len(iphone_reqs)}건")
    print(f"  command.txt 폴링:      {len(cmd_reqs)}건")
    print(f"  ringtone 다운로드:     {len(tone_reqs)}건")

    if cmd_reqs:
        print(f"\n  ✅ STEP1 OK — iPhone이 command.txt를 폴링하고 있습니다")
        ips = list({r['ip'] for r in cmd_reqs})
        print(f"     iPhone IP: {ips}")
    else:
        print(f"\n  ❌ STEP1 FAIL — command.txt 폴링 없음")
        print(f"     AudioAgent가 실행 중이지 않거나 IP가 다릅니다")

    if tone_reqs:
        print(f"  ✅ STEP2 OK — iPhone이 ringtone을 다운로드했습니다")
        for r in tone_reqs:
            print(f"     [{r['time']}] {r['path']}")
        print(f"\n  ✅ AudioAgent 정상 동작 확인!")
    else:
        if cmd_reqs:
            print(f"  ❌ STEP2 FAIL — command.txt는 폴링하지만 ringtone 다운로드 없음")
            print(f"     command.txt에 'play:...' 명령이 없었거나 파싱 오류")
        else:
            print(f"  ❌ STEP2 FAIL — ringtone 다운로드 없음")
    print(f"{'='*55}")


def main():
    mac_ip = get_local_ip()
    print(f"{'='*55}")
    print(f"🔬 AudioAgent 동작 검증 테스트")
    print(f"  Mac IP:     {mac_ip}")
    print(f"  서버 URL:   http://{mac_ip}:{PORT}/")
    print(f"  serve dir:  {AGENT_DIR}")
    print(f"{'='*55}\n")

    # 준비
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    ringtone = AGENT_DIR / 'ringtone_1s.wav'
    cmd_path = AGENT_DIR / 'command.txt'

    print("[STEP 0] 파일 준비")
    make_ringtone(ringtone)
    # command.txt 초기화
    cmd_path.write_text('', encoding='utf-8')
    print(f"  ✅ command.txt 초기화\n")

    # HTTP 서버 시작
    print(f"[STEP 1] HTTP 서버 시작 (포트 {PORT})")
    try:
        srv = start_server()
        print(f"  ✅ 서버 시작됨: http://{mac_ip}:{PORT}/\n")
    except OSError as e:
        print(f"  ❌ 서버 시작 실패: {e}")
        print(f"     이미 사용 중인 경우: lsof -ti:{PORT} | xargs kill -9")
        return

    # iPhone의 폴링 감지 대기
    print(f"[STEP 2] iPhone 폴링 감지 대기 (5초)")
    print(f"  → AudioAgent 앱이 iPhone에서 실행 중이어야 합니다")
    print(f"  → 폴링 요청이 들어오면 아래에 표시됩니다:\n")
    time.sleep(5)

    # command.txt에 재생 명령 기입
    print(f"\n[STEP 3] command.txt 에 재생 명령 기입")
    cmd_path.write_text('play:ringtone_1s.wav', encoding='utf-8')
    print(f"  ✅ 'play:ringtone_1s.wav' 기입 완료")
    print(f"  → AudioAgent가 폴링 후 ringtone_1s.wav를 다운로드해야 합니다\n")

    # ringtone 다운로드 대기
    print(f"[STEP 4] ringtone 다운로드 대기 (5초)\n")
    time.sleep(5)

    # command.txt 초기화
    cmd_path.write_text('', encoding='utf-8')
    print(f"\n[STEP 5] command.txt 초기화 완료")

    # 결과 요약
    print_summary()

    # 서버 유지 (추가 관찰)
    print(f"\n서버를 유지합니다. 추가 요청 관찰 중...")
    print(f"Ctrl+C로 종료\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n\n🛑 종료")
        print_summary()
        srv.shutdown()


if __name__ == '__main__':
    main()
