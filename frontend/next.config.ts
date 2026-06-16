import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  basePath: "/mvp",
  assetPrefix: "/mvp",
  trailingSlash: true,
};

export default nextConfig;
