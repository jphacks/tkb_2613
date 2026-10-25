"use client";

import { useEffect, useState } from "react";

import type { PostClues } from "@/components/post-list/PostCard";
import { SeekerEyes } from "@/components/seeker-eyes/SeekerEyes";
import { messages } from "@/lib/messages";
import type { Post } from "@/types/post";

const t = messages.loading;

/** 一言を切り替える間隔 */
const LINE_INTERVAL_MS = 3500;
/** 実況に残す行の数。多いと画面共有で読み切れない */
const FEED_SIZE = 5;
/** 実況に出す本文の長さ */
const SNIPPET_LENGTH = 24;

interface FeedLine {
  key: string;
  kind: "post" | "clue";
  text: string;
}

function snippet(post: Post): string {
  const text = post.text.replace(/\s+/g, " ").trim();
  if (!text) return t.photoPost(post.images.length);
  return text.length > SNIPPET_LENGTH ? `${text.slice(0, SNIPPET_LENGTH)}…` : text;
}

/**
 * 届いた順に実況の行を作る。投稿はすべて手がかりより先に届く（SSE の契約）ので、
 * 投稿の行を並べたあとに、手がかりが届いた順（found のキーの順）で「〇〇を見つけた」を並べる。
 */
function feedLines(posts: readonly Post[], found: Readonly<Record<string, PostClues>>): FeedLine[] {
  const postLines = posts.map((post) => ({
    key: `p:${post.post_id}`,
    kind: "post" as const,
    text: t.reading(snippet(post)),
  }));
  const clueLines = Object.entries(found).flatMap(([postId, { clues }]) =>
    [...new Set(clues.map((c) => c.type))].map((type) => ({
      key: `c:${postId}:${type}`,
      kind: "clue" as const,
      text: t.found(messages.clues.typeLabels[type]),
    })),
  );
  return [...postLines, ...clueLines];
}

/** 診断の間、数秒ごとに次の一言へ進む */
function useRotatingLine(lines: readonly string[], active: boolean): { index: number; line: string } {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setIndex((i) => (i + 1) % lines.length), LINE_INTERVAL_MS);
    return () => clearInterval(id);
  }, [lines.length, active]);
  return { index, line: lines[index] };
}

interface DiagnoseLoadingProps {
  /** 診断の間は true。false のときは状態の文言だけを出す */
  active: boolean;
  posts: readonly Post[];
  found: Readonly<Record<string, PostClues>>;
  /** いまの進み具合（DiagnosePanel の状態の文言） */
  status: string;
}

/**
 * 診断の状態の表示。診断の間は「もういいかい？」から始まる画面になり、投稿が1件ずつ読まれ、
 * 手がかりが見つかるたびに差し込まれる。怖さは言葉と流れで出し、点滅や大きな動きは使わない。
 *
 * 終わったあとも role="status" の要素は同じものを使い続ける（差し替えると読み上げられないことがあるため）。
 */
export function DiagnoseLoading({ active, posts, found, status }: DiagnoseLoadingProps) {
  const { index, line } = useRotatingLine(t.lines, active);

  return (
    <div
      className={
        active
          ? "mt-6 max-w-2xl rounded-sm border border-ink/15 bg-paper-deep/70 px-6 py-8 shadow-[6px_6px_0_oklch(5%_0.03_265)]"
          : "mt-4"
      }
    >
      {active && <p className="horror-title font-horror text-4xl sm:text-5xl">{t.calling}</p>}

      <p role="status" className={active ? "mt-6 flex items-center gap-3 text-lg" : "text-ink/70"}>
        {active && <SeekerEyes className="h-5 w-16 shrink-0" />}
        {status}
      </p>

      {active && (
        <LoadingProgress
          posts={posts.length}
          searched={Object.keys(found).length}
          line={line}
          lineKey={index}
          feed={feedLines(posts, found).slice(-FEED_SIZE).reverse()}
        />
      )}
    </div>
  );
}

interface LoadingProgressProps {
  posts: number;
  searched: number;
  line: string;
  lineKey: number;
  /** 新しい順 */
  feed: readonly FeedLine[];
}

/** 調べた割合のバー、切り替わる一言、実況 */
function LoadingProgress({ posts, searched, line, lineKey, feed }: LoadingProgressProps) {
  const ratio = posts > 0 ? searched / posts : 0;
  return (
    <>
      <div
        role="progressbar"
        aria-label={t.progressLabel}
        aria-valuemin={0}
        aria-valuemax={posts}
        aria-valuenow={searched}
        className="mt-5 h-2 overflow-hidden rounded-full bg-ink/10"
      >
        <div
          className="h-full origin-left bg-seeker transition-transform duration-500 ease-out"
          style={{ transform: `scaleX(${ratio})` }}
        />
      </div>

      {/* 同じ一言がくり返されるので読み上げない。進み具合は status が伝える */}
      <p aria-hidden key={lineKey} className="loading-line mt-5 min-h-6 text-ink/60">
        {line}
      </p>

      {feed.length > 0 && (
        <ol aria-label={t.feedLabel} className="mt-6 space-y-2 border-t border-ink/10 pt-5">
          {feed.map((item, i) => (
            <li
              key={item.key}
              className={`loading-line truncate ${item.kind === "clue" ? "text-seeker" : "text-ink/80"}`}
              style={{ opacity: 1 - i * 0.16 }}
            >
              {item.text}
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
