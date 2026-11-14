import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Post } from "@/types/post";
import type { ProfileCandidateSet, ProfileRelation } from "@/types/profile";

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

const claim: ProfileCandidateSet = {
  attribute: "residential_area",
  status: "candidate",
  reason: null,
  candidates: [{
    rank: 1,
    value: "架空の区",
    confidence: 0.65,
    status: "weak",
    evidence: [evidence(posts[0]), evidence(posts[1]), evidence(posts[2]), evidence(posts[3])],
    evidence_paths: [
      { evidence: [evidence(posts[0]), evidence(posts[1])], confidence: 0.65, provenance: "combined_inference" },
      { evidence: [evidence(posts[2]), evidence(posts[3])], confidence: 0.6, provenance: "combined_inference" },
    ],
    observed_at: null,
    assessment: {
      minimal_scope: "bluesky",
      offline_subtype: null,
      psychological_resistance: null,
      persona_context: null,
      inference_ease: null,
      inference_ease_basis: null,
      harm_severity: null,
      harm_scenario: null,
      harm_prerequisites: [],
      harm_status: "unknown",
    },
    counter_evidence: [],
  }],
  candidate_pool: [{
    rank: 1,
    value: "架空の区",
    confidence: 0.65,
    status: "weak",
    evidence: [evidence(posts[0]), evidence(posts[1]), evidence(posts[2]), evidence(posts[3])],
    evidence_paths: [
      { evidence: [evidence(posts[0]), evidence(posts[1])], confidence: 0.65, provenance: "combined_inference" },
      { evidence: [evidence(posts[2]), evidence(posts[3])], confidence: 0.6, provenance: "combined_inference" },
    ],
    observed_at: null,
    assessment: {
      minimal_scope: "bluesky",
      offline_subtype: null,
      psychological_resistance: null,
      persona_context: null,
      inference_ease: null,
      inference_ease_basis: null,
      harm_severity: null,
      harm_scenario: null,
      harm_prerequisites: [],
      harm_status: "unknown",
    },
    counter_evidence: [],
  }],
  conflicting_evidence: [],
};

