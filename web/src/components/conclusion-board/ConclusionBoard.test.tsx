import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CLUE_LABELS } from "@/lib/clueLabels";
import { messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";

import { ConclusionBoard } from "./ConclusionBoard";

const CLUE: Clue = {
  post_id: "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx",
  image_index: null,
  type: "place_text",
  value: "新宿",
  region: null,
  confidence: 0.8,
  source: "text",
};

const CONCLUSION: Conclusion = {
  rule: "station_from_place",
  attribute: "station",
  value: "新宿",
  clue_indices: [0],
  note: "",
};

/** jsdom には ResizeObserver がないので、observe した瞬間に 1 回知らせる代わりを置く */
class ImmediateResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe() {
    this.callback([], this as unknown as ResizeObserver);
  }
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ImmediateResizeObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ConclusionBoard", () => {
  it("pins each clue used as evidence once and ties a red string to every conclusion it supports", () => {
    const clues: Clue[] = [CLUE, { ...CLUE, type: "routine_text", value: "毎朝 8 時の電車" }];
    const conclusions: Conclusion[] = [
      { ...CONCLUSION, clue_indices: [0, 1] },
      { ...CONCLUSION, attribute: "active_time", value: "平日の朝", clue_indices: [1] },
    ];
    const { container } = render(<ConclusionBoard clues={clues} conclusions={conclusions} />);

    const evidence = within(screen.getByRole("list", { name: messages.board.evidence })).getAllByRole(
      "listitem",
    );
    expect(evidence.map((e) => e.textContent)).toEqual([
      `${CLUE_LABELS.place_text}新宿`,
      `${CLUE_LABELS.routine_text}毎朝 8 時の電車`,
    ]);
    const strings = container.querySelector("svg.red-strings");
    expect(strings).toHaveAttribute("aria-hidden", "true");
    expect(strings?.querySelectorAll("path")).toHaveLength(3);
  });

  it("announces みーつけた and flashes once when something is inferred", () => {
    const { container } = render(<ConclusionBoard clues={[CLUE]} conclusions={[CONCLUSION]} />);

    expect(screen.getByText(messages.board.found)).toBeInTheDocument();
    expect(container.querySelector(".found-flash")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("最寄り駅")).toBeInTheDocument();
  });

  it("stays calm when nothing is inferred", () => {
    const { container } = render(<ConclusionBoard clues={[]} conclusions={[]} />);

    expect(screen.queryByText(messages.board.found)).not.toBeInTheDocument();
    expect(container.querySelector(".found-flash")).not.toBeInTheDocument();
    expect(screen.getByText("投稿からは、あなたについて推定できることは見つかりませんでした")).toBeInTheDocument();
  });
});
