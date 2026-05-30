import type { NextConfig } from "next";

// BACKEND_URL が設定されていれば /api/console/* をそこへプロキシ。
// 未設定なら frontend 内の dev mock (src/app/api/console/*) が応答する。
const backendUrl = process.env.BACKEND_URL?.trim() || null;

const nextConfig: NextConfig = {
  async rewrites() {
    if (!backendUrl) return [];
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
