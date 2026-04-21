use std::process::Command;
use tauri::Emitter;
use crate::utils::{extended_path, find_python, find_node, find_appium,
                   app_support_dir, venv_python, scripts_dir};
use crate::types::{EnvItem, EnvCheckResult, ConnectionStatus};
use crate::device_cmd::find_adb;

pub(crate) fn run_version(prog: &str, args: &[&str]) -> Option<String> {
    Command::new("sh")
        .env("PATH", extended_path())
        .args(["-c", &format!("{} {}", prog, args.join(" "))])
        .output()
        .ok()
        .map(|o| {
            let out = String::from_utf8_lossy(&o.stdout).to_string();
            let err = String::from_utf8_lossy(&o.stderr).to_string();
            let combined = if out.is_empty() { err } else { out };
            combined.lines().next().unwrap_or("").trim().to_string()
        })
}

#[tauri::command]
pub async fn check_environment() -> Result<EnvCheckResult, String> {
    let mut items: Vec<EnvItem> = Vec::new();

    // Node.js
    let node_ver = find_node().and_then(|p| run_version(&p, &["--version"]));
    items.push(EnvItem {
        key: "node".into(),
        label: "Node.js".into(),
        ok: node_ver.is_some(),
        version: node_ver.clone().unwrap_or_default(),
        hint: if node_ver.is_none() { "https://nodejs.org 에서 설치 또는 brew install node".into() } else { String::new() },
    });

    // Appium
    let appium_path = find_appium();
    let appium_ver = appium_path.as_ref().and_then(|p| run_version(p, &["--version"]));
    items.push(EnvItem {
        key: "appium".into(),
        label: "Appium".into(),
        ok: appium_ver.is_some(),
        version: appium_ver.clone().unwrap_or_default(),
        hint: if appium_ver.is_none() { "npm install -g appium".into() } else { String::new() },
    });

    // Appium UiAutomator2 (Android)
    let ua2_ok = appium_path.as_ref().map(|p| {
        Command::new("sh")
            .env("PATH", extended_path())
            .args(["-c", &format!("{} driver list --installed 2>&1", p)])
            .output()
            .map(|o| String::from_utf8_lossy(&o.stdout).contains("uiautomator2"))
            .unwrap_or(false)
    }).unwrap_or(false);
    items.push(EnvItem {
        key: "appium_ua2".into(),
        label: "Appium UiAutomator2".into(),
        ok: ua2_ok,
        version: String::new(),
        hint: if !ua2_ok { "appium driver install uiautomator2".into() } else { String::new() },
    });

    // Appium XCUITest (iOS)
    let xcui_ok = appium_path.as_ref().map(|p| {
        Command::new("sh")
            .env("PATH", extended_path())
            .args(["-c", &format!("{} driver list --installed 2>&1", p)])
            .output()
            .map(|o| String::from_utf8_lossy(&o.stdout).contains("xcuitest"))
            .unwrap_or(false)
    }).unwrap_or(false);
    items.push(EnvItem {
        key: "appium_xcui".into(),
        label: "Appium XCUITest (iOS)".into(),
        ok: xcui_ok,
        version: String::new(),
        hint: if !xcui_ok { "appium driver install xcuitest".into() } else { String::new() },
    });

    // ADB
    let adb_result = find_adb();
    let adb_ver = adb_result.as_ref().ok().and_then(|p| run_version(p, &["version"]));
    items.push(EnvItem {
        key: "adb".into(),
        label: "ADB (Android Debug Bridge)".into(),
        ok: adb_result.is_ok(),
        version: adb_ver.unwrap_or_default(),
        hint: if adb_result.is_err() { "Android Studio → SDK Manager → SDK Tools → Android SDK Platform-Tools 설치".into() } else { String::new() },
    });

    // Python3
    let py_path = find_python();
    let py_ver = py_path.as_ref().and_then(|p| run_version(p, &["--version"]));
    items.push(EnvItem {
        key: "python3".into(),
        label: "Python 3".into(),
        ok: py_ver.is_some(),
        version: py_ver.clone().unwrap_or_default(),
        hint: if py_ver.is_none() { "brew install python3".into() } else { String::new() },
    });

    // Xcode CLI (xcrun / simctl) — macOS 전용, Windows에서는 검사 생략
    #[cfg(not(windows))]
    {
        let xcrun_ok = run_version("xcrun", &["-f", "simctl"]).is_some();
        items.push(EnvItem {
            key: "xcode_cli".into(),
            label: "Xcode CLI Tools".into(),
            ok: xcrun_ok,
            version: String::new(),
            hint: if !xcrun_ok { "xcode-select --install".into() } else { String::new() },
        });
    }

    // tidevice (크로스플랫폼 iOS 도구)
    let tidevice_ver = run_version("tidevice", &["version"]);
    items.push(EnvItem {
        key: "tidevice".into(),
        label: "tidevice (iOS WDA 설치)".into(),
        ok: tidevice_ver.is_some(),
        version: tidevice_ver.clone().unwrap_or_default(),
        hint: if tidevice_ver.is_none() { "pip install tidevice".into() } else { String::new() },
    });

    // Python 환경 (venv + 패키지)
    let venv_py = venv_python();
    let python_env_ready = venv_py.exists() && {
        Command::new(&venv_py)
            .args(["-c", "import sounddevice, appium, selenium"])
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    };
    items.push(EnvItem {
        key: "python_env".into(),
        label: "Python 패키지 (venv)".into(),
        ok: python_env_ready,
        version: String::new(),
        hint: if !python_env_ready { "앱 내 '환경 설정' 버튼으로 자동 설치".into() } else { String::new() },
    });

    let all_ok = items.iter().all(|i| i.ok);
    Ok(EnvCheckResult { items, all_ok, python_env_ready })
}

