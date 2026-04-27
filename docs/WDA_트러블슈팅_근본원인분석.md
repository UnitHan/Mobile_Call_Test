# WDA (WebDriverAgent) 트러블슈팅 근본원인 분석 및 대책

> 작성일: 2026-04-27  
> 대상 환경: Xcode 26.3 / iOS SDK 26.2 / iPhone 15 Plus (iOS 26.4)  
> 계정: SeongJun Choi (`35597M53Y5`) / Bundle: `com.jjun.1`

---

## 1. 발생했던 핵심 에러

```
*** Terminating app due to uncaught exception 'NSInternalInconsistencyException',
reason: 'Cannot initiate shared session more than once.'
```

이 에러는 **두 가지 완전히 다른 원인**으로 발생한다. 표면적인 메시지가 동일해 혼동하기 쉽다.

---

## 2. 원인 분석

### 원인 A: Xcode가 열려있어 DTX 세션 독점 (즉각 크래시)

| 항목 | 내용 |
|------|------|
| 증상 | xcodebuild 실행 1~2초 내에 즉시 크래시 |
| 원인 | Xcode.app이 실행 중이면 디바이스의 DTX(Device Tester eXecutor) 세션을 독점 |
| 확인 방법 | `ps aux \| grep "/Xcode.app/Contents/MacOS/Xcode"` |
| 해결 | `killall Xcode` 후 재시도 |

```bash
# 확인
ps aux | grep "/Xcode.app/Contents/MacOS/Xcode" | grep -v grep

# 해결
killall Xcode
sleep 3
```

### 원인 B: Python으로 직접 생성한 xctestrun 파일 (잘못된 포맷)

| 항목 | 내용 |
|------|------|
| 증상 | Xcode 없어도 동일 에러 발생, 에러 시점 동일 |
| 원인 | Python `plistlib`으로 생성한 xctestrun은 SDK 이름, 메타데이터 구조가 Xcode 실제 출력물과 다름 |
| 식별 방법 | 파일 크기 ≤ 2KB → Python 생성 (가짜). 실제 Xcode 생성물은 4KB 이상 |
| 해결 | `xcodebuild build-for-testing`으로 진짜 xctestrun 생성 |

**잘못된 Python 생성 xctestrun 예시** (1.8KB):
```
WebDriverAgentRunner_iphoneos18.xctestrun  ← SDK 이름 "iphoneos18" 자체가 틀림
```

**올바른 Xcode 생성 xctestrun 예시** (4.0KB):
```
WebDriverAgentRunner_iphoneos26.2-arm64.xctestrun  ← Xcode 버전에 맞는 이름
```

### 원인 C: `CODE_SIGN_STYLE=Manual` 사용 시 IntegrationApp 서명 불일치

`WebDriverAgent` 프로젝트는 `WebDriverAgentRunner`, `IntegrationApp`, `WebDriverAgentLib` 세 개의 Target을 포함한다. Manual 서명 시 각 Target마다 별도 프로파일이 필요하고, 특히 `WebDriverAgentLib`는 프로파일을 아예 지원하지 않는다.

```
error: Provisioning profile has app ID "...xctrunner",
       which does not match the bundle ID "com.jjun.1.IntegrationApp"
error: WebDriverAgentLib does not support provisioning profiles
```

**해결**: `CODE_SIGN_STYLE=Automatic`으로 전환하면 Xcode가 자동으로 각 Target에 맞는 프로파일을 선택.

---

## 3. 올바른 빌드 명령어

```bash
WDA_DIR=$(find ~/.appium -name "appium-webdriveragent" -maxdepth 8 -type d 2>/dev/null | head -1)
TEAM_ID="35597M53Y5"    # 본인 팀 ID로 교체

cd "$WDA_DIR"
xcodebuild build-for-testing \
  -project WebDriverAgent.xcodeproj \
  -scheme WebDriverAgentRunner \
  -destination "id=${UDID}" \
  -sdk iphoneos \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  CODE_SIGN_STYLE=Automatic \
  -allowProvisioningUpdates \
  ONLY_ACTIVE_ARCH=NO \
  2>&1 | grep -E "error:|TEST BUILD|FAILED|SUCCEEDED"
```

**핵심 포인트**:
- `-sdk iphoneos` (버전 없이): 현재 Xcode에 설치된 최신 SDK 자동 사용 → xctestrun 이름도 자동 맞춰짐
- `CODE_SIGN_STYLE=Automatic`: IntegrationApp, WebDriverAgentLib 각각 자동 서명
- `ONLY_ACTIVE_ARCH=NO`: arm64/arm64e 모두 빌드 (멀티 아키텍처 디바이스 대응)

---

## 4. xctestrun 파일 유효성 판별

