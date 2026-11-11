// Every route renders, in every page state, under the board's Content-Security-Policy, with no
// error, and nothing fetched from another site.
import { expect, test } from "@playwright/test";
import { open, ROUTES, STATES } from "./helpers";

for (const state of STATES)
  for (const r of ROUTES)
    test(`${state}: #${r.hash} renders`, async ({ page, baseURL }) => {
      const away: string[] = [];
      page.on("request", (q) => !q.url().startsWith(`${baseURL}/`) && !q.url().startsWith("data:") && away.push(q.url()));
      const { errors, csp } = await open(page, r.fixture ?? state, r.hash);
      await expect(page.locator(".sh-crumb")).toHaveText(r.crumb);
      await expect(page.locator("#view > *").first()).toBeVisible();
      await expect(page.locator(".sh-strip .strip")).toBeVisible();
      expect(errors).toEqual([]);
      expect(await csp()).toEqual([]);
      expect(away, "requests to another site").toEqual([]);
    });

test("an unknown route opens Home", async ({ page }) => {
  await open(page, "healthy", "no/such/place");
  await expect(page.locator(".sh-crumb")).toHaveText(/Home$/);
});
