/**
 * useTcRunner — TC 테스트 실행 전체 로직 훅
 * - 단독 실행 / 반복 실행 / 예약 실행
 * - TC별 실시간 진행 상태 (subStatus, phase)
 * - 완료 후 음단절 분석 자동 연동 (TC_01/TC_02)
 */
import { useRef, useState, useCallback, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import * as XLSX from "xlsx";
import { useT } from "../i18n";
import type {
  TcId, TcResult, TcStatus, RepeatOptions, ScheduleOptions,
  TcSession, DropoutSeverity, TcSpeakerConfig, AudioProfile,
  TargetAppConfig,
} from "../types";
import { SUPPORTED_APPS, DEFAULT_APP_CONFIG, SUPPORTED_CARRIERS, DEFAULT_CARRIER } from "../types";

interface ConnectionStatus {
  success: boolean;
  message: string;
}

interface TestRunResult extends ConnectionStatus {
  ios_recording: string;
  android_recording: string;
  screenshots: string[];
  vishing_detected: boolean | null;
}

interface DropoutAnalysisResult extends ConnectionStatus {
  report_path: string;
  dropout_count: number;
  severity: string;
  ios_visqol_mos: number | null;
  android_visqol_mos: number | null;
  // v2
  and_dropped_count:  number;
  and_degraded_count: number;
  and_poor_count:     number;
  and_severity:       string;
  ios_dropped_count:  number;
  ios_degraded_count: number;
  ios_poor_count:     number;
  ios_severity:       string;
  voip_delay_ms:      number;
  // v3: 디바이스 & 앱 버전
  android_app_ver:    string;
  ios_app_ver:        string;
  android_device:     string;
  android_os_ver:     string;
  ios_device:         string;
  ios_os_ver:         string;
  profile_name:       string;
}

interface RunnerCallDeps {
  speaker1Device: string;
  speaker2Device: string;
  speaker1Number: string;
  speaker2Number: string;
  speaker1AudioFile: string;
  speaker2AudioFile: string;
  speaker1OutputDevice: string;
  speaker2OutputDevice: string;
  speaker1Channel: string;
  speaker2Channel: string;
  speaker1RecChannel: string;
  speaker2RecChannel: string;
  speaker1OutputPair: string;
  speaker2OutputPair: string;
  tcSpeakerConfig: TcSpeakerConfig;
  profiles: AudioProfile[];
  refAudioPathS1: string;
  refAudioPathS2: string;
  /** @deprecated S1/S2 미설정 시 양쪽 공통 폴백 */
  refAudioPath: string;
  scriptPath: string;
  profileName: string;
}

export interface TcRunnerState {
  isTcRunning: boolean;
  tcResults: TcResult[];
  sessions: TcSession[];
  /** TC별 최신 결과 (진행 상태 표시용) */
  runningResults: Map<TcId, TcResult>;
  /** 반복 진행 카운터 */
  repeatProgress: { current: number; total: number } | null;
  /** 예약 카운트다운 (초) */
  scheduleCountdown: number | null;
}

export interface TcRunnerActions {
  startTc: (
    selectedTcs: Set<TcId>,
    deps: RunnerCallDeps,
    repeat: RepeatOptions,
    schedule: ScheduleOptions,
    providedSessionId?: string,
  ) => Promise<void>;
  stopTc: () => Promise<void>;
  clearResults: () => void;
  deleteSelected: (runIds: Set<string>) => void;
}

const STORAGE_RESULTS_KEY = "ixio-tc-results";
const STORAGE_SESSIONS_KEY = "ixio-tc-sessions";
const STORAGE_ACTIVE_SESSION_KEY = "ixio-tc-active-session";

function loadStored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (raw) return JSON.parse(raw) as T;
  } catch {}
  return fallback;
}

/** 앱 강제 종료 후 복구용: 활성 세션의 runIds를 localStorage에 즉시 갱신 */
function updateActiveSessionRunIds(runIds: string[]): void {
  try {
    const raw = localStorage.getItem(STORAGE_ACTIVE_SESSION_KEY);
    if (!raw) return;
    const active: Record<string, unknown> = JSON.parse(raw);
    active.runIds = [...runIds];
    localStorage.setItem(STORAGE_ACTIVE_SESSION_KEY, JSON.stringify(active));
  } catch {}
}

