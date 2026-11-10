import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import XPage from "./page";

const posts = [
  { post_id: "x:9001", text: "毎週火曜はジム", created_at: "2026-11-03T18:00:00+09:00", images: [] },
  { post_id: "x:9002", text: "火曜のジム", created_at: "2026-11-10T18:00:00+09:00", images: [] },
];
const clues = [
  { post_id: "x:9001", image_index: null, type: "routine_text", value: "毎週火曜はジム",
    region: null, confidence: 0.9, source: "text", quote: "毎週火曜はジム" },
  { post_id: "x:9002", image_index: null, type: "routine_text", value: "火曜のジム",
    region: null, confidence: 0.9, source: "text", quote: "火曜のジム" },
];
const conclusions = [{ rule: "R3", attribute: "routine", value: "火曜のジム",
  clue_indices: [0, 1], note: "" }];
const plan = { delete: [], broken: [], after: [], posts: [] };
const snapshot = { posts, clues, conclusions, plan, mock: true, elapsed_ms: 12 };
const after = { posts: [posts[1]], clues: [clues[1]], conclusions: [], plan, mock: true };

function response(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("X diagnosis page", () => {
  it("starts the GPU demo with synthetic posts only", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request): Promise<Response> => {
      const path = String(input);
      if (path.endsWith("/config")) return response({ mock_enabled: true, gpu_demo_enabled: true, live_enabled: false, max_posts: 30 });
      if (path.endsWith("/mock/gpu-session")) return response({ username: "架空のXアカウント", mock: true });
      if (path.endsWith("/session")) return response({}, 401);
      throw new Error(`unexpected path ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<XPage />);
    fireEvent.click(await screen.findByRole("checkbox", { name: /自分の投稿を診断し/ }));
    fireEvent.click(screen.getByRole("button", { name: "架空のX投稿をGPUで診断" }));
    expect(await screen.findByText("架空のXアカウント")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/x/mock/gpu-session",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ consent: true }) }),
    );
  });

  it("shows synthetic evidence, previews exclusion, and rediagnoses", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request): Promise<Response> => {
      const path = String(input);
      if (path.endsWith("/config")) return response({ mock_enabled: true, gpu_demo_enabled: false, live_enabled: false, max_posts: 30 });
      if (path.endsWith("/mock/session")) return response({ username: "架空のXアカウント", mock: true });
      if (path.endsWith("/session")) return response({}, 401);
      if (path.endsWith("/diagnose")) return response(snapshot);
      if (path.endsWith("/simulate")) return response({ delete: ["x:9001"], broken: ["routine"], after: [] });
      if (path.endsWith("/rediagnose")) return response(after);
      throw new Error(`unexpected path ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<XPage />);

    fireEvent.click(await screen.findByRole("checkbox", { name: /自分の投稿を診断し/ }));
    fireEvent.click(screen.getByRole("button", { name: "架空のX投稿で試す" }));
    fireEvent.click(await screen.findByRole("button", { name: "診断する" }));
    expect(await screen.findByText("推定の根拠投稿")).toBeInTheDocument();
    expect(screen.getByText(/投稿 x:9001/)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("checkbox", { name: "仮除外する" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "仮除外を試す" }));
    expect(await screen.findByRole("status")).toHaveTextContent("routine");
    fireEvent.click(screen.getByRole("button", { name: "選択した投稿を除いて再診断" }));
    await waitFor(() => expect(screen.getByText("仮除外後の再診断")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith("/api/x/rediagnose", expect.objectContaining({ method: "POST" }));
  });
});
