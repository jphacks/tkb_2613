import type { NextConfig } from "next";

// 画面の多層防御。Next.js がインラインのスクリプトを使うので script-src は縛らず、壊れない範囲だけ入れる
// （ほかに必要な見出しは CloudFront の管理ポリシーが付ける）
export const CONTENT_SECURITY_POLICY = "frame-ancestors 'none'; object-src 'none'; base-uri 'none'";

const nextConfig: NextConfig = {
  // 応答に x-powered-by: Next.js を付けない（使っている仕組みを外に出さない）
  poweredByHeader: false,
  // 開発サーバーの受信ログに X OAuth のコールバックのクエリ（code・state）を出さない。
  // 本番ビルドは受信ログを出さず、中継失敗のログは app/api/x/callback/route.ts で抑える
  logging: { incomingRequests: { ignore: [/\/api\/x\/callback/] } },
  async headers() {
    return [{ source: "/:path*", headers: [{ key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY }] }];
  },
  // Docker イメージを小さくするため、必要なファイルだけを .next/standalone に出力する
  output: "standalone",
  // /api を api（FastAPI）に中継し、画面と api の入口を 1 つにする（セッションの Cookie を同じオリジンで使うため）。
  // API_ORIGIN はビルド時に読まれる。Vercel では Tailscale Funnel などで公開した api の URL を入れる
  async rewrites() {
    const origin = (process.env.API_ORIGIN ?? "http://localhost:8001").replace(/\/+$/, "");
    return [{ source: "/api/:path*", destination: `${origin}/api/:path*` }];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
