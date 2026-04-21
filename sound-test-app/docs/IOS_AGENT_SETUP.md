# iOS 오디오 Agent 설정 가이드

## 방법 1: Swift 앱 설치 (5분 소요)

### 1단계: Xcode에서 프로젝트 생성
```bash
# Xcode 열기
open -a Xcode

# File > New > Project
# iOS > App 선택
# Product Name: AudioAgent
# Interface: SwiftUI
# Language: Swift
```

### 2단계: AudioAgent.swift 복사
- `AudioAgent.swift` 파일의 내용을 `ContentView.swift`에 붙여넣기
- Bundle Identifier 변경: `com.yourdomain.AudioAgent`

### 3단계: iPhone에 설치
1. iPhone을 Mac에 USB 연결
2. Xcode에서 상단의 디바이스 선택: "JJ's iPhone"
3. ▶️ Run 버튼 클릭
4. iPhone에서 설정 > 일반 > VPN 및 기기 관리 > 개발자 앱 신뢰

### 4단계: 사용 방법
- 앱이 백그라운드에서 실행 중이면 자동으로 오디오 재생
- Mac HTTP 서버(포트 8800)에서 명령 확인
- `command.txt` 파일에 `play:speaker_2.wav` 쓰면 자동 재생

---

## 방법 2: iOS Shortcuts (제일 간단 ⭐)

### 1단계: Shortcuts 앱에서 새 단축어 생성

1. **iPhone에서 Shortcuts 앱 열기**

2. **새 단축어 만들기**
   - 이름: "Play Audio"
   
3. **액션 추가:**
   ```
   [1] URL 가져오기
       → http://192.168.219.1:8800/speaker_2.wav
   
   [2] URL 콘텐츠 가져오기
       → [1]번의 URL
   
   [3] 미디어 재생
       → [2]번의 파일
   ```

4. **저장**

### 2단계: Appium으로 Shortcuts 실행

Python 코드:
```python
# iPhone에서 Shortcuts 앱 열기
driver.execute_script('mobile: launchApp', {'bundleId': 'com.apple.shortcuts'})
time.sleep(1)

# "Play Audio" 단축어 찾기
shortcut = driver.find_element(AppiumBy.ACCESSIBILITY_ID, "Play Audio")
shortcut.click()
```

### 3단계: URL Scheme으로 직접 실행 (더 간단)

```python
# Shortcuts를 URL Scheme으로 트리거
shortcut_url = "shortcuts://run-shortcut?name=Play%20Audio"
driver.get(shortcut_url)
```

---

## 방법 3: 물리적 Line-In (하드웨어 필요)

### 필요한 장비:
1. **Mac → iPhone 연결:**
   - Lightning to 3.5mm 어댑터 (약 10,000원)
   - 3.5mm 오디오 케이블 (약 5,000원)

2. **연결 방법:**
   ```
   Mac 헤드폰 출력 (3.5mm)
       ↓ [오디오 케이블]
   Lightning 어댑터 입력
       ↓
   iPhone Lightning 포트
   ```

3. **주의사항:**
   ⚠️ Lightning 포트는 입력을 지원하지 않습니다!
   ⚠️ 이 방법은 작동하지 않습니다.

**대안:**
- USB-C to Lightning 케이블로 연결
- Mac을 "오디오 입력 장치"로 설정 ❌ (불가능)

---

## 🎯 권장 방법: Shortcuts (방법 2)

**장점:**
✅ 코드 작성 불필요
✅ 5분 안에 설정 완료
✅ 안정적
✅ 통화 중에도 작동
✅ Appium으로 쉽게 트리거

**단점:**
⚠️ URL Scheme이 차단될 수 있음 (iOS 보안)
⚠️ HTTP 서버 필요 (이미 구현됨)

---

## 구현 완료된 코드 통합

`ixio_automated_test.py`에서 iOS 감지 시:

```python
if self.speaker2_platform == 'iOS':
    # Shortcuts로 오디오 재생
    try:
        shortcut_url = f"shortcuts://run-shortcut?name=Play%20Audio"
        driver2.get(shortcut_url)
        print(f"✅ Shortcuts로 오디오 재생 트리거")
    except:
        # 대체: Mac 스피커 재생
        DeviceAudioPlayer.play_audio_on_mac(audio_file)
```

---

## 테스트 순서

1. **Shortcuts 설치 확인:**
   ```bash
   # iPhone에서 Shortcuts 앱 열기
   # "Play Audio" 단축어 생성 확인
   ```

2. **HTTP 서버 테스트:**
   ```bash
   cd /Users/qabulls/Documents/sound
   python3 -m http.server 8800
   # iPhone Safari에서 접속: http://192.168.219.1:8800/speaker_2.wav
   ```

3. **Shortcuts URL Scheme 테스트:**
   ```bash
   # iPhone Safari 주소창에 입력:
   shortcuts://run-shortcut?name=Play%20Audio
   ```

4. **전체 테스트 실행**
   - Tauri 앱에서 "테스트 시작" 클릭
