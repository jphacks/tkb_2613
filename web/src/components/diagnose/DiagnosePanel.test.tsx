import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginPanel } from "@/components/login/LoginPanel";
import { SessionProvider } from "@/components/session/SessionProvider";
import { ApiError, diagnose, getDiagnosis, getFeatures, getSession, simulate } from "@/lib/api";
import { messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import type { DiagnoseEvent } from "@/types/diagnose";
import type { Post } from "@/types/post";

import { DiagnosePanel } from "./DiagnosePanel";

const d = messages.diagnose;
const b = messages.board;

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    diagnose: vi.fn(),
    getDiagnosis: vi.fn(),
    getSession: vi.fn(),
    simulate: vi.fn(),
    getFeatures: vi.fn(async () => ({ share_enabled: false, auth_mode: "app_password" })),
  };
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
  vi.mocked(getDiagnosis).mockResolvedValue(null);
  render(
    <SessionProvider>
      <DiagnosePanel />
    </SessionProvider>,
  );
  return screen.findByRole("button", { name: d.start });
}

afterEach(() => {
  vi.mocked(simulate).mockReset();
  vi.mocked(diagnose).mockReset();
  vi.mocked(getSession).mockReset();
  vi.mocked(getDiagnosis).mockReset();
});

describe("DiagnosePanel", () => {
  it("restores a completed diagnosis from the same login session", async () => {
    const savedPost = post(1, "保存済みの投稿");
    const savedClue = clue(savedPost.post_id, "毎週火曜はジム");
    vi.mocked(getSession).mockResolvedValue(ALICE);
    vi.mocked(getDiagnosis).mockResolvedValue({
      posts: [savedPost], clues: [savedClue],
      conclusions: [{ rule: "R3", attribute: "routine", value: "毎週火曜", clue_indices: [0], note: "" }],
      plan: { delete: [savedPost.post_id], broken: ["routine"], after: [], posts: [{ post_id: savedPost.post_id, broken: ["routine"] }] },
    });
    render(<SessionProvider><DiagnosePanel /></SessionProvider>);

    expect(await screen.findByRole("region", { name: b.heading })).toBeInTheDocument();
    // 削除候補・推理の流れ（捜査ボード）・投稿一覧の3か所
    expect(screen.getAllByText("保存済みの投稿")).toHaveLength(3);
    expect(screen.getByRole("list", { name: messages.risky.listLabel })).toBeInTheDocument();
    expect(diagnose).not.toHaveBeenCalled();
  });

  it("puts the delete summary above the board and folds the read posts", async () => {
    const savedPost = post(1, "保存済みの投稿");
    vi.mocked(getSession).mockResolvedValue(ALICE);
    vi.mocked(getDiagnosis).mockResolvedValue({
      posts: [savedPost], clues: [clue(savedPost.post_id, "毎週火曜はジム")],
      conclusions: [{ rule: "R3", attribute: "routine", value: "毎週火曜", clue_indices: [0], note: "" }],
      plan: { delete: [savedPost.post_id], broken: ["routine"], after: [], posts: [{ post_id: savedPost.post_id, broken: ["routine"] }] },
    });
    render(<SessionProvider><DiagnosePanel /></SessionProvider>);

    const summary = await screen.findByRole("region", { name: messages.plan.label });
    const board = screen.getByRole("region", { name: b.heading });
    // 要約は捜査ボードより前にある
    expect(summary.compareDocumentPosition(board) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const link = within(summary).getByRole("link", { name: messages.plan.show });
    expect(document.getElementById(link.getAttribute("href")!.slice(1))).toHaveTextContent(messages.risky.heading);

    const posts = screen.getByRole("list", { name: d.postsLabel });
    expect(posts.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText(d.postsSummary(1))).toBeInTheDocument();
  });

  it("marks posts deleted after the diagnosis and keeps them out of the delete candidates", async () => {
    const gone = post(1, "消した投稿");
    const kept = post(2, "残った投稿");
    vi.mocked(getSession).mockResolvedValue(ALICE);
    vi.mocked(getDiagnosis).mockResolvedValue({
      posts: [gone, kept],
      clues: [clue(gone.post_id, "毎週火曜はジム"), clue(kept.post_id, "夜勤明け")],
      deleted: [gone.post_id],
      conclusions: [{ rule: "R3", attribute: "routine", value: "夜勤明け", clue_indices: [1], note: "" }],
      // api は消した投稿を候補から除いて返す。画面でも念のため外す
      plan: {
        delete: [kept.post_id], broken: ["routine"], after: [],
        posts: [{ post_id: gone.post_id, broken: ["routine"] }, { post_id: kept.post_id, broken: ["routine"] }],
      },
    });
    render(<SessionProvider><DiagnosePanel /></SessionProvider>);

    const candidates = await screen.findByRole("list", { name: messages.risky.listLabel });
    expect(within(candidates).getAllByRole("listitem")).toHaveLength(1);
    expect(candidates).toHaveTextContent("残った投稿");
    expect(candidates).not.toHaveTextContent("消した投稿");

    const items = within(screen.getByRole("list", { name: d.postsLabel })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent(d.deletedBadge);
    expect(items[1]).not.toHaveTextContent(d.deletedBadge);
  });

  it("goes back to the login screen and says the session expired when diagnose returns 401", async () => {
    vi.mocked(getSession).mockResolvedValue(ALICE);
    vi.mocked(getDiagnosis).mockResolvedValue(null);
    vi.mocked(diagnose).mockImplementation(async function* () {
      throw new ApiError("unauthorized", messages.errors.sessionExpired, 401);
    });
    render(
      <SessionProvider>
        <LoginPanel />
        <DiagnosePanel />
      </SessionProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: d.start }));

    expect(await screen.findByRole("alert")).toHaveTextContent(messages.login.expired);
    expect(screen.getByRole("form", { name: messages.login.formLabel })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: d.start })).not.toBeInTheDocument();
  });

  it("goes back to the login screen when restoring the diagnosis returns 401", async () => {
    vi.mocked(getSession).mockResolvedValue(ALICE);
    vi.mocked(getDiagnosis).mockRejectedValue(new ApiError("unauthorized", messages.errors.sessionExpired, 401));
    render(
      <SessionProvider>
        <LoginPanel />
        <DiagnosePanel />
      </SessionProvider>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(messages.login.expired);
    expect(screen.getByRole("form", { name: messages.login.formLabel })).toBeInTheDocument();
  });

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

    expect(await screen.findByRole("status")).toHaveTextContent(d.connecting);
    const button = screen.getByRole("button", { name: d.start });
    expect(button).toBeDisabled();
    expect(button.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.getByRole("region", { name: d.heading })).toHaveAttribute("aria-busy", "true");

    release();

    expect(await screen.findByRole("status")).toHaveTextContent(d.done(0));
    expect(button).toBeEnabled();
    expect(button.querySelector(".animate-spin")).toBeNull();
    expect(screen.getByRole("region", { name: d.heading })).toHaveAttribute("aria-busy", "false");
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
    expect(screen.getByRole("status")).toHaveTextContent(d.reading(1));
    expect(screen.getByRole("button", { name: d.start })).toBeDisabled();

    stream.release();

    expect(await screen.findByText("ジムおわり")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(d.done(2));
    expect(screen.getByRole("button", { name: d.start })).toBeEnabled();
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
    await screen.findByText(d.done(1));
    fireEvent.click(button);
    await screen.findByText(d.done(1));

    expect(screen.getAllByText("夜勤明け。電車混んでる")).toHaveLength(1);
  });

  it("shows the error and keeps the posts read so far", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield { event: "post", post: post(1, "夜勤明け。電車混んでる") };
      throw new ApiError("network", messages.errors.diagnoseInterrupted);
    });

    fireEvent.click(await renderLoggedIn());

    expect(await screen.findByRole("alert")).toHaveTextContent(messages.errors.diagnoseInterrupted);
    expect(screen.getByText("夜勤明け。電車混んでる")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: d.start })).toBeEnabled();
  });

  it("does not show details of unexpected errors", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield* [];
      throw new Error("secret internal detail");
    });

    fireEvent.click(await renderLoggedIn());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(d.failed);
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
    expect(screen.queryByRole("region", { name: b.heading })).not.toBeInTheDocument();

    stream.release();

    const board = await screen.findByRole("region", { name: b.heading });
    const identity = screen.getByRole("article", { name: messages.identity.label });
    const evidence = screen.getByRole("list", { name: messages.reveal.evidenceLabel });
    const restart = screen.getByRole("button", { name: d.rediagnose });
    expect(screen.queryByRole("button", { name: d.start })).not.toBeInTheDocument();
    expect(identity.compareDocumentPosition(evidence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(evidence.compareDocumentPosition(board) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(board.compareDocumentPosition(restart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const [item] = within(within(board).getByRole("list", { name: b.conclusionsLabel })).getAllByRole(
      "listitem",
    );
    expect(item).toHaveTextContent(b.attributeLabels.routine);
    expect(item).toHaveTextContent(b.inferred);
    expect(item).toHaveTextContent("毎週火曜 20時ごろに出かけている");
    expect(within(item).getByRole("list", { name: b.reasonsLabel })).toHaveTextContent(
      "生活の決まり 毎週火曜はジム",
    );
    expect(screen.getByRole("list", { name: messages.post.cluesLabel })).toHaveTextContent("毎週火曜はジム");
    expect(screen.getByText(messages.clues.failed("写真を取得できませんでした"))).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(d.done(2));
  });

  it("offers a quiet re-diagnose button after the result that warns it uses one of today's diagnoses", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield { event: "post", post: post(1, "夜勤明け。電車混んでる") };
      yield { event: "conclusions", clues: [], conclusions: [] };
      yield { event: "done", posts_seen: 1 };
    });
    fireEvent.click(await renderLoggedIn());
    const again = await screen.findByRole("button", { name: d.rediagnose });
    expect(diagnose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: d.start })).not.toBeInTheDocument();
    expect(again).toHaveAccessibleDescription(d.rediagnoseNote);

    // 確認は挟まず、押したらそのまま診断し直す
    fireEvent.click(again);
    expect(diagnose).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole("button", { name: d.rediagnose })).toBeInTheDocument();
    expect(diagnose).toHaveBeenCalledTimes(2);
  });

  it("returns to the top after the result replaces the loading screen", async () => {
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield { event: "conclusions", clues: [clue(post(1, "本文").post_id, "本文")], conclusions: [] };
      yield { event: "done", posts_seen: 1 };
    });

    fireEvent.click(await renderLoggedIn());

    await vi.waitFor(() => expect(scroll).toHaveBeenCalledWith(0, 0));
    scroll.mockRestore();
  });

  it("says when nothing could be inferred", async () => {
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield { event: "conclusions", clues: [], conclusions: [] };
      yield { event: "done", posts_seen: 0 };
    });

    fireEvent.click(await renderLoggedIn());

    expect(
      await screen.findByText(b.empty),
    ).toBeInTheDocument();
  });

  it("lists the risky posts and turns broken conclusions into unknown when simulated", async () => {
    const gymPost = post(2, "ジムおわり 毎週火曜はここ");
    const gym = clue(gymPost.post_id, "毎週火曜のジム");
    vi.mocked(diagnose).mockImplementation(async function* () {
      yield { event: "post", post: gymPost };
      yield { event: "clues", post_id: gymPost.post_id, clues: [gym], error: null };
      yield {
        event: "conclusions",
        clues: [gym],
        conclusions: [{ rule: "R3", attribute: "routine", value: "毎週火曜", clue_indices: [0], note: "" }],
      };
      yield {
        event: "plan",
        delete: [gymPost.post_id],
        broken: ["routine"],
        after: [],
        posts: [{ post_id: gymPost.post_id, broken: ["routine"] }],
      };
      yield { event: "done", posts_seen: 1 };
    });
    vi.mocked(simulate).mockResolvedValue({ delete: [gymPost.post_id], broken: ["routine"], after: [] });

    fireEvent.click(await renderLoggedIn());
    const risky = await screen.findByRole("list", { name: messages.risky.listLabel });
    expect(risky).toHaveTextContent(messages.risky.breaks(b.attributeLabels.routine));

    fireEvent.click(screen.getByRole("button", { name: messages.risky.simulate }));

    const board = screen.getByRole("list", { name: b.conclusionsLabel });
    await vi.waitFor(() => expect(board).toHaveTextContent(b.unknown));
    expect(board).not.toHaveTextContent("毎週火曜");
    expect(vi.mocked(simulate).mock.calls[0][1]).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: messages.risky.reset }));

    expect(screen.getByRole("list", { name: b.conclusionsLabel })).toHaveTextContent("毎週火曜");
  });
});

