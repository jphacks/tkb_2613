import { describe, expect, it } from "vitest";

import { formatClock, isThreadsProgress, progressErrorKey } from "./threads-progress";

const RUNNING = {
  state: "running", stage: "reading", elapsed_ms: 1200, posts_total: 3, posts_read: 1,
  read_post_ids: ["threads:1"], stages: ["checking_model", "fetching", "reading", "inferring"], error: null,
};

describe("isThreadsProgress", () => {
  it("accepts the api response", () => {
    expect(isThreadsProgress(RUNNING)).toBe(true);
  });

  it.each([
    ["an unknown state", { ...RUNNING, state: "queued" }],
    ["an unknown stage", { ...RUNNING, stage: "guessing" }],
    ["a fractional count", { ...RUNNING, posts_read: 0.5 }],
    ["a percentage instead of counts", { ...RUNNING, posts_total: null, posts_read: -1 }],
    ["an unknown error code", { ...RUNNING, error: "gpu exploded" }],
    ["non-string post ids", { ...RUNNING, read_post_ids: [1] }],
  ])("rejects %s", (_name, value) => {
    expect(isThreadsProgress(value)).toBe(false);
  });
});

describe("formatClock", () => {
  it.each([
    [0, "0:00"],
    [5_999, "0:05"],
    [65_000, "1:05"],
    [3_725_000, "1:02:05"],
    [-10, "0:00"],
  ])("formats %d ms as %s", (ms, text) => {
    expect(formatClock(ms)).toBe(text);
  });
});

describe("progressErrorKey", () => {
  it("separates a stopped model from other failures", () => {
    expect(progressErrorKey("model_unavailable")).toBe("modelUnavailable");
    expect(progressErrorKey("failed")).toBe("failed");
  });
});
