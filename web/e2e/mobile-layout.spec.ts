import { expect, test, type Page } from "playwright/test";

// スマホ幅（390px）で、横にはみ出してレイアウトの幅が広がらないこと。
// 広がると、スマホでは画面全体が縮んだり横に揺れたりする。make dev（モック）を立てた状態で動かす。
const WIDTH = 390;

test.use({ viewport: { width: WIDTH, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });

async function expectNoHorizontalOverflow(page: Page) {
  const size = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    innerWidth: window.innerWidth,
  }));
  expect(size.scrollWidth).toBeLessThanOrEqual(size.clientWidth);
  expect(size.innerWidth).toBe(WIDTH);
}

test("トップ画面がスマホ幅で横にはみ出さない", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("体験デモの結果がスマホ幅で横にはみ出さない（証拠カードの演出中も）", async ({ page }) => {
  await page.goto("/demo");
  await expect(page.getByRole("heading", { name: "消したらどうなる？" })).toBeVisible({ timeout: 30_000 });
  // 証拠カードは時間差で拡大しながら現れる。演出の途中で測る
  await expectNoHorizontalOverflow(page);
  await expect(page.locator(".reveal-slam").last()).toHaveCSS("opacity", "1", { timeout: 15_000 });
  await expectNoHorizontalOverflow(page);

  // 架空のアカウントの帯は、下までスクロールしても画面の一番上に残る
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const banner = await page.getByRole("note").first().boundingBox();
  expect(banner?.y).toBe(0);

  await page.getByRole("button", { name: "消したらどうなる" }).click();
  await expect(page.locator("main [role=status]").first()).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("X の公開情報チェックがスマホ幅で横にはみ出さない", async ({ page }) => {
  await page.goto("/x");
  await expectNoHorizontalOverflow(page);
  await page.getByRole("checkbox", { name: /利用目的を確認し/ }).check();
  await page.getByRole("button", { name: "架空のX投稿で試す" }).click();
  await page.getByRole("button", { name: "公開情報を確認する" }).click();
  await expect(page.getByText("公開情報チェック結果", { exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
