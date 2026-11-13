import type { Metadata } from "next";
// フォントは自前で配信する（実行時に Google Fonts へ接続しない）
import "@fontsource/dela-gothic-one/400.css";
import "@fontsource/zen-antique/400.css";
import "@fontsource/zen-kaku-gothic-new/400.css";
import "@fontsource/zen-kaku-gothic-new/700.css";
import "./globals.css";

import { SiteFooter } from "@/components/legal/SiteFooter";
import { SessionProvider } from "@/components/session/SessionProvider";
import { messages } from "@/lib/messages";

export const metadata: Metadata = {
  title: messages.app.name,
  description: messages.app.description,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  // 証拠カードが叩きつけられる演出（.reveal-slam）は一瞬だけ画面幅を超えて拡大する。スマホでその間に
  // レイアウトの幅が広がって画面が縮まないよう、横方向だけ切る。html にも付けると body の値が画面全体へ
  // 移らず、body 自身がはみ出しを切る。clip はスクロール領域を作らないので sticky の帯はそのまま動く
  return (
    <html lang="ja" className="h-full overflow-x-clip antialiased">
      <body className="min-h-full overflow-x-clip">
        <SessionProvider>{children}</SessionProvider>
        <SiteFooter />
      </body>
    </html>
  );
}
