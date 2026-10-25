import { describe, expect, it } from "vitest";

import { CLUE_SOURCES, CLUE_TYPES, isDetectResponse } from "./clue";

const POST_ID = "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx";

const PHOTO_CLUE = {
  post_id: POST_ID,
  image_index: 0,
  type: "station_sign",
  value: "新宿",
  region: [120, 80, 340, 150],
  confidence: 0.92,
  source: "vlm",
};

const TEXT_CLUE = {
  post_id: POST_ID,
  image_index: null,
  type: "routine_text",
  value: "夜勤明け",
  region: null,
  confidence: 0.9,
  source: "text",
};

describe("isDetectResponse", () => {
  it("accepts photo and text clues in the documented format", () => {
    expect(isDetectResponse({ clues: [PHOTO_CLUE, TEXT_CLUE] })).toBe(true);
  });

  it("accepts an empty clue list", () => {
    expect(isDetectResponse({ clues: [] })).toBe(true);
  });

  it("accepts a photo clue without a region", () => {
    expect(isDetectResponse({ clues: [{ ...PHOTO_CLUE, type: "uniform", region: null }] })).toBe(true);
  });

  it("accepts name_text from both photo and text", () => {
    expect(
      isDetectResponse({
        clues: [
          { ...PHOTO_CLUE, type: "name_text" },
          { ...TEXT_CLUE, type: "name_text" },
        ],
      }),
    ).toBe(true);
  });

  it.each([
    ["null", null],
    ["missing clues", {}],
    ["clues not an array", { clues: "x" }],
    ["unknown type", { clues: [{ ...PHOTO_CLUE, type: "unknown" }] }],
    ["unknown source", { clues: [{ ...PHOTO_CLUE, source: "browser" }] }],
    ["confidence above 1", { clues: [{ ...PHOTO_CLUE, confidence: 1.2 }] }],
    ["region too short", { clues: [{ ...PHOTO_CLUE, region: [1, 2, 3] }] }],
    ["region inverted", { clues: [{ ...PHOTO_CLUE, region: [340, 80, 120, 150] }] }],
    ["value not a string", { clues: [{ ...PHOTO_CLUE, value: 1 }] }],
    ["empty post_id", { clues: [{ ...PHOTO_CLUE, post_id: "" }] }],
    ["negative image_index", { clues: [{ ...PHOTO_CLUE, image_index: -1 }] }],
    ["region on a text clue", { clues: [{ ...TEXT_CLUE, region: [0, 0, 10, 10] }] }],
    ["photo clue without image_index", { clues: [{ ...PHOTO_CLUE, image_index: null }] }],
    ["text source with image_index", { clues: [{ ...PHOTO_CLUE, type: "name_text", source: "text" }] }],
    ["photo-only type from text", { clues: [{ ...TEXT_CLUE, type: "station_sign" }] }],
    ["text-only type from photo", { clues: [{ ...PHOTO_CLUE, type: "age_text", region: null }] }],
  ])("rejects %s", (_label, input) => {
    expect(isDetectResponse(input)).toBe(false);
  });
});

describe("clue enums", () => {
  it("match the types and sources documented in CLAUDE.md", () => {
    expect([...CLUE_TYPES].sort()).toEqual(
      [
        "station_sign", "rail_view", "reflection", "shop", "landmark", "address_text",
        "postal_code", "phone", "plate", "uniform", "face", "key", "code", "local_item", "notice",
        "name_text", "org_text", "handle_text", "place_text",
        "age_text", "routine_text", "relation_text",
      ].sort(),
    );
    expect([...CLUE_SOURCES].sort()).toEqual(["meta", "ocr", "text", "vlm"]);
  });
});
