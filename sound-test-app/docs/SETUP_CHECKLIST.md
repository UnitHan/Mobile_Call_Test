# 설정 체크리스트

## ✅ 환경 설정 완료 항목

### 1. Python 환경
- [x] Python 3.10 가상환경 생성 완료
- [x] 의존성 패키지 설치 완료
  - Appium-Python-Client
  - selenium
  - numpy
  - moviepy
  - matplotlib
  - pytest

### 2. 다음 단계 (필요한 작업)

#### A. Appium 설치 (필수)
- [ ] Node.js 설치
  ```bash
  brew install node
  ```
- [ ] Appium 설치
  ```bash
  npm install -g appium
  ```
- [ ] Appium 드라이버 설치
  ```bash
  appium driver install uiautomator2
  appium driver install xcuitest  # iOS용
  ```

#### B. Android 설정
- [ ] Android Studio 설치
- [ ] ADB 환경 변수 설정
- [ ] 디바이스 USB 디버깅 활성화
- [ ] UDID 확인
  ```bash
  adb devices
  ```

#### C. iOS 설정 (선택사항)
- [ ] Xcode 설치
- [ ] WebDriverAgent 설정
- [ ] UDID 확인

#### D. config.py 설정
- [ ] `android_a` UDID 입력
- [ ] `android_b` 또는 `ios_b` UDID 입력
- [ ] 실제 전화번호 입력
- [ ] platformVersion 확인

#### E. 오디오 파일 준비
- [ ] 스테레오 WAV 파일 준비
  - L 채널: 화자1 음성
  - R 채널: 화자2 음성
- [ ] 파일을 프로젝트 루트에 배치
  - 파일명: `test_audio_stereo.wav`

#### F. 실행 테스트
- [ ] Appium 서버 실행
  ```bash
  appium
  ```
- [ ] 테스트 스크립트 실행
  ```bash
  source venv/bin/activate
  python dual_speaker_call_test.py
  ```

---

## 📝 설정 값 메모

### 디바이스 정보

#### 화자 1 (android_a)
- UDID: `______________________`
- 전화번호: `+82______________`
- Android 버전: `______`

#### 화자 2 (android_b 또는 ios_b)
- UDID: `______________________`
- 전화번호: `+82______________`
- OS 버전: `______`

### 오디오 파일
- 파일명: `______________________`
- 위치: `/Users/qabulls/Documents/sound/`

---

## 🚀 실행 명령어 정리

### 가상환경 활성화
```bash
cd /Users/qabulls/Documents/sound
source venv/bin/activate
```

### Appium 서버 실행 (터미널 1)
```bash
appium
```

### 테스트 실행 (터미널 2)
```bash
source venv/bin/activate
python dual_speaker_call_test.py
```

---

## 📚 문서 참고

- **빠른 시작**: [QUICK_START.md](QUICK_START.md)
- **Appium 설치**: [APPIUM_SETUP_GUIDE.md](APPIUM_SETUP_GUIDE.md)
- **디바이스 설정**: [config.py](config.py)

---

**현재 완료된 것:**
✅ Python 3.10 가상환경 설정
✅ 모든 Python 의존성 설치 완료

**다음에 해야 할 것:**
⬜ Appium 설치
⬜ 디바이스 연결
⬜ config.py 설정
⬜ 오디오 파일 준비
