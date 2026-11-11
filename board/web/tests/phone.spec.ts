// At 390 px: no sideways scroll on any route, the rail is the bar along the bottom with the
// places only, and the strip sits above it.
import { expect, test } from "@playwright/test";
import { open, ROUTES } from "./helpers";

test.beforeEach(({}, info) => test.skip(info.project.name !== "phone", "the phone layout"));

for (const r of ROUTES)
  test(`#${r.hash} fits 390 px`, async ({ page }) => {
    await open(page, r.fixture ?? "needs-you", r.hash);
    const w = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(w[0], "sideways scroll").toBeLessThanOrEqual(w[1]);
  });

test("the rail is the bottom bar, the strip above it", async ({ page }) => {
  await open(page, "lab", "supply");
  const vh = page.viewportSize()!.height;
  const rail = (await page.locator(".sh-rail").boundingBox())!;
  expect(Math.round(rail.y + rail.height)).toBe(vh);
  expect(rail.width).toBe(390);
  expect(rail.height, "one row of icons").toBeLessThan(70);
  const strip = (await page.locator(".sh-strip").boundingBox())!;
  expect(Math.round(strip.y + strip.height)).toBeLessThanOrEqual(Math.round(rail.y) + 1);
  // the places stay; the machines, + and the lab's name leave the bar
  await expect(page.locator(".sh-rail a[aria-label='Supply']")).toBeVisible();
  await expect(page.locator(".sh-rail .sh-m").first()).toBeHidden();
  await expect(page.locator(".sh-rail .sh-lab")).toBeHidden();
  await expect(page.locator(".sh-rail a[aria-label='Add a machine']")).toBeHidden();
  await expect(page.getByLabel("Ask VECTOR or search")).toBeHidden();
});

test("the door at 390 px", async ({ page }) => {
  await open(page, "door");
  await expect(page.locator(".sh-rail")).toHaveCount(0);
  const w = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(w[0]).toBeLessThanOrEqual(w[1]);
});
