/// db_cmd.rs — DB 관련 Tauri 커맨드
///
/// Frontend에서 invoke("db_save_result", {...}) 형태로 호출.

use std::path::PathBuf;
use std::sync::Mutex;
use once_cell::sync::OnceCell;
use serde::{Deserialize, Serialize};
use rusqlite::Connection;
use tauri::Emitter;

use crate::db::{
    self, TcResultRow, TcSessionRow, ResultFile,
};

// ── 전역 DB 연결 ───────────────────────────────────────────────────────────────

static DB_CONN: OnceCell<Mutex<Connection>> = OnceCell::new();

pub fn init_db(data_dir: PathBuf) {
    let conn = db::open_db(&data_dir)
        .expect("SQLite DB 초기화 실패");
    DB_CONN.set(Mutex::new(conn)).ok();
    println!("[db] ixio_results.db 초기화 완료: {:?}", data_dir.join("ixio_results.db"));
}

fn with_db<F, T>(f: F) -> Result<T, String>
where
    F: FnOnce(&Connection) -> rusqlite::Result<T>,
{
    let guard = DB_CONN
        .get()
        .ok_or("DB 미초기화")?
        .lock()
        .map_err(|e| e.to_string())?;
    f(&guard).map_err(|e| e.to_string())
}

// ── Frontend → Rust 입력 타입 ─────────────────────────────────────────────────

