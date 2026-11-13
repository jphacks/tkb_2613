import { expect, test } from "playwright/test";

// 偽の X API で OAuth → 本人投稿の原文表示 → ログアウトでの破棄を通す。
// 設定は playwright.fake-x.config.ts。ブラウザから本物の X へは1件も出さない。
const FAKE_X = "http://127.0.0.1:4010";

type Calls = { authorize: number; token: number; me: number; tweets: number; resources: number };

async function fakeCalls(): Promise<Calls> {
  return (await (await fetch(`${FAKE_X}/__calls`)).json()) as Calls;
}

test("偽のX APIでOAuthから本人投稿表示・ログアウトでの破棄まで通す", async ({ page, context }) => {
  const outside: string[] = [];
  // X の認可画面だけを偽の X に差し替える。それ以外の x.com への通信は止めて記録する
  await context.route(/^https:\/\/([a-z0-9-]+\.)*x\.com\//, async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === "https://x.com" && url.pathname === "/i/oauth2/authorize") {
      const answer = await fetch(`${FAKE_X}/i/oauth2/authorize${url.search}`, { redirect: "manual" });
      await route.fulfill({ status: answer.status, headers: { Location: answer.headers.get("location") ?? "" } });
      return;
    }
    outside.push(url.origin);
    await route.abort();
  });
  // プロフィール画像の取得先（pbs.twimg.com）も本物へは出さず、1x1 の画像で返す
  await context.route("https://pbs.twimg.com/**", (route) => route.fulfill({
    contentType: "image/png",
    body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=", "base64"),
  }));
  const before = await fakeCalls();

  await page.goto("/x");
  await expect(page.getByRole("button", { name: "架空のX投稿で試す" })).toHaveCount(0);
  await expect(page.getByText(/X APIの読み取りは課金対象です/)).toBeVisible();
  await page.getByRole("checkbox", { name: /利用目的を確認し/ }).check();
  await page.getByRole("button", { name: "Xでログイン" }).click();

  // コールバックで code と state を消費し、クエリのない /x に戻る
  await page.waitForURL((url) => url.pathname === "/x" && url.search === "");
  await expect(page.getByText("fictional_xtest")).toBeVisible();

  await page.getByRole("button", { name: "自分の投稿を読み込む" }).click();
  await expect(page.getByText("本人投稿の取得結果", { exact: true })).toBeVisible();
  await expect(page.getByText("投稿 5 件", { exact: false })).toBeVisible();
  await expect(page.getByText("原文表示のみ", { exact: false })).toBeVisible();
  await expect(page.getByText("本文に書かれている情報")).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: "仮除外する" })).toHaveCount(0);

  // X の表示要件：投稿者・ロゴ・本文のリンク・permalink・編集済み
  const cards = page.getByRole("article", { name: "架空のテスターの投稿" });
  await expect(cards).toHaveCount(5);
  const first = cards.first();
  await expect(first.getByRole("img", { name: "X" })).toBeVisible();
  await expect(first.getByRole("link", { name: "@fictional_xtest" })).toHaveAttribute("href", "https://x.com/fictional_xtest");
  await expect(first.getByRole("link", { name: "Xで見る" }))
    .toHaveAttribute("href", "https://x.com/fictional_xtest/status/1900000000000000099");
  await expect(first.getByRole("link", { name: "#新宿" })).toHaveAttribute("href", "https://x.com/search?q=%23新宿");
  const second = cards.nth(1);
  await expect(second.getByRole("link", { name: "@friend_xx" })).toHaveAttribute("href", "https://x.com/friend_xx");
  await expect(second.getByRole("link", { name: "library.example/fictional" })).toHaveAttribute("href", "https://t.co/fakeLink01");
  await expect(second.getByText("編集済み")).toBeVisible();
  await expect(page.getByText("架空の投稿（Xの投稿ではありません）")).toHaveCount(0);

  const used = await fakeCalls();
  expect(used.authorize - before.authorize).toBe(1);
  expect(used.token - before.token).toBe(1);
  expect(used.me - before.me).toBe(1);
  expect(used.tweets - before.tweets).toBe(1);

  const session = (await context.cookies()).find((cookie) => cookie.name === "x_tkb_session");
  expect(session?.httpOnly).toBe(true);
  expect((await page.request.get("/api/x/diagnosis")).status()).toBe(200);

  await page.getByRole("button", { name: "ログアウトしてデータを破棄" }).click();
  await expect(page.getByRole("button", { name: "Xでログイン" })).toBeVisible();
  expect((await context.cookies()).some((cookie) => cookie.name === "x_tkb_session")).toBe(false);
  // 古いセッションの Cookie を送り直しても、投稿と結果はもう返らない
  const stale = { Cookie: `x_tkb_session=${session?.value ?? ""}` };
  expect((await page.request.get("/api/x/session", { headers: stale })).status()).toBe(401);
  expect((await page.request.get("/api/x/diagnosis", { headers: stale })).status()).toBe(401);
  expect(outside).toEqual([]);
});
