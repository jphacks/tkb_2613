"use client";

import { useEffect, useRef, useState, type CSSProperties, type RefObject } from "react";

import { messages } from "@/lib/messages";
import { meshBounds, toLocalMeters } from "@/lib/mesh";
import { paced } from "@/lib/motion";
import type { Narrowing } from "@/types/narrowing";

import "./narrowing.css";

const t = messages.narrowing;

/** 段が切り替わる時刻（秒。発表モードでは --stage-pace 倍に伸びる） */
const ZOOM_AT = 1.0;
const WALK_AT = 1.2;
const BLOCK_AT = 2.4;
/** 生活圏の地図で、円のまわりに残す余白（半径の倍率）と、最小の大きさ（m） */
const MARGIN = 1.5;
const MIN_HALF = 400;
/** どれだけ見えたら演出を始めるか */
const VISIBLE_RATIO = 0.35;

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

interface Step {
  key: string;
  label: string;
  count: string;
  at: number;
}

/** 1都3県の世帯数は、県境のメッシュに隣の県の世帯が少し入るので10万世帯単位で切り捨てる */
export function regionCount(households: number): string {
  const man = Math.floor(households / 100_000) * 10;
  return t.manHouseholds(man.toLocaleString("ja-JP"));
}

export function narrowingSteps(narrowing: Narrowing): Step[] {
  const { region, walk, block } = narrowing;
  const steps: Step[] = [{ key: "region", label: t.region(region.label), count: regionCount(region.households), at: 0 }];
  if (walk) {
    steps.push({
      key: "walk",
      label: t.walk(walk.station, walk.radius_m, walk.minutes),
      count: t.households(walk.households.toLocaleString("ja-JP")),
      at: WALK_AT,
    });
  }
  if (block) {
    steps.push({ key: "block", label: `${t.block}：${block.value}`, count: t.oneBlock, at: walk ? BLOCK_AT : WALK_AT });
  }
  return steps;
}

/** 1都3県の全体図。正方形の中に、世帯のある範囲の外枠と、生活圏の位置の印を描く */
function RegionMap({ narrowing, walk }: { narrowing: Narrowing; walk: NonNullable<Narrowing["walk"]> }) {
  const [south, west, north, east] = narrowing.region.bounds;
  const local = toLocalMeters(walk.center);
  const [x1, y1] = local(north, west);
  const [x2, y2] = local(south, east);
  const side = Math.max(x2 - x1, y2 - y1);
  const left = (x1 + x2 - side) / 2;
  const top = (y1 + y2 - side) / 2;
  // 印（生活圏）の位置。ここに向かって寄っていく
  const origin = `${((-left / side) * 100).toFixed(2)}% ${((-top / side) * 100).toFixed(2)}%`;
  const dot = side / 60;
  return (
    <div className="narrowing-layer narrowing-region" style={{ transformOrigin: origin, animationDelay: paced(ZOOM_AT) }}>
      <svg viewBox={`${left} ${top} ${side} ${side}`} className="size-full" aria-hidden="true">
        <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} className="narrowing-region-outline" vectorEffect="non-scaling-stroke" />
        <rect x={-dot / 2} y={-dot / 2} width={dot} height={dot} className="text-seeker" fill="currentColor" />
      </svg>
    </div>
  );
}

/** 生活圏の地図。メッシュ番号から位置を計算したマスと、徒歩の円 */
function WalkMap({ walk, showBlock }: { walk: NonNullable<Narrowing["walk"]>; showBlock: boolean }) {
  const local = toLocalMeters(walk.center);
  const half = Math.max(walk.radius_m * MARGIN, MIN_HALF);
  const most = Math.max(1, ...walk.meshes.map((m) => m.households));
  const mark = half * 0.12;
  return (
    <div className="narrowing-layer narrowing-local" style={{ animationDelay: paced(ZOOM_AT) }}>
      <svg viewBox={`${-half} ${-half} ${2 * half} ${2 * half}`} className="size-full" aria-hidden="true">
        {walk.meshes.map((mesh) => {
          const [s, w, n, e] = meshBounds(mesh.code);
          const [x1, y1] = local(n, w);
          const [x2, y2] = local(s, e);
          return (
            <rect
              key={mesh.code}
              x={x1}
              y={y1}
              width={x2 - x1}
              height={y2 - y1}
              className="narrowing-mesh"
              style={{ fillOpacity: 0.12 + 0.5 * (mesh.households / most) } as CSSProperties}
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
        <circle r={walk.radius_m} className="narrowing-circle" vectorEffect="non-scaling-stroke" />
        <circle r={half / 70} className="text-ink" fill="currentColor" />
        {showBlock && (
          <rect
            x={-mark / 2}
            y={-mark / 2}
            width={mark}
            height={mark}
            className="narrowing-mark text-seeker"
            fill="currentColor"
            style={{ animationDelay: paced(BLOCK_AT) }}
          />
        )}
      </svg>
    </div>
  );
}

/**
 * 身元カードのあとに出す絞り込み。1都3県の世帯数 → 生活圏（徒歩の円）の世帯数 → 番地（1区画）の順に数え下げ、
 * 地図は1都3県の全体から、メッシュのマスで描いた生活圏へ寄っていく。
 * 止まった状態（動きを減らす設定の人に見せる状態）は、生活圏の地図に番地の印があり、すべての段が並んだ最後の状態。
 * 演出は画面に入ってから始める（narrowing.css の narrowing-playing）。
 */
export function NarrowingStages({ narrowing }: { narrowing: Narrowing | null }) {
  if (!narrowing) return null;
  return <Stages narrowing={narrowing} />;
}

function Stages({ narrowing }: { narrowing: Narrowing }) {
  // 身元カードより下にあるので、画面に入ってから演出を始める（それまでは最初の場面で止めておく）
  const [ref, playing] = usePlayWhenVisible<HTMLElement>();
  const steps = narrowingSteps(narrowing);
  const { walk } = narrowing;
  return (
    <figure
      ref={ref}
      aria-label={t.summary(steps.map((s) => `${s.label} ${s.count}`))}
      className={`narrowing space-y-6 border-y-2 border-ink py-6 ${playing ? "narrowing-playing" : ""}`}
    >
      <figcaption className="horror-title text-3xl sm:text-5xl">{t.heading}</figcaption>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] sm:items-center">
        {walk && (
          <div aria-hidden="true" className="narrowing-map relative mx-auto aspect-square w-full max-w-sm overflow-hidden bg-paper-deep">
            <RegionMap narrowing={narrowing} walk={walk} />
            <WalkMap walk={walk} showBlock={narrowing.block !== null} />
          </div>
        )}
        <ol aria-hidden="true" className="space-y-4">
          {steps.map((step, i) => {
            const next = steps[i + 1];
            return (
              <li key={step.key} className="narrowing-row" style={{ animationDelay: paced(step.at) }}>
                <span className="block text-sm tracking-widest text-ink/70">{step.label}</span>
                <span
                  className={`narrowing-count font-display text-4xl tabular-nums sm:text-5xl sm:whitespace-nowrap ${next ? "narrowing-past" : "text-seeker"}`}
                  style={next ? { animationDelay: paced(next.at) } : undefined}
                >
                  {step.count}
                  {next && <span className="narrowing-strike" style={{ animationDelay: paced(next.at) }} />}
                </span>
              </li>
            );
          })}
        </ol>
      </div>
      <p className="text-xs text-ink/60">
        {t.note}
        <span className="block">
          {t.sourcesLabel}：{narrowing.sources.join(" ／ ")}
        </span>
      </p>
    </figure>
  );
}
