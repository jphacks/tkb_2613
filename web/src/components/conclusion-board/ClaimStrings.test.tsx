import { act, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Post } from "@/types/post";
import type { ProfileEvidence, ProfileItem } from "@/types/profile";

import { ClaimStrings } from "./ClaimStrings";

const makePost = (suffix: string, text: string): Post => ({
  post_id: `at://did:plc:test/app.bsky.feed.post/${suffix}`,
  text,
  created_at: "2026-10-20T08:31:00+09:00",
  images: [],
});

const posts = [
  makePost("bus", "家の前のバス停、千駄木三丁目から毎朝バスに乗って出勤。"),
  makePost("shelter", "近所の千駄木小学校が避難所になっているので、防災リュックを見直した。"),
  makePost("school", "娘の小学校のあおぞらフェスタ、今年は輪投げ係になった。"),
  makePost("sign", "門のところの避難所の看板、ちゃんと見たのは初めて。"),
];

const fromPost = (post: Post, source: ProfileEvidence["source"] = "post_text"): ProfileEvidence => ({
  post_id: post.post_id,
  clue_index: source === "clue" ? 0 : null,
  required: true,
  source,
});
const openData: ProfileEvidence = { post_id: null, clue_index: null, required: true, source: "open_data", excerpt: "出典：国土地理院" };

function claim(paths: ProfileEvidence[][]): ProfileItem {
  return {
    attribute: "residential_area",
    value: "文京区",
    confidence: 0.65,
    status: "weak",
    evidence: paths.flat(),
    evidence_paths: paths.map((evidence) => ({ evidence, confidence: 0.65, provenance: "combined_inference" })),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ClaimStrings", () => {
  it("draws a red string from the anchor post of each evidence path to the answer", () => {
    const { container } = render(
      <ClaimStrings
        claim={claim([
          [fromPost(posts[3], "clue"), fromPost(posts[1]), openData],
          [fromPost(posts[0]), openData],
          [fromPost(posts[2]), openData],
        ])}
        posts={posts}
      />,
    );

    const figure = screen.getByRole("figure", { name: "別々の 3 つの道筋が、同じ答え「文京区」を指す" });
    const cards = within(figure).getAllByRole("listitem");
    // 道筋ごとに、本人との関係が書かれた投稿（post_text）を1枚ずつ出す
    expect(cards.map((c) => c.textContent)).toEqual([
      expect.stringContaining("近所の千駄木小学校が避難所"),
      expect.stringContaining("家の前のバス停"),
      expect.stringContaining("娘の小学校のあおぞらフェスタ"),
    ]);
    const strings = [...container.querySelectorAll(".claim-string")];
    expect(strings).toHaveLength(3);
    // 1 本ずつ順に伸び、最後に答えの箱が弾む
    const delays = strings.map((s) => Number(/([\d.]+)s/.exec(s.getAttribute("style") ?? "")?.[1]));
    expect(delays).toEqual([...delays].sort((a, b) => a - b));
    const answer = within(figure).getByText("文京区");
    const answerDelay = Number(/([\d.]+)s/.exec(answer.getAttribute("style") ?? "")?.[1]);
    expect(answerDelay).toBeGreaterThan(delays[2]);
    expect(answerDelay + 0.6).toBeLessThanOrEqual(2.2);
  });

  it("does not draw anything for a single path", () => {
    const { container } = render(<ClaimStrings claim={claim([[fromPost(posts[0]), openData]])} posts={posts} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("does not count a path that points at no post of the account", () => {
    const { container } = render(<ClaimStrings claim={claim([[fromPost(posts[0])], [openData]])} posts={posts} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("holds the strings until the figure scrolls into view", () => {
    let callback: IntersectionObserverCallback = () => {};
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: IntersectionObserverCallback) {
          callback = cb;
        }
        observe() {}
        disconnect() {}
      },
    );
    render(<ClaimStrings claim={claim([[fromPost(posts[0])], [fromPost(posts[2])]])} posts={posts} />);
    const figure = screen.getByRole("figure");
    expect(figure).not.toHaveClass("in-view");

    act(() => callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
    expect(figure).toHaveClass("in-view");
  });
});
