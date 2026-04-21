use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;
use crate::types::{ConnectionStatus, DeviceInfo, DeviceListResponse};
use crate::state::{ui_log, WATCHDOG_PROCESS, WATCHDOG_DEVICES};
use crate::utils::{find_tool, extended_path, find_python, venv_python, scripts_dir};

/// PATH + Homebrew + Android SDK를 포함한 확장 경로에서 adb를 찾습니다.
/// 내부적으로 `utils::find_tool()` 에 위임합니다.
pub(crate) fn find_adb() -> Result<String, String> {
    find_tool(&["adb"])
        .ok_or_else(|| "ADB를 찾을 수 없습니다. Android SDK platform-tools를 설치하고 PATH에 추가하세요.".to_string())
}

#[tauri::command]
pub async fn connect_android_wireless(ip_port: String) -> Result<ConnectionStatus, String> {
    ui_log(&format!("🔌 Android 무선 연결 시도: {}", ip_port));
    
    let adb = find_adb()?;
    ui_log(&format!("📍 ADB 경로: {}", adb));
    
    // adb connect 명령어 실행
    ui_log(&format!("⚙️  실행 명령: {} connect {}", adb, ip_port));
    let output = Command::new(&adb)
        .arg("connect")
        .arg(&ip_port)
        .output()
        .map_err(|e| {
            let err_msg = format!("ADB 실행 실패: {}", e);
            println!("❌ {}", err_msg);
            err_msg
        })?;
    
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    
    ui_log(&format!("📤 ADB stdout: {}", stdout.trim()));
    if !stderr.is_empty() {
        ui_log(&format!("⚠️  ADB stderr: {}", stderr.trim()));
    }
    
    // 연결 성공 여부 확인
    let success = stdout.contains("connected") || stdout.contains("already connected");
    
    let result = ConnectionStatus {
        success,
        message: if success {
            format!("✅ {} 연결 성공", ip_port)
        } else {
            format!("❌ 연결 실패: {}", stdout.trim())
        },
    };
    
    ui_log(&format!("🏁 연결 결과: {}", result.message));

    // 무선 연결 성공 시 tcp:7779 포트 포워딩 설정
    if success {
        match Command::new(&adb)
            .args(&["-s", &ip_port, "forward", "tcp:7779", "tcp:7779"])
            .output()
        {
            Ok(fwd) if fwd.status.success() => {
                ui_log(&format!("✅ adb forward tcp:7779 설정 완료 ({})", ip_port));
                // 실제 등록 확인: adb -s <ip_port> forward --list
                if let Ok(list) = Command::new(&adb)
                    .args(&["-s", &ip_port, "forward", "--list"])
                    .output()
                {
                    let out = String::from_utf8_lossy(&list.stdout);
                    ui_log(&format!("📋 adb forward --list:\n{}", out.trim()));
                }
            }
            Ok(fwd) => {
                let msg = String::from_utf8_lossy(&fwd.stderr);
                ui_log(&format!("⚠️  adb forward 실패: {}", msg.trim()));
            }
            Err(e) => {
                ui_log(&format!("⚠️  adb forward 오류: {}", e));
            }
        }
    }

    Ok(result)
}

#[tauri::command]
pub async fn disconnect_android_wireless(ip_port: String) -> Result<ConnectionStatus, String> {
    ui_log(&format!("🔌 Android 무선 연결 종료: {}", ip_port));
    
    let adb = find_adb()?;
    
    // adb disconnect 명령어 실행
    let output = Command::new(&adb)
        .arg("disconnect")
        .arg(&ip_port)
        .output()
        .map_err(|e| format!("ADB 실행 실패: {}", e))?;
    
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    
    ui_log(&format!("ADB 출력: {}", stdout));
    if !stderr.is_empty() {
        ui_log(&format!("ADB 에러: {}", stderr));
    }
    
    Ok(ConnectionStatus {
        success: true,
        message: format!("✅ {} 연결 종료", ip_port),
    })
}

