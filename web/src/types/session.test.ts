import { describe, expect, it } from "vitest";

import { isSessionResponse, normalizeHandle } from "./session";

describe("normalizeHandle", () => {
  it("removes spaces and a leading @", () => {
    expect(normalizeHandle("  @alice.bsky.social ")).toBe("alice.bsky.social");
    expect(normalizeHandle("alice.bsky.social")).toBe("alice.bsky.social");
  });
});

describe("isSessionResponse", () => {
  it("checks the shape", () => {
    expect(isSessionResponse({ handle: "alice.bsky.social", did: "did:plc:abc" })).toBe(true);
    expect(isSessionResponse({ handle: "", did: "did:plc:abc" })).toBe(false);
    expect(isSessionResponse({ handle: "a", did: "plc:abc" })).toBe(false);
    expect(isSessionResponse({ handle: "a" })).toBe(false);
    expect(isSessionResponse(null)).toBe(false);
  });
});
