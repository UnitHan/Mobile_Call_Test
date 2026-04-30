#!/usr/bin/env python3
"""
patch_bazel_env.py — Bazel 5.x + macOS 26.x / 15.x 빌드 환경 패치

적용 패치:
  1. wrapped_clang / wrapped_clang_pp  → 쉘 스크립트로 교체 (LC_UUID 우회)
  2. libtool_check_unique              → 쉘 스크립트로 교체 (LC_UUID 우회)
  3. external/zlib/zutil.h             → fdopen 매크로 Apple 조건부 우회

사용법:
  python3 patch_bazel_env.py [--sdk-path /path/to/sdk]
  (인자 생략 시 xcrun으로 자동 탐지)
"""

import glob, os, subprocess, sys

# ─── SDK / Developer Dir 탐지 ──────────────────────────────────────────────────
def detect_sdk() -> str:
    try:
        return subprocess.check_output(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True
        ).strip()
    except Exception as e:
        print(f"[!] xcrun 실패: {e}")
        sys.exit(1)

def detect_developer_dir() -> str:
    try:
        return subprocess.check_output(["xcode-select", "-p"], text=True).strip()
    except Exception:
        return "/Applications/Xcode.app/Contents/Developer"

SDK = sys.argv[2] if len(sys.argv) >= 3 and sys.argv[1] == "--sdk-path" else detect_sdk()
DEV = detect_developer_dir()

print(f"[*] SDK  → {SDK}")
print(f"[*] DEV  → {DEV}")

# ─── Bazel output_base 탐지 ──────────────────────────────────────────────────
USER = os.environ.get("USER", os.path.basename(os.path.expanduser("~")))
search_roots = [
    f"/private/var/tmp/_bazel_{USER}/*/external/local_config_cc",
    f"/var/tmp/_bazel_{USER}/*/external/local_config_cc",
    os.path.expanduser(f"~/.cache/bazel/_bazel_{USER}/*/external/local_config_cc"),
]
bases = []
for pattern in search_roots:
    bases += glob.glob(pattern)

if not bases:
    print("[!] Bazel output_base를 찾지 못했습니다.")
    print("    먼저 'bazelisk build :visqol' 을 한 번 실행해 Bazel 캐시를 초기화하세요.")
    print("    (빌드 실패해도 괜찮습니다. 이후 이 스크립트를 다시 실행하세요.)")
    sys.exit(2)

# ─── Patch 1 & 2: wrapped_clang / wrapped_clang_pp / libtool_check_unique ──────
WRAPPED_TEMPLATE = """\
#!/bin/bash
# {name} — Bazel 5.x LC_UUID workaround ({sdk})
SDKROOT="{sdk}"
DEVELOPER_DIR="{dev}"
ARGS=()
for arg in "$@"; do
    case "$arg" in
        DEBUG_PREFIX_MAP_PWD=*)
            PWD_VAL="${{arg#DEBUG_PREFIX_MAP_PWD=}}"
            ARGS+=("-fdebug-prefix-map=$(pwd)=${{PWD_VAL}}")
            ;;
        *)
            arg="${{arg//__BAZEL_XCODE_SDKROOT__/${{SDKROOT}}}}"
            arg="${{arg//__BAZEL_XCODE_DEVELOPER_DIR__/${{DEVELOPER_DIR}}}}"
            ARGS+=("$arg")
            ;;
    esac
done
exec /usr/bin/clang "${{ARGS[@]}}"
"""

LIBTOOL_CHECK_TEMPLATE = """\
#!/bin/bash
# libtool_check_unique — Bazel 5.x LC_UUID workaround
declare -A seen
for arg in "$@"; do
    if [[ "$arg" == *.o ]]; then
        base=$(basename "$arg")
        if [[ ${seen[$base]+x} ]]; then
            exit 1
        fi
        seen[$base]=1
    fi
done
exit 0
"""


def backup_and_write(path: str, content: str, label: str):
    orig = path + ".orig"
    if os.path.exists(path):
        size = os.path.getsize(path)
        if not os.path.exists(orig) and size > 200:
            os.rename(path, orig)
            print(f"  → backed up: {os.path.basename(orig)}")
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o755)
    print(f"  ✅ {label}")


for ccdir in bases:
    print(f"\n[+] Patching: {ccdir}")

    for name in ("wrapped_clang", "wrapped_clang_pp"):
        path = os.path.join(ccdir, name)
        if not os.path.exists(path):
            continue
        content = WRAPPED_TEMPLATE.format(name=name, sdk=SDK, dev=DEV)
        backup_and_write(path, content, name)

    libtool_path = os.path.join(ccdir, "libtool_check_unique")
    if os.path.exists(libtool_path):
        backup_and_write(libtool_path, LIBTOOL_CHECK_TEMPLATE, "libtool_check_unique")

# ─── Patch 3: zlib/zutil.h fdopen 매크로 ──────────────────────────────────────
OLD_FDOPEN = (
    "#      ifndef fdopen\n"
    "#        define fdopen(fd,mode) NULL /* No fdopen() */"
)
NEW_FDOPEN = (
    "#      if !defined(fdopen) && !defined(__APPLE__) "
    "/* macOS has fdopen: skip null-define */\n"
    "#        define fdopen(fd,mode) NULL /* No fdopen() */"
)

zutil_candidates = []
for ccdir in bases:
    zutil_candidates += glob.glob(os.path.join(ccdir, "..", "..", "zlib", "zutil.h"))

for zutil in map(os.path.normpath, zutil_candidates):
    if not os.path.exists(zutil):
        continue
    with open(zutil) as f:
        content = f.read()
    if OLD_FDOPEN in content:
        content = content.replace(OLD_FDOPEN, NEW_FDOPEN, 1)
        with open(zutil, "w") as f:
            f.write(content)
        print(f"\n  ✅ zlib/zutil.h patched  ({zutil})")
    elif "__APPLE__" in content and "fdopen" in content:
        print(f"\n  ℹ️  zlib/zutil.h 이미 패치됨: {zutil}")
    else:
        print(f"\n  ⚠️  zlib/zutil.h 패턴 없음 (건너뜀): {zutil}")

print("\n[done] 패치 완료 → bazelisk build :visqol 을 다시 실행하세요.")
