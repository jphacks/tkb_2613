import { CLUE_LABELS } from "@/lib/clueLabels";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import { PROFILE_ATTRIBUTE_CATALOG, type ProfileItem, type WebFact } from "@/types/profile";

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
  webFacts?: readonly WebFact[];
  webLookupStatus?: "not_run" | "fixture";
  ownerProfileText?: string;
  selfReportClues?: readonly Clue[];
}

/** 捜査ボード。限定ルールのプロフィール推定を主表示し、旧試作ルールは別枠に置く。 */
export function ConclusionBoard({ clues, conclusions, profileClaims = [], webFacts = [], webLookupStatus = "not_run", ownerProfileText = "", selfReportClues = [] }: ConclusionBoardProps) {
  return (
    <section aria-labelledby="board-heading" className="max-w-2xl space-y-4">
      <h3 id="board-heading" className="font-display text-2xl">
        捜査ボード
      </h3>
      <p className="text-xs text-ink/60">{webLookupStatus === "fixture" ? "公開Webの情報は架空のデモデータです" : "公開Webの照合はまだ行っていません"}</p>
      <section aria-labelledby="profile-claims-heading" className="space-y-3">
        <h4 id="profile-claims-heading" className="font-display text-xl">投稿を横断した推定</h4>
        {profileClaims.length === 0 ? (
          <p className="text-ink/70">現在の限定ルールでは、根拠のあるプロフィール推定は成立しませんでした。これは安全の確認を意味しません。</p>
        ) : (
          <ul className="space-y-3">
            {profileClaims.map((item) => (
              <li key={item.attribute} className="border-l-4 border-seeker bg-paper-deep px-4 py-3">
                <p className="text-xs text-ink/60">{PROFILE_ATTRIBUTE_CATALOG[item.attribute].label} ・{item.status === "weak" ? "弱い推定" : "推定"}・暫定ルール確度 {Math.round(item.confidence * 100)}%</p>
                <p className="mt-1 text-lg font-bold">{item.value}</p>
                <p className="text-sm text-ink/70">{item.attribute === "child_age" ? "別々の本人投稿にある生年と誕生日の記述から、診断日時点の年齢を計算した暫定候補です。生年の情報は片方の投稿を消しても残ります。" : item.assessment?.minimal_scope === "bluesky_plus_public_web" ? "本人投稿で勤務先名として明示された会社名を、別投稿と公式情報で照合した暫定候補です。プロフィール文を根拠に使う場合も、同じ会社名に触れる別投稿2件を必要とします。" : "本人との明示的な関係、固有名の橋渡し、型付きの値から作った暫定候補です。プロフィール文を根拠に使う場合も、橋渡しと値を示す別投稿2件を必要とします。"}</p>
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
                      const webFact = evidence.web_fact_id ? webFacts.find((fact) => fact.id === evidence.web_fact_id) : undefined;
                      const sourceLabel = evidence.source === "public_web" ? "公開Web" : evidence.source === "profile_text" ? "プロフィール文" : evidence.source === "post_text" ? "投稿本文" : evidence.source === "image_alt" ? "画像alt" : "投稿手がかり";
                      const clueSource = clue?.source === "ocr" ? "写真OCR" : clue?.source === "vlm" ? "写真VLM" : clue?.source === "alt" ? "画像alt" : clue?.source === "text" ? "投稿本文" : undefined;
                      const clueRegion = clue?.region ? `画像位置: ${clue.region.join(", ")} px` : undefined;
                      return <li key={`${evidence.post_id}:${evidence.clue_index}:${evidence.excerpt}:${evidence.web_fact_id}`} className="rounded border border-ink/20 px-2 py-1 text-sm"><span className="block text-[10px] text-ink/60">{sourceLabel}{evidence.post_id ? ` · ${evidence.post_id}` : ""}</span>{webFact ? <><span>{webFact.excerpt}</span><a href={webFact.source_url} target="_blank" rel="noopener noreferrer" className="mt-1 block underline">出典: {webFact.source_title}</a></> : <><span>{clue?.value ?? evidence.excerpt ?? "根拠"}</span>{clueSource && <span className="mt-1 block text-[10px] text-ink/60">{clueSource}{clueRegion ? ` · ${clueRegion}` : ""}</span>}</>}</li>;
                    })}
                  </ul>
                ))}
              </li>
            ))}
          </ul>
        )}
      </section>
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
      {conclusions.length > 0 && (
        <details className="rounded-sm border border-ink/20 px-4 py-3">
          <summary className="cursor-pointer font-bold">検証前の候補（試作ルール）</summary>
          <p className="my-2 text-sm text-ink/70">R1〜R3の試作ルールによる候補です。検証済みの事実ではなく、自宅・勤務先・危険性を示す結論として扱わないでください。</p>
          <ol aria-label="試作ルールの候補" className="space-y-4">
            {conclusions.map((conclusion, i) => (
              <li key={i} className="border-l-4 border-seeker bg-paper-deep px-4 py-3">
                <p className="text-xs tracking-widest text-ink/60">{conclusion.rule} ・{ATTRIBUTE_LABELS[conclusion.attribute] ?? conclusion.attribute}<span className="ml-2 rounded-sm bg-ink/10 px-1.5 py-0.5">候補</span></p>
                <p className="mt-1 text-xl font-bold">{conclusion.value}</p>
                {conclusion.note && <p className="mt-1 text-sm text-ink/70">{conclusion.note}</p>}
                <p className="mt-3 text-xs tracking-widest text-ink/60">根拠（{conclusion.clue_indices.length} 件）</p>
                <ul aria-label="根拠の手がかり" className="mt-1 flex flex-wrap gap-2">{conclusion.clue_indices.map((index) => { const clue = clues[index]; return <li key={index} className="rounded-sm border border-ink/20 px-2 py-0.5 text-sm"><span className="text-xs text-ink/60">{CLUE_LABELS[clue.type]}</span>{" "}{clue.value}</li>; })}</ul>
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}
