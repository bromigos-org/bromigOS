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
  await expect(page.locator(".stage.board .verdict")).toHaveText("1 THING NEEDS YOU");
  await expect(page.locator(".rt", { hasText: "STORAGE" })).toContainText("getting worse");
  await expect(page.locator(".panel", { hasText: "FIXED BY ITSELF" })).toContainText("Photos' update was put back");
  await page.locator(".rt", { hasText: "STORAGE" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Data › Drives$/);
});

test("the hero draws the rack, or keeps its glyph without WebGL, with one context at most", async ({ page }) => {
  const { errors } = await open(page, "healthy", "m/myserver");
  const mount = page.locator(".holo-mount");
  await expect(mount).toHaveAttribute("aria-label", "myserver's hologram");
  await expect(mount.locator("canvas, svg.gl").first()).toBeAttached();
  await page.waitForTimeout(1500);
  expect(await page.locator("canvas").count()).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
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
