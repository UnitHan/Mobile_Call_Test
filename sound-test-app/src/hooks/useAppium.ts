import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { ConnectionStatus } from "../types";

export type AppiumStatus = "idle" | "starting" | "running" | "stopping" | "error";

export function useAppium(setStatus: (msg: string) => void) {
  const [appiumStatus, setAppiumStatus] = useState<AppiumStatus>("idle");

  const handleStartAppium = async () => {
    try {
      setAppiumStatus("starting");
      setStatus("🚀 Appium 서버 시작 중...");
      const result = await invoke<ConnectionStatus>("start_appium_server");
      setAppiumStatus("running");
      setStatus(result.message);
    } catch (error) {
      setAppiumStatus("error");
      setStatus(`❌ Appium 시작 실패: ${error}`);
    }
  };

  const handleStopAppium = async () => {
    try {
      setAppiumStatus("stopping");
      const result = await invoke<ConnectionStatus>("stop_appium_server");
      setAppiumStatus("idle");
      setStatus(result.message);
    } catch (error) {
      setAppiumStatus("idle");
      setStatus(`❌ Appium 중지 실패: ${error}`);
    }
  };

  return { appiumStatus, handleStartAppium, handleStopAppium };
}
