use std::process::{Command, Stdio};
use std::thread;
use std::io::{BufRead, BufReader};
use tauri::Emitter;
use crate::utils::{extended_path, find_appium, android_sdk_root};
use crate::types::ConnectionStatus;
use crate::state::{APPIUM_PROCESS_ANDROID, APPIUM_PROCESS_IOS,
                   TC_A_APPIUM_ANDROID, TC_A_APPIUM_IOS,
                   TC_B_APPIUM_ANDROID, TC_B_APPIUM_IOS};

/// 특정 포트를 점유한 프로세스 종료 (macOS/Linux: lsof | Windows: netstat+taskkill)
pub(crate) fn kill_port(port: u16) {
    #[cfg(windows)]
    {
        // netstat -aon에서 PID 추출 후 taskkill
        if let Ok(out) = Command::new("cmd")
            .args(&["/C", &format!("netstat -aon | findstr :{} | findstr LISTENING", port)])
            .output()
        {
            let stdout = String::from_utf8_lossy(&out.stdout);
            for line in stdout.lines() {
                if let Some(pid) = line.split_whitespace().last() {
                    let _ = Command::new("taskkill")
                        .args(&["/F", "/PID", pid])
                        .output();
                }
            }
        }
    }
    #[cfg(not(windows))]
    {
        let _ = Command::new("bash")
            .args(&["-c", &format!("lsof -ti tcp:{} | xargs kill -9 2>/dev/null", port)])
            .output();
    }
}

pub(crate) fn build_appium_cmd(appium_bin: &str, sdk_root: &str, port: u16) -> Command {
    let mut cmd = Command::new(appium_bin);
    cmd.env("PATH", extended_path())
       .env("ANDROID_HOME", sdk_root)
       .env("ANDROID_SDK_ROOT", sdk_root)
       .args(&["-p", &port.to_string()]);
    if port == 4724 {
        cmd.env("APPIUM_XCUITEST_PREFER_DEVICECTL", "1");
    }
    cmd
}

// ADB 경로 찾기 헬퍼 함수

pub(crate) fn strip_ansi(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\x1b' {
            if chars.peek() == Some(&'[') {
                chars.next();
                while let Some(&nc) = chars.peek() {
                    chars.next();
                    if nc.is_ascii_alphabetic() { break; }
                }
            }
        } else {
            result.push(c);
        }
    }
    result
}

#[tauri::command]
pub async fn start_appium_server(app: tauri::AppHandle) -> Result<ConnectionStatus, String> {
    let emit_log = |msg: &str| {
        let _ = app.emit("appium-log", msg.to_string());
        println!("{}", msg);
    };

    emit_log("[Appium] 서버 시작 중... (Android:4723 / iOS:4724)");

    // 기존 프로세스 종료 (메모리 추적 + 포트 강제 해제)
    let mut android_guard = APPIUM_PROCESS_ANDROID.lock().expect("APPIUM_PROCESS_ANDROID Mutex 오염");
    if let Some(mut child) = android_guard.take() { let _ = child.kill(); }
    let mut ios_guard = APPIUM_PROCESS_IOS.lock().expect("APPIUM_PROCESS_IOS Mutex 오염");
    if let Some(mut child) = ios_guard.take() { let _ = child.kill(); }
    drop(android_guard);
    drop(ios_guard);
    // 포트에 남아있는 프로세스 종료 (크로스플랫폼)
    kill_port(4723);
    kill_port(4724);
    std::thread::sleep(std::time::Duration::from_millis(500));
    let mut android_guard = APPIUM_PROCESS_ANDROID.lock().expect("APPIUM_PROCESS_ANDROID Mutex 오염");
    let mut ios_guard = APPIUM_PROCESS_IOS.lock().expect("APPIUM_PROCESS_IOS Mutex 오염");

    let appium_bin = find_appium()
        .ok_or_else(|| "Appium을 찾을 수 없습니다. npm install -g appium 으로 설치하세요.".to_string())?;

    // Android Appium (4723)
    let sdk_root = android_sdk_root();
    match build_appium_cmd(&appium_bin, &sdk_root, 4723)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
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
            emit_log("[Appium] Android Appium 시작됨 (4723)");
            *android_guard = Some(child);
        }
        Err(e) => return Err(format!("Android Appium 시작 실패: {}", e)),
    }

    // iOS Appium (4724)
    match build_appium_cmd(&appium_bin, &sdk_root, 4724)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
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
                for line in reader.lines().flatten() {
                    let _ = app_d.emit("appium-log", format!("[4724/err] {}", strip_ansi(&line)));
                }
            });
            emit_log("[Appium] iOS Appium 시작됨 (4724)");
            *ios_guard = Some(child);
        }
        Err(e) => return Err(format!("iOS Appium 시작 실패: {}", e)),
    }

    // 대기
    std::thread::sleep(std::time::Duration::from_secs(3));
    emit_log("[Appium] ✅ 서버 준비 완료");

    Ok(ConnectionStatus {
        success: true,
        message: "✅ Appium 서버 시작됨 (Android: 4723, iOS: 4724)".to_string(),
    })
}

