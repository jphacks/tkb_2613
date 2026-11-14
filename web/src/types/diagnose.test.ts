import { describe, expect, it } from "vitest";

import { InvalidDiagnoseEventError, isDiagnosisSnapshot, isLegacySharedSnapshot, isSimulation, isThreadsSimulation, toDiagnoseEvent } from "./diagnose";
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
const PROFILE_CLAIMS = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => ({
  attribute, status: "unknown", candidates: [], candidate_pool: [],
  reason: "no_grounded_rule", conflicting_evidence: [],
}));

describe("isDiagnosisSnapshot", () => {
  const snapshot = {
    posts: [POST], clues: [CLUE], profile_claims: PROFILE_CLAIMS,
    plan: { delete: [], broken: [], after: PROFILE_CLAIMS, posts: [] },
  };

  it("accepts deletion-aware snapshots and rejects IDs outside the snapshot", () => {
    expect(isDiagnosisSnapshot(snapshot)).toBe(true);
    expect(isDiagnosisSnapshot({ ...snapshot, deleted: [POST.post_id] })).toBe(true);
    expect(isDiagnosisSnapshot({ ...snapshot, deleted: [] })).toBe(true);
    expect(isDiagnosisSnapshot({ ...snapshot, deleted: ["at://did:plc:other/app.bsky.feed.post/missing"] })).toBe(false);
    expect(isDiagnosisSnapshot({ ...snapshot, deleted: [1] })).toBe(false);
    expect(isDiagnosisSnapshot({ ...snapshot, conclusions: [] })).toBe(false);
  });
});

describe("simulation API boundaries", () => {
  it("accepts legacy conclusions only on the Threads compatibility validator", () => {
    const legacy = { delete: [], broken: ["routine"], after: [CONCLUSION] };
    expect(isSimulation(legacy)).toBe(false);
    expect(isThreadsSimulation(legacy)).toBe(true);
  });
});

