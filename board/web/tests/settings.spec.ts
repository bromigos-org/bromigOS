// Settings: only what is real, and read-only. Lab (the name, the address, the door, the world and
// what root lets the page do), Notifications (the alerts' channels with their quiet hours, and
// the checks), Mascot (the command). No control here changes anything.
import { expect, test } from "@playwright/test";
import { open } from "./helpers";
import { copy, openReal, real, Service, whole } from "./service";

type P = import("@playwright/test").Page;
const row = (page: P, text: string) => page.locator(".rows li", { hasText: text });
/** A panel by its heading (a channel's own words may hold another panel's name). */
const panel = (page: P, title: string) => page.locator(".panel").filter({ has: page.locator("h2", { hasText: title }) });

test("Lab: the name, the address, the door and the world, as the server has them", async ({ page }) => {
  await open(page, "healthy", "settings/lab");
  await expect(page.locator(".sh-crumb")).toHaveText(/Settings › Lab$/);
  const rd = page.locator(".st-rd .rd");
  await expect(rd.nth(0)).toContainText("myserver");
  await expect(rd.nth(1)).toContainText("myserver.local");
  await expect(rd.nth(2)).toContainText("shows the apps");
  await expect(rd.nth(3)).toContainText("wick");
  await expect(panel(page, "THIS LAB")).toContainText("/etc/bromigos/server.toml");
});

test("Lab: what the page may do isn't claimed until the server says", async ({ page }) => {
  await open(page, "healthy", "settings/lab");
  const may = panel(page, "WHAT THIS PAGE MAY DO");
  await expect(may.locator(".rows li")).toHaveCount(4);
  await expect(may.locator(".rows li .st")).toHaveText(["not said", "not said", "not said", "not said"]);
  await expect(may.locator(".pl")).toHaveCount(1);
  await expect(may).toContainText('actions = ["restart"]');
});

test("Lab: with the server's list, each action is allowed or not, and none is a switch", async ({ page }) => {
  await open(page, "actions", "settings/lab");
  const may = panel(page, "WHAT THIS PAGE MAY DO");
  await expect(may.locator(".rows li .st")).toHaveText(["allowed", "allowed", "allowed", "allowed"]);
  await expect(may.locator(".pl")).toHaveCount(0);
  await expect(page.locator("#view").locator("button, input, select")).toHaveCount(0);
});

test("Notifications: each channel as the server lists it, its quiet hours, and what is wrong with one", async ({ page }) => {
  await open(page, "channels", "settings");
  await expect(page.locator(".sh-crumb")).toHaveText(/Settings › Notifications$/);
  const ch = panel(page, "CHANNELS");
  await expect(ch.locator("h2")).toContainText("CHANNELS · 2 on");
  await expect(ch.locator(".st-ch li")).toHaveCount(4);
  const discord = ch.locator(".st-ch li", { hasText: "Discord · discord" });
  await expect(discord).toContainText("critical, needs you · every alert · minimal detail");
  await expect(discord).toContainText("quiet 22:00-07:00, critical still goes");
  await expect(discord).toContainText("address set");
  await expect(discord.locator(".st")).toHaveText("on");
  // a channel whose last message didn't go, and one of whose settings the server doesn't use
  const ops = ch.locator(".st-ch li", { hasText: "Webhook · ops" });
  await expect(ops).toContainText("critical · drives, backups, job-results · full detail");
  await expect(ops).toContainText("the channel answered 404 (the address is gone)");
  await expect(ops).toContainText("setting not used: quiet is HH:MM-HH:MM, not 'late'");
  await expect(ops).toContainText("no quiet hours");
  await expect(ops.locator(".st")).toHaveText("needs a look");
  await expect(ch.locator(".st-ch li", { hasText: "Discord · spare" }).locator(".st")).toHaveText("off");
  await expect(ch.locator(".st-ch li", { hasText: "BRODEC" }).locator(".st")).toHaveText("not on this server");
  // neither an address nor a key is ever on the page
  await expect(page.locator("#view")).not.toContainText("discord.com");
  await expect(page.locator("#view")).not.toContainText("hooks.example");
});

test("Notifications: quiet hours are each channel's own, and only of channels that are on", async ({ page }) => {
  await open(page, "channels", "settings");
  const q = panel(page, "QUIET HOURS");
  await expect(q.locator(".rows li")).toHaveCount(1);
  await expect(q.locator(".rows li")).toContainText("22:00-07:00 · Discord · discord");
  await expect(q.locator(".rows li .chip")).toHaveText("CRITICAL STILL GOES");
});

