#!/usr/bin/env bash
# build_wda_ipa.sh
# WebDriverAgentRunner IPA를 빌드하고 연결된 모든 iPhone에 설치합니다.
#
# 사용법:
#   ./build_wda_ipa.sh                      # 빌드 + 연결된 모든 iPhone에 설치
#   ./build_wda_ipa.sh --build-only         # 빌드만 (IPA 생성)
#   ./build_wda_ipa.sh --install-only       # 설치만 (기존 IPA 재사용, 모든 기기)
#   ./build_wda_ipa.sh --install-only UDID  # 특정 iPhone에만 설치
#   ./build_wda_ipa.sh --xcode-setup        # Xcode 계정/서명 설정 안내 (첫 빌드 전 실행)
#
# 새 iPhone 연결 시:
#   ./build_wda_ipa.sh  → -allowProvisioningDeviceRegistration으로 UDID 자동 등록 후 빌드+설치
#   이후엔: ./build_wda_ipa.sh --install-only  (재빌드 불필요)

set -euo pipefail

WDA_SRC="/Users/qabulls/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent"
SCHEME="WebDriverAgentRunner"
BUNDLE_ID="com.jjun.1.WebDriverAgentRunner"
TEAM_ID="5392L928H5"
BUILD_DIR="/tmp/wda_build"
IPA_DIR="/tmp/wda_ipa"
IPA_PATH="$IPA_DIR/WebDriverAgentRunner.ipa"
MODE="${1:-}"
SPECIFIC_UDID="${2:-}"

log()  { echo "$(date '+%H:%M:%S') $*"; }
ok()   { echo "$(date '+%H:%M:%S')   ✅ $*"; }
warn() { echo "$(date '+%H:%M:%S')   ⚠️  $*"; }
err()  { echo "$(date '+%H:%M:%S')   ❌ $*" >&2; }

