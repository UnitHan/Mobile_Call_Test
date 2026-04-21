use std::process::{Command, Stdio};
use std::thread;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use serde_json;
use tauri::Emitter;
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::sync::{Arc, Mutex};
use crate::utils::{extended_path, find_python, find_appium, android_sdk_root, venv_python, scripts_dir};
use crate::types::{ConnectionStatus, TestRunResult, DropoutAnalysisResult};
use crate::state::{APPIUM_PROCESS_ANDROID, APPIUM_PROCESS_IOS, TEST_PROCESS, ANALYSIS_PROCESS,
                   PREV_TEST_COMPLETED_OK, WATCHDOG_DEVICES, ui_log};
use crate::appium_cmd::{build_appium_cmd, strip_ansi, ensure_tc_appium_running};
use base64::Engine as _;

/// base64 인코딩된 바이너리 데이터를 파일로 저장합니다
#[tauri::command]
pub fn save_xlsx(data_b64: String, default_name: String) -> Result<String, String> {
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(&data_b64)
        .map_err(|e| format!("base64 디코딩 실패: {e}"))?;

    // 기본 저장 경로: ~/Desktop/파일명
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    let desktop = PathBuf::from(&home).join("Desktop");
    let save_dir = if desktop.is_dir() { desktop } else { PathBuf::from(&home) };
    let save_path = save_dir.join(&default_name);

    std::fs::write(&save_path, &bytes)
        .map_err(|e| format!("파일 저장 실패: {e}"))?;

    // 저장 완료 후 Finder에서 열기
    #[cfg(target_os = "macos")]
    { let _ = std::process::Command::new("open").arg("-R").arg(&save_path).spawn(); }

    Ok(save_path.to_string_lossy().into_owned())
}

/// UTF-8 HTML 문자열을 reports/daily/ 폴더에 저장하고 경로를 반환합니다
#[tauri::command]
pub fn save_session_report(html: String, filename: String) -> Result<String, String> {
    // ~/Documents/sound/reports/daily/ 에 저장
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    let report_dir = PathBuf::from(&home)
        .join("Documents").join("sound").join("reports").join("daily");
    std::fs::create_dir_all(&report_dir)
        .map_err(|e| format!("디렉토리 생성 실패: {e}"))?;

    let save_path = report_dir.join(&filename);
    std::fs::write(&save_path, html.as_bytes())
        .map_err(|e| format!("파일 저장 실패: {e}"))?;

    Ok(save_path.to_string_lossy().into_owned())
}

/// 이미지/파일을 base64 문자열로 읽어 반환합니다
#[tauri::command]
pub fn read_file_base64(path: String) -> Result<String, String> {
    let data = std::fs::read(&path).map_err(|e| format!("파일 읽기 실패: {}", e))?;
    Ok(base64::engine::general_purpose::STANDARD.encode(&data))
}

/// HTML/WAV 등 보고서 파일을 OS 기본 앱으로 엽니다
#[tauri::command]
pub fn open_report(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("open 실패: {}", e))?;
    }
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/C", "start", "", &path])
            .spawn()
            .map_err(|e| format!("start 실패: {}", e))?;
    }
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("xdg-open 실패: {}", e))?;
    }
    Ok(())
}

/// Appium 서버(android:4723, ios:4724)가 준비되었는지 확인하고,
/// 필요하면 재시작합니다. `prev_ok=true` & 두 서버 모두 생존 시 건너뜀.
fn ensure_appium_running(app: &tauri::AppHandle, prev_ok: bool) -> Result<(), String> {
    let android_alive = Command::new("curl")
        .args(&["-sf", "--max-time", "2", "http://127.0.0.1:4723/status"])
        .stdout(Stdio::null()).stderr(Stdio::null())
        .output().map(|o| o.status.success()).unwrap_or(false);
    let ios_alive = Command::new("curl")
        .args(&["-sf", "--max-time", "2", "http://127.0.0.1:4724/status"])
        .stdout(Stdio::null()).stderr(Stdio::null())
        .output().map(|o| o.status.success()).unwrap_or(false);

    if android_alive && ios_alive && prev_ok {
        println!("✅ Appium 서버 이미 실행 중 (이전 테스트 정상 완료) → 초기화 생략, 즉시 시작");
        return Ok(());
    }

    if !prev_ok && (android_alive || ios_alive) {
        println!("⚠️ 이전 테스트 실패 — Appium 재시작으로 세션 초기화");
    }

    // 전체 초기화
    println!("🧹 기존 세션 정리 중...");
    #[cfg(windows)]
    { let _ = Command::new("taskkill").args(&["/F", "/IM", "node.exe"]).output(); }
    #[cfg(not(windows))]
    { let _ = Command::new("pkill").args(&["-f", "appium"]).output(); }
    std::thread::sleep(std::time::Duration::from_millis(1500));

    let _ = Command::new("adb").arg("kill-server").output();
    std::thread::sleep(std::time::Duration::from_millis(1000));
    let _ = Command::new("adb").arg("start-server").output();
    std::thread::sleep(std::time::Duration::from_millis(2000));

    // Watchdog이 관리 중인 무선 기기를 adb kill-server 후 자동 재연결
    {
        let devices = WATCHDOG_DEVICES.lock().unwrap().clone();
        if !devices.is_empty() {
            println!("🔄 Watchdog 무선 기기 재연결 중: {}", devices.join(", "));
            for udid in &devices {
                let out = Command::new("adb")
                    .args(&["connect", udid])
                    .output()
                    .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
                    .unwrap_or_default();
                println!("  [↺] {} → {}", udid, out);
            }
            std::thread::sleep(std::time::Duration::from_millis(1000));
        }
    }
    let mut android_guard = APPIUM_PROCESS_ANDROID.lock().unwrap();
    *android_guard = None;
    let mut ios_guard = APPIUM_PROCESS_IOS.lock().unwrap();
    *ios_guard = None;

    println!("🔄 Appium 서버 시작 중...");
    let appium_bin = find_appium()
        .ok_or_else(|| "Appium을 찾을 수 없습니다. npm install -g appium 으로 설치하세요.".to_string())?;
    let sdk_root = android_sdk_root();

    match build_appium_cmd(&appium_bin, &sdk_root, 4723)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn() {
        Ok(mut child) => {
            let stdout = child.stdout.take().expect("stdout: Stdio::piped() 필요");
            let stderr = child.stderr.take().expect("stderr: Stdio::piped() 필요");
            let app_a = app.clone();
            thread::spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().flatten() {
                    let _ = app_a.emit("appium-log", format!("[4723] {}", strip_ansi(&line)));
                }
            });
            let app_b = app.clone();
            thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines().flatten() {
                    let _ = app_b.emit("appium-log", format!("[4723/err] {}", strip_ansi(&line)));
                }
            });
            println!("  ✓ Android Appium 시작됨 (4723)");
            *android_guard = Some(child);
        }
        Err(e) => return Err(format!("Android Appium 시작 실패: {}", e)),
    }
    match build_appium_cmd(&appium_bin, &sdk_root, 4724)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn() {
        Ok(mut child) => {
            let stdout = child.stdout.take().expect("stdout: Stdio::piped() 필요");
            let stderr = child.stderr.take().expect("stderr: Stdio::piped() 필요");
            let app_c = app.clone();
            thread::spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().flatten() {
                    let _ = app_c.emit("appium-log", format!("[4724] {}", strip_ansi(&line)));
                }
            });
            let app_d = app.clone();
            thread::spawn(move || {
                let reader = BufReader::new(stderr);
                let mut hang_count = 0u32;
                let mut alerted = false;
                for line in reader.lines().flatten() {
                    let stripped = strip_ansi(&line);
                    // iProxy "Could not find" / "socket hang up" 반복 감지 → 팝업 알림
                    if stripped.contains("Could not find the expected device") || stripped.contains("socket hang up") {
                        hang_count += 1;
                        if !alerted && hang_count >= 5 {
                            alerted = true;
                            let _ = app_d.emit("device-alert",
                                "[DEVICE_ALERT] iPhone WDA에 반복 연결 실패 — Xcode에서 WebDriverAgent를 아이폰에 다시 빌드/설치한 후 재시도하세요.");
                        }
                    } else {
                        hang_count = 0;
                    }
                    let _ = app_d.emit("appium-log", format!("[4724/err] {}", &stripped));
                }
            });
            println!("  ✓ iOS Appium 시작됨 (4724)");
            *ios_guard = Some(child);
        }
        Err(e) => return Err(format!("iOS Appium 시작 실패: {}", e)),
    }
    println!("  ⏳ Appium 초기화 대기 (5초)...");
    std::thread::sleep(std::time::Duration::from_secs(5));
    println!("✅ Appium 서버 준비 완료\n");
    Ok(())
}

