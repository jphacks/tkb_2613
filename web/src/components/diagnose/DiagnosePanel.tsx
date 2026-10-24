"use client";

import { useEffect, useRef, useState } from "react";

import { PostCard } from "@/components/post-list/PostCard";
import { useSession } from "@/components/session/SessionProvider";
import { ApiError, diagnose } from "@/lib/api";
import type { Post } from "@/types/post";

/**
 * 診断の状態。connecting は押してから最初のイベントが届くまで、reading は投稿が届いている間。
 * 手がかりやプロフィールのイベントを足すときは、ここに状態を足す。
 */
type Phase =
  | { kind: "idle" }
  | { kind: "connecting" }
  | { kind: "reading" }
  | { kind: "done"; postsSeen: number }
  | { kind: "error"; message: string };

function statusText(phase: Phase, postCount: number): string | null {
  switch (phase.kind) {
    case "connecting":
      return "特定班AIが投稿を取りに行っています…";
    case "reading":
      return `投稿を読んでいます…（${postCount} 件）`;
    case "done":
      return `${phase.postsSeen} 件の投稿を読みました`;
    default:
      return null;
  }
}

/**
 * 診断を始め、ログインした本人の投稿を届いた順に並べる。
 * 診断の結果は画面のメモリにだけ置き、保存しない。
 */
export function DiagnosePanel() {
  const { state: session } = useSession();
  const [posts, setPosts] = useState<readonly Post[]>([]);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const controller = useRef<AbortController | null>(null);

  // 画面を離れたら、読み込み中の診断を止める
  useEffect(() => () => controller.current?.abort(), []);

  if (session.status !== "authenticated") return null;

  async function start() {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setPosts([]);
    setPhase({ kind: "connecting" });
    try {
      for await (const event of diagnose({ signal: current.signal })) {
        if (event.event === "post") {
          setPosts((prev) => [...prev, event.post]);
          setPhase({ kind: "reading" });
        } else {
          setPhase({ kind: "done", postsSeen: event.posts_seen });
        }
      }
    } catch (e) {
      if (current.signal.aborted) return;
      setPhase({ kind: "error", message: e instanceof ApiError ? e.message : "診断できませんでした" });
    }
  }

  const busy = phase.kind === "connecting" || phase.kind === "reading";
  const status = statusText(phase, posts.length);

  // ログイン画面と同じ形：ボタンの文言は変えず、処理中は回る印を出し、状態とエラーはボタンの下に出す
  return (
    <section aria-labelledby="diagnose-heading" aria-busy={busy} className="mt-12 space-y-8">
      <div>
        <h2 id="diagnose-heading" className="sr-only">
          診断
        </h2>
        <button
          type="button"
          onClick={start}
          disabled={busy}
          className="inline-flex items-center gap-3 rounded-sm bg-seeker px-6 py-3 font-display text-lg text-paper shadow-[4px_4px_0_var(--color-ink)] transition-transform hover:-translate-y-0.5 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink active:translate-y-0.5 active:shadow-none disabled:cursor-not-allowed disabled:opacity-60 disabled:shadow-none"
        >
          {busy && (
            <span
              aria-hidden
              className="size-4 animate-spin rounded-full border-2 border-paper border-t-transparent motion-reduce:animate-none"
            />
          )}
          診断する
        </button>

        {status && (
          <p role="status" className="mt-4 text-ink/70">
            {status}
          </p>
        )}
        {phase.kind === "error" && (
          <p role="alert" className="mt-4 border-l-4 border-seeker bg-seeker/10 px-4 py-3">
            {phase.message}
          </p>
        )}
      </div>

      {posts.length > 0 && (
        <ol aria-label="読んだ投稿" className="max-w-2xl space-y-5">
          {posts.map((post) => (
            <li key={post.post_id}>
              <PostCard post={post} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
