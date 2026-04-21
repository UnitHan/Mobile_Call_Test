# 📋 ixi-O 통화 품질 자동 검증 시스템 — 개발일지

> **프로젝트**: ixi-O Sound Test App  
> **기술 스택**: Tauri 2 (Rust) + React 19 (TypeScript) + Python (Appium/ViSQOL) + Gemini AI  
> **작성일**: 2026-03-31  

---

## 1. 프로젝트 개요

LG U+ ixi-O AI 통화 에이전트의 **통화 품질·음단절·보이스피싱 탐지**를 자동화 검증하는 Tauri 데스크톱 앱.  
하드웨어(CONNECT 6 사운드카드)와 소프트웨어(Appium, ViSQOL, Gemini AI)를 결합하여  
iOS/Android 실제 단말 기반 End-to-End 통화 테스트를 수행한다.

---

## 2. 개발 타임라인

### Phase 0 — 기반 구축 (프로젝트 초기)

| 날짜 | 작업 | 상태 |
|------|------|------|
| 초기 | Tauri 2 + React 19 + Vite 7 프로젝트 생성 | ✅ |
| 초기 | Python 분석 파이프라인 구축 (analyze_hybrid.py, audio_quality.py, html_report.py) | ✅ |
| 초기 | CONNECT 6 사운드카드 채널 매핑 (8채널 USB 오디오) | ✅ |
| 초기 | ViSQOL 3.3.3 빌드 및 MOS 점수 계산 연동 | ✅ |
| 초기 | Appium 기반 iOS/Android 자동화 프레임워크 구현 | ✅ |

### Phase 1 — 핵심 UI 컴포넌트 개발

| 날짜 | 작업 | 상태 |
|------|------|------|
| - | `AppHeader` — 앱 헤더 + 설정 버튼 + 테스트 결과 배지 | ✅ |
| - | `DeviceSection` — Android(ADB)/iOS(devicectl) 디바이스 자동 감지 및 연결 | ✅ |
| - | `SpeakerSection` — 화자 1(iOS발신)/화자 2(Android수신) 설정 + 스왑 기능 | ✅ |
| - | `AudioSection` — 음원 파일/정답지/대본 설정 | ✅ |
| - | `ExecSection` — TC 실행 제어 (시작/중지/스케줄) | ✅ |
| - | `EnvPanel` — ADB/Appium/Python 환경 상태 표시 | ✅ |
| - | `LogPanel` — 실시간 로그 스트리밍 (Tauri 이벤트) | ✅ |

### Phase 2 — TC 시스템 및 대시보드

| 날짜 | 작업 | 상태 |
|------|------|------|
| - | `TcSelectPanel` — 4개 TC 체크박스 선택 + 반복/예약 옵션 | ✅ |
| - | `DashboardView` — 게시판 형태 결과 테이블 | ✅ |
| - | `ResultDetailModal` — 상세 결과 모달 (MOS, 음단절, Gemini 분석) | ✅ |
| - | `ReportModal` — HTML 리포트 뷰어 | ✅ |
| - | TC_01~04 정의 (정방향/역방향 × 일반/보이스피싱) | ✅ |

### Phase 3 — Rust 백엔드 커맨드

| 날짜 | 작업 | 상태 |
|------|------|------|
| - | `device_cmd.rs` — ADB 무선 연결, iOS devicectl 디바이스 목록 | ✅ |
| - | `appium_cmd.rs` — Appium 서버 관리 (시작/중지/상태, 포트 4723/4724) | ✅ |
| - | `test_cmd.rs` — Python 스크립트 호출, 음단절 분석, 보고서 생성 (23개 커맨드) | ✅ |
| - | `env_cmd.rs` — tool 점검, Python venv 설정 | ✅ |
| - | `state.rs` — 전역 프로세스 Mutex 관리 (Appium, Watchdog) | ✅ |

### Phase 4 — Python 테스트 엔진

| 날짜 | 작업 | 상태 |
|------|------|------|
| - | `ixio_automated_test.py` — 메인 TC 오케스트레이터 | ✅ |
| - | `tc01_ios_caller.py` — iOS 발신 시퀀스 (키패드→통화→종료→요약) | ✅ |
| - | `android_call_handler.py` / `call_state_detector.py` — Android 수신 처리 | ✅ |
| - | `audio_handler.py` / `audio_player_worker.py` — 음원 재생 제어 | ✅ |
| - | `call_recorder.py` / `mixer_recorder.py` — G8/CONNECT6 녹음 | ✅ |
| - | `ios_wda_manager.py` — WebDriverAgent 관리 | ✅ |
| - | `device_detector.py` — 디바이스 자동 감지 | ✅ |
| - | `crash_reporter.py` — 크래시 리포트 수집 | ✅ |
| - | `core_audio_utils.py` — macOS Core Audio 유틸리티 | ✅ |

