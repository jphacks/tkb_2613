"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { useSession } from "@/components/session/SessionProvider";
import { ApiError, checkDraft, MAX_IMAGE_BYTES } from "@/lib/api";
import { CLUE_LABELS } from "@/lib/clueLabels";
import type { DraftCheckResponse } from "@/types/draftCheck";

const SOURCE_LABELS = { ocr: "OCR", vlm: "写真の読み取り", alt: "画像alt", text: "本文の読み取り", profile_text: "プロフィール文", meta: "投稿情報" } as const;

export function DraftCheckPanel() {
  const { state: session } = useSession();
  if (session.status !== "authenticated") return null;
  return <AuthenticatedDraftCheckPanel key={session.session.did} />;
}

function AuthenticatedDraftCheckPanel() {
  const [text, setText] = useState("");
  const [photo, setPhoto] = useState<File | undefined>();
  const [result, setResult] = useState<DraftCheckResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    return () => controller.current?.abort();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setError(null);
    setResult(null);
    setBusy(true);
    try {
      const response = await checkDraft(text, photo, { signal: current.signal });
      if (!current.signal.aborted) setResult(response);
    } catch (cause) {
      if (!current.signal.aborted) {
        setError(cause instanceof ApiError ? cause.message : "下書きを確認できませんでした");
      }
    } finally {
      if (!current.signal.aborted) setBusy(false);
    }
  }

  return (
    <section aria-labelledby="draft-check-heading" aria-busy={busy} className="mt-16 max-w-3xl space-y-6">
      <div>
        <h2 id="draft-check-heading" className="font-display text-2xl text-seeker">投稿前に手がかりを確認</h2>
        <p className="mt-2 max-w-2xl text-sm text-ink/70">
          下書きの本文や写真から見える手がかりを、あなたの過去の投稿と照らします。場所から自宅や最寄り駅を推定する機能ではありません。
          下書きは保存・投稿されず、同じ手がかりが見つかった投稿だけを表示します。
        </p>
      </div>
      <form onSubmit={submit} className="space-y-4">
        <label className="block space-y-2">
          <span className="font-bold">本文</span>
          <textarea
            value={text}
            onChange={(event) => { setText(event.target.value); setResult(null); }}
            maxLength={10_000}
            rows={5}
            className="w-full rounded-sm border-2 border-ink bg-paper-deep px-3 py-2 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-seeker"
          />
        </label>
        <div className="block space-y-2">
          <label className="block space-y-2">
            <span className="block font-bold">写真（1枚まで）</span>
            <input
              ref={photoInput}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
              aria-describedby="draft-photo-help"
              onChange={(event) => { setPhoto(event.target.files?.[0]); setResult(null); }}
              className="block max-w-full text-sm"
            />
          </label>
          <span id="draft-photo-help" className="block text-xs text-ink/60">20MBまで。写真は確認中だけメモリ上で扱います。</span>
        </div>
        <button
          type="submit"
          disabled={busy || (!text.trim() && !photo) || (photo?.size ?? 0) > MAX_IMAGE_BYTES}
          className="rounded-sm bg-seeker px-5 py-2.5 font-bold text-paper shadow-[3px_3px_0_var(--color-ink)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "投稿を照合しています…" : "過去の投稿と照合"}
        </button>
      </form>
      {error && <p role="alert" className="border-l-4 border-seeker bg-seeker/10 px-4 py-3">{error}</p>}
      {result && (
        <div role="status" className="space-y-4">
          <p className="text-sm text-ink/70">
            {result.mock_mode
              ? `デモ用の架空投稿 ${result.posts_checked} 件を確認しました。`
              : `本人の過去の投稿 ${result.posts_checked} 件を確認しました。`}
          </p>
          {result.notices.map((notice) => (
            <p key={notice} className="rounded-sm border border-ink/30 px-3 py-2 text-sm text-ink/70">
              {notice}
            </p>
          ))}
          {result.overlaps.length === 0 ? (
            <p className="rounded-sm border border-ink/30 p-4">
              {result.mock_mode ? "同じ手がかりの文字列は見つかりませんでした。" : "同じ種類・表記の手がかりは見つかりませんでした。"}
            </p>
          ) : (
            <ul aria-label="過去の投稿と重なる手がかり" className="space-y-3">
              {result.overlaps.map((overlap, index) => (
                <li key={`${overlap.clue.type}-${overlap.clue.value}-${index}`} className="rounded-sm border border-ink/30 bg-paper-deep p-4">
                  <p className="font-bold">{CLUE_LABELS[overlap.clue.type]}：{overlap.clue.value}</p>
                  <p className="mt-1 text-xs text-ink/60">
                    {result.mock_mode
                      ? "モックの本文文字列照合"
                      : `下書きからの観測：${SOURCE_LABELS[overlap.clue.source]}`}
                  </p>
                  <ul className="mt-3 space-y-1 border-t border-ink/20 pt-2 text-sm">
                    {overlap.evidence.map((evidence) => (
                      <li key={evidence.post_id}>
                        過去の投稿 {new Date(evidence.created_at).toLocaleDateString("ja-JP")} に
                        {result.mock_mode ? "同じ文字列" : "同じ手がかり"}
                        <span className="ml-2 break-all text-xs text-ink/60">{evidence.post_id}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