#[tauri::command]
pub async fn play_test_tone(app: tauri::AppHandle, device_index: Option<i64>, output_pair: Option<String>) -> Result<ConnectionStatus, String> {
    let python_path = if venv_python().exists() {
        venv_python().to_string_lossy().to_string()
    } else {
        find_python().ok_or("Python3를 찾을 수 없습니다.".to_string())?
    };
    let scripts = scripts_dir(&app);
    let script_path = scripts.join("play_test_tone.py");

    let mut cmd = Command::new(&python_path);
    cmd.env("PATH", extended_path())
       .args(["-u", &script_path.to_string_lossy()]);
    if let Some(idx) = device_index {
        cmd.args(["--device", &idx.to_string()]);
    }
    if let Some(ref op) = output_pair {
        if !op.is_empty() {
            cmd.args(["--output-pair", op]);
        }
    }

    let output = cmd.output()
        .map_err(|e| format!("Python 실행 실패: {}", e))?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let success = output.status.success() && !stdout.contains("❌");
    ui_log(&stdout);
    Ok(ConnectionStatus { success, message: stdout })
}

#[tauri::command]
pub async fn list_audio_devices(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    // 1) venv python 우선, 없으면 시스템 python3
    let python_path = if venv_python().exists() {
        venv_python().to_string_lossy().to_string()
    } else {
        find_python().ok_or("Python3를 찾을 수 없습니다.".to_string())?
    };
    let scripts = scripts_dir(&app);
    let script_path = scripts.to_string_lossy().to_string();
    let output = Command::new(&python_path)
        .env("PATH", extended_path())
        .args(["-c", &format!(
            "import sys; sys.path.insert(0, '{0}'); \
            from audio_handler import DeviceAudioPlayer; \
            import json; print(json.dumps(DeviceAudioPlayer.list_output_devices()))",
            script_path
        )])
        .output()
        .map_err(|e| format!("Python 실행 실패: {}", e))?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let devices: serde_json::Value = serde_json::from_str(&stdout)
        .unwrap_or(serde_json::json!([]));
    Ok(devices)
}

/// 현재 연결된 USB 오디오 인터페이스 목록 반환 (locationID + sd 인덱스 포함)
#[tauri::command]
pub async fn scan_audio_interfaces(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let python_path = if venv_python().exists() {
        venv_python().to_string_lossy().to_string()
    } else {
        find_python().ok_or("Python3를 찾을 수 없습니다.".to_string())?
    };
    let scripts = scripts_dir(&app);
    let script_path = scripts.to_string_lossy().to_string();
    let output = Command::new(&python_path)
        .env("PATH", extended_path())
        .args(["-c", &format!(
            "import sys; sys.path.insert(0, '{0}'); \
            from usb_audio_devices import scan_audio_interfaces; \
            import json; print(json.dumps(scan_audio_interfaces()))",
            script_path
        )])
        .output()
        .map_err(|e| format!("Python 실행 실패: {}", e))?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let result: serde_json::Value = serde_json::from_str(&stdout)
        .unwrap_or(serde_json::json!([]));
    Ok(result)
}

/// android_a / ios_b 슬롯의 locationID를 config.py에 저장
#[tauri::command]
pub async fn save_audio_interface_config(
    app: tauri::AppHandle,
    android_location_id: i64,
    ios_location_id: i64,
) -> Result<serde_json::Value, String> {
    let python_path = if venv_python().exists() {
        venv_python().to_string_lossy().to_string()
    } else {
        find_python().ok_or("Python3를 찾을 수 없습니다.".to_string())?
    };
    let scripts = scripts_dir(&app);
    let script_path = scripts.to_string_lossy().to_string();
    let output = Command::new(&python_path)
        .env("PATH", extended_path())
        .args(["-c", &format!(
            "import sys; sys.path.insert(0, '{0}'); \
            from usb_audio_devices import save_audio_interface_config; \
            import json; print(json.dumps(save_audio_interface_config({1}, {2})))",
            script_path, android_location_id, ios_location_id
        )])
        .output()
        .map_err(|e| format!("Python 실행 실패: {}", e))?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let result: serde_json::Value = serde_json::from_str(&stdout)
        .unwrap_or(serde_json::json!({"ok": false, "message": "JSON 파싱 실패"}));
    Ok(result)
}

