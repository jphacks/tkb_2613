import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ThreadsPage from "./page";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("Threads review flow without a model", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows own post details, runs the non-AI check, and logs out without diagnose", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/config")) {
        return json({ mock_enabled: false, gpu_demo_enabled: false, live_enabled: true, max_posts: 30 });
      }
      if (path.endsWith("/session") && init?.method === "DELETE") return new Response(null, { status: 204 });
      if (path.endsWith("/session")) return json({ username: "reviewer", mock: false });
      if (path.endsWith("/diagnosis")) return json({ detail: "診断結果がありません" }, 404);
      if (path.endsWith("/posts")) {
        return json({
          mock: false,
          posts: [{
            post_id: "threads:review-1",
            text: "公式サイト https://example.com を確認",
            created_at: "2026-11-12T12:00:00+09:00",
            images: [],
          }],
        });
      }
      throw new Error(`unexpected fetch: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

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
