import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/components/session/SessionProvider";
import { ApiError, diagnose, getSession } from "@/lib/api";
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
});
