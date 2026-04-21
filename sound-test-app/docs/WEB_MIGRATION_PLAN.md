# ixi-O 통화기능 테스트 — 웹 서비스 전환 마이그레이션 계획

> 작성일: 2026-03-30  
> 목적: 현재 Tauri 데스크톱 앱을 웹 브라우저 기반 서비스로 전환 시 변경 필요 항목 사전 도출  
> 원칙: **현재 GUI(React + CSS)를 최대한 유지**, 내부 PC 설정값은 변경 없음

---

## 목차

1. [현재 아키텍처 요약](#1-현재-아키텍처-요약)
2. [전환 대상 분류 기준](#2-전환-대상-분류-기준)
3. [변경 항목 전체 목록](#3-변경-항목-전체-목록)
4. [항목별 상세](#4-항목별-상세)
5. [유지 가능 항목 (변경 불필요)](#5-유지-가능-항목-변경-불필요)
6. [신규 구축 필요 항목](#6-신규-구축-필요-항목)
7. [권장 전환 순서](#7-권장-전환-순서)

---

## 1. 현재 아키텍처 요약

```
┌─────────────────────────────────────────────┐
│              Tauri Desktop App              │
│  ┌────────────────┐  ┌───────────────────┐  │
│  │  React Frontend │  │   Rust Backend    │  │
│  │  (Vite + TS)    │◄─►  (Tauri IPC)     │  │
│  │  App.css (dark) │  │  test_cmd.rs      │  │
│  │  12 components  │  │  23 커맨드         │  │
│  │  10 hooks       │  │  5 이벤트 스트림    │  │
│  └────────────────┘  └──────┬────────────┘  │
│                              │               │
│          ┌───────────────────┼──────┐        │
│          │     로컬 시스템 자원      │        │
│          │  Python, ADB, Appium,   │        │
│          │  pymobiledevice3, sox   │        │
│          └─────────────────────────┘        │
└─────────────────────────────────────────────┘
```

| 계층 | 기술 | 비고 |
|------|------|------|
| Frontend | React 19 + TypeScript + Vite 7 | 단일 `App.css`, 다크 테마 |
| Backend | Rust (Tauri 2) | IPC 기반 커맨드/이벤트 |
| 프로세스 | Python 스크립트 (ixio_automated_test.py 등) | 서브프로세스 실행 |
| 디바이스 | ADB, pymobiledevice3, tidevice, Appium | USB 직접 연결 |
| 저장소 | localStorage + 로컬 파일시스템 | 녹음 WAV, HTML 보고서 |

---

## 2. 전환 대상 분류 기준

| 분류 | 설명 | 아이콘 |
|------|------|--------|
| **그대로 유지** | React 컴포넌트/CSS/로직 변경 없음 | ✅ |
| **소폭 수정** | API 호출 방식만 변경 (IPC→HTTP) | 🔄 |
| **대폭 수정** | 아키텍처 변경 필요 | ⚠️ |
| **신규 구축** | 현재 없는 서버사이드 기능 | 🆕 |
| **불가/대체** | 브라우저 제약으로 다른 방식 필요 | 🚫 |

---

## 3. 변경 항목 전체 목록

### A. 통신 계층

| # | 항목 | 현재 | 전환 후 | 분류 |
|---|------|------|---------|------|
| A-1 | Tauri IPC (`invoke`) | 23개 커맨드 | REST API / WebSocket | 🔄 |
| A-2 | Tauri 이벤트 (`listen`) | 5개 실시간 스트림 | WebSocket / SSE | ⚠️ |
| A-3 | Tauri 플러그인 (dialog, opener) | 네이티브 | Web File API / `<a download>` | ⚠️ |

### B. 프로세스 실행

| # | 항목 | 현재 | 전환 후 | 분류 |
|---|------|------|---------|------|
| B-1 | Python 테스트 스크립트 실행 | `Command::new("python3")` | 서버사이드 실행 | ⚠️ |
| B-2 | Appium 서버 관리 | Rust에서 프로세스 spawn | 서버에서 관리 / Docker | ⚠️ |
| B-3 | ADB 명령 실행 | `std::process::Command("adb")` | 서버 API 프록시 | ⚠️ |
| B-4 | iOS 디바이스 명령 | `devicectl`, `idevice_id`, `tidevice` | 서버 API 프록시 | ⚠️ |
| B-5 | 환경 점검 (tool detection) | `which` / `command -v` | 서버사이드 점검 API | 🔄 |

### C. 파일 시스템

| # | 항목 | 현재 | 전환 후 | 분류 |
|---|------|------|---------|------|
| C-1 | 녹음 파일 저장/열기 | 로컬 경로 직접 접근 | 서버 저장소 + 다운로드 API | ⚠️ |
| C-2 | HTML 보고서 열기 | `open_report` → OS 기본 앱 | 새 탭에서 렌더링 또는 다운로드 | 🔄 |
| C-3 | 음원 프로파일 파일 선택 | Tauri file dialog | `<input type="file">` + 업로드 | ⚠️ |
| C-4 | 번들 Python 스크립트 | 앱 리소스에서 추출 | 서버에 사전 배포 | 🆕 |
| C-5 | Python venv 설정 | 앱 내에서 자동 생성 | 서버 환경에 사전 설치 | 🆕 |
| C-6 | 스크린샷 파일 | 로컬 경로 | 서버 저장 + URL 제공 | 🔄 |

### D. 디바이스/하드웨어

| # | 항목 | 현재 | 전환 후 | 분류 |
|---|------|------|---------|------|
| D-1 | Android USB 연결 | 로컬 ADB | 서버에 연결된 디바이스 API | ⚠️ |
| D-2 | iOS USB 연결 | pymobiledevice3/devicectl | 서버에 연결된 디바이스 API | ⚠️ |
| D-3 | 오디오 장치 목록 | Python sounddevice 호출 | 서버 오디오 장치 API | 🔄 |
| D-4 | 시스템 스피커 재생 | sox 기반 로컬 재생 | 서버사이드 재생 명령 | 🔄 |

### E. 상태 저장

| # | 항목 | 현재 | 전환 후 | 분류 |
|---|------|------|---------|------|
| E-1 | 화자 설정 | `localStorage (speakerConfig_v1)` | 그대로 유지 or DB | ✅ |
| E-2 | 음원 프로파일 | `localStorage (ixio-audio-profiles)` | DB + 파일 서버 | ⚠️ |
| E-3 | 녹음 모드 | `localStorage (recordingMode)` | 그대로 유지 | ✅ |
| E-4 | 테스트 결과 | `useState` (메모리) | DB 영속화 | 🆕 |
| E-5 | TC별 화자 설정 | `localStorage (tcSpeaker-*)` | 그대로 유지 or DB | ✅ |

### F. UI / 프론트엔드

| # | 항목 | 현재 | 전환 후 | 분류 |
|---|------|------|---------|------|
| F-1 | React 컴포넌트 12개 | Vite + React 19 | 그대로 유지 | ✅ |
| F-2 | App.css 다크 테마 | CSS 변수 기반 | 그대로 유지 | ✅ |
| F-3 | 커스텀 훅 10개 | Tauri IPC 호출 포함 | HTTP/WS 호출로 교체 | 🔄 |
| F-4 | 앱 헤더 버전 표시 | Tauri 앱 버전 | 서버 버전 API | 🔄 |
| F-5 | CSV/Excel 내보내기 | 프론트엔드 `xlsx` 라이브러리 | 그대로 유지 | ✅ |

---

## 4. 항목별 상세

### A-1. Tauri IPC → REST API 전환

현재 23개 `invoke()` 호출을 HTTP API로 교체해야 한다.

| Tauri 커맨드 | 용도 | REST 대응 |
|-------------|------|-----------|
| `check_tools` | 환경 점검 | `GET /api/env/check` |
| `setup_python_env` | venv 설정 | 불필요 (서버 사전 설정) |
| `connect_android_wireless` | ADB WiFi 연결 | `POST /api/device/android/connect` |
| `detect_iphones` | iPhone 탐지 | `GET /api/device/ios/list` |
| `detect_android_devices` | Android 탐지 | `GET /api/device/android/list` |
| `get_ios_app_version` | iOS 앱 버전 | `GET /api/device/ios/app-version` |
| `get_android_app_version` | Android 앱 버전 | `GET /api/device/android/app-version` |
| `start_appium` | Appium 시작 | `POST /api/appium/start` |
| `stop_appium` | Appium 중지 | `POST /api/appium/stop` |
| `start_appium_tc` | TC별 Appium | `POST /api/appium/start-tc` |
| `stop_appium_tc` | TC별 Appium 중지 | `POST /api/appium/stop-tc` |
| `run_tc` | 테스트 실행 | `POST /api/test/run` |
| `stop_tc` | 테스트 중지 | `POST /api/test/stop` |
| `list_audio_devices` | 오디오 장치 | `GET /api/audio/devices` |
| `play_test_tone` | 테스트 톤 재생 | `POST /api/audio/test-tone` |
| `open_report` | 보고서 열기 | 새 탭 or 다운로드 |
| `download_audio` | 음원 다운로드 | `GET /api/audio/download` |
| `read_file_base64` | 파일 읽기 | `GET /api/file/:id` |
| `pick_audio_file` | 파일 선택 | `<input type="file">` |
| `install_wda` | WDA 설치 | `POST /api/device/ios/install-wda` |
| `start_android_watchdog` | 연결 감시 | `WebSocket /ws/watchdog` |
| `stop_android_watchdog` | 감시 중지 | WebSocket 연결 해제 |

**작업 방법**: 각 훅에서 `invoke("command")` → `fetch("/api/...")` 또는 래퍼 함수로 교체

```typescript
// AS-IS (Tauri)
const devices = await invoke<Device[]>("detect_android_devices");

// TO-BE (Web)
const res = await fetch("/api/device/android/list");
const devices: Device[] = await res.json();
```

### A-2. Tauri 이벤트 → WebSocket/SSE

| 이벤트 | 용도 | 전환 방식 |
|--------|------|-----------|
| `test-log` | 테스트 실행 로그 스트림 | `WebSocket /ws/test-log` |
| `appium-log` | Appium 서버 로그 | `WebSocket /ws/appium-log` |
| `setup-log` | 환경 설정 진행 | `WebSocket /ws/setup-log` |
| `audio-progress` | 음원 재생 진행률 | `WebSocket /ws/audio-progress` |
| `device-alert` | 디바이스 경고 팝업 | `WebSocket /ws/alerts` |

**작업 방법**: `listen("event")` → `new WebSocket()` + `onmessage` 핸들러

### A-3. Tauri 플러그인 대체

| 플러그인 | 현재 용도 | 웹 대체 |
|----------|----------|---------|
| `@tauri-apps/plugin-dialog` | WAV/MP3 파일 선택 | `<input type="file" accept=".wav,.mp3">` |
| `@tauri-apps/plugin-opener` | 파일/URL 열기 | `window.open()` / `<a>` 태그 |

### B-1~B-4. 프로세스 실행 → 서버사이드

브라우저에서는 로컬 프로세스를 실행할 수 없으므로 **백엔드 서버**가 필수다.

```
[브라우저] ──HTTP/WS──▶ [웹 서버 (FastAPI/Express)]
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
                 Python    Appium     ADB/iOS
                 스크립트   서버       디바이스
```

**핵심 변경**:
- Rust `Command::new()` 로직 → Python FastAPI 서버 내 `subprocess` 호출로 이식
- 프로세스 생명주기 관리 (시작/중지/타임아웃) 서버에서 처리
- `setsid()` 기반 프로세스 그룹 관리 → 서버사이드에서 동일 구현

### C-1~C-3. 파일 시스템 전환

| 현재 | 웹 전환 후 |
|------|-----------|
| 녹음 WAV → 로컬 절대경로 | 서버 저장소 → UUID 기반 URL |
| HTML 보고서 → `open` 명령 | 서버 URL → 새 탭 `window.open()` |
| 음원 파일 선택 → Tauri dialog | `<input type="file">` → 서버 업로드 |
| 스크린샷 → 로컬 경로 + base64 | 서버 저장 → `<img src="/api/file/...">` |

### E-4. 테스트 결과 영속화

현재는 `useState`로 메모리에만 존재 (새로고침 시 소멸).

**웹 전환 시 옵션**:
- (A) `localStorage` — 브라우저별 독립, 이미 익숙한 패턴 (단일 PC 사용 시 충분)
- (B) 서버 DB (SQLite/PostgreSQL) — 다중 사용자/공유 필요 시

---

## 5. 유지 가능 항목 (변경 불필요)

아래 항목은 Tauri 의존성이 없어 **코드 변경 없이 그대로 사용** 가능하다.

| 항목 | 파일 |
|------|------|
| React 컴포넌트 구조 (12개) | `src/components/*.tsx` |
| 다크 테마 CSS | `src/App.css` |
| 타입 정의 | `src/types.ts` |
| CSV/Excel 내보내기 | `xlsx` 라이브러리 |
| 대시보드 필터/정렬 로직 | `DashboardView.tsx` |
| MOS 색상 코딩/배지 | 컴포넌트 내 JSX |
| 화자 설정 UI | `SettingsModal.tsx`, `SpeakerSection.tsx` |
| TC 선택 UI | `TcSelectPanel.tsx` |
| 로그 패널 UI | `LogPanel.tsx` |
| 환경 패널 UI | `EnvPanel.tsx` |
| localStorage 기반 설정 저장 | `useSpeakerConfig.ts` 등 |

---

## 6. 신규 구축 필요 항목

### 6-1. 백엔드 웹 서버

| 항목 | 설명 |
|------|------|
| **프레임워크** | FastAPI (Python, 기존 스크립트와 동일 언어) 또는 Express (Node.js) |
| **REST API** | 23개 엔드포인트 (섹션 4 A-1 표 참조) |
| **WebSocket** | 5개 채널 (로그/진행률/알림 스트리밍) |
| **파일 서빙** | 녹음 WAV, HTML 보고서, 스크린샷 정적 파일 |
| **프로세스 관리** | Python 테스트 스크립트, Appium 서버 생명주기 |

### 6-2. 정적 파일 서버 / 저장소

| 항목 | 설명 |
|------|------|
| 녹음 파일 저장 | 서버 디스크 or NAS (`/data/recordings/`) |
| HTML 보고서 저장 | 서버 디스크 (`/data/reports/`) |
| 음원 프로파일 파일 | 업로드 → 서버 저장 (`/data/audio-profiles/`) |
| 다운로드 API | `GET /api/file/:id` (Content-Disposition: attachment) |

### 6-3. 인증/보안 (다중 사용자 시)

| 항목 | 설명 |
|------|------|
| 사용자 인증 | JWT 또는 세션 기반 로그인 |
| API 접근 제어 | 인증 미들웨어 |
| 파일 다운로드 보안 | path traversal 방지, 화이트리스트 |
| CORS | 프론트엔드 origin 허용 설정 |

### 6-4. 프론트엔드 빌드 변경

| 항목 | 현재 | 전환 후 |
|------|------|---------|
| 빌드 도구 | Vite + `@tauri-apps/cli` | Vite only (Tauri 제거) |
| 진입점 | `tauri.conf.json` → Vite dev server | Vite → 정적 파일 빌드 |
| 환경 감지 | 불필요 | `window.__TAURI__` 분기 (하이브리드 과도기) |
| 패키지 제거 | — | `@tauri-apps/api`, `plugin-dialog`, `plugin-opener` |

---

## 7. 권장 전환 순서

```
Phase 1: 백엔드 서버 기초                    Phase 2: 프론트엔드 전환
┌──────────────────────┐                  ┌──────────────────────┐
│ ① 웹 서버 프레임워크  │                  │ ⑤ invoke → fetch     │
│   선정 + 프로젝트 생성│                  │   (23개 커맨드 교체) │
│ ② REST API 구현      │                  │ ⑥ listen → WebSocket │
│   (디바이스/환경/실행)│                  │   (5개 이벤트 교체)  │
│ ③ WebSocket 구현     │──────────────▶   │ ⑦ 플러그인 대체      │
│   (로그/진행률 스트림)│                  │   (파일선택/다운로드) │
│ ④ 파일 서빙 API      │                  │ ⑧ Tauri 의존성 제거  │
└──────────────────────┘                  └──────────────────────┘
                                                    │
                                                    ▼
                                          Phase 3: 배포/안정화
                                          ┌──────────────────────┐
                                          │ ⑨ 정적 파일 빌드     │
                                          │ ⑩ 서버 배포 구성     │
                                          │ ⑪ 통합 테스트        │
                                          │ ⑫ (선택) 인증 추가   │
                                          └──────────────────────┘
```

### 단계별 세부

| 순서 | 작업 | 난이도 | 선행조건 |
|------|------|--------|----------|
| ① | 웹 서버 프로젝트 생성 (FastAPI 권장) | 낮음 | — |
| ② | REST API 23개 엔드포인트 구현 | 중간 | ① |
| ③ | WebSocket 5개 채널 구현 | 중간 | ① |
| ④ | 파일 업로드/다운로드/서빙 API | 낮음 | ① |
| ⑤ | Frontend `invoke()` → `fetch()` 교체 (10개 훅) | 중간 | ②③ |
| ⑥ | Frontend `listen()` → WebSocket 교체 | 낮음 | ③⑤ |
| ⑦ | Tauri 플러그인 → Web API 대체 | 낮음 | ⑤ |
| ⑧ | Tauri/Rust 의존성 완전 제거 | 낮음 | ⑤⑥⑦ |
| ⑨ | Vite 정적 빌드 → 서버 배포 | 낮음 | ⑧ |
| ⑩ | 서버 + 프론트엔드 통합 배포 | 중간 | ⑨ |
| ⑪ | 전 TC 통합 테스트 | 중간 | ⑩ |
| ⑫ | (선택) 사용자 인증 | 중간 | ⑩ |

---

## 참고: 하이브리드 과도기 전략

Tauri 앱과 웹 버전을 동시에 유지해야 하는 경우:

```typescript
// src/lib/api.ts — 공통 래퍼
export async function apiCall<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (window.__TAURI__) {
    return invoke<T>(command, args);
  }
  const res = await fetch(`/api/${command}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  return res.json();
}
```

이렇게 래퍼를 두면 **훅 코드 변경 최소화** + 두 환경 동시 지원 가능.
