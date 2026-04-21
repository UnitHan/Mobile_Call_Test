use std::process::Command;
use std::path::PathBuf;
use tauri::Manager;

pub fn extended_path() -> String {
    let current = std::env::var("PATH").unwrap_or_default();

    #[cfg(windows)]
    {
        let home = std::env::var("USERPROFILE").unwrap_or_default();
        // Android SDK, Python Scripts, npm global, Homebrew 등
        let extras = format!(
            r"{home}\AppData\Local\Android\Sdk\platform-tools;\
{home}\AppData\Roaming\npm;\
C:\Program Files\nodejs;\
C:\Python312;C:\Python311;C:\Python310;\
{home}\AppData\Local\Programs\Python\Python312;\
{home}\AppData\Local\Programs\Python\Python311;\
{home}\AppData\Local\Programs\Python\Python310",
            home = home
        );
        if current.is_empty() { extras } else { format!("{};{}", extras, current) }
    }

    #[cfg(not(windows))]
    {
        let home = std::env::var("HOME").unwrap_or_default();
        let extras = format!(
            "/usr/local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:\
/usr/bin:/bin:/usr/sbin:/sbin:\
{home}/.nvm/versions/node/$(ls {home}/.nvm/versions/node 2>/dev/null | tail -1)/bin:\
{home}/Library/Android/sdk/platform-tools:\
{home}/.local/bin",
            home = home
        );
        if current.is_empty() { extras } else { format!("{}:{}", extras, current) }
    }
}

/// 주어진 이름들 중 하나라도 PATH 상에 있으면 그 경로를 반환
pub fn find_tool(names: &[&str]) -> Option<String> {
    let path = extended_path();
    for name in names {
        if let Ok(out) = Command::new("sh")
            .env("PATH", &path)
            .args(["-c", &format!("which {}", name)])
            .output()
        {
            let p = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if !p.is_empty() && out.status.success() {
                return Some(p);
            }
        }
    }
    None
}

pub fn find_python() -> Option<String> {
    find_tool(&["python3", "python"])
}

pub fn find_node() -> Option<String> {
    find_tool(&["node"])
}

pub fn find_appium() -> Option<String> {
    find_tool(&["appium"])
}

/// macOS 기본 Android SDK 경로 (~/Library/Android/sdk)
pub fn android_sdk_root() -> String {
    let home = std::env::var("HOME").unwrap_or_default();
    // 1) 이미 환경변수로 설정된 경우 우선 사용
    if let Ok(v) = std::env::var("ANDROID_HOME") {
        if !v.is_empty() { return v; }
    }
    if let Ok(v) = std::env::var("ANDROID_SDK_ROOT") {
        if !v.is_empty() { return v; }
    }
    // 2) macOS 기본 위치
    format!("{}/Library/Android/sdk", home)
}

/// 앱 지원 디렉토리 (macOS: ~/Library/Application Support/... | Windows: %APPDATA%/...)
pub fn app_support_dir() -> PathBuf {
    #[cfg(windows)]
    {
        let appdata = std::env::var("APPDATA")
            .unwrap_or_else(|_| std::env::var("USERPROFILE")
                .map(|h| format!(r"{}\AppData\Roaming", h))
                .unwrap_or_else(|_| "C:\\Temp".to_string()));
        PathBuf::from(appdata).join("com.qabulls.call")
    }
    #[cfg(not(windows))]
    {
        let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
        PathBuf::from(home).join("Library/Application Support/com.qabulls.call")
    }
}

/// venv Python 실행파일 경로 (macOS/Linux: venv/bin/python | Windows: venv/Scripts/python.exe)
pub fn venv_python() -> PathBuf {
    #[cfg(windows)]
    { app_support_dir().join(r"venv\Scripts\python.exe") }
    #[cfg(not(windows))]
    { app_support_dir().join("venv/bin/python") }
}

/// 번들 또는 앱 지원 폴더 내 스크립트 디렉토리
pub fn scripts_dir(app: &tauri::AppHandle) -> PathBuf {
    // 0순위: 빌드 타임 cargo manifest 기준 scripts 폴더 (cargo tauri dev 개발 환경)
    // env!()는 컴파일 타임 상수이므로 절대경로 하드코딩 없이 동작
    let dev_scripts = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("scripts");
    if dev_scripts.join("ixio_automated_test.py").exists() {
        return dev_scripts;
    }
    // 1순위: 앱 지원 폴더 (설치 후 복사된 위치)
    let installed = app_support_dir().join("scripts");
    if installed.join("ixio_automated_test.py").exists() {
        return installed;
    }
    // 2순위: Tauri 번들 리소스 (앱 내부)
    if let Ok(res_dir) = app.path().resource_dir() {
        let bundled = res_dir.join("scripts");
        if bundled.join("ixio_automated_test.py").exists() {
            return bundled;
        }
    }
    // 3순위: manifest 기준 scripts (최후 폴백)
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("scripts")
}

