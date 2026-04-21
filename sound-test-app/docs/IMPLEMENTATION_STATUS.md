# 🔧 ixi-O Sound Test App — 현재 구현사항 정리

> **기준일**: 2026-03-31  
> **앱 버전**: v0.1.0  
> **빌드 상태**: ✅ 컴파일 성공  

---

## 1. 프론트엔드 구현 현황

### 1.1 컴포넌트 목록 (12개)

| 컴포넌트 | 파일 | 기능 | 상태 |
|----------|------|------|------|
| `AppHeader` | `AppHeader.tsx` | 앱 타이틀, 설정(⚙) 버튼, 테스트 결과 배지 | ✅ 완료 |
| `DeviceSection` | `DeviceSection.tsx` | Android(ADB)/iOS(devicectl) 디바이스 목록 + ixi-O 배너 | ✅ 완료 |
| `SpeakerSection` | `SpeakerSection.tsx` | 화자 1↔화자 2 설정, 전화번호, 스왑 기능 | ✅ 완료 |
| `AudioSection` | `AudioSection.tsx` | 음원 프로파일 선택, 재생/정답지/대본 파일 | ✅ 완료 |
| `ExecSection` | `ExecSection.tsx` | 테스트 시작/중지/스케줄 실행 | ✅ 완료 |
| `EnvPanel` | `EnvPanel.tsx` | ADB/Appium/Python 환경 상태 표시판 | ✅ 완료 |
| `LogPanel` | `LogPanel.tsx` | 실시간 로그 스트림 (Tauri 이벤트) | ✅ 완료 |
| `TcSelectPanel` | `TcSelectPanel.tsx` | TC_01~04 체크박스, 반복/예약 옵션 | ✅ 완료 |
| `DashboardView` | `DashboardView.tsx` | 게시판 형태 결과 테이블 | ✅ 기본 완료 |
| `ResultDetailModal` | `ResultDetailModal.tsx` | 상세 결과 (MOS, 음단절, 스크린샷) | ✅ 완료 |
| `ReportModal` | `ReportModal.tsx` | HTML 리포트 뷰어 | ✅ 완료 |
| `SettingsModal` | `SettingsModal.tsx` | 6탭 설정 팝업 (820px) | ✅ 완료 |

### 1.2 커스텀 훅 (10개)

| 훅 | 파일 | 역할 |
|----|------|------|
| `useDevices` | `useDevices.ts` | ADB/iOS 디바이스 목록 + 연결 상태 |
| `useSpeakerConfig` | `useSpeakerConfig.ts` | 화자 1/2 설정 관리 + localStorage |
| `useAudioProfiles` | `useAudioProfiles.ts` | 음원 프로파일 CRUD |
| `useAudioDevices` | `useAudioDevices.ts` | CONNECT 6 오디오 장치 목록 |
| `useTcAudioConfig` | `useTcAudioConfig.ts` | TC별 오디오 설정 |
| `useTcRunner` | `useTcRunner.ts` | TC 실행 엔진 (invoke 호출) |
| `useAppium` | `useAppium.ts` | Appium 서버 시작/중지/상태 |
| `useEnvCheck` | `useEnvCheck.ts` | 환경 도구 점검 |
| `useLogs` | `useLogs.ts` | Tauri 이벤트 로그 수집 |
| `useAppVersions` | `useAppVersions.ts` | 앱 버전 조회 |

### 1.3 설정 모달 탭 구성 (6개)

| 탭 | 아이콘 | 내용 |
|----|--------|------|
| 화자 설정 | 🎤 | TC별 디바이스 선택 |
| 음원 프로파일 | 🎵 | S1/S2 음원 + 화자별 정답지 파일 선택 |
| 음원 대본 | 📄 | 음단절 분석용 .txt 대본 등록 |
| 디바이스/오디오설정 | 📱 | CONNECT 6 채널 설정, L/R 분리, 출력 쌍 |
| 파일 저장 방식 | 💾 | 파일 추출 vs 직접 녹음 라디오 |
| 오픈소스 라이선스 | 📜 | 8개 라이선스 그룹 아코디언 + Copyright |

