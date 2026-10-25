import { messages } from "@/lib/messages";
import type { Conclusion } from "@/types/diagnose";

const t = messages.identity;

/** 数字は 3 桁で回す（手がかりは直近 MAX_POSTS 件の投稿からなので、3 桁あれば足りる） */
const DIGITS = 3;

/** 0〜9 を 2 周並べ、2 周目の目的の数字で止める。1 桁ごとに少しずつ遅れて止まる */
function Roller({ value }: { value: number }) {
  const digits = String(Math.min(value, 10 ** DIGITS - 1)).padStart(DIGITS, "0");
  return (
    <span aria-hidden="true" className="roller">
      {[...digits].map((d, i) => (
        <span key={i} className="roller-digit">
          <span
            className="roller-strip"
            style={{ transform: `translateY(${-(10 + Number(d)) * 5}%)`, animationDelay: `${0.4 + i * 0.25}s` }}
          >
            {Array.from({ length: 20 }, (_, n) => (
              <span key={n}>{n % 10}</span>
            ))}
          </span>
        </span>
      ))}
    </span>
  );
}

/** 写真の枠に出す人影。顔は出さない（顔の手がかりを出すかはチームで決めてから） */
function Silhouette() {
  return (
    <svg viewBox="0 0 120 140" aria-hidden="true" className="h-full w-full">
      <circle cx="60" cy="50" r="26" className="fill-ink/15" />
      <path d="M10 140 C 14 100, 36 86, 60 86 C 84 86, 106 100, 110 140 Z" className="fill-ink/15" />
      <text x="60" y="64" textAnchor="middle" className="fill-seeker font-display text-[40px]">
        ？
      </text>
    </svg>
  );
}

/** 身元カードに並べる、強い手がかり 1 行 */
export interface Highlight {
  label: string;
  value: string;
}

interface IdentityCardProps {
  name: string | null;
  conclusions: readonly Conclusion[];
  /** 名前のほかに並べる強い手がかり。危ない種類の順 */
  highlights: readonly Highlight[];
  clueCount: number;
}

/**
 * 身元が割れた瞬間のカード。人影の枠、写っていた名前、推定できたこと、見つかった手がかりの数を並べる。
 * 数字は「本人である確率」ではなく、実際に見つかった手がかりの数にする（確率は出せないので出さない）。
 */
export function IdentityCard({ name, conclusions, highlights, clueCount }: IdentityCardProps) {
  return (
    <article
      aria-label={t.label}
      className="identity-card reveal-slam relative grid gap-6 border border-ink/20 bg-paper-deep/80 p-5 shadow-[8px_8px_0_oklch(0%_0_0/0.5)] sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] sm:p-7"
    >
      <div className="relative mx-auto aspect-[6/7] w-40 overflow-hidden border border-ink/20 bg-paper sm:w-full">
        <Silhouette />
        <p className="absolute inset-x-0 bottom-0 bg-paper/80 px-3 py-1.5 text-center text-xs tracking-widest text-ink/70">
          {t.silhouette}
        </p>
      </div>

      <div className="flex min-w-0 flex-col gap-5">
        <div>
          <p className="text-xs tracking-[0.3em] text-ink/60">{t.nameLabel}</p>
          <p className="identity-name mt-1 text-5xl font-bold break-words sm:text-6xl">{name ?? t.nameUnknown}</p>
        </div>

        {highlights.length > 0 && (
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 border-y border-ink/15 py-3">
            {/* display: contents の要素は動かないので、動きは dt と dd に付ける */}
            {highlights.map((h, i) => {
              const delay = { animationDelay: `${0.4 + i * 0.12}s` };
              return (
                <div key={i} className="contents">
                  <dt className="reveal-stamp text-xs leading-7 tracking-widest text-ink/60" style={delay}>
                    {h.label}
                  </dt>
                  <dd className="reveal-stamp text-lg font-bold break-words" style={delay}>
                    {h.value}
                  </dd>
                </div>
              );
            })}
          </dl>
        )}

        {conclusions.length > 0 && (
          <ul aria-label={messages.reveal.conclusionsLabel} className="space-y-2">
            {conclusions.map((c, i) => (
              <li key={i} className="reveal-stamp" style={{ animationDelay: `${0.5 + i * 0.2}s` }}>
                <span className="mr-2 text-xs tracking-widest text-ink/60">
                  {messages.board.attributeLabels[c.attribute] ?? c.attribute}
                </span>
                <span className="mr-2 rounded-sm bg-ink/10 px-1.5 py-0.5 text-xs">{t.inferred}</span>
                <span className="text-lg font-bold text-seeker sm:text-xl">{c.value}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-auto">
          <p className="text-xs tracking-[0.3em] text-ink/60">{t.cluesFound}</p>
          <p className="flex items-end gap-2">
            <Roller value={clueCount} />
            <span className="sr-only">{clueCount}</span>
            <span className="pb-2 text-2xl text-ink/70">{t.cluesUnit}</span>
          </p>
        </div>
      </div>
    </article>
  );
}
