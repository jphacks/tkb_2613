import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
      `${messages.clues.typeLabels.place_text}新宿`,
      `${messages.clues.typeLabels.routine_text}毎朝 8 時の電車`,
    ]);
    const strings = container.querySelector("svg.red-strings");
    expect(strings).toHaveAttribute("aria-hidden", "true");
    expect(strings?.querySelectorAll("path")).toHaveLength(3);
  });

  it("announces みーつけた and flashes once when something is inferred", () => {
    const { container } = render(<ConclusionBoard clues={[CLUE]} conclusions={[CONCLUSION]} />);

    expect(screen.getByText(messages.board.found)).toBeInTheDocument();
    expect(container.querySelector(".found-flash")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText(messages.board.attributeLabels.station)).toBeInTheDocument();
  });

  it("stays calm when nothing is inferred", () => {
    const { container } = render(<ConclusionBoard clues={[]} conclusions={[]} />);

    expect(screen.queryByText(messages.board.found)).not.toBeInTheDocument();
    expect(container.querySelector(".found-flash")).not.toBeInTheDocument();
    expect(screen.getByText(messages.board.empty)).toBeInTheDocument();
  });

  it("shows broken items as unknown after a simulated deletion, without the evidence", () => {
    render(<ConclusionBoard clues={[CLUE]} conclusions={[]} unknown={["station"]} />);

    const cards = within(screen.getByRole("list", { name: messages.board.conclusionsLabel })).getAllByRole("listitem");
    expect(cards).toHaveLength(1);
    expect(cards[0]).toHaveTextContent(messages.board.attributeLabels.station);
    expect(cards[0]).toHaveTextContent(messages.board.unknown);
    expect(screen.queryByText(CLUE.value)).not.toBeInTheDocument();
    expect(screen.queryByText(messages.board.empty)).not.toBeInTheDocument();
  });

  it("marks each inference as strong or weak without showing the number", () => {
    const conclusions: Conclusion[] = [
      { ...CONCLUSION, confidence: 0.92 },
      { ...CONCLUSION, attribute: "active_time", value: "平日の朝", confidence: 0.4 },
      { ...CONCLUSION, attribute: "routine", value: "毎朝" },
    ];
    render(<ConclusionBoard clues={[CLUE]} conclusions={conclusions} />);

    const cards = within(screen.getByRole("list", { name: messages.board.conclusionsLabel })).getAllByRole(
      "listitem",
    ).filter((item) => item.parentElement?.getAttribute("aria-label") === messages.board.conclusionsLabel);
    expect(cards[0]).toHaveTextContent(messages.board.confidence.strong);
    expect(cards[1]).toHaveTextContent(messages.board.confidence.weak);
    // 確からしさのない古い閲覧リンクには印を出さない
    expect(cards[2]).not.toHaveTextContent(messages.board.confidence.strong);
    expect(cards[2]).not.toHaveTextContent(messages.board.confidence.weak);
    expect(screen.queryByText(/0\.92|92%/)).not.toBeInTheDocument();
  });

  it("lets the user follow the reasoning chain only when the posts are given", () => {
    const post = { post_id: CLUE.post_id, text: "新宿で乗り換え", created_at: "2026-10-20T08:31:00+09:00", images: [] };
    const { rerender } = render(<ConclusionBoard clues={[CLUE]} conclusions={[CONCLUSION]} />);
    expect(screen.queryByText(messages.board.chain.summary)).not.toBeInTheDocument();

    rerender(<ConclusionBoard clues={[CLUE]} conclusions={[CONCLUSION]} posts={[post]} />);

    expect(screen.getByText(messages.board.chain.summary)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: messages.board.chain.label })).toHaveTextContent("新宿で乗り換え");
  });
});
