// Reduced motion holds every animation: with it, nothing on the page animates, even while a job
// runs (its Pulse) and under the pointer (the icons' hover moves). Without it, they do, so this
// test can fail.
import { expect, test } from "@playwright/test";
import { open } from "./helpers";

const running = (page: import("@playwright/test").Page) =>
  page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length);

test("without reduced motion, a running job pulses", async ({ page }) => {
  await open(page, "running", "home");
  await expect(page.locator(".strip .pulse")).toBeVisible();
  expect(await running(page)).toBeGreaterThan(0);
});

test.describe("with reduced motion", () => {
  test.use({ reducedMotion: "reduce" });
  for (const hash of ["home", "supply", "data", "m/myserver"])
    test(`#${hash}: nothing moves`, async ({ page }) => {
      await open(page, "running", hash);
      await page.getByRole("button", { name: "Raise the drawer of jobs" }).click();
      await expect(page.locator("#sh-actd .pulse").first()).toBeVisible();
      expect(await running(page)).toBe(0);
      await page.getByRole("button", { name: "Depth" }).hover();
      expect(await running(page)).toBe(0);
    });
});