/// Frontend TcResult 에서 보내는 저장 요청
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SaveResultPayload {
    pub run_id: String,
    pub session_id: Option<String>,
    pub repeat_index: Option<i64>,
    pub tc_id: String,
    pub started_at: String,
    pub finished_at: String,
    pub duration_ms: i64,
    pub status: String,
    pub ios_visqol_mos: Option<f64>,
    pub android_visqol_mos: Option<f64>,
    pub snr_db: Option<f64>,
    pub dropout_count: Option<i64>,
    pub dropout_severity: Option<String>,
    pub dropout_report_path: Option<String>,
    pub mos_report_path: Option<String>,
    pub vishing_detected: Option<bool>,
    pub error_msg: Option<String>,
    /// [{ label, path }] 형태의 음원 파일 목록
    pub extracted_audio_paths: Vec<ExtractedFile>,
    /// 스크린샷 경로 목록
    pub screenshot_paths: Vec<String>,
    /// 로그 라인 목록
    pub log_lines: Vec<String>,
    // v2: 플랫폼별 세부
    pub and_dropped_count:  Option<i64>,
    pub and_degraded_count: Option<i64>,
    pub and_poor_count:     Option<i64>,
    pub and_severity:       Option<String>,
    pub ios_dropped_count:  Option<i64>,
    pub ios_degraded_count: Option<i64>,
    pub ios_poor_count:     Option<i64>,
    pub ios_severity:       Option<String>,
    pub voip_delay_ms:      Option<i64>,
    // v3: 디바이스 & 앱 버전
    pub android_app_ver:    Option<String>,
    pub ios_app_ver:        Option<String>,
    pub android_device:     Option<String>,
    pub android_os_ver:     Option<String>,
    pub ios_device:         Option<String>,
    pub ios_os_ver:         Option<String>,
    pub profile_name:       Option<String>,
    // v4: 통신사
    pub carrier:            Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ExtractedFile {
    pub label: String,
    pub path: String,
}

/// Frontend TcSession에서 보내는 저장 요청
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SaveSessionPayload {
    pub session_id: String,
    pub tc_ids: Vec<String>,
    pub started_at: String,
    pub finished_at: Option<String>,
    pub repeat_count: Option<i64>,
    pub repeat_mode: Option<String>,
    pub fail_action: Option<String>,
}

// ── Tauri 커맨드 ──────────────────────────────────────────────────────────────

/// MOS 보고서 경로만 DB 업데이트 (경량)
#[tauri::command]
pub fn db_update_mos_report_path(run_id: String, path: String) -> Result<(), String> {
    with_db(|conn| {
        db::update_mos_report_path(conn, &run_id, &path)
    })
}

/// TC 실행 결과 1건 저장 (음원·스크린샷·로그 포함)
#[tauri::command]
pub fn db_save_result(app: tauri::AppHandle, payload: SaveResultPayload) -> Result<(), String> {
    let tc_id  = payload.tc_id.clone();
    let status = payload.status.clone();
    with_db(|conn| {
        let row = TcResultRow {
            run_id:              payload.run_id.clone(),
            session_id:          payload.session_id.clone(),
            repeat_index:        payload.repeat_index,
            tc_id:               payload.tc_id.clone(),
            started_at:          payload.started_at.clone(),
            finished_at:         payload.finished_at.clone(),
            duration_ms:         payload.duration_ms,
            status:              payload.status.clone(),
            ios_visqol_mos:      payload.ios_visqol_mos,
            android_visqol_mos:  payload.android_visqol_mos,
            snr_db:              payload.snr_db,
            dropout_count:       payload.dropout_count,
            dropout_severity:    payload.dropout_severity.clone(),
            dropout_report_path: payload.dropout_report_path.clone(),
            mos_report_path:     payload.mos_report_path.clone(),
            vishing_detected:    payload.vishing_detected,
            error_msg:           payload.error_msg.clone(),
            and_dropped_count:   payload.and_dropped_count,
            and_degraded_count:  payload.and_degraded_count,
            and_poor_count:      payload.and_poor_count,
            and_severity:        payload.and_severity.clone(),
            ios_dropped_count:   payload.ios_dropped_count,
            ios_degraded_count:  payload.ios_degraded_count,
            ios_poor_count:      payload.ios_poor_count,
            ios_severity:        payload.ios_severity.clone(),
            voip_delay_ms:       payload.voip_delay_ms,
            android_app_ver:     payload.android_app_ver.clone(),
            ios_app_ver:         payload.ios_app_ver.clone(),
            android_device:      payload.android_device.clone(),
            android_os_ver:      payload.android_os_ver.clone(),
            ios_device:          payload.ios_device.clone(),
            ios_os_ver:          payload.ios_os_ver.clone(),
            profile_name:        payload.profile_name.clone(),
            carrier:             payload.carrier.clone(),
        };
        db::insert_result(conn, &row)?;

        // 음원 파일
        let audio_files: Vec<ResultFile> = payload.extracted_audio_paths.iter().map(|f| ResultFile {
            run_id:    payload.run_id.clone(),
            file_type: "audio".to_string(),
            label:     f.label.clone(),
            path:      f.path.clone(),
        }).collect();
        db::insert_result_files(conn, &audio_files)?;

        // 스크린샷
        let screenshots: Vec<ResultFile> = payload.screenshot_paths.iter().map(|p| ResultFile {
            run_id:    payload.run_id.clone(),
            file_type: "screenshot".to_string(),
            label:     "screenshot".to_string(),
            path:      p.clone(),
        }).collect();
        db::insert_result_files(conn, &screenshots)?;

        // 로그
        db::insert_result_logs(conn, &payload.run_id, &payload.log_lines)?;

        Ok(())
    })
    .map(|_| {
        let msg = format!("[db] ✅ DB 적재 완료: {} ({})", tc_id, status);
        println!("{}", msg);
        let _ = app.emit("test-log", &msg);
    })
    .map_err(|e| {
        let msg = format!("[db] ❌ DB 적재 실패: {} — {}", tc_id, e);
        eprintln!("{}", msg);
        let _ = app.emit("test-log", &msg);
        e
    })
}

/// 세션 저장 (시작 시 + 완료 시 upsert)
#[tauri::command]
pub fn db_save_session(payload: SaveSessionPayload) -> Result<(), String> {
    with_db(|conn| {
        let row = TcSessionRow {
            session_id:   payload.session_id,
            tc_ids:       serde_json::to_string(&payload.tc_ids).unwrap_or_default(),
            started_at:   payload.started_at,
            finished_at:  payload.finished_at,
            repeat_count: payload.repeat_count,
            repeat_mode:  payload.repeat_mode,
            fail_action:  payload.fail_action,
        };
        db::upsert_session(conn, &row)
    })
}

/// 중단된 세션의 진행도 조회 — 재개 팝업용
/// (completed_sets: MAX(repeat_index) 완료된 세트 수, total_sets: 예약 총 횟수)
#[tauri::command]
pub fn db_get_session_progress(session_id: String) -> Result<(i64, i64), String> {
    with_db(|conn| {
        let row: (Option<i64>, Option<i64>) = conn.query_row(
            "SELECT s.repeat_count, COALESCE(MAX(r.repeat_index), 0) \
             FROM tc_sessions s \
             LEFT JOIN tc_results r ON s.session_id = r.session_id \
             WHERE s.session_id = ?1 \
             GROUP BY s.session_id",
            rusqlite::params![&session_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ).unwrap_or((None, Some(0)));
        Ok((row.1.unwrap_or(0), row.0.unwrap_or(1)))
    })
}

/// Legacy(sessionId 없는) running 항목용: tc_ids + repeat_count 조합으로
/// 가장 최근 미완료 또는 최근 완료 세션을 찾아 (sessionId, completed, total) 반환
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FoundSession {
    pub session_id: String,
    pub completed: i64,
    pub total: i64,
}

#[tauri::command]
pub fn db_find_recent_session(tc_ids_json: String, repeat_count: i64) -> Result<Option<FoundSession>, String> {
    with_db(|conn| {
        // 1) 미완료 세션 먼저 (finished_at IS NULL)
        // 2) 없으면 최근 완료 세션 (finished_at DESC)
        let sql = "SELECT s.session_id, s.repeat_count, COALESCE(MAX(r.repeat_index), 0) AS completed \
                   FROM tc_sessions s \
                   LEFT JOIN tc_results r ON s.session_id = r.session_id \
                   WHERE s.tc_ids = ?1 AND s.repeat_count = ?2 \
                   GROUP BY s.session_id \
                   ORDER BY (CASE WHEN s.finished_at IS NULL THEN 0 ELSE 1 END), s.started_at DESC \
                   LIMIT 1";
        let result = conn.query_row(
            sql,
            rusqlite::params![&tc_ids_json, repeat_count],
            |row| {
                Ok(FoundSession {
                    session_id: row.get(0)?,
                    total:      row.get::<_, Option<i64>>(1)?.unwrap_or(repeat_count),
                    completed:  row.get(2)?,
                })
            },
        );
        match result {
            Ok(found) => Ok(Some(found)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(e),
        }
    })
}

/// 대기열 시간 추산용 데이터
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct QueueEstimate {
    /// 완료된 세션 기반 평균 ms — (1 TC × 1 세트) 단위
    pub avg_ms_per_tc_set: f64,
    /// 실행 중 세션: 완료된 세트 수 (세션 없으면 0)
    pub running_completed: i64,
    /// 실행 중 세션: 총 세트 수 (세션 없으면 0)
    pub running_total: i64,
    /// 실행 중 세션: started_at ISO 문자열
    pub running_started_at: Option<String>,
}

/// 대기열 예상 시간 계산용 데이터 조회
/// running_session_id 가 있으면 해당 세션의 진행도도 함께 반환
#[tauri::command]
pub fn db_get_queue_estimate(running_session_id: Option<String>) -> Result<QueueEstimate, String> {
    with_db(|conn| {
        // 1) 완료된 세션들의 평균 — ms per (1 TC × 1 set)
        let avg_ms_per_tc_set: f64 = conn.query_row(
            "SELECT COALESCE(AVG(dur), 0) FROM ( \
               SELECT \
                 (julianday(finished_at) - julianday(started_at)) * 86400000.0 \
                 / (repeat_count * (length(tc_ids) - length(replace(tc_ids, ',', '')) + 1)) \
                 AS dur \
               FROM tc_sessions \
               WHERE finished_at IS NOT NULL AND repeat_count > 0 \
             )",
            [],
            |row| row.get(0),
        ).unwrap_or(0.0);

        // 2) 실행 중 세션 진행도
        let (running_completed, running_total, running_started_at) =
            if let Some(ref sid) = running_session_id {
                conn.query_row(
                    "SELECT \
                       COALESCE(MAX(r.repeat_index), 0), \
                       s.repeat_count, \
                       s.started_at \
                     FROM tc_sessions s \
                     LEFT JOIN tc_results r ON s.session_id = r.session_id \
                     WHERE s.session_id = ?1 \
                     GROUP BY s.session_id",
                    rusqlite::params![sid],
                    |row| Ok((
                        row.get::<_, i64>(0)?,
                        row.get::<_, Option<i64>>(1)?.unwrap_or(0),
                        row.get::<_, Option<String>>(2)?,
                    )),
                ).unwrap_or((0, 0, None))
            } else {
                (0, 0, None)
            };

        Ok(QueueEstimate {
            avg_ms_per_tc_set,
            running_completed,
            running_total,
            running_started_at,
        })
    })
}

// ── 쿼리 커맨드 출력 타입 ─────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ResultSummary {
    pub run_id: String,
    pub session_id: Option<String>,
    pub repeat_index: Option<i64>,
    pub tc_id: String,
    pub started_at: String,
    pub finished_at: String,
    pub duration_ms: i64,
    pub status: String,
    pub ios_visqol_mos: Option<f64>,
    pub android_visqol_mos: Option<f64>,
    pub snr_db: Option<f64>,
    pub dropout_count: Option<i64>,
    pub dropout_severity: Option<String>,
    pub dropout_report_path: Option<String>,
    pub mos_report_path: Option<String>,
    pub vishing_detected: Option<bool>,
    pub error_msg: Option<String>,
    // v2
    pub and_dropped_count:  Option<i64>,
    pub and_degraded_count: Option<i64>,
    pub and_poor_count:     Option<i64>,
    pub and_severity:       Option<String>,
    pub ios_dropped_count:  Option<i64>,
    pub ios_degraded_count: Option<i64>,
    pub ios_poor_count:     Option<i64>,
    pub ios_severity:       Option<String>,
    pub voip_delay_ms:      Option<i64>,
    // v3: 디바이스 & 앱 버전
    pub android_app_ver:    Option<String>,
    pub ios_app_ver:        Option<String>,
    pub android_device:     Option<String>,
    pub android_os_ver:     Option<String>,
    pub ios_device:         Option<String>,
    pub ios_os_ver:         Option<String>,
    pub profile_name:       Option<String>,
    // v4: 통신사
    pub carrier:            Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ResultDetail {
    pub result: ResultSummary,
    pub audio_files: Vec<FileEntry>,
    pub screenshots: Vec<String>,
    pub log_lines: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct FileEntry {
    pub label: String,
    pub path: String,
}

/// 최근 결과 N건 조회 (기본 200건)
#[tauri::command]
pub fn db_query_results(limit: Option<i64>) -> Result<Vec<ResultSummary>, String> {
    with_db(|conn| {
        let rows = db::query_results(conn, limit.unwrap_or(200))?;
        Ok(rows.into_iter().map(row_to_summary).collect())
    })
}

/// 앱 시작 시 DB에서 세션+결과 복원 (localStorage 소실 대응)
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DbSnapshot {
    pub sessions: Vec<DbSessionSummary>,
    pub results:  Vec<ResultSummary>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DbSessionSummary {
    pub session_id:   String,
    pub tc_ids:       Vec<String>,
    pub started_at:   String,
    pub finished_at:  Option<String>,
    pub repeat_count: Option<i64>,
    pub repeat_mode:  Option<String>,
    pub fail_action:  Option<String>,
    pub run_ids:      Vec<String>,
}

#[tauri::command]
pub fn db_load_snapshot(limit: Option<i64>) -> Result<DbSnapshot, String> {
    with_db(|conn| {
        let lim = limit.unwrap_or(5000);

        // 결과 조회
        let result_rows = db::query_results(conn, lim)?;
        let results: Vec<ResultSummary> = result_rows.iter().map(|r| row_to_summary(r.clone())).collect();

        // 세션 조회
        let session_rows = db::query_sessions(conn, lim)?;

        // 세션별 run_id 목록 구축
        let mut session_run_map: std::collections::HashMap<String, Vec<String>> = std::collections::HashMap::new();
        for r in &result_rows {
            if let Some(sid) = &r.session_id {
                session_run_map.entry(sid.clone()).or_default().push(r.run_id.clone());
            }
        }

        let sessions: Vec<DbSessionSummary> = session_rows.into_iter().map(|s| {
            let tc_ids: Vec<String> = serde_json::from_str(&s.tc_ids).unwrap_or_default();
            let run_ids = session_run_map.remove(&s.session_id).unwrap_or_default();
            DbSessionSummary {
                session_id:   s.session_id,
                tc_ids,
                started_at:   s.started_at,
                finished_at:  s.finished_at,
                repeat_count: s.repeat_count,
                repeat_mode:  s.repeat_mode,
                fail_action:  s.fail_action,
                run_ids,
            }
        }).collect();

        Ok(DbSnapshot { sessions, results })
    })
}

/// 특정 run_id의 상세 조회 (음원·스크린샷·로그 포함)
#[tauri::command]
pub fn db_query_result_detail(run_id: String) -> Result<ResultDetail, String> {
    with_db(|conn| {
        let rows = db::query_results(conn, 1)?;
        // run_id로 단건 조회
        let mut stmt = conn.prepare(
            "SELECT run_id, session_id, repeat_index, tc_id, started_at, finished_at,
                    duration_ms, status, ios_visqol_mos, android_visqol_mos, snr_db,
                    dropout_count, dropout_severity, dropout_report_path, mos_report_path,
                    vishing_detected, error_msg,
                    and_dropped_count, and_degraded_count, and_poor_count, and_severity,
                    ios_dropped_count, ios_degraded_count, ios_poor_count, ios_severity,
                    voip_delay_ms,
                    android_app_ver, ios_app_ver, android_device, android_os_ver,
                    ios_device, ios_os_ver, profile_name, carrier
             FROM tc_results WHERE run_id = ?1"
        )?;
        let row = stmt.query_row(rusqlite::params![run_id], |row| {
            Ok(db::TcResultRow {
                run_id:               row.get(0)?,
                session_id:           row.get(1)?,
                repeat_index:         row.get(2)?,
                tc_id:                row.get(3)?,
                started_at:           row.get(4)?,
                finished_at:          row.get(5)?,
                duration_ms:          row.get(6)?,
                status:               row.get(7)?,
                ios_visqol_mos:       row.get(8)?,
                android_visqol_mos:   row.get(9)?,
                snr_db:               row.get(10)?,
                dropout_count:        row.get(11)?,
                dropout_severity:     row.get(12)?,
                dropout_report_path:  row.get(13)?,
                mos_report_path:      row.get(14)?,
                vishing_detected:     row.get::<_, Option<i64>>(15)?.map(|v| v != 0),
                error_msg:            row.get(16)?,
                and_dropped_count:    row.get(17)?,
                and_degraded_count:   row.get(18)?,
                and_poor_count:       row.get(19)?,
                and_severity:         row.get(20)?,
                ios_dropped_count:    row.get(21)?,
                ios_degraded_count:   row.get(22)?,
                ios_poor_count:       row.get(23)?,
                ios_severity:         row.get(24)?,
                voip_delay_ms:        row.get(25)?,
                android_app_ver:      row.get(26)?,
                ios_app_ver:          row.get(27)?,
                android_device:       row.get(28)?,
                android_os_ver:       row.get(29)?,
                ios_device:           row.get(30)?,
                ios_os_ver:           row.get(31)?,
                profile_name:         row.get(32)?,
                carrier:              row.get(33)?,
            })
        })?;

        let files = db::query_result_files(conn, &run_id)?;
        let logs  = db::query_result_logs(conn, &run_id)?;

        let audio_files = files.iter()
            .filter(|f| f.file_type == "audio")
            .map(|f| FileEntry { label: f.label.clone(), path: f.path.clone() })
            .collect();
        let screenshots = files.iter()
            .filter(|f| f.file_type == "screenshot")
            .map(|f| f.path.clone())
            .collect();

        let _ = rows; // suppress unused warning
        Ok(ResultDetail {
            result: row_to_summary(row),
            audio_files,
            screenshots,
            log_lines: logs,
        })
    })
}

fn row_to_summary(r: db::TcResultRow) -> ResultSummary {
    ResultSummary {
        run_id:              r.run_id,
        session_id:          r.session_id,
        repeat_index:        r.repeat_index,
        tc_id:               r.tc_id,
        started_at:          r.started_at,
        finished_at:         r.finished_at,
        duration_ms:         r.duration_ms,
        status:              r.status,
        ios_visqol_mos:      r.ios_visqol_mos,
        android_visqol_mos:  r.android_visqol_mos,
        snr_db:              r.snr_db,
        dropout_count:       r.dropout_count,
        dropout_severity:    r.dropout_severity,
        dropout_report_path: r.dropout_report_path,
        mos_report_path:     r.mos_report_path,
        vishing_detected:    r.vishing_detected,
        error_msg:           r.error_msg,
        and_dropped_count:   r.and_dropped_count,
        and_degraded_count:  r.and_degraded_count,
        and_poor_count:      r.and_poor_count,
        and_severity:        r.and_severity,
        ios_dropped_count:   r.ios_dropped_count,
        ios_degraded_count:  r.ios_degraded_count,
        ios_poor_count:      r.ios_poor_count,
        ios_severity:        r.ios_severity,
        voip_delay_ms:       r.voip_delay_ms,
        android_app_ver:     r.android_app_ver,
        ios_app_ver:         r.ios_app_ver,
        android_device:      r.android_device,
        android_os_ver:      r.android_os_ver,
        ios_device:          r.ios_device,
        ios_os_ver:          r.ios_os_ver,
        profile_name:        r.profile_name,
        carrier:             r.carrier,
    }
}

// ── 통계 / 내보내기 커맨드 ─────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TcStats {
    pub tc_id: String,
    pub total: i64,
    pub pass: i64,
    pub fail: i64,
    pub error: i64,
    pub pass_rate: f64,
    pub avg_duration_ms: f64,
    pub avg_ios_mos: Option<f64>,
    pub avg_android_mos: Option<f64>,
    pub avg_dropout_count: Option<f64>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DailyMos {
    pub date: String,           // YYYY-MM-DD
    pub tc_id: String,
    pub avg_ios_mos: Option<f64>,
    pub avg_android_mos: Option<f64>,
    pub run_count: i64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SeverityStats {
    pub tc_id: String,
    pub severity: String,
    pub count: i64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DbExportData {
    /// 전체 결과 목록 (최근 N건)
    pub results: Vec<ResultSummary>,
    /// TC별 PASS/FAIL/ERROR 통계
    pub tc_stats: Vec<TcStats>,
    /// 날짜별 MOS 추이
    pub daily_mos: Vec<DailyMos>,
    /// Severity 분포
    pub severity_stats: Vec<SeverityStats>,
    /// 조회 기간
    pub from_date: Option<String>,
    pub to_date: Option<String>,
    pub total_count: i64,
}

/// Excel 내보내기용 전체 통계 데이터 조회
/// from_date / to_date: "YYYY-MM-DD" 형식 (null이면 전체 기간)
#[tauri::command]
pub fn db_export_stats(
    from_date: Option<String>,
    to_date: Option<String>,
    limit: Option<i64>,
) -> Result<DbExportData, String> {
    with_db(|conn| {
        // 날짜 필터 조건
        let from = from_date.clone().unwrap_or_else(|| "1970-01-01".to_string());
        let to   = to_date.clone().unwrap_or_else(|| "9999-12-31".to_string());
        let lim  = limit.unwrap_or(5000);

        // 1. 전체 결과 목록
        let mut stmt = conn.prepare(&format!(
            "SELECT run_id, session_id, repeat_index, tc_id, started_at, finished_at,
                    duration_ms, status, ios_visqol_mos, android_visqol_mos, snr_db,
                    dropout_count, dropout_severity, dropout_report_path, mos_report_path,
                    vishing_detected, error_msg,
                    and_dropped_count, and_degraded_count, and_poor_count, and_severity,
                    ios_dropped_count, ios_degraded_count, ios_poor_count, ios_severity,
                    voip_delay_ms,
                    android_app_ver, ios_app_ver, android_device, android_os_ver,
                    ios_device, ios_os_ver, profile_name, carrier
             FROM tc_results
             WHERE date(started_at) >= '{}' AND date(started_at) <= '{}'
             ORDER BY started_at DESC LIMIT {}", from, to, lim
        ))?;
        let results: Vec<ResultSummary> = stmt.query_map([], |row| {
            Ok(db::TcResultRow {
                run_id:               row.get(0)?,
                session_id:           row.get(1)?,
                repeat_index:         row.get(2)?,
                tc_id:                row.get(3)?,
                started_at:           row.get(4)?,
                finished_at:          row.get(5)?,
                duration_ms:          row.get(6)?,
                status:               row.get(7)?,
                ios_visqol_mos:       row.get(8)?,
                android_visqol_mos:   row.get(9)?,
                snr_db:               row.get(10)?,
                dropout_count:        row.get(11)?,
                dropout_severity:     row.get(12)?,
                dropout_report_path:  row.get(13)?,
                mos_report_path:      row.get(14)?,
                vishing_detected:     row.get::<_, Option<i64>>(15)?.map(|v| v != 0),
                error_msg:            row.get(16)?,
                and_dropped_count:    row.get(17)?,
                and_degraded_count:   row.get(18)?,
                and_poor_count:       row.get(19)?,
                and_severity:         row.get(20)?,
                ios_dropped_count:    row.get(21)?,
                ios_degraded_count:   row.get(22)?,
                ios_poor_count:       row.get(23)?,
                ios_severity:         row.get(24)?,
                voip_delay_ms:        row.get(25)?,
                android_app_ver:      row.get(26)?,
                ios_app_ver:          row.get(27)?,
                android_device:       row.get(28)?,
                android_os_ver:       row.get(29)?,
                ios_device:           row.get(30)?,
                ios_os_ver:           row.get(31)?,
                profile_name:         row.get(32)?,
                carrier:              row.get(33)?,
            })
        })?.filter_map(|r| r.ok()).map(row_to_summary).collect();

        // 실제 전체 건수 (LIMIT 무관)
        let total_count: i64 = conn.query_row(
            &format!(
                "SELECT COUNT(*) FROM tc_results WHERE date(started_at) >= '{}' AND date(started_at) <= '{}'",
                from, to
            ),
            [],
            |row| row.get(0),
        ).unwrap_or(0);

        // 2. TC별 PASS/FAIL 통계
        let mut stmt2 = conn.prepare(&format!(
            "SELECT tc_id,
                    COUNT(*) as total,
                    SUM(CASE WHEN status='PASS'  THEN 1 ELSE 0 END) as pass,
                    SUM(CASE WHEN status='FAIL'  THEN 1 ELSE 0 END) as fail,
                    SUM(CASE WHEN status='ERROR' THEN 1 ELSE 0 END) as err,
                    AVG(duration_ms),
                    AVG(ios_visqol_mos),
                    AVG(android_visqol_mos),
                    AVG(dropout_count)
             FROM tc_results
             WHERE date(started_at) >= '{}' AND date(started_at) <= '{}'
             GROUP BY tc_id ORDER BY tc_id", from, to
        ))?;
        let tc_stats: Vec<TcStats> = stmt2.query_map([], |row| {
            let total: i64 = row.get(1)?;
            let pass: i64  = row.get(2)?;
            Ok(TcStats {
                tc_id:             row.get(0)?,
                total,
                pass,
                fail:              row.get(3)?,
                error:             row.get(4)?,
                pass_rate:         if total > 0 { pass as f64 / total as f64 * 100.0 } else { 0.0 },
                avg_duration_ms:   row.get::<_, Option<f64>>(5)?.unwrap_or(0.0),
                avg_ios_mos:       row.get(6)?,
                avg_android_mos:   row.get(7)?,
                avg_dropout_count: row.get(8)?,
            })
        })?.filter_map(|r| r.ok()).collect();

        // 3. 날짜별 MOS 추이
        let mut stmt3 = conn.prepare(&format!(
            "SELECT date(started_at) as d, tc_id,
                    AVG(ios_visqol_mos), AVG(android_visqol_mos), COUNT(*)
             FROM tc_results
             WHERE date(started_at) >= '{}' AND date(started_at) <= '{}'
             GROUP BY d, tc_id ORDER BY d, tc_id", from, to
        ))?;
        let daily_mos: Vec<DailyMos> = stmt3.query_map([], |row| {
            Ok(DailyMos {
                date:            row.get(0)?,
                tc_id:           row.get(1)?,
                avg_ios_mos:     row.get(2)?,
                avg_android_mos: row.get(3)?,
                run_count:       row.get(4)?,
            })
        })?.filter_map(|r| r.ok()).collect();

        // 4. Severity 분포
        let mut stmt4 = conn.prepare(&format!(
            "SELECT tc_id, COALESCE(dropout_severity, '없음') as sev, COUNT(*)
             FROM tc_results
             WHERE date(started_at) >= '{}' AND date(started_at) <= '{}'
             GROUP BY tc_id, sev ORDER BY tc_id, sev", from, to
        ))?;
        let severity_stats: Vec<SeverityStats> = stmt4.query_map([], |row| {
            Ok(SeverityStats {
                tc_id:    row.get(0)?,
                severity: row.get(1)?,
                count:    row.get(2)?,
            })
        })?.filter_map(|r| r.ok()).collect();

        Ok(DbExportData {
            results,
            tc_stats,
            daily_mos,
            severity_stats,
            from_date: from_date.clone(),
            to_date:   to_date.clone(),
            total_count,
        })
    })
}

/// localStorage에 이미 쌓인 결과를 DB로 일괄 소급 적재
/// - sessions: tc_sessions 먼저 upsert (results FK 충족)
/// - 이미 존재하는 run_id는 건너뜀 (중복 방지)
/// - 반환값: 실제로 새로 저장된 결과 건수
#[tauri::command]
pub fn db_batch_save_results(
    sessions: Vec<SaveSessionPayload>,
    results: Vec<SaveResultPayload>,
) -> Result<usize, String> {
    let total = results.len();
    println!("[db] 소급 적재 시작: 세션 {}건 + 결과 {}건 처리 예정", sessions.len(), total);

    with_db(|conn| {
        // ① 세션 먼저 upsert — results FK 충족을 위해 반드시 선행
        for s in &sessions {
            let row = TcSessionRow {
                session_id:   s.session_id.clone(),
                tc_ids:       serde_json::to_string(&s.tc_ids).unwrap_or_default(),
                started_at:   s.started_at.clone(),
                finished_at:  s.finished_at.clone(),
                repeat_count: s.repeat_count,
                repeat_mode:  s.repeat_mode.clone(),
                fail_action:  s.fail_action.clone(),
            };
            if let Err(e) = db::upsert_session(conn, &row) {
                eprintln!("[db] 세션 소급 적재 실패 session_id={}: {:?}", s.session_id, e);
            }
        }
        println!("[db] 세션 upsert 완료: {}건", sessions.len());

        let mut saved   = 0usize;
        let mut skipped = 0usize;
        let mut failed  = 0usize;

        // ② 결과 적재
        for payload in &results {
            // 이미 존재하는 run_id면 스킵
            let existing: i64 = conn
                .query_row(
                    "SELECT COUNT(*) FROM tc_results WHERE run_id = ?1",
                    rusqlite::params![payload.run_id],
                    |r| r.get(0),
                )
                .unwrap_or(0);
            if existing > 0 {
                skipped += 1;
                continue;
            }

            let row = TcResultRow {
                run_id:              payload.run_id.clone(),
                session_id:          payload.session_id.clone(),
                repeat_index:        payload.repeat_index,
                tc_id:               payload.tc_id.clone(),
                started_at:          payload.started_at.clone(),
                finished_at:         payload.finished_at.clone(),
                duration_ms:         payload.duration_ms,
                status:              payload.status.clone(),
                ios_visqol_mos:      payload.ios_visqol_mos,
                android_visqol_mos:  payload.android_visqol_mos,
                snr_db:              payload.snr_db,
                dropout_count:       payload.dropout_count,
                dropout_severity:    payload.dropout_severity.clone(),
                dropout_report_path: payload.dropout_report_path.clone(),
                mos_report_path:     payload.mos_report_path.clone(),
                vishing_detected:    payload.vishing_detected,
                error_msg:           payload.error_msg.clone(),
                and_dropped_count:   payload.and_dropped_count,
                and_degraded_count:  payload.and_degraded_count,
                and_poor_count:      payload.and_poor_count,
                and_severity:        payload.and_severity.clone(),
                ios_dropped_count:   payload.ios_dropped_count,
                ios_degraded_count:  payload.ios_degraded_count,
                ios_poor_count:      payload.ios_poor_count,
                ios_severity:        payload.ios_severity.clone(),
                voip_delay_ms:       payload.voip_delay_ms,
                android_app_ver:     payload.android_app_ver.clone(),
                ios_app_ver:         payload.ios_app_ver.clone(),
                android_device:      payload.android_device.clone(),
                android_os_ver:      payload.android_os_ver.clone(),
                ios_device:          payload.ios_device.clone(),
                ios_os_ver:          payload.ios_os_ver.clone(),
                profile_name:        payload.profile_name.clone(),
                carrier:             payload.carrier.clone(),
            };

            if let Err(e) = db::insert_result(conn, &row) {
                eprintln!("[db] 소급 적재 실패 run_id={}: {:?}", payload.run_id, e);
                failed += 1;
                continue;
            }

            let audio_files: Vec<db::ResultFile> = payload
                .extracted_audio_paths
                .iter()
                .map(|f| db::ResultFile {
                    run_id:    payload.run_id.clone(),
                    file_type: "audio".to_string(),
                    label:     f.label.clone(),
                    path:      f.path.clone(),
                })
                .collect();
            if let Err(e) = db::insert_result_files(conn, &audio_files) {
                eprintln!("[db] 음원파일 적재 실패 run_id={}: {:?}", payload.run_id, e);
            }

            let screenshots: Vec<db::ResultFile> = payload
                .screenshot_paths
                .iter()
                .map(|p| db::ResultFile {
                    run_id:    payload.run_id.clone(),
                    file_type: "screenshot".to_string(),
                    label:     "screenshot".to_string(),
                    path:      p.clone(),
                })
                .collect();
            if let Err(e) = db::insert_result_files(conn, &screenshots) {
                eprintln!("[db] 스크린샷 적재 실패 run_id={}: {:?}", payload.run_id, e);
            }

            if let Err(e) = db::insert_result_logs(conn, &payload.run_id, &payload.log_lines) {
                eprintln!("[db] 로그 적재 실패 run_id={}: {:?}", payload.run_id, e);
            }

            saved += 1;
        }
        println!("[db] 소급 적재 완료: {}건 저장 / {}건 중복 스킵 / {}건 실패 (전체 {}건)",
                 saved, skipped, failed, total);
        Ok(saved)
    })
}

// ── 단위 테스트 ───────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// Tauri가 JS `invoke("db_save_result", { payload: { runId, ... } })` 를 수신했을 때
    /// `payload` 값을 SaveResultPayload 로 역직렬화할 수 있는지 검증.
    /// serde rename_all = "camelCase" 가 올바르게 적용되어 camelCase → snake_case 변환되는지 확인.
    #[test]
    fn test_save_result_payload_deserialize_camelcase() {
        let json_val = json!({
            "runId":             "run-test-001",
            "sessionId":         null,
            "repeatIndex":       null,
            "tcId":              "TC_01",
            "startedAt":         "2026-04-09T10:00:00",
            "finishedAt":        "2026-04-09T10:01:00",
            "durationMs":        60000_i64,
            "status":            "PASS",
            "iosVisqolMos":      3.5_f64,
            "androidVisqolMos":  4.1_f64,
            "snrDb":             null,
            "dropoutCount":      0_i64,
            "dropoutSeverity":   "없음",
            "dropoutReportPath": null,
            "mosReportPath":     null,
            "vishingDetected":   false,
            "errorMsg":          null,
            "extractedAudioPaths": [{"label": "iOS", "path": "/a.wav"}],
            "screenshotPaths":   [],
            "logLines":          ["[ts] PASS"]
        });

        let payload: SaveResultPayload =
            serde_json::from_value(json_val).expect("SaveResultPayload 역직렬화 실패");

        assert_eq!(payload.run_id,            "run-test-001", "run_id");
        assert_eq!(payload.tc_id,             "TC_01",        "tc_id");
        assert_eq!(payload.status,            "PASS",         "status");
        assert_eq!(payload.ios_visqol_mos,    Some(3.5),      "ios_visqol_mos");
        assert_eq!(payload.android_visqol_mos,Some(4.1),      "android_visqol_mos");
        assert_eq!(payload.dropout_count,     Some(0),        "dropout_count");
        assert_eq!(payload.vishing_detected,  Some(false),    "vishing_detected");
        assert_eq!(payload.extracted_audio_paths.len(), 1,    "audio paths 1건");
        assert_eq!(payload.log_lines,         vec!["[ts] PASS"], "log_lines");
    }

    /// SaveSessionPayload 역직렬화 검증
    #[test]
    fn test_save_session_payload_deserialize_camelcase() {
        let json_val = json!({
            "sessionId":   "sess-abc",
            "tcIds":       ["TC_01", "TC_02"],
            "startedAt":   "2026-04-09T10:00:00",
            "finishedAt":  null,
            "repeatCount": null,
            "repeatMode":  null,
            "failAction":  null
        });

        let payload: SaveSessionPayload =
            serde_json::from_value(json_val).expect("SaveSessionPayload 역직렬화 실패");

        assert_eq!(payload.session_id, "sess-abc");
        assert_eq!(payload.tc_ids,     vec!["TC_01", "TC_02"]);
        assert!(payload.finished_at.is_none());
    }

    /// camelCase 키 없이 snake_case 로 보내면 역직렬화 실패해야 함.
    /// → JS에서 payload 래핑 없이 직접 필드를 넘기던 기존 버그를 재현.
    #[test]
    fn test_snake_case_fields_fail() {
        let json_val = json!({
            "run_id":    "run-test", // JS에서 직접 넘길 때 camelCase가 없으면 실패
            "tc_id":     "TC_01",
            "started_at": "2026-04-09T10:00:00",
            "finished_at": "2026-04-09T10:01:00",
            "duration_ms": 60000_i64,
            "status":    "PASS",
            "extracted_audio_paths": [],
            "screenshot_paths": [],
            "log_lines": []
        });
        // serde rename_all=camelCase 이므로 snake_case 키는 인식 못함 → 필수 runId 누락 → 에러
        let result: Result<SaveResultPayload, _> = serde_json::from_value(json_val);
        assert!(result.is_err(), "snake_case 키를 보내면 역직렬화가 실패해야 함 (camelCase 필수)");
    }
}
