/**
 * 投稿の形式（Bluesky から取得したもの）。TypeScript 側の正。
 * Python 側の Post（tkb_common に追加予定）と同時に変更すること。形は CLAUDE.md の「投稿」。
 */

/** 画像を取りに行く先は Bluesky の CDN だけ（CLAUDE.md のセキュリティのルール） */
export const IMAGE_URL_PREFIX = "https://cdn.bsky.app/";

export interface PostImage {
  /** 投稿の中で何枚目か（0 から）。手がかりの image_index と対応する */
  readonly index: number;
  readonly url: string;
  readonly alt: string;
  /** 元の画像の大きさ。手がかりの region はこの大きさのピクセルで表す */
  readonly width: number;
  readonly height: number;
}

export interface Post {
  /** AT URI（at://did:plc:…/app.bsky.feed.post/…） */
  readonly post_id: string;
  readonly text: string;
  /** ISO 8601（タイムゾーンつき） */
  readonly created_at: string;
  readonly images: readonly PostImage[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) > 0;
}

function isPostImage(value: unknown, index: number): value is PostImage {
  return (
    isRecord(value) &&
    value.index === index &&
    typeof value.url === "string" &&
    value.url.startsWith(IMAGE_URL_PREFIX) &&
    typeof value.alt === "string" &&
    isPositiveInteger(value.width) &&
    isPositiveInteger(value.height)
  );
}

export function isPost(value: unknown): value is Post {
  return (
    isRecord(value) &&
    typeof value.post_id === "string" &&
    value.post_id.startsWith("at://") &&
    typeof value.text === "string" &&
    typeof value.created_at === "string" &&
    !Number.isNaN(Date.parse(value.created_at)) &&
    Array.isArray(value.images) &&
    value.images.every((image, i) => isPostImage(image, i))
  );
}
