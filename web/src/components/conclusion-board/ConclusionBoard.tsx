import { CLUE_LABELS } from "@/lib/clueLabels";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";

/** engine の試作の項目名（attribute）の表示名。16項目への対応づけまでのつなぎ */
const ATTRIBUTE_LABELS: Readonly<Record<string, string>> = {
  station: "最寄り駅",
  home_area: "住んでいる町",
  active_time: "よくいる時間",
  routine: "決まった外出",
};

interface ConclusionBoardProps {
  clues: readonly Clue[];
  conclusions: readonly Conclusion[];
}

/** 捜査ボード。推理の結論を「推定」として並べ、根拠の手がかりを添える。 */
export function ConclusionBoard({ clues, conclusions }: ConclusionBoardProps) {
  const found = conclusions.length > 0;
  return (
    <section aria-labelledby="board-heading" className="max-w-2xl space-y-4">
      {/* 表示された瞬間に 1 回だけ演出が走る。何も推定できなかったときは出さない */}
      {found && (
        <>
          <div aria-hidden="true" className="found-flash" />
          <p className="horror-title found-title text-5xl sm:text-6xl">みーつけた</p>
        </>
      )}
      <h3 id="board-heading" className="font-display text-2xl">
        捜査ボード
      </h3>
      {conclusions.length === 0 ? (
        <p className="text-ink/70">投稿からは、あなたについて推定できることは見つかりませんでした</p>
      ) : (
        <ol aria-label="推定できたこと" className="space-y-4">
          {conclusions.map((conclusion, i) => (
            <li key={i} className="border-l-4 border-seeker bg-paper-deep px-4 py-3">
              <p className="text-xs tracking-widest text-ink/60">
                {ATTRIBUTE_LABELS[conclusion.attribute] ?? conclusion.attribute}
                <span className="ml-2 rounded-sm bg-ink/10 px-1.5 py-0.5">推定</span>
              </p>
              <p className="mt-1 text-xl font-bold">{conclusion.value}</p>
              {conclusion.note && <p className="mt-1 text-sm text-ink/70">{conclusion.note}</p>}
              <p className="mt-3 text-xs tracking-widest text-ink/60">
                根拠（{conclusion.clue_indices.length} 件）
              </p>
              <ul aria-label="根拠の手がかり" className="mt-1 flex flex-wrap gap-2">
                {conclusion.clue_indices.map((index) => {
                  const clue = clues[index];
                  return (
                    <li key={index} className="rounded-sm border border-ink/20 px-2 py-0.5 text-sm">
                      <span className="text-xs text-ink/60">{CLUE_LABELS[clue.type]}</span>{" "}
                      {clue.value}
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
