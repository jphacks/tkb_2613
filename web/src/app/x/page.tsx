"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { ConclusionBoard } from "@/components/conclusion-board/ConclusionBoard";
import { PostCard } from "@/components/post-list/PostCard";
import { isDiagnosisSnapshot, isSimulation, type DiagnosisSnapshot, type Simulation } from "@/types/diagnose";

type XDiagnosis = DiagnosisSnapshot & { readonly elapsed_ms?: number; readonly mock?: boolean };
type XConfig = { mock_enabled: boolean; gpu_demo_enabled: boolean; live_enabled: boolean; max_posts: number };
type XSession = { username: string; mock: boolean };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isConfig(value: unknown): value is XConfig {
  return isRecord(value) && typeof value.mock_enabled === "boolean" &&
    typeof value.gpu_demo_enabled === "boolean" &&
    typeof value.live_enabled === "boolean" && typeof value.max_posts === "number";
}

function isSession(value: unknown): value is XSession {
  return isRecord(value) && typeof value.username === "string" && typeof value.mock === "boolean";
}

async function call(path: string, method: "GET" | "POST" | "DELETE" = "GET", body?: unknown): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`/api/x/${path}`, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.timeout(path === "diagnose" ? 2_100_000 : 20_000),
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    if (cause instanceof Error && (cause.name === "TimeoutError" || cause.name === "AbortError")) {
      throw new Error("通信がタイムアウトしました。時間を置いて再度お試しください。");
    }
    throw new Error("通信に失敗しました。接続を確認して再度お試しください。");
  }
  if (!response.ok) {
    if (response.status === 504) throw new Error("通信がタイムアウトしました。時間を置いて再度お試しください。");
    if (response.status === 429 || response.status === 503) throw new Error("X APIまたはモデルが混雑しています。時間を置いてください。");
    if (response.status === 403) throw new Error("この操作は現在利用できません。Xの用途承認と設定を確認してください。");
    if (response.status === 401) throw new Error("Xにログインし直してください。");
    throw new Error("操作に失敗しました。再度お試しください。");
  }
  if (response.status === 204) return null;
  return response.json() as Promise<unknown>;
}

function requireDiagnosis(value: unknown): XDiagnosis {
  if (!isDiagnosisSnapshot(value)) throw new Error("診断結果を読み取れませんでした。");
  return value as XDiagnosis;
}

