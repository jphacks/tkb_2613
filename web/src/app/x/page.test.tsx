import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import XPage from "./page";

const posts = [
  { post_id: "x:9001", text: "渋谷駅、火曜10時", created_at: "2026-11-03T18:00:00+09:00", images: [] },
  { post_id: "x:9002", text: "渋谷駅 火曜日10時", created_at: "2026-11-10T18:00:00+09:00", images: [] },
];
const station = {
  category: "station", value: "渋谷駅", count: 2,
  evidence: [
    { post_id: "x:9001", quote: "渋谷駅" },
    { post_id: "x:9002", quote: "渋谷駅" },
  ],
};
const weekday = {
  category: "weekday", value: "火曜日", count: 2,
  evidence: [
    { post_id: "x:9001", quote: "火曜" },
    { post_id: "x:9002", quote: "火曜日" },
  ],
};
const snapshot = { posts, information: [station, weekday], mock: true, elapsed_ms: 1 };
const after = {
  posts: [posts[1]],
  information: [{ ...station, count: 1, evidence: [station.evidence[1]] }],
  mock: true,
};

function response(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("X public information page", () => {
  it("explains consent and keeps live X disabled", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request): Promise<Response> => {
      const path = String(input);
      if (path.endsWith("/config")) return response({ mock_enabled: true, live_enabled: false, max_posts: 30 });
      if (path.endsWith("/session")) return response({}, 401);
      throw new Error(`unexpected path ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<XPage />);

    expect(await screen.findByText("現在は架空の合成投稿だけを使います")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Xでログイン" })).not.toBeInTheDocument();
    expect(screen.getByText(/住所、勤務先、居住地域、健康や政治信条などは推定しません/)).toBeInTheDocument();
  });

  it("shows literal evidence, source posts, exclusion, and reaggregation", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request): Promise<Response> => {
      const path = String(input);
      if (path.endsWith("/config")) return response({ mock_enabled: true, live_enabled: false, max_posts: 30 });
      if (path.endsWith("/mock/session")) return response({ username: "架空のXアカウント", mock: true });
      if (path.endsWith("/session")) return response({}, 401);
      if (path.endsWith("/diagnose")) return response(snapshot);
      if (path.endsWith("/simulate")) return response({
        delete: ["x:9001"], before: [station, weekday], after: [after.information[0]],
        removed: [{ category: "weekday", value: "火曜日" }],
      });
      if (path.endsWith("/rediagnose")) return response(after);
      throw new Error(`unexpected path ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<XPage />);

    fireEvent.click(await screen.findByRole("checkbox", { name: /利用目的を確認し/ }));
    fireEvent.click(screen.getByRole("button", { name: "架空のX投稿で試す" }));
    fireEvent.click(await screen.findByRole("button", { name: "公開情報を確認する" }));

    expect(await screen.findByText("駅名：渋谷駅")).toBeInTheDocument();
    expect(screen.getAllByText("2件の投稿に記載")).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "元投稿を確認" })).toHaveLength(4);

    fireEvent.click(screen.getAllByRole("checkbox", { name: "仮除外する" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "仮除外後を比べる" }));
    expect(await screen.findByRole("status")).toHaveTextContent("曜日「火曜日」");

    fireEvent.click(screen.getByRole("button", { name: "選択した投稿を除いて再集計" }));
    await waitFor(() => expect(screen.getByText("仮除外後の再集計")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/x/rediagnose", expect.objectContaining({ method: "POST" }),
    );
  });
});
