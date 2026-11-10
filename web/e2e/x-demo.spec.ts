import { expect, test } from "playwright/test";

test("合成X投稿を診断し、根拠を見て仮除外・再診断する", async ({ page }) => {
  await page.goto("/x");
  await expect(page.getByRole("heading", { name: "Xで、みーつけた" })).toBeVisible();
  await page.getByRole("checkbox", { name: /自分の投稿を診断し/ }).check();
  await page.getByRole("button", { name: "架空のX投稿で試す" }).click();
  await expect(page.getByText("架空のXアカウント")).toBeVisible();
  await page.getByRole("button", { name: "診断する" }).click();
  await expect(page.getByText("診断結果", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "診断した投稿" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "推定の根拠投稿" })).toBeVisible();
  await expect(page.getByText(/投稿 x:9001/)).toBeVisible();
  await expect(page.getByText(/根拠「毎週火曜はジム」/)).toBeVisible();

  await page.getByRole("checkbox", { name: "仮除外する" }).first().check();
  await page.getByRole("button", { name: "仮除外を試す" }).click();
  await expect(page.getByRole("status")).toContainText("仮除外で不明になる項目");
  await page.getByRole("button", { name: "選択した投稿を除いて再診断" }).click();
  await expect(page.getByText("仮除外後の再診断")).toBeVisible();
  await page.getByRole("button", { name: "全投稿の結果に戻す" }).click();
  await expect(page.getByText("診断結果", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "ログアウト" }).click();
  await expect(page.getByRole("button", { name: "架空のX投稿で試す" })).toBeVisible();
});

test("X OAuthの開始先とPKCE導線を確認する。Xには接続しない", async ({ page }) => {
  await page.route("**/api/x/config", (route) => route.fulfill({
    json: { mock_enabled: false, gpu_demo_enabled: false, live_enabled: true, max_posts: 30 },
  }));
  await page.route(/\/api\/x\/session$/, (route) => route.fulfill({ status: 401, json: {} }));
  await page.route("**/api/x/start", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ consent: true });
    await route.fulfill({ json: { authorize_url: "https://x.com/i/oauth2/authorize?response_type=code&state=synthetic&code_challenge=synthetic&code_challenge_method=S256" } });
  });
  await page.route("https://x.com/i/oauth2/authorize**", (route) => route.fulfill({
    contentType: "text/html; charset=utf-8", body: "<title>合成OAuth画面</title><h1>合成OAuth画面</h1>",
  }));
  await page.goto("/x");
  await page.getByRole("checkbox", { name: /自分の投稿を診断し/ }).check();
  await page.getByRole("button", { name: "Xでログイン" }).click();
  await expect(page.getByRole("heading", { name: "合成OAuth画面" })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("code_challenge_method")).toBe("S256");
});

test("認証失敗、API制限、タイムアウトを画面で説明する", async ({ page }) => {
  await page.goto("/x");
  await page.getByRole("checkbox", { name: /自分の投稿を診断し/ }).check();
  await page.getByRole("button", { name: "架空のX投稿で試す" }).click();
  const cases = [
    { status: 401, message: "Xにログインし直してください。" },
    { status: 503, message: "X APIまたはモデルが混雑しています。時間を置いてください。" },
    { status: 504, message: "通信がタイムアウトしました。時間を置いて再度お試しください。" },
  ];
  for (const item of cases) {
    await page.route("**/api/x/diagnose", (route) => route.fulfill({ status: item.status, json: {} }), { times: 1 });
    await page.getByRole("button", { name: "診断する" }).click();
    await expect(page.locator("main [role=alert]")).toHaveText(item.message);
  }
});

test("Blueskyの既存ホームとログイン画面が表示される", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("みーつけた");
  await expect(page.getByRole("form")).toBeVisible();
});
