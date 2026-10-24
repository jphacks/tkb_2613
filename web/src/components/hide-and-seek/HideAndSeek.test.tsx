import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, detectClues } from "@/lib/api";
import { messages } from "@/lib/messages";
import type { DetectResponse } from "@/types/clue";

import { HideAndSeek } from "./HideAndSeek";

const t = messages.hideAndSeek;

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, detectClues: vi.fn() };
});

const RESPONSE: DetectResponse = {
  clues: [
    {
      post_id: "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx",
      image_index: 0,
      type: "station_sign",
      value: "新宿",
      region: [1, 1, 2, 2],
      confidence: 0.9,
      source: "vlm",
    },
  ],
};

function choosePhoto() {
  const file = new File([new Uint8Array(4)], "photo.jpg", { type: "image/jpeg" });
  fireEvent.change(screen.getByLabelText(t.pick), { target: { files: [file] } });
  return file;
}

beforeEach(() => {
  vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:photo"), revokeObjectURL: vi.fn() });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(detectClues).mockReset();
});

describe("HideAndSeek", () => {
  it("disables the search button until a photo is chosen", () => {
    render(<HideAndSeek />);

    expect(screen.getByRole("button", { name: t.search })).toBeDisabled();
  });

  it("shows found clues after searching the chosen photo", async () => {
    vi.mocked(detectClues).mockResolvedValue(RESPONSE);
    render(<HideAndSeek />);

    const file = choosePhoto();
    fireEvent.click(screen.getByRole("button", { name: t.search }));

    expect(await screen.findByRole("heading", { name: t.found })).toBeInTheDocument();
    expect(screen.getByText("新宿")).toBeInTheDocument();
    expect(detectClues).toHaveBeenCalledWith(file);
  });

  it("shows a friendly message when the search fails", async () => {
    vi.mocked(detectClues).mockRejectedValue(new ApiError("network", messages.errors.network));
    render(<HideAndSeek />);

    choosePhoto();
    fireEvent.click(screen.getByRole("button", { name: t.search }));

    expect(await screen.findByRole("alert")).toHaveTextContent(messages.errors.network);
  });

  it("releases the previous preview when another photo is chosen", () => {
    render(<HideAndSeek />);

    choosePhoto();
    choosePhoto();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:photo");
  });
});
