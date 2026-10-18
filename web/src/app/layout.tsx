import type { Metadata } from "next";
// フォントは自前で配信する（実行時に Google Fonts へ接続しない）
import "@fontsource/dela-gothic-one/400.css";
import "@fontsource/zen-kaku-gothic-new/400.css";
import "@fontsource/zen-kaku-gothic-new/700.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "もういいかい？",
  description: "SNS に上げる前の写真から、特定につながる手がかりを見つけて隠すかくれんぼ",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ja" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
