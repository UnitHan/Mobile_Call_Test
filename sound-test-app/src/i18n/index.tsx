import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import { ko } from "./locales/ko";
import { en } from "./locales/en";
import type { Translations } from "./locales/ko";

export type Lang = "ko" | "en";

const STORAGE_KEY = "ixio-lang";

const translations: Record<Lang, Translations> = { ko, en };

/** 점(.)으로 구분된 경로로 중첩 객체 값 조회 */
function getNestedValue(obj: unknown, path: string): string | undefined {
  const parts = path.split(".");
  let cur: unknown = obj;
  for (const p of parts) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[p];
  }
  return typeof cur === "string" ? cur : undefined;
}

interface LangCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const LangContext = createContext<LangCtx>({
  lang: "ko",
  setLang: () => {},
  t: (k) => k,
});

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(
    () => (localStorage.getItem(STORAGE_KEY) as Lang | null) ?? "ko"
  );

  function setLang(l: Lang) {
    setLangState(l);
    localStorage.setItem(STORAGE_KEY, l);
  }

  function t(key: string, vars?: Record<string, string | number>): string {
    let str = getNestedValue(translations[lang], key);
    if (str === undefined) {
      // 한국어 폴백
      str = getNestedValue(translations.ko, key) ?? key;
    }
    if (vars) {
      Object.entries(vars).forEach(([k, v]) => {
        str = (str as string).replace(`{${k}}`, String(v));
      });
    }
    return str as string;
  }

  return (
    <LangContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LangContext.Provider>
  );
}

export function useT() {
  return useContext(LangContext);
}
