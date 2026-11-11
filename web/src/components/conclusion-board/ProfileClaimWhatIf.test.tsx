import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Post } from "@/types/post";
import type { ProfileItem } from "@/types/profile";

import { ProfileClaimWhatIf } from "./ProfileClaimWhatIf";

const makePost = (suffix: string): Post => ({
  post_id: `at://did:plc:test/app.bsky.feed.post/${suffix}`,
  text: `架空の投稿 ${suffix}`,
  created_at: "2026-10-20T08:31:00+09:00",
  images: [],
});

const posts = [makePost("a"), makePost("b"), makePost("c"), makePost("d")];

function evidence(post: Post) {
  return { post_id: post.post_id, clue_index: null, required: true, source: "post_text" as const, excerpt: `投稿内の記述 ${post.post_id.slice(-1)}` };
}

const claim: ProfileItem = {
  attribute: "residential_area",
  value: "架空の区",
  confidence: 0.65,
  status: "weak",
  evidence: [evidence(posts[0]), evidence(posts[1]), evidence(posts[2]), evidence(posts[3])],
  evidence_paths: [
    { evidence: [evidence(posts[0]), evidence(posts[1])], confidence: 0.65 },
    { evidence: [evidence(posts[2]), evidence(posts[3])], confidence: 0.6 },
  ],
};

describe("ProfileClaimWhatIf", () => {
  it("shows broken claims separately from evidence fragments that remain", () => {
    render(<ProfileClaimWhatIf claims={[claim]} clues={[]} posts={posts} suggestions={[posts[0].post_id, posts[2].post_id]} webFacts={[]} />);

    expect(screen.getByRole("region", { name: "仮除外で支持されなくなる推定" })).toHaveTextContent("架空の区");
    expect(screen.getByText("残る個別の根拠")).toBeInTheDocument();
    expect(screen.getByText(/投稿内の記述 b/)).toBeInTheDocument();
    expect(screen.getByText(/投稿内の記述 d/)).toBeInTheDocument();
    expect(screen.getByText(/根拠経路だけを使う比較/)).toBeInTheDocument();
  });

  it("keeps a known claim when one complete alternative path survives", () => {
    render(<ProfileClaimWhatIf claims={[claim]} clues={[]} posts={posts} suggestions={[posts[0].post_id, posts[2].post_id]} webFacts={[]} />);

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]); // Keep post C, so path C+D survives.
    expect(screen.getByRole("region", { name: "仮除外後も根拠経路が残る推定" })).toHaveTextContent("架空の区");
    expect(screen.getByRole("region", { name: "仮除外後も根拠経路が残る推定" })).toHaveTextContent("残る完全な根拠経路：1 件");
    expect(screen.getByRole("region", { name: "仮除外で支持されなくなる推定" })).toHaveTextContent("0");
  });

  it("allows choosing other evidence posts when no suggestion is produced and caps selections at three", () => {
    render(<ProfileClaimWhatIf claims={[claim]} clues={[]} posts={posts} suggestions={[]} webFacts={[]} />);

    const morePosts = screen.getByText(/ほかの根拠投稿/);
    fireEvent.click(morePosts);
    const choices = within(morePosts.closest("details")!).getAllByRole("checkbox");
    fireEvent.click(choices[0]);
    fireEvent.click(choices[1]);
    fireEvent.click(choices[2]);
    expect(choices[3]).toBeDisabled();
    expect(screen.getByText(/現在の候補には3件以内で推定を崩す組合せがありません/)).toBeInTheDocument();
  });
});
