"use client";

import { useEffect, useRef, useState } from "react";

import { EscapeStamps, type BrokenInference } from "@/components/escape-stamps/EscapeStamps";
import { ApiError, deletePosts, simulate } from "@/lib/api";
import { attributeLabel, messages } from "@/lib/messages";
import { isLikelyNameText } from "@/lib/reveal";
import type { Clue } from "@/types/clue";
import { type Deletion, type RiskyPost, type Simulation } from "@/types/diagnose";
import type { Post } from "@/types/post";
import type { ProfileCandidateSet } from "@/types/profile";

import { DeleteConfirm } from "./DeleteConfirm";

const t = messages.risky;

const DIRECT_CLUES = ["face", "name_text", "address_text", "phone", "postal_code"] as const;

/** 投稿の本文はこの文字数で切って見せる */
const EXCERPT_LENGTH = 60;

interface RiskyPostsProps {
  posts: readonly Post[];
  risky: readonly RiskyPost[];
  /** 各投稿に直接写っていた手がかりの説明に使う。 */
  clues?: readonly Clue[];
  /** 診断の手がかりの数（simulate の結果の根拠の番号を確かめる） */
  clueCount: number;
  /** カタログ属性の候補セット（シミュレート後の件数比較と逃げ切り判定に使う） */
  profileClaims?: readonly ProfileCandidateSet[];
  onSessionExpired?: () => void;
  /** 消したらどうなるか・実際に消した結果。元に戻したり選び直したりしたら null */
  onSimulated: (simulation: Simulation | null) => void;
  onDeleted?: (deletion: Deletion) => void;
}

function labelsOf(attributes: readonly string[]): string {
  return attributes.map((a) => attributeLabel(a)).join("・");
}

function excerpt(text: string): string {
  if (!text) return t.noText;
  return text.length > EXCERPT_LENGTH ? `${text.slice(0, EXCERPT_LENGTH)}…` : text;
}

function supportedCount(claims: readonly ProfileCandidateSet[]): number {
  return claims.filter((claimSet) => claimSet.candidates.length > 0).length;
}

function brokenProfileInferences(claims: readonly ProfileCandidateSet[], lost: readonly string[]): BrokenInference[] {
  return lost.map((attribute) => {
    const candidates = claims.find((c) => c.attribute === attribute)?.candidates ?? [];
    return {
      label: attributeLabel(attribute),
      value: candidates.map((c) => c.value).join(" / "),
    };
  });
}

/**
 * 危ない投稿（診断の plan）を並べ、選んだ投稿を消したらどうなるかを見せる（まーだだよ）。
 * 結果は捜査ボードに渡して、崩れた項目を「不明」にする。
 * 試したあと、確認ダイアログで OK したときだけ Bluesky から実際に消す（もういいよ）。消したあとは選び直せない。
 */
