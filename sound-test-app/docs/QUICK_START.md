# 빠른 시작 가이드

## 프로그램 개요

이 프로그램은 **화자 1, 화자 2** 간의 통화를 자동으로 시작하고, **스테레오 오디오 파일**을 각 화자별로 분리하여 재생하는 Appium 기반 자동화 테스트입니다.

- **화자 1**: 발신자 - L 채널 오디오 재생
- **화자 2**: 수신자 - R 채널 오디오 재생
- **통화 연결 확인 후 동시에 오디오 재생**

---

## 1. 환경 설정 (한 번만)

### 1.1 Python 가상환경 설정

```bash
# 프로젝트 폴더로 이동
cd /Users/qabulls/Documents/sound

# 가상환경 활성화 (이미 생성됨)
source venv/bin/activate

# 의존성 확인
pip list
```

✅ **이미 완료됨!** Python 3.10 가상환경과 의존성이 설치되어 있습니다.

### 1.2 Appium 설치

```bash
# Node.js 설치
brew install node

# Appium 설치
npm install -g appium

# Appium 드라이버 설치
appium driver install uiautomator2  # Android용
appium driver install xcuitest      # iOS용 (macOS만)

# 설치 확인
appium --version
```

📖 자세한 설치 방법: [APPIUM_SETUP_GUIDE.md](APPIUM_SETUP_GUIDE.md)

---

## 2. 디바이스 설정

### 2.1 Android 디바이스

#### USB 디버깅 활성화
1. 설정 > 휴대전화 정보 > 빌드번호 7번 탭 (개발자 모드 활성화)
2. 설정 > 개발자 옵션 > USB 디버깅 활성화

#### UDID 확인
```bash
adb devices

# 출력 예시:
# ABC123456789    device
#
# ABC123456789가 UDID입니다
```

#### WiFi 연결 (선택사항)
```bash
# WiFi 디버깅 활성화 (설정 > 개발자 옵션 > 무선 디버깅)
adb connect 192.168.0.10:5555

# 연결 확인
adb devices
```

### 2.2 iOS 디바이스 (선택사항)

#### Xcode에서 UDID 확인
1. Xcode 실행
2. Window > Devices and Simulators
3. 디바이스 선택 > Identifier 확인

---

## 3. config.py 설정

`config.py` 파일을 열어 실제 디바이스 정보를 입력하세요.

```python
DEVICES = {
    'android_a': {
        # ...
        'udid': 'ABC123456789',  # ⚠️ 여기에 실제 UDID 입력
        'platformVersion': '13',  # ⚠️ 실제 Android 버전
    },
    'android_b': {
        # ...
        'udid': 'DEF987654321',  # ⚠️ 여기에 실제 UDID 입력
        'platformVersion': '13',
    },
}

PHONE_NUMBERS = {
    'android_a': '+821012345678',  # ⚠️ 화자1 실제 전화번호
    'android_b': '+821087654321',  # ⚠️ 화자2 실제 전화번호
}
```

---

## 4. 오디오 파일 준비

**스테레오 WAV 파일**을 준비하세요.

- **L 채널**: 화자1 음성
- **R 채널**: 화자2 음성
- **형식**: WAV, 스테레오 (2채널)

파일 위치: 프로젝트 루트에 `test_audio_stereo.wav` 배치

예시:
```
/Users/qabulls/Documents/sound/
├── dual_speaker_call_test.py
├── test_audio_stereo.wav  ← 여기에 오디오 파일
└── ...
```

---

## 5. 테스트 실행

### 5.1 Appium 서버 실행 (터미널 1)

```bash
# 새 터미널 창 열기
appium

# 출력:
# [Appium] Welcome to Appium v2.x.x
# [Appium] Appium REST http interface listener started on 0.0.0.0:4723
```

⚠️ **이 터미널은 계속 열어두세요!**

### 5.2 테스트 스크립트 실행 (터미널 2)

```bash
# 가상환경 활성화
source venv/bin/activate

# 테스트 실행
python dual_speaker_call_test.py
```

---

## 6. dual_speaker_call_test.py 설정

스크립트 하단의 `main()` 함수에서 설정을 수정할 수 있습니다.

