# ixi-O 통화 음단절 자동 분석 시스템 — 기술 가이드

> **대상 독자**: QA 팀원, 신규 개발자, 빌드/릴리즈 담당자
> **최종 수정**: 2026-03-05

---

## 목차

1. [개요](#1-개요)
2. [테스트 목적 및 요구사항](#2-테스트-목적-및-요구사항)
3. [기술 스택 및 아키텍처](#3-기술-스택-및-아키텍처)
4. [구현 내용](#4-구현-내용)
5. [주요 시나리오](#5-주요-시나리오)
6. [실행 방법 (Quick Start)](#6-실행-방법-quick-start)
7. [보고서 읽는 법](#7-보고서-읽는-법)
8. [디렉터리 구조](#8-디렉터리-구조)
9. [FAQ / 트러블슈팅](#9-faq--트러블슈팅)

---

## 1. 개요

ixi-O(AI 콜센터 자동응답 앱)는 **iOS 앱이 발화하고, 상대방 Android 폰이 수신**하는 형태로 동작합니다.  
현장에서 반복적으로 보고된 문제는 **수신 쪽(Android)에서 특정 구간의 음성이 들리지 않는 현상** — 이른바 "음단절"입니다.

이 시스템은 다음 두 스크립트로 구성됩니다:

| 스크립트 | 역할 |
|---|---|
| `collect_recordings.py` | Android/iOS 디바이스에서 녹음 파일 자동 수집 |
| `analyze_hybrid.py` | 수집된 녹음을 AI + 신호처리로 분석 → HTML 보고서 생성 |

**한 줄 요약**: 통화 테스트 후 `python collect_recordings.py` 한 번으로 수집부터 AI 분석 보고서까지 자동 완료됩니다.

---

## 2. 테스트 목적 및 요구사항

### 2-1. 핵심 문제

```
iOS ixi-O 앱이 발화한 음성이
  ┌──────────────────────────┐
  │  iPhone 로컬 녹음         │  ← 깨끗하게 들림 ✅
  └──────────────────────────┘
  ┌──────────────────────────┐
  │  VoIP 네트워크 → Android  │  ← 구간 음단절 발생 ❌
  └──────────────────────────┘
```

두 경로는 **동일한 발화 소스**이므로, 차이가 발생하면 그 원인은 **iOS 앱의 VoIP 오디오 파이프라인** 내부에 있다고 판단할 수 있습니다.

### 2-2. 전통적 테스트 방법의 한계

| 기존 방법 | 문제점 |
|---|---|
| 사람이 직접 청취 비교 | 반복 재생 필요, 피로도 ↑, 타임스탬프 기록 어려움 |
| 단순 파형 에너지 비교 | 묵음 구간은 탐지해도 "대본의 어느 발화인지" 알 수 없음 |
| 단일 플랫폼만 녹음 | 기준 음원 없어 앱 결함인지 네트워크 결함인지 구분 불가 |

### 2-3. 테스트 요구사항

| # | 요구사항 |
|---|---|
| R-01 | iOS 발화와 Android 수신 녹음을 **동시** 수집할 수 있을 것 |
| R-02 | 음단절 발생 **타임스탬프(ms)**와 **누락된 대본 내용**을 함께 리포팅 |
| R-03 | 음단절이 iOS 앱 결함인지, 수신단(Android) 네트워크 결함인지 구분 가능할 것 |
| R-04 | 비엔지니어도 결과를 이해할 수 있는 보고서 형태 |
| R-05 | CI/CD 파이프라인 연동 가능 (CLI 실행, 비대화형) |

---

## 3. 기술 스택 및 아키텍처

### 3-1. 기술 스택

| 구분 | 기술 | 용도 |
|---|---|---|
| **언어** | Python 3.12 | 전체 파이프라인 |
| **AI 분석** | Google Gemini 2.5 Flash | 두 음원을 직접 청취 → 음단절 타임스탬프 JSON 반환 |
| **신호처리** | librosa | RMS 에너지 계산, 의심 구간 힌트 생성 |
| **시각화** | matplotlib | 파형 + 마커 차트 (PNG → HTML 임베드) |
| **파일 수집** | adb (Android), xcrun devicectl (iOS) | 디바이스에서 녹음 파일 PC로 복사 |
| **포맷 변환** | ffmpeg | m4a → WAV 16kHz mono |
| **보고서** | HTML (인라인 CSS) | 브라우저에서 바로 열기 가능, 첨부 공유 용이 |

### 3-2. 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────────┐
│                         테스트 실행 PC (macOS)                    │
│                                                                    │
│  [collect_recordings.py]                                          │
│    │                                                               │
│    ├── adb pull ──────────────── Android 폰                       │
│    │    /sdcard/Recordings/ixiO/                                   │
│    │    *.m4a → ffmpeg → recording_android_YYYYMMDD_HHMMSS_N.wav  │
│    │                                                               │
│    ├── xcrun devicectl copy ──── iPhone                           │
│    │    com.lguplus.aicallagent 앱 Documents/                     │
│    │    *.m4a → ffmpeg → recording_iOS_YYYYMMDD_HHMMSS_N.wav      │
│    │                                                               │
│    └── python analyze_hybrid.py  ◄──────────────────────┐        │
│                                                           │        │
│  [analyze_hybrid.py]                                      │        │
│    │                                                       │        │
│    ├── librosa.load() ── 두 WAV 로드                      │        │
│    │                                                       │        │
│    ├── compute_signal_hints()                             │        │
│    │    iOS RMS vs Android RMS → 에너지 낮은 상위 N구간   │        │
│    │                                                       │        │
│    ├── Gemini 2.5 Flash API                               │        │
│    │    ┌──────────────┐  ┌──────────────┐               │        │
│    │    │  파일 1 WAV   │  │  파일 2 WAV   │ + 프롬프트   │        │
│    │    │ (iPhone 로컬) │  │(Android 수신) │              │        │
│    │    └──────────────┘  └──────────────┘               │        │
│    │         → JSON: 음단절 타임스탬프, 누락 대본, 원인   │        │
│    │                                                       │        │
│    ├── 파형 차트 생성 (matplotlib PNG → base64)           │        │
│    │                                                       │        │
│    └── hybrid_report.html 생성 ──────────────────────────┘        │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

### 3-3. 두 파일의 역할

> **중요**: "iOS 녹음" = iPhone이 **수신**한 파일이 아닙니다.  
> iOS ixi-O 앱이 **발화**한 내용을 iPhone이 **로컬 녹음**한 것입니다.

| 파일명 패턴 | 녹음 기기 | 발화 주체 | 역할 |
|---|---|---|---|
| `recording_iOS_*.wav` | **iPhone** | iOS ixi-O 앱 | ✅ **기준 파일** — 네트워크 미경유, 앱 발화 원본 |
| `recording_android_*.wav` | **Android 폰** | iOS ixi-O 앱 (동일) | 🔴 **진단 대상** — VoIP 경유, 음단절 발생 경로 |

두 파일에서 **차이가 나는 구간 = iOS ixi-O 앱 VoIP 파이프라인 결함**으로 판정합니다.

---

## 4. 구현 내용

### 4-1. collect_recordings.py

#### 흐름

```
실행
 │
 ├─ Android 연결 확인 (adb devices)
 │    └─ /sdcard/Recordings/ixiO/ 에서 최신 N개 파일 선택
 │         └─ adb pull → /tmp/
 │              └─ ffmpeg: m4a → WAV 16kHz mono
 │                   └─ recordings/recording_android_YYYYMMDD_HHMMSS_N.wav 저장
 │
 ├─ iOS 연결 확인 (xcrun devicectl list devices)
 │    └─ devicectl copy from (com.lguplus.aicallagent 앱 Documents)
 │         └─ ffmpeg: m4a → WAV 16kHz mono
 │              └─ recordings/recording_iOS_YYYYMMDD_HHMMSS_N.wav 저장
 │
 └─ (--no-analyze 없을 경우) python analyze_hybrid.py 호출
```

#### 주요 옵션

```bash
# 최신 1개씩 수집 (기본값)
python collect_recordings.py

# 최신 2개씩 수집
python collect_recordings.py --count 2

# 수집만, 분석 제외
python collect_recordings.py --no-analyze
```

#### 파일명 규칙

```
recording_iOS_20260305_091700_1.wav
           │   │       │      └─ 세션 내 순번 (1, 2, 3...)
           │   │       └─ 통화 시작 시각 HHMMSS
           │   └─ 날짜 YYYYMMDD
           └─ 플랫폼 (iOS / android)
```

---

### 4-2. analyze_hybrid.py

#### 핵심 분석 방법: 하이브리드 방식

단일 알고리즘으로는 "어느 대본 문장이 빠졌는가"를 알기 어렵습니다.  
librosa(신호처리)와 Gemini(AI 청취)를 역할 분담합니다:

| 역할 | 담당 | 이유 |
|---|---|---|
| **Primary Judge** (음단절 탐지·대본 대조) | Gemini 2.5 Flash | 사람처럼 음성을 듣고 대본과 비교 가능 |
| **힌트 제공** (의심 구간 사전 좁히기) | librosa RMS 비교 | Gemini 컨텍스트 절약, 분석 집중도 향상 |
| **시각화** | matplotlib | 파형에 마커를 찍어 직관적 이해 |

#### 주요 함수 설명

```
find_recordings()
  └─ recordings/ 폴더에서 iOS/Android 쌍을 자동 매칭
       신규 패턴 우선 → 구형 패턴 fallback

compute_signal_hints(ios_y, and_y)
  └─ 전체 구간을 window별로 RMS 계산
       iOS에너지 있는데 Android에너지 낮은 구간 = 의심 후보

gemini_hybrid_analyze(...)
  └─ 두 WAV + 대본 + librosa 힌트를 Gemini에 전달
       반환: JSON (초기음단절, 중간음단절 목록, 원인, 심각도)

_parse_gemini_json(raw)
  └─ Gemini 응답 정제 파서
       후행쉼표·주석·한글설명 자동 제거 후 json.loads()

gemini_card_html(result)
  └─ JSON → HTML 카드 렌더링

build_waveform_chart(...)
  └─ 파형 + 음단절 마커 PNG 생성 → base64 임베드
```

#### Gemini에게 전달하는 정보

```
[파일 1: iPhone 로컬 WAV]  ← 기준
[파일 2: Android 수신 WAV] ← 진단 대상
[대본 텍스트]
[librosa 힌트 JSON] — iOS 대비 Android 에너지 낮은 구간 상위 N개
```

Gemini 반환 JSON 구조:

```json
{
  "listening_summary": "두 파일 차이 요약 (2~3문장)",
  "initial_dropout": {
    "local_detected": false,
    "remote_detected": true,
    "local_first_ms": 200,
    "remote_first_ms": 3800,
    "cut_content": "안녕하십니까, 서울중앙지검 청단범죄수사 1팀...",
    "duration_ms": 3600
  },
  "mid_call_dropouts": [
    {
      "timestamp_ref_ms": 12500,
      "duration_ms": 800,
      "script_expected": "현재 박편육 수사관에게 연결해 드리겠습니다",
      "local_actual": "현재 박편육 수사관에게 연결해 드리겠습니다",
      "remote_actual": "묵음",
      "dropout_in": "수신만",
      "confidence": "high"
    }
  ],
  "root_cause": "iOS AudioSession 활성화 지연으로 통화 초기 2~3초 패킷 미전송 추정",
  "dev_pain_points": ["[iOS] AVAudioSession setActive 타이밍 점검", ...],
  "severity": "심각"
}
```

---

## 5. 주요 시나리오

### 시나리오 A — 통화 초기 음단절 (가장 흔한 케이스)

```
0ms              3800ms
├────────────────┤──────────────────────────────►
│ 로컬(기준): 앱이 발화 시작                      │
│ 수신(진단): ██████████ 묵음 ████    발화 시작   │
                 └── 이 구간이 누락 (duration_ms = 3800)
```

**예상 원인**: iOS `AVAudioSession.setActive(true)` 완료 전에 VoIP 패킷 전송 시작 → 초기 패킷 drop  
**보고서 표시**: 초기 드롭아웃 카드 — `remote_detected: true`

---

### 시나리오 B — 화자 전환 시 순간 묵음

```
박편육 발화 중 ──────┤ 임채팅으로 전환 ├──── 임채팅 발화
로컬:  ~~~~~~~~~~~ 연속 ~~~~~~~~~~~~~~~~~~~~~~~~~~
수신:  ~~~~~~~~~~~ [묵음 600ms] ~~~~~~~~~~~~~~~~~
                   └── 전환 시 버퍼 flush 누락 의심
```

**예상 원인**: 발화자(화자) 전환 시 VAD(Voice Activity Detection)가 묵음으로 오인하거나, 오디오 트랙 스위치 시 버퍼가 비워짐  
**보고서 표시**: 중간 드롭아웃 테이블 — `dropout_in: "수신만"`

---

### 시나리오 C — 특정 키워드 단어 단위 소실

```
대본: "...5억 원을 임시 보호 조치..."
로컬: "...5억 원을 임시 보호 조치..."
수신: "...       임시 보호 조치..."  ← "5억 원을" 소실
```

**예상 원인**: 네트워크 지터 보상 버퍼 오동작, 패킷 손실 복구 실패  
**보고서 표시**: 중간 드롭아웃 테이블 — `confidence: "high"`, `script_expected` 명시

---

### 시나리오 D — 두 파일 모두 초기 묵음 (앱 발화 자체 결함)

```
로컬:  ████████ 묵음 ████ 발화 시작   ← 로컬에서도 늦음
수신:  ████████ 묵음 ████ 발화 시작
```

**해석**: 수신단 문제가 아닌, **iOS 앱 자체가 발화를 늦게 시작**하는 것.  
AudioEngine 초기화 지연 또는 TTS 엔진 준비 지연일 가능성.  
**보고서 표시**: `local_detected: true`, `remote_detected: true` 모두 표시

---

### 시나리오 E — 음단절 없음 (정상 케이스)

```
로컬:  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
수신:  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~  (동일)
```

**보고서 표시**: "초기 음단절 없음 (로컬·수신 모두)" + "발화 중 드롭아웃 없음" + `severity: "없음"`

---

## 6. 실행 방법 (Quick Start)

### 사전 준비

```bash
# 1. 의존성 설치 (최초 1회)
cd /Users/qabulls/Documents/sound
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. ffmpeg 설치 (최초 1회)
brew install ffmpeg

# 3. Google AI API 키 등록
echo "GEMINI_API_KEY=your_key_here" > env
```

### 통화 테스트 절차

```
1. Android 폰, iPhone 모두 USB로 PC에 연결
2. ixi-O 앱에서 통화 실행 (대본에 따른 테스트 시나리오)
3. 통화 종료 후 PC에서 아래 명령 실행:

   python collect_recordings.py

4. 브라우저에서 hybrid_report.html 열기
```

### 개별 실행 (수집 생략, 이미 있는 파일 분석)

```bash
source .venv/bin/activate
python analyze_hybrid.py
# → hybrid_report.html 생성
```

---

## 7. 보고서 읽는 법

`hybrid_report.html`을 브라우저로 열면 다음 섹션이 표시됩니다:

```
┌─────────────────────────────────────── hybrid_report.html ───┐
│                                                                │
│  [테스트 환경 정보]  날짜, 앱버전, 단말, 분석도구             │
│                                                                │
│  ┌──── 음원 1 — 박편육·임채팅 발화 ─────────────────────────┐ │
│  │                                                            │ │
│  │  [파형 차트]  로컬(파랑) / 수신(주황) 비교                │ │
│  │               ▲ 빨간 영역 = 음단절 마커                    │ │
│  │                                                            │ │
│  │  [Gemini 분석 결과 카드]                                   │ │
│  │    • 청취 요약 (2~3줄)                                     │ │
│  │    • 통화 초기 음단절 (로컬기준 / 수신기준 시작 ms)        │ │
│  │    • 발화 중 드롭아웃 테이블:                              │ │
│  │        오프셋 | 손실길이 | 대본예상 | 로컬내용 | 수신내용  │ │
│  │    • 기술적 원인 추정                                      │ │
│  │    • 개발팀 점검 항목                                      │ │
│  │    • 심각도 배지 (없음/경미/보통/심각)                     │ │
│  └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

#### 컬럼 설명

| 컬럼 | 설명 |
|---|---|
| **오프셋** | 파일 시작부터 해당 음단절까지의 시간 (예: `00:12.5`) |
| **발생시각** | 실제 통화 시각으로 환산 (예: `09:17:12`) |
| **손실길이** | 묵음 지속 시간 (ms) |
| **대본(예상)** | 이 시점에 들려야 할 발화 내용 |
| **로컬(iPhone)·기준** | 파일 1에서 실제 들리는 내용 |
| **수신(Android)·진단대상** | 파일 2에서 실제 들리는 내용 |
| **음단절 위치** | 🔴 수신만 / 회색 로컬만 / 🟠 양쪽 |
| **확신도** | Gemini 판단 자신감 (high / medium / low) |

---

## 8. 디렉터리 구조

```
sound/
├── collect_recordings.py     # 수집 파이프라인
├── analyze_hybrid.py         # 분석 + 보고서 생성 (메인)
├── hybrid_report.html        # ← 생성된 보고서 (브라우저로 열기)
├── env                       # GEMINI_API_KEY (git 제외)
├── requirements.txt
├── .venv/                    # Python 가상환경
└── recordings/               # 수집된 WAV 파일
    ├── recording_iOS_20260305_091700_1.wav       ← 기준 파일
    ├── recording_android_20260305_091700_1.wav   ← 진단 대상
    ├── recording_iOS_20260305_091700_2.wav
    └── recording_android_20260305_091700_2.wav
```

---

## 9. FAQ / 트러블슈팅

### Q. `adb: command not found` 오류가 납니다

```bash
brew install --cask android-platform-tools
# 또는 Android Studio 설치 후 PATH에 platform-tools 추가
```

---

### Q. iOS 파일 수집이 안 됩니다 (`devicectl` 실패)

```bash
# Xcode Command Line Tools 설치 확인
xcode-select --install

# 연결된 디바이스 목록 확인
xcrun devicectl list devices
```

iPhone이 목록에 없으면 케이블 재연결 또는 신뢰 승인(iPhone 화면에서 "신뢰") 필요합니다.

---

### Q. `⚠️ Gemini 오류: JSON 파싱 실패` 메시지가 나옵니다

Gemini가 가끔 JSON 형식을 깨뜨리는 텍스트를 포함해 응답합니다.  
`_parse_gemini_json()` 함수가 후행 쉼표·주석·한글 설명 자동 정제를 시도합니다.  
계속 실패 시 보고서의 "raw" 필드를 확인해 Gemini 원문 응답을 직접 확인하세요.

---

### Q. 음단절이 없는데 보고서에 드롭아웃이 많이 잡힙니다

librosa 힌트는 에너지 비율 기반 추정으로, **오탐(false positive) 가능성**이 있습니다.  
최종 판단은 Gemini의 `confidence` 필드를 기준으로 하고, `low` 항목은 참고 수준으로 보십시오.

---

### Q. 두 파일의 길이가 달라도 됩니까?

됩니다. Gemini는 각 파일을 독립적으로 청취하고 대본을 기준으로 비교합니다.  
librosa 힌트 계산 시에는 짧은 쪽 길이에 맞춰 트리밍됩니다.

---

### Q. 새로운 테스트 시나리오(대본)를 추가하려면?

`analyze_hybrid.py` 내 `CALL_META`와 `SCRIPT_REFERENCE`를 수정합니다:

```python
CALL_META = {
    1: {
        "label":    "음원 1 — 새 시나리오 이름",
        "speakers": "발화자1(역할) · 발화자2(역할)",
    },
    ...
}
```

---

*이 문서는 `DROPOUT_TEST_GUIDE.md`로 관리됩니다. 내용 변경 시 Confluence 페이지에 동기화하세요.*
