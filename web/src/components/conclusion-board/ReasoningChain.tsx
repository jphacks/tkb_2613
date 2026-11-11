import { messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import type { Post } from "@/types/post";

const t = messages.board.chain;

/** 投稿の本文はこの文字数で切って見せる */
const EXCERPT_LENGTH = 60;

interface ReasoningChainProps {
  conclusion: Conclusion;
  clues: readonly Clue[];
  posts: readonly Post[];
}

interface Step {
  post: Post | undefined;
  postId: string;
  clues: Clue[];
}

/** 根拠の手がかりを、出てきた順に投稿ごとにまとめる */
function stepsOf(conclusion: Conclusion, clues: readonly Clue[], posts: readonly Post[]): Step[] {
  const byId = new Map(posts.map((p) => [p.post_id, p]));
  const steps: Step[] = [];
  for (const index of new Set(conclusion.clue_indices)) {
    const clue = clues[index];
    if (!clue) continue;
    const step = steps.find((s) => s.postId === clue.post_id);
    if (step) step.clues.push(clue);
    else steps.push({ post: byId.get(clue.post_id), postId: clue.post_id, clues: [clue] });
  }
  return steps;
}

function excerpt(text: string): string {
  if (!text) return t.noText;
  return text.length > EXCERPT_LENGTH ? `${text.slice(0, EXCERPT_LENGTH)}…` : text;
}

/**
 * 推理の連鎖を「この投稿 → この手がかり → この推定」の順にたどる。
 * 使うのは本人の投稿と、そこから取った手がかりだけ（外の Web は見ない）。
 */
export function ReasoningChain({ conclusion, clues, posts }: ReasoningChainProps) {
  const steps = stepsOf(conclusion, clues, posts);
  if (steps.length === 0) return null;
  const label = messages.board.attributeLabels[conclusion.attribute] ?? conclusion.attribute;
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer font-bold underline-offset-4 hover:underline focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink">
        {t.summary}
      </summary>
      <ol aria-label={t.label} className="mt-2 space-y-2 border-l-2 border-ink/20 pl-4">
        {steps.map((step) => (
          <li key={step.postId}>
            <p className="text-xs tracking-widest text-ink/60">{t.post}</p>
            <p className="break-words">{excerpt(step.post?.text ?? "")}</p>
            <ul aria-label={t.clue} className="mt-1 space-y-0.5">
              {step.clues.map((clue, i) => (
                <li key={i}>
                  <span aria-hidden className="mr-1 text-ink/40">↳</span>
                  <span className="text-xs text-ink/60">
                    {t.clue}・{messages.clues.typeLabels[clue.type]}
                    {clue.image_index !== null && `（${t.photo(clue.image_index + 1)}）`}
                  </span>{" "}
                  {clue.value}
                </li>
              ))}
            </ul>
          </li>
        ))}
        <li>
          <p className="text-xs tracking-widest text-ink/60">
            <span aria-hidden className="mr-1">→</span>
            {t.conclusion}・{label}
          </p>
          <p className="font-bold">{conclusion.value}</p>
          {conclusion.note && <p className="text-ink/70">{conclusion.note}</p>}
        </li>
      </ol>
    </details>
  );
}
