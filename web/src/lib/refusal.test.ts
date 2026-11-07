import { describe, expect, it } from "vitest";

import { formatOpening, readRefusal, refusalMessage, toRefusal } from "./refusal";

describe("formatOpening", () => {
  it("shows the next opening in Japan time", () => {
    expect(formatOpening("2026-11-16T20:00:00+09:00")).toBe("11月16日の20:00");
    // UTC で書かれていても日本時間で出す
    expect(formatOpening("2026-11-17T11:05:00Z")).toBe("11月17日の20:05");
  });

  it("returns null for a time it cannot read", () => {
    expect(formatOpening("not a date")).toBeNull();
  });
});

describe("toRefusal", () => {
  it("reads the code and its details", () => {
    expect(
      toRefusal({ detail: { code: "closed", message: "公開時間外です", next_open: "2026-11-16T20:00:00+09:00" } }),
    ).toEqual({ code: "closed", next_open: "2026-11-16T20:00:00+09:00", limit: undefined });
    expect(toRefusal({ detail: { code: "daily_limit", message: "…", limit: 3 } })).toMatchObject({
      code: "daily_limit",
      limit: 3,
    });
  });

  it.each([
    undefined,
    { detail: "ログインしてください" }, // 文字列だけの detail（今までの形）
    { detail: [{ loc: ["body"], msg: "…", type: "…" }] }, // 422
    { detail: { code: "unknown_reason" } },
    { detail: { message: "コードがない" } },
  ])("ignores other shapes: %j", (body) => {
    expect(toRefusal(body)).toBeNull();
  });

  it("drops details of the wrong type", () => {
    expect(toRefusal({ detail: { code: "daily_limit", limit: "3" } })).toMatchObject({ limit: undefined });
    expect(toRefusal({ detail: { code: "closed", next_open: 123 } })).toMatchObject({ next_open: null });
  });
});

describe("readRefusal", () => {
  it("reads a JSON body and returns null for other bodies", async () => {
    const json = new Response(JSON.stringify({ detail: { code: "busy", message: "混雑しています" } }));
    expect(await readRefusal(json)).toMatchObject({ code: "busy" });
    expect(await readRefusal(new Response("Bad Gateway"))).toBeNull();
  });
});

describe("refusalMessage", () => {
  it("tells when the service opens next", () => {
    expect(refusalMessage({ code: "closed", next_open: "2026-11-16T20:00:00+09:00" })).toBe(
      "公開時間外です。次は11月16日の20:00からです",
    );
  });

  it("says the service ended when there is no next opening", () => {
    expect(refusalMessage({ code: "closed", next_open: null })).toBe("公開は終了しました。ありがとうございました");
  });

  it("explains each reason", () => {
    expect(refusalMessage({ code: "daily_limit", limit: 3 })).toContain("今日の診断は 3 回までです");
    expect(refusalMessage({ code: "daily_limit" })).toContain("今日の診断回数の上限に達しました");
    expect(refusalMessage({ code: "busy" })).toContain("混雑しています");
    expect(refusalMessage({ code: "already_running" })).toContain("このアカウントの別の診断が進んでいます");
    expect(refusalMessage({ code: "model_unavailable" })).toContain("準備中");
    expect(refusalMessage({ code: "bluesky_busy" })).toContain("Bluesky が混雑しています");
  });
});
