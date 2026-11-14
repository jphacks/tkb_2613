"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ConclusionBoard } from "@/components/conclusion-board/ConclusionBoard";
import { NarrowingStages } from "@/components/narrowing/NarrowingStages";
import { PostCard } from "@/components/post-list/PostCard";
import { Reveal } from "@/components/reveal/Reveal";
import { ApiError, getDemoDiagnosis, simulateDemo } from "@/lib/api";
import { attributeLabel, messages } from "@/lib/messages";
import { isProfileSimulationAfter, type DemoDiagnosis, type Simulation } from "@/types/diagnose";
import { visibleNarrowing } from "@/types/narrowing";
import { profileClaimsAfterDeletion } from "@/types/profile";

const t = messages.demo;
const r = messages.risky;

/**
 * ログインなしの体験デモ。架空アカウントの診断結果を見せ、削除候補を仮に除いた結果を試せる。
 * 削除の操作はない。架空のアカウントであることを、画面の一番上に常に出す。
 */
export default function DemoPage() {
  const [result, setResult] = useState<DemoDiagnosis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [simulation, setSimulation] = useState<Simulation | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getDemoDiagnosis({ signal: controller.signal })
      .then((demo) => {
        if (!controller.signal.aborted) setResult(demo);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(t.failed);
      });
    return () => controller.abort();
  }, []);

  const baseProfileClaims = result?.profile_claims ?? [];
  const excluded = new Set(simulation?.delete ?? []);
  const visibleProfileClaims = simulation
    ? isProfileSimulationAfter(simulation.after)
      ? simulation.after
      : profileClaimsAfterDeletion(baseProfileClaims, excluded)
    : baseProfileClaims;
  const visibleSuggestions = (result?.profile_claim_suggestions ?? []).filter((id) => !excluded.has(id));

  return (
    <>
      <p role="note" className="sticky top-0 z-10 bg-ink px-4 py-2 text-center text-sm font-bold text-paper">
        {t.banner}
      </p>
      <main className="mx-auto max-w-5xl space-y-10 px-4 py-12 sm:px-8 sm:py-16">
        <header className="space-y-3">
          <h1 className="horror-title text-4xl leading-tight sm:text-5xl">{t.heading}</h1>
          <p className="max-w-xl text-ink/80">{t.lead}</p>
        </header>
        {!result && !error && <p role="status">{t.loading}</p>}
        {error && <p role="alert" className="border-l-4 border-seeker bg-seeker/10 px-4 py-3">{error}</p>}
        {result && (
          <>
            <Reveal posts={result.posts} clues={result.clues} conclusions={[]} profileClaims={visibleProfileClaims} excludedPostIds={excluded}>
              <NarrowingStages narrowing={visibleNarrowing(simulation ? simulation.narrowing : result.narrowing, excluded)} />
            </Reveal>
            <ConclusionBoard
              clues={result.clues}
              conclusions={[]}
              unknown={simulation?.broken}
              profileClaims={visibleProfileClaims}
              profileRelations={result.profile_relations ?? []}
              deletedPostIds={simulation?.delete ?? []}
              profileClaimSuggestions={visibleSuggestions}
              posts={result.posts}
            />
            <DemoCandidates result={result} onSimulated={setSimulation} />
            <ol aria-label={messages.diagnose.postsLabel} className="max-w-2xl space-y-5">
              {result.posts.map((post) => (
                <li key={post.post_id}>
                  <PostCard post={post} found={{ clues: result.clues.filter((c) => c.post_id === post.post_id), error: null }} />
                </li>
              ))}
            </ol>
          </>
        )}
        <p>
          <Link href="/" className="font-bold underline underline-offset-4 hover:text-seeker">{t.backHome}</Link>
        </p>
      </main>
    </>
  );
}

/** 削除候補を選んで「消したらどうなる」を試す。実際に消すボタンは置かない */
function DemoCandidates({ result, onSimulated }: {
  result: DemoDiagnosis;
  onSimulated: (simulation: Simulation | null) => void;
}) {
  const candidates = result.plan.posts;
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set(candidates.map((c) => c.post_id)));
  const [outcome, setOutcome] = useState<Simulation | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);
  if (candidates.length === 0) return null;

  function reset() {
    controller.current?.abort();
    setPending(false);
    setOutcome(null);
    setError(null);
    onSimulated(null);
  }

  function toggle(postId: string) {
    reset();
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(postId)) next.delete(postId);
      else next.add(postId);
      return next;
    });
  }

  async function run() {
    reset();
    const current = new AbortController();
    controller.current = current;
    setPending(true);
    try {
      const ids = candidates.map((c) => c.post_id).filter((id) => selected.has(id));
      const simulation = await simulateDemo(ids, result.clues.length, { signal: current.signal });
      if (current.signal.aborted) return;
      setOutcome(simulation);
      onSimulated(simulation);
    } catch (e) {
      if (!current.signal.aborted) setError(e instanceof ApiError ? e.message : r.failed);
    } finally {
      if (!current.signal.aborted) setPending(false);
    }
  }

  const byId = new Map(result.posts.map((p) => [p.post_id, p]));
  return (
    <section aria-labelledby="demo-candidates" aria-busy={pending} className="max-w-2xl space-y-4">
      <h2 id="demo-candidates" className="horror-title text-4xl">{t.candidatesHeading}</h2>
      <p className="text-ink/80">{t.candidatesLead}</p>
      <ol aria-label={t.candidatesLabel} className="space-y-3">
        {candidates.map((c) => (
          <li key={c.post_id}>
            <label className={`flex cursor-pointer gap-3 border-l-4 bg-paper-deep px-4 py-3 ${selected.has(c.post_id) ? "border-seeker" : "border-ink/20"}`}>
              <input type="checkbox" checked={selected.has(c.post_id)} onChange={() => toggle(c.post_id)} className="mt-1 size-4 shrink-0 accent-[var(--color-seeker)]" />
              <span className="min-w-0">
                <span className="block break-words">{byId.get(c.post_id)?.text || r.noText}</span>
                <span className="mt-1 block text-sm font-bold text-seeker">
                  {c.broken.length > 0 ? r.breaks(c.broken.map((a) => attributeLabel(a)).join("・")) : r.breaksNothing}
                </span>
              </span>
            </label>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={run} disabled={pending || selected.size === 0} className="rounded-sm bg-seeker px-5 py-2.5 font-display text-paper shadow-[4px_4px_0_var(--color-ink)] transition-transform hover:-translate-y-0.5 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:cursor-not-allowed disabled:opacity-60 disabled:shadow-none">
          {r.simulate}
        </button>
        {outcome && (
          <button type="button" onClick={reset} className="rounded-sm border border-ink/40 px-4 py-2 hover:bg-ink/10 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink">
            {r.reset}
          </button>
        )}
      </div>
      {pending && <p role="status" className="text-ink/70">{r.simulating}</p>}
      {outcome && <p role="status" className="font-bold">{r.result(outcome.delete.length, outcome.broken.length)}</p>}
      {error && <p role="alert" className="border-l-4 border-seeker bg-seeker/10 px-4 py-3">{error}</p>}
    </section>
  );
}
