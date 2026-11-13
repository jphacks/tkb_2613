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
      if (path.endsWith("/config")) return response({ mock_enabled: true, live_enabled: false, max_posts: 5 });
      if (path.endsWith("/session")) return response({}, 401);
      throw new Error(`unexpected path ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<XPage />);

    expect(await screen.findByText("現在は架空の合成投稿だけを使います")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Xでログイン" })).not.toBeInTheDocument();
    expect(screen.getByText(/AI推論、個人情報や位置情報の抽出・集計は行いません/)).toBeInTheDocument();
  });

  function stubConfig(config: unknown, status = 200) {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request): Promise<Response> => {
      const path = String(input);
      if (path.endsWith("/config")) return response(config, status);
      if (path.endsWith("/session")) return response({}, 401);
      throw new Error(`unexpected path ${path}`);
    }));
  }

  it.each([
    ["the API reports live X closed", { mock_enabled: false, live_enabled: false, max_posts: 30 }, 200],
    ["the config request fails", {}, 503],
    ["the config response is malformed", { mock_enabled: false, live_enabled: "yes", max_posts: 30 }, 200],
  ])("hides the live X entry when %s", async (_case, config, status) => {
    stubConfig(config, status);
    render(<XPage />);

    expect(await screen.findByText("現在、X公開情報チェックは準備中です。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Xでログイン" })).not.toBeInTheDocument();
    expect(screen.queryByText(/X APIの読み取りは課金対象です/)).not.toBeInTheDocument();
  });

  it("shows the live X entry only when the API reports every approval in place", async () => {
    stubConfig({ mock_enabled: false, live_enabled: true, max_posts: 5 });
    render(<XPage />);

    expect(await screen.findByRole("button", { name: "Xでログイン" })).toBeDisabled();
    expect(screen.getByText(/X APIの読み取りは課金対象です/)).toBeInTheDocument();
  });

  it("loads a live account through the raw posts endpoint without analysis controls", async () => {
    const xDisplay = {
      synthetic: false,
      author: { username: "owner", name: "Owner", profile_image_url: null, profile_url: "https://x.com/owner" },
      posts: Object.fromEntries(posts.map((post) => [post.post_id, {
        permalink: `https://x.com/owner/status/${post.post_id.slice(2)}`, edited: false, entities: [],
      }])),
    };
    const fetchMock = vi.fn(async (input: string | URL | Request): Promise<Response> => {
      const path = String(input);
      if (path.endsWith("/config")) return response({ mock_enabled: false, live_enabled: true, max_posts: 5 });
      if (path.endsWith("/session")) return response({ username: "owner", mock: false });
      if (path.endsWith("/diagnosis")) return response({}, 404);
      if (path.endsWith("/posts")) return response({
        posts, information: [], post_errors: [], view: "posts", mock: false, x_display: xDisplay,
      });
      throw new Error(`unexpected path ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<XPage />);

    fireEvent.click(await screen.findByRole("button", { name: "自分の投稿を読み込む" }));

    expect(await screen.findByText("本人投稿の取得結果")).toBeInTheDocument();
    expect(screen.getByText("投稿 2 件・原文表示のみ")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "仮除外する" })).not.toBeInTheDocument();
    expect(screen.queryByText("本文に書かれている情報")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/x/posts", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).not.toHaveBeenCalledWith("/api/x/diagnose", expect.anything());
  });

  it("shows an empty state when the live account has no posts", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request): Promise<Response> => {
      const path = String(input);
      if (path.endsWith("/config")) return response({ mock_enabled: false, live_enabled: true, max_posts: 5 });
      if (path.endsWith("/session")) return response({ username: "owner", mock: false });
      if (path.endsWith("/diagnosis")) return response({}, 404);
      if (path.endsWith("/posts")) return response({
        posts: [], information: [], post_errors: [], view: "posts", mock: false,
        x_display: {
          synthetic: false,
          author: { username: "owner", name: "Owner", profile_image_url: null, profile_url: "https://x.com/owner" },
          posts: {},
        },
      });
      throw new Error(`unexpected path ${path}`);
    }));
    render(<XPage />);

    fireEvent.click(await screen.findByRole("button", { name: "自分の投稿を読み込む" }));
    expect(await screen.findByText("表示できる投稿はありません。")).toBeInTheDocument();
  });

  it("shows a safe message when the X API request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request): Promise<Response> => {
      const path = String(input);
      if (path.endsWith("/config")) return response({ mock_enabled: false, live_enabled: true, max_posts: 5 });
      if (path.endsWith("/session")) return response({ username: "owner", mock: false });
      if (path.endsWith("/diagnosis")) return response({}, 404);
      if (path.endsWith("/posts")) return response({}, 502);
      throw new Error(`unexpected path ${path}`);
    }));
    render(<XPage />);

    fireEvent.click(await screen.findByRole("button", { name: "自分の投稿を読み込む" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("X APIから投稿を取得できませんでした");
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

  it("renders posts with the X display card when the API sends display information", async () => {
    const xDisplay = {
      synthetic: true,
      author: { username: "架空のXアカウント", name: "架空のXアカウント", profile_image_url: null, profile_url: null },
      posts: Object.fromEntries(posts.map((post) => [post.post_id, { permalink: null, edited: false, entities: [] }])),
    };
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request): Promise<Response> => {
      const path = String(input);
      if (path.endsWith("/config")) return response({ mock_enabled: true, live_enabled: false, max_posts: 30 });
      if (path.endsWith("/mock/session")) return response({ username: "架空のXアカウント", mock: true });
      if (path.endsWith("/session")) return response({}, 401);
      if (path.endsWith("/diagnose")) return response({ ...snapshot, x_display: xDisplay });
      throw new Error(`unexpected path ${path}`);
    }));
    render(<XPage />);

    fireEvent.click(await screen.findByRole("checkbox", { name: /利用目的を確認し/ }));
    fireEvent.click(screen.getByRole("button", { name: "架空のX投稿で試す" }));
    fireEvent.click(await screen.findByRole("button", { name: "公開情報を確認する" }));

    expect(await screen.findAllByText("架空の投稿（Xの投稿ではありません）")).toHaveLength(2);
    expect(screen.queryByRole("img", { name: "X" })).not.toBeInTheDocument();
  });

  it("highlights places and stations without counting values when the API uses the highlight view", async () => {
    const xDisplay = {
      synthetic: true,
      author: { username: "架空のXアカウント", name: "架空のXアカウント", profile_image_url: null, profile_url: null },
      posts: Object.fromEntries(posts.map((post) => [post.post_id, { permalink: null, edited: false, entities: [] }])),
    };
    const highlightSnapshot = {
      ...snapshot, view: "highlight", information: [], x_display: xDisplay,
      highlights: { "x:9001": [{ category: "station", start: 0, end: 3 }], "x:9002": [{ category: "station", start: 0, end: 3 }] },
    };
    const fetchMock = vi.fn(async (input: string | URL | Request): Promise<Response> => {
      const path = String(input);
      if (path.endsWith("/config")) return response({ mock_enabled: true, live_enabled: false, max_posts: 30, info_view: "highlight" });
      if (path.endsWith("/mock/session")) return response({ username: "架空のXアカウント", mock: true });
      if (path.endsWith("/session")) return response({}, 401);
      if (path.endsWith("/diagnose")) return response(highlightSnapshot);
      if (path.endsWith("/rediagnose")) return response({ ...highlightSnapshot, posts: [posts[1]], highlights: { "x:9002": highlightSnapshot.highlights["x:9002"] } });
      throw new Error(`unexpected path ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<XPage />);

    fireEvent.click(await screen.findByRole("checkbox", { name: /利用目的を確認し/ }));
    fireEvent.click(screen.getByRole("button", { name: "架空のX投稿で試す" }));
    fireEvent.click(await screen.findByRole("button", { name: "公開情報を確認する" }));

    expect(await screen.findByText(/件数は数えません/)).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll("article mark")).map((m) => m.textContent)).toEqual(["渋谷駅", "渋谷駅"]);
    expect(screen.queryByText("駅名：渋谷駅")).not.toBeInTheDocument();
    expect(screen.queryByText(/件の投稿に記載/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "仮除外後を比べる" })).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("checkbox", { name: /仮除外する/ })[0]);
    fireEvent.click(screen.getByRole("button", { name: "選択した投稿を除いて表示" }));
    expect(await screen.findByText("（表示から除外中）")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith("/api/x/simulate", expect.anything());
  });
});
