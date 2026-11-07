import type { Metadata } from "next";

import { LegalPage } from "@/components/legal/LegalPage";
import { privacy } from "@/lib/legal";
import { messages } from "@/lib/messages";

export const metadata: Metadata = { title: `${privacy.title} | ${messages.app.name}` };

export default function PrivacyPage() {
  return <LegalPage document={privacy} />;
}
