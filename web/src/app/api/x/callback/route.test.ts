// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";

import { GET } from "./route";

vi.mock("next/server", async (importOriginal) => ({
  ...await importOriginal<typeof import("next/server")>(),
  connection: vi.fn(async () => {}),
}));

const CODE = "SyntheticCode4f2a";
const STATE = "SyntheticState9c1d";
const CALLBACK = `https://example.com/api/x/callback?code=${CODE}&state=${STATE}`;

function spyConsole() {
  return (["log", "info", "warn", "error", "debug"] as const).map((name) =>
    vi.spyOn(console, name).mockImplementation(() => {}));
}

function logged(spies: ReturnType<typeof spyConsole>): string {
  return spies.flatMap((spy) => spy.mock.calls.flat()).map(String).join("\n");
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("relays the callback to the api with cookies and returns its redirect and cookies", async () => {
  vi.stubEnv("API_INTERNAL_ORIGIN", "http://api.internal:8001/");
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => {
    const headers = new Headers({ Location: "/x" });
    headers.append("Set-Cookie", "x_tkb_session=s; Path=/api/x; HttpOnly; SameSite=Lax");
    headers.append("Set-Cookie", "x_oauth_start=; Max-Age=0; Path=/api/x");
    return new Response(null, { status: 303, headers });
  });
  vi.stubGlobal("fetch", fetchMock);
  const spies = spyConsole();

  const response = await GET(new NextRequest(CALLBACK, { headers: { cookie: "x_oauth_start=nonce" } }));

  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe(`http://api.internal:8001/api/x/callback?code=${CODE}&state=${STATE}`);
  expect(new Headers(init?.headers).get("cookie")).toBe("x_oauth_start=nonce");
  expect(init?.redirect).toBe("manual");
  expect(response.status).toBe(303);
  expect(response.headers.get("location")).toBe("/x");
  expect(response.headers.getSetCookie()).toHaveLength(2);
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(logged(spies)).not.toMatch(new RegExp(`${CODE}|${STATE}`));
});

it("passes api errors through without logging the query", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "X の認証状態が一致しません" }, { status: 400 })));
  const spies = spyConsole();

  const response = await GET(new NextRequest(CALLBACK));

  expect(response.status).toBe(400);
  expect(await response.json()).toEqual({ detail: "X の認証状態が一致しません" });
  expect(logged(spies)).not.toMatch(new RegExp(`${CODE}|${STATE}`));
});

it("answers 502 without logging the query when the api is unreachable", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => {
    throw new TypeError(`fetch failed: http://api/api/x/callback?code=${CODE}&state=${STATE}`);
  }));
  const spies = spyConsole();

  const response = await GET(new NextRequest(CALLBACK));

  expect(response.status).toBe(502);
  expect(JSON.stringify(await response.json())).not.toMatch(new RegExp(`${CODE}|${STATE}`));
  expect(logged(spies)).not.toMatch(new RegExp(`${CODE}|${STATE}`));
});