describe("ProfileClaimWhatIf", () => {
  it("shows broken claims separately from evidence fragments that remain", () => {
    render(<ProfileClaimWhatIf claims={[claim]} clues={[]} posts={posts} suggestions={[posts[0].post_id, posts[2].post_id]} webFacts={[]} />);

    expect(screen.getByRole("region", { name: "仮除外で支持されなくなる候補" })).toHaveTextContent("架空の区");
    expect(screen.getByRole("region", { name: "仮除外で支持されなくなる候補" })).toHaveTextContent("仮除外後：不明");
    expect(screen.getByText("残る個別の根拠")).toBeInTheDocument();
    expect(screen.getByText(/投稿内の記述 b/)).toBeInTheDocument();
    expect(screen.getByText(/投稿内の記述 d/)).toBeInTheDocument();
    expect(screen.getByText(/保存済みの全候補の根拠経路を再評価/)).toBeInTheDocument();
  });

  it("keeps a known claim when one complete alternative path survives", () => {
    render(<ProfileClaimWhatIf claims={[claim]} clues={[]} posts={posts} suggestions={[posts[0].post_id, posts[2].post_id]} webFacts={[]} />);

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]); // Keep post C, so path C+D survives.
    expect(screen.getByRole("region", { name: "仮除外後も根拠経路が残る候補" })).toHaveTextContent("架空の区");
    expect(screen.getByRole("region", { name: "仮除外後も根拠経路が残る候補" })).toHaveTextContent("表示候補数：1 → 1 件（根拠のある候補全体：1 → 1 件）");
    expect(screen.getByRole("region", { name: "仮除外で支持されなくなる候補" })).toHaveTextContent("0");
  });

  it("removes a home-to-commute relation when a selected post breaks its complete path", () => {
    const homeClaim = { ...claim, attribute: "home_nearest_station" as const };
    const regularClaim = { ...claim, attribute: "regular_station" as const };
    const relation: ProfileRelation = {
      kind: "home_nearest_is_commute_origin",
      left: { kind: "profile_candidate", attribute: "home_nearest_station", value: "架空の区" },
      right: { kind: "profile_candidate", attribute: "regular_station", value: "架空の区" },
      evidence_paths: [{ evidence: [evidence(posts[0]), evidence(posts[1])], confidence: 0.55, provenance: "combined_inference" }],
    };
    render(<ProfileClaimWhatIf claims={[homeClaim, regularClaim]} relations={[relation]} clues={[]} posts={posts} suggestions={[]} webFacts={[]} />);
    expect(screen.getByRole("region", { name: "仮除外後に残る関係" })).toHaveTextContent("自宅の最寄り駅：架空の区 → 投稿時点の通勤利用駅候補：架空の区");
    const morePosts = screen.getByText(/ほかの根拠投稿/);
    fireEvent.click(morePosts);
    const [postA] = within(morePosts.closest("details")!).getAllByRole("checkbox");
    fireEvent.click(postA);
    expect(screen.getByRole("region", { name: "仮除外後に残る関係" })).toHaveTextContent("選んだ投稿を含まない完全な関係根拠は残りません。");
  });

  it("promotes a previously hidden grounded candidate and reports rank and count changes", () => {
    const assessment = claim.candidates[0].assessment;
    const candidates = [
      { rank: 1, value: "候補 A", confidence: 0.90, status: "weak" as const, evidence: [evidence(posts[0]), evidence(posts[1])], evidence_paths: [{ evidence: [evidence(posts[0]), evidence(posts[1])], confidence: 0.90, provenance: "combined_inference" as const }], assessment, observed_at: null, counter_evidence: [] },
      { rank: 2, value: "候補 B", confidence: 0.75, status: "weak" as const, evidence: [evidence(posts[2]), evidence(posts[3])], evidence_paths: [{ evidence: [evidence(posts[2]), evidence(posts[3])], confidence: 0.75, provenance: "combined_inference" as const }], assessment, observed_at: null, counter_evidence: [] },
      { rank: 3, value: "候補 C", confidence: 0.74, status: "weak" as const, evidence: [evidence(posts[1]), evidence(posts[3])], evidence_paths: [{ evidence: [evidence(posts[1]), evidence(posts[3])], confidence: 0.74, provenance: "combined_inference" as const }], assessment, observed_at: null, counter_evidence: [] },
    ];
    const claimWithPool: ProfileCandidateSet = {
      ...claim,
      status: "candidate",
      candidates: [candidates[0]],
      candidate_pool: candidates,
    };

    render(<ProfileClaimWhatIf claims={[claimWithPool]} clues={[]} posts={posts} suggestions={[posts[0].post_id]} webFacts={[]} />);

    const after = screen.getByRole("region", { name: "仮除外後も根拠経路が残る候補" });
    expect(after).toHaveTextContent("候補 B / 候補 C");
    expect(after).toHaveTextContent("表示候補数：1 → 2 件（根拠のある候補全体：3 → 2 件）");
    expect(after).toHaveTextContent("候補 B：#2 → #1");
  });

  it("drops current-location wording when the what-if result is older than 15 minutes", () => {
    const oldLocation = { ...claim.candidates[0], observed_at: new Date(Date.now() - 16 * 60_000).toISOString() };
    const locationSet: ProfileCandidateSet = {
      ...claim,
      attribute: "realtime_location",
      candidates: [oldLocation],
      candidate_pool: [oldLocation],
    };
    render(<ProfileClaimWhatIf claims={[locationSet]} clues={[]} posts={posts} suggestions={[]} webFacts={[]} />);

    const after = screen.getByRole("region", { name: "仮除外後も根拠経路が残る候補" });
    expect(after).toHaveTextContent("投稿時点の位置候補：架空の区");
    expect(after).not.toHaveTextContent("リアルタイムの現在地");
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
    expect(screen.getByText(/現在の候補には3件以内で候補を崩す組合せがありません/)).toBeInTheDocument();
  });
});
