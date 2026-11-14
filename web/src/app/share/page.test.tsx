import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getSharedResult } from "@/lib/api";
import { messages } from "@/lib/messages";
import type { DiagnosisSnapshot, LegacySharedSnapshot } from "@/types/diagnose";
import { PROFILE_DIAGNOSED_ATTRIBUTES } from "@/types/profile";

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
      profile_claims: PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => ({
        attribute, status: "unknown", candidates: [], candidate_pool: [], reason: null, conflicting_evidence: [],
      })),
      profile_relations: [],
      plan: { delete: [], broken: [], after: PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => ({
        attribute, status: "unknown", candidates: [], candidate_pool: [], reason: null, conflicting_evidence: [],
      })), posts: [] },
    };
    vi.mocked(getSharedResult).mockResolvedValue(saved);

    render(<SharedResultPage />);

    expect(await screen.findByText("デモの投稿")).toBeInTheDocument();
    expect(getSharedResult).toHaveBeenCalledWith(token, expect.any(Object));
    expect(screen.queryByRole("button", { name: "Bluesky から消す" })).not.toBeInTheDocument();
  });

  it("renders an old saved conclusion snapshot without recomputing it", async () => {
    window.location.hash = "b".repeat(43);
    const legacy: LegacySharedSnapshot = {
      posts: [],
      clues: [],
      conclusions: [{ rule: "R3", attribute: "routine", value: "火曜の夜勤", clue_indices: [], note: "保存済み" }],
      plan: {
        delete: [], broken: ["routine"],
        after: [{ rule: "R3", attribute: "routine", value: "火曜の夜勤", clue_indices: [], note: "保存済み" }],
        posts: [],
      },
    };
    vi.mocked(getSharedResult).mockResolvedValue(legacy);
    render(<SharedResultPage />);
    expect((await screen.findAllByText("火曜の夜勤")).length).toBeGreaterThan(0);
    expect(getSharedResult).toHaveBeenCalledWith("b".repeat(43), expect.any(Object));
  });

  it("says result links are turned off instead of calling the link invalid", async () => {
    window.location.hash = "a".repeat(43);
    vi.mocked(getSharedResult).mockRejectedValue(
      new ApiError("server", messages.errors.shareDisabled, 404, "share_disabled"),
    );
    render(<SharedResultPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(messages.errors.shareDisabled);
  });

  it("still calls an unknown link invalid", async () => {
    window.location.hash = "a".repeat(43);
    vi.mocked(getSharedResult).mockRejectedValue(new ApiError("server", "…", 404));
    render(<SharedResultPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("リンクが無効か、有効期限が切れています。");
  });
});
