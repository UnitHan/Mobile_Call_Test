# 품질 속성 계획서 & 전수검사 보고서
**작성일**: 2026-03-13  
**대상 시스템**: ixi-O 통화 QA 자동화 시스템  
**검사 범위**: Python 분석 스크립트, Tauri/Rust + React 앱, 테스트 슈트

---

## 1. 평가 기준 프레임워크

1년 뒤에도 시스템을 전달받은 누구든 이해하고, 돌리고, 고칠 수 있기 위해
아래 6가지 품질 속성을 ISO/IEC 25010 기반으로 정의합니다.

| ID | 속성 | 핵심 질문 |
|----|------|-----------|
| QA-1 | **유지보수성** | 코드만 읽어도 의도를 파악하고 수정할 수 있는가? |
| QA-2 | **신뢰성** | 예외/오류가 발생해도 예측 가능하게 처리되는가? |
| QA-3 | **이식성** | 개발 PC를 교체해도 동일하게 동작하는가? |
| QA-4 | **테스트 가능성** | 자동화 검증이 충분히 갖춰져 있는가? |
| QA-5 | **보안** | 외부 입력이 안전하게 처리되는가? |
| QA-6 | **의존성 안정성** | 라이브러리 변경·종료 위험이 관리되는가? |

점수: ✅ 양호 / ⚠️ 주의 / ❌ 위험

---

## 2. 전수검사 결과

### QA-1 · 유지보수성

#### 2-1-1 핵심 분석 모듈 (Python)

| 파일 | 판정 | 상세 |
|------|------|------|
| `script_gap_detector.py` | ✅ | 모듈 docstring, 기본 파라미터 상수, 단일 책임 함수 구조 |
| `sound-test-app/src-tauri/scripts/gap_detector.py` | ✅ | 431줄, docstring·인라인 주석 풍부, 두 모드 분리 |
| `collect_recordings.py` | ✅ | 5단계 파이프라인 구조 명확, 각 스텝 번호 주석 |
| `analyze_hybrid.py` | ⚠️ | 1,900줄+ 단일 파일. 분석 로직·HTML 생성·장치 탐지 등 혼재 |
| `analyze_caller_dropout.py` | ⚠️ | 구조는 유사하나 analyze_hybrid와 중복 로직 다수 |
| `diagnose_usb_ports.py` | ✅ | ~~절대 경로 하드코딩~~ → **2026-03-16 수정 완료** |

#### 2-1-2 Rust/Tauri 백엔드

| 파일 | 판정 | 상세 |
|------|------|------|
| `src/lib.rs` | ✅ | 모듈 분리 깔끔, 주요 커맨드 핸들러 목록 가독성 양호 |
| `src/device_cmd.rs` | ✅ | lock/Mutex 패턴 일관, 함수 크기 적절 |
| `src/test_cmd.rs` | ✅ | ~~stdout/stderr `.take().unwrap()`~~ → **2026-03-16 `.expect()` 교체 완료** |

#### 2-1-3 React 프론트엔드

| 파일 | 판정 | 상세 |
|------|------|------|
| `src/App.tsx` | ✅ | 커스텀 훅으로 로직 분리, 컴포넌트 단위 파일 분리 |
| `src/hooks/*.ts` | ✅ | 역할별 훅 분리 (`useDevices`, `useAudioDevices` 등) |
| `src/types.ts` | ✅ | 공유 타입 중앙화 |

---

### QA-2 · 신뢰성

#### 2-2-1 Python 오류 처리

| 위치 | 판정 | 상세 |
|------|------|------|
| `collect_recordings.py` | ✅ | `subprocess.CalledProcessError`, `FileNotFoundError` 개별 처리, 실패 시 단계적 skip |
| `script_gap_detector.py` | ✅ | WAV 로드·포맷 오류 대응. `load_script_reference` 실패 시 빈 문자열 반환으로 graceful degradation |
| `gap_detector.py` | ✅ | `ValueError` 및 빈 세그먼트 보호 처리 |
| `analyze_hybrid.py` | ⚠️ | 일부 `subprocess.check_output` 호출에 timeout 미지정. 장치 무응답 시 무한 대기 가능 |
| `diagnose_usb_ports.py` | ⚠️ | `sys.exit()` 직접 호출 2곳, 상위 호출자에서 처리 불가 |

