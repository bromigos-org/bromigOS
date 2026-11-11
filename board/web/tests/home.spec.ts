// Home: the hero's status line (the station's own; tests/lamplight.spec.ts has the station),
// NEEDS YOU with each item's machine and where it is fixed, This week marked planned, and a tile
// per machine whose readings go grey when old.
import { expect, test } from "@playwright/test";
import { open, READ_AT, VERDICT } from "./helpers";

test("healthy: all machines nominal, nothing needs you", async ({ page }) => {
  await open(page, "healthy", "home");
  await expect(page.locator("[data-lamplight='mount']")).toHaveCount(1);
  await expect(page.locator(".lamp.on")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(VERDICT)).toHaveText("ALL MACHINES NOMINAL");
  await expect(page.locator(".lamp .readout").first()).toHaveAttribute("title", "1 of 1 machine answers now");
  await expect(page.locator(READ_AT)).toHaveText("21:53 · JUST NOW");
  await expect(page.locator(".hm-needs")).toContainText("NEEDS YOU · 0");
  await expect(page.locator(".hm-needs .lb-need")).toHaveCount(0);
});

test("needs you: the verdict, the item and where it is fixed", async ({ page }) => {
  await open(page, "needs-you", "home");
  await expect(page.locator(VERDICT)).toHaveText("1 MACHINE NEEDS YOU");
  const need = page.locator(".hm-needs .lb-need");
  await expect(need).toHaveCount(2);
  await expect(need.first()).toContainText("A drive is getting worse: WDC WD40EFRX-68N32N0 (sdb) · myserver");
  await expect(need.nth(1)).toContainText("Replacing a drive: sdb · myserver");
  await need.first().getByRole("link").click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Data › Drives$/);
});

test("This week is planned and shows no number", async ({ page }) => {
  await open(page, "healthy", "home");
  const week = page.locator(".hm-week");
  await expect(week.locator(".pl")).toHaveCount(1);
  await expect(week.locator(".rd .v")).toHaveText(["·", "·", "·", "·", "·"]);
});

test("a tile per machine, with its readings and its page", async ({ page }) => {
  await open(page, "lab", "home");
  await expect(page.locator(".hm-m")).toHaveCount(4);
  const my = page.locator(".hm-m", { hasText: "myserver" });
  await expect(my).toContainText("23 %");
  await expect(my).toContainText("49 %");
  await expect(my).toContainText("38 °C");
  await expect(page.locator(".hm-m", { hasText: "node3" })).toContainText("no readings");
  await my.click();
  await expect(page.locator(".sh-crumb")).toHaveText(/myserver›Overview$/);
});

test("stale: the verdict says how old, and the readings go grey", async ({ page }) => {
  await open(page, "stale", "home");
  // just opened: the page is still reading; after that, how old the server's reading is
  await expect(page.locator(VERDICT)).toHaveText("READING THE SERVER");
  await expect(page.locator(VERDICT)).toHaveText("NOT READ FOR 5 MIN", { timeout: 20_000 });
  await expect(page.locator(".hm-m .spec.q")).toHaveCount(3);
});

test("first run: Home points at the server's Set-up", async ({ page }) => {
  await open(page, "setup", "home");
  await expect(page.locator(VERDICT)).toHaveText("NOTHING INSTALLED YET");
  await page.getByRole("link", { name: "Set up myserver" }).click();
  await expect(page).toHaveURL(/#m\/myserver\/setup$/);
});
