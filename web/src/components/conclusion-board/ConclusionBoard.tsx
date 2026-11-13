"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import { profileRelationsAfterDeletion, PROFILE_ATTRIBUTE_CATALOG, type ExternalLookupStatus, type ExternalProfileResult, type ProfileCandidateSet, type ProfileEvidence, type ProfileEvidencePath, type ProfileRelation, type WebFact } from "@/types/profile";
import type { Post } from "@/types/post";
import { ProfileClaimWhatIf } from "./ProfileClaimWhatIf";

const t = messages.board;

/** 糸のたるみ（px） */
const SAG = 28;

interface ConclusionBoardProps {
  clues: readonly Clue[];
  conclusions: readonly Conclusion[];
  /** 消したらどうなるかで推定できなくなった項目（attribute）。「不明」のカードで出す */
  unknown?: readonly string[];
  profileClaims?: readonly ProfileCandidateSet[];
  profileRelations?: readonly ProfileRelation[];
  deletedPostIds?: readonly string[];
  profileClaimSuggestions?: readonly string[];
  posts?: readonly Post[];
  webFacts?: readonly WebFact[];
  externalLookupStatus?: ExternalLookupStatus;
  externalProfileResults?: readonly ExternalProfileResult[];
  ownerProfileText?: string;
  selfReportClues?: readonly Clue[];
}

interface RedString {
  key: string;
  d: string;
}

function profileAttributeLabel(set: ProfileCandidateSet, nowMs: number): string {
  if (set.attribute !== "realtime_location") return PROFILE_ATTRIBUTE_CATALOG[set.attribute].label;
  if (nowMs === 0) return "投稿時点の位置候補";
  const allRecent = set.candidates.length > 0 && set.candidates.every((candidate) => {
    const timestamp = candidate.observed_at ? Date.parse(candidate.observed_at) : Number.NaN;
    const age = nowMs - timestamp;
    return age >= 0 && age <= 15 * 60_000;
  });
  return allRecent ? "直近15分以内の投稿時点の位置候補" : "投稿時点の位置候補";
}

function profileEvidenceKey(reference: ProfileEvidence): string {
  return [reference.post_id, reference.clue_index, reference.source, reference.excerpt, reference.web_fact_id].join(":");
}

