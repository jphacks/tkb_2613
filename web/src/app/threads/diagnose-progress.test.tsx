import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { messages } from "@/lib/messages";
import { PROGRESS_POLL_MS } from "@/lib/useThreadsDiagnosis";

import profileFixture from "./fixtures/threads-profile.json";
import ThreadsPage from "./page";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const LIVE_STAGES = ["checking_model", "fetching", "reading", "inferring"];
const POSTS = profileFixture.snapshot.posts;
const IDLE = {
  state: "idle", stage: null, elapsed_ms: null, posts_total: null, posts_read: 0,
  read_post_ids: [], stages: [], error: null,
};

function running(stage: string, read: number, elapsed = 65_000) {
  return {
    state: "running", stage, elapsed_ms: elapsed,
    posts_total: stage === "reading" || stage === "inferring" ? POSTS.length : null,
    posts_read: read, read_post_ids: POSTS.slice(0, read).map((post) => post.post_id),
    stages: LIVE_STAGES, error: null,
  };
}

interface ApiState {
  /** GET /diagnosis の応答。null なら 404 */
  diagnosis: unknown;
  progress: unknown;
  /** POST /diagnose の応答。保留にしたいときは Promise を入れる */
  diagnose: () => Response | Promise<Response>;
}

/** ログイン済みの Threads API のモック。state を書き換えると以後の応答が変わる */
function stubApi(initial: Partial<ApiState> = {}) {
  const state: ApiState = {
    diagnosis: null,
    progress: IDLE,
    diagnose: () => json(profileFixture.snapshot),
    ...initial,
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/config")) return json({ mock_enabled: true, gpu_demo_enabled: false, live_enabled: false, max_posts: 30 });
    if (path.endsWith("/session")) return json({ username: "架空のThreadsアカウント", mock: true });
    if (path.endsWith("/diagnosis")) return state.diagnosis === null ? json({ detail: "none" }, 404) : json(state.diagnosis);
    if (path.endsWith("/progress")) return json(state.progress);
    if (path.endsWith("/posts")) return json({ mock: true, posts: POSTS });
    if (path.endsWith("/diagnose") && init?.method === "POST") return state.diagnose();
    throw new Error(`unexpected fetch: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { state, fetchMock };
}

function diagnoseCalls(fetchMock: ReturnType<typeof vi.fn>): number {
  return fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/diagnose")).length;
}

async function openAiCard() {
  expect(await screen.findByText("架空のThreadsアカウント")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "本人投稿を確認" }));
  return screen.findByRole("button", { name: "AI診断を試す" });
}

async function nextPoll() {
  await act(() => vi.advanceTimersByTimeAsync(PROGRESS_POLL_MS));
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  window.localStorage.clear();
  window.history.replaceState(null, "", "/threads");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Threads AI diagnosis in progress", () => {
  it("puts the start button before the post list", async () => {
    stubApi();
    render(<ThreadsPage />);
    const button = await openAiCard();
    const firstPost = screen.getByText(POSTS[0].text);

    expect(button.compareDocumentPosition(firstPost) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the Bluesky loading screen with real steps, counts, and elapsed time, then the reveal", async () => {
    let finish: (response: Response) => void = () => undefined;
    const { state } = stubApi({ diagnose: () => new Promise<Response>((resolve) => { finish = resolve; }) });
    render(<ThreadsPage />);
    fireEvent.click(await openAiCard());

    expect(await screen.findByText(messages.loading.calling)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("AI診断中です");
    expect(screen.getByText("経過 0:00")).toBeInTheDocument();
    // まだサーバーから件数が届いていないので、見込みの割合は出さない
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "AI診断を試す" })).not.toBeInTheDocument();

    state.progress = running("reading", 2);
    await nextPoll();

    const steps = await screen.findByRole("list", { name: "診断の段階" });
    const items = within(steps).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("AIモデルに接続"),
      expect.stringContaining("投稿を取得"),
      expect.stringContaining("本文・画像を解析"),
      expect.stringContaining("推理結果を生成"),
    ]);
    expect(items[2]).toHaveAttribute("aria-current", "step");
    expect(items[2]).toHaveTextContent(`2 / ${POSTS.length} 件`);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "2");
    expect(bar).toHaveAttribute("aria-valuemax", String(POSTS.length));
    expect(screen.getByText(/経過 1:0\d/)).toBeInTheDocument();
    expect(screen.getByText(messages.loading.reading(POSTS[0].text.slice(0, 24) + (POSTS[0].text.length > 24 ? "…" : ""))))
      .toBeInTheDocument();

    finish(json(profileFixture.snapshot));
    expect(await screen.findByRole("heading", { name: "ぜんぶ、みえてる" })).toBeInTheDocument();
    expect(screen.queryByText(messages.loading.calling)).not.toBeInTheDocument();
  });

  it("sends only one diagnosis for a double click", async () => {
    let finish: (response: Response) => void = () => undefined;
    const { fetchMock } = stubApi({ diagnose: () => new Promise<Response>((resolve) => { finish = resolve; }) });
    render(<ThreadsPage />);
    const button = await openAiCard();

    fireEvent.click(button);
    fireEvent.click(button);

    expect(diagnoseCalls(fetchMock)).toBe(1);
    finish(json(profileFixture.snapshot));
    expect(await screen.findByRole("heading", { name: "ぜんぶ、みえてる" })).toBeInTheDocument();
    expect(diagnoseCalls(fetchMock)).toBe(1);
  });

  it("treats 409 as a diagnosis already running and waits for its result", async () => {
    // 別のタブで始めた診断が走っている。POST した時点で progress は running になっている
    const { state } = stubApi();
    state.diagnose = () => {
      state.progress = running("reading", 1);
      return json({ detail: "診断中です" }, 409);
    };
    render(<ThreadsPage />);
    fireEvent.click(await openAiCard());

    expect(await screen.findByText(/診断を実行中です。ページを再読み込みしても処理は続きます/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    state.progress = { ...IDLE, state: "done" };
    state.diagnosis = profileFixture.snapshot;
    await nextPoll();

    expect(await screen.findByRole("heading", { name: "ぜんぶ、みえてる" })).toBeInTheDocument();
  });

  it("says a diagnosis is running when 409 came from another request", async () => {
    stubApi({ diagnose: () => json({ detail: "処理中です" }, 409) });
    render(<ThreadsPage />);
    fireEvent.click(await openAiCard());

    expect(await screen.findByRole("alert")).toHaveTextContent("診断を実行中です。終わるまでお待ちください。");
  });

  it("comes back to the running diagnosis after a reload and shows its result", async () => {
    const { state, fetchMock } = stubApi({ progress: running("inferring", POSTS.length, 125_000) });
    render(<ThreadsPage />);

    expect(await screen.findByText(messages.loading.calling)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("診断を実行中です。ページを再読み込みしても処理は続きます");
    expect(screen.getByText(/経過 2:0\d/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", String(POSTS.length));

    state.progress = { ...IDLE, state: "done" };
    state.diagnosis = profileFixture.snapshot;
    await nextPoll();

    expect(await screen.findByRole("heading", { name: "ぜんぶ、みえてる" })).toBeInTheDocument();
    expect(diagnoseCalls(fetchMock)).toBe(0);
  });

  it("shows the failure and lets the user try again", async () => {
    const { state } = stubApi({ diagnose: () => json({ detail: "x" }, 500) });
    render(<ThreadsPage />);
    fireEvent.click(await openAiCard());

    expect(await screen.findByRole("alert")).toHaveTextContent("操作に失敗しました。再度お試しください。");
    expect(screen.queryByText(messages.loading.calling)).not.toBeInTheDocument();

    state.diagnose = () => json(profileFixture.snapshot);
    fireEvent.click(screen.getByRole("button", { name: "AI診断を試す" }));
    expect(await screen.findByRole("heading", { name: "ぜんぶ、みえてる" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("explains that the model is unavailable when the GPU is stopped", async () => {
    stubApi({ diagnose: () => json({ detail: "x" }, 503) });
    render(<ThreadsPage />);
    fireEvent.click(await openAiCard());

    expect(await screen.findByRole("alert")).toHaveTextContent("AI診断モデルは現在利用できません");
  });

  it("explains a GPU stop that happened before the reload", async () => {
    stubApi({ progress: { ...IDLE, state: "failed", error: "model_unavailable" } });
    render(<ThreadsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("AI診断モデルは現在利用できません");
    await waitFor(() => expect(screen.queryByText(messages.loading.calling)).not.toBeInTheDocument());
  });
});
