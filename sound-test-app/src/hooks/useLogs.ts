import { useState, useRef } from "react";
import { listen } from "@tauri-apps/api/event";

const MAX_LOGS = 500;
// 스크롤 스로틀 간격 (ms) — 로그 이벤트마다 setTimeout 누적 방지
const SCROLL_THROTTLE_MS = 120;

export function useLogs() {
  const [appiumLogs, setAppiumLogs] = useState<string[]>([]);
  const [consoleLogs, setConsoleLogs] = useState<string[]>([]);
  const appiumLogRef = useRef<HTMLDivElement>(null);
  const consoleLogRef = useRef<HTMLDivElement>(null);
  const appiumScrollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const consoleScrollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearAppiumLogs = () => setAppiumLogs([]);
  const clearConsoleLogs = () => setConsoleLogs([]);

  /** useEffect 내에서 호출 — 모든 로그 이벤트 구독 시작. cleanup 함수 반환. */
  const startListening = async () => {
    // 스로틀된 스크롤: SCROLL_THROTTLE_MS 내 중복 호출 무시
    const makeScroll = (
      ref: React.RefObject<HTMLDivElement | null>,
      timerRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>,
    ) => () => {
      if (timerRef.current !== null) return;
      timerRef.current = setTimeout(() => {
        if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
        timerRef.current = null;
      }, SCROLL_THROTTLE_MS);
    };
    const scrollAppium = makeScroll(appiumLogRef, appiumScrollTimer);
    const scrollConsole = makeScroll(consoleLogRef, consoleScrollTimer);

    const unlisten1 = listen<string>("appium-log", (event) => {
      setAppiumLogs((prev) => {
        const next = [...prev, event.payload];
        return next.length > MAX_LOGS ? next.slice(-MAX_LOGS) : next;
      });
      scrollAppium();
    });

    const unlisten2 = listen<string>("test-log", (event) => {
      setConsoleLogs((prev) => {
        const next = [...prev, event.payload];
        return next.length > MAX_LOGS ? next.slice(-MAX_LOGS) : next;
      });
      scrollConsole();
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
