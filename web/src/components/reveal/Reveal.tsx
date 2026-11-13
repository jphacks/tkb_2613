"use client";

import type { ReactNode } from "react";

import { messages } from "@/lib/messages";
import { paced, staggerDelay } from "@/lib/motion";
import { identityName, pickFace, pickSpotlight, type RevealItem } from "@/lib/reveal";
import { toPercentBox } from "@/lib/region";
import { useLoadedSize } from "@/lib/useLoadedSize";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import type { Post } from "@/types/post";

import { IdentityCard } from "./IdentityCard";
import "./redaction.css";

const t = messages.reveal;

/** 1 枚ごとに叩きつける間隔（秒）。身元カードの数字が止まってから始める */
const FIRST_DELAY = 1.6;
const STEP = 0.5;

/** 証拠のカードが叩きつけられる長さ（globals.css の .reveal-slam） */
const SLAM = 0.45;

/** 黒い帯がはがれる長さ（redaction.css の .redaction-bar） */
const PEEL = 0.6;

/** 身元カードに並べる強い手がかりの数 */
const MAX_HIGHLIGHTS = 4;

/** カードを少しずつ傾けて、机に投げ出したように見せる。毎回同じ角度になるよう番号で決める */
function tilt(i: number): string {
  return `${[-3, 2.5, -1.5, 3.5, -2.5, 1.5, -3.5, 2][i % 8]}deg`;
}

/** 本文の中の手がかりの位置。見つからなければ -1（写真の手がかりも -1） */
function textAt(item: RevealItem): number {
  return item.clue.image_index === null ? item.post.text.indexOf(item.clue.value) : -1;
}

/**
 * 黒い帯をはがす遅れ（秒）。証拠のカードがすべて叩きつけられてから、本文に手がかりのあるカードを上から順にはがす。
 * 一度に動くのは帯だけにし、ずらしは 1 枚 0.4 秒前後で全体を 2 秒以内に収める。
 */
function peelDelays(items: readonly RevealItem[]): Map<number, number> {
  const landed = FIRST_DELAY + (items.length - 1) * STEP + SLAM;
  const peeled = items.filter((item) => textAt(item) >= 0);
  return new Map(
    peeled.map((item, k) => [item.clueIndex, landed + staggerDelay(k, peeled.length, { duration: PEEL })]),
  );
}