#[tauri::command]
pub fn get_android_ip() -> Result<ConnectionStatus, String> {
    ui_log("📡 Android 디바이스 IP 주소 확인 중...");
    
    let adb = find_adb()?;
    ui_log(&format!("📍 ADB 경로: {}", adb));
    
    // USB로 연결된 디바이스 확인
    ui_log("🔍 adb devices 실행 중...");
    let devices_output = Command::new(&adb)
        .arg("devices")
        .output()
        .map_err(|e| format!("ADB devices 실패: {}", e))?;
    
    let devices = String::from_utf8_lossy(&devices_output.stdout);
    ui_log(&format!("📋 adb devices:\n{}", devices.trim()));
    
    // 첫 번째 연결된 디바이스 찾기 (USB 연결 또는 무선 연결)
    let mut usb_device_id: Option<&str> = None;
    let mut wireless_device_ip: Option<&str> = None;
    
    for line in devices.lines().skip(1) {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with("List of devices") {
            continue;
        }
        
        let parts: Vec<&str> = trimmed.split_whitespace().collect();
        if parts.len() >= 2 && parts[1] == "device" {
            let device_identifier = parts[0];
            
            if device_identifier.contains(":5555") || (device_identifier.contains('.') && device_identifier.contains(':')) {
                // 이미 무선으로 연결된 디바이스 (IP:port 방식)
                wireless_device_ip = Some(device_identifier);
                ui_log(&format!("📡 무선 연결된 디바이스 발견: {}", device_identifier));
            } else if device_identifier.contains("_adb-tls-connect") {
                // Android 11+ TLS 무선 디버깅 방식 → IP:port 형식이 없을 때 USB처럼 취급
                if usb_device_id.is_none() {
                    usb_device_id = Some(device_identifier);
                    ui_log(&format!("📡 TLS 무선 연결된 디바이스 발견: {}", device_identifier));
                }
            } else {
                // USB로 연결된 디바이스
                usb_device_id = Some(device_identifier);
                ui_log(&format!("🔌 USB 연결된 디바이스 발견: {}", device_identifier));
            }
        }
    }
    
    // 이미 무선 연결이 되어 있으면 해당 IP 반환
    if let Some(wireless_ip) = wireless_device_ip {
        ui_log(&format!("✅ 이미 무선 연결됨: {}", wireless_ip));
        return Ok(ConnectionStatus {
            success: true,
            message: format!("ALREADY:{}", wireless_ip),
        });
    }
    
    // USB 또는 TLS 무선 기기가 있으면 IP:PORT 형식으로 전환
    let device_id = match usb_device_id {
        Some(id) => id,
        None => {
            ui_log("❌ 연결된 Android 디바이스를 찾을 수 없습니다.");
            return Ok(ConnectionStatus {
                success: false,
                message: "❌ USB 또는 무선으로 연결된 Android 디바이스가 없습니다.".to_string(),
            });
        }
    };

    let is_tls = device_id.contains("_adb-tls-connect");
    if is_tls {
        ui_log(&format!("📡 TLS 무선 기기 발견 — IP:PORT 형식으로 자동 전환 중: {}", device_id));
    } else {
        ui_log(&format!("📱 USB 디바이스 선택: {}", device_id));
    }

    // ── Wi-Fi IP 먼저 추출 (tcpip 전에 해야 TLS 연결이 살아 있음) ──────────
    ui_log("📡 Wi-Fi IP 주소 확인 중...");
    let device_ip: Option<String> = {
        // wlan0 우선, 없으면 ip route로 fallback
        let candidates = [
            vec!["-s", device_id, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"],
            vec!["-s", device_id, "shell", "ip", "route"],
        ];
        let mut found = None;
        for args in &candidates {
            if let Ok(out) = Command::new(&adb).args(args).output() {
                let txt = String::from_utf8_lossy(&out.stdout);
                ui_log(&format!("  → {}", txt.trim()));
                for line in txt.lines() {
                    if line.contains("inet") || line.contains("src") {
                        // "inet A.B.C.D/mask" 또는 "... src A.B.C.D"
                        let parts: Vec<&str> = line.split_whitespace().collect();
                        for (i, p) in parts.iter().enumerate() {
                            let candidate = if *p == "src" {
                                parts.get(i + 1).copied().unwrap_or("")
                            } else if *p == "inet" || *p == "inet6" {
                                parts.get(i + 1).copied().unwrap_or("").split('/').next().unwrap_or("")
                            } else {
                                continue;
                            };
                            // 로컬 사설 IP만 허용
                            if candidate.starts_with("192.168.")
                                || candidate.starts_with("10.")
                                || candidate.starts_with("172.")
                            {
                                found = Some(candidate.to_string());
                                break;
                            }
                        }
                    }
                    if found.is_some() { break; }
                }
            }
            if found.is_some() { break; }
        }
        found
    };

    let ip = match device_ip {
        Some(ref i) => i.as_str(),
        None => {
            return Ok(ConnectionStatus {
                success: false,
                message: "❌ Wi-Fi IP를 찾을 수 없습니다. Wi-Fi가 연결되어 있는지 확인하세요.".to_string(),
            });
        }
    };
    let ip_port = format!("{}:5555", ip);
    ui_log(&format!("✅ IP 주소 발견: {}", ip_port));

    // ── TCP/IP 모드 전환 ─────────────────────────────────────────────────────
    ui_log("🔧 TCP/IP 모드로 전환 중 (adb tcpip 5555)...");
    let tcpip_out = Command::new(&adb)
        .args(&["-s", device_id, "tcpip", "5555"])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_default();
    ui_log(&format!("  tcpip 결과: {}", tcpip_out));

    // TLS 연결이라면 tcpip 후 daemon이 재시작됨 → 잠시 대기
    let wait_secs = if is_tls { 3u64 } else { 5u64 };
    ui_log(&format!("⏳ {}초 대기 중...", wait_secs));
    thread::sleep(Duration::from_secs(wait_secs));

    // ── adb connect IP:5555 자동 시도 (TLS 기기일 때) ──────────────────────
    if is_tls {
        ui_log(&format!("🔌 자동 연결 시도: adb connect {}", ip_port));
        let conn_out = Command::new(&adb)
            .args(&["connect", &ip_port])
            .output()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
            .unwrap_or_default();
        ui_log(&format!("  connect 결과: {}", conn_out));

        if conn_out.contains("connected") && !conn_out.contains("unable") {
            ui_log(&format!("✅ IP:PORT 전환 완료: {}", ip_port));
            return Ok(ConnectionStatus {
                success: true,
                message: ip_port,
            });
        }
        // 연결 실패해도 IP 자체는 반환 (UI에서 수동 연결 가능)
        ui_log("⚠️  자동 connect 실패 — UI에서 수동으로 연결하세요");
        return Ok(ConnectionStatus {
            success: true,
            message: ip_port,
        });
    }

    // USB 기기: IP만 반환(UI에서 "연결" 버튼으로 connect 수행)
    ui_log("⚠️  USB 케이블 제거 후 '연결' 버튼을 누르세요.");
    Ok(ConnectionStatus {
        success: true,
        message: ip_port,
    })
}

#[tauri::command]
pub fn check_iphone_connection() -> Result<ConnectionStatus, String> {
    ui_log("📱 iPhone 연결 상태 확인 중...");

    // ── devicectl JSON + Python 파싱 (무선/USB 모두 지원) ──
    let tmp_path = "/tmp/devicectl_check.json";
    let ran = Command::new("xcrun")
        .args(&["devicectl", "list", "devices", "--json-output", tmp_path])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    if ran {
        let py_script = format!(
            r#"import json,sys,subprocess,re
def get_local_ip(name):
    try:
        r=subprocess.run(['dns-sd','-G','v4',f'{{name}}.local'],capture_output=True,timeout=3)
        out=(r.stdout or b'').decode(errors='ignore')
    except subprocess.TimeoutExpired as e:
        out=(e.stdout or b'').decode(errors='ignore')
    except Exception:
        return ''
    for m in re.finditer(r'(\d+\.\d+\.\d+\.\d+)',out):
        ip=m.group(1); parts=ip.split('.')
        if ip.startswith('192.168.') or ip.startswith('10.') or (ip.startswith('172.') and 16<=int(parts[1])<=31):
            return ip
    return ''
try:
    d=json.load(open('{}'))
    found=[]
    for dev in d.get('result',{{}}).get('devices',[]):
        conn=dev.get('connectionProperties',{{}})
        state=conn.get('tunnelState','')
        udid=dev.get('hardwareProperties',{{}}).get('udid','')
        name=dev.get('deviceProperties',{{}}).get('name','iPhone')
        transport=conn.get('transportType','')
        if state=='connected' and udid:
            if transport=='localNetwork':
                ip=get_local_ip(name)
                tag=f'무선 {{ip}}' if ip else '무선'
            elif transport=='wired':
                tag='유선'
            else:
                tag=transport or '?'
            found.append(f'{{name}} [{{tag}}] ({{udid}})')
    print('FOUND:'+', '.join(found) if found else 'NONE')
except Exception as e:
    print(f'ERR:{{e}}',file=sys.stderr); print('NONE')
"#,
            tmp_path
        );

        let mut py_cmd2 = Command::new("python3");
        py_cmd2.args(&["-c", &py_script]);
        if let Some(stdout) = run_cmd_timeout(py_cmd2, 8) {
            let stdout = stdout.trim().to_string();
            let _ = std::fs::remove_file(tmp_path);

            if stdout.starts_with("FOUND:") {
                let info = stdout.trim_start_matches("FOUND:").trim();
                ui_log(&format!("✅ iPhone 연결됨 (devicectl): {}", info));
                return Ok(ConnectionStatus {
                    success: true,
                    message: format!("✅ iPhone 연결됨: {}", info),
                });
            }
        }
        let _ = std::fs::remove_file(tmp_path);
    }

    // ── idevice_id fallback (USB 전용) ──
    if let Ok(output) = Command::new("idevice_id").arg("-l").output() {
        let stdout = String::from_utf8_lossy(&output.stdout);
        let found: Vec<&str> = stdout.lines().filter(|l| !l.trim().is_empty()).collect();
        if !found.is_empty() {
            ui_log(&format!("✅ iPhone 연결됨 (idevice_id USB): {}개", found.len()));
            return Ok(ConnectionStatus {
                success: true,
                message: format!("✅ iPhone 연결됨 ({}개)", found.len()),
            });
        }
    }

    Ok(ConnectionStatus {
        success: false,
        message: "❌ 연결된 iPhone이 없습니다. Xcode 무선 디버깅 또는 USB 연결을 확인하세요.".to_string(),
    })
}

/// spawn 후 secs초 초과 시 kill 후 stdout 반환 (크로스플랫폼: macOS / Windows / Linux)
pub(crate) fn run_cmd_timeout(mut cmd: Command, secs: u64) -> Option<String> {
    let mut child = cmd
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;

    let deadline = std::time::Instant::now() + Duration::from_secs(secs);
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,   // 정상 종료
            Ok(None) => {
                if std::time::Instant::now() >= deadline {
                    let _ = child.kill();
                    break;
                }
                thread::sleep(Duration::from_millis(200));
            }
            Err(_) => break,
        }
    }
    let out = child.wait_with_output().ok()?;
    Some(String::from_utf8_lossy(&out.stdout).to_string())
}

