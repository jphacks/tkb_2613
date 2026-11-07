import type { Metadata } from "next";

import { LegalPage } from "@/components/legal/LegalPage";
import { terms } from "@/lib/legal";
import { messages } from "@/lib/messages";

export const metadata: Metadata = { title: `${terms.title} | ${messages.app.name}` };

export default function TermsPage() {
  return <LegalPage document={terms} />;
}
