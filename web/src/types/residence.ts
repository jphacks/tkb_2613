/**
 * 住まいの推定（点数の地図）。TypeScript 側の正。
 * common/src/tkb_common/residence.py と同時に変更すること。契約は docs/api-sse-contract.md の「住まいの推定」。
 *
 * 数字は推定。画面では「確定」「特定した」と言わず、「一番濃いのはここ」「8割の範囲は約○人」のように相対的に言う。
 */

export interface ResidenceRegion {
  /** 8割の範囲に住む人数（age_class があればその5歳階級） */
  readonly people: number;
  readonly cells: number;
  readonly city: string | null;
  readonly town: string | null;
  readonly station: string | null;
  readonly station_walk_minutes: number | null;
  /** 層8：同じ年齢・同じ誕生日の計算上の人数（目安） */
  readonly same_birthday: number | null;
}

export interface ResidenceMapCell {
  readonly lat: number;
  readonly lon: number;
  /** 本計算（層7を掛けない）の確率 */
  readonly p: number;
  /** 層7を掛けたときの確率 */
  readonly p_geo: number;
  /** 層7だけの点数（一番高いマスが 1） */
  readonly geo: number;
  readonly in_region: boolean;
}

export interface ResidenceMapLabel {
  readonly kind: "station" | "town";
  readonly name: string;
  readonly lat: number;
  readonly lon: number;
}

export interface ResidenceMap {
  readonly cell_lat: number;
  readonly cell_lon: number;
  readonly cells: readonly ResidenceMapCell[];
  readonly labels: readonly ResidenceMapLabel[];
}

export interface ResidenceStep {
  /** null は投稿なし（事前の人数だけ） */
  readonly post_id: string | null;
  readonly people: number;
  readonly cells: number;
  readonly same_birthday: number | null;
}

export interface ResidenceInfluence {
  readonly post_id: string;
  readonly people_without: number;
  /** 外したときの人数 − 今の人数。一番大きいものが「消すべき1件」 */
  readonly delta: number;
  /** 外すと範囲が狭まる（ほかと矛盾している可能性） */
  readonly contradiction: boolean;
}

export interface ResidenceEvidence {
  readonly post_id: string;
  /** 0：年齢、1〜7：層、8：誕生日 */
  readonly layer: number;
  readonly kind: string;
  readonly value: string;
  readonly excerpt: string;
  readonly applied: boolean;
  readonly clue_indices: readonly number[];
}

export interface ResidenceGeoprofile {
  readonly region: ResidenceRegion;
  readonly places: readonly string[];
  readonly other_bases: readonly string[];
  readonly buffer_m: number;
}

export interface ResidenceEstimate {
  readonly age_class: string | null;
  readonly region: ResidenceRegion;
  readonly geoprofile: ResidenceGeoprofile | null;
  readonly map: ResidenceMap;
  readonly steps: readonly ResidenceStep[];
  readonly influence: readonly ResidenceInfluence[];
  readonly evidence: readonly ResidenceEvidence[];
  readonly assumptions: readonly string[];
  readonly sources: readonly string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
function isNullableNumber(value: unknown): value is number | null {
  return value === null || isNumber(value);
}
function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}
function isStrings(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

function isRegion(value: unknown): value is ResidenceRegion {
  return (
    isRecord(value) && isNumber(value.people) && value.people >= 0 && isNumber(value.cells) &&
    isNullableString(value.city) && isNullableString(value.town) && isNullableString(value.station) &&
    isNullableNumber(value.station_walk_minutes) && isNullableNumber(value.same_birthday)
  );
}

function isMapCell(value: unknown): value is ResidenceMapCell {
  return (
    isRecord(value) && isNumber(value.lat) && isNumber(value.lon) && isNumber(value.p) &&
    isNumber(value.p_geo) && isNumber(value.geo) && typeof value.in_region === "boolean"
  );
}

function isMapLabel(value: unknown): value is ResidenceMapLabel {
  return (
    isRecord(value) && (value.kind === "station" || value.kind === "town") &&
    typeof value.name === "string" && isNumber(value.lat) && isNumber(value.lon)
  );
}

function isMap(value: unknown): value is ResidenceMap {
  return (
    isRecord(value) && isNumber(value.cell_lat) && isNumber(value.cell_lon) &&
    Array.isArray(value.cells) && value.cells.every(isMapCell) &&
    Array.isArray(value.labels) && value.labels.every(isMapLabel)
  );
}

function isStep(value: unknown): value is ResidenceStep {
  return (
    isRecord(value) && isNullableString(value.post_id) && isNumber(value.people) &&
    isNumber(value.cells) && isNullableNumber(value.same_birthday)
  );
}

function isInfluence(value: unknown): value is ResidenceInfluence {
  return (
    isRecord(value) && typeof value.post_id === "string" && isNumber(value.people_without) &&
    isNumber(value.delta) && typeof value.contradiction === "boolean"
  );
}

function isEvidence(value: unknown, clueCount: number): value is ResidenceEvidence {
  return (
    isRecord(value) && typeof value.post_id === "string" && Number.isInteger(value.layer) &&
    (value.layer as number) >= 0 && (value.layer as number) <= 8 &&
    typeof value.kind === "string" && typeof value.value === "string" &&
    typeof value.excerpt === "string" && typeof value.applied === "boolean" &&
    Array.isArray(value.clue_indices) &&
    value.clue_indices.every((i) => Number.isInteger(i) && (i as number) >= 0 && (i as number) < clueCount)
  );
}

function isGeoprofile(value: unknown): value is ResidenceGeoprofile {
  return (
    isRecord(value) && isRegion(value.region) && isStrings(value.places) &&
    isStrings(value.other_bases) && isNumber(value.buffer_m)
  );
}

/** 住まいの推定の形を確かめる。clueCount は根拠の手がかりの番号の上限（診断の clues の数） */
export function isResidenceEstimate(
  value: unknown,
  clueCount = Number.POSITIVE_INFINITY,
): value is ResidenceEstimate {
  return (
    isRecord(value) && isNullableString(value.age_class) && isRegion(value.region) &&
    (value.geoprofile === null || isGeoprofile(value.geoprofile)) && isMap(value.map) &&
    Array.isArray(value.steps) && value.steps.every(isStep) &&
    Array.isArray(value.influence) && value.influence.every(isInfluence) &&
    Array.isArray(value.evidence) && value.evidence.every((e) => isEvidence(e, clueCount)) &&
    isStrings(value.assumptions) && isStrings(value.sources)
  );
}

/** null（表がない・場所の手がかりがない）か、住まいの推定 */
export function isResidenceOrNull(
  value: unknown,
  clueCount = Number.POSITIVE_INFINITY,
): value is ResidenceEstimate | null {
  return value === null || isResidenceEstimate(value, clueCount);
}
