/**
 * 投稿の形式（Bluesky から取得したもの）。TypeScript 側の正。
 * common/src/tkb_common/schemas.py と同時に変更すること。
 */

/** Bluesky投稿で画像を取りに行ってよいCDN */
export const BSKY_CDN_PREFIX = "https://cdn.bsky.app/";
/** Threads API の media_url が返す Meta 管理 CDN */
export const THREADS_MEDIA_HOST_SUFFIXES = ["cdninstagram.com", "fbcdn.net"] as const;
/** Bluesky の投稿に付けられる写真は4枚まで */
export const MAX_IMAGES_PER_POST = 4;

export interface PostImage {
  readonly index: number;
  readonly url: string;
  readonly alt: string;
  readonly width: number;
  readonly height: number;
  /** モック専用のローカル画像ファイル名。実モードでは常に未設定。 */
  readonly mock_asset?: string | null;
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
    typeof value.alt === "string" &&
    (value.mock_asset === undefined ||
      value.mock_asset === null ||
      (typeof value.mock_asset === "string" &&
        /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value.mock_asset))) &&
    isPositiveInt(value.width) &&
    isPositiveInt(value.height)
  );
}

export function isPost(value: unknown): value is Post {
  if (!(
    isRecord(value) &&
    typeof value.post_id === "string" &&
    value.post_id.length > 0 &&
    typeof value.text === "string" &&
    isAwareDateTime(value.created_at) &&
    Array.isArray(value.images) &&
    value.images.length <= MAX_IMAGES_PER_POST &&
    value.images.every(isPostImage)
  )) return false;
  const postId = value.post_id as string;
  const images = value.images as readonly PostImage[];
  return images.every((image) => {
    if (image.url.startsWith(BSKY_CDN_PREFIX)) return true;
    if (!postId.startsWith("threads:")) return false;
    try {
      const parsed = new URL(image.url);
      return parsed.protocol === "https:" && THREADS_MEDIA_HOST_SUFFIXES.some(
        (suffix) => parsed.hostname === suffix || parsed.hostname.endsWith(`.${suffix}`),
      );
    } catch {
      return false;
    }
  });
}