function provenanceLabels(candidate: ProfileCandidateSet["candidates"][number]): readonly string[] {
  return [...new Set(candidate.evidence_paths.map(evidencePathLabel))];
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

function profileEvidenceLabel(reference: ProfileEvidence, clues: readonly Clue[], webFacts: readonly WebFact[]): string {
  if (reference.source === "public_web") {
    return webFacts.find((fact) => fact.id === reference.web_fact_id)?.excerpt ?? "公開Webの根拠";
  }
  if (reference.clue_index !== null && reference.clue_index !== undefined) {
    const clue = clues[reference.clue_index];
    if (clue) return `${messages.clues.typeLabels[clue.type]}：${clue.value}`;
  }
  return reference.excerpt ?? (reference.source === "profile_text" ? "プロフィール文" : "投稿本文");
}

/**
 * 証拠のカードの中心から、推定のカードの上端のすぐ内側へ、たるんだ糸を引く。
 * 糸はカードの後ろを通すので、端はカードに隠れて「留めてある」ように見える。
 * 1 つの推定に複数の糸が来るときは、上端に等間隔に並べる。
 */
function layoutStrings(
  board: HTMLElement,
  pins: ReadonlyMap<number, HTMLElement>,
  cards: ReadonlyMap<number, HTMLElement>,
  conclusions: readonly Conclusion[],
): RedString[] {
  const origin = board.getBoundingClientRect();
  return conclusions.flatMap((conclusion, ci) => {
    const card = cards.get(ci)?.getBoundingClientRect();
    if (!card) return [];
    const count = conclusion.clue_indices.length;
    return conclusion.clue_indices.flatMap((clueIndex, k) => {
      const pin = pins.get(clueIndex)?.getBoundingClientRect();
      if (!pin) return [];
      const x1 = pin.left + pin.width / 2 - origin.left;
      const y1 = pin.top + pin.height / 2 - origin.top;
      const x2 = card.left + (card.width * (k + 1)) / (count + 1) - origin.left;
      const y2 = card.top + 12 - origin.top;
      const d = `M ${x1} ${y1} Q ${(x1 + x2) / 2} ${(y1 + y2) / 2 + SAG} ${x2} ${y2}`;
      return [{ key: `${clueIndex}-${ci}`, d }];
    });
  });
}

/**
 * 捜査ボード。推定に使われた手がかりを「証拠」として留め、推定へ赤い糸を張る。
 * 推定には根拠の手がかりも文字で添える（糸は飾りなので読み上げない）。
 */
export function ConclusionBoard({
  clues, conclusions, unknown = [], profileClaims = [], profileRelations = [], deletedPostIds = [], profileClaimSuggestions = [], posts = [],
  webFacts = [], externalLookupStatus = "not_requested", externalProfileResults = [], ownerProfileText = "", selfReportClues = [],
}: ConclusionBoardProps) {
  // R8 copies observed name text directly. Its legacy Conclusion has no provenance
  // field, so it cannot safely be shown as an inference; profile candidate cards
  // are the provenance-labelled source for name results.
  const boardConclusions = useMemo(
    () => conclusions.filter(
      (conclusion) => conclusion.attribute !== "full_name" && conclusion.attribute !== "given_name_or_nickname",
    ),
    [conclusions],
  );
  const boardUnknown = unknown.filter(
    (attribute) => attribute !== "full_name" && attribute !== "given_name_or_nickname",
  );
  const boardRef = useRef<HTMLDivElement>(null);
  const pinRefs = useRef(new Map<number, HTMLElement>());
  const cardRefs = useRef(new Map<number, HTMLElement>());
  const [strings, setStrings] = useState<readonly RedString[]>([]);
  const [nowMs, setNowMs] = useState(0);
  const postNumbers = new Map(posts.map((post, index) => [post.post_id, index + 1]));
  const postDates = new Map(posts.map((post) => [post.post_id, post.created_at]));
  const hasTimedLocationCandidate = profileClaims.some((set) =>
    set.attribute === "realtime_location" && set.candidates.some((candidate) => candidate.observed_at),
  );
  const visibleProfileClaims = profileClaims.filter((set) => set.candidates.length > 0);
  const visibleRelations = profileRelationsAfterDeletion(profileRelations, new Set(deletedPostIds), profileClaims);

  useEffect(() => {
    setNowMs(Date.now());
    if (!hasTimedLocationCandidate) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, [hasTimedLocationCandidate]);

  // 消したらどうなるかで全部「不明」になっても、演出は出したままにする（出し直さない）
  const found = boardConclusions.length > 0 || boardUnknown.length > 0 || visibleProfileClaims.length > 0;
  const evidence = [...new Set(boardConclusions.flatMap((c) => c.clue_indices))].sort((a, b) => a - b);

  function profileEvidenceList(label: string, references: readonly ProfileEvidence[]) {
    const unique = [...new Map(references.map((reference) => [profileEvidenceKey(reference), reference])).values()];
    if (unique.length === 0) return null;
    return <div className="mt-2">
      <p className="text-xs font-bold">{label}（{unique.length}）</p>
      <ul className="mt-1 list-disc pl-5 text-xs">
        {unique.map((reference) => <li key={profileEvidenceKey(reference)}>
          {profileEvidenceLabel(reference, clues, webFacts)}{reference.post_id ? `（投稿 ${postNumbers.get(reference.post_id) ?? "?"}${postDates.has(reference.post_id) ? `・${new Date(postDates.get(reference.post_id)!).toLocaleDateString("ja-JP", { timeZone: "Asia/Tokyo" })}` : ""}）` : ""}
        </li>)}
      </ul>
    </div>;
  }

  // カードの位置は描いてみないと分からないので、描いたあとに測る。幅が変わったら測り直す
  useLayoutEffect(() => {
    const board = boardRef.current;
    if (!board || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() =>
      setStrings(layoutStrings(board, pinRefs.current, cardRefs.current, boardConclusions)),
    );
    observer.observe(board);
    return () => observer.disconnect();
  }, [boardConclusions]);

  return (
    <>
    <section aria-labelledby="board-heading" className="max-w-2xl space-y-4">
      {/* 表示された瞬間に 1 回だけ演出が走る。何も推定できなかったときは出さない */}
      {found && (
        <>
          <div aria-hidden="true" className="found-flash" />
          <p className="horror-title found-title text-5xl sm:text-6xl">{t.found}</p>
        </>
      )}
      <h3 id="board-heading" className="font-display text-2xl">
        {t.heading}
      </h3>
      {!found ? (
        <p className="text-ink/70">{t.empty}</p>
      ) : (
        <div ref={boardRef} className="relative">
          <svg aria-hidden="true" className="red-strings absolute inset-0 h-full w-full overflow-visible">
            {strings.map((s, i) => (
              <path
                key={s.key}
                pathLength={1}
                d={s.d}
                className="red-string"
                style={{ animationDelay: `${0.6 + i * 0.15}s` }}
              />
            ))}
          </svg>

          <ul aria-label={t.evidence} className="relative flex flex-wrap gap-x-3 gap-y-5 pt-2">
            {evidence.map((index) => {
              const clue = clues[index];
              return (
                <li
                  key={index}
                  ref={(el) => {
                    if (el) pinRefs.current.set(index, el);
                    else pinRefs.current.delete(index);
                  }}
                  className="evidence-pin rounded-sm border border-ink/20 bg-paper-deep px-2.5 py-1.5 text-sm shadow-[2px_2px_0_oklch(0%_0_0/0.4)]"
                >
                  <span className="block text-xs text-ink/60">{messages.clues.typeLabels[clue.type]}</span>
                  <span className="font-bold">{clue.value}</span>
                </li>
              );
            })}
          </ul>

          <ol aria-label={t.conclusionsLabel} className="relative mt-16 space-y-6">
            {boardConclusions.map((conclusion, i) => (
              <li
                key={i}
                ref={(el) => {
                  if (el) cardRefs.current.set(i, el);
                  else cardRefs.current.delete(i);
                }}
                className="border-l-4 border-seeker bg-paper-deep px-4 py-3"
              >
                <p className="text-xs tracking-widest text-ink/60">
                  {t.attributeLabels[conclusion.attribute] ?? conclusion.attribute}
                  <span className="ml-2 rounded-sm bg-ink/10 px-1.5 py-0.5">{t.inferred}</span>
                </p>
                <p className="mt-1 text-xl font-bold">{conclusion.value}</p>
                {conclusion.note && <p className="mt-1 text-sm text-ink/70">{conclusion.note}</p>}
                <p className="mt-3 text-xs tracking-widest text-ink/60">
                  {t.reasons(conclusion.clue_indices.length)}
                </p>
                <ul aria-label={t.reasonsLabel} className="mt-1 flex flex-wrap gap-2">
                  {conclusion.clue_indices.map((index) => {
                    const clue = clues[index];
                    return (
                      <li key={index} className="rounded-sm border border-ink/20 px-2 py-0.5 text-sm">
                        <span className="text-xs text-ink/60">{messages.clues.typeLabels[clue.type]}</span>{" "}
                        {clue.value}
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
            {boardUnknown.map((attribute) => (
              <li
                key={`unknown-${attribute}`}
                className="border-l-4 border-dashed border-ink/30 bg-paper-deep/50 px-4 py-3 text-ink/60"
              >
                <p className="text-xs tracking-widest">{t.attributeLabels[attribute] ?? attribute}</p>
                <p className="mt-1 text-xl font-bold line-through decoration-seeker decoration-2">{t.unknown}</p>
                <p className="mt-1 text-sm">{t.unknownNote}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
    {(profileClaims.length > 0 || profileRelations.length > 0 || ownerProfileText || externalProfileResults.length > 0 || externalLookupStatus !== "not_requested") && (
      <section aria-labelledby="profile-claims-heading" className="mt-8 max-w-2xl space-y-4">
        <h3 id="profile-claims-heading" className="font-display text-2xl">プロフィール候補</h3>
        <p className="text-sm text-ink/70">表示するのは根拠経路のある候補だけです。値を本人が直接公開した経路と、投稿を組み合わせて導いた経路を分けて示します。候補スコアは正しさの確率ではありません。</p>
        {visibleProfileClaims.length === 0 ? <p className="text-ink/70">根拠経路のある候補はありません。</p> : (
          <ul className="space-y-3">
            {visibleProfileClaims.map((claimSet) => (
              <li key={claimSet.attribute} className="border-l-4 border-seeker bg-paper-deep px-4 py-3">
                <p className="text-xs tracking-widest text-ink/60">
                  {profileAttributeLabel(claimSet, nowMs)} ・{
                    claimSet.status === "ambiguous" ? "複数の候補" : "候補（正解とは限りません）"
                  }
                </p>
                <ul aria-label={`${profileAttributeLabel(claimSet, nowMs)}の候補`} className="mt-2 space-y-2">
                  {claimSet.candidates.map((candidate) => {
                    const observedAt = candidate.observed_at ? Date.parse(candidate.observed_at) : Number.NaN;
                    const ageMs = nowMs - observedAt;
                    const recentLocation = claimSet.attribute === "realtime_location" && ageMs >= 0 && ageMs <= 15 * 60_000;
                    return <li key={candidate.value} className="rounded border border-ink/15 px-3 py-2">
                      <p className="text-xl font-bold">{candidate.value}</p>
                      <ul aria-label="値の根拠経路" className="mt-1 flex flex-wrap gap-2 text-xs">
                        {provenanceLabels(candidate).map((label) => <li key={label} className="rounded border border-ink/25 px-2 py-0.5">{label}</li>)}
                      </ul>
                      <p className="mt-1 text-sm text-ink/70">{candidate.status === "weak" ? "弱い候補" : "候補"} ・ 順位 #{candidate.rank} / 根拠候補 {claimSet.candidate_pool.length} 件 ・ 根拠スコア {candidate.confidence.toFixed(2)}（正しさの確率ではありません）</p>
                      {claimSet.attribute === "realtime_location" && candidate.observed_at && (
                        <p className="mt-1 text-xs text-ink/70">
                          投稿時点：{new Date(candidate.observed_at).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })}
                          {nowMs === 0 ? "（時刻を確認中）" : recentLocation ? "（15分以内の投稿）" : "（15分経過。最新情報ではありません）"}
                        </p>
                      )}
                      <details className="mt-2 text-sm">
                        <summary className="cursor-pointer font-bold">根拠と反対の根拠を確認</summary>
                        <div className="mt-2">
                          <p className="text-xs font-bold">候補を支える根拠経路（{candidate.evidence_paths.length}）</p>
                          <ul className="mt-1 space-y-2">
                            {candidate.evidence_paths.map((path, index) => <li key={`${candidate.value}:${index}`} className="rounded border border-ink/15 px-2 py-1.5">
                              <p className="text-xs font-bold">{evidencePathLabel(path)}</p>
                              {profileEvidenceList("この経路の根拠", path.evidence)}
                            </li>)}
                          </ul>
                        </div>
                        {profileEvidenceList("この候補への反対根拠", candidate.counter_evidence)}
                        {profileEvidenceList("項目全体に関する矛盾根拠", claimSet.conflicting_evidence)}
                      </details>
                    </li>;
                  })}
                </ul>
                {claimSet.attribute === "regular_station" && <p className="mt-2 text-xs text-ink/70">投稿時点の習慣候補です。現在も同じ駅を利用している保証はありません。根拠投稿の日付を確認してください。</p>}
                {claimSet.candidates.length === 0 && claimSet.conflicting_evidence.length > 0 && (
                  <details className="mt-2 text-sm">
                    <summary className="cursor-pointer font-bold">矛盾を示す根拠を確認</summary>
                    {profileEvidenceList("項目全体に関する矛盾根拠", claimSet.conflicting_evidence)}
                  </details>
                )}
              </li>
            ))}
          </ul>
        )}
        {visibleRelations.length > 0 && <div className="rounded border border-ink/20 px-3 py-3">
          <h4 className="font-bold">投稿から結んだ関係候補</h4>
          <ul className="mt-2 space-y-2 text-sm">
            {visibleRelations.map((relation, index) => <li key={`${relation.kind}:${index}`}>
              <span className="font-bold">
                {relation.left.kind === "profile_candidate" ? PROFILE_ATTRIBUTE_CATALOG[relation.left.attribute].label : "投稿中の通勤・通学先"}：{relation.left.value}
                {" → "}
                {relation.right.kind === "profile_candidate" ? PROFILE_ATTRIBUTE_CATALOG[relation.right.attribute].label : "投稿中の通勤・通学先"}：{relation.right.value}
              </span>
              <span className="ml-2 text-ink/70">{relation.kind === "home_nearest_is_commute_origin" ? "自宅最寄りの本人投稿と、別投稿の反復通勤文を結んだ候補" : "投稿中の通勤・通学先と独立した所属候補の値が一致（雇用・在学の確定ではありません）"}</span>
              <details className="mt-1 text-xs"><summary className="cursor-pointer">関係の根拠</summary>
                {relation.evidence_paths.map((path, pathIndex) => <div key={pathIndex}>{profileEvidenceList("根拠経路", path.evidence)}</div>)}
              </details>
            </li>)}
          </ul>
          <p className="mt-2 text-xs text-ink/70">関係表示は独立した本人投稿の根拠を示すもので、候補の確率や正解を意味しません。</p>
        </div>}
        <ProfileClaimWhatIf claims={profileClaims} relations={profileRelations} clues={clues} posts={posts} suggestions={profileClaimSuggestions} webFacts={webFacts} />
        {ownerProfileText && <details><summary className="cursor-pointer font-bold">本人プロフィール文と自己申告の手がかり</summary><p className="mt-2 whitespace-pre-wrap text-sm">{ownerProfileText}</p><ul className="mt-2 list-disc pl-5 text-sm">{selfReportClues.map((clue, index) => <li key={`${clue.post_id}:${index}`}>{clue.value}</li>)}</ul></details>}
        {externalLookupStatus !== "not_requested" && <div className="rounded border border-ink/20 p-3">
          <h4 className="font-bold">公開Web上の外部ページ候補</h4>
          <p className="mt-1 text-xs text-ink/70">検索結果は候補です。本人との同一性や記事の執筆者は確認していません。</p>
          {externalProfileResults.length === 0 ? <p className="mt-2 text-sm">{externalLookupStatus === "unavailable" ? "検索サービスを利用できませんでした。" : "候補はありませんでした。"}</p> : <ul className="mt-2 space-y-2">{externalProfileResults.map((result) => <li key={result.id} className="text-sm"><a className="underline" href={result.url} target="_blank" rel="noreferrer">{result.title || result.domain}</a><span className="ml-2 text-xs text-ink/60">{result.status === "owner_linked" ? "本人の公開投稿にURLあり" : "検索候補"}</span></li>)}</ul>}
        </div>}
      </section>
    )}
    </>
  );
}
