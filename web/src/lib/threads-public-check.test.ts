import { describe, expect, it } from "vitest";

import type { Post } from "@/types/post";

import { checkThreadsPublicText } from "./threads-public-check";

function post(postId: string, text: string): Post {
  return { post_id: postId, text, created_at: "2026-11-12T12:00:00+09:00", images: [] };
}

describe("checkThreadsPublicText", () => {
  it("reports only direct, deterministic text patterns", () => {
    const [finding] = checkThreadsPublicText([
      post("threads:1", "連絡先 test@example.com / 090-1234-5678 https://example.com @sample"),
    ]);

    expect(finding).toEqual({
      postId: "threads:1",
      labels: [
        "URLらしき文字列",
        "メールアドレスらしき文字列",
        "電話番号らしき文字列",
        "@ユーザーネームらしき文字列",
      ],
    });
  });

  it("does not infer personal information from ordinary text", () => {
    expect(checkThreadsPublicText([post("threads:2", "今日は公園へ行きました")])).toEqual([
      { postId: "threads:2", labels: [] },
    ]);
  });

  it("distinguishes a postal-code pattern from a hyphenated phone number", () => {
    const findings = checkThreadsPublicText([
      post("threads:postal", "〒123-4567"),
      post("threads:phone", "090-1234-5678"),
    ]);

    expect(findings[0].labels).toContain("郵便番号らしき文字列");
    expect(findings[1].labels).not.toContain("郵便番号らしき文字列");
  });
});
