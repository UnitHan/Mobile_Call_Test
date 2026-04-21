import { useState, useRef, useCallback, useEffect } from "react";
import type { TcResult, TcStatus, TcSession, TcId, DropoutSeverity, TargetAppConfig } from "../types";
import { SUPPORTED_APPS, DEFAULT_APP_CONFIG, SUPPORTED_CARRIERS } from "../types";
import { invoke } from "@tauri-apps/api/core";
import { useT } from "../i18n";

// 시연용 고정 세션 ID (useTcRunner.ts 와 동기화)
const DEMO_SESSION_ID = "demo-dropout-benchmark-20260406";

function fmtTime(iso: string) {
  const d = new Date(iso);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mi}:${ss}`;
}

/** 세션 수준 전체 소요 시간 포맷 */
function fmtSessionDuration(startIso: string, endIso: string | null, t: (k: string, v?: Record<string, string | number>) => string): string {
  if (!endIso) return t("dash.session.inProgress");
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (ms <= 0) return t("duration.zero");
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  if (h === 0) return t("duration.minutes", { m });
  if (m === 0 && s === 0) return t("duration.hours", { h });
  if (m === 0) return t("duration.hoursSeconds", { h, s });
  return t("duration.hoursMinutes", { h, m });
}

function fmtDuration(ms: number, t: (k: string) => string) {
  if (ms <= 0) return "—";
  if (ms < 60000) return `${(ms / 1000).toFixed(0)}${t("duration.secShort")}`;
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${m}${t("duration.minShort")} ${s}${t("duration.secUnit")}`;
}

function StatusBadge({ s }: { s: TcStatus }) {
  const { t } = useT();
  const label: Record<TcStatus, string> = {
    PASS: t("dash.status.PASS"),
    FAIL: t("dash.status.FAIL"),
    ERROR: t("dash.status.ERROR"),
    RUNNING: t("dash.status.RUNNING"),
    QUEUED: t("dash.status.QUEUED"),
    SCHEDULED: t("dash.status.SCHEDULED"),
  };
  const cls: Record<TcStatus, string> = {
    PASS: "badge-pass", FAIL: "badge-fail", ERROR: "badge-error",
    RUNNING: "badge-running", QUEUED: "badge-queued", SCHEDULED: "badge-scheduled",
  };
  return <span className={`status-badge ${cls[s]}`}>{label[s]}</span>;
}

function SeverityBadge({ s }: { s: DropoutSeverity }) {
  const { t } = useT();
  const cls: Record<DropoutSeverity, string> = {
    "없음": "severity-none", "경미": "severity-low",
    "보통": "severity-mid", "심각": "severity-high",
  };
  const label = t(`dash.severity.${s}`);
  return <span className={`severity-badge ${cls[s]}`}>{label}</span>;
}

function mosCls(mos: number | null) {
  if (mos == null) return "";
  if (mos >= 4.0) return "mos-great";
  if (mos >= 3.5) return "mos-good";
  if (mos >= 3.0) return "mos-mid";
  return "mos-bad";
}

