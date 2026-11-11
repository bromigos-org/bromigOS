// Every string Lamplight draws is untrusted text: on the Lab board a name, a word, a hint or a
// detail comes from a command's output (a drive's model string, a share's name, a job's words).
// Here every string in the data, at any depth, is replaced by a payload that would show if it
// were ever parsed as markup or broke out of an attribute. Pass 1 keeps ids, kinds and state
// words valid, so every layer draws; pass 2 makes those hostile too; pass 3 puts the payload where
// a number or a yes/no should be as well.
import { readFileSync, readdirSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { example, type Scenario } from "../lib/lamplight/examples";
import { open } from "./helpers";
import { WEBGL } from "./webgl";

test.use(WEBGL); // the holograms are drawn in this spec

// Markup reaches the page in one place (base.ts: setHtml and addHtml, fed by html`…`, which
// escapes every value). No other file writes it, and no other file but the icons' own constant
// makes a piece of markup without html`…`.
test("the module writes markup in one place", () => {
  const dir = SRC;
  for (const f of readdirSync(dir).filter((f) => f.endsWith(".ts"))) {
    const code = readFileSync(dir + f, "utf8").replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    if (f !== "base.ts") expect(code, `${f} writes markup itself`).not.toMatch(/innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser|createContextualFragment|srcdoc/);
    if (f !== "base.ts" && f !== "symbols.ts") expect(code, `${f} marks a string as markup`).not.toMatch(/new Safe\(/);
    expect(code, `${f} sets a handler or a URL from a string`).not.toMatch(/\.on[a-z]+\s*=|setAttribute\(\s*["'](?:on|href|src|style)|javascript:/);
  }
});

const PAYLOAD = `x"'><i data-pwn="1"></i><img src=x onerror=1>&lt;`;
const SRC = new URL("../lib/lamplight/", import.meta.url).pathname;
// The class and attribute names the module may write: the classes its stylesheet styles, and the
// words in its own source. A class or an attribute name that is neither came from the data.
const CLASSES = [...new Set([
  ...[...readFileSync(SRC + "lamplight.css", "utf8").matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]),
  "d0", "d1", "d2", "d3", "d4", "tp-decks", "tp-booth", "tp-log", "tp-hub",   // the two the source writes from a number or a tab's own id
  "data-engine",   // three.js names its own canvas
  ...readdirSync(SRC).filter((f) => f.endsWith(".ts") && f !== "examples.ts").flatMap((f) => readFileSync(SRC + f, "utf8").match(/[a-zA-Z][\w-]*/g) ?? []),
])];
// the module's example labs (every optional layer: stars, the log, goals, the roll-call, friends, the hub, a plan), and the board's own fixtures
const SETS = ["example:needs", "example:calm", "example:quiet", "example:goal", "example:setup", "board:healthy", "board:needs-you", "board:lab", "board:setup", "board:watch"];

for (const set of SETS)
  for (const pass of [1, 2, 3])
    test(`${set}, pass ${pass}: hostile text stays text`, async ({ page }) => {
      const thrown: string[] = [];
      page.on("pageerror", (e) => thrown.push(e.message));
      // the fixture build hands the tests the module the page itself loaded (components/Lamplight.tsx)
      await open(page, "healthy", "home");
      await page.waitForFunction(() => !!(window as any).__lamplight, null, { timeout: 30_000 });
      const [from, name] = set.split(":");
      const lab = from === "example" ? example(name as Scenario) : null;
      const found = await page.evaluate(async ({ lab, name, pass, PAYLOAD, CLASSES }) => {
        const LP = (window as any).__lamplight, assets = LP.ASSETS;
        const clean = lab ?? LP.fromBoard((await (await fetch(`/fixtures/${name}.json`)).json()).board);
        for (const id of ["t-home", "t-machine", "t-rack"]) if (!document.getElementById(id)) document.body.appendChild(Object.assign(document.createElement("div"), { id }));
        // ids, kinds and state words: kept in pass 1 so each layer is drawn, hostile in pass 2
        const KEEP = new Set(["id", "machine", "kind", "state", "severity", "deck", "mascot", "tone", "mark", "art", "can", "go", "job", "cause", "type"]);
        const hostile = (v: any, key = ""): any =>
          typeof v === "string" ? (pass !== 2 && KEEP.has(key) ? v : PAYLOAD)
          : pass === 3 && (typeof v === "number" || typeof v === "boolean") ? PAYLOAD
          : Array.isArray(v) ? v.map((x) => hostile(x, key))
          : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, hostile(x, k)]))
          : v;
        const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
        const errors: string[] = [];
        const draw = async (data: any) => {
          for (const id of ["t-home", "t-machine", "t-rack"]) LP.unmount(document.getElementById(id));
          const common = { assets, reduced: true, onError: (e: any) => errors.push(String(e?.message ?? e)) };
          const home = LP.mount(document.getElementById("t-home"), { ...common, data });
          const m0 = data.machines[0] ?? { id: "none", kind: "server" };
          const machine = LP.mountMachine(document.getElementById("t-machine"), { ...common, data, machine: m0.id });
          LP.mountRack(document.getElementById("t-rack"), { ...common, kind: m0.kind, state: m0.state, label: m0.name });
          await sleep(700);   // the crew is added after the station's first frame
          const seen: Element[] = [];
          const look = () => seen.push(...[...document.querySelectorAll("#t-home .lp, #t-machine .lp, #t-rack .lp")].map((r) => r.cloneNode(true) as Element));
          look();
          for (const t of ["booth", "log", "hub", "decks"]) { home.setTab(t); await sleep(60); look(); }
          (document.querySelector("#t-home .far") as HTMLElement | null)?.click();
          (document.querySelector("#t-home [data-show='next']") as HTMLElement | null)?.click();
          home.update(JSON.parse(JSON.stringify(data))); machine.update(data);
          home.update({ ...data, clock: typeof data.clock === "string" ? data.clock + " " : "00:00" });   // a head-only update
          await sleep(200); look();
          return seen;
        };
        const known = new Set(CLASSES);
        await draw(clean);   // the lab as it is, first: every model and painting is loaded before the hostile one is drawn
        const seen = await draw(hostile(clean));
        const where = (e: Element) => { const p: string[] = []; for (let n: Element | null = e; n && p.length < 4 && !n.classList.contains("lp"); n = n.parentElement) p.unshift(`${n.tagName.toLowerCase()}${n.getAttribute("class") ? "." + n.getAttribute("class")!.trim().split(/\s+/).slice(0, 2).join(".") : ""}`); return p.join(" > "); };
        const bad = new Set<string>();
        for (const r of seen) {
          for (const e of r.querySelectorAll("[data-pwn], [onerror], img[src='x' i]")) bad.add(`markup: ${where(e.parentElement ?? e)}`);
          for (const e of [r, ...r.querySelectorAll("*")]) {
            for (const a of e.attributes) if (!known.has(a.name) && a.name !== "style") bad.add(`attribute ${a.name}: ${where(e)}`);
            for (const c of (e.getAttribute("class") ?? "").split(/\s+/)) if (c && !known.has(c)) bad.add(`class ${c}: ${where(e)}`);
          }
        }
        const text = seen.map((r) => r.textContent ?? "").join("\n");
        return { bad: [...bad].sort(), shown: text.includes(PAYLOAD) || text.includes(PAYLOAD.toUpperCase()), row: [...new Set(seen.flatMap((r) => [...r.querySelectorAll(".crow b")].map((b) => b.textContent)))], top: document.querySelector("#t-machine .mh-top b")?.textContent ?? "", machines: clean.machines.length, errors };
      }, { lab, name, pass, PAYLOAD, CLASSES });
      expect(found.bad, "what the payload did").toEqual([]);
      expect(thrown, "errors thrown on the page").toEqual([]);
      // and the text is there to read, as text: a machine's name in the deck list and on its page
      expect(found.shown).toBe(true);
      if (found.machines) {
        expect(found.row).toContain(PAYLOAD.toUpperCase());
        expect(found.top).toContain(PAYLOAD.toUpperCase());
      }
    });

// The same, through the page itself: a board document whose words are hostile, drawn by Home's
// station and a machine's hero as the page mounts them.
test("a hostile board document through the page: Home's station and a machine's hero", async ({ page }) => {
  await page.route("**/fixtures/needs-you.json", async (route) => {
    const doc = await (await route.fetch()).json();
    doc.board.lab.name = PAYLOAD;
    for (const m of doc.board.machines) { m.state_word = PAYLOAD; m.roles = [PAYLOAD, PAYLOAD]; m.kind = m.name === "myserver" ? m.kind : PAYLOAD; }
    for (const n of doc.board.needs_you) { n.words = PAYLOAD; n.detail = PAYLOAD; if (n.subject) { n.subject.name = PAYLOAD; } n.severity = PAYLOAD; }
    doc.board.status.words = PAYLOAD;
    await route.fulfill({ json: doc });
  });
  const { errors, csp } = await open(page, "needs-you", "home");
  const lamp = page.locator(".lamp.on");
  await expect(lamp.locator(".stage.ready")).toBeVisible({ timeout: 30_000 });
  await expect(lamp.locator(".alarm-bar")).toContainText(PAYLOAD.toUpperCase());
  await expect(lamp.locator('.crow[data-c="myserver"] .st')).toContainText(PAYLOAD.toUpperCase());
  await page.evaluate(() => (window.location.hash = "m/myserver"));
  const hero = page.locator(".mc-hero.on .mhero");
  await expect(hero).toHaveClass(/ready/, { timeout: 30_000 });
  await expect(hero.locator(".mh-top")).toContainText(PAYLOAD.toUpperCase());
  expect(await page.locator("[data-pwn], [onerror], img[src='x' i]").count()).toBe(0);
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});
