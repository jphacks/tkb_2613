import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConclusionBoard } from "./ConclusionBoard";

const candidate = {
  id: "candidate-1",
  url: "https://example.net/blog",
  domain: "example.net",
  title: "架空のブログ",
  status: "candidate" as const,
  owner_evidence: null,
};

describe("ConclusionBoard external profile results", () => {
  it.each([
    ["not_requested", "公開Web検索は行っていません。"],
    ["fixture", "モック用の架空候補です（外部通信なし）"],
    ["searched", "検索順位やハンドル一致だけでは同一人物と判断していません。"],
    ["no_results", "検索結果はありませんでした。安全の確認を意味しません。"],
    ["unavailable", "公開Web検索を利用できませんでした。安全の確認を意味しません。"],
  ] as const)("explains the %s state", (status, message) => {
    render(<ConclusionBoard clues={[]} conclusions={[]} externalLookupStatus={status} />);
    expect(screen.getByRole("status")).toHaveTextContent(message);
    expect(screen.getByText("勤務先名の公的情報照合はまだ行っていません" )).toBeInTheDocument();
  });

  it("distinguishes a search candidate from an owner-published link", () => {
    render(
      <ConclusionBoard
        clues={[]}
        conclusions={[]}
        webLookupStatus="fixture"
        externalLookupStatus="searched"
        externalProfileResults={[
          candidate,
          {
            ...candidate,
            id: "owner-1",
            url: "https://example.org/article",
            domain: "example.org",
            title: "架空の記事",
            status: "owner_linked",
            owner_evidence: {
              kind: "post_text",
              post_id: "at://did:plc:test/app.bsky.feed.post/a",
              excerpt: "私の記事 https://example.org/article",
            },
          },
        ]}
      />,
    );

    expect(screen.getByText("勤務先名の公開Web情報は架空のデモデータです")).toBeInTheDocument();
    expect(screen.getByText("検索候補（同一人物未確認）")).toBeInTheDocument();
    expect(screen.getByText("本人のプロフィール/投稿に掲載されたURLと一致")).toBeInTheDocument();
    expect(screen.getByText(/本人の投稿/)).toBeInTheDocument();
    expect(screen.getByText(/実世界の同一人物を確認したものではありません/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "https://example.net/blog" })).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders a sourced profile claim, its assessment, and an unmapped prototype fallback", () => {
    const postId = "at://did:plc:test/app.bsky.feed.post/a";
    render(
      <ConclusionBoard
        clues={[{
          post_id: postId,
          image_index: 0,
          type: "station_sign",
          value: "根津",
          region: [1, 2, 30, 40],
          confidence: 0.9,
          source: "ocr",
        }]}
        posts={[{ post_id: postId, text: "根津駅で撮影", created_at: "2026-10-20T08:00:00Z", images: [] }]}
        profileClaims={[{
          attribute: "regular_station",
          value: "根津駅",
          confidence: 0.85,
          status: "found",
          evidence: [{ post_id: postId, clue_index: 0, required: true, source: "clue" }],
          evidence_paths: [{
            confidence: 0.85,
            evidence: [{ post_id: postId, clue_index: 0, required: true, source: "clue" }],
          }],
          assessment: {
            minimal_scope: "bluesky",
            offline_subtype: null,
            psychological_resistance: 2,
            persona_context: "架空の利用者",
            inference_ease: 3,
            inference_ease_basis: "provisional",
            harm_severity: null,
            harm_scenario: "架空の被害例",
            harm_prerequisites: ["追加条件"],
            harm_status: "prerequisites_unmet",
          },
        }]}
        conclusions={[{
          rule: "R1",
          attribute: "unknown_prototype_attribute",
          value: "架空の候補",
          clue_indices: [0],
          note: "架空の注記",
        }]}
      />,
    );

    expect(screen.getByText("根津駅")).toBeInTheDocument();
    expect(screen.getByText("Bluesky内のみ")).toBeInTheDocument();
    expect(screen.getByText(/条件未成立: 架空の被害例/)).toBeInTheDocument();
    expect(screen.getByText(/写真OCR · 画像位置: 1, 2, 30, 40 px/)).toBeInTheDocument();
    expect(screen.getByText(/unknown_prototype_attribute/)).toBeInTheDocument();
    expect(screen.getByText("架空の注記")).toBeInTheDocument();
  });
});
