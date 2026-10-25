import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, deletePosts, simulate } from "@/lib/api";
import { messages } from "@/lib/messages";
import type { RiskyPost, Simulation } from "@/types/diagnose";
import type { Post } from "@/types/post";

import { RiskyPosts } from "./RiskyPosts";

const t = messages.risky;

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, simulate: vi.fn(), deletePosts: vi.fn() };
});

function post(n: number, text: string): Post {
  return {
    post_id: `at://did:plc:abc/app.bsky.feed.post/3k${n}`,
    text,
    created_at: "2026-10-20T08:31:00+09:00",
    images: [],
  };
}

const ADDRESS = post(9, "荷物届いた");
const GYM = post(2, "ジムおわり 毎週火曜はここ");
const RISKY: RiskyPost[] = [
  { post_id: ADDRESS.post_id, broken: ["station", "active_time"] },
  { post_id: GYM.post_id, broken: ["routine"] },
];
const ALL_BROKEN: Simulation = {
  delete: [ADDRESS.post_id, GYM.post_id],
  broken: ["station", "active_time", "routine"],
  after: [],
};

function renderRisky(onSimulated = vi.fn()) {
  render(<RiskyPosts posts={[GYM, ADDRESS]} risky={RISKY} clueCount={20} onSimulated={onSimulated} />);
  return onSimulated;
}

afterEach(() => {
  vi.mocked(simulate).mockReset();
  vi.mocked(deletePosts).mockReset();
});

describe("RiskyPosts", () => {
  it("lists the risky posts in plan order with what each one breaks, all selected", () => {
    renderRisky();

    const items = within(screen.getByRole("list", { name: t.listLabel })).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent(ADDRESS.text);
    expect(items[0]).toHaveTextContent(t.breaks("最寄り駅・よくいる時間"));
    expect(items[1]).toHaveTextContent(t.breaks("決まった外出"));
    expect(screen.getAllByRole("checkbox").map((c) => (c as HTMLInputElement).checked)).toEqual([true, true]);
  });

  it("simulates the selected posts and reports that the user got away", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    const onSimulated = renderRisky();

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByText(t.result(2, 3))).toBeInTheDocument();
    expect(screen.getByText(t.safe)).toBeInTheDocument();
    expect(vi.mocked(simulate).mock.calls[0][0]).toEqual([ADDRESS.post_id, GYM.post_id]);
    expect(vi.mocked(simulate).mock.calls[0][1]).toBe(20);
    expect(onSimulated).toHaveBeenLastCalledWith(ALL_BROKEN);
  });

  it("sends only the posts that stay selected", async () => {
    // 宛名の投稿が残るので、最寄り駅は推定されたまま（逃げ切りにはならない）
    vi.mocked(simulate).mockResolvedValue({
      delete: [GYM.post_id],
      broken: ["routine"],
      after: [{ rule: "R1", attribute: "station", value: "根津駅", clue_indices: [0], note: "" }],
    });
    renderRisky();

    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByText(t.result(1, 1))).toBeInTheDocument();
    expect(screen.queryByText(t.safe)).not.toBeInTheDocument();
    expect(vi.mocked(simulate).mock.calls[0][0]).toEqual([GYM.post_id]);
  });

  it("drops the old result when the selection changes or on reset", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    const onSimulated = renderRisky();

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    await screen.findByText(t.result(2, 3));
    fireEvent.click(screen.getAllByRole("checkbox")[1]);

    expect(screen.queryByText(t.result(2, 3))).not.toBeInTheDocument();
    expect(onSimulated).toHaveBeenLastCalledWith(null);

    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.reset }));

    expect(screen.queryByText(t.result(2, 3))).not.toBeInTheDocument();
    expect(onSimulated).toHaveBeenLastCalledWith(null);
  });

  it("cannot simulate with nothing selected", () => {
    renderRisky();

    for (const box of screen.getAllByRole("checkbox")) fireEvent.click(box);

    expect(screen.getByRole("button", { name: t.simulate })).toBeDisabled();
  });

  it("shows the api error", async () => {
    vi.mocked(simulate).mockRejectedValue(new ApiError("server", messages.errors.diagnoseFirst, 409));
    renderRisky();

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByRole("alert")).toHaveTextContent(messages.errors.diagnoseFirst);
  });

  it("offers to delete for real only after simulating", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    renderRisky();
    expect(screen.queryByRole("button", { name: t.deleteForReal })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByRole("button", { name: t.deleteForReal })).toBeInTheDocument();
  });

  it("does not delete until the user confirms, and cancelling deletes nothing", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    const dialog = screen.getByRole("alertdialog", { name: t.confirmHeading });
    expect(dialog).toHaveTextContent(t.confirmLead(2));
    expect(within(dialog).getByRole("list", { name: t.confirmListLabel })).toHaveTextContent(ADDRESS.text);
    expect(within(dialog).getByRole("button", { name: t.cancel })).toHaveFocus();

    fireEvent.click(within(dialog).getByRole("button", { name: t.cancel }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deletePosts).not.toHaveBeenCalled();
  });

  it("closes the confirmation with Escape", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deletePosts).not.toHaveBeenCalled();
  });

  it("deletes the simulated posts once confirmed and shows that the user got away", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    vi.mocked(deletePosts).mockResolvedValue({ ...ALL_BROKEN, failed: [] });
    const onSimulated = renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    fireEvent.click(screen.getByRole("button", { name: t.confirm }));

    expect(await screen.findByText(messages.escaped.heading)).toBeInTheDocument();
    expect(screen.getByText(messages.escaped.deleted(2))).toBeInTheDocument();
    expect(screen.getByText(t.safe)).toBeInTheDocument();
    expect(vi.mocked(deletePosts).mock.calls[0][0]).toEqual([ADDRESS.post_id, GYM.post_id]);
    expect(vi.mocked(deletePosts).mock.calls[0][1]).toBe(20);
    expect(onSimulated).toHaveBeenLastCalledWith({ ...ALL_BROKEN, failed: [] });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    // 消したあとは選び直せない
    expect(screen.queryByRole("button", { name: t.simulate })).not.toBeInTheDocument();
    for (const box of screen.getAllByRole("checkbox")) expect(box).toBeDisabled();
  });

  it("says which posts could not be deleted", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    vi.mocked(deletePosts).mockResolvedValue({
      delete: [GYM.post_id],
      failed: [ADDRESS.post_id],
      broken: ["routine"],
      after: [{ rule: "R1", attribute: "station", value: "根津駅", clue_indices: [0], note: "" }],
    });
    renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    fireEvent.click(screen.getByRole("button", { name: t.confirm }));

    expect(await screen.findByText(messages.escaped.deleted(1))).toBeInTheDocument();
    expect(screen.getByText(messages.escaped.failed(1))).toBeInTheDocument();
    expect(screen.queryByText(t.safe)).not.toBeInTheDocument();
  });

  it("shows the error when deleting fails and keeps the simulation", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    vi.mocked(deletePosts).mockRejectedValue(new Error("boom"));
    renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    fireEvent.click(screen.getByRole("button", { name: t.confirm }));

    expect(await screen.findByRole("alert")).toHaveTextContent(t.deleteFailed);
    expect(screen.getByRole("alert")).not.toHaveTextContent("boom");
    expect(screen.getByRole("button", { name: t.deleteForReal })).toBeInTheDocument();
  });

  it("says so when no post can break the profile", () => {
    render(<RiskyPosts posts={[]} risky={[]} clueCount={0} onSimulated={vi.fn()} />);

    expect(screen.getByText(t.none)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t.simulate })).not.toBeInTheDocument();
  });
});
