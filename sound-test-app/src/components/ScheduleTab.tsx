/**
 * ScheduleTab — 칸반보드형 테스트 예약 관리
 *   [대기중] → [테스트 중] → [테스트 완료]  /  [재테스트] 드롭존
 *   - 대기중 칸반은 쌓인 순서대로 자동 실행
 *   - 시간 지정 예약도 지원 (선택)
 *   - 완료된 카드를 [재테스트] 구역에 드래그 → 대기열 재진입
 */
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { createPortal } from "react-dom";
import { invoke } from "@tauri-apps/api/core";
import type { TcId, RepeatOptions, ScheduleOptions } from "../types";
import { TC_DEFS } from "./TcSelectPanel";
import { useT } from "../i18n";

// ── 타입 ─────────────────────────────────────────────────────────────────────

export interface ScheduleEntry {
  id: string;
  scheduledAt: string | null;     // null = 즉시 대기열, string = 시간 지정
  repeatOptions: RepeatOptions;
  tcIds: TcId[];
  label: string;
  status: "pending" | "running" | "done" | "cancelled";
  createdAt: string;
  sessionId?: string | null;      // running 시 채워짐 → 재시작 시 인터럽트 감지용
}

function saveSchedules(list: ScheduleEntry[]) {
  invoke("save_schedules", { schedules: JSON.stringify(list) }).catch(() => {});
}

// ── 대기열 시간 추산 타입 ────────────────────────────────────────────────────

interface QueueEstimate {
  avgMsPerTcSet: number;
  runningCompleted: number;
  runningTotal: number;
  runningStartedAt: string | null;
}

interface EntryEta {
  estStart: Date;
  estEnd: Date;
}

// 기본값: 2.625분/TC/세트 (실측 5.25분/세트 ÷ 2 TC)
const DEFAULT_MS_PER_TC_SET = 157500;

function fmtShort(iso: string | null, lang: string) {
  if (!iso) return null;
  return new Date(iso).toLocaleString(lang === "ko" ? "ko-KR" : "en-US", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function msUntil(iso: string): number {
  return new Date(iso).getTime() - Date.now();
}

function fmtRemaining(iso: string, t: (k: string, v?: Record<string, string | number>) => string): string {
  const ms = msUntil(iso);
  if (ms <= 0) return t("schedule.soonStart");
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  if (d > 0) return t("schedule.inDay", { d, h, m });
  if (h > 0) return t("schedule.inHour", { h, m, s: ss });
  if (m > 0) return t("schedule.inMin", { m, s: ss });
  return t("schedule.inSec", { s: ss });
}

function getWeekdayBtns(lang: string) {
  const locale = lang === "ko" ? "ko-KR" : "en-US";
  return [1, 2, 3, 4, 5, 6, 0].map((dow) => ({
    label: new Intl.DateTimeFormat(locale, { weekday: "short" }).format(new Date(2024, 0, 7 + dow)),
    dow,
  }));
}

// ── 시간 그리드 팝업 ──────────────────────────────────────────────────────────

function usePickerPortal(open: boolean, close: () => void) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    if (!open) { setPos(null); return; }
    const rect = wrapRef.current?.getBoundingClientRect();
    if (rect) setPos({ top: rect.bottom + 4, left: rect.left });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      const target = e.target as Node;
      const insideWrap = wrapRef.current?.contains(target);
      const popup = document.querySelector(".time-picker-popup-portal");
      const insidePopup = popup?.contains(target);
      if (!insideWrap && !insidePopup) close();
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, close]);

  return { wrapRef, pos };
}

