#!/usr/bin/env bash
# =============================================================================
# install_visqol.sh  — macOS(Apple Silicon/Intel) visqol-3.3.3 원클릭 설치
# =============================================================================
# 지원 환경: macOS 13 ~ 26.x (Xcode 14~26), Apple Silicon / Intel
# 필요 사전 조건: Xcode full install (Command Line Tools 만으로는 부족)
#
# 사용법:
#   chmod +x install_visqol.sh
#   ./install_visqol.sh [--visqol-dir /path/to/visqol-3.3.3]
#
# 기본 동작:
#   1. 의존성 확인/설치 (brew, bazelisk, armadillo)
#   2. visqol-3.3.3 소스 다운로드 (단, --visqol-dir 지정 시 생략)
#   3. WORKSPACE armadillo patch (SourceForge URL 404 우회)
#   4. .bazelversion = 5.4.0 설정
#   5. 첫 바젤빌드 (실패해도 OK — Bazel 캐시 초기화 목적)
#   6. Bazel 환경 패치 (wrapped_clang / libtool_check_unique / zutil.h)
#   7. 최종 빌드
#   8. 바이너리 위치 안내
# =============================================================================
set -euo pipefail

# ─── 색상 출력 ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()  { echo -e "${CYAN}[*]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
log_err()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VISQOL_DIR=""

# ─── 인수 파싱 ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --visqol-dir) VISQOL_DIR="$2"; shift 2 ;;
        --help|-h)
            echo "사용법: $0 [--visqol-dir /path/to/visqol-3.3.3]"
            exit 0 ;;
        *) log_warn "알 수 없는 인수: $1"; shift ;;
    esac
done

# ─── Step 0: 환경 확인 ────────────────────────────────────────────────────────
log_info "환경 확인 중..."

# Xcode 설치 확인
if ! xcode-select -p &>/dev/null; then
    log_err "Xcode가 설치되어 있지 않습니다. Xcode full install 필요 (App Store)"
fi
XCODE_PATH="$(xcode-select -p)"
SDK_PATH="$(xcrun --sdk macosx --show-sdk-path 2>/dev/null)"
SDK_VER="$(xcrun --sdk macosx --show-sdk-version 2>/dev/null)"
log_ok "Xcode Developer Dir: $XCODE_PATH"
log_ok "macOS SDK: $SDK_PATH (v$SDK_VER)"

# macOS 버전
MACOS_VER="$(sw_vers -productVersion)"
log_ok "macOS: $MACOS_VER"

# Python3
if ! command -v python3 &>/dev/null; then
    log_err "python3 를 찾을 수 없습니다. Xcode 또는 brew로 설치하세요."
fi
PYTHON3="$(command -v python3)"
log_ok "Python3: $($PYTHON3 --version)"

# ─── Step 1: brew 확인 ────────────────────────────────────────────────────────
log_info "Homebrew 확인..."
if ! command -v brew &>/dev/null; then
    log_warn "Homebrew 미설치 — 설치 중..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Apple Silicon brew PATH 추가
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
fi
log_ok "brew: $(brew --version | head -1)"

# ─── Step 2: bazelisk 설치 ────────────────────────────────────────────────────
log_info "bazelisk 확인..."
if ! command -v bazelisk &>/dev/null; then
    log_warn "bazelisk 미설치 — brew install bazelisk..."
    # 기존 bazel(9.x)과 충돌 방지
    if brew list bazel &>/dev/null 2>&1; then
        log_warn "기존 bazel 감지 → unlink 후 bazelisk 설치"
        brew unlink bazel || true
    fi
    brew install bazelisk
fi
log_ok "bazelisk: $(bazelisk --version 2>&1 | head -1)"

# ─── Step 3: armadillo 설치 (brew) ───────────────────────────────────────────
log_info "armadillo 헤더 확인..."
if ! brew list armadillo &>/dev/null 2>&1; then
    log_warn "armadillo 미설치 — brew install armadillo..."
    brew install armadillo
fi
ARMA_PREFIX="$(brew --prefix armadillo)"
log_ok "armadillo: $ARMA_PREFIX"

# ─── Step 4: visqol 소스 준비 ────────────────────────────────────────────────
if [[ -z "$VISQOL_DIR" ]]; then
    VISQOL_DIR="$(pwd)/visqol-3.3.3"
    if [[ ! -d "$VISQOL_DIR" ]]; then
        log_info "visqol-3.3.3 소스 다운로드 중..."
        # GitHub release tar.gz
        curl -fsSL "https://github.com/google/visqol/archive/refs/tags/v3.3.3.tar.gz" \
            -o /tmp/visqol-3.3.3.tar.gz
        tar -xzf /tmp/visqol-3.3.3.tar.gz
        mv visqol-3.3.3 "$VISQOL_DIR" 2>/dev/null || true
        log_ok "소스 다운로드 완료: $VISQOL_DIR"
    else
        log_ok "소스 디렉토리 재사용: $VISQOL_DIR"
    fi
else
    [[ -d "$VISQOL_DIR" ]] || log_err "지정한 --visqol-dir 경로가 없습니다: $VISQOL_DIR"
    log_ok "소스 디렉토리: $VISQOL_DIR"
fi

cd "$VISQOL_DIR"

# ─── Step 5: .bazelversion 설정 ──────────────────────────────────────────────
log_info ".bazelversion → 5.4.0"
echo "5.4.0" > .bazelversion
# 5.4.0 다운로드 (캐시 없으면 여기서 받음)
bazelisk version 2>&1 | head -3

# ─── Step 6: WORKSPACE armadillo 패치 ────────────────────────────────────────
log_info "WORKSPACE armadillo 패치 확인..."
if grep -q "sourceforge.net.*armadillo" WORKSPACE; then
    log_warn "http_archive(armadillo) → new_local_repository(brew) 로 교체..."
    "$PYTHON3" "$SCRIPT_DIR/patch_workspace_armadillo.py" "$ARMA_PREFIX"
else
    log_ok "WORKSPACE armadillo 이미 패치됨 (건너뜀)"
fi

# ─── Step 7: 첫 번째 빌드 (Bazel 캐시 초기화) ────────────────────────────────
log_info "Step 7: 첫 번째 빌드 시도 (Bazel output_base 초기화 목적)..."
log_warn "이 단계는 에러가 발생해도 정상입니다. 계속 진행합니다."
bazelisk build :visqol 2>&1 | tail -5 || true

# ─── Step 8: Bazel 환경 패치 ─────────────────────────────────────────────────
log_info "Step 8: Bazel 환경 패치 적용 (wrapped_clang / libtool / zutil.h)..."
"$PYTHON3" "$SCRIPT_DIR/patch_bazel_env.py"

# ─── Step 9: 최종 빌드 ───────────────────────────────────────────────────────
log_info "Step 9: 최종 빌드..."
bazelisk build :visqol 2>&1 | tail -10

BINARY="$VISQOL_DIR/bazel-bin/visqol"
if [[ -x "$BINARY" ]]; then
    log_ok "====================================================="
    log_ok " 빌드 성공!"
    log_ok " 바이너리: $BINARY"
    log_ok " 테스트: $BINARY --help"
    log_ok "====================================================="
else
    log_err "빌드 실패. 로그를 확인하세요."
fi
