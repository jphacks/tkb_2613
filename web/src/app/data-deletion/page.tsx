import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage } from "@/components/legal/LegalPage";
import { dataDeletion } from "@/lib/legal";
import { messages } from "@/lib/messages";

export const metadata: Metadata = { title: `${dataDeletion.title} | ${messages.app.name}` };

export default function DataDeletionPage() {
  return (
    <LegalPage document={dataDeletion}>
      <section aria-labelledby="data-deletion-links" className="space-y-3">
        <h2 id="data-deletion-links" className="border-l-4 border-seeker pl-3 text-xl font-bold">
          関連ページ
        </h2>
        <p className="flex flex-wrap gap-x-6 gap-y-2">
          <Link href="/threads" className="underline underline-offset-4 hover:text-seeker">Threads診断</Link>
          <Link href="/support" className="underline underline-offset-4 hover:text-seeker">サポート</Link>
          <Link href="/privacy" className="underline underline-offset-4 hover:text-seeker">プライバシーポリシー</Link>
        </p>
      </section>
    </LegalPage>
  );
}
