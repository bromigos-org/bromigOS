// The tests' web server: the static export (out/) as Caddy serves it, with the board's
// Content-Security-Policy (default-src 'self'), and /fonts/ from the system's Geist Mono, as
// the package's symlinks do. /api/ answers 404: a fixture build must not call it.
// Usage: node tests/serve.mjs [port]
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const root = new URL("../out/", import.meta.url).pathname;
const fonts = process.env.BOARD_FONTS ?? "/usr/share/fonts/TTF"; // ttf-geist-mono's folder
const port = Number(process.argv[2] ?? process.env.PORT ?? 4317);
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".ttf": "font/ttf", ".svg": "image/svg+xml", ".bin": "application/octet-stream", ".png": "image/png", ".txt": "text/plain" };
const HEADERS = { "Content-Security-Policy": "default-src 'self'", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store" };

createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (path.startsWith("/api/")) {
    res.writeHead(404, { ...HEADERS, "Content-Type": "application/json" });
    return res.end('{"error":{"code":"no-api","words":"The test server has no API."}}');
  }
  let file = path.startsWith("/fonts/") ? join(fonts, normalize(path.slice(7))) : join(root, normalize(path));
  if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
  if (!file.startsWith(root) && !file.startsWith(fonts)) file = "";
  if (!file || !existsSync(file)) {
    res.writeHead(404, { ...HEADERS, "Content-Type": "text/plain" });
    return res.end("not found");
  }
  res.writeHead(200, { ...HEADERS, "Content-Type": TYPES[extname(file)] ?? "application/octet-stream" });
  createReadStream(file).pipe(res);
}).listen(port, "127.0.0.1", () => console.log(`serving ${root} on http://127.0.0.1:${port}`));
