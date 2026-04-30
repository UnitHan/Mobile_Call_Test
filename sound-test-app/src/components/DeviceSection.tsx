import { useState, useEffect, useRef } from "react";
import type { DeviceInfo } from "../types";
import type { NoticeItem } from "../hooks/useNotice";
import { useT } from "../i18n";

interface DeviceSectionProps {
  androidIpPort: string;
  onChangeIpPort: (val: string) => void;
  onGetAndroidIp: () => void;
  onDisconnectAndroid: () => void;
  onRefreshAndroid: () => void;
  onCheckIphone: () => void;
  onRefreshIos: () => void;
  androidDevices?: DeviceInfo[];
  iosDevices: DeviceInfo[];
  onInstallWda: (udid: string | null) => void;
  /** WDA 설치 대상 UDID — Settings에서 설정, App.tsx에서 전달 */
  wdaUdid?: string;
  watchdogRunning: boolean;
  onStartWatchdog: () => void;
  onStopWatchdog: () => void;
  notices?: NoticeItem[];
}

export function DeviceSection({
  androidIpPort,
  onChangeIpPort,
  onGetAndroidIp,
  onDisconnectAndroid,
  onRefreshAndroid,
  onCheckIphone,
  onRefreshIos,
  androidDevices = [],
  iosDevices,
  onInstallWda,
  wdaUdid: wdaUdidProp = "",
  watchdogRunning,
  onStartWatchdog,
  onStopWatchdog,
  notices = [],
}: DeviceSectionProps) {
  // 공지 슬라이드 인덱스
  const [noticeIdx, setNoticeIdx] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (notices.length <= 1) { setNoticeIdx(0); return; }
    timerRef.current = setInterval(() => {
      setNoticeIdx((i) => (i + 1) % notices.length);
    }, 5000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [notices.length]);

  // 공지가 바뀌면 인덱스 초기화
  useEffect(() => {
    setNoticeIdx(0);
  }, [notices]);

  const currentNotice = notices[noticeIdx];

  const targetUdid = wdaUdidProp || (iosDevices[0]?.udid ?? null);

  const { t } = useT();

  return (
    <section className="card card-device">
      <div className="card-title">{t("device.title")}</div>

      <div className="field-row">
        <span className="device-tag android">Android</span>
        <input
          type="text"
          value={androidIpPort}
          onChange={(e) => onChangeIpPort(e.target.value)}
          placeholder="192.168.0.10:5555"
          className="inp inp-flex"
        />
        <button className="btn-xs" onClick={onGetAndroidIp}>
          {t("device.autoConnect")}
        </button>
        <button className="btn-xs btn-danger" onClick={onDisconnectAndroid}>
          {t("device.disconnect")}
        </button>
        <button
          className="btn-xs btn-ghost"
          onClick={onRefreshAndroid}
          title={t("device.autoConnect")}
        >
          ↺
        </button>
      </div>
      {/* 현재 인식된 Android 디바이스 표시 */}
      {androidDevices.length > 0 && (
        <div style={{ marginTop: 4, paddingLeft: 2 }}>
          {androidDevices.map((d) => (
            <div key={d.udid} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.78rem", color: "var(--text-dim)" }}>
              <span style={{ color: "#4ade80", fontSize: "0.72rem" }}>●</span>
              <span style={{ fontFamily: "monospace" }}>{d.udid}</span>
              <span style={{ color: "var(--text-dim)" }}>—</span>
              <span>{d.name}</span>
            </div>
          ))}
        </div>
      )}

      {/* 하단 영역: 왼쪽 버튼들 + 오른쪽 배너 */}
      <div className="device-lower">
        <div className="device-buttons">
          {/* Watchdog 토글 */}
          <div className="field-row" style={{ marginTop: "6px" }}>
            <span className="device-tag android" style={watchdogRunning ? { background: "#0d3320", color: "#4ade80", borderColor: "#166534" } : {}}>
              {watchdogRunning ? "🐕 Watch" : "🐕 Watch"}
            </span>
            {watchdogRunning ? (
              <>
                <button className="btn-xs btn-danger" onClick={onStopWatchdog}>
                  {t("device.watchdogStop")}
                </button>
                <span style={{ fontSize: "11px", color: "#4ade80" }}>{t("device.watchdogRunning")}</span>
              </>
            ) : (
              <>
                <button className="btn-xs btn-accent" onClick={onStartWatchdog}>
                  {t("device.watchdogStart")}
                </button>
                <span style={{ fontSize: "11px", color: "var(--text-dim)" }}>{t("device.watchdogDesc")}</span>
              </>
            )}
          </div>

          <div className="field-row" style={{ marginTop: "6px" }}>
            <span className="device-tag ios">iPhone</span>
            <button className="btn-xs btn-accent" onClick={onCheckIphone}>
              {t("device.checkIphone")}
            </button>
            <button
              className="btn-xs btn-ghost"
              onClick={onRefreshIos}
              title="iOS 기기 목록 새로고침"
            >
              ↺
            </button>
          </div>

          <div className="field-row" style={{ marginTop: "6px" }}>
            <span className="device-tag ios">WDA</span>
            {wdaUdidProp && (
              <span style={{ fontSize: "0.75rem", color: "var(--text-dim)", marginRight: 4 }}>
                {iosDevices.find((d) => d.udid === wdaUdidProp)?.name ?? wdaUdidProp.slice(0, 8) + "…"}
              </span>
            )}
            <button
              className="btn-xs"
              onClick={() => onInstallWda(targetUdid)}
              title="WDA.ipa 파일을 선택하여 iPhone에 설치합니다"
            >
              {t("device.wdaInstall")}
            </button>
          </div>
        </div>

        {/* ── 공지사항 전광판 ── */}
        <div className="notice-board-wrap">
          <div className="notice-board-header">
            <span className="notice-board-icon">📢</span>
            <span className="notice-board-label">{t("device.notice")}</span>
            {notices.length > 1 && (
              <span className="notice-board-counter">{noticeIdx + 1} / {notices.length}</span>
            )}
          </div>
          <div className="notice-board-body">
            {currentNotice ? (
              <div className="notice-board-ticker" key={currentNotice.id}>
                <span className="notice-board-text">{currentNotice.text}</span>
              </div>
            ) : (
              <span className="notice-board-empty">{t("device.noNotice")}</span>
            )}
          </div>
          {notices.length > 1 && (
            <div className="notice-board-dots">
              {notices.map((_, i) => (
                <button
                  key={i}
                  className={`notice-dot${i === noticeIdx ? " active" : ""}`}
                  onClick={() => setNoticeIdx(i)}
                  aria-label={`${t("device.notice")} ${i + 1}`}
                />
              ))}
            </div>
          )}
        </div>

      </div>
    </section>
  );
}
