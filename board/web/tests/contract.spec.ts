// The page's real client against the service's real answers (tests/contract/service.json, made
// from the service's own code by scripts/make-contract.py). No fixture mode here: every request
// goes to /api/ and is answered by tests/service.ts as the service answers. What this suite
// holds: no document the service can send, and no way it can fail, blanks the page or makes it
// say something that isn't so.
import { expect, test } from "@playwright/test";
import { READ_AT, VERDICT } from "./helpers";
import { Answer, CODE, copy, go, live, openReal, pass, PLACES, real, Service, station, whole } from "./service";

test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "the contract is the same at every width"));

const verdict = VERDICT;
const tile = (page: import("@playwright/test").Page, name: string) => page.locator(".rt", { hasText: name });

// ---------------------------------------------------------------- the door and signing in

test("the door: the real door document, and only the door's two requests", async ({ page }) => {
  const s = new Service();
  s.signedIn = false;
  const w = await openReal(page, s);
  await expect(page.locator(".sh-crumb")).toHaveText(/The door$/);
  await expect(page.locator(".door-tiles .tile")).toHaveCount(real.doors.healthy.tiles.length);
  await expect(page.locator(".door-tiles .tile").first()).toHaveAttribute("href", real.doors.healthy.tiles[0].open.url);
  expect([...new Set(s.seen.map((x) => `${x.method} ${x.path}`))].sort()).toEqual(["GET /api/door", "GET /api/session"]);
  expect(w.errors).toEqual([]);
  expect(await w.csp()).toEqual([]);
});

test("the door with its app list turned off, and with no snapshot yet", async ({ page }) => {
  const s = new Service();
  s.signedIn = false;
  s.door = real.doors.off;
  await openReal(page, s);
  await expect(page.locator("#view")).toContainText("The app list is turned off here");
  await expect(page.locator("html")).toHaveAttribute("data-world", "tidewell");
});

test("signing in: the service's own refusal, then the code, sent as the service asks", async ({ page }) => {
  const s = new Service();
  s.signedIn = false;
  await openReal(page, s, "signin");
  const field = page.getByRole("textbox", { name: "One-time code" });
  await field.fill("WRONG-99");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("#signin-why")).toHaveText(real.http.signin_wrong_code.body.error.words);
  await field.fill(" abcd-efgh ");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Home$/);
  const post = s.seen.filter((x) => x.method === "POST" && x.path === "/api/session").at(-1)!;
  expect(post.headers["x-bromigos-board"]).toBe("1");
  expect(post.headers["content-type"]).toMatch(/^application\/json/);
  expect(JSON.parse(post.body!)).toEqual({ code: CODE });
  await expect(page.locator(verdict)).toHaveText("ALL MACHINES NOMINAL");
});

test("signing out sends the header too, and lands on the door", async ({ page }) => {
  const s = new Service();
  await openReal(page, s, "home");
  await page.locator(".menu.um > summary").click();
  await page.getByRole("link", { name: /Sign out/ }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/The door$/);
  const del = s.seen.find((x) => x.method === "DELETE")!;
  expect(del.headers["x-bromigos-board"]).toBe("1");
  expect(del.headers["content-type"]).toMatch(/^application\/json/);
});

test("a signed-in browser never sees the door flash while its session is read", async ({ page }) => {
  const s = new Service();
  s.sessionDelay = 1200;
  let door = false;
  await s.attach(page);
  await page.exposeFunction("sawDoor", () => (door = true));
  await page.addInitScript(() => {
    new MutationObserver(() => document.querySelector(".shell.signed-out") && (window as any).sawDoor()).observe(document, { subtree: true, childList: true, attributes: true });
  });
  await page.goto("/#home");
  await expect(page.locator(".sh-rail")).toBeVisible();
  expect(door, "the door was drawn before the session was known").toBe(false);
});

