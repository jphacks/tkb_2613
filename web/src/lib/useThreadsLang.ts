"use client";

import { useCallback, useSyncExternalStore } from "react";

import { parseThreadsLang, THREADS_LANG_KEY, type ThreadsLang } from "@/lib/threads-i18n";

const listeners = new Set<() => void>();

function readStored(): ThreadsLang | null {
  try { return parseThreadsLang(window.localStorage.getItem(THREADS_LANG_KEY)); }
  catch { return null; }
}

function writeStored(lang: ThreadsLang): void {
  try { window.localStorage.setItem(THREADS_LANG_KEY, lang); }
  catch { /* 保存できなくても、この画面の表示は切り替わる。 */ }
}

/** 優先順位：URL の ?lang= → 保存した選択 → 日本語。URL の指定は見つけた時点で保存し、OAuth 後も保つ。 */
function readLang(): ThreadsLang {
  const fromUrl = parseThreadsLang(new URLSearchParams(window.location.search).get("lang"));
  if (fromUrl) {
    writeStored(fromUrl);
    return fromUrl;
  }
  return readStored() ?? "ja";
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/**
 * Threads 画面の表示言語。サーバー描画とハイドレーションでは常に日本語で、直後に保存値へ切り替わる。
 * 選択は localStorage に保存し、Threads の認可画面へ出て戻っても保つ（?lang=en で直接開くこともできる）。
 */
export function useThreadsLang(): readonly [ThreadsLang, (next: ThreadsLang) => void] {
  const lang = useSyncExternalStore(subscribe, readLang, () => "ja" as ThreadsLang);
  const choose = useCallback((next: ThreadsLang) => {
    writeStored(next);
    // URL に ?lang= が残っていると、選び直した言語より優先されてしまうので外す
    const url = new URL(window.location.href);
    if (url.searchParams.has("lang")) {
      url.searchParams.delete("lang");
      window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    }
    listeners.forEach((listener) => listener());
  }, []);
  return [lang, choose] as const;
}
