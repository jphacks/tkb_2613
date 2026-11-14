"use client";

import { useEffect, useState } from "react";

import { DiagnoseLoading } from "@/components/diagnose-loading/DiagnoseLoading";
import type { ThreadsText } from "@/lib/threads-i18n";
import { formatClock, type ThreadsProgress } from "@/lib/threads-progress";
import type { Post } from "@/types/post";

/** 経過時間の表示を進める間隔 */
const TICK_MS = 1000;

interface ThreadsDiagnosingProps {
  readonly t: ThreadsText;
  readonly status: string;
  /** 診断の前に取得した本人投稿。再読み込みのあとは空 */
  readonly posts: readonly Post[];
  /** サーバーから届いた最新の進み具合。まだ届いていなければ null */
  readonly progress: ThreadsProgress | null;
  /** 診断を始めた時刻（Date.now() の値）。サーバーの経過時間があればそれに合わせる */
  readonly startedAt: number;
}

/**
 * Threads の診断中の表示。Bluesky と同じ DiagnoseLoading を使い、
 * サーバーが返した実際の段階と読み終えた件数、経過時間を足す。
 */
export function ThreadsDiagnosing({ t, status, posts, progress, startedAt }: ThreadsDiagnosingProps) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(id);
  }, []);

  const stages = progress?.stages ?? [];
  const current = progress?.stage ? stages.indexOf(progress.stage) : -1;
  const total = progress?.posts_total ?? null;
  // 件数が届くのは解析の段階から。それより前は割合を出さない
  const bar = total !== null && total > 0 ? { done: progress?.posts_read ?? 0, total } : null;
  const read = new Set(progress?.read_post_ids ?? []);
  const readPosts = posts.filter((post) => read.has(post.post_id));

  return (
    <DiagnoseLoading active posts={readPosts} found={{}} status={status} progress={bar}>
      <p className="mt-3 font-bold tabular-nums text-ink/80">{t.elapsedLive(formatClock(now - startedAt))}</p>
      {stages.length > 0 && (
        <ol aria-label={t.stagesLabel} className="mt-5 grid gap-2 text-sm sm:grid-cols-2">
          {stages.map((stage, index) => {
            const done = index < current;
            const active = index === current;
            return (
              <li
                key={stage}
                aria-current={active ? "step" : undefined}
                className={`flex items-center gap-2 rounded-sm border px-3 py-2 ${
                  active ? "border-seeker bg-paper font-bold" : done ? "border-ink/20 text-ink/70" : "border-ink/10 text-ink/45"
                }`}
              >
                <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${active ? "bg-seeker" : done ? "bg-ink/60" : "bg-ink/15"}`} />
                <span className="min-w-0 flex-1">{t.stageLabels[stage]}</span>
                {active && stage === "reading" && total !== null && (
                  <span className="tabular-nums">{t.postsRead(progress?.posts_read ?? 0, total)}</span>
                )}
                <span className="sr-only">{done ? t.stageDone : active ? t.stageCurrent : ""}</span>
              </li>
            );
          })}
        </ol>
      )}
    </DiagnoseLoading>
  );
}
