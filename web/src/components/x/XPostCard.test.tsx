import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { XAuthor, XPostDisplay } from "@/lib/xDisplay";

import { XPostCard } from "./XPostCard";

const text = "@friend_1 と #新宿 https://t.co/abc";
const post = { post_id: "x:123", text, created_at: "2026-11-10T03:00:00Z", images: [] };
const author: XAuthor = {
  username: "fictional_xtest",
  name: "架空のテスター",
  profile_image_url: "https://pbs.twimg.com/profile_images/1/a_normal.jpg",
  profile_url: "https://x.com/fictional_xtest",
};
const display: XPostDisplay = {
  permalink: "https://x.com/fictional_xtest/status/123",
  edited: true,
  entities: [
    { kind: "mention", start: 0, end: 9, href: "https://x.com/friend_1", display: null },
    { kind: "hashtag", start: 12, end: 15, href: "https://x.com/search?q=%23新宿", display: null },
    { kind: "url", start: 16, end: 32, href: "https://t.co/abc", display: "example.com/page" },
  ],
};

describe("XPostCard", () => {
  afterEach(() => vi.restoreAllMocks());

  it("meets the X display requirements for a real post", () => {
    render(<XPostCard post={post} author={author} display={display} synthetic={false} />);
    const card = screen.getByRole("article", { name: "架空のテスターの投稿" });

    // 投稿者：アイコン・表示名・@ユーザー名がプロフィールへリンクする
    const profileLinks = within(card).getAllByRole("link").filter((a) => a.getAttribute("href") === author.profile_url);
    expect(profileLinks).toHaveLength(3);
    expect(within(card).getByText("@fictional_xtest")).toBeInTheDocument();
    expect(card.querySelector("img")?.getAttribute("src")).toBe(author.profile_image_url);
    // X のロゴ
    expect(within(card).getByRole("img", { name: "X" })).toBeInTheDocument();
    // 本文のエンティティ
    expect(within(card).getByRole("link", { name: "@friend_1" })).toHaveAttribute("href", "https://x.com/friend_1");
    expect(within(card).getByRole("link", { name: "#新宿" })).toHaveAttribute("href", "https://x.com/search?q=%23新宿");
    expect(within(card).getByRole("link", { name: "example.com/page" })).toHaveAttribute("href", "https://t.co/abc");
    // 日時は permalink へ。操作アイコンの代わりに「Xで見る」
    expect(within(card).getByRole("link", { name: /2026\/11\/10/ })).toHaveAttribute("href", display.permalink);
    expect(within(card).getByRole("link", { name: "Xで見る" })).toHaveAttribute("href", display.permalink);
    expect(within(card).getByText("編集済み")).toBeInTheDocument();
    for (const link of within(card).getAllByRole("link")) {
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
  });

  it("opens the permalink from whitespace around the author and post text", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    const { container } = render(
      <XPostCard post={post} author={author} display={display} synthetic={false} />,
    );

    fireEvent.click(container.querySelector("header") as HTMLElement);
    fireEvent.click(container.querySelector("p") as HTMLElement);
    expect(open).toHaveBeenCalledTimes(2);
    expect(open).toHaveBeenCalledWith(display.permalink, "_blank", "noopener,noreferrer");
  });

  it("does not dress a synthetic post up as an X post", () => {
    render(<XPostCard post={post} author={{ ...author, profile_image_url: null }} display={{ ...display, edited: false }} synthetic />);
    const card = screen.getByRole("article");

    expect(within(card).queryAllByRole("link")).toHaveLength(0);
    expect(within(card).queryByRole("img", { name: "X" })).not.toBeInTheDocument();
    expect(within(card).getByText("架空")).toBeInTheDocument();
    expect(within(card).getByText("架空の投稿（Xの投稿ではありません）")).toBeInTheDocument();
    expect(card).toHaveTextContent(text); // 本文はそのまま（t.co も置き換えない）
  });
});

describe("XPostCard highlights", () => {
  it("marks places and stations without changing the text, also inside links", () => {
    const body = "🍜 渋谷駅 #渋谷駅 東京都渋谷区";
    const tagged: XPostDisplay = {
      permalink: null, edited: false,
      entities: [{ kind: "hashtag", start: 6, end: 10, href: "https://x.com/search?q=%23渋谷駅", display: null }],
    };
    const { container } = render(<XPostCard post={{ ...post, text: body }} author={author} display={tagged} synthetic={false}
      highlights={[
        { category: "station", start: 2, end: 5 },
        { category: "station", start: 7, end: 10 },
        { category: "place", start: 11, end: 17 },
      ]} />);

    const marks = Array.from(container.querySelectorAll("mark")).map((m) => [m.textContent, m.dataset.category]);
    expect(marks).toEqual([["渋谷駅", "station"], ["渋谷駅", "station"], ["東京都渋谷区", "place"]]);
    expect(screen.getByRole("link", { name: "#渋谷駅" })).toBeInTheDocument();
    expect(container.querySelector("p")?.textContent).toBe(body);
  });

  it("does not mark anything by default", () => {
    const { container } = render(<XPostCard post={post} author={author} display={display} synthetic />);
    expect(container.querySelectorAll("mark")).toHaveLength(0);
  });
});
