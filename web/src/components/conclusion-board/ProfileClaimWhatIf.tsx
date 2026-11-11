"use client";

import { useState } from "react";

import { CLUE_LABELS } from "@/lib/clueLabels";
import type { Clue } from "@/types/clue";
import type { Post } from "@/types/post";
import { PROFILE_ATTRIBUTE_CATALOG, profileClaimAfterDeletion, type ProfileEvidence, type ProfileItem, type WebFact } from "@/types/profile";

interface ProfileClaimWhatIfProps {
  claims: readonly ProfileItem[];
  clues: readonly Clue[];
  posts: readonly Post[];
  suggestions: readonly string[];
  webFacts: readonly WebFact[];
}

function evidenceLabel(reference: ProfileEvidence, clues: readonly Clue[], webFacts: readonly WebFact[]): string {
  if (reference.source === "public_web") {
    return webFacts.find((fact) => fact.id === reference.web_fact_id)?.excerpt ?? "公開Webの根拠";
  }
  if (reference.clue_index !== null && reference.clue_index !== undefined) {
    const clue = clues[reference.clue_index];
    if (clue) return `${CLUE_LABELS[clue.type]}：${clue.value}`;
  }
  return reference.excerpt ?? (reference.source === "profile_text" ? "プロフィール文" : "投稿本文");
}

function evidenceKey(reference: ProfileEvidence): string {
  return [reference.post_id, reference.clue_index, reference.source, reference.excerpt, reference.web_fact_id].join(":");
}

function postText(post: Post | undefined): string {
  const text = post?.text.trim() || "本文なし";
  return text.length > 72 ? `${text.slice(0, 72)}…` : text;
}

