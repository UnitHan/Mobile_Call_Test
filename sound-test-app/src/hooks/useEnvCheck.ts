import { useState, useRef, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { EnvItem, EnvCheckResult, ConnectionStatus } from "../types";

export function useEnvCheck() {
  const [showEnvPanel, setShowEnvPanel] = useState(false);
  const [envItems, setEnvItems] = useState<EnvItem[]>([]);
  const [envAllOk, setEnvAllOk] = useState(true);
  const [pythonEnvReady, setPythonEnvReady] = useState(false);
  const [envChecking, setEnvChecking] = useState(false);
  const [setupRunning, setSetupRunning] = useState(false);
  const [setupLogs, setSetupLogs] = useState<string[]>([]);
  const setupLogRef = useRef<HTMLDivElement>(null);

  // setup-log 이벤트 구독 (Python 환경 설치 중 스트리밍 로그)
  useEffect(() => {
    const unlisten = listen<string>("setup-log", (event) => {
      setSetupLogs((prev) => [...prev, event.payload]);
      setTimeout(() => {
        if (setupLogRef.current)
          setupLogRef.current.scrollTop = setupLogRef.current.scrollHeight;
      }, 0);
    });
    return () => {
      unlisten.then((fn) => fn());
    };
  }, []);
  const checkEnv = async () => {
    setEnvChecking(true);
    try {
      const result = await invoke<EnvCheckResult>("check_environment");
      setEnvItems(result.items);
      setEnvAllOk(result.all_ok);
      setPythonEnvReady(result.python_env_ready);
    } catch (e) {
      console.error("env check failed", e);
    } finally {
      setEnvChecking(false);
    }
  };

  const setupPython = async () => {
    setSetupRunning(true);
    setSetupLogs([]);
    try {
      const result = await invoke<ConnectionStatus>("setup_python_env");
      setSetupLogs((prev) => [...prev, result.message]);
      await checkEnv();
    } catch (e) {
      setSetupLogs((prev) => [...prev, `❌ ${e}`]);
    } finally {
      setSetupRunning(false);
    }
  };

  return {
    showEnvPanel,
    setShowEnvPanel,
    envItems,
    envAllOk,
    pythonEnvReady,
    envChecking,
    setupRunning,
    setupLogs,
    setupLogRef,
    checkEnv,
    setupPython,
  };
}
