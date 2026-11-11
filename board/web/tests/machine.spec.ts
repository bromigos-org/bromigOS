// A machine's page: Overview's hero, needs and reading tiles from the board's documents; Vitals'
// gauges and the ECharts trend (and its planned state when the server keeps no trends);
// Hardware's parts; Set-up on a first run.
import { expect, test } from "@playwright/test";
import { open, VERDICT } from "./helpers";
import { copy, go, live, openReal, real, Service, whole } from "./service";
import { WEBGL } from "./webgl";

test.use(WEBGL); // the holograms are drawn in this spec

test("Overview, healthy: the verdict, the lit groups, the three readings and the apps", async ({ page }) => {
  await open(page, "healthy", "m/myserver");
  const hero = page.locator(".mc-hero");
  await expect(hero.locator(".verdict")).toHaveText("ALL SYSTEMS NOMINAL");
  await expect(hero.locator(".over")).toHaveText("5 OF 8 GROUPS LIT");
  await expect(hero.locator(".mod.on")).toHaveCount(5);
  await expect(hero.locator(".mod", { hasText: "GAMES" })).toContainText("empty");
  await expect(page.locator(".rt", { hasText: "STORAGE" })).toContainText("healthy");
  await expect(page.locator(".rt", { hasText: "BACKUPS" })).toContainText("PROVEN 12 DAYS AGO");
  await expect(page.locator(".rt", { hasText: "UPDATES" })).toContainText("came back healthy");
  await expect(page.locator(".mc-apps .tile")).toHaveCount(7);
  await expect(page.locator(".mc-parts .chip")).toHaveCount(3);
  await expect(page.locator(".mc-apps .tile", { hasText: "Photos" })).toContainText("Last photo backed up 2 hours ago");
});

test("Overview, one thing wrong: the verdict, the drive and what fixed itself", async ({ page }) => {
  await open(page, "needs-you", "m/myserver");
  await expect(page.locator(VERDICT)).toHaveText("2 THINGS NEED YOU");
  await expect(page.locator(".rt", { hasText: "STORAGE" })).toContainText("getting worse");
  await expect(page.locator(".panel", { hasText: "FIXED BY ITSELF" })).toContainText("Updating Photos");
  await expect(page.locator(".panel", { hasText: "FIXED BY ITSELF" })).toContainText("It failed and put things back by itself.");
  await page.locator(".rt", { hasText: "STORAGE" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Data › Drives$/);
});

test("the hero draws the machine on its deck tray: one canvas, and something on it", async ({ page }) => {
  const { errors, csp } = await open(page, "healthy", "m/myserver");
  const hero = page.locator(".mc-hero .mhero");
  await expect(hero).toHaveClass(/ready/, { timeout: 30_000 });
  await expect(hero).not.toHaveClass(/nogl/);
  await expect(hero.locator(".mh-top")).toContainText("D2·A · MYSERVER");
  await expect(hero.locator(".mh-top")).toContainText("ONLINE");
  await expect(page.locator("canvas")).toHaveCount(1);
  // the canvas carries a picture: the hero looks different with it than without it
  await expect
    .poll(async () => {
      const withIt = await hero.screenshot();
      await page.locator("canvas").evaluate((c) => ((c as HTMLElement).hidden = true));
      const without = await hero.screenshot();
      await page.locator("canvas").evaluate((c) => ((c as HTMLElement).hidden = false));
      return Buffer.compare(withIt, without) !== 0;
    }, { timeout: 20_000 })
    .toBe(true);
  // "DOCKS AT D2" goes back to the whole station
  await hero.getByRole("button", { name: "DOCKS AT D2" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Home$/);
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});

test("something wrong on it: the cause is lit and LINEMAN stands beside it", async ({ page }) => {
  await open(page, "needs-you", "m/myserver");
  const hero = page.locator(".mc-hero .mhero");
  await expect(hero).toHaveClass(/ready/, { timeout: 30_000 });
  await expect(hero.locator(".mh-top")).toContainText("NEEDS YOU · A DRIVE IS GETTING WORSE");
  await expect(hero.locator('img.crewx[src$="/lamplight/crew/lineman.webp"]')).toBeVisible();
  await expect(hero.locator(".cap2")).toContainText("LINEMAN");
  await expect(hero.locator(".tgt2")).toHaveCount(1);
});

test("a kind with no cleared model shows its icon on the tray, and asks for no mesh of its own", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => asked.push(new URL(r.url()).pathname));
  await open(page, "lab", "m/vault");
  const hero = page.locator(".mc-hero .mhero");
  await expect(hero).toHaveClass(/ready/, { timeout: 30_000 });
  await expect(hero.locator(".kico.big")).toBeVisible();
  await expect(hero.locator(".mh-top")).toContainText("VAULT");
  expect(asked.filter((p) => p.startsWith("/holo/"))).toEqual(["/holo/lite/wick-cut.bin"]);
});

