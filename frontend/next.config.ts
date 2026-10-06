import type { NextConfig } from "next";

const isGitHubPagesBuild = process.env.GITHUB_PAGES === "true";

const nextConfig: NextConfig = {
  distDir: isGitHubPagesBuild ? ".next-pages" : ".next-local",
  ...(isGitHubPagesBuild ? { output: "export" as const, basePath: "/coding-assistant" } : {}),
};

export default nextConfig;
