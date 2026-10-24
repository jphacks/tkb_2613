import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
