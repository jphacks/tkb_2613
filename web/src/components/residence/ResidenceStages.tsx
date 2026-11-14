"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

import { ResidenceMap } from "@/components/residence/ResidenceMap";
import { messages } from "@/lib/messages";
import { paced } from "@/lib/motion";
import { changedSteps, densestText, excerpt, formatPeople } from "@/lib/residence";
import type { Post } from "@/types/post";
import type { ResidenceEstimate } from "@/types/residence";

import "./residence.css";

const t = messages.residence;
/** 段と段の間（秒。発表モードでは --stage-pace 倍に伸びる） */
const STEP_GAP = 0.55;
const VISIBLE_RATIO = 0.3;

/** 画面に入ったら true（一度だけ）。IntersectionObserver がなければすぐ true */
function usePlayWhenVisible<T extends Element>(): [RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || playing) return;
    if (typeof IntersectionObserver === "undefined") {
      const frame = requestAnimationFrame(() => setPlaying(true));
      return () => cancelAnimationFrame(frame);
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setPlaying(true);
          observer.disconnect();
        }
      },
      { threshold: VISIBLE_RATIO },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [playing]);
  return [ref, playing];
}

function postText(posts: readonly Post[], postId: string | null): string | null {
  if (postId === null) return null;
  return excerpt(posts.find((p) => p.post_id === postId)?.text ?? "");
}

/**
 * 住まいの推定（点数の地図）。投稿を1件ずつ重ねるたびに 8割の範囲の人数が減っていく演出（f1 の代わり）、
 * 確率の地図、投稿ごとの影響の棒グラフ、使った仮定。
 * 止まった状態（動きを減らす設定の人に見せる状態）は、すべての段が並び、最後の人数が赤い状態。
 * 「確定」「特定した」とは言わず、「一番濃いのはここ」「8割の範囲は約○人」のように相対的に言う。
 */
export function ResidenceStages({ residence, posts }: { residence: ResidenceEstimate; posts: readonly Post[] }) {
  const [ref, playing] = usePlayWhenVisible<HTMLElement>();
  const steps = changedSteps(residence.steps);
  const { region } = residence;
  const regionText = t.region(formatPeople(region.people), residence.age_class);
  return (
    <figure
      ref={ref}
      aria-label={t.summary(`${t.densest}：${densestText(residence)}。${regionText}`)}
      className={`residence space-y-6 border-y-2 border-ink py-6 ${playing ? "residence-playing" : ""}`}
    >
      <figcaption className="space-y-2">
        <span className="horror-title block text-3xl sm:text-5xl">{t.heading}</span>
        <span className="block text-sm text-ink/70">{t.lead}</span>
      </figcaption>

      <ol aria-hidden="true" className="space-y-3">
        {steps.map((step, i) => {
          const next = steps[i + 1];
          const label = postText(posts, step.post_id) ?? t.start(residence.age_class);
          return (
            <li key={step.post_id ?? "start"} className="residence-row grid gap-x-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-baseline" style={{ animationDelay: paced(i * STEP_GAP) }}>
              <span className="text-sm tracking-wide text-ink/70">{label}</span>
              <span
                className={`residence-count font-display text-3xl tabular-nums sm:text-4xl ${next ? "residence-past" : "text-seeker"}`}
                style={next ? { animationDelay: paced((i + 1) * STEP_GAP) } : undefined}
              >
                {formatPeople(step.people)}
                {next && <span className="residence-strike" style={{ animationDelay: paced((i + 1) * STEP_GAP) }} />}
              </span>
            </li>
          );
        })}
      </ol>

      <div className="grid gap-6 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] sm:items-start">
        <ResidenceMap residence={residence} />
        <div className="space-y-4">
          <p className="residence-callout border-l-4 border-seeker pl-3">
            <span className="block text-sm font-bold text-seeker">{t.densest}</span>
            <span className="block text-xl font-bold">{densestText(residence)}</span>
            <span className="block">{regionText}</span>
            {region.same_birthday !== null && <span className="block text-sm">{t.birthday(formatPeople(region.same_birthday))}</span>}
          </p>
          <Influence residence={residence} posts={posts} />
        </div>
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer font-bold">{t.assumptions}</summary>
        <ol className="mt-2 list-decimal space-y-1 pl-6">
          {residence.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ol>
      </details>
      <p className="text-xs text-ink/60">
        {t.sourcesLabel}：{residence.sources.join(" ／ ")}
      </p>
    </figure>
  );
}

/** 投稿ごとの影響の棒グラフ。一番長いものが「消すべき1件」 */
function Influence({ residence, posts }: { residence: ResidenceEstimate; posts: readonly Post[] }) {
  const rows = residence.influence;
  if (rows.length === 0) return null;
  const longest = Math.max(1, ...rows.map((r) => r.delta));
  return (
    <section aria-label={t.influenceHeading} className="space-y-2">
      <h3 className="font-bold">{t.influenceHeading}</h3>
      <p className="text-xs text-ink/70">{t.influenceLead}</p>
      <ol className="space-y-2">
        {rows.map((row, i) => {
          const top = i === 0 && row.delta > 0;
          const width = row.delta > 0 ? Math.max(2, (row.delta / longest) * 100) : 0;
          return (
            <li key={row.post_id} className="text-sm">
              <span className="flex flex-wrap items-baseline gap-x-2">
                <span className="min-w-0 flex-1">{postText(posts, row.post_id)}</span>
                {top && <span className="residence-badge bg-seeker px-1.5 text-xs font-bold text-paper">{t.influenceTop}</span>}
                {row.contradiction && <span className="border border-ink px-1.5 text-xs">{t.contradiction}</span>}
                <span className="tabular-nums text-ink/70">{row.delta > 0 ? t.widens(formatPeople(row.delta)) : t.noChange}</span>
              </span>
              <span className="mt-1 block h-2 bg-ink/10" aria-hidden="true">
                <span className={`residence-bar block h-full ${top ? "bg-seeker" : "bg-ink"}`} style={{ width: `${width}%` }} />
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