```bash
# 유효한 xctestrun 찾기 (크기 2KB 초과 = Xcode 생성 정품)
find ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*/Build/Products \
  -name "*.xctestrun" 2>/dev/null \
| while IFS= read -r f; do
    sz=$(stat -f%z "$f")
    echo "$sz  $f"
  done | sort -rn | head -5

# 내용 확인 (진짜라면 ContainerInfo, BlueprintProviderName 등이 있어야 함)
plutil -p <파일경로> | head -15
```

| 파일 크기 | 판정 | 비고 |
|-----------|------|------|
| ≤ 2KB | ❌ Python 생성 (가짜) | `Cannot initiate shared session` 에러 |
| 4KB 이상 | ✅ Xcode 생성 (정품) | 정상 작동 |

---

## 5. 새 단말기 연결 시 100% 호환 체크리스트

새 iPhone을 처음 연결할 때 반드시 아래 순서로 확인한다.

### Step 1: 디바이스 인식 확인

```bash
# USB 연결 후 신뢰 팝업에서 "신뢰" 탭
idevice_id -l
# 출력 예: 00008120-000215420102201E

# 기기명 및 iOS 버전 확인
ideviceinfo -u <UDID> --key DeviceName
ideviceinfo -u <UDID> --key ProductVersion
```

### Step 2: 배포 타겟 패치 (신규 Xcode/appium 업데이트 후 필요)

```bash
WDA_DIR=$(find ~/.appium -name "appium-webdriveragent" -maxdepth 8 -type d | head -1)
PBXPROJ="$WDA_DIR/WebDriverAgent.xcodeproj/project.pbxproj"

# iOS 20+ 배포 타겟이 있으면 16.0으로 패치
grep "IPHONEOS_DEPLOYMENT_TARGET = 2[0-9]" "$PBXPROJ" && \
  sed -i '' 's/IPHONEOS_DEPLOYMENT_TARGET = 2[0-9]\.[0-9]*;/IPHONEOS_DEPLOYMENT_TARGET = 16.0;/g' "$PBXPROJ" && \
  echo "패치 완료" || echo "패치 불필요"
```

> **이유**: appium-webdriveragent가 Xcode 26.x SDK 기준으로 배포 타겟을 설정하는 경우가 있어, iOS 18 이하 기기에서 실행 불가. 16.0으로 낮추면 모든 기기 호환.

### Step 3: Xcode 종료 확인

```bash
# Xcode가 열려있으면 반드시 종료
if pgrep -x "Xcode" > /dev/null; then
    echo "Xcode 실행 중 → 종료"
    killall Xcode
    sleep 3
fi
```

### Step 4: 기존 xctestrun 유효성 확인 (2KB 초과 여부)

```bash
XCTESTRUN=$(find ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*/Build/Products \
  -name "*.xctestrun" 2>/dev/null | head -1)

if [[ -n "$XCTESTRUN" ]]; then
    sz=$(stat -f%z "$XCTESTRUN")
    echo "xctestrun 크기: ${sz} bytes"
    [[ $sz -le 2000 ]] && echo "❌ 가짜 파일 - build-for-testing 필요" || echo "✅ 유효함"
fi
```

### Step 5: xctestrun이 없거나 무효이면 빌드

```bash
xcodebuild build-for-testing \
  -project "$WDA_DIR/WebDriverAgent.xcodeproj" \
  -scheme WebDriverAgentRunner \
  -destination "id=${UDID}" \
  -sdk iphoneos \
  DEVELOPMENT_TEAM="35597M53Y5" \
  CODE_SIGN_STYLE=Automatic \
  -allowProvisioningUpdates \
  ONLY_ACTIVE_ARCH=NO
```

### Step 6: IPA 설치

```bash
XCTESTRUN=$(find ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*/Build/Products \
  -name "*.xctestrun" 2>/dev/null | xargs ls -t 2>/dev/null | head -1)
PRODUCTS_DIR=$(dirname "$XCTESTRUN")
APP_PATH="$PRODUCTS_DIR/Debug-iphoneos/WebDriverAgentRunner-Runner.app"

mkdir -p /tmp/wda_ipa/Payload
cp -R "$APP_PATH" /tmp/wda_ipa/Payload/
cd /tmp/wda_ipa && zip -qr WDA.ipa Payload/

xcrun devicectl device install app --device "$UDID" /tmp/wda_ipa/WDA.ipa
```

### Step 7: WDA 실행

```bash
# 기존 프로세스 정리
pkill -f "xcodebuild.*xctestrun" 2>/dev/null
killall iproxy 2>/dev/null
sleep 2

# 포트포워딩 + WDA 실행
iproxy 8100 8100 --udid "$UDID" >/dev/null 2>&1 &
xcodebuild test-without-building \
  -xctestrun "$XCTESTRUN" \
  -destination "id=${UDID}" \
  >/tmp/wda.log 2>&1 &

# 응답 확인 (최대 60초)
for i in $(seq 1 60); do
  curl -s --max-time 2 "http://localhost:8100/status" | grep -q '"build"' && \
    echo "WDA 기동 성공 (${i}초)" && break
  sleep 1
done

# Wi-Fi IP 확인
grep "ServerURLHere" /tmp/wda.log | head -1
```

