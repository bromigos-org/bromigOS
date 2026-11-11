// Layout that has to hold on every page: the rail's small marks on a machine (its state, and
// its update arrow) stay small, apart and readable; and the activity strip never covers the
// last row of a page or of a sheet, at either width.
import { expect, test, type Page } from "@playwright/test";
import { open, ROUTES } from "./helpers";

const box = async (page: Page, sel: string) => (await page.locator(sel).first().boundingBox())!;
const apart = (a: { x: number; y: number; width: number; height: number }, b: typeof a) =>
  a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y;

for (const [fixture, machine] of [["needs-you", "myserver"], ["lab", "mydesk"], ["lab", "myserver"]] as const)
  test(`the rail's marks on ${machine} (${fixture}): small, in their corners, apart`, async ({ page }, info) => {
    test.skip(info.project.name !== "desktop", "the machines are in the rail on a wide screen");
    await open(page, fixture, "home");
    const link = `.sh-rail a[data-m='${machine}']`;
    const entry = await box(page, link), state = await box(page, `${link} .sh-sd`), arrow = await box(page, `${link} .sh-up`), icon = await box(page, `${link} > svg.i:first-child`);
    // the update arrow is a corner mark, not a second icon over the machine's
    expect(arrow.width).toBeLessThanOrEqual(13);
    expect(arrow.height).toBeLessThanOrEqual(13);
    expect(arrow.width).toBeGreaterThanOrEqual(10);
    // the state's mark is big enough to read its shape
    expect(state.width).toBeGreaterThanOrEqual(13);
    expect(state.width).toBeLessThanOrEqual(16);
    expect(apart(arrow, state), "the arrow and the state mark overlap").toBe(true);
    // neither sits on the middle of the machine's icon, and both are inside the entry
    const mid = { x: icon.x + icon.width / 2 - 5, y: icon.y + icon.height / 2 - 5, width: 10, height: 10 };
    expect(apart(arrow, mid) && apart(state, mid), "a mark covers the machine's icon").toBe(true);
    for (const m of [arrow, state]) {
      expect(m.x).toBeGreaterThanOrEqual(entry.x);
      expect(m.x + m.width).toBeLessThanOrEqual(entry.x + entry.width);
      expect(m.y).toBeGreaterThanOrEqual(entry.y);
    }
    // the arrow to the left, the state to the right, both along the top
    expect(arrow.x + arrow.width / 2).toBeLessThan(icon.x + icon.width / 2);
    expect(state.x + state.width / 2).toBeGreaterThan(icon.x + icon.width / 2);
    // the machine's name has its own line under the icon
    const name = await box(page, `${link} .sh-rl`);
    expect(name.y, "the name runs into the icon").toBeGreaterThanOrEqual(icon.y + icon.height - 1);
  });

test("at phone width the machines, and their marks, are not in the bottom bar", async ({ page }, info) => {
  test.skip(info.project.name !== "phone", "the bottom bar");
  await open(page, "lab", "home");
  await expect(page.locator(".sh-rail .sh-up:visible, .sh-rail .sh-sd:visible")).toHaveCount(0);
  // the machines' states are on Home's tiles there, each a shape and a word
  await expect(page.locator(".hm-m .st")).toHaveCount(4);
});

/** After scrolling to the end, nothing of the page is under the strip (or, on a phone, the bar). */
async function clear(page: Page, where: string) {
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const got = await page.evaluate(() => {
    const view = document.querySelector("#view")!;
    const strip = document.querySelector(".sh-strip")!.getBoundingClientRect();
    const rail = document.querySelector(".sh-rail")!.getBoundingClientRect();
    const ends = [...view.querySelectorAll(":scope > *")].map((e) => e.getBoundingClientRect().bottom);
    return { end: Math.max(view.getBoundingClientRect().bottom, ...ends), strip: strip.top, stripEnd: strip.bottom, rail: rail.top, railIsBar: rail.width > 200, height: window.innerHeight };
  });
  expect(got.end, `${where}: the page ends under the activity strip`).toBeLessThanOrEqual(got.strip + 1);
  if (got.railIsBar) expect(got.stripEnd, `${where}: the strip is under the bottom bar`).toBeLessThanOrEqual(got.rail + 1);
  expect(got.stripEnd, `${where}: the strip is off the screen`).toBeLessThanOrEqual(got.height + 1);
}

for (const fixture of ["needs-you", "cant-read"])
  test(`${fixture}: the strip never covers the end of a page or a sheet`, async ({ page }) => {
    await open(page, fixture, "home");
    for (const hash of [...ROUTES.filter((r) => !r.fixture).map((r) => r.hash), "supply/add/navidrome", "supply/stacks"]) {
      await page.evaluate((h) => (window.location.hash = h), hash);
      await page.waitForFunction((h) => window.location.hash === `#${h}`, hash);
      await clear(page, `#${hash}`);
    }
  });

test("a sheet taller than the page under it still ends above the strip", async ({ page }) => {
  await open(page, "needs-you", "supply/add/navidrome");
  await expect(page.getByRole("dialog", { name: "Add Music" })).toBeVisible();
  // the page under the sheet made as short as a page can be, and the sheet longer than the screen
  await page.evaluate(() => {
    const under = document.querySelector("#view > .sh-under") as HTMLElement, sheet = document.querySelector("#view > .sh-sheet") as HTMLElement;
    under.style.height = "40px";
    under.style.overflow = "hidden";
    sheet.style.minHeight = "1600px";
  });
  await clear(page, "a short page under a long sheet");
});
