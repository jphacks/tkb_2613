/**
 * 画面の演出で共通に使う動きの決まり。
 * - 登場は 0.5〜0.8 秒、入るときは ENTER_EASE
 * - ずらしは 1 項目 0.4 秒前後で、全体を 2 秒以内に収める
 * - 発表モード（?stage=1）では、CSS 変数 --stage-pace の倍率で演出の間を伸ばす（既定は 1）
 * 動きを減らす設定の人には、globals.css が動きを止め、最後の状態だけを見せる。
 */

export const ENTER_EASE = "cubic-bezier(0.16, 1, 0.3, 1)";

/** 1 項目ずつずらす秒数の目安 */
export const STAGGER_STEP = 0.4;

/** ずらしを含めた全体の上限（秒） */
export const STAGGER_TOTAL = 2;

/**
 * count 個を順に動かすときの、index 番目の遅れ（秒）。
 * 1 項目 step 秒ずつずらし、最後の項目が動き終わる（duration 秒）までを total 秒に収める。
 */
export function staggerDelay(
  index: number,
  count: number,
  { step = STAGGER_STEP, duration = 0.6, total = STAGGER_TOTAL }: { step?: number; duration?: number; total?: number } = {},
): number {
  if (count <= 1) return 0;
  const fit = Math.max(0, total - duration) / (count - 1);
  return index * Math.min(step, fit);
}

/** 発表モードで伸びる遅れ。style の animationDelay にそのまま渡す */
export function paced(seconds: number): string {
  return `calc(var(--stage-pace, 1) * ${Number(seconds.toFixed(3))}s)`;
}
