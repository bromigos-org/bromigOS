// Data: Drives from the drive health document (its verdicts, what changed on a drive, the
// planned pool and layouts), Backups from the backups document (the last good copy, where
// they go, the proof), and Move in, planned.
import { expect, test } from "@playwright/test";
import { open } from "./helpers";

test("Drives, healthy: every drive and the verdict", async ({ page }) => {
  await open(page, "healthy", "data");
  await expect(page.locator(".dt-stage .verdict")).toHaveText("ALL DRIVES HEALTHY");
  await expect(page.locator(".dt-bay")).toHaveCount(3);
  await expect(page.locator(".dt-stage .chip")).toHaveText("READ 12 MIN AGO");
  await expect(page.locator(".panel", { hasText: "THE POOL" }).locator(".pl")).toHaveCount(1);
});

test("Drives, getting worse: what changed and what to do", async ({ page }) => {
  await open(page, "needs-you", "data");
  await expect(page.locator(".dt-stage .verdict")).toHaveText("1 GETTING WORSE");
  const changed = page.locator(".panel", { hasText: "SDB · WHAT CHANGED" });
  await expect(changed).toContainText("reallocated sectors rose from 0 to 8 in the last 3 days");
  await expect(changed).toContainText("Back up now, and plan to replace it.");
  await expect(changed.locator(".pl")).toHaveCount(1);
});

test("Backups: the last good copy, where they go and the proof", async ({ page }) => {
  await open(page, "healthy", "data/backups");
  await expect(page.locator(".bk-stage .verdict")).toHaveText("BACKED UP 8 H AGO");
  await expect(page.locator(".bk-big b")).toHaveText("06:08");
  await expect(page.locator(".bk-stage .st-top .over")).toHaveText("2 DESTINATIONS · 17 KEPT");
  const where = page.locator(".panel", { hasText: "WHERE THEY GO" });
  await expect(where).toContainText("S3");
  await expect(where).toContainText("Go Bag");
  await expect(where).toContainText("carried away");
  await expect(page.locator(".panel", { hasText: "THE PROOF" })).toContainText("passed 12 days ago");
  await expect(page.locator(".panel", { hasText: "GET FILES BACK" }).locator(".pl")).toHaveCount(1);
});

test("Backups that couldn't be read say so", async ({ page }) => {
  await page.route("**/fixtures/healthy.json", async (route) => {
    const doc = await (await route.fetch()).json();
    await route.fulfill({ json: { ...doc, board: { ...doc.board, backups: null } } });
  });
  await open(page, "healthy", "data/backups");
  await expect(page.locator("#view")).toContainText("The backups couldn't be read on the server.");
});

test("Move in is planned", async ({ page }) => {
  await open(page, "healthy", "data/move");
  await expect(page.locator(".panel", { hasText: "MOVE IN" }).locator(".pl").first()).toBeVisible();
});