test("a signed-in browser at #signin gets Home; an address that isn't one gets Home", async ({ page }) => {
  const s = new Service();
  const w = await openReal(page, s, "signin");
  await expect(page.locator(".sh-crumb")).toHaveText(/Home$/);
  await expect(page.locator(verdict)).toBeVisible();
  await expect(page).toHaveURL(/#home$/);
  await page.goto("/#%");
  await page.reload();
  await expect(page.locator(".sh-crumb")).toHaveText(/Home$/);
  await whole(page, w, "#%");
});

test("the door at an address that isn't one", async ({ page }) => {
  const s = new Service();
  s.signedIn = false;
  await s.attach(page);
  await page.goto("/#%");
  await expect(page.locator(".sh-crumb")).toHaveText(/The door$/);
});

// ---------------------------------------------------------------- the board, as the service sends it

test("every place renders on the board the service sends today", async ({ page }) => {
  const s = new Service();
  const w = await openReal(page, s, "home");
  for (const place of PLACES) {
    await go(page, place);
    await whole(page, w, place);
  }
  expect(await w.csp()).toEqual([]);
});

test("what the page says of the board the service sends today", async ({ page }) => {
  const s = new Service();
  await openReal(page, s, "home");
  await expect(page.locator(verdict)).toHaveText("ALL MACHINES NOMINAL");
  await expect(page.locator(READ_AT)).toContainText("JUST NOW");
  // a machine's page: the updates are read where the service puts them ({updates, rollbacks})
  await go(page, "m/myserver");
  await expect(page.locator(verdict)).toHaveText("ALL SYSTEMS NOMINAL");
  await expect(tile(page, "UPDATES")).toContainText("came back healthy");
  await expect(tile(page, "UPDATES")).toContainText("WINDOW 03:00-05:00");
  await expect(tile(page, "STORAGE")).toContainText("healthy");
  // the last test restore passed: said from last_test, since the service drops last_test_passed
  await expect(tile(page, "BACKUPS")).toContainText("PROVEN 12 DAYS AGO");
  await expect(page.locator(".mc-apps .tile")).toHaveCount(2);
  // nothing measures the machine yet: said, not drawn as zero
  await go(page, "m/myserver/vitals");
  await expect(page.locator(verdict)).toHaveText("NOT MEASURED");
  await expect(page.locator(".vt-trends .vt-none")).toContainText("Trends aren't kept on this server yet");
  await go(page, "supply/updates");
  await expect(page.locator(".panel", { hasText: "THE SYSTEM" })).toContainText("Updates by itself, restarting only between 03:00 and 05:00");
  await expect(page.locator(".panel", { hasText: "THE APPS" })).toContainText("don't report updates yet");
  // the whole catalogue is in the apps list, installed or not
  await go(page, "supply/browse");
  await expect(page.locator(".su-group .tile")).toHaveCount(real.boards.healthy.apps.length);
  await go(page, "data/backups");
  await expect(page.locator(verdict)).toHaveText("BACKED UP 7 H AGO");
  await expect(page.locator(".panel", { hasText: "THE PROOF" })).toContainText("passed 12 days ago");
});

/** What each real board must make the page say (and never say). */
const SAYS: Record<string, { at: string; has?: [string, string | RegExp][]; never?: [string, string | RegExp][] }[]> = {
  needs_you: [
    { at: "home", has: [[verdict, "1 MACHINE NEEDS YOU"], [".hm-needs", "A drive is getting worse"]] },
    { at: "m/myserver", has: [[verdict, "2 THINGS NEED YOU"], [".panel:has-text('FIXED BY ITSELF')", "Updating Photos"]] },
    { at: "data", has: [[verdict, "1 GETTING WORSE"], ["#view", "8 reallocated sectors appeared in the last 3 days"]] },
  ],
  drives_watch_unknown: [
    { at: "data", has: [[verdict, "1 CAN'T BE READ · 1 MORE NOT HEALTHY"]], never: [["#view", "ALL DRIVES HEALTHY"]] },
    { at: "m/myserver", has: [[".rt:has-text('STORAGE') h3", "cannot tell"]], never: [[verdict, "NOMINAL"]] },
    { at: "home", never: [[verdict, "NOMINAL"]] },
  ],
  backups_attention: [
    { at: "data/backups", has: [[verdict, "NEEDS A LOOK · LAST GOOD COPY 2 DAYS AGO"], [".panel:has-text('WHERE THEY GO')", "last run failed"]] },
    { at: "m/myserver", has: [[".rt:has-text('BACKUPS') h3", "needs a look"], [verdict, "THE BACKUPS NEED A LOOK"]] },
  ],
  backups_off: [{ at: "data/backups", has: [[verdict, "BACKUPS ARE OFF"]] }, { at: "m/myserver", has: [[".rt:has-text('BACKUPS') h3", "off"]] }],
  backups_not_a_server: [
    { at: "data/backups", has: [["#view", "The backups couldn't be read on the server: This computer isn't a bromigOS Server"]] },
    { at: "home", has: [[verdict, "COULDN'T READ THE BACKUPS"]] },
  ],
  apps_down: [
    { at: "home", has: [[verdict, "1 APP ISN'T RUNNING"]] },
    { at: "m/myserver", has: [[verdict, "1 APP ISN'T RUNNING"], [".mc-apps .tile:has-text('Photos')", "Down"]] },
    { at: "supply", has: [[".su-rd .rd >> nth=0", "2of 3"]] },
  ],
  setup: [{ at: "home", has: [[verdict, "NOTHING INSTALLED YET"]] }, { at: "supply", has: [["#view", "Nothing is installed yet."]] }],
  apps_missing: [
    { at: "home", has: [[verdict, "COULDN'T READ THE APPS"]] },
    { at: "m/myserver", has: [[".mc-apps", "The apps couldn't be read on the server: bromigos: no such command"], [".mgroups .over", "APPS NOT READ"]], never: [[verdict, "NOMINAL"]] },
    { at: "supply", has: [["#view", "The apps couldn't be read on the server"]] },
    { at: "supply/browse", has: [["#view", "The apps couldn't be read on the server"]] },
    { at: "supply/updates", has: [[".panel:has-text('THE APPS')", "couldn't be read"]] },
  ],
  apps_error: [{ at: "supply", has: [["#view", "The apps couldn't be read on the server"]] }, { at: "home", has: [[verdict, "COULDN'T READ THE APPS"]] }],
  storage_missing: [
    { at: "data", has: [["#view", "The drives' health couldn't be read on the server"]] },
    { at: "m/myserver", has: [[".rt:has-text('STORAGE')", "couldn't be read"]], never: [[verdict, "NOMINAL"]] },
  ],
  backups_missing: [{ at: "data/backups", has: [["#view", "The backups couldn't be read on the server"]] }, { at: "m/myserver", has: [[".rt:has-text('BACKUPS')", "couldn't be read"]] }],
  system_missing: [
    { at: "m/myserver", has: [[".rt:has-text('UPDATES')", "couldn't be read"]], never: [[verdict, "NOMINAL"]] },
    { at: "supply/updates", has: [[".panel:has-text('THE SYSTEM')", "couldn't be read"]] },
  ],
  alerts_missing: [
    { at: "home", has: [[verdict, "COULDN'T READ THE ALERTS"], [".hm-needs", "can't check"]], never: [[".hm-needs", "nothing"]] },
    { at: "m/myserver/vitals", has: [[".panel:has-text('WATCHES')", "can't check"]] },
  ],
  activity_missing: [{ at: "home", has: [[verdict, "COULDN'T READ THE JOBS"], [".hm-needs", "can't check"]] }],
};

for (const name of Object.keys(real.boards))
  test(`the service's board "${name}": every place renders, and says what is so`, async ({ page }) => {
    const s = new Service();
    s.board = real.boards[name];
    const stream = `activity_${name}`;
    if (real.http[stream]) s.activity = live(stream);
    const w = await openReal(page, s, "home");
    for (const place of PLACES) {
      await go(page, place);
      await whole(page, w, `${name} at #${place}`);
    }
    for (const check of SAYS[name] ?? []) {
      await go(page, check.at);
      for (const [where, words] of check.has ?? []) await expect(page.locator(where).first(), `${name} at #${check.at}`).toContainText(words);
      for (const [where, words] of check.never ?? []) await expect(page.locator(where).first(), `${name} at #${check.at}`).not.toContainText(words);
    }
  });

test("a stale board: reading at first, then how old, by the server's own count", async ({ page }) => {
  const s = new Service();
  s.board = real.boards.stale;
  await page.clock.install();
  await openReal(page, s, "home");
  await expect(page.locator(verdict)).toHaveText("READING THE SERVER");
  expect(s.count("/api/board")).toBe(1);
  // a stale answer is asked for again in 3 seconds, not 15
  await pass(page, 3500);
  await expect.poll(() => s.count("/api/board")).toBe(2);
  await pass(page, 12_000);
  await expect(page.locator(verdict)).toHaveText("NOT READ FOR 5 MIN");
  // and when the server has read itself again, the board is fresh
  s.board = real.boards.healthy;
  await pass(page, 3500);
  await expect(page.locator(verdict)).toHaveText("ALL MACHINES NOMINAL");
});

// ---------------------------------------------------------------- documents that aren't what they should be

const BROKEN: [string, unknown][] = [
  ["null", null],
  ["an empty object", {}],
  ["an empty list", []],
  ["a word", "x"],
  ["a number", 7],
  ["true", true],
  ["a command's error document", { schema: 1, ok: false, error: "it could not be read" }],
  ["a list of the wrong things", [null, 7, "x", {}, { id: 3 }, []]],
];
const PARTS = ["apps", "storage", "backups", "updates", "ups", "machines", "needs_you", "fixed", "status", "lab", "server", "alerts", "activity", "sources", "at", "age_s", "stale", "max_age_s", "host", "settings"];

for (const [what, value] of BROKEN)
  test(`each part of the board as ${what}: nothing blanks`, async ({ page }) => {
    test.setTimeout(120_000);
    const s = new Service();
    const w = await openReal(page, s, "home");
    for (const part of PARTS) {
      s.board = { ...copy(real.boards.needs_you), [part]: value };
      await page.reload();
      await expect(page.locator(".shell")).toBeVisible();
      for (const place of ["home", "m/myserver", "m/myserver/vitals", "m/myserver/hardware", "data", "data/backups", "supply", "supply/updates"]) {
        await go(page, place);
        await whole(page, w, `${part} = ${what}, at #${place}`);
        await station(page, `${part} = ${what}, at #${place}`); // the station and the machine's hero draw from this document too
        await whole(page, w, `${part} = ${what}, at #${place}, with the station mounted`);
      }
    }
  });

for (const [what, value] of BROKEN)
  test(`the whole board, the door, the session and a job as ${what}: nothing blanks`, async ({ page }) => {
    const s = new Service();
    s.board = value;
    s.door = value;
    s.activity = `event: snapshot\ndata: ${JSON.stringify({ schema: 1, jobs: [value, { id: "x", state: "no-such-state" }, { state: "running" }] })}\n\nevent: job\ndata: ${JSON.stringify(value)}\n\nevent: nonsense\ndata: {}\n\nevent: job\ndata: not json\n\n`;
    const w = await openReal(page, s, "home");
    for (const place of PLACES) {
      await go(page, place);
      await whole(page, w, `everything = ${what}, at #${place}`);
      await station(page, `everything = ${what}, at #${place}`);
    }
    await expect(page.locator(".sh-strip .strip")).toContainText("Nothing running");
  });

test("an address the server gives becomes a link only when it is http or https", async ({ page }) => {
  const s = new Service();
  const b = copy(real.boards.healthy);
  const evil = ["javascript:alert(document.domain)", "data:text/html,<script>alert(1)</script>", "//elsewhere.example/x", "/relative", "ftp://files.example/x", " https://ok.example"];
  const installed = b.apps.filter((t: any) => t.installed);
  installed[1].open = { url: evil[0], port: 1 };
  installed[2].open = { url: evil[1], port: 2 };
  b.apps.find((t: any) => t.id === "monitoring").installed = true;
  b.apps.find((t: any) => t.id === "monitoring").open = { url: evil[4], port: 3 };
  b.lab.address = evil[0];
  s.board = b;
  const d = copy(real.doors.healthy);
  d.tiles = evil.map((url, i) => ({ ...d.tiles[0], id: `e${i}`, open: { url } }));
  s.door = d;
  const w = await openReal(page, s, "home");
  for (const place of ["home", "m/myserver", "m/myserver/vitals", "supply", "supply/browse", "settings"]) {
    await go(page, place);
    const hrefs = await page.locator("a[href]").evaluateAll((as) => as.map((a) => a.getAttribute("href")!));
    for (const h of hrefs) expect(h, `a link at #${place}`).toMatch(/^(#|https?:\/\/)/);
    const titles = await page.locator(".sh-rail a").evaluateAll((as) => as.map((a) => a.getAttribute("title") ?? ""));
    expect(titles.join(" ")).not.toContain("javascript:");
  }
  await whole(page, w, "unsafe addresses");
  // the door: only the one address that is a web address is a tile
  s.signedIn = false;
  await page.reload();
  await expect(page.locator(".door-tiles .tile")).toHaveCount(1);
  await expect(page.locator(".door-tiles .tile")).toHaveAttribute("href", "https://ok.example");
});

// ---------------------------------------------------------------- when the server stops answering

test("the board isn't ready yet (503 gathering): the server's sentence, then the board", async ({ page }) => {
  const s = new Service();
  const g = real.http.board_gathering;
  s.board = new Answer(g.status, { body: g.body, headers: g.headers });
  await page.clock.install();
  await openReal(page, s, "home");
  await expect(page.locator("#view")).toContainText(g.body.error.words);
  await expect(page.locator(".sh-lost")).toHaveCount(0);
  s.board = real.boards.healthy;
  await pass(page, 5500);
  await expect(page.locator(verdict)).toHaveText("ALL MACHINES NOMINAL");
});

for (const [what, answer] of [
  ["a 502 from the proxy", new Answer(502, { text: "<html><body>502 Bad Gateway</body></html>" })],
  ["a 500 with the service's words", new Answer(500, { body: { error: { code: "oops", words: "The board couldn't read itself." } } })],
  ["going away", "gone"],
] as const)
  test(`the server ${what === "going away" ? what : `answers ${what}`} mid-session: it is said, the last board stays, and its age grows`, async ({ page }) => {
    const s = new Service();
    await page.clock.install();
    const w = await openReal(page, s, "home", { quiet: /EventSource|event-stream/ });
    await expect(page.locator(verdict)).toHaveText("ALL MACHINES NOMINAL");
    await expect(page.locator(READ_AT)).toContainText("JUST NOW");
    s.board = answer;
    s.activity = answer;
    await s.drop(page);
    await pass(page, 16_000);
    await expect(page.locator(".sh-lost")).toBeVisible();
    await expect(page.locator(".sh-lost")).toHaveAttribute("title", what === "a 500 with the service's words" ? /The board couldn't read itself\./ : what === "going away" ? /isn't answering/ : /couldn't answer just now/);
    // the last reading stays on the page, and soon reads as old: never "just now" for ever
    await page.clock.runFor(5 * 60_000);
    await expect(page.locator(verdict)).toHaveText(/^NOT READ FOR 5 MIN$/);
    await expect(page.locator(READ_AT)).toContainText("5 MIN AGO");
    await expect(page.locator(".sh-strip .strip")).toContainText("not live");
    for (const place of ["m/myserver", "data", "supply", "activity"]) {
      await go(page, place);
      await whole(page, w, `${what}, at #${place}`);
    }
    await expect(page.locator(".sh-rail")).toBeVisible();
    // it comes back by itself
    s.board = real.boards.healthy;
    s.activity = live("activity_healthy");
    await go(page, "home");
    await pass(page, 16_000);
    await expect(page.locator(".sh-lost")).toHaveCount(0);
    await expect(page.locator(verdict)).toHaveText("ALL MACHINES NOMINAL");
    await expect(page.locator(".sh-strip .strip")).not.toContainText("not live");
  });

test("the door when the server isn't there: said, and asked again", async ({ page }) => {
  const s = new Service();
  s.signedIn = false;
  s.door = "gone";
  await page.clock.install();
  await s.attach(page);
  await page.goto("/");
  await expect(page.locator(".unreach")).toContainText("isn't answering");
  s.door = real.doors.healthy;
  await pass(page, 11_000);
  await expect(page.locator(".door-tiles .tile")).toHaveCount(real.doors.healthy.tiles.length);
});

test("the session ends elsewhere (401 mid-session): back to the door", async ({ page }) => {
  const s = new Service();
  await page.clock.install();
  await openReal(page, s, "data");
  await expect(page.locator(".sh-rail")).toBeVisible();
  s.signedIn = false;
  await pass(page, 16_000);
  await expect(page.locator(".sh-crumb")).toHaveText(/The door$/);
  await expect(page.locator(".sh-rail")).toHaveCount(0);
  await expect(page.locator(".door-tiles .tile").first()).toBeVisible();
});

test("the stream says signed-out: the page asks, and goes back to the door", async ({ page }) => {
  const s = new Service();
  let first = true;
  s.activity = () => {
    if (!first) return live("activity_healthy");
    first = false;
    s.signedIn = false;
    return `${real.http.activity_healthy.body}event: signed-out\ndata: {"words":"Sign in first."}\n\n`;
  };
  await openReal(page, s, "home");
  await expect(page.locator(".sh-crumb")).toHaveText(/The door$/);
});

test("a stream the server refuses (502 while it restarts) is opened again, on a timer", async ({ page }) => {
  const s = new Service();
  let refusals = 3;
  s.activity = () => (refusals-- > 0 ? new Answer(502, { text: "Bad Gateway" }) : live("activity_running"));
  await page.clock.install();
  await openReal(page, s, "home", { quiet: /EventSource|event-stream/ });
  // never "nothing running" before the jobs have been read
  await expect(page.locator(".sh-strip .strip")).toContainText("Reading the jobs");
  await pass(page, 12_000);
  await expect.poll(() => s.count("/api/activity")).toBe(4);
  await expect(page.locator(".sh-strip .strip")).toContainText("Backing up this server");
  await expect(page.locator(".sh-strip .strip")).not.toContainText("not live");
});

test("a hidden tab asks nothing; looked at again, it reads at once", async ({ page }) => {
  const s = new Service();
  await page.clock.install();
  await openReal(page, s, "home");
  await expect(page.locator(verdict)).toHaveText("ALL MACHINES NOMINAL");
  const hide = (hidden: boolean) =>
    page.evaluate((h) => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => h });
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (h ? "hidden" : "visible") });
      document.dispatchEvent(new Event("visibilitychange"));
    }, hidden);
  await hide(true);
  const before = s.seen.length;
  await page.clock.runFor(10 * 60_000);
  expect(s.seen.length - before, "requests made while hidden").toBe(0);
  await hide(false);
  await expect.poll(() => s.seen.length - before).toBeGreaterThanOrEqual(3); // the door, the session, the board; then the stream
  await expect.poll(() => s.seen.slice(before).some((x) => x.path === "/api/board")).toBe(true);
  await expect.poll(() => s.seen.slice(before).some((x) => x.path === "/api/activity")).toBe(true);
  // after ten minutes away the page doesn't claim "just now" from its old board: it reads, then says
  await expect(page.locator(verdict)).toHaveText("ALL MACHINES NOMINAL");
});

