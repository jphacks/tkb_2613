"use client";

import { useState } from "react";

import { CLUE_LABELS } from "@/lib/clueLabels";
import type { Clue, Region } from "@/types/clue";

interface ResultFrameProps {
  imageUrl: string;
  clues: readonly Clue[];
}

interface Size {
  width: number;
  height: number;
}

function toPercentBox([x1, y1, x2, y2]: Region, { width, height }: Size) {
  const pct = (n: number, total: number) => `${(n / total) * 100}%`;
  return { left: pct(x1, width), top: pct(y1, height), width: pct(x2 - x1, width), height: pct(y2 - y1, height) };
}

/** 結果表示の枠。写真の上に手がかりの位置を重ね、一覧を並べる。 */
export function ResultFrame({ imageUrl, clues }: ResultFrameProps) {
  const [size, setSize] = useState<Size | null>(null);

  return (
    <div className="grid gap-8 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <figure className="relative self-start overflow-hidden rounded-sm border border-ink/15 bg-paper-deep shadow-[6px_6px_0_var(--color-ink)]">
        {/* blob URL を表示するだけなので next/image は使わない */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imageUrl}
          alt="選んだ写真"
          className="block h-auto w-full"
          onLoad={(e) =>
            setSize({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })
          }
        />
        {size &&
          clues.map((clue, i) => (
            <span
              key={i}
              data-testid={`clue-region-${i}`}
              aria-hidden
              className="absolute border-2 border-seeker bg-seeker/15"
              style={toPercentBox(clue.region, size)}
            >
              <span className="absolute -top-6 left-0 bg-seeker px-1.5 text-xs font-bold text-paper">
                {i + 1}
              </span>
            </span>
          ))}
      </figure>

      {clues.length === 0 ? (
        <p className="text-ink/70">手がかりは見つかりませんでした</p>
      ) : (
        <ol aria-label="見つかった手がかり" className="space-y-3">
          {clues.map((clue, i) => (
            <li
              key={i}
              className="grid grid-cols-[2rem_1fr_auto] items-baseline gap-3 border-b border-dashed border-ink/25 pb-3"
            >
              <span className="font-display text-xl text-seeker">{i + 1}</span>
              <span>
                <span className="block text-xs tracking-widest text-ink/60">
                  {CLUE_LABELS[clue.type]}
                </span>
                <span className="text-lg font-bold">{clue.value}</span>
              </span>
              <span className="tabular-nums text-sm text-ink/70">
                {Math.round(clue.confidence * 100)}%
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