function HourPicker({ value, onChange }: { value: number | null; onChange: (h: number) => void }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const { wrapRef, pos } = usePickerPortal(open, close);
  const { t } = useT();
  const unit = t("schedule.hourUnit");
  const nowHour = new Date().getHours();

  return (
    <div ref={wrapRef} className="time-picker-wrap">
      <button type="button" className={`time-picker-btn${value !== null ? " selected" : ""}`}
        onClick={() => setOpen((v) => !v)}>
        {value !== null ? `${String(value).padStart(2, "00")}${unit}` : `-- ${unit}`}
        <span className="time-picker-caret">▾</span>
      </button>
      {open && pos && createPortal(
        <div className="time-picker-popup time-picker-popup-portal"
          style={{ position: "fixed", top: pos.top, left: pos.left }}>
          <div className="time-picker-grid time-picker-grid-6col">
            {Array.from({ length: 24 }, (_, i) => (
              <button key={i} type="button"
                className={`time-cell${value === i ? " active" : ""}${i === nowHour && value !== i ? " time-cell-now" : ""}`}
                onClick={() => { onChange(i); close(); }}>
                {String(i).padStart(2, "0")}
              </button>
            ))}
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

function MinutePicker({ value, disabled, onChange }: { value: number | null; disabled?: boolean; onChange: (m: number) => void }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const { wrapRef, pos } = usePickerPortal(open, close);
  const { t } = useT();
  const unit = t("schedule.minuteUnit");
  const nowMin = new Date().getMinutes();

  return (
    <div ref={wrapRef} className="time-picker-wrap">
      <button type="button" className={`time-picker-btn${value !== null ? " selected" : ""}${disabled ? " disabled" : ""}`}
        disabled={disabled}
        onClick={() => !disabled && setOpen((v) => !v)}>
        {value !== null ? `${String(value).padStart(2, "0")}${unit}` : `-- ${unit}`}
        <span className="time-picker-caret">▾</span>
      </button>
      {open && pos && createPortal(
        <div className="time-picker-popup time-picker-popup-portal"
          style={{ position: "fixed", top: pos.top, left: pos.left }}>
          <div className="time-picker-grid time-picker-grid-10col">
            {Array.from({ length: 60 }, (_, i) => (
              <button key={i} type="button"
                className={`time-cell${value === i ? " active" : ""}${i === nowMin && value !== i ? " time-cell-now" : ""}`}
                onClick={() => { onChange(i); close(); }}>
                {String(i).padStart(2, "0")}
              </button>
            ))}
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

function nextDateOfWeekday(dow: number): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = (dow - today.getDay() + 7) % 7;
  const d = new Date(today);
  d.setDate(today.getDate() + diff);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

function fmtDate(yyyymmdd: string, lang: string): string {
  const [y, m, d] = yyyymmdd.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  return new Intl.DateTimeFormat(lang === "ko" ? "ko-KR" : "en-US", {
    year: "numeric", month: "long", day: "numeric", weekday: "short",
  }).format(date);
}

// ── Props ────────────────────────────────────────────────────────────────────

interface Props {
  enabledTcIds: Set<TcId>;
  isTcRunning: boolean;
  onTrigger: (tcIds: Set<TcId>, repeat: RepeatOptions, schedule: ScheduleOptions, sessionId: string) => void;
}

// ── Main Component ────────────────────────────────────────────────────────────

export function ScheduleTab({ enabledTcIds, isTcRunning, onTrigger }: Props) {
  const { t, lang } = useT();
  const [schedules, setSchedules] = useState<ScheduleEntry[]>([]);
  const schedulesRef = useRef<ScheduleEntry[]>([]);  // 항상 최신 schedules — fireEntry 등에서 직접 읽기용
  const [schedulesLoaded, setSchedulesLoaded] = useState(false);
  const [_now, setNow] = useState(Date.now());
  const prevRunningRef = useRef(false);
  const isTcRunningRef = useRef(isTcRunning);
  const onTriggerRef   = useRef(onTrigger);
  // fireRef: fireEntry 호출 후 isTcRunning prop 갱신 전까지 True → 이중 발화 차단
  const fireRef = useRef(false);
  useEffect(() => {
    isTcRunningRef.current = isTcRunning;
    if (isTcRunning) fireRef.current = false;  // prop 갱신 확인 → 플래그 해제
  }, [isTcRunning]);
  useEffect(() => { onTriggerRef.current = onTrigger; }, [onTrigger]);

  // 폼 상태
  const [showForm,  setShowForm]  = useState(false);
  const [formTcs,   setFormTcs]   = useState<TcId[]>(["TC_01", "TC_02"]);
  const [formCount, setFormCount] = useState(10);
  const [formMode,  setFormMode]  = useState<"set" | "tc">("set");
  const [formFail,  setFormFail]  = useState<"stop" | "continue" | "retry_crash">("continue");
  const [formLabel, setFormLabel] = useState("");
  const [formDate,  setFormDate]  = useState("");         // YYYY-MM-DD
  const [formHour,  setFormHour]  = useState<number | null>(null); // 0-23
  const [formMin,   setFormMin]   = useState<number | null>(null); // 0-59
  const [formDateMode, setFormDateMode] = useState<string | null>(null); // "0"-"6"=요일, "custom", null
  const [showCalendar, setShowCalendar] = useState(false);
  const [editId, setEditId] = useState<string | null>(null); // null=신규, string=수정 중인 entry id

  // 재개 팝업 상태: { entry, completedSets, totalSets }
  const [resumePrompts, setResumePrompts] = useState<
    Array<{ entry: ScheduleEntry; completed: number; total: number }>
  >([]);

  // 드래그 상태
  const [dragId,   setDragId]   = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<"pending" | "retest" | null>(null);

  // 시간 지정 타이머 refs
  const timerRefs = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // stale 복구 완료 여부 — 앱 재시작 시 resumePrompts 결정 전에 자동 큐 실행을 차단
  const [staleCheckDone, setStaleCheckDone] = useState(false);

  // 대기열 시간 추산
  const [queueEstimate, setQueueEstimate] = useState<QueueEstimate | null>(null);

  // 1초 tick (카운트다운 갱신)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // ── 마운트 시 파일에서 예약 목록 로드 ────────────────────────────────────
  // StrictMode에서 mount→cleanup→remount 시 두 번째 IPC만 사용 (ignore 패턴)
  useEffect(() => {
    let ignore = false;
    invoke<string>("load_schedules")
      .then((json) => {
        if (ignore) return;
        try { setSchedules(JSON.parse(json)); }
        catch { setSchedules([]); }
      })
      .catch(() => {})
      .finally(() => { if (!ignore) setSchedulesLoaded(true); });
    return () => { ignore = true; };
  }, []);

  // ── 로드 완료 후 stale 상태 복구 / 재개 팝업 감지 ─────────────────────────────
  // 앱 강제종료·재시작 시 "running" 엔트리 처리:
  //   - sessionId 있음 → DB 조회후 재개 팝업 표시
  //   - sessionId 없음 → DB에서 tc_ids+repeat_count로 매칭 세션 검색 → 찾으면 팝업, 못 찾으면 done
  useEffect(() => {
    if (!schedulesLoaded) return;
    if (isTcRunning) { setStaleCheckDone(true); return; } // 실제 실행 중이면 건드리지 않음

    const stale = schedules.filter((s) => s.status === "running");
    if (stale.length === 0) { setStaleCheckDone(true); return; }

    // sessionId 있는 항목과 없는 항목을 모두 처리
    const withSession = stale.filter((s) => !!s.sessionId);
    const noSession   = stale.filter((s) => !s.sessionId);

    // sessionId 있는 항목: DB 진행도 조회
    const withSessionPromises = withSession.map((entry) =>
      invoke<[number, number]>("db_get_session_progress", { sessionId: entry.sessionId })
        .then(([completed, total]) => ({ entry, completed, total }))
        .catch(() => ({ entry, completed: 0, total: entry.repeatOptions.count }))
    );

    // sessionId 없는 (legacy) 항목: DB에서 tc_ids+repeat_count로 최근 세션 매칭
    interface FoundSession { sessionId: string; completed: number; total: number }
    const noSessionPromises = noSession.map((entry) =>
      invoke<FoundSession | null>("db_find_recent_session", {
        tcIdsJson: JSON.stringify(entry.tcIds),
        repeatCount: entry.repeatOptions.count,
      }).then((found) => {
        if (found) {
          return { entry: { ...entry, sessionId: found.sessionId }, completed: found.completed, total: found.total };
        }
        return null; // DB에 매칭 세션이 없으면 null → done 처리
      }).catch(() => null)
    );

    Promise.all([...withSessionPromises, ...noSessionPromises]).then((results) => {
      const resolved    = results.filter((r): r is NonNullable<typeof r> => r !== null);
      const unresolved  = noSession.filter((entry) =>
        !resolved.some((r) => r.entry.id === entry.id)
      );

      // 매칭 안 된 legacy 항목 → done 전환
      if (unresolved.length > 0) {
        setSchedules((prev) =>
          prev.map((s) =>
            unresolved.some((u) => u.id === s.id) ? { ...s, status: "done" as const } : s
          )
        );
      }

      // 매칭된 legacy 항목 → sessionId 패치
      const legacyMatched = resolved.filter((r) =>
        noSession.some((ns) => ns.id === r.entry.id)
      );
      if (legacyMatched.length > 0) {
        setSchedules((prev) =>
          prev.map((s) => {
            const m = legacyMatched.find((r) => r.entry.id === s.id);
            return m ? { ...s, sessionId: m.entry.sessionId } : s;
          })
        );
      }

      if (resolved.length > 0) {
        setResumePrompts(resolved);
      }
      setStaleCheckDone(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schedulesLoaded]);

  // ── 대기열 시간 추산: 주기적 DB 조회 (30초) ───────────────────────────────
  useEffect(() => {
    if (!schedulesLoaded) return;
    function fetchEstimate() {
      const running = schedules.find((s) => s.status === "running");
      invoke<QueueEstimate>("db_get_queue_estimate", {
        runningSessionId: running?.sessionId ?? null,
      })
        .then(setQueueEstimate)
        .catch(() => {});
    }
    fetchEstimate();
    const id = setInterval(fetchEstimate, 30_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schedules, schedulesLoaded]);

  // ── core: running → done + 다음 pending 자동 실행 ──────────────────────────
  useEffect(() => {
    if (prevRunningRef.current && !isTcRunning) {
      // nextPending: running→done 이후 실행될 첫 번째 pending 항목
      // updater 밖에서 계산 (schedules 는 이 effect 실행 시점의 최신 상태)
      const nextPending = [...schedules]
        .filter((s) => s.status === "pending" && !s.scheduledAt)
        .sort((a, b) => a.createdAt.localeCompare(b.createdAt))[0];

      setSchedules((prev) =>
        prev.map((s) =>
          s.status === "running" ? { ...s, status: "done" as const } : s
        )
      );

      if (nextPending) {
        // timerRefs에 저장 → schedules effect cleanup 시 함께 정리됨
        const tid = setTimeout(() => {
          if (!isTcRunningRef.current && !fireRef.current) fireEntry(nextPending);
        }, 2000);
        timerRefs.current.set("after-done", tid);
      }
    }
    prevRunningRef.current = isTcRunning;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isTcRunning]);

  // ── schedules 변경 → 파일 저장 + ref 동기화 + 타이머 등록 + 큐 자동 실행 ───────────────
  useEffect(() => {
    // 로드 완료 전에는 빈 배열로 파일을 덮어쓰지 않는다
    if (!schedulesLoaded) return;
    schedulesRef.current = schedules;
    saveSchedules(schedules);
    timerRefs.current.forEach((t) => clearTimeout(t));
    timerRefs.current.clear();

    // "running" entry 가 있더라도 실제 isTcRunning=false 이면 이미 완료된 stale 상태이므로
    // 큐 자동 실행을 막지 않는다. prop 기준으로 판단한다.
    // fireRef: fireEntry 호출 후 isTcRunning prop 업데이트 전까지의 창(window)도 막는다
    const isAnyRunning = isTcRunningRef.current || fireRef.current;

    for (const s of schedules) {
      if (s.status !== "pending") continue;

      if (!s.scheduledAt) {
        // 즉시 대기열 아이템: 아무것도 실행 중이 아닐 때 첫 번째 항목만 자동 시작
        // (아래 queueAutoStart 로직에서 처리)
        continue;
      }

      // 시간 지정 예약
      const ms = msUntil(s.scheduledAt);
      if (ms <= 0) {
        // 과거 시각 → scheduledAt=null 로 변환해 즉시 대기열에 편입
        // (타이머가 발화했으나 isTcRunning=true 였던 경우도 여기서 처리)
        setSchedules((prev) =>
          prev.map((e) =>
            e.id === s.id ? { ...e, scheduledAt: null } : e
          )
        );
        continue;
      }
      const tid = setTimeout(() => {
        if (!isTcRunningRef.current) {
          fireEntry(s);
        } else {
          // 타이머 발화 시각에 다른 테스트가 실행 중인 경우
          // → scheduledAt=null 로 변환해 그 테스트 완료 후 큐에서 자동 실행되도록 편입
          setSchedules((prev) =>
            prev.map((e) =>
              e.id === s.id ? { ...e, scheduledAt: null } : e
            )
          );
        }
      }, ms);
      timerRefs.current.set(s.id, tid);
    }

    // 즉시 대기열 자동 실행: 실행 중인 것 없으면 createdAt 가장 앞 항목 시작
    // stale 복구 미완료 또는 재개 팝업 미응답 시 자동 실행 차단
    const hasStaleRunning = schedules.some((s) => s.status === "running");
    if (!isAnyRunning && staleCheckDone && resumePrompts.length === 0 && !hasStaleRunning) {
      const next = [...schedules]
        .filter((s) => s.status === "pending" && !s.scheduledAt)
        .sort((a, b) => a.createdAt.localeCompare(b.createdAt))[0];
      if (next) {
        // 한 틱 뒤에 실행 (현재 렌더 사이클과 분리)
        const tid = setTimeout(() => {
          if (!isTcRunningRef.current && !fireRef.current) fireEntry(next);
        }, 100);
        timerRefs.current.set(next.id + "-q", tid);
      }
    }

    return () => { timerRefs.current.forEach((t) => clearTimeout(t)); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schedules, schedulesLoaded, staleCheckDone, resumePrompts]);

  // ── fireEntry: pending → running + onTrigger ──────────────────────────────
  function fireEntry(entry: ScheduleEntry) {
    // 이중 실행 차단: isTcRunning prop 또는 이미 호출된 fireRef
    if (isTcRunningRef.current || fireRef.current) return;
    fireRef.current = true;
    const sessionId = crypto.randomUUID();

    // ref에서 최신 상태를 직접 읽어 새 배열을 계산하고 즉시 파일에 저장
    const prev = schedulesRef.current;
    const exists = prev.some((s) => s.id === entry.id);
    const base = exists ? prev : [...prev, entry];
    const next = base.map((s) =>
      s.id === entry.id ? { ...s, status: "running" as const, sessionId } : s
    );
    schedulesRef.current = next;
    saveSchedules(next);      // 즉시 파일 저장 — effect 타이밍에 의존하지 않음
    setSchedules(next);       // React 상태도 동기화 → UI 갱신

    const tcSet = new Set(entry.tcIds) as Set<TcId>;
    onTriggerRef.current(tcSet, entry.repeatOptions, { enabled: false, scheduledAt: null }, sessionId);
  }

  // ── 추가 ─────────────────────────────────────────────────────────────────
  // 날짜+시간 → ISO 8601 (로컬 타임존, 명시적 생성자로 파싱 버그 방지)
  function buildScheduledAt(): string | null {
    if (!formDate) return null;
    const [y, mo, d] = formDate.split('-').map(Number);
    const h  = formHour  ?? 0;
    const mi = formMin   ?? 0;
    return new Date(y, mo - 1, d, h, mi, 0).toISOString();
  }

  function closeForm() {
    setFormLabel(""); setFormDate(""); setFormHour(null); setFormMin(null);
    setFormDateMode(null); setShowCalendar(false); setShowForm(false); setEditId(null);
  }

  function handleAdd() {
    if (formTcs.length === 0) { alert(t("schedule.alertSelectTc")); return; }
    // 날짜 선택했는데 시간 미설정 시 경고
    if (formDate && (formHour === null || formMin === null)) {
      alert(t("schedule.alertSetTime"));
      return;
    }
    const scheduledAt = buildScheduledAt();
    if (scheduledAt && msUntil(scheduledAt) <= 0) { alert(t("schedule.alertPastTime")); return; }

    const newLabel = formLabel.trim() || `${formTcs.join(" \u2192 ")} \u00d7 ${formCount}${t("tc.times")}`;

    if (editId !== null) {
      // 수정 모드: 기존 항목 업데이트 (id·status·createdAt 유지)
      setSchedules((prev) =>
        prev.map((s) =>
          s.id === editId
            ? { ...s, scheduledAt, repeatOptions: { count: formCount, mode: formMode, failAction: formFail }, tcIds: [...formTcs], label: newLabel }
            : s
        )
      );
    } else {
      // 신규 추가 — useEffect가 자동 실행 결정
      const entry: ScheduleEntry = {
        id: `sch-${Date.now()}`,
        scheduledAt,
        repeatOptions: { count: formCount, mode: formMode, failAction: formFail },
        tcIds: [...formTcs],
        label: newLabel,
        status: "pending",
        createdAt: new Date().toISOString(),
      };
      setSchedules((prev) => [...prev, entry]);
    }
    closeForm();
  }

  function handleDelete(id: string) {
    const t = timerRefs.current.get(id);
    if (t) { clearTimeout(t); timerRefs.current.delete(id); }
    setSchedules((prev) => prev.filter((s) => s.id !== id));
  }

  function handleCancel(id: string) {
    const t = timerRefs.current.get(id);
    if (t) { clearTimeout(t); timerRefs.current.delete(id); }
    setSchedules((prev) =>
      prev.map((s) => s.id === id ? { ...s, status: "cancelled" as const } : s)
    );
  }

  function openEdit(entry: ScheduleEntry) {
    setFormTcs([...entry.tcIds]);
    setFormCount(entry.repeatOptions.count);
    setFormMode(entry.repeatOptions.mode);
    setFormFail(entry.repeatOptions.failAction);
    setFormLabel(entry.label);
    if (entry.scheduledAt) {
      const d = new Date(entry.scheduledAt);
      const yyyy = d.getFullYear();
      const mm   = String(d.getMonth() + 1).padStart(2, "0");
      const dd   = String(d.getDate()).padStart(2, "0");
      setFormDate(`${yyyy}-${mm}-${dd}`);
      setFormHour(d.getHours());
      setFormMin(d.getMinutes());
      // 저장된 날짜의 요일이 nextDateOfWeekday(dow)와 일치하면 요일 모드로 복원,
      // 그렇지 않으면 custom(직접 설정)으로 복원
      const storedDow = d.getDay();
      const expectedDate = nextDateOfWeekday(storedDow);
      setFormDateMode(`${yyyy}-${mm}-${dd}` === expectedDate ? String(storedDow) : "custom");
    } else {
      setFormDate(""); setFormHour(null); setFormMin(null); setFormDateMode(null);
    }
    setShowCalendar(false);
    setEditId(entry.id);
    setShowForm(true);
  }

  // ── 드래그 & 드롭 ────────────────────────────────────────────────────────
  function onDropPending() {
    if (!dragId) return;
    setDragOver(null);
    setSchedules((prev) => {
      const src = prev.find((s) => s.id === dragId);
      if (!src || src.status === "pending" || src.status === "running") return prev;
      return prev.map((s) =>
        s.id === dragId
          ? { ...s, status: "pending" as const, scheduledAt: null, createdAt: new Date().toISOString() }
          : s
      );
    });
    setDragId(null);
  }

  function onDropRetest() {
    if (!dragId) return;
    setDragOver(null);
    setSchedules((prev) => {
      const src = prev.find((s) => s.id === dragId);
      if (!src || src.status === "running") return prev;
      const clone: ScheduleEntry = {
        ...src,
        id: `sch-${Date.now()}`,
        scheduledAt: null,
        status: "pending",
        createdAt: new Date().toISOString(),
        label: src.label.replace(/^\[재테스트\]\s*/, ""),
      };
      return [...prev, clone];
    });
    setDragId(null);
  }

  // ── TC 폼 헬퍼 ────────────────────────────────────────────────────────────
  function toggleTc(id: TcId) {
    setFormTcs((prev) => prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]);
  }
  function moveTc(id: TcId, dir: -1 | 1) {
    setFormTcs((prev) => {
      const idx = prev.indexOf(id);
      if (idx < 0) return prev;
      const next = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  }

  // ── resumePrompt 핸들러 ───────────────────────────────────────────────────
  function handleResume(prompt: typeof resumePrompts[0]) {
    const remaining = prompt.total - prompt.completed;
    setResumePrompts((prev) => prev.filter((p) => p.entry.id !== prompt.entry.id));

    if (remaining <= 0) {
      // 잔여 없으면 done 처리만
      setSchedules((prev) =>
        prev.map((s) =>
          s.id === prompt.entry.id ? { ...s, status: "done" as const } : s
        )
      );
      return;
    }

    // 잔여 횟수 항목을 즉시 running으로 시작
    const sessionId = crypto.randomUUID();
    fireRef.current = true;
    const resumeEntry: ScheduleEntry = {
      ...prompt.entry,
      id: `sch-${Date.now()}`,
      status: "running",
      scheduledAt: null,
      sessionId,
      createdAt: new Date().toISOString(),
      repeatOptions: { ...prompt.entry.repeatOptions, count: remaining },
      label: `${prompt.entry.label.replace(/^\[재개\]\s*/, "")}`,
    };
    // ref에서 직접 계산 → 즉시 파일 저장
    const prev = schedulesRef.current;
    const withDone = prev.map((s) =>
      s.id === prompt.entry.id ? { ...s, status: "done" as const } : s
    );
    const next = [...withDone, resumeEntry];
    schedulesRef.current = next;
    saveSchedules(next);
    setSchedules(next);
    const tcSet = new Set(resumeEntry.tcIds) as Set<TcId>;
    onTriggerRef.current(tcSet, resumeEntry.repeatOptions, { enabled: false, scheduledAt: null }, sessionId);
  }

  function handleResumeFromStart(prompt: typeof resumePrompts[0]) {
    setResumePrompts((prev) => prev.filter((p) => p.entry.id !== prompt.entry.id));

    // 처음부터 다시 → 즉시 running으로 시작
    const sessionId = crypto.randomUUID();
    fireRef.current = true;
    const resumeEntry: ScheduleEntry = {
      ...prompt.entry,
      id: `sch-${Date.now()}`,
      status: "running",
      scheduledAt: null,
      sessionId,
      createdAt: new Date().toISOString(),
    };
    // ref에서 직접 계산 → 즉시 파일 저장
    const prev = schedulesRef.current;
    const withDone = prev.map((s) =>
      s.id === prompt.entry.id ? { ...s, status: "done" as const } : s
    );
    const next = [...withDone, resumeEntry];
    schedulesRef.current = next;
    saveSchedules(next);
    setSchedules(next);
    const tcSet = new Set(resumeEntry.tcIds) as Set<TcId>;
    onTriggerRef.current(tcSet, resumeEntry.repeatOptions, { enabled: false, scheduledAt: null }, sessionId);
  }

  function handleResumeSkip(prompt: typeof resumePrompts[0]) {
    setResumePrompts((prev) => prev.filter((p) => p.entry.id !== prompt.entry.id));
    setSchedules((prev) =>
      prev.map((s) =>
        s.id === prompt.entry.id ? { ...s, status: "done" as const } : s
      )
    );
  }

  // ── 컬럼별 데이터 ────────────────────────────────────────────────────────
  const pendingItems  = [...schedules]
    .filter((s) => s.status === "pending")
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  const runningItems  = schedules.filter((s) => s.status === "running");
  const doneItems     = [...schedules]
    .filter((s) => s.status === "done" || s.status === "cancelled")
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  // ── 대기열 ETA 계산 ─────────────────────────────────────────────────────
  const etas = useMemo(() => {
    const result = new Map<string, EntryEta>();
    if (!queueEstimate) return result;
    const avgPerTcSet = queueEstimate.avgMsPerTcSet || DEFAULT_MS_PER_TC_SET;
    const now = Date.now();
    let nextStartMs = now;

    // 실행 중 항목: 잔여 시간 추산
    const running = schedules.find((s) => s.status === "running");
    if (running && queueEstimate.runningTotal > 0) {
      const remaining = queueEstimate.runningTotal - queueEstimate.runningCompleted;
      let avgPerSet: number;
      if (queueEstimate.runningCompleted > 0 && queueEstimate.runningStartedAt) {
        // 현재 세션 자체 실측 평균 사용
        const elapsed = now - new Date(queueEstimate.runningStartedAt).getTime();
        avgPerSet = elapsed / queueEstimate.runningCompleted;
      } else {
        // 글로벌 평균 × TC 수
        avgPerSet = avgPerTcSet * running.tcIds.length;
      }
      const remainingMs = remaining * avgPerSet;
      result.set(running.id, { estStart: new Date(now), estEnd: new Date(now + remainingMs) });
      nextStartMs = now + remainingMs;
    }

    // 대기 항목: 순서대로 누적
    for (const entry of pendingItems) {
      if (entry.scheduledAt) {
        // 시간 지정 항목은 기존 카운트다운 사용
        const scheduledMs = new Date(entry.scheduledAt).getTime();
        if (scheduledMs > nextStartMs) nextStartMs = scheduledMs;
      }
      const durationMs = entry.tcIds.length * entry.repeatOptions.count * avgPerTcSet;
      result.set(entry.id, { estStart: new Date(nextStartMs), estEnd: new Date(nextStartMs + durationMs) });
      nextStartMs += durationMs;
    }

    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queueEstimate, schedules]);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="kanban-tab">

      {/* 헤더 */}
      <div className="kanban-header">
        <span className="kanban-title">{t("schedule.title")}</span>
        <button
          className="btn-xs btn-primary"
          onClick={() => setShowForm(true)}
        >
          {t("schedule.addNew")}
        </button>
      </div>

      {/* ── 중단된 테스트 재개 팝업 ────────────────────────────────────── */}
      {resumePrompts.length > 0 && (
        <div className="modal-overlay">
          <div className="modal-panel" style={{ width: 460 }}>
            <div className="modal-header">
              <span className="modal-title">⚠️ {t("schedule.resumeTitle")}</span>
            </div>
            <div className="modal-body" style={{ gap: 14 }}>
              {resumePrompts.map((prompt) => {
                const remaining = prompt.total - prompt.completed;
                return (
                  <div key={prompt.entry.id} className="resume-prompt-card">
                    <div className="resume-prompt-label">{prompt.entry.label}</div>
                    <div className="resume-prompt-info">
                      ▶ {prompt.entry.tcIds.join(" → ")} &nbsp;|&nbsp;
                      {t("schedule.resumeProgress", {
                        completed: String(prompt.completed),
                        total: String(prompt.total),
                      })}
                    </div>
                    {remaining > 0 ? (
                      <div className="resume-prompt-info" style={{ color: "var(--accent)" }}>
                        {t("schedule.resumeRemaining", { remaining: String(remaining) })}
                      </div>
                    ) : (
                      <div className="resume-prompt-info" style={{ color: "var(--ok)" }}>
                        {t("schedule.resumeAlreadyDone")}
                      </div>
                    )}
                    <div className="resume-prompt-actions">
                      {remaining > 0 && (
                        <button className="btn-xs btn-primary" onClick={() => handleResume(prompt)}>
                          {t("schedule.resumeContinue", { remaining: String(remaining) })}
                        </button>
                      )}
                      <button className="btn-xs" onClick={() => handleResumeFromStart(prompt)}>
                        {t("schedule.resumeFromStart")}
                      </button>
                      <button className="btn-xs btn-ghost" onClick={() => handleResumeSkip(prompt)}>
                        {t("schedule.resumeSkip")}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ── 신규 예약 모달 ─────────────────────────────────────────────── */}
      {showForm && (
        <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setShowForm(false); }}>
          <div className="modal-panel" style={{ width: 520 }}>
            <div className="modal-header">
              <span className="modal-title">{editId !== null ? t("schedule.editTitle") : `📋 ${t("schedule.addNew")}`}</span>
              <button className="btn-close-red" onClick={closeForm}>✕</button>
            </div>
            <div className="modal-body" style={{ gap: 12 }}>

              {/* TC 선택 */}
              <div className="kanban-form-row">
                <label className="kanban-form-label" style={{ paddingTop: 4 }}>{t("schedule.tcOrder")}</label>
                <div style={{ flex: 1 }}>
                  <div className="schedule-tc-grid" style={{ marginBottom: 6 }}>
                    {TC_DEFS.filter((tc) => enabledTcIds.has(tc.id)).map((tc) => {
                      const idx = formTcs.indexOf(tc.id);
                      const sel = idx >= 0;
                      return (
                        <button key={tc.id} type="button"
                          className={`schedule-tc-chip${sel ? " selected" : ""}`}
                          onClick={() => toggleTc(tc.id)}
                        >
                          {sel && <span className="tc-order-badge">{idx + 1}</span>}
                          {tc.label}
                        </button>
                      );
                    })}
                  </div>
                  {formTcs.length > 0 && (
                    formTcs.length === 2 ? (() => {
                      /* TC 2개: 정방향/역방향 토글 버튼 (TC 번호 오름차순 기준) */
                      const sorted = [...formTcs].sort() as [TcId, TcId];
                      const rev    = [sorted[1], sorted[0]] as [TcId, TcId];
                      const isFwd  = formTcs[0] === sorted[0];
                      return (
                        <div className="btn-toggle-group" style={{ marginTop: 6, width: "fit-content" }}>
                          <button
                            type="button"
                            className={`btn-toggle tc-dir-btn${isFwd ? " active" : ""}`}
                            onClick={() => setFormTcs(sorted)}
                          >
                            {sorted[0]} → {sorted[1]}
                          </button>
                          <button
                            type="button"
                            className={`btn-toggle tc-dir-btn${!isFwd ? " active" : ""}`}
                            onClick={() => setFormTcs(rev)}
                          >
                            {rev[0]} → {rev[1]}
                          </button>
                        </div>
                      );
                    })() : (
                      /* TC 3개 이상: 기존 ◀▶ 순서 조정 UI */
                      <div className="schedule-tc-order">
                        <span className="schedule-tc-order-label">{t("schedule.execOrder")}</span>
                        {formTcs.map((id, idx) => (
                          <span key={id} className="schedule-tc-order-item">
                            {idx > 0 && <span className="schedule-tc-arrow">→</span>}
                            <span className="schedule-tc-order-name">{id}</span>
                            <span className="schedule-tc-order-btns">
                              <button type="button" disabled={idx === 0} onClick={() => moveTc(id, -1)}>◀</button>
                              <button type="button" disabled={idx === formTcs.length - 1} onClick={() => moveTc(id, 1)}>▶</button>
                            </span>
                          </span>
                        ))}
                      </div>
                    )
                  )}
                </div>
              </div>

              {/* 반복 횟수 */}
              <div className="kanban-form-row">
                <label className="kanban-form-label">{t("tc.opt.count")}</label>
                <div className="count-stepper">
                  <button
                    type="button"
                    className="count-step-btn"
                    aria-label="decrease"
                    onClick={() => setFormCount((v) => Math.max(1, v - 1))}
                    disabled={formCount <= 1}
                  >−</button>
                  <input
                    type="number" min={1} max={9999}
                    className="schedule-num-input"
                    value={formCount}
                    onChange={(e) => setFormCount(Math.max(1, Math.min(9999, Number(e.target.value))))}
                  />
                  <button
                    type="button"
                    className="count-step-btn"
                    aria-label="increase"
                    onClick={() => setFormCount((v) => Math.min(9999, v + 1))}
                    disabled={formCount >= 9999}
                  >+</button>
                </div>
                <span className="schedule-form-unit">{t("tc.times")}</span>
              </div>

              {/* 반복 단위 */}
              <div className="kanban-form-row">
                <label className="kanban-form-label">{t("tc.opt.unit")}</label>
                <div className="btn-toggle-group">
                  <button
                    type="button"
                    className={`btn-toggle${formMode === "set" ? " active" : ""}`}
                    onClick={() => setFormMode("set")}
                  >
                    {t("tc.opt.unitSet")}
                  </button>
                  <button
                    type="button"
                    className={`btn-toggle${formMode === "tc" ? " active" : ""}`}
                    onClick={() => setFormMode("tc")}
                  >
                    {t("tc.opt.unitTc")}
                  </button>
                </div>
              </div>

              {/* 실패 처리 */}
              <div className="kanban-form-row">
                <label className="kanban-form-label">{t("tc.opt.failAction")}</label>
                <select className="schedule-select" value={formFail}
                  onChange={(e) => setFormFail(e.target.value as typeof formFail)}>
                  <option value="stop">{t("tc.opt.failStop")}</option>
                  <option value="continue">{t("tc.opt.failContinue")}</option>
                  <option value="retry_crash">{t("tc.opt.failRetry")}</option>
                </select>
              </div>

              {/* 예약 날짜 */}
              <div className="kanban-form-row" style={{ alignItems: "flex-start" }}>
                <label className="kanban-form-label" style={{ paddingTop: 4 }}>
                  {formDate ? t("schedule.scheduleDate") : t("schedule.scheduleTime")}
                  {!formDate && <span style={{ fontSize: 10, color: "var(--text-dim)", marginLeft: 4 }}>{t("schedule.scheduleOptional")}</span>}
                </label>
                <div style={{ flex: 1 }}>
                  {/* 요일 + 직접 설정 버튼 */}
                  <div className="schedule-weekday-group">
                    {getWeekdayBtns(lang).map(({ label, dow }) => (
                      <button
                        key={dow}
                        type="button"
                        className={`btn-toggle-day${formDateMode === String(dow) ? " active" : ""}`}
                        onClick={() => {
                          setFormDateMode(String(dow));
                          setFormDate(nextDateOfWeekday(dow));
                          setShowCalendar(false);
                          setFormHour(null);
                          setFormMin(null);
                        }}
                      >
                        {label}
                      </button>
                    ))}
                    <button
                      type="button"
                      className={`btn-toggle-day${formDateMode === "custom" ? " active" : ""}`}
                      onClick={() => {
                        setFormDateMode("custom");
                        setShowCalendar(true);
                        setFormDate("");
                        setFormHour(null);
                        setFormMin(null);
                      }}
                    >
                      {t("schedule.customDate")}
                    </button>
                  </div>

                  {/* 달력 인풋 (직접 설정 클릭 후만 표시, 선택하면 닫힘) */}
                  {showCalendar && (
                    <input
                      type="date"
                      className="schedule-datetime-input"
                      style={{ marginTop: 6, width: "100%" }}
                      value={formDate}
                      min={new Date().toISOString().slice(0, 10)}
                      autoFocus
                      onChange={(e) => {
                        setFormDate(e.target.value);
                        if (e.target.value) setShowCalendar(false);
                      }}
                    />
                  )}

                  {formDate && !showCalendar && (
                    <div className="schedule-date-display">
                      <span className="schedule-date-text">
                        📅 {fmtDate(formDate, lang)}
                      </span>
                      <button
                        className="btn-xs"
                        onClick={() => { setFormDate(""); setFormDateMode(null); setFormHour(null); setFormMin(null); }}
                      >
                        {t("schedule.cancelDate")}
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* 예약 시간 — 날짜 선택 후 표시 */}
              {formDate && !showCalendar && (
                <div className="kanban-form-row">
                  <label className="kanban-form-label">{t("schedule.scheduleTime")}</label>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <HourPicker value={formHour} onChange={(h) => { setFormHour(h); setFormMin(null); }} />
                    <MinutePicker value={formMin} disabled={formHour === null} onChange={setFormMin} />
                  </div>
                </div>
              )}

              {/* 메모 */}
              <div className="kanban-form-row">
                <label className="kanban-form-label">{t("schedule.memo")}</label>
                <input type="text" className="schedule-label-input"
                  placeholder={t("schedule.memoPlaceholder")}
                  value={formLabel} maxLength={60}
                  onChange={(e) => setFormLabel(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                />
              </div>

            </div>

            {/* 모달 푸터 */}
            <div className="modal-footer">
              <button className="btn-xs" onClick={closeForm}>{t("schedule.close")}</button>
              <button className="btn-xs btn-primary" onClick={handleAdd}>
                {editId !== null ? t("schedule.editDone") : t("schedule.addQueue")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 칸반 보드 ──────────────────────────────────────────────────── */}
      <div className="kanban-board">

        {/* 대기중 */}
        <div
          className={`kanban-col${dragOver === "pending" ? " kanban-col-dragover" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDragOver("pending"); }}
          onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(null); }}
          onDrop={onDropPending}
        >
          <div className="kanban-col-hdr kanban-hdr-pending">
            {t("schedule.colPending")}
            <span className="kanban-badge">{pendingItems.length}</span>
          </div>
          <div className="kanban-col-body">
            {pendingItems.length === 0
              ? <div className="kanban-empty">{t("schedule.emptyPending")}</div>
              : pendingItems.map((entry, i) => (
                <KanbanCard key={entry.id} entry={entry} order={i + 1}
                  eta={etas.get(entry.id)}
                  onCancel={handleCancel} onDelete={handleDelete} onEdit={openEdit}
                  onDragStart={() => setDragId(entry.id)}
                  onDragEnd={() => { setDragId(null); setDragOver(null); }}
                />
              ))
            }
          </div>
        </div>

        {/* 테스트 중 */}
        <div className="kanban-col">
          <div className="kanban-col-hdr kanban-hdr-running">
            {t("schedule.colRunning")}
            <span className="kanban-badge">{runningItems.length}</span>
          </div>
          <div className="kanban-col-body">
            {runningItems.length === 0
              ? <div className="kanban-empty">{t("schedule.emptyRunning")}</div>
              : runningItems.map((entry) => (
                <KanbanCard key={entry.id} entry={entry}
                  eta={etas.get(entry.id)}
                  progress={queueEstimate && queueEstimate.runningTotal > 0
                    ? { completed: queueEstimate.runningCompleted, total: queueEstimate.runningTotal }
                    : undefined}
                  onDelete={handleDelete}
                  onDragStart={() => setDragId(entry.id)}
                  onDragEnd={() => { setDragId(null); setDragOver(null); }}
                />
              ))
            }
          </div>
        </div>

        {/* 테스트 완료 */}
        <div className="kanban-col">
          <div className="kanban-col-hdr kanban-hdr-done">
            {t("schedule.colDone")}
            <span className="kanban-badge">{doneItems.length}</span>
          </div>
          <div className="kanban-col-body">
            {doneItems.length === 0
              ? <div className="kanban-empty">{t("schedule.emptyDone")}</div>
              : doneItems.map((entry) => (
                <KanbanCard key={entry.id} entry={entry}
                  onDelete={handleDelete}
                  onDragStart={() => setDragId(entry.id)}
                  onDragEnd={() => { setDragId(null); setDragOver(null); }}
                />
              ))
            }
          </div>
        </div>

        {/* 재테스트 드롭존 */}
        <div
          className={`kanban-col kanban-retest-col${dragOver === "retest" ? " kanban-col-dragover" : ""}${dragId ? " kanban-drop-active" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDragOver("retest"); }}
          onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(null); }}
          onDrop={onDropRetest}
        >
          <div className="kanban-col-hdr kanban-hdr-retest">
            {t("schedule.colRetest")}
          </div>
          <div className="kanban-col-body kanban-retest-body">
            <div className="kanban-retest-hint">
              {dragId
                ? t("schedule.retestHint")
                : t("schedule.retestEmpty")
              }
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

// ── KanbanCard ────────────────────────────────────────────────────────────────

interface CardProps {
  entry: ScheduleEntry;
  order?: number;
  eta?: EntryEta;
  progress?: { completed: number; total: number };
  onDelete: (id: string) => void;
  onCancel?: (id: string) => void;
  onEdit?: (entry: ScheduleEntry) => void;
  onDragStart?: () => void;
  onDragEnd?: () => void;
}

function fmtEta(date: Date, lang: string): string {
  return date.toLocaleString(lang === "ko" ? "ko-KR" : "en-US", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function fmtDuration(ms: number, t: (k: string, v?: Record<string, string | number>) => string): string {
  const totalMin = Math.round(ms / 60_000);
  if (totalMin < 60) return t("schedule.etaMin", { m: totalMin });
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return t("schedule.etaHour", { h, m });
}

function KanbanCard({ entry, order, eta, progress, onDelete, onCancel, onEdit, onDragStart, onDragEnd }: CardProps) {
  const { t, lang } = useT();
  const isDraggable = entry.status !== "running";
  return (
    <div
      className={`kanban-card kanban-card-${entry.status}`}
      draggable={isDraggable}
      onDragStart={isDraggable ? onDragStart : undefined}
      onDragEnd={isDraggable ? onDragEnd : undefined}
    >
      <div className="kanban-card-top">
        {order !== undefined && <span className="kanban-card-order">{order}</span>}
        <span className="kanban-card-label">{entry.label}</span>
        {entry.status === "running" && <span className="kanban-card-running-dot" />}
      </div>
      <div className="kanban-card-meta">
        {/* 실행 중 → 진행도 + 예상 완료 */}
        {entry.status === "running" && progress && progress.total > 0 && (
          <>
            <span className="kanban-card-progress">
              📊 {t("schedule.etaProgress", {
                completed: String(progress.completed),
                total: String(progress.total),
                percent: String(Math.round(progress.completed / progress.total * 100)),
              })}
            </span>
            <div className="kanban-card-progress-bar">
              <div className="kanban-card-progress-fill"
                style={{ width: `${Math.round(progress.completed / progress.total * 100)}%` }} />
            </div>
          </>
        )}
        {entry.status === "running" && eta && (
          <span className="kanban-card-eta">
            ⏱ {t("schedule.etaEnd")} {fmtEta(eta.estEnd, lang)}
          </span>
        )}
        {/* 대기 → 예상 시작/완료 */}
        {entry.status === "pending" && !entry.scheduledAt && eta && (
          <span className="kanban-card-eta">
            ⏱ {t("schedule.etaStart")} {fmtEta(eta.estStart, lang)}
            {" · "}
            {fmtDuration(eta.estEnd.getTime() - eta.estStart.getTime(), t)}
          </span>
        )}
        {entry.scheduledAt && entry.status === "pending" && (
          <span className="kanban-card-countdown">⏰ {fmtRemaining(entry.scheduledAt, t)}</span>
        )}
        {entry.scheduledAt && entry.status !== "pending" && (
          <span>📅 {fmtShort(entry.scheduledAt, lang)}</span>
        )}
        <span>▶ {entry.tcIds.join(" → ")}</span>
        <span>🔁 {entry.repeatOptions.count}{t("tc.times")} ({entry.repeatOptions.mode === "set" ? t("schedule.modeSet") : t("schedule.modeTc")})</span>
      </div>
      <div className="kanban-card-actions">
        {entry.status === "pending" && onEdit && (
          <button className="btn-xs" onClick={() => onEdit(entry)}>수정</button>
        )}
        {entry.status === "pending" && onCancel && (
          <button className="btn-xs btn-warn" onClick={() => onCancel(entry.id)}>{t("schedule.cardCancel")}</button>
        )}
        <button className="btn-xs btn-ghost" onClick={() => onDelete(entry.id)}>{t("schedule.cardDelete")}</button>
      </div>
    </div>
  );
}
