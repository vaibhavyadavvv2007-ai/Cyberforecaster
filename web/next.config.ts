import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Fully offline demo — no telemetry, no external font/image fetching.
  reactStrictMode: true,
};

export default nextConfig;
