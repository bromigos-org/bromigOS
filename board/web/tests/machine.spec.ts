// A machine's page: Overview's hero, needs and reading tiles from the board's documents; Vitals'
// gauges and the ECharts trend (and its planned state when the server keeps no trends);
// Hardware's parts; Set-up on a first run.
import { expect, test } from "@playwright/test";
import { open } from "./helpers";

test("Overview, healthy: the verdict, the lit groups, the three readings and the apps", async ({ page }) => {
  await open(page, "healthy", "m/myserver");
  const hero = page.locator(".stage.board");
  await expect(hero.locator(".verdict")).toHaveText("ALL SYSTEMS NOMINAL");
  await expect(hero.locator(".over")).toHaveText("5 OF 8 GROUPS LIT");
  await expect(hero.locator(".mod.on")).toHaveCount(5);
  await expect(hero.locator(".mod", { hasText: "GAMES" })).toContainText("empty");
  await expect(page.locator(".rt", { hasText: "STORAGE" })).toContainText("healthy");
  await expect(page.locator(".rt", { hasText: "BACKUPS" })).toContainText("PROVEN 12 DAYS AGO");
  await expect(page.locator(".rt", { hasText: "UPDATES" })).toContainText("came back healthy");
  await expect(page.locator(".mc-apps .tile")).toHaveCount(7);
  await expect(page.locator(".mc-parts .chip")).toHaveCount(3);
  await expect(page.locator(".mc-apps .tile", { hasText: "Photos" })).toContainText("Last photo backed up 2 hours ago");
});

test("Overview, one thing wrong: the verdict, the drive and what fixed itself", async ({ page }) => {
  await open(page, "needs-you", "m/myserver");
  await expect(page.locator(".stage.board .verdict")).toHaveText("2 THINGS NEED YOU");
  await expect(page.locator(".rt", { hasText: "STORAGE" })).toContainText("getting worse");
  await expect(page.locator(".panel", { hasText: "FIXED BY ITSELF" })).toContainText("Updating Photos");
  await expect(page.locator(".panel", { hasText: "FIXED BY ITSELF" })).toContainText("It failed and put things back by itself.");
  await page.locator(".rt", { hasText: "STORAGE" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Data › Drives$/);
});

test("the hero draws the rack: one canvas, and something on it", async ({ page }) => {
  const { errors } = await open(page, "healthy", "m/myserver");
  const mount = page.locator(".holo-mount");
  await expect(mount).toHaveAttribute("aria-label", "myserver's hologram");
  await expect(mount).toHaveClass(/drawn/, { timeout: 30_000 });
  await expect(page.locator("canvas")).toHaveCount(1);
  await expect(mount.locator("svg.gl")).toHaveCount(0);
  // the canvas carries a picture: the hero looks different with it than without it
  const rack = page.locator(".st-rack");
  await expect
    .poll(async () => {
      const withIt = await rack.screenshot();
      await page.locator("canvas").evaluate((c) => ((c as HTMLElement).hidden = true));
      const without = await rack.screenshot();
      await page.locator("canvas").evaluate((c) => ((c as HTMLElement).hidden = false));
      return Buffer.compare(withIt, without) !== 0;
    }, { timeout: 20_000 })
    .toBe(true);
  expect(errors).toEqual([]);
});

test("without WebGL the machine's glyph stays, and nothing breaks", async ({ page }) => {
  await page.addInitScript(() => {
    const get = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) {
      return /webgl/.test(kind) ? null : (get as any).call(this, kind, ...rest);
    } as typeof get;
  });
  const failures: string[] = [];
  page.on("pageerror", (e) => failures.push(e.message));
  await page.goto("/?fixture=healthy#m/myserver");
  await expect(page.locator(".stage.board .verdict")).toHaveText("ALL SYSTEMS NOMINAL");
  await expect(page.locator(".holo-mount svg.gl")).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(page.locator(".holo-mount")).not.toHaveClass(/drawn/);
  await expect(page.locator(".holo-mount canvas")).toHaveCount(0);
  expect(await page.locator(".broken").count()).toBe(0);
  expect(failures).toEqual([]);
});

