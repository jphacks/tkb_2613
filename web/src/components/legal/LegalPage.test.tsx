import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ContactPage from "@/app/contact/page";
import DataDeletionPage from "@/app/data-deletion/page";
import PrivacyPage from "@/app/privacy/page";
import SupportPage from "@/app/support/page";
import TermsPage from "@/app/terms/page";
import { dataDeletion, ISSUES_URL, LEGAL_UPDATED, privacy, SUPPORT_EMAIL, SUPPORT_MAILTO, support, terms } from "@/lib/legal";

import { SiteFooter } from "./SiteFooter";

describe("legal pages", () => {
  it.each([
    ["terms", TermsPage, terms],
    ["privacy", PrivacyPage, privacy],
    ["data-deletion", DataDeletionPage, dataDeletion],
    ["support", SupportPage, support],
    ["contact", ContactPage, support],
  ] as const)("%s shows its title, update date, sections and a way home", (_name, Page, document) => {
    render(<Page />);

    expect(screen.getByRole("heading", { level: 1, name: document.title })).toBeInTheDocument();
    expect(screen.getByText(`最終更新：${LEGAL_UPDATED}`)).toBeInTheDocument();
    for (const section of document.sections) {
      expect(screen.getByRole("region", { name: section.heading })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: /みーつけた/ })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: SUPPORT_EMAIL })).toHaveAttribute("href", SUPPORT_MAILTO);
  });

  it("privacy policy accurately explains Threads collection, AI, AWS, retention and rights", () => {
    render(<PrivacyPage />);
    const text = document.body.textContent ?? "";

    expect(text).toContain("ユーザーID・ユーザーネーム・認可トークン");
    expect(text).toContain("最大30件");
    expect(text).toContain("Threads の画像や動画のデータは取得しません");
    expect(text).toContain("Ollama");
    expect(text).toContain("ブラウザ内の固定文字列パターン");
    expect(text).toContain("外部サービスやモデルへ送りません");
    expect(text).toContain("一覧取得とは別に任意のAI診断");
    expect(text).toContain("Amazon Web Services");
    expect(text).toContain("最大30分");
    expect(text).toContain("Metaからの認証解除・データ削除通知");
    expect(text).toContain("利用者の権利");
    expect(text).toContain("パスワードは、ログインに使ったら捨てます");
    expect(text).toContain("人物を特定したり、プロフィールの項目");
    expect(text).toContain("アプリパスワード");
    expect(text).not.toContain("受け取った情報を、ほかの人や会社に渡したり売ったりすることはありません");
  });

  it("terms say deletion only happens after the user confirms and cannot be undone", () => {
    render(<TermsPage />);
    const text = document.body.textContent ?? "";

    expect(text).toContain("確認の画面で「削除する」を押したときだけ");
    expect(text).toContain("元に戻せません");
    expect(text).toContain("Threads連携には投稿を削除する機能や権限はありません");
    expect(text).toContain("AI診断ではありません");
    expect(text).toContain("20:00〜22:00");
  });

  it.each([SupportPage, ContactPage])("support routes link only to GitHub Issues and warn against personal details", (Page) => {
    render(<Page />);

    const link = screen.getByRole("link", { name: /GitHub.*Issue/ });
    expect(link).toHaveAttribute("href", ISSUES_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getAllByText(/個人に関わる内容.*Issue に書かないでください/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: SUPPORT_EMAIL })).toHaveAttribute("href", SUPPORT_MAILTO);
  });

  it("data deletion page distinguishes in-memory app data from Threads content", () => {
    render(<DataDeletionPage />);
    const text = document.body.textContent ?? "";

    expect(text).toContain("アクセストークン");
    expect(text).toContain("最大30分");
    expect(text).toContain("署名付き通知");
    expect(text).toContain("確認コードや依頼履歴を永続保存していない");
    expect(text).toContain("Threads上の投稿、Threadsアカウント");
    expect(screen.getByRole("link", { name: "サポート" })).toHaveAttribute("href", "/support");
  });
});

describe("SiteFooter", () => {
  it("links to all public review documents", () => {
    render(<SiteFooter />);
    const nav = screen.getByRole("navigation", { name: "このサービスについて" });

    expect(within(nav).getByRole("link", { name: "利用規約" })).toHaveAttribute("href", "/terms");
    expect(within(nav).getByRole("link", { name: "プライバシーポリシー" })).toHaveAttribute("href", "/privacy");
    expect(within(nav).getByRole("link", { name: "データ削除" })).toHaveAttribute("href", "/data-deletion");
    expect(within(nav).getByRole("link", { name: "サポート" })).toHaveAttribute("href", "/support");
  });
});
