import type { Post } from "@/types/post";

export interface ThreadsPublicFinding {
  readonly postId: string;
  readonly labels: readonly string[];
}

const DIRECT_PATTERNS: readonly { readonly label: string; readonly pattern: RegExp }[] = [
  { label: "URLらしき文字列", pattern: /https?:\/\/[^\s]+/iu },
  { label: "メールアドレスらしき文字列", pattern: /[\p{L}\p{N}.%+-]+@[\p{L}\p{N}.-]+\.[a-z]{2,}/iu },
  { label: "電話番号らしき文字列", pattern: /(?:0\d{1,4}[-ー]\d{1,4}[-ー]\d{3,4}|\b\d{10,11}\b)/u },
  { label: "郵便番号らしき文字列", pattern: /(?<![\dー-])(?:〒\s*)?\d{3}[-ー]\d{4}(?![\dー-])/u },
  { label: "@ユーザーネームらしき文字列", pattern: /(?:^|[\s(（])@[a-z0-9._]{1,30}\b/iu },
];

/**
 * 取得済みの本人投稿を、外部送信せず固定の文字列パターンだけで確認する。
 * 所有者・実在性・意味は推定せず、AI診断として扱わない。
 */
export function checkThreadsPublicText(posts: readonly Post[]): readonly ThreadsPublicFinding[] {
  return posts.map((post) => ({
    postId: post.post_id,
    labels: DIRECT_PATTERNS.filter(({ pattern }) => pattern.test(post.text)).map(({ label }) => label),
  }));
}
