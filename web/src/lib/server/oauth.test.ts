// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST as deletePost } from "@/app/__internal/oauth/delete/route";
import { OAUTH_SCOPE, pendingStateMatches, validInternalSecret } from "@/lib/server/oauth";

const memory = globalThis as typeof globalThis & {
  tkbOAuthStates?: Map<string, { value: { appState: string }; expires: number }>;
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.useRealTimers();
  memory.tkbOAuthStates?.clear();
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
