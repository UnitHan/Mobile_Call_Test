#!/usr/bin/env python3
"""
DB 실시간 모니터링 스크립트
- SQLite DB를 2초마다 폴링하여 신규 tc_results 레코드를 감지
- TC_01 최종 결과(PASS/FAIL/ERROR)가 쓰이면 적재 여부를 판정하고 종료
- 타임아웃(기본 30분) 초과 시 자동 종료

사용법:
  python3 monitor_db.py
  python3 monitor_db.py --timeout 20        # 20분 타임아웃
  python3 monitor_db.py --tc TC_02          # 다른 TC 모니터링
"""
import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime

# ── 설정 ─────────────────────────────────────────────────────────────────────
DB_PATH  = os.path.expanduser(
    "~/Library/Application Support/com.qabulls.call/ixio_results.db"
)
POLL_SEC = 2          # 폴링 간격 (초)
FINAL    = {"PASS", "FAIL", "ERROR"}

# ── 색상 ─────────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def clr(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"

# ── DB 헬퍼 ──────────────────────────────────────────────────────────────────
def open_db() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        print(clr(RED, f"[ERROR] DB 파일을 찾을 수 없습니다:\n  {DB_PATH}"))
        print(clr(YELLOW, "앱(ixi-O)이 실행 중인지 확인하세요."))
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM tc_results").fetchone()[0]


def get_new_rows(conn: sqlite3.Connection, since_run_ids: set) -> list:
    """since_run_ids에 없는 신규 행 반환"""
    rows = conn.execute(
        "SELECT run_id, session_id, tc_id, repeat_index, status, "
        "       started_at, finished_at, duration_ms, "
        "       ios_visqol_mos, android_visqol_mos, snr_db, "
        "       dropout_count, dropout_severity, error_msg "
        "FROM tc_results ORDER BY started_at"
    ).fetchall()
    return [r for r in rows if r["run_id"] not in since_run_ids]


# ── 출력 헬퍼 ────────────────────────────────────────────────────────────────
def fmt_row(row: sqlite3.Row) -> str:
    status = row["status"]
    color  = GREEN if status == "PASS" else RED if status in ("FAIL","ERROR") else YELLOW

    repeat = f"#{row['repeat_index']}회차" if row["repeat_index"] is not None else "단독"
    dur    = f"{row['duration_ms']/1000:.1f}s" if row["duration_ms"] else "—"
    ios    = f"{row['ios_visqol_mos']:.3f}" if row["ios_visqol_mos"] else "—"
    aod    = f"{row['android_visqol_mos']:.3f}" if row["android_visqol_mos"] else "—"
    drop   = str(row["dropout_count"]) if row["dropout_count"] is not None else "—"
    sev    = row["dropout_severity"] or "—"
    err    = f"  ❗ {row['error_msg']}" if row["error_msg"] else ""

    return (
        f"  {clr(color, f'[{status}]')}"
        f"  {row['tc_id']} {repeat}"
        f"  ⏱ {dur}"
        f"  MOS iOS={ios} AOS={aod}"
        f"  탈락={drop}({sev})"
        f"{err}"
    )