#[tauri::command]
pub async fn setup_python_env(app: tauri::AppHandle) -> Result<ConnectionStatus, String> {
    let _ = app.emit("setup-log", "🔧 Python 환경 설정 시작...");

    // 1. 앱 지원 폴더 준비
    let support = app_support_dir();
    let scripts_dest = support.join("scripts");
    std::fs::create_dir_all(&scripts_dest)
        .map_err(|e| format!("디렉토리 생성 실패: {}", e))?;

    // 2. 번들 스크립트 복사
    let src = scripts_dir(&app);
    let files = ["ixio_automated_test.py", "audio_handler.py", "config.py",
                 "core_audio_utils.py", "call_state_detector.py",
                 "wda_auto_answer.py", "device_detector.py",
                 "wda_installer.py", "ios_wda_manager.py",
                 "appium_device_setup.py", "requirements.txt"];
    for f in &files {
        let from = src.join(f);
        let to = scripts_dest.join(f);
        if from.exists() {
            std::fs::copy(&from, &to)
                .map_err(|e| format!("파일 복사 실패 {}: {}", f, e))?;
        }
    }
    let _ = app.emit("setup-log", "✅ 스크립트 복사 완료");

    // 3. venv 생성
    let venv_dir = support.join("venv");
    let py = find_python().ok_or("Python3를 찾을 수 없습니다. python3 설치하세요.".to_string())?;

    // venv 생성 여부 판단: 플랫폼별 python 실행파일 경로
    #[cfg(windows)]
    let venv_python_path = venv_dir.join(r"Scripts\python.exe");
    #[cfg(not(windows))]
    let venv_python_path = venv_dir.join("bin/python");

    if !venv_python_path.exists() {
        let _ = app.emit("setup-log", "🐍 Python venv 생성 중...");
        let status = Command::new(&py)
            .env("PATH", extended_path())
            .args(["-m", "venv", venv_dir.to_str().unwrap()])
            .status()
            .map_err(|e| format!("venv 생성 실패: {}", e))?;
        if !status.success() {
            return Err("venv 생성에 실패했습니다.".to_string());
        }
        let _ = app.emit("setup-log", "✅ venv 생성 완료");
    }

    // 4. pip upgrade + requirements 설치
    #[cfg(windows)]
    let pip = venv_dir.join(r"Scripts\pip.exe");
    #[cfg(not(windows))]
    let pip = venv_dir.join("bin/pip");
    let req = scripts_dest.join("requirements.txt");
    let _ = app.emit("setup-log", "📦 패키지 설치 중... (1~2분 소요)");
    let output = Command::new(&pip)
        .env("PATH", extended_path())
        .args(["install", "--upgrade", "pip", "-q"])
        .output()
        .map_err(|e| format!("pip 업그레이드 실패: {}", e))?;
    if !output.status.success() {
        let msg = String::from_utf8_lossy(&output.stderr).to_string();
        return Err(format!("pip 업그레이드 실패: {}", msg));
    }
    if req.exists() {
        let output = Command::new(&pip)
            .env("PATH", extended_path())
            .args(["install", "-r", req.to_str().unwrap(), "-q"])
            .output()
            .map_err(|e| format!("패키지 설치 실패: {}", e))?;
        if !output.status.success() {
            let msg = String::from_utf8_lossy(&output.stderr).to_string();
            return Err(format!("패키지 설치 실패: {}", msg));
        }
    }
    let _ = app.emit("setup-log", "✅ 모든 패키지 설치 완료");
    Ok(ConnectionStatus { success: true, message: "✅ Python 환경 설정 완료".to_string() })
}