```python
def main():
    # 설정
    SPEAKER1_DEVICE = 'android_a'    # 화자1 디바이스
    SPEAKER2_DEVICE = 'android_b'    # 화자2 디바이스 (또는 'ios_b')
    STEREO_AUDIO_FILE = 'test_audio_stereo.wav'  # 오디오 파일명
    CALL_DURATION = 60  # 통화 시간 (초)
    
    # ...
```

---

## 7. 실행 흐름

프로그램 실행 시 다음과 같이 진행됩니다:

```
1️⃣ 스테레오 오디오 분리 (L/R 채널)
   └─> audio_files/test_audio_LEFT.wav
   └─> audio_files/test_audio_RIGHT.wav

2️⃣ 디바이스 연결
   └─> 화자1 (android_a) ✅
   └─> 화자2 (android_b) ✅

3️⃣ 오디오 파일 전송
   └─> Android: /sdcard/Download/

4️⃣ 통화 시작
   └─> 화자1 → 화자2 발신
   └─> 화자2 자동 수신

5️⃣ 통화 연결 확인 ⏳

6️⃣ 오디오 재생 🔊
   └─> 화자1: L 채널 재생
   └─> 화자2: R 채널 재생 (동시)

7️⃣ 통화 유지 (60초)

8️⃣ 통화 종료 📵

9️⃣ 정리 및 종료 ✅
```

---

## 8. 문제 해결

### Q1. "디바이스 연결 실패"

```bash
# Appium 서버가 실행 중인지 확인
ps aux | grep appium

# ADB 재시작
adb kill-server
adb start-server
adb devices
```

### Q2. "Element를 찾을 수 없습니다"

UI 요소는 OS/제조사/앱 버전마다 다를 수 있습니다.

**해결 방법:**
1. **Appium Inspector** 다운로드: https://github.com/appium/appium-inspector/releases
2. 실제 UI 요소 확인
3. 스크립트의 selector(ID, XPATH) 수정

### Q3. "통화 연결 실패"

- 두 디바이스가 실제로 통화 가능한지 확인 (통신사, 요금제 등)
- 전화번호가 정확한지 확인
- 수동으로 한 번 테스트해보세요

### Q4. "오디오 재생 안 됨"

Android:
```bash
# 파일이 전송되었는지 확인
adb shell ls /sdcard/Download/

# 권한 확인
adb shell ls -l /sdcard/Download/test_audio.wav
```

---

## 9. 고급 사용법

### 익시오(AI Call) 앱 사용

`config.py`에서 앱 패키지 변경:

```python
'appPackage': 'com.lguplus.aicallagent',  # 익시오 앱
'appActivity': '.MainActivity',
```

그리고 `ixio_call_test.py` 사용:

```bash
python ixio_call_test.py
```

### 다른 테스트 스크립트

```bash
# 일반 음성 통화 테스트
python voice_call_test.py

# 오디오 파일 분리만
python separate_audio.py your_audio.wav

# 스테레오 분석
python analyze_stereo.py your_audio.wav
```

---

## 10. 참고 파일

- `APPIUM_SETUP_GUIDE.md` - Appium 상세 설치 가이드
- `config.py` - 디바이스 및 전화번호 설정
- `dual_speaker_call_test.py` - 메인 테스트 스크립트
- `audio_handler.py` - 오디오 처리
- `call_state_detector.py` - 통화 상태 감지

---

## 11. 주의사항

⚠️ **실제 통화가 발생합니다!**
- 통화료가 발생할 수 있습니다
- 테스트용 번호 사용을 권장합니다

⚠️ **자동화 제한**
- 일부 UI 요소는 제조사/버전마다 다를 수 있습니다
- 수동 조작이 필요한 경우가 있을 수 있습니다

⚠️ **디바이스 상태**
- 충분한 배터리 확보
- 안정적인 네트워크 연결
- 방해금지 모드 해제

---

## 12. 도움말

문제가 발생하면:

1. 로그 확인 (터미널 출력)
2. Appium Inspector로 UI 요소 확인
3. 수동으로 단계별 테스트
4. config.py 설정 재확인

---

**Happy Testing! 🎉**
