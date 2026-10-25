import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getSharedResult } from "@/lib/api";
import type { DiagnosisSnapshot } from "@/types/diagnose";

import SharedResultPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, getSharedResult: vi.fn() };
});

afterEach(() => {
  window.location.hash = "";
  vi.mocked(getSharedResult).mockReset();
});

describe("SharedResultPage", () => {
  it("shows the saved result without login or deletion controls", async () => {
    const token = "a".repeat(43);
    window.location.hash = token;
    const saved: DiagnosisSnapshot = {
      posts: [{
        post_id: "at://did:plc:demo/app.bsky.feed.post/1", text: "デモの投稿",
        created_at: "2026-10-20T08:31:00+09:00", images: [],
      }],
      clues: [],
      conclusions: [],
      plan: { delete: [], broken: [], after: [], posts: [] },
    };
    vi.mocked(getSharedResult).mockResolvedValue(saved);

    render(<SharedResultPage />);

    expect(await screen.findByText("デモの投稿")).toBeInTheDocument();
    expect(getSharedResult).toHaveBeenCalledWith(token, expect.any(Object));
    expect(screen.queryByRole("button", { name: "Bluesky から消す" })).not.toBeInTheDocument();
  });
});
