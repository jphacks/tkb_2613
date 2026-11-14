import { act, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { visibleNarrowing, type Narrowing } from "@/types/narrowing";

import { NarrowingStages, regionCount } from "./NarrowingStages";

/** 架空のデモ。数は tkb_engine.narrowing の形に合わせた例 */
const NARROWING: Narrowing = {
  region: { label: "1都3県", households: 17_410_647, bounds: [34.9, 138.9, 36.9, 140.9] },
  walk: {
    station: "根津駅",
    minutes: 4,
    radius_m: 320,
    center: [35.717325, 139.76575],
    households: 4400,
    meshes: [
      { code: "533946611", households: 4441, share: 0.746 },
      { code: "533946513", households: 2445, share: 0.427 },
    ],
    post_ids: ["s1", "s2", "w"],
  },
  block: { value: "文京区弥生 2-99 付近", post_ids: ["env"] },
  sources: ["令和2年国勢調査 地域メッシュ統計", "徒歩1分＝80m（不動産の表示に関する公正競争規約施行規則 第9条第9号）"],
};

function delayOf(el: Element | null): string {
  return el?.getAttribute("style") ?? "";
}

describe("regionCount", () => {
  it("floors the 1都3県 households to units of 100,000", () => {
    expect(regionCount(17_410_647)).toBe("約1,740万世帯");
    expect(regionCount(17_499_999)).toBe("約1,740万世帯");
  });
});

describe("NarrowingStages", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("counts down from the region to the walking circle and the block", () => {
    const { container } = render(<NarrowingStages narrowing={NARROWING} />);

    const figure = screen.getByRole("figure");
    expect(figure).toHaveAccessibleName(
      "絞り込み：1都3県のすべての世帯 約1,740万世帯、根津駅から半径320m（徒歩4分） 約4,400世帯、番地：文京区弥生 2-99 付近 1区画",
    );
    const rows = container.querySelectorAll(".narrowing-row");
    expect([...rows].map((row) => row.textContent)).toEqual([
      "1都3県のすべての世帯約1,740万世帯",
      "根津駅から半径320m（徒歩4分）約4,400世帯",
      "番地：文京区弥生 2-99 付近1区画",
    ]);
    // 段は順に出る（遅れは発表モードで伸びる calc）
    expect(delayOf(rows[1])).toContain("calc(var(--stage-pace, 1) * 1.2s)");
    expect(delayOf(rows[2])).toContain("calc(var(--stage-pace, 1) * 2.4s)");
    // 前の段の数は、次の段が出るときに線で消す
    expect(rows[0].querySelector(".narrowing-strike")).not.toBeNull();
    expect(rows[2].querySelector(".narrowing-strike")).toBeNull();
    expect(within(figure).getByText(/出典/)).toHaveTextContent("第9条第9号");
  });

  it("draws one square per census mesh, the walking circle and the block mark", () => {
    const { container } = render(<NarrowingStages narrowing={NARROWING} />);

    expect(container.querySelectorAll(".narrowing-mesh")).toHaveLength(2);
    expect(container.querySelector(".narrowing-circle")?.getAttribute("r")).toBe("320");
    expect(container.querySelector(".narrowing-mark")).not.toBeNull();
    // 全体図は、生活圏の印に向かって寄る
    expect(delayOf(container.querySelector(".narrowing-region"))).toMatch(/transform-origin: [\d.]+% [\d.]+%/);
  });

  it("shows only the counts when there is no walking circle", () => {
    const { container } = render(<NarrowingStages narrowing={{ ...NARROWING, walk: null }} />);

    expect(container.querySelector(".narrowing-map")).toBeNull();
    expect([...container.querySelectorAll(".narrowing-row")].map((row) => row.textContent)).toEqual([
      "1都3県のすべての世帯約1,740万世帯",
      "番地：文京区弥生 2-99 付近1区画",
    ]);
  });

  it("starts the animation only when the figure scrolls into view", () => {
    let fire: (visible: boolean) => void = () => {};
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
          fire = (visible) => callback([{ isIntersecting: visible }]);
        }
        observe() {}
        disconnect() {}
      },
    );
    render(<NarrowingStages narrowing={NARROWING} />);
    const figure = screen.getByRole("figure");

    expect(figure).not.toHaveClass("narrowing-playing");
    act(() => fire(false));
    expect(figure).not.toHaveClass("narrowing-playing");
    act(() => fire(true));
    expect(figure).toHaveClass("narrowing-playing");
  });

  it("renders nothing without narrowing data", () => {
    const { container } = render(<NarrowingStages narrowing={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("visibleNarrowing", () => {
  it("drops a stage whose evidence post is excluded", () => {
    expect(visibleNarrowing(NARROWING, new Set(["env"]))?.block).toBeNull();
    expect(visibleNarrowing(NARROWING, new Set(["w"]))?.walk).toBeNull();
    expect(visibleNarrowing(NARROWING, new Set(["w", "env"]))).toBeNull();
    expect(visibleNarrowing(NARROWING, new Set())).toEqual(NARROWING);
    expect(visibleNarrowing(undefined, new Set())).toBeNull();
    expect(visibleNarrowing({ ...NARROWING, region: null } as unknown as Narrowing, new Set())).toBeNull();
  });
});
