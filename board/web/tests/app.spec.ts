// One app's page (#app/ID): what it is, where it answers, its state, what it takes, where its
// data lives, the server's backups, its update, and the commands that look closer. Restart and
// Remove are the service's actions: offered only when the server says the page may, and sent
// exactly as the service asks. Deleting data also takes the app's id typed and a fresh code.
import { expect, test } from "@playwright/test";
import { open } from "./helpers";
import { Answer, copy, openReal, real, Service, whole } from "./service";

const head = ".apphead";

test("an app: what it is, its state, what it takes, where it answers", async ({ page }) => {
  await open(page, "healthy", "app/photos");
  await expect(page.locator(".sh-crumb")).toHaveText(/Supply › Photos$/);
  await expect(page.locator(`${head} h2`)).toHaveText("PHOTOS");
  await expect(page.locator(`${head} .chip`).first()).toHaveText("IMMICH · v3.3.5");
  await expect(page.locator(`${head} .st`)).toHaveText("Running");
  await expect(page.getByRole("link", { name: "Open Photos" }).first()).toHaveAttribute("href", "https://photos-myserver.local");
  const takes = page.locator(".panel", { hasText: "WHAT IT TAKES" });
  await expect(takes.locator(".rd").nth(0)).toContainText("2GB");
  await expect(takes.locator(".rd").nth(0)).toContainText("used now");
  await expect(takes.locator(".rd").nth(1)).toContainText("38GB");
  await expect(takes.locator(".rd").nth(3)).toContainText("photos-myserver.local");
  await expect(takes.locator(".rd").nth(3)).toContainText("port 2283");
});

test("an app: where its data lives, the server's backups, its update, and the commands", async ({ page }) => {
  await open(page, "healthy", "app/photos");
  const data = page.locator(".panel", { hasText: "WHERE ITS DATA LIVES" });
  await expect(data).toContainText("/srv/apps/photos");
  await expect(data).toContainText("38 GB");
  await expect(data).toContainText("This server's backups");
  // the page doesn't know when the app was installed, so it never says the last backup holds it
  await expect(data).toContainText("The server's backups include /srv/apps.");
  await expect(data).not.toContainText("holds /srv/apps");
  await expect(data).not.toContainText("so this folder");
  await expect(data.getByRole("link", { name: "OPEN" })).toHaveAttribute("href", "#data/backups");
  const up = page.locator(".panel", { hasText: "UPDATES" });
  await expect(up.locator(".vers")).toContainText("v3.3.5");
  await expect(up.locator(".vers")).toContainText("v3.3.6");
  const cmds = page.locator("#app-commands");
  await expect(cmds).toContainText("bromigos lab apps logs photos -f");
  await expect(cmds).toContainText("bromigos lab apps show photos");
  await expect(cmds).toContainText("sudo bromigos lab apps restart photos");
  // restore points aren't built: marked planned, with nothing drawn as if they were
  await expect(page.locator(".panel", { hasText: "RESTORE POINTS" }).locator(".pl")).toHaveCount(1);
});

test("an app that doesn't report updates says so, and is never called up to date", async ({ page }) => {
  await open(page, "healthy", "app/passwords");
  const up = page.locator(".panel", { hasText: "UPDATES" });
  await expect(up).toContainText("Passwords doesn't report updates yet");
  await expect(up).not.toContainText("up to date");
  await expect(up.locator(".pl")).toHaveCount(1);
});

test("restart and remove aren't offered until the server says the page may", async ({ page }) => {
  await open(page, "healthy", "app/photos");
  await expect(page.getByRole("button", { name: "Restart Photos" })).toHaveCount(0);
  await page.getByRole("link", { name: "Remove Photos" }).click();
  const sheet = page.getByRole("dialog", { name: "Remove Photos" });
  await expect(sheet).toContainText("Its data stays · /srv/apps/photos · 38 GB");
  await expect(sheet).toContainText("sudo bromigos lab apps remove photos --plan");
  await expect(sheet).toContainText("sudo bromigos lab apps remove photos --delete-data");
  await expect(sheet.getByRole("button")).toHaveCount(0);
  await expect(sheet.locator("input")).toHaveCount(0);
  await expect(sheet.locator(".pl")).toHaveCount(1);
  // a long command wraps inside the sheet: the page never scrolls sideways
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await sheet.getByRole("link", { name: "Close" }).click();
  await expect(page.locator(`${head} h2`)).toHaveText("PHOTOS");
});

