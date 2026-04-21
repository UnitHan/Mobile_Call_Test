# 익시오 통화 자동화 테스트

Tauri(Rust) + React/TypeScript GUI + Python Appium 자동화로 구성된 **화자 간 통화 품질 테스트 도구**.

두 단말(화자1·화자2)에서 익시오 앱(`com.lguplus.aicallagent`)으로 통화를 연결하고,  
USB 외장 사운드카드를 통해 각 단말에 지정 음원을 재생해 통화 음질을 자동으로 검증합니다.

---

## 시스템 구성

```
┌─────────────────────────────────────────────────────────┐
│                  Mac (테스트 호스트)                     │
│                                                         │
│  ┌─────────────────────┐   ┌─────────────────────────┐ │
│  │  Tauri GUI 앱       │   │  Python 자동화 스크립트  │ │
│  │  (React + Rust)     │──▶│  ixio_automated_test.py │ │
│  └─────────────────────┘   └───────────┬─────────────┘ │
│                                        │               │
│  ┌─────────────────────┐   ┌───────────▼─────────────┐ │
│  │ USB 사운드카드 [0]   │   │  Appium 서버 x2         │ │
│  │ (화자1용 음원 출력)  │   │  Android :4723          │ │
│  ├─────────────────────┤   │  iOS     :4724          │ │
│  │ USB 사운드카드 [2]   │   └─────────────────────────┘ │
│  │ (화자2용 음원 출력)  │                               │
│  └─────────────────────┘                               │
└──────────┬──────────────────────────┬──────────────────┘
           │ 케이블                   │ Wi-Fi
    ┌──────▼──────┐           ┌──────▼──────┐
    │  화자1 단말  │           │  화자2 단말  │
    │  (발신자)   │ ─통화─▶   │  (수신자)   │
    │  iPhone/AOS │           │  AOS/iPhone │
    └─────────────┘           └─────────────┘
```

---

## 디렉터리 구조

```
sound/
├── sound-test-app/              ← Tauri GUI 앱 (메인)
│   ├── src/                     ← React + TypeScript 프론트엔드
│   │   ├── components/          ← 화면 컴포넌트
│   │   │   ├── DeviceSection.tsx     단말 선택
│   │   │   ├── AudioSection.tsx      오디오 설정
│   │   │   ├── SpeakerSection.tsx    화자 설정
│   │   │   └── LogPanel.tsx          로그 출력
│   │   └── hooks/               ← 상태 관리 훅
│   └── src-tauri/
│       ├── src/                 ← Rust 백엔드 커맨드
│       └── scripts/             ← Python 자동화 스크립트
│           ├── ixio_automated_test.py   ← 메인 테스트 오케스트레이터
│           ├── ios_call_handler.py      ← iPhone 통화 제어 (WDA)
│           ├── android_call_handler.py  ← Android 통화 제어 (ADB)
│           ├── answer_strategies.py     ← 수신 전략
│           ├── audio_player_worker.py   ← 오디오 재생 워커
│           ├── audio_handler.py         ← 오디오 장치 해결
│           ├── device_detector.py       ← 단말 자동 감지
│           ├── ios_wda_manager.py       ← WDA 세션 관리
│           ├── core_audio_utils.py      ← macOS 오디오 유틸 (SwitchAudioSource)
│           ├── usb_audio_devices.py     ← USB 사운드카드 탐색
│           ├── config.py                ← 전역 설정
│           └── requirements.txt
├── audio_files/                 ← 테스트용 WAV 파일
└── README.md                    ← 이 파일
```

---

## 환경 요구사항

