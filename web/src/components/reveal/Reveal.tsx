"use client";

import type { ReactNode } from "react";

import { messages } from "@/lib/messages";
import { postImageSrc } from "@/lib/post-image";
import { pickFace, pickSpotlight, validNameConclusions, type RevealItem } from "@/lib/reveal";
import { paced } from "@/lib/motion";
import { toPercentBox } from "@/lib/region";
import { useLoadedSize } from "@/lib/useLoadedSize";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import type { Post } from "@/types/post";
import type { ProfileCandidate, ProfileCandidateSet } from "@/types/profile";

import { IdentityCard } from "./IdentityCard";

const t = messages.reveal;

/** 1 枚ごとに叩きつける間隔（秒）。身元カードの数字が止まってから始める */
const FIRST_DELAY = 1.6;
const STEP = 0.5;

/** 身元カードに並べる強い手がかりの数 */
const MAX_HIGHLIGHTS = 4;

/** カードを少しずつ傾けて、机に投げ出したように見せる。毎回同じ角度になるよう番号で決める */
function tilt(i: number): string {
  return `${[-3, 2.5, -1.5, 3.5, -2.5, 1.5, -3.5, 2][i % 8]}deg`;
}

/** 写真全体に手がかりの位置を示す。 */
function PhotoEvidence({ item, label }: { item: RevealItem; label: string }) {
  const { image, clue } = item;
  const imageUrl = image ? postImageSrc(image) : null;
  const loaded = useLoadedSize(image && clue.region ? imageUrl : null);
  if (!image || !clue.region || !loaded) return <TextEvidence item={item} label={label} />;
  return (
    <figure className="space-y-4">
      <p className="text-xs tracking-widest text-ink/60">{t.originalPhoto}</p>
      <div className="relative mx-auto w-full max-w-xl overflow-hidden bg-paper" style={{ aspectRatio: `${loaded.width} / ${loaded.height}` }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={postImageSrc(image)} alt={t.photoAlt(label, clue.value)} referrerPolicy="no-referrer" className="absolute inset-0 size-full" />
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
  profileClaims?: readonly ProfileCandidateSet[];
  excludedPostIds?: ReadonlySet<string>;
  children?: ReactNode;
}

function profileName(profileClaims: readonly ProfileCandidateSet[]): { candidate: ProfileCandidate | null; provenance: string[]; ambiguous: boolean } {
  const fullNameSet = profileClaims.find((set) => set.attribute === "full_name");
  const fullNameCandidates = fullNameSet?.candidates ?? [];
  // An explicit full-name candidate takes priority over a shorter name, but an
  // ambiguous full-name set never gets collapsed to rank #1.
  const candidates = fullNameCandidates.length > 0
    ? fullNameCandidates
    : profileClaims.filter((set) => set.attribute === "given_name" || set.attribute === "nickname")
      .flatMap((set) => set.candidates);
  if (candidates.length !== 1) {
    return { candidate: null, provenance: [], ambiguous: candidates.length > 1 };
  }
  const candidate = candidates[0];
  const provenance = [...new Set(candidate.evidence_paths.map((path) => {
    if (path.provenance === "direct_disclosure") return "自分で直接公開";
    if (path.provenance === "combined_inference") {
      return path.evidence.some((reference) => reference.source === "public_web")
        ? "投稿と公開Webから推定"
        : "投稿の組み合わせから推定";
    }
    return "根拠経路未分類";
  }))];
  return { candidate, provenance, ambiguous: false };
}

/**
 * 診断が終わった瞬間に、画面の一番上で「ここまでわかった」を叩きつける。
 * 推定できたことを大きく出し、続けて証拠を 1 枚ずつ机に投げ出すように並べる。
 * 動きを減らす設定の人には、動きなしで並べて見せる（globals.css）。
 */
export function Reveal({ posts, clues, conclusions, profileClaims = [], excludedPostIds = new Set(), children }: RevealProps) {
  const items = pickSpotlight(posts, clues, conclusions, excludedPostIds, profileClaims);
  const identity = profileName(profileClaims);
  const profileInferences = conclusions.length > 0
    ? []
    : profileClaims
      .filter((set) => set.candidates.length > 0 && set.attribute !== "full_name" && set.attribute !== "given_name" && set.attribute !== "nickname")
      .map((set) => ({ attribute: set.attribute, value: set.candidates.map((candidate) => candidate.value).join(" / ") }));
  if (items.length === 0 && conclusions.length === 0 && profileInferences.length === 0 && !identity.candidate && !identity.ambiguous) {
    return children ?? null;
  }
  const visibleClues = clues.filter((clue) => !excludedPostIds.has(clue.post_id));
  const postCount = new Set(visibleClues.map((c) => c.post_id)).size;
  const otherConclusions = conclusions.length > 0
    ? validNameConclusions(conclusions).filter(
      (conclusion) => conclusion.attribute !== "full_name" && conclusion.attribute !== "given_name_or_nickname",
    )
    : profileInferences;

  return (
    <section aria-labelledby="reveal-heading" className="reveal space-y-10">
      <div aria-hidden="true" className="found-flash" />
      <div>
        <h2 id="reveal-heading" className="horror-title reveal-heading text-4xl leading-tight sm:text-8xl">
          {t.heading}
        </h2>
        <p className="mt-3 text-ink/70">{t.count(visibleClues.length, postCount)}</p>
      </div>

      <IdentityCard
        name={identity.candidate?.value ?? null}
        nameProvenance={identity.provenance}
        nameAmbiguous={identity.ambiguous}
        face={pickFace(posts, clues)}
        conclusions={otherConclusions}
        highlights={items
          .filter((item) => item.clue.type !== "name_text" && item.clue.type !== "face" && !item.used)
          .slice(0, MAX_HIGHLIGHTS)
          .map((item) => ({ label: messages.clues.typeLabels[item.clue.type], value: item.clue.value }))}
        clueCount={visibleClues.length}
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
