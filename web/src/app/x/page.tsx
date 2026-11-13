"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PostCard } from "@/components/post-list/PostCard";
import { XPostCard } from "@/components/x/XPostCard";
import { HIGHLIGHT_LABEL } from "@/components/x/XPostCard";
import { isHighlights, isXDisplay, type XDisplay, type XHighlight, type XPostDisplay } from "@/lib/xDisplay";
import { isPost, type Post } from "@/types/post";

type PublicInfoCategory = "place" | "station" | "weekday" | "time" | "school";
type PublicInfoEvidence = { readonly post_id: string; readonly quote: string };
type PublicInfoItem = {
  readonly category: PublicInfoCategory;
  readonly value: string;
  readonly count: number;
  readonly evidence: readonly PublicInfoEvidence[];
};
type PostError = { readonly post_id: string; readonly error: string };
type XDiagnosis = {
  readonly posts: readonly Post[];
  readonly information: readonly PublicInfoItem[];
  readonly post_errors?: readonly PostError[];
  readonly x_display?: XDisplay;
  // highlight は地名・駅名の位置だけで、値ごとに数えない（X_INFO_VIEW）
  readonly view?: "aggregate" | "highlight" | "posts";
  readonly highlights?: Readonly<Record<string, readonly XHighlight[]>>;
  readonly elapsed_ms?: number;
  readonly mock?: boolean;
};
type XSimulation = {
  readonly delete: readonly string[];
  readonly before: readonly PublicInfoItem[];
  readonly after: readonly PublicInfoItem[];
  readonly removed: readonly { readonly category: PublicInfoCategory; readonly value: string }[];
};
type XConfig = { mock_enabled: boolean; live_enabled: boolean; max_posts: number };
type XSession = { username: string; mock: boolean };

const CATEGORY_LABEL: Record<PublicInfoCategory, string> = {
  place: "地名",
  station: "駅名",
  weekday: "曜日",
  time: "時刻",
  school: "学校名",
};
const CATEGORIES = new Set(Object.keys(CATEGORY_LABEL));
const NO_DISPLAY: XPostDisplay = { permalink: null, edited: false, entities: [] };
const NO_HIGHLIGHTS: readonly XHighlight[] = [];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isConfig(value: unknown): value is XConfig {
  return isRecord(value) && typeof value.mock_enabled === "boolean" &&
    typeof value.live_enabled === "boolean" && typeof value.max_posts === "number";
}

function isSession(value: unknown): value is XSession {
  return isRecord(value) && typeof value.username === "string" && typeof value.mock === "boolean";
}

function isPublicInfo(value: unknown): value is PublicInfoItem {
  return isRecord(value) && typeof value.category === "string" && CATEGORIES.has(value.category) &&
    typeof value.value === "string" && Number.isInteger(value.count) && (value.count as number) > 0 &&
    Array.isArray(value.evidence) && value.evidence.length === value.count &&
    value.evidence.every((item) => isRecord(item) && typeof item.post_id === "string" &&
      typeof item.quote === "string");
}

function isPostErrors(value: unknown): value is readonly PostError[] {
  return value === undefined || (Array.isArray(value) && value.every((item) =>
    isRecord(item) && typeof item.post_id === "string" && typeof item.error === "string"));
}

function requireDiagnosis(value: unknown): XDiagnosis {
  if (!isRecord(value) || !Array.isArray(value.posts) || !value.posts.every(isPost) ||
      !Array.isArray(value.information) || !value.information.every(isPublicInfo) ||
      !isPostErrors(value.post_errors) ||
      (value.x_display !== undefined && !isXDisplay(value.x_display)) ||
      (value.view !== undefined && value.view !== "aggregate" && value.view !== "highlight" &&
        value.view !== "posts") ||
      (value.highlights !== undefined && !isHighlights(value.highlights))) {
    throw new Error("公開情報チェックの結果を読み取れませんでした。");
  }
  const diagnosis = value as XDiagnosis;
  if (diagnosis.view === "posts" &&
      (diagnosis.information.length > 0 || (diagnosis.highlights && Object.keys(diagnosis.highlights).length > 0) ||
        !diagnosis.x_display || diagnosis.x_display.synthetic)) {
    throw new Error("本人投稿の表示結果を読み取れませんでした。");
  }
  const posts = new Map(diagnosis.posts.map((post) => [post.post_id, post]));
  if (diagnosis.information.some((item) => item.evidence.some((evidence) =>
    !posts.get(evidence.post_id)?.text.includes(evidence.quote)))) {
    throw new Error("公開情報チェックの根拠を確認できませんでした。");
  }
  return diagnosis;
}

