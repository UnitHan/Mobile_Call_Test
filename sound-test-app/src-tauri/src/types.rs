use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnvItem {
    pub key: String,
    pub label: String,
    pub ok: bool,
    pub version: String,
    pub hint: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnvCheckResult {
    pub items: Vec<EnvItem>,
    pub all_ok: bool,
    pub python_env_ready: bool,
}


#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceInfo {
    pub udid: String,
    pub platform: String,
    pub name: String,
    pub connected: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceListResponse {
    pub devices: Vec<DeviceInfo>,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConnectionStatus {
    pub success: bool,
    pub message: String,
}

/// run_ixio_test 반환값 — 성공/실패 외 수집된 음원 경로도 포함
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestRunResult {
    pub success: bool,
    pub message: String,
    pub ios_recording: String,
    pub android_recording: String,
    pub screenshots: Vec<String>,
    pub vishing_detected: Option<bool>,
}

/// run_dropout_analysis 반환값 — 결과 보고서 경로 포함
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DropoutAnalysisResult {
    pub success: bool,
    pub message: String,
    pub report_path: String,
    pub dropout_count: i64,
    pub severity: String,
    pub ios_visqol_mos: Option<f64>,
    pub android_visqol_mos: Option<f64>,
    // v2: 플랫폼별 세부
    pub and_dropped_count:  i64,
    pub and_degraded_count: i64,
    pub and_poor_count:     i64,
    pub and_severity:       String,
    pub ios_dropped_count:  i64,
    pub ios_degraded_count: i64,
    pub ios_poor_count:     i64,
    pub ios_severity:       String,
    pub voip_delay_ms:      i64,
    // v3: 디바이스 & 앱 버전
    pub android_app_ver:    String,
    pub ios_app_ver:        String,
    pub android_device:     String,
    pub android_os_ver:     String,
    pub ios_device:         String,
    pub ios_os_ver:         String,
    pub profile_name:       String,
}

