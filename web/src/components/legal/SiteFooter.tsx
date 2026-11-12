import Link from "next/link";

import { messages } from "@/lib/messages";

const LINKS = [
  { href: "/privacy", label: "プライバシーポリシー" },
  { href: "/terms", label: "利用規約" },
  { href: "/data-deletion", label: "データ削除" },
  { href: "/support", label: "サポート" },
] as const;

/** すべての画面の一番下。Meta 審査を含む公開文書へのリンク */
export function SiteFooter() {
  return (
    <footer className="mx-auto max-w-5xl border-t border-ink/15 px-4 py-8 text-sm text-ink/70 sm:px-8">
      <nav aria-label="このサービスについて">
        <ul className="flex flex-wrap gap-x-6 gap-y-2">
          {LINKS.map((link) => (
            <li key={link.href}>
              <Link href={link.href} className="underline underline-offset-4 hover:text-seeker focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-seeker">
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <p className="mt-4 text-ink/50">{messages.app.name}：JPHACKS 2026 チーム tkb_2613 の作品</p>
    </footer>
  );
}