export default function XPage() {
  const [config, setConfig] = useState<XConfig | null>(null);
  const [session, setSession] = useState<XSession | null>(null);
  const [consent, setConsent] = useState(false);
  const [original, setOriginal] = useState<XDiagnosis | null>(null);
  const [view, setView] = useState<XDiagnosis | null>(null);
  const [selected, setSelected] = useState<readonly string[]>([]);
  const [preview, setPreview] = useState<Simulation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const settings = await call("config");
        if (!isConfig(settings)) throw new Error("X診断の設定を読み取れませんでした。");
        if (active) setConfig(settings);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "接続に失敗しました。");
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
    setError("");
    try { await action(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "操作に失敗しました。"); }
    finally { setBusy(false); }
  }

  function toggle(postId: string) {
    setSelected((current) => current.includes(postId)
      ? current.filter((id) => id !== postId) : [...current, postId]);
    setPreview(null);
  }

  const current = view ?? original;
  return (
    <main className="mx-auto max-w-4xl px-5 py-12">
      <Link href="/" className="text-sm underline">みーつけたに戻る</Link>
      <header className="mt-8 border-b border-ink/30 pb-8">
        <p className="text-sm tracking-widest text-ink/60">X / 本人投稿の診断</p>
        <h1 className="mt-3 font-display text-4xl">Xで、みーつけた</h1>
        <p className="mt-4 max-w-2xl text-ink/75">
          自分の投稿本文から手がかりを探し、投稿を組み合わせて分かることを表示します。
          結果は推定です。Xへの投稿削除は行いません。
        </p>
      </header>

      {!session && (
        <section className="mt-10 max-w-2xl space-y-5" aria-label="X診断の開始">
          <label className="flex gap-3 rounded-sm border border-ink/30 bg-paper-deep p-4">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>自分の投稿を診断し、本文と投稿時刻から手がかり・推定を作ることに同意します。実投稿はローカルOllamaにのみ渡し、結果はログアウトまたは30分で消えます。</span>
          </label>
          <p className="text-sm text-ink/70">X APIの読み取りは従量課金です。現在の概算は本人確認 $0.010、投稿1件 $0.005、最大30件で約 $0.16 です。</p>
          <div className="flex flex-wrap gap-3">
            {config?.mock_enabled && <button type="button" disabled={!consent || busy}
              className="rounded-sm bg-seeker px-5 py-3 font-bold text-paper disabled:opacity-50"
              onClick={() => void perform(async () => {
                const data = await call("mock/session", "POST", { consent: true });
                if (!isSession(data)) throw new Error("接続状態を読み取れませんでした。");
                setSession(data);
              })}>架空のX投稿で試す</button>}
            {config?.gpu_demo_enabled && <button type="button" disabled={!consent || busy}
              className="rounded-sm border border-ink px-5 py-3 font-bold disabled:opacity-50"
              onClick={() => void perform(async () => {
                const data = await call("mock/gpu-session", "POST", { consent: true });
                if (!isSession(data)) throw new Error("接続状態を読み取れませんでした。");
                setSession(data);
              })}>架空のX投稿をGPUで診断</button>}
            {config?.live_enabled && <button type="button" disabled={!consent || busy}
              className="rounded-sm border border-ink px-5 py-3 font-bold disabled:opacity-50"
              onClick={() => void perform(async () => {
                const data = await call("start", "POST", { consent: true });
                if (!isRecord(data) || typeof data.authorize_url !== "string" ||
                    new URL(data.authorize_url).origin !== "https://x.com") {
                  throw new Error("Xの認証先を確認できませんでした。");
                }
                window.location.assign(data.authorize_url);
              })}>Xでログイン</button>}
          </div>
          {!config?.mock_enabled && !config?.live_enabled && <p>現在、X診断は公開準備中です。</p>}
        </section>
      )}

      {session && <section className="mt-9 space-y-5" aria-label="Xアカウント">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-sm bg-paper-deep p-4">
          <p><span className="mr-2 inline-block bg-ink px-2 py-0.5 font-bold text-paper">X</span>
            {session.mock ? session.username : `@${session.username}`}</p>
          <button type="button" disabled={busy} className="text-sm underline" onClick={() => void perform(async () => {
            await call("session", "DELETE");
            setSession(null); setOriginal(null); setView(null); setSelected([]); setPreview(null);
          })}>ログアウト</button>
        </div>
        {!original && <button type="button" disabled={busy}
          className="rounded-sm bg-seeker px-6 py-3 font-bold text-paper disabled:opacity-50"
          onClick={() => void perform(async () => {
            const result = requireDiagnosis(await call("diagnose", "POST"));
            setOriginal(result); setView(result);
          })}>{busy ? "診断中…" : "診断する"}</button>}
      </section>}

      {error && <p role="alert" className="mt-6 border-l-4 border-seeker p-3">{error}</p>}

      {original && current && <div className="mt-12 space-y-10">
        <div aria-live="polite" className="border-l-4 border-seeker bg-paper-deep p-4">
          <p className="font-bold">{view === original ? "診断結果" : "仮除外後の再診断"}</p>
          <p className="text-sm text-ink/70">投稿 {current.posts.length} 件・手がかり {current.clues.length} 件・推定 {current.conclusions.length} 件
            {typeof original.elapsed_ms === "number" && view === original ? `・処理 ${original.elapsed_ms} ms` : ""}</p>
        </div>
        <ConclusionBoard clues={current.clues} conclusions={current.conclusions} unknown={preview?.broken} />

        <section aria-labelledby="x-evidence-heading" className="space-y-4">
          <h2 id="x-evidence-heading" className="font-display text-xl">推定の根拠投稿</h2>
          {current.conclusions.map((conclusion, index) => <article key={`${conclusion.rule}-${index}`}
            className="border border-ink/20 bg-paper-deep p-4">
            <h3 className="font-bold">{conclusion.attribute}：{conclusion.value}</h3>
            <ul className="mt-3 space-y-2 text-sm">
              {conclusion.clue_indices.map((clueIndex) => {
                const clue = current.clues[clueIndex];
                const post = current.posts.find((item) => item.post_id === clue?.post_id);
                return clue && post ? <li key={clueIndex} className="border-l-2 border-seeker pl-3">
                  <span className="block text-ink/60">投稿 {post.post_id}・{new Date(post.created_at).toLocaleString("ja-JP")}</span>
                  <span>根拠「{clue.quote ?? clue.value}」</span>
                </li> : null;
              })}
            </ul>
          </article>)}
        </section>

        <section aria-labelledby="x-posts-heading" className="space-y-4">
          <h2 id="x-posts-heading" className="font-display text-xl">診断した投稿</h2>
          <p className="text-sm text-ink/70">投稿を選んで仮除外できます。X上の投稿は削除されません。</p>
          <ol className="space-y-5">{original.posts.map((post) => <li key={post.post_id}
            className={selected.includes(post.post_id) ? "rounded-sm border border-seeker p-3" : "p-3"}>
            <label className="mb-3 flex items-center gap-2 text-sm">
              <input type="checkbox" checked={selected.includes(post.post_id)} onChange={() => toggle(post.post_id)} />
              仮除外する
            </label>
            <PostCard post={post} found={{ clues: original.clues.filter((clue) => clue.post_id === post.post_id), error: null }} />
          </li>)}</ol>
          <div className="flex flex-wrap gap-3">
            <button type="button" disabled={!selected.length || busy} className="rounded-sm border border-ink px-4 py-2 disabled:opacity-50"
              onClick={() => void perform(async () => {
                const result = await call("simulate", "POST", { delete: selected });
                if (!isSimulation(result, original.clues.length)) throw new Error("仮除外の結果を読み取れませんでした。");
                setPreview(result);
              })}>仮除外を試す</button>
            <button type="button" disabled={!selected.length || busy} className="rounded-sm bg-seeker px-4 py-2 font-bold text-paper disabled:opacity-50"
              onClick={() => void perform(async () => {
                const result = requireDiagnosis(await call("rediagnose", "POST", { delete: selected }));
                setView(result); setPreview(null);
              })}>選択した投稿を除いて再診断</button>
            {view !== original && <button type="button" className="underline" onClick={() => { setView(original); setPreview(null); setSelected([]); }}>全投稿の結果に戻す</button>}
          </div>
          {preview && <p role="status">仮除外で不明になる項目：{preview.broken.length ? preview.broken.join("、") : "ありません"}</p>}
        </section>
      </div>}
    </main>
  );
}
