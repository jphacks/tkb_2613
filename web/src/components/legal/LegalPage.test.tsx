import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ContactPage from "@/app/contact/page";
import PrivacyPage from "@/app/privacy/page";
import TermsPage from "@/app/terms/page";
import { contact, ISSUES_URL, LEGAL_UPDATED, privacy, terms } from "@/lib/legal";

import { SiteFooter } from "./SiteFooter";

describe("legal pages", () => {
  it.each([
    ["terms", TermsPage, terms],
    ["privacy", PrivacyPage, privacy],
    ["contact", ContactPage, contact],
  ] as const)("%s shows its title, update date, sections and a way home", (_name, Page, document) => {
    render(<Page />);

    expect(screen.getByRole("heading", { level: 1, name: document.title })).toBeInTheDocument();
    expect(screen.getByText(`最終更新：${LEGAL_UPDATED}`)).toBeInTheDocument();
    for (const section of document.sections) {
      expect(screen.getByRole("region", { name: section.heading })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: /みーつけた/ })).toHaveAttribute("href", "/");
  });

  it("privacy policy states what is sent and what is not kept, as decided", () => {
    render(<PrivacyPage />);
    const text = document.body.textContent ?? "";

    expect(text).toContain("第三者の AI サービスには送りません");
    expect(text).toContain("診断結果は保存しません");
    expect(text).toContain("パスワードは、ログインに使ったら捨てます");
    expect(text).toContain("IP アドレスは、攻撃を防ぐために一時的に処理するだけで、保存しません");
    expect(text).toContain("顔から人物を調べたり");
    expect(text).toContain("アプリパスワード");
    // 決定どおり、閲覧リンク（期限付きの保存）の例外は書かない
    expect(text).not.toContain("閲覧リンク");
  });

  it("terms say deletion only happens after the user confirms and cannot be undone", () => {
    render(<TermsPage />);
    const text = document.body.textContent ?? "";

    expect(text).toContain("確認の画面で「削除する」を押したときだけ");
    expect(text).toContain("元に戻せません");
    expect(text).toContain("20:00〜22:00");
  });

  it("contact page links only to GitHub Issues and warns against personal details", () => {
    render(<ContactPage />);

    const link = screen.getByRole("link", { name: /GitHub の Issue/ });
    expect(link).toHaveAttribute("href", ISSUES_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getAllByText(/個人に関わる内容.*Issue に書かないでください/).length).toBeGreaterThan(0);
    // メールアドレスなど、ほかの連絡先は出さない
    expect(document.body.textContent).not.toMatch(/@[a-z0-9-]+\.[a-z]/i);
  });
});

describe("SiteFooter", () => {
  it("links to the terms, privacy policy and contact page", () => {
    render(<SiteFooter />);
    const nav = screen.getByRole("navigation", { name: "このサービスについて" });

    expect(within(nav).getByRole("link", { name: "利用規約" })).toHaveAttribute("href", "/terms");
    expect(within(nav).getByRole("link", { name: "プライバシーポリシー" })).toHaveAttribute("href", "/privacy");
    expect(within(nav).getByRole("link", { name: "問い合わせ" })).toHaveAttribute("href", "/contact");
  });
});
