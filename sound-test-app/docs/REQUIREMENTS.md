# 📑 ixi-O Sound Test App — 개발 요구사항 및 기획 문서

> **프로젝트**: ixi-O 통화 품질 자동 검증 시스템  
> **작성일**: 2026-03-31  
> **버전**: v1.0  

---

## 1. 프로젝트 목적

LG U+ ixi-O AI 통화 에이전트의 품질을 **실제 단말 기반**으로 자동 검증한다.

### 1.1 핵심 검증 항목

| # | 항목 | 설명 | 측정 방식 |
|---|------|------|-----------|
| 1 | **통화 음질** | MOS(Mean Opinion Score) 기준 통화 품질 | ViSQOL + PESQ |
| 2 | **음단절 탐지** | 통화 중 음성 끊김/손실 구간 검출 | Gemini AI + librosa 신호처리 |
| 3 | **보이스피싱 감지** | ixi-O 보이스피싱 경고 팝업 정상 작동 여부 | Appium UI 자동화 스크린샷 |
| 4 | **양방향 검증** | 발신→수신 / 수신→발신 양방향 통화 품질 | TC 정방향/역방향 구분 |

### 1.2 대상 시스템

- **테스트 대상**: LG U+ ixi-O 앱 (iOS/Android)
- **하드웨어**: CONNECT 6 8채널 USB 사운드카드, Galaxy S 시리즈, iPhone
- **분석 도구**: ViSQOL 3.3.3, Gemini AI, librosa

---

## 2. 기능 요구사항

### 2.1 TC (Test Case) 정의

#### TC_01 — 일반 통화 (정방향)
```
발신: 화자 1 (iOS/iPhone)  →  수신: 화자 2 (Android/Galaxy)
검증: MOS 점수 + 음단절 분석 + SNR
```

| 단계 | 동작 | 자동화 |
|------|------|--------|
| 1 | iOS에서 ixi-O 앱 실행 | Appium (XCUITest) |
| 2 | 키패드에서 Android 번호 입력 | Appium 터치 |
| 3 | 통화 버튼 터치 → 발신 | Appium |
| 4 | Android에서 자동 수신 | ADB shell / Appium |
| 5 | 음원 재생 (화자 1 → CONNECT 6) | Python audio_handler |
| 6 | 녹음 시작 (CONNECT 6 입력 채널) | Python call_recorder |
| 7 | 통화 종료 감지 → 녹음 중지 | call_state_detector |
| 8 | 녹음 파일 수집 | adb pull / xcrun |
| 9 | MOS 분석 (ViSQOL) | audio_quality.py |
| 10 | 음단절 분석 (Gemini + librosa) | analyze_hybrid.py |
| 11 | HTML 보고서 생성 | html_report.py |

#### TC_02 — 일반 통화 (역방향)
```
발신: 화자 2 (Android)  →  수신: 화자 1 (iOS)
검증: TC_01과 동일
```

#### TC_03 — 보이스피싱 감지 (정방향)
```
발신: 화자 1 (iOS)  →  수신: 화자 2 (Android)
검증: MOS + 음단절 + 보이스피싱 경고 팝업 스크린샷
```

#### TC_04 — 보이스피싱 감지 (역방향)
```
발신: 화자 2 (Android)  →  수신: 화자 1 (iOS)
검증: MOS + 음단절 + 보이스피싱 경고 팝업 스크린샷
```

### 2.2 실행 옵션 요구사항

| 기능 | 설명 | 구현 상태 |
|------|------|-----------|
| **TC 다중 선택** | 체크박스로 복수 TC 선택 후 순차 실행 | ✅ 구현 |
| **반복 실행** | N회 반복 (TC 단위 / 세트 단위 모드) | ✅ 구현 |
| **실패 처리** | 중단 / 계속 / 재시도 옵션 | ✅ 구현 |
| **예약 실행** | N분 후 테스트 시작 | ✅ 구현 |
| **결과 대시보드** | 게시판 형태 결과 조회 | ✅ 구현 |
| **CSV/Excel 내보내기** | 결과 데이터 다운로드 | 🔲 미구현 |

### 2.3 화자 설정 요구사항

