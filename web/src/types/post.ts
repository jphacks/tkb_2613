/**
 * 投稿の形式（Bluesky から取得したもの）。TypeScript 側の正。
 * common/src/tkb_common/schemas.py と同時に変更すること。
 */

/** 画像を取りに行ってよいのは Bluesky の CDN だけ */
export const BSKY_CDN_PREFIX = "https://cdn.bsky.app/";
/** Bluesky の投稿に付けられる写真は4枚まで */
export const MAX_IMAGES_PER_POST = 4;

export interface PostImage {
  readonly index: number;
  readonly url: string;
  readonly alt: string;
  readonly width: number;
  readonly height: number;
}

export interface Post {
  readonly post_id: string;
  readonly text: string;
  /** 時差つきの ISO 8601（例：2026-10-20T08:31:00+09:00） */
  readonly created_at: string;
  readonly images: readonly PostImage[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isPositiveInt(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) > 0;
}

/** 時差（Z か ±hh:mm）のある日時か */
function isAwareDateTime(value: unknown): value is string {
  if (typeof value !== "string") return false;
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value)) return false;
  return !Number.isNaN(Date.parse(value));
}

function isPostImage(value: unknown, index: number): value is PostImage {
  return (
    isRecord(value) &&
    value.index === index &&
    typeof value.url === "string" &&
    value.url.startsWith(BSKY_CDN_PREFIX) &&
    typeof value.alt === "string" &&
    isPositiveInt(value.width) &&
    isPositiveInt(value.height)
  );
}

export function isPost(value: unknown): value is Post {
  return (
    isRecord(value) &&
    typeof value.post_id === "string" &&
    value.post_id.length > 0 &&
    typeof value.text === "string" &&
    isAwareDateTime(value.created_at) &&
    Array.isArray(value.images) &&
    value.images.length <= MAX_IMAGES_PER_POST &&
    value.images.every(isPostImage)
  );
}
