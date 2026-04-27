#!/bin/bash
# ============================================================
# WDA 설치 및 실행 스크립트 (새 맥북 / 새 iPhone 연결용)
# 계정: SeongJun Choi (Personal Team) - Team ID: 35597M53Y5
# Bundle prefix: com.jjun.1
# ============================================================
set -euo pipefail

# ──────────────────────────────────────────

WDA_PORT="${WDA_PORT:-8100}"
TEAM_ID="35597M53Y5"
BUNDLE_PREFIX="com.jjun.1"
WDA_DIR=$(find ~/.appium -name "appium-webdriveragent" -maxdepth 8 -type d 2>/dev/null | head -1)

# ──────────────────────────────────────────
# 색상 출력 헬퍼
# ──────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
die()  { echo -e "${RED}❌ $*${NC}"; exit 1; }

# ──────────────────────────────────────────
# 1. iPhone UDID 자동 감지
# ──────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo " STEP 1: iPhone 연결 확인"
echo "══════════════════════════════════════════════"

UDID=$(idevice_id -l 2>/dev/null | head -1)
if [[ -z "$UDID" ]]; then
    die "연결된 iPhone이 없습니다. USB로 연결 후 '이 컴퓨터를 신뢰' 탭하세요."
fi
ok "iPhone UDID: $UDID"

# 기기 이름/iOS 버전 출력
DEVICE_NAME=$(ideviceinfo -u "$UDID" --key DeviceName 2>/dev/null || echo "Unknown")
IOS_VER=$(ideviceinfo -u "$UDID" --key ProductVersion 2>/dev/null || echo "Unknown")
ok "기기명: $DEVICE_NAME  /  iOS: $IOS_VER"

# ── WDA 이미 실행 중인지 확인 (iproxy 로 포트포워딩 후 /status 호출) ──
echo "WDA 이미 실행 중인지 확인 중..."
iproxy "$WDA_PORT" "$WDA_PORT" --udid "$UDID" > /dev/null 2>&1 &
IPROXY_CHECK_PID=$!
sleep 1
WDA_STATUS=$(curl -s --max-time 4 "http://localhost:${WDA_PORT}/status" 2>/dev/null || true)
if echo "$WDA_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['value']['build']['version'])" 2>/dev/null | grep -q .; then
    WDA_VER=$(echo "$WDA_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['value']['build']['version'])" 2>/dev/null)
    ok "WDA 이미 실행 중 (버전: $WDA_VER) → 포트 $WDA_PORT"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  WDA_URL = http://localhost:${WDA_PORT}"
    echo "  iproxy PID: $IPROXY_CHECK_PID (포트포워딩 유지 중)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    ok "모든 단계 완료 (이미 실행 중)"
    exit 0
fi
kill $IPROXY_CHECK_PID 2>/dev/null || true

# ──────────────────────────────────────────
# 2. WDA 소스 확인
# ──────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo " STEP 2: WDA 소스 확인"
echo "══════════════════════════════════════════════"

if [[ -z "$WDA_DIR" ]]; then
    warn "appium-webdriveragent를 찾을 수 없습니다. appium 설치 시도..."
    npm install -g appium 2>&1 | tail -3
    appium driver install xcuitest 2>&1 | tail -3
    WDA_DIR=$(find ~/.appium -name "appium-webdriveragent" -maxdepth 8 -type d 2>/dev/null | head -1)
    [[ -z "$WDA_DIR" ]] && die "WDA 소스를 찾을 수 없습니다."
fi
ok "WDA 소스: $WDA_DIR"

# ──────────────────────────────────────────
# 3. pbxproj 배포 타겟 패치 (iOS 16.0 이상 호환)
# ──────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo " STEP 3: 배포 타겟 패치 (iOS 26.x → 16.0)"
echo "══════════════════════════════════════════════"

PBXPROJ="$WDA_DIR/WebDriverAgent.xcodeproj/project.pbxproj"
CURRENT_TARGET=$(grep "IPHONEOS_DEPLOYMENT_TARGET" "$PBXPROJ" 2>/dev/null | grep -E "2[0-9]\." | head -1 || echo "")

if [[ -n "$CURRENT_TARGET" ]]; then
    warn "배포 타겟에 iOS 20+ 값 발견 → 16.0으로 패치"
    cp "$PBXPROJ" "$PBXPROJ.bak"
    sed -i '' 's/IPHONEOS_DEPLOYMENT_TARGET = 2[0-9]\.[0-9]*;/IPHONEOS_DEPLOYMENT_TARGET = 16.0;/g' "$PBXPROJ"
    ok "패치 완료 (백업: project.pbxproj.bak)"
else
    ok "배포 타겟 패치 불필요 (이미 16.0 이하)"
fi

# ──────────────────────────────────────────
# 4. xctestrun 확인 / build-for-testing
# ──────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo " STEP 4: xctestrun 확인 / 빌드"
echo "══════════════════════════════════════════════"

# 유효한 xctestrun = Xcode가 생성한 것 (파일 크기 > 2KB)
_find_valid_xctestrun() {
    find ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*/Build/Products \
        -name "*.xctestrun" 2>/dev/null \
    | while IFS= read -r f; do
        sz=$(stat -f%z "$f" 2>/dev/null || echo 0)
        [[ $sz -gt 2000 ]] && echo "$f"
    done | xargs ls -t 2>/dev/null | head -1 || true
}