# Xcode 계정/프로비저닝 사전 체크
check_xcode_account() {
    local profile_count
    profile_count=$(ls ~/Library/MobileDevice/Provisioning\ Profiles/*.mobileprovision 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$profile_count" -eq 0 ]]; then
        err "프로비저닝 프로파일 없음 (0개)"
        echo ""
        echo "  ──────────────────────────────────────────────────────────"
        echo "  [해결 방법] Xcode에서 1회 Apple 계정 재인증 필요:"
        echo ""
        echo "  1) Xcode를 열고 ⌘, (Settings) → Accounts 탭"
        echo "  2) Apple ID(SeongJun Choi) 선택 → 'Download Manual Profiles' 클릭"
        echo "  3) 또는 이 스크립트에서 자동으로 열려면:"
        echo "       ./build_wda_ipa.sh --xcode-setup"
        echo "  ──────────────────────────────────────────────────────────"
        echo ""
        return 1
    fi
    ok "프로비저닝 프로파일 ${profile_count}개 확인"
    return 0
}

# Xcode에서 WDA 프로젝트를 열어 서명 설정 안내
xcode_setup() {
    log "Xcode에서 WDA 프로젝트 여는 중..."
    open -a Xcode "$WDA_SRC/WebDriverAgent.xcodeproj"
    echo ""
    echo "  ──────────────────────────────────────────────────────────"
    echo "  Xcode가 열렸습니다. 다음 순서로 진행하세요:"
    echo ""
    echo "  1) ⌘, (Settings) → Accounts 탭"
    echo "     → Apple ID 선택 → 'Download Manual Profiles' 클릭"
    echo ""
    echo "  2) WebDriverAgentRunner 타겟 클릭"
    echo "     → Signing & Capabilities 탭"
    echo "     → Team: SeongJun Choi (5392L928H5)"
    echo "     → Bundle ID: com.jjun.1.WebDriverAgentRunner"
    echo "     → 에러(빨간 느낌표) 없어지면 완료"
    echo ""
    echo "  3) Xcode 닫고 다시 빌드:"
    echo "       ./build_wda_ipa.sh"
    echo "  ──────────────────────────────────────────────────────────"
    exit 0
}

# 연결된 실제 iPhone UDID 목록
get_iphones() {
    xcrun xctrace list devices 2>/dev/null \
        | grep -v -E "Simulator|simulator" \
        | grep -oE "[0-9A-F]{8}-[0-9A-F]{16}" \
        || true
}

build_wda() {
    # 프로비저닝 프로파일 사전 확인
    check_xcode_account || exit 1

    log "🔨 WDA 빌드 시작..."
    rm -rf "$BUILD_DIR"
    mkdir -p "$BUILD_DIR"

    # -allowProvisioningDeviceRegistration: 현재 연결된 모든 iPhone UDID를
    # Apple Developer Portal에 자동 등록 → 프로비저닝 프로파일 자동 갱신
    # → 새 iPhone 연결 후 이 스크립트 1회 실행만으로 완료
    xcodebuild \
        -project "$WDA_SRC/WebDriverAgent.xcodeproj" \
        -scheme "$SCHEME" \
        -destination "generic/platform=iOS" \
        -derivedDataPath "$BUILD_DIR" \
        -allowProvisioningUpdates \
        -allowProvisioningDeviceRegistration \
        CODE_SIGN_STYLE=Automatic \
        DEVELOPMENT_TEAM="$TEAM_ID" \
        PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" \
        clean build \
        2>&1 | grep -E "^error:|BUILD SUCCEEDED|BUILD FAILED|Signing cert|Provisioning" || true

    APP_PATH=$(find "$BUILD_DIR" \
        -name "WebDriverAgentRunner.app" \
        -not -path "*iphonesimulator*" \
        | head -1)

    if [[ -z "$APP_PATH" ]]; then
        err "빌드 실패: WebDriverAgentRunner.app 없음"
        log "  전체 로그: $BUILD_DIR/Logs/Build/"
        exit 1
    fi
    ok "빌드 완료: $APP_PATH"

    rm -rf "$IPA_DIR"
    mkdir -p "$IPA_DIR/Payload"
    cp -R "$APP_PATH" "$IPA_DIR/Payload/"
    (cd "$IPA_DIR" && zip -qr "WebDriverAgentRunner.ipa" Payload/)
    ok "IPA 생성: $IPA_PATH  ($(du -sh "$IPA_PATH" | cut -f1))"
}

install_on_device() {
    local udid="$1"
    local label="$2"
    log "📲 설치: $label ($udid)"
    if xcrun devicectl device install app --device "$udid" "$IPA_PATH" 2>&1 \
        | grep -v "^Waiting\|^$" ; then
        ok "설치 완료: $label"
    else
        warn "설치 실패: $label — Xcode Devices 탭에서 수동 설치 필요"
    fi
}

verify_wda() {
    local udid="$1"

    local uuid
    uuid=$(xcrun devicectl list devices --json-output /tmp/_wdav.json 2>/dev/null && \
        python3 -c "
import json
for d in json.load(open('/tmp/_wdav.json')).get('result',{}).get('devices',[]):
    if d.get('hardwareProperties',{}).get('udid','')=='$udid':
        print(d.get('identifier','')); break
" 2>/dev/null || true)

    [[ -z "$uuid" ]] && { warn "기기 UUID 미감지 — WDA를 수동 실행하세요"; return; }

    log "🚀 WDA 실행..."
    xcrun devicectl device process launch --device "$uuid" "$BUNDLE_ID" 2>&1 | grep -v "^$" || true

    # Bonjour로 IP 탐지
    local ip
    ip=$(python3 - <<'PY' 2>/dev/null || echo ""
import subprocess, re, sys
try:
    r = subprocess.run(['dns-sd','-q',
        'ixi-O-tonghwateseuteuyong-iPhone-17-Pro.local','A','IN'],
        capture_output=True, timeout=5, text=True)
    for ln in r.stdout.splitlines():
        m = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', ln)
        if m: print(m.group(1)); sys.exit(0)
except: pass
PY
)
    [[ -z "$ip" ]] && ip="192.168.219.119"

    log "⏳ WDA 응답 대기 (최대 30초, $ip:8100)..."
    for i in $(seq 1 30); do
        curl -sf "http://$ip:8100/status" >/dev/null 2>&1 && {
            ok "WDA 동작 확인: http://$ip:8100/status"
            return
        }
        sleep 1
        [[ $((i % 5)) -eq 0 ]] && log "  대기 ${i}초..."
    done
    warn "WDA 응답 없음. iPhone에서 앱 신뢰 설정 확인:"
    warn "  설정 → 일반 → VPN 및 기기 관리 → 개발자 앱 → 신뢰"
}

install_wda() {
    [[ ! -f "$IPA_PATH" ]] && { err "IPA 없음: $IPA_PATH  (먼저 빌드하세요)"; exit 1; }

    if [[ -n "$SPECIFIC_UDID" ]]; then
        install_on_device "$SPECIFIC_UDID" "지정 기기"
        verify_wda "$SPECIFIC_UDID"
        return
    fi

    local udids
    udids=$(get_iphones)
    [[ -z "$udids" ]] && { warn "연결된 iPhone 없음"; exit 1; }

    local cnt=0
    while IFS= read -r udid; do
        [[ -z "$udid" ]] && continue
        local name
        name=$(xcrun xctrace list devices 2>/dev/null \
            | grep "$udid" | sed 's/ ([^)]*([^)]*))$//' | xargs || echo "iPhone")
        install_on_device "$udid" "$name"
        verify_wda "$udid"
        ((cnt++)) || true
    done <<< "$udids"
    log "📦 총 ${cnt}대 설치 완료"
}

echo "======================================================"
echo " WDA IPA Builder  |  $BUNDLE_ID"
echo " Team: $TEAM_ID   |  IPA: $IPA_PATH"
echo "======================================================"

case "$MODE" in
    --xcode-setup)  xcode_setup ;;
    --build-only)   build_wda ;;
    --install-only) install_wda ;;
    *)              build_wda; install_wda ;;
esac

log "🎉 완료"