test("with the server's leave: restart is a control, and removing is two separate choices", async ({ page }) => {
  await open(page, "actions", "app/photos");
  await page.getByRole("button", { name: "Restart Photos" }).click();
  await expect(page.locator(".panel", { has: page.locator(head) }).locator("[role=status]")).toContainText("Its steps are in the activity strip.");
  // the command isn't repeated where the control is
  await expect(page.locator("#app-commands")).not.toContainText("apps restart photos");
  await page.getByRole("link", { name: "Remove Photos" }).click();
  const sheet = page.getByRole("dialog", { name: "Remove Photos" });
  await expect(sheet.getByRole("button", { name: "Remove, keep its data" })).toBeVisible();
  const del = sheet.getByRole("button", { name: "Remove and delete data" });
  await expect(del).toHaveAttribute("aria-disabled", "true");
  await sheet.getByLabel(/The app's id/).fill("photos");
  await expect(del).toHaveAttribute("aria-disabled", "true"); // the id alone isn't enough: a fresh code too
  await sheet.getByLabel("One-time code").fill("kx7 42q");
  await expect(del).toHaveAttribute("aria-disabled", "false");
});

test("an app the server won't remove says why, and offers nothing to press", async ({ page }) => {
  await open(page, "actions", "app/caddy");
  await expect(page.getByRole("link", { name: "Remove Front door" })).toHaveCount(0);
  await expect(page.locator(".panel", { hasText: "NEEDED BY" })).toContainText("Passwords");
  await page.goto("/?fixture=actions#app/caddy/remove");
  const sheet = page.getByRole("dialog", { name: "Remove Front door" });
  await expect(sheet).toContainText("Passwords needs it: remove that first.");
  await expect(sheet.getByRole("button")).toHaveCount(0);
});

test("an app that isn't installed, and one the catalogue doesn't have", async ({ page }) => {
  await open(page, "healthy", "app/navidrome");
  await expect(page.locator(`${head} h2`)).toHaveText("MUSIC");
  await expect(page.locator(head)).toContainText("NOT INSTALLED");
  await expect(page.getByRole("link", { name: "Add Music" })).toHaveAttribute("href", "#supply/add/navidrome");
  await expect(page.getByRole("link", { name: "Remove Music" })).toHaveCount(0);
  await expect(page.locator(".panel", { hasText: "WHERE ITS DATA LIVES" })).toHaveCount(0);
  await page.goto("/?fixture=healthy#app/nothere");
  await expect(page.locator("#view")).toContainText("No app called nothere is in the catalogue.");
});

test("the apps unread: the page says so, and shows no app", async ({ page }) => {
  await open(page, "cant-read", "app/photos");
  await expect(page.locator("#view")).toContainText("The apps couldn't be read on the server");
  await expect(page.locator(head)).toHaveCount(0);
});

test.describe("the real client, the service's real answers", () => {
  test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "the contract is the same at every width"));

  test("a real tile: the page says what the service sent, and asks nothing but GETs", async ({ page }) => {
    const s = new Service();
    // a server that lets the page do nothing (root's [board] actions = []): no control at all
    s.board = { ...copy(real.boards.healthy), actions: [] };
    const w = await openReal(page, s, "app/photos");
    const t = real.boards.healthy.apps.find((a: { id: string }) => a.id === "photos");
    await expect(page.locator(`${head} h2`)).toHaveText("PHOTOS");
    await expect(page.locator(`${head} .chip`).first()).toHaveText(`${t.app.toUpperCase()} · ${t.version}`);
    await expect(page.locator(".panel", { hasText: "WHERE ITS DATA LIVES" })).toContainText("348 KB");
    // nothing is allowed: no control that changes anything
    await expect(page.getByRole("button", { name: "Restart Photos" })).toHaveCount(0);
    await expect(page.locator(".panel", { hasText: "UPDATES" })).toContainText("doesn't report updates yet");
    expect(s.seen.filter((x) => x.method !== "GET")).toEqual([]);
    await whole(page, w, "one app");
  });

  test("a real tile that measures nothing: not measured, never a zero", async ({ page }) => {
    const s = new Service();
    await openReal(page, s, "app/caddy");
    const takes = page.locator(".panel", { hasText: "WHAT IT TAKES" });
    await expect(takes.locator(".rd").nth(1)).toContainText("not measured");
    await expect(takes.locator(".rd").nth(1).locator(".v")).toHaveText("·");
    await expect(page.locator(".panel", { hasText: "WHERE ITS DATA LIVES" })).toContainText("SIZE NOT MEASURED");
  });

  test("restart and remove are sent as the service asks, and a refusal is said in its words", async ({ page }) => {
    const s = new Service();
    s.board = { ...copy(real.boards.healthy), actions: ["add", "restart", "remove", "delete-data"] };
    s.actions = new Answer(403, { body: { error: { code: "not-allowed", words: "This server doesn't let the board do that ([board] actions in /etc/bromigos/server.toml)." } } });
    await openReal(page, s, "app/photos", { quiet: /403/ });
    const said = page.locator(".panel", { has: page.locator(head) }).locator("[role=status]");
    await page.getByRole("button", { name: "Restart Photos" }).click();
    await expect(said).toHaveText("This server doesn't let the board do that ([board] actions in /etc/bromigos/server.toml).");
    s.actions = { schema: 1, ok: true, job: "20261110-2113-app.restart-photos-1a2b", request: "r1", words: "Restarting Photos." };
    await page.getByRole("button", { name: "Restart Photos" }).click();
    await expect(said).toHaveText("Restarting Photos. Its steps are in the activity strip.");

    await page.getByRole("link", { name: "Remove Photos" }).click();
    const sheet = page.getByRole("dialog", { name: "Remove Photos" });
    // deleting: the id typed, and a fresh code; the server refuses a code it doesn't know
    s.actions = new Answer(403, { body: { error: { code: "needs-code", words: "Deleting an app's data needs a fresh code: run sudo bromigos server board code at the server, and type it here. A code that signed a browser in doesn't count." } } });
    await sheet.getByLabel(/The app's id/).fill("photos");
    await sheet.getByLabel("One-time code").fill("kx7 42q");
    await sheet.getByRole("button", { name: "Remove and delete data" }).click();
    await expect(sheet.locator("[role=status]")).toContainText("Deleting an app's data needs a fresh code");
    // keeping the data needs neither
    s.actions = { schema: 1, ok: true, job: null, request: "r2", words: "Removing Photos, keeping its data." };
    await sheet.getByRole("button", { name: "Remove, keep its data" }).click();
    await expect(sheet.locator("[role=status]")).toHaveText("Removing Photos, keeping its data. Its steps are in the activity strip.");

    const posts = s.seen.filter((x) => x.path === "/api/actions");
    expect(posts.map((x) => JSON.parse(x.body!))).toEqual([
      { verb: "restart", app: "photos" },
      { verb: "restart", app: "photos" },
      { verb: "remove", app: "photos", delete_data: true, code: "KX742Q" },
      { verb: "remove", app: "photos" },
    ]);
    for (const p of posts) expect(p.headers["x-bromigos-board"]).toBe("1");
  });

  test("deleting data while the server is busy checking codes: said so, and nothing is cleared", async ({ page }) => {
    const s = new Service();
    s.board = copy(real.boards.healthy); // the real board: root's actions include delete-data
    s.actions = new Answer(503, { headers: { "retry-after": "5" }, body: { error: { code: "busy", words: "The server is checking many codes at once. Try again in a moment." } } });
    await openReal(page, s, "app/photos/remove", { quiet: /503/ });
    const sheet = page.getByRole("dialog", { name: "Remove Photos" });
    await sheet.getByLabel(/The app's id/).fill("photos");
    await sheet.getByLabel("One-time code").fill("kx7 42q");
    await sheet.getByRole("button", { name: "Remove and delete data" }).click();
    await expect(sheet.locator("[role=status]")).toHaveText("The server is busy. Try again in a moment.");
    await expect(sheet.getByLabel("One-time code")).toHaveValue("kx7 42q");
    await expect(sheet.getByRole("button", { name: "Remove and delete data" })).toHaveAttribute("aria-disabled", "false");
  });

  test("deleting data needs its own leave: without it the sheet shows the command, and no field", async ({ page }) => {
    const s = new Service();
    s.board = { ...copy(real.boards.healthy), actions: ["restart", "remove"] };
    await openReal(page, s, "app/photos/remove");
    const sheet = page.getByRole("dialog", { name: "Remove Photos" });
    await expect(sheet.getByRole("button", { name: "Remove, keep its data" })).toBeVisible();
    await expect(sheet.getByRole("button", { name: "Remove and delete data" })).toHaveCount(0);
    await expect(sheet.locator("input")).toHaveCount(0);
    await expect(sheet).toContainText("sudo bromigos lab apps remove photos --delete-data");
  });

  test("a job about this app is on its page while it runs", async ({ page }) => {
    const s = new Service();
    const job = copy(real.boards.running.activity.jobs.find((j: { state: string }) => j.state === "running"));
    s.activity = `event: snapshot\ndata: ${JSON.stringify({ schema: 1, jobs: [{ ...job, id: "20261110-2113-app.restart-photos-1a2b", kind: "app.restart", title: "Restarting Photos", subject: { type: "app", id: "photos", name: "Photos" } }] })}\n\n`;
    await openReal(page, s, "app/photos");
    await expect(page.locator(".panel", { hasText: "GOING ON · 1" })).toContainText("Restarting Photos");
    await openReal(page, s, "app/passwords");
    await expect(page.locator(".panel", { hasText: "GOING ON" })).toHaveCount(0);
  });
});
