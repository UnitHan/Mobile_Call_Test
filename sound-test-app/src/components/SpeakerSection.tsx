import type { DeviceInfo } from "../types";
import { useT } from "../i18n";

interface SpeakerColProps {
  label: string;
  role: string;
  colorClass: "s1" | "s2";
  allDevices: { android: DeviceInfo[]; ios: DeviceInfo[] };
  selectedDevice: string;
  onDeviceChange: (val: string) => void;
  phoneNumber: string;
  onPhoneChange: (val: string) => void;
  shortDeviceLabel: (name: string, udid: string) => string;
}

/** 010- prefix를 보호하는 전화번호 포맷 */
export function formatPhoneInput(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  const suffix = digits.startsWith("010")
    ? digits.slice(3, 11)
    : digits.slice(0, 8);
  if (suffix.length === 0) return "010-";
  if (suffix.length <= 4) return `010-${suffix}`;
  return `010-${suffix.slice(0, 4)}-${suffix.slice(4)}`;
}

export function toPlainPhone(display: string): string {
  return display.replace(/\D/g, "");
}

function SpeakerCol({
  label,
  role,
  colorClass,
  allDevices,
  selectedDevice,
  onDeviceChange,
  phoneNumber,
  onPhoneChange,
  shortDeviceLabel,
}: SpeakerColProps) {
  const { t } = useT();
  const handleFocus = (e: React.FocusEvent<HTMLInputElement>) => {
    const pos = e.target.value.length;
    setTimeout(() => e.target.setSelectionRange(pos, pos), 0);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (
      (e.key === "Backspace" || e.key === "Delete") &&
      phoneNumber === "010-"
    ) {
      e.preventDefault();
    }
  };

  return (
    <div className="speaker-col">
      <div className={`speaker-head ${colorClass}`}>
        {label} <span className="speaker-role">{role}</span>
      </div>
      <label className="field-label">{t("speaker.device")}</label>
      <select
        value={selectedDevice}
        onChange={(e) => onDeviceChange(e.target.value)}
        className="inp"
      >
        <option value="">{t("speaker.select")}</option>
        <optgroup label="Android">
          {allDevices.android.map((d) => (
            <option key={d.udid} value={d.udid}>
              {shortDeviceLabel(d.name, d.udid)}
            </option>
          ))}
        </optgroup>
        <optgroup label="iOS">
          {allDevices.ios.map((d) => (
            <option key={d.udid} value={d.udid}>
              {shortDeviceLabel(d.name, d.udid)}
            </option>
          ))}
        </optgroup>
      </select>
      <label className="field-label" style={{ marginTop: "6px" }}>
        {t("speaker.phone")}
      </label>
      <div className="phone-wrap">
        <input
          type="tel"
          value={phoneNumber}
          maxLength={13}
          className="inp"
          onChange={(e) => onPhoneChange(formatPhoneInput(e.target.value))}
          onFocus={handleFocus}
          onKeyDown={handleKeyDown}
          placeholder="010-0000-0000"
          style={{
            paddingRight: phoneNumber.length > 4 ? "28px" : undefined,
          }}
        />
        {phoneNumber.length > 4 && (
          <button
            className="phone-clear"
            onClick={() => onPhoneChange("010-")}
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

/** 화자 설정 (화자 1 + 화자 2 나란히 배치) */
interface SpeakerSectionProps {
  androidDevices: DeviceInfo[];
  iosDevices: DeviceInfo[];
  speaker1Device: string;
  speaker2Device: string;
  speaker1Number: string;
  speaker2Number: string;
  onSpeaker1DeviceChange: (val: string) => void;
  onSpeaker2DeviceChange: (val: string) => void;
  onSpeaker1NumberChange: (val: string) => void;
  onSpeaker2NumberChange: (val: string) => void;
  shortDeviceLabel: (name: string, udid: string) => string;
  /** 발신/수신자 스왑 콜백 */
  onSwap?: () => void;
}

export function SpeakerSection({
  androidDevices,
  iosDevices,
  speaker1Device,
  speaker2Device,
  speaker1Number,
  speaker2Number,
  onSpeaker1DeviceChange,
  onSpeaker2DeviceChange,
  onSpeaker1NumberChange,
  onSpeaker2NumberChange,
  shortDeviceLabel,
  onSwap,
}: SpeakerSectionProps) {
  const { t } = useT();
  const allDevices = { android: androidDevices, ios: iosDevices };

  return (
    <section className="card">
      <div className="card-title">{t("speaker.title")}</div>
      <div className="speaker-pair">
        <SpeakerCol
          label={t("speaker.s1")}
          role={t("speaker.callerRole")}
          colorClass="s1"
          allDevices={allDevices}
          selectedDevice={speaker1Device}
          onDeviceChange={onSpeaker1DeviceChange}
          phoneNumber={speaker1Number}
          onPhoneChange={onSpeaker1NumberChange}
          shortDeviceLabel={shortDeviceLabel}
        />
        {onSwap && (
          <div className="speaker-swap-col">
            <button
              className="btn-swap"
              onClick={onSwap}
              title={`${t("speaker.callerRole")} ↔ ${t("speaker.receiverRole")}`}
            >
              ⇄
            </button>
          </div>
        )}
        <SpeakerCol
          label={t("speaker.s2")}
          role={t("speaker.receiverRole")}
          colorClass="s2"
          allDevices={allDevices}
          selectedDevice={speaker2Device}
          onDeviceChange={onSpeaker2DeviceChange}
          phoneNumber={speaker2Number}
          onPhoneChange={onSpeaker2NumberChange}
          shortDeviceLabel={shortDeviceLabel}
        />
      </div>
    </section>
  );
}