describe("DiagnosePanel public web lookup consent", () => {
  const consent = () => screen.queryByRole("checkbox", { name: new RegExp(d.publicWebConsentLabel.slice(0, 8)) });

  afterEach(() => {
    vi.mocked(getFeatures).mockReset();
    vi.mocked(getFeatures).mockResolvedValue({ share_enabled: false, auth_mode: "app_password" });
  });

  it("hides the consent checkbox and never sends consent when the api says lookup is unavailable", async () => {
    vi.mocked(getFeatures).mockResolvedValue({ share_enabled: false, public_web_lookup_available: false });
    vi.mocked(diagnose).mockImplementation(async function* () {});
    const start = await renderLoggedIn();
    await vi.waitFor(() => expect(getFeatures).toHaveBeenCalled());

    expect(consent()).not.toBeInTheDocument();
    expect(screen.queryByText(d.publicWebConsentNote)).not.toBeInTheDocument();

    fireEvent.click(start);
    await vi.waitFor(() => expect(diagnose).toHaveBeenCalled());
    expect(vi.mocked(diagnose).mock.calls[0][0]).toMatchObject({ publicWebLookupConsent: false });
  });

  it("hides the consent checkbox when the features cannot be read", async () => {
    vi.mocked(getFeatures).mockResolvedValue({ share_enabled: false });
    await renderLoggedIn();
    await vi.waitFor(() => expect(getFeatures).toHaveBeenCalled());

    expect(consent()).not.toBeInTheDocument();
  });

  it("shows the consent checkbox with the no-charge note when lookup is available, and sends the choice", async () => {
    vi.mocked(getFeatures).mockResolvedValue({ share_enabled: false, public_web_lookup_available: true });
    vi.mocked(diagnose).mockImplementation(async function* () {});
    const start = await renderLoggedIn();

    const checkbox = await screen.findByRole("checkbox", { name: new RegExp(d.publicWebConsentLabel.slice(0, 8)) });
    expect(checkbox).not.toBeChecked();
    // 利用者は払わないこと、検索語の保持期間の注意の両方を出す
    expect(d.publicWebConsentNote).toContain("料金が請求されることはなく");
    expect(d.publicWebConsentNote).toContain("最大90日保持");
    expect(screen.getByText(d.publicWebConsentNote)).toBeInTheDocument();

    fireEvent.click(checkbox);
    fireEvent.click(start);
    await vi.waitFor(() => expect(diagnose).toHaveBeenCalled());
    expect(vi.mocked(diagnose).mock.calls[0][0]).toMatchObject({ publicWebLookupConsent: true });
  });
});
