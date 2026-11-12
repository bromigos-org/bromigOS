// After `next build`: a fixture build (BOARD_FIXTURES=1) gets fixtures/*.json in out/fixtures/,
// for ?fixture=NAME. Then the export is checked: it must name no other site and run no inline
// script, so it works under Content-Security-Policy: default-src 'self'.
import { copyFileSync, mkdirSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const out = new URL("../out/", import.meta.url).pathname;
if (process.env.BOARD_FIXTURES === "1") {
  const src = new URL("../fixtures/", import.meta.url).pathname;
  mkdirSync(join(out, "fixtures"), { recursive: true });
  for (const f of readdirSync(src).filter((f) => f.endsWith(".json"))) copyFileSync(join(src, f), join(out, "fixtures", f));
  // the lab's example pictures, clip and model (scripts/make-fixtures.mjs)
  mkdirSync(join(out, "fixtures", "lab"), { recursive: true });
  for (const f of readdirSync(join(src, "lab"))) copyFileSync(join(src, "lab", f), join(out, "fixtures", "lab", f));
}

const walk = (d) => readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : [join(d, f)]));
const bad = [];
for (const f of walk(out)) {
  if (!/\.(html|css)$/.test(f)) continue;
  const t = readFileSync(f, "utf8");
  // a URL to another site in markup or a stylesheet: the page must fetch nothing from outside
  for (const m of t.matchAll(/(?:src|href)=["'](https?:)?\/\/[^"']+|url\(\s*["']?(?:https?:)?\/\/[^)]+\)|@import\s+["']?(?:https?:)?\/\//g)) bad.push(`${f}: ${m[0].slice(0, 80)}`);
  if (f.endsWith(".html")) {
    // an inline script that would run (JSON data blocks are fine) or an inline style attribute
    for (const m of t.matchAll(/<script(?![^>]*\bsrc=)(?![^>]*type="application\/json")[^>]*>/g)) bad.push(`${f}: inline ${m[0]}`);
    for (const m of t.matchAll(/\sstyle="[^"]*"/g)) bad.push(`${f}: inline style ${m[0].slice(0, 60)}`);
  }
}
if (bad.length) {
  console.error("The export breaks the board's rules (no other site, no inline script or style):\n  " + bad.join("\n  "));
  process.exit(1);
}
console.log(`postbuild: ${out} is clean${process.env.BOARD_FIXTURES === "1" ? ", with fixtures" : ""}`);
