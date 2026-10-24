import { afterEach, describe, expect, it, vi } from "vitest";

import nextConfig from "./next.config";

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
