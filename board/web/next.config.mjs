// The Lab board's page is a static export: plain files that Caddy serves from
// /usr/share/bromigos-board/web, with no Node on the server (docs/board.md).
// BOARD_FIXTURES=1 builds the test copy: the page then reads ?fixture=NAME from fixtures/
// instead of the API (lib/api/client.ts). The package's own build never sets it.
import { execFileSync } from "node:child_process";

const fixtures = process.env.BOARD_FIXTURES === "1";

/** The build's id: the commit it was built from, so two builds of one commit are the same files.
 *  BOARD_BUILD_ID (the package sets it), else git's short commit, else "dev". */
function buildId() {
  if (process.env.BOARD_BUILD_ID) return process.env.BOARD_BUILD_ID.replace(/[^A-Za-z0-9._-]/g, "") || "dev";
  try {
    return execFileSync("git", ["rev-parse", "--short=12", "HEAD"], { stdio: ["ignore", "pipe", "ignore"] }).toString().trim() || "dev";
  } catch {
    return "dev";
  }
}

/** @type {import('next').NextConfig} */
export default {
  output: "export",
  reactStrictMode: true,
  poweredByHeader: false,
  productionBrowserSourceMaps: false,
  images: { unoptimized: true },
  generateBuildId: buildId,
  env: { NEXT_PUBLIC_BOARD_FIXTURES: fixtures ? "1" : "0" },
};
