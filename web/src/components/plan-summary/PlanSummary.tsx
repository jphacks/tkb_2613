import { attributeLabel, messages } from "@/lib/messages";
import type { RiskyPost } from "@/types/diagnose";

const t = messages.plan;

/** 4段階のうち、結果を見ている今いる段階（まーだだよ：消す投稿を選ぶ） */
const CURRENT_STEP = 2;

interface PlanSummaryProps {
  /** 診断の plan の投稿（消した投稿は除いたもの） */
  risky: readonly RiskyPost[];
  /** 「消す投稿を見る」で飛ぶ先（まーだだよ の見出しの id） */
  targetId: string;
}

/** 1件ずつ消したときに崩れる項目を、重ねずに並べる（全部消せば少なくともこれらは崩れる） */
function brokenLabels(risky: readonly RiskyPost[]): string {
  const attributes = [...new Set(risky.flatMap((r) => r.broken))];
  return attributes.map((a) => attributeLabel(a)).join("・");
}

/**
 * 結果の先頭に置く要約。いちばん大事な「どの投稿を消せばよいか」を、長い結果を読む前に示し、
 * まーだだよ の一覧へ飛べるようにする。診断の4段階のどこにいるかも見せる。
 */
export function PlanSummary({ risky, targetId }: PlanSummaryProps) {
  const labels = brokenLabels(risky);
  const headline = risky.length === 0 ? t.none : labels ? t.breaks(risky.length, labels) : t.direct(risky.length);

  return (
    <section aria-label={t.label} className="max-w-2xl space-y-4 border-l-4 border-seeker bg-paper-deep px-5 py-5">
      <ol aria-label={t.stepsLabel} className="flex flex-wrap gap-x-4 gap-y-2 text-xs">
        {t.steps.map((step, index) => (
          <li
            key={step}
            aria-current={index === CURRENT_STEP ? "step" : undefined}
            className={`flex items-baseline gap-1.5 ${
              index === CURRENT_STEP ? "font-bold text-seeker" : index < CURRENT_STEP ? "text-ink/70" : "text-ink/45"
            }`}
          >
            <span aria-hidden className="tabular-nums">{index + 1}</span>
            <span>{step}</span>
            <span className="text-ink/50">（{t.stepNotes[index]}）</span>
          </li>
        ))}
      </ol>
      <p className="text-lg font-bold leading-relaxed">{headline}</p>
      {risky.length > 0 && (
        <a
          href={`#${targetId}`}
          className="inline-flex items-center gap-2 rounded-sm bg-seeker px-5 py-2.5 font-display text-paper shadow-[4px_4px_0_var(--color-ink)] transition-transform hover:-translate-y-0.5 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink active:translate-y-0.5 active:shadow-none"
        >
          {t.show}
          <span aria-hidden>↓</span>
        </a>
      )}
    </section>
  );
}
