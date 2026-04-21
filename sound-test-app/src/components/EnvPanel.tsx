import type { EnvItem } from "../types";
import { useT } from "../i18n";

interface EnvPanelProps {
  envItems: EnvItem[];
  envChecking: boolean;
  pythonEnvReady: boolean;
  setupRunning: boolean;
  setupLogs: string[];
  setupLogRef: React.RefObject<HTMLDivElement | null>;
  onClose: () => void;
  onRefresh: () => void;
  onSetupPython: () => void;
}

export function EnvPanel({
  envItems,
  envChecking,
  pythonEnvReady,
  setupRunning,
  setupLogs,
  setupLogRef,
  onClose,
  onRefresh,
  onSetupPython,
}: EnvPanelProps) {
  const { t } = useT();
  function envLabel(item: EnvItem): string {
    const key = `env.labels.${item.key}` as Parameters<typeof t>[0];
    const translated = t(key);
    // 번역키가 없으면(=키 자체 반환) 백엔드 label 폴백
    return translated !== key ? translated : item.label;
  }

  function envHint(item: EnvItem): string {
    const key = `env.hints.${item.key}` as Parameters<typeof t>[0];
    const translated = t(key);
    return translated !== key ? translated : item.hint;
  }

  return (
    <div className="env-overlay" onClick={onClose}>
      <div className="env-panel" onClick={(e) => e.stopPropagation()}>
        <div className="env-panel-header">
          <span className="env-panel-title">{t("env.title")}</span>
          <button
            className="btn-xs btn-ghost"
            onClick={onRefresh}
            disabled={envChecking}
          >
            {envChecking ? t("env.checking") : t("env.refresh")}
          </button>
          <button className="btn-close-red" onClick={onClose} title={t("dash.cancel")}>
            ×
          </button>
        </div>
        <div className="env-list">
          {envItems.map((item) => (
            <div key={item.key} className={`env-item ${item.ok ? "ok" : "fail"}`}>
              <span className="env-status">{item.ok ? "✅" : "❌"}</span>
              <div className="env-info">
                <span className="env-label">{envLabel(item)}</span>
                {item.version && (
                  <span className="env-version">{item.version}</span>
                )}
                {!item.ok && item.hint && (
                  <span className="env-hint">{envHint(item)}</span>
                )}
              </div>
            </div>
          ))}
        </div>
        {!pythonEnvReady && (
          <div className="env-setup-section">
            <button
              className="btn-xs btn-accent"
              onClick={onSetupPython}
              disabled={setupRunning}
              style={{ width: "100%", padding: "7px 0" }}
            >
              {setupRunning ? t("env.installing") : t("env.installPython")}
            </button>
            {setupLogs.length > 0 && (
              <div className="env-setup-log" ref={setupLogRef}>
                {setupLogs.map((l, i) => (
                  <div key={i} className="log-line">
                    {l}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