test("without WebGL the hero's words stand, and nothing breaks", async ({ page }) => {
  await page.addInitScript(() => {
    const get = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) {
      return /webgl/.test(kind) ? null : (get as any).call(this, kind, ...rest);
    } as typeof get;
  });
  const failures: string[] = [];
  page.on("pageerror", (e) => failures.push(e.message));
  await page.goto("/?fixture=healthy#m/myserver");
  await expect(page.locator(VERDICT)).toHaveText("ALL SYSTEMS NOMINAL");
  const hero = page.locator(".mc-hero .mhero");
  await expect(hero).toHaveClass(/nogl/, { timeout: 30_000 });
  await expect(hero.locator(".mh-top")).toContainText("D2·A · MYSERVER");
  await expect(hero.locator("canvas")).toHaveCount(0);
  await expect(page.locator(".mgroups .mod.on")).toHaveCount(5);
  expect(await page.locator(".broken").count()).toBe(0);
  expect(failures).toEqual([]);
});

test("a model that fails to load once is asked for again by the next view", async ({ page }) => {
  let asked = 0;
  await page.route("**/holo/rack.bin", (route) => (++asked === 1 ? route.fulfill({ status: 503, body: "" }) : route.fallback()));
  await page.goto("/?fixture=healthy#m/myserver");
  const hero = page.locator(".mc-hero .mhero");
  await expect(hero).toHaveClass(/nogl/, { timeout: 30_000 });
  await expect(hero.locator(".mh-top")).toContainText("D2·A · MYSERVER");
  await expect.poll(() => asked).toBe(1);
  // away and back: the failed load wasn't kept, and no half-made view is left behind
  await page.evaluate(() => (window.location.hash = "home"));
  await expect(page.locator(".lamp.on .stage.ready")).toBeVisible({ timeout: 30_000 });
  await page.evaluate(() => (window.location.hash = "m/myserver"));
  await expect(hero).toHaveClass(/ready/, { timeout: 30_000 });
  await expect(hero).not.toHaveClass(/nogl/);
  expect(asked).toBe(2);
  await expect(page.locator("canvas")).toHaveCount(1);
});

test("Vitals: four gauges, then the trend, series by series", async ({ page }) => {
  await open(page, "healthy", "m/myserver/vitals");
  await expect(page.locator(".vt-stage .verdict")).toHaveText("VITALS NOMINAL");
  await expect(page.locator(".vt-g .vt-fig")).toHaveText(["23%", "7.8GB", "38°C", "34"]);
  const trend = page.locator(".vt-trends");
  await expect(trend.locator(".trend canvas")).toBeAttached();
  await expect(trend.locator(".vt-chh .k")).toHaveText("Processor");
  await trend.getByText("Memory", { exact: true }).click();
  await expect(trend.locator(".vt-chh .k")).toHaveText("Memory");
  await expect(trend.locator("table.sr-only tbody tr")).toHaveCount(97);
  await trend.getByText("7 D").click();
  await expect(trend.locator(".vt-none")).toContainText("Trends aren't kept on this server yet");
  await expect(trend.locator(".vt-none .pl")).toHaveCount(1);
});

test("Vitals with no trends kept: planned, and nothing drawn", async ({ page }) => {
  await open(page, "needs-you", "m/myserver/vitals");
  await expect(page.locator(".vt-trends .vt-none")).toContainText("Trends aren't kept");
  await expect(page.locator(".vt-trends .trend")).toHaveCount(0);
});

