import { useState } from "react";
import type { TcId, TcResult, TcStatus, RepeatOptions, ScheduleOptions } from "../types";
import { TC_ENABLED } from "../data/tcConfig";
import { useT } from "../i18n";
import { MosRepeatModal } from "./MosRepeatModal";

export const TC_DEFS: { id: TcId; label: string; desc: string }[] = [
  { id: "TC_00", label: "TC_00", desc: "tc.descs.TC_00" },
  { id: "TC_01", label: "TC_01", desc: "tc.descs.TC_01" },
  { id: "TC_02", label: "TC_02", desc: "tc.descs.TC_02" },
  { id: "TC_03", label: "TC_03", desc: "tc.descs.TC_03" },
  { id: "TC_04", label: "TC_04", desc: "tc.descs.TC_04" },
];

function tcStatusIcon(status: TcStatus | undefined): string {
  if (!status) return "";
  const map: Record<TcStatus, string> = {
    RUNNING: "🔄", QUEUED: "⏸", SCHEDULED: "⏰",
    PASS: "✅", FAIL: "❌", ERROR: "⚠️",
  };
  return map[status] ?? "";
}

interface Props {
  selectedTcs: Set<TcId>;
  onToggle: (id: TcId) => void;
  onStartTest: (repeat: RepeatOptions, schedule: ScheduleOptions) => void;
  onStop: () => void;
  isRunning: boolean;
  isBlocked: boolean;
  /** 현재 실행 중인 TC별 최신 결과 (진행 상태 표시용) */
  runningResults: Map<TcId, TcResult>;
  /** 반복 진행 카운터 */
  repeatProgress: { current: number; total: number } | null;
}

