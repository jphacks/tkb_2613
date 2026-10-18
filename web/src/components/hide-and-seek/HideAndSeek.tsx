"use client";

import { useEffect, useState } from "react";

import { ResultFrame } from "@/components/result-frame/ResultFrame";
import { ACCEPTED_IMAGE_TYPES, ApiError, detectClues } from "@/lib/api";
import type { Clue } from "@/types/clue";

type Phase =
  | { kind: "idle" }
  | { kind: "searching" }
  | { kind: "found"; clues: readonly Clue[] }
  | { kind: "error"; message: string };

interface Photo {
  file: File;
  url: string;
}

/** 写真を選び、AI に探させ、結果を表示する。写真はブラウザのメモリ上だけで扱う。 */
export function HideAndSeek() {
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  useEffect(() => {
    if (!photo) return;
    return () => URL.revokeObjectURL(photo.url);
  }, [photo]);

  function choose(file: File | undefined) {
    setPhase({ kind: "idle" });
    setPhoto(file ? { file, url: URL.createObjectURL(file) } : null);
  }

  async function search() {
    if (!photo) return;
    setPhase({ kind: "searching" });
    try {
      const { clues } = await detectClues(photo.file);
      setPhase({ kind: "found", clues });
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "うまく探せませんでした";
      setPhase({ kind: "error", message });
    }
  }

  return (
    <div className="space-y-10">
      <section aria-label="写真の選択" className="flex flex-wrap items-end gap-4">
        <label className="cursor-pointer rounded-sm border-2 border-ink bg-paper px-5 py-3 font-bold transition-transform hover:-translate-y-0.5 focus-within:outline-3 focus-within:outline-offset-2 focus-within:outline-seeker active:translate-y-0">
          写真を選ぶ
          <input
            type="file"
            accept={ACCEPTED_IMAGE_TYPES.join(",")}
            className="sr-only"
            onChange={(e) => choose(e.target.files?.[0])}
          />
        </label>
        <button
          type="button"
          onClick={search}
          disabled={!photo || phase.kind === "searching"}
          className="rounded-sm bg-seeker px-6 py-3 font-display text-lg text-paper shadow-[4px_4px_0_var(--color-ink)] transition-transform hover:-translate-y-0.5 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink active:translate-y-0.5 active:shadow-none disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
        >
          もういいかい？
        </button>
        {phase.kind === "searching" && (
          <p role="status" className="text-ink/70">
            さがしています…
          </p>
        )}
      </section>

      {phase.kind === "error" && (
        <p role="alert" className="border-l-4 border-seeker bg-seeker/10 px-4 py-3">
          {phase.message}
        </p>
      )}

      {photo && phase.kind === "found" && (
        <section aria-labelledby="found-heading" className="space-y-6">
          <h2 id="found-heading" className="font-display text-4xl text-seeker">
            みーつけた
          </h2>
          <ResultFrame imageUrl={photo.url} clues={phase.clues} />
        </section>
      )}

      {photo && phase.kind !== "found" && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={photo.url} alt="選んだ写真のプレビュー" className="max-h-[60vh] w-auto rounded-sm border border-ink/15" />
      )}
    </div>
  );
}
