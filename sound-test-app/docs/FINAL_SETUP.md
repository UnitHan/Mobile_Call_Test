# 익시오 통화 테스트 앱 - 최종 설정 가이드

## ✅ 완료된 작업

### 1. Python 환경
- ✅ Python 3.10 가상환경 설정 완료
- ✅ 모든 의존성 설치 완료

### 2. GUI 앱 개발 완료
- ✅ Tauri + React 기반 앱
- ✅ Android ADB 무선 연결 기능
- ✅ iPhone 연결 확인 기능
- ✅ 화자 1, 화자 2 설정 UI
- ✅ 오디오 파일 선택
- ✅ Appium 백그라운드 실행
- ✅ 익시오 통화 자동화

### 3. 테스트 시나리오 구현
- ✅ 익시오 앱 자동 실행
- ✅ 전화 발신
- ✅ "통화 종료" 버튼 감지
- ✅ 3초 대기 후 오디오 재생
- ✅ 오디오 완료 후 통화 종료

---

## 🚀 빠른 시작

### 1. 앱 실행 (개발 모드)

```bash
# 터미널 열기
cd /Users/qabulls/Documents/sound/sound-test-app

# 개발 모드로 실행
npm run tauri dev
```

### 2. DMG 빌드 (배포용)

```bash
cd /Users/qabulls/Documents/sound/sound-test-app
npm run tauri build
```

빌드 완료 후:
- 위치: `src-tauri/target/release/bundle/dmg/`
- DMG 파일을 설치하여 사용

---

## 📱 앱 사용 흐름

### Step 1: Android 연결
1. Android 디바이스에서 무선 디버깅 활성화
2. IP:PORT 입력 (예: 192.168.0. 10:5555)
3. "🔌 Android 자동 연결" 버튼 클릭

### Step 2: iPhone 연결 (선택)
1. Xcode에서 무선 디버깅 설정
2. "📱 iPhone 연결 확인" 버튼 클릭

### Step 3: 화자 설정
- **화자 1 (발신자)**: 디바이스 선택 + 전화번호 입력
- **화자 2 (수신자)**: 디바이스 선택 + 전화번호 입력

### Step 4: 오디오 파일
- 스테레오 WAV 파일명 입력
- 파일은 `/Users/qabulls/Documents/sound/` 에 배치

### Step 5: 테스트 시작
- "▶️ 테스트 시작" 버튼 클릭
- 자동으로 모든 시나리오 실행

---

## 📋 필수 준비사항

### 1. Appium 설치
```bash
npm install -g appium
appium driver install uiautomator2
```

### 2. 오디오 파일 준비
```bash
# 스테레오 WAV 파일 준비
# L 채널 = 화자1 음성
# R 채널 = 화자2 음성
# 
# 파일 위치: /Users/qabulls/Documents/sound/test_audio_stereo.wav
```

### 3. 디바이스 설정
**Android:**
- USB 디버깅 활성화
- 무선 디버깅 활성화
- IP 주소 확인

**iPhone (선택):**
- Xcode에서 무선 디버깅 설정
- "Connect via network" 활성화

---

## 🎯 자동화 프로세스

앱이 자동으로 수행하는 작업:

1. **Appium 서버 시작** (백그라운드)
2. **익시오 앱 실행**
3. **키패드 열기**
4. **전화번호 입력**
5. **발신 버튼 클릭**
6. **"통화 종료" 버튼 감지**
   - 익시오 전화 연결 중 상태
7. **3초 대기**
8. **오디오 재생**
   - 화자1: L 채널
   - 화자2: R 채널 (동시)
9. **오디오 완료 대기**
10. **통화 종료**

---

## 🛠️ 문제 해결

### "Android 연결 실패"
```bash
adb kill-server
adb start-server
adb devices
```

### "Appium 시작 실패"
```bash
# Appium 재설치
npm uninstall -g appium
npm install -g appium
appium driver install uiautomator2
```

### "Python 스크립트 실패"
```bash
# 가상환경 확인
cd /Users/qabulls/Documents/sound
source venv/bin/activate
which python
```

### "익시오 앱을 찾을 수 없음"
- 디바이스에 익시오 앱이 설치되어 있는지 확인
- 앱 패키지명 확인: `com.lguplus.aicallagent`

---

## 📂 프로젝트 구조

```
sound/
├── ixio_automated_test.py       # 익시오 테스트 스크립트
├── audio_handler.py             # 오디오 처리
├── call_state_detector.py       # 통화 상태 감지
├── config.py                    # 디바이스 설정
├── venv/                        # Python 가상환경
│   └── bin/python              # Python 실행 파일
├── test_audio_stereo.wav       # 테스트 오디오 (준비 필요)
└── sound-test-app/             # GUI 앱
    ├── src/                    # React UI
    │   ├── App.tsx
    │   └── App.css
    └── src-tauri/              # Rust 백엔드
        └── src/lib.rs
```

---

## 🎬 데모 시나리오

### 시나리오 1: Android → Android
1. 화자1: Android 디바이스 (발신)
2. 화자2: Android 디바이스 (수신)
3. 익시오 앱으로 통화
4. 스테레오 오디오 재생

### 시나리오 2: Android → iPhone
1. 화자1: Android 디바이스 (발신, 익시오)
2. 화자2: iPhone (수신)
3. 자동 통화 및 오디오 재생

---

## 📝 개발 모드 로그 확인

터미널에서 실시간 로그 확인:

```bash
cd /Users/qabulls/Documents/sound/sound-test-app
npm run tauri dev
```

Python 스크립트 로그도 터미널에 출력됩니다.

---

## 🔄 업데이트 사항

**v1.0 (2026-02-19)**
- ✅ GUI 앱 완성
- ✅ Android ADB 무선 연결
- ✅ iPhone 연결 확인
- ✅ 익시오 통화 자동화
- ✅ 스테레오 오디오 재생
- ✅ "통화 종료" 버튼 감지
- ✅ 3초 대기 로직

---

## 📚 관련 문서

- [GUI_APP_GUIDE.md](GUI_APP_GUIDE.md) - 앱 사용 가이드
- [QUICK_START.md](QUICK_START.md) - 빠른 시작 (CLI 버전)
- [APPIUM_SETUP_GUIDE.md](APPIUM_SETUP_GUIDE.md) - Appium 설치

---

**모든 준비가 완료되었습니다! 🎉**

앱을 실행하려면:
```bash
cd sound-test-app
npm run tauri dev
```

DMG를 빌드하려면:
```bash
cd sound-test-app
npm run tauri build
```
