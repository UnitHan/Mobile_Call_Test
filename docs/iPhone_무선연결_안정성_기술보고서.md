# iPhone 무선 연결 안정성 기술 보고서

> 작성일: 2026-04-16  
> 환경: macOS + Xcode + pymobiledevice3 tunneld + Appium XCUITest  
> 대상 기기: iPhone 17 Pro (iOS 26.2.1, 23C71)

---

## 1. 현상

Xcode 무선 디버깅 중 **"An error occurred while communicating with a remote process"** 에러 발생.  
WDA(WebDriverAgent) 세션이 끊기면서 자동화 테스트가 중단됨.

tunneld 에러 로그:
```
WARNING got OSError in sock-read-task-fd8e:ebf9:4b31::2
INFO Disconnected from tunnel --rsd fd8e:ebf9:4b31::1 63846
```

USB 연결 시에도 tunnel 생성 → 7~13초 후 Disconnect가 반복되는 패턴 확인:
```
10:46:53 Created tunnel --rsd fdec:c9e6:13df::1 63852
10:47:00 Disconnected from tunnel (7초)
10:47:25 Created tunnel --rsd fde2:ab06:f2fc::1 63855
10:47:31 Disconnected from tunnel (6초)
10:47:38 Created tunnel --rsd fd07:cf01:c32::1 63860
10:47:47 Disconnected from tunnel (9초)
```

---

## 2. 원인 분석

### 2.1 끊김 원인 분류

| 원인 | 빈도 | 설명 |
|------|------|------|
| **Wi-Fi 불안정** | 높음 | 동일 AP에서 간헐적 패킷 유실, DHCP 갱신 시 IP 변경 |
| **iPhone 절전** | 높음 | 화면 꺼짐 후 Wi-Fi 저전력 모드 진입 → 연결 타임아웃 |
| **tunneld 세션 만료** | 중간 | IPv6 tunnel 유지 실패 (OSError in sock-read-task) |
| **Xcode Preparing 루프** | 중간 | 기기 준비 과정에서 개발자 디스크 이미지/심볼 불일치 |
| **WDA 30분 제한** | 낮음 | Xcode로 실행한 WDA가 30분 후 자동 종료 |
| **mDNS 해석 실패** | 낮음 | `.local` 호스트명 → IP 해석 지연/실패 |

### 2.2 "Preparing" 무한 루프

Xcode Window → Devices에서 "Preparing 품질프로페션의 iPhone" 상태가 지속되는 경우:

- **원인**: Xcode가 기기의 Developer Disk Image 또는 Debug Symbols를 다운로드/설치 중
- iOS 26.x 신규 버전은 Xcode가 Apple 서버에서 심볼을 다운로드해야 함
- 네트워크 불안정 시 다운로드 반복 실패 → Preparing 무한 루프

---

## 3. 해결 방안

### 3.1 즉시 적용 가능 (소프트웨어)

#### A. iPhone Wi-Fi 절전 차단

| 설정 경로 | 값 | 효과 |
|-----------|-----|------|
| 설정 → 디스플레이 → 자동 잠금 | **안 함** | 화면 상시 켜짐 → Wi-Fi 풀파워 유지 |
| 설정 → 배터리 → 저전력 모드 | **끔** | Wi-Fi 절전 방지 |
| 설정 → Wi-Fi → (i) → 개인정보 보호 주소 | **끔** | MAC 주소 고정 → DHCP lease 안정 |
| 설정 → Wi-Fi → (i) → IP 구성 → 수동 | **고정 IP 설정** | DHCP 갱신 시 IP 변경 방지 |

> **권장 고정 IP 설정**:
> - IP: 192.168.219.110
> - 서브넷: 255.255.255.0
> - 라우터: 192.168.219.1
> - DNS: 192.168.219.1 (또는 8.8.8.8)

#### B. Mac 측 네트워크 최적화

```bash
# Wi-Fi 전원 관리 비활성화 (인터페이스별)
sudo /usr/libexec/airportd prefs DisableJoinPrompt=YES

# mDNS 캐시 플러시 (연결 불안정 시)
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```

#### C. tunneld 안정화

현재 `com.qabulls.pymobiledevice3.tunneld.plist`:
- `KeepAlive=true` → 크래시 시 자동 재시작 ✅
- `ThrottleInterval=5` → 재시작 간격 5초 ✅

**추가 권장 설정**:
```xml
<!-- 연결 실패 시 재시도 횟수 증가를 위한 환경변수 -->
<key>EnvironmentVariables</key>
<dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
</dict>
```

**tunneld 수동 재시작** (연결 끊김 시):
```bash
# 방법 1: launchctl (LaunchDaemon 등록 시)
sudo launchctl kickstart -k system/com.qabulls.pymobiledevice3.tunneld

# 방법 2: 직접 실행 (디버깅용)
sudo /Users/qabulls/Documents/sound/.venv/bin/pymobiledevice3 remote tunneld
```

#### D. WDA 연결 유지 강화

Appium capabilities에 아래 설정 추가:

```python
# WDA 연결 타임아웃 확장 (기본 300초 → 3600초)
'appium:wdaConnectionTimeout': 3600000,

# WDA 시작 타임아웃
'appium:wdaStartupTimeout': 120000,

# 재연결 시도 (세션 유지)
'appium:wdaStartupRetries': 5,
'appium:wdaStartupRetryInterval': 20000,

# Xcode WDA 재기동 방지 (기존 세션 재사용)
'appium:webDriverAgentUrl': 'http://192.168.219.110:8100',
'appium:noReset': True,
'appium:waitForQuiescence': False,
```