describe("isLegacySharedSnapshot", () => {
  it("accepts saved legacy Conclusion and plan before/after values", () => {
    const oldConclusion = { ...CONCLUSION, clue_indices: [] };
    expect(isLegacySharedSnapshot({
      posts: [POST],
      clues: [CLUE],
      conclusions: [oldConclusion],
      plan: {
        delete: [], broken: ["routine"], before: [oldConclusion], after: [oldConclusion], posts: [],
      },
    })).toBe(true);
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
    const data = { clues: [CLUE], profile_claims: PROFILE_CLAIMS };
    expect(toDiagnoseEvent("conclusions", JSON.stringify(data))).toEqual({
      event: "conclusions",
      ...data,
    });
    expect(() => toDiagnoseEvent("conclusions", JSON.stringify({ ...data, conclusions: [CONCLUSION] })))
      .toThrow(InvalidDiagnoseEventError);
  });

  it("validates per-image place candidates, clue references, and source licenses", () => {
    const photoClue = { ...CLUE, image_index: 0, type: "shop", source: "ocr", region: [1, 1, 5, 5] };
    const result = {
      post_id: POST.post_id, image_index: 0, status: "candidate", granularity: "facility",
      candidates: [{
        place_id: "places:one", label: "架空の施設", place_type: "facility", photo_relation: "visible_in_frame",
        area_label: null, score: 0.91, evidence: [{ kind: "clue", clue_index: 0, reference_id: null }],
        source_ids: ["source:one"], sources: [{
          source_id: "source:one", provider: "fixture", dataset: "places", license_id: "CC-BY-4.0",
          record_id: "one", version: "v1", attribution: null,
        }],
      }],
      reason_codes: [], lookup_status: "local_only",
    };
    expect(toDiagnoseEvent("conclusions", JSON.stringify({ clues: [photoClue], profile_claims: PROFILE_CLAIMS, photo_place_results: [result] })))
      .toMatchObject({ event: "conclusions", photo_place_results: [result] });
    expect(() => toDiagnoseEvent("conclusions", JSON.stringify({
      clues: [photoClue], profile_claims: PROFILE_CLAIMS, photo_place_results: [{ ...result, candidates: [{
        ...result.candidates[0], evidence: [{ kind: "clue", clue_index: 4, reference_id: null }],
      }] }],
    }))).toThrow(InvalidDiagnoseEventError);
    expect(() => toDiagnoseEvent("conclusions", JSON.stringify({
      clues: [photoClue], profile_claims: PROFILE_CLAIMS, photo_place_results: [{ ...result, status: "ambiguous" }],
    }))).toThrow(InvalidDiagnoseEventError);
  });

  it("accepts a corroboration only when it points to another candidate in the same result", () => {
    const photoClue = { ...CLUE, image_index: 0, type: "shop", source: "ocr", region: [1, 1, 5, 5] };
    const candidate = (place_id: string, extra: object = {}) => ({
      place_id, label: "市民会館", place_type: "facility", photo_relation: "visible_in_frame",
      area_label: "府中市", score: null, evidence: [{ kind: "clue", clue_index: 0, reference_id: null }],
      source_ids: [`source:${place_id}`], sources: [], ...extra,
    });
    const result = (candidates: object[]) => ({
      post_id: POST.post_id, image_index: 0, status: "ambiguous", granularity: "facility",
      candidates, reason_codes: ["multiple_matches"], lookup_status: "web_searched",
    });
    const event = (candidates: object[]) => JSON.stringify({ clues: [photoClue], profile_claims: PROFILE_CLAIMS, photo_place_results: [result(candidates)] });

    expect(toDiagnoseEvent("conclusions", event([candidate("p05:1"), candidate("brave:1", { corroborated_by: ["p05:1"] })])))
      .toMatchObject({ event: "conclusions" });
    for (const refs of [["p05:missing"], ["brave:1"], "p05:1", ["p05:1", "p05:1"]]) {
      expect(() => toDiagnoseEvent("conclusions", event([candidate("p05:1"), candidate("brave:1", { corroborated_by: refs })])))
        .toThrow(InvalidDiagnoseEventError);
    }
  });

  it("reads all candidate sets, including attributes that remain unknown", () => {
    const profile_claims = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => ({
      attribute,
      status: "unknown",
      candidates: [],
      candidate_pool: [],
      reason: "no_grounded_rule",
      conflicting_evidence: [],
    }));
    expect(toDiagnoseEvent("conclusions", JSON.stringify({
      clues: [CLUE], profile_claims, profile_claim_suggestions: [],
    }))).toMatchObject({ event: "conclusions", profile_claims });
    expect(toDiagnoseEvent("conclusions", JSON.stringify({
      clues: [CLUE], profile_claims: profile_claims.slice(1), profile_claim_suggestions: [],
    }))).toMatchObject({
      event: "conclusions",
      clues: [CLUE],
      profile_claims: [],
      profile_claims_error: true,
    });
    expect(isDiagnosisSnapshot({
      posts: [POST],
      deleted: [],
      clues: [CLUE],
      profile_claims: profile_claims.slice(1),
      plan: { delete: [], broken: [], after: [], posts: [] },
    })).toBe(false);
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
    expect(toDiagnoseEvent("conclusions", JSON.stringify({ clues: [], profile_claims: PROFILE_CLAIMS, profile_relations }))).toMatchObject({
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

  it("reads a plan event with profile candidate sets", () => {
    const profileClaims = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => ({
      attribute,
      status: "unknown",
      candidates: [],
      candidate_pool: [],
      reason: "no_grounded_rule",
      conflicting_evidence: [],
    }));
    const data = {
      delete: [POST.post_id],
      broken: ["routine"],
      after: profileClaims,
      posts: [{ post_id: POST.post_id, broken: ["routine"] }],
    };
    expect(toDiagnoseEvent("plan", JSON.stringify(data))).toEqual({
      event: "plan",
      ...data,
    });
  });

  it("rejects a legacy Conclusion plan on the Bluesky event contract", () => {
    const data = {
      delete: [POST.post_id],
      broken: ["routine"],
      after: [CONCLUSION],
      posts: [{ post_id: POST.post_id, broken: ["routine"] }],
    };
    expect(() => toDiagnoseEvent("plan", JSON.stringify(data))).toThrow(InvalidDiagnoseEventError);
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
  ])("throws on %s", (_, event, data) => {
    expect(() => toDiagnoseEvent(event, data)).toThrow();
  });

  it.each([
    PROFILE_CLAIMS.map((claim, index) => index === 0 ? { ...claim, reason: null } : claim),
    PROFILE_CLAIMS.slice(1),
  ])("surfaces malformed candidate sets as a board warning", (profile_claims) => {
    expect(toDiagnoseEvent("conclusions", JSON.stringify({ clues: [CLUE], profile_claims }))).toMatchObject({
      event: "conclusions", profile_claims: [], profile_claims_error: true,
    });
  });
});
