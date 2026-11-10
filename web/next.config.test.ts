import { afterEach, describe, expect, it, vi } from "vitest";

import nextConfig, { CONTENT_SECURITY_POLICY } from "./next.config";

async function apiRewrite() {
  const rewrites = await nextConfig.rewrites?.();
  expect(Array.isArray(rewrites)).toBe(true);
  return rewrites;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("rewrites", () => {
  it("forwards /api to the local api by default", async () => {
    vi.stubEnv("API_ORIGIN", undefined);

    expect(await apiRewrite()).toEqual([
      { source: "/api/:path*", destination: "http://localhost:8001/api/:path*" },
    ]);
  });

  it("forwards /api to API_ORIGIN, ignoring a trailing slash", async () => {
    vi.stubEnv("API_ORIGIN", "https://mouiikai.example.ts.net/");

    expect(await apiRewrite()).toEqual([
      { source: "/api/:path*", destination: "https://mouiikai.example.ts.net/api/:path*" },
    ]);
  });
});

describe("security headers", () => {
  it("does not advertise the framework", () => {
    expect(nextConfig.poweredByHeader).toBe(false);
  });

  it("sends a CSP that forbids framing, plugins and base rewriting on every path", async () => {
    expect(await nextConfig.headers?.()).toEqual([
      { source: "/:path*", headers: [{ key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY }] },
    ]);
    expect(CONTENT_SECURITY_POLICY).toContain("frame-ancestors 'none'");
    expect(CONTENT_SECURITY_POLICY).toContain("object-src 'none'");
    expect(CONTENT_SECURITY_POLICY).toContain("base-uri 'none'");
  });
});