test("Notifications with no channel of the server's own: said so, and no quiet hours are made up", async ({ page }) => {
  await open(page, "healthy", "settings");
  const ch = panel(page, "CHANNELS");
  await expect(ch.locator("h2")).toContainText("CHANNELS · 0 on");
  await expect(ch).toContainText("No channel of this server's own yet.");
  await expect(panel(page, "QUIET HOURS")).toContainText("there are no quiet hours to keep");
  await expect(panel(page, "QUIET HOURS").locator(".rows li")).toHaveCount(0);
});

test("Notifications: the checks, whether each could look, and what it raised", async ({ page }) => {
  await open(page, "needs-you", "settings");
  const checks = panel(page, "THE CHECKS");
  await expect(checks.locator("h2")).toContainText("THE CHECKS · 1");
  await expect(row(page, "disk.smart")).toContainText("1 raised");
  await expect(row(page, "disk.smart")).toContainText("looked");
});

test("Mascot: the three modes and the command, and nothing to press", async ({ page }) => {
  await open(page, "healthy", "settings/mascot");
  const m = panel(page, "STATIC");
  await expect(m.locator(".rows li")).toHaveCount(3);
  await expect(m).toContainText("bromigos mascot quiet");
  await expect(m).toContainText("~/.config/bromigos/mascot.toml");
  await expect(m.locator(".pl")).toHaveCount(1);
  await expect(page.locator("#view").locator("button, input, select")).toHaveCount(0);
});

test("the tabs not built stay planned, and aren't links", async ({ page }) => {
  await open(page, "healthy", "settings");
  await expect(page.locator(".sh-tabs .sh-tab.off")).toHaveCount(3);
  await expect(page.locator(".sh-tabs .sh-tab.off .pl")).toHaveCount(3);
  await expect(page.locator(".sh-tabs a.sh-tab")).toHaveText(["Lab", "Notifications", "Mascot"]);
});

test.describe("the real client, the service's real answers", () => {
  test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "the contract is the same at every width"));

  test("the real channels document on the page, and nothing but GETs", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.alerts_channels;
    const w = await openReal(page, s, "settings");
    const sent = real.boards.alerts_channels.alerts.channels.channels;
    await expect(page.locator(".st-ch li")).toHaveCount(sent.length);
    await expect(panel(page, "CHANNELS").locator("h2")).toContainText(`CHANNELS · ${sent.filter((c: { on: boolean }) => c.on).length} on`);
    await expect(page.locator(".st-ch li", { hasText: "Webhook · ops" })).toContainText(sent[1].last_error.why);
    await whole(page, w, "settings, the real channels");
    for (const tab of ["settings/lab", "settings/mascot"]) {
      await page.evaluate((h) => (window.location.hash = h), tab);
      await whole(page, w, tab);
    }
    expect(s.seen.filter((x) => x.method !== "GET")).toEqual([]);
  });

  test("the alerts unread on a real board: the page says so, and lists no channel", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.alerts_missing;
    await openReal(page, s, "settings");
    await expect(page.locator("#view")).toContainText("The alerts and their channels couldn't be read on the server");
    await expect(page.locator(".st-ch li")).toHaveCount(0);
    await expect(page.locator("#view")).not.toContainText("No channel of this server's own yet");
  });

  test("the alerts, their channels and the board's settings as anything else: nothing blanks, nothing is made up", async ({ page }) => {
    const s = new Service();
    const w = await openReal(page, s, "settings");
    const base = copy(real.boards.alerts_channels);
    for (const value of [null, {}, [], "x", 7, { channels: "x" }, { channels: [null, 7, "x", {}, { name: 3 }] }]) {
      s.board = { ...base, alerts: { ...base.alerts, channels: value }, settings: value, actions: value };
      await page.reload();
      await expect(panel(page, "THE CHECKS")).toBeVisible();
      await whole(page, w, `channels = ${JSON.stringify(value)}`);
      await page.evaluate(() => (window.location.hash = "settings/lab"));
      await expect(panel(page, "WHAT THIS PAGE MAY DO")).toBeVisible();
      await whole(page, w, `settings = ${JSON.stringify(value)}`);
      await page.evaluate(() => (window.location.hash = "settings"));
    }
  });

  test("a server that turned every action off: each is not allowed, and that is an answer, not a planned mark", async ({ page }) => {
    const s = new Service();
    s.board = { ...copy(real.boards.healthy), actions: [] };
    await openReal(page, s, "settings/lab");
    const may = panel(page, "WHAT THIS PAGE MAY DO");
    await expect(may.locator(".rows li .st")).toHaveText(["not allowed", "not allowed", "not allowed", "not allowed"]);
    await expect(may.locator(".pl")).toHaveCount(0);
    s.board = { ...copy(real.boards.healthy), actions: ["restart"] };
    await page.reload();
    await expect(may.locator(".rows li .st")).toHaveText(["allowed", "not allowed", "not allowed", "not allowed"]);
  });
});
