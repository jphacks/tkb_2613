import type { Metadata } from "next";

import { LegalPage } from "@/components/legal/LegalPage";
import { ISSUES_URL, support } from "@/lib/legal";
import { messages } from "@/lib/messages";

export const metadata: Metadata = { title: `${support.title} | ${messages.app.name}` };

export default function SupportPage() {
  return (
    <LegalPage document={support}>
      <section aria-labelledby="support-issue-link" className="space-y-3">
        <h2 id="support-issue-link" className="border-l-4 border-seeker pl-3 text-xl font-bold">
          GitHub Issueを開く
        </h2>
        <p>
          <a
            href={ISSUES_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block rounded-sm border-2 border-ink px-4 py-2 font-bold hover:bg-ink hover:text-paper focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-seeker"
          >
            GitHubのIssue（新しいタブで開きます）
          </a>
        </p>
        <p className="text-sm text-ink/70">個人情報や認証情報はIssueに書かないでください。</p>
      </section>
    </LegalPage>
  );
}