#[tauri::command]
pub fn list_android_devices() -> Result<DeviceListResponse, String> {
    ui_log("📱 Android 디바이스 목록 확인 중...");

    let adb = find_adb()?;

    // adb devices -l  (5초 타임아웃 – daemon 재시작 시 무한 블로킹 방지)
    let mut cmd = Command::new(&adb);
    cmd.args(&["devices", "-l"]);
    let stdout = run_cmd_timeout(cmd, 5).unwrap_or_default();
    ui_log(&format!("📋 adb devices:\n{}", stdout.trim()));

    let mut devices = Vec::new();
    // mDNS TLS 방식 UDID 목록 (adb-SERIAL._adb-tls-connect._tcp)
    // → IP:port 항목과 같은 모델이 없을 때만 포함
    let mut tls_devices: Vec<(String, String)> = Vec::new(); // (udid, name)
    let mut ip_models: std::collections::HashSet<String> = std::collections::HashSet::new();

    for line in stdout.lines().skip(1) {
        let t = line.trim();
        if t.is_empty() || t.starts_with("List of devices") { continue; }
        let parts: Vec<&str> = t.split_whitespace().collect();
        if parts.len() >= 2 && parts[1] == "device" {
            let udid = parts[0].to_string();
            let name = parts[2..].join(" ");
            if udid.contains("_adb-tls-connect") {
                // TLS mDNS 항목 — 일단 별도 보관
                tls_devices.push((udid, name));
            } else {
                // IP:port 또는 USB 시리얼 항목
                if udid.contains('.') && udid.contains(':') {
                    // 무선 IP:port → 모델 이름 수집
                    if let Some(m) = parts[2..].iter().find(|p| p.starts_with("model:")) {
                        ip_models.insert(m.to_string());
                    }
                }
                ui_log(&format!("✅ Android: {} - {}", udid, name));
                devices.push(DeviceInfo { udid, platform: "Android".to_string(), name, connected: true });
            }
        }
    }

    // TLS mDNS 항목: 같은 모델의 IP:port 항목이 없을 때만 포함
    for (udid, name) in tls_devices {
        let model = name.split_whitespace()
            .find(|p| p.starts_with("model:"))
            .map(|s| s.to_string());
        let has_ip_dup = model.as_ref().map(|m| ip_models.contains(m)).unwrap_or(false);
        if !has_ip_dup {
            ui_log(&format!("✅ Android (TLS무선): {} - {}", udid, name));
            devices.push(DeviceInfo { udid, platform: "Android".to_string(), name, connected: true });
        }
    }

    // 중복 제거: 같은 모델이 USB(시리얼)와 무선(IP:5555) 둘 다 있으면 무선만 유지
    let wireless: Vec<&DeviceInfo> = devices.iter().filter(|d| d.udid.contains(':') && d.udid.contains('.') ).collect();
    let wireless_models: std::collections::HashSet<String> = wireless.iter()
        .filter_map(|d| d.name.split_whitespace().find(|p| p.starts_with("model:")).map(|s| s.to_string()))
        .collect();
    let devices: Vec<DeviceInfo> = devices.into_iter().filter(|d| {
        let is_usb = !d.udid.contains('.');
        if is_usb {
            // 같은 모델의 무선 연결이 있으면 USB 항목 제거
            let model = d.name.split_whitespace().find(|p| p.starts_with("model:")).map(|s| s.to_string());
            if let Some(m) = model {
                return !wireless_models.contains(&m);
            }
        }
        true
    }).collect();

    ui_log(&format!("✅ Android 디바이스 {}개 발견", devices.len()));

    // 무선 기기 포워딩 상태 확인
    for d in devices.iter().filter(|d| d.udid.contains('.') && d.udid.contains(':')) {
        if let Ok(list) = Command::new(&adb)
            .args(&["-s", &d.udid, "forward", "--list"])
            .output()
        {
            let out = String::from_utf8_lossy(&list.stdout);
            let trimmed = out.trim();
            if trimmed.is_empty() {
                ui_log(&format!("⚠️  {} forward 없음 (tcp:7779 미설정)", d.udid));
            } else {
                ui_log(&format!("📋 {} forward --list:\n{}", d.udid, trimmed));
            }
        }
    }

    Ok(DeviceListResponse {
        devices: devices.clone(),
        message: format!("Android 디바이스 {}개 발견", devices.len()),
    })
}

