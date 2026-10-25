import { describe, expect, it } from "vitest";

import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import type { Post } from "@/types/post";

import { cropStyle, FACE_MIN_CONFIDENCE, pickFace, pickName, pickReveal } from "./reveal";

const POST: Post = {
  post_id: "at://did:plc:xxxx/app.bsky.feed.post/1",
  text: "夜勤明けのラーメン",
  created_at: "2026-10-20T08:31:00+09:00",
  images: [{ index: 0, url: "https://cdn.bsky.app/img/a", alt: "", width: 1000, height: 500 }],
};

function clue(type: Clue["type"], value: string, extra: Partial<Clue> = {}): Clue {
  return {
    post_id: POST.post_id,
    image_index: null,
    type,
    value,
    region: null,
    confidence: 0.5,
    source: "text",
    ...extra,
  };
}

function conclusion(clue_indices: number[]): Conclusion {
  return { rule: "r", attribute: "routine", value: "v", clue_indices, note: "" };
}

describe("pickReveal", () => {
  it("puts clues used by a conclusion first, then the more dangerous types", () => {
    const clues = [clue("routine_text", "夜勤明け"), clue("shop", "赤札堂"), clue("name_text", "はるき")];

    const picked = pickReveal([POST], clues, [conclusion([0])]);

    expect(picked.map((p) => p.clue.value)).toEqual(["夜勤明け", "はるき", "赤札堂"]);
    expect(picked[0].used).toBe(true);
    expect(picked[1].used).toBe(false);
  });

  it("merges the same type and value into one card and respects the limit", () => {
    const clues = [clue("routine_text", "ジム"), clue("routine_text", "ジム"), clue("shop", "a"), clue("shop", "b")];

    expect(pickReveal([POST], clues, [], 2).map((p) => p.clue.value)).toEqual(["a", "b"]);
    expect(pickReveal([POST], clues, [])).toHaveLength(3);
  });

  it("attaches the photo for photo clues and skips clues whose post is missing", () => {
    const clues = [
      clue("station_sign", "根x", { image_index: 0, region: [0, 0, 10, 10], source: "vlm" }),
      clue("name_text", "x", { post_id: "at://other" }),
    ];

    const picked = pickReveal([POST], clues, []);

    expect(picked).toHaveLength(1);
    expect(picked[0].image).toBe(POST.images[0]);
  });
});

describe("cropStyle", () => {
  it("crops around the region with a margin and places the mark inside", () => {
    const crop = cropStyle([400, 200, 600, 300], { width: 1000, height: 500 }, 0.5);

    // 余白込みで x 300〜700、y 150〜350 を切り抜く
    expect(crop.aspectRatio).toBe("400 / 200");
    expect(crop.image).toEqual({ width: "250%", height: "250%", left: "-75%", top: "-75%" });
    expect(crop.mark).toEqual({ left: "25%", top: "25%", width: "50%", height: "50%" });
  });

  it("does not crop outside the photo", () => {
    const crop = cropStyle([0, 0, 100, 100], { width: 100, height: 100 });

    expect(crop.image).toEqual({ width: "100%", height: "100%", left: "0%", top: "0%" });
    expect(crop.mark).toEqual({ left: "0%", top: "0%", width: "100%", height: "100%" });
  });
});

describe("pickName", () => {
  it("prefers the name with fewer unreadable letters, then the more confident one", () => {
    const clues = [
      clue("name_text", "xx はるき 様", { confidence: 0.99 }),
      clue("name_text", "はるき", { confidence: 0.6 }),
      clue("name_text", "はるか", { confidence: 0.5 }),
    ];

    expect(pickName(clues)).toBe("はるき");
    expect(pickName([clue("shop", "赤札堂")])).toBeNull();
  });
});

describe("pickFace", () => {
  const face = (confidence: number, extra: Partial<Clue> = {}) =>
    clue("face", "1人", { image_index: 0, region: [10, 10, 50, 50], source: "vlm", confidence, ...extra });

  it("picks the most confident face at or above the threshold", () => {
    const best = face(0.95);

    const picked = pickFace([POST], [face(FACE_MIN_CONFIDENCE), best]);

    expect(picked?.clue).toBe(best);
    expect(picked?.image).toBe(POST.images[0]);
  });

  it("does not show a face below the threshold, without a position, or without the photo", () => {
    expect(pickFace([POST], [face(FACE_MIN_CONFIDENCE - 0.01)])).toBeNull();
    expect(pickFace([POST], [face(0.95, { region: null })])).toBeNull();
    expect(pickFace([POST], [face(0.95, { image_index: 3 })])).toBeNull();
    expect(pickFace([POST], [face(0.95, { post_id: "at://other" })])).toBeNull();
  });
});
