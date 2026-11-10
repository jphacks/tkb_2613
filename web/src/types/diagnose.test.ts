import { describe, expect, it } from "vitest";

import { toDiagnoseEvent } from "./diagnose";

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
    expect(toDiagnoseEvent("clues", JSON.stringify(data))).toEqual({ event: "clues", ...data });
  });

  it("reads a clues event for a post that failed", () => {
    const data = { post_id: POST.post_id, clues: [], error: "写真を取得できませんでした" };
    expect(toDiagnoseEvent("clues", JSON.stringify(data))).toEqual({ event: "clues", ...data });
  });

  it("reads a conclusions event", () => {
    const data = { clues: [CLUE], conclusions: [CONCLUSION] };
    expect(toDiagnoseEvent("conclusions", JSON.stringify(data))).toEqual({ event: "conclusions", ...data });
  });

  it("reads sourced Web facts in a conclusions event", () => {
    const fact = {
      id: "official-1", subject: "青空社", relation: "legal_name_of", object: "株式会社青空",
      source_url: "https://example.org/company/training", source_title: "架空の公式会社案内",
      source_kind: "official_organization", excerpt: "青空社の正式名称は株式会社青空です",
      retrieved_at: "2026-11-10T10:00:00+09:00", verification_status: "verified",
    };
    const data = { clues: [], conclusions: [], web_facts: [fact], web_lookup_status: "fixture" };
    expect(toDiagnoseEvent("conclusions", JSON.stringify(data))).toEqual({ event: "conclusions", ...data });
    const claim = {
      attribute: "employer_name", value: "株式会社青空", confidence: 0.65, status: "weak",
      evidence: [{ post_id: null, clue_index: null, required: true, source: "public_web", web_fact_id: "missing" }],
    };
    expect(() => toDiagnoseEvent("conclusions", JSON.stringify({ ...data, profile_claims: [claim] }))).toThrow();
    expect(() => toDiagnoseEvent("conclusions", JSON.stringify({ ...data, web_facts: [fact, fact] }))).toThrow();
  });

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
    expect(toDiagnoseEvent("plan", JSON.stringify({ delete: [] }))).toBeNull();
  });

  it.each([
    ["data not JSON", "post", "{"],
    ["post in the wrong format", "post", JSON.stringify({ post: { ...POST, post_id: "" } })],
    ["post missing", "post", JSON.stringify({})],
    ["posts_seen negative", "done", JSON.stringify({ posts_seen: -1 })],
    ["posts_seen not an integer", "done", JSON.stringify({ posts_seen: "10" })],
    ["clue in the wrong format", "clues", JSON.stringify({ post_id: "x", clues: [{ ...CLUE, type: "?" }], error: null })],
    ["clues error not a string", "clues", JSON.stringify({ post_id: "x", clues: [], error: 1 })],
    [
      "evidence pointing outside the clues",
      "conclusions",
      JSON.stringify({ clues: [CLUE], conclusions: [{ ...CONCLUSION, clue_indices: [1] }] }),
    ],
    [
      "conclusion missing a field",
      "conclusions",
      JSON.stringify({ clues: [CLUE], conclusions: [{ ...CONCLUSION, value: undefined }] }),
    ],
  ])("throws on %s", (_, event, data) => {
    expect(() => toDiagnoseEvent(event, data)).toThrow();
  });
});
