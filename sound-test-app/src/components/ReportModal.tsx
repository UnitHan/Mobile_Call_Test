/**
 * ReportModal — 종합 테스트 보고서 모달
 * - 상단: TC별 종합 집계 표 (PASS/FAIL/ERROR 수, 평균 MOS, 평균 음단절)
 * - 하단 탭: 각 개별 실행 결과 상세
 * - 엑셀 내보내기 (.xlsx)
 */
import { useState } from "react";
import * as XLSX from "xlsx";
import type { TcResult, TcSession, DropoutSeverity } from "../types";
import { invoke } from "@tauri-apps/api/core";
import { useT } from "../i18n";

// ── 유틸 ──────────────────────────────────────────────────────────────────────

function fmtTime(iso: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ko-KR", {
    month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function fmtDur(ms: number) {
  if (!ms) return "—";
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${((ms % 60000) / 1000).toFixed(0)}s`;
}

function avg(vals: (number | null)[]): number | null {
  const nums = vals.filter((v): v is number => v != null);
  return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
}

function fmt2(v: number | null) {
  return v != null ? v.toFixed(2) : "—";
}

function mosGrade(mos: number | null, t: (k: string) => string): string {
  if (mos == null) return "";
  if (mos >= 4.0) return t("dash.mosGrade.great");
  if (mos >= 3.5) return t("dash.mosGrade.good");
  if (mos >= 3.0) return t("dash.mosGrade.mid");
  if (mos >= 2.5) return t("dash.mosGrade.poor");
  return t("dash.mosGrade.veryPoor");
}

function mosCls(v: number | null) {
  if (v == null) return "";
  if (v >= 4.0) return "mos-good";
  if (v >= 3.0) return "mos-ok";
  if (v >= 2.5) return "mos-warn";
  return "mos-bad";
}

function dropCls(s: DropoutSeverity | null) {
  if (!s) return "";
  return { "없음": "severity-none", "경미": "severity-low", "보통": "severity-mid", "심각": "severity-high" }[s] ?? "";
}

async function openReport(path: string) {
  try { await invoke("open_report", { path }); }
  catch { window.open(`file://${path}`, "_blank"); }
}

// ── 종합 집계 계산 ─────────────────────────────────────────────────────────────

const TC_LABELS: Record<string, string> = {
  TC_01: "TC_01 통화품질 (발신)",
  TC_02: "TC_02 통화품질 (수신)",
  TC_03: "TC_03 MOS 측정",
  TC_04: "TC_04 음단절",
  // TC_05: "TC_05 종합",  // TODO: 추후 활성화
};

interface TcSummaryRow {
  tcId: string;
  total: number;
  pass: number;
  fail: number;
  error: number;
  passRate: string;
  avgIosMos: number | null;
  avgAosMos: number | null;
  totalDropout: number | null;
  maxDropout: number | null;
}

function buildSummary(results: TcResult[]): TcSummaryRow[] {
  const map = new Map<string, TcResult[]>();
  for (const r of results) {
    if (!map.has(r.tcId)) map.set(r.tcId, []);
    map.get(r.tcId)!.push(r);
  }
  const rows: TcSummaryRow[] = [];
  for (const [tcId, rr] of map.entries()) {
    const pass   = rr.filter((r) => r.status === "PASS").length;
    const fail   = rr.filter((r) => r.status === "FAIL").length;
    const error  = rr.filter((r) => r.status === "ERROR").length;
    const done   = rr.filter((r) => r.status !== "RUNNING" && r.status !== "QUEUED");
    rows.push({
      tcId,
      total: rr.length,
      pass, fail, error,
      passRate: done.length > 0 ? `${Math.round((pass / done.length) * 100)}%` : "—",
      avgIosMos: avg(rr.map((r) => r.iosVisqolMos)),
      avgAosMos: avg(rr.map((r) => r.androidVisqolMos)),
      totalDropout: rr.reduce<number | null>((s, r) => r.dropoutCount == null ? s : (s ?? 0) + r.dropoutCount, null),
      maxDropout: rr.reduce<number | null>((mx, r) => {
        if (r.dropoutCount == null) return mx;
        return mx == null ? r.dropoutCount : Math.max(mx, r.dropoutCount);
      }, null),
    });
  }
  return rows.sort((a, b) => a.tcId.localeCompare(b.tcId));
}

// ── 엑셀 내보내기 ─────────────────────────────────────────────────────────────

function exportXlsx(results: TcResult[], sessions: TcSession[], t: (k: string, v?: Record<string, string | number>) => string) {
  const wb = XLSX.utils.book_new();

  // ── 시트1: 종합 요약 ─────────────────────────────────────────────────────
  const summary = buildSummary(results);
  const sumRows = [
    ["TC ID", "TC 설명", "전체", "PASS", "FAIL", "ERROR", "통과율",
      "평균 MOS(iOS)", "평균 MOS(AOS)", "전체 음단절", "최대 음단절"],
    ...summary.map((r) => [
      r.tcId, TC_LABELS[r.tcId] ?? r.tcId,
      r.total, r.pass, r.fail, r.error, r.passRate,
      r.avgIosMos != null ? +r.avgIosMos.toFixed(2) : "",
      r.avgAosMos != null ? +r.avgAosMos.toFixed(2) : "",
      r.totalDropout ?? "",
      r.maxDropout ?? "",
    ]),
  ];
  const wsSum = XLSX.utils.aoa_to_sheet(sumRows);
  wsSum["!cols"] = [10, 28, 6, 6, 6, 6, 8, 14, 14, 12, 12].map((w) => ({ wch: w }));
  XLSX.utils.book_append_sheet(wb, wsSum, "종합 요약");

  // ── 세션별 시트 ──────────────────────────────────────────────────────────
  const sessionHeader = [
    "#", "회차", "TC ID", "실행시각", "상태", "소요(s)",
    "MOS(iOS)", "MOS(AOS)", "음단절 건수", "음단절 정도",
    "iOS 녹음", "Android 녹음", "보고서 경로", "오류",
  ];

  const printSession = (label: string, rows: TcResult[]) => {
    const data = [
      sessionHeader,
      ...rows.map((r, i) => [
        i + 1,
        r.repeatIndex ?? "",
        r.tcId,
        fmtTime(r.startedAt),
        r.status,
        r.durationMs > 0 ? +(r.durationMs / 1000).toFixed(1) : "",
        r.iosVisqolMos != null ? +r.iosVisqolMos.toFixed(3) : "",
        r.androidVisqolMos != null ? +r.androidVisqolMos.toFixed(3) : "",
        r.dropoutCount ?? "",
        r.dropoutSeverity ?? "",
        r.extractedAudioPaths.find((a) => a.label.includes("iOS"))?.path ?? "",
        r.extractedAudioPaths.find((a) => a.label.includes("Android"))?.path ?? "",
        r.dropoutReportPath ?? "",
        r.errorMsg ?? "",
      ]),
    ];
    const ws = XLSX.utils.aoa_to_sheet(data);
    ws["!cols"] = [4, 4, 8, 18, 8, 8, 10, 10, 10, 8, 40, 40, 40, 30].map((w) => ({ wch: w }));
    // 시트 이름은 31자 제한, 특수문자 제거
    const sheetName = label.replace(/[\\/:?*[\]]/g, "_").slice(0, 31);
    XLSX.utils.book_append_sheet(wb, ws, sheetName);
  };

  // 세션별로 시트 분리
  if (sessions.length > 0) {
    const usedRunIds = new Set<string>();
    for (const s of sessions) {
      const rows = results.filter((r) => r.sessionId === s.sessionId);
      rows.forEach((r) => usedRunIds.add(r.runId));
      const label = s.repeatOptions
        ? `반복_${s.tcIds.join("-")}_${new Date(s.startedAt).toLocaleDateString("ko-KR").replace(/\. /g, "_").replace(".", "")}`
        : `세션_${s.tcIds.join("-")}_${new Date(s.startedAt).toLocaleDateString("ko-KR").replace(/\. /g, "_").replace(".", "")}`;
      if (rows.length > 0) printSession(label.slice(0, 31), rows);
    }
    const orphans = results.filter((r) => !usedRunIds.has(r.runId));
    if (orphans.length > 0) printSession("기타", orphans);
  } else {
    printSession("전체 결과", results);
  }

  // ── 다운로드 ─────────────────────────────────────────────────────────────
  const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
  const filename = `tc_report_${ts}.xlsx`;
  try {
    const wbout = XLSX.write(wb, { bookType: "xlsx", type: "array" });
    const b64 = btoa(String.fromCharCode(...new Uint8Array(wbout)));
    invoke("save_xlsx", { dataB64: b64, defaultName: filename })
      .then((path) => alert(t("report.xlsxSaveDone", { path: String(path) })))
      .catch((e) => {
        console.error("save_xlsx failed, trying browser fallback:", e);
        // 브라우저 폴백
        XLSX.writeFile(wb, filename);
      });
  } catch (e) {
    console.error("XLSX write error:", e);
    XLSX.writeFile(wb, filename);
  }
}

// ── DB 내보내기 타입 ─────────────────────────────────────────────────────────────

interface DbResultSummary {
  runId: string; sessionId: string; repeatIndex: number | null; tcId: string;
  startedAt: string; finishedAt: string | null; durationMs: number; status: string;
  iosVisqolMos: number | null; androidVisqolMos: number | null; snrDb: number | null;
  dropoutCount: number | null; dropoutSeverity: string | null;
  dropoutReportPath: string | null; mosReportPath: string | null;
  vishingDetected: boolean | null; errorMsg: string | null;
}

interface DbTcStats {
  tcId: string; total: number; pass: number; fail: number; error: number;
  passRate: number; avgDurationMs: number;
  avgIosMos: number | null; avgAndroidMos: number | null; avgDropoutCount: number | null;
}

interface DbDailyMos {
  date: string; tcId: string;
  avgIosMos: number | null; avgAndroidMos: number | null; runCount: number;
}

interface DbSeverityStats { tcId: string; severity: string; count: number; }

interface DbExportData {
  results: DbResultSummary[];
  tcStats: DbTcStats[];
  dailyMos: DbDailyMos[];
  severityStats: DbSeverityStats[];
  fromDate: string | null; toDate: string | null;
  totalCount: number;
}

// ── DB 엑셀 내보내기 ──────────────────────────────────────────────────────────

async function exportXlsxFromDb(fromDate: string | undefined, toDate: string | undefined, t: (k: string, v?: Record<string, string | number>) => string) {
  let data: DbExportData;
  try {
    data = await invoke<DbExportData>("db_export_stats", {
      fromDate: fromDate ?? null,
      toDate:   toDate   ?? null,
      limit:    null,
    });
  } catch (e) {
    alert(t("report.xlsxDbFail", { err: String(e) }));
    return;
  }

  if (data.totalCount === 0) {
    alert(t("report.xlsxDbEmpty"));
    return;
  }

  const wb = XLSX.utils.book_new();

  // ── 시트1: 결과 전체 목록 ─────────────────────────────────────────────────
  const resHeader = [
    "run_id", "session_id", "회차", "TC ID", "실행시각", "종료시각", "소요(ms)",
    "상태", "MOS(iOS)", "MOS(AOS)", "SNR(dB)", "음단절 건수", "음단절 정도",
    "vishing 감지", "오류",
  ];
  const resRows  = [
    resHeader,
    ...data.results.map((r) => [
      r.runId, r.sessionId, r.repeatIndex ?? "", r.tcId,
      r.startedAt, r.finishedAt ?? "",
      r.durationMs,
      r.status,
      r.iosVisqolMos    != null ? +r.iosVisqolMos.toFixed(3)    : "",
      r.androidVisqolMos != null ? +r.androidVisqolMos.toFixed(3) : "",
      r.snrDb           != null ? +r.snrDb.toFixed(1)          : "",
      r.dropoutCount    ?? "",
      r.dropoutSeverity ?? "",
      r.vishingDetected != null ? (r.vishingDetected ? "Y" : "N") : "",
      r.errorMsg ?? "",
    ]),
  ];
  const wsRes = XLSX.utils.aoa_to_sheet(resRows);
  wsRes["!cols"] = [36, 36, 4, 8, 20, 20, 8, 8, 10, 10, 8, 10, 8, 8, 30].map((w) => ({ wch: w }));
  XLSX.utils.book_append_sheet(wb, wsRes, "결과 전체");

  // ── 시트2: TC별 통계 ──────────────────────────────────────────────────────
  const statsHeader = [
    "TC ID", "전체", "PASS", "FAIL", "ERROR", "통과율(%)",
    "평균 소요(s)", "평균 MOS(iOS)", "평균 MOS(AOS)", "평균 음단절",
  ];
  const statsRows = [
    statsHeader,
    ...data.tcStats.map((s) => [
      s.tcId, s.total, s.pass, s.fail, s.error,
      +s.passRate.toFixed(1),
      +(s.avgDurationMs / 1000).toFixed(1),
      s.avgIosMos       != null ? +s.avgIosMos.toFixed(3)       : "",
      s.avgAndroidMos   != null ? +s.avgAndroidMos.toFixed(3)   : "",
      s.avgDropoutCount != null ? +s.avgDropoutCount.toFixed(1) : "",
    ]),
  ];
  const wsStats = XLSX.utils.aoa_to_sheet(statsRows);
  wsStats["!cols"] = [10, 6, 6, 6, 6, 10, 10, 14, 14, 12].map((w) => ({ wch: w }));
  XLSX.utils.book_append_sheet(wb, wsStats, "TC별 통계");

  // ── 시트3: 날짜별 MOS 추이 ───────────────────────────────────────────────
  const mosHeader = ["날짜", "TC ID", "평균 MOS(iOS)", "평균 MOS(AOS)", "실행 수"];
  const mosRows = [
    mosHeader,
    ...data.dailyMos.map((d) => [
      d.date, d.tcId,
      d.avgIosMos     != null ? +d.avgIosMos.toFixed(3)     : "",
      d.avgAndroidMos != null ? +d.avgAndroidMos.toFixed(3) : "",
      d.runCount,
    ]),
  ];
  const wsMos = XLSX.utils.aoa_to_sheet(mosRows);
  wsMos["!cols"] = [12, 10, 14, 14, 8].map((w) => ({ wch: w }));
  XLSX.utils.book_append_sheet(wb, wsMos, "날짜별 MOS 추이");

  // ── 시트4: Severity 분포 ──────────────────────────────────────────────────
  const sevHeader = ["TC ID", "음단절 정도", "건수"];
  const sevRows = [
    sevHeader,
    ...data.severityStats.map((s) => [s.tcId, s.severity, s.count]),
  ];
  const wsSev = XLSX.utils.aoa_to_sheet(sevRows);
  wsSev["!cols"] = [10, 12, 8].map((w) => ({ wch: w }));
  XLSX.utils.book_append_sheet(wb, wsSev, "Severity 분포");

  // ── 저장 ─────────────────────────────────────────────────────────────────
  const period = fromDate && toDate ? `${fromDate}_${toDate}`
               : fromDate           ? `${fromDate}_이후`
               : toDate             ? `~${toDate}`
               : "전체";
  const ts = new Date().toISOString().slice(0, 10);
  const filename = `tc_db_stats_${period}_${ts}.xlsx`;
  try {
    const wbout = XLSX.write(wb, { bookType: "xlsx", type: "array" });
    const b64 = btoa(String.fromCharCode(...new Uint8Array(wbout)));
    invoke("save_xlsx", { dataB64: b64, defaultName: filename })
      .then((path) => alert(t("report.xlsxDbSaveDone", { count: data.totalCount, path: String(path) })))
      .catch((e) => { console.error("save_xlsx 실패:", e); XLSX.writeFile(wb, filename); });
  } catch (e) {
    console.error("XLSX write error:", e);
    XLSX.writeFile(wb, filename);
  }
}

// ── 세션 요약 카드 ───────────────────────────────────────────────────────────────

function SessionStatsCard({ label, session, rows }: {
  label: string;
  session: TcSession | null;
  rows: TcResult[];
}) {
  const { t } = useT();
  if (rows.length === 0) return null;
  const done = rows.filter((r) => r.status !== "RUNNING" && r.status !== "QUEUED");
  const pass  = rows.filter((r) => r.status === "PASS").length;
  const fail  = rows.filter((r) => r.status === "FAIL").length;
  const error = rows.filter((r) => r.status === "ERROR").length;
  const passRateNum = done.length > 0 ? Math.round((pass / done.length) * 100) : null;
  const passRateStr = passRateNum != null ? `${passRateNum}%` : "—";
  const avgIosMos  = avg(rows.map((r) => r.iosVisqolMos));
  const avgAosMos  = avg(rows.map((r) => r.androidVisqolMos));
  const totalDropout = rows.reduce<number | null>((s, r) => r.dropoutCount == null ? s : (s ?? 0) + r.dropoutCount, null);
  const maxDropout = rows.reduce<number | null>((mx, r) => {
    if (r.dropoutCount == null) return mx;
    return mx == null ? r.dropoutCount : Math.max(mx, r.dropoutCount);
  }, null);
  const perTc = buildSummary(rows);
  const multiTc = perTc.length > 1;

  return (
    <div className="session-stats-card">
      <div className="session-stats-header">
        <span className="session-stats-title">{label}</span>
        {session && (
          <span className="session-stats-meta">
            {fmtTime(session.startedAt)}
            {session.finishedAt && ` — ${fmtTime(session.finishedAt)}`}
          </span>
        )}
      </div>
      <div className="session-stats-row">
        <div className="stat-box">
          <span className="stat-box-label">{t("dash.stat.total")}</span>
          <span className="stat-box-value">{rows.length}{t("report.runUnit")}</span>
        </div>
        <div className="stat-box">
          <span className="stat-box-label">PASS</span>
          <span className="stat-box-value td-pass">{pass}</span>
        </div>
        <div className="stat-box">
          <span className="stat-box-label">FAIL</span>
          <span className={`stat-box-value ${fail > 0 ? "td-fail" : ""}`}>{fail}</span>
        </div>
        {error > 0 && (
          <div className="stat-box">
            <span className="stat-box-label">ERROR</span>
            <span className="stat-box-value td-error">{error}</span>
          </div>
        )}
        <div className="stat-box stat-box-highlight">
          <span className="stat-box-label">{t("dash.stat.passRate")}</span>
          <span className={`stat-box-value ${passRateNum != null && passRateNum >= 80 ? "td-pass" : "td-fail"}`}>
            {passRateStr}
          </span>
        </div>
        <div className="stat-box-divider" />
        <div className="stat-box">
          <span className="stat-box-label">{t("dash.stat.avgIosMos")}</span>
          <span className={`stat-box-value ${mosCls(avgIosMos)}`}>{fmt2(avgIosMos)}</span>
        </div>
        <div className="stat-box">
          <span className="stat-box-label">{t("dash.stat.avgAosMos")}</span>
          <span className={`stat-box-value ${mosCls(avgAosMos)}`}>{fmt2(avgAosMos)}</span>
        </div>
        <div className="stat-box">
          <span className="stat-box-label">{t("dash.stat.avgDropout")}</span>
          <span className="stat-box-value">
            {totalDropout != null ? `${totalDropout}${t("dash.dropoutUnit")}` : "—"}
          </span>
        </div>
        <div className="stat-box">
          <span className="stat-box-label">{t("dash.stat.maxDropout")}</span>
          <span className={`stat-box-value ${maxDropout != null && maxDropout > 0 ? "td-fail" : ""}`}>
            {maxDropout != null ? `${maxDropout}${t("dash.dropoutUnit")}` : "—"}
          </span>
        </div>
      </div>
      {multiTc && (
        <div className="session-stats-tc-row">
          {perTc.map((row) => (
            <div key={row.tcId} className="tc-mini-stat">
              <span className="tc-id-badge">{row.tcId}</span>
              <span>{row.total}{t("report.runUnit")}</span>
              <span className={parseInt(row.passRate) >= 80 ? "td-pass" : "td-fail"}>{row.passRate}</span>
              <span className={mosCls(row.avgIosMos)}>iOS {fmt2(row.avgIosMos)}</span>
              <span className={mosCls(row.avgAosMos)}>AOS {fmt2(row.avgAosMos)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  results: TcResult[];
  sessions: TcSession[];
  onClose: () => void;
}

// ── 컴포넌트 ──────────────────────────────────────────────────────────────────

export function ReportModal({ results, sessions, onClose }: Props) {
  const { t } = useT();
  const summary = buildSummary(results);

  // 개별 시트 탭: 세션별 또는 단일 목록
  type SheetItem = { label: string; rows: TcResult[]; session: TcSession | null };
  const sheets: SheetItem[] = [];
  if (sessions.length > 0) {
    const usedRunIds = new Set<string>();
    for (const s of [...sessions].reverse()) {
      const rows = results.filter((r) => r.sessionId === s.sessionId);
      rows.forEach((r) => usedRunIds.add(r.runId));
      if (rows.length === 0) continue;
      const label = s.repeatOptions
        ? `🔁 ${s.tcIds.join(",")} ×${s.repeatOptions.count}`
        : `▶ ${s.tcIds.join(",")}`;
      sheets.push({ label, rows, session: s });
    }
    const orphans = results.filter((r) => !usedRunIds.has(r.runId));
    if (orphans.length > 0) sheets.push({ label: "기타", rows: orphans, session: null });
  } else {
    sheets.push({ label: "전체", rows: [...results].reverse(), session: null });
  }

  const [activeSheet, setActiveSheet] = useState(0);
  const [activeResultIdx, setActiveResultIdx] = useState<number | null>(null);
  const [dbFrom, setDbFrom] = useState("");
  const [dbTo,   setDbTo]   = useState("");
  const [dbExporting, setDbExporting] = useState(false);

  const currentSheet = sheets[activeSheet];

  async function handleDbExport() {
    setDbExporting(true);
    try {
      await exportXlsxFromDb(dbFrom || undefined, dbTo || undefined, t);
    } finally {
      setDbExporting(false);
    }
  }

  return (
    <div className="modal-overlay report-overlay" onClick={onClose}>
      <div className="report-modal" onClick={(e) => e.stopPropagation()}>

        {/* 헤더 */}
        <div className="report-header">
          <span className="report-title">{t("report.title")}</span>
          <div className="report-header-actions">
            <button
              className="btn-xs btn-accent"
              onClick={() => exportXlsx(results, sessions, t)}
              title="현재 세션 데이터 엑셀 내보내기"
            >
              {t("report.excelCurrent")}
            </button>
            <span className="db-export-group">
              <input
                type="date"
                className="db-date-input"
                value={dbFrom}
                onChange={(e) => setDbFrom(e.target.value)}
                title="조회 시작일 (비우면 전체)"
              />
              <span className="db-date-sep">~</span>
              <input
                type="date"
                className="db-date-input"
                value={dbTo}
                onChange={(e) => setDbTo(e.target.value)}
                title="조회 종료일 (비우면 전체)"
              />
              <button
                className="btn-xs btn-primary"
                onClick={handleDbExport}
                disabled={dbExporting}
                title="DB에 저장된 전체 기간 통계 엑셀 내보내기 (4개 시트)"
              >
                {dbExporting ? t("report.dbExporting") : t("report.excelDb")}
              </button>
            </span>
            <button className="btn-xs btn-ghost" onClick={onClose}>✕</button>
          </div>
        </div>

        <div className="report-body">

          {/* ── 종합 요약 표 ── */}
          <div className="report-section">
            <div className="report-section-title">{t("report.tcSummaryTitle")}</div>
            <div className="report-summary-wrap">
              <table className="report-summary-table">
                <thead>
                  <tr>
                    <th>TC ID</th>
                    <th>{t("dash.stat.total")}</th>
                    <th>PASS</th>
                    <th>FAIL</th>
                    <th>ERROR</th>
                    <th>{t("dash.stat.passRate")}</th>
                    <th>{t("dash.stat.avgIosMos")}</th>
                    <th>{t("dash.stat.avgAosMos")}</th>
                    <th>{t("dash.stat.avgDropout")}</th>
                    <th>{t("dash.stat.maxDropout")}</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.map((row) => (
                    <tr key={row.tcId}>
                      <td><span className="tc-id-badge">{row.tcId}</span></td>
                      <td className="td-num">{row.total}</td>
                      <td className="td-pass">{row.pass}</td>
                      <td className="td-fail">{row.fail}</td>
                      <td className="td-error">{row.error}</td>
                      <td className={`td-rate ${parseInt(row.passRate) >= 80 ? "td-pass" : "td-fail"}`}>
                        {row.passRate}
                      </td>
                      <td className={`td-mos ${mosCls(row.avgIosMos)}`}>
                        {fmt2(row.avgIosMos)}
                        {row.avgIosMos != null && <span className="mos-grade"> {mosGrade(row.avgIosMos, t)}</span>}
                      </td>
                      <td className={`td-mos ${mosCls(row.avgAosMos)}`}>
                        {fmt2(row.avgAosMos)}
                        {row.avgAosMos != null && <span className="mos-grade"> {mosGrade(row.avgAosMos, t)}</span>}
                      </td>
                      <td className="td-dropout">
                        {row.totalDropout != null ? `${row.totalDropout}${t("dash.dropoutUnit")}` : "\u2014"}
                      </td>
                      <td className="td-dropout">
                        {row.maxDropout != null ? `${row.maxDropout}${t("dash.dropoutUnit")}` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* ── 세션/개별 시트 ── */}
          <div className="report-section report-detail-section">
            <div className="report-sheet-tabs">
              {sheets.map((s, i) => (
                <button
                  key={i}
                  className={`report-sheet-tab${i === activeSheet ? " active" : ""}`}
                  onClick={() => { setActiveSheet(i); setActiveResultIdx(null); }}
                >
                  {s.label}
                  <span className="sheet-count">{s.rows.length}</span>
                </button>
              ))}
            </div>

            {currentSheet && (
              <div className="report-sheet-content">
                <SessionStatsCard
                  label={currentSheet.label}
                  session={currentSheet.session}
                  rows={currentSheet.rows}
                />
                <table className="report-detail-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>{t("report.colRepeat")}</th>
                      <th>TC ID</th>
                      <th>{t("dash.col.startedAt")}</th>
                      <th>{t("dash.col.status")}</th>
                      <th>{t("report.colElapsed")}</th>
                      <th>{t("report.colMosIos")}</th>
                      <th>{t("report.colMosAos")}</th>
                      <th>{t("report.colDropout")}</th>
                      <th>{t("report.colAudio")}</th>
                      <th>{t("report.colReport")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentSheet.rows.map((r, i) => (
                      <>
                        <tr
                          key={r.runId}
                          className={`report-detail-row${activeResultIdx === i ? " row-expanded" : ""}`}
                          onClick={() => setActiveResultIdx(activeResultIdx === i ? null : i)}
                        >
                          <td className="td-num">{i + 1}</td>
                          <td className="td-repeat">{r.repeatIndex ?? "—"}</td>
                          <td><span className="tc-id-badge">{r.tcId}</span></td>
                          <td className="td-time">{fmtTime(r.startedAt)}</td>
                          <td>
                            <span className={`status-badge status-${r.status.toLowerCase()}`}>
                              {r.status}
                            </span>
                          </td>
                          <td className="td-dur">{fmtDur(r.durationMs)}</td>
                          <td className={`td-mos ${mosCls(r.iosVisqolMos)}`}>
                            {fmt2(r.iosVisqolMos)}
                          </td>
                          <td className={`td-mos ${mosCls(r.androidVisqolMos)}`}>
                            {fmt2(r.androidVisqolMos)}
                          </td>
                          <td className="td-dropout">
                            {r.dropoutCount != null ? `${r.dropoutCount}${t("dash.dropoutUnit")}` : "—"}
                            {r.dropoutSeverity && (
                              <span className={`severity-badge ${dropCls(r.dropoutSeverity)}`}> {r.dropoutSeverity}</span>
                            )}
                          </td>
                          <td>
                            {r.extractedAudioPaths.map((af, j) => (
                              <button
                                key={j}
                                className="btn-icon"
                                title={af.label}
                                onClick={(e) => { e.stopPropagation(); openReport(af.path); }}
                              >
                                🎵
                              </button>
                            ))}
                          </td>
                          <td>
                            {r.dropoutReportPath && (
                              <button
                                className="btn-icon"
                                title="분석 보고서 열기"
                                onClick={(e) => { e.stopPropagation(); openReport(r.dropoutReportPath!); }}
                              >
                                📊
                              </button>
                            )}
                            {r.mosReportPath && (
                              <button
                                className="btn-icon"
                                title="MOS 보고서 열기"
                                onClick={(e) => { e.stopPropagation(); openReport(r.mosReportPath!); }}
                              >
                                📈
                              </button>
                            )}
                          </td>
                        </tr>
                        {activeResultIdx === i && (
                          <tr key={`${r.runId}-detail`} className="report-expanded-row">
                            <td colSpan={11}>
                              <div className="report-expanded-body">
                                {r.extractedAudioPaths.length > 0 && (
                                  <div className="expanded-block">
                                    <span className="expanded-label">{t("report.expandedAudio")}</span>
                                    {r.extractedAudioPaths.map((af, j) => (
                                      <button
                                        key={j}
                                        className="btn-xs btn-ghost expanded-audio-btn"
                                        onClick={() => openReport(af.path)}
                                      >
                                        {af.label}: {af.path.split("/").pop()}
                                      </button>
                                    ))}
                                  </div>
                                )}
                                {r.dropoutReportPath && (
                                  <div className="expanded-block">
                                    <span className="expanded-label">{t("report.expandedReport")}</span>
                                    <button
                                      className="btn-xs btn-accent"
                                      onClick={() => openReport(r.dropoutReportPath!)}
                                    >
                                      {t("report.expandedReportBtn")}
                                    </button>
                                  </div>
                                )}
                                {r.errorMsg && (
                                  <div className="expanded-block">
                                    <span className="expanded-label">{t("report.expandedError")}</span>
                                    <span className="expanded-error">{r.errorMsg}</span>
                                  </div>
                                )}
                                {r.logLines.length > 0 && (
                                  <div className="expanded-block expanded-log">
                                    <span className="expanded-label">{t("report.expandedLog")}</span>
                                    <span className="expanded-log-text">{r.logLines.join(" | ")}</span>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}
