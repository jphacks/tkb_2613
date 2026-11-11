import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, getDemoDiagnosis, simulateDemo } from "@/lib/api";
import { messages } from "@/lib/messages";
import type { DemoDiagnosis } from "@/types/diagnose";

import DemoPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, getDemoDiagnosis: vi.fn(), simulateDemo: vi.fn() };
});

const t = messages.demo;
const GYM = "at://did:plc:demo/app.bsky.feed.post/2";
const DEMO: DemoDiagnosis = {
  demo: true,
  posts: [
    { post_id: "at://did:plc:demo/app.bsky.feed.post/1", text: "夜勤明けのラーメン", created_at: "2026-10-20T08:31:00+09:00", images: [] },
    { post_id: GYM, text: "毎週火曜はジム", created_at: "2026-10-21T20:10:00+09:00", images: [] },
  ],
  clues: [
    { post_id: GYM, image_index: null, type: "routine_text", value: "毎週火曜はジム", region: null, confidence: 0.9, source: "text" },
  ],
  conclusions: [{ rule: "R3", attribute: "routine", value: "毎週火曜 20時ごろ", clue_indices: [0], note: "" }],
  plan: { delete: [GYM], broken: ["routine"], after: [], posts: [{ post_id: GYM, broken: ["routine"] }] },
};

/** jsdom には ResizeObserver がない（捜査ボードの糸で使う） */
class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", NoopResizeObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(getDemoDiagnosis).mockReset();
  vi.mocked(simulateDemo).mockReset();
});

describe("DemoPage", () => {
  it("always says the account is fictional, even before and without a result", async () => {
    vi.mocked(getDemoDiagnosis).mockRejectedValue(new ApiError("network", "x"));
    render(<DemoPage />);

    expect(screen.getByRole("note")).toHaveTextContent(t.banner);
    expect(await screen.findByRole("alert")).toHaveTextContent(t.failed);
    expect(screen.getByRole("note")).toHaveTextContent(t.banner);
  });

  it("shows the fictional diagnosis without login and without any delete control", async () => {
    vi.mocked(getDemoDiagnosis).mockResolvedValue(DEMO);
    render(<DemoPage />);

    expect(await screen.findByRole("list", { name: messages.board.conclusionsLabel })).toHaveTextContent("毎週火曜 20時ごろ");
    expect(screen.getByRole("note")).toHaveTextContent(t.banner);
    expect(screen.queryByRole("button", { name: messages.risky.deleteForReal })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: messages.risky.confirm })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: t.backHome })).toHaveAttribute("href", "/");
  });

  it("simulates removing the selected candidates and updates the board", async () => {
    vi.mocked(getDemoDiagnosis).mockResolvedValue(DEMO);
    vi.mocked(simulateDemo).mockResolvedValue({ delete: [GYM], broken: ["routine"], after: [] });
    render(<DemoPage />);
    const candidates = await screen.findByRole("list", { name: t.candidatesLabel });
    expect(within(candidates).getByRole("checkbox")).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: messages.risky.simulate }));

    expect(await screen.findByText(messages.risky.result(1, 1))).toBeInTheDocument();
    expect(simulateDemo).toHaveBeenCalledWith([GYM], DEMO.clues.length, expect.any(Object));
    expect(screen.getByText(messages.board.unknownNote)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: messages.risky.reset }));
    expect(screen.queryByText(messages.board.unknownNote)).not.toBeInTheDocument();
  });
});
