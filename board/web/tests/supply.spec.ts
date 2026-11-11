// Supply: Installed (the tiles, their readings, the sort), Browse (every catalogue item, found
// by name, with Add), the Add sheet (what it asks, the command, the planned confirm) and Updates.
import { expect, test } from "@playwright/test";
import { open } from "./helpers";

test("Installed: every installed app, what they use, and the sort", async ({ page }) => {
  await open(page, "healthy", "supply");
  await expect(page.locator(".tiles.apps .tile")).toHaveCount(10);
  await expect(page.locator(".su-rd .rd").first()).toContainText("10of 10");
  await page.locator("label[for=su-sort-memory]").click();
  await expect(page.locator(".tiles.apps .tile").first()).toContainText("Photos");
});

test("Installed with nothing installed points at Browse", async ({ page }) => {
  await open(page, "setup", "supply");
  await expect(page.locator(".stub")).toContainText("Nothing is installed yet.");
});

test("Browse: the catalogue by group, found by name, with Add", async ({ page }) => {
  await open(page, "healthy", "supply/browse");
  await expect(page.locator(".su-group")).not.toHaveCount(0);
  await expect(page.locator(".tile.in", { hasText: "Photos" })).toHaveCount(1);
  await page.getByLabel("Find an app").fill("navidrome");
  await expect(page.locator(".su-group .tile")).toHaveCount(1);
  await page.getByRole("link", { name: "Add Music" }).click();
  const sheet = page.getByRole("dialog", { name: "Add Music" });
  await expect(sheet).toContainText("NAVIDROME");
  await expect(sheet).toContainText("sudo bromigos lab apps add navidrome --plan");
  await expect(sheet.locator(".pl")).toHaveCount(1);
  await sheet.getByRole("link", { name: "Close" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Supply › Browse$/);
});

test("Updates: the system's, and each app with one waiting", async ({ page }) => {
  await open(page, "healthy", "supply/updates");
  await expect(page.locator(".panel", { hasText: "THE SYSTEM" })).toContainText("Updates by itself");
  const apps = page.locator(".panel", { hasText: "THE APPS" });
  await expect(apps).toContainText("Photos v3.3.5 → v3.3.6");
  await expect(apps).toContainText("Uptime 2.5.8 → 2.5.9");
});
