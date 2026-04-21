# Appium 설치 및 설정 가이드

## 1. Appium 설치

### macOS에서 Appium 설치

```bash
# Node.js 설치 (Homebrew 사용)
brew install node

# Appium 2.0 설치
npm install -g appium

# Appium Doctor 설치 (환경 확인 도구)
npm install -g appium-doctor

# Appium 드라이버 설치
appium driver install uiautomator2  # Android용
appium driver install xcuitest      # iOS용
```

### 설치 확인

```bash
# Appium 버전 확인
appium --version

# 환경 설정 확인
appium-doctor --android  # Android 환경 확인
appium-doctor --ios      # iOS 환경 확인
```

## 2. Android 설정

### 필수 요구사항

1. **Android Studio 설치**
   - https://developer.android.com/studio
   - Android SDK, Platform Tools 포함

2. **환경 변수 설정**

```bash
# ~/.zshrc 또는 ~/.bash_profile에 추가
export ANDROID_HOME=$HOME/Library/Android/sdk
export PATH=$PATH:$ANDROID_HOME/emulator
export PATH=$PATH:$ANDROID_HOME/tools
export PATH=$PATH:$ANDROID_HOME/tools/bin
export PATH=$PATH:$ANDROID_HOME/platform-tools

# 적용
source ~/.zshrc
```

3. **ADB 확인**

```bash
adb version
```

### 실제 Android 디바이스 설정

1. **USB 디버깅 활성화**
   - 설정 > 휴대전화 정보 > 빌드 번호 7번 탭
   - 설정 > 개발자 옵션 > USB 디버깅 활성화

2. **무선 디버깅 설정 (WiFi 연결)**
   - 설정 > 개발자 옵션 > 무선 디버깅 활성화
   - IP 주소와 포트 확인 (예: 192.168.0.10:5555)

```bash
# WiFi로 디바이스 연결
adb connect 192.168.0.10:5555

# 연결 확인
adb devices
```

3. **UDID 확인**

```bash
adb devices
# 출력 예: ABC123456789    device
# ABC123456789가 UDID
```

## 3. iOS 설정 (macOS만 가능)

### 필수 요구사항

1. **Xcode 설치**
   - App Store에서 Xcode 설치
   - 최신 버전 권장

2. **Xcode Command Line Tools 설치**

```bash
xcode-select --install
```

3. **WebDriverAgent 설정**

```bash
# Carthage 설치 (의존성 관리)
brew install carthage

# WebDriverAgent 빌드
cd /Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/Developer/Library/Frameworks/
# 여기서 Xcode로 WebDriverAgent 프로젝트 열기
```

4. **iOS 실제 디바이스 설정**

   - 설정 > 일반 > VPN 및 기기 관리 > 개발자 앱 신뢰
   - Xcode에서 Signing & Capabilities 설정
   - 실제 디바이스를 Mac에 USB 연결

5. **UDID 확인**

```bash
# Xcode에서
Window > Devices and Simulators > 디바이스 선택 > Identifier 확인

# 또는 터미널에서
idevice_id -l
```

## 4. Appium 서버 실행

### 기본 실행

```bash
# 기본 포트(4723)로 실행
appium

# 또는 특정 포트 지정
appium --port 4723
```

### Appium Inspector 사용 (UI 요소 확인)

```bash
# Appium Inspector 다운로드
# https://github.com/appium/appium-inspector/releases

# 실행 후 설정:
# - Remote Host: 127.0.0.1
# - Remote Port: 4723
# - Capabilities: JSON 형식으로 디바이스 정보 입력
```

예시 Capabilities (Android):
```json
{
  "platformName": "Android",
  "platformVersion": "13",
  "deviceName": "Android_Device",
  "udid": "your_device_udid",
  "automationName": "UiAutomator2",
  "appPackage": "com.android.dialer",
  "appActivity": ".DialtactsActivity"
}
```

## 5. 프로젝트 config.py 설정

```python
# config.py 파일 수정

DEVICES = {
    'android_a': {
        'platformName': 'Android',
        'platformVersion': '13',  # 실제 Android 버전
        'deviceName': 'Speaker1_Android',
        'udid': 'ABC123456789',  # adb devices로 확인한 UDID
        'automationName': 'UiAutomator2',
        'appPackage': 'com.android.dialer',
        'appActivity': '.DialtactsActivity',
        'noReset': True,
        'newCommandTimeout': 300,
    },
    'android_b': {
        'platformName': 'Android',
        'platformVersion': '13',
        'deviceName': 'Speaker2_Android',
        'udid': 'DEF987654321',  # 두 번째 Android UDID
        'automationName': 'UiAutomator2',
        'appPackage': 'com.android.dialer',
        'appActivity': '.DialtactsActivity',
        'noReset': True,
        'newCommandTimeout': 300,
    },
    'ios_b': {
        'platformName': 'iOS',
        'platformVersion': '17.0',  # 실제 iOS 버전
        'deviceName': 'Speaker2_iPhone',
        'udid': 'your-ios-udid-here',  # Xcode에서 확인한 UDID
        'automationName': 'XCUITest',
        'bundleId': 'com.apple.mobilephone',
        'noReset': True,
        'newCommandTimeout': 300,
        'wdaLocalPort': 8100,
        'usePrebuiltWDA': True,
    }
}

PHONE_NUMBERS = {
    'android_a': '+821012345678',  # 화자1 전화번호
    'android_b': '+821087654321',  # 화자2 전화번호 (Android)
    'ios_b': '+821098765432',      # 화자2 전화번호 (iOS)
}
```

## 6. 테스트 실행

```bash
# 1. 가상환경 활성화
source venv/bin/activate

# 2. Appium 서버 실행 (새 터미널 창에서)
appium

# 3. 테스트 스크립트 실행 (원래 터미널에서)
python dual_speaker_call_test.py
```

## 7. 문제 해결

### Appium 연결 안 됨
```bash
# Appium 서버 재시작
pkill -f appium
appium
```

### Android 디바이스 연결 안 됨
```bash
# ADB 재시작
adb kill-server
adb start-server
adb devices
```

### iOS WebDriverAgent 오류
```bash
# WDA 재빌드
cd ~/path/to/WebDriverAgent
./Scripts/bootstrap.sh
```

### UI 요소를 찾지 못함
- Appium Inspector로 실제 요소 확인
- selector 업데이트 필요

## 8. 추가 도구

### Appium Desktop (레거시, 참고용)
```bash
# Appium Inspector를 사용하세요 (최신)
# https://github.com/appium/appium-inspector
```

### Android Device Monitor
```bash
# Android Studio에서
Tools > Device Manager
```

## 참고 자료

- Appium 공식 문서: https://appium.io/docs/en/latest/
- UiAutomator2: https://github.com/appium/appium-uiautomator2-driver
- XCUITest: https://github.com/appium/appium-xcuitest-driver
- Appium Inspector: https://github.com/appium/appium-inspector
