# iPhone 무선 자동화 연결 가이드

> Appium + XCUITest로 USB 없이 iPhone을 Wi-Fi로 제어하는 방법

---

## 📌 한 줄 요약

iPhone에서 Xcode가 설치한 **WebDriverAgent(WDA)** 앱이 HTTP 서버 역할을 하고,  
Appium이 그 서버로 명령을 보내 iPhone을 원격 조종합니다.  
USB 없이 Wi-Fi로 동작하게 하려면 몇 가지 우회 작업이 필요합니다.

---

## 🗺️ 전체 구조 한눈에 보기

```
Mac (Appium 4724) ──── Wi-Fi ────> iPhone (WDA :8100)
        ↑                                   ↑
  Python 스크립트                    Xcode가 설치한 앱
  webDriverAgentUrl                  HTTP 서버로 동작
  지정                               포트 8100 리슨
```

**흐름:**
1. Xcode로 iPhone에 WDA 앱 빌드/설치
2. iPhone과 Mac을 같은 Wi-Fi에 연결
3. Xcode에서 WDA 실행 → iPhone IP:8100에서 HTTP 서버 시작
4. Python 스크립트에서 `webDriverAgentUrl = http://{iPhone IP}:8100` 지정
5. Appium이 WDA 서버로 명령 전달 → iPhone 제어

---

## 🔧 사전 준비 (최초 1회)

### 1단계: WDA 앱을 iPhone에 설치

WDA는 Appium이 iPhone을 제어할 때 사용하는 **브릿지 앱**입니다.  
직접 App Store에 올라와 있지 않으므로 Xcode로 직접 빌드해야 합니다.

```bash
# Appium XCUITest 드라이버가 WDA 소스를 자동 설치
appium driver install xcuitest

# WDA 소스 경로 확인
ls ~/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/
```

**Xcode로 WDA 빌드:**
1. Xcode 실행
2. `~/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj` 파일 열기
3. iPhone을 **USB로 연결** (최초 1회만 USB 필요)
4. `WebDriverAgentRunner` 타겟 선택 → iPhone 선택 → ▶️ 실행
5. iPhone에 앱 설치 완료 확인

> 💡 **Bundle ID 커스터마이징 (권장)**  
> Xcode → WebDriverAgentRunner → Signing & Capabilities  
> Bundle ID를 `com.{팀이름}.WebDriverAgentRunner` 으로 변경  
> 예: `com.jjun2.WebDriverAgentRunner`

---

### 2단계: iPhone을 Wi-Fi로 연결 (Xcode)

USB를 꽂은 상태에서:
1. Xcode 메뉴 → **Window → Devices and Simulators**
2. iPhone 선택 → **Connect via network** 체크박스 ✅
3. iPhone 옆에 🌐 아이콘이 표시되면 성공
4. USB 제거해도 Xcode에서 디바이스 연결 유지됨

---

## 🐛 왜 일반 방법으로 바로 안 되나?

### 문제 1: Appium이 iPhone을 못 찾음
```
Error: Unknown device or simulator UDID: '00008101-...'
```

**원인:** Appium은 기본적으로 `libimobiledevice`로 기기를 찾는데,  
이건 USB 연결만 지원합니다. Wi-Fi 연결된 iPhone은 못 찾습니다.

**해결:** `APPIUM_XCUITEST_PREFER_DEVICECTL=1` 환경변수 설정  
→ Appium이 Apple의 `xcrun devicectl`(Wi-Fi 지원)을 사용하도록 전환

```bash
# Appium 서버 실행 시 환경변수 추가
APPIUM_XCUITEST_PREFER_DEVICECTL=1 appium -p 4724
```

---

### 문제 2: iOS 버전을 못 읽음
```
Error: Could not find the expected device (Usbmux.connectLockdown 실패)
```

**원인:** Appium이 iOS 버전을 자동으로 읽을 때 `usbmux`(USB 프로토콜)를 사용합니다.  
Wi-Fi 연결에서는 usbmux로 통신이 안 됩니다.

**해결:** capabilities에 `platformVersion`을 **직접 지정**하면 Appium이 조회를 건너뜀

```python
# xcrun xctrace로 버전 파싱 → capabilities에 직접 지정
result = subprocess.run(['xcrun', 'xctrace', 'list', 'devices'], ...)
# "JJ (26.3) (00008101-...)" 에서 "26.3" 추출

device_config['appium:platformVersion'] = '26.3'  # 자동 조회 우회
```

---

### 문제 3: WDA 세션 충돌 (socket hang up)
```
Error: Could not proxy command. Original error: socket hang up
```

**원인:** Xcode가 WDA를 실행한 상태에서 이전 세션(연결)이 살아있으면,  
Appium이 새 세션을 만들려 할 때 WDA가 거부합니다.

**해결:** Appium 연결 전에 기존 WDA 세션을 **먼저 삭제**

```python
# WDA /status 에서 현재 세션 ID 확인
status = GET http://192.168.219.110:8100/status
session_id = status['sessionId']  # e.g. "EB11D2AC-..."

# 세션 삭제
DELETE http://192.168.219.110:8100/session/{session_id}

# 이후 Appium 연결 → 새 세션 정상 생성
```

---

### 문제 4: WDA 재기동 시도로 hang up
**원인:** `useNewWDA`, `usePrebuiltWDA`, `updatedWDABundleId` capability가 있으면  
Appium이 WDA를 **종료하고 새로 기동**하려 시도합니다.  
Xcode가 소유한 WDA는 외부에서 종료/재기동을 거부하므로 hang up 발생.

