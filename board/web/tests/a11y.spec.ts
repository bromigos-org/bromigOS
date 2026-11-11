// Every control has a hint (a title: what it is and what it does) and an accessible name, and
// axe finds nothing, on every route, signed in and at the door, with the drawers open too.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { CONTROLS, open, ROUTES } from "./helpers";
import { WEBGL } from "./webgl";

test.use(WEBGL); // the holograms are drawn in this spec

async function everyControl(page: Page, where: string) {
  const all = page.locator(CONTROLS);
  const n = await all.count();
  let seen = 0;
  for (let i = 0; i < n; i++) {
    const c = all.nth(i);
    if (!(await c.isVisible())) continue;
    seen++;
    const what = `${where}: ${await c.evaluate((e) => e.outerHTML.slice(0, 140))}`;
    expect(((await c.getAttribute("title")) ?? "").trim(), `${what} has no hint`).not.toBe("");
    await expect(c, `${what} has no accessible name`).toHaveAccessibleName(/\S/);
  }
  expect(seen, `${where}: no controls found`).toBeGreaterThan(0);
}

async function axe(page: Page, where: string) {
  const r = await new AxeBuilder({ page }).analyze();
  expect(r.violations.map((v) => `${where}: ${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`)).toEqual([]);
}

for (const r of ROUTES)
  test(`#${r.hash}: hints, names and axe`, async ({ page }) => {
    await open(page, r.fixture ?? "needs-you", r.hash);
    await everyControl(page, r.hash);
    await axe(page, r.hash);
  });

test("the drawers, the You menu and search: hints, names and axe", async ({ page }) => {
  await open(page, "needs-you", "home");
  await page.getByRole("button", { name: "Raise the drawer of jobs" }).click();
  await expect(page.locator("#sh-actd")).toBeVisible();
  await everyControl(page, "activity drawer");
  await axe(page, "activity drawer");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Depth" }).click();
  await expect(page.locator("#sh-depthd")).toBeVisible();
  await everyControl(page, "depth drawer");
  await axe(page, "depth drawer");
  await page.keyboard.press("Escape");
  if (await page.getByLabel("Ask VECTOR or search").isVisible()) {
    await page.getByLabel("Ask VECTOR or search").fill("pho");
    await expect(page.locator(".sh-found")).toBeVisible();
    await everyControl(page, "search");
    await page.getByLabel("Ask VECTOR or search").fill("");
  }
  await page.locator(".menu.um > summary").click();
  await everyControl(page, "you menu");
  await axe(page, "you menu");
});

for (const [fixture, hash] of [["door", ""], ["door-empty", ""], ["door", "signin"], ["unreachable", ""]])
  test(`the door (${fixture}${hash ? ` #${hash}` : ""}): hints, names and axe`, async ({ page }) => {
    await open(page, fixture, hash);
    await everyControl(page, `door ${fixture}`);
    await axe(page, `door ${fixture}`);
  });