/// config.py에 저장된 android_a / ios_b locationID를 반환
#[tauri::command]
pub async fn get_audio_interface_config(
    app: tauri::AppHandle,
) -> Result<serde_json::Value, String> {
    let python_path = if venv_python().exists() {
        venv_python().to_string_lossy().to_string()
    } else {
        find_python().ok_or("Python3를 찾을 수 없습니다.".to_string())?
    };
    let scripts = scripts_dir(&app);
    let script_path = scripts.to_string_lossy().to_string();
    let output = Command::new(&python_path)
        .env("PATH", extended_path())
        .args(["-c", &format!(
            "import sys; sys.path.insert(0, '{0}'); \
            from usb_audio_devices import get_audio_interface_config; \
            import json; r = get_audio_interface_config(); print(json.dumps(r) if r is not None else 'null')",
            script_path
        )])
        .output()
        .map_err(|e| format!("Python 실행 실패: {}", e))?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let result: serde_json::Value = serde_json::from_str(&stdout)
        .unwrap_or(serde_json::Value::Null);
    Ok(result)
}

#[tauri::command]
pub async fn run_ixio_test(
    app: tauri::AppHandle,
    speaker1_device: String,
    speaker2_device: String,
    speaker1_number: String,
    speaker2_number: String,
    speaker1_audio_file: String,
    speaker2_audio_file: String,
    speaker1_output_device: Option<i64>,
    speaker2_output_device: Option<i64>,
    speaker1_channel: Option<String>,
    speaker2_channel: Option<String>,
    // 녹음 채널 (CONNECT 6 입력 채널, 예: "6,7" = Loopback 1)
    speaker1_rec_channel: Option<String>,
    speaker2_rec_channel: Option<String>,
    // 출력 채널 쌍 (CONNECT 6 출력, 예: "2,3" = Out 3/4)
    speaker1_output_pair: Option<String>,
    speaker2_output_pair: Option<String>,
    // TC 전용 포트 (None이면 메인 Appium 4723/4724 사용)
    appium_port_android: Option<u16>,
    appium_port_ios: Option<u16>,
    // TC 유형 (TC_01 ~ TC_04, 빈 문자열 = 일반 테스트)
    tc_type: Option<String>,
    // 녹음 방식: "extract" (파일 추출, 기본) 또는 "direct" (AG03 믹서 직접 녹음)
    recording_mode: Option<String>,
    // 테스트 대상 앱 패키지/번들 (None이면 익시오 기본값)
    android_app_package: Option<String>,
    android_app_activity: Option<String>,
    ios_app_bundle_id: Option<String>,
    carrier: Option<String>,
) -> Result<TestRunResult, String> {
    // TC_02/TC_04 역방향 스왑은 프론트엔드(useTcRunner.ts)에서 처리됨
    // Rust에서는 전달받은 값을 그대로 사용

    println!("🎯 익시오 통화 테스트 시작");
    println!("  TC유형: {:?}", tc_type);
    println!("  화자1: {} ({})", speaker1_device, speaker1_number);
    println!("  화자2: {} ({})", speaker2_device, speaker2_number);
    println!("  화자1 오디오: {}", speaker1_audio_file);
    println!("  화자2 오디오: {}", speaker2_audio_file);

    // ── Android ADB 연결 사전 점검 ──────────────────────────────────────────
    // iOS UDID 형식: XXXXXXXX-XXXXXXXXXXXXXXXX (8+16 hex) → 아닌 것이 Android
    fn is_ios_udid(id: &str) -> bool {
        let p: Vec<&str> = id.splitn(2, '-').collect();
        p.len() == 2
            && p[0].len() == 8
            && p[1].len() == 16
            && p[0].chars().all(|c| c.is_ascii_hexdigit())
            && p[1].chars().all(|c| c.is_ascii_hexdigit())
    }
    // TLS mDNS 형식은 실제 IP 연결이 아님 → IP:PORT 연결 보장 후 effective ID 획득
    let effective_speaker1: String = if !is_ios_udid(&speaker1_device) {
        crate::device_cmd::adb_ensure_connected(&speaker1_device)?
    } else {
        speaker1_device.clone()
    };
    let effective_speaker2: String = if !is_ios_udid(&speaker2_device) {
        crate::device_cmd::adb_ensure_connected(&speaker2_device)?
    } else {
        speaker2_device.clone()
    };
    if effective_speaker1 != speaker1_device {
        println!("  📱 화자1 유효 ID (IP:PORT): {}", effective_speaker1);
    }
    if effective_speaker2 != speaker2_device {
        println!("  📱 화자2 유효 ID (IP:PORT): {}", effective_speaker2);
    }

    // Appium 서버 확인 및 필요 시 재시작
    // TC 모드(포트가 지정됨)일 때는 메인 Appium(4723/4724)을 건드리지 않는다.
    let is_tc_mode = appium_port_android.is_some() || appium_port_ios.is_some();
    let prev_ok = PREV_TEST_COMPLETED_OK.load(Ordering::Relaxed);
    if is_tc_mode {
        let and_port = appium_port_android.unwrap_or(4725);
        let ios_port = appium_port_ios.unwrap_or(4726);
        if !prev_ok {
            // 이전 테스트 실패 → UiAutomator2 크래시 가능성 → Appium 강제 재시작
            println!("⚠️ 이전 테스트 실패 — TC Appium 강제 재시작 (UiAutomator2 초기화)");
            let _ = app.emit("appium-log", format!("[TC-Appium] ⚠️ 이전 테스트 실패 → {}:{} 강제 재시작", and_port, ios_port));
            use crate::appium_cmd::kill_port;
            kill_port(and_port);
            kill_port(ios_port);
            std::thread::sleep(std::time::Duration::from_millis(500));
        }
        ensure_tc_appium_running(&app, and_port, ios_port)?;
    } else {
        ensure_appium_running(&app, prev_ok)?;
    }
    PREV_TEST_COMPLETED_OK.store(false, Ordering::Relaxed);

    // Python 경로: venv 우선, 없으면 시스템 python3
    let python_path_buf = if venv_python().exists() {
        venv_python()
    } else {
        PathBuf::from(find_python().ok_or("Python3를 찾을 수 없습니다. 앱 내 환경 설정을 먼저 실행하세요.".to_string())?)
    };
    let python_path = python_path_buf.to_string_lossy().to_string();
    let scripts = scripts_dir(&app);
    let script_path = scripts.join("ixio_automated_test.py").to_string_lossy().to_string();
    let project_dir = scripts.to_string_lossy().to_string();
    
    // 프로세스 시작 (-u: stdout/stderr 즉시 플러시, 버퍼링 없음)
    let sdk_root_py = android_sdk_root();
    let mut cmd = Command::new(&python_path);
    cmd.current_dir(&project_dir)
        .env("PYTHONUNBUFFERED", "1")
        .env("PATH", extended_path())
        .env("ANDROID_HOME", &sdk_root_py)
        .env("ANDROID_SDK_ROOT", &sdk_root_py)
        .arg("-u")
        .arg(&script_path)
        .arg("--speaker1-device")
        .arg(&effective_speaker1)
        .arg("--speaker2-device")
        .arg(&effective_speaker2)
        .arg("--speaker1-number")
        .arg(&speaker1_number)
        .arg("--speaker2-number")
        .arg(&speaker2_number)
        .arg("--speaker1-audio")
        .arg(&speaker1_audio_file)
        .arg("--speaker2-audio")
        .arg(&speaker2_audio_file)
        .args(speaker1_output_device.map(|d| vec!["--speaker1-output-device".to_string(), d.to_string()]).unwrap_or_default())
        .args(speaker2_output_device.map(|d| vec!["--speaker2-output-device".to_string(), d.to_string()]).unwrap_or_default())
        .args(speaker1_channel.as_deref().filter(|c| *c == "L" || *c == "R").map(|c| vec!["--speaker1-channel".to_string(), c.to_string()]).unwrap_or_default())
        .args(speaker2_channel.as_deref().filter(|c| *c == "L" || *c == "R").map(|c| vec!["--speaker2-channel".to_string(), c.to_string()]).unwrap_or_default())
        .args(speaker1_rec_channel.as_deref().filter(|c| !c.is_empty()).map(|c| vec!["--speaker1-rec-channel".to_string(), c.to_string()]).unwrap_or_default())
        .args(speaker2_rec_channel.as_deref().filter(|c| !c.is_empty()).map(|c| vec!["--speaker2-rec-channel".to_string(), c.to_string()]).unwrap_or_default())
        .args(speaker1_output_pair.as_deref().filter(|c| !c.is_empty()).map(|c| vec!["--speaker1-output-pair".to_string(), c.to_string()]).unwrap_or_default())
        .args(speaker2_output_pair.as_deref().filter(|c| !c.is_empty()).map(|c| vec!["--speaker2-output-pair".to_string(), c.to_string()]).unwrap_or_default())
        .args(appium_port_android.map(|p| vec!["--appium-port-android".to_string(), p.to_string()]).unwrap_or_default())
        .args(appium_port_ios.map(|p| vec!["--appium-port-ios".to_string(), p.to_string()]).unwrap_or_default())
        .args(tc_type.as_deref().filter(|t| !t.is_empty()).map(|t| vec!["--tc-type".to_string(), t.to_string()]).unwrap_or_default())
        .args(recording_mode.as_deref().filter(|m| !m.is_empty()).map(|m| vec!["--recording-mode".to_string(), m.to_string()]).unwrap_or_default())
        .args(android_app_package.as_deref().filter(|p| !p.is_empty()).map(|p| vec!["--android-app-package".to_string(), p.to_string()]).unwrap_or_default())
        .args(android_app_activity.as_deref().filter(|a| !a.is_empty()).map(|a| vec!["--android-app-activity".to_string(), a.to_string()]).unwrap_or_default())
        .args(ios_app_bundle_id.as_deref().filter(|b| !b.is_empty()).map(|b| vec!["--ios-app-bundle-id".to_string(), b.to_string()]).unwrap_or_default())
        .args(carrier.as_deref().filter(|c| !c.is_empty()).map(|c| vec!["--carrier".to_string(), c.to_string()]).unwrap_or_default())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    // Unix: 독립 프로세스 그룹(setsid)으로 시작 → stop_test 시 kill -9 -pgid 로
    // Python 하위 subprocess(adb 등)까지 한 번에 종료 → stdout 파이프 즉시 EOF
    #[cfg(unix)]
    unsafe {
        cmd.pre_exec(|| {
            libc::setsid();
            Ok(())
        });
    }

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Python 스크립트 실행 실패: {}", e))?;

    // PID 저장
    let pid = child.id();
    {
        let mut test_process = TEST_PROCESS.lock().unwrap();
        *test_process = Some(pid);
    }
    println!("📝 테스트 프로세스 ID: {}", pid);

    // stdout 실시간 라인 단위 읽기 + AUDIO_PROGRESS 이벤트 emit
    let stdout_pipe = child.stdout.take().expect("stdout: Stdio::piped() 필요");
    let stderr_pipe = child.stderr.take().expect("stderr: Stdio::piped() 필요");
    let app_clone = app.clone();

    // TC_RESULT_JSON: 파싱용 공유 변수
    let tc_result_json: Arc<Mutex<Option<serde_json::Value>>> = Arc::new(Mutex::new(None));
    let tc_result_json_clone = tc_result_json.clone();

    // stdout 마지막 N줄 캐시 (stderr가 빈 문자열일 때 디버깅용)
    const STDOUT_TAIL_LINES: usize = 15;
    let stdout_tail: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let stdout_tail_clone = stdout_tail.clone();

    let stdout_thread = thread::spawn(move || {
        let reader = BufReader::new(stdout_pipe);
        for line in reader.lines() {
            if let Ok(line) = line {
                println!("{}", line);
                if line.starts_with("TC_RESULT_JSON:") {
                    let json_str = &line["TC_RESULT_JSON:".len()..];
                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(json_str) {
                        *tc_result_json_clone.lock().unwrap() = Some(v);
                    }
                } else if line.starts_with("AUDIO_PROGRESS:") {
                    let _ = app_clone.emit("audio-progress", &line);
                } else if line.starts_with("[DEVICE_ALERT]") {
                    // Python 스크립트가 감지한 장치 준비 오류 → 팝업 알림 이벤트
                    let _ = app_clone.emit("device-alert", &line);
                    let _ = app_clone.emit("test-log", &line);
                } else {
                    let _ = app_clone.emit("test-log", &line);
                }
                // stdout 마지막 N줄 유지
                {
                    let mut tail = stdout_tail_clone.lock().unwrap();
                    tail.push(line);
                    if tail.len() > STDOUT_TAIL_LINES {
                        tail.remove(0);
                    }
                }
            }
        }
    });

    let app_stderr = app.clone();
    let stderr_thread = thread::spawn(move || {
        let mut buf = String::new();
        let reader = BufReader::new(stderr_pipe);
        for line in reader.lines() {
            if let Ok(line) = line {
                eprintln!("{}", line);
                let _ = app_stderr.emit("test-log", format!("[stderr] {}", &line));
                buf.push_str(&line);
                buf.push('\n');
            }
        }
        buf
    });

    // 프로세스 완료 대기
    let status = child.wait()
        .map_err(|e| format!("스크립트 실행 중 오류: {}", e))?;
    stdout_thread.join().ok();
    let stderr_output = stderr_thread.join().unwrap_or_default();

    // 완료 후 PID 제거
    {
        let mut test_process = TEST_PROCESS.lock().unwrap();
        *test_process = None;
    }

    // TC_RESULT_JSON에서 수집된 음원/스크린샷 경로 추출
    let parsed = tc_result_json.lock().unwrap().clone();
    let ios_recording = parsed.as_ref()
        .and_then(|v| v["ios_recording"].as_str())
        .unwrap_or("").to_string();
    let android_recording = parsed.as_ref()
        .and_then(|v| v["android_recording"].as_str())
        .unwrap_or("").to_string();
    let screenshots: Vec<String> = parsed.as_ref()
        .and_then(|v| v["screenshots"].as_array())
        .map(|arr| arr.iter().filter_map(|x| x.as_str().map(String::from)).collect())
        .unwrap_or_default();
    let vishing_detected: Option<bool> = parsed.as_ref()
        .and_then(|v| v["vishing_detected"].as_bool());

    if status.success() {
        // 정상 완료 플래그 설정 → 다음 재시작 시 세션 정리 생략
        PREV_TEST_COMPLETED_OK.store(true, Ordering::Relaxed);
        println!("♻️  다음 재시작 시 빠른 재시작 모드 활성화됨");
        Ok(TestRunResult {
            success: true,
            message: "✅ 테스트 완료".to_string(),
            ios_recording,
            android_recording,
            screenshots,
            vishing_detected,
        })
    } else if status.code() == Some(2) {
        // exit code 2 = 통화 강제 종료 → 동일 회차 재시작 신호
        PREV_TEST_COMPLETED_OK.store(false, Ordering::Relaxed);
        Ok(TestRunResult {
            success: false,
            message: "⚠️ 통화 강제 종료 감지 — 동일 회차 재시작".to_string(),
            ios_recording: String::new(),
            android_recording: String::new(),
            screenshots: vec![],
            vishing_detected: None,
        })
    } else if status.code() == Some(3) {
        // exit code 3 = 앱 크래시 감지 → 로그/메일 처리 완료, 재시작 신호
        PREV_TEST_COMPLETED_OK.store(false, Ordering::Relaxed);
        Ok(TestRunResult {
            success: false,
            message: "🚨 앱 크래시 감지 — 크래시 리포트 발송 완료, 재시작".to_string(),
            ios_recording: String::new(),
            android_recording: String::new(),
            screenshots: vec![],
            vishing_detected: None,
        })
    } else {
        // 실패 시 다음 실행은 전체 초기화
        PREV_TEST_COMPLETED_OK.store(false, Ordering::Relaxed);
        let exit_code = status.code().map(|c| c.to_string()).unwrap_or_else(|| "signal".to_string());
        let detail = if stderr_output.trim().is_empty() {
            let tail = stdout_tail.lock().unwrap();
            if tail.is_empty() {
                "(stderr/stdout 모두 비어있음)".to_string()
            } else {
                format!("[stdout 마지막 {}줄]\n{}", tail.len(), tail.join("\n"))
            }
        } else {
            stderr_output
        };
        Err(format!("테스트 실패 (exit={}): {}", exit_code, detail))
    }
}

