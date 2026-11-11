import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import type { Post } from "@/types/post";

import { ReasoningChain } from "./ReasoningChain";

const t = messages.board.chain;

function post(n: number, text: string): Post {
  return { post_id: `at://did:plc:demo/app.bsky.feed.post/${n}`, text, created_at: "2026-10-20T08:31:00+09:00", images: [] };
}

const SIGN = post(1, "今日も電車混んでる");
const PARCEL = post(2, "荷物届いた");
const CLUES: Clue[] = [
  { post_id: SIGN.post_id, image_index: 0, type: "station_sign", value: "根x", region: null, confidence: 0.6, source: "vlm" },
  { post_id: PARCEL.post_id, image_index: 0, type: "postal_code", value: "113-0032", region: null, confidence: 0.9, source: "vlm" },
  { post_id: SIGN.post_id, image_index: null, type: "routine_text", value: "電車混んでる", region: null, confidence: 0.8, source: "text" },
];
const CONCLUSION: Conclusion = {
  rule: "R4", attribute: "station", value: "根津駅", clue_indices: [0, 1, 2],
  note: "駅名標の一部と郵便番号の地域が重なる",
};

describe("ReasoningChain", () => {
  it("follows each post, then its clues, then the inference in this order", () => {
    render(<ReasoningChain conclusion={CONCLUSION} clues={CLUES} posts={[PARCEL, SIGN]} />);

    expect(screen.getByText(t.summary)).toBeInTheDocument();
    const steps = within(screen.getByRole("list", { name: t.label })).getAllByRole("listitem")
      .filter((item) => item.parentElement?.getAttribute("aria-label") === t.label);
    // 根拠の手がかりが出てきた順に投稿を並べ、同じ投稿の手がかりはまとめる。最後が推定
    expect(steps).toHaveLength(3);
    expect(steps[0]).toHaveTextContent(SIGN.text);
    expect(steps[0]).toHaveTextContent("根x");
    expect(steps[0]).toHaveTextContent("電車混んでる");
    expect(steps[0]).toHaveTextContent(t.photo(1));
    expect(steps[1]).toHaveTextContent(PARCEL.text);
    expect(steps[1]).toHaveTextContent("113-0032");
    expect(steps[2]).toHaveTextContent(`${t.conclusion}・${messages.board.attributeLabels.station}`);
    expect(steps[2]).toHaveTextContent("根津駅");
    expect(steps[2]).toHaveTextContent(CONCLUSION.note);
  });

  it("still shows the clue when its post is not among the posts", () => {
    render(<ReasoningChain conclusion={{ ...CONCLUSION, clue_indices: [1] }} clues={CLUES} posts={[SIGN]} />);

    const steps = within(screen.getByRole("list", { name: t.label })).getAllByRole("listitem")
      .filter((item) => item.parentElement?.getAttribute("aria-label") === t.label);
    expect(steps[0]).toHaveTextContent(t.noText);
    expect(steps[0]).toHaveTextContent("113-0032");
  });

  it("shows nothing without evidence", () => {
    const { container } = render(<ReasoningChain conclusion={{ ...CONCLUSION, clue_indices: [] }} clues={CLUES} posts={[SIGN]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
