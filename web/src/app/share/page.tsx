"use client";

import { useEffect, useState } from "react";

import { ConclusionBoard } from "@/components/conclusion-board/ConclusionBoard";
import { PostCard } from "@/components/post-list/PostCard";
import { Reveal } from "@/components/reveal/Reveal";
import { getSharedResult } from "@/lib/api";
import { messages } from "@/lib/messages";
import { validNameConclusions } from "@/lib/reveal";
import type { DiagnosisSnapshot } from "@/types/diagnose";

export default function SharedResultPage() {
  const [result, setResult] = useState<DiagnosisSnapshot | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const token = window.location.hash.slice(1);
    const controller = new AbortController();
    if (!/^[A-Za-z0-9_-]{32,128}$/.test(token)) {
      queueMicrotask(() => {
        if (!controller.signal.aborted) setError(true);
      });
      return () => controller.abort();
    }
    getSharedResult(token, { signal: controller.signal })
      .then((snapshot) => {
        if (!controller.signal.aborted) setResult(snapshot);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="mx-auto max-w-5xl space-y-10 px-4 py-12 sm:px-8 sm:py-20">
      <h1 className="sr-only">{messages.app.name} の閲覧用診断結果</h1>
      <p className="text-sm text-ink/70">閲覧専用の診断結果です。この画面から投稿を削除することはできません。</p>
      {!result && !error && <p role="status">結果を読み込んでいます…</p>}
      {error && <p role="alert">リンクが無効か、有効期限が切れています。</p>}
      {result && (
        <>
          <Reveal posts={result.posts} clues={result.clues} conclusions={validNameConclusions(result.conclusions)} />
          <ConclusionBoard clues={result.clues} conclusions={validNameConclusions(result.conclusions)} />
          {result.plan.posts.length > 0 && (
            <section aria-label={messages.risky.heading} className="max-w-2xl space-y-3">
              <h2 className="horror-title text-4xl">{messages.risky.heading}</h2>
              <p className="text-sm text-ink/70">削除候補の閲覧のみできます。</p>
              <ul className="space-y-2">
                {result.plan.posts.map((candidate) => (
                  <li key={candidate.post_id} className="border-l-4 border-seeker bg-paper-deep px-4 py-3">
                    {result.posts.find((post) => post.post_id === candidate.post_id)?.text || messages.risky.noText}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <ol aria-label="診断した投稿" className="max-w-2xl space-y-5">
            {result.posts.map((post) => (
              <li key={post.post_id}>
                <PostCard post={post} found={{ clues: result.clues.filter((clue) => clue.post_id === post.post_id), error: null }} />
              </li>
            ))}
          </ol>
        </>
      )}
    </main>
  );
}
