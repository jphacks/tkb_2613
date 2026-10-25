"use client";

import { useState } from "react";

import { createResultLink, revokeResultLink } from "@/lib/api";

/** 診断した本人が押したときだけ、期限付きの閲覧リンクを作る。 */
export function ResultShare() {
  const [link, setLink] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);

  async function create() {
    setPending(true);
    setError(false);
    try {
      const token = await createResultLink();
      setToken(token);
      setLink(`${window.location.origin}/share#${token}`);
    } catch {
      setError(true);
    } finally {
      setPending(false);
    }
  }

  async function revoke() {
    if (!token) return;
    setPending(true);
    setError(false);
    try {
      await revokeResultLink(token);
      setToken(null);
      setLink(null);
    } catch {
      setError(true);
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="結果の閲覧リンク" className="max-w-2xl space-y-3 border-t border-ink/20 pt-6">
      <p className="text-sm text-ink/70">結果を別の端末で見せる場合、閲覧専用リンクを作れます。リンクを知る人は2時間、投稿・写真・推定を見ることができます。</p>
      {!link && (
        <button type="button" onClick={create} disabled={pending} className="rounded-sm border border-ink/50 px-4 py-2 hover:bg-ink/10 disabled:opacity-50">
          {pending ? "リンクを作成中…" : "閲覧リンクを作る"}
        </button>
      )}
      {link && (
        <div className="space-y-2">
          <label htmlFor="result-link" className="block text-sm">閲覧リンク</label>
          <input id="result-link" readOnly value={link} onFocus={(event) => event.currentTarget.select()} className="w-full rounded-sm border border-ink/40 bg-paper px-3 py-2 text-sm" />
          <a href={link} target="_blank" rel="noopener noreferrer" className="inline-block text-sm text-seeker underline underline-offset-4">別の画面で開く</a>
          <button type="button" onClick={revoke} disabled={pending} className="ml-4 text-sm underline underline-offset-4 disabled:opacity-50">リンクを無効にする</button>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-seeker">リンクを作れませんでした。ログイン状態を確認してください。</p>}
    </section>
  );
}
