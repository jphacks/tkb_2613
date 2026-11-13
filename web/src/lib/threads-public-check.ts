import type { Post } from "@/types/post";

/** 固定パターンの種類。表示の言語に依らない識別子（画面側で翻訳する） */
export type PublicPatternKind = "url" | "email" | "phone" | "postal" | "handle";

export interface ThreadsPublicFinding {
  readonly postId: string;
  readonly kinds: readonly PublicPatternKind[];
  readonly labels: readonly string[];
}

const DIRECT_PATTERNS: readonly {
  readonly kind: PublicPatternKind;
  readonly label: string;
  readonly pattern: RegExp;
}[] = [
  { kind: "url", label: "URLらしき文字列", pattern: /https?:\/\/[^\s]+/iu },
  { kind: "email", label: "メールアドレスらしき文字列", pattern: /[\p{L}\p{N}.%+-]+@[\p{L}\p{N}.-]+\.[a-z]{2,}/iu },
  { kind: "phone", label: "電話番号らしき文字列", pattern: /(?:0\d{1,4}[-ー]\d{1,4}[-ー]\d{3,4}|\b\d{10,11}\b)/u },
  { kind: "postal", label: "郵便番号らしき文字列", pattern: /(?<![\dー-])(?:〒\s*)?\d{3}[-ー]\d{4}(?![\dー-])/u },
  { kind: "handle", label: "@ユーザーネームらしき文字列", pattern: /(?:^|[\s(（])@[a-z0-9._]{1,30}\b/iu },
];

/**
 * 取得済みの本人投稿を、外部送信せず固定の文字列パターンだけで確認する。
 * 所有者・実在性・意味は推定せず、AI診断として扱わない。
 */
export function checkThreadsPublicText(posts: readonly Post[]): readonly ThreadsPublicFinding[] {
  return posts.map((post) => {
    const hits = DIRECT_PATTERNS.filter(({ pattern }) => pattern.test(post.text));
    return {
      postId: post.post_id,
      kinds: hits.map(({ kind }) => kind),
      labels: hits.map(({ label }) => label),
    };
  });
}
