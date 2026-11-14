import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DecodeText, PLACE_KANJI, decodeDelays, spinChars } from "./DecodeText";

describe("DecodeText", () => {
  it("keeps the real value for screen readers and spins a strip of kanji for each character", () => {
    const { container } = render(<DecodeText value="文京区 千駄木" delay={0.8} />);

    expect(screen.getByText("文京区 千駄木")).toHaveClass("sr-only");
    const strips = container.querySelectorAll(".decode-strip");
    // 空白は回さない
    expect(strips).toHaveLength(6);
    for (const strip of strips) {
      expect(strip.closest("[aria-hidden='true']")).not.toBeNull();
    }
    // 帯の最後が本当の文字で、止まった状態ではそこが見える
    expect(strips[0].lastElementChild?.textContent).toBe("文");
    expect(strips[5].lastElementChild?.textContent).toBe("木");
  });

  it("spins only kanji used in place names, and the same value always spins the same way", () => {
    const chars = spinChars("根津駅", 1);
    expect(chars.length).toBeGreaterThan(3);
    expect(chars.every((c) => PLACE_KANJI.includes(c))).toBe(true);
    expect(spinChars("根津駅", 1)).toEqual(chars);
  });

  it("locks the characters from left to right and scales by the presentation pace", () => {
    const { container } = render(<DecodeText value="根津駅" delay={0.8} />);
    const styles = [...container.querySelectorAll(".decode-strip")].map((s) => s.getAttribute("style") ?? "");
    expect(styles.every((s) => s.includes("var(--stage-pace, 1)"))).toBe(true);

    const ends = decodeDelays(3).map((d) => d.end);
    expect(ends).toEqual([...ends].sort((a, b) => a - b));
    expect(new Set(ends).size).toBe(3);
    // 1 つの値の解読は 0.5〜0.8 秒で終わる
    expect(ends[2]).toBeGreaterThanOrEqual(0.5);
    expect(ends[2]).toBeLessThanOrEqual(0.8);
  });
});