#[tauri::command]
pub fn list_ios_devices(app: tauri::AppHandle) -> Result<DeviceListResponse, String> {
    ui_log("📱 iOS 디바이스 목록 확인 중...");

    let python_path = if venv_python().exists() {
        venv_python().to_string_lossy().to_string()
    } else {
        find_python().ok_or("Python3를 찾을 수 없습니다.".to_string())?
    };
    let scripts = scripts_dir(&app);
    let script_path = scripts.join("list_ios_devices.py");

    let mut devices: Vec<DeviceInfo> = Vec::new();
    let mut seen_udids: std::collections::HashSet<String> = std::collections::HashSet::new();

    // ── 1. xcrun devicectl (USB + 무선, 5초 타임아웃) ────────────────────────
    let tmp_path = "/tmp/devicectl_ios_list.json";
    let mut dc_cmd = Command::new("xcrun");
    dc_cmd.args(&["devicectl", "list", "devices", "--json-output", tmp_path]);
    if run_cmd_timeout(dc_cmd, 5).is_some() && std::path::Path::new(tmp_path).exists() {
        let mut py_cmd = Command::new(&python_path);
        py_cmd.env("PATH", extended_path())
              .args([script_path.to_string_lossy().as_ref(), tmp_path]);
        if let Some(stdout) = run_cmd_timeout(py_cmd, 8) {
            for line in stdout.lines() {
                if line.starts_with("ERR:") {
                    ui_log(&format!("⚠️ devicectl JSON: {}", line));
                    continue;
                }
                let parts: Vec<&str> = line.splitn(2, '|').collect();
                if parts.len() == 2 {
                    let udid = parts[0].trim().to_string();
                    let name = parts[1].trim().to_string();
                    if !udid.is_empty() && !seen_udids.contains(&udid) {
                        seen_udids.insert(udid.clone());
                        ui_log(&format!("✅ iOS (devicectl): {} - {}", udid, name));
                        devices.push(DeviceInfo { udid, platform: "iOS".to_string(), name, connected: true });
                    }
                }
            }
        }
        let _ = std::fs::remove_file(tmp_path);
    }

    // ── 2. idevice_id fallback (USB 전용, 3초 타임아웃) ─────────────────────
    let mut id_cmd = Command::new("idevice_id");
    id_cmd.arg("-l");
    if let Some(stdout) = run_cmd_timeout(id_cmd, 3) {
        for line in stdout.lines() {
            let udid = line.trim().to_string();
            if udid.is_empty() || seen_udids.contains(&udid) { continue; }
            seen_udids.insert(udid.clone());

            let mut info_cmd = Command::new("ideviceinfo");
            info_cmd.args(&["-u", &udid, "-k", "DeviceName"]);
            let device_name = run_cmd_timeout(info_cmd, 3)
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .map(|s| format!("{} (유선)", s))
                .unwrap_or_else(|| "iPhone (유선)".to_string());

            ui_log(&format!("✅ iOS (idevice_id USB): {} - {}", udid, device_name));
            devices.push(DeviceInfo { udid, platform: "iOS".to_string(), name: device_name, connected: true });
        }
    }

    ui_log(&format!("✅ iOS 디바이스 {}개 발견", devices.len()));
    Ok(DeviceListResponse {
        devices: devices.clone(),
        message: format!("iOS 디바이스 {}개 발견", devices.len()),
    })
}

