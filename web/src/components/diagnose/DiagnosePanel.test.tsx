import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/components/session/SessionProvider";
import { ApiError, diagnose, getSession } from "@/lib/api";
import type { Clue } from "@/types/clue";
import type { DiagnoseEvent } from "@/types/diagnose";
import type { Post } from "@/types/post";

import { DiagnosePanel } from "./DiagnosePanel";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, diagnose: vi.fn(), getSession: vi.fn() };
});

const ALICE = { handle: "alice.bsky.social", did: "did:plc:abc" };

function post(n: number, text: string): Post {
  return {
    post_id: `at://did:plc:abc/app.bsky.feed.post/3k${n}`,
    text,
    created_at: "2026-10-20T08:31:00+09:00",
    images: [],
  };
}

function clue(postId: string, value: string): Clue {
  return {
    post_id: postId,
    image_index: null,
    type: "routine_text",
    value,
    region: null,
    confidence: 0.9,
    source: "text",
  };
}

/** 呼び出し側が release() するまで、2 件目以降を止めておくイベント列 */
function pausedAfterFirst(events: DiagnoseEvent[]) {
  let release = () => {};
  const gate = new Promise<void>((resolve) => (release = resolve));
  async function* run(): AsyncGenerator<DiagnoseEvent> {
    const [first, ...rest] = events;
    yield first;
    await gate;
    yield* rest;
  }
  return { run, release };
}

async function renderLoggedIn() {
  vi.mocked(getSession).mockResolvedValue(ALICE);
  render(
    <SessionProvider>
      <DiagnosePanel />
    </SessionProvider>,
  );
  return screen.findByRole("button", { name: "診断する" });
}

afterEach(() => {
  vi.mocked(diagnose).mockReset();
  vi.mocked(getSession).mockReset();
});

describe("DiagnosePanel", () => {
  it("shows nothing when logged out", async () => {
    vi.mocked(getSession).mockResolvedValue(null);
    const { container } = render(
      <SessionProvider>
        <DiagnosePanel />
      </SessionProvider>,
    );

    await vi.waitFor(() => expect(getSession).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("shows that it is fetching posts before the first event arrives", async () => {
    let release = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    vi.mocked(diagnose).mockImplementation(async function* () {
      await gate;
      yield { event: "done", posts_seen: 0 };
    });

    fireEvent.click(await renderLoggedIn());

    expect(await screen.findByRole("status")).toHaveTextContent("特定班AIが投稿を取りに行っています…");
    const button = screen.getByRole("button", { name: "診断する" });
    expect(button).toBeDisabled();
    expect(button.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.getByRole("region", { name: "診断" })).toHaveAttribute("aria-busy", "true");

    release();

    expect(await screen.findByRole("status")).toHaveTextContent("0 件の投稿を読みました");
    expect(button).toBeEnabled();
    expect(button.querySelector(".animate-spin")).toBeNull();
    expect(screen.getByRole("region", { name: "診断" })).toHaveAttribute("aria-busy", "false");
  });

  it("adds posts one by one as they arrive, then says how many were read", async () => {
    const stream = pausedAfterFirst([
      { event: "post", post: post(1, "夜勤明け。電車混んでる") },
      { event: "post", post: post(2, "ジムおわり") },
      { event: "done", posts_seen: 2 },
    ]);
    vi.mocked(diagnose).mockImplementation(stream.run);

    fireEvent.click(await renderLoggedIn());

    expect(await screen.findByText("夜勤明け。電車混んでる")).toBeInTheDocument();
    expect(screen.queryByText("ジムおわり")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("投稿を読んでいます…（1 件）");
    expect(screen.getByRole("button", { name: "診断する" })).toBeDisabled();

    stream.release();

    expect(await screen.findByText("ジムおわり")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 件の投稿を読みました");
    expect(screen.getByRole("button", { name: "診断する" })).toBeEnabled();
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      expect.stringContaining("夜勤明け。電車混んでる"),
      expect.stringContaining("ジムおわり"),
    ]);
  });

  it("starts over with an empty list when run again", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield { event: "post", post: post(1, "夜勤明け。電車混んでる") };
      yield { event: "done", posts_seen: 1 };
    });
    const button = await renderLoggedIn();

    fireEvent.click(button);
    await screen.findByText("1 件の投稿を読みました");
    fireEvent.click(button);
    await screen.findByText("1 件の投稿を読みました");

    expect(screen.getAllByText("夜勤明け。電車混んでる")).toHaveLength(1);
  });

  it("shows the error and keeps the posts read so far", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield { event: "post", post: post(1, "夜勤明け。電車混んでる") };
      throw new ApiError("network", "診断の途中で接続が切れました");
    });

    fireEvent.click(await renderLoggedIn());

    expect(await screen.findByRole("alert")).toHaveTextContent("診断の途中で接続が切れました");
    expect(screen.getByText("夜勤明け。電車混んでる")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "診断する" })).toBeEnabled();
  });

  it("does not show details of unexpected errors", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield* [];
      throw new Error("secret internal detail");
    });

    fireEvent.click(await renderLoggedIn());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("診断できませんでした");
    expect(alert).not.toHaveTextContent("secret");
  });

  it("shows clues under each post and the conclusions board at the end", async () => {
    const first = post(1, "夜勤明け。電車混んでる");
    const second = post(2, "毎週火曜はジム");
    const gym = clue(second.post_id, "毎週火曜はジム");
    const stream = pausedAfterFirst([
      { event: "post", post: first },
      { event: "post", post: second },
      { event: "clues", post_id: second.post_id, clues: [gym], error: null },
      { event: "clues", post_id: first.post_id, clues: [], error: "写真を取得できませんでした" },
      {
        event: "conclusions",
        clues: [gym],
        conclusions: [
          {
            rule: "R3",
            attribute: "routine",
            value: "毎週火曜 20時ごろに出かけている",
            clue_indices: [0],
            note: "同じ曜日・時間帯の投稿 3 件",
          },
        ],
      },
      { event: "done", posts_seen: 2 },
    ]);
    vi.mocked(diagnose).mockImplementation(stream.run);

    fireEvent.click(await renderLoggedIn());
    await screen.findByText("夜勤明け。電車混んでる");
    expect(screen.queryByRole("region", { name: "捜査ボード" })).not.toBeInTheDocument();

    stream.release();

    const board = await screen.findByRole("region", { name: "捜査ボード" });
    const [item] = within(within(board).getByRole("list", { name: "推定できたこと" })).getAllByRole(
      "listitem",
    );
    expect(item).toHaveTextContent("決まった外出");
    expect(item).toHaveTextContent("推定");
    expect(item).toHaveTextContent("毎週火曜 20時ごろに出かけている");
    expect(within(item).getByRole("list", { name: "根拠の手がかり" })).toHaveTextContent(
      "生活の決まり 毎週火曜はジム",
    );
    expect(screen.getByRole("list", { name: "この投稿の手がかり" })).toHaveTextContent("毎週火曜はジム");
    expect(screen.getByText("手がかりを探せませんでした（写真を取得できませんでした）")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 件の投稿を読みました");
  });

  it("says when nothing could be inferred", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield { event: "conclusions", clues: [], conclusions: [] };
      yield { event: "done", posts_seen: 0 };
    });

    fireEvent.click(await renderLoggedIn());

    expect(
      await screen.findByText("投稿からは、あなたについて推定できることは見つかりませんでした"),
    ).toBeInTheDocument();
  });
});
