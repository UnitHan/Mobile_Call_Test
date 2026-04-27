# Release Notes

---

## v0.2.0 — 2026-04-22

### New Features

#### UI / 앱 헤더
- **신호등 버튼 영역 텍스트 제거**: `AppHeader`에서 `app-title` span 제거 — macOS 신호등 옆 타이틀 텍스트 미노출
- **타이틀바 Overlay 모드**: `titleBarStyle: Overlay` + `hiddenTitle: true` 적용 — 프레임리스 스타일
- **앱 이름 변경**: `ixi-O 통화기능 테스트` → `ixi-O 음성통화 테스트 자동화`
- **드래그 영역**: `data-tauri-drag-region` 속성 추가 + `core:window:allow-start-dragging` capability

#### Android 디바이스 정보 표시
- `DeviceSection`에 `androidDevices` prop 추가 — 현재 인식된 Android 디바이스 UDID 실시간 표시

#### 오디오 인터페이스 설정 탭 (SettingsModal)
- 탭 레이블 i18n 처리: `"오디오 인터페이스"` 하드코딩 → `t("settings.tabs.audioInterface")` 번역 키
- 슬롯 레이아웃: `stg-field-row` → `.audio-slot-row` grid(`190px | 1fr`) 레이아웃으로 정렬 개선
- **저장 후 재시작 없이 즉시 반영**: 저장 버튼 클릭 시 `audio-interface-updated` 이벤트 → `loadAudioDevices()` 재호출
- i18n 키 추가: `ko.ts` / `en.ts` — `settings.tabs.audioInterface`, `settings.audioInterfaceTab.*` 전체

#### CSS
- `.btn-sm.btn-accent`: 채워진 파란색 배경 + 흰 텍스트 스타일 (`background: var(--accent)`)
- `.audio-iface-card`, `.audio-iface-name`, `.audio-iface-detail`, `.audio-iface-msg.ok/err` 추가
- `.audio-slot-row`, `.audio-slot-label`, `.audio-slot-select` 추가

### Improvements

#### WDA 기동 안정화 (`ios_wda_manager.py`)
- **기동 방식 전환**: `xcrun devicectl device process launch` → `xcodebuild test-without-building`
  - 기존 방식은 XCTest 환경 변수(`USE_PORT` 등)를 전달하지 못해 WDA HTTP 서버가 기동되지 않던 문제 해결
  - DerivedData에서 최신 `.xctestrun` 파일을 자동 탐색
  - xctestrun `EnvironmentVariables.USE_PORT` 값을 plistlib으로 읽어 포트를 동적으로 결정
- **포트 탐색 순서 변경**: `[8100, 8200, 27753]` → `[8110, 8100, 8200, 27753]` (8110 우선)
- **WDA 이중 실행 제거**: `find_wda_url`에서 auto-launch 로직 제거 — `appium_device_setup`에서만 1회 기동

#### WDA 포트 설정 (`config.py`)
- `WDA_PORT`: `8100` → `8110` (xctestrun `USE_PORT=8110` 기준)
- `wdaLocalPort`: `8100` → `8110`

#### WDA 빌드 스크립트 (`build_wda_ipa.sh`) — 신규
- `--xcode-setup` 모드: WDA xcodeproj 자동 오픈 + 서명 설정 단계별 안내
- `check_xcode_account()`: 빌드 전 프로비저닝 프로파일 0개 시 조기 실패 + 해결 방법 출력
- 지원 모드: 기본(빌드+설치), `--build-only`, `--install-only [UDID]`, `--xcode-setup`

#### 보안 강화 (`test_cmd.rs`)
- `save_audio_interface_config` 파일 경로 접근에 허용 루트 검증 추가
  - 허용: `~/Documents/sound`, `/tmp`, `$TMPDIR`
  - 그 외 경로 접근 시 `"허용되지 않은 경로입니다"` 오류 반환

#### 이벤트 정리 (`useAudioDevices.ts`)
- `audio-interface-updated` 이벤트 리스너 해제(`unlistenInterface`) 반환 클린업에 추가

### Bug Fixes
- `useTcRunner.ts`: `sleep()` 내부 `setTimeout` 콜백에서 `clearInterval` 누락 수정

---

### 변경 파일 요약

| 영역 | 파일 |
|------|------|
| UI | `AppHeader.tsx`, `DeviceSection.tsx`, `SettingsModal.tsx`, `App.css`, `App.tsx` |
| i18n | `ko.ts`, `en.ts` |
| Tauri 설정 | `tauri.conf.json`, `capabilities/default.json` |
| Rust | `test_cmd.rs`, `util_cmd.rs`, `db_cmd.rs`, `lib.rs` |
| Python | `ios_wda_manager.py`, `appium_device_setup.py`, `config.py` |
| 신규 스크립트 | `build_wda_ipa.sh` |
| React Hooks | `useAudioDevices.ts`, `useTcRunner.ts` |
| 문서 | `docs/작업일지_20260421.md`, `docs/작업일지_20260422.md` |
