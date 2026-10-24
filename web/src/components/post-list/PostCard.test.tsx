import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Post } from "@/types/post";

import { PostCard } from "./PostCard";

const POST: Post = {
  post_id: "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx",
  text: "夜勤明けのラーメン",
  created_at: "2026-10-20T08:31:00+09:00",
  images: [
    {
      index: 0,
      url: "https://cdn.bsky.app/img/feed_fullsize/plain/did:plc:xxxx/demo01@jpeg",
      alt: "",
      width: 1200,
      height: 900,
    },
  ],
};

describe("PostCard", () => {
  it("shows the text and the posting time in Japan time", () => {
    render(<PostCard post={POST} />);

    expect(screen.getByText("夜勤明けのラーメン")).toBeInTheDocument();
    const time = screen.getByText(/10\/20.*8:31/);
    expect(time.tagName).toBe("TIME");
    expect(time).toHaveAttribute("datetime", "2026-10-20T08:31:00+09:00");
  });

  it("shows each photo, naming it by its number when it has no alt text", () => {
    render(<PostCard post={POST} />);

    const img = screen.getByRole("img", { name: "写真 1" });
    expect(img).toHaveAttribute("src", POST.images[0].url);
    expect(img).toHaveAttribute("referrerpolicy", "no-referrer");
  });

  it("uses the alt text of the post when it has one", () => {
    render(<PostCard post={{ ...POST, images: [{ ...POST.images[0], alt: "ラーメンの丼" }] }} />);

    expect(screen.getByRole("img", { name: "ラーメンの丼" })).toBeInTheDocument();
  });

  it("keeps the photo's shape and shows a placeholder when the photo cannot be loaded", () => {
    render(<PostCard post={POST} />);

    fireEvent.error(screen.getByRole("img", { name: "写真 1" }));

    expect(screen.queryByRole("img", { name: "写真 1" })).not.toBeInTheDocument();
    const placeholder = screen.getByText("写真 1（表示できません）");
    expect(placeholder.closest("[style]")).toHaveStyle({ aspectRatio: "1200 / 900" });
  });

  it("shows no photo area for a text-only post", () => {
    render(<PostCard post={{ ...POST, images: [] }} />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