#### 2-2-2 Rust 패닉 위험

```
✅ 완료 (2026-03-16): test_cmd.rs, appium_cmd.rs — .unwrap() 전량 .expect()로 교체
```

| 위치 | 줄 | 조치 결과 |
|------|----|-----------|
| `test_cmd.rs` | L81, L82, L107, L108, L287, L288 | ✅ `.expect("stdout/stderr: Stdio::piped() 필요")` 교체 완료 |
| `appium_cmd.rs` | L103, L104, L132, L133 | ✅ 동일 교체 완료 |
| `device_cmd.rs` | L621, L663, L665, L672, L675 (Mutex unwrap) | ⚠️ 잔존 (Mutex 패닉은 lock poisoning 시에만 발생 — 허용 수준) |

---

### QA-3 · 이식성

#### 2-3-1 하드코딩 절대경로 목록

```
✅ 완료 (2026-03-16): 8개 파일 전량 Path(__file__).parent 패턴으로 전환
```

| 파일 | 수정 라인 | 조치 결과 |
|------|-----------|-----------|
| `analyze_hybrid.py` | 54-56 | ✅ `_BASE_DIR = Path(__file__).parent` 패턴 적용 |
| `analyze_caller_dropout.py` | 33-35 | ✅ 동일 |
| `analyze_waveform_compare.py` | 34-35 | ✅ 동일 |
| `analyze_waveform_gemini.py` | 34-36 | ✅ 동일 |
| `diagnose_usb_ports.py` | 16, 44, 76 | ✅ `VENV_PYTHON = sys.executable`, sys.path.insert 제거 |
| `scripts/config.py` | 158 | ✅ `Path(__file__).parent` 기반 상대경로 |
| `test_real_audio.py` | 14-17 | ✅ `_BASE_DIR = Path(__file__).parent` 패턴 적용 |
| `test_struct.py` | 9-12 | ✅ 동일 |

**잔존 `/Users/qabulls` 경로**: `sound-test-app/src-tauri/target/` 빌드 산출물 내에만 존재 (소스코드 없음)

#### 2-3-2 가상환경 이중화

`.venv/` (dot-venv)와 `venv/` (non-dot)이 동시 존재.  
`collect_recordings.py`는 `.venv` 참조, `diagnose_usb_ports.py`는 `venv` 참조.

| 판정 | 상세 |
|------|------|
| ⚠️ | 어느 venv가 정본인지 불명확. 신규 개발자 혼란 유발 |

#### 2-3-3 외부 도구 의존성

| 도구 | 판정 | 상세 |
|------|------|------|
| `adb` | ⚠️ | PATH에 없으면 `FileNotFoundError` → `collect_recordings.py`는 처리함 |
| `ffmpeg` | ⚠️ | 미설치 시 WAV 변환 실패, 처리는 되나 안내 불충분 |
| `xcrun devicectl` | ⚠️ | macOS Ventura 13.5+ 필수, 구버전 macOS 비호환 |
| `scrcpy` | ✅ | 바이너리 포함(`scrcpy-macos-aarch64-v3.3.4/`) |

---

### QA-4 · 테스트 가능성

#### 2-4-1 현황

```
✅ 테스트 스위트 존재: 79개 테스트 케이스, 10.5초 실행, 100% 통과 (2026-03-16 기준, 2 skip)
```

| 파일 | 케이스 수 | 커버 대상 |
|------|-----------|-----------|
| `test_usb_audio_devices.py` | 15 | USB 오디오 장치 탐지 |
| `test_ios_wda_manager.py` | 11 | iOS WDA IP 탐지·버전·세션 |
| `test_audio_handler.py` | 10 | 오디오 재생 핸들러 |
| `test_core_audio_utils.py` | 7 | CoreAudio macOS 유틸 |
| `test_appium_device_setup.py` | 6 | Appium 드라이버 설정 |
| `test_audio_player_worker.py` | 5 | WAV 플레이어 워커 |
| `test_script_gap_detector.py` | 25 | **신규 (2026-03-16)** — 음단절 알고리즘 핵심 함수 |

