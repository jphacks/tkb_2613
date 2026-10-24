import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Clue } from "@/types/clue";
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

  it("shakes the card only when a clue is found", () => {
    const clue: Clue = {
      post_id: POST.post_id,
      image_index: null,
      type: "place_text",
      value: "新宿",
      region: null,
      confidence: 0.8,
      source: "text",
    };
    const { container, rerender } = render(<PostCard post={POST} />);
    const card = container.querySelector("article");
    expect(card).not.toHaveClass("clue-hit");

    rerender(<PostCard post={POST} found={{ clues: [], error: null }} />);
    expect(card).not.toHaveClass("clue-hit");

    rerender(<PostCard post={POST} found={{ clues: [clue], error: null }} />);
    expect(card).toHaveClass("clue-hit");
  });

  it("frames a photo clue on its own photo once the photo has loaded", () => {
    const clue: Clue = {
      ...TEXT_CLUE,
      image_index: 0,
      type: "station_sign",
      source: "vlm",
      region: [600, 225, 1200, 450],
    };
    const { container } = render(<PostCard post={POST} found={{ clues: [clue], error: null }} />);
    expect(container.querySelector(".photo-mark")).not.toBeInTheDocument();

    const img = screen.getByRole("img", { name: "写真 1" });
    Object.defineProperty(img, "naturalWidth", { value: 2400 });
    Object.defineProperty(img, "naturalHeight", { value: 1800 });
    fireEvent.load(img);

    expect(container.querySelector(".photo-mark")).toHaveStyle({
      left: "25%",
      top: "12.5%",
      width: "25%",
      height: "12.5%",
    });
  });
});

const TEXT_CLUE: Clue = {
  post_id: POST.post_id,
  image_index: null,
  type: "place_text",
  value: "新宿",
  region: null,
  confidence: 0.8,
  source: "text",
};