#[tauri::command]
pub async fn stop_test() -> Result<ConnectionStatus, String> {
    println!("🛑 테스트 강제 종료 중...");

    // 1. Python 테스트 프로세스 종료
    // 단계1: SIGTERM → Python SIGTERM 핸들러가 end_call()로 기기 통화를 먼저 끊음
    // 단계2: 3초 대기 후에도 살아있으면 SIGKILL로 강제 종료
    let mut test_process = TEST_PROCESS.lock().unwrap();
    if let Some(pid) = test_process.take() {
        // SIGTERM으로 프로세스 그룹 전체에 정상 종료 요청
        let _ = Command::new("kill").args(&["-15", &format!("-{}", pid)]).output();
        let _ = Command::new("kill").args(&["-15", &pid.to_string()]).output();
        println!("📵 SIGTERM 전송 → Python이 end_call() 실행 중 (최대 3초 대기)...");
        drop(test_process);

        // 3초간 종료 대기 (0.3초 간격으로 생존 확인)
        let mut alive = true;
        for _ in 0..10 {
            std::thread::sleep(std::time::Duration::from_millis(300));
            let check = Command::new("kill").args(&["-0", &pid.to_string()]).output();
            if check.map(|o| !o.status.success()).unwrap_or(true) {
                alive = false;
                break;
            }
        }

        // 항상 process group SIGKILL 전송 — Python이 sys.exit()로 빠르게 종료해도
        // audio_player_worker 등 자식 subprocess가 orphan으로 남을 수 있으므로
        // 메인 프로세스 생사와 무관하게 프로세스 그룹 전체를 정리한다.
        let _ = Command::new("kill").args(&["-9", &format!("-{}", pid)]).output();
        if alive {
            println!("⚡ 3초 초과 → 메인 프로세스 SIGKILL");
            let _ = Command::new("kill").args(&["-9", &pid.to_string()]).output();
        }
        // audio_player_worker.py / afplay 잔존 프로세스 최종 정리 (pgid 이탈 대비)
        let _ = Command::new("pkill").args(&["-9", "-f", "audio_player_worker.py"]).output();
        let _ = Command::new("pkill").args(&["-9", "-f", "afplay"]).output();
        println!("✅ 테스트 프로세스 그룹({}) 종료 완료", pid);
    } else {
        drop(test_process);
    }

    // 1-1. 분석 프로세스 종료 (음단절 분석 진행 중이면 함께 kill)
    {
        let mut analysis_pid = ANALYSIS_PROCESS.lock().unwrap();
        if let Some(pid) = analysis_pid.take() {
            let _ = Command::new("kill").args(&["-9", &pid.to_string()]).output();
            let _ = Command::new("kill").args(&["-9", &format!("-{}", pid)]).output();
            println!("🧹 분석 프로세스({}) 강제 종료", pid);
        }
    }
    // analyze_hybrid.py 잔존 프로세스 최종 정리
    let _ = Command::new("pkill").args(&["-9", "-f", "analyze_hybrid.py"]).output();

    // 2. Appium 자식 프로세스도 종료 (재시작 시 포트 충돌 방지)
    {
        let mut ag = APPIUM_PROCESS_ANDROID.lock().unwrap();
        if let Some(mut child) = ag.take() { let _ = child.kill(); }
    }
    {
        let mut ig = APPIUM_PROCESS_IOS.lock().unwrap();
        if let Some(mut child) = ig.take() { let _ = child.kill(); }
    }
    // pkill로 잔여 Appium 프로세스 정리 + 포트 강제 해제
    let _ = Command::new("pkill").args(&["-9", "-f", "appium"]).output();
    let _ = Command::new("bash")
        .args(&["-c", "lsof -ti tcp:4723 | xargs kill -9 2>/dev/null; lsof -ti tcp:4724 | xargs kill -9 2>/dev/null"])
        .output();
    println!("🧹 Appium 프로세스 정리 완료 (다음 실행 시 새로 시작)");

    Ok(ConnectionStatus {
        success: true,
        message: "✅ 테스트 종료됨 (Appium 포함)".to_string(),
    })
}

