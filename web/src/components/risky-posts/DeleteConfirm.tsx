"use client";

import { useEffect, useRef } from "react";

import { messages } from "@/lib/messages";

const t = messages.risky;

interface DeleteConfirmProps {
  /** 消す投稿の、画面に見せる抜粋 */
  excerpts: readonly string[];
  pending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Bluesky から実際に消す前の確認。元に戻せないので、消す投稿を並べて見せ、最初は「やめる」に焦点を置く。
 * Esc や外側のクリックでも閉じる（消している間は閉じない）。
 */
export function DeleteConfirm({ excerpts, pending, onConfirm, onCancel }: DeleteConfirmProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !pending) onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending, onCancel]);

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-paper/80 px-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !pending) onCancel();
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-confirm-heading"
        aria-describedby="delete-confirm-lead"
        className="w-full max-w-lg space-y-4 rounded-sm border border-seeker bg-paper-deep px-6 py-6 shadow-[6px_6px_0_oklch(5%_0.03_265)]"
      >
        <h4 id="delete-confirm-heading" className="font-display text-2xl text-seeker">
          {t.confirmHeading}
        </h4>
        <p id="delete-confirm-lead">{t.confirmLead(excerpts.length)}</p>
        <ul aria-label={t.confirmListLabel} className="space-y-2 border-l-4 border-seeker/60 pl-4 text-sm text-ink/80">
          {excerpts.map((text, i) => (
            <li key={i} className="break-words">
              {text}
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap justify-end gap-3 pt-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            disabled={pending}
            className="rounded-sm border border-ink/40 px-4 py-2 transition-colors hover:bg-ink/10 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:cursor-not-allowed disabled:opacity-60"
          >
            {t.cancel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="inline-flex items-center gap-3 rounded-sm bg-seeker px-5 py-2 font-display text-paper focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending && (
              <span
                aria-hidden
                className="size-4 animate-spin rounded-full border-2 border-paper border-t-transparent motion-reduce:animate-none"
              />
            )}
            {t.confirm}
          </button>
        </div>
        {pending && (
          <p role="status" className="text-sm text-ink/70">
            {t.deleting}
          </p>
        )}
      </div>
    </div>
  );
}