```
화자 1 (Speaker 1)                   화자 2 (Speaker 2)
┌─────────────────┐                 ┌─────────────────┐
│ 디바이스: iPhone │                 │ 디바이스: Galaxy │
│ 역할: 발신자     │  ←── 스왑 ──→  │ 역할: 수신자     │
│ 전화번호: xxx    │                 │ 전화번호: xxx    │
│ 재생 음원: A.wav │                 │ 재생 음원: B.wav │
│ 출력 채널: L     │                 │ 출력 채널: R     │
│ 녹음 채널: ch1   │                 │ 녹음 채널: ch2   │
│ 정답지: refA.wav │                 │ 정답지: refB.wav │
└─────────────────┘                 └─────────────────┘
```

- 화자별 독립적인 음원/정답지 파일 설정
- L/R/LR 채널 선택
- 화자 즉시 스왑 기능

### 2.4 음원 프로파일 요구사항

| 필드 | 설명 |
|------|------|
| `name` | 프로파일 이름 |
| `speaker1AudioFile` | 화자 1 재생 음원 경로 |
| `speaker2AudioFile` | 화자 2 재생 음원 경로 |
| `refAudioPathS1` | 화자 1 정답지 (S1 재생→iOS 수신 비교용) |
| `refAudioPathS2` | 화자 2 정답지 (S2 재생→Android 수신 비교용) |
| `scriptPath` | 음단절 분석용 대본 텍스트 파일 |

### 2.5 디바이스/오디오 설정 요구사항

- CONNECT 6 출력 채널쌍 선택 (1-2, 3-4, 5-6)
- 녹음 채널 L/R 분리
- 파일 저장 방식: 파일 추출(adb pull) vs 직접 녹음

### 2.6 환경 점검 요구사항

| 도구 | 점검 항목 |
|------|-----------|
| ADB | 설치 여부 + 버전 |
| Appium | 설치 + 실행 상태 |
| Python | venv 활성화 + 패키지 |
| Node.js | npm/npx 사용 가능 |
| ViSQOL | 바이너리 존재 |

---

## 3. 비기능 요구사항

### 3.1 UI/UX

