import { defineConfig, devices } from "playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // 偽の X API の E2E は playwright.fake-x.config.ts で専用のサーバーを立てて動かす
  testIgnore: "x-fake-api.spec.ts",
  retries: 0,
  reporter: "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    ...devices["Desktop Chrome"],
    trace: "retain-on-failure",
  },
});
