import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SAMPLE_RESIDENCE } from "@/fixtures/residence";
import { changedSteps, densestText, excerpt, formatPeople } from "@/lib/residence";
import type { Post } from "@/types/post";

import { ResidenceStages } from "./ResidenceStages";

const TEXTS: Record<number, string> = {
  1: "千代田線、また止まってる…",
  3: "最寄り駅まで徒歩5分の部屋にして正解だった",
  4: "南北線の駅も歩いて行けるの、地味に便利",
  5: "近所の秋祭り、法被の背中に『弥生』って入ってて地元感あった",
  13: "22歳、いまだに自炊がうまくならない",
  14: "誕生日が4月14日だと、新学期のバタバタで毎年誰にも祝われない",
};
const POSTS: Post[] = Object.entries(TEXTS).map(([n, text]) => ({
  post_id: `at://did:plc:demo/app.bsky.feed.post/${n}`,
  text,
  created_at: "2026-11-01T21:00:00+09:00",
  images: [],
}));

describe("数の表し方", () => {
  it.each([
    [29_581_605, "約2,958万人"],
    [943_082, "約94.3万人"],
    [2432.4, "約2,432人"],
    [0.0151, "0.015人"],
  ])("%s → %s", (people, text) => {
    expect(formatPeople(people)).toBe(text);
  });

  it("人数が変わった段だけを残す", () => {
    const steps = changedSteps(SAMPLE_RESIDENCE.steps);
    expect(steps.map((s) => s.post_id?.split("/").pop() ?? null)).toEqual([null, "1", "3", "4", "5", "13", "14"]);
    expect(changedSteps([...SAMPLE_RESIDENCE.steps.slice(0, 5), { ...SAMPLE_RESIDENCE.steps[4], post_id: "x" }])).toHaveLength(5);
  });

  it("抜き出しは長ければ切る", () => {
    expect(excerpt("")).toBe("（本文なし）");
    expect(excerpt("あ".repeat(40))).toHaveLength(28);
  });

  it("一番濃いマスの説明", () => {
    expect(densestText(SAMPLE_RESIDENCE)).toBe("文京区 弥生一丁目／東大前まで徒歩5分のあたり");
  });
});

describe("ResidenceStages", () => {
  it("一番濃い場所と8割の範囲を、相対的な言い方で出す", () => {
    render(<ResidenceStages residence={SAMPLE_RESIDENCE} posts={POSTS} />);

    const figure = screen.getByRole("figure");
    expect(figure).toHaveAccessibleName(/一番濃いのはここ：文京区 弥生一丁目.*8割の範囲は約28人（20〜24歳）/);
    expect(screen.getByText("同じ年齢・同じ誕生日の人は、計算上0.015人（目安）")).toBeInTheDocument();
    expect(figure.textContent).not.toMatch(/確定|特定した/);
  });

  it("投稿を重ねるたびに減る人数を、前の段に線を引いて並べる", () => {
    const { container } = render(<ResidenceStages residence={SAMPLE_RESIDENCE} posts={POSTS} />);

    const rows = container.querySelectorAll(".residence-row");
    expect(rows).toHaveLength(7);
    expect(rows[0].textContent).toContain("投稿なし（1都3県の20〜24歳）");
    expect(rows[0].textContent).toContain("約2,958万人");
    expect(rows[6].querySelector(".text-seeker")?.textContent).toBe("約28人");
    expect(container.querySelectorAll(".residence-strike")).toHaveLength(6);
    expect(rows[2].getAttribute("style")).toContain("var(--stage-pace, 1)");
  });

  it("消すと効く投稿の棒グラフで、一番長いものに「消すべき1件」を付ける", () => {
    render(<ResidenceStages residence={SAMPLE_RESIDENCE} posts={POSTS} />);

    const chart = screen.getByRole("region", { name: "消すと効く投稿" });
    const items = within(chart).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("千代田線、また止まってる…");
    expect(items[0]).toHaveTextContent("消すべき1件");
    expect(items[0]).toHaveTextContent("+約2,461人");
    expect(items.at(-1)).toHaveTextContent("変わらない");
    expect(within(chart).getAllByText("消すべき1件")).toHaveLength(1);
  });

  it("外すと狭まる投稿に矛盾の印を付ける", () => {
    const residence = {
      ...SAMPLE_RESIDENCE,
      influence: [...SAMPLE_RESIDENCE.influence, { post_id: POSTS[3].post_id, people_without: 10, delta: -18, contradiction: true }],
    };
    render(<ResidenceStages residence={residence} posts={POSTS} />);
    expect(screen.getByText("ほかと矛盾している可能性")).toBeInTheDocument();
  });

  it("よく行く場所の山を切り替えて重ねる", () => {
    const { container } = render(<ResidenceStages residence={SAMPLE_RESIDENCE} posts={POSTS} />);

    const toggle = screen.getByRole("button", { name: "よく行く場所の山を重ねる" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(container.querySelectorAll(".residence-geo")).toHaveLength(0);
    act(() => {
      fireEvent.click(toggle);
    });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelectorAll(".residence-geo").length).toBe(SAMPLE_RESIDENCE.map.cells.length);
    expect(screen.getByText(/運河は離れた別の拠点として外しました/)).toBeInTheDocument();
    expect(screen.getByText("重ねると、8割の範囲は約28人")).toBeInTheDocument();
  });

  it("層7がなければ切り替えを出さない。地図のマスと駅名・町名を描く", () => {
    const { container } = render(<ResidenceStages residence={{ ...SAMPLE_RESIDENCE, geoprofile: null }} posts={POSTS} />);

    expect(screen.queryByRole("button", { name: "よく行く場所の山を重ねる" })).toBeNull();
    expect(container.querySelectorAll(".residence-cell")).toHaveLength(SAMPLE_RESIDENCE.map.cells.length);
    expect(container.querySelectorAll(".residence-region").length).toBeGreaterThan(0);
    expect(screen.getByText("根津駅")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "確率の地図" })).toBeInTheDocument();
  });

  it("使った仮定と出典を出す", () => {
    render(<ResidenceStages residence={SAMPLE_RESIDENCE} posts={POSTS} />);

    expect(screen.getByText("使った仮定を見る")).toBeInTheDocument();
    expect(screen.getByText("層どうしは独立とみなす")).toBeInTheDocument();
    expect(screen.getByText(/© OpenStreetMap contributors/)).toBeInTheDocument();
  });
});

describe("地図の濃淡", () => {
  it("一番濃いマスを 1 にして、4桁下までを対数で付ける", async () => {
    const { shade } = await import("./ResidenceMap");
    expect(shade(1, 1)).toBe(1);
    expect(shade(0.01, 1)).toBeCloseTo(0.5);
    expect(shade(1e-5, 1)).toBe(0);
    expect(shade(0, 1)).toBe(0);
    expect(shade(1.5e-4, 1)).toBeCloseTo(0.04, 2);
  });
});
