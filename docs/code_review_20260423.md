# 전체 코드리뷰 보고서 (2026-04-23)

## 1) 리뷰 범위
- 저장소: `/Users/qabulls/Documents/sound`
- 집중 범위: `sound-test-app` (Tauri Rust + React + Python scripts)
- 기준: 현재 워크트리 상태(스테이징/미스테이징 포함)

## 2) 재검증 결과
- `npm run build` (sound-test-app): 성공
- `cargo check` (src-tauri): 성공
- `pytest -q tests` (src-tauri/scripts): **125개 중 3개 실패**
  - 실패: `tests/test_ios_wda_manager.py::TestGetIphoneIp::*` 3건

## 3) 잘하고 있는 점
- SQL 내보내기 보안 강화가 잘 적용됨.
  - 날짜 검증 및 파라미터 바인딩 적용: `sound-test-app/src-tauri/src/db_cmd.rs:647`, `:679`, `:740`, `:765`, `:782`
- 파일 삭제 명령에 허용 루트 검증이 추가됨.
  - `sound-test-app/src-tauri/src/util_cmd.rs:29-47`, `:54-57`
- Android 명령 실행에서 `os.system`을 `subprocess.run`으로 교체해 안전성과 오류 처리 개선.
  - `sound-test-app/src-tauri/scripts/audio_handler.py:205`, `:270`, `:437`
- 반복 대기 로직에서 `setInterval` 정리가 보강되어 타이머 누수 가능성이 감소.
  - `sound-test-app/src/App.tsx:398-401`, `:409-412`
  - `sound-test-app/src/hooks/useTcRunner.ts:1259-1262`
- SMTP 비밀번호를 Keychain으로 이전/저장하는 UI 흐름이 정리됨.
  - `sound-test-app/src/components/SettingsModal.tsx:307-323`, `:329-333`

## 4) 문제점 (심각도 순)

### [HIGH] 평문 SMTP 비밀번호 저장 경로가 여전히 남아 있음
- 근거
  - `.env.mail`에서 비밀번호 로드: `sound-test-app/src-tauri/scripts/crash_reporter.py:29-39`
  - 런타임에 `.env.mail`로 비밀번호 저장: `sound-test-app/src-tauri/scripts/crash_reporter.py:266-272`
  - 테스트 메일 스크립트가 평문 저장: `sound-test-app/src-tauri/scripts/send_test_mail.py:23`, `:38-40`, `:96`
  - `.env.mail` 무시 규칙 없음: `.gitignore`에 해당 패턴 부재 (`/Users/qabulls/Documents/sound/.gitignore`)
- 영향
  - 계정 탈취/오발송/내부 정보 유출 위험.

### [HIGH] 파일 저장 커맨드에서 파일명 경로 이탈 방어 미흡
- 근거
  - `tmp_dir.join(filename)` 직접 사용: `sound-test-app/src-tauri/src/util_cmd.rs:197`, `:209`
  - Desktop/reports 저장 시에도 파일명 정규화 없음: `sound-test-app/src-tauri/src/test_cmd.rs:29`, `:51`
- 영향
  - 절대경로나 `..` 포함 입력 시 의도 경로 밖 파일 생성/덮어쓰기 가능.

### [MEDIUM] iOS WDA 매니저 회귀로 단위테스트 3건 실패
- 근거
  - `dns-sd` stdout을 bytes로 가정해 decode: `sound-test-app/src-tauri/scripts/ios_wda_manager.py:138-143`
  - 테스트 실패 지점: `tests/test_ios_wda_manager.py` (GetIphoneIp 3건)
- 영향
  - CI 신뢰도 하락, 네트워크 탐지 경로 회귀 조기 탐지 어려움.

### [MEDIUM] 오디오 인터페이스 자동저장에 비동기 경쟁 가능성
- 근거
  - 상태 업데이트 직후 이전 상태를 사용해 저장 호출 가능: `sound-test-app/src/components/SettingsModal.tsx:85-93`
  - 변경 이벤트마다 즉시 저장 호출(요청 취소/직렬화 없음): `:63-83`
- 영향
  - 빠른 연속 조작 시 이전 값으로 저장될 가능성(간헐적 오설정).

### [LOW] 문구 품질 회귀(오탈자)
- 근거
  - `"바뀌지 수 있습니다"` 오탈자: `sound-test-app/src/i18n/locales/ko.ts:311`
- 영향
  - 사용자 신뢰/완성도 저하.

### [LOW] 보고서 열기 커맨드 경로 허용 범위 검증 없음
- 근거
  - 입력 경로 그대로 `open/xdg-open` 전달: `sound-test-app/src-tauri/src/test_cmd.rs:79-101`
- 영향
  - 데이터 소스가 오염되면 의도하지 않은 파일/URI 오픈 가능.

## 5) 개선 필요한 점
- 민감정보 저장 정책을 Keychain 단일 경로로 통일.
- Tauri 파일 쓰기/열기 커맨드에 공통 경로 정책(allowlist + canonicalize + basename 강제) 적용.
- 자동저장 로직을 `useEffect` 기반으로 단일 파이프라인화(디바운스 + 마지막 요청만 유효 처리).
- 회귀 테스트 보강: `ios_wda_manager`의 `dns-sd` 경로에 str/bytes/None 케이스 추가.
- i18n 문자열 검수 체크리스트(배포 전 맞춤법/문구 lint 수준 점검) 도입.

## 6) 대책 내용 (우선순위)

### 1순위 (즉시)
- `.env.mail` 저장/로드 코드 제거 또는 비활성화.
- `.gitignore`에 `sound-test-app/src-tauri/scripts/.env.mail` 추가.
- SMTP 앱 비밀번호 즉시 교체(회전).

### 2순위 (이번 스프린트)
- `save_temp_file`, `save_temp_text`, `save_xlsx`, `save_session_report`에 파일명 정규화 적용:
  - `Path::new(filename).file_name()`만 허용
  - 경로 결합 후 `canonicalize`로 허용 루트 재검증
- `open_report`에도 허용 루트/확장자 검증 추가.

### 3순위 (안정화)
- `ios_wda_manager` 출력 파싱 유틸을 별도 함수로 분리해 타입 방어(str/bytes/None) 적용.
- `SettingsModal` 자동저장을 request-id 기반으로 직렬화하여 stale write 차단.
- 오탈자 수정: `ko.ts` 문구 정정.

## 7) 종합
- 최근 변경에서 **DB 쿼리 보안, 파일 삭제 경로 제한, 타이머 정리**는 분명한 개선입니다.
- 다만 현재 릴리즈 기준으로는 **비밀번호 평문 저장 경로와 파일 저장 경로 검증 미흡**이 핵심 리스크입니다.
- 위 1순위 조치 완료 후 재검증(빌드/테스트/보안 점검) 권장합니다.
