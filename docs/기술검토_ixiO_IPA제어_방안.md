# 기술 검토 — ixiO 앱 제어용 IPA 개발 가능성

**작성일:** 2026-04-08  
**작성자:** 자동화 테스트 플랫폼 팀  
**검토 대상:** iPhone 내 ixiO 통화 앱을 외부에서 제어하는 IPA 개발 3가지 방안

---

## 0. 현재 구조와 문제 인식

현재 자동화 아키텍처는 다음과 같다:

```
Mac (Python/Appium) → USB → iPhone (Appium Agent) → ixiO 앱 UI 터치
```

**현재 방식의 한계:**
- Appium은 UI 요소 탐색 기반 → ixiO UI 구조 변경 시 스크립트 깨짐
- `WebDriverAgent` (Appium iOS 에이전트) 설치에 **Apple Developer 계정** 필요
- 전화 걸기 이후 통화 중 상태 확인/제어가 불가
- Appium 세션 불안정 시 전체 TC 실패

**목표:** ixiO 앱과 **직접 소통**하거나, 더 안정적인 방식으로 **전화 걸기/받기/끊기**를 제어하는 IPA 개발

---

## 1. 방안별 상세 기술 검토

---

### 방안 A: 앱 내장형 로컬 웹 서버 (코드 수정 필요)

#### 핵심 조건
> ixiO 앱의 **소스 코드에 접근 가능**해야 한다.

#### 구현 구조

```
Mac Python 스크립트
    └─ HTTP POST http://iPhone-IP:8080/call?number=01012345678
           │
    iPhone (ixiO 앱 내부 TCP 서버)
           │
    ixiO CallManager.makeCall("01012345678")
```

