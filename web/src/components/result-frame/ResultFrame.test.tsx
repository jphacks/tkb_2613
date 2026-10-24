import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Clue } from "@/types/clue";

import { ResultFrame } from "./ResultFrame";

const POST_ID = "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx";

const CLUES: Clue[] = [
  {
    post_id: POST_ID,
    image_index: 0,
    type: "station_sign",
    value: "新宿",
    region: [100, 50, 300, 150],
    confidence: 0.92,
    source: "vlm",
  },
  {
    post_id: POST_ID,
    image_index: 0,
    type: "phone",
    value: "03-0000-0000",
    region: [0, 0, 100, 25],
    confidence: 0.5,
    source: "ocr",
  },
  {
    post_id: POST_ID,
    image_index: null,
    type: "routine_text",
    value: "夜勤明け",
    region: null,
    confidence: 0.9,
    source: "text",
  },
];

function loadImage(width: number, height: number) {
  const img = screen.getByRole("img", { name: "選んだ写真" });
  Object.defineProperty(img, "naturalWidth", { value: width });
  Object.defineProperty(img, "naturalHeight", { value: height });
  fireEvent.load(img);
}

describe("ResultFrame", () => {
  it("lists every clue with its label, value and confidence", () => {
    render(<ResultFrame imageUrl="blob:photo" clues={CLUES} />);

    const items = within(screen.getByRole("list", { name: "見つかった手がかり" })).getAllByRole(
      "listitem",
    );
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("駅名標");
    expect(items[0]).toHaveTextContent("新宿");
    expect(items[0]).toHaveTextContent("92%");
    expect(items[1]).toHaveTextContent("電話番号");
  });

  it("places region boxes relative to the image size once loaded", () => {
    render(<ResultFrame imageUrl="blob:photo" clues={CLUES} />);

    expect(screen.queryByTestId("clue-region-0")).not.toBeInTheDocument();
    loadImage(1000, 500);

    const box = screen.getByTestId("clue-region-0");
    expect(box).toHaveStyle({ left: "10%", top: "10%", width: "20%", height: "20%" });
  });

  it("lists clues without a region but draws no box for them", () => {
    render(<ResultFrame imageUrl="blob:photo" clues={CLUES} />);
    loadImage(1000, 500);

    expect(screen.getByText("夜勤明け")).toBeInTheDocument();
    expect(screen.queryByTestId("clue-region-2")).not.toBeInTheDocument();
  });

  it("shows a message when no clues were found", () => {
    render(<ResultFrame imageUrl="blob:photo" clues={[]} />);

    expect(screen.getByText("手がかりは見つかりませんでした")).toBeInTheDocument();
  });
});
