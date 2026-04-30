#!/usr/bin/env python3
"""
patch_workspace_armadillo.py — WORKSPACE의 armadillo http_archive를
brew 설치 경로의 new_local_repository로 교체

사용법:
  python3 patch_workspace_armadillo.py /opt/homebrew/opt/armadillo
"""

import re, sys, os

arma_prefix = sys.argv[1] if len(sys.argv) > 1 else "/opt/homebrew/opt/armadillo"

ws_path = "WORKSPACE"
if not os.path.exists(ws_path):
    print(f"[!] WORKSPACE 파일이 없습니다: {os.path.abspath(ws_path)}")
    sys.exit(1)

with open(ws_path) as f:
    content = f.read()

# SourceForge URL 포함된 armadillo http_archive 블록 탐지
OLD = re.compile(
    r'(# Armadillo Headers.*?\n)'      # 주석 줄
    r'http_archive\(\s*\n'
    r'    name = "armadillo_headers",\s*\n'
    r'.*?'                              # 중간 내용 (lazy)
    r'\)',
    re.DOTALL,
)

NEW = f"""# Armadillo Headers (brew local — SourceForge 9.860.2 URL 404 workaround)
new_local_repository(
    name = "armadillo_headers",
    path = "{arma_prefix}",
    build_file_content = \"\"\"
cc_library(
    name = "armadillo_header",
    hdrs = glob(["include/armadillo", "include/armadillo_bits/*.hpp"]),
    includes = ["include/"],
    visibility = ["//visibility:public"],
)
\"\"\",
)"""

m = OLD.search(content)
if m:
    content = content[:m.start()] + NEW + content[m.end():]
    with open(ws_path, "w") as f:
        f.write(content)
    print(f"[✓] WORKSPACE armadillo 패치 완료 (→ {arma_prefix})")
elif "new_local_repository" in content and "armadillo_headers" in content:
    print("[i] WORKSPACE armadillo 이미 new_local_repository로 설정됨 (건너뜀)")
else:
    print("[!] armadillo http_archive 블록을 찾지 못했습니다. 수동으로 확인하세요.")
    sys.exit(1)
