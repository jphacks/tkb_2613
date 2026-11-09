import { CLUE_LABELS } from "@/lib/clueLabels";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import { PROFILE_ATTRIBUTE_CATALOG, type ProfileItem } from "@/types/profile";

/** engine の試作の項目名（attribute）の表示名。16項目への対応づけまでのつなぎ */
const ATTRIBUTE_LABELS: Readonly<Record<string, string>> = {
  station: "投稿で見つかった駅",
  home_area: "投稿で見つかった町域候補",
  active_time: "よくいる時間",
  routine: "決まった外出",
};

interface ConclusionBoardProps {
  clues: readonly Clue[];
  conclusions: readonly Conclusion[];
  profileClaims?: readonly ProfileItem[];
  ownerProfileText?: string;
  selfReportClues?: readonly Clue[];
}

/** 捜査ボード。推理の結論を「推定」として並べ、根拠の手がかりを添える。 */
export function ConclusionBoard({ clues, conclusions, profileClaims = [], ownerProfileText = "", selfReportClues = [] }: ConclusionBoardProps) {
  return (
    <section aria-labelledby="board-heading" className="max-w-2xl space-y-4">
      <h3 id="board-heading" className="font-display text-2xl">
        捜査ボード
      </h3>
      {conclusions.length === 0 && profileClaims.length === 0 ? (
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
              {(conclusion.attribute === "station" || conclusion.attribute === "home_area") && <p className="mt-1 text-xs text-ink/60">投稿に書かれた値です。自宅との関係は確認できていません。</p>}
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
      {ownerProfileText && (
        <details className="rounded-sm border border-ink/20 px-4 py-3">
          <summary className="cursor-pointer font-bold">プロフィール文（本人の自己申告）</summary>
          <p className="mt-2 whitespace-pre-wrap text-sm">{ownerProfileText}</p>
        </details>
      )}
      {selfReportClues.length > 0 && (
        <section aria-label="プロフィール文から見つかった自己申告">
          <h4 className="font-display text-lg">プロフィール文の自己申告（推論とは別）</h4>
          <ul className="list-disc pl-5 text-sm">
            {selfReportClues.map((clue, index) => <li key={`${clue.type}:${index}`}>{clue.value}</li>)}
          </ul>
        </section>
      )}
      {profileClaims.length > 0 && (
        <section aria-labelledby="profile-claims-heading" className="space-y-3">
          <h4 id="profile-claims-heading" className="font-display text-xl">投稿を横断した推定</h4>
          <ul className="space-y-3">
            {profileClaims.map((item) => (
              <li key={item.attribute} className="border-l-4 border-seeker bg-paper-deep px-4 py-3">
                <p className="text-xs text-ink/60">{PROFILE_ATTRIBUTE_CATALOG[item.attribute].label} ・{item.status === "weak" ? "弱い推定" : "推定"}・暫定ルール確度 {Math.round(item.confidence * 100)}%</p>
                <p className="mt-1 text-lg font-bold">{item.value}</p>
                <p className="text-sm text-ink/70">本人との明示的な関係、固有名の橋渡し、型付きの値から作った暫定候補です。プロフィール文を根拠に使う場合も、橋渡しと値を示す別投稿2件を必要とします。</p>
                <dl className="mt-2 grid grid-cols-2 gap-2 text-xs text-ink/70">
                  <div><dt>必要な情報範囲</dt><dd>{item.assessment?.minimal_scope === "bluesky" ? "Bluesky内のみ" : item.assessment?.minimal_scope === "bluesky_plus_public_web" ? "Bluesky＋公開Web" : item.assessment?.minimal_scope === "bluesky_plus_offline" ? `Bluesky＋オフライン（${item.assessment.offline_subtype ?? "経路未指定"}）` : "未評価"}</dd></div>
                  <div><dt>心理的抵抗感</dt><dd>{item.assessment?.psychological_resistance == null ? "未評価" : `${item.assessment.psychological_resistance}/5 (${item.assessment.persona_context})`}</dd></div>
                  <div><dt>推論の容易さ</dt><dd>{item.assessment?.inference_ease == null ? "未評価" : `${item.assessment.inference_ease}/5 (${item.assessment.inference_ease_basis === "provisional" ? "暫定" : "測定済み"})`}</dd></div>
                  <div><dt>想定被害</dt><dd>{item.assessment?.harm_status === "prerequisites_unmet" ? `条件未成立: ${item.assessment.harm_scenario ?? "シナリオ未記載"}（条件: ${item.assessment.harm_prerequisites.join("、") || "未記載"}）` : item.assessment?.harm_status === "applicable" ? `${item.assessment.harm_severity}/5: ${item.assessment.harm_scenario}` : "未評価"}</dd></div>
                </dl>
                {(item.evidence_paths ?? []).map((path, pathIndex) => (
                  <ul key={pathIndex} aria-label={`根拠経路 ${pathIndex + 1}`} className="mt-2 flex flex-wrap gap-2">
                    {path.evidence.map((evidence) => {
                      const clue = evidence.clue_index == null ? undefined : clues[evidence.clue_index];
                      const sourceLabel = evidence.source === "profile_text" ? "プロフィール文" : evidence.source === "post_text" ? "投稿本文" : evidence.source === "image_alt" ? "画像alt" : "投稿手がかり";
                      return <li key={`${evidence.post_id}:${evidence.clue_index}:${evidence.excerpt}`} className="rounded border border-ink/20 px-2 py-1 text-sm"><span className="block text-[10px] text-ink/60">{sourceLabel}{evidence.post_id ? ` · ${evidence.post_id}` : ""}</span>{clue?.value ?? evidence.excerpt ?? "根拠"}</li>;
                    })}
                  </ul>
                ))}
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}
