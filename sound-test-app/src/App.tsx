import { useState, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import "./App.css";

// ── hooks ──────────────────────────────────────────────────────────────────
import { useDevices } from "./hooks/useDevices";
import { useEnvCheck } from "./hooks/useEnvCheck";
import { useAppium } from "./hooks/useAppium";
import { useLogs } from "./hooks/useLogs";
import { useAudioDevices } from "./hooks/useAudioDevices";
import { useSpeakerConfig } from "./hooks/useSpeakerConfig";
import { useTcSpeakerConfig } from "./hooks/useTcAudioConfig";
import { useTcRunner } from "./hooks/useTcRunner";
import { useAudioProfiles } from "./hooks/useAudioProfiles";
import { useNotice } from "./hooks/useNotice";

// ── components ─────────────────────────────────────────────────────────────
import { AppHeader } from "./components/AppHeader";
import { EnvPanel } from "./components/EnvPanel";
import { DeviceSection } from "./components/DeviceSection";
import { SpeakerSection, toPlainPhone } from "./components/SpeakerSection";
import { AudioSection } from "./components/AudioSection";
import { ExecSection } from "./components/ExecSection";
import { LogPanel } from "./components/LogPanel";
import { TcSelectPanel } from "./components/TcSelectPanel";
import ixioBannerImg from "./assets/ixio_banner.png";
import { DashboardView } from "./components/DashboardView";
import { ResultDetailModal } from "./components/ResultDetailModal";
import { ReportModal } from "./components/ReportModal";
import { SettingsModal } from "./components/SettingsModal";
import { ScheduleTab } from "./components/ScheduleTab";

import type { ConnectionStatus, TcId } from "./types";
import { SUPPORTED_APPS, DEFAULT_APP_CONFIG } from "./types";
import type { TargetAppConfig } from "./types";
import { TC_ENABLED } from "./data/tcConfig";
import { useT } from "./i18n";

// ── 장치 표시 유틸 ──────────────────────────────────────────────────────────
function shortDeviceLabel(name: string, udid: string): string {
  const modelMatch = name.match(/model:(\S+)/);
  const ipMatch =
    udid.match(/([\d.]+:\d+)$/) || name.match(/\(([\d.]+:\d+)\)/);
  if (modelMatch) {
    return ipMatch
      ? `${modelMatch[1]} (${ipMatch[1]})`
      : modelMatch[1];
  }
  if (name.match(/\(\d+\.\d+\.\d+\.\d+\)$/)) return name;
  return name.length > 30 ? name.slice(0, 30) + "…" : name;
}

// ── 테스트 콘솔 로그 라인 분류 ──────────────────────────────────────────────
function classifyConsoleLine(line: string): string {
  if (
    line.includes("[stderr]") ||
    line.includes("❌") ||
    line.includes("Error")
  )
    return "log-err";
  if (line.includes("✅") || line.includes("완료")) return "log-ok";
  if (line.includes("진행 중") || line.includes("[진행중]")) return "log-progress";
  if (line.startsWith("🔄") || line.startsWith("⏳")) return "log-info";
  return "";
}

// ── App ────────────────────────────────────────────────────────────────────
function App() {
  const [statusMessage, setStatusMessage] = useState("");

  // hooks
  const devices = useDevices(setStatusMessage);
  const env = useEnvCheck();
  const appium = useAppium(setStatusMessage);
  const logs = useLogs();
  const audio = useAudioDevices(setStatusMessage);
  const speaker = useSpeakerConfig();
  const {
    speaker1Device, setSpeaker1Device,
    speaker2Device, setSpeaker2Device,
    speaker1Number, setSpeaker1Number,
    speaker2Number, setSpeaker2Number,
    speaker1AudioFile, setSpeaker1AudioFile,
    speaker2AudioFile, setSpeaker2AudioFile,
    speaker1OutputDevice, setSpeaker1OutputDevice,
    speaker2OutputDevice, setSpeaker2OutputDevice,
    speaker1Channel, setSpeaker1Channel,
    speaker2Channel, setSpeaker2Channel,
    speaker1RecChannel, setSpeaker1RecChannel,
    speaker2RecChannel, setSpeaker2RecChannel,
    speaker1OutputPair, setSpeaker1OutputPair,
    speaker2OutputPair, setSpeaker2OutputPair,
  } = speaker;
  const [deviceAlert, setDeviceAlert] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [repeatCount, setRepeatCount] = useState(3);
  const [currentRepeat, setCurrentRepeat] = useState(0);
  const [totalRepeat, setTotalRepeat] = useState(0);
  const stopRepeatRef = useRef(false);

  // speaker 최신값 ref (useEffect에서 stale closure 방지)
  const speaker1Ref = useRef(speaker1Device);
  const speaker2Ref = useRef(speaker2Device);
  speaker1Ref.current = speaker1Device;
  speaker2Ref.current = speaker2Device;

  // 설정 모달 상태
  const [showSettings, setShowSettings] = useState(false);

  // TC 대시보드 상태
  const [activeTab, setActiveTab] = useState<"home" | "dashboard" | "schedule">("home");
  const [selectedTcs, setSelectedTcs] = useState<Set<TcId>>(new Set());
  const [activeResult, setActiveResult] = useState<import("./types").TcResult | null>(null);
  const [showReport, setShowReport] = useState(false);

  // TC Runner
  const tcRunner = useTcRunner(setStatusMessage);
  // TC별 화자 설정 — App 레벨에서 유지 (모달 언마운트 시 상태 손실 방지)
  const tcSpeakerCfgHook = useTcSpeakerConfig();

  // 음원 프로파일
  const profileHook = useAudioProfiles();
  const { selectedProfile, selectProfile } = profileHook;

  // 공지사항
  const notice = useNotice();

  // 분석 상태: 마지막으로 테스트가 성공 완료된 경우 분석 버튼 활성화
  const [lastTestSucceeded, setLastTestSucceeded] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  // 화자 발신/수신 스왑
  const handleSwapSpeakers = () => {
    const d1 = speaker1Device, d2 = speaker2Device;
    const n1 = speaker1Number, n2 = speaker2Number;
    const af1 = speaker1AudioFile, af2 = speaker2AudioFile;
    const od1 = speaker1OutputDevice, od2 = speaker2OutputDevice;
    const ch1 = speaker1Channel, ch2 = speaker2Channel;
    const rc1 = speaker1RecChannel, rc2 = speaker2RecChannel;
    const op1 = speaker1OutputPair, op2 = speaker2OutputPair;
    setSpeaker1Device(d2);
    setSpeaker2Device(d1);
    setSpeaker1Number(n2);
    setSpeaker2Number(n1);
    setSpeaker1AudioFile(af2);
    setSpeaker2AudioFile(af1);
    setSpeaker1OutputDevice(od2);
    setSpeaker2OutputDevice(od1);
    setSpeaker1Channel(ch2);
    setSpeaker2Channel(ch1);
    setSpeaker1RecChannel(rc2);
    setSpeaker2RecChannel(rc1);
    setSpeaker1OutputPair(op2);
    setSpeaker2OutputPair(op1);
  };

  // 마운트 시 초기화
  useEffect(() => {
    devices.loadAndroidDevices();
    devices.loadIosDevices();
    audio.loadAudioDevices();

    const cleanupLogs = logs.startListening();
    const cleanupProgress = audio.startProgressListening();

    return () => {
      cleanupLogs.then((fn) => fn());
      cleanupProgress.then((fn) => fn());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 디바이스 목록 갱신 시: stale/중복/빈 speaker 자동 보정
  // - 목록에 없는 디바이스는 같은 플랫폼 내에서 교체
  // - 양쪽 speaker가 동일 디바이스면 다른 기기로 교체
  // - speaker가 비어 있으면 남은 기기로 할당
  useEffect(() => {
    const allDevices = [...devices.androidDevices, ...devices.iosDevices];
    if (allDevices.length === 0) return;

    const allUdids = new Set(allDevices.map((d) => d.udid));
    let s1 = speaker1Ref.current;
    let s2 = speaker2Ref.current;
    let changed = false;

    // 1) stale 디바이스 교체 (같은 플랫폼만)
    if (s1 && !allUdids.has(s1)) {
      const wasAndroid = s1.includes(":");
      const pool = wasAndroid ? devices.androidDevices : devices.iosDevices;
      const rep = pool.find((d) => d.udid !== s2)?.udid ?? "";
      if (rep) { s1 = rep; changed = true; }
    }
    if (s2 && !allUdids.has(s2)) {
      const wasAndroid = s2.includes(":");
      const pool = wasAndroid ? devices.androidDevices : devices.iosDevices;
      const rep = pool.find((d) => d.udid !== s1)?.udid ?? "";
      if (rep) { s2 = rep; changed = true; }
    }

    // 2) 중복 보정: 양쪽이 같은 디바이스인데 다른 기기가 있으면 교체
    if (s1 && s1 === s2 && allDevices.length >= 2) {
      const other = allDevices.find((d) => d.udid !== s1);
      if (other) {
        console.log(`[중복보정] speaker2 중복 → ${other.udid}`);
        s2 = other.udid;
        changed = true;
      }
    }

    // 3) 빈 speaker 할당
    if (!s1 && allDevices.length >= 1) {
      const avail = allDevices.find((d) => d.udid !== s2);
      if (avail) { s1 = avail.udid; changed = true; }
    }
    if (!s2 && allDevices.length >= 1) {
      const avail = allDevices.find((d) => d.udid !== s1);
      if (avail) { s2 = avail.udid; changed = true; }
    }

    if (changed) {
      if (s1 !== speaker1Ref.current) {
        console.log(`[자동교체] speaker1: ${speaker1Ref.current} → ${s1}`);
        setSpeaker1Device(s1);
      }
      if (s2 !== speaker2Ref.current) {
        console.log(`[자동교체] speaker2: ${speaker2Ref.current} → ${s2}`);
        setSpeaker2Device(s2);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [devices.androidDevices, devices.iosDevices]);

  // Android 자동연결 성공 시: 새 IP가 확정되면 speaker도 직접 교체
  useEffect(() => {
    const ev = devices.lastAndroidConnect;
    if (!ev) return;
    const { newIp, oldIp } = ev;
    if (newIp === oldIp) return;

    const s1 = speaker1Ref.current;
    const s2 = speaker2Ref.current;

    if (s1 === oldIp) {
      console.log(`[자동연결] speaker1: ${oldIp} → ${newIp}`);
      setSpeaker1Device(newIp);
    }
    if (s2 === oldIp && newIp !== s1) {
      console.log(`[자동연결] speaker2: ${oldIp} → ${newIp}`);
      setSpeaker2Device(newIp);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [devices.lastAndroidConnect]);

  // 앱 시작 시 환경 체크 (1회)
  useEffect(() => {
    env.checkEnv();
  }, []);

  // iPhone 준비 안됨 알림 이벤트 구독
  useEffect(() => {
    const unlistenPromise = listen<string>("device-alert", (event) => {
      const msg = event.payload.replace(/^\[DEVICE_ALERT\]\s*/, "").trim();
      setDeviceAlert(msg);
    });
    return () => { unlistenPromise.then((fn) => fn()); };
  }, []);

  // ── 테스트 실행 ──────────────────────────────────────────────────────────

  const runOnce = async (): Promise<ConnectionStatus> => {
    const result = await invoke<ConnectionStatus>("run_ixio_test", {
      speaker1Device,
      speaker2Device,
      speaker1Number: toPlainPhone(speaker1Number),
      speaker2Number: toPlainPhone(speaker2Number),
      speaker1AudioFile,
      speaker2AudioFile,
      speaker1OutputDevice:
        speaker1OutputDevice !== "" ? parseInt(speaker1OutputDevice) : null,
      speaker2OutputDevice:
        speaker2OutputDevice !== "" ? parseInt(speaker2OutputDevice) : null,
      speaker1OutputPair: speaker1OutputPair !== "" ? speaker1OutputPair : null,
      speaker2OutputPair: speaker2OutputPair !== "" ? speaker2OutputPair : null,
      speaker1Channel: speaker1Channel !== "" ? speaker1Channel : null,
      speaker2Channel: speaker2Channel !== "" ? speaker2Channel : null,
      speaker1RecChannel: speaker1RecChannel !== "" ? speaker1RecChannel : null,
      speaker2RecChannel: speaker2RecChannel !== "" ? speaker2RecChannel : null,
    });
    setStatusMessage(result.message);
    return result;
  };

  const validateInputs = (): string | null => {
    if (!speaker1Device || !speaker2Device) return t("status.selectDevice");
    if (!speaker1AudioFile) return t("status.selectAudio1");
    if (!speaker2AudioFile) return t("status.selectAudio2");
    if (!speaker1AudioFile.startsWith("/")) return t("status.absolutePath1");
    if (!speaker2AudioFile.startsWith("/")) return t("status.absolutePath2");
    return null;
  };

  const handleStartTest = async () => {
    const err = validateInputs();
    if (err) { setStatusMessage(err); return; }
    setLastTestSucceeded(false);
    try {
      setIsRunning(true);
      setCurrentRepeat(0);
      setTotalRepeat(0);
      audio.resetProgress();
      setStatusMessage(t("status.testStarting"));
      const r = await runOnce();
      if (r.success) {
        setLastTestSucceeded(true);
        setStatusMessage(t("status.testDone"));
      } else {
        setStatusMessage(r.message);
      }
    } catch (error) {
      setStatusMessage(t("status.testFail", { err: String(error) }));
    } finally {
      setIsRunning(false);
    }
  };

  // 프로파일 선택 핸들러 (콘텐츠만 선택 — 하드웨어 복사 없음)
  const handleSelectProfile = (id: string) => {
    selectProfile(id);
    setLastTestSucceeded(false);
  };

  const handleRunAnalysis = async () => {
    const refPathS1  = selectedProfile?.refAudioPathS1 ?? "";
    const refPathS2  = selectedProfile?.refAudioPathS2 ?? "";
    const refPath    = selectedProfile?.refAudioPath ?? "";
    const scriptPath = selectedProfile?.scriptPath   ?? "";
    // S1/S2 중 하나라도 있거나, 레거시 refAudioPath가 있으면 분석 가능
    if (!refPathS1 && !refPathS2 && !refPath) {
      setStatusMessage(t("status.analysisNoRef"));
      return;
    }
    try {
      setIsAnalyzing(true);
      setStatusMessage(t("status.analysisRunning"));
      const r = await invoke<ConnectionStatus>("run_dropout_analysis", {
        refAudioPathS1: refPathS1,
        refAudioPathS2: refPathS2,
        scriptPath,
        profileName: selectedProfile?.name ?? "",
        tcType: "",
        appTag: (() => {
          try {
            const cfg: TargetAppConfig = JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG;
            const aTag = SUPPORTED_APPS.find(a => a.id === cfg.androidAppId)?.tag ?? "ixiO";
            const iTag = SUPPORTED_APPS.find(a => a.id === cfg.iosAppId)?.tag ?? "ixiO";
            return `${aTag}_${iTag}`;
          } catch { return "ixiO_ixiO"; }
        })(),
      });
      setStatusMessage(r.success ? t("status.analysisDone") : r.message);
    } catch (e) {
      setStatusMessage(t("status.analysisFail", { err: String(e) }));
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleRepeatTest = async () => {
    const err = validateInputs();
    if (err) { setStatusMessage(err); return; }
    stopRepeatRef.current = false;
    setIsRunning(true);
    setTotalRepeat(repeatCount);
    try {
      for (let i = 1; i <= repeatCount; ) {
        if (stopRepeatRef.current) {
          setStatusMessage(t("status.repeatStopMid", { cur: String(i - 1), total: String(repeatCount) }));
          break;
        }
        setCurrentRepeat(i);
        audio.resetProgress();
        setStatusMessage(t("status.repeatRunning", { cur: String(i), total: String(repeatCount) }));
        const result = await runOnce();
        if (stopRepeatRef.current) {
          setStatusMessage(t("status.repeatStopMid", { cur: String(i), total: String(repeatCount) }));
          break;
        }
        if (!result.success) {
          // 통화 강제 종료 또는 앱 크래시 → 동일 회차 재시작 (i 증가 없음)
          const isCrash = result.message?.includes("크래시");
          const waitSec = isCrash ? 10 : 5;
          const reason  = isCrash
            ? t("status.crashDetected", { cur: String(i), total: String(repeatCount), sec: String(waitSec) })
            : t("status.forceClose", { cur: String(i), total: String(repeatCount), sec: String(waitSec) });
          setStatusMessage(reason);
          await new Promise<void>((res) => {
            const check = setInterval(() => {
              if (stopRepeatRef.current) { clearTimeout(id); clearInterval(check); res(); }
            }, 200);
            const id = setTimeout(() => { clearInterval(check); res(); }, waitSec * 1000);
          });
          continue;
        }
        i++;  // 정상 완료 시에만 다음 회차로 진행
        if (i <= repeatCount) {
          setStatusMessage(t("status.repeatDoneNext", { cur: String(i - 1), total: String(repeatCount) }));
          await new Promise<void>((res) => {
            const check = setInterval(() => {
              if (stopRepeatRef.current) { clearTimeout(id); clearInterval(check); res(); }
            }, 200);
            const id = setTimeout(() => { clearInterval(check); res(); }, 3000);
          });
        } else {
          setStatusMessage(t("status.repeatDone", { total: String(repeatCount) }));
        }
      }
    } catch (error) {
      setStatusMessage(t("status.repeatFail", { err: String(error) }));
    } finally {
      setIsRunning(false);
      setCurrentRepeat(0);
      setTotalRepeat(0);
      stopRepeatRef.current = false;
    }
  };

  // ── TC 대시보드 핸들러 ──────────────────────────────────────────────────────

  const handleToggleTc = (id: TcId) => {
    setSelectedTcs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleTcStartTest = async (
    repeat: import("./types").RepeatOptions,
    schedule: import("./types").ScheduleOptions,
  ) => {
    // ── 글로벌 speaker 보정: stale / 중복 / 빈값 수정 ──
    const allDevices = [...devices.androidDevices, ...devices.iosDevices];
    const connectedUdids = new Set(allDevices.map((d) => d.udid));
    let s1 = speaker1Ref.current;
    let s2 = speaker2Ref.current;

    console.log(`[TC시작] 보정 전: s1=${s1}, s2=${s2}, 연결=${[...connectedUdids].join(", ")}`);

    // stale 교체 (같은 플랫폼만)
    if (s1 && !connectedUdids.has(s1)) {
      const pool = s1.includes(":") ? devices.androidDevices : devices.iosDevices;
      s1 = pool.find((d) => d.udid !== s2)?.udid ?? "";
    }
    if (s2 && !connectedUdids.has(s2)) {
      const pool = s2.includes(":") ? devices.androidDevices : devices.iosDevices;
      s2 = pool.find((d) => d.udid !== s1)?.udid ?? "";
    }
    // 중복 보정
    if (s1 && s1 === s2 && allDevices.length >= 2) {
      const other = allDevices.find((d) => d.udid !== s1);
      if (other) s2 = other.udid;
    }
    // 빈값 할당
    if (!s1 && allDevices.length >= 1) {
      s1 = allDevices.find((d) => d.udid !== s2)?.udid ?? "";
    }
    if (!s2 && allDevices.length >= 1) {
      s2 = allDevices.find((d) => d.udid !== s1)?.udid ?? "";
    }
    // 변경 시 state + ref 즉시 반영
    if (s1 !== speaker1Ref.current) {
      console.log(`[TC시작 보정] speaker1: ${speaker1Ref.current} → ${s1}`);
      setSpeaker1Device(s1);
      speaker1Ref.current = s1;
    }
    if (s2 !== speaker2Ref.current) {
      console.log(`[TC시작 보정] speaker2: ${speaker2Ref.current} → ${s2}`);
      setSpeaker2Device(s2);
      speaker2Ref.current = s2;
    }
    console.log(`[TC시작] 보정 후: s1=${s1}, s2=${s2}`);

    // ── TC별 디바이스 오버라이드: stale/중복 → 오버라이드 제거 (글로벌 설정으로 전환) ──
    const rawTcConfig = JSON.parse(JSON.stringify(tcSpeakerCfgHook.config)) as Record<string, any>;
    for (const [tcId, entry] of Object.entries(rawTcConfig) as [string, any][]) {
      if (!entry) continue;
      const e1 = entry.speaker1Device || "";
      const e2 = entry.speaker2Device || "";
      const hasBoth = !!(e1 && e2);

      // stale 검사: 연결 안 된 디바이스 → 제거
      if (e1 && !connectedUdids.has(e1)) {
        console.log(`[TC설정 ${tcId}] speaker1 stale: ${e1} → 오버라이드 제거`);
        entry.speaker1Device = "";
      }
      if (e2 && !connectedUdids.has(e2)) {
        console.log(`[TC설정 ${tcId}] speaker2 stale: ${e2} → 오버라이드 제거`);
        entry.speaker2Device = "";
      }

      // 중복 검사: 양쪽 같은 디바이스 → 오버라이드 전부 제거
      if (hasBoth && entry.speaker1Device === entry.speaker2Device && entry.speaker1Device) {
        console.log(`[TC설정 ${tcId}] 중복: 양쪽 ${entry.speaker1Device} → 오버라이드 제거`);
        entry.speaker1Device = "";
        entry.speaker2Device = "";
      }
    }
    // stale 정리 결과는 현재 실행에만 사용 (localStorage에 덮어쓰지 않음 — 사용자 TC 설정 보존)

    await tcRunner.startTc(
      selectedTcs,
      {
        speaker1Device: s1, speaker2Device: s2,
        speaker1Number: toPlainPhone(speaker1Number),
        speaker2Number: toPlainPhone(speaker2Number),
        speaker1AudioFile: selectedProfile?.speaker1AudioFile || speaker1AudioFile,
        speaker2AudioFile: selectedProfile?.speaker2AudioFile || speaker2AudioFile,
        speaker1OutputDevice, speaker2OutputDevice,
        speaker1Channel, speaker2Channel,
        speaker1RecChannel, speaker2RecChannel,
        speaker1OutputPair, speaker2OutputPair,
        tcSpeakerConfig: rawTcConfig,
        profiles: profileHook.profiles,
        refAudioPathS1: selectedProfile?.refAudioPathS1 ?? "",
        refAudioPathS2: selectedProfile?.refAudioPathS2 ?? "",
        refAudioPath: selectedProfile?.refAudioPath ?? "",
        scriptPath: selectedProfile?.scriptPath ?? "",
        profileName: selectedProfile?.name ?? "",
      },
      repeat,
      schedule,
    );
    setActiveTab("dashboard");
  };

  const handleStopTc = async () => {
    await tcRunner.stopTc();
  };

  const handleStopTest = async () => {
    stopRepeatRef.current = true;  // 반복 루프 중단 플래그
    try {
      setStatusMessage(t("status.stopTest"));
      const result = await invoke<ConnectionStatus>("stop_test");
      setStatusMessage(result.message);
      setIsRunning(false);
    } catch (error) {
      setStatusMessage(t("status.stopFail", { err: String(error) }));
    }
  };

  // ── 렌더 ─────────────────────────────────────────────────────────────────

  const newResultCount = tcRunner.tcResults.length;

  const { t } = useT();

  return (
    <div className="app">
      <AppHeader
        statusMessage={statusMessage}
        envAllOk={env.envAllOk}
        appiumStatus={appium.appiumStatus}
        currentRepeat={tcRunner.repeatProgress?.current ?? currentRepeat}
        totalRepeat={tcRunner.repeatProgress?.total ?? totalRepeat}
        onEnvClick={() => {
          env.setShowEnvPanel(true);
          env.checkEnv();
        }}
        onStartAppium={appium.handleStartAppium}
        onStopAppium={appium.handleStopAppium}
        onOpenSettings={() => setShowSettings(true)}
      />

      {/* ── 탭 스트립 ── */}
      <div className="tab-strip" data-tauri-drag-region>
        <button
          className={`tab-btn${activeTab === "home" ? " active" : ""}`}
          onClick={() => setActiveTab("home")}
        >
          {t("app.homeTab")}
        </button>
        <button
          className={`tab-btn${activeTab === "dashboard" ? " active" : ""}`}
          onClick={() => setActiveTab("dashboard")}
        >
          {t("app.dashTab")}
          {newResultCount > 0 && (
            <span className="tab-badge">{newResultCount}</span>
          )}
        </button>
        <button
          className={`tab-btn${activeTab === "schedule" ? " active" : ""}`}
          onClick={() => setActiveTab("schedule")}
        >
          {t("app.scheduleTab")}
        </button>
      </div>

      {showSettings && (
        <SettingsModal
          onClose={() => setShowSettings(false)}
          deviceOptions={[
            ...devices.iosDevices.map((d) => ({ value: d.udid, label: d.name || d.udid })),
            ...devices.androidDevices.map((d) => ({ value: d.udid, label: d.name || d.udid })),
          ]}
          audioOutputOptions={audio.audioDevices
            .map((d) => ({ value: String(d.id), label: `[${d.id}] ${d.name} (${d.channels ?? '?'}ch)` }))}
          profileHook={profileHook}
          tcConfigApi={tcSpeakerCfgHook}
          speaker1Device={speaker1Device}
          speaker2Device={speaker2Device}
          speaker1Number={speaker1Number}
          speaker2Number={speaker2Number}
          speaker1OutputDevice={speaker1OutputDevice}
          speaker2OutputDevice={speaker2OutputDevice}
          speaker1Channel={speaker1Channel}
          speaker2Channel={speaker2Channel}
          speaker1RecChannel={speaker1RecChannel}
          speaker2RecChannel={speaker2RecChannel}
          speaker1OutputPair={speaker1OutputPair}
          speaker2OutputPair={speaker2OutputPair}
          onSpeaker1DeviceChange={setSpeaker1Device}
          onSpeaker2DeviceChange={setSpeaker2Device}
          onSpeaker1NumberChange={setSpeaker1Number}
          onSpeaker2NumberChange={setSpeaker2Number}
          onSpeaker1OutputDeviceChange={setSpeaker1OutputDevice}
          onSpeaker2OutputDeviceChange={setSpeaker2OutputDevice}
          onSpeaker1ChannelChange={setSpeaker1Channel}
          onSpeaker2ChannelChange={setSpeaker2Channel}
          onSpeaker1RecChannelChange={setSpeaker1RecChannel}
          onSpeaker2RecChannelChange={setSpeaker2RecChannel}
          onSpeaker1OutputPairChange={setSpeaker1OutputPair}
          onSpeaker2OutputPairChange={setSpeaker2OutputPair}
          notices={notice.notices}
          onAddNotice={notice.addNotice}
          onUpdateNotice={notice.updateNotice}
          onDeleteNotice={notice.deleteNotice}
          onMoveNoticeUp={notice.moveUp}
        />
      )}

      {activeResult && (
        <ResultDetailModal result={activeResult} onClose={() => setActiveResult(null)} />
      )}

      {showReport && (
        <ReportModal
          results={tcRunner.tcResults}
          sessions={tcRunner.sessions}
          onClose={() => setShowReport(false)}
        />
      )}

      {/* ── iPhone 준비 필요 알림 팝업 ── */}
      {deviceAlert && (
        <div className="device-alert-overlay" onClick={() => setDeviceAlert(null)}>
          <div className="device-alert-modal" onClick={(e) => e.stopPropagation()}>
            <div className="device-alert-icon">📱</div>
            <div className="device-alert-title">{t("alert.iphoneReady")}</div>
            <div className="device-alert-message">{deviceAlert}</div>
            <button className="btn-xs btn-accent" style={{ marginTop: "14px", padding: "6px 20px" }} onClick={() => setDeviceAlert(null)}>
              {t("alert.confirm")}
            </button>
          </div>
        </div>
      )}

      {env.showEnvPanel && (
        <EnvPanel
          envItems={env.envItems}
          envChecking={env.envChecking}
          pythonEnvReady={env.pythonEnvReady}
          setupRunning={env.setupRunning}
          setupLogs={env.setupLogs}
          setupLogRef={env.setupLogRef}
          onClose={() => env.setShowEnvPanel(false)}
          onRefresh={env.checkEnv}
          onSetupPython={env.setupPython}
        />
      )}

      {/* ── 홈 탭 ── */}
      {activeTab === "home" && <>

      <TcSelectPanel
        selectedTcs={selectedTcs}
        onToggle={handleToggleTc}
        onStartTest={handleTcStartTest}
        onStop={handleStopTc}
        isRunning={tcRunner.isTcRunning}
        isBlocked={false}
        runningResults={tcRunner.runningResults}
        repeatProgress={tcRunner.repeatProgress}
      />

      <main className="app-main">
        {/* ── 행1 왼쪽: 디바이스 연결 ── */}
        <DeviceSection
          androidIpPort={devices.androidIpPort}
          onChangeIpPort={devices.setAndroidIpPort}
          onGetAndroidIp={devices.handleGetAndroidIp}
          onDisconnectAndroid={devices.handleDisconnectAndroid}
          onRefreshAndroid={devices.loadAndroidDevices}
          onCheckIphone={devices.handleCheckIphone}
          onRefreshIos={devices.loadIosDevices}
          androidDevices={devices.androidDevices}
          iosDevices={devices.iosDevices}
          onInstallWda={devices.handleInstallWda}
          watchdogRunning={devices.watchdogRunning}
          onStartWatchdog={devices.handleStartWatchdog}
          onStopWatchdog={devices.handleStopWatchdog}
          notices={notice.notices}
        />
        {/* ── 행1 오른쪽: 오디오 설정 (프로파일 라디오 통합) ── */}
        <AudioSection
          audioDevices={audio.audioDevices}
          profiles={profileHook.profiles}
          selectedProfileId={profileHook.selectedProfileId}
          onSelectProfile={handleSelectProfile}
          onEditProfiles={() => setShowSettings(true)}
          speaker1AudioFile={speaker1AudioFile}
          speaker2AudioFile={speaker2AudioFile}
          speaker1OutputDevice={speaker1OutputDevice}
          speaker2OutputDevice={speaker2OutputDevice}
          speaker1Channel={speaker1Channel}
          speaker2Channel={speaker2Channel}
          onSpeaker1OutputDeviceChange={setSpeaker1OutputDevice}
          onSpeaker2OutputDeviceChange={setSpeaker2OutputDevice}
          onSpeaker1ChannelChange={setSpeaker1Channel}
          onSpeaker2ChannelChange={setSpeaker2Channel}
          onTestTone1={() => audio.handleTestTone(speaker1OutputDevice, "S1", speaker1OutputPair)}
          onTestTone2={() => audio.handleTestTone(speaker2OutputDevice, "S2", speaker2OutputPair)}
          onRefreshDevices={audio.loadAudioDevices}
        />
        {/* ── 행2 왼쪽: 화자 설정 ── */}
        <SpeakerSection
          androidDevices={devices.androidDevices}
          iosDevices={devices.iosDevices}
          speaker1Device={speaker1Device}
          speaker2Device={speaker2Device}
          speaker1Number={speaker1Number}
          speaker2Number={speaker2Number}
          onSpeaker1DeviceChange={setSpeaker1Device}
          onSpeaker2DeviceChange={setSpeaker2Device}
          onSpeaker1NumberChange={setSpeaker1Number}
          onSpeaker2NumberChange={setSpeaker2Number}
          shortDeviceLabel={shortDeviceLabel}
          onSwap={handleSwapSpeakers}
        />
        {/* ── 행2 오른쪽: 테스트 실행 ── */}
        <ExecSection
          appiumStatus={appium.appiumStatus}
          isRunning={isRunning}
          isBlocked={false}
          speaker1Progress={audio.speaker1Progress}
          speaker2Progress={audio.speaker2Progress}
          speaker1Channel={speaker1Channel}
          speaker2Channel={speaker2Channel}
          repeatCount={repeatCount}
          currentRepeat={currentRepeat}
          totalRepeat={totalRepeat}
          onStart={handleStartTest}
          onStartRepeat={handleRepeatTest}
          onStop={handleStopTest}
          onRepeatCountChange={setRepeatCount}
          lastTestSucceeded={lastTestSucceeded}
          isAnalyzing={isAnalyzing}
          onAnalyze={handleRunAnalysis}
        />
        {/* ── 행3 왼쪽: Appium 로그 ── */}
        <LogPanel
          title={t("log.appiumTitle")}
          logs={logs.appiumLogs}
          onClear={logs.clearAppiumLogs}
          logRef={logs.appiumLogRef}
          emptyMessage={t("log.appiumEmpty")}
          bannerSrc={ixioBannerImg}
        />
        {/* ── 행3 오른쪽: 테스트 콘솔 ── */}
        <LogPanel
          title={t("log.consoleTitle")}
          logs={logs.consoleLogs}
          onClear={logs.clearConsoleLogs}
          logRef={logs.consoleLogRef}
          emptyMessage={t("log.consoleEmpty")}
          classifyLine={classifyConsoleLine}
          infoContent={
            <div className="tc-info-guide">
              <h4>{t("tc.guide.title")}</h4>

              <h5 className="tc-info-mode-label mode-tc">{t("tc.guide.tcMode")}</h5>
              <dl>
                <dt>TC_01</dt>
                <dd>{t("tc.guide.tc01desc")}<br/>{t("tc.guide.tc01detail")}<br/>{t("tc.guide.tc01note")}</dd>
                <dt>TC_02</dt>
                <dd>{t("tc.guide.tc02desc")}<br/>{t("tc.guide.tc02detail")}<br/>{t("tc.guide.tc02note")}</dd>
              </dl>

              <h5 className="tc-info-mode-label mode-normal">{t("tc.guide.normalMode")}</h5>
              <p className="tc-info-note">{t("tc.guide.bottomNote")}</p>
            </div>
          }
        />
      </main>

      </>}

      {/* ── 대시보드 탭 ── */}
      {activeTab === "dashboard" && (
        <div className="dashboard-container">
          <DashboardView
            results={tcRunner.tcResults}
            runningResults={tcRunner.runningResults}
            sessions={tcRunner.sessions}
            onClear={tcRunner.clearResults}
            onDeleteSelected={tcRunner.deleteSelected}
            onSelectResult={setActiveResult}
            onGenerateReport={() => setShowReport(true)}
          />
        </div>
      )}

      {/* ── 예약 테스트 탭 ── */}
      {/* display:none 으로 숨기되 항상 마운트 유지 — unmount 시 타이머/isTcRunning 변화를 놓치는 버그 방지 */}
      <div className="dashboard-container" style={{ display: activeTab === "schedule" ? undefined : "none" }}>
        <ScheduleTab
            enabledTcIds={new Set(Object.entries(TC_ENABLED).filter(([, v]) => v).map(([k]) => k as TcId))}
            isTcRunning={tcRunner.isTcRunning}
            onTrigger={(tcIds, repeat, schedule, sessionId) => {
              setSelectedTcs(tcIds);
              const rawTcSpeakerConfig = JSON.parse(JSON.stringify(tcSpeakerCfgHook.config));
              tcRunner.startTc(tcIds, {
                speaker1Device, speaker2Device,
                speaker1Number: toPlainPhone(speaker1Number),
                speaker2Number: toPlainPhone(speaker2Number),
                speaker1AudioFile: selectedProfile?.speaker1AudioFile || speaker1AudioFile,
                speaker2AudioFile: selectedProfile?.speaker2AudioFile || speaker2AudioFile,
                speaker1OutputDevice, speaker2OutputDevice,
                speaker1Channel, speaker2Channel,
                speaker1RecChannel, speaker2RecChannel,
                speaker1OutputPair, speaker2OutputPair,
                tcSpeakerConfig: rawTcSpeakerConfig,
                profiles: profileHook.profiles,
                refAudioPathS1: selectedProfile?.refAudioPathS1 ?? "",
                refAudioPathS2: selectedProfile?.refAudioPathS2 ?? "",
                refAudioPath: selectedProfile?.refAudioPath ?? "",
                scriptPath: selectedProfile?.scriptPath ?? "",
                profileName: selectedProfile?.name ?? "",
              }, repeat, schedule, sessionId);
              // 예약 탭에서 칸반 카드가 테스트 중으로 이동하는 것을 볼 수 있도록 탭 전환 없음
            }}
          />
        </div>

      {activeTab === "home" && <footer className="app-footer">
        <span className="footer-label">{t("footer.connected")}</span>
        {devices.androidDevices.length === 0 &&
        devices.iosDevices.length === 0 ? (
          <span className="footer-empty">{t("footer.noDevice")}</span>
        ) : (
          <>
            {devices.androidDevices.map((d) => (
              <span key={d.udid} className="device-chip android">
                {shortDeviceLabel(d.name, d.udid)}
              </span>
            ))}
            {devices.iosDevices.map((d) => (
              <span key={d.udid} className="device-chip ios">
                {shortDeviceLabel(d.name, d.udid)}
              </span>
            ))}
          </>
        )}
        <span className="footer-brand">QA Bulls</span>
      </footer>}
    </div>
  );
}

export default App;
