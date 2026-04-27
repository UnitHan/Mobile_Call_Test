/// util_cmd.rs — 유틸리티 Tauri 커맨드
///   - clear_all_results : 결과 파일(HTML 리포트 + WAV) 일괄 삭제
///   - send_stats_email  : 통계 엑셀 파일을 SMTP로 발송
///   - save_temp_file    : base64 데이터를 임시 파일로 저장 (이메일 첨부용)

use std::path::Path;
use serde::{Deserialize, Serialize};

// ─── 결과 파일 삭제 ────────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ClearFilesPayload {
    /// 삭제할 파일 경로 목록 (HTML 리포트, WAV 등)
    pub paths: Vec<String>,
    /// 빈 디렉토리도 삭제할지 여부
    pub prune_empty_dirs: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ClearFilesResult {
    pub deleted: usize,
    pub failed: Vec<String>,
}

#[tauri::command]
pub fn clear_result_files(payload: ClearFilesPayload) -> Result<ClearFilesResult, String> {
    // 허용 루트: ~/Documents/sound/, /tmp/, 시스템 임시 디렉토리
    let home = std::env::var("HOME").unwrap_or_default();
    let allowed_roots: Vec<std::path::PathBuf> = vec![
        std::path::PathBuf::from(&home).join("Documents").join("sound"),
        std::path::PathBuf::from("/tmp"),
        std::env::temp_dir(),
    ];
    fn is_allowed(p: &Path, roots: &[std::path::PathBuf]) -> bool {
        if let Ok(canon) = p.canonicalize() {
            return roots.iter().any(|r| canon.starts_with(r));
        }
        // 아직 존재하지 않는 파일은 부모 디렉토리로 체크
        if let Some(parent) = p.parent() {
            if let Ok(canon) = parent.canonicalize() {
                return roots.iter().any(|r| canon.starts_with(r));
            }
        }
        false
    }

    let mut deleted = 0usize;
    let mut failed  = Vec::<String>::new();

    for p in &payload.paths {
        let path = Path::new(p);
        if !is_allowed(path, &allowed_roots) {
            failed.push(format!("{}: 허용되지 않은 경로", p));
            continue;
        }
        if !path.exists() {
            // 이미 없으면 성공으로 처리
            deleted += 1;
            continue;
        }
        let result = if path.is_dir() {
            std::fs::remove_dir_all(path)
        } else {
            std::fs::remove_file(path)
        };
        match result {
            Ok(_) => deleted += 1,
            Err(e) => failed.push(format!("{}: {}", p, e)),
        }
    }

    // 빈 부모 디렉토리 정리
    if payload.prune_empty_dirs {
        let mut dirs: Vec<String> = payload.paths
            .iter()
            .filter_map(|p| {
                Path::new(p).parent().and_then(|d| d.to_str()).map(|s| s.to_string())
            })
            .collect();
        dirs.sort();
        dirs.dedup();
        for dir in dirs {
            let dp = Path::new(&dir);
            if dp.exists() {
                if let Ok(mut entries) = std::fs::read_dir(dp) {
                    if entries.next().is_none() {
                        let _ = std::fs::remove_dir(dp);
                    }
                }
            }
        }
    }

    Ok(ClearFilesResult { deleted, failed })
}

// ─── 이메일 발송 (SMTP / Gmail App Password) ──────────────────────────────────

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SendEmailPayload {
    /// 발신자 계정 (Gmail)
    pub from_addr:    String,
    /// Gmail 앱 비밀번호 (16자리)
    pub app_password: String,
    /// 수신자 목록
    pub to_addrs:     Vec<String>,
    pub subject:      String,
    pub body_html:    String,
    /// 첨부 파일 경로 (xlsx 등). 비어 있으면 첨부 없음
    pub attachments:  Vec<String>,
}

/// SMTP(Gmail)로 메일 발송
/// 의존: lettre crate — Cargo.toml에 추가 필요
#[tauri::command]
pub fn send_stats_email(payload: SendEmailPayload) -> Result<String, String> {
    use std::fs;
    use lettre::{
        Message,
        SmtpTransport, Transport,
        transport::smtp::authentication::Credentials,
        message::{header, MultiPart, SinglePart, Attachment},
    };

    // ── 메시지 빌드 ────────────────────────────────────────────────────────
    let body_part = SinglePart::builder()
        .header(header::ContentType::TEXT_HTML)
        .body(payload.body_html.clone());

    let mut mp = MultiPart::mixed().singlepart(body_part);

    for att_path in &payload.attachments {
        let fname = Path::new(att_path)
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("attachment")
            .to_string();
        let data = fs::read(att_path)
            .map_err(|e| format!("첨부 파일 읽기 실패 {att_path}: {e}"))?;
        let mime_str = if fname.ends_with(".json") {
            "application/json"
        } else if fname.ends_with(".xlsx") {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        } else {
            "application/octet-stream"
        };
        let content_type = lettre::message::header::ContentType::parse(mime_str).unwrap();
        mp = mp.singlepart(
            Attachment::new(fname).body(data, content_type),
        );
    }

    let mut msg_builder = Message::builder()
        .from(payload.from_addr.parse().map_err(|e| format!("발신 주소 오류: {e}"))?)
        .subject(payload.subject.clone());

    for to in &payload.to_addrs {
        msg_builder = msg_builder
            .to(to.parse().map_err(|e| format!("수신 주소 오류 {to}: {e}"))?);
    }

    let email = msg_builder
        .multipart(mp)
        .map_err(|e| format!("메일 생성 실패: {e}"))?;

    // ── SMTP 발송 ─────────────────────────────────────────────────────────
    let creds = Credentials::new(payload.from_addr.clone(), payload.app_password.clone());
    let mailer = SmtpTransport::relay("smtp.gmail.com")
        .map_err(|e| format!("SMTP relay 오류: {e}"))?
        .credentials(creds)
        .build();

    mailer.send(&email).map_err(|e| format!("메일 발송 실패: {e}"))?;

    Ok(format!(
        "✅ 메일 발송 완료 → {}",
        payload.to_addrs.join(", ")
    ))
}

// ─── 임시 파일 저장 (이메일 첨부용) ───────────────────────────────────────────

/// base64 인코딩된 데이터를 임시 디렉토리에 저장하고 절대 경로를 반환
#[tauri::command]
pub fn save_temp_file(data_b64: String, filename: String) -> Result<String, String> {
    use base64::Engine;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(&data_b64)
        .map_err(|e| format!("base64 디코딩 실패: {e}"))?;

    let tmp_dir = std::env::temp_dir().join("ixio-milestone");
    std::fs::create_dir_all(&tmp_dir)
        .map_err(|e| format!("임시 디렉토리 생성 실패: {e}"))?;
    let path = tmp_dir.join(&filename);
    std::fs::write(&path, &bytes)
        .map_err(|e| format!("임시 파일 저장 실패: {e}"))?;
    Ok(path.to_string_lossy().into_owned())
}

/// 문자열 데이터를 임시 디렉토리에 저장하고 절대 경로를 반환
#[tauri::command]
pub fn save_temp_text(text: String, filename: String) -> Result<String, String> {
    let tmp_dir = std::env::temp_dir().join("ixio-milestone");
    std::fs::create_dir_all(&tmp_dir)
        .map_err(|e| format!("임시 디렉토리 생성 실패: {e}"))?;
    let path = tmp_dir.join(&filename);
    std::fs::write(&path, text.as_bytes())
        .map_err(|e| format!("임시 파일 저장 실패: {e}"))?;
    Ok(path.to_string_lossy().into_owned())
}
