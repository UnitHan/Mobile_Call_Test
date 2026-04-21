import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";

interface AppVersions {
  ios: string;
  android: string;
}

export function useAppVersions(iosPkg: string, androidPkg: string) {
  const [versions, setVersions] = useState<AppVersions>({ ios: "", android: "" });

  const refresh = useCallback(async () => {
    try {
      const v = await invoke<AppVersions>("get_app_versions", {
        iosPkg: iosPkg || "",
        androidPkg: androidPkg || "",
      });
      setVersions(v);
    } catch {
      // 조회 실패 시 무시 (버전 표시 없음)
    }
  }, [iosPkg, androidPkg]);

  useEffect(() => {
    refresh();
    // 30초마다 갱신 (디바이스 연결/해제 반영)
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  return versions;
}