#[tauri::command]
pub async fn install_wda(
    app: tauri::AppHandle,
    ipa_path: String,
    udid: Option<String>,
) -> Result<ConnectionStatus, String> {
    ui_log(&format!("📦 WDA 설치 시작: {}", ipa_path));

    let python_path = if venv_python().exists() {
        venv_python().to_string_lossy().to_string()
    } else {
        find_python().ok_or("❌ Python3를 찾을 수 없습니다. python3를 설치하세요.".to_string())?
    };
    let scripts = scripts_dir(&app);
    let script_path = scripts.join("wda_installer.py");

    let mut cmd = Command::new(&python_path);
    cmd.env("PATH", extended_path())
       .args(["-u", &script_path.to_string_lossy(), &ipa_path]);
    if let Some(ref u) = udid {
        cmd.args(["--udid", u]);
    }

    let output = cmd.output()
        .map_err(|e| format!("Python 실행 실패: {}", e))?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    let combined = if stderr.is_empty() { stdout } else { format!("{}
{}", stdout.trim(), stderr.trim()) };
    ui_log(&combined);
    let success = output.status.success() && !combined.contains("❌");
    Ok(ConnectionStatus { success, message: combined })
}

// ── Android Watchdog ──────────────────────────────────────────────────────────

#[tauri::command]
pub async fn start_android_watchdog(
    app: tauri::AppHandle,
    devices: Vec<String>,
    interval: Option<u64>,
    keepalive: Option<u64>,
) -> Result<ConnectionStatus, String> {
    // 이미 실행 중이면 중지 후 재시작
    {
        let mut guard = WATCHDOG_PROCESS.lock().expect("WATCHDOG_PROCESS Mutex 오염");
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
        }
    }

    if devices.is_empty() {
        return Ok(ConnectionStatus {
            success: false,
            message: "❌ 감시할 Android UDID를 입력하세요.".to_string(),
        });
    }

    let python_path = if venv_python().exists() {
        venv_python().to_string_lossy().to_string()
    } else {
        find_python().ok_or("Python3를 찾을 수 없습니다.".to_string())?
    };

    let scripts = scripts_dir(&app);
    let script_path = scripts.join("android_watchdog.py");

    let check_interval = interval.unwrap_or(30).to_string();
    let keepalive_sec  = keepalive.unwrap_or(30).to_string();

    let mut cmd = Command::new(&python_path);
    cmd.env("PATH", extended_path())
       .args(["-u", &script_path.to_string_lossy()])
       .args(["--interval", &check_interval])
       .args(["--keepalive", &keepalive_sec])
       .arg("--devices")
       .args(&devices)
       .stdout(Stdio::null())
       .stderr(Stdio::null());

    let child = cmd.spawn()
        .map_err(|e| format!("Watchdog 시작 실패: {}", e))?;

    let msg = format!("🐕 Watchdog 시작: {} (check={}s keepalive={}s)",
        devices.join(", "), check_interval, keepalive_sec);
    ui_log(&msg);

    *WATCHDOG_PROCESS.lock().expect("WATCHDOG_PROCESS Mutex 오염") = Some(child);
    // 감시 기기 목록 저장 (테스트 시작 시 adb kill-server 후 자동 재연결에 사용)
    *WATCHDOG_DEVICES.lock().expect("WATCHDOG_DEVICES Mutex 오염") = devices;

    Ok(ConnectionStatus { success: true, message: msg })
}

#[tauri::command]
pub async fn stop_android_watchdog() -> Result<ConnectionStatus, String> {
    let mut guard = WATCHDOG_PROCESS.lock().expect("WATCHDOG_PROCESS Mutex 오염");
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        WATCHDOG_DEVICES.lock().expect("WATCHDOG_DEVICES Mutex 오염").clear();
        ui_log("🛑 Watchdog 정지됨");
        Ok(ConnectionStatus { success: true, message: "🛑 Watchdog 정지됨".to_string() })
    } else {
        Ok(ConnectionStatus { success: false, message: "⚠️ 실행 중인 Watchdog 없음".to_string() })
    }
}