#[tauri::command]
pub async fn stop_appium_server() -> Result<ConnectionStatus, String> {
    println!("⏹️ Appium 서버 종료 중...");
    
    let mut android_stopped = false;
    let mut ios_stopped = false;
    
    // Android Appium 종료
    let mut android_guard = APPIUM_PROCESS_ANDROID.lock().expect("APPIUM_PROCESS_ANDROID Mutex 오염");
    if let Some(mut child) = android_guard.take() {
        let _ = child.kill();
        android_stopped = true;
        println!("✅ Android Appium 종료 (4723)");
    }
    
    // iOS Appium 종료
    let mut ios_guard = APPIUM_PROCESS_IOS.lock().expect("APPIUM_PROCESS_IOS Mutex 오염");
    if let Some(mut child) = ios_guard.take() {
        let _ = child.kill();
        ios_stopped = true;
        println!("✅ iOS Appium 종료 (4724)");
    }
    
    if android_stopped || ios_stopped {
        Ok(ConnectionStatus {
            success: true,
            message: "✅ Appium 서버 종료됨".to_string(),
        })
    } else {
        Ok(ConnectionStatus {
            success: true,
            message: "Appium 서버가 실행 중이 아닙니다.".to_string(),
        })
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// TC 전용 Appium 시작/중지
//   Group A (TC_01/TC_02): Android 4725 / iOS 4726
//   Group B (TC_03/TC_04): Android 4727 / iOS 4728
// ─────────────────────────────────────────────────────────────────────────────

/// TC Appium 헬스체크 — 포트가 응답하지 않으면 재시동
/// test_cmd.rs에서 각 TC 실행 직전에 호출한다.
pub(crate) fn ensure_tc_appium_running(
    app: &tauri::AppHandle,
    android_port: u16,
    ios_port: u16,
) -> Result<(), String> {
    let alive = |port: u16| -> bool {
        Command::new("curl")
            .args(["-sf", "--max-time", "2", &format!("http://127.0.0.1:{}/status", port)])
            .stdout(Stdio::null()).stderr(Stdio::null())
            .output().map(|o| o.status.success()).unwrap_or(false)
    };

    let and_alive = alive(android_port);
    let ios_alive = alive(ios_port);
    if and_alive && ios_alive {
        return Ok(());
    }

    let msg = format!(
        "[TC-Appium] 포트 {}:{} — Android={} iOS={} → 재시동 중...",
        android_port, ios_port,
        if and_alive { "OK" } else { "DEAD" },
        if ios_alive { "OK" } else { "DEAD" },
    );
    println!("{}", msg);
    let _ = app.emit("appium-log", msg);

    let appium_bin = find_appium()
        .ok_or_else(|| "Appium을 찾을 수 없습니다.".to_string())?;
    let sdk_root = android_sdk_root();

    // 죽어있는 포트만 재시동
    if !and_alive {
        kill_port(android_port);
        std::thread::sleep(std::time::Duration::from_millis(300));
        let (mutex_and, _) = tc_mutexes_for_port(android_port);
        match spawn_appium_for_port(app, &appium_bin, &sdk_root, android_port) {
            Ok(child) => { *mutex_and.lock().unwrap() = Some(child); }
            Err(e) => return Err(e),
        }
    }
    if !ios_alive {
        kill_port(ios_port);
        std::thread::sleep(std::time::Duration::from_millis(300));
        let (_, mutex_ios) = tc_mutexes_for_port(ios_port);
        match spawn_appium_for_port(app, &appium_bin, &sdk_root, ios_port) {
            Ok(child) => { *mutex_ios.lock().unwrap() = Some(child); }
            Err(e) => return Err(e),
        }
    }

    // 재시동 후 최대 10초 대기
    for _ in 0..20 {
        std::thread::sleep(std::time::Duration::from_millis(500));
        if alive(android_port) && alive(ios_port) {
            let _ = app.emit("appium-log", format!("[TC-Appium] ✅ {}:{} 재시동 완료", android_port, ios_port));
            return Ok(());
        }
    }
    Err(format!("TC Appium({}/{}) 재시동 후에도 응답하지 않습니다.", android_port, ios_port))
}

/// 포트 번호로 해당 TC 뮤텍스 쌍 반환 (android 포트 기준)
fn tc_mutexes_for_port(
    port: u16,
) -> (&'static std::sync::Mutex<Option<std::process::Child>>, &'static std::sync::Mutex<Option<std::process::Child>>) {
    use crate::state::{TC_A_APPIUM_ANDROID, TC_A_APPIUM_IOS, TC_B_APPIUM_ANDROID, TC_B_APPIUM_IOS};
    match port {
        4725 => (&TC_A_APPIUM_ANDROID, &TC_A_APPIUM_IOS),
        4726 => (&TC_A_APPIUM_IOS, &TC_A_APPIUM_ANDROID), // iOS 포트로 호출 시
        4727 => (&TC_B_APPIUM_ANDROID, &TC_B_APPIUM_IOS),
        _    => (&TC_B_APPIUM_IOS, &TC_B_APPIUM_ANDROID),
    }
}

/// port 번호 하나에 대해 Appium 프로세스를 생성하고 로그 스레드를 붙이는 헬퍼
fn spawn_appium_for_port(
    app: &tauri::AppHandle,
    appium_bin: &str,
    sdk_root: &str,
    port: u16,
) -> Result<std::process::Child, String> {
    let mut cmd = build_appium_cmd(appium_bin, sdk_root, port);
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = cmd.spawn()
        .map_err(|e| format!("TC Appium({}) 시작 실패: {}", port, e))?;

    if let Some(stdout) = child.stdout.take() {
        let a = app.clone();
        let p = port;
        thread::spawn(move || {
            for ln in BufReader::new(stdout).lines().flatten() {
                let _ = a.emit("appium-log", format!("[{}] {}", p, strip_ansi(&ln)));
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        let b = app.clone();
        let p = port;
        thread::spawn(move || {
            for ln in BufReader::new(stderr).lines().flatten() {
                let _ = b.emit("appium-log", format!("[{}/err] {}", p, strip_ansi(&ln)));
            }
        });
    }
    Ok(child)
}

/// TC 전용 Appium 서버 시작 (Group A: 4725/4726, Group B: 4727/4728)
/// group: "A" | "B" | "all"
#[tauri::command]
pub async fn start_tc_appium_servers(app: tauri::AppHandle, group: String) -> Result<ConnectionStatus, String> {
    let run_a = group == "A" || group == "all";
    let run_b = group == "B" || group == "all";

    // 기존 TC 프로세스 정리
    if run_a {
        kill_port(4725); kill_port(4726);
        if let Ok(mut g) = TC_A_APPIUM_ANDROID.lock() { if let Some(mut c) = g.take() { let _ = c.kill(); } }
        if let Ok(mut g) = TC_A_APPIUM_IOS.lock()     { if let Some(mut c) = g.take() { let _ = c.kill(); } }
    }
    if run_b {
        kill_port(4727); kill_port(4728);
        if let Ok(mut g) = TC_B_APPIUM_ANDROID.lock() { if let Some(mut c) = g.take() { let _ = c.kill(); } }
        if let Ok(mut g) = TC_B_APPIUM_IOS.lock()     { if let Some(mut c) = g.take() { let _ = c.kill(); } }
    }
    std::thread::sleep(std::time::Duration::from_millis(400));

    let appium_bin = find_appium()
        .ok_or_else(|| "Appium을 찾을 수 없습니다.".to_string())?;
    let sdk_root = android_sdk_root();
    let mut started: Vec<String> = Vec::new();

    if run_a {
        let _ = app.emit("appium-log", "[TC-Appium] Group A 시작 중... (4725/4726)".to_string());
        match spawn_appium_for_port(&app, &appium_bin, &sdk_root, 4725) {
            Ok(child) => { *TC_A_APPIUM_ANDROID.lock().unwrap() = Some(child); started.push("4725".into()); }
            Err(e) => { let _ = app.emit("appium-log", e.clone()); eprintln!("{}", e); }
        }
        match spawn_appium_for_port(&app, &appium_bin, &sdk_root, 4726) {
            Ok(child) => { *TC_A_APPIUM_IOS.lock().unwrap() = Some(child); started.push("4726".into()); }
            Err(e) => { let _ = app.emit("appium-log", e.clone()); eprintln!("{}", e); }
        }
    }
    if run_b {
        let _ = app.emit("appium-log", "[TC-Appium] Group B 시작 중... (4727/4728)".to_string());
        match spawn_appium_for_port(&app, &appium_bin, &sdk_root, 4727) {
            Ok(child) => { *TC_B_APPIUM_ANDROID.lock().unwrap() = Some(child); started.push("4727".into()); }
            Err(e) => { let _ = app.emit("appium-log", e.clone()); eprintln!("{}", e); }
        }
        match spawn_appium_for_port(&app, &appium_bin, &sdk_root, 4728) {
            Ok(child) => { *TC_B_APPIUM_IOS.lock().unwrap() = Some(child); started.push("4728".into()); }
            Err(e) => { let _ = app.emit("appium-log", e.clone()); eprintln!("{}", e); }
        }
    }

    std::thread::sleep(std::time::Duration::from_secs(3));
    let msg = format!("✅ TC Appium 시작됨 (포트: {})", started.join(", "));
    let _ = app.emit("appium-log", format!("[TC-Appium] 준비 완료 — 포트: {}", started.join(", ")));
    println!("{}", msg);
    Ok(ConnectionStatus { success: true, message: msg })
}

/// TC 전용 Appium 서버 전체 종료
#[tauri::command]
pub async fn stop_tc_appium_servers() -> Result<ConnectionStatus, String> {
    if let Ok(mut g) = TC_A_APPIUM_ANDROID.lock() { if let Some(mut c) = g.take() { let _ = c.kill(); } }
    if let Ok(mut g) = TC_A_APPIUM_IOS.lock()     { if let Some(mut c) = g.take() { let _ = c.kill(); } }
    if let Ok(mut g) = TC_B_APPIUM_ANDROID.lock() { if let Some(mut c) = g.take() { let _ = c.kill(); } }
    if let Ok(mut g) = TC_B_APPIUM_IOS.lock()     { if let Some(mut c) = g.take() { let _ = c.kill(); } }
    for port in [4725u16, 4726, 4727, 4728] { kill_port(port); }
    println!("✅ TC Appium 서버 전체 종료 (4725-4728)");
    Ok(ConnectionStatus { success: true, message: "✅ TC Appium 종료됨".to_string() })
}

