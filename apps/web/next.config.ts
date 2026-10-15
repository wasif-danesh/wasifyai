import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  // the shared packages are TypeScript source (no build step)
  transpilePackages: ["@wasifyai/ui", "@wasifyai/client"],
  // Music moved under /music when the home page arrived; keep old links and bookmarks working.
  async redirects() {
    return [
      { source: "/songs", destination: "/music/songs", permanent: true },
      { source: "/songs/:id", destination: "/music/songs/:id", permanent: true },
    ];
  },
};
export default config;