| 항목 | 요구사항 |
|------|----------|
| 테마 | 다크 테마 (배경 #0d1117) |
| 레이아웃 | CSS Grid 2열 구조 |
| 반응형 | 최소 1280px 이상 지원 |
| 실시간 피드백 | Tauri 이벤트 기반 로그 스트리밍 |
| 설정 저장 | localStorage 기반 영속 저장 |

### 3.2 파일 관리

| 항목 | 요구사항 | 구현 상태 |
|------|----------|-----------|
| 녹음 파일 | `YYYY-MM-DD` 폴더 자동 분류 | ✅ |
| HTML 보고서 | `reports/YYYY-MM-DD/` 폴더 자동 분류 | ✅ |
| 스크린샷 | `screenshots/YYYY-MM-DD/` 폴더 자동 분류 | ✅ |

### 3.3 빌드/배포

| 항목 | 내용 |
|------|------|
| 플랫폼 | macOS (Apple Silicon aarch64) |
| 빌드 | `npm run tauri build` → DMG |
| Python 런타임 | 앱 내 번들링 or 시스템 Python |

---

## 4. 데이터 모델

### 4.1 TcResult (테스트 결과)

```typescript
interface TcResult {
  runId: number;
  tcId: TcId;              // "TC_01" | "TC_02" | "TC_03" | "TC_04"
  sessionId: string;
  repeatIndex: number;
  startedAt: string;
  finishedAt: string;
  durationMs: number;
  status: TcStatus;        // "PASS" | "FAIL" | "ERROR" | "RUNNING" | "QUEUED"
  phase: string;
  subStatus?: string;
  iosVisqolMos?: number;
  androidVisqolMos?: number;
  snrDb?: number;
  dropoutCount?: number;
  dropoutSeverity?: string;
  dropoutReportPath?: string;
  mosReportPath?: string;
  extractedAudioPaths: string[];
  screenshotPaths: string[];
  logLines: string[];
  errorMsg?: string;
}
```

### 4.2 AudioProfile (음원 프로파일)

```typescript
interface AudioProfile {
  id: string;
  name: string;
  speaker1AudioFile?: string;
  speaker2AudioFile?: string;
  refAudioPathS1?: string;
  refAudioPathS2?: string;
  scriptPath?: string;
}
```

### 4.3 SpeakerConfig (화자 설정)

```typescript
interface SpeakerConfig {
  phoneNumber: string;
  deviceSerial: string;
  audioFile: string;
  outputDevice: string;
  outputChannel: "L" | "R" | "LR";
  recordChannel: string;
  refAudioPath: string;
}
```

---

## 5. 아키텍처 설계

### 5.1 전체 데이터 흐름

```
┌─────────────────────────────────────────────────────┐
│                    React UI (Frontend)               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│  │DeviceSec │ │SpeakerSec│ │TcSelect  │ │Dashboard│ │
│  │AudioSec  │ │ExecSec   │ │SettingsM │ │LogPanel │ │
│  └──────────┘ └──────────┘ └──────────┘ └─────────┘ │
│            ↕ Tauri invoke() IPC                      │
├─────────────────────────────────────────────────────┤
│               Rust Backend (Tauri)                   │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐     │
│  │device_cmd  │ │appium_cmd  │ │  test_cmd     │     │
│  │env_cmd     │ │state/types │ │  (23 cmds)    │     │
│  └────────────┘ └────────────┘ └──────┬───────┘     │
│                                       │ spawn        │
├───────────────────────────────────────┤──────────────┤
│            Python Test Engine                        │
│  ┌────────────────┐  ┌────────────────┐              │
│  │ixio_automated  │  │tc01_ios_caller │              │
│  │_test.py        │  │.py             │              │
│  └───────┬────────┘  └───────┬────────┘              │
│          │ Appium            │ Appium                 │
│  ┌───────┴────────┐  ┌──────┴─────────┐             │
│  │  Android (ADB) │  │  iOS (WDA)     │             │
│  └────────────────┘  └────────────────┘              │
│                                                      │
│  ┌────────────────────────────────────┐               │
│  │  CONNECT 6 (USB Audio 8ch)        │               │
│  │  재생: ch1-2 / 녹음: ch3-4        │               │
│  └────────────────────────────────────┘               │
│                                                      │
│  ┌─────────┐ ┌───────────┐ ┌────────────┐           │
│  │ViSQOL   │ │Gemini AI  │ │html_report │           │
│  │MOS 분석 │ │음단절 분석│ │보고서 생성 │           │
│  └─────────┘ └───────────┘ └────────────┘           │
└─────────────────────────────────────────────────────┘
```

### 5.2 TC 실행 시퀀스

```
사용자: TC 선택 + 시작 버튼
  ↓
[useTcRunner] invoke("run_ixio_test", { tcId, speakers, options })
  ↓
[Rust test_cmd] spawn Python: ixio_automated_test.py
  ↓
[Python]
  ├─ Appium: iOS 발신 → Android 수신
  ├─ 음원 재생 (CONNECT 6 출력)
  ├─ 녹음 (CONNECT 6 입력)
  ├─ 통화 종료 감지
  └─ 녹음 파일 수집 (adb pull / xcrun)
  ↓
[Rust] Python stdout 파싱 → TestRunResult
  ↓
[Frontend] invoke("run_dropout_analysis", { recordings })
  ↓
[Python]
  ├─ ViSQOL MOS 계산
  ├─ Gemini AI 음단절 탐지
  └─ HTML 보고서 생성
  ↓
[DashboardView] 결과 표시 + 상세 모달
```

---

## 6. 음단절 분석 파이프라인 (5단계)

```
Stage 1: VAD (Voice Activity Detection)
  음성 구간 / 무음 구간 분리

Stage 2: FFT 스펙트럼 분석
  주파수 대역별 에너지 분포

Stage 3: Cross-Correlation
  원본(정답지) ↔ 녹음 파일 시간축 정렬

Stage 4: 구간별 비교
  에너지/주파수 차이 기반 음단절 후보 검출

Stage 5: Gemini AI 3중 판정
  ├─ 판정 1: 구간별 손실 정도
  ├─ 판정 2: 패턴 분류 (끊김/잡음/왜곡)
  └─ 판정 3: 종합 심각도 등급
```

---

## 7. 향후 기획 (로드맵)

### Phase 2 — 고급 기능
- [ ] TC 병렬 실행 (다중 디바이스 동시)
- [ ] 실시간 MOS 모니터링
- [ ] 통화 중 실시간 파형 표시
- [ ] 자동 재시도 로직 고도화

### Phase 3 — 웹 마이그레이션
- [ ] Tauri IPC → REST API 전환
- [ ] 로컬 프로세스 → 서버 API
- [ ] 다중 사용자 지원
- [ ] 클라우드 기반 결과 저장

### Phase 4 — CI/CD 통합
- [ ] GitHub Actions 자동 빌드
- [ ] 테스트 리포트 자동 업로드
- [ ] Slack/Teams 알림 연동
