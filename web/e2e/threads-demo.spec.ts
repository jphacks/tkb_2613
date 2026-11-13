import { expect, test } from "playwright/test";

test("審査フロー：本人投稿の一覧・詳細とAIを使わないセルフチェックを通してログアウトする", async ({ page }) => {
  await page.goto("/threads");
  await expect(page.getByRole("heading", { name: "Threadsで、みーつけた" })).toBeVisible();
  await page.getByRole("checkbox", { name: /自分の投稿ID・本文・投稿時刻/ }).check();
  await page.getByRole("button", { name: "架空のThreads投稿で試す" }).click();
  await expect(page.getByText("架空のThreadsアカウント")).toBeVisible();
  await page.getByRole("button", { name: "本人投稿を確認" }).click();
  await expect(page.getByText("本人投稿 5 件を取得しました。")).toBeVisible();
  await page.getByText("取得情報の詳細").first().click();
  await expect(page.getByText("投稿ID：").first()).toBeVisible();
  await page.getByRole("button", { name: "公開情報をセルフチェック" }).click();
  await expect(page.getByRole("status")).toContainText("AI診断ではありません");
  await page.getByRole("button", { name: "ログアウト" }).click();
  await expect(page.getByRole("button", { name: "架空のThreads投稿で試す" })).toBeVisible();
});

test("英語表示：審査フローを英語のまま通し、再読み込みしても英語が保たれる", async ({ page }) => {
  await page.goto("/threads?lang=en");
  await expect(page.getByRole("heading", { name: "Miitsuketa for Threads" })).toBeVisible();
  await page.getByRole("checkbox", { name: /I agree that this app retrieves my own Threads post IDs/ }).check();
  await page.getByRole("button", { name: "Try with fictional Threads posts" }).click();
  await expect(page.getByText("架空のThreadsアカウント")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Review my posts" })).toBeVisible();
  await page.getByRole("button", { name: "Review my posts" }).click();
  await expect(page.getByText(/Retrieved 5 of your own posts\./)).toBeVisible();
  await expect(page.getByText("毎週火曜はジムに行く")).toBeVisible();
  await page.getByText("Retrieved data details").first().click();
  await expect(page.getByText("Post ID:").first()).toBeVisible();
  await page.getByRole("button", { name: "Check visible public information" }).click();
  await expect(page.getByRole("status")).toContainText("not an AI diagnosis");
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Try with fictional Threads posts" })).toBeVisible();
});

test("任意機能：合成Threads投稿をAI診断し、根拠を見て仮除外・再診断する", async ({ page }) => {
  await page.goto("/threads");
  await expect(page.getByRole("heading", { name: "Threadsで、みーつけた" })).toBeVisible();
  await page.getByRole("checkbox", { name: /自分の投稿ID・本文・投稿時刻/ }).check();
  await page.getByRole("button", { name: "架空のThreads投稿で試す" }).click();
  await expect(page.getByText("架空のThreadsアカウント")).toBeVisible();
  await page.getByRole("button", { name: "本人投稿を確認" }).click();
  await expect(page.getByText("本人投稿 5 件を取得しました。")).toBeVisible();
  await page.getByText("任意機能：AI診断（モデル稼働時のみ）").click();
  await page.getByRole("button", { name: "AI診断を試す" }).click();
  await expect(page.getByText("診断結果", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "診断した投稿" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "推定の根拠投稿" })).toBeVisible();
  await expect(page.getByText(/投稿 threads:9001/)).toBeVisible();
  await expect(page.getByText(/根拠「毎週火曜はジム」/)).toBeVisible();

  await page.getByRole("checkbox", { name: "仮除外する" }).first().check();
  await page.getByRole("button", { name: "仮除外を試す" }).click();
  await expect(page.getByRole("status")).toContainText("仮除外で不明になる項目");
  await page.getByRole("button", { name: "選択した投稿を除いて再診断" }).click();
  await expect(page.getByText("仮除外後の再診断")).toBeVisible();
  await page.getByRole("button", { name: "全投稿の結果に戻す" }).click();
  await expect(page.getByText("診断結果", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "ログアウト" }).click();
  await expect(page.getByRole("button", { name: "架空のThreads投稿で試す" })).toBeVisible();
});

test("OAuth失敗を説明し、URLから失敗理由を消す", async ({ page }) => {
  await page.goto("/threads?auth_error=state");
  await expect(page.locator("main [role=alert]")).toContainText("最初からログインし直してください");
  await expect(page).toHaveURL(/\/threads$/);
});
