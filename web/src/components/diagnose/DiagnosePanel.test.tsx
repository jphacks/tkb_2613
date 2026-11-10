import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionProvider, useSession } from "@/components/session/SessionProvider";
import { ApiError, createSession, deleteSession, diagnose, getSession } from "@/lib/api";
import type { Clue } from "@/types/clue";
import type { DiagnoseEvent } from "@/types/diagnose";
import type { Post } from "@/types/post";

import { DiagnosePanel } from "./DiagnosePanel";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, createSession: vi.fn(), deleteSession: vi.fn(), diagnose: vi.fn(), getSession: vi.fn() };
});

const ALICE = { handle: "alice.bsky.social", did: "did:plc:abc" };
const BOB = { handle: "bob.bsky.social", did: "did:plc:other" };

function SessionControls() {
  const { state, login, logout } = useSession();
  return state.status === "authenticated"
    ? <button type="button" onClick={() => void logout()}>ログアウトして切替</button>
    : <button type="button" onClick={() => void login("bob.bsky.social", "test-password")}>別アカウントでログイン</button>;
}

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
  vi.mocked(createSession).mockReset();
  vi.mocked(deleteSession).mockReset();
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

  it("clears diagnosis data and aborts its request when the authenticated owner changes", async () => {
    let signal: AbortSignal | undefined;
    vi.mocked(getSession).mockResolvedValue(ALICE);
    vi.mocked(deleteSession).mockResolvedValue(undefined);
    vi.mocked(createSession).mockResolvedValue(BOB);
    vi.mocked(diagnose).mockImplementation(async function* (options) {
      signal = options?.signal;
      yield { event: "post", post: post(1, "Alice only post") };
      yield { event: "conclusions", clues: [], conclusions: [], profile_claims: [
        {
          attribute: "residential_area", value: "Alice only claim", confidence: 0.65, status: "weak",
          evidence: [{ post_id: post(1, "").post_id, clue_index: null, required: true, source: "post_text", excerpt: "Alice only" }],
        },
      ] };
      yield { event: "done", posts_seen: 1 };
    });

    render(
      <SessionProvider>
        <SessionControls />
        <DiagnosePanel />
      </SessionProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "診断する" }));
    expect(await screen.findByText("Alice only claim")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "ログアウトして切替" }));
    await screen.findByRole("button", { name: "別アカウントでログイン" });
    expect(signal?.aborted).toBe(true);
    expect(screen.queryByText("Alice only claim")).not.toBeInTheDocument();
    expect(screen.queryByText("Alice only post")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "別アカウントでログイン" }));
    expect(await screen.findByRole("button", { name: "診断する" })).toBeInTheDocument();
    expect(screen.queryByText("Alice only claim")).not.toBeInTheDocument();
    expect(screen.queryByText("Alice only post")).not.toBeInTheDocument();
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
    expect(screen.getByText("2 件の投稿を読みました")).toBeInTheDocument();
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
    expect(within(board).getByText("現在の限定ルールでは、根拠のあるプロフィール推定は成立しませんでした。これは安全の確認を意味しません。")).toBeInTheDocument();
    const prototype = within(board).getByText("検証前の候補（試作ルール）");
    expect(prototype.closest("details")).toBeInTheDocument();
    expect(prototype.closest("details")).not.toHaveAttribute("open");
    expect(within(prototype.closest("details")!).getByText(/R1〜R3の試作ルールによる候補です/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "この投稿の手がかり" })).toHaveTextContent("毎週火曜はジム");
    expect(screen.getByText("手がかりを探せませんでした（写真を取得できませんでした）")).toBeInTheDocument();
    expect(screen.getByText("2 件の投稿を読みました")).toBeInTheDocument();
  });

  it("requires per-run opt-in and distinguishes search candidates from owner-linked URLs", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield {
        event: "conclusions",
        clues: [],
        conclusions: [],
        external_lookup_status: "fixture",
        external_profile_results: [
          { id: "fixture-linked", url: "https://example.com/blog", domain: "example.com", title: "架空ブログ", status: "owner_linked", owner_evidence: { kind: "profile_text", post_id: null, excerpt: "ブログ: https://example.com/blog" } },
          { id: "fixture-candidate", url: "https://sample.org/notes", domain: "sample.org", title: "架空メモ", status: "candidate", owner_evidence: null },
        ],
      };
      yield { event: "done", posts_seen: 0 };
    });

    const diagnoseButton = await renderLoggedIn();
    const consent = screen.getByRole("checkbox", { name: /公開Webで外部SNS・ブログ・記事の候補を検索する/ });
    expect(consent).not.toBeChecked();
    fireEvent.click(diagnoseButton);
    await screen.findByRole("region", { name: "捜査ボード" });
    expect(diagnose).toHaveBeenLastCalledWith(expect.objectContaining({ publicWebLookupConsent: false }));

    fireEvent.click(consent);
    fireEvent.click(diagnoseButton);
    const board = await screen.findByRole("region", { name: "捜査ボード" });
    expect(diagnose).toHaveBeenLastCalledWith(expect.objectContaining({ publicWebLookupConsent: true }));
    expect(within(board).getByText("本人のプロフィール/投稿に掲載されたURLと一致")).toBeInTheDocument();
    expect(within(board).getByText("検索候補（同一人物未確認）")).toBeInTheDocument();
    expect(within(board).getByText(/実世界の同一人物を確認したものではありません/)).toBeInTheDocument();
    expect(consent).not.toBeChecked();
  });

  it("states that no claim was established under current rules without implying safety", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield { event: "conclusions", clues: [], conclusions: [] };
      yield { event: "done", posts_seen: 0 };
    });

    fireEvent.click(await renderLoggedIn());

    expect(
      await screen.findByText("現在の限定ルールでは、根拠のあるプロフィール推定は成立しませんでした。これは安全の確認を意味しません。"),
    ).toBeInTheDocument();
  });

  it("shows a primary profile claim before the collapsed prototype candidates", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield {
        event: "conclusions",
        clues: [],
        conclusions: [
          { rule: "R1", attribute: "home_area", value: "投稿記載の町域", clue_indices: [], note: "試作" },
        ],
        profile_claims: [
          {
            attribute: "residential_area",
            value: "東京都渋谷区",
            confidence: 0.82,
            status: "found",
            evidence: [
              { post_id: post(1, "").post_id, clue_index: null, required: true, source: "post_text", excerpt: "渋谷区に住んでいる" },
            ],
          },
        ],
      };
      yield { event: "done", posts_seen: 1 };
    });

    fireEvent.click(await renderLoggedIn());

    const claim = await screen.findByText("東京都渋谷区");
    const prototypeSummary = screen.getByText("検証前の候補（試作ルール）");
    expect(claim.compareDocumentPosition(prototypeSummary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(prototypeSummary.closest("details")).not.toHaveAttribute("open");
  });
});