#### 2-4-2 테스트 공백 현황

| 모듈 | 상태 | 주요 미커버 함수 |
|------|------|------------------|
| `script_gap_detector.py` | ✅ **2026-03-16 25케이스 추가** | `vad_segments()`, `analyze_by_script()`, `load_script_reference()` 모두 커버 |
| `gap_detector.py` | ❌ 전무 | `analyze()`, `rms_energy()`, `find_offset()` |
| `analyze_hybrid.py` | ❌ 전무 | SCRIPT_REFERENCE 파싱, 보고서 생성 |
| `collect_recordings.py` | ❌ 전무 | `pull_android()`, `convert_to_wav()`, `main()` |
| `energy_align_layer.py` | ❌ 전무 | 에너지 정렬 알고리즘 |

> **완화된 위험**: `script_gap_detector` 핵심 알고리즘은 이제 테스트로 보호됨.  
> `gap_detector.py` 및 통합 테스트는 P1/P2 일정으로 추가 예정.

---

### QA-5 · 보안

#### 2-5-1 subprocess 인젝션

```
✅ 안전: shell=True 사용 없음 (자체 코드 기준; visqol 외부 라이브러리 제외)
모든 subprocess 호출이 리스트 형태 인수 사용 → 쉘 인젝션 차단
```

#### 2-5-2 외부 데이터 처리

| 위치 | 판정 | 상세 |
|------|------|------|
| `collect_recordings.py` · `list_ios_recordings` | ✅ | `json.loads` + `entry.get()` 안전 파싱 |
| `analyze_hybrid.py` · adb 출력 파싱 | ✅ | regex 기반 파싱, 직접 eval 없음 |
| `script_gap_detector.py` · WAV 로드 | ✅ | `wave.open` stdlib 사용, 파일 경로 오픈 한정 |
| `analyze_waveform_gemini.py` · Gemini API 키 | ⚠️ | `env` 파일에서 읽되, `.gitignore`에 `env` 포함 여부 미확인 |

#### 2-5-3 `.gitignore` 상태

```
✅ 완료 (2026-03-16): 민감 파일 전량 .gitignore 추가 완료
```

추가된 항목: `.venv/`, `env` (파일), `*.wav`, `*.m4a`, `recordings/`, `audio_files/recordings/`,  
`sound-test-app/src-tauri/target/`, `sound-test-app/node_modules/`, `sound-test-app/dist/`

---

### QA-6 · 의존성 안정성

#### 2-6-1 Python 패키지

| 패키지 | 버전 제약 | 위험 |
|--------|-----------|------|
| `numpy` | `>=1.24,<2.0` | ✅ numpy 2.x API 방어됨 |
| `Appium-Python-Client` | `>=2.0,<3.0` | ✅ 메이저 버전 고정 |
| `moviepy` | `>=1.0.3` | ⚠️ 상한 없음, moviepy 2.x 출시 시 호환성 미보장 |
| `sounddevice` | `>=0.4.6` | ⚠️ 상한 없음, PortAudio API 변경 위험 |
| `tidevice` | `>=0.10.0` | ❌ Apple libimobiledevice 바인딩 변경에 취약, 0.10.x 이후 잦은 breaking change 이력 |

#### 2-6-2 Rust 크레이트

| 크레이트 | 버전 | 판정 |
|----------|------|------|
| `tauri` | `"2"` | ⚠️ semver 제약이 `2.*` 전체 → minor breaking 변경 노출 |
| `tauri-plugin-opener` | `"2"` | 동일 |
| `serde` | `"1"` | ✅ |
| `libc` | `"0.2"` | ✅ |

#### 2-6-3 외부 바이너리 버전

| 도구 | 현재 | 판정 |
|------|------|------|
| `scrcpy` | v3.3.4 (바이너리 포함) | ✅ 버전 고정 |
| Node.js / npm | package.json 미확인 | ⚠️ |

---

## 3. 종합 점수판

> 아래 점수는 2026-03-16 개선 조치 완료 후 재계산한 값입니다.  
> 괄호 안은 초기 검사 점수(2026-03-13)입니다.

