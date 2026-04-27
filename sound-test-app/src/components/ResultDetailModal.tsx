import { useRef, useState, useEffect } from "react";
import type { TcResult, DropoutSeverity } from "../types";
import { invoke } from "@tauri-apps/api/core";
import { useT } from "../i18n";

function severityCls(s: DropoutSeverity): string {
  return { "없음": "severity-none", "경미": "severity-low", "보통": "severity-mid", "심각": "severity-high" }[s] ?? "";
}

async function openReport(path: string) {
  try { await invoke("open_report", { path }); }
  catch { window.open(`file://${path}`, "_blank"); }
}

function fileName(path: string): string {
  return path.split("/").pop() ?? path;
}

interface Props {
  result: TcResult;
  onClose: () => void;
}

export function ResultDetailModal({ result, onClose }: Props) {
  const { t } = useT();
  const logRef = useRef<HTMLDivElement>(null);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});

  function mosGrade(mos: number | null): string {
    if (mos == null) return "";
    if (mos >= 4.0) return t("result.mosGradeExcellent");
    if (mos >= 3.5) return t("result.mosGradeGood");
    if (mos >= 3.0) return t("result.mosGradeFair");
    if (mos >= 2.5) return t("result.mosGradePoor");
    return t("result.mosGradeBad");
  }

  /* 스크린샷 base64 썸네일 로드 */
  useEffect(() => {
    let cancelled = false;
    const paths = result.screenshotPaths;
    if (paths.length === 0) return;

    (async () => {
      const map: Record<string, string> = {};
      for (const p of paths) {
        try {
          const b64: string = await invoke("read_file_base64", { path: p });
          const ext = p.toLowerCase().endsWith(".jpg") ? "jpeg" : "png";
          map[p] = `data:image/${ext};base64,${b64}`;
        } catch {
          /* 로드 실패 시 빈 값 */
        }
      }
      if (!cancelled) setThumbs(map);
    })();
    return () => { cancelled = true; };
  }, [result.screenshotPaths]);

  function copyLogs() {
    navigator.clipboard.writeText(result.logLines.join("\n"));
  }

  const statusCls: Record<string, string> = {
    PASS: "modal-status-pass", FAIL: "modal-status-fail",
    ERROR: "modal-status-error", RUNNING: "modal-status-running",
    QUEUED: "modal-status-running", SCHEDULED: "modal-status-running",
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>

        {/* 헤더 */}
        <div className="modal-header">
          <div className="modal-title-row">
            <span className="modal-title">{result.tcId} {t("result.title")}</span>
            {result.repeatIndex != null && (
              <span className="modal-repeat-badge">{t("result.repeatBadge", { n: result.repeatIndex })}</span>
            )}
            {result.phase != null && (
              <span className="modal-phase-badge">Phase {result.phase}</span>
            )}
          </div>
          <button className="btn-close-red" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          {/* 기본 정보 */}
          <div className="modal-meta-row">
            <span>{t("result.startedAt")}: <b>{new Date(result.startedAt).toLocaleString()}</b></span>
            <span>{t("result.elapsed")}: <b>{result.durationMs > 0 ? `${(result.durationMs / 1000).toFixed(1)}s` : "—"}</b></span>
            <span>{t("result.status")}: <b className={statusCls[result.status] ?? ""}>{result.status}</b></span>
          </div>

          {/* MOS 측정 지표 */}
          <div className="modal-section">
            <div className="modal-section-title">{t("result.mosSection")}</div>
            {(() => {
              const isRev = result.tcId === "TC_02" || result.tcId === "TC_04";
              const label1 = isRev ? "[iOS] ViSQOL MOS" : "[Android] ViSQOL MOS";
              const label2 = isRev ? "[Android] ViSQOL MOS" : "[iOS] ViSQOL MOS";
              const val1 = isRev ? result.androidVisqolMos : result.iosVisqolMos;
              const val2 = isRev ? result.iosVisqolMos : result.androidVisqolMos;
              return (
            <div className="modal-metrics">
              <div className="metric-item">
                <span className="metric-label">{label1}</span>
                <span className="metric-val">{val1?.toFixed(3) ?? "—"}</span>
                <span className="metric-grade">{mosGrade(val1)}</span>
              </div>
              <div className="metric-item">
                <span className="metric-label">{label2}</span>
                <span className="metric-val">{val2?.toFixed(3) ?? "—"}</span>
                <span className="metric-grade">{mosGrade(val2)}</span>
              </div>
              {result.snrDb != null && (
                <div className="metric-item">
                  <span className="metric-label">SNR</span>
                  <span className="metric-val">{result.snrDb.toFixed(1)} dB</span>
                  <span className="metric-grade"></span>
                </div>
              )}
            </div>
              );
            })()}
          </div>

          {/* 음단절 분석 (TC_01/TC_02/TC_03/TC_04) */}
          {(["TC_01", "TC_02", "TC_03", "TC_04"] as const).includes(result.tcId as any) && (
            <div className="modal-section">
              <div className="modal-section-title">{t("result.dropoutSection")}</div>
              <div className="modal-metrics">
                <div className="metric-item">
                  <span className="metric-label">{t("result.dropoutCount")}</span>
                  <span className="metric-val">{result.dropoutCount != null ? `${result.dropoutCount}${t("result.dropoutCountUnit")}` : "—"}</span>
                  {result.dropoutSeverity && (
                    <span className={`severity-badge ${severityCls(result.dropoutSeverity)}`}>
                      {t(`result.severity${result.dropoutSeverity === "없음" ? "None" : result.dropoutSeverity === "경미" ? "Low" : result.dropoutSeverity === "보통" ? "Mid" : "High"}`)}
                    </span>
                  )}
                </div>
              </div>
              {result.dropoutReportPath ? (
                <button
                  className="btn-xs btn-accent modal-report-btn"
                  onClick={() => openReport(result.dropoutReportPath!)}
                >
                  {t("result.dropoutReportBtn")}
                </button>
              ) : result.status === "PASS" ? (
                <div className="modal-report-pending">{t("result.dropoutNoReport")}</div>
              ) : null}
            </div>
          )}

          {/* 단말에서 수집된 음원 파일 */}
          {result.extractedAudioPaths.length > 0 && (
            <div className="modal-section">
              <div className="modal-section-title">{t("result.audioSection")}</div>
              <div className="modal-audio-files">
                {result.extractedAudioPaths.map((af, i) => (
                  <div key={i} className="audio-file-row">
                    <span className="audio-file-label">{af.label}</span>
                    <span className="audio-file-name" title={af.path}>{fileName(af.path)}</span>
                    <button
                      className="btn-xs btn-ghost"
                      onClick={() => openReport(af.path)}
                      title={t("result.audioOpenTitle")}
                    >
                      {t("result.audioOpen")}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* MOS 보고서 (TC_00) */}
          {(result.tcId as string) === "TC_00" && (
            <div className="modal-section">
              <div className="modal-section-title">{t("result.mosReportSection")}</div>
              {result.mosReportPath ? (
                <button
                  className="btn-xs btn-accent modal-report-btn"
                  onClick={() => openReport(result.mosReportPath!)}
                >
                  📈 {t("result.mosReportBtn")}
                </button>
              ) : result.status === "PASS" ? (
                <div className="modal-report-pending">{t("result.mosReportPending")}</div>
              ) : null}
            </div>
          )}

          {/* 보이스피싱 감지 결과 (TC_03/TC_04 전용) */}
          {(result.tcId === "TC_03" || result.tcId === "TC_04") && (
            <div className="modal-section">
              <div className="modal-section-title">{t("result.vishingSection")}</div>
              <div className="modal-metrics">
                <div className="metric-item">
                  <span className="metric-label">{t("result.vishingLabel")}</span>
                  {result.vishingDetected === true ? (
                    <span className="modal-status-pass">{t("result.vishingPass")}</span>
                  ) : result.vishingDetected === false ? (
                    <span className="modal-status-fail">{t("result.vishingFail")}</span>
                  ) : (
                    <span>{t("result.vishingPending")}</span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* 스크린샷 */}
          {result.screenshotPaths.length > 0 && (
            <div className="modal-section">
              <div className="modal-section-title">{t("result.screenshotSection")}</div>
              <div className="modal-screenshots">
                {result.screenshotPaths.map((p, i) => {
                  const name = p.split("/").pop() ?? `screenshot_${i}`;
                  const label = name.replace(/\.(png|jpg)$/i, "").replace(/_/g, " ");
                  return (
                    <div key={i} className="screenshot-thumb" title={label}>
                      {thumbs[p] ? (
                        <img
                          src={thumbs[p]}
                          alt={label}
                          onClick={() => openReport(p)}
                          style={{ cursor: "pointer" }}
                        />
                      ) : (
                        <div className="screenshot-placeholder" onClick={() => openReport(p)} style={{ cursor: "pointer" }}>
                          📷 {label}
                        </div>
                      )}
                      <span className="screenshot-label">{label}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 오류 메시지 */}
          {result.errorMsg && (
            <div className="modal-section">
              <div className="modal-section-title">{t("result.errorSection")}</div>
              <div className="modal-error-msg">{result.errorMsg}</div>
            </div>
          )}

          {/* 실행 로그 */}
          <div className="modal-section modal-log-section">
            <div className="modal-section-header">
              <span className="modal-section-title">{t("result.logSection")}</span>
              <button className="btn-xs btn-ghost" onClick={copyLogs}>{t("result.logCopy")}</button>
            </div>
            <div className="modal-log-body" ref={logRef}>
              {result.logLines.length === 0
                ? <span className="log-empty">{t("result.logEmpty")}</span>
                : result.logLines.map((line, i) => (
                    <div key={i} className="log-line">{line}</div>
                  ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
