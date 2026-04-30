/**
 * useAudioProfiles
 * ─────────────────────────────────────────────────────────────────────────────
 * 음원 프로파일(콘텐츠 전용): S1/S2 음원 + 정답지 + 대본.
 * 하드웨어 라우팅(출력장치·채널 등)은 글로벌 설정에서 일원 관리.
 * localStorage 키: "ixio-audio-profiles" / "ixio-selected-profile-id"
 */
import { useState, useCallback } from "react";
import type { AudioProfile } from "../types";

const STORAGE_KEY    = "ixio-audio-profiles";
const SELECTED_KEY   = "ixio-selected-profile-id";

// ── 기본 프로파일 ─────────────────────────────────────────────────────────────

// dating 테스트 음원 경로 (설정 모달 파일 피커로 변경 가능)
const DATING_S1 = "/Users/m9test/yjlee/Mobile_Call_Test/sound-test-app/audio_files/dating_SPEAKER_00.wav";
const DATING_S2 = "/Users/m9test/yjlee/Mobile_Call_Test/sound-test-app/audio_files/dating_SPEAKER_01.wav";

const DEFAULT_PROFILES: AudioProfile[] = [
  {
    id:   "daily",
    name: "일상 대화",
    speaker1AudioFile: "",
    speaker2AudioFile: "",
    refAudioPathS1: "",
    refAudioPathS2: "",
    refAudioPath: "",
    scriptPath: "",
  },
  {
    id:   "phishing",
    name: "보이스피싱",
    speaker1AudioFile: "",
    speaker2AudioFile: "",
    refAudioPathS1: "",
    refAudioPathS2: "",
    refAudioPath: "",
    scriptPath: "",
  },
  {
    id:   "dating",
    name: "데이팅",
    speaker1AudioFile: DATING_S1,
    speaker2AudioFile: DATING_S2,
    refAudioPathS1: DATING_S1,
    refAudioPathS2: DATING_S2,
    refAudioPath: "",
    scriptPath: "",
  },
];

// ── 유틸 ─────────────────────────────────────────────────────────────────────
function loadProfiles(): AudioProfile[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PROFILES;
    const parsed = JSON.parse(raw) as AudioProfile[];
    if (!parsed.length) return DEFAULT_PROFILES;
    // 하위호환 마이그레이션: refAudioPath만 있고 S1/S2가 없는 경우 + 하드웨어 필드 strip
    const mapped = parsed.map((p) => ({
      id: p.id,
      // "보이스피싱 테스트" → "보이스피싱" 이름 마이그레이션
      name: p.id === "phishing" && p.name === "보이스피싱 테스트" ? "보이스피싱" : p.name,
      speaker1AudioFile: p.speaker1AudioFile ?? "",
      speaker2AudioFile: p.speaker2AudioFile ?? "",
      refAudioPathS1: p.refAudioPathS1 ?? "",
      refAudioPathS2: p.refAudioPathS2 ?? "",
      refAudioPath:   p.refAudioPath   ?? "",
      scriptPath: p.scriptPath ?? "",
    }));
    // 내장 프로파일 누락 시 append (신규 기본 프로파일이 기존 사용자에게 자동 노출)
    for (const def of DEFAULT_PROFILES) {
      if (!mapped.some((p) => p.id === def.id)) {
        mapped.push(def);
      }
    }
    return mapped;
  } catch {
    return DEFAULT_PROFILES;
  }
}

function saveProfiles(list: AudioProfile[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}

function loadSelectedId(profiles: AudioProfile[]): string {
  try {
    const saved = localStorage.getItem(SELECTED_KEY);
    if (saved && profiles.some((p) => p.id === saved)) return saved;
  } catch { /* ignore */ }
  // 저장값 없거나 유효하지 않으면 첫 번째 프로파일 자동 선택
  return profiles[0]?.id ?? "";
}

// ── 훅 ───────────────────────────────────────────────────────────────────────
export interface UseAudioProfilesResult {
  profiles: AudioProfile[];
  selectedProfileId: string;
  selectedProfile: AudioProfile | null;

  /** 프로파일 선택 (Radio 버튼) */
  selectProfile: (id: string) => void;

  /** 프로파일 단일 필드 업데이트 (설정 모달에서 사용) */
  updateProfile: (id: string, patch: Partial<AudioProfile>) => void;

  /** 새 프로파일 추가 */
  addProfile: (name: string) => AudioProfile;

  /** 프로파일 삭제 (기본 프로파일은 삭제 불가) */
  removeProfile: (id: string) => void;
}

export function useAudioProfiles(): UseAudioProfilesResult {
  const [profiles, setProfiles] = useState<AudioProfile[]>(() => loadProfiles());
  const [selectedProfileId, setSelectedProfileId] = useState<string>(() =>
    loadSelectedId(loadProfiles())
  );

  const selectedProfile = profiles.find((p) => p.id === selectedProfileId) ?? null;

  const selectProfile = useCallback((id: string) => {
    setSelectedProfileId(id);
    localStorage.setItem(SELECTED_KEY, id);
  }, []);

  const updateProfile = useCallback((id: string, patch: Partial<AudioProfile>) => {
    setProfiles((prev) => {
      const next = prev.map((p) => (p.id === id ? { ...p, ...patch } : p));
      saveProfiles(next);
      return next;
    });
  }, []);

  const addProfile = useCallback((name: string): AudioProfile => {
    const newProfile: AudioProfile = {
      id:   `profile_${Date.now()}`,
      name,
      speaker1AudioFile: "",
      speaker2AudioFile: "",
      refAudioPathS1:  "",
      refAudioPathS2:  "",
      refAudioPath:  "",
      scriptPath:    "",
    };
    setProfiles((prev) => {
      const next = [...prev, newProfile];
      saveProfiles(next);
      return next;
    });
    return newProfile;
  }, []);

  const removeProfile = useCallback((id: string) => {
    // 기본 프로파일 삭제 방지
    if (id === "phishing" || id === "daily" || id === "dating") return;
    setProfiles((prev) => {
      const next = prev.filter((p) => p.id !== id);
      saveProfiles(next);
      if (selectedProfileId === id) {
        const newSel = next[0]?.id ?? "";
        setSelectedProfileId(newSel);
        localStorage.setItem(SELECTED_KEY, newSel);
      }
      return next;
    });
  }, [selectedProfileId]);

  return {
    profiles,
    selectedProfileId,
    selectedProfile,
    selectProfile,
    updateProfile,
    addProfile,
    removeProfile,
  };
}