export function TcSelectPanel({
  selectedTcs, onToggle, onStartTest, onStop,
  isRunning, isBlocked, runningResults, repeatProgress,
}: Props) {
  const disabled = isRunning || isBlocked;

  // 반복 옵션
  const [repeatCount, setRepeatCount] = useState(3);
  const [repeatMode, setRepeatMode] = useState<"tc" | "set">("set");
  const [failAction, setFailAction] = useState<"stop" | "continue" | "retry_crash">("continue");

  // TC_00 전용: MOS 반복 횟수 팝업
  const [mosModalOpen, setMosModalOpen] = useState(false);
  const isTc00Only = selectedTcs.size === 1 && selectedTcs.has("TC_00" as TcId);

  // 예약 옵션 (예약 탭에서만 사용, 여기서는 기본값)
  const [showOptions, setShowOptions] = useState(false);

  const { t } = useT();

  function handleStart() {
    // TC_00 단독 → MOS 반복 팝업
    if (isTc00Only) {
      setMosModalOpen(true);
      return;
    }
    // TC 시작 = 1회 단독 실행
    onStartTest(
      { count: 1, mode: repeatMode, failAction },
      { enabled: false, scheduledAt: null },
    );
  }

  function handleRepeatStart() {
    // TC_00 단독은 반복 시작 비활성화 (MOS 팝업에서 별도 처리)
    if (isTc00Only) return;
    onStartTest(
      { count: repeatCount, mode: repeatMode, failAction },
      { enabled: false, scheduledAt: null },
    );
  }

  function handleMosConfirm(count: number) {
    setMosModalOpen(false);
    onStartTest(
      { count, mode: "set", failAction: "continue" },
      { enabled: false, scheduledAt: null },
    );
  }

  return (
    <div className="tc-panel">
      <div className="tc-panel-top">
        <span className="tc-panel-label">{t("tc.select")}</span>
        <button
          className={`btn-xs btn-ghost tc-options-toggle${showOptions ? " active" : ""}`}
          onClick={() => setShowOptions((v) => !v)}
          title={t("tc.options")}
        >
          {t("tc.options")}
        </button>

        {/* 헤더 우측 액션 버튼 행 */}
        <div className="tc-header-actions">
          <button
            className="btn-xs btn-tc-start"
            disabled={disabled || selectedTcs.size === 0 || isRunning}
            onClick={handleStart}
            title={isTc00Only ? "MOS 측정 시작" : "1회 단독 실행"}
          >
            {t("tc.start")}
          </button>

          <button
            className="btn-xs btn-tc-repeat"
            disabled={disabled || selectedTcs.size === 0 || isRunning || isTc00Only}
            onClick={handleRepeatStart}
            title={isTc00Only ? t("mos.useStartBtn") : `${repeatCount}${t("tc.times")} 반복 실행`}
          >
            {t("tc.repeatStart")}
          </button>

          <div className="tc-repeat-spin">
            <button
              className="tc-spin-btn"
              onClick={() => setRepeatCount((v) => Math.max(1, v - 1))}
              disabled={disabled || isRunning}
              tabIndex={-1}
            ><span style={{ fontSize: 16, lineHeight: 1 }}>&#x25BC;</span></button>
            <input
              type="number" min={1} max={9999}
              className="tc-spin-input"
              value={repeatCount}
              onChange={(e) => setRepeatCount(Math.max(1, Math.min(9999, Number(e.target.value))))}
              disabled={disabled}
            />
            <button
              className="tc-spin-btn"
              onClick={() => setRepeatCount((v) => Math.min(9999, v + 1))}
              disabled={disabled || isRunning}
              tabIndex={-1}
            ><span style={{ fontSize: 16, lineHeight: 1 }}>&#x25B2;</span></button>
            <span className="tc-spin-unit">{t("tc.times")}</span>
          </div>

          <button
            className="btn-xs btn-tc-stop"
            onClick={onStop}
            disabled={!isRunning}
            title="TC 테스트 중단"
          >
            {t("tc.stop")}
          </button>
        </div>
      </div>

      {/* TC 체크박스 목록 */}
      <div className="tc-checks">
        {TC_DEFS.filter((tc) => {
          if (!TC_ENABLED[tc.id]) return false;
          return true;
        }).map((tc) => {
          const res = runningResults.get(tc.id);
          const isActive = res?.status === "RUNNING" || res?.status === "QUEUED";
          return (
            <label
              key={tc.id}
              className={[
                "tc-check-item",
                selectedTcs.has(tc.id) ? "checked" : "",
                disabled ? "disabled" : "",
                isActive ? "tc-active" : "",
              ].filter(Boolean).join(" ")}
            >
              <input
                type="checkbox"
                checked={selectedTcs.has(tc.id)}
                onChange={() => onToggle(tc.id)}
                disabled={disabled}
              />
              <span className="tc-id-tag">{tc.id}</span>
              <span className="tc-desc">{t(tc.desc)}</span>
              {res && (
                <span className="tc-run-status">
                  {tcStatusIcon(res.status)}
                  {res.status === "RUNNING" && res.subStatus && (
                    <span className="tc-sub-status">{res.subStatus}</span>
                  )}
                  {res.status === "RUNNING" && res.phase && (
                    <span className="tc-phase-badge">Ph{res.phase}</span>
                  )}
                </span>
              )}
            </label>
          );
        })}
      </div>

      {/* 반복 진행 프로그레스 */}
      {isRunning && repeatProgress && repeatProgress.total > 1 && (
        <div className="tc-repeat-progress">
          <span className="tc-repeat-counter">
            {t("tc.repeatProgress")} {repeatProgress.current} / {repeatProgress.total}{t("tc.times")}
          </span>
          <div className="tc-repeat-bar">
            <div
              className="tc-repeat-fill"
              style={{ width: `${(repeatProgress.current / repeatProgress.total) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* 반복/예약 옵션 패널 */}
      {showOptions && (
        <div className="tc-options-panel">
          <div className="tc-opt-row">
            <label className="tc-opt-label">{t("tc.opt.count")}</label>
            <input
              type="number" min={1} max={9999}
              className="tc-opt-input"
              value={repeatCount}
              onChange={(e) => setRepeatCount(Math.max(1, Math.min(9999, Number(e.target.value))))}
              disabled={disabled}
            />
            <span className="tc-opt-unit">{t("tc.times")}</span>
          </div>
          <div className="tc-opt-row">
            <label className="tc-opt-label">{t("tc.opt.unit")}</label>
            <div className="tc-opt-radio-group">
              <label>
                <input type="radio" name="repeatMode" value="set"
                  checked={repeatMode === "set"}
                  onChange={() => setRepeatMode("set")} disabled={disabled} />
                {t("tc.opt.unitSet")}
              </label>
              <label>
                <input type="radio" name="repeatMode" value="tc"
                  checked={repeatMode === "tc"}
                  onChange={() => setRepeatMode("tc")} disabled={disabled} />
                {t("tc.opt.unitTc")}
              </label>
            </div>
          </div>
          <div className="tc-opt-row">
            <label className="tc-opt-label">{t("tc.opt.failAction")}</label>
            <select
              className="tc-opt-select"
              value={failAction}
              onChange={(e) => setFailAction(e.target.value as typeof failAction)}
              disabled={disabled}
            >
              <option value="stop">{t("tc.opt.failStop")}</option>
              <option value="continue">{t("tc.opt.failContinue")}</option>
              <option value="retry_crash">{t("tc.opt.failRetry")}</option>
            </select>
          </div>
        </div>
      )}

      {/* TC_00 MOS 반복 횟수 팝업 */}
      <MosRepeatModal
        open={mosModalOpen}
        onConfirm={handleMosConfirm}
        onCancel={() => setMosModalOpen(false)}
      />
    </div>
  );
}
