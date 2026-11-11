// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST as deletePost } from "@/app/%5F%5Finternal/oauth/delete/route";
import { POST as dropSession } from "@/app/%5F%5Finternal/oauth/drop/route";
import {
  OAUTH_SCOPE, oauthTtlSeconds, pendingStateMatches, resetOAuthExpiry, revokeOAuthSession, validInternalSecret,
} from "@/lib/server/oauth";

const memory = globalThis as typeof globalThis & {
  tkbOAuthStates?: Map<string, { value: { appState: string }; expires: number }>;
  tkbOAuthSessions?: Map<string, { value: unknown; expires: number }>;
  tkbOAuthExpiries?: Map<string, number>;
  tkbOAuthRevoking?: Set<string>;
  tkbOAuthClient?: unknown;
};

const ALICE = "did:plc:alice";

/** SDK の代わり。revoke の中で、失効の処理中の印が付いているかも記録する */
function fakeClient(revoke: (did: string) => Promise<void> = async () => {}) {
  const calls: { did: string; revoking: boolean }[] = [];
  memory.tkbOAuthClient = {
    revoke: async (did: string) => {
      calls.push({ did, revoking: memory.tkbOAuthRevoking?.has(did) ?? false });
      await revoke(did);
    },
  };
  return calls;
}

function drop(did: string): Promise<Response> {
  return dropSession(new Request("http://web:3000/__internal/oauth/drop", {
    method: "POST", headers: { "X-Internal-Auth": "test-only-secret" }, body: JSON.stringify({ did }),
  }));
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.useRealTimers();
  memory.tkbOAuthStates?.clear();
  memory.tkbOAuthSessions?.clear();
  memory.tkbOAuthExpiries?.clear();
  memory.tkbOAuthRevoking?.clear();
  memory.tkbOAuthClient = undefined;
});

describe("OAuth token revocation", () => {
  it("revokes the token on logout, then forgets the session", async () => {
    vi.stubEnv("INTERNAL_AUTH_SECRET", "test-only-secret");
    const calls = fakeClient();
    memory.tkbOAuthSessions?.set(ALICE, { value: {}, expires: Date.now() + 60_000 });

    const response = await drop(ALICE);

    expect(response.status).toBe(204);
    expect(calls).toEqual([{ did: ALICE, revoking: true }]);
    expect(memory.tkbOAuthSessions?.has(ALICE)).toBe(false);
    expect(memory.tkbOAuthRevoking?.size).toBe(0);
  });

  it("still logs out and forgets the session when revocation fails", async () => {
    vi.stubEnv("INTERNAL_AUTH_SECRET", "test-only-secret");
    fakeClient(async () => {
      throw new Error("authorization server unreachable");
    });
    memory.tkbOAuthSessions?.set(ALICE, { value: {}, expires: Date.now() + 60_000 });
    memory.tkbOAuthExpiries?.set(ALICE, Date.now() + 60_000);

    const response = await drop(ALICE);

    expect(response.status).toBe(204);
    expect(memory.tkbOAuthSessions?.has(ALICE)).toBe(false);
    expect(memory.tkbOAuthExpiries?.has(ALICE)).toBe(false);
  });

  it("does not revoke without the internal secret", async () => {
    vi.stubEnv("INTERNAL_AUTH_SECRET", "test-only-secret");
    const calls = fakeClient();
    const response = await dropSession(new Request("http://web:3000/__internal/oauth/drop", {
      method: "POST", body: JSON.stringify({ did: ALICE }),
    }));
    expect(response.status).toBe(403);
    expect(calls).toEqual([]);
  });

  it("revokes the token when the session lifetime ends", async () => {
    vi.useFakeTimers();
    vi.stubEnv("SESSION_TTL_MINUTES", "1");
    const calls = fakeClient();
    memory.tkbOAuthSessions?.set(ALICE, { value: {}, expires: 0 });
    resetOAuthExpiry(ALICE);

    await vi.advanceTimersByTimeAsync(59_000);
    expect(calls).toEqual([]);
    await vi.advanceTimersByTimeAsync(1_000);

    expect(calls).toEqual([{ did: ALICE, revoking: true }]);
    expect(memory.tkbOAuthSessions?.has(ALICE)).toBe(false);
  });

  it("does not revoke a newer login when an older lifetime ends", async () => {
    vi.useFakeTimers();
    vi.stubEnv("SESSION_TTL_MINUTES", "1");
    const calls = fakeClient();
    memory.tkbOAuthSessions?.set(ALICE, { value: {}, expires: 0 });
    resetOAuthExpiry(ALICE);
    await vi.advanceTimersByTimeAsync(30_000);
    resetOAuthExpiry(ALICE); // ログインし直した

    await vi.advanceTimersByTimeAsync(30_000);
    expect(calls).toEqual([]);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(calls).toEqual([{ did: ALICE, revoking: true }]);
  });

  it("never throws from revokeOAuthSession", async () => {
    fakeClient(async () => {
      throw new Error("x");
    });
    await expect(revokeOAuthSession(ALICE)).resolves.toBeUndefined();
  });
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
