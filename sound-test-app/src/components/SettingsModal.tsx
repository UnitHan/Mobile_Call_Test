import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { TcId, TcSpeakerEntry, AudioProfile, DeviceInfo } from "../types";
import type { NoticeItem } from "../hooks/useNotice";
import { SUPPORTED_APPS, DEFAULT_APP_CONFIG, getAppDisplayName } from "../types";
import type { TargetAppConfig } from "../types";
import { useTcSpeakerConfig } from "../hooks/useTcAudioConfig";
import type { UseAudioProfilesResult } from "../hooks/useAudioProfiles";
import { open } from "@tauri-apps/plugin-dialog";
import { formatPhoneInput } from "./SpeakerSection";
import { LICENSE_GROUPS } from "../data/licenses";
import { TC_ENABLED, FEATURE_ENABLED } from "../data/tcConfig";
import { useT } from "../i18n";

// ── 오디오 인터페이스 정보 타입 ──────────────────────────────────────────────
interface AudioInterface {
  location_id: number;
  name: string;
  sd_out_index: number | null;
  sd_in_index: number | null;
  out_channels: number;
  in_channels: number;
  sample_rate: number;
}

// ── 오디오 인터페이스 탭 컴포넌트 (SettingsModal 외부 정의) ─────────────────
function AudioInterfaceTab() {
  const { t } = useT();
  const [interfaces, setInterfaces] = useState<AudioInterface[]>([]);
  const [androidLocId, setAndroidLocId] = useState<number | null>(null);
  const [iosLocId, setIosLocId] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  const scan = useCallback(async () => {
    setScanning(true);
    setMessage(null);
    try {
      const result = await invoke<AudioInterface[]>("scan_audio_interfaces");
      setInterfaces(result || []);
      // config.py 현재 값 로드
      const cfg = await invoke<{ android_location_id: number; ios_location_id: number } | null>(
        "get_audio_interface_config"
      ).catch(() => null);
      if (cfg) {
        setAndroidLocId(cfg.android_location_id);
        setIosLocId(cfg.ios_location_id);
      } else if (result && result.length >= 2) {
        // config 없으면 순서대로 기본 할당
        setAndroidLocId(result[1]?.location_id ?? null);
        setIosLocId(result[0]?.location_id ?? null);
      }
    } catch (e) {
      setMessage({ text: t("settings.audioInterface.scanError", { error: String(e) }), ok: false });
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => { scan(); }, [scan]);

  const save = async () => {
    if (androidLocId === null || iosLocId === null) {
      setMessage({ text: t("settings.audioInterface.selectBothError"), ok: false });
      return;
    }
    if (androidLocId === iosLocId) {
      setMessage({ text: t("settings.audioInterface.sameDeviceError"), ok: false });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const res = await invoke<{ ok: boolean; message: string }>(
        "save_audio_interface_config",
        { androidLocationId: androidLocId, iosLocationId: iosLocId }
      );
      setMessage({ text: res.message, ok: res.ok });
    } catch (e) {
      setMessage({ text: t("settings.audioInterface.saveError", { error: String(e) }), ok: false });
    } finally {
      setSaving(false);
    }
  };

  const fmtLoc = (lid: number) => `0x${lid.toString(16).toUpperCase().padStart(8, "0")} (${lid})`;

  return (
    <div className="stg-device-body">
      <div className="stg-desc-box">
        {t("settings.audioInterface.title")}<br />
        <span style={{ fontSize: "0.9em", color: "var(--text-dim)" }}>
          {t("settings.audioInterface.desc")}
        </span>
      </div>

      {/* 스캔 결과 테이블 */}
      <div style={{ marginTop: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <span className="stg-subsection-title" style={{ margin: 0 }}>🔌 {t("settings.audioInterface.connectedDevices")}</span>
          <button className="stg-btn-small" onClick={scan} disabled={scanning}>
            {scanning ? t("settings.audioInterface.scanning") : `🔄 ${t("settings.audioInterface.rescan")}`}
          </button>
        </div>

        {interfaces.length === 0 && !scanning && (
          <div style={{ color: "var(--text-dim)", fontSize: "0.9em" }}>{t("settings.audioInterface.noDevices")}</div>
        )}

        {interfaces.map((iface) => (
          <div key={iface.location_id}
            style={{
              background: "var(--bg-card, #1e1e2e)",
              border: "1px solid var(--border, #333)",
              borderRadius: 6,
              padding: "8px 12px",
              marginBottom: 6,
              fontSize: "0.88em",
              fontFamily: "monospace",
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 2 }}>{iface.name}</div>
            <div style={{ color: "var(--text-dim)" }}>
              LocationID: {fmtLoc(iface.location_id)}<br />
              IN: sd[{iface.sd_in_index ?? "?"}] ({iface.in_channels}ch) &nbsp;|&nbsp;
              OUT: sd[{iface.sd_out_index ?? "?"}] ({iface.out_channels}ch) &nbsp;|&nbsp;
              SR: {iface.sample_rate} Hz
            </div>
          </div>
        ))}
      </div>

      {/* 역할 할당 */}
      {interfaces.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="stg-subsection-title">📋 {t("settings.audioInterface.slotAssign")}</div>

          {/* Android 슬롯 */}
          <div className="stg-field-row" style={{ marginTop: 10 }}>
            <span className="stg-field-name">🤖 {t("settings.audioInterface.androidSlot")}</span>
            <span className="stg-field-hint">{t("settings.audioInterface.androidSlotHint")}</span>
            <select
              className="stg-select"
              value={androidLocId ?? ""}
              onChange={(e) => setAndroidLocId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">{t("settings.audioInterface.selectPlaceholder")}</option>
              {interfaces.map((iface) => (
                <option key={iface.location_id} value={iface.location_id}>
                  {iface.name} &nbsp; sd[{iface.sd_out_index ?? "?"}] &nbsp; {fmtLoc(iface.location_id)}
                </option>
              ))}
            </select>
          </div>

          {/* iOS 슬롯 */}
          <div className="stg-field-row" style={{ marginTop: 8 }}>
            <span className="stg-field-name">🍎 {t("settings.audioInterface.iosSlot")}</span>
            <span className="stg-field-hint">{t("settings.audioInterface.iosSlotHint")}</span>
            <select
              className="stg-select"
              value={iosLocId ?? ""}
              onChange={(e) => setIosLocId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">{t("settings.audioInterface.selectPlaceholder")}</option>
              {interfaces.map((iface) => (
                <option key={iface.location_id} value={iface.location_id}>
                  {iface.name} &nbsp; sd[{iface.sd_out_index ?? "?"}] &nbsp; {fmtLoc(iface.location_id)}
                </option>
              ))}
            </select>
          </div>

          <button
            className="stg-btn-primary"
            style={{ marginTop: 14 }}
            onClick={save}
            disabled={saving || androidLocId === null || iosLocId === null}
          >
            {saving ? t("settings.audioInterface.saving") : `💾 ${t("settings.audioInterface.saveButton")}`}
          </button>

          {message && (
            <div style={{
              marginTop: 8,
              padding: "6px 10px",
              borderRadius: 5,
              fontSize: "0.88em",
              background: message.ok ? "rgba(76,175,80,0.15)" : "rgba(244,67,54,0.15)",
              color: message.ok ? "#81c784" : "#e57373",
            }}>
              {message.ok ? "✅" : "❌"} {message.text}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


const TC_DEFS: { id: TcId; descKey: string }[] = [
  { id: "TC_00", descKey: "tc.descs.TC_00" },
  { id: "TC_01", descKey: "tc.descs.TC_01" },
  { id: "TC_02", descKey: "tc.descs.TC_02" },
  { id: "TC_03", descKey: "tc.descs.TC_03" },
  { id: "TC_04", descKey: "tc.descs.TC_04" },
];

// ── 화자 설정 탭용 재사용 필드 컴포넌트 (SettingsModal 외부 정의 필수 — 내부 정의 시 매 렌더마다 remount) ──

function TcSelectField({
  label, hint, field, options, entry, tcId, updateField,
}: {
  label: string; hint: string;
  field: keyof TcSpeakerEntry;
  options: { value: string; label: string }[];
  entry: TcSpeakerEntry; tcId: TcId;
  updateField: (tcId: TcId, field: keyof TcSpeakerEntry, value: string) => void;
}) {
  return (
    <div className="stg-file-row">
      <div className="stg-file-label">
        <span className="stg-field-name">{label}</span>
        <span className="stg-field-hint">{hint}</span>
      </div>
      {options.length > 0 ? (
        <select
          className="inp stg-file-inp"
          value={(entry[field] as string) ?? ""}
          onChange={(e) => updateField(tcId, field, e.target.value)}
        >
          <option value="">— 선택하세요 —</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      ) : (
        <input
          className="inp stg-file-inp"
          value={(entry[field] as string) ?? ""}
          placeholder="UDID 직접 입력"
          onChange={(e) => updateField(tcId, field, e.target.value)}
        />
      )}
    </div>
  );
}



interface Props {
  onClose: () => void;
  /** 연결된 iOS/Android 디바이스 목록 */
  deviceOptions?: { value: string; label: string }[];
  /** 오디오 출력 장치 목록 */
  audioOutputOptions?: { value: string; label: string }[];
  /** 음원 프로파일 훅 (선택 전달) */
  profileHook?: UseAudioProfilesResult;
  /** TC별 화자 설정 훅 — App.tsx에서 전달 시 모달 언마운트와 무관하게 상태 유지 */
  tcConfigApi?: ReturnType<typeof useTcSpeakerConfig>;
  /** 전역 화자 설정 */
  speaker1Device?: string;
  speaker2Device?: string;
  speaker1Number?: string;
  speaker2Number?: string;
  speaker1OutputDevice?: string;
  speaker2OutputDevice?: string;
  speaker1Channel?: string;
  speaker2Channel?: string;
  speaker1RecChannel?: string;
  speaker2RecChannel?: string;
  speaker1OutputPair?: string;
  speaker2OutputPair?: string;
  onSpeaker1DeviceChange?: (v: string) => void;
  onSpeaker2DeviceChange?: (v: string) => void;
  onSpeaker1NumberChange?: (v: string) => void;
  onSpeaker2NumberChange?: (v: string) => void;
  onSpeaker1OutputDeviceChange?: (v: string) => void;
  onSpeaker2OutputDeviceChange?: (v: string) => void;
  onSpeaker1ChannelChange?: (v: string) => void;
  onSpeaker2ChannelChange?: (v: string) => void;
  onSpeaker1RecChannelChange?: (v: string) => void;
  onSpeaker2RecChannelChange?: (v: string) => void;
  onSpeaker1OutputPairChange?: (v: string) => void;
  onSpeaker2OutputPairChange?: (v: string) => void;
  /** 공지사항 관련 */
  notices?: NoticeItem[];
  onAddNotice?: (text: string) => void;
  onUpdateNotice?: (id: string, text: string) => void;
  onDeleteNotice?: (id: string) => void;
  onMoveNoticeUp?: (id: string) => void;
  /** WDA 타겟 기기 선택 */
  iosDevices?: DeviceInfo[];
  wdaUdid?: string;
  onWdaUdidChange?: (v: string) => void;
}

type SettingsTab = "speaker" | "script" | "profile" | "device" | "audio_interface" | "recording" | "notice" | "license" | "language" | "app";

function filename(path: string) {
  return path ? path.split("/").pop() ?? path : "";
}

const SMTP_PW_ACCOUNT = "smtp-app-password";
const TEST_EMAIL_ADDR  = "m9.chapter1@gmail.com";
const FROM_EMAIL_ADDR  = "qabulls.test@gmail.com";

function SmtpPasswordField() {
  const { t } = useT();
  const [pw, setPw] = useState<string>("");
  const [show, setShow] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testStatus, setTestStatus] = useState<"idle" | "sending" | "ok" | "fail">("idle");
  const [testError, setTestError] = useState<string>("");

  // 앱 시작 시 Keychain에서 로드 (localStorage 평문 잔존 시 마이그레이션 후 삭제)
  useEffect(() => {
    invoke<string | null>("get_secret", { account: SMTP_PW_ACCOUNT })
      .then((val) => {
        if (val) {
          setPw(val);
        } else {
          // 이전 localStorage 평문이 남아있으면 Keychain으로 이전 후 삭제
          const legacy = localStorage.getItem("ixio-smtp-app-password");
          if (legacy) {
            invoke("store_secret", { account: SMTP_PW_ACCOUNT, secret: legacy })
              .then(() => {
                localStorage.removeItem("ixio-smtp-app-password");
                setPw(legacy);
              })
              .catch(console.warn);
          }
        }
      })
      .catch(console.warn);
  }, []);

  async function handleSave() {
    const trimmed = pw.trim();
    try {
      await invoke("store_secret", { account: SMTP_PW_ACCOUNT, secret: trimmed });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.warn("[keychain] 저장 실패:", e);
    }
  }

  async function handleTestSend() {
    const trimmed = pw.trim();
    if (!trimmed) { alert("앱 비밀번호를 먼저 저장해주세요."); return; }
    setTestStatus("sending");
    setTestError("");
    try {
      await invoke("send_stats_email", { payload: {
        fromAddr:    FROM_EMAIL_ADDR,
        appPassword: trimmed,
        toAddrs:     [TEST_EMAIL_ADDR],
        subject:     "[ixi-O] SMTP 테스트 발송",
        bodyHtml:    `<p>ixi-O 통화기능 테스트 — SMTP 발송 테스트 메일입니다.</p>
                      <p>발신: ${FROM_EMAIL_ADDR}<br>수신: ${TEST_EMAIL_ADDR}<br>
                      시각: ${new Date().toLocaleString("ko-KR")}</p>`,
        attachments: [],
      } });
      setTestStatus("ok");
      setTimeout(() => setTestStatus("idle"), 4000);
    } catch (e) {
      const msg = String(e);
      console.warn("[smtp] 테스트 발송 실패:", msg);
      setTestError(msg);
      setTestStatus("fail");
      setTimeout(() => { setTestStatus("idle"); setTestError(""); }, 10000);
    }
  }

  const testLabel =
    testStatus === "sending" ? "발송 중..." :
    testStatus === "ok"      ? "✓ 발송 완료" :
    testStatus === "fail"    ? "✗ 발송 실패" : "테스트 발송";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* 비밀번호 입력 행 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)", width: 160, flexShrink: 0 }}>
          {t("settings.recordingTab.gmailLabel")}
        </span>
        <input
          type={show ? "text" : "password"}
          value={pw}
          onChange={(e) => { setPw(e.target.value); setSaved(false); }}
          placeholder={t("settings.recordingTab.gmailPlaceholder")}
          maxLength={32}
          style={{
            flex: 1, fontSize: 13, padding: "5px 10px", borderRadius: 6,
            border: "1px solid var(--border-soft)", background: "var(--bg-input, #1a1f2e)",
            color: "var(--text-main)", fontFamily: "monospace", letterSpacing: show ? "normal" : "0.15em"
          }}
          onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }}
        />
        <button
          className="btn-xs"
          style={{ padding: "3px 8px", flexShrink: 0 }}
          onClick={() => setShow((s) => !s)}
          title={show ? t("settings.recordingTab.hidePw") : t("settings.recordingTab.showPw")}
        >
          {show ? t("settings.recordingTab.hidePw") : t("settings.recordingTab.showPw")}
        </button>
        <button
          className={`btn-xs ${saved ? "btn-ok" : "btn-accent"}`}
          style={{ flexShrink: 0 }}
          onClick={handleSave}
        >
          {saved ? t("settings.recordingTab.savedPw") : t("settings.recordingTab.savePw")}
        </button>
      </div>
      {/* 테스트 발송 행 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, paddingLeft: 168 }}>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          수신: {TEST_EMAIL_ADDR}
        </span>
        <button
          className={`btn-xs ${testStatus === "ok" ? "btn-ok" : testStatus === "fail" ? "btn-danger" : "btn-accent"}`}
          style={{ flexShrink: 0 }}
          disabled={testStatus === "sending"}
          onClick={handleTestSend}
        >
          {testLabel}
        </button>
      </div>
      {testError && (
        <div style={{ paddingLeft: 168, fontSize: 11, color: "var(--color-fail, #ff5252)", wordBreak: "break-all" }}>
          ❌ {testError}
        </div>
      )}
    </div>
  );
}

export function SettingsModal({
  onClose,
  deviceOptions = [],
  audioOutputOptions = [],
  profileHook,
  tcConfigApi,
  speaker1Device = "",
  speaker2Device = "",
  speaker1Number = "010-",
  speaker2Number = "010-",
  speaker1OutputDevice = "",
  speaker2OutputDevice = "",
  speaker1Channel = "",
  speaker2Channel = "",
  speaker1RecChannel = "",
  speaker2RecChannel = "",
  speaker1OutputPair = "",
  speaker2OutputPair = "",
  onSpeaker1DeviceChange,
  onSpeaker2DeviceChange,
  onSpeaker1NumberChange,
  onSpeaker2NumberChange,
  onSpeaker1OutputDeviceChange,
  onSpeaker2OutputDeviceChange,
  onSpeaker1ChannelChange,
  onSpeaker2ChannelChange,
  onSpeaker1RecChannelChange,
  onSpeaker2RecChannelChange,
  onSpeaker1OutputPairChange,
  onSpeaker2OutputPairChange,
  notices = [],
  onAddNotice,
  onUpdateNotice,
  onDeleteNotice,
  onMoveNoticeUp,
  iosDevices = [],
  wdaUdid = "",
  onWdaUdidChange,
}: Props) {
  const { lang, setLang, t } = useT();
  // built-in 프로파일 ID → 번역명 반환 (사용자 추가 프로파일은 저장된 name 그대로)
  const profileDisplayName = (p: AudioProfile) => {
    if (p.id === "daily")    return t("profiles.daily");
    if (p.id === "phishing") return t("profiles.phishing");
    if (p.id === "dating")   return t("profiles.dating");
    return p.name;
  };
  // 공지사항 편집 상태
  const [noticeInput, setNoticeInput] = useState("");
  const [editingNoticeId, setEditingNoticeId] = useState<string | null>(null);
  const [editingNoticeText, setEditingNoticeText] = useState("");
  const _internalCfg = useTcSpeakerConfig();
  const { getEntry, updateField, clearEntry, hasConfig } = tcConfigApi ?? _internalCfg;
  const [selectedTc, setSelectedTc] = useState<TcId>("TC_01");
  const [activeTab, setActiveTab] = useState<SettingsTab>("speaker");

  // 프로파일 탭 상태
  const [editingProfileId, setEditingProfileId] =
    useState<string>(() => profileHook?.profiles[0]?.id ?? "");
  const [newProfileName, setNewProfileName] = useState("");
  const [addingTab, setAddingTab] = useState(false);

  // 파일 저장 방식 상태 (localStorage 유지)
  const [recordingMode, setRecordingMode] = useState<"extract" | "direct">(
    () => (localStorage.getItem("recordingMode") as "extract" | "direct") || "extract"
  );
  const handleRecordingMode = (mode: "extract" | "direct") => {
    setRecordingMode(mode);
    localStorage.setItem("recordingMode", mode);
  };

  // MOS 측정 ON/OFF 상태 (localStorage 유지)
  const [mosMeasurementEnabled, setMosMeasurementEnabled] = useState<boolean>(
    () => localStorage.getItem("mosMeasurementEnabled") !== "false"
  );
  const handleMosMeasurementEnabled = (enabled: boolean) => {
    setMosMeasurementEnabled(enabled);
    localStorage.setItem("mosMeasurementEnabled", enabled ? "true" : "false");
  };

  // 라이선스 아코디언 — 하나만 열기
  const [openLicense, setOpenLicense] = useState<string | null>(null);

  // 앱 설정 상태 (localStorage 유지)
  const [appConfig, setAppConfig] = useState<TargetAppConfig>(() => {
    try {
      return JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG;
    } catch { return DEFAULT_APP_CONFIG; }
  });
  useEffect(() => {
    const onSync = () => {
      try {
        setAppConfig(JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG);
      } catch { /* ignore */ }
    };
    window.addEventListener("targetAppConfigChanged", onSync);
    return () => window.removeEventListener("targetAppConfigChanged", onSync);
  }, []);
  const handleAppConfig = (key: keyof TargetAppConfig, value: string) => {
    const next = { ...appConfig, [key]: value };
    setAppConfig(next);
    localStorage.setItem("targetAppConfig", JSON.stringify(next));
    window.dispatchEvent(new Event("targetAppConfigChanged"));
  };

  const entry = getEntry(selectedTc);

  return (
    <div className="stg-overlay" onMouseDown={onClose}>
      <div className="stg-modal" onMouseDown={(e) => e.stopPropagation()}>
        {/* ── 헤더 ── */}
        <div className="stg-header">
          <span className="stg-title">⚙ {t("settings.title")}</span>
          <button className="btn-close-red" onClick={onClose}>✕</button>
        </div>

        {/* ── 탭 ── */}
        <div className="stg-tabs">
          <button
            className={`stg-tab${activeTab === "speaker" ? " active" : ""}`}
            onClick={() => setActiveTab("speaker")}
          >
            🎤 {t("settings.tabs.speaker")}
          </button>
          <button
            className={`stg-tab${activeTab === "profile" ? " active" : ""}`}
            onClick={() => setActiveTab("profile")}
          >
            🎵 {t("settings.tabs.profile")}
          </button>
          <button
            className={`stg-tab${activeTab === "script" ? " active" : ""}`}
            onClick={() => setActiveTab("script")}
          >
            📄 {t("settings.tabs.script")}
          </button>
          <button
            className={`stg-tab${activeTab === "device" ? " active" : ""}`}
            onClick={() => setActiveTab("device")}
          >
            📱 {t("settings.tabs.device")}
          </button>
          <button
            className={`stg-tab${activeTab === "audio_interface" ? " active" : ""}`}
            onClick={() => setActiveTab("audio_interface")}
          >
            🔌 {t("settings.tabs.audioInterface")}
          </button>
          <button
            className={`stg-tab${activeTab === "recording" ? " active" : ""}`}
            onClick={() => setActiveTab("recording")}
          >
            💾 {t("settings.tabs.recording")}
          </button>
          <button
            className={`stg-tab${activeTab === "app" ? " active" : ""}`}
            onClick={() => setActiveTab("app")}
          >
            📦 {t("settings.tabs.app")}
          </button>
          <button
            className={`stg-tab${activeTab === "notice" ? " active" : ""}`}
            onClick={() => setActiveTab("notice")}
          >
            📢 {t("settings.tabs.notice")}
          </button>
          <button
            className={`stg-tab${activeTab === "license" ? " active" : ""}`}
            onClick={() => setActiveTab("license")}
          >
            📜 {t("settings.tabs.license")}
          </button>
          <button
            className={`stg-tab${activeTab === "language" ? " active" : ""}`}
            onClick={() => setActiveTab("language")}
          >
            🌐 {t("settings.tabs.language")}
          </button>
        </div>

        {/* ════════════════════════════════════════════════════════════
             음원 프로파일 탭 — TC 사이드바 없이 전체폭 독립 패널
            ════════════════════════════════════════════════════════════ */}
        {activeTab === "profile" && (() => {
          const ph = profileHook;
          if (!ph) return (
            <div className="stg-body">
              <div className="stg-desc-box" style={{ color: "#ff9800", gridColumn: "1/-1" }}>
                {t("settings.profileTab.noProfile")}
              </div>
            </div>
          );
          const ep = ph.profiles.find((p) => p.id === editingProfileId) ?? ph.profiles[0];

          async function pickFile(field: keyof AudioProfile) {
            const result = await open({
              filters: [{ name: "오디오 파일", extensions: ["wav", "mp3", "m4a", "flac"] }],
              multiple: false,
            });
            if (typeof result === "string" && result) {
              ph!.updateProfile(ep.id, { [field]: result } as Partial<AudioProfile>);
            }
          }
          const upd = (field: keyof AudioProfile, val: string) =>
            ph.updateProfile(ep.id, { [field]: val } as Partial<AudioProfile>);

          return (
            <div className="stg-profile-body">
              {/* 프로파일 시트탭 */}
              <div className="stg-sheet-tab-bar">
                {ph.profiles.map((p) => (
                  <button
                    key={p.id}
                    className={`stg-sheet-tab${editingProfileId === p.id ? " active" : ""}`}
                    onClick={() => setEditingProfileId(p.id)}
                  >
                    {profileDisplayName(p)}
                    {(p.refAudioPathS1 || p.refAudioPathS2 || p.refAudioPath) && <span className="stg-sheet-tab-dot" title={t("settings.profileTab.refSet")} />}
                  </button>
                ))}
                {addingTab ? (
                  <input
                    className="stg-sheet-tab-new-inp"
                    autoFocus
                    value={newProfileName}
                    placeholder={t("settings.profileTab.namePlaceholder")}
                    onChange={(e) => setNewProfileName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && newProfileName.trim()) {
                        const np = ph.addProfile(newProfileName.trim());
                        setEditingProfileId(np.id);
                        setNewProfileName("");
                        setAddingTab(false);
                      }
                      if (e.key === "Escape") { setAddingTab(false); setNewProfileName(""); }
                    }}
                    onBlur={() => { setAddingTab(false); setNewProfileName(""); }}
                  />
                ) : (
                  <button className="stg-sheet-tab-add" onClick={() => setAddingTab(true)}>＋ {t("settings.profileTab.add")}</button>
                )}
              </div>

              {!ep ? (
                <div className="stg-sheet-content"><div className="stg-desc-box">{t("settings.profileTab.empty")}</div></div>
              ) : (
                <div className="stg-sheet-content">
                <>
                  {/* 삭제 버튼 (기본 제외) */}
                  {ep.id !== "phishing" && ep.id !== "daily" && ep.id !== "dating" && (
                    <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
                      <button
                        className="btn-xs btn-danger"
                        onClick={() => {
                          ph.removeProfile(ep.id);
                          setEditingProfileId(ph.profiles[0]?.id ?? "");
                        }}
                      >🗑 {t("settings.profileTab.deleteProfile")}</button>
                    </div>
                  )}

                  {/* 이름 */}
                  <div className="stg-file-row">
                    <div className="stg-file-label"><span className="stg-field-name">{t("settings.profileTab.profileName")}</span></div>
                    <input className="inp stg-file-inp" value={ep.name}
                      onChange={(e) => upd("name", e.target.value)} />
                  </div>

                  {/* S1 */}
                  <div className="stg-subsection-title" style={{ marginTop: 12 }}>🔊 {t("settings.profileTab.s1Audio")}</div>
                  <div className="stg-file-row">
                    <div className="stg-file-label">
                      <span className="stg-field-name">{t("settings.profileTab.audioFile")}</span>
                      <span className="stg-field-hint">{t("settings.profileTab.s1Hint")}</span>
                    </div>
                    <div className="stg-file-input-row">
                      <input className="inp stg-file-inp" readOnly
                        value={filename(ep.speaker1AudioFile)}
                        placeholder={t("settings.profileTab.selectFile")} title={ep.speaker1AudioFile} />
                      <button className="btn-xs btn-accent" onClick={() => pickFile("speaker1AudioFile")}>📁 {t("settings.profileTab.select")}</button>
                      {ep.speaker1AudioFile && (
                        <button className="btn-xs btn-ghost stg-clear-btn"
                          onClick={() => upd("speaker1AudioFile", "")} title={t("settings.profileTab.reset")}>✕</button>
                      )}
                    </div>
                  </div>

                  {/* S2 */}
                  <div className="stg-subsection-title" style={{ marginTop: 12 }}>🔊 {t("settings.profileTab.s2Audio")}</div>
                  <div className="stg-file-row">
                    <div className="stg-file-label">
                      <span className="stg-field-name">{t("settings.profileTab.audioFile")}</span>
                      <span className="stg-field-hint">{t("settings.profileTab.s2Hint")}</span>
                    </div>
                    <div className="stg-file-input-row">
                      <input className="inp stg-file-inp" readOnly
                        value={filename(ep.speaker2AudioFile)}
                        placeholder={t("settings.profileTab.selectFile")} title={ep.speaker2AudioFile} />
                      <button className="btn-xs btn-accent" onClick={() => pickFile("speaker2AudioFile")}>📁 {t("settings.profileTab.select")}</button>
                      {ep.speaker2AudioFile && (
                        <button className="btn-xs btn-ghost stg-clear-btn"
                          onClick={() => upd("speaker2AudioFile", "")} title={t("settings.profileTab.reset")}>✕</button>
                      )}
                    </div>
                  </div>

                  {/* 정답지 — 화자별 분리 */}
                  <div className="stg-subsection-title" style={{ marginTop: 14 }}>🎯 {t("settings.profileTab.refAudio")}</div>
                  <div className="stg-file-row">
                    <div className="stg-file-label">
                      <span className="stg-field-name">{t("settings.profileTab.refS1")}</span>
                      <span className="stg-field-hint">{t("settings.profileTab.refS1Hint")}</span>
                    </div>
                    <div className="stg-file-input-row">
                      <input className="inp stg-file-inp" readOnly
                        value={filename(ep.refAudioPathS1)}
                        placeholder={t("settings.profileTab.selectFile")} title={ep.refAudioPathS1} />
                      <button className="btn-xs btn-accent" onClick={() => pickFile("refAudioPathS1")}>📁 {t("settings.profileTab.select")}</button>
                      {ep.refAudioPathS1 && (
                        <button className="btn-xs btn-ghost stg-clear-btn"
                          onClick={() => upd("refAudioPathS1", "")} title={t("settings.profileTab.reset")}>✕</button>
                      )}
                    </div>
                    {ep.refAudioPathS1 && (
                      <div className="stg-full-path" title={ep.refAudioPathS1}>{ep.refAudioPathS1}</div>
                    )}
                  </div>
                  <div className="stg-file-row">
                    <div className="stg-file-label">
                      <span className="stg-field-name">{t("settings.profileTab.refS2")}</span>
                      <span className="stg-field-hint">{t("settings.profileTab.refS2Hint")}</span>
                    </div>
                    <div className="stg-file-input-row">
                      <input className="inp stg-file-inp" readOnly
                        value={filename(ep.refAudioPathS2)}
                        placeholder={t("settings.profileTab.selectFile")} title={ep.refAudioPathS2} />
                      <button className="btn-xs btn-accent" onClick={() => pickFile("refAudioPathS2")}>📁 {t("settings.profileTab.select")}</button>
                      {ep.refAudioPathS2 && (
                        <button className="btn-xs btn-ghost stg-clear-btn"
                          onClick={() => upd("refAudioPathS2", "")} title={t("settings.profileTab.reset")}>✕</button>
                      )}
                    </div>
                    {ep.refAudioPathS2 && (
                      <div className="stg-full-path" title={ep.refAudioPathS2}>{ep.refAudioPathS2}</div>
                    )}
                  </div>
                </>
                </div>
              )}
            </div>
          );
        })()}

        {/* ════════════════════════════════════════════════════════════
             음원 대본 탭 — 프로파일 시트탭 + scriptPath 설정
            ════════════════════════════════════════════════════════════ */}
        {activeTab === "script" && (() => {
          const ph = profileHook;
          if (!ph) return (
            <div className="stg-profile-body">
              <div className="stg-desc-box" style={{ color: "#ff9800" }}>{t("settings.profileTab.noProfile")}</div>
            </div>
          );
          const sp = ph.profiles.find((p) => p.id === editingProfileId) ?? ph.profiles[0];
          const updScript = (val: string) =>
            ph.updateProfile(sp.id, { scriptPath: val } as Partial<AudioProfile>);
          async function pickScriptFile() {
            const result = await open({
              filters: [{ name: "대본 파일", extensions: ["txt"] }],
              multiple: false,
            });
            if (typeof result === "string" && result) updScript(result);
          }
          return (
            <div className="stg-profile-body">
              {/* 스크립트 탭 - 프로파일 시트탭 */}
              <div className="stg-sheet-tab-bar">
                {ph.profiles.map((p) => (
                  <button
                    key={p.id}
                    className={`stg-sheet-tab${editingProfileId === p.id ? " active" : ""}`}
                    onClick={() => setEditingProfileId(p.id)}
                  >
                    {profileDisplayName(p)}
                    {p.scriptPath && <span className="stg-sheet-tab-dot" title={t("settings.scriptTab.scriptSet")} />}
                  </button>
                ))}
              </div>
              {!sp ? (
                <div className="stg-sheet-content"><div className="stg-desc-box">{t("settings.profileTab.empty")}</div></div>
              ) : (
                <div className="stg-sheet-content">
                  <div className="stg-desc-box">
                    {t("settings.scriptTab.desc", { name: sp ? profileDisplayName(sp) : "" })}
                  </div>
                  <div className="stg-subsection-title" style={{ marginTop: 14 }}>📄 {t("settings.scriptTab.scriptFile")}</div>
                  <div className="stg-file-row">
                    <div className="stg-file-label">
                      <span className="stg-field-name">{t("settings.scriptTab.scriptTxt")}</span>
                      <span className="stg-field-hint">{t("settings.scriptTab.formatHint")}</span>
                    </div>
                    <div className="stg-file-input-row">
                      <input className="inp stg-file-inp" readOnly
                        value={filename(sp.scriptPath)}
                        placeholder={t("settings.scriptTab.selectPlaceholder")} title={sp.scriptPath} />
                      <button className="btn-xs btn-accent" onClick={pickScriptFile}>📁 {t("settings.scriptTab.register")}</button>
                      {sp.scriptPath && (
                        <button className="btn-xs btn-ghost stg-clear-btn"
                          onClick={() => updScript("")} title={t("settings.profileTab.reset")}>✕</button>
                      )}
                    </div>
                    {sp.scriptPath && (
                      <div className="stg-full-path" title={sp.scriptPath}>{sp.scriptPath}</div>
                    )}
                  </div>
                  <div className="stg-script-format" style={{ marginTop: 18 }}>
                    <div className="stg-format-title">📋 {t("settings.scriptTab.formatTitle")}</div>
                    <pre className="stg-format-code">{t("settings.scriptTab.formatExample")}</pre>
                  </div>
                </div>
              )}
            </div>
          );
        })()}

        {/* ════════════════════════════════════════════════════════════
             화자 설정 탭 — TC 사이드바 + 메인 패널
            ════════════════════════════════════════════════════════════ */}
        {activeTab === "speaker" && (
          <div className="stg-body">
            {/* ── 사이드바: TC 목록 ── */}
            <aside className="stg-sidebar">
              {TC_DEFS.filter((tc) => TC_ENABLED[tc.id]).map((tc) => (
                <button
                  key={tc.id}
                  className={`stg-tc-btn${selectedTc === tc.id ? " active" : ""}`}
                  onClick={() => setSelectedTc(tc.id)}
                >
                  <span className="stg-tc-id">{tc.id}</span>
                  <span className="stg-tc-desc">{t(tc.descKey)}</span>
                  {hasConfig(tc.id) && (
                    <span className="stg-tc-dot stg-dot-audio" title={t("settings.speakerTab.configured")} />
                  )}
                </button>
              ))}
            </aside>

            {/* ── 메인 패널 ── */}
            <section className="stg-main">
              <div className="stg-section-title">
                <span className="stg-tc-id-lg">{selectedTc}</span>
                &nbsp;—&nbsp;
                {t(TC_DEFS.find((tc) => tc.id === selectedTc)?.descKey ?? "")}
              </div>

              <div className="stg-desc-box">
                {t("settings.speakerTab.desc")}<br />
                <span style={{ fontSize: "0.9em", color: "var(--text-dim)" }}>
                  {t("settings.speakerTab.descHint")}
                </span>
              </div>

              <div className="stg-subsection-title">📱 {t("settings.speakerTab.device")}</div>
              <TcSelectField label={t("settings.speakerTab.s1Device")} hint="S1 단말 UDID"
                field="speaker1Device" options={deviceOptions}
                entry={entry} tcId={selectedTc} updateField={updateField} />
              <TcSelectField label={t("settings.speakerTab.s2Device")} hint="S2 단말 UDID"
                field="speaker2Device" options={deviceOptions}
                entry={entry} tcId={selectedTc} updateField={updateField} />

              <div className="stg-subsection-title" style={{ marginTop: 16 }}>🎵 {t("settings.tabs.profile")}</div>
              <div className="stg-file-row">
                <div className="stg-file-label">
                  <span className="stg-field-name">{t("settings.speakerTab.profile")}</span>
                  <span className="stg-field-hint">{t("settings.speakerTab.profileHint")}</span>
                </div>
                {profileHook && profileHook.profiles.length > 0 ? (
                  <select
                    className="inp stg-file-inp"
                    value={entry.profileId ?? ""}
                    onChange={(e) => updateField(selectedTc, "profileId", e.target.value)}
                  >
                    <option value="">— {t("settings.speakerTab.globalProfile")} —</option>
                    {profileHook.profiles.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                ) : (
                  <span style={{ color: "var(--text-dim)", fontSize: "0.9em" }}>
                    {t("settings.speakerTab.noProfile")}
                  </span>
                )}
              </div>

              {hasConfig(selectedTc) && (
                <button className="btn-xs btn-danger stg-reset-btn"
                  onClick={() => clearEntry(selectedTc)}>
                  🗑 {selectedTc} {t("settings.speakerTab.reset")}
                </button>
              )}
            </section>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════
             단말/전화번호 탭 — 전역 화자1·화자2 디바이스 & 번호 설정
            ════════════════════════════════════════════════════════════ */}
        {activeTab === "device" && (
          <div className="stg-device-body">
            <div className="stg-desc-box">
              {t("settings.deviceTab.desc")}
            </div>

            {/* ── S1 ── */}
            <div className="stg-subsection-title" style={{ marginTop: 14 }}>📱 S1 {t("settings.deviceTab.s1Title")}</div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.device")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s1UDID")}</span>
              </div>
              {deviceOptions.length > 0 ? (
                <select className="inp stg-file-inp" value={speaker1Device}
                  onChange={(e) => onSpeaker1DeviceChange?.(e.target.value)}>
                  <option value="">—</option>
                  {deviceOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              ) : (
                <input className="inp stg-file-inp" value={speaker1Device}
                  placeholder={t("settings.deviceTab.udidPlaceholder")}
                  onChange={(e) => onSpeaker1DeviceChange?.(e.target.value)} />
              )}
            </div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.phone")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s1PhoneHint")}</span>
              </div>
              <input className="inp stg-file-inp" value={speaker1Number}
                placeholder="010-0000-0000" maxLength={13}
                onChange={(e) => onSpeaker1NumberChange?.(formatPhoneInput(e.target.value))}
                onFocus={(e) => { if (!e.target.value) onSpeaker1NumberChange?.("010-"); }} />
            </div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.output")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s1OutputHint")}</span>
              </div>
              <select className="inp stg-file-inp" value={speaker1OutputDevice}
                onChange={(e) => onSpeaker1OutputDeviceChange?.(e.target.value)}>
                <option value="">{t("settings.deviceTab.defaultOutput")}</option>
                {audioOutputOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.channel")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s1ChannelHint")}</span>
              </div>
              <select className="inp stg-file-inp" value={speaker1Channel}
                onChange={(e) => onSpeaker1ChannelChange?.(e.target.value)}>
                <option value="">{t("settings.deviceTab.bothCh")}</option>
                <option value="L">L ({t("settings.deviceTab.left")})</option>
                <option value="R">R ({t("settings.deviceTab.right")})</option>
              </select>
            </div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.recChannel")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s1RecHint")}</span>
              </div>
              <select className="inp stg-file-inp" value={speaker1RecChannel}
                onChange={(e) => onSpeaker1RecChannelChange?.(e.target.value)}>
                <option value="">{t("settings.deviceTab.auto")}</option>
                <option value="0">Ch 1 — Input 1 (iPhone)</option>
                <option value="1">Ch 2 — Input 2 (Android)</option>
                <option value="2,3">Ch 3-4 — Aux In</option>
                <option value="4,5">Ch 5-6 — Mobile In</option>
                <option value="6,7">Ch 7-8 — Loopback 1 (Mix A)</option>
                <option value="12,13">Ch 13-14 — Loopback 2 (Mix B)</option>
              </select>
            </div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.outputPair")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s1OutputPairHint")}</span>
              </div>
              <select className="inp stg-file-inp" value={speaker1OutputPair}
                onChange={(e) => onSpeaker1OutputPairChange?.(e.target.value)}>
                <option value="">Out 1/2 ({t("settings.deviceTab.defaultOutput")})</option>
                <option value="0,1">Out 1/2</option>
                <option value="2,3">Out 3/4</option>
                <option value="4,5">Out 5/6</option>
                <option value="6,7">Out 7/8</option>
              </select>
            </div>

            {/* ── S2 ── */}
            <div className="stg-subsection-title" style={{ marginTop: 16 }}>📱 S2 {t("settings.deviceTab.s2Title")}</div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.device")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s2UDID")}</span>
              </div>
              {deviceOptions.length > 0 ? (
                <select className="inp stg-file-inp" value={speaker2Device}
                  onChange={(e) => onSpeaker2DeviceChange?.(e.target.value)}>
                  <option value="">—</option>
                  {deviceOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              ) : (
                <input className="inp stg-file-inp" value={speaker2Device}
                  placeholder={t("settings.deviceTab.udidPlaceholder")}
                  onChange={(e) => onSpeaker2DeviceChange?.(e.target.value)} />
              )}
            </div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.phone")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s2PhoneHint")}</span>
              </div>
              <input className="inp stg-file-inp" value={speaker2Number}
                placeholder="010-0000-0000" maxLength={13}
                onChange={(e) => onSpeaker2NumberChange?.(formatPhoneInput(e.target.value))}
                onFocus={(e) => { if (!e.target.value) onSpeaker2NumberChange?.("010-"); }} />
            </div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.output")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s2OutputHint")}</span>
              </div>
              <select className="inp stg-file-inp" value={speaker2OutputDevice}
                onChange={(e) => onSpeaker2OutputDeviceChange?.(e.target.value)}>
                <option value="">{t("settings.deviceTab.defaultOutput")}</option>
                {audioOutputOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.channel")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s2ChannelHint")}</span>
              </div>
              <select className="inp stg-file-inp" value={speaker2Channel}
                onChange={(e) => onSpeaker2ChannelChange?.(e.target.value)}>
                <option value="">{t("settings.deviceTab.bothCh")}</option>
                <option value="L">L ({t("settings.deviceTab.left")})</option>
                <option value="R">R ({t("settings.deviceTab.right")})</option>
              </select>
            </div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.recChannel")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s2RecHint")}</span>
              </div>
              <select className="inp stg-file-inp" value={speaker2RecChannel}
                onChange={(e) => onSpeaker2RecChannelChange?.(e.target.value)}>
                <option value="">{t("settings.deviceTab.auto")}</option>
                <option value="0">Ch 1 — Input 1 (iPhone)</option>
                <option value="1">Ch 2 — Input 2 (Android)</option>
                <option value="2,3">Ch 3-4 — Aux In</option>
                <option value="4,5">Ch 5-6 — Mobile In</option>
                <option value="6,7">Ch 7-8 — Loopback 1 (Mix A)</option>
                <option value="12,13">Ch 13-14 — Loopback 2 (Mix B)</option>
              </select>
            </div>
            <div className="stg-file-row">
              <div className="stg-file-label">
                <span className="stg-field-name">{t("settings.deviceTab.outputPair")}</span>
                <span className="stg-field-hint">{t("settings.deviceTab.s2OutputPairHint")}</span>
              </div>
              <select className="inp stg-file-inp" value={speaker2OutputPair}
                onChange={(e) => onSpeaker2OutputPairChange?.(e.target.value)}>
                <option value="">Out 1/2 ({t("settings.deviceTab.defaultOutput")})</option>
                <option value="0,1">Out 1/2</option>
                <option value="2,3">Out 3/4</option>
                <option value="4,5">Out 5/6</option>
                <option value="6,7">Out 7/8</option>
              </select>
            </div>

            {/* ── WDA 타겟 기기 ── */}
            {iosDevices.length > 1 && (
              <>
                <div className="stg-subsection-title" style={{ marginTop: 16 }}>📱 WDA</div>
                <div className="stg-file-row">
                  <div className="stg-file-label">
                    <span className="stg-field-name">{t("settings.deviceTab.wdaDevice")}</span>
                    <span className="stg-field-hint">{t("settings.deviceTab.wdaDeviceHint")}</span>
                  </div>
                  <select className="inp stg-file-inp" value={wdaUdid}
                    onChange={(e) => onWdaUdidChange?.(e.target.value)}>
                    <option value="">{t("device.wdaAutoSelect")}</option>
                    {iosDevices.map((d) => (
                      <option key={d.udid} value={d.udid}>
                        {d.name} ({d.udid.slice(0, 8)}…)
                      </option>
                    ))}
                  </select>
                </div>
              </>
            )}
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════
             오디오 인터페이스 탭 — CONNECT 6 × 2대 할당 고정
            ════════════════════════════════════════════════════════════ */}
        {activeTab === "audio_interface" && (
          <AudioInterfaceTab />
        )}

        {/* ════════════════════════════════════════════════════════════
             파일 저장 방식 탭 — 파일 추출 / 직접 녹음 라디오 선택
            ════════════════════════════════════════════════════════════ */}
        {activeTab === "recording" && (
          <div className="stg-device-body">
            <div className="stg-desc-box">
              {t("settings.recordingTab.desc")}<br />
              <span style={{ fontSize: "0.9em", color: "var(--text-dim)" }}>
                {t("settings.recordingTab.descHint")}
              </span>
            </div>

            <div className="stg-radio-group">
              {/* ── 파일 추출 방식 ── */}
              <label className={`stg-radio-card${recordingMode === "extract" ? " active" : ""}`}>
                <input
                  type="radio" name="recordingMode" value="extract"
                  checked={recordingMode === "extract"}
                  onChange={() => handleRecordingMode("extract")}
                />
                <div className="stg-radio-content">
                  <div className="stg-radio-title">📂 {t("settings.recordingTab.extractTitle")}</div>
                  <div className="stg-radio-desc">
                    {t("settings.recordingTab.extractDesc")}
                  </div>
                  {recordingMode === "extract"
                    ? <span className="stg-radio-badge stg-badge-current">{t("settings.recordingTab.current")}</span>
                    : <span className="stg-radio-badge stg-badge-upcoming">{t("settings.recordingTab.deselected")}</span>
                  }
                </div>
              </label>

              {/* ── 직접 녹음 방식 ── */}
              <label className={`stg-radio-card${recordingMode === "direct" ? " active" : ""}`}>
                <input
                  type="radio" name="recordingMode" value="direct"
                  checked={recordingMode === "direct"}
                  onChange={() => handleRecordingMode("direct")}
                />
                <div className="stg-radio-content">
                  <div className="stg-radio-title">🎙️ {t("settings.recordingTab.directTitle")}</div>
                  <div className="stg-radio-desc">
                    {t("settings.recordingTab.directDesc")}
                    <br />{t("settings.recordingTab.directChannelHint")}
                  </div>
                  {recordingMode === "direct"
                    ? <span className="stg-radio-badge stg-badge-current">{t("settings.recordingTab.current")}</span>
                    : <span className="stg-radio-badge stg-badge-upcoming">{t("settings.recordingTab.directReq")}</span>
                  }
                </div>
              </label>
            </div>

            {/* ── 마일스톤 이메일 알림 ── */}
            {FEATURE_ENABLED.MILESTONE_EMAIL_PANEL && (
            <div style={{ borderTop: "1px solid var(--border-soft)", marginTop: 20, paddingTop: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "var(--accent)", marginBottom: 10 }}>
                {t("settings.recordingTab.emailTitle")}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
                {t("settings.recordingTab.emailDesc")}<br />
                {t("settings.recordingTab.emailAccounts")}
              </div>
              <SmtpPasswordField />
            </div>
            )}

            {/* ── MOS 측정 ON/OFF ── */}
            <div style={{ borderTop: "1px solid var(--border-soft)", marginTop: 20, paddingTop: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "var(--accent)", marginBottom: 8 }}>
                📈 {t("settings.recordingTab.mosMeasurementTitle")}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
                {t("settings.recordingTab.mosMeasurementDesc")}
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <button
                  className={`btn-xs${mosMeasurementEnabled ? " btn-ok" : ""}`}
                  style={{ minWidth: 72 }}
                  onClick={() => handleMosMeasurementEnabled(true)}
                >
                  ✅ ON
                </button>
                <button
                  className={`btn-xs${!mosMeasurementEnabled ? " btn-danger" : ""}`}
                  style={{ minWidth: 72 }}
                  onClick={() => handleMosMeasurementEnabled(false)}
                >
                  ⛔ OFF
                </button>
                <span style={{ fontSize: 12, color: mosMeasurementEnabled ? "var(--color-pass, #66bb6a)" : "var(--color-fail, #ff5252)", alignSelf: "center" }}>
                  {mosMeasurementEnabled ? t("settings.recordingTab.mosOn") : t("settings.recordingTab.mosOff")}
                </span>
              </div>
            </div>
          </div>
        )}
        {/* ════════════════════════════════════════════════════════════
             공지사항 탭
            ════════════════════════════════════════════════════════════ */}
        {activeTab === "notice" && (
          <div className="stg-body stg-notice-body">
            {/* 작성 영역 */}
            <div className="stg-notice-compose">
              <div className="stg-notice-compose-title">{t("settings.noticeTab.compose")}</div>
              <textarea
                className="stg-notice-textarea"
                value={noticeInput}
                onChange={(e) => setNoticeInput(e.target.value)}
                placeholder={t("settings.noticeTab.placeholder")}
                rows={3}
              />
              <div className="stg-notice-compose-actions">
                <button
                  className="btn-xs btn-accent"
                  disabled={!noticeInput.trim()}
                  onClick={() => {
                    if (noticeInput.trim()) {
                      onAddNotice?.(noticeInput.trim());
                      setNoticeInput("");
                    }
                  }}
                >
                  ＋ {t("settings.noticeTab.add")}
                </button>
              </div>
            </div>

            {/* 공지 목록 */}
            <div className="stg-notice-list-label">{t("settings.noticeTab.listLabel", { count: notices.length })}</div>
            {notices.length === 0 ? (
              <div className="stg-notice-empty">{t("settings.noticeTab.empty")}</div>
            ) : (
              <div className="stg-notice-list">
                {notices.map((n, i) => (
                  <div className="stg-notice-item" key={n.id}>
                    {editingNoticeId === n.id ? (
                      <div className="stg-notice-edit-wrap">
                        <textarea
                          className="stg-notice-textarea"
                          value={editingNoticeText}
                          onChange={(e) => setEditingNoticeText(e.target.value)}
                          rows={2}
                          autoFocus
                        />
                        <div className="stg-notice-edit-btns">
                          <button className="btn-xs btn-accent" onClick={() => {
                            onUpdateNotice?.(n.id, editingNoticeText);
                            setEditingNoticeId(null);
                          }}>{t("settings.noticeTab.save")}</button>
                          <button className="btn-xs btn-ghost" onClick={() => setEditingNoticeId(null)}>{t("settings.noticeTab.cancel")}</button>
                        </div>
                      </div>
                    ) : (
                      <div className="stg-notice-item-inner">
                        <div className="stg-notice-item-meta">
                          <span className="stg-notice-idx">{i + 1}</span>
                          <span className="stg-notice-date">{n.createdAt}</span>
                        </div>
                        <div className="stg-notice-item-text">{n.text}</div>
                        <div className="stg-notice-item-actions">
                          {i > 0 && (
                            <button className="btn-xs btn-ghost" title={t("settings.noticeTab.up")} onClick={() => onMoveNoticeUp?.(n.id)}>↑</button>
                          )}
                          <button className="btn-xs btn-ghost" onClick={() => {
                            setEditingNoticeId(n.id);
                            setEditingNoticeText(n.text);
                          }}>✏️ {t("settings.noticeTab.edit")}</button>
                          <button className="btn-xs btn-danger" onClick={() => onDeleteNotice?.(n.id)}>{t("settings.noticeTab.delete")}</button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {/* ════════════════════════════════════════════════════════════
             오픈소스 라이선스 탭
            ════════════════════════════════════════════════════════════ */}
        {activeTab === "license" && (
          <div className="stg-body" style={{ flexDirection: "column", overflow: "auto", padding: "16px 20px" }}>
            <div className="stg-desc-box" style={{ marginBottom: 16, color: "#ffffff" }}>
              {t("settings.licenseTab.desc")}
            </div>
            {LICENSE_GROUPS.map((g) => (
              <div key={g.license} className={`lic-group${openLicense === g.license ? " open" : ""}`}>
                <div className="lic-summary" onClick={() => setOpenLicense(openLicense === g.license ? null : g.license)}>
                  <span className="lic-name">{g.license}</span>
                  <span className="lic-count">{g.packages.length}{t("settings.licenseTab.pkgCount")}</span>
                </div>
                {openLicense === g.license && (
                  <>
                    <div className="lic-packages">
                      {g.packages.map((p) => (
                        <span key={p.name} className="lic-pkg">{p.name} <span className="lic-ver">v{p.version}</span></span>
                      ))}
                    </div>
                    <pre className="lic-text">{g.text}</pre>
                  </>
                )}
              </div>
            ))}

            <div className="lic-copyright">
              <p>© 2025 QA Bulls. All rights reserved.</p>
              <p>{t("settings.licenseTab.copyright")}</p>
              <p className="lic-contact">{t("settings.licenseTab.contact")}: <a href="mailto:qabulls.test@gmail.com">qabulls.test@gmail.com</a></p>
            </div>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════
             언어 설정 탭
            ════════════════════════════════════════════════════════════ */}
        {activeTab === "language" && (
          <div className="stg-device-body">
            <div className="stg-desc-box">{t("settings.languageTab.desc")}</div>
            <div className="stg-radio-group">
              <label className={`stg-radio-card${lang === "ko" ? " active" : ""}`}>
                <input
                  type="radio" name="lang" value="ko"
                  checked={lang === "ko"}
                  onChange={() => setLang("ko")}
                />
                <div className="stg-radio-content">
                  <div className="stg-radio-title">🇰🇷 {t("settings.languageTab.ko")}</div>
                </div>
              </label>
              <label className={`stg-radio-card${lang === "en" ? " active" : ""}`}>
                <input
                  type="radio" name="lang" value="en"
                  checked={lang === "en"}
                  onChange={() => setLang("en")}
                />
                <div className="stg-radio-content">
                  <div className="stg-radio-title">🇺🇸 {t("settings.languageTab.en")}</div>
                </div>
              </label>
            </div>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════
             앱 설정 탭
            ════════════════════════════════════════════════════════════ */}
        {activeTab === "app" && (
          <div className="stg-device-body">
            <div className="stg-desc-box">{t("settings.appTab.desc")}</div>

            {/* Android 앱 */}
            <div className="stg-section">
              <div className="stg-section-title">🤖 {t("settings.appTab.androidApp")}</div>
              <div className="stg-file-row">
                <div className="stg-file-label">
                  <span className="stg-field-name">{t("settings.appTab.selectApp")}</span>
                  <span className="stg-field-hint">{t("settings.appTab.androidHint")}</span>
                </div>
                <select
                  className="inp stg-file-inp"
                  value={appConfig.androidAppId}
                  onChange={(e) => handleAppConfig("androidAppId", e.target.value)}
                >
                  {SUPPORTED_APPS.filter(a => a.package).map(a => (
                    <option key={a.id} value={a.id}>{getAppDisplayName(a, lang)} ({a.package})</option>
                  ))}
                </select>
              </div>
            </div>

            {/* iOS 앱 */}
            <div className="stg-section">
              <div className="stg-section-title">🍎 {t("settings.appTab.iosApp")}</div>
              <div className="stg-file-row">
                <div className="stg-file-label">
                  <span className="stg-field-name">{t("settings.appTab.selectApp")}</span>
                  <span className="stg-field-hint">{t("settings.appTab.iosHint")}</span>
                </div>
                <select
                  className="inp stg-file-inp"
                  value={appConfig.iosAppId}
                  onChange={(e) => handleAppConfig("iosAppId", e.target.value)}
                >
                  {SUPPORTED_APPS.filter(a => a.bundleId).map(a => (
                    <option key={a.id} value={a.id}>{getAppDisplayName(a, lang)} ({a.bundleId})</option>
                  ))}
                </select>
              </div>
            </div>

            {/* 현재 설정 요약 */}
            <div className="stg-desc-box" style={{ marginTop: 12, background: "var(--bg-tertiary)", fontSize: 13 }}>
              <strong>{t("settings.appTab.current")}:</strong><br />
              Android → {(() => { const a = SUPPORTED_APPS.find(x => x.id === appConfig.androidAppId); return a ? getAppDisplayName(a, lang) : "?"; })()}
              {" "}({SUPPORTED_APPS.find(a => a.id === appConfig.androidAppId)?.package ?? "-"})<br />
              iOS → {(() => { const a = SUPPORTED_APPS.find(x => x.id === appConfig.iosAppId); return a ? getAppDisplayName(a, lang) : "?"; })()}
              {" "}({SUPPORTED_APPS.find(a => a.id === appConfig.iosAppId)?.bundleId ?? "-"})
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
