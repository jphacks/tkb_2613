import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider, useSession } from "@/components/session/SessionProvider";
import { checkDraft, createSession, deleteSession, getSession } from "@/lib/api";
import type { DraftCheckResponse } from "@/types/draftCheck";

import { DraftCheckPanel } from "./DraftCheckPanel";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    checkDraft: vi.fn(),
    createSession: vi.fn(),
    deleteSession: vi.fn(),
    getSession: vi.fn(),
  };
});

const ALICE = { handle: "alice.bsky.social", did: "did:plc:alice" };
const BOB = { handle: "bob.bsky.social", did: "did:plc:bob" };

function SessionSwitcher() {
  const { login } = useSession();
  return <button onClick={() => login("bob.bsky.social", "test")}>別のアカウントへ</button>;
}

const ALICE_RESULT: DraftCheckResponse = {
  posts_checked: 1,
  mock_mode: false,
  notices: [],
  overlaps: [
    {
      clue: {
        post_id: "draft:ephemeral",
        image_index: null,
        type: "place_text",
        value: "ALICE-PRIVATE-RESULT",
        region: null,
        confidence: 0.8,
        source: "text",
      },
      evidence: [{ post_id: "at://did:plc:alice/app.bsky.feed.post/one", created_at: "2026-10-20T08:00:00Z" }],
    },
  ],
};

describe("DraftCheckPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("clears the previous account draft and ignores its in-flight result after an account switch", async () => {
    vi.mocked(getSession).mockResolvedValue(ALICE);
    vi.mocked(createSession).mockResolvedValue(BOB);
    vi.mocked(deleteSession).mockResolvedValue(undefined);
    let resolveCheck: (value: DraftCheckResponse) => void = () => {};
    vi.mocked(checkDraft).mockImplementation(
      () => new Promise((resolve) => { resolveCheck = resolve; }),
    );

    render(
      <SessionProvider>
        <DraftCheckPanel />
        <SessionSwitcher />
      </SessionProvider>,
    );

    const input = await screen.findByLabelText("本文");
    fireEvent.change(input, { target: { value: "Alice private draft" } });
    const photo = new File(["photo"], "draft.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("写真（1枚まで）"), { target: { files: [photo] } });
    fireEvent.click(screen.getByRole("button", { name: "過去の投稿と照合" }));
    await waitFor(() => expect(checkDraft).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "別のアカウントへ" }));
    await waitFor(() => expect(createSession).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByLabelText("本文")).toHaveValue(""));
    expect(screen.getByLabelText("写真（1枚まで）")).toHaveValue("");

    resolveCheck(ALICE_RESULT);
    await waitFor(() => expect(screen.queryByText("ALICE-PRIVATE-RESULT")).not.toBeInTheDocument());
  });

  it("shows a mock no-overlap result and its notices", async () => {
    vi.mocked(getSession).mockResolvedValue(ALICE);
    vi.mocked(checkDraft).mockResolvedValue({
      posts_checked: 2,
      mock_mode: true,
      notices: ["架空の注意事項"],
      overlaps: [],
    });
    render(<SessionProvider><DraftCheckPanel /></SessionProvider>);

    fireEvent.change(await screen.findByLabelText("本文"), { target: { value: "架空の下書き" } });
    fireEvent.click(screen.getByRole("button", { name: "過去の投稿と照合" }));

    expect(await screen.findByText("デモ用の架空投稿 2 件を確認しました。")).toBeInTheDocument();
    expect(screen.getByText("架空の注意事項")).toBeInTheDocument();
    expect(screen.getByText("同じ手がかりの文字列は見つかりませんでした。")).toBeInTheDocument();
  });

  it("shows matched real observations and their source", async () => {
    vi.mocked(getSession).mockResolvedValue(ALICE);
    vi.mocked(checkDraft).mockResolvedValue(ALICE_RESULT);
    render(<SessionProvider><DraftCheckPanel /></SessionProvider>);

    fireEvent.change(await screen.findByLabelText("本文"), { target: { value: "架空の下書き" } });
    fireEvent.click(screen.getByRole("button", { name: "過去の投稿と照合" }));

    expect(await screen.findByText("本人の過去の投稿 1 件を確認しました。")).toBeInTheDocument();
    expect(screen.getByText("下書きからの観測：本文の読み取り")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "過去の投稿と重なる手がかり" })).getByText(/同じ手がかり/)).toBeInTheDocument();
  });

  it("shows a safe fallback when the request fails", async () => {
    vi.mocked(getSession).mockResolvedValue(ALICE);
    vi.mocked(checkDraft).mockRejectedValue(new Error("internal detail"));
    render(<SessionProvider><DraftCheckPanel /></SessionProvider>);

    fireEvent.change(await screen.findByLabelText("本文"), { target: { value: "架空の下書き" } });
    fireEvent.click(screen.getByRole("button", { name: "過去の投稿と照合" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("下書きを確認できませんでした");
    expect(screen.queryByText("internal detail")).not.toBeInTheDocument();
  });
});
