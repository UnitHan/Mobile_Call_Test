#!/bin/bash
# WDA 실행 스크립트 (xcrun devicectl 전용 - libimobiledevice 불필요)
# Team ID: 35597M53Y5 / Bundle prefix: com.jjun.1
set -euo pipefail

WDA_PORT="${WDA_PORT:-8100}"
TARGET_UDID="${TARGET_UDID:-}"
TEAM_ID="35597M53Y5"
BUNDLE_ID="${WDA_BUNDLE_ID:-com.jjun.1.WebDriverAgentRunner.xctrunner}"
WDA_DIR=$(find ~/.appium -name "appium-webdriveragent" -maxdepth 8 -type d 2>/dev/null | head -1)

ok()   { echo "OK: $*"; }
warn() { echo "WARN: $*"; }
die()  { echo "ERROR: $*"; exit 1; }

echo ""
echo "=== STEP 1: iPhone 연결 확인 (devicectl) ==="

TMP_JSON="/tmp/_wda_devices_$$.json"
xcrun devicectl list devices --json-output "$TMP_JSON" 2>/dev/null || die "xcrun devicectl 실패"

UDID=$(python3 -c "
import json, os
target = os.environ.get('TARGET_UDID','').strip()
data = json.load(open('$TMP_JSON'))
devs = data.get('result',{}).get('devices',[])
for d in devs:
    uid = d.get('hardwareProperties',{}).get('udid','')
    if uid and (not target or uid == target):
        print(uid); break
" 2>/dev/null)

DEVICE_UUID=$(python3 -c "
import json, os
target = os.environ.get('TARGET_UDID','').strip()
data = json.load(open('$TMP_JSON'))
devs = data.get('result',{}).get('devices',[])
for d in devs:
    uid = d.get('hardwareProperties',{}).get('udid','')
    if uid and (not target or uid == target):
        print(d.get('identifier','')); break
" 2>/dev/null)

TUNNEL_IP=$(python3 -c "
import json, os
target = os.environ.get('TARGET_UDID','').strip()
data = json.load(open('$TMP_JSON'))
devs = data.get('result',{}).get('devices',[])
for d in devs:
    uid = d.get('hardwareProperties',{}).get('udid','')
    if uid and (not target or uid == target):
        print(d.get('connectionProperties',{}).get('tunnelIPAddress','')); break
" 2>/dev/null || true)

DEVICE_OS_VER=$(python3 -c "
import json, os
target = '$UDID'
data = json.load(open('$TMP_JSON'))
devs = data.get('result',{}).get('devices',[])
for d in devs:
    uid = d.get('hardwareProperties',{}).get('udid','')
    if uid and (not target or uid == target):
        print(d.get('deviceProperties',{}).get('osVersionNumber',''))
        break
" 2>/dev/null || true)

rm -f "$TMP_JSON"

if [[ -n "$TARGET_UDID" ]]; then
    [[ -z "$UDID" ]] && die "대상 iPhone을 찾을 수 없음 (UDID: $TARGET_UDID). 연결 상태 확인 후 '신뢰' 탭하세요."
else
    [[ -z "$UDID" ]] && die "연결된 iPhone 없음. USB 연결 후 '신뢰' 탭하세요."
fi
[[ -z "$DEVICE_UUID" ]] && die "devicectl UUID 조회 실패"
ok "iPhone UDID: $UDID"
ok "devicectl UUID: ${DEVICE_UUID:0:8}..."
# iOS 버전 (없으면 xcrun으로 폴백)
if [[ -z "$DEVICE_OS_VER" ]]; then
    DEVICE_OS_VER=$(xcrun devicectl device info details --device "$DEVICE_UUID" 2>/dev/null \
        | grep -E '"osVersionNumber"' | head -1 | sed 's/.*: *"\([^"]*\)".*/\1/' || true)
fi
IOS_MAJOR=$(echo "$DEVICE_OS_VER" | cut -d'.' -f1)
ok "iOS 버전: ${DEVICE_OS_VER:-unknown} (major: ${IOS_MAJOR:-?})"

echo ""
echo "=== STEP 2: WDA 실행 상태 확인 ==="

if [[ -n "$TUNNEL_IP" ]]; then
    STATUS=$(curl -s --max-time 3 "http://[${TUNNEL_IP}]:${WDA_PORT}/status" 2>/dev/null || true)
    if echo "$STATUS" | grep -q '"build"'; then
        ok "WDA 이미 실행 중 (tunnelIP: ${TUNNEL_IP}, port: $WDA_PORT)"
        echo "WDA_URL = http://[${TUNNEL_IP}]:${WDA_PORT}"
        ok "완료 (이미 실행 중)"
        exit 0
    fi
fi

echo ""
echo "=== STEP 3: WDA 소스 확인 ==="

if [[ -z "$WDA_DIR" ]]; then
    warn "appium-webdriveragent 없음 - appium + xcuitest 설치 시도..."
    npm install -g appium 2>&1 | tail -3
    appium driver install xcuitest 2>&1 | tail -3
    WDA_DIR=$(find ~/.appium -name "appium-webdriveragent" -maxdepth 8 -type d 2>/dev/null | head -1)
    [[ -z "$WDA_DIR" ]] && die "WDA 소스 없음"
fi
ok "WDA 소스: $WDA_DIR"

PBXPROJ="$WDA_DIR/WebDriverAgent.xcodeproj/project.pbxproj"
CURRENT_TARGET=$(grep "IPHONEOS_DEPLOYMENT_TARGET" "$PBXPROJ" 2>/dev/null | grep -E "2[0-9]\." | head -1 || true)
if [[ -n "$CURRENT_TARGET" ]]; then
    warn "배포 타겟 iOS 20+ 감지 - 16.0으로 패치"
    cp "$PBXPROJ" "$PBXPROJ.bak"
    sed -i '' 's/IPHONEOS_DEPLOYMENT_TARGET = 2[0-9]\.[0-9]*;/IPHONEOS_DEPLOYMENT_TARGET = 16.0;/g' "$PBXPROJ"
    ok "배포 타겟 패치 완료"
else
    ok "배포 타겟 패치 불필요"
fi

echo ""
echo "=== STEP 4: xctestrun 확인 / 빌드 ==="

# iOS major 버전에 맞는 xctestrun 우선 탐색, 없으면 전체 중 최신
_find_xctestrun_for_ios() {
    local major="$1"
    local best=""
    # 버전 매칭 우선
    if [[ -n "$major" ]]; then
        best=$(find ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*/Build/Products \
            -name "*iphoneos${major}*-arm64.xctestrun" 2>/dev/null \
            | while IFS= read -r f; do
                sz=$(stat -f%z "$f" 2>/dev/null || echo 0)
                [[ $sz -gt 2000 ]] && echo "$f"
            done | xargs ls -t 2>/dev/null | head -1 || true)
    fi
    # 버전 매칭 없으면 전체 최신
    if [[ -z "$best" ]]; then
        best=$(find ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*/Build/Products \
            -name "*.xctestrun" 2>/dev/null \
            | while IFS= read -r f; do
                sz=$(stat -f%z "$f" 2>/dev/null || echo 0)
                [[ $sz -gt 2000 ]] && echo "$f"
            done | xargs ls -t 2>/dev/null | head -1 || true)
    fi
    echo "$best"
}

XCTESTRUN=$(_find_xctestrun_for_ios "$IOS_MAJOR")

# xctestrun 버전 불일치 감지 → 강제 재빌드
XCTESTRUN_NEEDS_BUILD=0
if [[ -n "$XCTESTRUN" && -n "$IOS_MAJOR" ]]; then
    XCTR_BASENAME=$(basename "$XCTESTRUN")
    if ! echo "$XCTR_BASENAME" | grep -q "iphoneos${IOS_MAJOR}"; then
        warn "xctestrun 버전 불일치: $XCTR_BASENAME (기기 iOS ${IOS_MAJOR}) → 재빌드"
        XCTESTRUN=""
        XCTESTRUN_NEEDS_BUILD=1
        rm -f "/tmp/wda_installed_${UDID}_"*.stamp 2>/dev/null || true
    fi
fi

if [[ -n "$XCTESTRUN" ]]; then
    ok "기존 xctestrun 재사용: $(basename "$XCTESTRUN")"
else
    warn "xctestrun 없음 - build-for-testing 실행 (Team: $TEAM_ID, 기기 iOS: ${DEVICE_OS_VER:-unknown})"
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
    XCTESTRUN=$(_find_xctestrun_for_ios "$IOS_MAJOR")
    [[ -z "$XCTESTRUN" ]] && die "build-for-testing 실패. 로그: $BFT_LOG"
    ok "xctestrun 생성: $(basename "$XCTESTRUN")"
    # 새 xctestrun → 이전 IPA stamp 무효화 (재설치 강제)
    rm -f "/tmp/wda_installed_${UDID}_"*.stamp 2>/dev/null || true
fi

echo ""
echo "=== STEP 5: IPA 설치 ==="

PRODUCTS_DIR=$(dirname "$XCTESTRUN")
APP_PATH="$PRODUCTS_DIR/Debug-iphoneos/WebDriverAgentRunner-Runner.app"

# 설치 stamp 파일: UDID + xctestrun 조합이 같으면 재설치 생략
_XCTR_KEY=$(basename "$XCTESTRUN" .xctestrun)
_STAMP="/tmp/wda_installed_${UDID}_${_XCTR_KEY}.stamp"

if [[ -f "$_STAMP" ]]; then
    ok "IPA 설치 생략 (이미 설치됨: $(cat "$_STAMP"))"
elif [[ -d "$APP_PATH" ]]; then
    IPA_DIR="/tmp/wda_ipa_$(date +%s)"
    mkdir -p "$IPA_DIR/Payload"
    cp -R "$APP_PATH" "$IPA_DIR/Payload/"
    cd "$IPA_DIR"
    zip -qr WDA.ipa Payload/ --exclude "*.DS_Store"
    ok "IPA 생성: $(du -sh WDA.ipa | cut -f1)"
    _INSTALL_LOG="/tmp/wda_install_$$.log"
    xcrun devicectl device install app --device "$DEVICE_UUID" "$IPA_DIR/WDA.ipa" \
        > "$_INSTALL_LOG" 2>&1 &
    _INSTALL_PID=$!
    _DEADLINE=$(( SECONDS + 90 ))
    while kill -0 "$_INSTALL_PID" 2>/dev/null && [[ $SECONDS -lt $_DEADLINE ]]; do
        sleep 2
    done
    if kill -0 "$_INSTALL_PID" 2>/dev/null; then
        kill "$_INSTALL_PID" 2>/dev/null || true
        wait "$_INSTALL_PID" 2>/dev/null || true
        warn "IPA 설치 시간 초과 (90초) - 이미 설치된 경우 정상"
        date > "$_STAMP"
    else
        if wait "$_INSTALL_PID"; then
            ok "WDA IPA 설치 완료"
            date > "$_STAMP"
        else
            warn "설치 실패: $(tail -3 "$_INSTALL_LOG")"
        fi
    fi
    rm -f "$_INSTALL_LOG"
    cd - > /dev/null
else
    warn ".app 없음 - 설치 건너뜀 (이미 설치된 경우 정상)"
fi

# IPA 설치 후 TUNNEL_IP 재조회 (연결 끊겼다 재연결된 경우 대비)
if [[ -z "$TUNNEL_IP" ]]; then
    echo "  🔄 TUNNEL_IP 재조회 중 (IPA 설치로 디바이스 재연결 대기)..."
    for _retry in $(seq 1 10); do
        sleep 2
        TMP_JSON2="/tmp/_wda_reconnect_$$.json"
        xcrun devicectl list devices --json-output "$TMP_JSON2" 2>/dev/null || true
        TUNNEL_IP=$(python3 -c "
import json, os
target = '$UDID'
data = json.load(open('$TMP_JSON2'))
devs = data.get('result',{}).get('devices',[])
for d in devs:
    uid = d.get('hardwareProperties',{}).get('udid','')
    if uid == target:
        print(d.get('connectionProperties',{}).get('tunnelIPAddress',''))
        break
" 2>/dev/null || true)
        rm -f "$TMP_JSON2"
        if [[ -n "$TUNNEL_IP" ]]; then
            ok "TUNNEL_IP 재확보: ${TUNNEL_IP} (재시도 ${_retry}회)"
            break
        fi
        printf "  연결 대기 중... %ds\r" "$((_retry * 2))"
    done
    [[ -z "$TUNNEL_IP" ]] && warn "TUNNEL_IP 재조회 실패 — xcodebuild log 기반 URL 감지로 진행"
fi

echo ""
echo "=== STEP 6: WDA 실행 ==="

xcrun devicectl device process terminate --device "$DEVICE_UUID" "$BUNDLE_ID" 2>/dev/null || true
# 이 기기(UDID)에 해당하는 xcodebuild만 종료 (다른 기기 WDA 프로세스 보호)
pkill -f "xcodebuild.*${UDID}" 2>/dev/null || true
sleep 1
ok "기존 WDA 프로세스 정리 완료"

WDA_LOG="/tmp/wda_${UDID:0:8}.log"
xcodebuild test-without-building \
    -xctestrun "$XCTESTRUN" \
    -destination "id=${UDID}" > "$WDA_LOG" 2>&1 &
WDA_PID=$!
echo "WDA 기동 중... (PID: $WDA_PID, 로그: $WDA_LOG)"

WDA_URL=""
for i in $(seq 1 60); do
    URL=$(grep -o "ServerURLHere->http://[^<]*" "$WDA_LOG" 2>/dev/null | head -1 | sed 's/ServerURLHere->//' || true)
    if [[ -n "$URL" ]]; then
        WDA_URL="$URL"
        break
    fi
    if [[ -n "$TUNNEL_IP" ]]; then
        STATUS=$(curl -s --max-time 1 "http://[${TUNNEL_IP}]:${WDA_PORT}/status" 2>/dev/null || true)
        if echo "$STATUS" | grep -q '"build"'; then
            WDA_URL="http://[${TUNNEL_IP}]:${WDA_PORT}"
            break
        fi
    fi
    printf "  기다리는 중... %ds\r" "$i"
    sleep 1
done

echo ""
if [[ -z "$WDA_URL" ]]; then
    warn "WDA URL 자동 감지 실패. 로그: tail -f $WDA_LOG"
    warn "WDA 백그라운드 실행 중 (PID: $WDA_PID) - IP 스캔으로 재탐색합니다."
else
    ok "WDA 기동 완료: $WDA_URL"
    echo "WDA_URL = $WDA_URL"
fi

ok "모든 단계 완료"
