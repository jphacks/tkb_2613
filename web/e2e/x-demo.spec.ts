import { expect, test } from "playwright/test";

test("合成X投稿の明記情報を確認し、仮除外・再集計する", async ({ page }) => {
  await page.goto("/x");
  await expect(page.getByRole("heading", { name: "自分の投稿を確認する" })).toBeVisible();
  await page.getByRole("checkbox", { name: /利用目的を確認し/ }).check();
  await page.getByRole("button", { name: "架空のX投稿で試す" }).click();
  await expect(page.getByText("架空のXアカウント")).toBeVisible();
  await page.getByRole("button", { name: "公開情報を確認する" }).click();
  await expect(page.getByText("公開情報チェック結果", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "確認した投稿" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "本文に書かれている情報" })).toBeVisible();
  await expect(page.getByText("駅名：渋谷駅")).toBeVisible();
  await expect(page.getByText(/根拠「渋谷駅」/).first()).toBeVisible();

  await page.getByRole("checkbox", { name: "仮除外する" }).first().check();
  await page.getByRole("button", { name: "仮除外後を比べる" }).click();
  await expect(page.getByRole("status")).toContainText("明記情報");
  await page.getByRole("button", { name: "選択した投稿を除いて再集計" }).click();
  await expect(page.getByText("仮除外後の再集計")).toBeVisible();
  await page.getByRole("button", { name: "全投稿の結果に戻す" }).click();
  await expect(page.getByText("公開情報チェック結果", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "ログアウトしてデータを破棄" }).click();
  await expect(page.getByRole("button", { name: "架空のX投稿で試す" })).toBeVisible();
});

test("X OAuthの開始先とPKCE導線を確認する。Xには接続しない", async ({ page }) => {
  await page.route("**/api/x/config", (route) => route.fulfill({
    json: { mock_enabled: false, live_enabled: true, max_posts: 5 },
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
  await page.getByRole("checkbox", { name: /利用目的を確認し/ }).check();
  await page.getByRole("button", { name: "Xでログイン" }).click();
  await expect(page.getByRole("heading", { name: "合成OAuth画面" })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("code_challenge_method")).toBe("S256");
});

test("認証失敗を画面で説明する", async ({ page }) => {
  await page.goto("/x");
  await page.getByRole("checkbox", { name: /利用目的を確認し/ }).check();
  await page.getByRole("button", { name: "架空のX投稿で試す" }).click();
  const cases = [
    { status: 401, message: "Xにログインし直してください。" },
    { status: 403, message: "実X連携は用途承認と安全設定の確認が完了するまで利用できません。" },
    { status: 429, message: "本日のXの取得上限に達しました。日付が変わってから（UTC）お試しください。" },
  ];
  for (const item of cases) {
    await page.route("**/api/x/diagnose", (route) => route.fulfill({ status: item.status, json: {} }), { times: 1 });
    await page.getByRole("button", { name: "公開情報を確認する" }).click();
    await expect(page.locator("main [role=alert]")).toHaveText(item.message);
  }
});

test("Blueskyの既存ホームとログイン画面が表示される", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("みーつけた");
  await expect(page.getByRole("form")).toBeVisible();
});
