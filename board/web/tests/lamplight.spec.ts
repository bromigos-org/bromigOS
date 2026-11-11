// Lamplight, Home's hero: the lab as a living station, drawn from the board's own document under
// the board's Content-Security-Policy. The station says the page's status line, lights what needs
// you where it is, opens the page that owns each fact, asks only for what its manifest names
// (lib/lamplight-assets.ts), and stands as words when there is no WebGL.
import { expect, test, type Page } from "@playwright/test";
import { open, VERDICT } from "./helpers";
import { WEBGL } from "./webgl";

test.use(WEBGL); // the holograms are drawn in this spec

const CREW = ["lineman-stand", "lineman", "noir", "owl-scan", "owl"].map((n) => `/lamplight/crew/${n}.webp`).sort();

/** Opens Home on a fixture and waits for the station's hologram; `asked` is every path the page fetched. */
async function station(page: Page, fixture: string) {
  const asked: string[] = [];
  page.on("request", (r) => asked.push(new URL(r.url()).pathname));
  const h = await open(page, fixture, "home");
  await expect(page.locator(".lamp.on .stage.ready")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".lamp .crewx").first()).toBeVisible();
  return { ...h, asked, lamp: page.locator(".lamp") };
}

test("calm: the station is lit, says the page's line, and keeps one WebGL canvas", async ({ page }) => {
  const { lamp, errors, csp, asked } = await station(page, "healthy");
  await expect(page.locator("[data-lamplight='mount'] .lp")).toHaveCount(1);
  await expect(page.locator(VERDICT)).toHaveText("ALL MACHINES NOMINAL");
  await expect(lamp.locator(".head")).toContainText("A RELAY STATION OF THE WICK'S CLASS");
  await expect(lamp.locator(".alarm-bar")).toHaveCount(0);
  await expect(lamp.locator('.crow[data-c="myserver"]')).toContainText("ONLINE");
  await expect(lamp.locator('.crow[data-c="myserver"]')).toContainText("10 apps");
  // OWL listens on the mast; LINEMAN and NOIR wait in quarters, and the shells with no painting are named in words
  await expect(lamp.locator('img.crewx[src$="/crew/owl.webp"]')).toBeVisible();
  await expect(lamp.locator('img.crewx[src$="/crew/lineman-stand.webp"]')).toBeVisible();
  await expect(lamp.locator('img.crewx[src$="/crew/noir.webp"]')).toBeVisible();
  await expect(lamp.locator('.crow[data-c="quarters"]')).toContainText("5 OFF DUTY");
  // the hologram's one canvas (the dust behind the stars is a 2D one, marked as such)
  await expect(lamp.locator("canvas:not([data-k='dust'])")).toHaveCount(1);
  // the board sends no stars, show, goals, friends or plan, so none is drawn
  await expect(lamp.locator(".stars > *, .far, .vplan, .xch, .monx")).toHaveCount(0);
  await expect(lamp.locator(".tabs")).toBeHidden();
  await expect(lamp.locator("svg.elev")).toBeVisible(); // the deck plan is the machines themselves
  // nothing is injected that the policy would refuse, and only the station's own files were asked for
  expect(await page.evaluate(() => document.querySelectorAll(".lp style, .lp [style*='url(']").length)).toBe(0);
  expect(asked.filter((p) => p.startsWith("/holo/")).sort()).toEqual(["/holo/lite/rack.bin", "/holo/lite/wick-cut.bin"]);
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});

test("something needs you: the alarm, the hull, LINEMAN at the machine, and each opens where it is fixed", async ({ page }) => {
  const { lamp, errors, csp } = await station(page, "needs-you");
  await expect(page.locator(VERDICT)).toHaveText("1 MACHINE NEEDS YOU");
  await expect(lamp.locator(".stage")).toHaveClass(/alarm/);
  await expect(lamp.locator(".alarm-bar")).toContainText("HULL ALARM · D2·A MYSERVER · A DRIVE IS GETTING WORSE");
  await expect(lamp.locator('.part[data-part="hull"]')).toHaveClass(/warn/);
  await expect(lamp.locator('.crow[data-c="myserver"]')).toContainText("NEEDS YOU");
  await expect(lamp.locator(".readout.warn")).toHaveAttribute("title", "2 things need you");
  await expect(lamp.locator('img.crewx[src$="/crew/owl-scan.webp"]')).toBeVisible();
  await expect(lamp.locator('img.crewx[src$="/crew/lineman.webp"]')).toBeVisible();
  await expect(lamp.locator(".cap2.warn")).toContainText("LINEMAN");
  await lamp.locator(".alarm-bar").click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Data › Drives$/);
  await page.goBack();
  await expect(page.locator(".lamp.on")).toBeVisible();
  await page.locator('.lamp .crow[data-c="myserver"]').click();
  await expect(page.locator(".sh-crumb")).toHaveText(/myserver›Overview$/);
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});

test("the crew: the five cut-outs that ship are asked for across the states, and no other painting", async ({ page }) => {
  const calm = await station(page, "healthy");
  const needs = await station(page, "needs-you");
  const art = [...new Set([...calm.asked, ...needs.asked].filter((p) => p.startsWith("/lamplight/")))].sort();
  expect(art).toEqual(CREW); // a cut-out stands in place of the portrait cut from a loop, so no still is fetched
});

