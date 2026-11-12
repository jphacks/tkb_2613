import { expect, test } from "playwright/test";

// 偽の X API で OAuth → 投稿の取得 → 集計 → 仮除外 → ログアウトでの破棄を通す。
// 設定は playwright.fake-x.config.ts。ブラウザから本物の X へは1件も出さない。
const FAKE_X = "http://127.0.0.1:4010";

type Calls = { authorize: number; token: number; me: number; tweets: number; resources: number };

async function fakeCalls(): Promise<Calls> {
  return (await (await fetch(`${FAKE_X}/__calls`)).json()) as Calls;
}

test("偽のX APIでOAuthから仮除外・ログアウトでの破棄まで通す", async ({ page, context }) => {
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
  const before = await fakeCalls();

  await page.goto("/x");
  await expect(page.getByRole("button", { name: "架空のX投稿で試す" })).toHaveCount(0);
  await expect(page.getByText(/X APIの読み取りは課金対象です/)).toBeVisible();
  await page.getByRole("checkbox", { name: /利用目的を確認し/ }).check();
  await page.getByRole("button", { name: "Xでログイン" }).click();

  // コールバックで code と state を消費し、クエリのない /x に戻る
  await page.waitForURL((url) => url.pathname === "/x" && url.search === "");
  await expect(page.getByText("fictional_x_tester")).toBeVisible();

  await page.getByRole("button", { name: "公開情報を確認する" }).click();
  await expect(page.getByText("公開情報チェック結果", { exact: true })).toBeVisible();
  await expect(page.getByText("投稿 5 件", { exact: false })).toBeVisible();
  await expect(page.getByText("駅名：新宿駅")).toBeVisible();
  await expect(page.getByText("6件目以降は")).toHaveCount(0);

  await page.getByRole("checkbox", { name: "仮除外する" }).first().check();
  await page.getByRole("button", { name: "仮除外後を比べる" }).click();
  await expect(page.getByRole("status")).toContainText("明記情報");
  await page.getByRole("button", { name: "選択した投稿を除いて再集計" }).click();
  await expect(page.getByText("仮除外後の再集計")).toBeVisible();
  await expect(page.getByText("投稿 4 件", { exact: false })).toBeVisible();

  const used = await fakeCalls();
  expect(used.authorize - before.authorize).toBe(1);
  expect(used.token - before.token).toBe(1);
  expect(used.me - before.me).toBe(1);
  expect(used.tweets - before.tweets).toBe(1); // 仮除外・再集計で X を再び呼ばない

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
