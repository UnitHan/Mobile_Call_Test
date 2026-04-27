# iPhone 14 #2 WDA 셋업 가이드 (다른 맥북 이전용)

> 작성일: 2026-04-23  
> 대상 기기: ixi-O 테스트용 iPhone 14 #2 (`00008110-001915E00E23A01E`, iOS 18.1)  
> 서명 계정: seyong park (`J845P53DFM`)  
> WDA Bundle ID: `com.seyong.1.WebDriverAgentRunner.xctrunner`

---

## 0. 원클릭 자동 스크립트 (권장)

iPhone을 USB로 연결한 뒤 아래 스크립트 하나로 **빌드 → IPA 설치 → WDA 실행**까지 자동 수행됩니다.

```bash
# 스크립트 복사 후 실행 (새 맥북에서)
chmod +x setup_wda_iphone.sh
./setup_wda_iphone.sh
```

스크립트 위치: `sound/setup_wda_iphone.sh`  
설정값 (스크립트 상단에서 변경 가능):

| 항목 | 기본값 |
|------|--------|
| `TEAM_ID` | `J845P53DFM` (seyong park) |
| `BUNDLE_PREFIX` | `com.seyong.1` |
| `WDA_PORT` | `8100` |

> 스크립트가 iPhone UDID를 자동 감지하므로 기기가 바뀌어도 재사용 가능합니다.

---

## 1. 사전 준비 (새 맥북)

### 1-1. Xcode 설치

```bash
# App Store에서 Xcode 설치 후 Command Line Tools 세팅
xcode-select --install
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

### 1-2. 필수 도구 설치

```bash
# Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 필수 패키지
brew install node python@3.10 libimobiledevice ideviceinstaller

# appium + xcuitest-driver
npm install -g appium
appium driver install xcuitest
```

### 1-3. Apple 개발자 계정 등록

1. Xcode 실행 → `Xcode > Settings > Accounts`
2. `+` 버튼 → Apple ID 로그인
3. **Team**: `seyong park (J845P53DFM)` 계정 추가
4. `Manage Certificates` → `+` → `Apple Development` 인증서 생성

---

## 2. WDA 소스 준비 (두 가지 방법 중 선택)

### 방법 A: 이전 맥북에서 빌드 결과물 복사 (권장 - 빠름)

이전 맥북에서 DerivedData 폴더를 통째로 복사합니다.

```bash
# [이전 맥북] 복사할 파일 압축
DERIVED="/Users/qabulls/Library/Developer/Xcode/DerivedData/WebDriverAgent-cwvlifwmrcvajlcmhcqhslwwurdz"
tar -czf /tmp/wda14_build.tar.gz \
  "$DERIVED/Build/Products/Debug-iphoneos/" \
  "$DERIVED/Build/Products/WebDriverAgentRunner_iphoneos26.2-arm64.xctestrun"

# 파일 크기 확인
du -sh /tmp/wda14_build.tar.gz
```

```bash
# [이전 맥북] AirDrop 또는 scp로 전송
scp /tmp/wda14_build.tar.gz 새맥북IP:/tmp/
```

```bash
# [새 맥북] 압축 해제
mkdir -p ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-cwvlifwmrcvajlcmhcqhslwwurdz/Build/Products
tar -xzf /tmp/wda14_build.tar.gz -C ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-cwvlifwmrcvajlcmhcqhslwwurdz/Build/Products/
```

> ⚠️ 코드 서명이 `seyong park` 계정으로 되어 있으므로, **새 맥북에도 동일 Apple ID가 로그인된 Xcode**가 있어야 합니다.

---

### 방법 B: 새 맥북에서 직접 빌드 (WDA 소스 패치 포함)

#### B-1. appium WDA 소스 위치 확인

```bash
WDA_DIR=$(find ~/.appium -name "appium-webdriveragent" -maxdepth 6 -type d 2>/dev/null | head -1)
echo "WDA 소스: $WDA_DIR"
# 예: ~/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent
```

#### B-2. 배포 타겟 패치 (iOS 18.1 호환)

> appium WDA 기본 배포 타겟이 iOS 26.x 이상으로 설정되어 있어, iOS 18.1 기기에서 실행 불가. 반드시 패치 필요.

```bash
cd "$WDA_DIR"

# 백업
cp WebDriverAgent.xcodeproj/project.pbxproj WebDriverAgent.xcodeproj/project.pbxproj.bak

# 배포 타겟을 16.0으로 낮추기 (iOS 18.1 기기 호환)
sed -i '' 's/IPHONEOS_DEPLOYMENT_TARGET = 2[0-9]\.[0-9];/IPHONEOS_DEPLOYMENT_TARGET = 16.0;/g' \
  WebDriverAgent.xcodeproj/project.pbxproj