/** 写真全体に手がかりの位置を示す。 */
function PhotoEvidence({ item, label, peelAt }: { item: RevealItem; label: string; peelAt?: number }) {
  const { image, clue } = item;
  const loaded = useLoadedSize(image && clue.region ? image.url : null);
  if (!image || !clue.region || !loaded) return <TextEvidence item={item} label={label} peelAt={peelAt} />;
  return (
    <figure className="space-y-4">
      <p className="text-xs tracking-widest text-ink/60">{t.originalPhoto}</p>
      <div className="relative mx-auto w-full max-w-xl overflow-hidden bg-paper" style={{ aspectRatio: `${loaded.width} / ${loaded.height}` }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={image.url} alt={t.photoAlt(label, clue.value)} referrerPolicy="no-referrer" className="absolute inset-0 size-full" />
        <span aria-hidden="true" className="reveal-mark" style={toPercentBox(clue.region, loaded)} />
      </div>
      <figcaption>
        <span className="block text-xs tracking-widest text-ink/60">{label}</span>
        <span className="text-2xl font-bold break-words text-seeker">{clue.type === "face" ? t.faceObserved : clue.value}</span>
        {clue.type === "face" && <span className="ml-2 text-xs text-ink/60">{messages.identity.faceCaption}</span>}
      </figcaption>
    </figure>
  );
}

/**
 * 本文の手がかりは、投稿の本文の中で該当する言葉を黒い帯で隠しておき、カードが叩きつけられたあとに帯が
 * 右から左へ縮んで消え、言葉が赤くなる（redaction.css）。動きを減らす設定では、はがれた赤い言葉だけを見せる。
 * 写真が読めないときもここに来る
 */
function TextEvidence({ item, label, peelAt = 0 }: { item: RevealItem; label: string; peelAt?: number }) {
  const { clue, post } = item;
  const at = textAt(item);
  const delay = { animationDelay: paced(peelAt) };
  return (
    <div className="space-y-2">
      <span className="block text-xs tracking-widest text-ink/60">
        {label}
        {clue.image_index === null && <span className="ml-2">{t.fromText}</span>}
      </span>
      <p className="horror-title text-3xl leading-tight break-words">{clue.value}</p>
      {at >= 0 && (
        <blockquote className="border-l-2 border-ink/30 pl-3 text-sm text-ink/80">
          {post.text.slice(0, at)}
          <span className="redaction">
            <span className="redaction-word" style={delay}>
              {clue.value}
            </span>
            <span aria-hidden="true" className="redaction-bar" style={delay} />
          </span>
          {post.text.slice(at + clue.value.length)}
        </blockquote>
      )}
    </div>
  );
}

interface RevealProps {
  posts: readonly Post[];
  clues: readonly Clue[];
  conclusions: readonly Conclusion[];
  /** 身元カードのすぐ下に置くもの（消す投稿の要約）。推定が何もないときは、これだけを出す */
  children?: ReactNode;
}

/**
 * 診断が終わった瞬間に、画面の一番上で「ここまでわかった」を叩きつける。
 * 推定できたことを大きく出し、続けて証拠を 1 枚ずつ机に投げ出すように並べる。
 * 動きを減らす設定の人には、動きなしで並べて見せる（globals.css）。
 */
export function Reveal({ posts, clues, conclusions, children }: RevealProps) {
  const items = pickSpotlight(posts, clues, conclusions);
  if (items.length === 0 && conclusions.length === 0) return children ?? null;
  const postCount = new Set(clues.map((c) => c.post_id)).size;

  const identity = identityName(clues, conclusions);
  const peels = peelDelays(items);

  return (
    <section aria-labelledby="reveal-heading" className="reveal space-y-10">
      <div aria-hidden="true" className="found-flash" />
      <div>
        <h2 id="reveal-heading" className="horror-title reveal-heading text-4xl leading-tight sm:text-8xl">
          {t.heading}
        </h2>
        <p className="mt-3 text-ink/70">{t.count(clues.length, postCount)}</p>
      </div>

      <IdentityCard
        name={identity.name}
        face={pickFace(posts, clues)}
        conclusions={identity.rest}
        highlights={items
          .filter((item) => item.clue.type !== "name_text" && item.clue.type !== "face" && !item.used)
          .slice(0, MAX_HIGHLIGHTS)
          .map((item) => ({ label: messages.clues.typeLabels[item.clue.type], value: item.clue.value }))}
        clueCount={clues.length}
      />

      {children}

      {items.length > 0 && (
        <ul aria-label={t.evidenceLabel} className="grid grid-cols-1 gap-8">
          {items.map((item, i) => {
            const label = messages.clues.typeLabels[item.clue.type];
            return (
              <li
                key={item.clueIndex}
                className="reveal-slam evidence-pin relative bg-paper-deep p-4 shadow-[6px_6px_0_oklch(0%_0_0/0.5)]"
                style={{ animationDelay: paced(FIRST_DELAY + i * STEP), rotate: tilt(i) }}
              >
                {item.used && (
                  <span className="absolute -top-3 right-3 z-10 rotate-6 bg-seeker px-2 py-0.5 text-xs font-bold text-paper">
                    {t.used}
                  </span>
                )}
                {item.image ? (
                  <PhotoEvidence item={item} label={label} peelAt={peels.get(item.clueIndex)} />
                ) : (
                  <TextEvidence item={item} label={label} peelAt={peels.get(item.clueIndex)} />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