for (const skew of [3 * 60_000, -3 * 60_000, 400 * 86_400_000])
  test(`this browser's clock is ${skew > 0 ? "ahead" : "behind"} by ${Math.abs(skew) / 60_000} minutes: a fresh board is fresh`, async ({ page }) => {
    const s = new Service();
    await page.clock.install({ time: new Date(real.now + skew) });
    await openReal(page, s, "home");
    await expect(page.locator(verdict)).toHaveText("ALL MACHINES NOMINAL");
    await expect(page.locator(READ_AT)).toContainText("JUST NOW");
    await go(page, "data");
    await expect(page.locator(".dt-stage .chip")).toHaveText("READ 12 MIN AGO");
    await go(page, "data/backups");
    await expect(page.locator(verdict)).toHaveText("BACKED UP 7 H AGO");
  });

// ---------------------------------------------------------------- what the page may do

test("a job that asks: its question and the command, and nothing the service has no route for", async ({ page }) => {
  const s = new Service();
  s.board = real.boards.needs_you;
  s.activity = live("activity_needs_you");
  const w = await openReal(page, s, "home");
  await page.getByRole("button", { name: "Raise the drawer of jobs" }).click();
  const drawer = page.getByRole("complementary", { name: "Activity" });
  const job = drawer.locator(".job.ask");
  await expect(job).toContainText("Swap the drive now. It is safe to pull sdb.");
  await expect(job.locator("pre")).toHaveText(/^sudo bromigos activity answer \d{8}-\d{4}-drive\.replace-sdb-[0-9a-f]{4} swapped$/);
  await expect(drawer.getByRole("button", { name: /swapped|Cancel|Retry|Answer/ })).toHaveCount(0);
  await expect(drawer.locator(".job", { hasText: "Updating Photos" })).toContainText("no answer in 2 minutes");
  // the running job can be cancelled at the server, not from here
  s.activity = live("activity_running");
  await page.reload();
  await page.getByRole("button", { name: "Raise the drawer of jobs" }).click();
  await expect(page.getByRole("complementary", { name: "Activity" }).getByRole("button", { name: /Cancel|Retry/ })).toHaveCount(0);
  expect(s.seen.filter((x) => x.method !== "GET")).toEqual([]);
  await whole(page, w, "the activity drawer");
});

