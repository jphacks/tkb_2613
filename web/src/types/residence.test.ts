import { describe, expect, it } from "vitest";

import { SAMPLE_RESIDENCE } from "../fixtures/residence";
import { toDiagnoseEvent } from "./diagnose";
import { isResidenceEstimate, isResidenceOrNull } from "./residence";

describe("住まいの推定の形", () => {
  it("正しい形を受け付ける", () => {
    expect(isResidenceEstimate(SAMPLE_RESIDENCE)).toBe(true);
    expect(isResidenceOrNull(null)).toBe(true);
  });

  it("根拠の手がかりの番号が範囲の外なら断る", () => {
    const broken = {
      ...SAMPLE_RESIDENCE,
      evidence: [{ ...SAMPLE_RESIDENCE.evidence[0], clue_indices: [3] }],
    };
    expect(isResidenceEstimate(broken, 3)).toBe(false);
    expect(isResidenceEstimate(broken, 4)).toBe(true);
  });

  it.each([
    ["人数が負", { ...SAMPLE_RESIDENCE, region: { ...SAMPLE_RESIDENCE.region, people: -1 } }],
    ["層の番号が範囲の外", { ...SAMPLE_RESIDENCE, evidence: [{ ...SAMPLE_RESIDENCE.evidence[0], layer: 9 }] }],
    ["地図のマスの形が違う", { ...SAMPLE_RESIDENCE, map: { ...SAMPLE_RESIDENCE.map, cells: [{ lat: 1 }] } }],
    ["ラベルの種類が違う", { ...SAMPLE_RESIDENCE, map: { ...SAMPLE_RESIDENCE.map, labels: [{ kind: "shop", name: "x", lat: 1, lon: 1 }] } }],
    ["層7の形が違う", { ...SAMPLE_RESIDENCE, geoprofile: { places: [] } }],
  ])("%s なら断る", (_, value) => {
    expect(isResidenceEstimate(value)).toBe(false);
  });

  it("residence イベントを読む", () => {
    expect(toDiagnoseEvent("residence", JSON.stringify({ residence: SAMPLE_RESIDENCE }))).toEqual({
      event: "residence",
      residence: SAMPLE_RESIDENCE,
    });
    expect(toDiagnoseEvent("residence", JSON.stringify({ residence: null }))).toEqual({
      event: "residence",
      residence: null,
    });
    expect(() => toDiagnoseEvent("residence", JSON.stringify({ residence: { x: 1 } }))).toThrow();
  });
});
