import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1"],
  distDir: process.env.CANOPYLEDGER_NEXT_DIST_DIR ?? ".next",
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
};

export default nextConfig;
