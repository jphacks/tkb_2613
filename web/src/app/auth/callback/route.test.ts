// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";

import { GET } from "./route";
import { getOAuthClient, pendingStateMatches } from "@/lib/server/oauth";

vi.mock("next/server", async (importOriginal) => ({
  ...await importOriginal<typeof import("next/server")>(),
  connection: vi.fn(async () => {}),
}));

vi.mock("@atproto/api", () => ({
  Agent: class {
    app = { bsky: { actor: { getProfile: async () => ({ data: { did: "did:plc:alice", handle: "alice.bsky.social" } }) } } };
  },
}));

vi.mock("@/lib/server/oauth", () => ({
  authMode: () => "oauth",
  forgetOAuthSession: vi.fn(),
  getOAuthClient: vi.fn(() => ({ callback: async () => ({ session: { did: "did:plc:alice" }, state: "browser-state" }) })),
  pendingStateMatches: vi.fn(() => true),
  publicUrl: () => "https://example.com",
  resetOAuthExpiry: vi.fn(),
  START_COOKIE: "tkb_oauth_start",
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("keeps the session cookie when removing the OAuth start cookie", async () => {
  vi.stubEnv("INTERNAL_AUTH_SECRET", "test-only-secret");
  const fetchMock = vi.fn(async () => new Response("{}", {
    headers: { "Set-Cookie": "tkb_session=test-session; Max-Age=1800; Path=/; HttpOnly; SameSite=Lax; Secure" },
  }));
  vi.stubGlobal("fetch", fetchMock);

  const response = await GET(new NextRequest("https://example.com/auth/callback?state=sdk-state&code=test-code", {
    headers: { Cookie: "tkb_oauth_start=browser-state" },
  }));

  expect(pendingStateMatches).toHaveBeenCalledOnce();
  expect(getOAuthClient).toHaveBeenCalledOnce();
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(response.status).toBe(307);
  expect(response.headers.get("Location")).toBe("https://example.com/");
  expect(response.headers.get("Cache-Control")).toBe("no-store");
  const cookies = response.headers.getSetCookie();
  expect(cookies).toHaveLength(2);
  expect(cookies).toContainEqual(expect.stringContaining("tkb_session=test-session;"));
  expect(cookies).toContainEqual(expect.stringContaining("tkb_oauth_start=;"));
});
