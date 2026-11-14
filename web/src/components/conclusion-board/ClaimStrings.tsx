"use client";

import { useEffect, useRef, useState } from "react";

import { staggerDelay } from "@/lib/motion";
import type { Post } from "@/types/post";
import type { ProfileEvidence, ProfileEvidencePath } from "@/types/profile";

import "./claim-strings.css";

/** 投稿のカードに出す本文の長さ */
const EXCERPT = 40;
/** 画面に入ってから最初の糸が伸び始めるまで（秒） */
const START = 0.2;
/** 糸 1 本が伸びる長さ（秒。claim-strings.css と同じ） */
const DRAW = 0.5;
/** 答えの箱が弾む長さ（秒。claim-strings.css と同じ） */
const BOUNCE = 0.6;

/** 道筋の起点にする投稿の根拠。本人との関係が書かれた本文（post_text）を先に、なければ投稿を指す根拠 */
function anchorOf(evidence: readonly ProfileEvidence[]): ProfileEvidence | undefined {
  return evidence.find((e) => e.post_id && e.source === "post_text") ?? evidence.find((e) => e.post_id);
}

function excerpt(text: string): string {
  const chars = [...text];
  return chars.length > EXCERPT ? `${chars.slice(0, EXCERPT).join("")}…` : text;
}

/** 赤い糸に使う推定の部分。ProfileItem と、候補の一覧の ProfileCandidate のどちらも渡せる */
type StringClaim = {
  readonly value: string | null;
  readonly evidence_paths?: readonly ProfileEvidencePath[];
};

/** 道筋ごとの起点の投稿。同じ投稿が2つの道筋の起点になるときは1枚にまとめる */
function anchorPosts(claim: StringClaim, posts: readonly Post[]): Post[] {
  const byId = new Map(posts.map((p) => [p.post_id, p]));
  const anchors = (claim.evidence_paths ?? []).flatMap((path) => {
    const post = byId.get(anchorOf(path.evidence)?.post_id ?? "");
    return post ? [post] : [];
  });
  return [...new Map(anchors.map((p) => [p.post_id, p])).values()];
}

/**
 * プロフィールの推定で、根拠の道筋が2つ以上あるとき、それぞれの道筋の投稿のカードから答えへ赤い糸を順に伸ばし、
 * 最後に答えの箱が弾むように出る。根拠は profile_claims の候補の evidence_paths だけを使う。道筋が1つなら何も出さない。
 * 結果の下の方にあるので、画面に入るまで動きを止めておく（止まっている間は糸がない状態）。
 * 動きを減らす設定では、張り終わった糸と答えを最初から見せる。
 */
export function ClaimStrings({ claim, posts }: { claim: StringClaim; posts: readonly Post[] }) {
  const ref = useRef<HTMLElement>(null);
  const [inView, setInView] = useState(false);
  const anchors = claim.value ? anchorPosts(claim, posts) : [];
  const shown = anchors.length >= 2;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      // 見えているかを調べられないブラウザでは、すぐに動かす
      const id = requestAnimationFrame(() => setInView(true));
      return () => cancelAnimationFrame(id);
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setInView(true);
        observer.disconnect();
      }
    }, { threshold: 0.6 });
    observer.observe(el);
    return () => observer.disconnect();
  }, [shown]);

  if (!shown || !claim.value) return null;
  const n = anchors.length;
  const delays = anchors.map((_, i) => START + staggerDelay(i, n, { duration: DRAW, total: 2 - BOUNCE }));
  const answerAt = delays[n - 1] + DRAW;

  return (
    <figure
      ref={ref}
      aria-label={`別々の ${n} つの道筋が、同じ答え「${claim.value}」を指す`}
      className={`claim-strings mt-3 ${inView ? "in-view" : ""}`}
    >
      <ol className="grid gap-2" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
        {anchors.map((post) => (
          <li
            key={post.post_id}
            className="evidence-pin rounded-sm border border-ink/20 bg-paper px-2 py-1.5 text-xs leading-snug text-ink/80"
          >
            {excerpt(post.text)}
          </li>
        ))}
      </ol>
      <svg aria-hidden="true" viewBox="0 0 100 100" preserveAspectRatio="none" className="block h-14 w-full overflow-visible">
        {anchors.map((post, i) => {
          const x = ((i + 0.5) / n) * 100;
          return (
            <path
              key={post.post_id}
              d={`M ${x} 0 C ${x} 55, 50 45, 50 100`}
              className="claim-string"
              style={{ animationDelay: `${delays[i].toFixed(2)}s` }}
            />
          );
        })}
      </svg>
      <p className="text-center">
        <span
          className="claim-answer inline-block border-2 border-seeker bg-paper-deep px-4 py-1 text-xl font-bold text-seeker"
          style={{ animationDelay: `${answerAt.toFixed(2)}s` }}
        >
          {claim.value}
        </span>
      </p>
    </figure>
  );
}
