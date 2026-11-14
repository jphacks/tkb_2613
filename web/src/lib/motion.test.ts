import { describe, expect, it } from "vitest";

import { paced, staggerDelay } from "./motion";

describe("staggerDelay", () => {
  it("shifts each item by 0.4 seconds while everything fits in 2 seconds", () => {
    expect([0, 1, 2].map((i) => staggerDelay(i, 3))).toEqual([0, 0.4, 0.8]);
  });

  it("packs many items so that the last one finishes within 2 seconds", () => {
    const last = staggerDelay(9, 10, { duration: 0.6 });
    expect(last + 0.6).toBeCloseTo(2);
  });

  it("does not delay a single item", () => {
    expect(staggerDelay(0, 1)).toBe(0);
  });
});

describe("paced", () => {
  it("scales the delay by the stage pace with 1 as the default", () => {
    expect(paced(1.6)).toBe("calc(var(--stage-pace, 1) * 1.6s)");
    expect(paced(0.1 + 0.2)).toBe("calc(var(--stage-pace, 1) * 0.3s)");
  });
});