test("a model that fails to load once is asked for again by the next view", async ({ page }) => {
  let asked = 0;
  await page.route("**/holo/rack.bin", (route) => (++asked === 1 ? route.fulfill({ status: 503, body: "" }) : route.fallback()));
  await page.goto("/?fixture=healthy#m/myserver");
  await expect(page.locator(".holo-mount svg.gl")).toBeVisible();
  await expect.poll(() => asked).toBe(1);
  // away and back: the failed load wasn't kept, and no half-made view is left behind
  await page.evaluate(() => (window.location.hash = "home"));
  await expect(page.locator(".stage.lamp")).toBeVisible();
  await page.evaluate(() => (window.location.hash = "m/myserver"));
  await expect(page.locator(".holo-mount")).toHaveClass(/drawn/, { timeout: 30_000 });
  expect(asked).toBe(2);
  await expect(page.locator("canvas")).toHaveCount(1);
});

test("Vitals: four gauges, then the trend, series by series", async ({ page }) => {
  await open(page, "healthy", "m/myserver/vitals");
  await expect(page.locator(".vt-stage .verdict")).toHaveText("VITALS NOMINAL");
  await expect(page.locator(".vt-g .vt-fig")).toHaveText(["23%", "7.8GB", "38°C", "34"]);
  const trend = page.locator(".vt-trends");
  await expect(trend.locator(".trend canvas")).toBeAttached();
  await expect(trend.locator(".vt-chh .k")).toHaveText("Processor");
  await trend.getByText("Memory", { exact: true }).click();
  await expect(trend.locator(".vt-chh .k")).toHaveText("Memory");
  await expect(trend.locator("table.sr-only tbody tr")).toHaveCount(97);
  await trend.getByText("7 D").click();
  await expect(trend.locator(".vt-none")).toContainText("Trends aren't kept on this server yet");
  await expect(trend.locator(".vt-none .pl")).toHaveCount(1);
});

test("Vitals with no trends kept: planned, and nothing drawn", async ({ page }) => {
  await open(page, "needs-you", "m/myserver/vitals");
  await expect(page.locator(".vt-trends .vt-none")).toContainText("Trends aren't kept");
  await expect(page.locator(".vt-trends .trend")).toHaveCount(0);
});

test("Vitals of a machine that reports nothing: not measured", async ({ page }) => {
  await open(page, "lab", "m/node3/vitals");
  await expect(page.locator(".vt-stage .verdict")).toHaveText("NOT MEASURED");
  await expect(page.locator(".vt-g.q")).toHaveCount(4);
});

test("Hardware: the parts, the card, and system versions planned", async ({ page }) => {
  await open(page, "needs-you", "m/myserver/hardware");
  await expect(page.locator(".hw-part", { hasText: "PROCESSOR" }).locator(".v")).toContainText("4");
  await expect(page.locator(".hw-part", { hasText: "MEMORY" }).locator(".v")).toContainText("16");
  await expect(page.locator(".hw-part", { hasText: "DRIVES" })).toContainText("getting worse");
  await expect(page.locator(".hw-part", { hasText: "GRAPHICS CARD" })).toContainText("No graphics card for it here");
  await expect(page.locator(".panel", { hasText: "SYSTEM VERSIONS" }).locator(".pl")).toHaveCount(1);
});

test("a first run shows Set-up in Overview's place", async ({ page }) => {
  await open(page, "setup", "m/myserver");
  await expect(page.locator(".sh-tab.on")).toHaveText("Overview");
  await expect(page.locator(".panel", { hasText: "SET-UP" })).toBeVisible();
});

test("a machine the lab doesn't have says so", async ({ page }) => {
  await open(page, "healthy", "m/nosuch");
  await expect(page.locator("#view")).toContainText("No machine called nosuch is in this lab.");
});