test("adding an app: not offered until the server says the page may, then sent as the service asks", async ({ page }) => {
  const s = new Service();
  await openReal(page, s, "supply/add/navidrome");
  const sheet = page.getByRole("dialog", { name: "Add Music" });
  await expect(sheet).toContainText("sudo bromigos lab apps add navidrome --plan");
  await expect(sheet.getByRole("button", { name: "Add Music" })).toHaveCount(0);
  await expect(sheet.locator(".pl")).toHaveCount(1);
  // the server says the page may add
  s.board = { ...copy(real.boards.healthy), actions: ["add", "restart", "remove"] };
  s.actions = new Answer(403, { body: { error: { code: "not-allowed", words: "This server doesn't let the page add apps." } } });
  await page.reload();
  const add = page.getByRole("dialog", { name: "Add Music" }).getByRole("button", { name: "Add Music" });
  await add.click();
  await expect(page.locator(".su-add [role=status]")).toHaveText("This server doesn't let the page add apps.");
  s.actions = { schema: 1, ok: true, job: "20261110-2113-app.install-navidrome-1a2b", request: "r1", words: "Adding Music." };
  await add.click();
  await expect(page.locator(".su-add [role=status]")).toHaveText("Adding Music. Its steps are in the activity strip.");
  const posts = s.seen.filter((x) => x.path === "/api/actions");
  expect(posts.map((x) => JSON.parse(x.body!))).toEqual([{ verb: "add", app: "navidrome" }, { verb: "add", app: "navidrome" }]);
  expect(posts[0].headers["x-bromigos-board"]).toBe("1");
  expect(posts[0].headers["content-type"]).toMatch(/^application\/json/);
  // an app that is installed already has no Add
  await go(page, "supply/add/photos");
  await expect(page.getByRole("dialog", { name: "Add Photos" }).getByRole("button")).toHaveCount(0);
});

