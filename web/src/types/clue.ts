/**
 * 手がかりの形式。TypeScript 側の正。
 * api/src/tkb_api/schemas.py と同時に変更すること。
 */

export const CLUE_TYPES = [
  "station_sign",
  "address_text",
  "postal_code",
  "phone",
  "shop",
  "plate",
  "landmark",
  "exif_gps",
  "face",
  "iris",
  "key",
  "code",
] as const;

export const CLUE_SOURCES = ["ocr", "vlm", "browser"] as const;

export type ClueType = (typeof CLUE_TYPES)[number];
export type ClueSource = (typeof CLUE_SOURCES)[number];

/** 画像上の矩形 [左上x, 左上y, 右下x, 右下y]（ピクセル） */
export type Region = readonly [number, number, number, number];

export interface Clue {
  readonly type: ClueType;
  readonly value: string;
  readonly region: Region;
  readonly confidence: number;
  readonly source: ClueSource;
}

export interface DetectResponse {
  readonly clues: readonly Clue[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isRegion(value: unknown): value is Region {
  if (!Array.isArray(value) || value.length !== 4) return false;
  if (!value.every((n) => Number.isInteger(n) && n >= 0)) return false;
  const [x1, y1, x2, y2] = value as number[];
  return x2 > x1 && y2 > y1;
}

export function isClue(value: unknown): value is Clue {
  if (!isRecord(value)) return false;
  return (
    (CLUE_TYPES as readonly unknown[]).includes(value.type) &&
    typeof value.value === "string" &&
    isRegion(value.region) &&
    typeof value.confidence === "number" &&
    value.confidence >= 0 &&
    value.confidence <= 1 &&
    (CLUE_SOURCES as readonly unknown[]).includes(value.source)
  );
}

export function isDetectResponse(value: unknown): value is DetectResponse {
  return isRecord(value) && Array.isArray(value.clues) && value.clues.every(isClue);
}
