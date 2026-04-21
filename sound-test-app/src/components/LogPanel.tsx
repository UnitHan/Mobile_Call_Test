import { useState } from "react";
import type { ReactNode } from "react";
import { useT } from "../i18n";

interface LogPanelProps {
  title: string;
  logs: string[];
  onClear: () => void;
  logRef: React.RefObject<HTMLDivElement | null>;
  emptyMessage: string;
  classifyLine?: (line: string) => string;
  bannerSrc?: string;
  infoContent?: ReactNode;
}

const defaultClassify = (line: string): string => {
  if (line.includes("err") || line.includes("Error") || line.includes("❌"))
    return "log-err";
  if (line.includes("✅")) return "log-ok";
  return "";
};

export function LogPanel({
  title,
  logs,
  onClear,
  logRef,
  emptyMessage,
  classifyLine = defaultClassify,
  bannerSrc,
  infoContent,
}: LogPanelProps) {
  const [visible, setVisible] = useState(false);
  const { t } = useT();

  return (
    <section className="card log-card">
      <div className="log-header">
        <span className="log-title">{title}</span>
        <div className="log-header-actions">
          <button
            className="btn-xs btn-ghost"
            onClick={() => setVisible((v) => !v)}
          >
            {visible ? t("log.hide") : t("log.show")}
          </button>
          <button className="btn-xs btn-ghost" onClick={onClear}>
            {t("log.clear")}
          </button>
        </div>
      </div>
      {bannerSrc && !visible && (
        <div className="log-banner-wrap">
          <img src={bannerSrc} alt="" className="log-banner" />
        </div>
      )}
      {infoContent && !visible && (
        <div className="log-info-content">{infoContent}</div>
      )}
      {visible && (
        <div className="log-body" ref={logRef}>
          {logs.length === 0 ? (
            <span className="log-empty">{emptyMessage}</span>
          ) : (
            logs.map((line, i) => (
              <div key={i} className={`log-line ${classifyLine(line)}`}>
                {line}
              </div>
            ))
          )}
        </div>
      )}
    </section>
  );
}
