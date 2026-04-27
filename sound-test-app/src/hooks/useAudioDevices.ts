import { useState, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { listen } from "@tauri-apps/api/event";
import type { AudioDevice, ConnectionStatus } from "../types";

export function useAudioDevices(setStatus: (msg: string) => void) {
  const [audioDevices, setAudioDevices] = useState<AudioDevice[]>([]);
  const [speaker1Progress, setSpeaker1Progress] = useState<number>(-1);
  const [speaker2Progress, setSpeaker2Progress] = useState<number>(-1);
  const progressUnlisten = useRef<(() => void) | null>(null);

  const loadAudioDevices = async () => {
    try {
      const devices = await invoke<AudioDevice[]>("list_audio_devices");
      setAudioDevices(devices || []);
    } catch (error) {
      console.error("오디오 장치 목록 불러오기 실패:", error);
    }
  };

  const handleTestTone = async (deviceStr: string, label: string, outputPair?: string) => {
    // HDMI 등으로 인덱스가 밀릴 수 있으므로 재생 직전 장치 목록 새로고침
    await loadAudioDevices();
    const deviceIndex: number | null =
      deviceStr !== "" ? parseInt(deviceStr) : null;
    setStatus(`🔔 ${label} 테스트 톤 재생 중... (1초)`);
    try {
      const result = await invoke<ConnectionStatus>("play_test_tone", {
        deviceIndex,
        outputPair: outputPair || null,
      });
      setStatus(result.message);
    } catch (e) {
      setStatus(`❌ 테스트 톤 실패: ${e}`);
    }
  };

  const handleSelectAudioFile = async (
    speaker: 1 | 2,
    setFile: (path: string) => void
  ) => {
    try {
      const selected = await open({
        multiple: false,
        directory: false,
        filters: [{ name: "Audio", extensions: ["wav", "mp3", "m4a"] }],
      });
      if (selected && typeof selected === "string") {
        setFile(selected);
        setStatus(
          `✅ 화자${speaker} 오디오 선택됨: ${selected.split("/").pop()}`
        );
      }
    } catch (error) {
      setStatus(`❌ 파일 선택 실패: ${error}`);
    }
  };

  /** useEffect 내에서 호출 — audio-progress 이벤트 구독. cleanup 반환. */
  const startProgressListening = async () => {
    const unlisten = await listen<string>("audio-progress", (event) => {
      const parts = event.payload.split(":");
      if (parts.length >= 3 && parts[0] === "AUDIO_PROGRESS") {
        const progress = parseFloat(parts[2]);
        if (parts[1] === "speaker1") setSpeaker1Progress(progress);
        else if (parts[1] === "speaker2") setSpeaker2Progress(progress);
      }
    });
    // audio-interface-updated: 슬롯 저장 성공 시 재시작 없이 오디오 장치 목록 갱신
    const unlistenInterface = await listen("audio-interface-updated", () => {
      loadAudioDevices();
    });
    progressUnlisten.current = unlisten;
    return () => { unlisten(); unlistenInterface(); };
  };

  const resetProgress = () => {
    setSpeaker1Progress(-1);
    setSpeaker2Progress(-1);
  };

  return {
    audioDevices,
    speaker1Progress,
    speaker2Progress,
    progressUnlisten,
    loadAudioDevices,
    handleTestTone,
    handleSelectAudioFile,
    startProgressListening,
    resetProgress,
  };
}