### 1.4 UI 스타일링

- **테마**: 다크 모드 (`--bg: #0d1117`, `--accent: #388bfd`)
- **레이아웃**: CSS Grid 2열 구조 (`grid-template-columns: 1fr 1fr`)
- **설정 모달**: 820px 너비
- **ixi-O 배너**: `.device-lower` flex, `filter: brightness(0.7) contrast(0.9)`
- **라이선스 UI**: 상태 기반 아코디언, 흰색 텍스트, `rgba(255,255,255,.05)` 배경

---

## 2. Rust 백엔드 구현 현황

### 2.1 모듈 구조

| 파일 | 역할 | 커맨드 수 |
|------|------|-----------|
| `test_cmd.rs` | 테스트 실행, 분석, 보고서 | ~15 |
| `device_cmd.rs` | ADB 무선연결, iOS devicectl | ~4 |
| `appium_cmd.rs` | Appium 서버 시작/중지/상태 | ~4 |
| `env_cmd.rs` | 환경 도구 점검, venv 설정 | ~3 |
| `state.rs` | 전역 Mutex (Appium, Watchdog 프로세스) | - |
| `types.rs` | Rust 직렬화 타입 정의 | - |
| `utils.rs` | 공통 유틸리티 | - |
| `lib.rs` | invoke_handler 등록 | - |

### 2.2 주요 Tauri 커맨드

```rust
// 테스트 실행
run_ixio_test        // Python ixio_automated_test.py 호출
run_dropout_analysis // 음단절 분석 실행
open_report          // HTML 보고서 열기

// 디바이스 관리
list_adb_devices     // ADB 디바이스 목록
connect_adb_wireless // ADB 무선 연결
list_ios_devices     // iOS devicectl 디바이스 목록

// Appium 관리
start_appium         // Appium 서버 시작 (포트 4723/4724)
stop_appium          // Appium 서버 중지
appium_status        // 서버 상태 조회

// 환경
check_tools          // ADB/Appium/Python/Node 점검
setup_venv           // Python 가상환경 설정
```

### 2.3 이벤트 스트림 (5개)

| 이벤트 이름 | 발생 시점 | 데이터 |
|-------------|-----------|--------|
| `test-log` | Python stdout/stderr 출력 시 | 텍스트 라인 |
| `appium-log` | Appium 서버 로그 | 텍스트 라인 |
| `setup-log` | venv 설정 진행 | 텍스트 라인 |
| `audio-progress` | 음원 재생 진행률 | 퍼센트 |
| `device-alert` | 디바이스 연결/해제 | 상태 변경 |

### 2.4 날짜별 폴더 정리 (test_cmd.rs)

```rust
// KST(UTC+9) 기준 YYYY-MM-DD 계산
// Civil calendar 변환 (Howard Hinnant 알고리즘)
// 보고서 저장: sound_root/reports/YYYY-MM-DD/hybrid_report_{epoch}.html
```

---

## 3. Python 테스트 엔진 구현 현황

### 3.1 핵심 스크립트 (src-tauri/scripts/)

