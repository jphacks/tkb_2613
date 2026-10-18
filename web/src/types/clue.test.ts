import { describe, expect, it } from "vitest";

import { CLUE_SOURCES, CLUE_TYPES, isDetectResponse } from "./clue";

const VALID_CLUE = {
  type: "station_sign",
  value: "新宿",
  region: [120, 80, 340, 150],
  confidence: 0.92,
  source: "vlm",
};

describe("isDetectResponse", () => {
  it("accepts the documented clue format", () => {
    expect(isDetectResponse({ clues: [VALID_CLUE] })).toBe(true);
  });

  it("accepts an empty clue list", () => {
    expect(isDetectResponse({ clues: [] })).toBe(true);
  });

  it.each([
    ["null", null],
    ["missing clues", {}],
    ["clues not an array", { clues: "x" }],
    ["unknown type", { clues: [{ ...VALID_CLUE, type: "unknown" }] }],
    ["unknown source", { clues: [{ ...VALID_CLUE, source: "gpt" }] }],
    ["confidence above 1", { clues: [{ ...VALID_CLUE, confidence: 1.2 }] }],
    ["region too short", { clues: [{ ...VALID_CLUE, region: [1, 2, 3] }] }],
    ["region inverted", { clues: [{ ...VALID_CLUE, region: [340, 80, 120, 150] }] }],
    ["value not a string", { clues: [{ ...VALID_CLUE, value: 1 }] }],
  ])("rejects %s", (_label, input) => {
    expect(isDetectResponse(input)).toBe(false);
  });
});

describe("clue enums", () => {
  it("match the types and sources documented in CLAUDE.md", () => {
    expect([...CLUE_TYPES].sort()).toEqual(
      [
        "station_sign", "address_text", "postal_code", "phone", "shop", "plate",
        "landmark", "exif_gps", "face", "iris", "key", "code",
      ].sort(),
    );
    expect([...CLUE_SOURCES].sort()).toEqual(["browser", "ocr", "vlm"]);
  });
});
