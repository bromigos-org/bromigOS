// The Lab board's page is a static export: plain files that Caddy serves from
// /usr/share/bromigos-board/web, with no Node on the server (DESIGN.md §1, docs/board.md).
// BOARD_FIXTURES=1 builds the test copy: the page then reads ?fixture=NAME from fixtures/
// instead of the API (lib/api/client.ts). The package's own build never sets it.
const fixtures = process.env.BOARD_FIXTURES === "1";

/** @type {import('next').NextConfig} */
export default {
  output: "export",
  reactStrictMode: true,
  poweredByHeader: false,
  productionBrowserSourceMaps: false,
  images: { unoptimized: true },
  env: { NEXT_PUBLIC_BOARD_FIXTURES: fixtures ? "1" : "0" },
};