test("trends the server doesn't keep (the real 404) are planned; ones it does are drawn", async ({ page }) => {
  const s = new Service();
  await openReal(page, s, "m/myserver/vitals");
  await expect(page.locator(".vt-trends .vt-none")).toContainText("Trends aren't kept on this server yet");
  s.vitals = { schema: 1, machine: "myserver", range: "24h", series: { cpu_pct: [[real.now - 3600_000, 20], [real.now - 1800_000, null], [real.now, 31], "x", [null, 3]], temp_c: "nope" } };
  await page.reload();
  await expect(page.locator(".vt-trends .trend canvas")).toBeAttached();
  await expect(page.locator(".vt-trends table.sr-only tbody tr")).toHaveCount(3);
  await page.locator("label[for=vt-s-temp_c]").click();
  await expect(page.locator(".vt-trends .vt-none")).toContainText("doesn't keep the drive heat trend");
});

test("a part that throws while it draws costs that part only", async ({ page }) => {
  const s = new Service();
  s.vitals = { schema: 1, machine: "myserver", range: "24h", series: { cpu_pct: [[real.now - 3600_000, 20], [real.now, 31]] } };
  // the chart library can't get a canvas: its panel fails, and only its panel
  await page.addInitScript(() => {
    const get = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) {
      if (kind === "2d") throw new Error("no canvas here");
      return (get as any).call(this, kind, ...rest);
    } as typeof get;
  });
  await openReal(page, s, "m/myserver/vitals");
  const broken = page.getByRole("alert").filter({ hasText: "couldn't be shown" });
  await expect(broken).toHaveText(/^The trend chart couldn't be shown\. The rest of the page still works/);
  await expect(page.locator(".vt-gauges .vt-g")).toHaveCount(4);
  await expect(page.locator(".sh-rail")).toBeVisible();
  await expect(page.locator(".sh-strip .strip")).toBeVisible();
  // and the next place is whole again
  await go(page, "home");
  await expect(page.locator(verdict)).toHaveText("ALL MACHINES NOMINAL");
  expect(await page.locator(".broken").count()).toBe(0);
});

test("every request that changes something carries the header and JSON; nothing else is asked for", async ({ page }) => {
  const s = new Service();
  await openReal(page, s, "home");
  for (const place of PLACES) await go(page, place);
  const asked = [...new Set(s.seen.map((x) => `${x.method} ${x.path}`))].sort();
  expect(asked).toEqual(["GET /api/activity", "GET /api/board", "GET /api/door", "GET /api/session", "GET /api/vitals"]);
  expect(s.seen.filter((x) => x.method !== "GET")).toEqual([]);
});
