import { messages } from "@/lib/messages";
import { staggerDelay } from "@/lib/motion";
import type { Conclusion } from "@/types/diagnose";

import "./escape-stamps.css";

/** 最後に弾むように出す一言 */
export const ESCAPED_MESSAGE = "もう、見つからない";
const UNKNOWN = "不明";

/** 判子を押し始めるまで（秒）。出た直後に一呼吸おく */
const START = 0.3;
/** 判子 1 つが押される長さ（秒。escape-stamps.css と同じ） */
const STAMP = 0.5;
/** 一言が弾む長さ（秒。escape-stamps.css と同じ） */
const BOUNCE = 0.6;

export interface BrokenInference {
  /** 項目の名前（「住んでいる町」など） */
  label: string;
  /** 消す前に推定できていた値 */
  value: string;
}

/** 崩れた項目（attribute）ごとに、捜査ボードと同じ項目名と、消す前に推定できていた値を並べる */
export function brokenInferences(before: readonly Conclusion[], lost: readonly string[]): BrokenInference[] {
  return lost.map((attribute) => ({
    label: messages.board.attributeLabels[attribute] ?? attribute,
    value: before.find((c) => c.attribute === attribute)?.value ?? "",
  }));
}

/** 推定できた項目の数（同じ項目に推定が2つあっても1と数える。「まーだだよ」の N → M と同じ数え方） */
export function countAttributes(conclusions: readonly Conclusion[]): number {
  return new Set(conclusions.map((c) => c.attribute)).size;
}

/** 消す前にあって、消したあとにない項目 */
export function lostAttributes(before: readonly Conclusion[], after: readonly Conclusion[]): string[] {
  const left = new Set(after.map((c) => c.attribute));
  return [...new Set(before.map((c) => c.attribute))].filter((a) => !left.has(a));
}

/**
 * 仮除外か削除で推定できた項目が減ったときの演出。崩れた推定に「不明」の判子を上から順に押して灰色にし、
 * 判子に合わせて推定できた項目の数を 1 つずつ減らし、最後に「もう、見つからない」が弾むように出る。
 * 減らなかったときは何も出さない（呼び出し側が今までの N → M を出す）。
 * 止まった状態（動きを減らす設定の人に見せる状態）は「判子が押され、数が減り、一言が出た」最後の状態にする。
 */
export function EscapeStamps({ before, after, broken }: { before: number; after: number; broken: readonly BrokenInference[] }) {
  if (after >= before || broken.length === 0) return null;
  const stamps = broken.map((_, i) => START + staggerDelay(i, broken.length, { duration: STAMP, total: 2 - BOUNCE }));
  const step = broken.length > 1 ? stamps[1] - stamps[0] : 0.4;
  const counts = Array.from({ length: before - after + 1 }, (_, i) => before - i);
  const messageAt = stamps[stamps.length - 1] + STAMP;

  return (
    <figure aria-label={messages.risky.countLabel(before, after)} className="space-y-4 border-y-2 border-ink py-4">
      <figcaption className="text-center text-sm tracking-widest text-ink/70">{messages.risky.countHeading}</figcaption>
      <p aria-hidden="true" className="text-center font-display text-6xl leading-none tabular-nums sm:text-7xl">
        <span>{before}</span>
        <span className="mx-3 text-ink/40 sm:mx-5">→</span>
        <span className="escape-count text-seeker">
          <span
            className="escape-count-strip"
            style={{
              transform: `translateY(${(-((counts.length - 1) / counts.length) * 100).toFixed(4)}%)`,
              animationDelay: `${stamps[0].toFixed(2)}s`,
              animationDuration: `${(step * (counts.length - 1)).toFixed(2)}s`,
              animationTimingFunction: `steps(${counts.length - 1}, start)`,
            }}
          >
            {counts.map((n) => (
              <span key={n}>{n}</span>
            ))}
          </span>
        </span>
      </p>
      <ul className="mx-auto max-w-md space-y-2">
        {broken.map((b, i) => (
          <li
            key={`${b.label}-${i}`}
            className="escape-row relative border-l-4 border-ink/30 bg-paper-deep/60 px-4 py-2 text-ink/50"
            style={{ animationDelay: `${stamps[i].toFixed(2)}s` }}
          >
            <span className="block text-xs tracking-widest">{b.label}</span>
            <span className="text-lg font-bold">{b.value}</span>
            <span className="escape-stamp" style={{ animationDelay: `${stamps[i].toFixed(2)}s` }}>
              {UNKNOWN}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-center">
        <span className="escape-message horror-title inline-block text-4xl sm:text-5xl" style={{ animationDelay: `${messageAt.toFixed(2)}s` }}>
          {ESCAPED_MESSAGE}
        </span>
      </p>
    </figure>
  );
}