test("Vitals of a machine that reports nothing: not measured", async ({ page }) => {
  await open(page, "lab", "m/node3/vitals");
  await expect(page.locator(".vt-stage .verdict")).toHaveText("NOT MEASURED");
  await expect(page.locator(".vt-g.q")).toHaveCount(4);
});

test("Hardware: the parts as the scan has them, the drives as their report has them, system versions planned", async ({ page }) => {
  await open(page, "needs-you", "m/myserver/hardware");
  await expect(page.locator(".hw-part", { hasText: "PROCESSOR" }).locator(".v")).toContainText("4");
  await expect(page.locator(".hw-part", { hasText: "MEMORY" }).locator(".v")).toContainText("16");
  const drives = page.locator(".hw-part", { hasText: "DRIVES" });
  await expect(drives).toContainText("getting worse");
  await expect(drives.locator(".v")).toContainText("3");
  await expect(drives.locator(".hw-drives li")).toHaveCount(3);
  await expect(drives.locator(".hw-drives li").first()).toHaveText("sdb WDC WD40EFRX-68N32N0");
  await expect(drives).toContainText("512 GB free for apps' data");
  const gpu = page.locator(".hw-part", { hasText: "GRAPHICS CARD" });
  await expect(gpu).toContainText("The scan found no graphics card");
  await expect(gpu.locator(".st")).toHaveText("none");
  await expect(page.locator(".panel", { hasText: "SYSTEM VERSIONS" }).locator(".pl")).toHaveCount(1);
});

test.describe("the real client, the service's real answers", () => {
  test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "the contract is the same at every width"));

  test("a box with a graphics card: its kind and its memory, as the scan says them", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.hardware_gpu;
    const w = await openReal(page, s, "m/myserver/hardware");
    const gpu = page.locator(".hw-part", { hasText: "GRAPHICS CARD" });
    await expect(gpu).toContainText("An NVIDIA card · 12 GB of its own memory");
    await expect(gpu.locator(".st")).toHaveCount(0);
    await whole(page, w, "hardware, a graphics card");
  });

  test("what is in the box unread: the server's reason, and no part is called missing", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.budget_missing;
    const w = await openReal(page, s, "m/myserver/hardware");
    await expect(page.locator(".hw-part", { hasText: "PROCESSOR" })).toContainText("What is in the box: couldn't be read on the server: bromigos: no such command");
    await expect(page.locator(".hw-part", { hasText: "PROCESSOR" }).locator(".v")).toContainText("·");
    const gpu = page.locator(".hw-part", { hasText: "GRAPHICS CARD" });
    await expect(gpu.locator(".st")).toHaveText("not read");
    await expect(gpu).not.toContainText("found no graphics card");
    // the drives are their own report's, and that was read
    await expect(page.locator(".hw-part", { hasText: "DRIVES" }).locator(".v")).toContainText("3");
    await whole(page, w, "hardware, unread");
  });

  test("what fixed itself is named by the job's own title, even when the job isn't in the list any more", async ({ page }) => {
    const s = new Service();
    s.board = { ...copy(real.boards.needs_you), activity: { schema: 1, jobs: [] } };
    s.activity = live("activity_healthy"); // a stream without the update that put itself back
    await openReal(page, s, "m/myserver");
    await expect(page.locator(".panel", { hasText: "FIXED BY ITSELF" })).toContainText("Updating Photos");
    await go(page, "home");
    await expect(page.locator(".hm-fixed")).toContainText("Updating Photos · myserver");
    // an older service without the title: the job's title from the list, or "A job", never blank
    s.board = { ...copy(real.boards.needs_you), activity: { schema: 1, jobs: [] }, fixed: real.boards.needs_you.fixed.map(({ title: _t, ...f }: { title: string }) => f) };
    await page.reload();
    await expect(page.locator(".hm-fixed .lb-need")).toContainText("A job · myserver");
  });
});

test("a first run shows Set-up in Overview's place", async ({ page }) => {
  await open(page, "setup", "m/myserver");
  await expect(page.locator(".sh-tab.on")).toHaveText("Overview");
  await expect(page.locator(".panel", { hasText: "SET-UP" })).toBeVisible();
});

test("a machine the lab doesn't have says so", async ({ page }) => {
  await open(page, "healthy", "m/nosuch");
  await expect(page.locator("#view")).toContainText("No machine called nosuch is in this lab.");
});
