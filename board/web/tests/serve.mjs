// The tests' web server: the static export (out/) as Caddy serves it, with the board's
// Content-Security-Policy (default-src 'self'), and /fonts/ from the system's Geist Mono, as
// the package's symlinks do. /api/ answers 404: a fixture page must not call it, and the contract
// tests answer it themselves (tests/service.ts); /__sse/NAME is their long-lived activity stream.
// Usage: node tests/serve.mjs [port]
import { existsSync, readFile, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const root = new URL("../out/", import.meta.url).pathname;
const fonts = process.env.BOARD_FONTS ?? "/usr/share/fonts/TTF"; // ttf-geist-mono's folder
const port = Number(process.argv[2] ?? process.env.PORT ?? 4317);
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".ttf": "font/ttf", ".svg": "image/svg+xml", ".bin": "application/octet-stream", ".png": "image/png", ".txt": "text/plain" };
const HEADERS = { "Content-Security-Policy": "default-src 'self'", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store" };

const streams = new Map(); // a test's id → its open activity streams
let samples = null;
const contract = () => (samples ??= JSON.parse(readFileSync(new URL("./contract/service.json", import.meta.url), "utf8")));

createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  // a stand-in activity stream for the contract tests (tests/service.ts sends /api/activity here):
  // the service's real first events, then the connection stays open with keep-alives, as it does
  if (path.startsWith("/__sse/")) {
    const sample = contract()?.http?.[path.slice(7)];
    if (!sample) {
      res.writeHead(404, HEADERS);
      return res.end("no such stream");
    }
    res.writeHead(200, { ...HEADERS, "Content-Type": "text/event-stream; charset=utf-8", "X-Accel-Buffering": "no" });
    res.write(sample.body);
    const alive = setInterval(() => res.write(": keep-alive\n\n"), 2000);
    const id = new URL(req.url, "http://x").searchParams.get("id") ?? "";
    (streams.get(id) ?? streams.set(id, new Set()).get(id)).add(res);
    req.on("close", () => {
      clearInterval(alive);
      streams.get(id)?.delete(res);
    });
    return;
  }
  // the server "going away" for one test's streams: its open connections are cut
  if (path.startsWith("/__drop/")) {
    for (const open of streams.get(path.slice(8)) ?? []) open.destroy();
    res.writeHead(200, HEADERS);
    return res.end("dropped");
  }
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
  // whole files, not streams: a stream that stalls under many parallel pages leaves a request open
  readFile(file, (err, body) => {
    if (err) {
      res.writeHead(500, { ...HEADERS, "Content-Type": "text/plain" });
      return res.end("could not read");
    }
    res.writeHead(200, { ...HEADERS, "Content-Type": TYPES[extname(file)] ?? "application/octet-stream", "Content-Length": body.length });
    res.end(body);
  });
}).listen({ port, host: "127.0.0.1", backlog: 1024 }, () => console.log(`serving ${root} on http://127.0.0.1:${port}`));
