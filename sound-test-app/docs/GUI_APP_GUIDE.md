# 익시오 통화 테스트 GUI 앱 사용 가이드

## 실행 방법

### 1. 개발 모드로 실행

```bash
cd sound-test-app
npm install  # 처음 한 번만
npm run tauri dev
```

### 2. 빌드 (DMG 파일 생성)

```bash
cd sound-test-app
npm run tauri build
```

빌드 완료 후:
- DMG 파일 위치: `sound-test-app/src-tauri/target/release/bundle/dmg/`
- 생성된 DMG 파일을 설치하여 사용

---

## 앱 사용 방법

### 1단계: 디바이스 연결

#### Android 무선 연결
1. Android 디바이스에서 무선 디버깅 활성화
   - 설정 > 개발자 옵션 > 무선 디버깅
   - IP 주소와 포트 확인 (예: 192.168.0.10:5555)

2. 앱에서 IP:PORT 입력
3. "🔌 Android 자동 연결" 버튼 클릭

#### iPhone 무선 연결 확인
1. Xcode에서 무선 디버깅 미리 설정
   - Window > Devices and Simulators
   - 디바이스 선택 > "Connect via network" 체크

2. 앱에서 "📱 iPhone 연결 확인" 버튼 클릭

---

### 2단계: 화자 설정

#### 화자 1 (발신자)
- 디바이스 선택 (드롭다운에서)
- 전화번호 입력 (국가코드 포함)

#### 화자 2 (수신자)
- 디바이스 선택
- 전화번호 입력

---

### 3단계: 오디오 파일 설정

스테레오 WAV 파일을 준비하세요:
- **L 채널**: 화자1 음성
- **R 채널**: 화자2 음성
- 파일을 프로젝트 루트에 배치
- 파일명을 입력창에 입력

예시: `test_audio_stereo.wav`

---

### 4단계: 테스트 실행

"▶️ 테스트 시작" 버튼 클릭

**자동 실행 프로세스:**
1. Appium 서버 자동 시작 (백그라운드)
2. 익시오 앱 자동 실행
3. 키패드 열기
4. 화자2에게 전화 발신
5. "통화 종료" 버튼 감지 (익시오 전화 연결 중...)
6. 3초 대기
7. 스테레오 오디오 자동 재생
   - 화자1: L 채널
   - 화자2: R 채널
8. 오디오 재생 완료 후 자동 통화 종료

---

## 필수 요구사항

### macOS 환경
```bash
# Node.js 설치
brew install node

# Rust 설치 (Tauri용)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Appium 설치
npm install -g appium
appium driver install uiautomator2
appium driver install xcuitest

# ADB 설치
brew install android-platform-tools

# iOS 도구 (선택)
brew install libimobiledevice
```

### Python 환경
```bash
# 가상환경이 이미 설정되어 있음
cd /Users/qabulls/Documents/sound
source venv/bin/activate
```

---

## 문제 해결

### "Android 연결 실패"
```bash
# ADB 확인
adb devices

# ADB 재시작
adb kill-server
adb start-server
```

### "Appium 시작 실패"
```bash
# Appium 설치 확인
appium --version

# 재설치
npm uninstall -g appium
npm install -g appium
```

### "Python 스크립트 실패"
```bash
# Python 경로 확인
which python3

# 가상환경 활성화 확인
source /Users/qabulls/Documents/sound/venv/bin/activate
```

### "디바이스를 찾을 수 없음"
- Android: 무선 디버깅이 활성화되어 있는지 확인
- iPhone: Xcode에서 디바이스가 보이는지 확인

---

## 개발자 콘솔 보기

문제 디버깅을 위해 개발자 콘솔 확인:

1. 개발 모드에서 실행: `npm run tauri dev`
2. 앱 내에서 오른쪽 클릭 > "Inspect Element"
3. Console 탭에서 로그 확인

또는 터미널에서 Python 스크립트 직접 실행:
```bash
cd /Users/qabulls/Documents/sound
source venv/bin/activate
python ixio_automated_test.py \
  --speaker1-device "ABC123" \
  --speaker2-device "DEF456" \
  --speaker1-number "+821012345678" \
  --speaker2-number "+821087654321" \
  --audio-file "test_audio_stereo.wav"
```

---

## 앱 구조

```
sound-test-app/
├── src/                    # React 프론트엔드
│   ├── App.tsx            # 메인 UI
│   └── App.css            # 스타일
├── src-tauri/             # Rust 백엔드
│   └── src/
│       └── lib.rs         # Tauri 명령어
└── package.json           # Node.js 설정
```

---

## 향후 개선사항

- [ ] 실시간 로그 스트리밍
- [ ] 테스트 진행률 표시
- [ ] 오디오 파일 브라우저 선택
- [ ] 설정 저장/불러오기
- [ ] 여러 테스트 시나리오 지원

---

**Happy Testing! 🎉**
