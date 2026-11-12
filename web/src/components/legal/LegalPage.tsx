import Link from "next/link";
import type { ReactNode } from "react";

import { LEGAL_UPDATED, SUPPORT_EMAIL, SUPPORT_MAILTO, type LegalBlock, type LegalDocument } from "@/lib/legal";
import { messages } from "@/lib/messages";

function Block({ block }: { block: LegalBlock }) {
  if (typeof block === "string") return <p>{block}</p>;
  return (
    <ul className="list-disc space-y-1.5 pl-6 marker:text-seeker">
      {block.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

/** 利用規約・プライバシーポリシー・問い合わせの共通のページ。children はセクションの後ろに足すもの */
export function LegalPage({ document, children }: { document: LegalDocument; children?: ReactNode }) {
  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:px-8 sm:py-20">
      <p className="mb-8 text-sm">
        <Link href="/" className="underline underline-offset-4 hover:text-seeker">
          ← {messages.app.name}
        </Link>
      </p>
      <header className="mb-10 border-b-2 border-ink pb-6">
        <h1 className="font-display text-4xl sm:text-5xl">{document.title}</h1>
        <p className="mt-4 text-ink/80">{document.lead}</p>
        <p className="mt-3 text-sm text-ink/60">最終更新：{LEGAL_UPDATED}</p>
      </header>
      <div className="space-y-10 leading-relaxed">
        {document.sections.map((section, index) => (
          <section key={section.heading} aria-labelledby={`legal-section-${index}`} className="space-y-3">
            <h2 id={`legal-section-${index}`} className="border-l-4 border-seeker pl-3 text-xl font-bold">
              {section.heading}
            </h2>
            {section.blocks.map((block, i) => (
              <Block key={i} block={block} />
            ))}
          </section>
        ))}
        {children}
        <section aria-labelledby="official-contact" className="space-y-3">
          <h2 id="official-contact" className="border-l-4 border-seeker pl-3 text-xl font-bold">
            公式問い合わせ先
          </h2>
          <p>
            メール：{" "}
            <a className="underline underline-offset-4 hover:text-seeker" href={SUPPORT_MAILTO}>
              {SUPPORT_EMAIL}
            </a>
          </p>
          <p className="text-sm text-ink/70">
            パスワード、アクセストークン、App Secretなどの認証情報は送らないでください。
          </p>
        </section>
      </div>
    </main>
  );
}