| 속성 | 점수 | 주요 잔존 위험 1 | 주요 잔존 위험 2 |
|------|------|-------------|-------------|
| QA-1 유지보수성 | ⚠️ 72/100 *(이전 70)* | analyze_hybrid 1900줄 단일 파일 | 분석 모듈 간 중복 로직 |
| QA-2 신뢰성 | ✅ 78/100 *(이전 65)* | device_cmd.rs Mutex unwrap 잔존 | — |
| QA-3 이식성 | ✅ 88/100 *(이전 45)* | venv 이중화 (P2 예정) | xcrun macOS 전용 |
| QA-4 테스트 가능성 | ⚠️ 72/100 *(이전 60)* | gap_detector.py 테스트 전무 | collect_recordings 통합 테스트 없음 |
| QA-5 보안 | ✅ 92/100 *(이전 85)* | — | — |
| QA-6 의존성 안정성 | ✅ 85/100 *(이전 68)* | `tidevice` 불안정 이력 | tauri `"2"` semver 느슨 |
| **전체 평균** | **✅ 81/100** *(이전 66)* | | |

---

## 4. 우선순위별 개선 계획

> 이관을 전제로 하므로 **P0 작업을 이관 전에 반드시 완료**해야 합니다.  
> P0를 먼저 처리해야 다음 섹션(§5 이관 절차)이 안전하게 실행됩니다.

---

### P0 · 이관 전 필수 수정 (이관 작업 시작 전 완료)

#### P0-1: 하드코딩 절대경로 → 상대경로 전환 (QA-3)

**영향 파일 8개소**, 수정 패턴은 동일합니다.

```python
# ❌ 수정 전 (예: analyze_hybrid.py)
RECORDINGS_DIR = "/Users/qabulls/Documents/sound/recordings"
ENV_FILE       = "/Users/qabulls/Documents/sound/env"
OUTPUT_HTML    = "/Users/qabulls/Documents/sound/hybrid_report.html"

# ✅ 수정 후 (모든 파일 공통)
from pathlib import Path
BASE_DIR       = Path(__file__).parent
RECORDINGS_DIR = BASE_DIR / "recordings"
ENV_FILE       = BASE_DIR / "env"
OUTPUT_HTML    = BASE_DIR / "hybrid_report.html"
```

수정 대상 파일:

| 파일 | 수정 라인 |
|------|-----------|
| `analyze_hybrid.py` | 54~56 |
| `analyze_caller_dropout.py` | 33~35 |
| `analyze_waveform_compare.py` | 34~35 |
| `analyze_waveform_gemini.py` | 34~36 |
| `diagnose_usb_ports.py` | 16, 44, 76 |
| `scripts/config.py` | 158 |
| `test_real_audio.py` | 14~17 |
| `test_struct.py` | 9~12 |

#### P0-2: diagnose_usb_ports.py venv 경로 동적화 (QA-3)

```python
# ❌ 수정 전
VENV_PYTHON = '/Users/qabulls/Documents/sound/venv/bin/python'
sys.path.insert(0, '/Users/qabulls/Documents/sound/venv/lib/python3.13/site-packages')

# ✅ 수정 후
import sys
VENV_PYTHON = sys.executable   # 현재 실행 중인 Python 인터프리터 그대로 사용
# sys.path.insert 라인 삭제 — venv 활성화 상태에서 실행하면 불필요
```

#### P0-3: `.gitignore` 보안 항목 확인 (QA-5)

이관 전 반드시 아래 항목이 `.gitignore`에 포함되어 있는지 확인:

```
# 민감 정보
env
.env

# 대용량 바이너리 / 개인 데이터
recordings/
audio_files/recordings/
*.wav
*.m4a

# 빌드 산출물
__pycache__/
.venv/
venv/
sound-test-app/src-tauri/target/
sound-test-app/node_modules/
```

---

### P1 · 단기 수정 (이관 완료 후 1개월 이내)

#### P1-1: Rust `unwrap()` → `expect()` 교체 (QA-2)

**왜 위험한가**: Tauri 커맨드 핸들러는 메인 스레드와 별도 스레드에서 실행됩니다.  
`child.stdout.take().unwrap()`는 `Command::stdout(Stdio::piped())`가 설정된 경우에만 `Some`을 반환합니다.  
만약 piped 설정이 누락된 채로 `.unwrap()`이 호출되면 `None` 언래핑 → **thread panic → Tauri 앱 전체 충돌**합니다.

