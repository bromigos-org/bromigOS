// The shell's behaviour: the door and signing in with the one-time code, signing out, the
// world, the rail and its scope, the strip following the activity stream, and the drawers.
import { expect, test } from "@playwright/test";
import { WORLDS } from "../lib/api/types";
import { open } from "./helpers";

test("the door shows the apps and nothing else", async ({ page }) => {
  await open(page, "door");
  await expect(page.locator(".sh-crumb")).toHaveText(/The door$/);
  await expect(page.locator(".door-tiles .tile")).toHaveCount(6);
  await expect(page.locator(".door-tiles .tile").first()).toHaveAttribute("href", "https://photos-myserver.local");
  for (const gone of [".sh-rail", ".sh-strip", ".sh-search", ".menu.um"]) await expect(page.locator(gone)).toHaveCount(0);
  await expect(page.locator("#view")).not.toContainText(/v3\.3\.5|Running|GB|%/);
});

test("the door with nothing installed says so", async ({ page }) => {
  await open(page, "door-empty");
  await expect(page.getByText("Apps appear here to open")).toBeVisible();
});

test("signing in with the one-time code, and out again", async ({ page }) => {
  await open(page, "door");
  await page.getByRole("link", { name: "Sign in with a code" }).click();
  await expect(page.getByRole("dialog", { name: "Sign in" })).toBeVisible();
  const field = page.getByRole("textbox", { name: "One-time code" });
  await expect(field).toBeFocused();
  await field.fill("WRONG-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("#signin-why")).toContainText("isn't right");
  await field.fill(" kx7-42q ");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Home$/);
  await expect(page.locator(".sh-rail")).toBeVisible();
  await page.locator(".menu.um > summary").click();
  await page.getByRole("link", { name: /Sign out/ }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/The door$/);
  await expect(page.locator(".sh-rail")).toHaveCount(0);
});

test("a server that doesn't answer says so, and shows nothing made up", async ({ page }) => {
  await open(page, "unreachable");
  await expect(page.locator(".unreach")).toContainText("isn't answering");
});

for (const world of WORLDS)
  test(`the server's world: ${world}`, async ({ page }) => {
    await page.route("**/fixtures/healthy.json", async (route) => {
      const doc = await (await route.fetch()).json();
      await route.fulfill({ json: { ...doc, door: { ...doc.door, world } } });
    });
    await open(page, "healthy", "home");
    await expect(page.locator("html")).toHaveAttribute("data-world", world);
    const tok = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--phosphor").trim());
    expect(tok).toMatch(/^#[0-9a-f]{6}$/);
  });

test("a world the page doesn't know falls back to the Wick", async ({ page }) => {
  await page.route("**/fixtures/healthy.json", async (route) => {
    const doc = await (await route.fetch()).json();
    await route.fulfill({ json: { ...doc, door: { ...doc.door, world: "nowhere" } } });
  });
  await open(page, "healthy", "home");
  await expect(page.locator("html")).toHaveAttribute("data-world", "wick");
});

test("the rail: machines with their state, + and the places", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "the rail's machines show on a wide screen");
  await open(page, "lab", "home");
  await expect(page.locator(".sh-rail .sh-m")).toHaveCount(4);
  await expect(page.locator(".sh-rail a[data-m='node3']")).toHaveAttribute("title", /not seen for 2 h/);
  await expect(page.locator(".sh-rail a[data-m='mydesk'] .sh-up.sec")).toHaveCount(1);
  await expect(page.locator(".sh-rail a[aria-label='Cameras']")).toHaveCount(0);
  await page.locator(".sh-rail a[data-m='vault']").click();
  await expect(page.locator(".sh-crumb")).toHaveText(/vault›Overview$/);
  // picking a machine scopes the places to it; the chip lets go
  await page.locator(".sh-rail a[aria-label='Supply']").click();
  await expect(page.locator(".sh-scope")).toContainText("only vault");
  await page.getByRole("button", { name: "Show the whole lab" }).click();
  await expect(page.locator(".sh-scope")).toHaveCount(0);
});

test("Cameras earns its rail entry only when a machine runs it", async ({ page }) => {
  await open(page, "cameras", "home");
  await expect(page.locator(".sh-rail a[aria-label='Cameras']")).toHaveCount(1);
});

test("the strip follows the activity stream", async ({ page }) => {
  await open(page, "running", "home");
  const strip = page.locator(".sh-strip .strip");
  await expect(strip).toContainText("Backing up this server");
  await expect(strip).toHaveClass(/run/);
  await expect(strip).toContainText("Nothing running", { timeout: 5000 });
  await expect(strip).toContainText("Last: Backing up this server · done");
});

test("the strip puts the job that asks you first, and its drawer answers", async ({ page }) => {
  await open(page, "needs-you", "home");
  const strip = page.locator(".sh-strip .strip");
  await expect(strip).toHaveClass(/ask/);
  await expect(strip).toContainText("Replacing a drive");
  await page.getByRole("button", { name: "Raise the drawer of jobs" }).click();
  const drawer = page.getByRole("complementary", { name: "Activity" });
  await expect(drawer).toBeVisible();
  await expect(drawer.locator(".job").first()).toContainText("Swap the drive now");
  await expect(drawer.getByRole("button", { name: "I've swapped it" })).toBeVisible();
  await expect(drawer.locator(".job.ask ol.steps li")).toHaveCount(5);
  await expect(drawer.locator(".job", { hasText: "Updating Photos" })).toContainText("no answer in 2 minutes");
  await drawer.getByRole("link", { name: "Show all jobs" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Activity › Now$/);
  await expect(drawer).toHaveCount(0);
});

test("an alert with no job is the strip's when nothing asks", async ({ page }) => {
  await open(page, "alert", "home");
  await expect(page.locator(".sh-strip .strip")).toContainText("myserver · A drive is getting worse");
});

test("the Depth drawer opens on every page and closes", async ({ page }) => {
  await open(page, "healthy", "activity");
  await page.getByRole("button", { name: "Depth" }).click();
  const d = page.getByRole("complementary", { name: "Depth" });
  await expect(d).toContainText("bromigos activity show ID --json");
  await d.getByRole("button", { name: "Close Depth" }).click();
  await expect(d).toHaveCount(0);
});

test("tabs: planned ones are dim and not links", async ({ page }) => {
  await open(page, "healthy", "data");
  const tabs = page.getByRole("navigation", { name: "Data" });
  await expect(tabs.getByRole("link")).toHaveText(["Drives", "Backups", "Move in"]);
  await expect(tabs.locator(".sh-tab.off")).toContainText("Shares");
  await tabs.getByRole("link", { name: "Backups" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Data › Backups$/);
});

test("search finds an app and goes there", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "search is in the top bar on a wide screen");
  await open(page, "healthy", "home");
  await page.getByLabel("Ask VECTOR or search").fill("immich");
  await page.getByLabel("Ask VECTOR or search").press("Enter");
  await expect(page).toHaveURL(/#app\/photos$/);
});
