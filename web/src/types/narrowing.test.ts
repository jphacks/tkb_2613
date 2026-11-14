import { describe, expect, it } from "vitest";

import { toDiagnoseEvent } from "./diagnose";
import { isNarrowing } from "./narrowing";
import { PROFILE_DIAGNOSED_ATTRIBUTES } from "./profile";

const VALID = {
  region: { label: "1都3県", households: 17_410_647, bounds: [34.9, 138.9, 36.9, 140.9] },
  walk: {
    station: "根津駅",
    minutes: 4,
    radius_m: 320,
    center: [35.717325, 139.76575],
    households: 4400,
    meshes: [{ code: "533946611", households: 4441, share: 0.746 }],
    post_ids: ["w"],
  },
  block: null,
  sources: ["令和2年国勢調査"],
};

describe("isNarrowing", () => {
  it("accepts the api shape", () => {
    expect(isNarrowing(VALID)).toBe(true);
    expect(isNarrowing({ ...VALID, walk: null, block: { value: "文京区弥生 2-99 付近", post_ids: ["env"] } })).toBe(true);
  });

  it.each([
    ["no stage", { ...VALID, walk: null }],
    ["bad mesh code", { ...VALID, walk: { ...VALID.walk, meshes: [{ code: "5339", households: 1, share: 0.5 }] } }],
    ["share above 1", { ...VALID, walk: { ...VALID.walk, meshes: [{ code: "533946611", households: 1, share: 1.5 }] } }],
    ["negative households", { ...VALID, region: { ...VALID.region, households: -1 } }],
    ["no evidence posts", { ...VALID, walk: { ...VALID.walk, post_ids: [] } }],
    ["empty station", { ...VALID, walk: { ...VALID.walk, station: "" } }],
    ["bounds out of order", { ...VALID, region: { ...VALID.region, bounds: [36.9, 138.9, 34.9, 140.9] } }],
  ])("rejects %s", (_, value) => {
    expect(isNarrowing(value)).toBe(false);
  });
});

describe("conclusions event", () => {
  it("keeps valid narrowing and drops a broken one without failing the diagnosis", () => {
    const base = {
      clues: [],
      profile_claims: PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => ({
        attribute,
        status: "unknown",
        candidates: [],
        candidate_pool: [],
        reason: "no_grounded_rule",
        conflicting_evidence: [],
      })),
    };
    const good = toDiagnoseEvent("conclusions", JSON.stringify({ ...base, narrowing: VALID }));
    expect(good?.event === "conclusions" && good.narrowing).toEqual(VALID);
    const broken = toDiagnoseEvent("conclusions", JSON.stringify({ ...base, narrowing: { region: 1 } }));
    expect(broken?.event === "conclusions" && broken.narrowing).toBeNull();
    const old = toDiagnoseEvent("conclusions", JSON.stringify(base));
    expect(old?.event === "conclusions" && "narrowing" in old).toBe(false);
  });
});