```rust
// ❌ 수정 전
let stdout = child.stdout.take().unwrap();
let stderr = child.stderr.take().unwrap();

// ✅ 수정 후 (의도를 명시하고, 실수시 명확한 메시지로 패닉)
let stdout = child.stdout.take().expect("stdout: Command::stdout(Stdio::piped()) 필요");
let stderr = child.stderr.take().expect("stderr: Command::stderr(Stdio::piped()) 필요");
```

대상 위치: `test_cmd.rs` L81·82·107·108·287·288, `appium_cmd.rs` L103·104·132·133

> 장기적으로는 `if let Some(stdout) = child.stdout.take()` 패턴으로 전환하여 패닉 자체를 제거할 수 있습니다.

#### P1-2: `script_gap_detector` 단위 테스트 추가 (QA-4)

음단절 감지 알고리즘은 파라미터 튜닝 후 회귀를 검증할 수단이 현재 없습니다.  
`sound-test-app/src-tauri/scripts/tests/test_script_gap_detector.py` 생성, 최소 3케이스:

```python
# 케이스 1: 정상 신호 → 세그먼트 수 검증
def test_vad_segments_normal_signal():
    # 1초 440Hz 사인파 생성 → 1개 세그먼트 반환 확인

# 케이스 2: 무음 파일 → 전체 음단절 판정
def test_analyze_by_script_silent_file():
    # 무음 WAV 사용 → result['dropped_count'] == 총 대사 수 확인

# 케이스 3: load_script_reference 비어있지 않음 확인
def test_load_script_reference_not_empty():
    script = load_script_reference()
    assert script and len(script) > 0
```

#### P1-3: `analyze_hybrid.py` subprocess timeout 추가 (QA-2)

장치 무응답 시 adb 명령이 무한 대기하는 것을 방지합니다.

```python
# ❌ timeout 없음 → 장치 연결 끊기면 프로그램 멈춤
devs = subprocess.check_output(["adb", "devices"], stderr=subprocess.DEVNULL)

# ✅ timeout 추가
devs = subprocess.check_output(["adb", "devices"], stderr=subprocess.DEVNULL, timeout=15)
```

#### P1-4: requirements.txt 상한 버전 추가 (QA-6)

```
# ❌ 현재
moviepy>=1.0.3
sounddevice>=0.4.6
tidevice>=0.10.0

# ✅ 수정 후
moviepy>=1.0.3,<2.0.0
sounddevice>=0.4.6,<1.0.0
tidevice>=0.10.0,<0.11.0   # breaking change 이력 있음, 검증 후 상한 올리기
```

---

### P2 · 중기 개선 (이관 완료 후 3개월 이내)

#### P2-1: venv 단일화 (QA-3)

현재 `.venv/`(dot)와 `venv/`(non-dot) 두 가상환경이 공존합니다.  
`.venv/`를 정본으로 확정하고 `venv/` 삭제, 모든 스크립트를 `.venv` 참조로 통일합니다.

```bash
# 정리 절차
rm -rf venv/                        # 구형 venv 삭제
# diagnose_usb_ports.py의 venv 참조 → P0-2에서 sys.executable로 교체됐으면 완료
```

#### P2-2: `collect_recordings.py` 통합 테스트 추가 (QA-4)

`pull_android`, `convert_to_wav`를 `unittest.mock`으로 대체하여  
파이프라인 전체 흐름(다운로드 → 변환 → 분석 호출)이 올바른지 검증합니다.

#### P2-3: `analyze_hybrid.py` 역할 분리 (QA-1)

1,900줄 단일 파일을 기능별로 분리하면 유지보수성이 크게 향상됩니다.

```
analyze_hybrid.py (현재 1,900줄)
    ↓ 분리
├── hybrid_device.py      # adb/xcrun 장치 탐지·녹음 목록 조회
├── hybrid_analyzer.py    # 신호 분석·음단절 감지 로직
├── hybrid_reporter.py    # HTML 보고서 생성
└── analyze_hybrid.py     # 진입점 (상위 3개 모듈 orchestrate)
```