---

## 6. 새 맥북 이전 시 전체 절차

### 방법 A: DerivedData 복사 (빠름, 동일 Apple ID 필요)

```bash
# [이전 맥북] 빌드 결과물 압축
DERIVED=$(find ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-* -maxdepth 0 -type d | head -1)
tar -czf /tmp/wda_build.tar.gz \
  "$DERIVED/Build/Products/Debug-iphoneos/" \
  "$DERIVED/Build/Products/"*iphoneos*.xctestrun

# [새 맥북] 복원
mkdir -p "$DERIVED/Build/Products"
tar -xzf /tmp/wda_build.tar.gz -C "$DERIVED/Build/Products/"
```

> ⚠️ 코드 서명이 이전 맥북의 인증서로 되어 있어, **새 맥북에 동일 Apple ID**가 Xcode에 등록되어 있어야 함.  
> 서명이 맞지 않으면 방법 B로 재빌드 필요.

### 방법 B: 새 맥북에서 직접 빌드 (권장)

1. **필수 도구 설치**:
   ```bash
   brew install libimobiledevice ideviceinstaller
   npm install -g appium && appium driver install xcuitest
   ```

2. **Apple ID Xcode 등록**: `Xcode > Settings > Accounts` → Apple ID 추가 → `Manage Certificates` → `Apple Development` 생성

3. **setup_wda_iphone.sh 실행**:
   ```bash
   chmod +x setup_wda_iphone.sh
   ./setup_wda_iphone.sh
   ```
   스크립트가 자동으로 배포 타겟 패치 → build-for-testing → IPA 설치 → WDA 기동 수행.

---

## 7. 환경별 설정값 (스크립트 상단 변경)

| 항목 | 이 맥북 값 | 새 맥북 적용 시 |
|------|-----------|----------------|
| `TEAM_ID` | `35597M53Y5` | 동일 Apple ID이면 동일값 유지 |
| `BUNDLE_PREFIX` | `com.jjun.1` | 동일 |
| `WDA_PORT` | `8100` | 동일 |
| xctestrun 이름 | `WebDriverAgentRunner_iphoneos26.2-arm64.xctestrun` | Xcode 버전에 따라 자동 변경됨 (스크립트가 자동 탐색) |
| WDA Wi-Fi IP | `192.168.219.126` | 네트워크 변경 시 재확인 필요 (`grep ServerURLHere /tmp/wda_*.log`) |

---

## 8. 자주 발생하는 에러 빠른 참조

| 에러 | 원인 | 해결 |
|------|------|------|
| `Cannot initiate shared session more than once` | Xcode 실행 중 or Python 생성 xctestrun | `killall Xcode` → `build-for-testing` 재실행 |
| `No Account for Team` | Xcode에 Apple ID 미등록 | `Xcode > Settings > Accounts` 등록 |
| `Provisioning profile does not match bundle ID` | `CODE_SIGN_STYLE=Manual` 사용 | `CODE_SIGN_STYLE=Automatic`으로 변경 |
| `WebDriverAgentLib does not support provisioning profiles` | Manual 서명 시 프레임워크에 프로파일 지정 | `CODE_SIGN_STYLE=Automatic`으로 변경 |
| `xctestrun platform mismatch` | 배포 타겟 미패치 | pbxproj 패치 후 재빌드 |
| WDA 설치 후 응답 없음 | iproxy 미실행 or 포트 충돌 | `killall iproxy && iproxy 8100 8100 --udid $UDID &` |
| WDA URL localhost 응답, IP 응답 없음 | Wi-Fi 미연결 or 다른 네트워크 | 로그에서 `ServerURLHere` IP 확인 후 직접 사용 |

---

## 9. 현재 구축된 자동화 스크립트 동작 요약

`setup_wda_iphone.sh` 실행 시 자동 수행 순서:

1. **STEP 1** — iPhone UDID 자동 감지, WDA 이미 실행 중이면 즉시 종료
2. **STEP 2** — appium WDA 소스 경로 확인 (없으면 자동 설치)
3. **STEP 3** — pbxproj 배포 타겟 iOS 26.x → 16.0 패치
4. **STEP 4** — 유효한 xctestrun(>2KB) 탐색 → 없으면 `build-for-testing` 자동 실행
5. **STEP 5** — DerivedData에서 .app 추출 → IPA 생성 → 디바이스 설치
6. **STEP 6** — 기존 WDA 프로세스 정리 → iproxy 포트포워딩 → `test-without-building` 실행 → 응답 확인

**완전 단독 실행 가능** (Xcode GUI 불필요, 초기 1회 빌드 후 xctestrun 재사용).