**해결:** `webDriverAgentUrl`을 지정할 때 WDA 제어 capabilities를 **모두 제거**

```python
# ❌ 잘못된 방법 - WDA 재기동 시도로 hang up
device_config = {
    'appium:webDriverAgentUrl': 'http://192.168.219.110:8100',
    'appium:useNewWDA': True,           # 이게 hang up 유발
    'appium:updatedWDABundleId': '...',  # 이것도
}

# ✅ 올바른 방법 - WDA 재사용만
device_config = {
    'appium:webDriverAgentUrl': 'http://192.168.219.110:8100',
    # WDA 제어 관련 capabilities 없음 → Appium이 재사용만 함
    'appium:noReset': True,
    'appium:waitForQuiescence': False,
}
```

---

## ✅ 최종 작동 방식 (전체 코드 흐름)

```python
# 1. iPhone IP 조회 (mDNS)
ping -c 1 JJ.local  →  192.168.219.110

# 2. WDA 실행 상태 확인
GET http://192.168.219.110:8100/status
→ { "ready": true, "sessionId": "EB11D2AC-..." }

# 3. 기존 세션 삭제 (있으면)
DELETE http://192.168.219.110:8100/session/EB11D2AC-...
→ { "value": null }

# 4. iOS 버전 조회 (usbmux 우회)
xcrun xctrace list devices
→ "JJ (26.3) (00008101-...)"  →  version = "26.3"

# 5. Appium 세션 생성
POST http://127.0.0.1:4724/session
{
  "platformName": "iOS",
  "appium:udid": "00008101-00164D3C0CE0001E",
  "appium:automationName": "XCUITest",
  "appium:platformVersion": "26.3",       ← usbmux 우회
  "appium:webDriverAgentUrl": "http://192.168.219.110:8100",  ← 기존 WDA 재사용
  "appium:noReset": true,
  "appium:waitForQuiescence": false
}
→ 세션 생성 성공 ✅
```

---

## 📋 환경 요구사항 체크리스트

| 항목 | 확인 방법 | 필요 조건 |
|------|-----------|-----------|
| Appium 버전 | `appium -v` | 3.x 이상 |
| XCUITest 드라이버 | `appium driver list` | 10.x 이상 |
| Xcode | `xcode-select -p` | 설치됨 |
| iPhone-Mac Wi-Fi | `ping JJ.local` | 응답 있음 |
| WDA 설치 여부 | `curl http://{iPhone IP}:8100/status` | `"ready": true` |
| devicectl | `xcrun devicectl list devices` | iPhone 표시됨 |

---

## 🚀 새 환경에서 처음 설정할 때 순서

```
1. Appium + XCUITe/Users/qabulls/Documents/sound/speaker_2.wavst 드라이버 설치
   npm install -g appium
   appium driver install xcuitest

2. iPhone을 USB로 Mac에 연결

3. Xcode에서 WDA 빌드 & 설치
   (위 1단계 참고)

4. Xcode에서 "Connect via network" 활성화
   (위 2단계 참고)

5. USB 제거 후 Wi-Fi 연결 확인
   ping {iPhone 이름}.local

6. Xcode에서 WebDriverAgentRunner 실행 (▶️)
   또는 Appium이 자동으로 실행하게 해도 됨

7. WDA 동작 확인
   curl http://{iPhone IP}:8100/status

8. Appium 서버 실행 (환경변수 필수!)
   APPIUM_XCUITEST_PREFER_DEVICECTL=1 appium -p 4724

9. Python 스크립트 실행
```

---

## ⚠️ 자주 겪는 문제와 해결법

### "WDA 응답 없음" (포트 8100 연결 실패)
```bash
curl http://{iPhone IP}:8100/status  # 실패
```
→ Xcode에서 WebDriverAgentRunner를 다시 실행하거나  
→ iPhone Wi-Fi 연결 상태 확인 (`ping JJ.local`)

### "Unknown UDID" 에러
```
APPIUM_XCUITEST_PREFER_DEVICECTL=1  # 환경변수 빠진 것
```
→ Appium 서버 실행 시 환경변수 반드시 포함

### 매 테스트마다 WDA가 꺼짐
→ Xcode에서 실행한 WDA는 30분 타임아웃 있음  
→ `appium:wdaConnectionTimeout: 90000` 설정으로 완화  
→ 또는 iPhone 잠금 화면이 꺼지지 않도록 설정

### iPhone 이름으로 IP 조회 실패
```python
# 기기 이름이 다른 경우
ping JJ.local  # "JJ"는 iPhone 설정의 이름
```
→ iPhone 설정 → 일반 → 정보 → 이름 확인  
→ 코드의 `_get_iphone_ip('JJ')` 에서 `'JJ'` 부분을 실제 이름으로 변경

---

## 📁 관련 파일

| 파일 | 역할 |
|------|------|
| `ixio_automated_test.py` | 테스트 메인 로직, iOS 연결 처리 |
| `sound-test-app/src-tauri/src/lib.rs` | Tauri 백엔드, Appium 서버 시작 (`APPIUM_XCUITEST_PREFER_DEVICECTL=1` 포함) |
| `audio_handler.py` | 오디오 재생 처리 |

---

## 🔑 핵심 요약 (3줄)

1. **WDA를 Xcode로 iPhone에 먼저 설치**해야 합니다 (최초 1회 USB 필요)
2. **`APPIUM_XCUITEST_PREFER_DEVICECTL=1`** 환경변수로 Wi-Fi 기기 탐색 활성화
3. **`webDriverAgentUrl`** 에 iPhone IP:8100 지정 + WDA 제어 capabilities 없이 → 재사용 성공
