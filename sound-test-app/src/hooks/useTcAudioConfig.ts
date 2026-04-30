import { useState, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { TcId, TcSpeakerConfig, TcSpeakerEntry } from "../types";

const EMPTY_ENTRY: TcSpeakerEntry = {
  speaker1Device: "",
  speaker2Device: "",
  profileId: "",
};

function migrateEntry(v: Record<string, string>): TcSpeakerEntry {
  return {
    speaker1Device: v.speaker1Device ?? "",
    speaker2Device: v.speaker2Device ?? "",
    profileId: v.profileId ?? "",
  };
}

export function useTcSpeakerConfig() {
  const [config, setConfig] = useState<TcSpeakerConfig>({});
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loaded = useRef(false);

  // 앱 시작 시 파일에서 로드 (localStorage 마이그레이션 포함)
  useEffect(() => {
    invoke<string>("load_tc_speaker_config")
      .then((raw) => {
        try {
          const stored = JSON.parse(raw) as Record<string, Record<string, string>>;
          const migrated: TcSpeakerConfig = {};
          for (const [k, v] of Object.entries(stored)) {
            migrated[k as TcId] = migrateEntry(v);
          }
          setConfig(migrated);
        } catch { /* 파싱 실패 시 기본값 유지 */ }
        // localStorage 마이그레이션
        try {
          const lsRaw = localStorage.getItem("ixio-tc-speaker-config");
          if (lsRaw) {
            const raw = JSON.parse(lsRaw) as Record<string, Record<string, string>>;
            const migrated: TcSpeakerConfig = {};
            for (const [k, v] of Object.entries(raw)) {
              migrated[k as TcId] = migrateEntry(v);
            }
            setConfig(migrated);
            localStorage.removeItem("ixio-tc-speaker-config");
          }
        } catch { /* ignore */ }
        loaded.current = true;
      })
      .catch(() => {
        loaded.current = true;
      });
  }, []);

  // config 변경 시 500ms debounce 저장
  useEffect(() => {
    if (!loaded.current) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      const saveable: Record<string, Record<string, string>> = {};
      for (const [k, v] of Object.entries(config)) {
        saveable[k] = v as Record<string, string>;
      }
      invoke("save_tc_speaker_config", { config: JSON.stringify(saveable) }).catch(console.warn);
    }, 500);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [config]);

  const getEntry = (tcId: TcId): TcSpeakerEntry =>
    config[tcId] ?? { ...EMPTY_ENTRY };

  const updateField = (tcId: TcId, field: keyof TcSpeakerEntry, value: string) => {
    setConfig((prev) => {
      const entry = prev[tcId] ?? { ...EMPTY_ENTRY };
      return { ...prev, [tcId]: { ...entry, [field]: value } };
    });
  };

  const clearEntry = (tcId: TcId) => {
    setConfig((prev) => ({ ...prev, [tcId]: { ...EMPTY_ENTRY } }));
  };

  const hasConfig = (tcId: TcId): boolean => {
    const e = config[tcId];
    if (!e) return false;
    return !!(e.speaker1Device || e.speaker2Device || e.profileId);
  };

  return { config, getEntry, updateField, clearEntry, hasConfig };
}

