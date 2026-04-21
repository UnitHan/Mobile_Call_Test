# 음원 파일 다운로드 버튼 전환 계획

> 작성일: 2026-03-30  
> 목적: 현재 OS 기본 플레이어로 여는 `📂 열기` 버튼을 `⬇ 다운로드` 버튼으로 변경  
> 배경: 향후 웹 서비스 전환 시 클라이언트 PC에서 파일을 다운로드받아 로컬에서 재생하도록 제공

---

## 1. 현재 구조 (AS-IS)

```
버튼 클릭 (📂 열기)
  ↓
Frontend: invoke("open_report", { path })    ← Tauri IPC
  ↓
Rust: std::process::Command("open" | "start" | "xdg-open")
  ↓
OS 기본 앱(QuickTime 등)으로 로컬 파일 직접 열기
```

### 관련 파일

| 파일 | 역할 | 핵심 위치 |
|------|------|-----------|
| `src/components/ResultDetailModal.tsx` | 상세 모달 — `📂 열기` 버튼 | L156-170 |
| `src/components/ReportModal.tsx` | 결과 테이블 — `🎵` 버튼, 확장 행 버튼 | L369-380, L405-415 |
| `src/hooks/useTcRunner.ts` | `extractedAudioPaths` 배열 조립 | L306-308 |
| `src/types.ts` | `TcResult.extractedAudioPaths` 타입 | L106 |
| `src-tauri/src/test_cmd.rs` | `open_report` Tauri 커맨드 | L27-53 |

### 데이터 흐름

```
Python stdout → TC_RESULT_JSON:{"ios_recording":"/.../xxx.wav", "android_recording":"/.../xxx.wav"}
  ↓
Rust 파싱 → TestRunResult { ios_recording, android_recording }
  ↓
Frontend → extractedAudioPaths: { label: string; path: string }[]
```

---

## 2. 목표 구조 (TO-BE)

### 2-A. Tauri 데스크톱 앱 (현재 플랫폼)

```
버튼 클릭 (⬇ 다운로드)
  ↓
Frontend: invoke("download_audio", { srcPath, fileName })
  ↓
Rust: 사용자 다운로드 폴더(~/Downloads)로 파일 복사
  ↓
완료 알림 (토스트 또는 badge)
```

### 2-B. 웹 서비스 전환 시

```
버튼 클릭 (⬇ 다운로드)
  ↓
Frontend: <a href="/api/audio/download?file=xxx.wav" download>
  또는 fetch → Blob → URL.createObjectURL → anchor click
  ↓
Backend API: /api/audio/download?file=xxx.wav
  ↓
서버에서 wav 파일을 HTTP Response (Content-Disposition: attachment)로 전송
  ↓
브라우저 기본 다운로드 (사용자 PC ~/Downloads)
```

---

## 3. 단계별 작업 계획

### Phase 1 — Tauri 앱 내 다운로드 버튼 전환 (즉시)

#### 3-1. Rust: `download_audio` Tauri 커맨드 추가

**파일**: `src-tauri/src/test_cmd.rs`

```rust
#[tauri::command]
pub fn download_audio(src_path: String, file_name: String) -> Result<String, String> {
    let downloads = dirs::download_dir()
        .ok_or("다운로드 폴더를 찾을 수 없습니다")?;
    let dest = downloads.join(&file_name);
    std::fs::copy(&src_path, &dest)
        .map_err(|e| format!("복사 실패: {e}"))?;
    Ok(dest.to_string_lossy().to_string())
}
```

- `dirs` 크레이트 추가 필요 (`Cargo.toml`에 `dirs = "6"`)
- 동일 파일명 존재 시 덮어쓰기 또는 `_1`, `_2` 접미사 처리

#### 3-2. Rust: `main.rs` 커맨드 등록

```rust
.invoke_handler(tauri::generate_handler![
    // ... 기존 핸들러 ...
    test_cmd::download_audio,
])
```

#### 3-3. Frontend: 버튼 UI 변경