/// 음단절 분석 실행
///
/// 1. `script_text`를 임시 파일에 저장
/// 2. `analyze_hybrid.py --limit 1 --ref-path-android <s1> --ref-path-ios <s2> --script-file <tmp>`
/// 3. Python 출력 → test-log 이벤트 실시간 스트림
/// 4. 완료 후 hybrid_report.html 브라우저에서 열기
#[tauri::command]
pub async fn run_dropout_analysis(
    app: tauri::AppHandle,
    ref_audio_path_s1: String,
    ref_audio_path_s2: String,
    script_path: String,
    profile_name: String,
    tc_type: Option<String>,
    app_tag: Option<String>,
    android_app_package: Option<String>,
    ios_app_bundle_id: Option<String>,
) -> Result<DropoutAnalysisResult, String> {
    println!("📊 음단절 분석 시작 — 정답지S1: {} / 정답지S2: {} / 프로파일: {}",
             ref_audio_path_s1, ref_audio_path_s2, profile_name);

    // analyze_hybrid.py 경로: src-tauri/scripts → src-tauri → sound-test-app → sound(루트)
    let scripts = scripts_dir(&app);
    let sound_root = scripts.parent()          // src-tauri/scripts → src-tauri
        .and_then(|p| p.parent())              // src-tauri → sound-test-app
        .and_then(|p| p.parent())              // sound-test-app → sound (루트)
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."));

    // Python 경로: 프로젝트 루트 .venv → app support venv → 시스템 python3
    let project_venv = sound_root.join(".venv/bin/python");
    let python_path = if project_venv.exists() {
        project_venv.to_string_lossy().to_string()
    } else if venv_python().exists() {
        venv_python().to_string_lossy().to_string()
    } else {
        find_python().ok_or("Python3를 찾을 수 없습니다.".to_string())?
    };
    println!("  🐍 Python: {}", python_path);

    let analyze_py = sound_root.join("analyze_hybrid.py");

    if !analyze_py.exists() {
        return Err(format!("analyze_hybrid.py를 찾을 수 없습니다: {}", analyze_py.display()));
    }

    let analyze_py_str = analyze_py.to_string_lossy().to_string();
    let sound_root_str = sound_root.to_string_lossy().to_string();

    // 분석 실행
    let mut cmd = Command::new(&python_path);
    cmd.current_dir(&sound_root_str)
        .env("PYTHONUNBUFFERED", "1")
        .env("PATH", extended_path())
        .arg("-u")
        .arg(&analyze_py_str)
        .arg("--limit").arg("1");
    // TC 유형 전달
    let tc = tc_type.as_deref().unwrap_or("");
    if !tc.is_empty() {
        cmd.arg("--tc-type").arg(tc);
    }
    // 화자별 정답지 → 플랫폼 매핑:
    //   S1 출력포트 = CONNECT 6 [1] → Android 입력
    //   S2 출력포트 = CONNECT 6 [2] → iPhone 입력
    //
    //   TC_01: 화자1=Android(S1 발신), 화자2=iPhone(S2 발신)
    //     → Android 녹음 = iPhone이 보낸 S2,  iOS 녹음 = Android가 보낸 S1
    //   TC_02: 화자1=iPhone(S1 발신), 화자2=Android(S2 발신)
    //     → Android 녹음 = iPhone이 보낸 S1,  iOS 녹음 = Android가 보낸 S2
    let is_reverse_tc = tc == "TC_02" || tc == "TC_04";
    let (ref_for_android, ref_for_ios) = if is_reverse_tc {
        // TC_02: Android 녹음=S1, iOS 녹음=S2
        (&ref_audio_path_s1, &ref_audio_path_s2)
    } else {
        // TC_01: Android 녹음=S2, iOS 녹음=S1
        (&ref_audio_path_s2, &ref_audio_path_s1)
    };
    if is_reverse_tc {
        println!("  ↔️ TC_02/04: Android 녹음=S1, iOS 녹음=S2 매핑");
    }
    if !ref_for_android.is_empty() {
        cmd.arg("--ref-path-android").arg(ref_for_android);
    }
    if !ref_for_ios.is_empty() {
        cmd.arg("--ref-path-ios").arg(ref_for_ios);
    }
    // 대본 파일이 있으면 모든 TC에 전달 (프로파일별 대본 사용)
    if !script_path.is_empty() {
        cmd.arg("--script-file").arg(&script_path);
    }
    // 프로파일명이 있으면 --profile-name 전달 (보고서 시나리오 표시용)
    if !profile_name.is_empty() {
        cmd.arg("--profile-name").arg(&profile_name);
    }
    // TC 모드: 분석 완료 후 브라우저 자동 열기 억제 (보고서 버튼으로만 열도록)
    cmd.arg("--no-open");
    // 앱 패키지명 전달 (버전 조회용)
    if let Some(ref pkg) = android_app_package {
        if !pkg.is_empty() {
            cmd.arg("--android-app-package").arg(pkg);
        }
    }
    if let Some(ref bid) = ios_app_bundle_id {
        if !bid.is_empty() {
            cmd.arg("--ios-app-bundle-id").arg(bid);
        }
    }
    // TC_00: MOS 전용 → HTML 보고서 생성 건너뜀 (MOS 세션 보고서만 별도 생성)
    let is_mos_only = tc == "TC_00";
    if is_mos_only {
        cmd.arg("--mos-only");
    }
    // per-run 보고서 경로 — 날짜별 폴더 + epoch 초로 고유 파일명 생성 (덮어쓰기 방지)
    let epoch_secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let today = {
        // KST (UTC+9) 기준 날짜 계산
        let secs = epoch_secs + 9 * 3600;
        let days = (secs / 86400) as i64;
        // 시빌 달력 변환 (1970-01-01 기준)
        let z = days + 719468;
        let era = z / 146097;
        let doe = z - era * 146097;
        let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
        let y = yoe + era * 400;
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
        let mp = (5 * doy + 2) / 153;
        let d = doy - (153 * mp + 2) / 5 + 1;
        let m = if mp < 10 { mp + 3 } else { mp - 9 };
        let y = if m <= 2 { y + 1 } else { y };
        format!("{:04}-{:02}-{:02}", y, m, d)
    };
    // MOS-only 모드에서는 보고서 파일 생성 안 함
    if !is_mos_only {
        let report_dir = sound_root.join("reports").join(&today);
        std::fs::create_dir_all(&report_dir).ok();
        let tag = app_tag.as_deref().unwrap_or("ixiO_ixiO");
        let report_out = report_dir.join(format!("hybrid_report_{}_{}.html", tag, epoch_secs));
        cmd.arg("--output").arg(report_out.to_string_lossy().as_ref());
    }
    cmd
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = cmd.spawn()
        .map_err(|e| format!("analyze_hybrid.py 실행 실패: {}", e))?;

    // 분석 PID 저장 → stop_test 시 kill 가능
    let analysis_pid = child.id();
    {
        let mut guard = ANALYSIS_PROCESS.lock().unwrap();
        *guard = Some(analysis_pid);
    }

    let stdout_pipe = child.stdout.take().expect("stdout 필요");
    let stderr_pipe = child.stderr.take().expect("stderr 필요");
    let app_out = app.clone();
    let app_err = app.clone();

    // ANALYSIS_RESULT_JSON: 파싱용 공유 변수
    let analysis_json: Arc<Mutex<Option<serde_json::Value>>> = Arc::new(Mutex::new(None));
    let analysis_json_clone = analysis_json.clone();

    let stdout_thread = thread::spawn(move || {
        let reader = BufReader::new(stdout_pipe);
        for line in reader.lines().flatten() {
            println!("{}", line);
            if line.starts_with("ANALYSIS_RESULT_JSON:") {
                let json_str = &line["ANALYSIS_RESULT_JSON:".len()..];
                if let Ok(v) = serde_json::from_str::<serde_json::Value>(json_str) {
                    *analysis_json_clone.lock().unwrap() = Some(v);
                }
            } else {
                let _ = app_out.emit("test-log", &line);
            }
        }
    });
    let stderr_thread = thread::spawn(move || {
        let reader = BufReader::new(stderr_pipe);
        for line in reader.lines().flatten() {
            eprintln!("{}", line);
            if !line.contains("DeprecationWarning") && !line.contains("UserWarning") {
                let _ = app_err.emit("test-log", format!("[stderr] {}", &line));
            }
        }
    });

    let status = child.wait()
        .map_err(|e| format!("분석 실행 오류: {}", e))?;

    // 분석 프로세스 종료 → PID 정리
    {
        let mut guard = ANALYSIS_PROCESS.lock().unwrap();
        *guard = None;
    }

    stdout_thread.join().ok();
    stderr_thread.join().ok();

    if status.success() {
        // TC 모드: 브라우저 자동 열기 안 함 — 사용자가 보고서 버튼을 눌러야만 열림
        let report_path = sound_root.join("hybrid_report.html");
        let report_path_str = report_path.to_string_lossy().to_string();

        // ANALYSIS_RESULT_JSON에서 dropout_count, severity 파싱
        let parsed = analysis_json.lock().unwrap().clone();
        let dropout_count = parsed.as_ref()
            .and_then(|v| v["dropout_count"].as_i64())
            .unwrap_or(0);
        let severity = parsed.as_ref()
            .and_then(|v| v["severity"].as_str())
            .unwrap_or("없음").to_string();
        let report_from_json = parsed.as_ref()
            .and_then(|v| v["report_path"].as_str())
            .unwrap_or("").to_string();
        let final_report = if !report_from_json.is_empty() { report_from_json } else { report_path_str };
        let ios_visqol_mos = parsed.as_ref()
            .and_then(|v| v["ios_visqol_mos"].as_f64());
        let android_visqol_mos = parsed.as_ref()
            .and_then(|v| v["android_visqol_mos"].as_f64());
        let and_dropped_count  = parsed.as_ref().and_then(|v| v["and_dropped_count"].as_i64()).unwrap_or(0);
        let and_degraded_count = parsed.as_ref().and_then(|v| v["and_degraded_count"].as_i64()).unwrap_or(0);
        let and_poor_count     = parsed.as_ref().and_then(|v| v["and_poor_count"].as_i64()).unwrap_or(0);
        let and_severity       = parsed.as_ref().and_then(|v| v["and_severity"].as_str()).unwrap_or("없음").to_string();
        let ios_dropped_count  = parsed.as_ref().and_then(|v| v["ios_dropped_count"].as_i64()).unwrap_or(0);
        let ios_degraded_count = parsed.as_ref().and_then(|v| v["ios_degraded_count"].as_i64()).unwrap_or(0);
        let ios_poor_count     = parsed.as_ref().and_then(|v| v["ios_poor_count"].as_i64()).unwrap_or(0);
        let ios_severity       = parsed.as_ref().and_then(|v| v["ios_severity"].as_str()).unwrap_or("없음").to_string();
        let voip_delay_ms      = parsed.as_ref().and_then(|v| v["voip_delay_ms"].as_i64()).unwrap_or(0);
        let android_app_ver    = parsed.as_ref().and_then(|v| v["android_app_ver"].as_str()).unwrap_or("").to_string();
        let ios_app_ver        = parsed.as_ref().and_then(|v| v["ios_app_ver"].as_str()).unwrap_or("").to_string();
        let android_device     = parsed.as_ref().and_then(|v| v["android_device"].as_str()).unwrap_or("").to_string();
        let android_os_ver     = parsed.as_ref().and_then(|v| v["android_os_ver"].as_str()).unwrap_or("").to_string();
        let ios_device         = parsed.as_ref().and_then(|v| v["ios_device"].as_str()).unwrap_or("").to_string();
        let ios_os_ver         = parsed.as_ref().and_then(|v| v["ios_os_ver"].as_str()).unwrap_or("").to_string();
        let profile_name       = parsed.as_ref().and_then(|v| v["profile_name"].as_str()).unwrap_or("").to_string();

        Ok(DropoutAnalysisResult {
            success: true,
            message: "✅ 분석 완료 — 보고서 버튼으로 결과를 확인하세요.".to_string(),
            report_path: final_report,
            dropout_count,
            severity,
            ios_visqol_mos,
            android_visqol_mos,
            and_dropped_count,
            and_degraded_count,
            and_poor_count,
            and_severity,
            ios_dropped_count,
            ios_degraded_count,
            ios_poor_count,
            ios_severity,
            voip_delay_ms,            android_app_ver,
            ios_app_ver,
            android_device,
            android_os_ver,
            ios_device,
            ios_os_ver,
            profile_name,        })
    } else {
        Err("음단절 분석 실패 — 콘솔 로그를 확인하세요.".to_string())
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// MOS 전용 보고서 생성 (TC_00)
// ═══════════════════════════════════════════════════════════════════════════════

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MosReportResult {
    pub success: bool,
    pub report_path: String,
    pub message: String,
}

/// TC_00 세션 완료 후 MOS 측정 결과 집계 보고서 생성.
/// runs_json: 프론트엔드에서 전달하는 호별 결과 JSON 문자열
#[tauri::command]
pub async fn generate_mos_report(
    app: tauri::AppHandle,
    runs_json: String,
) -> Result<MosReportResult, String> {
    let _ = app.emit("test-log", "📊 MOS 보고서 생성 시작…");

    // 1) Python 경로
    let scripts = scripts_dir(&app);
    let sound_root = scripts.parent()
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."));

    let project_venv = sound_root.join(".venv/bin/python");
    let python_path = if project_venv.exists() {
        project_venv.to_string_lossy().to_string()
    } else if venv_python().exists() {
        venv_python().to_string_lossy().to_string()
    } else {
        find_python().ok_or("Python3를 찾을 수 없습니다.".to_string())?
    };

    let mos_report_py = scripts.join("mos_report.py");
    if !mos_report_py.exists() {
        return Err(format!("mos_report.py를 찾을 수 없습니다: {}", mos_report_py.display()));
    }

    // 2) 보고서 출력 경로: ~/Documents/sound/reports/{date}/mos_report_{epoch}.html
    let reports_dir = sound_root.join("reports");
    let epoch = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let date_str = {
        // KST (UTC+9) 기준 날짜 계산
        let secs = epoch + 9 * 3600;
        let days = (secs / 86400) as i64;
        let z = days + 719468;
        let era = z / 146097;
        let doe = z - era * 146097;
        let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
        let y = yoe + era * 400;
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
        let mp = (5 * doy + 2) / 153;
        let d = doy - (153 * mp + 2) / 5 + 1;
        let m = if mp < 10 { mp + 3 } else { mp - 9 };
        let y = if m <= 2 { y + 1 } else { y };
        format!("{:04}-{:02}-{:02}", y, m, d)
    };
    let date_dir = reports_dir.join(&date_str);
    std::fs::create_dir_all(&date_dir).map_err(|e| format!("보고서 폴더 생성 실패: {}", e))?;
    let epoch = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let output_html = date_dir.join(format!("mos_report_{}.html", epoch));

    // 3) 임시 JSON 파일 (runs_json → temp file)
    let tmp_input = date_dir.join(format!("mos_input_{}.json", epoch));
    std::fs::write(&tmp_input, &runs_json)
        .map_err(|e| format!("임시 JSON 작성 실패: {}", e))?;

    // 4) Python 실행
    let output = Command::new(&python_path)
        .arg(mos_report_py.to_string_lossy().as_ref())
        .arg("--input").arg(tmp_input.to_string_lossy().as_ref())
        .arg("--output").arg(output_html.to_string_lossy().as_ref())
        .env("PATH", extended_path())
        .current_dir(sound_root.to_string_lossy().as_ref())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| format!("mos_report.py 실행 실패: {}", e))?;

    // 임시 파일 정리
    let _ = std::fs::remove_file(&tmp_input);

    let stdout_str = String::from_utf8_lossy(&output.stdout);
    let stderr_str = String::from_utf8_lossy(&output.stderr);

    if !output.status.success() {
        let _ = app.emit("test-log", &format!("❌ MOS 보고서 생성 실패: {}", stderr_str));
        return Err(format!("mos_report.py 실패 (exit={}): {}", output.status, stderr_str));
    }

    // MOS_REPORT_PATH: 파싱
    let report_path = stdout_str.lines()
        .find(|l| l.starts_with("MOS_REPORT_PATH:"))
        .map(|l| l["MOS_REPORT_PATH:".len()..].to_string())
        .unwrap_or_else(|| output_html.to_string_lossy().to_string());

    let _ = app.emit("test-log", &format!("📊 MOS 보고서 생성 완료: {}", report_path));

    Ok(MosReportResult {
        success: true,
        report_path,
        message: "✅ MOS 보고서 생성 완료".to_string(),
    })
}
