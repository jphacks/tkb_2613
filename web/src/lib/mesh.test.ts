import { describe, expect, it } from "vitest";

import { meshBounds, toLocalMeters } from "./mesh";

describe("meshBounds", () => {
  it("places a 500m mesh by its code (values from jismesh)", () => {
    // 根津駅（35.717325, 139.76575）を含むメッシュ。tkb_engine.walk_area.mesh_code と同じ番号
    const [south, west, north, east] = meshBounds("533946611");
    expect(south).toBeCloseTo(35.71666666666667, 9);
    expect(west).toBeCloseTo(139.7625, 9);
    expect(north - south).toBeCloseTo(15 / 3600, 12);
    expect(east - west).toBeCloseTo(22.5 / 3600, 12);
    expect(south).toBeLessThanOrEqual(35.717325);
    expect(north).toBeGreaterThan(35.717325);
    expect(west).toBeLessThanOrEqual(139.76575);
    expect(east).toBeGreaterThan(139.76575);
  });

  it("moves to the north and east quarters with the last digit", () => {
    const [s1, w1] = meshBounds("533946611");
    const [s4, w4] = meshBounds("533946614");
    expect(s4 - s1).toBeCloseTo(15 / 3600, 12);
    expect(w4 - w1).toBeCloseTo(22.5 / 3600, 12);
  });
});

describe("toLocalMeters", () => {
  it("puts east on +x and north on -y", () => {
    const local = toLocalMeters([35.7, 139.7]);
    const [x, y] = local(35.701, 139.701);
    expect(x).toBeGreaterThan(80);
    expect(x).toBeLessThan(100);
    expect(y).toBeLessThan(-100);
    expect(y).toBeGreaterThan(-120);
  });
});