XCTESTRUN=$(_find_valid_xctestrun)

if [[ -n "$XCTESTRUN" ]]; then
    ok "기존 xctestrun 재사용: $(basename "$XCTESTRUN")"
else
    warn "유효한 xctestrun 없음 → build-for-testing 실행 (Team: $TEAM_ID, Automatic 서명)"
    BFT_LOG="/tmp/wda_bft_$(date +%s).log"
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
        2>&1 | tee "$BFT_LOG" | grep -E "error:|TEST BUILD|FAILED|SUCCEED" | tail -5
    cd - > /dev/null

    XCTESTRUN=$(_find_valid_xctestrun)
    [[ -z "$XCTESTRUN" ]] && die "build-for-testing 실패. 로그 확인: $BFT_LOG"
    ok "xctestrun 생성: $(basename "$XCTESTRUN")"
fi

# ──────────────────────────────────────────
# 5. IPA 설치
# ──────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo " STEP 5: IPA 설치"
echo "══════════════════════════════════════════════"

PRODUCTS_DIR=$(dirname "$XCTESTRUN")
APP_PATH="$PRODUCTS_DIR/Debug-iphoneos/WebDriverAgentRunner-Runner.app"

if [[ -d "$APP_PATH" ]]; then
    IPA_DIR="/tmp/wda_ipa_$(date +%s)"
    mkdir -p "$IPA_DIR/Payload"
    cp -R "$APP_PATH" "$IPA_DIR/Payload/"
    cd "$IPA_DIR"
    zip -qr WDA.ipa Payload/ --exclude "*.DS_Store"
    ok "IPA 생성: $(du -sh WDA.ipa | cut -f1)"
    echo "iPhone에 WDA 설치 중..."
    xcrun devicectl device install app --device "$UDID" "$IPA_DIR/WDA.ipa" 2>&1 | tail -3 \
        && ok "WDA 설치 완료" \
        || warn "설치 실패 (무시하고 계속 - 이미 설치된 경우 정상)"
    cd - > /dev/null
else
    warn ".app 파일 없음 ($APP_PATH) - 설치 건너뜀"
fi

# ──────────────────────────────────────────
# 6. WDA 실행
# ──────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo " STEP 6: WDA 실행"
echo "══════════════════════════════════════════════"

# 기존 WDA 프로세스 완전 종료 (Cannot initiate shared session more than once 방지)
echo "기존 WDA 프로세스 종료 중..."
xcrun devicectl device process terminate \
    --device "$UDID" "${BUNDLE_PREFIX}.WebDriverAgentRunner.xctrunner" 2>/dev/null || true
# xcodebuild test 프로세스도 종료
pkill -f "xcodebuild.*xctestrun" 2>/dev/null || true
pkill -f "XCTRunner" 2>/dev/null || true
# 기기 side: XCTestManager_IDEInterface 세션 해제 위해 2초 대기
sleep 2
ok "기존 WDA 프로세스 종료 완료"

# iproxy 포트포워딩 시작 (USB → localhost:WDA_PORT)
killall iproxy 2>/dev/null || true
sleep 0.5
iproxy "$WDA_PORT" "$WDA_PORT" --udid "$UDID" > /dev/null 2>&1 &
IPROXY_PID=$!
ok "iproxy 포트포워딩 시작 (PID: $IPROXY_PID, localhost:${WDA_PORT} → device:${WDA_PORT})"

WDA_LOG="/tmp/wda_${UDID:0:8}.log"
xcodebuild test-without-building \
    -xctestrun "$XCTESTRUN" \
    -destination "id=${UDID}" > "$WDA_LOG" 2>&1 &
WDA_PID=$!
echo "WDA 기동 중... (PID: $WDA_PID, 로그: $WDA_LOG)"

# localhost:WDA_PORT 응답 대기 (최대 60초)
WDA_URL=""
for i in $(seq 1 60); do
    if curl -s --max-time 2 "http://localhost:${WDA_PORT}/status" 2>/dev/null | grep -q '"build"'; then
        WDA_URL="http://localhost:${WDA_PORT}"
        break
    fi
    # 로그에서 디바이스 IP 확인 (WiFi 연결 시)
    URL=$(grep -o "ServerURLHere->http://[^<]*" "$WDA_LOG" 2>/dev/null | head -1 | sed 's/ServerURLHere->//')
    if [[ -n "$URL" ]]; then
        WDA_URL="$URL"
        break
    fi
    printf "  기다리는 중... ${i}s\r"
    sleep 1
done

echo ""
if [[ -z "$WDA_URL" ]]; then
    warn "WDA URL 자동 감지 실패. 로그 확인: tail -f $WDA_LOG"
else
    ok "WDA 기동 완료: $WDA_URL"

    # 응답 확인
    STATUS=$(curl -s --max-time 5 "${WDA_URL}/status" 2>/dev/null | python3 -c \
        "import sys,json; d=json.load(sys.stdin); print('ready=', d.get('value',{}).get('ready'))" 2>/dev/null || echo "파싱실패")
    ok "WDA 상태: $STATUS"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  WDA_URL = $WDA_URL"
    echo "  iproxy PID: $IPROXY_PID (포트포워딩 유지 중)"
    echo "  diag_tc02_call.py의 WDA_URL을 위 값으로 업데이트하세요."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
fi

echo ""
ok "모든 단계 완료"
