import { act, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import type { Post } from "@/types/post";

import { DiagnoseLoading } from "./DiagnoseLoading";

const t = messages.loading;

function post(n: number, text: string, images = 0): Post {
  return {
    post_id: `at://did:plc:abc/app.bsky.feed.post/3k${n}`,
    text,
    created_at: "2026-10-20T08:31:00+09:00",
    images: Array.from({ length: images }, (_, index) => ({
      index,
      url: `https://cdn.bsky.app/img/${n}/${index}`,
      alt: "",
      width: 100,
      height: 100,
    })),
  };
}

function clue(postId: string, type: Clue["type"]): Clue {
  return { post_id: postId, image_index: null, type, value: "x", region: null, confidence: 0.9, source: "text" };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("DiagnoseLoading", () => {
  it("calls out first and shows the status", () => {
    render(<DiagnoseLoading active posts={[]} found={{}} status={messages.diagnose.connecting} />);

    expect(screen.getByText(t.calling)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(messages.diagnose.connecting);
    expect(screen.queryByRole("list", { name: t.feedLabel })).not.toBeInTheDocument();
  });

  it("shows how many posts have been searched", () => {
    const posts = [post(1, "a"), post(2, "b"), post(3, "c"), post(4, "d")];
    render(
      <DiagnoseLoading active posts={posts} found={{ [posts[0].post_id]: { clues: [], error: null } }} status="" />,
    );

    const bar = screen.getByRole("progressbar", { name: t.progressLabel });
    expect(bar).toHaveAttribute("aria-valuenow", "1");
    expect(bar).toHaveAttribute("aria-valuemax", "4");
  });

  it("puts what it found on top of the posts it read, once per kind", () => {
    const night = post(1, "夜勤明け。電車混んでる");
    const photo = post(2, "", 2);
    const found = {
      [night.post_id]: {
        clues: [clue(night.post_id, "routine_text"), clue(night.post_id, "routine_text")],
        error: null,
      },
    };
    render(<DiagnoseLoading active posts={[night, photo]} found={found} status="" />);

    const items = within(screen.getByRole("list", { name: t.feedLabel }))
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(items).toEqual([
      t.found(messages.clues.typeLabels.routine_text),
      t.reading(t.photoPost(2)),
      t.reading("夜勤明け。電車混んでる"),
    ]);
  });

  it("keeps only the latest lines and shortens long posts", () => {
    const posts = Array.from({ length: 8 }, (_, i) => post(i, `${i}${"あ".repeat(40)}`));
    render(<DiagnoseLoading active posts={posts} found={{}} status="" />);

    const items = within(screen.getByRole("list", { name: t.feedLabel })).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent(/^読んだ：「7あ+…」$/);
  });

  it("shows only the status once the diagnosis is over", () => {
    render(<DiagnoseLoading active={false} posts={[post(1, "a")]} found={{}} status={messages.diagnose.done(1)} />);

    expect(screen.getByRole("status")).toHaveTextContent(messages.diagnose.done(1));
    expect(screen.queryByText(t.calling)).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("changes its line every few seconds", () => {
    vi.useFakeTimers();
    render(<DiagnoseLoading active posts={[]} found={{}} status="" />);
    expect(screen.getByText(t.lines[0])).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(3500));

    expect(screen.queryByText(t.lines[0])).not.toBeInTheDocument();
    expect(screen.getByText(t.lines[1])).toBeInTheDocument();
  });
});
