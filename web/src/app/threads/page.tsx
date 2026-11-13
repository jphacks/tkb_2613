"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { ConclusionBoard } from "@/components/conclusion-board/ConclusionBoard";
import { PostCard } from "@/components/post-list/PostCard";
import { THREADS_TEXT, ThreadsError, type ThreadsErrorKey, type ThreadsLang } from "@/lib/threads-i18n";
import { checkThreadsPublicText } from "@/lib/threads-public-check";
import { useThreadsLang } from "@/lib/useThreadsLang";
import { isDiagnosisSnapshot, isSimulation, type DiagnosisSnapshot, type Simulation } from "@/types/diagnose";
import { isPost, type Post } from "@/types/post";
import { profileClaimsAfterDeletion } from "@/types/profile";

type ThreadsDiagnosis = DiagnosisSnapshot & { readonly elapsed_ms?: number; readonly mock?: boolean };
type ThreadsConfig = { mock_enabled: boolean; gpu_demo_enabled: boolean; live_enabled: boolean; max_posts: number };
type ThreadsSession = { username: string; mock: boolean };

const LANGUAGES: readonly { readonly code: ThreadsLang; readonly label: string }[] = [
  { code: "ja", label: "日本語" },
  { code: "en", label: "English" },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isConfig(value: unknown): value is ThreadsConfig {
  return isRecord(value) && typeof value.mock_enabled === "boolean" &&
    typeof value.gpu_demo_enabled === "boolean" &&
    typeof value.live_enabled === "boolean" && typeof value.max_posts === "number";
}

function isSession(value: unknown): value is ThreadsSession {
  return isRecord(value) && typeof value.username === "string" && typeof value.mock === "boolean";
}

function errorKeyOf(cause: unknown, fallback: ThreadsErrorKey): ThreadsErrorKey {
  return cause instanceof ThreadsError ? cause.key : fallback;
}

async function call(path: string, method: "GET" | "POST" | "DELETE" = "GET", body?: unknown): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`/api/threads/${path}`, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.timeout(path === "diagnose" ? 2_100_000 : 20_000),
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    if (cause instanceof Error && (cause.name === "TimeoutError" || cause.name === "AbortError")) {
      throw new ThreadsError("timeout");
    }
    throw new ThreadsError("network");
  }
  if (!response.ok) {
    if (response.status === 504) throw new ThreadsError("timeout");
    if (response.status === 503 && path === "diagnose") throw new ThreadsError("modelUnavailable");
    if (response.status === 429 || response.status === 503) throw new ThreadsError("busy");
    if (response.status === 403) throw new ThreadsError("forbidden");
    if (response.status === 401) throw new ThreadsError("loginAgain");
    throw new ThreadsError("failed");
  }
  if (response.status === 204) return null;
  return response.json() as Promise<unknown>;
}

function requireDiagnosis(value: unknown): ThreadsDiagnosis {
  if (!isDiagnosisSnapshot(value)) throw new ThreadsError("diagnosisUnreadable");
  return value as ThreadsDiagnosis;
}