| 스크립트 | 역할 | 상태 |
|----------|------|------|
| `ixio_automated_test.py` | TC 오케스트레이터 (메인 진입점) | ✅ |
| `tc01_ios_caller.py` | iOS 발신 시퀀스 (키패드→통화→종료→요약) | ✅ |
| `android_call_handler.py` | Android 수신 자동 응답 | ✅ |
| `ios_call_handler.py` | iOS 수신 자동 응답 | ✅ |
| `call_state_detector.py` | 통화 상태 감지 (연결/종료) | ✅ |
| `audio_handler.py` | 음원 재생 제어 | ✅ |
| `audio_player_worker.py` | 음원 재생 워커 스레드 | ✅ |
| `audio_playback_mixin.py` | 재생 믹스인 | ✅ |
| `call_recorder.py` | G8 USB 입력 녹음 (날짜별 폴더) | ✅ |
| `mixer_recorder.py` | CONNECT 6 듀얼 녹음 (날짜별 폴더) | ✅ |
| `call_audio_collector.py` | 녹음 파일 수집 (adb pull/xcrun) | ✅ |
| `device_detector.py` | 디바이스 자동 감지 | ✅ |
| `ios_wda_manager.py` | WebDriverAgent 관리 | ✅ |
| `wda_installer.py` | WDA 설치 자동화 | ✅ |
| `wda_auto_answer.py` | WDA 자동 응답 | ✅ |
| `appium_device_setup.py` | Appium 디바이스 설정 | ✅ |
| `answer_strategies.py` | 수신 응답 전략 패턴 | ✅ |
| `core_audio_utils.py` | macOS Core Audio 유틸리티 | ✅ |
| `usb_audio_devices.py` | USB 오디오 장치 목록 | ✅ |
| `crash_reporter.py` | 크래시 리포트 수집 | ✅ |
| `config.py` | 설정 파일 | ✅ |
| `play_test_tone.py` | 테스트 톤 재생 | ✅ |
| `list_ios_devices.py` | iOS 디바이스 목록 | ✅ |
| `android_watchdog.py` | Android 연결 감시 | ✅ |
| `dump_ixio_ui.py` | ixi-O 앱 UI 트리 덤프 | ✅ |
| `send_test_mail.py` | 테스트 결과 메일 발송 | ✅ |

### 3.2 분석 스크립트 (루트 sound/)

| 스크립트 | 역할 |
|----------|------|
| `analyze_hybrid.py` | Gemini AI + librosa 하이브리드 음단절 분석 |
| `audio_quality.py` | ViSQOL MOS + PESQ + SNR 계산 |
| `html_report.py` | 파형 비교 HTML 보고서 생성 |
| `gemini_analysis.py` | Gemini AI 단독 분석 |
| `analyze_dropout.py` | 음단절 상세 분석 |
| `analyze_spectrum.py` | FFT 스펙트럼 분석 |
| `analyze_stereo.py` | 스테레오 채널 분석 |
| `analyze_waveform_compare.py` | 파형 비교 분석 |
| `analyze_waveform_gemini.py` | Gemini 파형 분석 |
| `analyze_caller_dropout.py` | 발신자 측 음단절 분석 |
| `analyze_call_log.py` | 통화 로그 분석 |
| `energy_align_layer.py` | 에너지 기반 시간축 정렬 |
| `script_gap_detector.py` | 대본 기반 갭 탐지 |

### 3.3 유틸리티 스크립트

| 스크립트 | 역할 |
|----------|------|
| `normalize_recordings.py` | 녹음 파일 정규화 |
| `normalize_volume.py` | 볼륨 정규화 |
| `compare_volume.py` | 볼륨 비교 |
| `compare_recording_quality.py` | 녹음 품질 비교 |
| `wav_converter.py` | 포맷 변환 |
| `mp4_to_wav.py` | MP4→WAV 변환 |
| `separate_audio.py` | 오디오 채널 분리 |
| `collect_recordings.py` | 녹음 파일 수집 |
| `diagnose_connect6.py` | CONNECT 6 진단 |
| `diagnose_devices.py` | 디바이스 진단 |
| `diagnose_usb_ports.py` | USB 포트 진단 |
| `diagnose_recording_volume.py` | 녹음 볼륨 진단 |

### 3.4 테스트 코드 (scripts/tests/)

