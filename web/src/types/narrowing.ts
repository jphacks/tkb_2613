/**
 * f1 絞り込みの演出のデータ（api の conclusions イベントと GET /api/diagnosis の narrowing）。
 * Python は tkb_engine.narrowing。1都3県 → 生活圏（W1）→ 番地（R6）の順に数え下げる。
 * 各段の post_ids は、その段の推定の根拠の投稿。仮除外した投稿を含む段は出さない。
 */

export interface NarrowingMesh {
  /** 500m メッシュの番号（9桁） */
  readonly code: string;
  /** そのメッシュ全体の世帯数（国勢調査） */
  readonly households: number;
  /** メッシュのうち円に入る面積の割合（0〜1） */
  readonly share: number;
}

export interface Narrowing {
  readonly region: {
    readonly label: string;
    readonly households: number;
    /** [南, 西, 北, 東]（度） */
    readonly bounds: readonly [number, number, number, number];
  };
  readonly walk: {
    readonly station: string;
    readonly minutes: number;
    readonly radius_m: number;
    /** [緯度, 経度] */
    readonly center: readonly [number, number];
    /** 円と重なる面積で按分し、有効数字2桁で切り捨てた世帯数 */
    readonly households: number;
    readonly meshes: readonly NarrowingMesh[];
    readonly post_ids: readonly string[];
  } | null;
  readonly block: { readonly value: string; readonly post_ids: readonly string[] } | null;
  readonly sources: readonly string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isFiniteList(value: unknown, length: number): boolean {
  return Array.isArray(value) && value.length === length && value.every((v) => typeof v === "number" && Number.isFinite(v));
}

function isStringList(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string" && v.length > 0);
}

function isMesh(value: unknown): value is NarrowingMesh {
  return (
    isRecord(value) &&
    typeof value.code === "string" &&
    /^\d{8}[1-4]$/.test(value.code) &&
    isCount(value.households) &&
    typeof value.share === "number" &&
    value.share > 0 &&
    value.share <= 1
  );
}

function isWalk(value: unknown): value is NonNullable<Narrowing["walk"]> {
  return (
    isRecord(value) &&
    typeof value.station === "string" &&
    value.station.length > 0 &&
    isCount(value.minutes) &&
    value.minutes > 0 &&
    isCount(value.radius_m) &&
    value.radius_m > 0 &&
    isFiniteList(value.center, 2) &&
    isCount(value.households) &&
    Array.isArray(value.meshes) &&
    value.meshes.every(isMesh) &&
    isStringList(value.post_ids) &&
    value.post_ids.length > 0
  );
}

function isBlock(value: unknown): value is NonNullable<Narrowing["block"]> {
  return isRecord(value) && typeof value.value === "string" && value.value.length > 0 && isStringList(value.post_ids) && value.post_ids.length > 0;
}

export function isNarrowing(value: unknown): value is Narrowing {
  if (!isRecord(value) || !isRecord(value.region)) return false;
  const { region } = value;
  return (
    typeof region.label === "string" &&
    isCount(region.households) &&
    isFiniteList(region.bounds, 4) &&
    // [南, 西, 北, 東] の順
    (region.bounds as number[])[0] < (region.bounds as number[])[2] &&
    (region.bounds as number[])[1] < (region.bounds as number[])[3] &&
    (value.walk === null || isWalk(value.walk)) &&
    (value.block === null || isBlock(value.block)) &&
    (value.walk !== null || value.block !== null) &&
    isStringList(value.sources)
  );
}

/** 仮除外した投稿を根拠に含む段を落とす。形が違うか、推定の段が残らなければ null */
export function visibleNarrowing(narrowing: Narrowing | null | undefined, excluded: ReadonlySet<string>): Narrowing | null {
  // 開き直したときの応答（GET /api/diagnosis）は形を確かめてから使う。演出だけなので、違えば出さない
  if (!isNarrowing(narrowing)) return null;
  const keeps = (ids: readonly string[]) => ids.every((id) => !excluded.has(id));
  const walk = narrowing.walk && keeps(narrowing.walk.post_ids) ? narrowing.walk : null;
  const block = narrowing.block && keeps(narrowing.block.post_ids) ? narrowing.block : null;
  if (!walk && !block) return null;
  return { ...narrowing, walk, block };
}
