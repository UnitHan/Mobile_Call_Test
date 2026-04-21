import { useState, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";

export interface SpeakerConfig {
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
  setSpeaker1Device: (v: string) => void;
  setSpeaker2Device: (v: string) => void;
  setSpeaker1Number: (v: string) => void;
  setSpeaker2Number: (v: string) => void;
  setSpeaker1AudioFile: (v: string) => void;
  setSpeaker2AudioFile: (v: string) => void;
  setSpeaker1OutputDevice: (v: string) => void;
  setSpeaker2OutputDevice: (v: string) => void;
  setSpeaker1Channel: (v: string) => void;
  setSpeaker2Channel: (v: string) => void;
  setSpeaker1RecChannel: (v: string) => void;
  setSpeaker2RecChannel: (v: string) => void;
  setSpeaker1OutputPair: (v: string) => void;
  setSpeaker2OutputPair: (v: string) => void;
}

interface StoredSpeakerConfig {
  speaker1Device?: string;
  speaker2Device?: string;
  speaker1Number?: string;
  speaker2Number?: string;
  speaker1AudioFile?: string;
  speaker2AudioFile?: string;
  speaker1OutputDevice?: string;
  speaker2OutputDevice?: string;
  speaker1Channel?: string;
  speaker2Channel?: string;
  speaker1RecChannel?: string;
  speaker2RecChannel?: string;
  speaker1OutputPair?: string;
  speaker2OutputPair?: string;
}

const DEFAULTS: Required<StoredSpeakerConfig> = {
  speaker1Device: "",
  speaker2Device: "",
  speaker1Number: "010-",
  speaker2Number: "010-",
  speaker1AudioFile: "",
  speaker2AudioFile: "",
  speaker1OutputDevice: "",
  speaker2OutputDevice: "",
  speaker1Channel: "",
  speaker2Channel: "",
  speaker1RecChannel: "",
  speaker2RecChannel: "",
  speaker1OutputPair: "",
  speaker2OutputPair: "",
};

/**
 * 화자 1·2의 디바이스·번호·오디오·출력장치·채널 상태를 관리합니다.
 * 앱 데이터 디렉터리의 speaker_config.json 에 저장 — dev/prod 재시작에도 유지됩니다.
 */
export function useSpeakerConfig(): SpeakerConfig {
  const [cfg, setCfg] = useState<Required<StoredSpeakerConfig>>(DEFAULTS);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loaded = useRef(false);

  // 앱 시작 시 파일에서 로드 (localStorage 마이그레이션 포함)
  useEffect(() => {
    invoke<string>("load_speaker_config")
      .then((raw) => {
        try {
          const stored: StoredSpeakerConfig = JSON.parse(raw);
          setCfg((prev) => ({ ...prev, ...stored }));
        } catch {
          // 파싱 실패 시 기본값 유지
        }
        // localStorage 마이그레이션: 이전 데이터가 있으면 가져온 후 삭제
        try {
          const lsRaw = localStorage.getItem("speakerConfig_v1");
          if (lsRaw) {
            const lsObj: StoredSpeakerConfig = JSON.parse(lsRaw);
            setCfg((prev) => ({ ...prev, ...lsObj }));
            localStorage.removeItem("speakerConfig_v1");
          }
        } catch { /* ignore */ }
        loaded.current = true;
      })
      .catch(() => {
        loaded.current = true;
      });
  }, []);

  // cfg 변경 시 500ms debounce 저장 (로드 완료 후에만)
  useEffect(() => {
    if (!loaded.current) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      invoke("save_speaker_config", { config: JSON.stringify(cfg) }).catch(console.warn);
    }, 500);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [cfg]);

  const set = <K extends keyof StoredSpeakerConfig>(key: K, value: string) => {
    setCfg((prev) => ({ ...prev, [key]: value }));
  };

  return {
    ...cfg,
    setSpeaker1Device: (v) => set("speaker1Device", v),
    setSpeaker2Device: (v) => set("speaker2Device", v),
    setSpeaker1Number: (v) => set("speaker1Number", v),
    setSpeaker2Number: (v) => set("speaker2Number", v),
    setSpeaker1AudioFile: (v) => set("speaker1AudioFile", v),
    setSpeaker2AudioFile: (v) => set("speaker2AudioFile", v),
    setSpeaker1OutputDevice: (v) => set("speaker1OutputDevice", v),
    setSpeaker2OutputDevice: (v) => set("speaker2OutputDevice", v),
    setSpeaker1Channel: (v) => set("speaker1Channel", v),
    setSpeaker2Channel: (v) => set("speaker2Channel", v),
    setSpeaker1RecChannel: (v) => set("speaker1RecChannel", v),
    setSpeaker2RecChannel: (v) => set("speaker2RecChannel", v),
    setSpeaker1OutputPair: (v) => set("speaker1OutputPair", v),
    setSpeaker2OutputPair: (v) => set("speaker2OutputPair", v),
  };
}

