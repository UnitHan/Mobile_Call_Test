/// db.rs — SQLite 영속화 모듈
///
/// DB 파일: {app_data_dir}/ixio_results.db
/// 테이블:
///   - tc_sessions  : TcSession (세션 묶음)
///   - tc_results   : TcResult  (개별 실행 결과)
///   - result_files : 음원·스크린샷 파일 경로 (tc_results 1:N)
///   - result_logs  : 로그 라인 (tc_results 1:N)

use rusqlite::{Connection, Result, params};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

// ── DB Row 타입 ────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TcResultRow {
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
    // v2: 플랫폼별 세부 통계
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TcSessionRow {
    pub session_id: String,
    pub tc_ids: String,        // JSON array string
    pub started_at: String,
    pub finished_at: Option<String>,
    pub repeat_count: Option<i64>,
    pub repeat_mode: Option<String>,
    pub fail_action: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResultFile {
    pub run_id: String,
    pub file_type: String,   // "audio" | "screenshot"
    pub label: String,
    pub path: String,
}

// ── DB 초기화 ─────────────────────────────────────────────────────────────────

pub fn open_db(app_data_dir: &PathBuf) -> Result<Connection> {
    let db_path = app_data_dir.join("ixio_results.db");
    let conn = Connection::open(&db_path)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
    create_tables(&conn)?;
    Ok(conn)
}

fn create_tables(conn: &Connection) -> Result<()> {
    conn.execute_batch("
        CREATE TABLE IF NOT EXISTS tc_sessions (
            session_id    TEXT PRIMARY KEY,
            tc_ids        TEXT NOT NULL,
            started_at    TEXT NOT NULL,
            finished_at   TEXT,
            repeat_count  INTEGER,
            repeat_mode   TEXT,
            fail_action   TEXT
        );

        CREATE TABLE IF NOT EXISTS tc_results (
            run_id               TEXT PRIMARY KEY,
            session_id           TEXT REFERENCES tc_sessions(session_id),
            repeat_index         INTEGER,
            tc_id                TEXT NOT NULL,
            started_at           TEXT NOT NULL,
            finished_at          TEXT NOT NULL,
            duration_ms          INTEGER NOT NULL,
            status               TEXT NOT NULL,
            ios_visqol_mos       REAL,
            android_visqol_mos   REAL,
            snr_db               REAL,
            dropout_count        INTEGER,
            dropout_severity     TEXT,
            dropout_report_path  TEXT,
            mos_report_path      TEXT,
            vishing_detected     INTEGER,
            error_msg            TEXT,
            -- Android 세부 (v2)
            and_dropped_count    INTEGER,
            and_degraded_count   INTEGER,
            and_poor_count       INTEGER,
            and_severity         TEXT,
            -- iOS 세부 (v2)
            ios_dropped_count    INTEGER,
            ios_degraded_count   INTEGER,
            ios_poor_count       INTEGER,
            ios_severity         TEXT,
            -- 공통 (v2)
            voip_delay_ms        INTEGER,
            -- 디바이스 & 앱 버전 (v3)
            android_app_ver      TEXT,
            ios_app_ver          TEXT,
            android_device       TEXT,
            android_os_ver       TEXT,
            ios_device           TEXT,
            ios_os_ver           TEXT,
            profile_name         TEXT,
            -- 통신사 (v4)
            carrier              TEXT
        );

        CREATE TABLE IF NOT EXISTS result_files (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id    TEXT NOT NULL REFERENCES tc_results(run_id),
            file_type TEXT NOT NULL,
            label     TEXT NOT NULL,
            path      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS result_logs (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id  TEXT NOT NULL REFERENCES tc_results(run_id),
            line    TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_results_session  ON tc_results(session_id);
        CREATE INDEX IF NOT EXISTS idx_results_tc_id    ON tc_results(tc_id);
        CREATE INDEX IF NOT EXISTS idx_results_started  ON tc_results(started_at);
        CREATE INDEX IF NOT EXISTS idx_files_run_id     ON result_files(run_id);
        CREATE INDEX IF NOT EXISTS idx_logs_run_id      ON result_logs(run_id);
    ")?;

    // ── 기존 DB 무중단 마이그레이션: v2 컬럼 없으면 추가 ─────────────────────
    let migrations = [
        "ALTER TABLE tc_results ADD COLUMN and_dropped_count  INTEGER",
        "ALTER TABLE tc_results ADD COLUMN and_degraded_count INTEGER",
        "ALTER TABLE tc_results ADD COLUMN and_poor_count     INTEGER",
        "ALTER TABLE tc_results ADD COLUMN and_severity       TEXT",
        "ALTER TABLE tc_results ADD COLUMN ios_dropped_count  INTEGER",
        "ALTER TABLE tc_results ADD COLUMN ios_degraded_count INTEGER",
        "ALTER TABLE tc_results ADD COLUMN ios_poor_count     INTEGER",
        "ALTER TABLE tc_results ADD COLUMN ios_severity       TEXT",
        "ALTER TABLE tc_results ADD COLUMN voip_delay_ms      INTEGER",
        "ALTER TABLE tc_results ADD COLUMN android_app_ver    TEXT",
        "ALTER TABLE tc_results ADD COLUMN ios_app_ver        TEXT",
        "ALTER TABLE tc_results ADD COLUMN android_device     TEXT",
        "ALTER TABLE tc_results ADD COLUMN android_os_ver     TEXT",
        "ALTER TABLE tc_results ADD COLUMN ios_device         TEXT",
        "ALTER TABLE tc_results ADD COLUMN ios_os_ver         TEXT",
        "ALTER TABLE tc_results ADD COLUMN profile_name       TEXT",
        // v4: 통신사
        "ALTER TABLE tc_results ADD COLUMN carrier             TEXT",
    ];
    for sql in &migrations {
        // "duplicate column name" 오류는 이미 존재하는 것이므로 무시
        let _ = conn.execute(sql, []);
    }

    Ok(())
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

pub fn upsert_session(conn: &Connection, s: &TcSessionRow) -> Result<()> {
    conn.execute(
        "INSERT INTO tc_sessions (session_id, tc_ids, started_at, finished_at, repeat_count, repeat_mode, fail_action)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
         ON CONFLICT(session_id) DO UPDATE SET
           finished_at  = excluded.finished_at,
           repeat_count = excluded.repeat_count,
           repeat_mode  = excluded.repeat_mode,
           fail_action  = excluded.fail_action",
        params![
            s.session_id, s.tc_ids, s.started_at, s.finished_at,
            s.repeat_count, s.repeat_mode, s.fail_action,
        ],
    )?;
    Ok(())
}

pub fn insert_result(conn: &Connection, r: &TcResultRow) -> Result<()> {
    conn.execute(
        "INSERT OR REPLACE INTO tc_results
         (run_id, session_id, repeat_index, tc_id, started_at, finished_at,
          duration_ms, status, ios_visqol_mos, android_visqol_mos, snr_db,
          dropout_count, dropout_severity, dropout_report_path, mos_report_path,
          vishing_detected, error_msg,
          and_dropped_count, and_degraded_count, and_poor_count, and_severity,
          ios_dropped_count, ios_degraded_count, ios_poor_count, ios_severity,
          voip_delay_ms,
          android_app_ver, ios_app_ver, android_device, android_os_ver,
          ios_device, ios_os_ver, profile_name, carrier)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,
                 ?18,?19,?20,?21,?22,?23,?24,?25,?26,
                 ?27,?28,?29,?30,?31,?32,?33,?34)",
        params![
            r.run_id, r.session_id, r.repeat_index, r.tc_id,
            r.started_at, r.finished_at, r.duration_ms, r.status,
            r.ios_visqol_mos, r.android_visqol_mos, r.snr_db,
            r.dropout_count, r.dropout_severity, r.dropout_report_path,
            r.mos_report_path,
            r.vishing_detected.map(|v| v as i64),
            r.error_msg,
            r.and_dropped_count, r.and_degraded_count, r.and_poor_count, r.and_severity,
            r.ios_dropped_count, r.ios_degraded_count, r.ios_poor_count, r.ios_severity,
            r.voip_delay_ms,
            r.android_app_ver, r.ios_app_ver, r.android_device, r.android_os_ver,
            r.ios_device, r.ios_os_ver, r.profile_name,
            r.carrier,
        ],
    )?;
    Ok(())
}

/// MOS 보고서 경로만 업데이트 (전체 row INSERT OR REPLACE 없이 경량 UPDATE)
pub fn update_mos_report_path(conn: &Connection, run_id: &str, path: &str) -> Result<()> {
    conn.execute(
        "UPDATE tc_results SET mos_report_path = ?1 WHERE run_id = ?2",
        params![path, run_id],
    )?;
    Ok(())
}

pub fn insert_result_files(conn: &Connection, files: &[ResultFile]) -> Result<()> {
    for f in files {
        conn.execute(
            "INSERT INTO result_files (run_id, file_type, label, path) VALUES (?1,?2,?3,?4)",
            params![f.run_id, f.file_type, f.label, f.path],
        )?;
    }
    Ok(())
}

pub fn insert_result_logs(conn: &Connection, run_id: &str, logs: &[String]) -> Result<()> {
    for line in logs {
        conn.execute(
            "INSERT INTO result_logs (run_id, line) VALUES (?1, ?2)",
            params![run_id, line],
        )?;
    }
    Ok(())
}

// ── 쿼리 ──────────────────────────────────────────────────────────────────────

pub fn query_results(conn: &Connection, limit: i64) -> Result<Vec<TcResultRow>> {
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
         FROM tc_results ORDER BY started_at DESC LIMIT ?1"
    )?;
    let rows = stmt.query_map(params![limit], |row| {
        Ok(TcResultRow {
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
    rows.collect()
}

pub fn query_result_files(conn: &Connection, run_id: &str) -> Result<Vec<ResultFile>> {
    let mut stmt = conn.prepare(
        "SELECT run_id, file_type, label, path FROM result_files WHERE run_id = ?1"
    )?;
    let rows = stmt.query_map(params![run_id], |row| {
        Ok(ResultFile {
            run_id:    row.get(0)?,
            file_type: row.get(1)?,
            label:     row.get(2)?,
            path:      row.get(3)?,
        })
    })?;
    rows.collect()
}

pub fn query_result_logs(conn: &Connection, run_id: &str) -> Result<Vec<String>> {
    let mut stmt = conn.prepare(
        "SELECT line FROM result_logs WHERE run_id = ?1 ORDER BY id"
    )?;
    let rows = stmt.query_map(params![run_id], |row| row.get(0))?;
    rows.collect()
}

/// DB에서 세션 목록 조회 (최신순, limit건)
pub fn query_sessions(conn: &Connection, limit: i64) -> Result<Vec<TcSessionRow>> {
    let mut stmt = conn.prepare(
        "SELECT session_id, tc_ids, started_at, finished_at, repeat_count, repeat_mode, fail_action
         FROM tc_sessions ORDER BY started_at DESC LIMIT ?1"
    )?;
    let rows = stmt.query_map(params![limit], |row| {
        Ok(TcSessionRow {
            session_id:   row.get(0)?,
            tc_ids:       row.get(1)?,
            started_at:   row.get(2)?,
            finished_at:  row.get(3)?,
            repeat_count: row.get(4)?,
            repeat_mode:  row.get(5)?,
            fail_action:  row.get(6)?,
        })
    })?;
    rows.collect()
}

// ── 단위 테스트 ───────────────────────────────────────────────────────────────

#[cfg(test)]
pub fn open_in_memory() -> Result<Connection> {
    let conn = Connection::open_in_memory()?;
    conn.execute_batch("PRAGMA foreign_keys=ON;")?;
    create_tables(&conn)?;
    Ok(conn)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mk_session(id: &str) -> TcSessionRow {
        TcSessionRow {
            session_id:   id.to_string(),
            tc_ids:       r#"["TC_01"]"#.to_string(),
            started_at:   "2026-04-09T10:00:00".to_string(),
            finished_at:  None,
            repeat_count: None,
            repeat_mode:  None,
            fail_action:  None,
        }
    }

    fn mk_result(run_id: &str, session_id: Option<&str>) -> TcResultRow {
        TcResultRow {
            run_id:              run_id.to_string(),
            session_id:          session_id.map(str::to_string),
            repeat_index:        None,
            tc_id:               "TC_01".to_string(),
            started_at:          "2026-04-09T10:00:00".to_string(),
            finished_at:         "2026-04-09T10:01:00".to_string(),
            duration_ms:         60_000,
            status:              "PASS".to_string(),
            ios_visqol_mos:      Some(3.5),
            android_visqol_mos:  Some(4.1),
            snr_db:              None,
            dropout_count:       Some(0),
            dropout_severity:    Some("없음".to_string()),
            dropout_report_path: None,
            mos_report_path:     None,
            vishing_detected:    Some(false),
            error_msg:           None,
            and_dropped_count:   Some(0),
            and_degraded_count:  Some(0),
            and_poor_count:      Some(0),
            and_severity:        Some("없음".to_string()),
            ios_dropped_count:   Some(0),
            ios_degraded_count:  Some(0),
            ios_poor_count:      Some(0),
            ios_severity:        Some("없음".to_string()),
            voip_delay_ms:       Some(367),
            android_app_ver:     Some("3.1.0".to_string()),
            ios_app_ver:         Some("3.1.0".to_string()),
            android_device:      Some("Galaxy S24".to_string()),
            android_os_ver:      Some("Android 14".to_string()),
            ios_device:          Some("iPhone 15".to_string()),
            ios_os_ver:          Some("iOS 17.4".to_string()),
            profile_name:        Some("default".to_string()),
            carrier:             Some("lguplus".to_string()),
        }
    }

    // ── 세션 CRUD ─────────────────────────────────────────────────────────────

    #[test]
    fn test_upsert_session_insert() {
        let conn = open_in_memory().unwrap();
        let row = mk_session("sess-001");
        upsert_session(&conn, &row).expect("세션 삽입 실패");

        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM tc_sessions", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 1, "세션 1건이 적재되어야 함");
    }

    #[test]
    fn test_upsert_session_update() {
        let conn = open_in_memory().unwrap();
        let mut row = mk_session("sess-002");
        upsert_session(&conn, &row).unwrap();

        // finished_at 업데이트
        row.finished_at = Some("2026-04-09T11:00:00".to_string());
        upsert_session(&conn, &row).expect("세션 upsert 실패");

        let finished: Option<String> = conn
            .query_row("SELECT finished_at FROM tc_sessions WHERE session_id='sess-002'", [], |r| r.get(0))
            .unwrap();
        assert_eq!(finished.as_deref(), Some("2026-04-09T11:00:00"), "finished_at가 업데이트되어야 함");
    }

    // ── 결과 CRUD ─────────────────────────────────────────────────────────────

    #[test]
    fn test_insert_result_no_session() {
        let conn = open_in_memory().unwrap();
        // session_id = None : FK NULL → 허용
        let row = mk_result("run-001", None);
        insert_result(&conn, &row).expect("session_id=None 결과 삽입 실패");

        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM tc_results", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 1);
    }

    #[test]
    fn test_insert_result_with_valid_session() {
        let conn = open_in_memory().unwrap();
        upsert_session(&conn, &mk_session("sess-10")).unwrap();
        let row = mk_result("run-010", Some("sess-10"));
        insert_result(&conn, &row).expect("유효한 FK 결과 삽입 실패");
    }

    #[test]
    fn test_insert_result_fk_violation() {
        let conn = open_in_memory().unwrap();
        // 존재하지 않는 session_id 참조 → FK 위반
        let row = mk_result("run-bad", Some("sess-nonexistent"));
        let err = insert_result(&conn, &row);
        assert!(err.is_err(), "FK 위반 시 Err를 반환해야 함");
        let msg = err.unwrap_err().to_string();
        assert!(
            msg.contains("FOREIGN KEY") || msg.contains("foreign key"),
            "FK 에러 메시지여야 함, 실제: {msg}"
        );
    }

    #[test]
    fn test_insert_result_upsert_replace() {
        let conn = open_in_memory().unwrap();
        let mut row = mk_result("run-dup", None);
        insert_result(&conn, &row).unwrap();

        // 같은 run_id 로 status 변경 → INSERT OR REPLACE
        row.status = "FAIL".to_string();
        insert_result(&conn, &row).expect("중복 run_id upsert 실패");

        let status: String = conn
            .query_row("SELECT status FROM tc_results WHERE run_id='run-dup'", [], |r| r.get(0))
            .unwrap();
        assert_eq!(status, "FAIL");
    }

    // ── 파일·로그 ─────────────────────────────────────────────────────────────

    #[test]
    fn test_insert_result_files() {
        let conn = open_in_memory().unwrap();
        insert_result(&conn, &mk_result("run-f01", None)).unwrap();

        let files = vec![
            ResultFile { run_id: "run-f01".into(), file_type: "audio".into(), label: "iOS".into(),     path: "/a/ios.wav".into() },
            ResultFile { run_id: "run-f01".into(), file_type: "audio".into(), label: "Android".into(), path: "/a/and.wav".into() },
        ];
        insert_result_files(&conn, &files).expect("파일 삽입 실패");

        let count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM result_files WHERE run_id='run-f01'", [], |r| r.get(0),
        ).unwrap();
        assert_eq!(count, 2);
    }

    #[test]
    fn test_insert_result_logs() {
        let conn = open_in_memory().unwrap();
        insert_result(&conn, &mk_result("run-l01", None)).unwrap();

        let logs = vec!["[10:00] 시작".to_string(), "[10:01] PASS".to_string()];
        insert_result_logs(&conn, "run-l01", &logs).expect("로그 삽입 실패");

        let saved = query_result_logs(&conn, "run-l01").unwrap();
        assert_eq!(saved, logs);
    }

    // ── 전체 플로우 ───────────────────────────────────────────────────────────

    #[test]
    fn test_full_flow() {
        let conn = open_in_memory().unwrap();

        // 1) 세션 선행 저장 (finishedAt=None)
        let sess = mk_session("sess-full");
        upsert_session(&conn, &sess).expect("세션 선행 저장 실패");

        // 2) 결과 저장
        let result = mk_result("run-full-01", Some("sess-full"));
        insert_result(&conn, &result).expect("결과 저장 실패");

        // 3) 파일 + 로그
        insert_result_files(&conn, &[
            ResultFile { run_id: "run-full-01".into(), file_type: "audio".into(), label: "iOS".into(), path: "/ios.wav".into() },
        ]).unwrap();
        insert_result_logs(&conn, "run-full-01", &["[ts] ✅ PASS".to_string()]).unwrap();

        // 4) 세션 완료 업데이트
        let mut sess_done = sess.clone();
        sess_done.finished_at = Some("2026-04-09T10:10:00".to_string());
        upsert_session(&conn, &sess_done).expect("세션 완료 upsert 실패");

        // 검증
        let results = query_results(&conn, 10).unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].status, "PASS");

        let files = query_result_files(&conn, "run-full-01").unwrap();
        assert_eq!(files.len(), 1);

        let logs = query_result_logs(&conn, "run-full-01").unwrap();
        assert_eq!(logs.len(), 1);
    }
}
