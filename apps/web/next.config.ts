import type { NextConfig } from "next";

const API = process.env.API_URL || "http://localhost:8000";

const config: NextConfig = {
  output: "standalone",
  async rewrites() {
    // same-origin /api -> FastAPI, so cookies and SSE work without CORS
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};
export default config;
