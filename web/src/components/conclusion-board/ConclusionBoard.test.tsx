import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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

describe("ConclusionBoard", () => {
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
