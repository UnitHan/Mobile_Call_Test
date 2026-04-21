use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use tauri::Emitter;

pub static APPIUM_PROCESS_ANDROID: Mutex<Option<std::process::Child>> = Mutex::new(None);  // 4723 메인
pub static APPIUM_PROCESS_IOS: Mutex<Option<std::process::Child>> = Mutex::new(None);      // 4724 메인

// TC 전용 Appium (메인과 포트 분리)
// Group A (TC_01 / TC_02): Android 4725 / iOS 4726
pub static TC_A_APPIUM_ANDROID: Mutex<Option<std::process::Child>> = Mutex::new(None);
pub static TC_A_APPIUM_IOS:     Mutex<Option<std::process::Child>> = Mutex::new(None);
// Group B (TC_03 / TC_04): Android 4727 / iOS 4728
pub static TC_B_APPIUM_ANDROID: Mutex<Option<std::process::Child>> = Mutex::new(None);
pub static TC_B_APPIUM_IOS:     Mutex<Option<std::process::Child>> = Mutex::new(None);

// 테스트 프로세스 저장용
pub static TEST_PROCESS: Mutex<Option<u32>> = Mutex::new(None);
// 분석 프로세스 저장용 (종료 시 함께 kill)
pub static ANALYSIS_PROCESS: Mutex<Option<u32>> = Mutex::new(None);

// 이전 테스트 정상 완료 여부 (true: 빠른 재시작 가능, false: 전체 초기화 필요)
pub static PREV_TEST_COMPLETED_OK: AtomicBool = AtomicBool::new(false);

// Android 마지막 성공 연결 IP:PORT (재연결 시 사용, 예: "192.168.219.103:5555")
pub static LAST_ANDROID_IP: Mutex<Option<String>> = Mutex::new(None);

// Watchdog 프로세스 (Android 무선 ADB 연결 유지)
pub static WATCHDOG_PROCESS: Mutex<Option<std::process::Child>> = Mutex::new(None);
// Watchdog이 감시 중인 기기 목록 (adb kill-server 후 자동 재연결에 사용)
pub static WATCHDOG_DEVICES: Mutex<Vec<String>> = Mutex::new(Vec::new());

// 전역 AppHandle: println! + 프론트엔드 test-log 동시 출력 (크레이트 내부 전용)
pub(crate) static GLOBAL_APP: Mutex<Option<tauri::AppHandle>> = Mutex::new(None);

pub fn ui_log(msg: &str) {
    println!("{}", msg);
    if let Ok(guard) = GLOBAL_APP.lock() {
        if let Some(app) = guard.as_ref() {
            let _ = app.emit("test-log", msg.to_string());
        }
    }
}


