import { useState, useEffect, useRef } from "react";
import { useT } from "../i18n";

interface Props {
  open: boolean;
  onConfirm: (count: number) => void;
  onCancel: () => void;
}

/**
 * TC_00 (MOS 전용) 전용 반복 횟수 입력 팝업.
 * 기본값 10회, 최대 99999회.
 */
export function MosRepeatModal({ open, onConfirm, onCancel }: Props) {
  const [count, setCount] = useState(10);
  const inputRef = useRef<HTMLInputElement>(null);
  const { t } = useT();

  // 열릴 때 초기화 + 포커스
  useEffect(() => {
    if (open) {
      setCount(10);
      setTimeout(() => inputRef.current?.select(), 50);
    }
  }, [open]);

  if (!open) return null;

  const handleChange = (v: string) => {
    const n = Math.max(1, Math.min(99999, Number(v) || 1));
    setCount(n);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") onConfirm(count);
    if (e.key === "Escape") onCancel();
  };

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal-panel mos-repeat-modal"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="modal-header">
          <span className="modal-title">{t("mos.repeatTitle")}</span>
          <button className="btn-close-red" onClick={onCancel}>✕</button>
        </div>

        <div className="modal-body" style={{ padding: "20px 24px" }}>
          <p style={{ margin: "0 0 16px", color: "#ccc", fontSize: 14, lineHeight: 1.5 }}>
            {t("mos.repeatDesc")}
          </p>

          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <label style={{ fontWeight: 600, color: "#eee" }}>{t("mos.repeatLabel")}</label>
            <input
              ref={inputRef}
              type="number"
              min={1}
              max={99999}
              value={count}
              onChange={(e) => handleChange(e.target.value)}
              className="tc-opt-input"
              style={{ width: 100, textAlign: "center", fontSize: 16 }}
            />
            <span style={{ color: "#aaa" }}>{t("tc.times")}</span>
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn-xs btn-ghost" onClick={onCancel}>
            {t("mos.cancel")}
          </button>
          <button className="btn-xs btn-accent" onClick={() => onConfirm(count)}>
            {t("mos.repeatConfirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