def check_log_lines(conn: sqlite3.Connection, run_id: str) -> list:
    rows = conn.execute(
        "SELECT line FROM result_logs WHERE run_id = ? ORDER BY id",
        (run_id,)
    ).fetchall()
    return [r["line"] for r in rows]


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="ixi-O DB 실시간 모니터")
    parser.add_argument("--timeout", type=int, default=30, help="타임아웃 (분, 기본 30)")
    parser.add_argument("--tc",      type=str, default="TC_01", help="모니터링할 TC ID (기본 TC_01)")
    args = parser.parse_args()

    target_tc   = args.tc
    timeout_sec = args.timeout * 60
    deadline    = time.time() + timeout_sec

    print()
    print(clr(BOLD, "=" * 60))
    print(clr(BOLD, f"  ixi-O DB 실시간 모니터  —  대상: {target_tc}"))
    print(clr(BOLD, "=" * 60))
    print(f"  DB 경로: {DB_PATH}")
    print(f"  폴링 간격: {POLL_SEC}초  |  타임아웃: {args.timeout}분")
    print()

    conn = open_db()

    # ── 기존 건수 스냅샷 ──────────────────────────────────────────────────────
    prior_count   = get_count(conn)
    prior_run_ids = {r["run_id"] for r in conn.execute("SELECT run_id FROM tc_results")}

    print(clr(CYAN, f"[초기 상태] tc_results 기존 건수: {prior_count}건"))
    if prior_count == 0:
        print(clr(YELLOW,
            "  ⚠  DB가 비어 있습니다.\n"
            "  → 앱(ixi-O)을 재시작하면 localStorage 데이터(207건)가 소급 적재됩니다.\n"
            "  → 소급 적재 완료 후 이 스크립트가 새로운 신규 건을 탐지합니다."
        ))
    print()
    print(clr(CYAN, f"[대기 중] {target_tc} 테스트를 시작해주세요 ..."))
    print()

    detected_run_id  = None  # 최종 상태를 받은 run_id
    seen_run_ids     = set(prior_run_ids)
    last_partial_ids = set()   # RUNNING 상태로 중간 감지된 run_id

    try:
        while time.time() < deadline:
            time.sleep(POLL_SEC)

            try:
                new_rows = get_new_rows(conn, seen_run_ids)
            except Exception as e:
                print(clr(RED, f"[DB 읽기 오류] {e}"))
                continue

            # ── 소급 적재 감지 ────────────────────────────────────────────────
            if new_rows:
                tc_rows   = [r for r in new_rows if r["tc_id"] == target_tc]
                other_cnt = len([r for r in new_rows if r["tc_id"] != target_tc])

                if other_cnt > 0:
                    now = datetime.now().strftime("%H:%M:%S")
                    # 소급 적재(다른 TC 포함 대량)인지 신규 단건인지 구분
                    if other_cnt >= 5:
                        print(clr(CYAN, f"[{now}] 📥 소급 적재 감지: 신규 {len(new_rows)}건 (기타 TC {other_cnt}건 포함)"))
                    else:
                        print(clr(CYAN, f"[{now}] 신규 레코드 {other_cnt}건 감지 ({target_tc} 外)"))

                for row in new_rows:
                    seen_run_ids.add(row["run_id"])

                # ── target TC 행 처리 ─────────────────────────────────────────
                for row in tc_rows:
                    now = datetime.now().strftime("%H:%M:%S")
                    run_id = row["run_id"]
                    status = row["status"]
                    repeat = row["repeat_index"]
                    label  = f"#{repeat}회차" if repeat is not None else "단독"

                    if status in FINAL:
                        # ── 최종 결과 감지 ────────────────────────────────────
                        print()
                        print(clr(BOLD, "─" * 60))
                        print(clr(BOLD, f"[{now}] 🎯 {target_tc} {label} 최종 결과 감지!"))
                        print(fmt_row(row))

                        # 로그 라인 확인
                        logs = check_log_lines(conn, run_id)
                        db_ok_logs   = [l for l in logs if "✅ DB 적재 완료" in l]
                        db_fail_logs = [l for l in logs if "❌ DB 적재 실패" in l]

                        print()
                        if db_ok_logs:
                            print(clr(GREEN, "  ✅ DB 적재 완료 로그 확인:"))
                            for l in db_ok_logs:
                                print(f"     {l}")
                        elif db_fail_logs:
                            print(clr(RED, "  ❌ DB 적재 실패 로그 감지:"))
                            for l in db_fail_logs:
                                print(f"     {l}")
                        else:
                            # DB에 행은 있지만 로그 라인에 적재 메시지가 없는 경우
                            # → 소급 적재됐거나 이전 버전 빌드
                            print(clr(YELLOW,
                                "  ⚠  logLines에 DB 적재 로그가 없습니다.\n"
                                "     (구버전 빌드이거나 소급 적재된 데이터일 수 있습니다.)"
                            ))

                        # ── 최종 판정 ─────────────────────────────────────────
                        now_count = get_count(conn)
                        print()
                        print(clr(BOLD, "─" * 60))
                        if status in ("PASS", "FAIL"):
                            print(clr(GREEN, f"  ✅ DB 적재 정상: {target_tc} {label} → {status}"))
                        else:  # ERROR
                            err = row["error_msg"] or "알 수 없는 오류"
                            print(clr(RED,    f"  ❌ 테스트 ERROR: {err}"))
                            print(clr(YELLOW,  "  (ERROR 상태도 DB에는 정상 적재됨)"))

                        print(f"  tc_results 총 건수: {now_count}건")
                        print(clr(BOLD, "─" * 60))
                        print()
                        detected_run_id = run_id
                        return  # 정상 종료

                    else:
                        # RUNNING / QUEUED 등 중간 상태
                        if run_id not in last_partial_ids:
                            last_partial_ids.add(run_id)
                            print(clr(YELLOW, f"[{now}] ⏳ {target_tc} {label} 진행 중 (status={status}) — run_id={run_id[:16]}..."))

            else:
                # 변경 없음 — 진행 표시
                elapsed = int(time.time() - (deadline - timeout_sec))
                mins, secs = divmod(elapsed, 60)
                sys.stdout.write(
                    f"\r  [{mins:02d}:{secs:02d}] DB 변경 대기 중 ... "
                    f"(현재 {len(seen_run_ids)}건)    "
                )
                sys.stdout.flush()

    except KeyboardInterrupt:
        print()
        print(clr(YELLOW, "\n[중단] Ctrl+C로 종료됨"))
        now_count = get_count(conn)
        print(f"  최종 tc_results 건수: {now_count}건")
        return

    # 타임아웃
    print()
    print(clr(RED, f"\n[TIMEOUT] {args.timeout}분 내에 {target_tc} 결과가 감지되지 않았습니다."))
    print("원인 체크:")
    now_count = get_count(conn)
    print(f"  - 현재 DB 건수: {now_count}건")
    if now_count == 0:
        print(clr(YELLOW,
            "  1. 앱(ixi-O)이 실행 중이 아닌 것 같습니다.\n"
            "  2. 또는 앱 재시작 전에 이 스크립트를 먼저 껐을 수 있습니다.\n"
            "  3. 앱 콘솔에서 '[db] 소급 적재 완료' 로그를 확인하세요."
        ))
    else:
        print(clr(YELLOW,
            f"  DB에 {now_count}건은 있지만 금번 {target_tc} 실행 결과가 없습니다.\n"
            "  앱 콘솔에서 '[db] 결과 저장 실패' 경고를 확인하세요."
        ))


if __name__ == "__main__":
    main()
