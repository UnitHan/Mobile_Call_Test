import { useState, useEffect, useMemo } from "react";
import type { AppiumStatus } from "../hooks/useAppium";
import { useAppVersions } from "../hooks/useAppVersions";
import { useT } from "../i18n";
import { SUPPORTED_APPS, DEFAULT_APP_CONFIG, SUPPORTED_CARRIERS, DEFAULT_CARRIER, getAppDisplayName } from "../types";
import type { TargetAppConfig, CarrierId } from "../types";

interface AppHeaderProps {
  statusMessage: string;
  envAllOk: boolean;
  appiumStatus: AppiumStatus;
  currentRepeat: number;
  totalRepeat: number;
  onEnvClick: () => void;
  onStartAppium: () => void;
  onStopAppium: () => void;
  onOpenSettings: () => void;
}

export function AppHeader({
  statusMessage,
  envAllOk,
  appiumStatus,
  currentRepeat,
  totalRepeat,
  onEnvClick,
  onStartAppium,
  onStopAppium,
  onOpenSettings,
}: AppHeaderProps) {
  const { t, lang } = useT();
  const isRunning = /실행 중|진행 중|시작 중|분석 중|대기 중|Running|Starting|Analyzing/.test(statusMessage);
  const isDone = statusMessage.includes("완료") || statusMessage.includes("Complete");
  const isRepeating = currentRepeat > 0 && totalRepeat > 0;

  // ── 앱 설정 (localStorage 연동) ──
  const [appConfig, setAppConfig] = useState<TargetAppConfig>(() => {
    try {
      return JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG;
    } catch { return DEFAULT_APP_CONFIG; }
  });

  // localStorage 외부 변경 감지 (설정 모달에서 변경 시)
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === "targetAppConfig") {
        try {
          setAppConfig(JSON.parse(e.newValue || "null") ?? DEFAULT_APP_CONFIG);
        } catch { /* ignore */ }
      }
    };
    // 같은 탭 내 변경도 감지하기 위해 커스텀 이벤트 사용
    const onCustom = () => {
      try {
        setAppConfig(JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG);
      } catch { /* ignore */ }
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener("targetAppConfigChanged", onCustom);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("targetAppConfigChanged", onCustom);
    };
  }, []);

  const handleAppChange = (key: keyof TargetAppConfig, value: string) => {
    const next = { ...appConfig, [key]: value };
    setAppConfig(next);
    localStorage.setItem("targetAppConfig", JSON.stringify(next));
    window.dispatchEvent(new Event("targetAppConfigChanged"));
  };

  const androidApps = SUPPORTED_APPS.filter(a => a.package);
  const iosApps = SUPPORTED_APPS.filter(a => a.bundleId);

  // ── 선택된 앱의 패키지로 버전 조회 ──
  const androidPkg = useMemo(
    () => SUPPORTED_APPS.find(a => a.id === appConfig.androidAppId)?.package || "",
    [appConfig.androidAppId],
  );
  const iosPkg = useMemo(
    () => SUPPORTED_APPS.find(a => a.id === appConfig.iosAppId)?.bundleId || "",
    [appConfig.iosAppId],
  );
  const appVersions = useAppVersions(iosPkg, androidPkg);
  const androidVersion = appVersions.android;
  const iosVersion = appVersions.ios;

  // ── 통신사 설정 (localStorage 연동) ──
  const [carrierId, setCarrierId] = useState<CarrierId>(() => {
    try {
      return (localStorage.getItem("selectedCarrier") as CarrierId) || DEFAULT_CARRIER;
    } catch { return DEFAULT_CARRIER; }
  });

  useEffect(() => {
    const onCustom = () => {
      try {
        setCarrierId((localStorage.getItem("selectedCarrier") as CarrierId) || DEFAULT_CARRIER);
      } catch { /* ignore */ }
    };
    window.addEventListener("selectedCarrierChanged", onCustom);
    return () => window.removeEventListener("selectedCarrierChanged", onCustom);
  }, []);

  const handleCarrierChange = (value: string) => {
    setCarrierId(value as CarrierId);
    localStorage.setItem("selectedCarrier", value);
    window.dispatchEvent(new Event("selectedCarrierChanged"));
  };

  return (
    <header className="app-header">
      <span className="app-title">{t("app.title")}</span>
      <span className="app-status-msg" title={statusMessage}>
        {isRunning && <span className="status-tag tag-running">{t("header.statusRunning")}</span>}
        {isDone && <span className="status-tag tag-done">{t("header.statusDone")}</span>}
        {isRepeating && <span className="status-tag tag-repeat">{currentRepeat}/{totalRepeat}</span>}
        {statusMessage || t("header.statusReady")}
      </span>
      <div className="app-selector-group">
        <select
          className="app-select app-select-carrier"
          value={carrierId}
          onChange={(e) => handleCarrierChange(e.target.value)}
          title="테스트 통신사 선택"
        >
          {SUPPORTED_CARRIERS.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <select
          className="app-select app-select-android"
          value={appConfig.androidAppId}
          onChange={(e) => handleAppChange("androidAppId", e.target.value)}
          title="Android 테스트 앱"
        >
          {androidApps.map(a => (
            <option key={a.id} value={a.id}>{getAppDisplayName(a, lang)}</option>
          ))}
        </select>
        <select
          className="app-select app-select-ios"
          value={appConfig.iosAppId}
          onChange={(e) => handleAppChange("iosAppId", e.target.value)}
          title="iOS 테스트 앱"
        >
          {iosApps.map(a => (
            <option key={a.id} value={a.id}>{getAppDisplayName(a, lang)}</option>
          ))}
        </select>
      </div>
      <div className="app-ver-badges">
        {androidVersion && (
          <span className="ver-badge ver-android" title={`Android ${SUPPORTED_APPS.find(a => a.id === appConfig.androidAppId)?.name ?? ""} 버전`}>
            AOS {androidVersion}
          </span>
        )}
        {iosVersion && (
          <span className="ver-badge ver-ios" title={`iOS ${SUPPORTED_APPS.find(a => a.id === appConfig.iosAppId)?.name ?? ""} 버전`}>
            iOS {iosVersion}
          </span>
        )}
      </div>
      <div className="appium-ctrl">
        <button
          className="btn-xs btn-ghost settings-btn"
          onClick={onOpenSettings}
          title={t("header.btnSettings")}
        >
          ⚙
        </button>
        <button
          className={`btn-xs btn-ghost env-btn ${!envAllOk ? "env-warn" : ""}`}
          onClick={onEnvClick}
          title={t("header.btnEnv")}
        >
          <span className={`env-dot ${envAllOk ? "ok" : "warn"}`} />
          {t("header.btnEnv")}
        </button>
        {appiumStatus === "running" ? (
          <>
            <span className="appium-badge">{t("header.appiumRunning")}</span>
            <button className="btn-xs btn-ghost" onClick={onStopAppium}>
              {t("header.appiumStop")}
            </button>
          </>
        ) : (
          <button
            className={`btn-xs btn-accent ${
              appiumStatus === "starting" ? "is-loading" : ""
            }`}
            onClick={onStartAppium}
            disabled={
              appiumStatus === "starting" || appiumStatus === "stopping"
            }
          >
            {appiumStatus === "starting"
              ? t("header.appiumStarting")
              : appiumStatus === "error"
              ? t("header.appiumRestart")
              : t("header.appiumStart")}
          </button>
        )}
      </div>
    </header>
  );
}