export default function ThreadsPage() {
  const [lang, chooseLang] = useThreadsLang();
  const [config, setConfig] = useState<ThreadsConfig | null>(null);
  const [session, setSession] = useState<ThreadsSession | null>(null);
  const [consent, setConsent] = useState(false);
  const [original, setOriginal] = useState<ThreadsDiagnosis | null>(null);
  const [view, setView] = useState<ThreadsDiagnosis | null>(null);
  const [selected, setSelected] = useState<readonly string[]>([]);
  const [preview, setPreview] = useState<Simulation | null>(null);
  const [fetchedPosts, setFetchedPosts] = useState<readonly Post[] | null>(null);
  const [publicCheckDone, setPublicCheckDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ThreadsErrorKey | null>(null);
  const t = THREADS_TEXT[lang];

  useEffect(() => {
    document.documentElement.lang = t.htmlLang;
    return () => { document.documentElement.lang = "ja"; };
  }, [t.htmlLang]);

  useEffect(() => {
    let active = true;
    void (async () => {
      const authError = new URLSearchParams(window.location.search).get("auth_error");
      if (authError) {
        setError(authError === "denied" ? "authDenied" : authError === "state" ? "authState" : "authFailed");
        window.history.replaceState(null, "", "/threads");
      }
      try {
        const settings = await call("config");
        if (!isConfig(settings)) throw new ThreadsError("configUnreadable");
        if (active) setConfig(settings);
      } catch (cause) {
        if (active) setError(errorKeyOf(cause, "connectFailed"));
        return;
      }
      try {
        const connected = await call("session");
        if (!active || !isSession(connected)) return;
        setSession(connected);
        try {
          const restored = requireDiagnosis(await call("diagnosis"));
          if (active) { setOriginal(restored); setView(restored); }
        } catch { /* 診断前なら結果はない。 */ }
      } catch { /* 未ログイン時の 401 は通常状態。 */ }
    })();
    return () => { active = false; };
  }, []);

  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try { await action(); }
    catch (cause) { setError(errorKeyOf(cause, "failed")); }
    finally { setBusy(false); }
  }

  function toggle(postId: string) {
    setSelected((current) => current.includes(postId)
      ? current.filter((id) => id !== postId) : [...current, postId]);
    setPreview(null);
  }

  const current = view ?? original;
  // 仮除外を試している間は、選んだ投稿を根拠から除いた推定を出す（Bluesky の画面・GET /api/diagnosis と同じ規則）。
  // 再診断の結果は api が除いて返すので、そのまま使う
  const previewExcluded = new Set(preview?.delete ?? []);
  const profileClaims = profileClaimsAfterDeletion(current?.profile_claims ?? [], previewExcluded);
  const profileClaimSuggestions = (current?.profile_claim_suggestions ?? []).filter((id) => !previewExcluded.has(id));
  const publicFindings = fetchedPosts ? checkThreadsPublicText(fetchedPosts) : [];
  return (
    <main className="mx-auto max-w-4xl px-5 py-12">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <Link href="/" className="text-sm underline">{t.back}</Link>
        <div role="group" aria-label={t.langLabel} className="flex overflow-hidden rounded-sm border border-ink/40 text-sm">
          {LANGUAGES.map(({ code, label }) => <button key={code} type="button" lang={code}
            aria-pressed={lang === code} onClick={() => chooseLang(code)}
            className={`px-3 py-1.5 font-bold ${lang === code ? "bg-ink text-paper" : "text-ink/70 hover:text-ink"}`}>{label}</button>)}
        </div>
      </div>
      <header className="mt-8 border-b border-ink/30 pb-8">
        <p className="text-sm tracking-widest text-ink/60">{t.eyebrow}</p>
        <h1 className="mt-3 font-display text-3xl sm:text-4xl">{t.title}</h1>
        <p className="mt-4 max-w-2xl text-ink/75">{t.intro}</p>
      </header>

      {!session && (
        <section className="mt-10 max-w-2xl space-y-5" aria-label={t.startAria}>
          <label className="flex gap-3 rounded-sm border border-ink/30 bg-paper-deep p-4">
            <input type="checkbox" className="mt-1 shrink-0" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>{t.consent}</span>
          </label>
          <p className="text-sm text-ink/70">{t.noMedia}</p>
          <div className="flex flex-wrap gap-3">
            {config?.mock_enabled && <button type="button" disabled={!consent || busy}
              className="rounded-sm bg-seeker px-5 py-3 font-bold text-paper disabled:opacity-50"
              onClick={() => void perform(async () => {
                const data = await call("mock/session", "POST", { consent: true });
                if (!isSession(data)) throw new ThreadsError("sessionUnreadable");
                setSession(data);
              })}>{t.mockLogin}</button>}
            {config?.gpu_demo_enabled && <button type="button" disabled={!consent || busy}
              className="rounded-sm border border-ink px-5 py-3 font-bold disabled:opacity-50"
              onClick={() => void perform(async () => {
                const data = await call("mock/gpu-session", "POST", { consent: true });
                if (!isSession(data)) throw new ThreadsError("sessionUnreadable");
                setSession(data);
              })}>{t.gpuLogin}</button>}
            {config?.live_enabled && <button type="button" disabled={!consent || busy}
              className="rounded-sm border border-ink px-5 py-3 font-bold disabled:opacity-50"
              onClick={() => void perform(async () => {
                const data = await call("start", "POST", { consent: true });
                if (!isRecord(data) || typeof data.authorize_url !== "string" ||
                    new URL(data.authorize_url).origin !== "https://threads.net") {
                  throw new ThreadsError("authorizeUnverified");
                }
                window.location.assign(data.authorize_url);
              })}>{t.liveLogin}</button>}
          </div>
          {!config?.mock_enabled && !config?.live_enabled && <p>{t.preparing}</p>}
        </section>
      )}

      {session && <section className="mt-9 space-y-5" aria-label={t.accountAria}>
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-sm bg-paper-deep p-4">
          <p className="[overflow-wrap:anywhere]"><span className="mr-2 inline-block bg-ink px-2 py-0.5 font-bold text-paper">Threads</span>
            {session.mock ? session.username : `@${session.username}`}</p>
          <button type="button" disabled={busy} className="text-sm underline" onClick={() => void perform(async () => {
            await call("session", "DELETE");
            setSession(null); setOriginal(null); setView(null); setSelected([]); setPreview(null); setFetchedPosts(null); setPublicCheckDone(false);
          })}>{t.logout}</button>
        </div>
        {!original && <button type="button" disabled={busy}
          className="rounded-sm border border-ink px-5 py-3 font-bold disabled:opacity-50"
          onClick={() => void perform(async () => {
            const data = await call("posts");
            if (!isRecord(data) || data.mock !== session.mock || !Array.isArray(data.posts) ||
                !data.posts.every((post) => isPost(post) && post.post_id.startsWith("threads:") && post.images.length === 0)) {
              throw new ThreadsError("postsUnreadable");
            }
            setFetchedPosts(data.posts);
            setPublicCheckDone(false);
          })}>{t.reviewPosts}</button>}
        {busy && <p role="status" className="text-sm text-ink/70">{t.loading}</p>}
        {!original && fetchedPosts && <section aria-label={t.postsAria} className="space-y-4">
          <p className="text-sm text-ink/70">{t.postsFetched(fetchedPosts.length)}</p>
          <ol className="space-y-5">{fetchedPosts.map((post) => <li key={post.post_id}>
            <PostCard post={post} locale={lang} />
            <details className="mt-2 text-sm text-ink/70">
              <summary className="cursor-pointer underline underline-offset-4">{t.detailsSummary}</summary>
              <dl className="mt-2 grid gap-1 [overflow-wrap:anywhere]">
                <div><dt className="inline font-bold">{t.postId}</dt><dd className="inline">{post.post_id}</dd></div>
                <div><dt className="inline font-bold">{t.postTime}</dt><dd className="inline">{post.created_at}</dd></div>
                <div><dt className="inline font-bold">{t.media}</dt><dd className="inline">{t.mediaValue}</dd></div>
              </dl>
            </details>
          </li>)}</ol>
          <section aria-labelledby="threads-public-check" className="space-y-3 rounded-sm border border-ink/25 bg-paper-deep p-4">
            <h2 id="threads-public-check" className="font-bold">{t.checkTitle}</h2>
            <p className="text-sm text-ink/70">{t.checkIntro}</p>
            <button type="button" disabled={busy} className="rounded-sm border border-ink px-4 py-2 font-bold disabled:opacity-50"
              onClick={() => setPublicCheckDone(true)}>{t.checkButton}</button>
            {publicCheckDone && <div role="status" className="space-y-3">
              <p className="font-bold">{t.checkResult}</p>
              <p className="text-sm">{t.checkAll}</p>
              <ul className="list-disc space-y-2 pl-5 text-sm">{publicFindings.map((finding, index) => <li key={finding.postId}>
                {t.checkPost(index + 1, finding.kinds.length
                  ? finding.kinds.map((kind) => t.findingLabels[kind]).join(t.listSeparator) : t.checkNone)}
              </li>)}</ul>
              <p className="text-xs text-ink/60">{t.checkNote}</p>
            </div>}
          </section>
        </section>}
        {!original && fetchedPosts && <details className="rounded-sm border border-ink/20 p-4">
          <summary className="cursor-pointer font-bold">{t.aiSummary}</summary>
          <p className="mt-3 text-sm text-ink/70">{t.aiNote}</p>
          <button type="button" disabled={busy}
            className="mt-3 rounded-sm bg-seeker px-6 py-3 font-bold text-paper disabled:opacity-50"
            onClick={() => void perform(async () => {
              const result = requireDiagnosis(await call("diagnose", "POST"));
              setOriginal(result); setView(result);
            })}>{busy ? t.aiBusy : t.aiButton}</button>
        </details>}
      </section>}

      {error && <p role="alert" className="mt-6 border-l-4 border-seeker p-3">{t.errors[error]}</p>}

      {original && current && <div className="mt-12 space-y-10">
        <div aria-live="polite" className="border-l-4 border-seeker bg-paper-deep p-4">
          <p className="font-bold">{view === original ? t.resultFull : t.resultRe}</p>
          <p className="text-sm text-ink/70">{t.resultCount(current.posts.length, current.clues.length, current.conclusions.length)}
            {typeof original.elapsed_ms === "number" && view === original ? t.elapsed(original.elapsed_ms) : ""}</p>
        </div>
        <ConclusionBoard key={view === original ? "full" : "rediagnosed"} clues={current.clues}
          conclusions={current.conclusions} unknown={preview?.broken} posts={current.posts}
          profileClaims={profileClaims} profileClaimSuggestions={profileClaimSuggestions} />

        <section aria-labelledby="threads-evidence-heading" className="space-y-4">
          <h2 id="threads-evidence-heading" className="font-display text-xl">{t.evidenceTitle}</h2>
          {current.conclusions.map((conclusion, index) => <article key={`${conclusion.rule}-${index}`}
            className="border border-ink/20 bg-paper-deep p-4">
            <h3 className="font-bold">{conclusion.attribute}：{conclusion.value}</h3>
            <ul className="mt-3 space-y-2 text-sm">
              {conclusion.clue_indices.map((clueIndex) => {
                const clue = current.clues[clueIndex];
                const post = current.posts.find((item) => item.post_id === clue?.post_id);
                return clue && post ? <li key={clueIndex} className="border-l-2 border-seeker pl-3">
                  <span className="block text-ink/60 [overflow-wrap:anywhere]">{t.postRef(post.post_id, new Date(post.created_at).toLocaleString(t.dateLocale))}</span>
                  <span>{t.basis(clue.quote ?? clue.value)}</span>
                </li> : null;
              })}
            </ul>
          </article>)}
        </section>

        <section aria-labelledby="threads-posts-heading" className="space-y-4">
          <h2 id="threads-posts-heading" className="font-display text-xl">{t.postsTitle}</h2>
          <p className="text-sm text-ink/70">{t.postsNote}</p>
          <ol className="space-y-5">{original.posts.map((post) => <li key={post.post_id}
            className={selected.includes(post.post_id) ? "rounded-sm border border-seeker p-3" : "p-3"}>
            <label className="mb-3 flex items-center gap-2 text-sm">
              <input type="checkbox" checked={selected.includes(post.post_id)} onChange={() => toggle(post.post_id)} />
              {t.exclude}
            </label>
            <PostCard post={post} locale={lang} found={{ clues: original.clues.filter((clue) => clue.post_id === post.post_id), error: null }} />
          </li>)}</ol>
          <div className="flex flex-wrap gap-3">
            <button type="button" disabled={!selected.length || busy} className="rounded-sm border border-ink px-4 py-2 disabled:opacity-50"
              onClick={() => void perform(async () => {
                const result = await call("simulate", "POST", { delete: selected });
                if (!isSimulation(result, original.clues.length)) throw new ThreadsError("simulationUnreadable");
                setPreview(result);
              })}>{t.simulate}</button>
            <button type="button" disabled={!selected.length || busy} className="rounded-sm bg-seeker px-4 py-2 font-bold text-paper disabled:opacity-50"
              onClick={() => void perform(async () => {
                const result = requireDiagnosis(await call("rediagnose", "POST", { delete: selected }));
                setView(result); setPreview(null);
              })}>{t.rediagnose}</button>
            {view !== original && <button type="button" className="underline" onClick={() => { setView(original); setPreview(null); setSelected([]); }}>{t.showAll}</button>}
          </div>
          {preview && <p role="status">{t.brokenItems(preview.broken.length ? preview.broken.join(t.listSeparator) : t.none)}</p>}
        </section>
      </div>}
    </main>
  );
}
