import { useState, useCallback } from "react";

const STORAGE_KEY = "ixio-notice-board";

export interface NoticeItem {
  id: string;
  text: string;
  createdAt: string;
}

function load(): NoticeItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function save(items: NoticeItem[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

export function useNotice() {
  const [notices, setNotices] = useState<NoticeItem[]>(load);

  const addNotice = useCallback((text: string) => {
    const item: NoticeItem = {
      id: Date.now().toString(),
      text: text.trim(),
      createdAt: new Date().toLocaleString("ko-KR"),
    };
    setNotices((prev) => {
      const next = [item, ...prev];
      save(next);
      return next;
    });
  }, []);

  const updateNotice = useCallback((id: string, text: string) => {
    setNotices((prev) => {
      const next = prev.map((n) => (n.id === id ? { ...n, text: text.trim() } : n));
      save(next);
      return next;
    });
  }, []);

  const deleteNotice = useCallback((id: string) => {
    setNotices((prev) => {
      const next = prev.filter((n) => n.id !== id);
      save(next);
      return next;
    });
  }, []);

  const moveUp = useCallback((id: string) => {
    setNotices((prev) => {
      const idx = prev.findIndex((n) => n.id === id);
      if (idx <= 0) return prev;
      const next = [...prev];
      [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
      save(next);
      return next;
    });
  }, []);

  return { notices, addNotice, updateNotice, deleteNotice, moveUp };
}
