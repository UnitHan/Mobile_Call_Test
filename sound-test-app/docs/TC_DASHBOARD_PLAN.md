ViSQOL v3
# TC 대시보드 기능 작업계획서

> **작성일**: 2026-03-10  
> **대상 프로젝트**: `sound-test-app` (Tauri + React/TypeScript)  
> **목적**: 홈 화면에 TC 선택 패널 추가 → 테스트 자동 실행 → 결과 대시보드 게시판 구현

---

## 목차

1. [기능 요구사항](#1-기능-요구사항)
2. [전체 아키텍처 변경](#2-전체-아키텍처-변경)
3. [데이터 모델](#3-데이터-모델)
4. [UI 레이아웃 설계](#4-ui-레이아웃-설계)
5. [컴포넌트 구조](#5-컴포넌트-구조)
6. [실행 흐름](#6-실행-흐름)ㄴ
7. [구현 단계(Phase)](#7-구현-단계phase)
8. [파일 변경 목록](#8-파일-변경-목록)
9. [미결 사항](#9-미결-사항)

---

## 1. 기능 요구사항

### 1-1. TC 선택 패널 (홈 화면 상단)

| 항목 | 내용 |
|---|---|
| TC 목록 | TC_01, TC_02, TC_03 (이후 추가 가능한 구조) |
| 선택 방식 | **체크박스** (1개 이상 다중 선택 가능) |
| 실행 | 선택된 TC를 순서대로 자동 실행 |
| 제약 | 아무것도 선택 안 하면 "테스트 시작" 버튼 비활성화 |

> **라디오 vs 체크박스 결정**: 요구사항에 "1개나 n개 선택"이 명시되어 있으므로 **체크박스(다중 선택)** 방식을 사용.

### 1-2. 테스트 실행 흐름

```
사용자: TC 선택 → 테스트 시작 클릭
  └→ 선택된 TC를 큐에 적재
       └→ TC_01 실행 → 결과 저장
            └→ TC_02 실행 → 결과 저장  (선택된 경우)
                 └→ TC_03 실행 → 결과 저장  (선택된 경우)
                      └→ 대시보드 업데이트
```

### 1-3. 결과 대시보드 (별도 뷰 또는 탭)

- 테스트 결과 목록을 **게시판 형태**로 표시 (최신순)
- 각 행: 실행번호, TC ID, 실행시각, 결과(PASS/FAIL/ERROR), 소요시간, 상세보기 링크
- **"상세보기"** 클릭 → 해당 TC의 상세 결과 모달/패널 표시
  - Gemini 분석 결과, PESQ/ViSQOL MOS, 음단절 타임스탬프, 로그 등

---

## 2. 전체 아키텍처 변경

### 2-1. 뷰 구조 (현재 → 변경 후)

```
현재:
  App.tsx → 단일 홈 뷰

변경 후:
  App.tsx
   ├── "홈" 탭  ← 기존 화면 (디바이스/화자/오디오/실행 설정)
   │     └── TcSelectPanel (신규) — TC 선택 체크박스 + 테스트 시작
   └── "결과" 탭  ← 신규
         └── DashboardView — 게시판 목록 + 상세 모달
```

### 2-2. 탭 전환 방식

- 상단 헤더에 **탭 버튼** ("홈" / "테스트 결과 현황") 추가
- 탭 상태는 `App.tsx`의 `activeTab` state로 관리
- 결과가 새로 쌓이면 "결과" 탭 버튼에 **뱃지(숫자)** 표시 → 사용자 주의 유도

---

## 3. 데이터 모델

### 3-1. TC 정의 타입 (`src/types.ts` 추가)

```typescript
// TC 하나의 정적 메타데이터
export interface TcDefinition {
  id: "TC_01" | "TC_02" | "TC_03";          // TC 식별자
  label: string;                              // 화면 표시명
  description: string;                        // 1줄 설명
  category: "기본통화" | "음질측정" | "안정성";
}

// 단일 TC 실행 결과
export interface TcResult {
  runId: string;            // UUID (실행 세션 단위)
  tcId: TcDefinition["id"];
  startedAt: string;        // ISO8601
  finishedAt: string;       // ISO8601
  durationMs: number;

  status: "PASS" | "FAIL" | "ERROR" | "SKIP" | "RUNNING";

  // 측정 지표 (없으면 null)
  pesqMos:    number | null;
  visqolMos:  number | null;
  snrDb:      number | null;
  dropoutCount: number | null;   // Whisper/Gemini 탐지 음단절 수

  // 상세 데이터
  geminiJson: Record<string, unknown> | null;   // analyze_hybrid 결과 JSON
  logLines:   string[];                          // 실행 중 콘솔 출력
  errorMsg:   string | null;
  reportPath: string | null;   // hybrid_report.html 경로
}

// 전체 세션 (여러 TC 묶음)
export interface TestSession {
  sessionId: string;
  startedAt:  string;
  selectedTcs: TcDefinition["id"][];
  results: TcResult[];       // 실행 완료된 TC 결과 누적
  status: "RUNNING" | "DONE" | "ABORTED";
}
```

### 3-2. 결과 영속성

- 결과는 **메모리 state**에 유지 (앱 실행 중만)
- 추후 `localStorage` 또는 `tauri::fs`로 JSON 파일 저장 가능하도록 저장 함수를 별도 훅으로 분리
- 세션 최대 보관: 최근 50개 (초과 시 FIFO 삭제)

---

## 4. UI 레이아웃 설계

### 4-1. 홈 탭 — TC 선택 패널 위치

```
┌──────────────────────────────────────────────────────────────────────┐
│  헤더: ixi-O 통화 테스트  [홈]  [테스트 결과 현황 (3)]  …  환경·Appium  │
├──────────────────────────────────────────────────────────────────────┤
│  ┌─────────────── [신규] TC 선택 패널 (전체 폭) ───────────────────┐  │
│  │  ☑ TC_01  기본 통화 연결    ☑ TC_02  음질 측정    □ TC_03  안정성 테스트  │  [▶ 테스트 시작]  │
│  └─────────────────────────────────────────────────────────────────┘  │
│  [왼쪽 컬럼]                       [오른쪽 컬럼]                       │
│  디바이스 연결                      오디오 설정                         │
│  화자 설정                          실행 패널                           │
│  Appium 로그                        테스트 콘솔                         │
└──────────────────────────────────────────────────────────────────────┘
```

### 4-2. 결과 탭 — 대시보드 (게시판)

```
┌──────── 테스트 결과 현황 ────────────────────────────────────────┐
│                                         [🗑 전체 삭제]  [↓ CSV 내보내기]  │
│  ┌────┬───────┬────────────────┬────────┬───────┬──────┬──────────┐  │
│  │ #  │ TC ID │ 실행시각        │ 상태   │ PESQ  │ 소요 │ 상세보기 │  │
│  ├────┼───────┼────────────────┼────────┼───────┼──────┼──────────┤  │
│  │ 5  │ TC_01 │ 03-10 14:22:01 │ PASS ✅│ 3.812 │ 42s  │  [보기]  │  │
│  │ 4  │ TC_02 │ 03-10 14:21:10 │ FAIL ❌│ 1.434 │ 38s  │  [보기]  │  │
│  │ 3  │ TC_03 │ 03-10 14:20:05 │ PASS ✅│  —    │ 120s │  [보기]  │  │
│  └────┴───────┴────────────────┴────────┴───────┴──────┴──────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 4-3. 상세 모달

```
┌──────────── TC_01 실행 상세 (#5) ─────────────────────── [✕] ─┐
│  실행시각: 2026-03-10 14:22:01   소요: 42s   상태: PASS ✅       │
├───────────────────────────────────────────────────────────────┤
│  [측정 지표]                                                    │
│  PESQ MOS: 3.812 (양호)   ViSQOL MOS: 3.654 (양호)            │
│  SNR: 28.3 dB   음단절: 0건                                     │
├───────────────────────────────────────────────────────────────┤
│  [Gemini 분석 요약]                                             │
│  "두 파일 간 뚜렷한 음단절 없음. 초기 200ms 묵음은 정상 범위." │
│                                    [보고서 열기 (HTML)]        │
├───────────────────────────────────────────────────────────────┤
│  [실행 로그]  ─────────────────────────────────────── [복사]  │
│  ✅ 통화 연결 완료                                              │
│  📊 MOS 계산 중 (PESQ + ViSQOL)...                            │
│  ✅ PESQ MOS  : 3.812 (양호)                                   │
│  ✅ ViSQOL MOS: 3.654 (양호)                                   │
└───────────────────────────────────────────────────────────────┘
```

---

## 5. 컴포넌트 구조

### 5-1. 신규 파일 목록

```
src/
├── components/
│   ├── TcSelectPanel.tsx        ← TC 체크박스 선택 패널 (홈 탭 상단)
│   ├── DashboardView.tsx        ← 결과 게시판 메인 뷰
│   ├── ResultTable.tsx          ← 게시판 테이블 컴포넌트
│   └── ResultDetailModal.tsx    ← 상세 보기 모달
├── hooks/
│   └── useTestSession.ts        ← TC 실행 state 관리 + 결과 누적 훅
└── data/
    └── tcDefinitions.ts         ← TC_01/02/03 메타데이터 상수 정의
```

### 5-2. 기존 파일 수정 목록

```
src/
├── App.tsx           ← 탭 state, TcSelectPanel 추가, DashboardView 탭 추가
├── types.ts          ← TcDefinition, TcResult, TestSession 타입 추가
└── App.css           ← 탭, TC 패널, 게시판, 모달 스타일 추가
```

### 5-3. 컴포넌트 책임 분리

| 컴포넌트 | Props | 역할 |
|---|---|---|
| `TcSelectPanel` | `tcDefs`, `selected`, `onChange`, `onStart`, `isRunning` | 체크박스 렌더, 실행 버튼 |
| `DashboardView` | `sessions`, `onClear` | 게시판 레이아웃 + 모달 상태 관리 |
| `ResultTable` | `results`, `onViewDetail` | 게시판 테이블 행 렌더 |
| `ResultDetailModal` | `result`, `onClose` | 상세 지표 + 로그 + 보고서 링크 |
| `useTestSession` hook | — | TC 큐 실행, 결과 추가, 세션 완료 처리 |

---

## 6. 실행 흐름

### 6-1. TC 실행 시 처리 흐름

```
사용자: [TC_01 ☑] [TC_02 ☑] → [테스트 시작]
  │
  ├─ App.tsx: handleTcStart(selectedTcs)
  │    └─ useTestSession.startSession(["TC_01","TC_02"])
  │         ├─ 새 TestSession 생성 (RUNNING)
  │         ├─ TC_01 실행 루틴 호출
  │         │    ├─ TcResult 초기화 (status: RUNNING)
  │         │    ├─ 기존 invoke("run_ixio_test") 실행
  │         │    ├─ collect_recordings.py → analyze_hybrid.py 실행
  │         │    │    └─ PESQ, ViSQOL, 음단절 결과 파싱
  │         │    └─ TcResult 업데이트 (status: PASS/FAIL, 지표 채움)
  │         │
  │         ├─ TC_02 실행 루틴 호출 (동일 패턴)
  │         │
  │         └─ TestSession.status = "DONE"
  │              └─ "결과" 탭 뱃지 +1 업데이트
  │
  └─ 사용자: "결과" 탭 클릭 → DashboardView 렌더
```

### 6-2. TC별 시나리오 실행 구조 (placeholder)

각 TC의 실제 시나리오 내용은 작성 후 아래에 채워넣을 예정:

```typescript
// src/data/tcDefinitions.ts
export const TC_DEFINITIONS: TcDefinition[] = [
  {
    id: "TC_01",
    label: "TC_01 — (시나리오 TBD)",
    description: "시나리오 1번 작성 예정",
    category: "기본통화",
  },
  {
    id: "TC_02",
    label: "TC_02 — (시나리오 TBD)",
    description: "시나리오 2번 작성 예정",
    category: "음질측정",
  },
  {
    id: "TC_03",
    label: "TC_03 — (시나리오 TBD)",
    description: "시나리오 3번 작성 예정",
    category: "안정성",
  },
];

// 각 TC 실행 함수 (시나리오 내용 확정 후 구현)
export async function runTc01(config: TcRunConfig): Promise<Partial<TcResult>> { /* TBD */ }
export async function runTc02(config: TcRunConfig): Promise<Partial<TcResult>> { /* TBD */ }
export async function runTc03(config: TcRunConfig): Promise<Partial<TcResult>> { /* TBD */ }
```

---

## 7. 구현 단계(Phase)

### Phase 1 — 타입 + 데이터 구조 (준비)

- [ ] `src/types.ts`에 `TcDefinition`, `TcResult`, `TestSession` 추가
- [ ] `src/data/tcDefinitions.ts` 생성 (TC 메타데이터 상수 + placeholder 실행 함수)
- [ ] `src/hooks/useTestSession.ts` 생성 (상태 관리 훅 skeleton)

### Phase 2 — TC 선택 패널 (홈 탭)

- [ ] `src/components/TcSelectPanel.tsx` 구현
  - 체크박스 다중 선택 UI
  - "선택 안 하면 실행 불가" 유효성 검사
  - 실행 중 상태 표시 ("TC_01 실행 중… 1/2")
- [ ] `App.tsx`에 `TcSelectPanel` 삽입 (기존 2컬럼 레이아웃 위)
- [ ] `App.css`에 TC 패널 스타일 추가

### Phase 3 — 결과 탭 + 게시판

- [ ] `src/components/ResultTable.tsx` 구현
  - 컬럼: #, TC ID, 실행시각, 상태 배지, PESQ, ViSQOL, 소요시간, 상세보기
  - 상태별 색상: PASS(초록), FAIL(빨강), ERROR(주황), RUNNING(파랑, 스피너)
- [ ] `src/components/DashboardView.tsx` 구현
  - `ResultTable` 렌더 + "전체 삭제" 버튼
  - 모달 open/close 상태 관리
- [ ] `src/components/ResultDetailModal.tsx` 구현
  - 측정 지표 카드
  - Gemini 요약 텍스트
  - 로그 스크롤 패널
  - "보고서 열기" 버튼 (`tauri::shell::open`)
- [ ] `App.css`에 탭, 게시판, 모달 스타일 추가

### Phase 4 — 탭 전환 + 헤더 통합

- [ ] `App.tsx`에 `activeTab: "home" | "dashboard"` state 추가
- [ ] `AppHeader.tsx`에 탭 버튼 + 결과 뱃지 추가
- [ ] 탭 전환 애니메이션 CSS

### Phase 5 — TC 실행 로직 (시나리오 수령 후)

> **이 단계는 TC 시나리오 문서 수령 후 착수**

- [ ] `runTc01()` 구현 — 시나리오 1번 로직
- [ ] `runTc02()` 구현 — 시나리오 2번 로직
- [ ] `runTc03()` 구현 — 시나리오 3번 로직
- [ ] `useTestSession.ts`의 TC 큐 실행 루틴과 연결
- [ ] 실행 중 진행 상황 실시간 반영 (RUNNING → PASS/FAIL)

### Phase 6 — 검증 + 마무리

- [ ] 전체 시나리오 End-to-End 테스트
- [ ] 결과 CSV 내보내기 기능 (선택적)
- [ ] `DROPOUT_TEST_GUIDE.md` 업데이트

---

## 8. 파일 변경 목록

### 신규 생성

| 파일 | 용도 |
|---|---|
| `src/data/tcDefinitions.ts` | TC 메타데이터 + 실행 함수 |
| `src/hooks/useTestSession.ts` | 세션·결과 state 관리 훅 |
| `src/components/TcSelectPanel.tsx` | TC 체크박스 선택 패널 |
| `src/components/DashboardView.tsx` | 결과 게시판 뷰 |
| `src/components/ResultTable.tsx` | 게시판 테이블 |
| `src/components/ResultDetailModal.tsx` | 상세 보기 모달 |

### 기존 수정

| 파일 | 변경 내용 |
|---|---|
| `src/types.ts` | `TcDefinition`, `TcResult`, `TestSession` 타입 추가 |
| `src/App.tsx` | 탭 state, TC 선택 이벤트 핸들러, TcSelectPanel/DashboardView 렌더 추가 |
| `src/components/AppHeader.tsx` | 탭 버튼, 결과 뱃지 추가 |
| `src/App.css` | 탭·TC 패널·게시판·모달 스타일 추가 |

### Tauri 백엔드 (필요 시)

| 파일 | 변경 내용 |
|---|---|
| `src-tauri/src/lib.rs` | TC별 실행 cmd 추가 (시나리오 확정 후) |
| `src-tauri/src/types.rs` | TC 결과 관련 서버 사이드 타입 (필요 시) |

---

## 9. 미결 사항

| # | 항목 | 담당 | 비고 |
|---|---|---|---|
| 1 | **TC_01 시나리오** | 사용자 작성 예정 | 테스트 내용, 판정 기준 |
| 2 | **TC_02 시나리오** | 사용자 작성 예정 | |
| 3 | **TC_03 시나리오** | 사용자 작성 예정 | |
| 4 | 결과 영속성 방식 | 확인 필요 | 앱 재시작 후 결과 유지 여부 (`localStorage` vs `tauri::fs`) |
| 5 | TC 병렬 실행 여부 | 확인 필요 | 디바이스가 1쌍이므로 순차 실행이 기본값 |
| 6 | PASS/FAIL 판정 기준 | 시나리오 확정 시 정의 | PESQ 임계값, 음단절 횟수 등 |

---

## 개발 착수 순서 요약

```
[지금 바로 착수 가능]
  Phase 1 → Phase 2 → Phase 3 → Phase 4  (UI 골격, placeholder 실행 함수)

[TC 시나리오 문서 수령 후]
  Phase 5  (실제 TC 로직 구현)

[최종]
  Phase 6  (통합 검증)
```

> TC 시나리오(1~3번) 문서를 공유해 주시면 Phase 5 구현에 즉시 착수합니다.