/** Compare only already diagnosed evidence paths. This component never reruns inference. */
export function ProfileClaimWhatIf({ claims, clues, posts, suggestions, webFacts }: ProfileClaimWhatIfProps) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set(suggestions));
  const postById = new Map(posts.map((post) => [post.post_id, post]));
  const evidencePostIds = [...new Set(claims.flatMap((claim) =>
    (claim.evidence_paths ?? []).flatMap((path) => path.evidence.map((reference) => reference.post_id).filter((id): id is string => id !== null)),
  ))].filter((postId) => postById.has(postId));
  const validSuggestions = suggestions.filter((postId) => evidencePostIds.includes(postId));
  const otherEvidencePosts = evidencePostIds.filter((postId) => !validSuggestions.includes(postId));
  const postNumbers = new Map(posts.map((post, index) => [post.post_id, index + 1]));
  if (claims.length === 0 || evidencePostIds.length === 0) return null;

  const deleted = selected;
  const comparableClaims = claims.filter((claim) => claim.status !== "unknown" && (claim.evidence_paths?.length ?? 0) > 0);
  const notCompared = claims.filter((claim) => !comparableClaims.includes(claim));
  const after = comparableClaims.flatMap((claim) => {
    const recalculated = profileClaimAfterDeletion(claim, deleted);
    return recalculated ? [recalculated] : [];
  });
  const survivingAttributes = new Set(after.map((claim) => claim.attribute));
  const broken = comparableClaims.filter((claim) => !survivingAttributes.has(claim.attribute));
  const remainingPieces = broken.flatMap((claim) =>
    (claim.evidence_paths ?? []).flatMap((path) => path.evidence)
      .filter((reference) => reference.post_id === null || !deleted.has(reference.post_id))
      .map((reference) => ({ claim, reference })),
  );
  const uniquePieces = [...new Map(remainingPieces.map((piece) => [
    `${piece.claim.attribute}:${evidenceKey(piece.reference)}`, piece,
  ])).values()];
  function toggle(postId: string) {
    setSelected((previous) => {
      if (!previous.has(postId) && previous.size >= 3) return previous;
      const next = new Set(previous);
      if (next.has(postId)) next.delete(postId);
      else next.add(postId);
      return next;
    });
  }

  function postChoice(postId: string, suggested: boolean) {
    const post = postById.get(postId);
    const number = postNumbers.get(postId);
    return <label key={postId} className="flex items-start gap-2 break-words rounded border border-ink/20 p-2 text-sm">
      <input type="checkbox" checked={selected.has(postId)} disabled={!selected.has(postId) && selected.size >= 3} onChange={() => toggle(postId)} />
      <span className="min-w-0"><span className="block font-bold">投稿 {number}{suggested ? "（消す候補）" : ""}</span>
        <span className="break-words">{postText(post)}</span>
      </span>
    </label>;
  }

  return (
    <section aria-labelledby="profile-what-if-heading" className="mt-5 space-y-4 rounded-sm border-2 border-seeker/50 bg-paper px-4 py-4">
      <div>
        <h4 id="profile-what-if-heading" className="font-display text-xl">投稿を仮に外して比べる</h4>
        <p className="mt-1 text-sm text-ink/70">選んだ投稿が無かったら、それぞれの推定に根拠が残るかを見ます。診断で見つけた根拠の組み合わせだけで比べるので、ここで推定が消えても、ほかの方法で推定されないとは限りません。</p>
      </div>
      <fieldset className="space-y-2">
        <legend className="font-bold">外してみる投稿を選ぶ（3件まで）</legend>
        {validSuggestions.length === 0 && <p className="text-sm text-ink/70">3件以内で推定が崩れる組み合わせは見つかりませんでした。「ほかの根拠の投稿」から選んで比べられます。</p>}
        {validSuggestions.map((postId) => postChoice(postId, true))}
        {otherEvidencePosts.length > 0 && <details className="rounded border border-ink/20 px-3 py-2">
          <summary className="cursor-pointer font-bold">ほかの根拠の投稿（{otherEvidencePosts.length} 件）</summary>
          <ul className="mt-2 space-y-2">{otherEvidencePosts.map((postId) => <li key={postId}>{postChoice(postId, false)}</li>)}</ul>
        </details>}
      </fieldset>
      <div className="grid gap-4 sm:grid-cols-2">
        <section aria-label="外しても根拠が残る推定" className="space-y-2">
          <h5 className="font-bold">外しても根拠が残る推定（{after.length}）</h5>
          {after.length === 0 ? <p className="text-sm text-ink/70">根拠が残る推定はありません。</p> : after.map((claim) => (
            <article key={claim.attribute} className="rounded border border-ink/20 p-3 text-sm">
              <p className="font-bold">{PROFILE_ATTRIBUTE_CATALOG[claim.attribute].label}：{claim.value}</p>
              <p className="mt-1 text-xs text-ink/70">残る根拠の組み合わせ：{claim.evidence_paths?.length ?? 0} 通り</p>
              {(claim.evidence_paths ?? []).slice(0, 1).map((path) => (
                <ul key="example-path" aria-label="残る根拠の例" className="mt-2 list-disc pl-5 text-xs">
                  {path.evidence.map((reference) => <li key={evidenceKey(reference)}>{evidenceLabel(reference, clues, webFacts)}{reference.post_id ? `（投稿 ${postNumbers.get(reference.post_id) ?? "?"}）` : ""}</li>)}
                </ul>
              ))}
            </article>
          ))}
          {notCompared.length > 0 && <p className="text-xs text-ink/60">根拠の組み合わせが記録されていない {notCompared.length} 件は、ここでは比べられません。</p>}
        </section>
        <section aria-label="外すと根拠がなくなる推定" className="space-y-2">
          <h5 className="font-bold">外すと根拠がなくなる推定（{broken.length}）</h5>
          {broken.length === 0 ? <p className="text-sm text-ink/70">選んだ投稿を外しても、どの推定にも根拠が残ります。</p> : broken.map((claim) => (
            <article key={claim.attribute} className="rounded border border-ink/20 p-3 text-sm">
              <p className="font-bold">{PROFILE_ATTRIBUTE_CATALOG[claim.attribute].label}：{claim.value}</p>
              <p className="mt-1 text-xs">選んだ投稿なしでは、この推定を支える根拠がそろいません。</p>
            </article>
          ))}
          {uniquePieces.length > 0 && (
            <div className="rounded border border-ink/20 p-3 text-sm">
              <p className="font-bold">残っている根拠（これだけでは推定できないもの）</p>
              <p className="text-xs text-ink/70">推定に使った根拠の一部です。これだけでは上の推定は成り立ちません。</p>
              <ul className="mt-2 list-disc pl-5 text-xs">
                {uniquePieces.slice(0, 8).map(({ claim, reference }) => <li key={`${claim.attribute}:${evidenceKey(reference)}`}>
                  {PROFILE_ATTRIBUTE_CATALOG[claim.attribute].label}：{evidenceLabel(reference, clues, webFacts)}{reference.post_id ? `（投稿 ${postNumbers.get(reference.post_id) ?? "?"}）` : ""}
                </li>)}
              </ul>
              {uniquePieces.length > 8 && <p className="mt-1 text-xs text-ink/60">ほか {uniquePieces.length - 8} 件</p>}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
