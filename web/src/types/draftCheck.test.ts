import { describe, expect, it } from "vitest";

import { isDraftCheckResponse } from "./draftCheck";

const clue = {
  post_id: "draft:ephemeral",
  image_index: null,
  type: "place_text",
  value: "架空の場所",
  region: null,
  confidence: 0.8,
  source: "text",
};

const response = {
  posts_checked: 1,
  mock_mode: false,
  notices: ["架空の通知"],
  overlaps: [{
    clue,
    evidence: [{ post_id: "at://did:plc:test/app.bsky.feed.post/a", created_at: "2026-10-20T08:00:00Z" }],
  }],
};

describe("isDraftCheckResponse", () => {
  it("accepts an observation-only result", () => {
    expect(isDraftCheckResponse(response)).toBe(true);
  });

  it.each([
    ["null", null],
    ["negative post count", { ...response, posts_checked: -1 }],
    ["fractional post count", { ...response, posts_checked: 1.5 }],
    ["invalid mock flag", { ...response, mock_mode: "false" }],
    ["non-string notice", { ...response, notices: [1] }],
    ["invalid clue", { ...response, overlaps: [{ ...response.overlaps[0], clue: { ...clue, type: "unknown" } }] }],
    ["empty evidence", { ...response, overlaps: [{ ...response.overlaps[0], evidence: [] }] }],
    ["invalid date", { ...response, overlaps: [{ ...response.overlaps[0], evidence: [{ post_id: "post", created_at: "not-a-date" }] }] }],
  ])("rejects %s", (_name, value) => {
    expect(isDraftCheckResponse(value)).toBe(false);
  });
});