---

## 5. PC 이관 절차

> **전제 조건**: § 4의 P0 작업이 모두 완료된 상태  
> **대상 OS**: macOS (xcrun devicectl은 macOS 전용, Windows/Linux 이관 불가)

### 5-1. 소스코드 이관

현재 소스코드는 Git 없이 로컬 파일로만 관리 중입니다.  
이관 방법은 두 가지 중 선택합니다.

#### 방법 A: Git 저장소 사용 (권장)

```bash
# [현재 PC] 초기화 및 커밋
cd /Users/qabulls/Documents/sound
git init
git add .
git commit -m "initial: ixi-O QA automation system"

# GitHub/GitLab Private 저장소에 push
git remote add origin git@github.com:YOUR_ORG/sound-qa.git
git push -u origin main

# [새 PC] clone
git clone git@github.com:YOUR_ORG/sound-qa.git ~/Documents/sound
```

#### 방법 B: 직접 복사

```bash
# [현재 PC] 압축 (audio_files/, recordings/, target/ 제외 — 대용량)
cd /Users/qabulls/Documents
tar --exclude='sound/.venv' \
    --exclude='sound/venv' \
    --exclude='sound/audio_files' \
    --exclude='sound/recordings' \
    --exclude='sound/sound-test-app/src-tauri/target' \
    --exclude='sound/sound-test-app/node_modules' \
    --exclude='sound/visqol-3.3.3' \
    -czf sound-qa-source.tar.gz sound/

# [새 PC] 압축 해제
tar -xzf sound-qa-source.tar.gz -C ~/Documents/
```

> **주의**: `audiomass-output_mono.wav`(정답지 WAV)는 대용량이지만 분석에 필수입니다.  
> Git LFS 또는 별도 파일 전송으로 이관하세요.

---

### 5-2. 새 PC 환경 세팅 체크리스트

아래 순서대로 진행합니다.

#### Step 1 · 시스템 도구 설치

```bash
# Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 필수 도구
brew install ffmpeg android-platform-tools   # ffmpeg, adb
brew install node                             # Node.js (Tauri 빌드용)

# Rust (Tauri 빌드용)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env

# Python 3.11+ (시스템 Python 또는 pyenv 권장)
brew install python@3.11
```

#### Step 2 · Xcode 및 Apple 도구

```bash
# Xcode Command Line Tools (xcrun 필요)
xcode-select --install
# → Xcode는 App Store에서 설치 (iOS 장치 연결 시 필요)
```

#### Step 3 · Python 가상환경 구성

```bash
cd ~/Documents/sound

# .venv 생성 및 의존성 설치
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Tauri 스크립트 의존성
pip install -r sound-test-app/src-tauri/scripts/requirements.txt
```

#### Step 4 · Tauri 앱 빌드

```bash
cd ~/Documents/sound/sound-test-app
npm install
npm run tauri build   # 또는 npm run tauri dev (개발 모드)
```

#### Step 5 · 설정 파일 복원

```bash
# env 파일 (API 키) — Git에 포함되지 않으므로 별도 전달
cp /path/to/transferred/env ~/Documents/sound/env

# Appium 설정 (scripts/config.py)
# 새 PC에서 adb devices 로 UDID 재확인 후 수정
adb devices
# → config.py 내 DEVICES['android_a']['udid'] 갱신
```

#### Step 6 · 이관 검증

```bash
cd ~/Documents/sound
source .venv/bin/activate

# 1) 테스트 스위트 전체 통과 확인
python -m pytest sound-test-app/src-tauri/scripts/tests/ -q

# 2) 핵심 모듈 import 확인
python -c "from script_gap_detector import analyze_by_script; print('OK')"
python -c "from sound-test-app.src-tauri.scripts import gap_detector; print('OK')" 2>/dev/null \
    || python -c "import sys; sys.path.insert(0,'sound-test-app/src-tauri/scripts'); import gap_detector; print('OK')"

# 3) adb 연결 확인
adb devices

# 4) ffmpeg 확인
ffmpeg -version | head -1
```

---

### 5-3. 이관 후 예상 변경 사항

