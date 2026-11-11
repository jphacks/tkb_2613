import { describe, expect, it } from "vitest";

import {
  InvalidDiagnoseEventError, STRONG_CONFIDENCE, confidenceLevel, isDemoDiagnosis, isDiagnosisSnapshot,
  toDiagnoseEvent,
} from "./diagnose";

const POST = {
  post_id: "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx",
  text: "夜勤明けのラーメン",
  created_at: "2026-10-20T08:31:00+09:00",
  images: [],
};

const CLUE = {
  post_id: POST.post_id,
  image_index: null,
  type: "routine_text",
  value: "夜勤明け",
  region: null,
  confidence: 0.9,
  source: "text",
};

const CONCLUSION = {
  rule: "R3",
  attribute: "routine",
  value: "毎週火曜 20時ごろ",
  clue_indices: [0],
  note: "",
};

describe("isDiagnosisSnapshot", () => {
  const snapshot = {
    posts: [POST],
    clues: [CLUE],
    conclusions: [CONCLUSION],
    plan: { delete: [], broken: [], after: [CONCLUSION], posts: [] },
  };

  it("accepts a snapshot without deleted posts (shared results do not have them)", () => {
    expect(isDiagnosisSnapshot(snapshot)).toBe(true);
  });

  it("accepts deleted posts that were part of the diagnosis", () => {
    expect(isDiagnosisSnapshot({ ...snapshot, deleted: [POST.post_id] })).toBe(true);
    expect(isDiagnosisSnapshot({ ...snapshot, deleted: [] })).toBe(true);
  });

  it("rejects deleted posts that were not diagnosed or are not strings", () => {
    expect(isDiagnosisSnapshot({ ...snapshot, deleted: ["at://did:plc:other/app.bsky.feed.post/3k"] })).toBe(false);
    expect(isDiagnosisSnapshot({ ...snapshot, deleted: [1] })).toBe(false);
    expect(isDiagnosisSnapshot({ ...snapshot, deleted: null })).toBe(false);
  });
});

describe("isDemoDiagnosis", () => {
  const snapshot = {
    posts: [POST],
    clues: [CLUE],
    conclusions: [CONCLUSION],
    plan: { delete: [], broken: [], after: [], posts: [] },
  };

  it("accepts only snapshots marked as the demo", () => {
    expect(isDemoDiagnosis({ ...snapshot, demo: true })).toBe(true);
    expect(isDemoDiagnosis(snapshot)).toBe(false);
    expect(isDemoDiagnosis({ ...snapshot, demo: "true" })).toBe(false);
    expect(isDemoDiagnosis({ demo: true })).toBe(false);
  });
});

describe("conclusion confidence", () => {
  it("accepts a confidence between 0 and 1 and conclusions without one", () => {
    const event = (conclusion: unknown) =>
      toDiagnoseEvent("conclusions", JSON.stringify({ clues: [CLUE], conclusions: [conclusion] }));
    expect(event({ ...CONCLUSION, confidence: 0.95 })).not.toBeNull();
    expect(event(CONCLUSION)).not.toBeNull();
    for (const bad of [-0.1, 1.5, "0.9", null]) {
      expect(() => event({ ...CONCLUSION, confidence: bad })).toThrow(InvalidDiagnoseEventError);
    }
  });

  it("splits confidence into strong and weak at STRONG_CONFIDENCE", () => {
    expect(confidenceLevel({ ...CONCLUSION, confidence: STRONG_CONFIDENCE })).toBe("strong");
    expect(confidenceLevel({ ...CONCLUSION, confidence: STRONG_CONFIDENCE - 0.01 })).toBe("weak");
    expect(confidenceLevel(CONCLUSION)).toBeNull();
  });
});

describe("toDiagnoseEvent", () => {
  it("reads a clues event", () => {
    const data = { post_id: POST.post_id, clues: [CLUE], error: null };
    expect(toDiagnoseEvent("clues", JSON.stringify(data))).toEqual({
      event: "clues",
      ...data,
    });
  });

  it("reads a clues event for a post that failed", () => {
    const data = {
      post_id: POST.post_id,
      clues: [],
      error: "写真を取得できませんでした",
    };
    expect(toDiagnoseEvent("clues", JSON.stringify(data))).toEqual({
      event: "clues",
      ...data,
    });
  });

  it("reads a conclusions event", () => {
    const data = { clues: [CLUE], conclusions: [CONCLUSION] };
    expect(toDiagnoseEvent("conclusions", JSON.stringify(data))).toEqual({
      event: "conclusions",
      ...data,
    });
  });

  it("reads a post event", () => {
    expect(toDiagnoseEvent("post", JSON.stringify({ post: POST }))).toEqual({
      event: "post",
      post: POST,
    });
  });

  it("reads a done event", () => {
    expect(toDiagnoseEvent("done", JSON.stringify({ posts_seen: 10 }))).toEqual(
      {
        event: "done",
        posts_seen: 10,
      },
    );
  });

  it("reads a plan event", () => {
    const data = {
      delete: [POST.post_id],
      broken: ["routine"],
      after: [],
      posts: [{ post_id: POST.post_id, broken: ["routine"] }],
    };
    expect(toDiagnoseEvent("plan", JSON.stringify(data))).toEqual({
      event: "plan",
      ...data,
    });
  });

  it("rejects a plan event without the per-post breakdown", () => {
    const data = { delete: [], broken: [], after: [] };
    expect(() => toDiagnoseEvent("plan", JSON.stringify(data))).toThrow(
      InvalidDiagnoseEventError,
    );
  });

  it("skips event names added later, so the screen keeps working when the api grows", () => {
    expect(
      toDiagnoseEvent("profile", JSON.stringify({ items: [] })),
    ).toBeNull();
  });

  it.each([
    ["data not JSON", "post", "{"],
    [
      "post in the wrong format",
      "post",
      JSON.stringify({ post: { ...POST, post_id: "" } }),
    ],
    ["post missing", "post", JSON.stringify({})],
    ["posts_seen negative", "done", JSON.stringify({ posts_seen: -1 })],
    ["posts_seen not an integer", "done", JSON.stringify({ posts_seen: "10" })],
    [
      "clue in the wrong format",
      "clues",
      JSON.stringify({
        post_id: "x",
        clues: [{ ...CLUE, type: "?" }],
        error: null,
      }),
    ],
    [
      "clues error not a string",
      "clues",
      JSON.stringify({ post_id: "x", clues: [], error: 1 }),
    ],
    [
      "evidence pointing outside the clues",
      "conclusions",
      JSON.stringify({
        clues: [CLUE],
        conclusions: [{ ...CONCLUSION, clue_indices: [1] }],
      }),
    ],
    [
      "conclusion missing a field",
      "conclusions",
      JSON.stringify({
        clues: [CLUE],
        conclusions: [{ ...CONCLUSION, value: undefined }],
      }),
    ],
  ])("throws on %s", (_, event, data) => {
    expect(() => toDiagnoseEvent(event, data)).toThrow();
  });
});
