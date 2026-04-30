import type { AudioDevice, AudioProfile } from "../types";
import { useT } from "../i18n";

// ── 사운드카드+채널 행 (S1/S2 공통) ─────────────────────────────────────────
interface DeviceRowProps {
  badge: string;
  badgeClass: "s1" | "s2";
  audioFile: string;
  outputDevice: string;
  onOutputDeviceChange: (val: string) => void;
  channel: string;
  onChannelChange: (val: string) => void;
  onTestTone: () => void;
  audioDevices: AudioDevice[];
}

function DeviceRow({
  badge,
  badgeClass,
  audioFile,
  outputDevice,
  onOutputDeviceChange,
  channel,
  onChannelChange,
  onTestTone,
  audioDevices,
}: DeviceRowProps) {
  const { t } = useT();
  const fileName = audioFile ? audioFile.split("/").pop() ?? audioFile : "";
  return (
    <div className="audio-block">
      <div className={`audio-badge ${badgeClass}`}>{badge}</div>
      <div className="audio-fields">
        {/* 선택된 파일명 표시 (읽기전용) */}
        <div className="audio-file-display" title={audioFile || t("audio.profileAutoSetHint")}>
          {fileName || <span className="audio-file-placeholder">{t("audio.profileAutoSet")}</span>}
        </div>
        {/* 사운드카드 + 테스트 톤 + 채널 */}
        <div className="field-row" style={{ marginTop: "4px" }}>
          <select
            value={outputDevice}
            onChange={(e) => onOutputDeviceChange(e.target.value)}
            className="inp inp-flex"
          >
            <option value="">{t("audio.defaultOutput")}</option>
            {audioDevices.map((d) => (
              <option key={d.id} value={String(d.id)}>
                [{d.id}] {d.name}
              </option>
            ))}
          </select>
          <button
            className="btn-xs btn-ghost"
            title="이 장치로 1kHz 테스트 톤 재생 (1초)"
            onClick={onTestTone}
          >
            🔔
          </button>
          <select
            value={channel}
            onChange={(e) => onChannelChange(e.target.value)}
            className="inp inp-ch"
          >
            <option value="">L+R</option>
            <option value="L">Left</option>
            <option value="R">Right</option>
          </select>
        </div>
      </div>
    </div>
  );
}

// ── AudioSection props ────────────────────────────────────────────────────────
interface AudioSectionProps {
  audioDevices: AudioDevice[];
  // 프로파일
  profiles: AudioProfile[];
  selectedProfileId: string | null;
  onSelectProfile: (id: string) => void;
  onEditProfiles: () => void;
  // 현재 S1/S2 (프로파일 선택 시 자동 채워짐)
  speaker1AudioFile: string;
  speaker2AudioFile: string;
  speaker1OutputDevice: string;
  speaker2OutputDevice: string;
  speaker1Channel: string;
  speaker2Channel: string;
  onSpeaker1OutputDeviceChange: (val: string) => void;
  onSpeaker2OutputDeviceChange: (val: string) => void;
  onSpeaker1ChannelChange: (val: string) => void;
  onSpeaker2ChannelChange: (val: string) => void;
  onTestTone1: () => void;
  onTestTone2: () => void;
  onRefreshDevices: () => void;
}

export function AudioSection({
  audioDevices,
  profiles,
  selectedProfileId,
  onSelectProfile,
  onEditProfiles,
  speaker1AudioFile,
  speaker2AudioFile,
  speaker1OutputDevice,
  speaker2OutputDevice,
  speaker1Channel,
  speaker2Channel,
  onSpeaker1OutputDeviceChange,
  onSpeaker2OutputDeviceChange,
  onSpeaker1ChannelChange,
  onSpeaker2ChannelChange,
  onTestTone1,
  onTestTone2,
  onRefreshDevices,
}: AudioSectionProps) {
  const { t } = useT();
  return (
    <section className="card">
      <div className="card-title-row">
        <span className="card-title">{t("audio.title")}</span>
        <button
          className="btn-xs btn-ghost"
          onClick={onRefreshDevices}
          title={t("audio.deviceRefresh")}
        >
          {t("audio.deviceRefresh")}
        </button>
      </div>

      {/* ── 프로파일 라디오 선택 ── */}
      <div className="profile-select-bar">
        <div className="profile-radio-list">
          {profiles.map((p) => (
            <label
              key={p.id}
              className={`profile-radio-item${selectedProfileId === p.id ? " selected" : ""}`}
              onClick={() => onSelectProfile(p.id)}
            >
              <input
                type="radio"
                name="audio-profile"
                readOnly
                checked={selectedProfileId === p.id}
              />
              <span className="profile-radio-name">
                {p.id === "daily" ? t("profiles.daily") : p.id === "phishing" ? t("profiles.phishing") : p.id === "dating" ? t("profiles.dating") : p.name}
              </span>
              {(p.refAudioPathS1 || p.refAudioPathS2 || p.refAudioPath) && (
                <span className="profile-radio-badge" title="정답지 음원 설정됨">🎯</span>
              )}
            </label>
          ))}
        </div>
        <button
          className="btn-xs btn-ghost"
          title={t("audio.editProfilesTitle")}
          onClick={onEditProfiles}
        >
          {t("audio.editProfiles")}
        </button>
      </div>

      {/* ── S1 / S2 사운드카드·채널 ── */}
      <DeviceRow
        badge="S1"
        badgeClass="s1"
        audioFile={speaker1AudioFile}
        outputDevice={speaker1OutputDevice}
        onOutputDeviceChange={onSpeaker1OutputDeviceChange}
        channel={speaker1Channel}
        onChannelChange={onSpeaker1ChannelChange}
        onTestTone={onTestTone1}
        audioDevices={audioDevices}
      />
      <DeviceRow
        badge="S2"
        badgeClass="s2"
        audioFile={speaker2AudioFile}
        outputDevice={speaker2OutputDevice}
        onOutputDeviceChange={onSpeaker2OutputDeviceChange}
        channel={speaker2Channel}
        onChannelChange={onSpeaker2ChannelChange}
        onTestTone={onTestTone2}
        audioDevices={audioDevices}
      />
    </section>
  );
}