// ── 앱 버전 조회 ──────────────────────────────────────────────────────────

#[derive(serde::Serialize, serde::Deserialize, Debug, Clone)]
pub struct AppVersions {
    pub ios: String,
    pub android: String,
}

fn fetch_ios_app_version_sync(pkg: &str) -> String {
    if pkg.is_empty() {
        return String::new();
    }
    let path = extended_path();

    // ① xcrun devicectl list devices → UUID → device info apps --include-all-apps
    let tmp = format!("/tmp/ixio_devver_{}.json", std::process::id());
    let _ = Command::new("xcrun")
        .env("PATH", &path)
        .args(["devicectl", "list", "devices", "--json-output", &tmp])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();

    let uuid: Option<String> = (|| {
        let data = std::fs::read_to_string(&tmp).ok()?;
        let _ = std::fs::remove_file(&tmp);
        let v: serde_json::Value = serde_json::from_str(&data).ok()?;
        let devices = v.get("result")?.get("devices")?.as_array()?;
        for dev in devices {
            let state = dev
                .get("connectionProperties")
                .and_then(|c| c.get("tunnelState"))
                .and_then(|s| s.as_str())
                .unwrap_or("");
            if state == "connected" {
                if let Some(udid) = dev
                    .get("hardwareProperties")
                    .and_then(|h| h.get("udid"))
                    .and_then(|u| u.as_str())
                {
                    return Some(udid.to_string());
                }
            }
        }
        None
    })();

    if let Some(uuid) = uuid {
        if let Ok(out) = Command::new("xcrun")
            .env("PATH", &path)
            .args([
                "devicectl",
                "device",
                "info",
                "apps",
                "--device",
                &uuid,
                "--include-all-apps",
            ])
            .output()
        {
            let text = String::from_utf8_lossy(&out.stdout);
            for line in text.lines() {
                if line.contains(pkg) {
                    let parts: Vec<&str> = line.split_whitespace().collect();
                    if let Some(idx) = parts.iter().position(|p| *p == pkg) {
                        let ver = parts.get(idx + 1).copied().unwrap_or("");
                        let bver = parts.get(idx + 2).copied().unwrap_or("");
                        if !ver.is_empty() {
                            return if bver.is_empty() {
                                ver.to_string()
                            } else {
                                format!("{}({})", ver, bver)
                            };
                        }
                    }
                }
            }
        }
    }

    // ② ideviceinstaller fallback
    if let Ok(out) = Command::new("ideviceinstaller")
        .env("PATH", &path)
        .args(["-l"])
        .output()
    {
        let text = String::from_utf8_lossy(&out.stdout);
        for line in text.lines() {
            if line.contains(pkg) {
                // 형식: <bundle_id>, "<build>", "<name>"
                let parts: Vec<&str> = line.splitn(3, ',').collect();
                if parts.len() >= 2 {
                    let bver = parts[1].trim().trim_matches('"');
                    if !bver.is_empty() {
                        return bver.to_string();
                    }
                }
            }
        }
    }

    String::new()
}