function exportCsv(results: TcResult[], t: (k: string) => string) {
  const header = [
    "#", t("dash.col.runIndex"), t("dash.col.session"), t("dash.col.repeatIndex"),
    t("dash.col.startedAt"), t("dash.col.status"),
    t("dash.col.iosMos"), t("dash.col.aosMos"),
    t("dash.col.dropout"), t("dash.col.severity"), t("dash.col.duration"),
  ].join(",");
  const rows = [...results].sort(
    (a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime()
  ).map((r, i) => {
    const isRev = r.tcId === "TC_02" || r.tcId === "TC_04";
    const col1 = isRev ? (r.androidVisqolMos ?? "") : (r.iosVisqolMos ?? "");
    const col2 = isRev ? (r.iosVisqolMos ?? "") : (r.androidVisqolMos ?? "");
    return [
      i + 1, r.tcId, r.sessionId ?? "", r.repeatIndex ?? "",
      r.startedAt, r.status,
      col1, col2,
      r.dropoutCount ?? "", r.dropoutSeverity ?? "",
      r.durationMs,
    ].join(",");
  });
  const csv = [header, ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `tc_results_${new Date().toISOString().slice(0, 19).replace(/[:.]/g, "-")}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

async function openReport(path: string) {
  try {
    await invoke("open_report", { path });
  } catch {
    window.open(`file://${path}`, "_blank");
  }
}

function fmt2(v: number | null) {
  return v != null ? v.toFixed(2) : "—";
}

function mosGrade(v: number | null, t: (k: string) => string) {
  if (v == null) return "";
  if (v >= 4.0) return t("dash.mosGrade.great");
  if (v >= 3.5) return t("dash.mosGrade.good");
  if (v >= 3.0) return t("dash.mosGrade.mid");
  if (v >= 2.5) return t("dash.mosGrade.poor");
  return t("dash.mosGrade.veryPoor");
}

function DashboardSessionCard({
  session, rows,
  reportPath, onGenerateReport,
}: {
  session: TcSession;
  rows: TcResult[];
  reportPath: string | null;
  onGenerateReport: () => void;
  isDemo?: boolean;
}) {
  const { t } = useT();
  const done = rows.filter((r) => r.status !== "RUNNING" && r.status !== "QUEUED");
  const pass  = rows.filter((r) => r.status === "PASS").length;
  const fail  = rows.filter((r) => r.status === "FAIL").length;
  const error = rows.filter((r) => r.status === "ERROR").length;
  const passRateNum = done.length > 0 ? Math.round((pass / done.length) * 100) : null;

  const avgIosMos    = avg(rows.map((r) => r.iosVisqolMos));
  const avgAosMos    = avg(rows.map((r) => r.androidVisqolMos));
  const totalDropout = rows.reduce<number | null>((s, r) => r.dropoutCount == null ? s : (s ?? 0) + r.dropoutCount, null);
  const maxDropout   = rows.reduce<number | null>((mx, r) => {
    if (r.dropoutCount == null) return mx;
    return mx == null ? r.dropoutCount : Math.max(mx, r.dropoutCount);
  }, null);

  // 세션 결과에 기록된 앱 버전 (마지막 PASS 또는 마지막 결과에서 추출)
  const versionSource = rows.filter(r => r.status === "PASS").pop() ?? rows[rows.length - 1];
  const appVersions = versionSource
    ? { android: versionSource.androidAppVer ?? "", ios: versionSource.iosAppVer ?? "" }
    : undefined;

  // TC별 미니 통계 (여러 TC 섞인 세션)
  const tcMap = new Map<string, TcResult[]>();
  for (const r of rows) {
    if (!tcMap.has(r.tcId)) tcMap.set(r.tcId, []);
    tcMap.get(r.tcId)!.push(r);
  }
  const multiTc = tcMap.size > 1;

  const isRepeat = !!session.repeatOptions;

  return (
    <div className={`dashboard-session-card${isRepeat ? " repeat" : ""}`}>
      <div className="dashboard-session-card-header">
        <span className="session-card-title">
          {isRepeat
            ? `🔁 ${t("dash.session.repeatSession")} — ${session.tcIds.join(", ")} × ${session.repeatOptions!.count}${t("dash.session.repeatCount")}`
            : `▶ ${t("dash.session.session")} — ${session.tcIds.join(", ")}`}
        </span>
        <div className="session-card-actions">
          <div className="session-card-times">
            <span className="session-time-item">
              <span className="session-time-label">{t("dash.session.start")}</span>
              <span className="session-time-value">{fmtTime(session.startedAt)}</span>
            </span>
            {session.finishedAt && (
              <span className="session-time-item">
                <span className="session-time-label">{t("dash.session.done")}</span>
                <span className="session-time-value">{fmtTime(session.finishedAt)}</span>
              </span>
            )}
            <span className="session-time-item session-time-total">
              <span className="session-time-label">{t("dash.session.elapsed")}</span>
              <span className="session-time-value">
                {fmtSessionDuration(session.startedAt, session.finishedAt, t)}
              </span>
            </span>
          </div>
          {appVersions && (appVersions.ios || appVersions.android) && (
            <div className="session-app-versions">
              {appVersions.android && (
                <span className="session-version-badge version-aos">
                  AOS {appVersions.android}
                </span>
              )}
              {appVersions.ios && (
                <span className="session-version-badge version-ios">
                  iOS {appVersions.ios}
                </span>
              )}
            </div>
          )}
          {reportPath ? (
            <button
              className="btn-xs btn-accent session-report-btn"
              onClick={() => openReport(reportPath)}
              title={t("dash.session.reportOpen")}
            >
              📄 {t("dash.session.reportView")}
            </button>
          ) : (
            <button
              className="btn-xs session-report-btn"
              onClick={onGenerateReport}
              title={t("dash.session.reportGenTitle")}
            >
              📋 {t("dash.session.reportGen")}
            </button>
          )}
        </div>
      </div>
      <div className="session-stats-row">
        <div className="stat-box">
          <span className="stat-box-label">{t("dash.stat.total")}</span>
          <span className="stat-box-value">{rows.length}{t("dash.dropoutUnit")}</span>
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
          <span className={`stat-box-value ${
            passRateNum != null && passRateNum >= 80 ? "td-pass" : "td-fail"
          }`}>
            {passRateNum != null ? `${passRateNum}%` : "—"}
          </span>
        </div>
        <div className="stat-box-divider" />
        <div className="stat-box">
          <span className="stat-box-label">{t("dash.stat.avgIosMos")}</span>
          <span className={`stat-box-value ${mosCls(avgIosMos)}`}>
            {fmt2(avgIosMos)}
            {avgIosMos != null && <span className="stat-grade"> {mosGrade(avgIosMos, t)}</span>}
          </span>
        </div>
        <div className="stat-box">
          <span className="stat-box-label">{t("dash.stat.avgAosMos")}</span>
          <span className={`stat-box-value ${mosCls(avgAosMos)}`}>
            {fmt2(avgAosMos)}
            {avgAosMos != null && <span className="stat-grade"> {mosGrade(avgAosMos, t)}</span>}
          </span>
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
          {Array.from(tcMap.entries()).map(([tcId, rr]) => {
            const p = rr.filter((r) => r.status === "PASS").length;
            const d = rr.filter((r) => r.status !== "RUNNING" && r.status !== "QUEUED").length;
            const rate = d > 0 ? Math.round((p / d) * 100) : null;
            const iosMos = avg(rr.map((r) => r.iosVisqolMos));
            const aosMos = avg(rr.map((r) => r.androidVisqolMos));
            return (
              <div key={tcId} className="tc-mini-stat">
                <span className="tc-id-badge">{tcId}</span>
                <span>{rr.length}{t("dash.dropoutUnit")}</span>
                <span className={rate != null && rate >= 80 ? "td-pass" : "td-fail"}>
                  {rate != null ? `${rate}%` : "—"}
                </span>
                <span className={mosCls(iosMos)}>iOS {fmt2(iosMos)}</span>
                <span className={mosCls(aosMos)}>AOS {fmt2(aosMos)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface Props {
  results: TcResult[];
  runningResults: Map<TcId, TcResult>;
  sessions: TcSession[];
  onClear: () => void;
  onDeleteSelected: (runIds: Set<string>) => void;
  onSelectResult: (r: TcResult) => void;
  onGenerateReport: () => void;
}

// ── 커스텀 스크롤 액션 바 ────────────────────────────────────────────────────

function ScrollActionBar({ containerRef }: { containerRef: React.RefObject<HTMLDivElement | null> }) {
  const [thumb, setThumb] = useState({ top: 0, height: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);
  const dragStartRef = useRef<{ y: number; scrollTop: number } | null>(null);

  const calcThumb = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    if (scrollHeight <= clientHeight) { setThumb({ top: 0, height: 0 }); return; }
    const hPct = Math.max(8, (clientHeight / scrollHeight) * 100);
    const tPct = (scrollTop / (scrollHeight - clientHeight)) * (100 - hPct);
    setThumb({ top: tPct, height: hPct });
  }, [containerRef]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    calcThumb();
    el.addEventListener("scroll", calcThumb, { passive: true });
    const ro = new ResizeObserver(calcThumb);
    ro.observe(el);
    return () => { el.removeEventListener("scroll", calcThumb); ro.disconnect(); };
  }, [containerRef, calcThumb]);

  const onThumbMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const el = containerRef.current;
    if (!el) return;
    setIsDragging(true);
    dragStartRef.current = { y: e.clientY, scrollTop: el.scrollTop };
  }, [containerRef]);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      const el = containerRef.current;
      const track = trackRef.current;
      const drag = dragStartRef.current;
      if (!el || !track || !drag) return;
      const { scrollHeight, clientHeight } = el;
      const trackH = track.clientHeight;
      const thumbH = Math.max(32, (clientHeight / scrollHeight) * trackH);
      const scrollRange = scrollHeight - clientHeight;
      const moveRange = trackH - thumbH;
      if (moveRange <= 0) return;
      const delta = e.clientY - drag.y;
      el.scrollTop = Math.max(0, Math.min(scrollRange, drag.scrollTop + (delta / moveRange) * scrollRange));
    };
    const onUp = () => { setIsDragging(false); dragStartRef.current = null; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, [isDragging, containerRef]);

  const onTrackClick = useCallback((e: React.MouseEvent) => {
    const el = containerRef.current;
    const track = trackRef.current;
    if (!el || !track) return;
    const rect = track.getBoundingClientRect();
    const clickY = e.clientY - rect.top;
    const { scrollHeight, clientHeight } = el;
    const trackH = track.clientHeight;
    const thumbH = Math.max(32, (clientHeight / scrollHeight) * trackH);
    const scrollRange = scrollHeight - clientHeight;
    const moveRange = trackH - thumbH;
    if (moveRange <= 0) return;
    const ratio = Math.max(0, Math.min(1, (clickY - thumbH / 2) / moveRange));
    el.scrollTo({ top: ratio * scrollRange, behavior: "smooth" });
  }, [containerRef]);

  if (thumb.height === 0) return null;

  return (
    <div
      ref={trackRef}
      className={[
        "scroll-action-bar",
        isHovered || isDragging ? "active" : "",
        isDragging ? "dragging" : "",
      ].filter(Boolean).join(" ")}
      onClick={onTrackClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => { if (!isDragging) setIsHovered(false); }}
    >
      <div
        className="scroll-action-thumb"
        style={{ top: `${thumb.top}%`, height: `${thumb.height}%` }}
        onMouseDown={onThumbMouseDown}
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  );
}

export function DashboardView({ results, runningResults, sessions, onClear, onDeleteSelected, onSelectResult, onGenerateReport }: Props) {
  const { t } = useT();

  const [groupBySession, setGroupBySession] = useState(true);
  const groupsRef = useRef<HTMLDivElement>(null);

  // 세션별 보고서 경로 캐시: sessionId → file path
  const [sessionReports, setSessionReports] = useState<Map<string, string>>(new Map());

  // 확인 팝업
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearWithFiles, setClearWithFiles] = useState(true);  // 파일 함께 삭제 여부

  // 선택 모드
  const [selectMode, setSelectMode] = useState(false);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [confirmDeleteSel, setConfirmDeleteSel] = useState(false);

  function toggleCheck(runId: string) {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId); else next.add(runId);
      return next;
    });
  }

  function toggleAll(ids: string[]) {
    setCheckedIds((prev) => {
      const allChecked = ids.every((id) => prev.has(id));
      const next = new Set(prev);
      if (allChecked) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }

  function exitSelectMode() {
    setSelectMode(false);
    setCheckedIds(new Set());
  }

  async function handleGenerateSessionReport(session: TcSession, rows: TcResult[]) {
    const html = buildSessionReportHtml(session, rows);
    const ts = new Date(session.startedAt).toISOString().slice(0, 19).replace(/[T:]/g, "-");
    const filename = `session_report_${session.sessionId.slice(0, 8)}_${ts}.html`;
    try {
      const path = await invoke<string>("save_session_report", { html, filename });
      setSessionReports((prev) => new Map(prev).set(session.sessionId, path));
    } catch (e) {
      alert(`${t("dash.session.reportSaveFail")}: ${e}`);
    }
  }

  // 실행 중인 결과: results에 없는 항목만 앞에 추가 (실행 중 대시보드 실시간 표시)
  const liveResults = [
    ...Array.from(runningResults.values()).filter(
      (r) => r.status === "RUNNING" || r.status === "QUEUED"
    ).filter((r) => r.runId && !results.some((x) => x.runId === r.runId)),
    ...results,
  ];
  const activeResults = liveResults;
  const activeSessions = sessions;

  const sorted = [...activeResults].sort(
    (a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime()
  );

  // 세션 그룹 뷰 (최신 세션이 위)
  const sessionGroups: { session: TcSession | null; rows: TcResult[] }[] = [];
  if (groupBySession && activeSessions.length > 0) {
    const usedRunIds = new Set<string>();
    const sessionsSorted = [...activeSessions].sort(
      (a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime()
    );
    for (const session of sessionsSorted) {
      const rows = sorted.filter((r) => r.sessionId === session.sessionId);
      rows.forEach((r) => usedRunIds.add(r.runId));
      if (rows.length > 0) sessionGroups.push({ session, rows });
    }
    const orphans = sorted.filter((r) => !usedRunIds.has(r.runId));
    if (orphans.length > 0) sessionGroups.push({ session: null, rows: orphans });
  } else {
    sessionGroups.push({ session: null, rows: sorted });
  }

  return (
    <div className="dashboard-wrap">
      <div className="dashboard-header">
        <span className="dashboard-title">
          {t("dash.title")}
        </span>
        <div className="dashboard-actions">
          <label className="dashboard-toggle">
            <input
              type="checkbox"
              checked={groupBySession}
              onChange={(e) => setGroupBySession(e.target.checked)}
            />
            {t("dash.sessionGroup")}
          </label>
          <button
            className="btn-xs"
            disabled={activeResults.length === 0}
            onClick={() => exportCsv(activeResults, t)}
          >
            {t("dash.csv")}
          </button>

          {/* 보고서 생성 */}
          <button
            className="btn-xs btn-report"
            disabled={results.length === 0}
            onClick={onGenerateReport}
            title={t("dash.report")}
          >
            {t("dash.report")}
          </button>

          {/* 선택 모드 */}
          {selectMode ? (
            <>
              <button
                className="btn-xs btn-danger"
                disabled={checkedIds.size === 0}
                onClick={() => setConfirmDeleteSel(true)}
              >
                {t("dash.deleteSelectedBtn", { count: checkedIds.size })}
              </button>
              <button className="btn-xs" onClick={exitSelectMode}>
                {t("dash.cancel")}
              </button>
            </>
          ) : (
            <button
              className="btn-xs"
              disabled={results.length === 0}
              onClick={() => setSelectMode(true)}
              title={t("dash.selectDelete")}
            >
              {t("dash.selectDelete")}
            </button>
          )}

          <button
            className="btn-xs btn-danger"
            disabled={results.length === 0}
            onClick={() => setConfirmClear(true)}
          >
            {t("dash.clearAll")}
          </button>
        </div>
      </div>

      {/* 전체 삭제 확인 팝업 */}
      {confirmClear && (
        <div className="confirm-overlay" onClick={() => setConfirmClear(false)}>
          <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-title">{t("dash.confirmClearTitle")}</div>
            <div className="confirm-body"
              dangerouslySetInnerHTML={{ __html: t("dash.confirmClearBody", { count: results.length }) }}
            />
            <label className="confirm-file-check">
              <input
                type="checkbox"
                checked={clearWithFiles}
                onChange={(e) => setClearWithFiles(e.target.checked)}
              />
              &nbsp;{t("dash.confirmClearWithFiles")}
            </label>
            <div className="confirm-actions">
              <button className="btn-confirm" onClick={() => setConfirmClear(false)}>{t("dash.cancel")}</button>
              <button
                className="btn-confirm btn-danger"
                onClick={async () => {
                  setConfirmClear(false);
                  if (clearWithFiles) {
                    // 상세 조회로 음원·스크린샷 경로 수집 (demo 항목 제외)
                    const paths: string[] = [];
                    for (const r of results) {
                      if (r.runId.startsWith("demo-")) continue;
                      if (r.dropoutReportPath) paths.push(r.dropoutReportPath);
                      if (r.mosReportPath) paths.push(r.mosReportPath);
                      try {
                        const detail = await invoke<{
                          audioFiles: { label: string; path: string }[];
                          screenshots: string[];
                        }>("db_query_result_detail", { runId: r.runId });
                        for (const af of detail.audioFiles) paths.push(af.path);
                        for (const sp of detail.screenshots) paths.push(sp);
                      } catch {
                        // 상세 조회 실패 시 무시하고 계속
                      }
                    }
                    if (paths.length > 0) {
                      try {
                        await invoke("clear_result_files", { paths, pruneEmptyDirs: true });
                      } catch (e) {
                        console.warn("[clear] 파일 삭제 실패:", e);
                      }
                    }
                  }
                  onClear();
                }}
              >
                {t("dash.delete")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 선택 삭제 확인 팝업 */}
      {confirmDeleteSel && (
        <div className="confirm-overlay" onClick={() => setConfirmDeleteSel(false)}>
          <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-title">{t("dash.confirmDelSelTitle")}</div>
            <div className="confirm-body"
              dangerouslySetInnerHTML={{ __html: t("dash.confirmDelSelBody", { count: checkedIds.size }) }}
            />
            <div className="confirm-actions">
              <button className="btn-confirm" onClick={() => setConfirmDeleteSel(false)}>{t("dash.cancel")}</button>
              <button
                className="btn-confirm btn-danger"
                onClick={() => {
                  setConfirmDeleteSel(false);
                  onDeleteSelected(checkedIds);
                  exitSelectMode();
                }}
              >
                {t("dash.delete")}
              </button>
            </div>
          </div>
        </div>
      )}

      {sorted.length === 0 ? (
        <div className="dashboard-empty">
          {t("dash.empty")}<br />
          {t("dash.emptyHint")}
        </div>
      ) : (
        <div className="dashboard-groups-wrap">
          <div className="dashboard-groups" ref={groupsRef}>
          {sessionGroups.map(({ session, rows }, gi) => {
            if (rows.length === 0) return null;
            return (
              <div key={gi} className="dashboard-group">
                {session && (
                  <DashboardSessionCard
                    session={session}
                    rows={rows}
                    reportPath={sessionReports.get(session.sessionId) ?? null}
                    onGenerateReport={() => handleGenerateSessionReport(session, rows)}
                    isDemo={session.sessionId === DEMO_SESSION_ID}
                  />
                )}
                <div className="dashboard-table-wrap">
                  <table className={`dashboard-table${selectMode ? " select-mode" : ""}${session?.repeatOptions ? " repeat-mode" : ""}`}>
                    <thead>
                      <tr>
                        {selectMode && (
                        <th className="td-check">
                            <input
                              type="checkbox"
                              checked={rows.length > 0 && rows.every((r) => checkedIds.has(r.runId))}
                              onChange={() => toggleAll(rows.map((r) => r.runId))}
                            />
                          </th>
                        )}
                        <th>#</th>
                        {session?.repeatOptions && <th>{t("dash.col.repeatIndex")}</th>}
                        <th>{t("dash.col.runIndex")}</th>
                        <th>{t("dash.col.startedAt")}</th>
                        <th>{t("dash.col.status")}</th>
                        <th>{t("dash.col.iosMos")}</th>
                        <th>{t("dash.col.aosMos")}</th>
                        <th>{t("dash.col.vishing")}</th>
                        <th>{t("dash.col.dropout")}</th>
                        <th>{t("dash.col.duration")}</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr
                          key={r.runId}
                          className={[
                            r.status === "RUNNING" ? "row-running" : "",
                            selectMode && checkedIds.has(r.runId) ? "row-checked" : "",
                          ].filter(Boolean).join(" ")}
                        >
                          {selectMode && (
                            <td className="td-check">
                              <input
                                type="checkbox"
                                checked={checkedIds.has(r.runId)}
                                onChange={() => toggleCheck(r.runId)}
                              />
                            </td>
                          )}
                          <td className="td-num">{activeResults.length - activeResults.findIndex((x) => x.runId === r.runId)}</td>
                          {session?.repeatOptions && (
                            <td className="td-repeat">{r.repeatIndex ?? "—"}</td>
                          )}
                          <td><span className="tc-id-badge">{r.tcId}</span></td>
                          <td className="td-time">{fmtTime(r.startedAt)}</td>
                          <td><StatusBadge s={r.status} /></td>
                          {(() => {
                            const isReverse = r.tcId === "TC_02" || r.tcId === "TC_04";
                            const col1Mos = isReverse ? r.androidVisqolMos : r.iosVisqolMos;
                            const col2Mos = isReverse ? r.iosVisqolMos : r.androidVisqolMos;
                            const col1Os = isReverse ? "AOS" : "iOS";
                            const col2Os = isReverse ? "iOS" : "AOS";
                            return (
                              <>
                                <td className={`td-mos ${mosCls(col1Mos)}`}>
                                  {col1Mos != null ? (<><span className="os-badge">{col1Os}</span>{col1Mos.toFixed(2)}</>) : "—"}
                                </td>
                                <td className={`td-mos ${mosCls(col2Mos)}`}>
                                  {col2Mos != null ? (<><span className="os-badge">{col2Os}</span>{col2Mos.toFixed(2)}</>) : "—"}
                                </td>
                              </>
                            );
                          })()}
                          <td className="td-vishing">
                            {(r.tcId === "TC_03" || r.tcId === "TC_04")
                              ? r.vishingDetected === true
                                ? <span className="badge-pass">✅ PASS</span>
                                : r.vishingDetected === false
                                ? <span className="badge-fail">❌ FAIL</span>
                                : <span className="td-empty">—</span>
                              : (r.tcId === "TC_01" || r.tcId === "TC_02")
                                ? <span className="td-muted">{t("dash.notSupported")}</span>
                                : <span className="td-empty">—</span>
                            }
                          </td>
                          <td className="td-dropout">
                            <div style={{display:'flex', alignItems:'center', justifyContent:'center', gap:4, flexWrap:'nowrap', width:'100%'}}>
                              <span>
                                {r.dropoutSeverity ? (
                                  <SeverityBadge s={r.dropoutSeverity} />
                                ) : r.dropoutCount != null ? (
                                  <span className="td-dropout-count">{r.dropoutCount}건</span>
                                ) : "—"}
                              </span>
                              {r.dropoutReportPath && (
                                <button
                                  className="btn-icon"
                                  title="음단절 보고서"
                                  onClick={(e) => { e.stopPropagation(); openReport(r.dropoutReportPath!); }}
                                >
                                  📊
                                </button>
                              )}
                              {r.mosReportPath && (
                                <button
                                  className="btn-icon"
                                  title="MOS 보고서"
                                  onClick={(e) => { e.stopPropagation(); openReport(r.mosReportPath!); }}
                                >
                                  📈
                                </button>
                              )}
                            </div>
                          </td>
                          <td className="td-dur">{fmtDuration(r.durationMs, t)}</td>
                          <td>
                            <button
                              className="btn-xs btn-accent"
                              onClick={() => onSelectResult(r)}
                            >
                              {t("dash.session.view")}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
          </div>
          <ScrollActionBar containerRef={groupsRef} />
        </div>
      )}
    </div>
  );
}

function avg(vals: (number | null)[]): number | null {
  const nums = vals.filter((v): v is number => v != null);
  if (nums.length === 0) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

// ── 세션 HTML 보고서 생성 ─────────────────────────────────────────────────────

function _mos(v: number | null) { return v != null ? v.toFixed(2) : "—"; }
function _mosColor(v: number | null) {
  if (v == null) return "#888";
  if (v >= 4.0) return "#34c759";
  if (v >= 3.5) return "#30d158";
  if (v >= 3.0) return "#ffd60a";
  return "#ff453a";
}
function _statusColor(s: string) {
  if (s === "PASS") return "#34c759";
  if (s === "FAIL") return "#ff453a";
  if (s === "ERROR") return "#ff9f0a";
  return "#888";
}
function _fmtTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function _fmtDur(ms: number) {
  if (!ms || ms <= 0) return "—";
  if (ms < 60000) return `${(ms / 1000).toFixed(0)}s`;
  return `${Math.floor(ms / 60000)}분 ${((ms % 60000) / 1000).toFixed(0)}초`;
}

export function buildSessionReportHtml(session: TcSession, rows: TcResult[]): string {
  const done  = rows.filter((r) => r.status !== "RUNNING" && r.status !== "QUEUED");
  const pass  = rows.filter((r) => r.status === "PASS").length;
  const fail  = rows.filter((r) => r.status === "FAIL").length;
  const error = rows.filter((r) => r.status === "ERROR").length;
  const passRateNum = done.length > 0 ? Math.round((pass / done.length) * 100) : null;
  const passRateStr = passRateNum != null ? `${passRateNum}%` : "—";
  const passRateColor = passRateNum != null && passRateNum >= 80 ? "#34c759" : "#ff453a";

  // 세션 결과에 기록된 앱 버전 (마지막 PASS 또는 마지막 결과에서 추출)
  const versionSource = rows.filter(r => r.status === "PASS").pop() ?? rows[rows.length - 1];

  // 테스트 환경 정보: 마지막 PASS 결과에서 추출
  const envResult = [...rows].reverse().find((r) => r.status === "PASS" && (r.androidDevice || r.iosDevice)) ?? rows[rows.length - 1];
  let appCfg: TargetAppConfig;
  try { appCfg = JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG; }
  catch { appCfg = DEFAULT_APP_CONFIG; }
  const androidAppInfo = SUPPORTED_APPS.find(a => a.id === appCfg.androidAppId);
  const iosAppInfo = SUPPORTED_APPS.find(a => a.id === appCfg.iosAppId);
  const carrierName = SUPPORTED_CARRIERS.find(c => c.id === (envResult?.carrier ?? ""))?.name ?? "";

  const envRows: [string, string | null | undefined][] = [
    ["통신사", carrierName],
    ["Android 단말", envResult?.androidDevice],
    ["Android OS", envResult?.androidOsVer],
    ["Android 앱", androidAppInfo?.name],
    ["Android 앱 버전", envResult?.androidAppVer],
    ["iOS 단말", envResult?.iosDevice],
    ["iOS OS", envResult?.iosOsVer],
    ["iOS 앱", iosAppInfo?.name],
    ["iOS 앱 버전", envResult?.iosAppVer],
    ["프로파일", envResult?.profileName],
  ];
  const envTableHtml = envRows
    .filter(([, v]) => v && v !== "-")
    .map(([label, val]) => `<tr><td style="color:#8b949e;text-align:left;padding:4px 12px;white-space:nowrap">${label}</td><td style="text-align:left;padding:4px 12px">${val}</td></tr>`)
    .join("");

  const avgIosMos    = avg(rows.map((r) => r.iosVisqolMos));
  const avgAosMos    = avg(rows.map((r) => r.androidVisqolMos));
  const totalDropout = rows.reduce<number | null>((s, r) => r.dropoutCount == null ? s : (s ?? 0) + r.dropoutCount, null);
  const maxDropout   = rows.reduce<number | null>((mx, r) => {
    if (r.dropoutCount == null) return mx;
    return mx == null ? r.dropoutCount : Math.max(mx, r.dropoutCount);
  }, null);

  // TC별 미니 통계
  const tcMap = new Map<string, TcResult[]>();
  for (const r of rows) {
    if (!tcMap.has(r.tcId)) tcMap.set(r.tcId, []);
    tcMap.get(r.tcId)!.push(r);
  }

  const isRepeat = !!session.repeatOptions;
  const sessionTitle = isRepeat
    ? `반복 세션 — ${session.tcIds.join(", ")} × ${session.repeatOptions!.count}회`
    : `세션 — ${session.tcIds.join(", ")}`;

  const generatedAt = new Date().toLocaleString("ko-KR");

  const elapsedStr = session.finishedAt
    ? (() => {
        const ms = new Date(session.finishedAt).getTime() - new Date(session.startedAt).getTime();
        if (ms <= 0) return "0분";
        const h = Math.floor(ms / 3600000);
        const m = Math.floor((ms % 3600000) / 60000);
        const s = Math.floor((ms % 60000) / 1000);
        if (h === 0) return `${m}분`;
        if (m === 0 && s === 0) return `${h}시간`;
        if (m === 0) return `${h}시간 ${s}초`;
        return `${h}시간 ${m}분`;
      })()
    : "진행 중";

  // TC별 요약 행
  const tcSummaryRows = Array.from(tcMap.entries()).map(([tcId, rr]) => {
    const p = rr.filter((r) => r.status === "PASS").length;
    const f = rr.filter((r) => r.status === "FAIL").length;
    const e = rr.filter((r) => r.status === "ERROR").length;
    const d = rr.filter((r) => r.status !== "RUNNING" && r.status !== "QUEUED").length;
    const rate = d > 0 ? Math.round((p / d) * 100) : null;
    const rateColor = rate != null && rate >= 80 ? "#34c759" : "#ff453a";
    const iosMos = avg(rr.map((r) => r.iosVisqolMos));
    const aosMos = avg(rr.map((r) => r.androidVisqolMos));
    return `
      <tr>
        <td><span class="tc-badge">${tcId}</span></td>
        <td>${rr.length}</td>
        <td style="color:#34c759;font-weight:700">${p}</td>
        <td style="color:${f > 0 ? "#ff453a" : "#888"};font-weight:700">${f}</td>
        <td style="color:${e > 0 ? "#ff9f0a" : "#888"}">${e}</td>
        <td style="color:${rateColor};font-weight:700">${rate != null ? `${rate}%` : "—"}</td>
        <td style="color:${_mosColor(iosMos)}">${_mos(iosMos)}</td>
        <td style="color:${_mosColor(aosMos)}">${_mos(aosMos)}</td>
      </tr>`;
  }).join("");

  // 개별 실행 행
  const detailRows = rows.map((r, i) => {
    const isRev = r.tcId === "TC_02" || r.tcId === "TC_04";
    const col1 = isRev ? r.androidVisqolMos : r.iosVisqolMos;
    const col2 = isRev ? r.iosVisqolMos : r.androidVisqolMos;
    const col1Label = isRev ? "AOS" : "iOS";
    const col2Label = isRev ? "iOS" : "AOS";
    const repeatCell = session.repeatOptions
      ? `<td class="td-center">${r.repeatIndex ?? "—"}</td>` : "";
    const reportLinks = [
      r.dropoutReportPath ? `<a href="file://${r.dropoutReportPath}" target="_blank">📊</a>` : "",
      r.mosReportPath ? `<a href="file://${r.mosReportPath}" target="_blank">📈</a>` : "",
    ].filter(Boolean).join(" ");
    const audioLinks = r.extractedAudioPaths.map((af) => {
      const isIos = /ios/i.test(af.label);
      const isAos = /android|aos/i.test(af.label);
      const osTag = isIos
        ? `<span class="os-tag audio-ios">iOS</span>`
        : isAos
          ? `<span class="os-tag audio-aos">AOS</span>`
          : `<span class="os-tag">🎵</span>`;
      return `<a href="file://${af.path}" title="${af.label}" target="_blank" class="audio-link">${osTag}</a>`;
    }).join(" ");
    return `
      <tr class="${r.status === "FAIL" ? "row-fail" : r.status === "ERROR" ? "row-error" : ""}">
        <td class="td-center td-muted">${i + 1}</td>
        ${repeatCell}
        <td class="td-center"><span class="tc-badge">${r.tcId}</span></td>
        <td class="td-center td-muted">${_fmtTime(r.startedAt)}</td>
        <td class="td-center"><span class="status-badge" style="color:${_statusColor(r.status)}">${r.status}</span></td>
        <td class="td-center td-muted">${_fmtDur(r.durationMs)}</td>
        <td class="td-center" style="color:${_mosColor(col1)}">
          <span class="os-tag">${col1Label}</span>${_mos(col1)}
        </td>
        <td class="td-center" style="color:${_mosColor(col2)}">
          <span class="os-tag">${col2Label}</span>${_mos(col2)}
        </td>
        <td class="td-center">${r.dropoutCount != null ? `${r.dropoutCount}건` : "—"}${r.dropoutSeverity ? ` <span class="drop-badge drop-${r.dropoutSeverity}">${r.dropoutSeverity}</span>` : ""}</td>
        <td class="td-center">${audioLinks || "—"}</td>
        <td class="td-center">${reportLinks || "—"}</td>
        ${r.errorMsg ? `<td class="td-err">${r.errorMsg}</td>` : "<td></td>"}
      </tr>`;
  }).join("");

  const repeatHeader = session.repeatOptions ? "<th>회차</th>" : "";

  return `<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${sessionTitle}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background: #0d1117; color: #e6edf3; font-size: 13px; padding: 24px; }
    h1 { font-size: 18px; font-weight: 700; margin-bottom: 4px; }
    .meta { font-size: 11px; color: #8b949e; margin-bottom: 20px; }
    section { margin-bottom: 28px; }
    h2 { font-size: 13px; font-weight: 600; color: #58a6ff; margin-bottom: 10px;
         padding-bottom: 4px; border-bottom: 1px solid #30363d; }

    /* 요약 카드 */
    .summary-cards { display: flex; gap: 0; border: 1px solid #30363d;
                     border-radius: 8px; overflow: hidden; margin-bottom: 16px; }
    .stat-card { flex: 1; padding: 10px 16px; text-align: center;
                 border-right: 1px solid #30363d; background: #161b22; }
    .stat-card:last-child { border-right: none; }
    .stat-card.highlight { background: #0d2137; }
    .stat-label { font-size: 10px; color: #8b949e; margin-bottom: 4px; }
    .stat-val { font-size: 20px; font-weight: 700; }

    /* TC별 요약 표 */
    .tc-table, .detail-table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .tc-table th, .tc-table td,
    .detail-table th, .detail-table td {
      padding: 6px 10px; border-bottom: 1px solid #21262d; text-align: center;
    }
    .tc-table th, .detail-table th {
      background: #161b22; color: #8b949e; font-weight: 600; white-space: nowrap;
    }
    .tc-table tr:hover, .detail-table tr:hover { background: #1c2128; }
    .row-fail { background: rgba(255,67,58,0.06); }
    .row-error { background: rgba(255,159,10,0.06); }
    .td-center { text-align: center; }
    .td-muted { color: #8b949e; }
    .td-err { color: #ff453a; font-size: 11px; max-width: 200px; word-break: break-word; }

    .tc-badge { background: #1f6feb; color: #fff; font-size: 10px; font-weight: 700;
                padding: 2px 7px; border-radius: 4px; }
    .status-badge { font-weight: 700; font-size: 11px; }
    .os-tag { font-size: 9px; background: #21262d; padding: 0 4px; border-radius: 3px;
              color: #8b949e; margin-right: 3px; }
    .audio-link { text-decoration: none; }
    .audio-link:hover .os-tag { opacity: 0.75; }
    .audio-ios { background: rgba(10,132,255,0.18); color: #58a6ff;
                 border: 1px solid rgba(10,132,255,0.35); font-weight: 700; padding: 1px 6px; }
    .audio-aos { background: rgba(52,199,89,0.15); color: #34c759;
                 border: 1px solid rgba(52,199,89,0.35); font-weight: 700; padding: 1px 6px; }
    .drop-badge { font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 3px; }
    .drop-없음 { background: #0d2918; color: #34c759; }
    .drop-경미 { background: #0c2333; color: #64d2ff; }
    .drop-보통 { background: #2d2000; color: #ffd60a; }
    .drop-심각 { background: #2d0b0e; color: #ff453a; }
    a { color: #58a6ff; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .footer { font-size: 11px; color: #8b949e; margin-top: 32px; border-top: 1px solid #21262d;
              padding-top: 12px; text-align: right; }
    .version-badge { display: inline-block; font-size: 10px; font-weight: 600;
                     padding: 1px 7px; border-radius: 10px; margin-left: 6px; }
    .version-aos { background: rgba(52,199,89,0.15); color: #34c759; border: 1px solid rgba(52,199,89,0.35); }
    .version-ios { background: rgba(10,132,255,0.15); color: #58a6ff; border: 1px solid rgba(10,132,255,0.35); }
  </style>
</head>
<body>

<h1>📋 ${sessionTitle}</h1>
<div class="meta">
  시작: ${_fmtTime(session.startedAt)}
  ${session.finishedAt ? ` &nbsp;|&nbsp; 종료: ${_fmtTime(session.finishedAt)}` : ""}
  &nbsp;|&nbsp; 소요: <strong style="color:#e6edf3">${elapsedStr}</strong>
  ${versionSource?.androidAppVer ? `<span class="version-badge version-aos">AOS ${versionSource.androidAppVer}</span>` : ""}
  ${versionSource?.iosAppVer ? `<span class="version-badge version-ios">iOS ${versionSource.iosAppVer}</span>` : ""}
  &nbsp;|&nbsp; 생성: ${generatedAt}
</div>

<section>
  <h2>📊 전체 요약</h2>
  <div class="summary-cards">
    <div class="stat-card">
      <div class="stat-label">전체</div>
      <div class="stat-val">${rows.length}회</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">PASS</div>
      <div class="stat-val" style="color:#34c759">${pass}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">FAIL</div>
      <div class="stat-val" style="color:${fail > 0 ? "#ff453a" : "#8b949e"}">${fail}</div>
    </div>
    ${error > 0 ? `<div class="stat-card">
      <div class="stat-label">ERROR</div>
      <div class="stat-val" style="color:#ff9f0a">${error}</div>
    </div>` : ""}
    <div class="stat-card highlight">
      <div class="stat-label">통과율</div>
      <div class="stat-val" style="color:${passRateColor}">${passRateStr}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">평균 MOS(iOS)</div>
      <div class="stat-val" style="color:${_mosColor(avgIosMos)}">${_mos(avgIosMos)}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">평균 MOS(AOS)</div>
      <div class="stat-val" style="color:${_mosColor(avgAosMos)}">${_mos(avgAosMos)}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">전체 음단절</div>
      <div class="stat-val">${totalDropout != null ? `${totalDropout}건` : "—"}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">최대 음단절</div>
      <div class="stat-val" style="color:${maxDropout != null && maxDropout > 0 ? "#ff453a" : "#e6edf3"}">${maxDropout != null ? `${maxDropout}건` : "—"}</div>
    </div>
  </div>

  ${envTableHtml ? `
  <h2 style="margin-top:16px">🔧 테스트 환경</h2>
  <table style="font-size:12px;border-collapse:collapse">
    <tbody>${envTableHtml}</tbody>
  </table>` : ""}

  ${tcMap.size > 1 ? `
  <h2 style="margin-top:16px">TC별 집계</h2>
  <table class="tc-table">
    <thead><tr>
      <th>TC ID</th><th>전체</th><th>PASS</th><th>FAIL</th><th>ERROR</th>
      <th>통과율</th><th>평균 MOS(iOS)</th><th>평균 MOS(AOS)</th>
    </tr></thead>
    <tbody>${tcSummaryRows}</tbody>
  </table>` : ""}
</section>

<section>
  <h2>📋 개별 실행 결과</h2>
  <table class="detail-table">
    <thead><tr>
      <th>#</th>${repeatHeader}<th>TC ID</th><th>실행시각</th>
      <th>상태</th><th>소요</th><th>MOS①</th><th>MOS②</th>
      <th>음단절</th><th>음원</th><th>보고서</th><th>오류</th>
    </tr></thead>
    <tbody>${detailRows}</tbody>
  </table>
</section>

<div class="footer">ixi-O 통화기능 테스트 &nbsp;|&nbsp; Powered by ixio-test-app</div>
</body>
</html>`;
}
