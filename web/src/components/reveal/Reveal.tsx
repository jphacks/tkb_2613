"use client";

import { messages } from "@/lib/messages";
import { cropStyle, pickFace, pickName, pickReveal, type RevealItem } from "@/lib/reveal";
import { useLoadedSize } from "@/lib/useLoadedSize";
import type { Clue, ClueType } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import type { Post } from "@/types/post";

import { IdentityCard } from "./IdentityCard";

const t = messages.reveal;

/** 1 枚ごとに叩きつける間隔（秒）。身元カードの数字が止まってから始める */
const FIRST_DELAY = 1.6;
const STEP = 0.35;

/** 身元カードに並べる強い手がかりの数 */
const MAX_HIGHLIGHTS = 4;

/** 写真から出た手がかりでも、切り抜くより読み取った文字のほうがわかりやすい種類 */
const TEXT_ONLY_TYPES: ReadonlySet<ClueType> = new Set(["address_text"]);

/** カードを少しずつ傾けて、机に投げ出したように見せる。毎回同じ角度になるよう番号で決める */
function tilt(i: number): string {
  return `${[-3, 2.5, -1.5, 3.5, -2.5, 1.5, -3.5, 2][i % 8]}deg`;
}

/** 写真の手がかりの箇所を拡大して切り抜く。写真が読めるまでと読めなかったときは文字のカードにする */
function PhotoEvidence({ item, label }: { item: RevealItem; label: string }) {
  const { image, clue } = item;
  // 手がかりの位置は元の写真のピクセル座標なので、読み込んだ写真の実寸で切り抜く
  const size = useLoadedSize(image && clue.region ? image.url : null);
  if (!image || !clue.region || !size) return <TextEvidence item={item} label={label} />;
  const crop = cropStyle(clue.region, size);
  return (
    <figure className="space-y-2">
      <div className="relative overflow-hidden bg-paper" style={{ aspectRatio: crop.aspectRatio }}>
        {/* Bluesky の CDN の画像をそのまま表示するので next/image は使わない。読み込み済みなのですぐ出る */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={image.url}
          alt={t.photoAlt(label, clue.value)}
          referrerPolicy="no-referrer"
          className="absolute max-w-none"
          style={crop.image}
        />
        <span aria-hidden="true" className="reveal-mark" style={crop.mark} />
      </div>
      <figcaption>
        <span className="block text-xs tracking-widest text-ink/60">{label}</span>
        <span className="font-bold">{clue.value}</span>
      </figcaption>
    </figure>
  );
}

/** 本文の手がかりは、投稿の本文の中で該当する言葉に印を付ける。写真が読めないときもここに来る */
function TextEvidence({ item, label }: { item: RevealItem; label: string }) {
  const { clue, post } = item;
  const at = clue.image_index === null ? post.text.indexOf(clue.value) : -1;
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
          <mark className="bg-seeker/30 text-ink">{clue.value}</mark>
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
}

/**
 * 診断が終わった瞬間に、画面の一番上で「ここまでわかった」を叩きつける。
 * 推定できたことを大きく出し、続けて証拠を 1 枚ずつ机に投げ出すように並べる。
 * 動きを減らす設定の人には、動きなしで並べて見せる（globals.css）。
 */
export function Reveal({ posts, clues, conclusions }: RevealProps) {
  const items = pickReveal(posts, clues, conclusions);
  if (items.length === 0 && conclusions.length === 0) return null;
  const postCount = new Set(clues.map((c) => c.post_id)).size;

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
        name={pickName(clues)}
        face={pickFace(posts, clues)}
        conclusions={conclusions}
        highlights={items
          // 名前は大きく出し、推定の根拠は推定の行で見えるので、それ以外を並べる
          .filter((item) => item.clue.type !== "name_text" && !item.used)
          .slice(0, MAX_HIGHLIGHTS)
          .map((item) => ({ label: messages.clues.typeLabels[item.clue.type], value: item.clue.value }))}
        clueCount={clues.length}
      />

      {items.length > 0 && (
        <ul aria-label={t.evidenceLabel} className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          {items.map((item, i) => {
            const label = messages.clues.typeLabels[item.clue.type];
            return (
              <li
                key={item.clueIndex}
                className="reveal-slam evidence-pin relative bg-paper-deep p-4 shadow-[6px_6px_0_oklch(0%_0_0/0.5)]"
                style={{ animationDelay: `${FIRST_DELAY + i * STEP}s`, rotate: tilt(i) }}
              >
                {item.used && (
                  <span className="absolute -top-3 right-3 z-10 rotate-6 bg-seeker px-2 py-0.5 text-xs font-bold text-paper">
                    {t.used}
                  </span>
                )}
                {item.image && !TEXT_ONLY_TYPES.has(item.clue.type) ? (
                  <PhotoEvidence item={item} label={label} />
                ) : (
                  <TextEvidence item={item} label={label} />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
