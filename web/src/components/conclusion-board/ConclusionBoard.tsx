"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import { confidenceLevel, type Conclusion } from "@/types/diagnose";
import { openDataCitations, PROFILE_ATTRIBUTE_CATALOG, type ExternalLookupStatus, type ExternalProfileResult, type ProfileItem, type WebFact } from "@/types/profile";
import type { Post } from "@/types/post";
import { ClaimStrings } from "./ClaimStrings";
import { ProfileClaimWhatIf, whatIfEvidencePostIds } from "./ProfileClaimWhatIf";
import { ReasoningChain } from "./ReasoningChain";

const t = messages.board;

/** 確からしさが弱い推定にだけ、点線の枠の印を付ける。強い推定と、値のない古い閲覧リンクには何も出さない */
function ConfidenceMark({ conclusion }: { conclusion: Conclusion }) {
  return confidenceLevel(conclusion) === "weak" ? <WeakMark /> : null;
}

function WeakMark() {
  return (
    <span className="ml-2 rounded-sm border border-dashed border-ink/40 px-1.5 py-0.5 text-ink/70">
      {t.confidence.weak}
    </span>
  );
}

/** 糸のたるみ（px） */
const SAG = 28;

interface ConclusionBoardProps {
  clues: readonly Clue[];
  conclusions: readonly Conclusion[];
  /** 消したらどうなるかで推定できなくなった項目（attribute）。「不明」のカードで出す */
  unknown?: readonly string[];
  profileClaims?: readonly ProfileItem[];
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
  clues, conclusions, unknown = [], profileClaims = [], profileClaimSuggestions = [], posts = [],
  webFacts = [], externalLookupStatus = "not_requested", externalProfileResults = [], ownerProfileText = "", selfReportClues = [],
}: ConclusionBoardProps) {
  const boardRef = useRef<HTMLDivElement>(null);
  const pinRefs = useRef(new Map<number, HTMLElement>());
  const cardRefs = useRef(new Map<number, HTMLElement>());
  const [strings, setStrings] = useState<readonly RedString[]>([]);

  // 消したらどうなるかで全部「不明」になっても、演出は出したままにする（出し直さない）
  const found = conclusions.length > 0 || unknown.length > 0;
  const evidence = [...new Set(conclusions.flatMap((c) => c.clue_indices))].sort((a, b) => a - b);

  // カードの位置は描いてみないと分からないので、描いたあとに測る。幅が変わったら測り直す
  useLayoutEffect(() => {
    const board = boardRef.current;
    if (!board || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() =>
      setStrings(layoutStrings(board, pinRefs.current, cardRefs.current, conclusions)),
    );
    observer.observe(board);
    return () => observer.disconnect();
  }, [conclusions]);

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
            {conclusions.map((conclusion, i) => (
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
                  <ConfidenceMark conclusion={conclusion} />
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
                {posts.length > 0 && <ReasoningChain conclusion={conclusion} clues={clues} posts={posts} />}
              </li>
            ))}
            {unknown.map((attribute) => (
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
    {(profileClaims.length > 0 || ownerProfileText || externalProfileResults.length > 0 || externalLookupStatus !== "not_requested") && (
      <section aria-labelledby="profile-claims-heading" className="mt-8 max-w-2xl space-y-4">
        <h3 id="profile-claims-heading" className="font-display text-2xl">投稿を横断したプロフィール推定</h3>
        {profileClaims.length === 0 ? <p className="text-ink/70">投稿を横断して推定できた項目はありませんでした。</p> : (
          <ul className="space-y-3">
            {profileClaims.map((claim) => (
              <li key={claim.attribute} className="border-l-4 border-seeker bg-paper-deep px-4 py-3">
                {/* 捜査ボードと同じ見せ方：「推定」の印と、弱いときだけ「確からしさ：弱い」。数字は出さない */}
                <p className="text-xs tracking-widest text-ink/60">
                  {PROFILE_ATTRIBUTE_CATALOG[claim.attribute].label}
                  <span className="ml-2 rounded-sm bg-ink/10 px-1.5 py-0.5">{t.inferred}</span>
                  {claim.status === "weak" && <WeakMark />}
                </p>
                <p className="mt-1 text-xl font-bold">{claim.value}</p>
                {openDataCitations(claim).map((citation) => (
                  <p key={citation} className="mt-1 text-xs text-ink/70">{citation}</p>
                ))}
                {/* 根拠の道筋が2つ以上あるときだけ、道筋ごとの投稿から答えへ赤い糸を張る */}
                <ClaimStrings claim={claim} posts={posts} />
              </li>
            ))}
          </ul>
        )}
        {/* 消す投稿は「まーだだよ」で選ぶ。こちらは根拠経路ごとの細かい比較なので、開いたときだけ見せる */}
        {whatIfEvidencePostIds(profileClaims, posts).length > 0 && (
          <details className="rounded-sm border border-ink/20 px-4 py-3">
            <summary className="cursor-pointer font-bold">{messages.board.whatIfSummary}</summary>
            <ProfileClaimWhatIf claims={profileClaims} clues={clues} posts={posts} suggestions={profileClaimSuggestions} webFacts={webFacts} />
          </details>
        )}
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
