import { describe, expect, it } from "vitest";

import fixture from "../../../eval/fixtures/demo_observations.json";

import { isPost } from "./post";

const IMAGE = {
  index: 0,
  url: "https://cdn.bsky.app/img/feed_fullsize/plain/did:plc:xxxx/demo01@jpeg",
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
  it("accepts a post in the documented format", () => {
    expect(isPost(POST)).toBe(true);
  });

  it("accepts a text-only post and a photo-only post", () => {
    expect(isPost({ ...POST, images: [] })).toBe(true);
    expect(isPost({ ...POST, text: "" })).toBe(true);
  });

  it("accepts images numbered from 0 in order", () => {
    expect(isPost({ ...POST, images: [IMAGE, { ...IMAGE, index: 1 }] })).toBe(true);
  });

  it.each([
    ["null", null],
    ["post_id not an AT URI", { ...POST, post_id: "https://bsky.app/profile/x/post/1" }],
    ["text not a string", { ...POST, text: 1 }],
    ["created_at not a date", { ...POST, created_at: "昨日" }],
    ["images not an array", { ...POST, images: "x" }],
    ["image not on the Bluesky CDN", { ...POST, images: [{ ...IMAGE, url: "https://example.com/a.jpg" }] }],
    ["image over plain http", { ...POST, images: [{ ...IMAGE, url: "http://cdn.bsky.app/a.jpg" }] }],
    ["image index out of order", { ...POST, images: [{ ...IMAGE, index: 1 }] }],
    ["image width zero", { ...POST, images: [{ ...IMAGE, width: 0 }] }],
    ["image height not an integer", { ...POST, images: [{ ...IMAGE, height: 1.5 }] }],
    ["image alt missing", { ...POST, images: [{ ...IMAGE, alt: undefined }] }],
  ])("rejects %s", (_, value) => {
    expect(isPost(value)).toBe(false);
  });

  it("accepts every post of the demo account fixture", () => {
    expect(fixture.posts.length).toBeGreaterThan(0);
    expect(fixture.posts.filter((p: unknown) => !isPost(p))).toEqual([]);
  });
});