export function useTcRunner(
  setStatusMessage: (msg: string) => void,
): TcRunnerState & TcRunnerActions {
  const [isTcRunning, setIsTcRunning] = useState(false);
  const [tcResults, setTcResults] = useState<TcResult[]>(() => {
    // 과거에 오염된 DEMO localStorage 데이터도 정리
    const raw = loadStored<TcResult[]>(STORAGE_RESULTS_KEY, []).filter((r) => !r.runId.startsWith("demo-"));
    // 앱 강제 종료 시 RUNNING/QUEUED 상태로 남은 결과를 ERROR로 변환
    const cleaned = raw.map<TcResult>((r) => {
      if (r.status === "RUNNING" || r.status === "QUEUED") {
        return { ...r, status: "ERROR", subStatus: "강제 종료", errorMsg: "앱이 예기치 않게 종료되었습니다." };
      }
      return r;
    });
    try { localStorage.setItem(STORAGE_RESULTS_KEY, JSON.stringify(cleaned)); } catch {}
    return cleaned;
  });
  const [sessions, setSessions] = useState<TcSession[]>(() => {
    const raw = loadStored<TcSession[]>(STORAGE_SESSIONS_KEY, []).filter((s) => !s.sessionId.startsWith("demo-"));
    // 앱 강제 종료 시 저장된 부분 세션을 복구하여 세션 목록에 추가
    const recovered: TcSession[] = [];
    try {
      const activeRaw = localStorage.getItem(STORAGE_ACTIVE_SESSION_KEY);
      if (activeRaw) {
        const active = JSON.parse(activeRaw) as Partial<TcSession>;
        if (active.sessionId) {
          recovered.push({
            sessionId: active.sessionId,
            tcIds: active.tcIds ?? [],
            startedAt: active.startedAt ?? new Date().toISOString(),
            finishedAt: new Date().toISOString(),
            repeatOptions: active.repeatOptions ?? null,
            runIds: active.runIds ?? [],
          });
        }
        localStorage.removeItem(STORAGE_ACTIVE_SESSION_KEY);
      }
    } catch {}
    const all = [...raw, ...recovered];
    try { localStorage.setItem(STORAGE_SESSIONS_KEY, JSON.stringify(all)); } catch {}
    return all;
  });
  const [runningResults, setRunningResults] = useState<Map<TcId, TcResult>>(new Map());
  const [repeatProgress, setRepeatProgress] = useState<{ current: number; total: number } | null>(null);
  const [scheduleCountdown, setScheduleCountdown] = useState<number | null>(null);

  const stopRef = useRef(false);
  const tcResultsRef = useRef(tcResults);
  tcResultsRef.current = tcResults;

  const { t } = useT();
  const tRef = useRef(t);
  tRef.current = t;

  // tcResults / sessions 변경 시 localStorage에 자동 저장
  useEffect(() => {
    try { localStorage.setItem(STORAGE_RESULTS_KEY, JSON.stringify(tcResults)); } catch {}
  }, [tcResults]);
  useEffect(() => {
    try { localStorage.setItem(STORAGE_SESSIONS_KEY, JSON.stringify(sessions)); } catch {}
  }, [sessions]);

  // ── 앱 기동 시 localStorage → DB 소급 적재 (1회) ──────────────────────────
  useEffect(() => {
    const stored = loadStored<TcResult[]>(STORAGE_RESULTS_KEY, []);
    const finalStatuses: TcStatus[] = ["PASS", "FAIL", "ERROR"];
    const toMigrate = stored.filter((r) => finalStatuses.includes(r.status as TcStatus));
    console.info(`[db] 소급 적재 확인: localStorage 전체=${stored.length}건, 최종상태=${toMigrate.length}건`);
    if (toMigrate.length === 0) {
      console.info("[db] 소급 적재 대상 없음 — 건너뜀");
      return;
    }

    // NaN / undefined / null 등 잘못된 숫자값을 0으로 정규화
    const sanitizeNum = (v: unknown, fallback = 0): number => {
      const n = Number(v);
      return isFinite(n) ? n : fallback;
    };

    const payloads = toMigrate.map((r) => ({
      runId:               r.runId,
      sessionId:           r.sessionId ?? null,
      repeatIndex:         r.repeatIndex ?? null,
      tcId:                r.tcId,
      startedAt:           r.startedAt || new Date().toISOString(),
      finishedAt:          r.finishedAt || new Date().toISOString(),
      durationMs:          sanitizeNum(r.durationMs),
      status:              r.status,
      iosVisqolMos:        r.iosVisqolMos != null && isFinite(r.iosVisqolMos) ? r.iosVisqolMos : null,
      androidVisqolMos:    r.androidVisqolMos != null && isFinite(r.androidVisqolMos) ? r.androidVisqolMos : null,
      snrDb:               r.snrDb != null && isFinite(r.snrDb) ? r.snrDb : null,
      dropoutCount:        r.dropoutCount ?? null,
      dropoutSeverity:     r.dropoutSeverity ?? null,
      dropoutReportPath:   r.dropoutReportPath ?? null,
      mosReportPath:       r.mosReportPath ?? null,
      vishingDetected:     r.vishingDetected ?? null,
      errorMsg:            r.errorMsg ?? null,
      extractedAudioPaths: r.extractedAudioPaths ?? [],
      screenshotPaths:     r.screenshotPaths ?? [],
      logLines:            r.logLines ?? [],
    }));

    console.info(`[db] 소급 적재 invoke 호출: ${payloads.length}건`);

    // 세션도 함께 전달 (tc_results FK 충족을 위해 세션 먼저 삽입)
    const storedSessions = loadStored<TcSession[]>(STORAGE_SESSIONS_KEY, []);
    const sessionPayloads = storedSessions.map((s) => ({
      sessionId:    s.sessionId,
      tcIds:        s.tcIds,
      startedAt:    s.startedAt,
      finishedAt:   s.finishedAt ?? null,
      repeatCount:  s.repeatOptions?.count ?? null,
      repeatMode:   s.repeatOptions?.mode ?? null,
      failAction:   s.repeatOptions?.failAction ?? null,
    }));
    console.info(`[db] 세션 ${sessionPayloads.length}건 포함하여 전송`);

    invoke<number>("db_batch_save_results", { sessions: sessionPayloads, results: payloads })
      .then((saved) => console.info(`[db] 소급 적재 완료: ${saved}/${toMigrate.length}건`))
      .catch((e: unknown) => console.warn("[db] 소급 적재 실패:", e));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 앱 기동 시 DB 복원 (localStorage 소실 대응) ────────────────────────────
  // localStorage 결과가 DB보다 적으면 DB에서 전체 복원
  interface DbSnapshot {
    sessions: {
      sessionId: string; tcIds: string[]; startedAt: string; finishedAt: string | null;
      repeatCount: number | null; repeatMode: string | null; failAction: string | null;
      runIds: string[];
    }[];
    results: {
      runId: string; sessionId: string | null; repeatIndex: number | null;
      tcId: string; startedAt: string; finishedAt: string; durationMs: number;
      status: string;
      iosVisqolMos: number | null; androidVisqolMos: number | null; snrDb: number | null;
      dropoutCount: number | null; dropoutSeverity: string | null;
      dropoutReportPath: string | null; mosReportPath: string | null;
      vishingDetected: boolean | null; errorMsg: string | null;
      andDroppedCount: number | null; andDegradedCount: number | null; andPoorCount: number | null; andSeverity: string | null;
      iosDroppedCount: number | null; iosDegradedCount: number | null; iosPoorCount: number | null; iosSeverity: string | null;
      voipDelayMs: number | null;
      androidAppVer: string | null; iosAppVer: string | null;
      androidDevice: string | null; androidOsVer: string | null;
      iosDevice: string | null; iosOsVer: string | null;
      profileName: string | null; carrier: string | null;
    }[];
  }

  useEffect(() => {
    invoke<DbSnapshot>("db_load_snapshot", { limit: 5000 })
      .then((snap) => {
        const localCount = tcResultsRef.current.length;
        const dbCount = snap.results.length;
        console.info(`[db-restore] localStorage=${localCount}건, DB=${dbCount}건`);
        if (dbCount <= localCount) {
          console.info("[db-restore] localStorage가 최신 — 복원 불필요");
          return;
        }
        console.info(`[db-restore] DB에서 ${dbCount}건 복원 시작 (localStorage ${localCount}건 대체)`);

        // DB 결과 → TcResult 변환
        const restored: TcResult[] = snap.results.map((r) => ({
          runId: r.runId,
          sessionId: r.sessionId,
          repeatIndex: r.repeatIndex,
          tcId: r.tcId as TcId,
          startedAt: r.startedAt,
          finishedAt: r.finishedAt,
          durationMs: r.durationMs,
          status: r.status as TcStatus,
          phase: null,
          subStatus: "",
          iosVisqolMos: r.iosVisqolMos,
          androidVisqolMos: r.androidVisqolMos,
          snrDb: r.snrDb,
          dropoutCount: r.dropoutCount,
          dropoutSeverity: r.dropoutSeverity as DropoutSeverity | null,
          dropoutReportPath: r.dropoutReportPath,
          mosReportPath: r.mosReportPath,
          extractedAudioPaths: [],
          screenshotPaths: [],
          vishingDetected: r.vishingDetected,
          logLines: [],
          errorMsg: r.errorMsg,
          andDroppedCount: r.andDroppedCount,
          andDegradedCount: r.andDegradedCount,
          andPoorCount: r.andPoorCount,
          andSeverity: r.andSeverity,
          iosDroppedCount: r.iosDroppedCount,
          iosDegradedCount: r.iosDegradedCount,
          iosPoorCount: r.iosPoorCount,
          iosSeverity: r.iosSeverity,
          voipDelayMs: r.voipDelayMs,
          androidAppVer: r.androidAppVer,
          iosAppVer: r.iosAppVer,
          androidDevice: r.androidDevice,
          androidOsVer: r.androidOsVer,
          iosDevice: r.iosDevice,
          iosOsVer: r.iosOsVer,
          profileName: r.profileName,
          carrier: r.carrier,
        }));

        // DB 세션 → TcSession 변환
        const restoredSessions: TcSession[] = snap.sessions.map((s) => ({
          sessionId: s.sessionId,
          tcIds: s.tcIds as TcId[],
          startedAt: s.startedAt,
          finishedAt: s.finishedAt,
          repeatOptions: s.repeatCount != null ? {
            count: s.repeatCount,
            mode: (s.repeatMode ?? "set") as RepeatOptions["mode"],
            failAction: (s.failAction ?? "continue") as RepeatOptions["failAction"],
          } : null,
          runIds: s.runIds,
        }));

        setTcResults(restored);
        setSessions(restoredSessions);
        console.info(`[db-restore] 복원 완료: 결과 ${restored.length}건, 세션 ${restoredSessions.length}건`);
      })
      .catch((e: unknown) => console.warn("[db-restore] DB 스냅샷 로드 실패:", e));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 500회 단위 마일스톤 이메일 ───────────────────────────────────────────

  const MILESTONE_STEP   = 500;
  const MILESTONE_EMAILS = ["m9.chapter1@gmail.com", "seyongida@gmail.com"];
  const MILESTONE_STORAGE_KEY = "ixio-milestone-last-notified";

  async function checkMilestoneAndSendEmail() {
    try {
      // DB 전체 건수 조회 (totalCount는 LIMIT 무관 COUNT(*) 결과)
      const stats = await invoke<{ totalCount: number }>("db_export_stats", {
        fromDate: null, toDate: null, limit: 1,
      });
      const total = stats.totalCount;
      if (!total || total < MILESTONE_STEP) return;

      const milestone = Math.floor(total / MILESTONE_STEP) * MILESTONE_STEP;
      const lastNotified = parseInt(localStorage.getItem(MILESTONE_STORAGE_KEY) ?? "0", 10);
      if (milestone <= lastNotified) return;

      // 마일스톤 달성 — 전체 통계 데이터 요청

      interface TcStatItem {
        tcId: string; total: number; pass: number; fail: number; error: number;
        passRate: number; avgDurationMs: number;
        avgIosMos: number | null; avgAndroidMos: number | null; avgDropoutCount: number | null;
      }
      interface ResultItem {
        runId: string; sessionId: string | null; repeatIndex: number | null; tcId: string;
        startedAt: string; finishedAt: string; durationMs: number; status: string;
        iosVisqolMos: number | null; androidVisqolMos: number | null; snrDb: number | null;
        dropoutCount: number | null; dropoutSeverity: string | null;
        errorMsg: string | null;
      }
      interface DailyMosItem { date: string; tcId: string; avgIosMos: number | null; avgAndroidMos: number | null; runCount: number; }
      interface SevItem { tcId: string; severity: string; count: number; }
      interface ExportData {
        results: ResultItem[]; tcStats: TcStatItem[];
        dailyMos: DailyMosItem[]; severityStats: SevItem[];
        totalCount: number;
      }

      const exportData = await invoke<ExportData>(
        "db_export_stats", { fromDate: null, toDate: null, limit: null }
      );

      // ─── 엑셀 파일 생성 ────────────────────────────────────────────────
      const wb = XLSX.utils.book_new();

      // 시트1: 결과 전체
      const resHeader = [
        "run_id", "session_id", "회차", "TC ID", "실행시각", "종료시각", "소요(ms)",
        "상태", "MOS(iOS)", "MOS(AOS)", "SNR(dB)", "음단절 건수", "음단절 정도", "오류",
      ];
      const resRows = [resHeader, ...exportData.results.map((r) => [
        r.runId, r.sessionId ?? "", r.repeatIndex ?? "", r.tcId,
        r.startedAt, r.finishedAt, r.durationMs, r.status,
        r.iosVisqolMos != null ? +r.iosVisqolMos.toFixed(3) : "",
        r.androidVisqolMos != null ? +r.androidVisqolMos.toFixed(3) : "",
        r.snrDb != null ? +r.snrDb.toFixed(1) : "",
        r.dropoutCount ?? "", r.dropoutSeverity ?? "", r.errorMsg ?? "",
      ])];
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(resRows), "결과 전체");

      // 시트2: TC별 통계
      const statsHeader = ["TC ID", "전체", "PASS", "FAIL", "ERROR", "통과율(%)", "평균 소요(s)", "평균 MOS(iOS)", "평균 MOS(AOS)", "평균 음단절"];
      const statsRows = [statsHeader, ...exportData.tcStats.map((s) => [
        s.tcId, s.total, s.pass, s.fail, s.error, +s.passRate.toFixed(1),
        +(s.avgDurationMs / 1000).toFixed(1),
        s.avgIosMos != null ? +s.avgIosMos.toFixed(3) : "",
        s.avgAndroidMos != null ? +s.avgAndroidMos.toFixed(3) : "",
        s.avgDropoutCount != null ? +s.avgDropoutCount.toFixed(1) : "",
      ])];
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(statsRows), "TC별 통계");

      // 시트3: 날짜별 MOS
      const mosRows = [["날짜", "TC ID", "평균 MOS(iOS)", "평균 MOS(AOS)", "실행 수"],
        ...exportData.dailyMos.map((d) => [
          d.date, d.tcId,
          d.avgIosMos != null ? +d.avgIosMos.toFixed(3) : "",
          d.avgAndroidMos != null ? +d.avgAndroidMos.toFixed(3) : "",
          d.runCount,
        ])];
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(mosRows), "날짜별 MOS");

      // 시트4: Severity 분포
      const sevRows = [["TC ID", "음단절 정도", "건수"],
        ...exportData.severityStats.map((s) => [s.tcId, s.severity, s.count])];
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(sevRows), "Severity 분포");

      const wbBuf = XLSX.write(wb, { bookType: "xlsx", type: "array" });
      const xlsxB64 = btoa(String.fromCharCode(...new Uint8Array(wbBuf)));

      // ─── JSON 파일 생성 ─────────────────────────────────────────────────
      const jsonStr = JSON.stringify(exportData, null, 2);

      // ─── 임시 파일 저장 ─────────────────────────────────────────────────
      const ts = new Date().toISOString().slice(0, 10);
      const xlsxPath = await invoke<string>("save_temp_file", {
        dataB64: xlsxB64,
        filename: `ixio_stats_${milestone}_${ts}.xlsx`,
      });
      const jsonPath = await invoke<string>("save_temp_text", {
        text: jsonStr,
        filename: `ixio_stats_${milestone}_${ts}.json`,
      });

      // ─── HTML 본문 ─────────────────────────────────────────────────────
      const statsHtml = exportData.tcStats.map((s) => `
        <tr>
          <td>${s.tcId}</td><td>${s.total}</td>
          <td style="color:#4caf50">${s.pass}</td>
          <td style="color:#ff5252">${s.fail}</td>
          <td>${s.error}</td>
          <td>${s.passRate.toFixed(1)}%</td>
          <td>${s.avgIosMos?.toFixed(3) ?? "—"}</td>
          <td>${s.avgAndroidMos?.toFixed(3) ?? "—"}</td>
        </tr>`).join("");

      const bodyHtml = `
        <h2>🎉 ixi-O 통화기능 테스트 — ${milestone.toLocaleString()}회 달성</h2>
        <p>누적 테스트 횟수가 <b>${milestone.toLocaleString()}회</b>를 돌파했습니다. (총 ${total.toLocaleString()}건 DB 기록)</p>
        <h3>TC별 통계 요약</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="background:#1e2d4a;color:#fff">
              <th>TC ID</th><th>전체</th><th>PASS</th><th>FAIL</th><th>ERROR</th>
              <th>통과율</th><th>평균 MOS(iOS)</th><th>평균 MOS(AOS)</th>
            </tr>
          </thead>
          <tbody>${statsHtml}</tbody>
        </table>
        <p style="margin-top:16px">📎 첨부: 엑셀 통계 (전체 결과 + TC별 통계 + MOS 추이 + Severity) / JSON 전체 데이터</p>
        <p style="color:#888;font-size:12px">자동 발송 — ixi-O QA Bulls &nbsp;|&nbsp; ${new Date().toLocaleString("ko-KR")}</p>
      `;

      // ─── Keychain에서 SMTP 앱 비밀번호 조회 ────────────────────────────
      const appPassword = await invoke<string | null>("get_secret", { account: "smtp-app-password" }) ?? "";
      if (!appPassword) {
        console.warn("[milestone] SMTP 앱 비밀번호가 설정되지 않아 이메일 발송 건너뜀");
        return;
      }

      // ─── 이메일 발송 (엑셀 + JSON 첨부) ─────────────────────────────────
      await invoke("send_stats_email", { payload: {
        fromAddr:    "qabulls.test@gmail.com",
        appPassword,
        toAddrs:     MILESTONE_EMAILS,
        subject:     `[ixi-O] 누적 테스트 ${milestone.toLocaleString()}회 달성 통계`,
        bodyHtml,
        attachments: [xlsxPath, jsonPath],
      } });
      // 발송 성공 후에만 마일스톤 소비 — 실패 시 다음 TC 결과 적재 때 자동 재시도
      localStorage.setItem(MILESTONE_STORAGE_KEY, String(milestone));
      console.info(`[milestone] ${milestone}회 달성 메일 발송 완료 (xlsx: ${xlsxPath}, json: ${jsonPath})`);
    } catch (e) {
      console.warn("[milestone] 마일스톤 체크 실패:", e);
    }
  }

  // ── 실행 결과 업데이트 헬퍼 ────────────────────────────────────────────────

  function upsertResult(patch: Partial<TcResult> & { runId: string }) {
    // 상태 업데이터는 순수 함수여야 하므로 side effect(invoke) 없이 상태만 업데이트
    setTcResults((prev) => {
      const idx = prev.findIndex((r) => r.runId === patch.runId);
      if (idx === -1) return prev;
      const next = [...prev];
      next[idx] = { ...prev[idx], ...patch };
      // ref도 즉시 갱신 — 보고서 생성 등에서 최신 상태를 읽을 수 있도록
      tcResultsRef.current = next;
      return next;
    });

    // DB 저장은 상태 업데이터 밖에서 직접 호출
    const finalStatuses: TcStatus[] = ["PASS", "FAIL", "ERROR"];
    if (patch.status && finalStatuses.includes(patch.status as TcStatus)) {
      // finalResult 로 호출될 때 patch 자체가 완전한 TcResult 임
      const r = patch as TcResult;
      const runIdForLog  = r.runId;
      const repeatIdxLog = r.repeatIndex;
      invoke("db_save_result", {
        payload: {
          runId:               r.runId,
          sessionId:           r.sessionId ?? null,
          repeatIndex:         r.repeatIndex ?? null,
          tcId:                r.tcId,
          startedAt:           r.startedAt,
          finishedAt:          r.finishedAt,
          durationMs:          r.durationMs,
          status:              r.status,
          iosVisqolMos:        r.iosVisqolMos ?? null,
          androidVisqolMos:    r.androidVisqolMos ?? null,
          snrDb:               r.snrDb ?? null,
          dropoutCount:        r.dropoutCount ?? null,
          dropoutSeverity:     r.dropoutSeverity ?? null,
          dropoutReportPath:   r.dropoutReportPath ?? null,
          mosReportPath:       r.mosReportPath ?? null,
          vishingDetected:     r.vishingDetected ?? null,
          errorMsg:            r.errorMsg ?? null,
          extractedAudioPaths: r.extractedAudioPaths ?? [],
          screenshotPaths:     r.screenshotPaths ?? [],
          logLines:            r.logLines ?? [],
          // v2
          andDroppedCount:     r.andDroppedCount  ?? null,
          andDegradedCount:    r.andDegradedCount ?? null,
          andPoorCount:        r.andPoorCount     ?? null,
          andSeverity:         r.andSeverity      ?? null,
          iosDroppedCount:     r.iosDroppedCount  ?? null,
          iosDegradedCount:    r.iosDegradedCount ?? null,
          iosPoorCount:        r.iosPoorCount     ?? null,
          iosSeverity:         r.iosSeverity      ?? null,
          voipDelayMs:         r.voipDelayMs      ?? null,
          // v3
          androidAppVer:       r.androidAppVer    ?? null,
          iosAppVer:           r.iosAppVer        ?? null,
          androidDevice:       r.androidDevice    ?? null,
          androidOsVer:        r.androidOsVer     ?? null,
          iosDevice:           r.iosDevice        ?? null,
          iosOsVer:            r.iosOsVer         ?? null,
          profileName:         r.profileName      ?? null,
          // v4
          carrier:             r.carrier           ?? null,
        },
      }).then(() => {
        const ts    = new Date().toLocaleTimeString("ko-KR");
        const label = repeatIdxLog != null ? ` [#${repeatIdxLog}회차]` : "";
        setTcResults((prev) => {
          const i = prev.findIndex((x) => x.runId === runIdForLog);
          if (i === -1) return prev;
          const n = [...prev];
          n[i] = { ...n[i], logLines: [...(n[i].logLines ?? []), `[${ts}]${label} ✅ DB 적재 완료`] };
          return n;
        });
        checkMilestoneAndSendEmail();
      }).catch((e: unknown) => {
        const ts     = new Date().toLocaleTimeString("ko-KR");
        const label  = repeatIdxLog != null ? ` [#${repeatIdxLog}회차]` : "";
        const errMsg = String(e);
        setTcResults((prev) => {
          const i = prev.findIndex((x) => x.runId === runIdForLog);
          if (i === -1) return prev;
          const n = [...prev];
          n[i] = { ...n[i], logLines: [...(n[i].logLines ?? []), `[${ts}]${label} ❌ DB 적재 실패: ${errMsg}`] };
          return n;
        });
        console.warn("[db] 결과 저장 실패:", e);
      });
    }

    setRunningResults((prev) => {
      const cur = prev.get(patch.tcId as TcId);
      if (!cur) return prev;
      const next = new Map(prev);
      next.set(cur.tcId, { ...cur, ...patch });
      return next;
    });
  }

  function setSubStatus(runId: string, tcId: TcId, subStatus: string, phase?: 1 | 2) {
    upsertResult({ runId, tcId, subStatus, ...(phase ? { phase } : {}) });
  }

  // ── 예약 카운트다운 ──────────────────────────────────────────────────────────

  async function runScheduleDelay(scheduledAt: string): Promise<boolean> {
    const targetMs = new Date(scheduledAt).getTime();
    if (isNaN(targetMs)) return true; // 잘못된 날짜면 즉시 실행

    const updateCountdown = () => {
      const remaining = Math.ceil((targetMs - Date.now()) / 1000);
      setScheduleCountdown(remaining > 0 ? remaining : 0);
      return remaining;
    };

    const first = updateCountdown();
    if (first <= 0) { setScheduleCountdown(null); return true; }

    const fmtTarget = new Date(scheduledAt).toLocaleString("ko-KR");
    setStatusMessage(tRef.current("status.scheduleDelay", { min: String(Math.ceil(first / 60)) })
      .replace(/\d+분 후/, `${fmtTarget}에`));

    return new Promise<boolean>((resolve) => {
      const interval = setInterval(() => {
        if (stopRef.current) {
          clearInterval(interval);
          setScheduleCountdown(null);
          resolve(false);
          return;
        }
        const remaining = updateCountdown();
        if (remaining <= 0) {
          clearInterval(interval);
          setScheduleCountdown(null);
          resolve(true);
        }
      }, 1000);
    });
  }

  // ── TC → Appium 포트 매핑 ──────────────────────────────────────────────────

  function tcAppiumPorts(tcId: TcId): { android: number; ios: number; group: string } {
    if (tcId === "TC_00" || tcId === "TC_01" || tcId === "TC_02") {
      return { android: 4725, ios: 4726, group: "A" };
    }
    return { android: 4727, ios: 4728, group: "B" };
  }

  async function startTcAppiumForGroups(tcIds: TcId[]): Promise<void> {
    const groups = new Set(tcIds.map((id) => tcAppiumPorts(id).group));
    for (const grp of groups) {
      setStatusMessage(tRef.current("status.appiumStarting", { grp }));
      try {
        await invoke<ConnectionStatus>("start_tc_appium_servers", { group: grp });
      } catch (e) {
        setStatusMessage(tRef.current("status.appiumStartFail", { grp, err: String(e) }));
      }
    }
  }

  async function stopTcAppiumServers(): Promise<void> {
    try { await invoke("stop_tc_appium_servers"); } catch {}
  }

  // ── 단일 TC 1회 실행 ────────────────────────────────────────────────────────

  async function runSingleTc(
    tcId: TcId,
    deps: RunnerCallDeps,
    sessionId: string | null,
    repeatIndex: number | null,
  ): Promise<TcResult> {
    const runId = crypto.randomUUID();
    const startedAt = new Date().toISOString();

    const placeholder: TcResult = {
      runId, sessionId, repeatIndex, tcId,
      startedAt, finishedAt: startedAt, durationMs: 0,
      status: "RUNNING", phase: null, subStatus: "준비 중...",
      iosVisqolMos: null, androidVisqolMos: null, snrDb: null,
      dropoutCount: null, dropoutSeverity: null,
      dropoutReportPath: null, mosReportPath: null,
      extractedAudioPaths: [],
      screenshotPaths: [], vishingDetected: null, logLines: [], errorMsg: null,
      andDroppedCount: null, andDegradedCount: null, andPoorCount: null, andSeverity: null,
      iosDroppedCount: null, iosDegradedCount: null, iosPoorCount: null, iosSeverity: null,
      voipDelayMs: null,
      androidAppVer: null, iosAppVer: null, androidDevice: null, androidOsVer: null,
      iosDevice: null, iosOsVer: null, profileName: null,
      carrier: null,
    };
    setRunningResults((prev) => new Map(prev).set(tcId, placeholder));
    setTcResults((prev) => {
      // runId가 이미 없으면 placeholder를 앞에 추가 (실행 중 대시보드 표시용)
      if (prev.some((r) => r.runId === runId)) return prev;
      return [placeholder, ...prev];
    });

    // TC별 설정 결정
    // ── 1) 디바이스 배치: TC 개별 설정 > 역방향 자동스왑 > 전역
    const tcEntry = deps.tcSpeakerConfig[tcId];
    const isReverse = tcId === "TC_02" || tcId === "TC_04";
    const hasTcDeviceOverride = !!(tcEntry?.speaker1Device && tcEntry?.speaker2Device);

    let s1Device: string, s2Device: string;
    if (hasTcDeviceOverride) {
      // 사용자가 TC UI에서 양쪽 디바이스를 직접 지정 → 그대로 사용
      s1Device = tcEntry!.speaker1Device;
      s2Device = tcEntry!.speaker2Device;
    } else if (isReverse) {
      // TC_02/TC_04: 전역 디바이스를 자동 스왑
      s1Device = deps.speaker2Device;
      s2Device = deps.speaker1Device;
    } else {
      s1Device = deps.speaker1Device;
      s2Device = deps.speaker2Device;
    }

    // 디바이스가 전역 대비 뒤바뀌었는지 감지 → 번호·하드웨어·음원 연동
    const devicesReversed =
      s1Device === deps.speaker2Device && s2Device === deps.speaker1Device;

    // ── 2) 전화번호 (디바이스에 바인딩)
    const s1Number = devicesReversed ? deps.speaker2Number : deps.speaker1Number;
    const s2Number = devicesReversed ? deps.speaker1Number : deps.speaker2Number;

    // ── 3) 프로파일(콘텐츠) — 음원은 포지션(speaker1/speaker2)을 따름
    //   역방향 TC에서도 "화자1 대사 / 화자2 대사"는 고정 → 디바이스가 바뀌므로
    //   각 단말이 TC_01 과 다른 음원을 전송하게 됨
    const tcProfile = tcEntry?.profileId
      ? deps.profiles.find((p) => p.id === tcEntry.profileId) ?? null
      : null;
    const s1File = tcProfile?.speaker1AudioFile || deps.speaker1AudioFile;
    const s2File = tcProfile?.speaker2AudioFile || deps.speaker2AudioFile;

    // ── 4) 하드웨어 라우팅 (전역, 디바이스 위치에 따라 스왑)
    const s1Output  = devicesReversed ? deps.speaker2OutputDevice : deps.speaker1OutputDevice;
    const s2Output  = devicesReversed ? deps.speaker1OutputDevice : deps.speaker2OutputDevice;
    const s1Ch      = devicesReversed ? deps.speaker2Channel : deps.speaker1Channel;
    const s2Ch      = devicesReversed ? deps.speaker1Channel : deps.speaker2Channel;
    const s1RecCh   = devicesReversed ? deps.speaker2RecChannel : deps.speaker1RecChannel;
    const s2RecCh   = devicesReversed ? deps.speaker1RecChannel : deps.speaker2RecChannel;
    const s1OutPair = devicesReversed ? deps.speaker2OutputPair : deps.speaker1OutputPair;
    const s2OutPair = devicesReversed ? deps.speaker1OutputPair : deps.speaker2OutputPair;

    if (devicesReversed) {
      console.log(`↔️ ${tcId}: 디바이스 역순 감지 → 번호·하드웨어 스왑 (음원은 포지션 유지)`);
      console.log(`  s1=${s1Device} (${s1Number}) audio=${s1File}`);
      console.log(`  s2=${s2Device} (${s2Number}) audio=${s2File}`);
    }

    setSubStatus(runId, tcId, tRef.current("status.subRunning"), 1);
    setStatusMessage(tRef.current("status.tcRunning", { tcId }));

    try {
      const ports = tcAppiumPorts(tcId);
      const result = await invoke<TestRunResult>("run_ixio_test", {
        speaker1Device: s1Device,
        speaker2Device: s2Device,
        speaker1Number: s1Number,
        speaker2Number: s2Number,
        speaker1AudioFile: s1File,
        speaker2AudioFile: s2File,
        speaker1OutputDevice: s1Output !== "" ? parseInt(s1Output) : null,
        speaker2OutputDevice: s2Output !== "" ? parseInt(s2Output) : null,
        speaker1Channel: s1Ch !== "" ? s1Ch : null,
        speaker2Channel: s2Ch !== "" ? s2Ch : null,
        speaker1RecChannel: s1RecCh !== "" ? s1RecCh : null,
        speaker2RecChannel: s2RecCh !== "" ? s2RecCh : null,
        speaker1OutputPair: s1OutPair !== "" ? s1OutPair : null,
        speaker2OutputPair: s2OutPair !== "" ? s2OutPair : null,
        appiumPortAndroid: ports.android,
        appiumPortIos: ports.ios,
        tcType: tcId,
        recordingMode: (s1RecCh || s2RecCh)
          ? "direct"
          : (localStorage.getItem("recordingMode") || "extract"),
        androidAppPackage: (() => {
          try {
            const cfg: TargetAppConfig = JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG;
            return SUPPORTED_APPS.find(a => a.id === cfg.androidAppId)?.package ?? null;
          } catch { return null; }
        })(),
        androidAppActivity: (() => {
          try {
            const cfg: TargetAppConfig = JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG;
            return SUPPORTED_APPS.find(a => a.id === cfg.androidAppId)?.activity ?? null;
          } catch { return null; }
        })(),
        iosAppBundleId: (() => {
          try {
            const cfg: TargetAppConfig = JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG;
            return SUPPORTED_APPS.find(a => a.id === cfg.iosAppId)?.bundleId ?? null;
          } catch { return null; }
        })(),
        carrier: localStorage.getItem("selectedCarrier") || DEFAULT_CARRIER,
      });

      const finishedAt = new Date().toISOString();
      const durationMs = Date.parse(finishedAt) - Date.parse(startedAt);
      const status: TcStatus = result.success ? "PASS" : "FAIL";

      // 단말에서 수집된 음원 경로 추출
      const extractedAudioPaths: { label: string; path: string }[] = [];
      if (result.ios_recording) extractedAudioPaths.push({ label: "iOS 녹음", path: result.ios_recording });
      if (result.android_recording) extractedAudioPaths.push({ label: "Android 녹음", path: result.android_recording });

      // 스크린샷 경로
      const screenshotPaths: string[] = result.screenshots ?? [];

      // 보이스피싱 감지 결과 (TC_03/TC_04 전용)
      const vishingDetected: boolean | null =
        result.vishing_detected != null ? result.vishing_detected : null;

      setStatusMessage(result.message);
      setSubStatus(runId, tcId, result.success ? tRef.current("status.subDone") : tRef.current("status.subFail"));

      // TC_00~TC_04 완료 시 분석 자동 실행
      let dropoutCount: number | null = null;
      let dropoutSeverity: DropoutSeverity | null = null;
      let dropoutReportPath: string | null = null;
      let iosVisqolMos: number | null = null;
      let androidVisqolMos: number | null = null;
      // v2
      let andDroppedCount:  number | null = null;
      let andDegradedCount: number | null = null;
      let andPoorCount:     number | null = null;
      let andSeverity:      string | null = null;
      let iosDroppedCount:  number | null = null;
      let iosDegradedCount: number | null = null;
      let iosPoorCount:     number | null = null;
      let iosSeverity:      string | null = null;
      let voipDelayMs:      number | null = null;
      // v3
      let androidAppVer:    string | null = null;
      let iosAppVer:        string | null = null;
      let androidDevice:    string | null = null;
      let androidOsVer:     string | null = null;
      let iosDevice:        string | null = null;
      let iosOsVer:         string | null = null;
      let profileName:      string | null = null;
      // v4: 통신사
      const carrier: string | null = localStorage.getItem("selectedCarrier") || DEFAULT_CARRIER;

      if (["TC_00", "TC_01", "TC_02", "TC_03", "TC_04"].includes(tcId) && result.success) {
        setStatusMessage(tRef.current("status.tcAnalyzing", { tcId }));
        setSubStatus(runId, tcId, tRef.current("status.subAnalyzing"));
        try {
          // TC에 연결된 프로파일이 있으면 해당 프로파일의 ref/script 사용
          const effectiveRefS1 = tcProfile?.refAudioPathS1 || deps.refAudioPathS1;
          const effectiveRefS2 = tcProfile?.refAudioPathS2 || deps.refAudioPathS2;
          // TC_00: MOS 전용 — 대본(스크립트) 없이 분석
          const isMosOnly = tcId === "TC_00";
          const effectiveScript = isMosOnly ? "" : (tcProfile?.scriptPath || deps.scriptPath);
          const effectiveProfileName = tcProfile?.name || deps.profileName;

          // 앱 태그 도출 (보고서 파일명용) + 패키지명 (버전 조회용)
          let appTag = "ixiO_ixiO";
          let androidAppPkg: string | null = null;
          let iosAppBid: string | null = null;
          try {
            const cfg: TargetAppConfig = JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG;
            const aApp = SUPPORTED_APPS.find(a => a.id === cfg.androidAppId);
            const iApp = SUPPORTED_APPS.find(a => a.id === cfg.iosAppId);
            appTag = `${aApp?.tag ?? "ixiO"}_${iApp?.tag ?? "ixiO"}`;
            androidAppPkg = aApp?.package ?? null;
            iosAppBid = iApp?.bundleId ?? null;
          } catch { /* fallback */ }
          const analysisResult = await invoke<DropoutAnalysisResult>("run_dropout_analysis", {
            refAudioPathS1: effectiveRefS1,
            refAudioPathS2: effectiveRefS2,
            scriptPath: effectiveScript,
            profileName: effectiveProfileName,
            tcType: tcId,
            appTag,
            androidAppPackage: androidAppPkg,
            iosAppBundleId: iosAppBid,
          });
          // TC_00(MOS 전용): report_path 없음 — MOS 세션 보고서만 별도 생성
          if (!isMosOnly && analysisResult.report_path) {
            dropoutReportPath = analysisResult.report_path;
          }
          // TC_00: 음단절 통계 불필요 — MOS 값만 수집
          if (!isMosOnly && analysisResult.dropout_count != null) {
            dropoutCount = analysisResult.dropout_count;
          }
          if (!isMosOnly && analysisResult.severity) {
            dropoutSeverity = analysisResult.severity as DropoutSeverity;
          }
          if (analysisResult.ios_visqol_mos != null) {
            iosVisqolMos = analysisResult.ios_visqol_mos;
          }
          if (analysisResult.android_visqol_mos != null) {
            androidVisqolMos = analysisResult.android_visqol_mos;
          }
          // v2 필드
          andDroppedCount  = analysisResult.and_dropped_count  ?? null;
          andDegradedCount = analysisResult.and_degraded_count ?? null;
          andPoorCount     = analysisResult.and_poor_count     ?? null;
          andSeverity      = analysisResult.and_severity       ?? null;
          iosDroppedCount  = analysisResult.ios_dropped_count  ?? null;
          iosDegradedCount = analysisResult.ios_degraded_count ?? null;
          iosPoorCount     = analysisResult.ios_poor_count     ?? null;
          iosSeverity      = analysisResult.ios_severity       ?? null;
          voipDelayMs      = analysisResult.voip_delay_ms      ?? null;
          // v3 필드
          androidAppVer    = analysisResult.android_app_ver    || null;
          iosAppVer        = analysisResult.ios_app_ver        || null;
          androidDevice    = analysisResult.android_device     || null;
          androidOsVer     = analysisResult.android_os_ver     || null;
          iosDevice        = analysisResult.ios_device         || null;
          iosOsVer         = analysisResult.ios_os_ver         || null;
          profileName      = analysisResult.profile_name       || null;
        } catch (e) {
          console.warn("[TC] 음원 분석 실패:", e);
        }
      }

      const finalResult: TcResult = {
        ...placeholder,
        finishedAt, durationMs, status,
        subStatus: result.success ? tRef.current("status.subDone") : tRef.current("status.subFail"),
        logLines: [result.message],
        errorMsg: result.success ? null : result.message,
        extractedAudioPaths,
        screenshotPaths,
        vishingDetected,
        dropoutCount, dropoutSeverity, dropoutReportPath,
        iosVisqolMos, androidVisqolMos,
        andDroppedCount, andDegradedCount, andPoorCount, andSeverity,
        iosDroppedCount, iosDegradedCount, iosPoorCount, iosSeverity,
        voipDelayMs,
        androidAppVer, iosAppVer, androidDevice, androidOsVer,
        iosDevice, iosOsVer, profileName,
        carrier,
      };

      upsertResult(finalResult);
      return finalResult;

    } catch (e) {
      const finishedAt = new Date().toISOString();
      const durationMs = Date.parse(finishedAt) - Date.parse(startedAt);
      const finalResult: TcResult = {
        ...placeholder,
        finishedAt, durationMs, status: "ERROR",
        subStatus: tRef.current("status.subError"),
        errorMsg: String(e),
      };
      upsertResult(finalResult);
      return finalResult;
    }
  }

  // ── 세트 1회 실행 (선택된 TC 순서대로) ─────────────────────────────────────

  async function runSet(
    tcIds: TcId[],
    deps: RunnerCallDeps,
    sessionId: string,
    repeatIndex: number | null,
    failAction: RepeatOptions["failAction"],
    runIds: string[],
    runResultsMap?: Map<string, TcResult>,
  ): Promise<boolean> {
    // QUEUED 상태 미리 표시
    for (const tcId of tcIds) {
      setRunningResults((prev) => {
        const next = new Map(prev);
        const placeholder: TcResult = {
          runId: "", sessionId, repeatIndex, tcId,
          startedAt: new Date().toISOString(), finishedAt: "",
          durationMs: 0, status: "QUEUED", phase: null, subStatus: tRef.current("status.subQueued"),
          iosVisqolMos: null, androidVisqolMos: null, snrDb: null,
          dropoutCount: null, dropoutSeverity: null,
          dropoutReportPath: null, mosReportPath: null,
          extractedAudioPaths: [],
          screenshotPaths: [], vishingDetected: null, logLines: [], errorMsg: null,
          andDroppedCount: null, andDegradedCount: null, andPoorCount: null, andSeverity: null,
          iosDroppedCount: null, iosDegradedCount: null, iosPoorCount: null, iosSeverity: null,
          voipDelayMs: null,
          androidAppVer: null, iosAppVer: null, androidDevice: null, androidOsVer: null,
          iosDevice: null, iosOsVer: null, profileName: null,
          carrier: null,
        };
        next.set(tcId, placeholder);
        return next;
      });
    }

    for (const tcId of tcIds) {
      if (stopRef.current) return false;
      const result = await runSingleTc(tcId, deps, sessionId, repeatIndex);
      // set 모드에서도 runId 수집 (세션 등록용)
      if (result.runId) {
        runIds.push(result.runId);
        runResultsMap?.set(result.runId, result);
        updateActiveSessionRunIds(runIds);
      }
      if (stopRef.current) return false;
      if (result.status === "FAIL" || result.status === "ERROR") {
        if (failAction === "stop") return false;
      }
    }
    return true;
  }

  // ── 메인 실행 함수 ──────────────────────────────────────────────────────────

  const startTc = useCallback(async (
    selectedTcs: Set<TcId>,
    deps: RunnerCallDeps,
    repeat: RepeatOptions,
    schedule: ScheduleOptions,
    providedSessionId?: string,
  ) => {
    stopRef.current = false;
    setIsTcRunning(true);
    setRunningResults(new Map());
    setRepeatProgress(null);

    const tcIds = Array.from(selectedTcs);

    // TC Appium 자동 시작
    await startTcAppiumForGroups(tcIds);
    // 예약 탭 연동: ScheduleTab에서 사전 생성한 sessionId 사용, 없으면 샨 생성
    const sessionId = providedSessionId ?? crypto.randomUUID();
    const sessionStartedAt = new Date().toISOString();
    const runIds: string[] = [];

    // ── 세션 시작 시점의 앱 선택 캡처 ─────────────────────────────────────────
    // 보고서 생성은 세션 종료 후이므로, 그 사이 앱 선택이 바뀌어도 올바른 이름 유지
    let sessionAppConfig: TargetAppConfig;
    try { sessionAppConfig = JSON.parse(localStorage.getItem("targetAppConfig") || "null") ?? DEFAULT_APP_CONFIG; }
    catch { sessionAppConfig = DEFAULT_APP_CONFIG; }
    const sessionAndroidApp = SUPPORTED_APPS.find(a => a.id === sessionAppConfig.androidAppId);
    const sessionIosApp     = SUPPORTED_APPS.find(a => a.id === sessionAppConfig.iosAppId);

    // 활성 세션 즉시 저장 — 강제 종료 시에도 세션 정보 복구 가능
    try {
      localStorage.setItem(STORAGE_ACTIVE_SESSION_KEY, JSON.stringify({
        sessionId,
        tcIds,
        startedAt: sessionStartedAt,
        repeatOptions: repeat.count > 1 ? repeat : null,
        runIds: [],
      }));
    } catch {}

    // ── DB 세션 선행 저장 ─────────────────────────────────────────────────────
    // db_save_result 가 FK(session_id) 제약을 통과하려면 세션이 먼저 DB에 있어야 함.
    // 완료 시 finishedAt 포함 재호출(upsert)하므로 여기선 finishedAt=null 로 등록.
    invoke("db_save_session", {
      payload: {
        sessionId,
        tcIds,
        startedAt:   sessionStartedAt,
        finishedAt:  null,
        repeatCount: repeat.count > 1 ? repeat.count : null,
        repeatMode:  repeat.count > 1 ? repeat.mode  : null,
        failAction:  repeat.count > 1 ? repeat.failAction : null,
      },
    }).catch((e: unknown) => console.warn("[db] 세션 선행 저장 실패:", e));

    // 예약 딜레이
    if (schedule.enabled && schedule.scheduledAt) {
      const ok = await runScheduleDelay(schedule.scheduledAt);
      if (!ok) {
        setIsTcRunning(false);
        stopRef.current = false;
        return;
      }
    }

    const total = repeat.count;
    setRepeatProgress(total > 1 ? { current: 0, total } : null);
    const runResultsMap = new Map<string, TcResult>();

    if (repeat.mode === "set") {
      // 세트 반복: (TC_01 → TC_02 → TC_03) × N회
      for (let i = 1; i <= total; i++) {
        if (stopRef.current) break;
        if (total > 1) setRepeatProgress({ current: i, total });
        const ok = await runSet(tcIds, deps, sessionId, total > 1 ? i : null, repeat.failAction, runIds, runResultsMap);
        if (!ok && repeat.failAction === "stop") break;
        if (!stopRef.current && i < total) {
          setStatusMessage(tRef.current("status.setComplete", { cur: String(i), total: String(total) }));
          await sleep(3000, stopRef);
        }
      }
    } else {
      // TC별 반복: TC_01 × N회, 그 다음 TC_02 × N회
      for (const tcId of tcIds) {
        if (stopRef.current) break;
        for (let i = 1; i <= total; i++) {
          if (stopRef.current) break;
          if (total > 1) setRepeatProgress({ current: i, total });
          const result = await runSingleTc(tcId, deps, sessionId, total > 1 ? i : null);
          runIds.push(result.runId);
          runResultsMap.set(result.runId, result);
          updateActiveSessionRunIds(runIds);
          if ((result.status === "FAIL" || result.status === "ERROR") && repeat.failAction === "stop") break;
          if (!stopRef.current && i < total) {
            await sleep(3000, stopRef);
          }
        }
      }
    }

    // 활성 세션 키 정리 후 세션 등록
    try { localStorage.removeItem(STORAGE_ACTIVE_SESSION_KEY); } catch {}
    const finishedSession = {
      sessionId,
      tcIds,
      startedAt: sessionStartedAt,
      finishedAt: new Date().toISOString(),
      repeatOptions: repeat.count > 1 ? repeat : null,
      runIds,
    };
    setSessions((prev) => [...prev, finishedSession]);

    // 세션 DB 저장
    invoke("db_save_session", {
      payload: {
        sessionId,
        tcIds,
        startedAt:    sessionStartedAt,
        finishedAt:   finishedSession.finishedAt,
        repeatCount:  repeat.count > 1 ? repeat.count : null,
        repeatMode:   repeat.count > 1 ? repeat.mode  : null,
        failAction:   repeat.count > 1 ? repeat.failAction : null,
      },
    }).catch((e: unknown) => console.warn("[db] 세션 저장 실패:", e));

    // ── TC_00 MOS 전용 보고서 생성 ──────────────────────────────────────────
    if (tcIds.includes("TC_00" as TcId) && runIds.length > 0) {
      try {
        setStatusMessage("📊 MOS 측정 보고서 생성 중…");
        // runSingleTc 반환값에서 직접 수집한 결과 사용 (React 배치 지연 회피)
        const collectedResults = runIds
          .map((id) => runResultsMap.get(id))
          .filter((r): r is TcResult => r != null);
        const sessionRuns = collectedResults
          .filter((r) => r.tcId === "TC_00")
          .map((r) => ({
            repeat_index: r.repeatIndex,
            ios_visqol_mos: r.iosVisqolMos,
            android_visqol_mos: r.androidVisqolMos,
            voip_delay_ms: r.voipDelayMs,
            started_at: r.startedAt,
            duration_ms: r.durationMs,
            status: r.status,
          }));
        if (sessionRuns.length > 0) {
          // 디바이스 정보: 마지막 결과에서 추출
          const lastResult = collectedResults
            .filter((r) => r.tcId === "TC_00")
            .pop();
          // 앱 설정에서 앱 이름 가져오기
          // 세션 시작 시 캡처한 앱 정보 사용 (보고서 생성 전에 앱이 바뀌어도 올바른 이름 표시)
          const testInfo = lastResult ? {
            android_device: lastResult.androidDevice ?? "",
            android_os_ver: lastResult.androidOsVer ?? "",
            android_app_ver: lastResult.androidAppVer ?? "",
            android_app_name: sessionAndroidApp?.name ?? "",
            ios_device: lastResult.iosDevice ?? "",
            ios_os_ver: lastResult.iosOsVer ?? "",
            ios_app_ver: lastResult.iosAppVer ?? "",
            ios_app_name: sessionIosApp?.name ?? "",
            profile_name: lastResult.profileName ?? "",
            carrier: lastResult.carrier ?? "",
            carrier_name: SUPPORTED_CARRIERS.find(c => c.id === (lastResult.carrier ?? ""))?.name ?? "",
          } : {};
          const reportData = JSON.stringify({
            session_id: sessionId,
            test_info: testInfo,
            runs: sessionRuns,
          });
          const mosReport = await invoke<{ success: boolean; reportPath: string; message: string }>(
            "generate_mos_report", { runsJson: reportData }
          );
          if (mosReport.success && mosReport.reportPath) {
            console.info("[mos-report] 보고서 생성 완료:", mosReport.reportPath);
            // 마지막 TC_00 결과에 보고서 경로 연결
            const lastTc00 = collectedResults
              .filter((r) => r.tcId === "TC_00")
              .pop();
            if (lastTc00) {
              upsertResult({ runId: lastTc00.runId, mosReportPath: mosReport.reportPath });
              // DB에도 mos_report_path 반영 (upsertResult는 status 변경 시에만 DB 저장)
              invoke("db_update_mos_report_path", {
                runId: lastTc00.runId,
                path: mosReport.reportPath,
              }).catch((e: unknown) => console.warn("[db] mos_report_path 업데이트 실패:", e));
            }
            // 보고서 자동 열기
            invoke("open_report", { path: mosReport.reportPath }).catch(() => {});
          }
        }
      } catch (e) {
        console.warn("[mos-report] MOS 보고서 생성 실패:", e);
      }
    }

    setRepeatProgress(null);
    setRunningResults(new Map());
    setIsTcRunning(false);
    stopRef.current = false;
    setStatusMessage(tRef.current("status.appiumStopping"));
    await stopTcAppiumServers();
    setStatusMessage(tRef.current("status.tcComplete"));
  }, []);

  const stopTc = useCallback(async () => {
    stopRef.current = true;
    try {
      setStatusMessage(tRef.current("status.tcStopping"));
      const result = await invoke<ConnectionStatus>("stop_test");
      setStatusMessage(result.message);
    } catch (error) {
      setStatusMessage(tRef.current("status.tcStopFail", { err: String(error) }));
    } finally {
      setIsTcRunning(false);
    }
  }, []);

  const clearResults = useCallback(() => {
    setTcResults([]);
    setSessions([]);
    setRunningResults(new Map());
  }, []);

  const deleteSelected = useCallback((runIds: Set<string>) => {
    setTcResults((prev) => prev.filter((r) => !runIds.has(r.runId)));
    setSessions((prev) => prev.filter((s) => s.runIds.some((id) => !runIds.has(id))));
  }, []);

  return {
    isTcRunning, tcResults, sessions, runningResults,
    repeatProgress, scheduleCountdown,
    startTc, stopTc, clearResults, deleteSelected,
  };
}

function sleep(ms: number, stopRef: React.MutableRefObject<boolean>): Promise<void> {
  return new Promise<void>((resolve) => {
    const check = setInterval(() => {
      if (stopRef.current) { clearTimeout(id); clearInterval(check); resolve(); }
    }, 200);
    const id = setTimeout(() => { clearInterval(check); resolve(); }, ms);
  });
}
