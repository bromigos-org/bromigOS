// Pictures of every route, for review: SHOTS=DIR npx playwright test shots. Skipped otherwise.
// Headless, from the fixture build; the pictures go to DIR/<project>/<state>-<route>.png.
import { test } from "@playwright/test";
import { open, ROUTES } from "./helpers";
import { WEBGL } from "./webgl";

test.use(WEBGL); // the holograms are drawn in this spec

const dir = process.env.SHOTS;
const STATES = (process.env.SHOTS_STATES ?? "needs-you").split(",");

test.describe("shots", () => {
  test.skip(!dir, "set SHOTS=DIR to take pictures");
  for (const state of STATES)
    for (const r of [...ROUTES, { hash: "", crumb: /./, fixture: "door" }, { hash: "signin", crumb: /./, fixture: "door" }, { hash: "", crumb: /./, fixture: "door-empty" }])
      test(`${state} ${r.fixture ?? ""} #${r.hash}`, async ({ page }, info) => {
        await open(page, r.fixture ?? state, r.hash);
        await page.waitForTimeout(300);
        const name = `${r.fixture ?? state}-${(r.hash || "door").replace(/\//g, "_")}`;
        await page.screenshot({ path: `${dir}/${info.project.name}/${name}.png`, fullPage: true });
        if (r.hash === "home" && state === STATES[0]) {
          await page.getByRole("button", { name: "Raise the drawer of jobs" }).click();
          await page.screenshot({ path: `${dir}/${info.project.name}/${state}-activity-drawer.png` });
          await page.keyboard.press("Escape");
          await page.getByRole("button", { name: "Depth" }).click();
          await page.screenshot({ path: `${dir}/${info.project.name}/${state}-depth-drawer.png` });
        }
      });
});
