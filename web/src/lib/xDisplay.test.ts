import { describe, expect, it } from "vitest";

import { isAllowedXHref, isXDisplay, segmentXText, type XEntity } from "./xDisplay";

const mention = (start: number, end: number, href = "https://x.com/friend_1"): XEntity =>
  ({ kind: "mention", start, end, href, display: null });

describe("segmentXText", () => {
  it("splits by code points so emoji before an entity do not shift it", () => {
    const text = "🍜 @friend_1 と #新宿 https://t.co/abc";
    const segments = segmentXText(text, [
      { kind: "url", start: 18, end: 34, href: "https://t.co/abc", display: "example.com/page" },
      mention(2, 11),
      { kind: "hashtag", start: 14, end: 17, href: "https://x.com/search?q=%23新宿", display: null },
    ]);

    expect(segments.map((s) => s.kind)).toEqual(["text", "mention", "text", "hashtag", "text", "url"]);
    expect(segments[1]).toMatchObject({ text: "@friend_1", label: "@friend_1" });
    expect(segments[3]).toMatchObject({ text: "#新宿" });
    expect(segments[5]).toMatchObject({ text: "https://t.co/abc", label: "example.com/page" });
    expect(segments.map((s) => s.text).join("")).toBe(text); // 本文は変えない
  });

  it("keeps broken, overlapping, or disallowed entities as plain text", () => {
    const text = "@a_b @c_d";
    const segments = segmentXText(text, [
      mention(0, 4),
      mention(2, 6),
      mention(5, 99),
      mention(5, 9, "https://evil.example/c_d"),
      { kind: "url", start: 5, end: 9, href: "javascript:alert(1)", display: "x" },
    ]);
    expect(segments.map((s) => s.kind)).toEqual(["mention", "text"]);
    expect(segments.map((s) => s.text).join("")).toBe(text);
  });

  it("returns the whole text when there are no entities", () => {
    expect(segmentXText("今日は晴れ", [])).toEqual([{ kind: "text", text: "今日は晴れ" }]);
    expect(segmentXText("", [])).toEqual([]);
  });
});

describe("isAllowedXHref", () => {
  it("allows only https x.com for profiles and hashtags and t.co for urls", () => {
    expect(isAllowedXHref("mention", "https://x.com/a")).toBe(true);
    expect(isAllowedXHref("mention", "http://x.com/a")).toBe(false);
    expect(isAllowedXHref("mention", "https://x.com.evil.example/a")).toBe(false);
    expect(isAllowedXHref("url", "https://t.co/a")).toBe(true);
    expect(isAllowedXHref("url", "https://x.com/a")).toBe(false);
    expect(isAllowedXHref("hashtag", "not a url")).toBe(false);
  });
});

describe("isXDisplay", () => {
  it("accepts the API shape and rejects malformed input", () => {
    const valid = {
      synthetic: false,
      author: { username: "u", name: "n", profile_image_url: null, profile_url: "https://x.com/u" },
      posts: { "x:1": { permalink: "https://x.com/u/status/1", edited: false, entities: [mention(0, 1)] } },
    };
    expect(isXDisplay(valid)).toBe(true);
    expect(isXDisplay({ ...valid, synthetic: "no" })).toBe(false);
    expect(isXDisplay({ ...valid, posts: { "x:1": { permalink: 1, edited: false, entities: [] } } })).toBe(false);
  });
});