function requireSimulation(value: unknown): XSimulation {
  if (!isRecord(value) || !Array.isArray(value.delete) ||
      !value.delete.every((postId) => typeof postId === "string") ||
      !Array.isArray(value.before) || !value.before.every(isPublicInfo) ||
      !Array.isArray(value.after) || !value.after.every(isPublicInfo) ||
      !Array.isArray(value.removed) || !value.removed.every((item) =>
        isRecord(item) && typeof item.category === "string" && CATEGORIES.has(item.category) &&
        typeof item.value === "string")) {
    throw new Error("仮除外の結果を読み取れませんでした。");
  }
  return value as XSimulation;
}

async function call(path: string, method: "GET" | "POST" | "DELETE" = "GET", body?: unknown): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`/api/x/${path}`, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("通信に失敗しました。接続を確認して再度お試しください。");
  }
  if (!response.ok) {
    if (response.status === 403) throw new Error("実X連携は用途承認と安全設定の確認が完了するまで利用できません。");
    if (response.status === 401) throw new Error("Xにログインし直してください。");
    if (response.status === 429) throw new Error("本日のXの取得上限に達しました。日付が変わってから（UTC）お試しください。");
    if (response.status === 502) throw new Error("X APIから投稿を取得できませんでした。しばらくしてから再度お試しください。");
    if (response.status === 503) throw new Error("X APIの回数制限中、または一時的に利用できません。しばらくしてから再度お試しください。");
    throw new Error("操作に失敗しました。再度お試しください。");
  }
  if (response.status === 204) return null;
  return response.json() as Promise<unknown>;
}

