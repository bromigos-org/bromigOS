// Every string the post is handed is untrusted text: a job's title, its step and its stage are a
// command's own output, and its kind, its id and the agent's name are whatever a caller typed.
// Here every string in the jobs is replaced by a payload that would show if it were ever parsed
// as markup or broke out of an attribute. Pass 1 keeps ids, kinds and states valid, so every
// place is drawn; pass 2 makes the ids and kinds hostile too; pass 3 puts the payload where a
// state, a number or a yes/no should be as well. The station's own drawing (post.json) gets the
// same treatment: it is the page's own file, and it is still checked at the door.
import { readFileSync, readdirSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { open } from "./helpers";

const SRC = new URL("../lib/post/", import.meta.url).pathname;
const PAYLOAD = `x"'><i data-pwn="1"></i><img src=x onerror=1>&lt;`;
const files = readdirSync(SRC).filter((f) => f.endsWith(".ts"));

// The module makes every element with createElement and hands text to the page only as an
// attribute's value. No file writes markup, sets a handler or an address from a string, adds a
// style or a script element, or names another site or a data: URL.
test("the module writes no markup", ({}, info) => {
  test.skip(info.project.name !== "desktop", "no browser needed: once is enough");
  expect(files.length).toBeGreaterThan(6);
  for (const f of files) {
    const code = readFileSync(SRC + f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/"http:\/\/www\.w3\.org\/2000\/svg"/, '""').replace(/\/\/.*$/gm, "");
    expect(code, `${f} writes markup`).not.toMatch(/innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser|createContextualFragment|srcdoc|\beval\(|new Function/);
    expect(code, `${f} adds a style or a script`).not.toMatch(/["'`](?:style|script|iframe)["'`]/);
    expect(code, `${f} sets a handler or a URL from a string`).not.toMatch(/\.on[a-z]+\s*=|setAttribute\(\s*["'`](?:on|href|src|style)|javascript:/);
    expect(code, `${f} names another site or a data: URL`).not.toMatch(/https?:\/\/|["'`]data:|url\(data:/);
  }
});

// The class and attribute names the module may write: the classes its stylesheet styles, and the
// words in its own source. A class or an attribute name that is neither came from the data.
const KNOWN = [...new Set([
  ...[...readFileSync(SRC + "post.css", "utf8").matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]),
  ...["weld", "crank", "holo", "type", "scan", "pack", "lift"].map((k) => `p-${k}`),   // what the work throws off: a class per kind of work, made from the table's own word
  "data-job", "tabindex", "playsinline", "disablepictureinpicture",                    // the attributes the source sets through a property of another spelling
  ...files.flatMap((f) => readFileSync(SRC + f, "utf8").match(/[a-zA-Z][\w-]*/g) ?? []),
])];

const job = (id: string, kind: string, state: string, more: Record<string, unknown> = {}) =>
  ({ id, kind, title: `The job ${id}`, state, step: "step 1 of 2 · Doing it", pct: 40, agent: null, parent: null, ok: null, ...more });
/** A job at every place, one that asks, one for an agent, a part of another, and the ones that aren't drawn. */
const LAB = { known: true, jobs: [
  job("a", "lab.image", "running"), job("b", "app.install", "running", { pct: null }), job("c", "backup.run", "needs-you"), job("d", "drive.test", "running"),
  job("e", "server.update", "running"), job("f", "ci.check", "running"), job("g", "app.update", "running", { agent: "ledger" }), job("h", "app.update", "running", { parent: "g" }),
  job("i", "backup.run", "queued"), job("j", "backup.run", "succeeded", { ok: true }), job("k", "backup.run", "failed", { ok: false }),
] };

for (const pass of [1, 2, 3])
  test(`pass ${pass}: hostile jobs stay text`, async ({ page }) => {
    const thrown: string[] = [];
    page.on("pageerror", (e) => thrown.push(e.message));
    const asked: string[] = [];
    page.on("request", (r) => asked.push(r.url()));
    // the fixture build hands the tests the module the page itself loaded (components/Post.tsx)
    const { csp } = await open(page, "healthy", "activity");
    await page.waitForFunction(() => !!(window as any).__post, null, { timeout: 30_000 });
    const found = await page.evaluate(async ({ LAB, pass, PAYLOAD, KNOWN }) => {
      const P = (window as any).__post;
      const host = document.body.appendChild(Object.assign(document.createElement("div"), { id: "t-post" }));
      // ids, kinds and states: kept in pass 1 so every place is drawn; ids and kinds hostile in pass 2; all of it in pass 3
      const KEEP = pass === 1 ? ["id", "kind", "state", "parent"] : pass === 2 ? ["state"] : [];
      const hostile = (v: any, key = ""): any =>
        typeof v === "string" ? (KEEP.includes(key) ? v : PAYLOAD)
        : pass === 3 && (typeof v === "number" || typeof v === "boolean") ? PAYLOAD
        : Array.isArray(v) ? v.map((x) => hostile(x, key))
        : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, hostile(x, k)]))
        : v;
      const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
      const errors: string[] = [], went: string[] = [];
      const ready = new Promise<void>((done) => {
        (window as any).__t = P.mountPost(host, { data: LAB, base: "/post/", reduced: true, onReady: done, onError: (e: any) => { errors.push(String(e?.message ?? e)); done(); }, onNavigate: (route: string) => went.push(route) });
      });
      await ready;
      const post = (window as any).__t, bad = hostile(LAB);
      const seen: Element[] = [];
      const look = () => seen.push(document.querySelector("#t-post .post")!.cloneNode(true) as Element);
      await sleep(300); look();                         // the lab as it is, first: the loops it needs are fetched
      post.update(bad); await sleep(200); look();       // held still
      post.setReduced(false); await sleep(900); look(); // and moving: the crew, the rings, what the work throws off
      post.update(JSON.parse(JSON.stringify(bad))); post.update({ ...bad, jobs: [...bad.jobs].reverse() }); await sleep(200); look();
      (document.querySelector("#t-post .hit[role='button']") as HTMLElement | null)?.click();
      const known = new Set(KNOWN), problems = new Set<string>();
      const where = (e: Element) => `${e.tagName.toLowerCase()}.${(e.getAttribute("class") ?? "").trim().split(/\s+/).slice(0, 2).join(".")}`;
      for (const r of seen) {
        for (const e of r.querySelectorAll("[data-pwn], [onerror], img[src='x' i], i, script, style, a, iframe")) problems.add(`markup: ${where(e)}`);
        for (const e of [r, ...r.querySelectorAll("*")]) {
          for (const a of e.attributes) if (!known.has(a.name) && a.name !== "style") problems.add(`attribute ${a.name}: ${where(e)}`);
          for (const c of (e.getAttribute("class") ?? "").split(/\s+/)) if (c && !known.has(c)) problems.add(`class ${c}: ${where(e)}`);
          const src = e.getAttribute("src");
          if (src !== null && !/^\/post\/[a-z0-9-]+\.(webp|mp4)$/.test(src)) problems.add(`address ${src}: ${where(e)}`);
          const style = e.getAttribute("style") ?? "";
          if (/url\(/.test(style) && !/url\("\/post\/(pod-[a-z]+|ship-fold)\.webp"\)/.test(style)) problems.add(`style ${style.slice(0, 80)}: ${where(e)}`);
        }
      }
      const last = seen[seen.length - 1];
      const out = {
        problems: [...problems].sort(), errors, went,
        words: seen.map((r) => (r.textContent ?? "").trim()).join(""),
        titles: [...last.querySelectorAll("[title]")].map((e) => e.getAttribute("title") ?? ""),
        jobs: [...last.querySelectorAll("[data-job]")].map((e) => e.getAttribute("data-job")),
        unknown: last.classList.contains("unknown"),
      };
      post.unmount();
      return { ...out, left: document.querySelectorAll("#t-post *").length };
    }, { LAB, pass, PAYLOAD, KNOWN });
    expect(found.problems, "what the payload did").toEqual([]);
    expect(found.errors, "the station was drawn").toEqual([]);
    expect(thrown, "errors thrown on the page").toEqual([]);
    expect(found.words, "no words on the picture, hostile or not").toBe("");
    expect(found.left, "unmount leaves nothing behind").toBe(0);
    if (pass === 1) {
      // the text is there to read, as text: every drawn job's title in a hint, and its id on the button
      expect(found.titles.filter((t) => t.includes(`“${PAYLOAD}” (${PAYLOAD} · 40 %)`)).length).toBeGreaterThan(6);
      expect([...new Set(found.jobs)].sort()).toEqual(["a", "b", "c", "d", "e", "f", "g"]);   // "h" is a part of "g"; the queued and the ended aren't drawn
      expect(found.titles.some((t) => t.startsWith("The hologram table: "))).toBe(true);      // "g": an agent asked, whatever it is called
      expect(found.went).toHaveLength(1);
      expect(found.went[0]).toMatch(/^job\/[a-g]$/);
    } else if (pass === 2) {
      // one id for every job, and no kind: one job, at the terminal, and its id is carried as it is
      expect([...new Set(found.jobs)]).toEqual([PAYLOAD]);
      expect(found.titles.some((t) => t.startsWith("The terminal: "))).toBe(true);
      expect(found.went).toEqual([`job/${PAYLOAD}`]);
    } else {
      // no state is a state and "known" isn't a yes: nobody is drawn, and nothing is said to be known
      expect(found.jobs).toEqual([]);
      expect(found.unknown).toBe(true);
      expect(found.went).toEqual([]);
    }
    // every request stayed on this site and under the art folder's own names
    const art = asked.map((u) => new URL(u)).filter((u) => u.pathname.startsWith("/post/"));
    expect(art.filter((u) => !/^\/post\/[a-z0-9-]+\.(webp|mp4|json)$/.test(u.pathname)).map(String)).toEqual([]);
    expect(asked.filter((u) => !u.startsWith(new URL(page.url()).origin))).toEqual([]);
    expect(await csp()).toEqual([]);
  });

// The same, through the page itself: job records whose words are hostile, read by the page's own
// reader and drawn by Activity's hero and its list.
test("hostile job records through the page: the hero and the list", async ({ page }) => {
  await page.route("**/fixtures/post.json", async (route) => {
    const doc = await (await route.fetch()).json();
    for (const j of [...doc.activity, ...doc.board.activity.jobs]) {
      j.title = PAYLOAD; j.stage = PAYLOAD;
      for (const s of j.steps) { s.label = PAYLOAD; s.detail = PAYLOAD; }
      if (j.kind === "lab.pipeline") j.kind = PAYLOAD;                               // no kind at all: the terminal
      if (j.kind === "backup.run") j.requested_by = { ...j.requested_by, agent: PAYLOAD };   // no agent's name: left out
    }
    await route.fulfill({ json: doc });
  });
  const { errors, csp } = await open(page, "post", "activity");
  const post = page.locator(".post-hero.on .post");
  await expect(post.locator(".station")).toBeVisible({ timeout: 30_000 });
  await expect(post.locator(".hit.fig[data-job]")).toHaveCount(3);
  await expect(post.locator('.hit.fig[title^="OWL is working at the press: "]')).toHaveAttribute("title", new RegExp(`“${PAYLOAD.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}” \\(step 2 of 2 · `));
  await expect(post.locator('.hit.mach[title^="The terminal: "]')).toHaveCount(1);
  expect((await post.innerText()).trim()).toBe("");
  await expect(page.locator(".ac-group .job").first()).toContainText(PAYLOAD);
  expect(await page.locator("[data-pwn], [onerror], img[src='x' i]").count()).toBe(0);
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});

// The station's drawing. A room's name is the only text in it that reaches the page; everything
// else is a number, or a name that becomes part of a file's address and must be one of the
// module's own.
test("a hostile drawing: its words stay text, and a name that isn't one stops it at the door", async ({ page }) => {
  let mode: "names" | "addresses" = "names";
  await page.route("**/post/post.json", async (route) => {
    const doc = await (await route.fetch()).json();
    for (const t of Object.values(doc.map.types) as { name: string }[]) t.name = PAYLOAD;
    if (mode === "addresses") {
      doc.map.types["../../x"] = doc.map.types.d; doc.map.start.b1 = ["../../x", ["https://example.invalid/m", "core"]];
      doc.crew["../lineman-idle"] = 1;
    }
    await route.fulfill({ json: doc });
  });
  const asked: string[] = [];
  page.on("request", (r) => asked.push(r.url()));
  const { errors, csp } = await open(page, "jobs", "activity");
  const post = page.locator(".post-hero.on .post");
  await expect(post.locator(".station")).toBeVisible({ timeout: 30_000 });
  await expect(post.locator(".hit.room").first()).toHaveAttribute("title", new RegExp(`^The ${PAYLOAD.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
  expect(await page.locator("[data-pwn], [onerror], img[src='x' i]").count()).toBe(0);
  expect((await post.innerText()).trim()).toBe("");
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
  // names that would reach another address: the drawing is refused whole, and the plain state stands
  mode = "addresses";
  await page.reload();
  await expect(page.locator(".post-wait .post-line")).toHaveText("1 JOB RUNNING · 1 NEEDS YOU");
  await page.waitForTimeout(800);
  await expect(page.locator(".post-hero.on")).toHaveCount(0);
  await expect(page.locator(".post .station")).toHaveCount(0);
  const origin = new URL(page.url()).origin;
  expect(asked.filter((u) => !u.startsWith(origin) || u.includes("..") || u.includes("example.invalid"))).toEqual([]);
  expect(await csp()).toEqual([]);
});
