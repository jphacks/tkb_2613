import { describe, expect, it } from "vitest";

import { toDiagnoseEvent } from "./diagnose";

const POST = {
  post_id: "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx",
  text: "夜勤明けのラーメン",
  created_at: "2026-10-20T08:31:00+09:00",
  images: [],
};

describe("toDiagnoseEvent", () => {
  it("reads a post event", () => {
    expect(toDiagnoseEvent("post", JSON.stringify({ post: POST }))).toEqual({ event: "post", post: POST });
  });

  it("reads a done event", () => {
    expect(toDiagnoseEvent("done", JSON.stringify({ posts_seen: 10 }))).toEqual({
      event: "done",
      posts_seen: 10,
    });
  });

  it("skips event names added later, so the screen keeps working when the api grows", () => {
    expect(toDiagnoseEvent("clues", JSON.stringify({ clues: [] }))).toBeNull();
  });

  it.each([
    ["data not JSON", "post", "{"],
    ["post in the wrong format", "post", JSON.stringify({ post: { ...POST, post_id: "x" } })],
    ["post missing", "post", JSON.stringify({})],
    ["posts_seen negative", "done", JSON.stringify({ posts_seen: -1 })],
    ["posts_seen not an integer", "done", JSON.stringify({ posts_seen: "10" })],
  ])("throws on %s", (_, event, data) => {
    expect(() => toDiagnoseEvent(event, data)).toThrow();
  });
});
