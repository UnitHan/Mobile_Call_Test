import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import type { DeviceInfo, ConnectionStatus } from "../types";

export function useDevices(setStatus: (msg: string) => void) {
  const [androidDevices, setAndroidDevices] = useState<DeviceInfo[]>([]);
  const [iosDevices, setIosDevices] = useState<DeviceInfo[]>([]);
  const [androidIpPort, setAndroidIpPort] = useState("192.168.0.10:5555");
  const [watchdogRunning, setWatchdogRunning] = useState(false);
  // Android 자동연결 성공 시: { newIp, oldIp } → App.tsx useEffect에서 speaker 업데이트
  const [lastAndroidConnect, setLastAndroidConnect] = useState<{ newIp: string; oldIp: string } | null>(null);

  const loadAndroidDevices = async () => {
    try {
      const result = await invoke<any>("list_android_devices");
      setAndroidDevices(result.devices || []);
    } catch (error) {
      console.error("Android 디바이스 목록 불러오기 실패:", error);
    }
  };

  const loadIosDevices = async () => {
    try {
      const result = await invoke<any>("list_ios_devices");
      const list: DeviceInfo[] = result.devices || [];
      setIosDevices(list);
    } catch (error) {
      console.error("iOS 디바이스 목록 불러오기 실패:", error);
    }
  };

  const handleGetAndroidIp = async () => {
    try {
      setStatus("📡 Android 디바이스 IP 확인 중...");
      const result = await invoke<ConnectionStatus>("get_android_ip");

      if (result.success) {
        const raw = result.message;

        if (raw.startsWith("ALREADY:")) {
          const ipPort = raw.replace("ALREADY:", "");
          const oldIp = androidIpPort;
          setAndroidIpPort(ipPort);
          setStatus(`✅ 이미 무선 연결됨: ${ipPort}`);
          await loadAndroidDevices();
          setLastAndroidConnect({ newIp: ipPort, oldIp });
          return;
        }

        const ipPort = raw;
        const oldIp = androidIpPort;
        setAndroidIpPort(ipPort);
        setStatus(`⚠️  USB 케이블을 **지금** 제거하세요! (10초 후 자동 연결)`);

        await new Promise((resolve) => setTimeout(resolve, 10000));

        setStatus("🔌 무선 연결 시도 중...");
        const connectResult = await invoke<ConnectionStatus>(
          "connect_android_wireless",
          { ipPort }
        );
        setStatus(connectResult.message);

        if (connectResult.success) {
          await loadAndroidDevices();
          setLastAndroidConnect({ newIp: ipPort, oldIp });
        }
      } else {
        setStatus(result.message);
      }
    } catch (error) {
      setStatus(`❌ IP 확인 실패: ${error}`);
    }
  };

  const handleDisconnectAndroid = async () => {
    try {
      setStatus("🔌 Android 연결 종료 중...");
      const result = await invoke<ConnectionStatus>(
        "disconnect_android_wireless",
        { ipPort: androidIpPort }
      );
      setStatus(result.message);
      await loadAndroidDevices();
    } catch (error) {
      setStatus(`❌ 연결 종료 실패: ${error}`);
    }
  };

  const handleCheckIphone = async () => {
    try {
      setStatus("📱 iPhone 연결 확인 중...");
      const result = await invoke<ConnectionStatus>("check_iphone_connection");
      setStatus(result.message);
      if (result.success) {
        await loadIosDevices();
      }
    } catch (error) {
      setStatus(`❌ 확인 실패: ${error}`);
    }
  };

  const handleInstallWda = async (udid: string | null) => {
    try {
      const selected = await open({
        multiple: false,
        directory: false,
        filters: [{ name: "IPA", extensions: ["ipa"] }],
      });
      if (!selected || typeof selected !== "string") return;

      setStatus("📦 WDA 설치 중... (최대 5분 소요)");
      const result = await invoke<ConnectionStatus>("install_wda", {
        ipaPath: selected,
        udid: udid || null,
      });
      setStatus(result.message);
    } catch (error) {
      setStatus(`❌ WDA 설치 실패: ${error}`);
    }
  };

  const handleStartWatchdog = async () => {
    const devices = androidIpPort.trim() ? [androidIpPort.trim()] : [];
    if (!devices.length) {
      setStatus("❌ Watchdog: Android IP:Port를 먼저 입력하세요.");
      return;
    }
    try {
      const result = await invoke<ConnectionStatus>("start_android_watchdog", {
        devices,
        interval: 30,
        keepalive: 30,
      });
      setStatus(result.message);
      if (result.success) setWatchdogRunning(true);
    } catch (error) {
      setStatus(`❌ Watchdog 시작 실패: ${error}`);
    }
  };

  const handleStopWatchdog = async () => {
    try {
      const result = await invoke<ConnectionStatus>("stop_android_watchdog");
      setStatus(result.message);
      setWatchdogRunning(false);
    } catch (error) {
      setStatus(`❌ Watchdog 정지 실패: ${error}`);
    }
  };

  return {
    androidDevices,
    iosDevices,
    androidIpPort,
    setAndroidIpPort,
    watchdogRunning,
    lastAndroidConnect,
    loadAndroidDevices,
    loadIosDevices,
    handleGetAndroidIp,
    handleDisconnectAndroid,
    handleCheckIphone,
    handleInstallWda,
    handleStartWatchdog,
    handleStopWatchdog,
  };
}
