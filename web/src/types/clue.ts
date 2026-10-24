/**
 * 手がかりの形式。TypeScript 側の正。
 * api/src/tkb_api/schemas.py と同時に変更すること。
 */

/** 写真からだけ出る type */
export const PHOTO_ONLY_CLUE_TYPES = [
  "station_sign",
  "rail_view",
  "reflection",
  "shop",
  "landmark",
  "address_text",
  "postal_code",
  "phone",
  "plate",
  "uniform",
  "face",
  "key",
  "code",
] as const;

/** 写真と本文の両方から出る type */
export const PHOTO_OR_TEXT_CLUE_TYPES = ["name_text", "org_text", "handle_text", "place_text"] as const;

/** 本文からだけ出る type */
export const TEXT_ONLY_CLUE_TYPES = ["age_text", "routine_text", "relation_text"] as const;

export const CLUE_TYPES = [
  ...PHOTO_ONLY_CLUE_TYPES,
  ...PHOTO_OR_TEXT_CLUE_TYPES,
  ...TEXT_ONLY_CLUE_TYPES,
] as const;

/** text は本文から、meta は投稿時刻などから */
export const CLUE_SOURCES = ["ocr", "vlm", "text", "meta"] as const;
const PHOTO_SOURCES: readonly ClueSource[] = ["ocr", "vlm"];

export type ClueType = (typeof CLUE_TYPES)[number];
export type ClueSource = (typeof CLUE_SOURCES)[number];

/** 画像上の矩形 [左上x, 左上y, 右下x, 右下y]（ピクセル） */
export type Region = readonly [number, number, number, number];

export interface Clue {
  readonly post_id: string;
  /** 写真から出た手がかりだけに入れる。本文から出たものは null */
  readonly image_index: number | null;
  readonly type: ClueType;
  /** 一部しか読めない文字は、読めない桁や文字を x にする（例：270-01xx） */
  readonly value: string;
  /** 写真の手がかりでも位置がなければ null */
  readonly region: Region | null;
  readonly confidence: number;
  readonly source: ClueSource;
}

export interface DetectResponse {
  readonly clues: readonly Clue[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function includes<T>(list: readonly T[], value: unknown): value is T {
  return (list as readonly unknown[]).includes(value);
}

function isNonNegativeInt(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function isRegion(value: unknown): value is Region {
  if (!Array.isArray(value) || value.length !== 4) return false;
  if (!value.every(isNonNegativeInt)) return false;
  const [x1, y1, x2, y2] = value as number[];
  return x2 > x1 && y2 > y1;
}

/** 写真の手がかりか本文の手がかりかで、image_index・region・source・type がそろっているか */
function isConsistent(clue: Clue): boolean {
  const fromPhoto = clue.image_index !== null;
  if (clue.region !== null && !fromPhoto) return false;
  if (fromPhoto !== PHOTO_SOURCES.includes(clue.source)) return false;
  if (includes(PHOTO_ONLY_CLUE_TYPES, clue.type) && !fromPhoto) return false;
  if (includes(TEXT_ONLY_CLUE_TYPES, clue.type) && fromPhoto) return false;
  return true;
}

export function isClue(value: unknown): value is Clue {
  if (!isRecord(value)) return false;
  const shapeOk =
    typeof value.post_id === "string" &&
    value.post_id.length > 0 &&
    (value.image_index === null || isNonNegativeInt(value.image_index)) &&
    includes(CLUE_TYPES, value.type) &&
    typeof value.value === "string" &&
    (value.region === null || isRegion(value.region)) &&
    typeof value.confidence === "number" &&
    value.confidence >= 0 &&
    value.confidence <= 1 &&
    includes(CLUE_SOURCES, value.source);
  return shapeOk && isConsistent(value as unknown as Clue);
}

export function isDetectResponse(value: unknown): value is DetectResponse {
  return isRecord(value) && Array.isArray(value.clues) && value.clues.every(isClue);
}