export function RiskyPosts({ posts, risky, clues = [], clueCount, profileClaims = [], onSimulated, onDeleted, onSessionExpired }: RiskyPostsProps) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set(risky.map((r) => r.post_id)));
  const [result, setResult] = useState<Simulation | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deletion, setDeletion] = useState<Deletion | null>(null);
  const controller = useRef<AbortController | null>(null);

  function expiredBy(error: unknown): boolean {
    if (!(error instanceof ApiError) || error.kind !== "unauthorized" || !onSessionExpired) return false;
    onSessionExpired();
    return true;
  }

  useEffect(() => () => controller.current?.abort(), []);

  if (risky.length === 0) {
    return (
      <section aria-labelledby="risky-heading" className="max-w-2xl space-y-3">
        <h3 id="risky-heading" className="horror-title text-4xl">
          {t.heading}
        </h3>
        <p className="text-ink/70">{t.none}</p>
        <InviteLink />
      </section>
    );
  }

  const byId = new Map(posts.map((p) => [p.post_id, p]));

  function clear() {
    controller.current?.abort();
    setPending(false);
    setResult(null);
    setError(null);
    onSimulated(null);
  }

  function toggle(postId: string) {
    // 選び直したら、前の結果は残さない
    clear();
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(postId)) next.delete(postId);
      else next.add(postId);
      return next;
    });
  }

  async function confirmDelete() {
    if (!result) return;
    setDeleting(true);
    setError(null);
    try {
      // 試した投稿（result.delete）をそのまま消す
      const deleted = await deletePosts(result.delete, clueCount);
      setDeletion(deleted);
      onSimulated(deleted);
      onDeleted?.(deleted);
      setConfirming(false);
    } catch (e) {
      setConfirming(false);
      if (expiredBy(e)) return;
      setError(e instanceof ApiError ? e.message : t.deleteFailed);
    } finally {
      setDeleting(false);
    }
  }

  async function run() {
    clear();
    const current = new AbortController();
    controller.current = current;
    setPending(true);
    try {
      // 画面の並び（危ない順）で送る
      const ids = risky.map((r) => r.post_id).filter((id) => selected.has(id));
      const simulation = await simulate(ids, clueCount, {
        signal: current.signal,
      });
      if (current.signal.aborted) return;
      setResult(simulation);
      onSimulated(simulation);
    } catch (e) {
      if (current.signal.aborted) return;
      if (expiredBy(e)) return;
      setError(e instanceof ApiError ? e.message : t.failed);
    } finally {
      if (!current.signal.aborted) setPending(false);
    }
  }

  const shown = deletion ?? result;
  const gone = new Set(deletion
    ? deletion.delete.filter((id) => !deletion.failed.includes(id))
    : result?.delete ?? []);
  const directCluesLeft = clues.some((c) => !gone.has(c.post_id) && directClueLabel(c) !== null);
  const afterProfileClaims = shown?.after ?? [];
  const hasSurvivingProfileCandidate = supportedCount(afterProfileClaims) > 0;
  const escaped = shown !== null && (deletion?.failed.length ?? 0) === 0 && !directCluesLeft && !hasSurvivingProfileCandidate;
  const counts = shown !== null && profileClaims.length > 0
    ? { before: supportedCount(profileClaims), after: supportedCount(afterProfileClaims) }
    : null;
  const brokenItems = shown !== null && counts !== null && counts.after < counts.before
    ? brokenProfileInferences(profileClaims, shown.broken)
    : [];

  return (
    <section aria-labelledby="risky-heading" aria-busy={pending} className="max-w-2xl space-y-4">
      <h3 id="risky-heading" className="horror-title text-4xl">
        {t.heading}
      </h3>
      <p className="text-ink/80">{t.lead}</p>
      {/* 減ったときは、崩れた推定に判子を押して数を1つずつ減らす。減らなかったときは今までどおり N → M だけ */}
      {counts && shown && counts.after < counts.before && brokenItems.length > 0 ? (
        <EscapeStamps
          key={`${deletion ? "deleted" : "simulated"}:${shown.delete.join(",")}`}
          before={counts.before}
          after={counts.after}
          broken={brokenItems}
        />
      ) : (
        counts && <CountChange before={counts.before} after={counts.after} />
      )}

      <ol aria-label={t.listLabel} className="space-y-3">
        {risky.map((r) => {
          const post = byId.get(r.post_id);
          const checked = selected.has(r.post_id);
          const direct = [...new Set(clues.filter((c) => c.post_id === r.post_id).map(directClueLabel).filter((label): label is string => label !== null))];
          return (
            <li key={r.post_id}>
              <label
                className={`flex cursor-pointer gap-3 border-l-4 bg-paper-deep px-4 py-3 transition-colors ${
                  checked ? "border-seeker" : "border-ink/20"
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={deletion !== null}
                  onChange={() => toggle(r.post_id)}
                  className="mt-1 size-4 shrink-0 accent-[var(--color-seeker)]"
                />
                <span className="min-w-0">
                  <span className="block break-words">{excerpt(post?.text ?? "")}</span>
                  {post && post.images.length > 0 && (
                    <span className="mt-0.5 block text-xs text-ink/60">{t.photos(post.images.length)}</span>
                  )}
                  <span className="mt-1 block text-sm font-bold text-seeker">
                    {r.broken.length > 0
                      ? t.breaks(labelsOf(r.broken))
                      : t.breaksNothing}
                  </span>
                  {direct.length > 0 && <span className="mt-1 block text-sm text-ink/80">{t.directClues(direct.join("・"))}</span>}
                </span>
              </label>
            </li>
          );
        })}
      </ol>

      {!deletion && (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={run}
            disabled={pending || selected.size === 0}
            className="inline-flex items-center gap-3 rounded-sm bg-seeker px-5 py-2.5 font-display text-paper shadow-[4px_4px_0_var(--color-ink)] transition-transform hover:-translate-y-0.5 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink active:translate-y-0.5 active:shadow-none disabled:cursor-not-allowed disabled:opacity-60 disabled:shadow-none"
          >
            {pending && (
              <span
                aria-hidden
                className="size-4 animate-spin rounded-full border-2 border-paper border-t-transparent motion-reduce:animate-none"
              />
            )}
            {t.simulate}
          </button>
          {result && (
            <button
              type="button"
              onClick={clear}
              className="rounded-sm border border-ink/40 px-4 py-2 transition-colors hover:bg-ink/10 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink"
            >
              {t.reset}
            </button>
          )}
          {result && result.delete.length > 0 && (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="rounded-sm border-2 border-seeker px-4 py-2 font-display text-seeker transition-colors hover:bg-seeker hover:text-paper focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink"
            >
              {t.deleteForReal}
            </button>
          )}
        </div>
      )}

      {pending && (
        <p role="status" className="text-ink/70">
          {t.simulating}
        </p>
      )}
      {result && !deletion && (
        <div role="status" className="space-y-1">
          <p className="font-bold">{t.result(result.delete.length, result.broken.length)}</p>
          {result.broken.length > 0 && <p className="text-sm text-ink/70">{labelsOf(result.broken)}</p>}
          {escaped && <p className="font-display text-xl text-seeker">{t.safe}</p>}
        </div>
      )}
      {deletion && <Escaped deletion={deletion} escaped={escaped} />}
      {error && (
        <p role="alert" className="border-l-4 border-seeker bg-seeker/10 px-4 py-3">
          {error}
        </p>
      )}

      {confirming && result && (
        <DeleteConfirm
          excerpts={result.delete.map((id) => excerpt(byId.get(id)?.text ?? ""))}
          pending={deleting}
          onConfirm={confirmDelete}
          onCancel={() => setConfirming(false)}
        />
      )}
      <InviteLink />
    </section>
  );
}

function directClueLabel(clue: Clue): string | null {
  if (!DIRECT_CLUES.some((type) => type === clue.type)) return null;
  if (clue.type === "face" && clue.confidence < 0.8) return null;
  if (clue.type === "name_text" && !isLikelyNameText(clue.value)) return null;
  return messages.clues.typeLabels[clue.type];
}

function CountChange({ before, after }: { before: number; after: number }) {
  return <figure aria-label={t.countLabel(before, after)} className="border-y-2 border-ink py-4 text-center">
    <figcaption className="text-sm tracking-widest text-ink/70">{t.countHeading}</figcaption>
    <p aria-hidden className="mt-1 font-display text-6xl leading-none tabular-nums sm:text-7xl"><span>{before}</span><span className="mx-3 text-ink/40 sm:mx-5">→</span><span className={after < before ? "text-seeker" : ""}>{after}</span></p>
  </figure>;
}

export function inviteComposeUrl(origin: string): string {
  const text = `${messages.invite.text}\n${origin}/`;
  return `https://bsky.app/intent/compose?text=${encodeURIComponent(text)}`;
}

function InviteLink() {
  return <p className="border-t border-ink/15 pt-4">
    <a href={inviteComposeUrl(window.location.origin)} target="_blank" rel="noopener noreferrer" className="font-bold underline underline-offset-2">{messages.invite.link}</a>
    <span className="mt-1 block text-sm text-ink/60">{messages.invite.note}</span>
  </p>;
}

/** 実際に消したあと：消せた数、消せなかった数、逃げ切れたか */
function Escaped({ deletion, escaped }: { deletion: Deletion; escaped: boolean }) {
  const e = messages.escaped;
  return (
    <div role="status" className="space-y-2 border-t border-ink/15 pt-4">
      <p className="horror-title text-4xl">{e.heading}</p>
      <p className="font-bold">{e.deleted(deletion.delete.length)}</p>
      {deletion.broken.length > 0 && <p className="text-sm text-ink/70">{t.breaks(labelsOf(deletion.broken))}</p>}
      {escaped && <p className="font-display text-xl text-seeker">{t.safe}</p>}
      {deletion.failed.length > 0 && (
        <p className="border-l-4 border-seeker bg-seeker/10 px-4 py-2">
          {deletion.bluesky_busy ? e.blueskyBusy(deletion.failed.length) : e.failed(deletion.failed.length)}
        </p>
      )}
      <p className="text-sm text-ink/60">{e.rediagnose}</p>
    </div>
  );
}