**ResultDetailModal.tsx** (상세 모달)
```diff
- <button onClick={() => openReport(af.path)} title="파일 열기">
-   📂 열기
+ <button onClick={() => downloadAudio(af.path, af.label)} title="다운로드">
+   ⬇ 다운로드
```

**ReportModal.tsx** (테이블 행)
```diff
- <button onClick={(e) => { e.stopPropagation(); openReport(af.path); }}>
-   🎵
+ <button onClick={(e) => { e.stopPropagation(); downloadAudio(af.path, af.label); }}>
+   ⬇
```

#### 3-4. Frontend: `downloadAudio` 핸들러 함수

```typescript
async function downloadAudio(filePath: string, label: string) {
  const fileName = filePath.split("/").pop() || "audio.wav";
  try {
    const dest = await invoke<string>("download_audio", {
      srcPath: filePath,
      fileName,
    });
    // 성공 토스트: "다운로드 완료: ~/Downloads/xxx.wav"
  } catch (e) {
    // 에러 토스트
  }
}
```

---

### Phase 2 — 웹 서비스 전환 시 추가 작업

#### 3-5. 백엔드 API 엔드포인트

```
GET /api/audio/download?file={filename}
```

- 녹음 파일 저장 디렉토리에서 해당 파일을 찾아 `Content-Disposition: attachment` 헤더와 함께 응답
- 인증/권한 체크 필수 (파일명 기반 path traversal 방지)
- 파일명 화이트리스트 또는 UUID 기반 매핑 권장

#### 3-6. Frontend 분기 처리

```typescript
async function downloadAudio(filePath: string, label: string) {
  if (window.__TAURI__) {
    // Tauri 환경 → IPC 호출
    await invoke("download_audio", { srcPath: filePath, fileName });
  } else {
    // 웹 환경 → HTTP 다운로드
    const a = document.createElement("a");
    a.href = `/api/audio/download?file=${encodeURIComponent(fileName)}`;
    a.download = fileName;
    a.click();
  }
}
```

#### 3-7. 파일 저장소 전환

| 항목 | Tauri (현재) | 웹 서비스 (향후) |
|------|-------------|-----------------|
| 파일 위치 | 로컬 디스크 절대 경로 | 서버 저장소 (S3, NAS 등) |
| 접근 방식 | `std::fs::copy` | HTTP API + 스트리밍 응답 |
| 보안 | 로컬이므로 별도 인증 불필요 | JWT/세션 인증 + path traversal 방지 |
| 파일 식별 | 절대 경로 | UUID 또는 해시 기반 식별자 |

---

## 4. 보안 고려사항 (웹 전환 시)

| 위험 | 대응 |
|------|------|
| **Path Traversal** (`../../etc/passwd`) | 파일명에서 `..`, `/` 제거; 허용 디렉토리 화이트리스트 |
| **무단 접근** | 인증된 사용자만 다운로드 API 호출 가능 |
| **대용량 파일** | 스트리밍 응답 + Content-Length 설정 |
| **파일명 인코딩** | `Content-Disposition` 헤더에 UTF-8 파일명 인코딩 (`filename*=UTF-8''...`) |

---

## 5. 작업 우선순위

| 순서 | 작업 | 난이도 | 비고 |
|------|------|--------|------|
| 1 | `download_audio` Rust 커맨드 추가 | 낮음 | `dirs` 크레이트, `fs::copy` |
| 2 | `main.rs` 핸들러 등록 | 낮음 | 한 줄 추가 |
| 3 | Frontend 버튼 UI + 핸들러 변경 | 낮음 | 기존 `openReport` → `downloadAudio` |
| 4 | 다운로드 완료 토스트 알림 | 낮음 | 기존 토스트 컴포넌트 활용 |
| 5 | (향후) 웹 API 엔드포인트 | 중간 | 별도 백엔드 서버 필요 |
| 6 | (향후) `window.__TAURI__` 분기 | 낮음 | 환경 감지 후 분기 |
| 7 | (향후) 파일 저장소 마이그레이션 | 높음 | S3/NAS + UUID 매핑 |