#### E. Xcode "Preparing" 해결

```bash
# 1. 기존 기기 지원 파일 삭제
rm -rf ~/Library/Developer/Xcode/iOS\ DeviceSupport/*

# 2. Xcode DerivedData 정리
rm -rf ~/Library/Developer/Xcode/DerivedData/*

# 3. Xcode 재실행 → 기기 재연결 (USB로 1회)
#    Preparing 완료 후 Wi-Fi 전환
```

**또는 devicectl로 우회**:
```bash
# Xcode 없이 직접 기기 상태 확인
xcrun devicectl list devices --json-output /tmp/devices.json
python3 -c "import json; d=json.load(open('/tmp/devices.json')); print(json.dumps(d, indent=2))"
```

---

### 3.2 중기 적용 (아키텍처 개선)

#### F. 자동 재연결 스크립트 (테스트 앱 연동)

현재 `device_cmd.rs`에서 `check_iphone_connection()`이 `tunnelState=='connected'`를 확인합니다.  
여기에 **자동 복구 로직**을 추가할 수 있습니다:

```
[개선 플로우]
테스트 실행 중 WDA 응답 없음 감지
  ↓
1. WDA /status 체크 (3초 타임아웃)
  ↓ (실패)
2. tunneld 재시작 (launchctl kickstart)
  ↓ (10초 대기)
3. WDA /status 재체크
  ↓ (실패)
4. mDNS로 iPhone IP 재조회
  ↓
5. 새 IP로 WDA 연결 시도
  ↓ (성공)
6. Appium 세션 재생성 → 테스트 이어서 실행
```

#### G. USB 폴백 하이브리드 구성

무선 연결 실패 시 USB로 자동 전환:

| 우선순위 | 연결 방식 | 감지 방법 |
|---------|-----------|-----------|
| 1 | Wi-Fi (localNetwork) | `transportType=='localNetwork'` + tunnelState |
| 2 | USB (wired) | `transportType=='wired'` |
| 3 | USB via pymobiledevice3 | `idevice_id -l` |

---

### 3.3 하드웨어/인프라 (장기)

#### H. 전용 네트워크 환경

| 항목 | 현재 | 권장 |
|------|------|------|
| Wi-Fi AP | 가정/사무용 공유기 | **전용 5GHz AP** (테스트 기기만 연결) |
| 대역 | 2.4GHz/5GHz 혼합 | **5GHz 고정** (간섭 최소화) |
| DHCP | 동적 | **고정 IP 예약** (MAC 기반) |
| 거리 | 변동 | **AP와 1m 이내** |

#### I. USB 허브 기반 안정 구성 (권장)

무선 연결의 근본적 불안정성을 피하려면:

```
Mac ── USB-C Hub ─┬── iPhone (Lightning/USB-C)
                   └── Android (USB-C)
```

- **장점**: 연결 끊김 확률 거의 0%, 전원 공급 동시 해결
- **단점**: 물리적 배선 필요, 원격 관리 제한

> 현실적 권장: **USB 기본 + Wi-Fi 보조 (폴백)**

---

## 4. 현재 시스템 안정화 체크리스트

| # | 항목 | 상태 | 조치 |
|---|------|------|------|
| 1 | iPhone 자동 잠금 = 안 함 | ⬜ 확인 필요 | 설정 → 디스플레이 |
| 2 | 저전력 모드 끔 | ⬜ 확인 필요 | 설정 → 배터리 |
| 3 | 개인정보 보호 주소 끔 | ⬜ 확인 필요 | 설정 → Wi-Fi → (i) |
| 4 | iPhone 고정 IP 설정 | ⬜ 확인 필요 | 192.168.219.110 |
| 5 | tunneld KeepAlive 동작 | ✅ | plist 설정 확인됨 |
| 6 | WDA wdaConnectionTimeout | ⬜ 확인 필요 | 3600000ms 설정 |
| 7 | Xcode DeviceSupport 최신 | ⬜ 확인 필요 | Preparing 루프 해결 |
| 8 | Wi-Fi 5GHz 고정 | ⬜ 확인 필요 | AP 설정 |

---

## 5. 결론

| 방안 | 효과 | 난이도 | 우선순위 |
|------|------|--------|---------|
| iPhone 절전/IP 고정 (A) | ★★★★ | 낮음 | **즉시** |
| WDA 타임아웃 확장 (D) | ★★★ | 낮음 | **즉시** |
| Xcode Preparing 해결 (E) | ★★★★ | 낮음 | **즉시** |
| tunneld 환경변수 추가 (C) | ★★ | 낮음 | 이번 주 |
| 자동 재연결 로직 (F) | ★★★★★ | 중간 | 다음 스프린트 |
| USB 폴백 하이브리드 (G) | ★★★★ | 중간 | 다음 스프린트 |
| 전용 5GHz AP (H) | ★★★★ | 높음 (비용) | 장기 |
| USB 기본 구성 (I) | ★★★★★ | 낮음 | **권장 기본값** |

**최종 권장**: 일상 테스트는 **USB 기본 연결** + tunneld 자동 복구로 운영.  
원격/무인 테스트 시에만 Wi-Fi 구성 사용 (고정 IP + 절전 해제 + WDA 타임아웃 확장 필수).