# 패치 결과 확인 (16.0, 12.0, 17.6만 있으면 정상)
grep "IPHONEOS_DEPLOYMENT_TARGET" WebDriverAgent.xcodeproj/project.pbxproj | sort -u
```

#### B-3. Xcode에서 Build For Testing

1. Xcode에서 `$WDA_DIR/WebDriverAgent.xcodeproj` 열기
2. 상단 Scheme: `WebDriverAgentRunner` 선택
3. Destination: **ixi-O 테스트용 iPhone 14 #2** 선택
4. 각 Target(`WebDriverAgentLib`, `WebDriverAgentRunner`, `WebDriverAgentRunner_tvOS` 등) → `Signing & Capabilities` → Team: **seyong park** 선택
5. `Product > Build For > Testing` (단축키: `Cmd+Shift+U`)
6. 빌드 성공 후 xctestrun 파일 생성 확인:

```bash
find ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*/Build/Products -name "*.xctestrun" 2>/dev/null
```

---

## 3. iPhone 14 #2 연결 및 신뢰 설정

```bash
# USB 연결 후 기기 인식 확인
idevice_id -l
# 출력 예: 00008110-001915E00E23A01E

# 또는 devicectl 사용
xcrun devicectl list devices 2>/dev/null | grep "14"
```

> iPhone 화면에 **"이 컴퓨터를 신뢰하겠습니까?"** 팝업이 뜨면 **신뢰** 탭 필요.

---

## 4. WDA 실행

### 4-1. xctestrun 경로 확인

```bash
XCTESTRUN=$(find ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*/Build/Products \
  -name "*iphoneos*.xctestrun" 2>/dev/null | head -1)
echo "xctestrun: $XCTESTRUN"
```

### 4-2. WDA 기동

```bash
# 백그라운드 실행
xcodebuild test-without-building \
  -xctestrun "$XCTESTRUN" \
  -destination "id=00008110-001915E00E23A01E" > /tmp/wda14.log 2>&1 &

echo "WDA 로그: tail -f /tmp/wda14.log"
```

### 4-3. WDA URL 확인 (IP 및 포트)

```bash
# 로그에서 URL 추출
grep "ServerURLHere" /tmp/wda14.log
# 예: ServerURLHere->http://192.168.219.148:8100<-ServerURLHere

# 또는 응답 확인
curl -s http://192.168.219.148:8100/status | python3 -m json.tool | grep -E "ready|ip"
```

> 기본 포트는 **8100**. 포트가 다를 경우 아래 섹션 참조.

---

## 5. 스크립트 설정 업데이트

WDA IP와 포트를 확인한 후 `diag_tc02_call.py`의 WDA_URL을 업데이트합니다.

```python
# diag_tc02_call.py 상단 설정
WDA_URL = "http://192.168.219.148:8100"   # ← 새 IP로 변경
```

---

## 6. 트러블슈팅

### WDA가 응답 없을 때

```bash
# iPhone에 WDA 앱이 설치됐는지 확인
xcrun devicectl device info apps --device 00008110-001915E00E23A01E 2>/dev/null \
  | grep -i "webdriver\|xctrunner"

# WDA 프로세스가 iPhone에서 실행 중인지 확인
xcrun devicectl device process list --device 00008110-001915E00E23A01E 2>/dev/null \
  | grep -i "xctrunner"

# iPhone IP 재확인 (네트워크 변경 시)
dns-sd -G v4 ixi-O-teseuteuyong-iPhone-14-2.local &
sleep 3; kill %1 2>/dev/null
```

### "xctestrun platform mismatch" 에러

배포 타겟 패치가 안 된 경우. `방법 B-2` 패치를 다시 적용하고 `Cmd+Shift+K` (Clean) 후 `Cmd+Shift+U` (Build For Testing) 재실행.

### "이 맥에서 실행 불가 (코드서명 불일치)"

새 맥북에 `seyong park (J845P53DFM)` Apple ID가 Xcode에 등록되어 있지 않은 경우. 섹션 1-3 참조.

### 방법 A(복사)로 왔는데 서명 오류 발생 시

새 맥북에서 방법 B로 재빌드 필요. seyong park Apple ID로 새 맥북에서 직접 서명해야 함.

---

## 7. 기기 정보 요약

| 항목 | 값 |
|------|-----|
| 기기명 | ixi-O 테스트용 iPhone 14 #2 |
| UDID | `00008110-001915E00E23A01E` |
| iOS 버전 | 18.1 |
| Wi-Fi IP | `192.168.219.148` (유동 - 재확인 필요) |
| WDA 포트 | `8100` |
| WDA Bundle ID | `com.seyong.1.WebDriverAgentRunner.xctrunner` |
| Apple 개발자 팀 | seyong park (`J845P53DFM`) |
| WDA DerivedData | `WebDriverAgent-cwvlifwmrcvajlcmhcqhslwwurdz` |
