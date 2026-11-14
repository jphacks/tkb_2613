import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ESCAPED_MESSAGE, EscapeStamps } from "./EscapeStamps";

const broken = [
  { label: "ゴミの収集地区", value: "文京区 千駄木3～5丁目" },
  { label: "住んでいる町", value: "千駄木" },
];

function delayOf(el: Element | null): number {
  return Number(/([\d.]+)s/.exec(el?.getAttribute("style") ?? "")?.[1]);
}

describe("EscapeStamps", () => {
  it("stamps 不明 on each broken inference, counts down one by one and ends with the escape message", () => {
    const { container } = render(<EscapeStamps before={4} after={2} broken={broken} />);

    const figure = screen.getByRole("figure", { name: "推定できた項目は 4 から 2 になります" });
    const rows = within(figure).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("文京区 千駄木3～5丁目"),
      expect.stringContaining("千駄木"),
    ]);
    for (const row of rows) expect(within(row).getByText("不明")).toBeInTheDocument();

    // 判子は上から順に、0.4 秒ずつずらして押す
    const stamps = [...container.querySelectorAll(".escape-stamp")];
    expect(stamps.map(delayOf)).toEqual([0.3, 0.7]);
    // 数は判子に合わせて 4 → 3 → 2 と 1 つずつ減る（帯の最後が減ったあとの数）
    const strip = container.querySelector(".escape-count-strip");
    expect([...(strip?.children ?? [])].map((c) => c.textContent)).toEqual(["4", "3", "2"]);
    expect(delayOf(strip)).toBe(0.3);
    // 最後に「もう、見つからない」が弾む。全体は 2 秒ほどで終わる
    const message = within(figure).getByText(ESCAPED_MESSAGE);
    expect(delayOf(message)).toBeGreaterThan(0.7);
    expect(delayOf(message) + 0.6).toBeLessThanOrEqual(2.2);
  });

  it("shows nothing when no inference was lost", () => {
    const { container } = render(<EscapeStamps before={3} after={3} broken={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows nothing when the count did not go down even if some names were listed", () => {
    const { container } = render(<EscapeStamps before={2} after={2} broken={broken} />);
    expect(container).toBeEmptyDOMElement();
  });
});
