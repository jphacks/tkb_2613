"use client";

import { useEffect, useState } from "react";

import { CLUE_LABELS } from "@/lib/clueLabels";
import type { Clue } from "@/types/clue";
import type { Post } from "@/types/post";
import { PROFILE_ATTRIBUTE_CATALOG, profileCandidateAfterDeletion, profileRelationsAfterDeletion, type ProfileCandidate, type ProfileCandidateSet, type ProfileEvidence, type ProfileEvidencePath, type ProfileRelation, type WebFact } from "@/types/profile";

interface ProfileClaimWhatIfProps {
  claims: readonly ProfileCandidateSet[];
  relations?: readonly ProfileRelation[];
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

function evidencePathLabel(path: ProfileEvidencePath): string {
  if (path.provenance === "direct_disclosure") return "自分で直接公開";
  if (path.provenance === "combined_inference") {
    return path.evidence.some((reference) => reference.source === "public_web")
      ? "投稿と公開Webから推定"
      : "投稿の組み合わせから推定";
  }
  return "根拠経路未分類";
}

function provenanceLabels(candidate: ProfileCandidate): readonly string[] {
  return [...new Set(candidate.evidence_paths.map(evidencePathLabel))];
}

function postText(post: Post | undefined): string {
  const text = post?.text.trim() || "本文なし";
  return text.length > 72 ? `${text.slice(0, 72)}…` : text;
}

function profileAttributeLabel(set: ProfileCandidateSet, nowMs: number): string {
  if (set.attribute !== "realtime_location") return PROFILE_ATTRIBUTE_CATALOG[set.attribute].label;
  if (nowMs === 0) return "投稿時点の位置候補";
  const allRecent = set.candidates.length > 0 && set.candidates.every((candidate) => {
    const observedAt = candidate.observed_at ? Date.parse(candidate.observed_at) : Number.NaN;
    const ageMs = nowMs - observedAt;
    return ageMs >= 0 && ageMs <= 15 * 60_000;
  });
  return allRecent ? "直近15分以内の投稿時点の位置候補" : "投稿時点の位置候補";
}

/** Recalculate the full grounded candidate pool from existing evidence paths. No new inference is run. */
export function ProfileClaimWhatIf({ claims, relations = [], clues, posts, suggestions, webFacts }: ProfileClaimWhatIfProps) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set(suggestions));
  const [nowMs, setNowMs] = useState(0);
  const hasTimedLocationCandidate = claims.some((set) =>
    set.attribute === "realtime_location" && set.candidate_pool.some((candidate) => candidate.observed_at),
  );
  useEffect(() => {
    if (!hasTimedLocationCandidate) return;
    const initialTimer = window.setTimeout(() => setNowMs(Date.now()), 0);
    const timer = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(timer);
    };
  }, [hasTimedLocationCandidate]);
  const postById = new Map(posts.map((post) => [post.post_id, post]));
  const evidencePostIds = [...new Set(claims.flatMap((claimSet) =>
    claimSet.candidate_pool.flatMap((candidate) => candidate.evidence_paths.flatMap((path) =>
      path.evidence.map((reference) => reference.post_id).filter((id): id is string => id !== null),
    )),
  ))].filter((postId) => postById.has(postId));
  const validSuggestions = suggestions.filter((postId) => evidencePostIds.includes(postId));
  const otherEvidencePosts = evidencePostIds.filter((postId) => !validSuggestions.includes(postId));
  const postNumbers = new Map(posts.map((post, index) => [post.post_id, index + 1]));
  if (evidencePostIds.length === 0) return null;

  const deleted = selected;
  const comparableClaims = claims.filter((claimSet) =>
    (claimSet.status === "candidate" || claimSet.status === "ambiguous") &&
    claimSet.candidate_pool.length > 0,
  );
  const after = comparableClaims.map((claimSet) => profileCandidateAfterDeletion(claimSet, deleted));
  const survivingAttributes = new Set(after.filter((set) => set.candidates.length > 0).map((set) => set.attribute));
  const broken = comparableClaims.filter((set) => !survivingAttributes.has(set.attribute));
  const survivingRelations = profileRelationsAfterDeletion(relations, deleted, claims);
  const remainingPieces = broken.flatMap((claimSet) => claimSet.candidates.flatMap((candidate) =>
    candidate.evidence_paths.flatMap((path) => path.evidence)
      .filter((reference) => reference.post_id === null || !deleted.has(reference.post_id))
      .map((reference) => ({ claimSet, candidate, reference })),
  ));
  const uniquePieces = [...new Map(remainingPieces.map((piece) => [
    `${piece.claimSet.attribute}:${piece.candidate.value}:${evidenceKey(piece.reference)}`, piece,
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
      <span className="min-w-0"><span className="block font-bold">投稿 {number}{suggested ? " ・候補" : ""}</span>
        <span className="break-words">{postText(post)}</span>
      </span>
    </label>;
  }

  return (
    <section aria-labelledby="profile-what-if-heading" className="mt-5 space-y-4 rounded-sm border-2 border-seeker/50 bg-paper px-4 py-4">
      <div>
        <h4 id="profile-what-if-heading" className="font-display text-xl">候補を仮に外して比べる</h4>
        <p className="mt-1 text-sm text-ink/70">保存済みの全候補の根拠経路を再評価し、候補の順位と件数を更新します。新しい投稿や根拠は加えません。候補がなくなっても安全の確認にはなりません。</p>
      </div>
      <fieldset className="space-y-2">
        <legend className="font-bold">仮に外す投稿を選ぶ（最大3件）</legend>
        {validSuggestions.length === 0 && <p className="text-sm text-ink/70">現在の候補には3件以内で候補を崩す組合せがありません。別の根拠投稿を選んで比較できます。</p>}
        {validSuggestions.map((postId) => postChoice(postId, true))}
        {otherEvidencePosts.length > 0 && <details className="rounded border border-ink/20 px-3 py-2">
          <summary className="cursor-pointer font-bold">ほかの根拠投稿 ({otherEvidencePosts.length})</summary>
          <ul className="mt-2 space-y-2">{otherEvidencePosts.map((postId) => <li key={postId}>{postChoice(postId, false)}</li>)}</ul>
        </details>}
      </fieldset>
      {relations.length > 0 && <section aria-label="仮除外後に残る関係" className="rounded border border-ink/20 p-3">
        <h5 className="font-bold">仮除外後に残る関係 ({survivingRelations.length})</h5>
        {survivingRelations.length === 0 ? <p className="mt-1 text-sm text-ink/70">選んだ投稿を含まない完全な関係根拠は残りません。</p> :
          <ul className="mt-1 list-disc pl-5 text-sm">{survivingRelations.map((relation, index) =>
            <li key={`${relation.kind}:${index}`}>
              {relation.left.kind === "profile_candidate" ? PROFILE_ATTRIBUTE_CATALOG[relation.left.attribute].label : "投稿中の通勤・通学先"}：{relation.left.value}
              {" → "}
              {relation.right.kind === "profile_candidate" ? PROFILE_ATTRIBUTE_CATALOG[relation.right.attribute].label : "投稿中の通勤・通学先"}：{relation.right.value}
            </li>,
          )}</ul>}
      </section>}
      <div className="grid gap-4 sm:grid-cols-2">
        <section aria-label="仮除外後も根拠経路が残る候補" className="space-y-2">
          <h5 className="font-bold">仮除外後も支持される候補 ({after.filter((set) => set.candidates.length > 0).length})</h5>
          {after.every((set) => set.candidates.length === 0) ? <p className="text-sm text-ink/70">残る完全な根拠経路はありません。</p> : after.filter((set) => set.candidates.length > 0).map((set) => {
            const before = claims.find((claimSet) => claimSet.attribute === set.attribute);
            const rankChanges = set.candidates.flatMap((candidate) => {
              const prior = before?.candidate_pool.find((item) => item.value === candidate.value);
              return prior && prior.rank !== candidate.rank
                ? [`${candidate.value}：#${prior.rank} → #${candidate.rank}`]
                : prior ? [] : [`${candidate.value}：新しい候補 #${candidate.rank}`];
            });
            return <article key={set.attribute} className="rounded border border-ink/20 p-3 text-sm">
              <p className="font-bold">{profileAttributeLabel(set, nowMs)}：{set.candidates.map((candidate) => candidate.value).join(" / ")}</p>
              {set.attribute === "regular_station" && <p className="mt-1 text-xs text-ink/70">投稿時点の習慣候補です。現在も同じ駅を利用している保証はありません。</p>}
              {set.candidates.map((candidate) => <p key={`provenance-${candidate.value}`} className="mt-1 text-xs text-ink/70">
                {candidate.value} の根拠経路：{provenanceLabels(candidate).join("・")}
              </p>)}
              {set.status === "ambiguous" && <p className="mt-1 text-xs text-ink/70">同程度に支持される候補が複数あります。</p>}
              <p className="mt-1 text-xs text-ink/70">表示候補数：{before?.candidates.length ?? 0} → {set.candidates.length} 件（根拠のある候補全体：{before?.candidate_pool.length ?? 0} → {set.candidate_pool.length} 件）</p>
              {rankChanges.length > 0 && <p className="mt-1 text-xs text-ink/70">順位の変化：{rankChanges.join("、")}</p>}
              {set.candidates.map((candidate) => (
                <details key={`details-${candidate.value}`} className="mt-2 text-sm">
                  <summary className="cursor-pointer font-bold">候補順位 #{candidate.rank} ・ 根拠スコア {candidate.confidence.toFixed(2)}（正しさの確率ではありません）の根拠を確認</summary>
                  {candidate.evidence_paths.slice(0, 1).map((path) => (
                    <div key="example-path" className="mt-2">
                      <p className="text-xs font-bold">残る根拠経路の例：{evidencePathLabel(path)}</p>
                      <ul aria-label="残る根拠経路の例" className="mt-1 list-disc pl-5 text-xs">
                        {path.evidence.map((reference) => <li key={evidenceKey(reference)}>{evidenceLabel(reference, clues, webFacts)}{reference.post_id ? `（投稿 ${postNumbers.get(reference.post_id) ?? "?"}）` : ""}</li>)}
                      </ul>
                    </div>
                  ))}
                  {candidate.counter_evidence.length > 0 && <div className="mt-2">
                    <p className="text-xs font-bold">この候補への反対根拠（{candidate.counter_evidence.length}）</p>
                    <ul className="mt-1 list-disc pl-5 text-xs">
                      {candidate.counter_evidence.map((reference) => <li key={evidenceKey(reference)}>{evidenceLabel(reference, clues, webFacts)}{reference.post_id ? `（投稿 ${postNumbers.get(reference.post_id) ?? "?"}）` : ""}</li>)}
                    </ul>
                  </div>}
                </details>
              ))}
              {set.conflicting_evidence.length > 0 && <div className="mt-2">
                <p className="text-xs font-bold">項目全体の矛盾根拠（{set.conflicting_evidence.length}）</p>
                <ul className="mt-1 list-disc pl-5 text-xs">
                  {set.conflicting_evidence.map((reference) => <li key={evidenceKey(reference)}>{evidenceLabel(reference, clues, webFacts)}{reference.post_id ? `（投稿 ${postNumbers.get(reference.post_id) ?? "?"}）` : ""}</li>)}
                </ul>
              </div>}
            </article>;
          })}
        </section>
        <section aria-label="仮除外で支持されなくなる候補" className="space-y-2">
          <h5 className="font-bold">完全な根拠経路がなくなる候補 ({broken.length})</h5>
          {broken.length === 0 ? <p className="text-sm text-ink/70">選んだ投稿を仮に外しても、既知の経路は残ります。</p> : broken.map((set) => {
            const afterSet = after.find((candidateSet) => candidateSet.attribute === set.attribute);
            return <article key={set.attribute} className="rounded border border-ink/20 p-3 text-sm">
              <p className="font-bold">{profileAttributeLabel(set, nowMs)}：{set.candidates.map((candidate) => candidate.value).join(" / ")}</p>
              {set.candidates.map((candidate) => <p key={`provenance-${candidate.value}`} className="mt-1 text-xs text-ink/70">
                {candidate.value} の根拠経路：{provenanceLabels(candidate).join("・")}
              </p>)}
              <p className="mt-1 text-xs">仮除外後：不明。選んだ投稿を含まない完全な根拠経路は残りません。</p>
              <p className="mt-1 text-xs text-ink/70">表示候補数：{set.candidates.length} → {afterSet?.candidates.length ?? 0} 件（根拠のある候補全体：{set.candidate_pool.length} → {afterSet?.candidate_pool.length ?? 0} 件）</p>
              <p className="mt-1 text-xs text-ink/70">順位の変化：根拠を失った候補は表示対象から外れました。</p>
            </article>;
          })}
          {uniquePieces.length > 0 && (
            <div className="rounded border border-ink/20 p-3 text-sm">
              <p className="font-bold">残る個別の根拠</p>
              <p className="text-xs text-ink/70">これらは一部の根拠で、単独では候補を支えません。</p>
              <ul className="mt-2 list-disc pl-5 text-xs">
                {uniquePieces.slice(0, 8).map(({ claimSet, candidate, reference }) => <li key={`${claimSet.attribute}:${candidate.value}:${evidenceKey(reference)}`}>
                  {profileAttributeLabel(claimSet, nowMs)}（{candidate.value}）：{evidenceLabel(reference, clues, webFacts)}{reference.post_id ? `（投稿 ${postNumbers.get(reference.post_id) ?? "?"}）` : ""}
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
