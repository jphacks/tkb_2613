import { defineConfig, devices } from "playwright/test";

// 偽の X API での E2E（承認フラグをオンにしたこのテスト環境だけ）。本物の X には接続しない。
// 偽の X（127.0.0.1:4010）・api（127.0.0.1:8011）・画面（localhost:3100）を立てる。
// api は X_FAKE_API_BASE_URL が http の loopback で COOKIE_SECURE=0 のときだけ起動できる。
const WEB = "http://localhost:3100";
const API = "http://127.0.0.1:8011";
const FAKE_X = "http://127.0.0.1:4010";
const CLIENT_ID = "fake-x-client";
const CLIENT_SECRET = "fake-x-secret";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "x-fake-api.spec.ts",
  retries: 0,
  workers: 1,
  reporter: "list",
  use: { baseURL: WEB, ...devices["Desktop Chrome"], trace: "retain-on-failure" },
  webServer: [
    {
      command: "node e2e/fake-x/server.mjs",
      url: `${FAKE_X}/__health`,
      env: { FAKE_X_PORT: "4010", FAKE_X_CLIENT_ID: CLIENT_ID, FAKE_X_CLIENT_SECRET: CLIENT_SECRET },
      reuseExistingServer: false,
    },
    {
      command: "uv run uvicorn tkb_api.main:app --host 127.0.0.1 --port 8011",
      cwd: "..",
      url: `${API}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      // ログに callback のクエリが出ないことを CI で確かめるため、出力を残す
      stdout: "pipe",
      stderr: "pipe",
      env: {
        MOCK_MODE: "1",
        SHARE_ENABLED: "0",
        COOKIE_SECURE: "0",
        X_MOCK_MODE: "0",
        X_USE_CASE_APPROVED: "1",
        X_PAID_READS_APPROVED: "1",
        X_QUERY_LOGS_REDACTED: "1",
        X_CLIENT_ID: CLIENT_ID,
        X_CLIENT_SECRET: CLIENT_SECRET,
        X_PUBLIC_ORIGIN: WEB,
        X_CALLBACK_URL: `${WEB}/api/x/callback`,
        X_FAKE_API_BASE_URL: FAKE_X,
        X_MAX_POSTS: "5",
        X_DAILY_RESOURCE_LIMIT: "40",
      },
    },
    {
      command: "pnpm exec next dev --port 3100",
      url: `${WEB}/x`,
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
      env: { API_ORIGIN: API, API_INTERNAL_ORIGIN: API },
    },
  ],
});
