import type { Region } from "@/types/clue";

export interface Size {
  width: number;
  height: number;
}

/** 写真のピクセル座標の矩形を、写真の大きさに対する % の位置に直す。写真の上に重ねるときに使う。 */
export function toPercentBox([x1, y1, x2, y2]: Region, { width, height }: Size) {
  const pct = (n: number, total: number) => `${(n / total) * 100}%`;
  return { left: pct(x1, width), top: pct(y1, height), width: pct(x2 - x1, width), height: pct(y2 - y1, height) };
}
