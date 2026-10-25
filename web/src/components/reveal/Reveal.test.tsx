import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import type { Post } from "@/types/post";

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
  it("shows the conclusions and the evidence, marking the ones used by a conclusion", () => {
    render(<Reveal posts={[POST]} clues={[TEXT_CLUE, PHOTO_CLUE]} conclusions={[CONCLUSION]} />);

    expect(screen.getByRole("heading", { name: t.heading })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: t.conclusionsLabel })).getByText("夜勤のある仕事")).toBeInTheDocument();

    const cards = within(screen.getByRole("list", { name: t.evidenceLabel })).getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText(t.used)).toBeInTheDocument();
    expect(within(cards[0]).getByText("夜勤明け", { selector: "mark" })).toBeInTheDocument();
    expect(within(cards[1]).queryByText(t.used)).not.toBeInTheDocument();
  });

  it("shows the clue as text until the photo has loaded, then crops the photo around it", () => {
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

  it("shows the identity card with the written name, the strong clues and the clue count", () => {
    const name: Clue = { ...PHOTO_CLUE, type: "name_text", value: "はるき" };
    const blurred: Clue = { ...name, value: "xx はるき 様", confidence: 0.99 };
    render(<Reveal posts={[POST]} clues={[TEXT_CLUE, PHOTO_CLUE, blurred, name]} conclusions={[CONCLUSION]} />);

    const card = screen.getByRole("article", { name: messages.identity.label });
    // 読めない文字の少ない名前を選ぶ
    expect(within(card).getByText("はるき")).toBeInTheDocument();
    // 推定の根拠（夜勤明け）は推定の行で見えるので、強い手がかりの行には出さない
    expect(within(card).getByRole("definition")).toHaveTextContent("根x");
    expect(within(card).getByText("夜勤のある仕事")).toBeInTheDocument();
    // 回る数字は飾りなので、読み上げ用の数字で確かめる
    expect(within(card).getByText("4", { selector: ".sr-only" })).toBeInTheDocument();
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

  it("shows an address as text instead of cropping the photo", () => {
    const address: Clue = { ...PHOTO_CLUE, type: "address_text", value: "文京区弥生二丁目xx" };
    render(<Reveal posts={[POST]} clues={[address]} conclusions={[]} />);

    expect(FakeImage.last).toBeNull();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: t.evidenceLabel })).getByText("文京区弥生二丁目xx")).toBeInTheDocument();
  });

  it("shows nothing when nothing was found", () => {
    const { container } = render(<Reveal posts={[POST]} clues={[]} conclusions={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
