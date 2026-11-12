import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THREADS_LANG_KEY } from "@/lib/threads-i18n";

import ThreadsPage from "./page";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const POST_TEXT = "公式サイト https://example.com を確認";

/** ログイン済みで、本人投稿を1件返す Threads API のモック。モデル（/diagnose）は呼ばれない前提 */
function stubConnectedApi(configStatus = 200) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/config")) {
      return configStatus === 200
        ? json({ mock_enabled: false, gpu_demo_enabled: false, live_enabled: true, max_posts: 30 })
        : json({ detail: "busy" }, configStatus);
    }
    if (path.endsWith("/session") && init?.method === "DELETE") return new Response(null, { status: 204 });
    if (path.endsWith("/session")) return json({ username: "reviewer", mock: false });
    if (path.endsWith("/diagnosis")) return json({ detail: "診断結果がありません" }, 404);
    if (path.endsWith("/posts")) {
      return json({
        mock: false,
        posts: [{
          post_id: "threads:review-1",
          text: POST_TEXT,
          created_at: "2026-11-12T12:00:00+09:00",
          images: [],
        }],
      });
    }
    throw new Error(`unexpected fetch: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** ログアウト状態で、Threads ログインだけが使える API のモック */
function stubLoggedOutApi() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/config")) {
      return json({ mock_enabled: false, gpu_demo_enabled: false, live_enabled: true, max_posts: 30 });
    }
    return json({ detail: "unauthorized" }, 401);
  }));
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, "", "/threads");
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.lang = "ja";
});

describe("Threads review flow without a model", () => {
  it("shows own post details, runs the non-AI check, and logs out without diagnose", async () => {
    const fetchMock = stubConnectedApi();

    render(<ThreadsPage />);
    expect(await screen.findByText("@reviewer")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "本人投稿を確認" }));
    expect(await screen.findByText("公式サイト https://example.com を確認")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/diagnose"), expect.anything());

    fireEvent.click(screen.getByText("取得情報の詳細"));
    expect(screen.getByText("threads:review-1")).toBeInTheDocument();
    expect(screen.getByText(/画像・動画のURLやデータは取得していません/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "公開情報をセルフチェック" }));
    expect(screen.getByRole("status")).toHaveTextContent("URLらしき文字列");
    expect(screen.getByRole("status")).toHaveTextContent("AI診断ではありません");

    fireEvent.click(screen.getByRole("button", { name: "ログアウト" }));
    await waitFor(() => expect(screen.queryByText("@reviewer")).not.toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/diagnose"), expect.anything());
  });
});

describe("Japanese is the default display language", () => {
  it("starts in Japanese with the switcher showing 日本語 as selected", async () => {
    stubLoggedOutApi();
    render(<ThreadsPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Threadsで、みーつけた" })).toBeInTheDocument();
    const switcher = screen.getByRole("group", { name: "表示言語" });
    expect(within(switcher).getByRole("button", { name: "日本語" })).toHaveAttribute("aria-pressed", "true");
    expect(within(switcher).getByRole("button", { name: "English" })).toHaveAttribute("aria-pressed", "false");
    expect(await screen.findByRole("button", { name: "Threadsでログイン" })).toBeInTheDocument();
    expect(screen.getByText(/セルフチェックはAIではありません/)).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("ja");
  });
});

describe("English display language", () => {
  it("translates the consent, login button, and notices without changing the stored choice for Japanese users", async () => {
    stubLoggedOutApi();
    render(<ThreadsPage />);
    fireEvent.click(screen.getByRole("button", { name: "English" }));

    expect(screen.getByRole("heading", { level: 1, name: "Miitsuketa for Threads" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Display language" })).toBeInTheDocument();
    expect(screen.getByText(/The self-check is not AI/)).toBeInTheDocument();
    expect(screen.getByText(/I agree that this app retrieves my own Threads post IDs/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Log in with Threads" })).toBeInTheDocument();
    expect(screen.queryByText("Threadsでログイン")).not.toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
    expect(window.localStorage.getItem(THREADS_LANG_KEY)).toBe("en");
  });

  it("runs the whole review flow in English while keeping post text and username untouched", async () => {
    const fetchMock = stubConnectedApi();
    render(<ThreadsPage />);
    fireEvent.click(screen.getByRole("button", { name: "English" }));

    // ユーザー名は翻訳・変更しない
    expect(await screen.findByText("@reviewer")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review my posts" }));

    // 投稿本文・投稿IDは翻訳・変更しない
    expect(await screen.findByText(POST_TEXT)).toBeInTheDocument();
    expect(screen.getByText(/Retrieved 1 of your own post\./)).toBeInTheDocument();
    expect(screen.getByText(/No AI is used for this display/)).toBeInTheDocument();
    expect(screen.getByText(/Nov 12/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Retrieved data details"));
    expect(screen.getByText("threads:review-1")).toBeInTheDocument();
    expect(screen.getByText("Post ID:", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/Image and video URLs and data are not retrieved/)).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Public-information self-check (not AI)" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check visible public information" }));
    const result = screen.getByRole("status");
    expect(result).toHaveTextContent("Check result");
    expect(result).toHaveTextContent("Post 1: URL-like string");
    expect(result).toHaveTextContent("It is not an AI diagnosis");

    expect(screen.getByText("Optional: AI diagnosis (only while the model is running)")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/diagnose"), expect.anything());

    fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    await waitFor(() => expect(screen.queryByText("@reviewer")).not.toBeInTheDocument());
    expect(await screen.findByRole("button", { name: "Log in with Threads" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/threads/session", expect.objectContaining({ method: "DELETE" }));
  });

  it("shows the working indicator while a request is in flight", async () => {
    let release: (value: Response) => void = () => undefined;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/config")) {
        return Promise.resolve(json({ mock_enabled: false, gpu_demo_enabled: false, live_enabled: true, max_posts: 30 }));
      }
      if (path.endsWith("/session")) return Promise.resolve(json({ username: "reviewer", mock: false }));
      if (path.endsWith("/diagnosis")) return Promise.resolve(json({ detail: "none" }, 404));
      return new Promise<Response>((resolve) => { release = resolve; });
    }));
    render(<ThreadsPage />);
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    await screen.findByText("@reviewer");

    fireEvent.click(screen.getByRole("button", { name: "Review my posts" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Working…");
    release(json({ mock: false, posts: [] }));
    await waitFor(() => expect(screen.queryByText("Working…")).not.toBeInTheDocument());
  });

  it("translates an error already on screen when the language is switched", async () => {
    stubConnectedApi(429);
    render(<ThreadsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Threads APIが混雑しています。時間を置いてください。");
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(screen.getByRole("alert")).toHaveTextContent("The Threads API is busy. Please wait a moment.");
    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Threads APIが混雑しています");
  });

  it("explains an OAuth failure in English and removes the reason from the URL", async () => {
    window.localStorage.setItem(THREADS_LANG_KEY, "en");
    window.history.replaceState(null, "", "/threads?auth_error=state");
    stubLoggedOutApi();
    render(<ThreadsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The login could not be verified. Please start the login again.");
    expect(window.location.search).toBe("");
  });
});

describe("English display survives OAuth and later visits", () => {
  it("restores English from the saved choice after returning from the Threads authorization screen", async () => {
    window.localStorage.setItem(THREADS_LANG_KEY, "en");
    stubConnectedApi();
    render(<ThreadsPage />);

    expect(await screen.findByRole("button", { name: "Review my posts" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "English" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("@reviewer")).toBeInTheDocument();
  });

  it("opens in English from ?lang=en and remembers it", async () => {
    window.history.replaceState(null, "", "/threads?lang=en");
    stubLoggedOutApi();
    render(<ThreadsPage />);

    expect(await screen.findByRole("button", { name: "Log in with Threads" })).toBeInTheDocument();
    expect(window.localStorage.getItem(THREADS_LANG_KEY)).toBe("en");
  });

  it("lets a reviewer switch back to Japanese after opening ?lang=en", async () => {
    window.history.replaceState(null, "", "/threads?lang=en");
    stubLoggedOutApi();
    render(<ThreadsPage />);
    await screen.findByRole("button", { name: "Log in with Threads" });

    fireEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(await screen.findByRole("button", { name: "Threadsでログイン" })).toBeInTheDocument();
    expect(window.location.search).toBe("");
    expect(window.localStorage.getItem(THREADS_LANG_KEY)).toBe("ja");
  });

  it("ignores an unknown saved value and stays in Japanese", async () => {
    window.localStorage.setItem(THREADS_LANG_KEY, "fr");
    stubLoggedOutApi();
    render(<ThreadsPage />);

    expect(await screen.findByRole("button", { name: "Threadsでログイン" })).toBeInTheDocument();
  });
});
