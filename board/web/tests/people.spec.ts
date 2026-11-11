// People › Ways in: the browsers signed in to the board (the service's own list), signing one
// out, and the plain steps that sign another one in with a code. Household stays planned.
import { expect, test } from "@playwright/test";
import { open } from "./helpers";
import { copy, openReal, real, Service, whole } from "./service";

const rows = ".pp-browsers li";

test("Ways in: how you are signed in, and each signed-in browser", async ({ page }) => {
  await open(page, "healthy", "people/ways");
  await expect(page.locator(".sh-crumb")).toHaveText(/People › Ways in$/);
  await expect(page.locator(".pp-rd .rd").nth(0)).toContainText("2browsers");
  await expect(page.locator(".pp-rd .rd").nth(1)).toContainText("Firefox on Linux");
  await expect(page.locator(".pp-rd .rd").nth(3)).toContainText("owner");
  await expect(page.locator(rows)).toHaveCount(2);
  // this browser first, said to be this one
  await expect(page.locator(rows).first()).toContainText("Firefox on Linux");
  await expect(page.locator(rows).first()).toContainText("this browser");
  await expect(page.locator(rows).nth(1)).toContainText("Safari on a Mac");
  await expect(page.locator(rows).nth(1)).toContainText("last used 2 days ago");
});

test("signing another browser out takes it off the list, and says so", async ({ page }) => {
  await open(page, "healthy", "people/ways");
  await page.getByRole("button", { name: "Sign out Safari on a Mac" }).click();
  await expect(page.locator(rows)).toHaveCount(1);
  await expect(page.locator(".panel", { hasText: "SIGNED-IN BROWSERS" }).locator("[role=status]")).toHaveText("Safari on a Mac is signed out.");
  await expect(page.locator(".pp-rd .rd").nth(0)).toContainText("1browser");
});

test("signing this browser out goes back to the door", async ({ page }) => {
  await open(page, "healthy", "people/ways");
  await page.getByRole("button", { name: "Sign this browser out" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/The door$/);
});

test("the steps that sign another browser in: the code, the address, and what the code is good for", async ({ page }) => {
  await open(page, "healthy", "people/ways");
  const steps = page.locator(".panel", { hasText: "SIGN ANOTHER BROWSER IN" });
  await expect(steps.locator("ol li")).toHaveCount(3);
  await expect(steps).toContainText("sudo bromigos server board code");
  await expect(steps.locator("ol li").nth(1)).toContainText("myserver.local");
  await expect(steps).toContainText("10 minutes");
  await expect(steps).toContainText("One use");
  // the phone and the account aren't built: marked planned, and nothing to press
  await expect(steps.locator(".pl")).toHaveCount(1);
  await expect(steps.getByRole("button")).toHaveCount(0);
});

test("Household is planned, and shows no made-up person", async ({ page }) => {
  await open(page, "healthy", "people");
  await expect(page.locator(".stub")).toContainText("People › Household");
  await expect(page.locator(".stub .pl")).toHaveCount(1);
  await expect(page.locator(rows)).toHaveCount(0);
});

test.describe("the real client, the service's real answers", () => {
  test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "the contract is the same at every width"));

  test("the real session: its one browser, and the list read again when the tab is opened", async ({ page }) => {
    const s = new Service();
    const w = await openReal(page, s, "home");
    const before = s.count("/api/session");
    await page.getByRole("link", { name: "People", exact: true }).click();
    await page.getByRole("link", { name: "Ways in" }).click();
    await expect(page.locator(rows)).toHaveCount(1);
    await expect(page.locator(rows).first()).toContainText(real.http.session_signed_in.body.browsers[0].name);
    await expect.poll(() => s.count("/api/session")).toBeGreaterThan(before);
    expect(s.seen.filter((x) => x.method !== "GET")).toEqual([]);
    await whole(page, w, "ways in");
  });

  test("signing another browser out: the service's DELETE, with its header, and its new list", async ({ page }) => {
    const s = new Service();
    const mine = copy(real.http.session_signed_in.body.browsers[0]);
    s.browsers = [mine, { ...mine, id: "00000000000000a2", name: "Safari on a Mac", current: false, last_seen_at: mine.last_seen_at - 3 * 86_400_000 }];
    await openReal(page, s, "people/ways");
    await expect(page.locator(rows)).toHaveCount(2);
    await page.getByRole("button", { name: "Sign out Safari on a Mac" }).click();
    await expect(page.locator(rows)).toHaveCount(1);
    const del = s.seen.filter((x) => x.method === "DELETE");
    expect(del.map((x) => x.path)).toEqual(["/api/session/00000000000000a2"]);
    expect(del[0].headers["x-bromigos-board"]).toBe("1");
    expect(del[0].headers["content-type"]).toMatch(/^application\/json/);
  });

  test("a browser that was signed out elsewhere already: the server's words, and the list read again", async ({ page }) => {
    const s = new Service();
    const mine = copy(real.http.session_signed_in.body.browsers[0]);
    s.browsers = [mine, { ...mine, id: "00000000000000a2", name: "Safari on a Mac", current: false }];
    await openReal(page, s, "people/ways", { quiet: /404/ });
    await expect(page.locator(rows)).toHaveCount(2);
    s.browsers = [mine]; // it signed out by itself meanwhile
    await page.getByRole("button", { name: "Sign out Safari on a Mac" }).click();
    await expect(page.locator(".panel", { hasText: "SIGNED-IN BROWSERS" }).locator("[role=status]")).toHaveText(real.http.signout_other_unknown.body.error.words);
    await expect(page.locator(rows)).toHaveCount(1);
  });
});
