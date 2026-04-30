# visqol-setup

macOS (Apple Silicon / Intel) 에서 **ViSQOL v3.3.3** 을 자동으로 빌드·설치하는 스크립트 패키지입니다.

macOS 13 Ventura ~ **macOS 26 Tahoe beta** 에서 발생하는 빌드 오류 3가지를 자동으로 우회합니다.

---

## 빠른 시작

```bash
# 1. 이 폴더를 대상 맥북으로 복사
# 2. visqol-3.3.3 소스가 없으면 GitHub에서 자동 다운로드됨

cd visqol-setup
chmod +x install_visqol.sh
./install_visqol.sh
```

빌드 성공 시 `visqol-3.3.3/bazel-bin/visqol` 에 바이너리가 생성됩니다.

---

## 옵션

| 옵션 | 설명 |
|------|------|
| `--visqol-dir <경로>` | `visqol-3.3.3` 소스 폴더 위치를 지정 (기본: 스크립트 상위 디렉토리) |
| `--sdk-path <경로>` | Xcode SDK 경로를 직접 지정 (기본: `xcrun --show-sdk-path` 자동 탐지) |

예시:
```bash
./install_visqol.sh --visqol-dir ~/src/visqol-3.3.3 --sdk-path /Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX15.sdk
```

---

## 포함 파일

| 파일 | 설명 |
|------|------|
| `install_visqol.sh` | 전체 설치·빌드 자동화 셸 스크립트 |
| `patch_workspace_armadillo.py` | WORKSPACE의 armadillo http\_archive를 brew 로컬 경로로 교체 |
| `patch_bazel_env.py` | Bazel 캐시 내 wrapped\_clang / libtool\_check\_unique 패치 + zlib/zutil.h fdopen 버그 수정 |

---

## 자동으로 해결하는 오류 3가지

### 오류 1 — armadillo SourceForge URL 404
```
ERROR: Failed to fetch repository 'armadillo_headers': Download failed
  https://sourceforge.net/projects/arma/files/armadillo-9.860.2.tar.xz
```

**원인**: ViSQOL WORKSPACE가 참조하는 SourceForge URL이 404.  
**해결**: `patch_workspace_armadillo.py`가 `new_local_repository`로 교체하고, brew로 설치된 armadillo를 직접 참조.

---

### 오류 2 — wrapped_clang / libtool_check_unique LC_UUID 없음
```
dyld[xxxxx]: Library not loaded ... image not found
```
또는
```
ld: can't open output file for writing ... libtool_check_unique
```

**원인**: Bazel 5.x가 내장 Mach-O 바이너리로 제공하는 `wrapped_clang`, `wrapped_clang_pp`, `libtool_check_unique`에 `LC_UUID` load command가 없어 macOS 26.x beta dyld가 실행을 거부.  
**해결**: `patch_bazel_env.py`가 해당 바이너리를 동일 기능의 **쉘 스크립트**로 교체.

---

### 오류 3 — zlib/zutil.h `fdopen` 매크로 충돌
```
error: expected expression
  #define fdopen(fd,mode) NULL
  ^
```

**원인**: zlib 헤더가 `fdopen`을 `NULL`로 매크로 정의 → macOS SDK `_stdio.h`에서 실제 `fdopen` 선언 파싱 실패.  
**해결**: `patch_bazel_env.py`가 `!defined(fdopen)` 조건에 `&& !defined(__APPLE__)` 추가.

---

## 시스템 요구사항

| 항목 | 최소 버전 |
|------|-----------|
| macOS | 13 Ventura 이상 (Apple Silicon / Intel) |
| Xcode | 15 이상 (Command Line Tools 포함) |
| Python | 3.8 이상 |
| 인터넷 연결 | brew 및 bazelisk 설치, visqol 소스 다운로드 시 필요 |

> Homebrew, bazelisk, armadillo 는 설치되어 있지 않으면 스크립트가 자동 설치합니다.

---

## 빌드 이후 사용법

```bash
# 도움말
./visqol-3.3.3/bazel-bin/visqol --help

# WAV 파일 품질 측정
./visqol-3.3.3/bazel-bin/visqol \
  --reference_file reference.wav \
  --degraded_file  degraded.wav  \
  --similarity_to_quality_model ./visqol-3.3.3/model/libsvm_nu_svr_model.txt

# 편의를 위해 PATH에 추가
export PATH="$(pwd)/visqol-3.3.3/bazel-bin:$PATH"
```

---

## 문제 해결

### Bazel 빌드 캐시 완전 초기화
```bash
cd visqol-3.3.3
bazelisk clean --expunge
```

### patch_bazel_env.py 수동 실행
```bash
python3 visqol-setup/patch_bazel_env.py
# SDK 경로 수동 지정 시
python3 visqol-setup/patch_bazel_env.py --sdk-path /path/to/MacOSX.sdk
```

### 어떤 Bazel output_base가 쓰이는지 확인
```bash
cd visqol-3.3.3
bazelisk info output_base
```

---

## 테스트 환경

| 항목 | 버전 |
|------|------|
| macOS | 26.2 beta (Tahoe) |
| Xcode | 26.2 beta |
| Apple Silicon | M 시리즈 |
| bazelisk | 1.29.0 |
| Bazel | 5.4.0 (`.bazelversion` 지정) |
| armadillo | 15.2.6 (brew) |