| 항목 | 버전 | 비고 |
|------|------|------|
| macOS | 13+ | Tauri 필수 |
| Python | 3.10+ | |
| Rust / Cargo | 최신 stable | `rustup` |
| Node.js | 18+ | |
| Appium | 2.x | `npm install -g appium` |
| appium-uiautomator2-driver | 최신 | Android 자동화 |
| appium-xcuitest-driver | 최신 | iOS 자동화 |
| ADB | SDK Platform-Tools | Android 연결 |
| pymobiledevice3 | 최신 | iOS 무선 터널 |
| SwitchAudioSource | - | `brew install switchaudio-osx` |
| USB 외장 사운드카드 | 2개 | 각 화자 음원 출력용 |

---

## 설치

```bash
# 1. Python 의존성
cd sound-test-app/src-tauri/scripts
pip install -r requirements.txt

# 2. Appium 드라이버
appium driver install uiautomator2
appium driver install xcuitest

# 3. Tauri 앱 빌드 (개발 서버)
cd sound-test-app
npm install
npm run tauri dev
```

---

## 설정 (`config.py`)

```python
# ─ 1. 오디오 장치 (USB 사운드카드 locationID 확인)
# ioreg -r -c IOUSBInterface -l | grep -A5 "USB Audio" | grep locationID
AUDIO_DEVICES = {
    'android_a': {
        'location_id': 34734080,   # 화자1 엔드포인트 사운드카드
        'usb_port_order': 1,
    },
    'ios_b': {
        'location_id': 34799616,   # 화자2 엔드포인트 사운드카드
        'usb_port_order': 2,
    },
}

# ─ 2. iOS WDA IP (None = mDNS 자동 감지)
WDA_IP_OVERRIDE = None
WDA_PORT = 8100
```

> UDID, 전화번호, 음원 파일은 **GUI에서 직접 선택**합니다. config.py에 하드코딩하지 않아도 됩니다.

---

## 실행 흐름

```
[GUI 앱]
  │  단말 선택 (화자1 / 화자2)
  │  음원 파일 선택
  │  사운드카드 선택
  │  테스트 시작 버튼
  ▼
[Python: ixio_automated_test.py]
  1. UDID 자동 감지 (미선택 시)
  2. Appium 세션 연결 (Android: 4723 / iOS: 4724)
  3. 익시오 앱 키패드 이동
  4. 화자1 → 화자2 발신
  5. 화자2 자동 수신 (ADB or Appium UI)
  6. mCallState=2 고속 폴링(50ms) → 연결 확인
  7. 연결 확인 즉시 음원 재생
     ├── 화자1: USB 사운드카드 [android_a 슬롯]
     └── 화자2: USB 사운드카드 [ios_b 슬롯]
  8. 음원 재생 완료 → 통화 종료
```

---

## 단말 조합 지원

| 화자1 (발신) | 화자2 (수신) | 수신 방법 |
|-------------|-------------|----------|
| iPhone | Android | ADB keyevent |
| Android | iPhone | Appium UI |
| iPhone | iPhone | Appium UI (WDA) |
| Android | Android | ADB keyevent |

GUI 단말 선택 드롭다운에서 디바이스를 고르면 플랫폼이 자동 감지되어 동작합니다.

---

## USB 사운드카드 설정

macOS 재부팅 후 sounddevice 인덱스가 바뀌더라도 `locationID`로 올바른 장치를 자동 복구합니다.

```bash
# 현재 연결된 USB 오디오 장치 목록 확인
python usb_dual_audio_test.py --list

# locationID 확인 (물리 USB 포트 고정 식별자)
ioreg -r -c IOUSBInterface -l | grep -A5 "USB Audio" | grep locationID
```

---

## iOS 무선 연결 설정

```bash
# 최초 1회: USB 연결 상태에서 페어링
pymobiledevice3 pair

# 터널 데몬 시작 (백그라운드)
sudo pymobiledevice3 remote tunneld

# 이후 USB 없이 Wi-Fi만으로 자동 연결
```

---

## UDID 확인

```bash
# Android (Wi-Fi 연결)
adb connect 192.168.x.x:5555
adb devices

# iOS
xcrun devicectl list devices
# 또는 Xcode > Window > Devices and Simulators
```
