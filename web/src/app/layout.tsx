import type { Metadata } from "next";
// フォントは自前で配信する（実行時に Google Fonts へ接続しない）
import "@fontsource/dela-gothic-one/400.css";
import "@fontsource/zen-antique/400.css";
import "@fontsource/zen-kaku-gothic-new/400.css";
import "@fontsource/zen-kaku-gothic-new/700.css";
import "./globals.css";

import { SessionProvider } from "@/components/session/SessionProvider";
import { messages } from "@/lib/messages";

export const metadata: Metadata = {
  title: messages.app.name,
  description: messages.app.description,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ja" className="h-full antialiased">
      <body className="min-h-full">
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
