"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, deletePosts, simulate } from "@/lib/api";
import { messages } from "@/lib/messages";
import type { Deletion, RiskyPost, Simulation } from "@/types/diagnose";
import type { Post } from "@/types/post";

import { DeleteConfirm } from "./DeleteConfirm";

const t = messages.risky;

/** 投稿の本文はこの文字数で切って見せる */
const EXCERPT_LENGTH = 60;

interface RiskyPostsProps {
  posts: readonly Post[];
  risky: readonly RiskyPost[];
  /** 捜査ボードの末尾3項目（engine の推薦対象と同じ） */
  targetAttributes?: readonly string[];
  /** 診断の手がかりの数（simulate の結果の根拠の番号を確かめる） */
  clueCount: number;
  /** 消したらどうなるか・実際に消した結果。元に戻したり選び直したりしたら null */
  onSimulated: (simulation: Simulation | null) => void;
}

function labelsOf(attributes: readonly string[]): string {
  return attributes.map((a) => messages.board.attributeLabels[a] ?? a).join("・");
}

function excerpt(text: string): string {
  if (!text) return t.noText;
  return text.length > EXCERPT_LENGTH ? `${text.slice(0, EXCERPT_LENGTH)}…` : text;
}

/**
 * 危ない投稿（診断の plan）を並べ、選んだ投稿を消したらどうなるかを見せる（まーだだよ）。
 * 結果は捜査ボードに渡して、崩れた項目を「不明」にする。
 * 試したあと、確認ダイアログで OK したときだけ Bluesky から実際に消す（もういいよ）。消したあとは選び直せない。
 */
export function RiskyPosts({ posts, risky, targetAttributes = [], clueCount, onSimulated }: RiskyPostsProps) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set(risky.map((r) => r.post_id)));
  const [result, setResult] = useState<Simulation | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deletion, setDeletion] = useState<Deletion | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  if (risky.length === 0) {
    return (
      <section aria-labelledby="risky-heading" className="max-w-2xl space-y-3">
        <h3 id="risky-heading" className="horror-title text-4xl">
          {t.heading}
        </h3>
        <p className="text-ink/70">{t.none}</p>
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
      setConfirming(false);
    } catch (e) {
      setConfirming(false);
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
      setError(e instanceof ApiError ? e.message : t.failed);
    } finally {
      if (!current.signal.aborted) setPending(false);
    }
  }

  const shown = deletion ?? result;
  const escaped =
    shown !== null &&
    targetAttributes.length > 0 &&
    targetAttributes.every((a) => !shown.after.some((c) => c.attribute === a));

  return (
    <section aria-labelledby="risky-heading" aria-busy={pending} className="max-w-2xl space-y-4">
      <h3 id="risky-heading" className="horror-title text-4xl">
        {t.heading}
      </h3>
      <p className="text-ink/80">{t.lead}</p>

      <ol aria-label={t.listLabel} className="space-y-3">
        {risky.map((r) => {
          const post = byId.get(r.post_id);
          const checked = selected.has(r.post_id);
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
                    {r.broken.length > 0 ? t.breaks(labelsOf(r.broken)) : t.breaksNothing}
                  </span>
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
    </section>
  );
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
        <p className="border-l-4 border-seeker bg-seeker/10 px-4 py-2">{e.failed(deletion.failed.length)}</p>
      )}
      <p className="text-sm text-ink/60">{e.rediagnose}</p>
    </div>
  );
}