| 테스트 | 대상 |
|--------|------|
| `test_gap_detector.py` | 갭 탐지 알고리즘 |
| `test_usb_audio_devices.py` | USB 오디오 장치 |
| `test_script_gap_detector.py` | 대본 갭 탐지 |
| `test_core_audio_utils.py` | Core Audio 유틸 |
| `test_audio_handler.py` | 음원 재생 핸들러 |
| `test_ios_wda_manager.py` | WDA 관리자 |
| `test_collect_recordings.py` | 녹음 수집 |
| `test_appium_device_setup.py` | Appium 디바이스 |
| `test_audio_player_worker.py` | 재생 워커 |

---

## 4. 오픈소스 라이선스 현황

| 라이선스 | 패키지 수 | 주요 패키지 |
|----------|-----------|-------------|
| MIT | 30 | React, Vite, tokio, serde_json |
| Apache-2.0 | 35 | Tauri, serde, tao, wry, xlsx |
| MPL-2.0 | 5 | cssparser, unicode-bidi |
| BSD-3-Clause | 5 | brotli, instant |
| ISC | 1 | - |
| Unicode-3.0 | 7 | unicode-ident 등 |
| Zlib | 6 | miniz_oxide, adler |
| 0BSD | 1 | - |
| **합계** | **90** | |

---

## 5. 기존 문서 현황

| 문서 | 위치 | 내용 | 상태 |
|------|------|------|------|
| `TC_REQUIREMENTS.md` | `sound-test-app/` | TC_01~04 상세 정의 | ✅ |
| `TC_DASHBOARD_PLAN.md` | `sound/` | 결과 대시보드 9 Phase 설계 | ✅ |
| `QUALITY_AUDIT_2026.md` | `sound/` | ISO 25010 품질 감사 | ✅ |
| `WEB_MIGRATION_PLAN.md` | `sound-test-app/` | Tauri→웹 전환 6 Phase | ✅ |
| `AUDIO_DOWNLOAD_PLAN.md` | `sound-test-app/` | 다운로드 기능 계획 | ✅ |
| `IXIO_TEST_PROMO.md` | `sound-test-app/` | 기능 홍보 자료 | ✅ |
| `SEMINAR_음단절탐지_기술해설.md` | `sound/` | 음단절 5단계 파이프라인 해설 | ✅ |
| `DROPOUT_TEST_GUIDE.md` | `sound/` | 음단절 분석 가이드 | ✅ |
| `QUICK_START.md` | `sound/` | 빠른 시작 가이드 | ✅ |
| `APPIUM_SETUP_GUIDE.md` | `sound/` | Appium 설치/설정 | ✅ |
| `IOS_AGENT_SETUP.md` | `sound/` | iOS 오디오 에이전트 설정 | ✅ |
| `IOS_WIRELESS_SETUP.md` | `sound/` | iOS Wi-Fi 연결 설정 | ✅ |
| `TAURI_PROJECT_PLAN.md` | `sound/` | Tauri 프로젝트 구조 계획 | ✅ |
| `TAURI_SETUP_GUIDE.md` | `sound/` | Tauri 설치/빌드 가이드 | ✅ |
| `GUI_APP_GUIDE.md` | `sound/` | 앱 사용법 가이드 | ✅ |

---

## 6. 미구현/진행 중 항목

| 항목 | 상태 | 비고 |
|------|------|------|
| DashboardView 실데이터 연동 | 🔲 미구현 | 현재 예시 데이터 표시 |
| CSV/Excel 내보내기 | 🔲 미구현 | xlsx 라이브러리 준비됨 |
| 오디오 다운로드 버튼 | 🔲 미구현 | 계획 문서 작성됨 |
| 웹 마이그레이션 | 🔲 미구현 | 6 Phase 계획 문서 작성됨 |
| TC 병렬 실행 | 🔲 미구현 | Phase 2 계획 |
| CI/CD 통합 | 🔲 미구현 | Phase 4 계획 |
| 테스트 결과 배지 (읽지 않은 수) | 🔲 미구현 | 현재 전체 카운트 표시 |
