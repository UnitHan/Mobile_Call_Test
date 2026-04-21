/// schedule_cmd.rs — 예약 테스트 및 화자 설정 영속 저장
///
/// localStorage 대신 앱 데이터 디렉터리의 JSON 파일에 저장.
/// dev/prod 재실행·강제종료·재빌드에도 데이터가 보존된다.

use std::path::PathBuf;
use once_cell::sync::OnceCell;

static SCHEDULES_PATH: OnceCell<PathBuf> = OnceCell::new();
static SPEAKER_CONFIG_PATH: OnceCell<PathBuf> = OnceCell::new();
static TC_SPEAKER_CONFIG_PATH: OnceCell<PathBuf> = OnceCell::new();

/// lib.rs setup() 에서 앱 데이터 디렉터리를 받아 경로를 초기화한다.
pub fn init_schedules_path(data_dir: &PathBuf) {
    let path = data_dir.join("schedules.json");
    SCHEDULES_PATH.set(path).ok();
    let sp = data_dir.join("speaker_config.json");
    SPEAKER_CONFIG_PATH.set(sp).ok();
    let tc = data_dir.join("tc_speaker_config.json");
    TC_SPEAKER_CONFIG_PATH.set(tc).ok();
    println!("[schedule] 저장 경로 초기화 완료");
}

/// 저장된 예약 목록 JSON 문자열 반환. 파일 없으면 빈 배열 "[]" 반환.
#[tauri::command]
pub fn load_schedules() -> String {
    match SCHEDULES_PATH.get() {
        Some(path) => std::fs::read_to_string(path).unwrap_or_else(|_| "[]".to_string()),
        None => "[]".to_string(),
    }
}

/// 예약 목록 JSON 문자열을 파일에 저장.
#[tauri::command]
pub fn save_schedules(schedules: String) -> Result<(), String> {
    let path = SCHEDULES_PATH
        .get()
        .ok_or_else(|| "schedule 경로 미초기화".to_string())?;
    std::fs::write(path, schedules.as_bytes()).map_err(|e| e.to_string())
}

// ── 화자(Speaker) 전역 설정 ──────────────────────────────────────────────────

/// 저장된 화자 전역 설정 JSON 반환. 파일 없으면 "{}" 반환.
#[tauri::command]
pub fn load_speaker_config() -> String {
    match SPEAKER_CONFIG_PATH.get() {
        Some(path) => std::fs::read_to_string(path).unwrap_or_else(|_| "{}".to_string()),
        None => "{}".to_string(),
    }
}

/// 화자 전역 설정 JSON을 파일에 저장.
#[tauri::command]
pub fn save_speaker_config(config: String) -> Result<(), String> {
    let path = SPEAKER_CONFIG_PATH
        .get()
        .ok_or_else(|| "speaker_config 경로 미초기화".to_string())?;
    std::fs::write(path, config.as_bytes()).map_err(|e| e.to_string())
}

// ── TC별 화자 설정 ───────────────────────────────────────────────────────────

/// 저장된 TC별 화자 설정 JSON 반환. 파일 없으면 "{}" 반환.
#[tauri::command]
pub fn load_tc_speaker_config() -> String {
    match TC_SPEAKER_CONFIG_PATH.get() {
        Some(path) => std::fs::read_to_string(path).unwrap_or_else(|_| "{}".to_string()),
        None => "{}".to_string(),
    }
}

/// TC별 화자 설정 JSON을 파일에 저장.
#[tauri::command]
pub fn save_tc_speaker_config(config: String) -> Result<(), String> {
    let path = TC_SPEAKER_CONFIG_PATH
        .get()
        .ok_or_else(|| "tc_speaker_config 경로 미초기화".to_string())?;
    std::fs::write(path, config.as_bytes()).map_err(|e| e.to_string())
}
