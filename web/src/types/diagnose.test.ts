import { describe, expect, it } from "vitest";

import { InvalidDiagnoseEventError, toDiagnoseEvent } from "./diagnose";
import { PROFILE_DIAGNOSED_ATTRIBUTES } from "./profile";

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

  it("reads all 24 candidate sets, including attributes that remain unknown", () => {
    const profile_claims = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => ({
      attribute,
      status: "unknown",
      candidates: [],
      candidate_pool: [],
      reason: "no_grounded_rule",
      conflicting_evidence: [],
    }));
    expect(toDiagnoseEvent("conclusions", JSON.stringify({
      clues: [CLUE], conclusions: [], profile_claims, profile_claim_suggestions: [],
    }))).toMatchObject({ event: "conclusions", profile_claims });
    expect(() => toDiagnoseEvent("conclusions", JSON.stringify({
      clues: [CLUE], conclusions: [], profile_claims: profile_claims.slice(1), profile_claim_suggestions: [],
    }))).toThrow(InvalidDiagnoseEventError);
  });

  it("reads scoreless profile relations with complete evidence paths", () => {
    const profile_relations = [{
      kind: "home_nearest_is_commute_origin",
      left: { kind: "profile_candidate", attribute: "home_nearest_station", value: "根津駅" },
      right: { kind: "profile_candidate", attribute: "regular_station", value: "根津駅" },
      evidence_paths: [{ confidence: 0.55, provenance: "combined_inference", evidence: [
        { post_id: POST.post_id, clue_index: null, required: true, source: "post_text", excerpt: "私の自宅最寄り駅は根津駅です" },
        { post_id: "at://did:plc:xxxx/app.bsky.feed.post/other", clue_index: null, required: true, source: "post_text", excerpt: "私は毎朝、自宅最寄りから通勤しています" },
      ] }],
    }];
    expect(toDiagnoseEvent("conclusions", JSON.stringify({ clues: [], conclusions: [], profile_relations }))).toMatchObject({
      event: "conclusions", profile_relations,
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