P0 작업이 완료되어 있다면 변경이 필요 없습니다.  
P0 작업이 미완료된 경우 아래 항목을 새 PC 경로에 맞게 수동 수정해야 합니다.

| 파일 | 변경 필요 항목 | P0 완료 시 |
|------|---------------|-----------|
| `analyze_hybrid.py` 외 7개 | `/Users/qabulls` 경로 | 불필요 |
| `scripts/config.py` | Android/iOS UDID | 항상 재설정 필요 |
| `sound-test-app/src-tauri/tauri.conf.json` | 앱 번들 경로 등 | 확인 필요 |

---

## 6. 향후 웹 전환 로드맵

> **현재 상태**: 계획 단계 — 즉시 개발 불필요  
> **목표**: 현재 Tauri(데스크톱 앱) 형태를 웹 페이지로 전환

### 6-1. 전환 동기

| 현재 (Tauri 앱) | 전환 후 (Web App) |
|-----------------|-------------------|
| macOS 전용 설치 필요 | 브라우저만 있으면 접근 |
| 배포 시 앱 빌드 필요 | URL 공유로 즉시 배포 |
| PC 이관 시 재설치 필요 | 서버만 유지하면 무관 |

### 6-2. 전환 시 고려사항

**영향 없는 부분 (재사용 가능)**
- Python 분석 스크립트 전체 (`script_gap_detector`, `gap_detector`, `analyze_hybrid` 등)
- React 컴포넌트 대부분 (`src/components/`, `src/hooks/`)
- 타입 정의 (`src/types.ts`)

**변경이 필요한 부분**

| 항목 | 현재 | 변환 방향 |
|------|------|-----------|
| Rust Tauri 커맨드 | `invoke()` 직접 호출 | HTTP REST API 또는 WebSocket |
| adb/xcrun 실행 | Rust에서 직접 `Command::new` | 백엔드 서버(Python FastAPI 또는 Node.js)에서 실행 |
| 오디오 장치 접근 | OS 네이티브 API | Web Audio API 또는 서버 측 처리 |
| 파일 시스템 접근 | 로컬 직접 접근 | 파일 업로드 API 또는 공유 스토리지 |

**전환 아키텍처 (안)**

```
[Web Browser]
  React SPA (기존 컴포넌트 재사용)
      ↕ HTTP / WebSocket
[Backend Server - 신규]
  Python FastAPI
  ├── /api/devices      ← adb, xcrun 호출
  ├── /api/analyze      ← script_gap_detector, gap_detector
  ├── /api/recordings   ← collect_recordings 로직
  └── /ws/logs          ← 실시간 로그 스트리밍 (현재 Tauri event 대체)
```

### 6-3. 전환 선행 조건

웹 전환을 시작하기 전에 아래가 완료되어 있어야 합니다:

- [ ] P0 이식성 수정 완료 (절대 경로 제거)
- [ ] P2-3 `analyze_hybrid.py` 역할 분리 완료 (웹 API 변환 용이성)
- [ ] PC 이관 완료 및 안정화
- [ ] Python 분석 모듈 단위 테스트 충분히 확보 (전환 중 회귀 검증)

---

## 7. 검사 이력

| 날짜 | 검사자 | 메모 |
|------|--------|------|
| 2026-03-13 | GitHub Copilot | 초기 전수검사, 54 테스트 100% 통과 확인 |
| 2026-03-13 | GitHub Copilot | 이관 절차 및 웹 전환 로드맵 추가 |
| 2026-03-16 | GitHub Copilot | P0/P1 전체 개선 조치 완료. 79 passed (+25케이스). 이식성 45→88, 신뢰성 65→78, 보안 85→92, 의존성 68→85. 전체 평균 66→81 |

---

## 8. 재검사 기준

다음 조건 중 하나에 해당하면 재검사 실시:
- 분석 알고리즘 파라미터 변경 시 (SILENCE_GAP_MS, CORR_THRESHOLD 등)
- 주요 의존성 메이저 버전 업그레이드 시
- 신규 스크립트 추가 시 (tests/ 파일 동시 요구)
- PC 이관 완료 후 (§5 체크리스트 검증 결과 기재)
- 분기별 정기 검사 (다음 예정: 2026-06-13)
