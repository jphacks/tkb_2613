import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { attributeLabel, messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import type { Post } from "@/types/post";
import type { ProfileCandidateSet } from "@/types/profile";

import { Reveal } from "./Reveal";

const t = messages.reveal;

const POST: Post = {
  post_id: "at://did:plc:xxxx/app.bsky.feed.post/1",
  text: "夜勤明けのラーメン",
  created_at: "2026-10-20T08:31:00+09:00",
  images: [{ index: 0, url: "https://cdn.bsky.app/img/a", alt: "", width: 1000, height: 500 }],
};

const TEXT_CLUE: Clue = {
  post_id: POST.post_id,
  image_index: null,
  type: "routine_text",
  value: "夜勤明け",
  region: null,
  confidence: 0.9,
  source: "text",
};

const PHOTO_CLUE: Clue = {
  post_id: POST.post_id,
  image_index: 0,
  type: "station_sign",
  value: "根x",
  region: [400, 200, 600, 300],
  confidence: 0.8,
  source: "vlm",
};

const CONCLUSION: Conclusion = {
  rule: "r",
  attribute: "routine",
  value: "夜勤のある仕事",
  clue_indices: [0],
  note: "",
};

function nameCandidateSet(attribute: "full_name" | "given_name" | "nickname", values: readonly string[]): ProfileCandidateSet {
  const assessment = {
    minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
    inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
    harm_prerequisites: [], harm_status: "unknown" as const,
  };
  const candidates = values.map((value, index) => {
    const evidence = [{ post_id: POST.post_id, clue_index: null, required: true, source: "profile_text" as const, excerpt: value }];
    return {
      rank: index + 1, value, confidence: 0.8 - index * 0.1, status: "found" as const,
      evidence, evidence_paths: [{ evidence, confidence: 0.8 - index * 0.1, provenance: "direct_disclosure" as const }],
      assessment, observed_at: null, counter_evidence: [],
    };
  });
  return {
    attribute, status: candidates.length > 1 ? "ambiguous" : "candidate", candidates, candidate_pool: candidates,
    reason: null, conflicting_evidence: [],
  };
}

/** jsdom は写真を読み込まないので、読み込みを手で終わらせられる代わりを置く */
class FakeImage {
  static last: FakeImage | null = null;
  static all: FakeImage[] = [];
  /** 作られた写真をすべて読み込み済みにする */
  static loadAll() {
    for (const img of FakeImage.all) img.onload?.();
  }
  onload: (() => void) | null = null;
  referrerPolicy = "";
  src = "";
  naturalWidth = 1000;
  naturalHeight = 500;
  constructor() {
    FakeImage.last = this;
    FakeImage.all.push(this);
  }
}

beforeEach(() => {
  FakeImage.last = null;
  FakeImage.all = [];
  vi.stubGlobal("Image", FakeImage);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Reveal", () => {
  it("puts its children right after the identity card, before the evidence", () => {
    render(
      <Reveal posts={[POST]} clues={[TEXT_CLUE, PHOTO_CLUE]} conclusions={[CONCLUSION]}>
        <p>消す投稿の要約</p>
      </Reveal>,
    );

    const summary = screen.getByText("消す投稿の要約");
    const evidence = screen.getByRole("list", { name: messages.reveal.evidenceLabel });
    expect(summary.compareDocumentPosition(evidence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("still shows its children when nothing was found", () => {
    render(<Reveal posts={[]} clues={[]} conclusions={[]}><p>消す投稿の要約</p></Reveal>);

    expect(screen.getByText("消す投稿の要約")).toBeInTheDocument();
  });

  it("shows the conclusions and the evidence, marking the ones used by a conclusion", () => {
    render(<Reveal posts={[POST]} clues={[TEXT_CLUE, PHOTO_CLUE]} conclusions={[CONCLUSION]} />);

    expect(screen.getByRole("heading", { name: t.heading })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: t.conclusionsLabel })).getByText("夜勤のある仕事")).toBeInTheDocument();

    const cards = within(screen.getByRole("list", { name: t.evidenceLabel })).getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    expect(screen.getByRole("article", { name: messages.identity.label }).compareDocumentPosition(cards[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(cards[0]).getByText("根x")).toBeInTheDocument();
    expect(within(cards[1]).getByText(t.used)).toBeInTheDocument();
    expect(within(cards[1]).getByText("夜勤明け", { selector: ".redaction-word" })).toBeInTheDocument();
  });

  it("hides the clue word in the post under a black bar that peels off after every card has landed", () => {
    const second: Clue = { ...TEXT_CLUE, type: "age_text", value: "ラーメン" };
    render(<Reveal posts={[{ ...POST, images: [] }]} clues={[TEXT_CLUE, second]} conclusions={[CONCLUSION]} />);

    const cards = within(screen.getByRole("list", { name: t.evidenceLabel })).getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    // 今までの <mark> の印は使わない
    expect(document.querySelector("blockquote mark")).toBeNull();
    const bars = cards.map((card) => card.querySelector(".redaction-bar") as HTMLElement);
    for (const bar of bars) {
      expect(bar).toHaveAttribute("aria-hidden", "true");
      // 言葉そのものは読み上げにも残す
      expect(bar.parentElement?.querySelector(".redaction-word")?.textContent).toBeTruthy();
    }
    // 2 枚目が叩きつけられ終わる（1.6 + 0.5 + 0.45 = 2.55 秒）まで待ち、上から順に 0.4 秒ずつずらしてはがす
    expect(bars[0].getAttribute("style")).toContain("2.55s");
    expect(bars[1].getAttribute("style")).toContain("2.95s");
    expect(bars[0].getAttribute("style")).toContain("var(--stage-pace, 1)");
  });

  it("stretches the gaps between the evidence cards by the presentation pace", () => {
    render(<Reveal posts={[POST]} clues={[TEXT_CLUE]} conclusions={[CONCLUSION]} />);

    const card = within(screen.getByRole("list", { name: t.evidenceLabel })).getAllByRole("listitem")[0];
    // 発表モード（html.stage）では --stage-pace が 1 より大きくなり、遅れが伸びる
    expect(card.getAttribute("style")).toContain("var(--stage-pace, 1)");
  });

  it("shows the clue as text until the full source photo has loaded", () => {
    render(<Reveal posts={[POST]} clues={[PHOTO_CLUE]} conclusions={[]} />);

    // 読み込むまでは、空の写真の枠を出さずに文字で見せる
    const evidence = screen.getByRole("list", { name: t.evidenceLabel });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(within(evidence).getByText("根x")).toBeInTheDocument();
    expect(FakeImage.last?.src).toBe(POST.images[0].url);
    expect(FakeImage.last?.referrerPolicy).toBe("no-referrer");

    act(() => FakeImage.loadAll());

    expect(
      screen.getByRole("img", { name: t.photoAlt(messages.clues.typeLabels.station_sign, "根x") }),
    ).toHaveAttribute("src", POST.images[0].url);
  });

  it("does not treat a raw written name as the account owner's name", () => {
    const name: Clue = { ...PHOTO_CLUE, type: "name_text", value: "はるき" };
    const blurred: Clue = { ...name, value: "xx はるき 様", confidence: 0.99 };
    render(<Reveal posts={[POST]} clues={[TEXT_CLUE, PHOTO_CLUE, blurred, name]} conclusions={[CONCLUSION]} />);

    const card = screen.getByRole("article", { name: messages.identity.label });
    expect(within(card).getByText(messages.identity.nameUnknown)).toBeInTheDocument();
    expect(within(card).queryByText("はるき")).not.toBeInTheDocument();
    // 推定の根拠（夜勤明け）は推定の行で見えるので、強い手がかりの行には出さない
    expect(within(card).getByRole("definition")).toHaveTextContent("根x");
    expect(within(card).getByText("夜勤のある仕事")).toBeInTheDocument();
    // 回る数字は飾りなので、読み上げ用の数字で確かめる
    expect(within(card).getByText("4", { selector: ".sr-only" })).toBeInTheDocument();
  });

  it("uses a single profile name candidate and labels its direct disclosure provenance", () => {
    render(<Reveal posts={[POST]} clues={[]} conclusions={[]} profileClaims={[nameCandidateSet("full_name", ["内藤大貴"])]} />);
    const card = screen.getByRole("article", { name: messages.identity.label });

    expect(within(card).getByText("内藤大貴")).toBeInTheDocument();
    expect(within(card).getByText("自分で直接公開")).toBeInTheDocument();
    expect(within(card).queryByText(messages.identity.nameUnknown)).not.toBeInTheDocument();
  });

  it("warns when a profile name candidate comes from a boarding pass", () => {
    const codeClue: Clue = { ...PHOTO_CLUE, type: "code", value: "PDF417: M1MASKED", source: "ocr" };
    const set = nameCandidateSet("full_name", ["KAKURE HARUKI"]);
    const evidence = [{ post_id: POST.post_id, clue_index: 0, required: true, source: "clue" as const }];
    const candidate = set.candidates[0];
    const boardingCandidate = {
      ...candidate,
      evidence,
      evidence_paths: [{ evidence, confidence: candidate.confidence, provenance: "combined_inference" as const }],
    };
    render(<Reveal posts={[POST]} clues={[codeClue]} conclusions={[]} profileClaims={[{
      ...set, candidates: [boardingCandidate], candidate_pool: [boardingCandidate],
    }]} />);
    expect(screen.getByRole("note")).toHaveTextContent("搭乗券の旅客名です。投稿者本人とは確認できません。");
  });

  it("does not promote rank one when multiple profile name candidates exist", () => {
    render(<Reveal posts={[POST]} clues={[]} conclusions={[]} profileClaims={[nameCandidateSet("full_name", ["内藤大貴", "佐藤はるき"])]} />);
    const card = screen.getByRole("article", { name: messages.identity.label });

    expect(within(card).getByText(messages.identity.nameMultiple)).toBeInTheDocument();
    expect(within(card).queryByText("内藤大貴")).not.toBeInTheDocument();
    expect(within(card).queryByText("自分で直接公開")).not.toBeInTheDocument();
  });

  it("prefers one full-name candidate over a separate given-name candidate", () => {
    render(<Reveal posts={[POST]} clues={[]} conclusions={[]} profileClaims={[
      nameCandidateSet("full_name", ["内藤大貴"]),
      nameCandidateSet("given_name", ["大貴"]),
    ]} />);
    const card = screen.getByRole("article", { name: messages.identity.label });

    expect(within(card).getByText("内藤大貴")).toBeInTheDocument();
    expect(within(card).queryByText("大貴")).not.toBeInTheDocument();
    expect(within(card).getByText("自分で直接公開")).toBeInTheDocument();
  });

  it("shows a confident face from the posts in the photo frame once the photo has loaded", () => {
    const face: Clue = { ...PHOTO_CLUE, type: "face", value: "1人", confidence: 0.9 };
    render(<Reveal posts={[POST]} clues={[face]} conclusions={[CONCLUSION]} />);
    const card = screen.getByRole("article", { name: messages.identity.label });

    // 読み込むまでは人影のまま
    expect(within(card).getByText(messages.identity.silhouette)).toBeInTheDocument();

    act(() => FakeImage.loadAll());

    expect(within(card).getByRole("img", { name: messages.identity.faceAlt })).toHaveAttribute("src", POST.images[0].url);
    expect(within(card).getByText(messages.identity.faceCaption)).toBeInTheDocument();
  });

  it("keeps the silhouette when the face is not confident enough", () => {
    const face: Clue = { ...PHOTO_CLUE, type: "face", value: "1人", confidence: 0.5 };
    render(<Reveal posts={[POST]} clues={[face]} conclusions={[CONCLUSION]} />);
    const card = screen.getByRole("article", { name: messages.identity.label });

    act(() => FakeImage.loadAll());

    expect(within(card).queryByRole("img", { name: messages.identity.faceAlt })).not.toBeInTheDocument();
    expect(within(card).getByText(messages.identity.silhouette)).toBeInTheDocument();
  });

  it("says the name is unknown when no name was written anywhere", () => {
    render(<Reveal posts={[POST]} clues={[TEXT_CLUE]} conclusions={[CONCLUSION]} />);

    expect(screen.getByText(messages.identity.nameUnknown)).toBeInTheDocument();
  });

  it("shows the entire source photo and a red mark for an address", () => {
    const address: Clue = { ...PHOTO_CLUE, type: "address_text", value: "文京区弥生二丁目xx" };
    render(<Reveal posts={[POST]} clues={[address]} conclusions={[]} />);

    act(() => FakeImage.loadAll());

    const evidence = screen.getByRole("list", { name: t.evidenceLabel });
    const photo = within(evidence).getByRole("img", { name: t.photoAlt(messages.clues.typeLabels.address_text, address.value) });
    expect(photo).toHaveAttribute("src", POST.images[0].url);
    expect(within(evidence).getByText(t.originalPhoto)).toBeInTheDocument();
    expect(photo.parentElement?.querySelector(".reveal-mark")).toBeInTheDocument();
    expect(within(evidence).getByText(address.value)).toBeInTheDocument();
  });

  it("uses the loaded photo dimensions for the red mark", () => {
    const postWithDifferentMetadata = { ...POST, images: [{ ...POST.images[0], width: 500, height: 250 }] };
    render(<Reveal posts={[postWithDifferentMetadata]} clues={[PHOTO_CLUE]} conclusions={[]} />);
    act(() => FakeImage.loadAll());

    const photo = screen.getByRole("img", { name: t.photoAlt(messages.clues.typeLabels.station_sign, PHOTO_CLUE.value) });
    const mark = photo.parentElement?.querySelector(".reveal-mark") as HTMLElement;
    expect(mark.style.left).toBe("40%");
    expect(mark.style.top).toBe("40%");
  });

  it("shows nothing when nothing was found", () => {
    const { container } = render(<Reveal posts={[POST]} clues={[]} conclusions={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows non-name catalog-driven profile claims and marks their clue_index evidence as used", () => {
    const assessment = {
      minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
      inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
      harm_prerequisites: [], harm_status: "unknown" as const,
    };
    const evidence = [{ post_id: POST.post_id, clue_index: 0, required: true, source: "post_text" as const, excerpt: "夜勤明け" }];
    const claimSet: ProfileCandidateSet = {
      attribute: "routine",
      status: "candidate",
      candidates: [{
        rank: 1, value: "夜勤シフト", confidence: 0.7, status: "weak",
        evidence, evidence_paths: [{ evidence, confidence: 0.7, provenance: "direct_disclosure" }],
        assessment, observed_at: null, counter_evidence: [],
      }],
      candidate_pool: [],
      reason: null,
      conflicting_evidence: [],
    };
    render(<Reveal posts={[POST]} clues={[TEXT_CLUE]} conclusions={[]} profileClaims={[claimSet]} />);

    expect(within(screen.getByRole("list", { name: t.conclusionsLabel })).getByText(attributeLabel("routine"))).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: t.conclusionsLabel })).getByText("夜勤シフト")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: t.evidenceLabel })).getByText(t.used)).toBeInTheDocument();
  });
});