#### 필요 라이브러리
| 라이브러리 | 특징 |
|-----------|------|
| [Swifter](https://github.com/httpswift/swifter) | Swift 순수 구현, SPM 지원, 가장 단순 |
| [GCDWebServer](https://github.com/swissr/GCDWebServer) | Obj-C 기반, 안정적, 파일 서버 내장 |
| Telegraph | Swift + TLS 지원, 보안 필요 시 |

#### 최소 구현 예제 (Swifter 기반)

```swift
import Swifter

class TestControlServer {
    let server = HttpServer()
    
    func start() {
        server["/call"] = { req in
            let number = req.queryParams.first(where: { $0.0 == "number" })?.1 ?? ""
            DispatchQueue.main.async {
                CallManager.shared.makeCall(to: number)
            }
            return HttpResponse.ok(.text("{\"status\": \"dialing\"}"))
        }
        
        server["/hangup"] = { _ in
            DispatchQueue.main.async { CallManager.shared.hangUp() }
            return HttpResponse.ok(.text("{\"status\": \"hungup\"}"))
        }
        
        server["/status"] = { _ in
            let state = CallManager.shared.currentState.rawValue
            return HttpResponse.ok(.text("{\"state\": \"\(state)\"}"))
        }
        
        try? server.start(8080, forceIPv4: true)
    }
}
```

#### Mac에서 호출 방법 (Python)

```python
import requests

IPHONE_IP = "192.168.1.100"  # 유동 IP 대신 static 설정 권장

def make_call(number: str):
    r = requests.post(f"http://{IPHONE_IP}:8080/call?number={number}")
    return r.json()

def get_call_status():
    r = requests.get(f"http://{IPHONE_IP}:8080/status")
    return r.json()["state"]  # "idle" | "dialing" | "connected" | "ended"
```

#### 현실적 제약사항

| 항목 | 상황 |
|------|------|
| 소스 코드 접근 | **LG U+ 내부 산 빌드** 기준으로는 가능 (내부 배포 빌드에 코드 추가) |
| 앱 스토어 배포 | 불가 (Apple 정책: 앱 내 HTTP 서버 허용 안 함) |
| 심사 없는 배포 | Enterprise 인증서 or Ad Hoc 배포로 가능 |
| 포그라운드 제약 | iOS 백그라운드에서 TCP 서버 **15초 후 중단** 가능 — `BackgroundMode: voip` 권한 필요 |
| IP 주소 관리 | 기기 IP가 변경되면 Mac 스크립트 수동 수정 필요 |

#### 평가
```
구현 복잡도: ★★★☆☆ (중간)  
안정성:     ★★★★☆ (높음 — UI 변경에 무관)  
선행 조건:  ixiO 앱 소스 접근 필수 ← 가장 큰 장벽
```

---

### 방안 B: URL Scheme + x-callback-url (설정 위주)

#### 핵심 조건
> ixiO 앱의 `Info.plist`에 **커스텀 URL Scheme 등록** + `AppDelegate`/`SceneDelegate` 처리 코드 필요  
> 소스 수정이 최소화되지만, 여전히 내부 빌드 접근이 필요하다.

#### URL Scheme 등록 (Info.plist)

```xml
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleURLSchemes</key>
        <array>
            <string>ixio</string>
        </array>
        <key>CFBundleURLName</key>
        <string>com.lguplus.ixio</string>
    </dict>
</array>
```

#### 앱 내 URL 처리 (SceneDelegate.swift)

```swift
func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
    guard let url = URLContexts.first?.url else { return }
    // URL 형식: ixio://call?number=01012345678&callback=ixio-test://result
    
    if url.host == "call",
       let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
       let number = components.queryItems?.first(where: { $0.name == "number" })?.value {
        CallManager.shared.makeCall(to: number)
    }
}
```

#### 호출 방법

**Mac Python → Appium으로 Safari 열어서 URL Scheme 실행:**
```python
driver.get(f"ixio://call?number=01012345678")
```

**또는 Siri Shortcuts를 통한 독립 트리거:**
```
단축어: "URL 열기" → ixio://call?number=01012345678
트리거: 자동화 → 다른 앱이 열릴 때
```

#### 제약사항

| 항목 | 설명 |
|------|------|
| 앱 전환 | URL Scheme 호출 시 ixiO 앱이 **포그라운드로 전환**됨 |
| 단방향 통신 | 응답(통화 성공/실패 여부)을 받을 수 없음 — x-callback-url로 보완 필요 |
| 연속 제어 | 전화 걸기 → 통화 중 → 끊기 흐름이 각각 별도 URL 호출 필요 |
| iOS 13+ 보안 | 다른 앱이 URL Scheme 호출 시 **사용자 확인 팝업** 발생 가능 |
| 소스 필요 여부 | Info.plist + SceneDelegate 수정 필요 → **내부 빌드 필요** |

#### x-callback-url로 결과 수신 (보완책)

```
ixio://call?number=01012345678
    &x-success=ixio-agent://callback?result=connected
    &x-error=ixio-agent://callback?result=failed
```
→ 별도 **ixio-agent IPA**가 callback URL을 받아 Mac에 HTTP 전달

#### 평가
```
구현 복잡도: ★★☆☆☆ (낮음 — 설정 + 최소 코드)  
안정성:     ★★★☆☆ (중간 — iOS 보안 팝업, 앱 전환 이슈)  
선행 조건:  ixiO 소스 수정 필요 (최소화 가능)
통화 상태 수신: 어려움 (단방향에 가까움)
```

---

### 방안 C: XCUITest 기반 Runner 앱 (소스 수정 불필요)

#### 핵심 조건
> ixiO 앱 **소스 코드 불필요** — 단, 기기에 **개발자 서명된 Runner IPA** 설치 필요

현재 Appium의 동작 방식이 바로 이 방식이다.  
`WebDriverAgent`가 XCUITest 프레임워크를 이용해 ixiO 앱을 제어한다.

#### 현재 Appium 방식과 차이

| 항목 | Appium | 자체 Runner IPA |
|------|--------|----------------|
| 에이전트 | WebDriverAgent (오픈소스) | 직접 빌드한 Swift 앱 |
| 통신 | USB → HTTP over USB | Wi-Fi HTTP or USB |
| 설치 | Xcode로 빌드 후 기기 설치 | IPA 파일 Ad Hoc 설치 |
| 유지보수 | WebDriverAgent 업데이트 의존 | 직접 제어 |
| UI 접근 | `XCUIApplication` 풀 지원 | 동일 |

#### 자체 Runner 앱 구조

```swift
// RunnerApp.swift — 독립 실행 가능한 XCUITest Runner
import XCTest

class iXiORunner: XCTestCase {
    
    let app = XCUIApplication(bundleIdentifier: "com.lguplus.ixio")
    
    override func setUp() {
        app.launch()
    }
    
    func dialNumber(_ number: String) {
        // 키패드 탭 이동
        app.tabBars.buttons["키패드"].tap()
        
        // 번호 입력
        for digit in number {
            app.buttons[String(digit)].tap()
        }
        
        // 전화 걸기
        app.buttons["통화"].tap()
    }
    
    func hangUp() {
        app.buttons["종료"].tap()
    }
}
```

#### 외부 제어 통합 방법

XCUITest 코드 자체를 HTTP 서버 명령으로 트리거하는 아키텍처:

```
Mac Python → HTTP → Runner IPA (XCUITest + 내장 HTTP 수신)
                         │
                    XCUIApplication → ixiO 앱 UI 제어
```

Runner IPA 내부에서 Swifter로 간이 HTTP 서버를 열고, `/dial`, `/hangup` 요청을 받으면 XCUITest 액션 실행.

#### 제약사항

| 항목 | 설명 |
|------|------|
| 서명 방법 | Enterprise 인증서 or Development 서명 (탈옥 불필요) |
| 기기 등록 | UDID를 Apple Developer 계정에 등록 필요 |
| App Store | 배포 불필요 — 내부 기기에만 Ad Hoc 설치 |
| UI 변경 취약성 | ixiO 앱 UI 변경 시 버튼 쿼리 수정 필요 |
| 시스템 앱 접근 | `XCUIApplication(bundleIdentifier:)`로 **모든 비시스템 앱** 제어 가능 |
| 실제 통화 상태 | CallKit의 상태는 별도 `CXCallObserver`로 수신 가능 |

#### CXCallObserver로 통화 상태 수신 (핵심 기능)

```swift
import CallKit

class CallStateMonitor: NSObject, CXCallObserverDelegate {
    let observer = CXCallObserver()
    var currentState = "idle"
    
    override init() {
        super.init()
        observer.setDelegate(self, queue: nil)
    }
    
    func callObserver(_ callObserver: CXCallObserver, callChanged call: CXCall) {
        if call.hasEnded { currentState = "ended" }
        else if call.isOutgoing && !call.hasConnected { currentState = "dialing" }
        else if call.hasConnected { currentState = "connected" }
        // Mac HTTP 서버에 상태 전송
        reportState(currentState)
    }
}
```

> **CXCallObserver는 다른 앱(ixiO)의 통화 상태도 읽을 수 있다** — ixiO 소스 수정 불필요

#### 평가
```
구현 복잡도: ★★★☆☆ (중간 — XCUITest + HTTP 서버 통합)  
안정성:     ★★★☆☆ (UI 변경에 취약, 그러나 현재 Appium보다 안정적)  
선행 조건:  ixiO 소스 접근 불필요 ← 최대 장점
통화 상태 수신: CXCallObserver로 가능
```

---

## 2. 방안 비교 요약

| 구분 | A. 내장 웹 서버 | B. URL Scheme | C. XCUITest Runner |
|------|----------------|---------------|-------------------|
| **ixiO 소스 수정** | 필수 | 필수 (최소) | 불필요 ✅ |
| **제어 깊이** | API 수준 (최고) | 파라미터 전달 | UI 수준 |
| **통화 상태 수신** | 직접 가능 | 어려움 | CXCallObserver ✅ |
| **iOS 백그라운드** | 15초 제한 (voip 권한으로 해결) | 앱 포그라운드 전환 | 포그라운드 유지 필요 |
| **Apple 서명 필요** | Enterprise/Ad Hoc | Enterprise/Ad Hoc | Development/Enterprise |
| **앱스토어 등록** | 불필요 | 불필요 | 불필요 |
| **구현 안정성** | 높음 | 보통 | 보통~높음 |
| **탈옥 필요** | 불필요 | 불필요 | 불필요 |

---

## 3. 현실적 추천 전략

### 조건 1: ixiO 내부 테스트 빌드 소스 접근 가능 → **방안 A**

내부 QA/개발팀과 협력하여 ixiO 테스트 빌드에 `TestControlServer` 모듈 추가.  
Enterprise 인증서로 서명 후 기기에 Ad Hoc 배포.  
현재 Appium 방식보다 훨씬 안정적이고, API 수준 제어가 가능해 테스트 정확도 향상.

```
추천도: ★★★★★ (가능하다면 최우선 선택)
```

### 조건 2: ixiO 소스 접근 불가 → **방안 C (XCUITest Runner) + 현재 방식 개선**

독립 Runner IPA를 개발해 ixiO 앱을 XCUITest로 제어 + CXCallObserver로 통화 상태 모니터링.  
현재 Appium 방식을 대체하는 자체 에이전트로 포지셔닝 가능.  
Appium 의존성 제거, WebDriverAgent 설치 불필요해짐.

```
추천도: ★★★★☆
```

### 방안 B는 단독 사용 비추천

URL Scheme만으로는 통화 상태 수신이 어렵고, 매 요청마다 앱 포그라운드 전환이 발생해 자동화 흐름이 불안정함. 방안 A 또는 C의 보조 수단(딥링크 트리거)으로만 활용 권장.

---

## 4. IPA 배포 방법 (공통)

어떤 방안을 선택하든 App Store 배포 없이 기기에 설치하는 방법:

| 방법 | 조건 | 기기 수 |
|------|------|---------|
| **Ad Hoc 배포** | Apple Developer 계정 ($99/년) + UDID 등록 | 최대 100대 |
| **Enterprise 배포** | Apple Developer Enterprise ($299/년) + 내부 사용 | 무제한 |
| **개발 기기 설치** | 같은 Apple ID로 로그인한 기기 | 무제한 (단, 7일마다 재서명) |
| **AltStore 방식** | 개인 Apple ID | 3개 앱 제한 |

**현재 플랫폼(내부 QA 전용)에서는 Ad Hoc 배포가 가장 적합.**

---

## 5. 현재 AudioAgent.swift 와의 관계

기존 `AudioAgent.swift`는 **오디오 재생 전용** 에이전트로, Mac → iPhone 방향으로만 명령을 받는다.  
본 문서에서 검토하는 방안은 **ixiO 앱 제어 전용** 에이전트로 별도 IPA로 개발하는 것이 적합하다.

```
기존: AudioAgent.app  → 음원 재생 전용
신규: iXiOController.app → 전화 걸기/받기/끊기 + 통화 상태 리포트
```

두 IPA를 하나로 합치는 것도 가능하나, 책임 분리 관점에서 분리 권장.

---

## 6. 결론

> **내부 ixiO 소스 접근 가능 여부가 핵심 갈림길이다.**

- 소스 접근 가능 → **방안 A**: Swifter 기반 HTTP 서버 내장, Mac에서 REST API 호출
- 소스 접근 불가 → **방안 C**: 자체 XCUITest Runner IPA + CXCallObserver 통화 상태 수신

두 방안 모두 **탈옥 불필요**, **내부 Wi-Fi 기반**, **Ad Hoc IPA 배포**로 현재 환경에서 즉시 적용 가능.  
개발 기간 예상: 방안 A는 약 1~2주, 방안 C는 약 2~3주.

---

## 참고 자료

- [Apple CallKit Documentation](https://developer.apple.com/documentation/callkit)
- [CXCallObserver — 다른 앱 통화 상태 관찰](https://developer.apple.com/documentation/callkit/cxcallobserver)
- [Swifter — Swift HTTP Server Library](https://github.com/httpswift/swifter)
- [XCUIApplication — 크로스 앱 UI 테스트](https://developer.apple.com/documentation/xctest/xcuiapplication)
- [Apple Enterprise Distribution](https://developer.apple.com/programs/enterprise/)
