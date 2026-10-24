import { CLUE_LABELS } from "@/lib/clueLabels";
import type { Clue } from "@/types/clue";

interface ClueListProps {
  clues: readonly Clue[];
  /** 取り出しに失敗したときの理由 */
  error?: string | null;
  label: string;
}

/** 投稿 1 件から取り出した手がかりの一覧。種類・値・確からしさを出す。 */
export function ClueList({ clues, error, label }: ClueListProps) {
  if (error) {
    return (
      <p className="border-l-4 border-ink/30 bg-ink/5 px-3 py-2 text-sm text-ink/70">
        手がかりを探せませんでした（{error}）
      </p>
    );
  }
  if (clues.length === 0) {
    return <p className="text-sm text-ink/60">手がかりは見つかりませんでした</p>;
  }
  return (
    <ul aria-label={label} className="flex flex-wrap gap-2">
      {clues.map((clue, i) => (
        <li
          key={i}
          className="inline-flex items-baseline gap-2 rounded-sm border border-seeker/40 bg-seeker/10 px-2.5 py-1 text-sm"
        >
          <span className="text-xs tracking-widest text-ink/60">{CLUE_LABELS[clue.type]}</span>
          <span className="font-bold">{clue.value}</span>
          <span className="tabular-nums text-xs text-ink/60">{Math.round(clue.confidence * 100)}%</span>
        </li>
      ))}
    </ul>
  );
}
