import { useState, useRef } from "react";
import { listen } from "@tauri-apps/api/event";

const MAX_LOGS = 500;

export function useLogs() {
  const [appiumLogs, setAppiumLogs] = useState<string[]>([]);
  const [consoleLogs, setConsoleLogs] = useState<string[]>([]);
  const appiumLogRef = useRef<HTMLDivElement>(null);
  const consoleLogRef = useRef<HTMLDivElement>(null);

  const clearAppiumLogs = () => setAppiumLogs([]);
  const clearConsoleLogs = () => setConsoleLogs([]);

  /** useEffect 내에서 호출 — 모든 로그 이벤트 구독 시작. cleanup 함수 반환. */
  const startListening = async () => {
    const scroll = (ref: React.RefObject<HTMLDivElement | null>) => {
      setTimeout(() => {
        if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
      }, 0);
    };

    const unlisten1 = listen<string>("appium-log", (event) => {
      setAppiumLogs((prev) => {
        const next = [...prev, event.payload];
        return next.length > MAX_LOGS ? next.slice(-MAX_LOGS) : next;
      });
      scroll(appiumLogRef);
    });

    const unlisten2 = listen<string>("test-log", (event) => {
      setConsoleLogs((prev) => {
        const next = [...prev, event.payload];
        return next.length > MAX_LOGS ? next.slice(-MAX_LOGS) : next;
      });
      scroll(consoleLogRef);
    });

    return async () => {
      (await unlisten1)();
      (await unlisten2)();
    };
  };

  return {
    appiumLogs,
    consoleLogs,
    appiumLogRef,
    consoleLogRef,
    clearAppiumLogs,
    clearConsoleLogs,
    startListening,
  };
}
