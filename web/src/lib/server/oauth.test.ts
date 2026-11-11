// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST as deletePost } from "@/app/%5F%5Finternal/oauth/delete/route";
import {
  OAUTH_SCOPE, oauthTtlSeconds, pendingStateMatches, resetOAuthExpiry, validInternalSecret,
} from "@/lib/server/oauth";

const memory = globalThis as typeof globalThis & {
  tkbOAuthStates?: Map<string, { value: { appState: string }; expires: number }>;
  tkbOAuthSessions?: Map<string, { value: unknown; expires: number }>;
  tkbOAuthExpiries?: Map<string, number>;
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.useRealTimers();
  memory.tkbOAuthStates?.clear();
  memory.tkbOAuthSessions?.clear();
  memory.tkbOAuthExpiries?.clear();
});

describe("OAuth session lifetime", () => {
  it("follows SESSION_TTL_MINUTES like the api", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-15T10:00:00Z"));
    vi.stubEnv("SESSION_TTL_MINUTES", "60");
    memory.tkbOAuthSessions?.set("did:plc:alice", { value: {}, expires: 0 });

    resetOAuthExpiry("did:plc:alice");

    const expected = Date.now() + 60 * 60 * 1000;
    expect(oauthTtlSeconds()).toBe(60 * 60);
    expect(memory.tkbOAuthExpiries?.get("did:plc:alice")).toBe(expected);
    expect(memory.tkbOAuthSessions?.get("did:plc:alice")?.expires).toBe(expected);
  });

  it("falls back to 30 minutes when unset or invalid", () => {
    vi.stubEnv("SESSION_TTL_MINUTES", undefined);
    expect(oauthTtlSeconds()).toBe(30 * 60);
    for (const value of ["", "0", "-5", "1.5", "abc"]) {
      vi.stubEnv("SESSION_TTL_MINUTES", value);
      expect(oauthTtlSeconds()).toBe(30 * 60);
    }
  });
});

describe("OAuth internal boundary", () => {
  it("requires both SDK state and the starting browser cookie", () => {
    memory.tkbOAuthStates?.set("sdk-state", {
      value: { appState: "browser-state" }, expires: Date.now() + 1000,
    });
    expect(pendingStateMatches("sdk-state", "browser-state")).toBe(true);
    expect(pendingStateMatches("sdk-state", "another-state")).toBe(false);
    expect(pendingStateMatches("unknown", "browser-state")).toBe(false);
    memory.tkbOAuthStates?.set("old", {
      value: { appState: "browser-state" }, expires: Date.now() - 1,
    });
    expect(pendingStateMatches("old", "browser-state")).toBe(false);
  });

  it("rejects missing or incorrect internal credentials", () => {
    vi.stubEnv("INTERNAL_AUTH_SECRET", "test-only-secret");
    expect(validInternalSecret(new Request("http://web:3000"))).toBe(false);
    expect(validInternalSecret(new Request("http://web:3000", { headers: { "X-Internal-Auth": "wrong" } }))).toBe(false);
    expect(validInternalSecret(new Request("http://web:3000", { headers: { "X-Internal-Auth": "test-only-secret" } }))).toBe(true);
  });

  it("denies a post from another DID before touching the SDK", async () => {
    vi.stubEnv("AUTH_MODE", "oauth");
    vi.stubEnv("INTERNAL_AUTH_SECRET", "test-only-secret");
    const response = await deletePost(new Request("http://web:3000/__internal/oauth/delete", {
      method: "POST", headers: { "X-Internal-Auth": "test-only-secret" },
      body: JSON.stringify({ did: "did:plc:alice", post_id: "at://did:plc:bob/app.bsky.feed.post/3kabc" }),
    }));
    expect(response.status).toBe(403);
    expect(OAUTH_SCOPE).toBe("atproto repo:app.bsky.feed.post?action=delete");
  });
});
