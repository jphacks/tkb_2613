"use client";

import { useEffect, useRef, useState } from "react";

import { ConclusionBoard } from "@/components/conclusion-board/ConclusionBoard";
import { DiagnoseLoading } from "@/components/diagnose-loading/DiagnoseLoading";
import { PostCard, type PostClues } from "@/components/post-list/PostCard";
import { PlanSummary } from "@/components/plan-summary/PlanSummary";
import { Reveal } from "@/components/reveal/Reveal";
import { RiskyPosts } from "@/components/risky-posts/RiskyPosts";
import { useSession } from "@/components/session/SessionProvider";
import { ResultShare } from "@/components/diagnose/ResultShare";
import { ApiError, diagnose, getDiagnosis, getFeatures } from "@/lib/api";
import { messages } from "@/lib/messages";
import { validNameConclusions } from "@/lib/reveal";
import type { Clue } from "@/types/clue";
import type { Conclusion, PhotoPlaceResult, RiskyPost, Simulation } from "@/types/diagnose";
import type { Post } from "@/types/post";
import { profileClaimsAfterDeletion, type ExternalLookupStatus, type ExternalProfileResult, type ProfileCandidateSet, type ProfileRelation, type WebFact } from "@/types/profile";

const t = messages.diagnose;
const RISKY_HEADING_ID = "risky-heading";

function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.kind === "unauthorized";
}

/**
 * 診断の状態。connecting は押してから最初のイベントが届くまで、reading は投稿が届いている間、
 * searching は手がかりを取り出している間。
 */
type Phase =
  | { kind: "idle" }
  | { kind: "connecting" }
  | { kind: "reading" }
  | { kind: "searching" }
  | { kind: "done"; postsSeen: number }
  | { kind: "error"; message: string };

interface Result {
  clues: readonly Clue[];
  photoPlaceResults?: readonly PhotoPlaceResult[];
  conclusions: readonly Conclusion[];
  profileClaims?: readonly ProfileCandidateSet[];
  profileRelations?: readonly ProfileRelation[];
  profileClaimSuggestions?: readonly string[];
  webFacts?: readonly WebFact[];
  externalLookupStatus?: ExternalLookupStatus;
  externalProfileResults?: readonly ExternalProfileResult[];
  ownerProfileText?: string;
  selfReportClues?: readonly Clue[];
}

function statusText(phase: Phase, postCount: number, searchedCount: number): string | null {
  switch (phase.kind) {
    case "connecting":
      return t.connecting;
    case "reading":
      return t.reading(postCount);
    case "searching":
      return t.searching(searchedCount, postCount);
    case "done":
      return t.done(phase.postsSeen);
    default:
      return null;
  }
}

interface DiagnosePanelProps {
  /** 結果を叩きつけたら true、診断をやり直したら false。ホームがタイトルをしまうのに使う */
  onRevealedChange?: (revealed: boolean) => void;
}

/**
 * 診断を始め、ログインした本人の投稿を届いた順に並べる。
 * 診断の結果は画面のメモリにだけ置き、保存しない。
 */