export default function XPage() {
  const [config, setConfig] = useState<XConfig | null>(null);
  const [session, setSession] = useState<XSession | null>(null);
  const [consent, setConsent] = useState(false);
  const [original, setOriginal] = useState<XDiagnosis | null>(null);
  const [view, setView] = useState<XDiagnosis | null>(null);
  const [selected, setSelected] = useState<readonly string[]>([]);
  const [preview, setPreview] = useState<XSimulation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const settings = await call("config");
        if (!isConfig(settings)) throw new Error("X連携の設定を読み取れませんでした。");
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
        } catch { /* チェック前なら保存結果はない。 */ }
      } catch { /* 未ログインは通常状態。 */ }
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
  const highlightView = original?.view === "highlight";
  const livePostView = original?.view === "posts";
  const shown = new Set(current?.posts.map((post) => post.post_id));
  return (
    <main className="mx-auto max-w-4xl px-5 py-12">
      <Link href="/" className="text-sm underline">みーつけたに戻る</Link>
      <header className="mt-8 border-b border-ink/30 pb-8">
        <p className="text-sm tracking-widest text-ink/60">X / 本人投稿</p>
        <h1 className="mt-3 font-display text-4xl">自分の投稿を確認する</h1>
        <p className="mt-4 max-w-2xl text-ink/75">
          Xで本人確認したアカウントから直近の投稿を最大{config?.max_posts ?? 5}件取得し、原文のまま表示します。
          AI推論、個人情報や位置情報の抽出・集計は行いません。
        </p>
      </header>

      {!session && <section className="mt-10 max-w-2xl space-y-5" aria-label="X公開情報チェックの開始">
        <div className="rounded-sm border border-ink/30 bg-paper-deep p-4 text-sm">
          <p className="font-bold">{config?.live_enabled ? "Xの本人投稿を読み取り専用で表示します" : "現在は架空の合成投稿だけを使います"}</p>
          <p className="mt-2">{config?.live_enabled
            ? "取得した本文と日時は、このブラウザの表示とサーバーの一時メモリだけで使います。AI、抽出、集計、外部検索、投稿の変更・削除は行いません。"
            : "Xの利用目的と課金・安全設定が確認できるまで、実投稿の取得は有効になりません。"}</p>
        </div>
        <label className="flex gap-3 rounded-sm border border-ink/30 bg-paper-deep p-4">
          <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
          <span>{config?.live_enabled
            ? `利用目的を確認し、本人の投稿を最大${config.max_posts}件取得して原文表示だけに使うことに同意します。データはログアウトまたは30分で破棄されます。`
            : "利用目的を確認し、合成投稿の限定カテゴリ集計と仮除外を行うことに同意します。データと結果はログアウトまたは30分で破棄されます。"}</span>
        </label>
        <div className="flex flex-wrap gap-3">
          {config?.mock_enabled && <button type="button" disabled={!consent || busy}
            className="rounded-sm bg-seeker px-5 py-3 font-bold text-paper disabled:opacity-50"
            onClick={() => void perform(async () => {
              const data = await call("mock/session", "POST", { consent: true });
              if (!isSession(data)) throw new Error("接続状態を読み取れませんでした。");
              setSession(data);
            })}>架空のX投稿で試す</button>}
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
        {!config?.mock_enabled && !config?.live_enabled && <p>現在、X公開情報チェックは準備中です。</p>}
        {config?.live_enabled && <p className="text-sm text-ink/70">X APIの読み取りは課金対象です。実行前にDeveloper Consoleで最新単価・残高・支出上限を確認してください。</p>}
      </section>}

      {session && <section className="mt-9 space-y-5" aria-label="Xアカウント">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-sm bg-paper-deep p-4">
          <p><span className="mr-2 inline-block bg-ink px-2 py-0.5 font-bold text-paper">X</span>
            {session.mock ? session.username : `@${session.username}`}</p>
          <button type="button" disabled={busy} className="text-sm underline" onClick={() => void perform(async () => {
            await call("session", "DELETE");
            setSession(null); setOriginal(null); setView(null); setSelected([]); setPreview(null);
          })}>ログアウトしてデータを破棄</button>
        </div>
        {!original && <button type="button" disabled={busy}
          className="rounded-sm bg-seeker px-6 py-3 font-bold text-paper disabled:opacity-50"
          onClick={() => void perform(async () => {
            const result = requireDiagnosis(await call(session.mock ? "diagnose" : "posts", "POST"));
            setOriginal(result); setView(result);
          })}>{busy ? "取得中…" : session.mock ? "公開情報を確認する" : "自分の投稿を読み込む"}</button>}
      </section>}

      {error && <p role="alert" className="mt-6 border-l-4 border-seeker p-3">{error}</p>}

      {original && current && <div className="mt-12 space-y-10">
        <div aria-live="polite" className="border-l-4 border-seeker bg-paper-deep p-4">
          {livePostView ? <>
            <p className="font-bold">本人投稿の取得結果</p>
            <p className="text-sm text-ink/70">投稿 {current.posts.length} 件・原文表示のみ</p>
          </> : highlightView ? <>
            <p className="font-bold">{view === original ? "公開情報チェック結果" : "仮除外後の表示"}</p>
            <p className="text-sm text-ink/70">投稿 {current.posts.length} 件・本文中の地名と駅名に色を付けています（件数は数えません）</p>
          </> : <>
            <p className="font-bold">{view === original ? "公開情報チェック結果" : "仮除外後の再集計"}</p>
            <p className="text-sm text-ink/70">投稿 {current.posts.length} 件・明記情報 {current.information.length} 種類</p>
          </>}
          {(original.post_errors?.length ?? 0) > 0 && <p className="mt-2 text-sm">
            {original.post_errors?.length} 件の投稿は読み取れなかったため、{highlightView ? "色付けしていません" : "集計に含めていません"}。
          </p>}
        </div>

        {highlightView && <section aria-labelledby="x-highlight-heading" className="space-y-2">
          <h2 id="x-highlight-heading" className="font-display text-xl">本文の中の地名・駅名</h2>
          <p className="text-sm">投稿の本文はそのままに、
            <mark className="rounded-sm bg-seeker/20 px-1">{HIGHLIGHT_LABEL.station}</mark>と
            <mark className="ml-1 rounded-sm bg-ink/15 px-1">{HIGHLIGHT_LABEL.place}</mark>に色を付けています。
            値ごとにまとめたり数えたりはしません。</p>
        </section>}

        {!livePostView && !highlightView && <section aria-labelledby="x-information-heading" className="space-y-4">
          <h2 id="x-information-heading" className="font-display text-xl">本文に書かれている情報</h2>
          {current.information.length === 0 && <p>対象カテゴリの情報は見つかりませんでした。</p>}
          {current.information.map((item) => <article key={`${item.category}:${item.value}`}
            className="border border-ink/20 bg-paper-deep p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-bold">{CATEGORY_LABEL[item.category]}：{item.value}</h3>
              <p className="text-sm">{item.count}件の投稿に記載</p>
            </div>
            <ul className="mt-3 space-y-2 text-sm">
              {item.evidence.map((evidence) => {
                const index = current.posts.findIndex((post) => post.post_id === evidence.post_id);
                return <li key={evidence.post_id} className="border-l-2 border-seeker pl-3">
                  根拠「{evidence.quote}」
                  {index >= 0 && <a className="ml-3 underline" href={`#x-post-${index}`}>元投稿を確認</a>}
                </li>;
              })}
            </ul>
          </article>)}
        </section>}

        <section aria-labelledby="x-posts-heading" className="space-y-4">
          <h2 id="x-posts-heading" className="font-display text-xl">{livePostView ? "取得した投稿" : "確認した投稿"}</h2>
          {livePostView ? <p className="text-sm text-ink/70">Xから取得した原文です。X上の投稿は変更・削除されません。</p>
            : <p className="text-sm text-ink/70">投稿を選んで{highlightView ? "表示" : "集計"}から仮除外できます。X上の投稿は変更・削除されません。</p>}
          {livePostView && original.posts.length === 0 && <p>表示できる投稿はありません。</p>}
          <ol className="space-y-5">{original.posts.map((post, index) => <li id={`x-post-${index}`} key={post.post_id}
            className={[
              "scroll-mt-5 p-3",
              selected.includes(post.post_id) ? "rounded-sm border border-seeker" : "",
              highlightView && !shown.has(post.post_id) ? "opacity-50" : "",
            ].join(" ")}>
            {!livePostView && <label className="mb-3 flex items-center gap-2 text-sm">
              <input type="checkbox" checked={selected.includes(post.post_id)} onChange={() => toggle(post.post_id)} />
              仮除外する
              {highlightView && !shown.has(post.post_id) && <span className="ml-2 font-bold">（表示から除外中）</span>}
            </label>}
            {original.x_display
              ? <XPostCard post={post} author={original.x_display.author}
                display={original.x_display.posts[post.post_id] ?? NO_DISPLAY}
                synthetic={original.x_display.synthetic}
                highlights={highlightView ? original.highlights?.[post.post_id] ?? NO_HIGHLIGHTS : NO_HIGHLIGHTS} />
              : <PostCard post={post} />}
          </li>)}</ol>
          {!livePostView && <div className="flex flex-wrap gap-3">
            {!highlightView && <button type="button" disabled={!selected.length || busy} className="rounded-sm border border-ink px-4 py-2 disabled:opacity-50"
              onClick={() => void perform(async () => setPreview(requireSimulation(
                await call("simulate", "POST", { delete: selected }),
              )))}>仮除外後を比べる</button>}
            <button type="button" disabled={!selected.length || busy} className="rounded-sm bg-seeker px-4 py-2 font-bold text-paper disabled:opacity-50"
              onClick={() => void perform(async () => {
                setView(requireDiagnosis(await call("rediagnose", "POST", { delete: selected })));
                setPreview(null);
              })}>{highlightView ? "選択した投稿を除いて表示" : "選択した投稿を除いて再集計"}</button>
            {view !== original && <button type="button" className="underline" onClick={() => {
              setView(original); setPreview(null); setSelected([]);
            }}>全投稿の結果に戻す</button>}
          </div>}
          {preview && <div role="status" className="rounded-sm bg-paper-deep p-4 text-sm">
            <p>明記情報：{preview.before.length}種類 → {preview.after.length}種類</p>
            <p>表示から消える情報：{preview.removed.length
              ? preview.removed.map((item) => `${CATEGORY_LABEL[item.category]}「${item.value}」`).join("、")
              : "ありません"}</p>
          </div>}
        </section>
      </div>}
    </main>
  );
}