---

## 3. 최근 개발 내역 (2026-03-31 기준)

### 3.1 ixi-O 광고 배너 배치 (DeviceSection)

**작업**: DeviceSection 패널 내 ixi-O 광고 배너 이미지 삽입  
**구현 방식**: `.device-lower` flex 컨테이너로 버튼 영역(좌) + 배너(우) 수평 배치  
**CSS**: `filter: brightness(0.7) contrast(0.9)` 적용으로 다크 테마 조화  
**특이사항**: 16회 이상 반복 수정 (→ [이슈 리포트 #1](#) 참조)

### 3.2 오픈소스 라이선스 메뉴

**작업**: SettingsModal에 📜 오픈소스 라이선스 탭 추가  
**구현 내용**:
- 8개 라이선스 그룹 (MIT, Apache-2.0, MPL-2.0, BSD-3-Clause, ISC, Unicode-3.0, Zlib, 0BSD)
- 상태 기반 아코디언 (한 번에 하나만 펼침)
- `src/data/licenses.ts` — 90개 패키지 라이선스 데이터
- 저작권 표시: © 2025 QA Bulls
- 설정 팝업 너비 680px → 820px 확장

### 3.3 날짜별 폴더 정리

**작업**: 모든 생성 파일을 `YYYY-MM-DD` 하위 폴더로 자동 정리  
**적용 범위**:
| 대상 | 파일 | 경로 형식 |
|------|------|-----------|
| 녹음 파일 | `call_recorder.py`, `mixer_recorder.py` | `output_dir/2026-03-31/*.wav` |
| HTML 보고서 | `test_cmd.rs` | `sound_root/reports/2026-03-31/hybrid_report_{epoch}.html` |
| 스크린샷 | `ixio_automated_test.py`, `tc01_ios_caller.py` | `screenshots/2026-03-31/*.png` |
| 기존 파일 | `organize_recordings.py` 실행으로 일괄 이동 | 날짜 추출 후 폴더 분류 |

### 3.4 설정 탭 이름 변경

- "단말/전화번호" → "디바이스/오디오설정"

### 3.5 Rust 컴파일 에러 수정

**문제**: `test_cmd.rs` 날짜 계산 코드에서 i32/i64 타입 불일치  
**해결**: Civil calendar 변환 알고리즘(Howard Hinnant 방식)으로 전면 교체, 모든 연산 i64 통일

---

## 4. 이전 개발 이력 (누적)

### 4.1 HTML 리포트 시스템

- `html_report.py` — 파형 비교, MOS 점수, 음단절 구간을 시각화하는 HTML 보고서 생성
- `waveform_compare_report.html`, `waveform_gemini_report.html` — 보고서 템플릿
- iOS 거짓양성(false positive) 감지 로직 보정

### 4.2 TC_03/TC_04 참조 음원 매핑

- 보이스피싱 TC에서 화자별 정답지(reference audio) 분리 매핑 구현
- `refAudioPathS1` / `refAudioPathS2` 필드 추가

### 4.3 대시보드 테이블 컬럼 폭 정렬

- 게시판 d-table 컬럼 너비 통일 작업

### 4.4 TC_05 숨김 처리

- 미구현 TC_05를 UI에서 숨김

### 4.5 HDMI 인덱스 드리프트 수정

- CONNECT 6 라우팅 진단 시 HDMI 인덱스가 drift하는 문제 해결

### 4.6 MOS 점수 등급 기준 업데이트

- ViSQOL MOS 등급 체계 재조정

### 4.7 음원 대역폭 분석

- 오디오 대역폭 분석 기능 추가

### 4.8 TC_03 음원 정지 문제 수정

- 보이스피싱 TC에서 음원이 중간에 정지되는 버그 수정

---

## 5. 기술 스택 상세

| 레이어 | 기술 | 버전 | 역할 |
|--------|------|------|------|
| **프레임워크** | Tauri | 2.x | 데스크톱 앱 런타임 |
| **프론트엔드** | React | 19.x | UI 컴포넌트 |
| **빌드** | Vite | 7.x | 번들링/HMR |
| **언어(FE)** | TypeScript | 5.x | 타입 안전성 |
| **런타임(BE)** | Rust | stable | 네이티브 커맨드 |
| **자동화** | Appium | 2.x | iOS/Android UI 제어 |
| **iOS 드라이버** | XCUITest | - | iOS Appium 드라이버 |
| **Android 드라이버** | UiAutomator2 | - | Android Appium 드라이버 |
| **음질 분석** | ViSQOL | 3.3.3 | MOS 점수 산출 |
| **AI 분석** | Gemini AI | - | 음단절 컨텍스트 분석 |
| **신호처리** | librosa | - | VAD, FFT, Cross-Correlation |
| **하드웨어** | CONNECT 6 | - | 8채널 USB 사운드카드 |
| **iOS 도구** | pymobiledevice3 | - | iOS 디바이스 통신 |
| **Android 도구** | ADB (scrcpy) | 3.3.4 | Android 디바이스 제어 |

---

## 6. 프로젝트 구조

```
sound/                              # 루트
├── sound-test-app/                 # Tauri 앱 (메인)
│   ├── src/                        # React 프론트엔드
│   │   ├── components/             # 12개 UI 컴포넌트
│   │   │   ├── AppHeader.tsx
│   │   │   ├── DeviceSection.tsx
│   │   │   ├── SpeakerSection.tsx
│   │   │   ├── AudioSection.tsx
│   │   │   ├── ExecSection.tsx
│   │   │   ├── EnvPanel.tsx
│   │   │   ├── LogPanel.tsx
│   │   │   ├── TcSelectPanel.tsx
│   │   │   ├── DashboardView.tsx
│   │   │   ├── ResultDetailModal.tsx
│   │   │   ├── ReportModal.tsx
│   │   │   └── SettingsModal.tsx
│   │   ├── hooks/                  # 10개 커스텀 훅
│   │   │   ├── useDevices.ts
│   │   │   ├── useSpeakerConfig.ts
│   │   │   ├── useAudioProfiles.ts
│   │   │   ├── useAudioDevices.ts
│   │   │   ├── useTcAudioConfig.ts
│   │   │   ├── useTcRunner.ts
│   │   │   ├── useAppium.ts
│   │   │   ├── useEnvCheck.ts
│   │   │   ├── useLogs.ts
│   │   │   └── useAppVersions.ts
│   │   ├── data/
│   │   │   └── licenses.ts         # 오픈소스 라이선스 데이터
│   │   ├── types.ts                # 타입 정의 (TcResult, AudioProfile 등)
│   │   ├── App.tsx                 # 메인 앱 레이아웃
│   │   ├── App.css                 # 다크 테마 스타일
│   │   └── main.tsx                # 엔트리포인트
│   ├── src-tauri/                  # Rust 백엔드
│   │   ├── src/
│   │   │   ├── main.rs
│   │   │   ├── lib.rs              # invoke_handler 등록
│   │   │   ├── test_cmd.rs         # 테스트 실행 커맨드 (23개)
│   │   │   ├── device_cmd.rs       # 디바이스 관리
│   │   │   ├── appium_cmd.rs       # Appium 서버 관리
│   │   │   ├── env_cmd.rs          # 환경 점검
│   │   │   ├── state.rs            # 전역 상태 (Mutex)
│   │   │   ├── types.rs            # Rust 직렬화 타입
│   │   │   └── utils.rs            # 유틸리티
│   │   ├── scripts/                # Python 테스트 스크립트 (25+개)
│   │   │   ├── ixio_automated_test.py   # 메인 오케스트레이터
│   │   │   ├── tc01_ios_caller.py       # iOS 발신 시퀀스
│   │   │   ├── call_recorder.py         # G8 USB 녹음
│   │   │   ├── mixer_recorder.py        # CONNECT 6 녹음
│   │   │   ├── audio_handler.py         # 음원 재생
│   │   │   ├── device_detector.py       # 디바이스 감지
│   │   │   ├── ios_wda_manager.py       # WDA 관리
│   │   │   └── ...
│   │   └── Cargo.toml
│   └── package.json
├── analyze_hybrid.py               # 하이브리드 분석(Gemini+librosa)
├── audio_quality.py                # 음질 분석 (ViSQOL MOS)
├── html_report.py                  # HTML 보고서 생성
├── audio_lib/                      # 공통 오디오 라이브러리
│   ├── dsp.py                      # 신호처리 함수
│   ├── io.py                       # 파일 I/O
│   └── consts.py                   # 상수
├── visqol-3.3.3/                   # ViSQOL 빌드
└── recordings/                     # 녹음 파일 저장소
```

---

## 7. 향후 계획

| 우선순위 | 항목 | 설명 |
|----------|------|------|
| P0 | DashboardView 실데이터 연동 | 현재 예시 데이터 → tcResults 배열 반영 |
| P1 | CSV/Excel 내보내기 | xlsx 라이브러리 활용 결과 데이터 익스포트 |
| P1 | 오디오 다운로드 기능 | "열기" → "다운로드" 버튼 전환 |
| P2 | 웹 마이그레이션 | Tauri IPC → REST API 전환 (6 Phase 계획) |
| P2 | TC Phase 2 | 병렬 실행, 고급 분석 옵션 |
| P3 | CI/CD 통합 | 자동 빌드/테스트 파이프라인 |