fn fetch_android_app_version_sync(pkg: &str) -> String {
    if pkg.is_empty() {
        return String::new();
    }
    let path = extended_path();
    let adb = match find_tool(&["adb"]) {
        Some(p) => p,
        None => return String::new(),
    };

    // 연결된 기기 serial 획득
    let devs = match Command::new(&adb)
        .env("PATH", &path)
        .arg("devices")
        .output()
    {
        Ok(o) => String::from_utf8_lossy(&o.stdout).to_string(),
        Err(_) => return String::new(),
    };
    let serial = devs
        .lines()
        .skip(1)
        .find(|l| l.ends_with("\tdevice"))
        .and_then(|l| l.split_whitespace().next())
        .map(|s| s.to_string());

    let serial = match serial {
        Some(s) => s,
        None => return String::new(),
    };

    let out = match Command::new(&adb)
        .env("PATH", &path)
        .args(["-s", &serial, "shell", "dumpsys", "package", pkg])
        .output()
    {
        Ok(o) => String::from_utf8_lossy(&o.stdout).to_string(),
        Err(_) => return String::new(),
    };

    let ver_name = out
        .lines()
        .find_map(|l| {
            let l = l.trim();
            if l.starts_with("versionName=") {
                Some(l.trim_start_matches("versionName=").to_string())
            } else {
                None
            }
        })
        .unwrap_or_default();
    let ver_code = out
        .lines()
        .find_map(|l| {
            let l = l.trim();
            if l.starts_with("versionCode=") {
                l.split_whitespace().next()
                    .map(|s| s.trim_start_matches("versionCode=").to_string())
            } else {
                None
            }
        })
        .unwrap_or_default();

    if ver_name.is_empty() {
        return String::new();
    }
    if ver_code.is_empty() {
        ver_name
    } else {
        format!("{}({})", ver_name, ver_code)
    }
}

#[tauri::command]
pub async fn get_app_versions(ios_pkg: String, android_pkg: String) -> AppVersions {
    let ios_pkg_c = ios_pkg.clone();
    let android_pkg_c = android_pkg.clone();
    let ios = tauri::async_runtime::spawn_blocking(move || fetch_ios_app_version_sync(&ios_pkg_c))
        .await
        .unwrap_or_default();
    let android = tauri::async_runtime::spawn_blocking(move || fetch_android_app_version_sync(&android_pkg_c))
        .await
        .unwrap_or_default();
    AppVersions { ios, android }
}

// ── ADB 연결 사전 점검 / 자동 재연결 ────────────────────────────────────────

const ADB_CONNECT_RETRIES: usize = 3;
const ADB_CONNECT_RETRY_SECS: u64 = 5;

/// IP:PORT 형식의 사설 IP 주소인지 확인합니다. (예: 192.168.1.1:5555)
/// TLS mDNS 형식(adb-xxx._adb-tls-connect._tcp)은 false를 반환합니다.
fn is_private_ip_port(s: &str) -> bool {
    if s.contains("_tcp") || s.contains("_adb") { return false; }
    match s.rsplit_once(':') {
        Some((ip, port)) => {
            port.parse::<u16>().is_ok()
                && (ip.starts_with("192.168.") || ip.starts_with("10.") || ip.starts_with("172."))
        }
        None => false,
    }
}