test("a lab of four: a kind with no cleared model stands as its icon, and its files are never asked for", async ({ page }) => {
  const { lamp, asked, errors, csp } = await station(page, "lab");
  await expect(lamp.locator(".kico")).toHaveCount(2); // vault (storage) and node3 (a small server)
  await expect(lamp.locator(".kico").first()).toHaveAttribute("title", /VAULT/);
  await expect(lamp.locator(".crow")).toHaveCount(5); // four machines and the crew's quarters
  await expect(lamp.locator(".readout").first()).toHaveAttribute("title", /of 4 machines answer now/);
  expect(asked.filter((p) => p.startsWith("/holo/")).sort()).toEqual(["/holo/lite/rack.bin", "/holo/lite/wick-cut.bin", "/holo/lite/workstation.bin"]);
  expect(asked.filter((p) => /storage|node|router|ups|dish|phone/.test(p) && !p.startsWith("/_next/"))).toEqual([]);
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});

test("a first run: set up is its own word, with no alarm", async ({ page }) => {
  const { lamp } = await station(page, "setup");
  await expect(page.locator(VERDICT)).toHaveText("NOTHING INSTALLED YET");
  await expect(lamp.locator('.crow[data-c="myserver"]')).toContainText("SET UP");
  await expect(lamp.locator('.crow[data-c="myserver"]')).toContainText("nothing installed yet");
  await expect(lamp.locator(".alarm-bar")).toHaveCount(0);
  await expect(lamp.locator(".stage")).not.toHaveClass(/alarm/);
});

test("an old reading: no signal, and nothing is shown as known", async ({ page }) => {
  await open(page, "stale", "home");
  const lamp = page.locator(".lamp.on");
  await expect(lamp.locator(".stage")).toHaveClass(/nosignal/, { timeout: 30_000 });
  await expect(page.locator(VERDICT)).toHaveText(/READING THE SERVER|NOT READ FOR 5 MIN/);
  await expect(lamp.locator(".head .line")).toHaveClass(/\bq\b/);
  await expect(lamp.locator('.crow[data-c="myserver"] .st')).toHaveClass(/unk/);
  await expect(lamp.locator(".alarm-bar")).toHaveCount(0);
  await expect(lamp.locator(".readout").first()).toHaveAttribute("title", "0 of 1 machine answers now");
});

test("the world's colours: the station is recoloured when the world changes", async ({ page }) => {
  const { lamp } = await station(page, "healthy");
  const before = await lamp.locator(".head h2").evaluate((e) => getComputedStyle(e).color);
  await page.evaluate(() => (document.documentElement.dataset.world = "tidewell"));
  await expect.poll(() => lamp.locator(".head h2").evaluate((e) => getComputedStyle(e).color)).not.toBe(before);
  await expect(lamp.locator("canvas:not([data-k='dust'])")).toHaveCount(1);
});

test("without WebGL the station's words stand: the line, the alarm and the decks", async ({ page }) => {
  await page.addInitScript(() => {
    const get = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) {
      return /webgl/.test(kind) ? null : (get as any).call(this, kind, ...rest);
    } as typeof get;
  });
  const failures: string[] = [];
  page.on("pageerror", (e) => failures.push(e.message));
  await page.goto("/?fixture=needs-you#home");
  const lamp = page.locator(".lamp.on");
  await expect(lamp.locator(".stage")).toHaveClass(/nogl/, { timeout: 30_000 });
  await expect(page.locator(VERDICT)).toHaveText("1 MACHINE NEEDS YOU");
  await expect(lamp.locator(".alarm-bar")).toBeVisible();
  await expect(lamp.locator('.crow[data-c="myserver"]')).toContainText("NEEDS YOU");
  await expect(lamp.locator("svg.elev")).toBeVisible();
  await expect(lamp.locator(".ov")).toBeHidden(); // nothing is pinned to a scene that isn't there
  expect(await page.locator(".broken").count()).toBe(0);
  expect(failures).toEqual([]);
});

test("the station's script doesn't arrive: the hero's frame keeps the lab's plain state", async ({ page }) => {
  // the scripts a page without a hero loads; any other script (the station's, with three.js) is then refused
  const shell = new Set<string>();
  let refuse = false;
  page.on("request", (r) => void (!refuse && r.url().includes("/_next/static/") && shell.add(r.url())));
  await page.goto("/?fixture=needs-you#supply");
  await expect(page.locator(".shell")).toBeVisible({ timeout: 15_000 });
  await page.waitForLoadState("networkidle");
  refuse = true;
  await page.route("**/_next/static/**", (route) => (shell.has(route.request().url()) ? route.fallback() : route.abort()));
  await page.evaluate(() => (window.location.hash = "home"));
  const frame = page.locator(".stage.lamp-wait");
  await expect(frame.locator(".verdict")).toHaveText("1 MACHINE NEEDS YOU");
  await expect(frame.locator(".over")).toHaveText("1 MACHINE");
  await expect(frame.locator(".chip")).toHaveText("21:53 · JUST NOW");
  await page.waitForTimeout(1000);
  await expect(frame).toBeVisible(); // it stays: the station never mounted
  await expect(page.locator(".lamp .lp")).toHaveCount(0);
  await expect(page.locator(".hm-needs .lb-need")).toHaveCount(2);
  expect(await page.locator(".broken").count()).toBe(0);
});