export function DiagnosePanel({ onRevealedChange }: DiagnosePanelProps = {}) {
  const { state: session, expire } = useSession();
  const [posts, setPosts] = useState<readonly Post[]>([]);
  const [found, setFound] = useState<Readonly<Record<string, PostClues>>>({});
  const [result, setResult] = useState<Result | null>(null);
  const [risky, setRisky] = useState<readonly RiskyPost[] | null>(null);
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [deleted, setDeleted] = useState<ReadonlySet<string>>(new Set());
  const [publicWebLookupConsent, setPublicWebLookupConsent] = useState(false);
  const [publicWebLookupAvailable, setPublicWebLookupAvailable] = useState(false);
  const [photoPlaceWebLookupConsent, setPhotoPlaceWebLookupConsent] = useState(false);
  const [photoPlaceWebLookupAvailable, setPhotoPlaceWebLookupAvailable] = useState(false);
  const [photoPlaceReferenceConsent, setPhotoPlaceReferenceConsent] = useState(false);
  const [photoPlaceReferenceAvailable, setPhotoPlaceReferenceAvailable] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const controller = useRef<AbortController | null>(null);
  const restoreController = useRef<AbortController | null>(null);

  // 画面を離れたら、読み込み中の診断を止める
  useEffect(() => () => {
    controller.current?.abort();
    restoreController.current?.abort();
  }, []);

  useEffect(() => {
    const current = new AbortController();
    getFeatures({ signal: current.signal }).then((features) => {
      if (!current.signal.aborted) setPublicWebLookupAvailable(features.public_web_lookup_available === true);
      if (!current.signal.aborted) setPhotoPlaceWebLookupAvailable(features.photo_place_web_lookup_available === true);
      if (!current.signal.aborted) setPhotoPlaceReferenceAvailable(features.commons_reference_lookup_available === true);
    });
    return () => current.abort();
  }, []);

  // 同じログインセッションで画面を開き直した場合は、再解析せず直近の結果へ戻す。
  const sessionDid = session.status === "authenticated" ? session.session.did : null;
  useEffect(() => {
    if (!sessionDid) return;
    const current = new AbortController();
    restoreController.current = current;
    getDiagnosis({ signal: current.signal })
      .then((snapshot) => {
        if (!snapshot || current.signal.aborted || controller.current) return;
        const gone = new Set(snapshot.deleted ?? []);
        setDeleted(gone);
        setPosts(snapshot.posts);
        setFound(Object.fromEntries(snapshot.posts.map((post) => [
          post.post_id,
          { clues: snapshot.clues.filter((clue) => clue.post_id === post.post_id), error: null },
        ])));
        setResult({
          clues: snapshot.clues,
          photoPlaceResults: snapshot.photo_place_results ?? [],
          conclusions: validNameConclusions(snapshot.conclusions),
          profileClaims: snapshot.profile_claims ?? [],
          profileRelations: snapshot.profile_relations ?? [],
          profileClaimSuggestions: snapshot.profile_claim_suggestions ?? [],
          webFacts: snapshot.web_facts ?? [],
          externalLookupStatus: snapshot.external_lookup_status ?? "not_requested",
          externalProfileResults: snapshot.external_profile_results ?? [],
          ownerProfileText: snapshot.owner_profile_text ?? "",
          selfReportClues: snapshot.self_report_clues ?? [],
        });
        setRisky(snapshot.plan.posts.filter((post) => !gone.has(post.post_id)));
        setPhase({ kind: "done", postsSeen: snapshot.posts.length });
        onRevealedChange?.(true);
      })
      .catch((error: unknown) => {
        // 復元に失敗しても、診断ボタンからやり直せる。
        if (!current.signal.aborted && isUnauthorized(error)) expire();
      });
    return () => current.abort();
  }, [sessionDid, onRevealedChange, expire]);

  // 結果への切り替えでヘッダーとローディング画面の高さが変わる。描画後に先頭へ戻す。
  useEffect(() => {
    if (phase.kind === "done" && result) window.scrollTo(0, 0);
  }, [phase.kind, result]);

  if (session.status !== "authenticated") return null;

  async function start() {
    const consentForThisRun = publicWebLookupConsent;
    const photoPlaceConsentForThisRun = photoPlaceWebLookupConsent;
    const photoPlaceReferenceConsentForThisRun = photoPlaceReferenceConsent;
    setPublicWebLookupConsent(false);
    setPhotoPlaceWebLookupConsent(false);
    setPhotoPlaceReferenceConsent(false);
    restoreController.current?.abort();
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setPosts([]);
    setFound({});
    setResult(null);
    setRisky(null);
    setSimulation(null);
    setDeleted(new Set());
    onRevealedChange?.(false);
    setPhase({ kind: "connecting" });
    try {
      for await (const event of diagnose({
        signal: current.signal,
        publicWebLookupConsent: consentForThisRun,
        photoPlaceWebLookupConsent: photoPlaceConsentForThisRun,
        photoPlaceReferenceConsent: photoPlaceReferenceConsentForThisRun,
      })) {
        switch (event.event) {
          case "post":
            setPosts((prev) => [...prev, event.post]);
            setPhase({ kind: "reading" });
            break;
          case "clues":
            setFound((prev) => ({ ...prev, [event.post_id]: { clues: event.clues, error: event.error } }));
            setPhase({ kind: "searching" });
            break;
          case "conclusions":
            setResult({
              clues: event.clues,
              photoPlaceResults: event.photo_place_results ?? [],
              conclusions: validNameConclusions(event.conclusions),
              profileClaims: event.profile_claims ?? [],
              profileRelations: event.profile_relations ?? [],
              profileClaimSuggestions: event.profile_claim_suggestions ?? [],
              webFacts: event.web_facts ?? [],
              externalLookupStatus: event.external_lookup_status ?? "not_requested",
              externalProfileResults: event.external_profile_results ?? [],
              ownerProfileText: event.owner_profile_text ?? "",
              selfReportClues: event.self_report_clues ?? [],
            });
            break;
          case "plan":
            setRisky(event.posts);
            break;
          case "done":
            setPhase({ kind: "done", postsSeen: event.posts_seen });
            onRevealedChange?.(true);
            break;
        }
      }
    } catch (e) {
      if (current.signal.aborted) return;
      if (isUnauthorized(e)) { expire(); return; }
      setPhase({ kind: "error", message: e instanceof ApiError ? e.message : t.failed });
    }
  }

  const busy = phase.kind === "connecting" || phase.kind === "reading" || phase.kind === "searching";
  const status = statusText(phase, posts.length, Object.keys(found).length);
  const livePosts = deleted.size === 0 ? posts : posts.filter((post) => !deleted.has(post.post_id));
  const simulatedGone = simulation?.delete ?? [];
  const excluded = simulation ? new Set([...deleted, ...simulatedGone]) : deleted;
  const visibleProfileClaims = profileClaimsAfterDeletion(result?.profileClaims ?? [], excluded);
  const visibleProfileClaimSuggestions = (result?.profileClaimSuggestions ?? []).filter((id) => !excluded.has(id));
  const visibleConclusions = simulation ? validNameConclusions(simulation.after) : result?.conclusions ?? [];

  // 結果が出たら再診断ボタンを下へ移し、身元カード→写真→捜査ボードを続けて見せる。
  const postList = (
    <ol aria-label={t.postsLabel} className="max-w-2xl space-y-5">
      {posts.map((post) => (
        <li key={post.post_id}>
          {deleted.has(post.post_id) && <p className="mb-2 text-xs font-bold text-ink/60">{t.deletedBadge}</p>}
          <PostCard post={post} found={found[post.post_id]} />
        </li>
      ))}
    </ol>
  );

  const controls = (afterResult: boolean) => (
    <div>
        {publicWebLookupAvailable && <label className="mb-4 flex max-w-2xl items-start gap-3 rounded-sm border border-ink/20 px-4 py-3 text-sm">
          <input type="checkbox" checked={publicWebLookupConsent} onChange={(event) => setPublicWebLookupConsent(event.currentTarget.checked)} disabled={busy} className="mt-1 size-4 shrink-0 accent-seeker" />
          <span><span className="block font-bold">公開Webで外部SNS・ブログ・記事の候補を検索する（この診断のみ）</span><span className="mt-1 block text-xs text-ink/70">同意すると、実モードではログイン中の公開BlueskyハンドルだけをBraveへ送ります。検索語は最大90日保持され、利用には有料プランと支払情報の登録が必要です。投稿文・プロフィール文・写真は送りません。候補だけでは同一人物と判断しません。モックモードは固定の架空結果を使い、外部通信しません。</span></span>
        </label>}
        <label className="mb-4 flex max-w-2xl items-start gap-3 rounded-sm border border-ink/20 px-4 py-3 text-sm">
          <input type="checkbox" checked={photoPlaceWebLookupConsent} onChange={(event) => setPhotoPlaceWebLookupConsent(event.currentTarget.checked)} disabled={busy || !photoPlaceWebLookupAvailable} className="mt-1 size-4 shrink-0 accent-seeker" />
          <span><span className="block font-bold">{t.photoPlaceWebConsentLabel}</span><span className="mt-1 block text-xs text-ink/70">{t.photoPlaceWebConsentNote}</span>{!photoPlaceWebLookupAvailable && <span className="mt-1 block text-xs text-ink/70">{t.photoPlaceWebConsentUnavailable}</span>}</span>
        </label>
        <label className="mb-4 flex max-w-2xl items-start gap-3 rounded-sm border border-ink/20 px-4 py-3 text-sm">
          <input type="checkbox" checked={photoPlaceReferenceConsent} onChange={(event) => setPhotoPlaceReferenceConsent(event.currentTarget.checked)} disabled={busy || !photoPlaceReferenceAvailable} className="mt-1 size-4 shrink-0 accent-seeker" />
          <span><span className="block font-bold">{t.photoPlaceReferenceConsentLabel}</span><span className="mt-1 block text-xs text-ink/70">{t.photoPlaceReferenceConsentNote}</span>{!photoPlaceReferenceAvailable && <span className="mt-1 block text-xs text-ink/70">{t.photoPlaceReferenceConsentUnavailable}</span>}</span>
        </label>
        {afterResult ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <button type="button" onClick={start} disabled={busy} aria-describedby="rediagnose-note" className="rounded-sm border border-ink/50 px-4 py-2 hover:bg-ink/10 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:cursor-not-allowed disabled:opacity-60">{t.rediagnose}</button>
            <p id="rediagnose-note" className="text-sm text-ink/70">{t.rediagnoseNote}</p>
          </div>
        ) : <button
          type="button"
          onClick={start}
          disabled={busy}
          className="inline-flex items-center gap-3 rounded-sm bg-seeker px-6 py-3 font-display text-lg text-paper shadow-[4px_4px_0_var(--color-ink)] transition-transform hover:-translate-y-0.5 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink active:translate-y-0.5 active:shadow-none disabled:cursor-not-allowed disabled:opacity-60 disabled:shadow-none"
        >
          {busy && (
            <span
              aria-hidden
              className="size-4 animate-spin rounded-full border-2 border-paper border-t-transparent motion-reduce:animate-none"
            />
          )}
          {t.start}
        </button>}

        {/* 診断の間は専用の画面を出し、done で捜査ボードに切り替える */}
        {status && <DiagnoseLoading active={busy} posts={posts} found={found} status={status} />}
        {phase.kind === "error" && (
          <p role="alert" className="mt-4 border-l-4 border-seeker bg-seeker/10 px-4 py-3">
            {phase.message}
          </p>
        )}
    </div>
  );

  return (
    <section aria-labelledby="diagnose-heading" aria-busy={busy} className="mt-12 space-y-8">
      <h2 id="diagnose-heading" className="sr-only">
        {t.heading}
      </h2>
      {!busy && result && (
        <Reveal posts={livePosts} clues={result.clues} conclusions={visibleConclusions} profileClaims={visibleProfileClaims} excludedPostIds={excluded}>
          {risky && <PlanSummary risky={risky.filter((post) => !excluded.has(post.post_id))} targetId={RISKY_HEADING_ID} />}
        </Reveal>
      )}
      {(busy || !result) && controls(false)}

      {!busy && result && (
        <ConclusionBoard
          clues={result.clues}
          photoPlaceResults={result.photoPlaceResults?.filter((item) => !excluded.has(item.post_id))}
          conclusions={simulation ? validNameConclusions(simulation.after) : result.conclusions}
          unknown={simulation?.broken}
          profileClaims={visibleProfileClaims}
          profileRelations={result.profileRelations}
          deletedPostIds={simulation?.delete ?? []}
          profileClaimSuggestions={visibleProfileClaimSuggestions}
          posts={livePosts}
          webFacts={result.webFacts}
          externalLookupStatus={result.externalLookupStatus}
          externalProfileResults={result.externalProfileResults}
          ownerProfileText={result.ownerProfileText}
          selfReportClues={result.selfReportClues}
        />
      )}

      {!busy && result && risky && (
        <RiskyPosts posts={livePosts} risky={risky.filter((post) => !deleted.has(post.post_id))} clues={result.clues} clueCount={result.clues.length} profileClaims={visibleProfileClaims} conclusions={result.conclusions} onSimulated={setSimulation} onDeleted={(deletion) => setDeleted((prev) => new Set([...prev, ...deletion.delete.filter((id) => !deletion.failed.includes(id))]))} onSessionExpired={expire} />
      )}
      {!busy && result && <ResultShare />}
      {!busy && result && controls(true)}

      {posts.length > 0 && (busy || !result) && postList}
      {posts.length > 0 && !busy && result && (
        <details className="max-w-2xl">
          <summary className="cursor-pointer font-bold">{t.postsSummary(posts.length)}</summary>
          <div className="mt-5">{postList}</div>
        </details>
      )}
    </section>
  );
}
