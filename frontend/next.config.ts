import type { NextConfig } from "next";

// NEXT_BUILD_MODE=export のとき:
//   - 静的ビルド (out/) を生成 → backend (aiohttp) が同一ドメインで配信する
//   - dev mock API routes は事前に削除されている前提 (Dockerfile 参照)
//   - rewrites は使わない (同一ドメインなので /api/console/* も同じサーバから返る)
//
// 開発時 (npm run dev):
//   - BACKEND_URL が設定されていれば rewrites で backend にプロキシ
//   - 未設定なら src/app/api/console/* の dev mock が応答
const isExport = process.env.NEXT_BUILD_MODE === "export";
const backendUrl = process.env.BACKEND_URL?.trim() || null;

const nextConfig: NextConfig = {
  ...(isExport
    ? { output: "export" as const, trailingSlash: true, images: { unoptimized: true } }
    : {}),
  async rewrites() {
    if (isExport || !backendUrl) return [];
    return {
      beforeFiles: [
        {
          source: "/api/console/:path*",
          destination: `${backendUrl}/api/console/:path*`,
        },
      ],
      afterFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;
