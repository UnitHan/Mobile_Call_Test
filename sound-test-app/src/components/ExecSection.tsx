import type { AppiumStatus } from "../hooks/useAppium";
import { useT } from "../i18n";

interface ProgressBarProps {
  label: string;
  progress: number;
  channel: string;
  t: (key: string) => string;
}

function ProgressBar({ label, progress, channel, t }: ProgressBarProps) {
  const idle = progress < 0;
  const done = progress >= 1.0;
  const pct = idle ? 0 : Math.round(progress * 100);
  const colorMap: Record<string, string> = {
    L: "#3b82f6",
    R: "#f97316",
    "": "#22c55e",
  };
  const color = colorMap[channel] ?? "#22c55e";

  return (
    <div className="progress-row">
      <span className="progress-label">{label}</span>
      <span
        className="progress-ch"
        style={{ background: idle ? "#333" : color }}
      >
        {channel === "L" ? "L" : channel === "R" ? "R" : "L+R"}
      </span>
      <div className="progress-track">
        <div
          className="progress-bar"
          style={{
            width: `${pct}%`,
            background: done
              ? "#22c55e"
              : `linear-gradient(90deg, ${color}99, ${color})`,
            boxShadow: !idle && !done ? `0 0 6px ${color}66` : "none",
          }}
        />
      </div>
      <span
        className="progress-pct"
        style={{ color: idle ? "#555" : done ? "#22c55e" : color }}
      >
        {idle ? t("exec.progressIdle") : done ? t("exec.progressDone") : `${pct}%`}
      </span>
    </div>
  );
}

interface ExecSectionProps {
  appiumStatus: AppiumStatus;
  isRunning: boolean;
  isBlocked?: boolean;   // TC 테스트 실행 중 (버튼 비활성화)
  speaker1Progress: number;
  speaker2Progress: number;
  speaker1Channel: string;
  speaker2Channel: string;
  repeatCount: number;
  currentRepeat: number;  // 0 = 반복 아님, 1~ = 현재 회차
  totalRepeat: number;    // 총 반복 횟수 (반복 중일 때만)
  onStart: () => void;
  onStartRepeat: () => void;
  onStop: () => void;
  onRepeatCountChange: (n: number) => void;
  /** 마지막 테스트 성공 여부 — true 이면 분석하기 버튼 활성화 */
  lastTestSucceeded?: boolean;
  /** 분석 실행 중 */
  isAnalyzing?: boolean;
  /** 분석하기 버튼 클릭 핸들러 */
  onAnalyze?: () => void;
}

export function ExecSection({
  appiumStatus,
  isRunning,
  isBlocked = false,
  speaker1Progress,
  speaker2Progress,
  speaker1Channel,
  speaker2Channel,
  repeatCount,
  currentRepeat,
  totalRepeat,
  onStart,
  onStartRepeat,
  onStop,
  onRepeatCountChange,
  lastTestSucceeded = false,
  isAnalyzing = false,
  onAnalyze,
}: ExecSectionProps) {
  const { t } = useT();
  const disabled = isRunning || isBlocked || appiumStatus !== "running";

  return (
    <section className="card card-exec">
      <div className="card-title">{t("exec.title")}</div>
      {appiumStatus !== "running" && (
        <div className="appium-warn">
          {t("exec.appiumWarn")}
        </div>
      )}

      <div className="exec-buttons">
        {/* 단일 테스트 */}
        <button className="btn-start" onClick={onStart} disabled={disabled}>
          {isRunning && currentRepeat === 0 ? (
            <><span className="spin">⟳</span> {t("exec.running")}</>
          ) : (
            <>{t("exec.start")}</>
          )}
        </button>

        {/* 반복 테스트 */}
        <div className="btn-repeat-wrap">
          <button className="btn-repeat" onClick={onStartRepeat} disabled={disabled}>
            {isRunning && currentRepeat > 0 ? (
              <><span className="spin">⟳</span> {currentRepeat}/{totalRepeat}{t("exec.times")}</>
            ) : (
              <>{t("exec.repeatStart")}</>
            )}
          </button>
          <input
            className="repeat-count-input"
            type="number"
            min={1}
            max={999}
            value={repeatCount}
            disabled={isRunning}
            onChange={(e) => {
              const v = parseInt(e.target.value);
              if (!isNaN(v) && v >= 1) onRepeatCountChange(v);
            }}
            title={t("tc.opt.count")}
          />
          <span className="repeat-count-unit">{t("exec.times")}</span>
        </div>

        <button className="btn-stop" onClick={onStop} disabled={!isRunning}>
          {t("exec.stop")}
        </button>
      </div>

      <div className="progress-list">
        <ProgressBar label="S1" progress={speaker1Progress} channel={speaker1Channel} t={t} />
        <ProgressBar label="S2" progress={speaker2Progress} channel={speaker2Channel} t={t} />
      </div>

      {/* 분석하기 버튼 — 테스트 성공 후 표시 */}
      {lastTestSucceeded && (
        <div className="analyze-bar">
          <button
            className="btn-analyze"
            disabled={isAnalyzing || isRunning}
            onClick={onAnalyze}
          >
            {isAnalyzing
              ? <><span className="spin">⟳</span> {t("exec.analyzing")}</>
              : <>📊 {t("exec.analyze")}</>}
          </button>
          <span className="analyze-hint">
            선택된 프로파일의 정답지와 최근 통화 녹음을 비교합니다.
          </span>
        </div>
      )}
    </section>
  );
}