/// TLS mDNS 기기에서 adb shell로 Wi-Fi IP를 동적 조회합니다.
fn get_ip_from_tls_device(adb: &str, device_id: &str) -> Option<String> {
    let out = Command::new(adb)
        .args(&["-s", device_id, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
        .unwrap_or_default();
    for line in out.lines() {
        if !line.contains("inet ") { continue; }
        let parts: Vec<&str> = line.split_whitespace().collect();
        if let Some(idx) = parts.iter().position(|&p| p == "inet") {
            if let Some(addr) = parts.get(idx + 1) {
                let ip = addr.split('/').next().unwrap_or("");
                if ip.starts_with("192.168.") || ip.starts_with("10.") || ip.starts_with("172.") {
                    return Some(format!("{}:5555", ip));
                }
            }
        }
    }
    None
}

/// `adb devices` 출력에서 IP:PORT 형식으로 연결된 Android 기기를 찾습니다.
/// TLS mDNS 항목은 "연결 없음"으로 취급합니다.
fn find_ip_port_connected(stdout: &str) -> Option<String> {
    stdout.lines().skip(1)
        .filter_map(|line| {
            let mut parts = line.split_whitespace();
            let id = parts.next()?;
            let status = parts.next()?;
            if status == "device" && is_private_ip_port(id) {
                Some(id.to_string())
            } else {
                None
            }
        })
        .next()
}

/// `adb devices` 출력에서 TLS mDNS 형식 기기 ID를 찾습니다.
fn find_tls_device(stdout: &str) -> Option<String> {
    stdout.lines().skip(1)
        .filter_map(|line| {
            let mut parts = line.split_whitespace();
            let id = parts.next()?;
            let status = parts.next()?;
            if status == "device" && (id.contains("_adb-tls-connect") || id.starts_with("adb-")) {
                Some(id.to_string())
            } else {
                None
            }
        })
        .next()
}

/// 테스트 시작 전 Android ADB IP:PORT 연결을 보장합니다.
///
/// - TLS mDNS 형식(`adb-xxx._adb-tls-connect._tcp`)은 "연결 없음"으로 취급합니다.
/// - IP:PORT 연결이 확인되면 `Ok(ip_port)` 반환.
/// - 없으면 `adb connect`를 최대 3회 재시도합니다.
/// - 모든 재시도 실패 시 `Err(메시지)` 반환 — 테스트를 시작하지 않습니다.
pub fn adb_ensure_connected(device_id: &str) -> Result<String, String> {
    let adb = find_adb().map_err(|e| format!("ADB 경로 조회 실패: {}", e))?;

    for attempt in 1..=(ADB_CONNECT_RETRIES + 1) {
        // adb devices 조회
        let mut cmd = Command::new(&adb);
        cmd.args(&["devices"]);
        let stdout = run_cmd_timeout(cmd, 5).unwrap_or_default();

        if attempt == 1 {
            ui_log(&format!("📋 adb devices (테스트 전 점검):\n{}", stdout.trim()));
        }

        // IP:PORT device 항목 탐색 (TLS 형식은 제외)
        if let Some(ip_port) = find_ip_port_connected(&stdout) {
            if attempt == 1 {
                ui_log(&format!("✅ Android IP:PORT 연결 확인: {}", ip_port));
            } else {
                ui_log(&format!("✅ Android IP:PORT 연결 성공 ({}/3 시도 후): {}", attempt - 1, ip_port));
            }
            if let Ok(mut guard) = crate::state::LAST_ANDROID_IP.lock() {
                *guard = Some(ip_port.clone());
            }
            return Ok(ip_port);
        }

        // IP:PORT 없음 → 마지막 시도면 에러 반환
        if attempt > ADB_CONNECT_RETRIES {
            break;
        }

        ui_log(&format!(
            "⚠️ Android IP:PORT 연결 없음 — adb connect 시도 ({}/{}) ...",
            attempt, ADB_CONNECT_RETRIES
        ));

        // 연결할 target IP 결정: LAST_ANDROID_IP 우선, 없으면 TLS 기기에서 조회
        let target: Option<String> = crate::state::LAST_ANDROID_IP.lock()
            .ok().and_then(|g| g.clone())
            .or_else(|| {
                // device_id가 TLS mDNS 형식이면 직접 사용
                if device_id.contains("_adb-tls-connect") || device_id.contains("adb-") {
                    return get_ip_from_tls_device(&adb, device_id);
                }
                // device_id가 빈 문자열이면 adb devices에서 TLS 기기 자동 탐색
                if device_id.is_empty() {
                    if let Some(tls_id) = find_tls_device(&stdout) {
                        ui_log(&format!("  🔍 TLS 기기 자동 탐색: {}", tls_id));
                        return get_ip_from_tls_device(&adb, &tls_id);
                    }
                }
                None
            });

        match target {
            Some(ref ip_port) => {
                ui_log(&format!("🔌 adb connect {} ...", ip_port));
                let out = Command::new(&adb)
                    .args(&["connect", ip_port])
                    .output()
                    .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
                    .unwrap_or_default();
                ui_log(&format!("  → {}", out));
                // 연결 결과는 다음 루프 iteration의 adb devices 재조회로 검증
            }
            None => {
                ui_log("⚠️ 연결 가능한 Android IP를 찾을 수 없습니다. 디바이스 Wi-Fi 연결을 확인하세요.");
            }
        }

        std::thread::sleep(std::time::Duration::from_secs(ADB_CONNECT_RETRY_SECS));
    }

    Err(format!(
        "❌ Android IP:PORT 연결 실패 ({}회 시도) — 테스트를 시작할 수 없습니다.\n\
         수동으로 'adb connect <IP>:5555'를 실행하거나 디바이스 Wi-Fi 연결을 확인하세요.",
        ADB_CONNECT_RETRIES
    ))
}