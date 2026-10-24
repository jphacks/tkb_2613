import { describe, expect, it } from "vitest";

import { isPost } from "./post";

const IMAGE = {
  index: 0,
  url: "https://cdn.bsky.app/img/feed_fullsize/plain/did:plc:xxxx/abc@jpeg",
  alt: "",
  width: 1200,
  height: 900,
};

const POST = {
  post_id: "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx",
  text: "夜勤明けのラーメン",
  created_at: "2026-10-20T08:31:00+09:00",
  images: [IMAGE],
};

describe("isPost", () => {
  it("accepts the documented post format", () => {
    expect(isPost(POST)).toBe(true);
  });

  it("accepts a post without images", () => {
    expect(isPost({ ...POST, images: [] })).toBe(true);
  });

  it.each([
    ["null", null],
    ["image outside the CDN", { ...POST, images: [{ ...IMAGE, url: "https://example.com/a.jpg" }] }],
    ["CDN look-alike host", { ...POST, images: [{ ...IMAGE, url: "https://cdn.bsky.app.evil.test/a" }] }],
    ["image index out of order", { ...POST, images: [{ ...IMAGE, index: 1 }] }],
    ["five images", { ...POST, images: [0, 1, 2, 3, 4].map((index) => ({ ...IMAGE, index })) }],
    ["zero width", { ...POST, images: [{ ...IMAGE, width: 0 }] }],
    ["date without offset", { ...POST, created_at: "2026-10-20T08:31:00" }],
    ["not a date", { ...POST, created_at: "yesterday+09:00" }],
    ["empty post_id", { ...POST, post_id: "" }],
  ])("rejects %s", (_label, input) => {
    expect(isPost(input)).toBe(false);
  });
});
