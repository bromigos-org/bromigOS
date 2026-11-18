// The post, Activity's hero: the lab's jobs as a station's crew at work, drawn from the job
// records alone under the board's Content-Security-Policy. A crew member stands at each job that
// runs or asks, a ring shows the job's own share done, a finish is shown once and only when the
// page saw it, every figure, machine and room opens its job as the list does, and the crew never
// leave the floor. Nothing here compares pictures: each test reads what the page built.
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { chart, offPath, rooms } from "../lib/post/floor";
import { sanePack } from "../lib/post/sane";
import { open } from "./helpers";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.json`, import.meta.url), "utf8"));
const pack = sanePack(JSON.parse(readFileSync(new URL("../public/post/post.json", import.meta.url), "utf8")))!;
const idOf = (name: string, kind: string, state: string) => (fixture(name).activity as { id: string; kind: string; state: string }[]).find((j) => j.kind === kind && j.state === state)!.id;

/** Opens Activity on a fixture and waits for the station; `asked` is every path under /post/ the page fetched. */
async function station(page: Page, name: string) {
  const asked: string[] = [];
  page.on("request", (r) => { const p = new URL(r.url()).pathname; if (p.startsWith("/post/")) asked.push(p); });
  const h = await open(page, name, "activity");
  await expect(page.locator(".post-hero.on .post .station")).toBeVisible({ timeout: 30_000 });
  return { ...h, asked, post: page.locator(".post"), fig: (crew: string) => page.locator(`.post .hit.fig[title^="${crew}"]`) };
}

/** Where each crew member's feet are, in the station's own pixels (the page places them in percent). */
const feet = (page: Page) =>
  page.evaluate(() => [...document.querySelectorAll<HTMLElement>(".post .act")].map((e) => [parseFloat(e.style.left), parseFloat(e.style.top)]))
    .then((all) => all.map(([x, y]) => [(x / 100) * pack.map.size[0], (y / 100) * pack.map.size[1]] as [number, number]));

test("a crew member at each job that runs or asks: the place, the ring and the hint are the record's", async ({ page }) => {
  const { post, fig, errors, csp, asked } = await station(page, "jobs");
  const run = idOf("jobs", "backup.run", "running"), ask = idOf("jobs", "storage.add", "needs-you");
  await expect(page.locator("[data-post='mount'] .post")).toHaveCount(1);
  // the disk that asks: LINEMAN stands at the power core, not working, on the amber ring
  await expect(fig("LINEMAN")).toHaveAttribute("title", "LINEMAN stands at the power core, not working: “Adding a disk: sdc” (step 2 of 2 · Making sdc ready) needs you. Press to open this job.");
  await expect(fig("LINEMAN")).toHaveAttribute("data-job", ask);
  // the backup that runs: OWL works at the press, and the ring is the record's 40 %
  await expect(fig("OWL")).toHaveAttribute("title", "OWL is working at the press: “Backing up this server” (step 2 of 2 · Copying what changed · 40 %) is running. Press to open this job.");
  await expect(fig("OWL")).toHaveAttribute("data-job", run);
  // nothing for EXO: the failed and the ended backups aren't drawn
  await expect(fig("EXO")).toHaveAttribute("title", "EXO, one of the crew, is resting in the quarters. With no job to work on, the crew rest in the quarters.");
  await expect(fig("EXO")).toHaveAttribute("role", "img");
  await expect(post.locator(".hit.fig[data-job]")).toHaveCount(2);
  const rings = post.locator(".act svg.ring:not([hidden])");
  await expect(rings).toHaveCount(2);
  await expect(post.locator(".act svg.ring.ask:not([hidden])")).toHaveCount(1);
  await expect(post.locator(".act svg.ring:not(.ask):not([hidden]) .fill")).toHaveAttribute("stroke-dasharray", "40.0 100");
  await expect(post.locator(".act svg.ring.turn:not([hidden])")).toHaveCount(0);
  // each in its own loop: OWL packing, the other two standing; the press runs, the core (a job that only asks) doesn't
  await expect(post.locator('.act img[src="/post/owl-pack.webp"]')).toBeVisible();
  await expect(post.locator('.act img[src="/post/lineman-idle.webp"]')).toBeVisible();
  await expect(post.locator('.mach img[src="/post/m-press-run.webp"]')).toBeVisible();
  await expect(post.locator('.mach img[src="/post/m-core-idle.webp"]')).toBeVisible();
  await expect(post.locator('video[src="/post/pod-e-work.mp4"]')).toHaveClass(/\bon\b/);
  await expect(post.locator('video[src="/post/pod-d-idle.mp4"]')).toHaveClass(/\bon\b/);
  // the machines and rooms say the same, and the ones with nothing say what they are for
  await expect(post.locator(`.hit.mach[data-job="${run}"]`)).toHaveAttribute("title", "The press: “Backing up this server” (step 2 of 2 · Copying what changed · 40 %) is running. Press to open this job.");
  await expect(post.locator(`.hit.room[data-job="${ask}"]`)).toHaveAttribute("title", /^The workshop, at the power core: “Adding a disk: sdc” .* needs you\. Press to open this job\.$/);
  await expect(post.locator(".hit.mach:not([data-job])")).toHaveCount(4);
  await expect(post.locator('.hit.mach[title^="The server rack. The lab\'s creation jobs are worked here"]')).toHaveAttribute("title", /Nothing is running here now\.$/);
  await expect(post.locator(".hit.pad")).toHaveAttribute("title", /^The landing pad\. Updates of the system and downloads arrive here, by shuttle/);
  await expect(post.locator(".ship")).toBeHidden();   // no job at the pad: no shuttle
  // no words or numbers on the picture, nothing the policy would refuse, and only the loops this lab needs were fetched
  expect((await post.innerText()).trim()).toBe("");
  expect(await page.evaluate(() => document.querySelectorAll(".post style, .post [onclick], .post [src^='data:']").length)).toBe(0);
  const art = [...new Set(asked)];
  expect(art).toEqual(expect.arrayContaining(["/post/post.json", "/post/frame.webp", "/post/owl-pack.webp", "/post/m-press-run.webp", "/post/pod-e-work.mp4"]));
  // (the press's finished loop comes with its running one, so it is there when the job ends)
  expect(art.filter((p) => /-(holo|scan|weld|crank|lift|work|cook|tend)\.webp$|\/ship-|-done\.mp4$|m-(rack|core|terminal|holotable|fabricator)-(run|done)/.test(p)), "fetched with no job that needs it").toEqual([]);
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});

test("a figure, its machine and its room open the job, as the list does", async ({ page }) => {
  const { post, fig } = await station(page, "jobs");
  const run = idOf("jobs", "backup.run", "running"), ask = idOf("jobs", "storage.add", "needs-you");
  await fig("OWL").click();
  await expect(page).toHaveURL(new RegExp(`#job/${run}$`));
  await expect(page.locator(".sh-sheet")).toContainText("Backing up this server");
  await page.goBack();
  // by keyboard: a machine with a job is a button
  await post.locator(`.hit.mach[data-job="${ask}"]`).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`#job/${ask}$`));
  await expect(page.locator(".sh-sheet")).toContainText("Adding a disk: sdc");
  await page.goBack();
  await expect(page.locator(".sh-sheet")).toHaveCount(0);
  // the room's floor, where neither its machine nor its crew member stands
  const floor = await post.locator(`.hit.room[data-job="${run}"]`).evaluate((hit) => {
    const b = hit.getBoundingClientRect();
    const mine = (x: number, y: number) => [[0, 0], [-6, 0], [6, 0], [0, -6], [0, 6]].every(([dx, dy]) => document.elementFromPoint(x + dx, y + dy) === hit);
    for (let i = 1; i < 20; i++) for (let k = 1; k < 20; k++) { const x = Math.round(b.left + (b.width * i) / 20), y = Math.round(b.top + (b.height * k) / 20); if (mine(x, y)) return [x, y]; }
    return null;
  });
  expect(floor, "a patch of the room's own floor").not.toBeNull();
  await page.mouse.click(floor![0], floor![1]);
  await expect(page).toHaveURL(new RegExp(`#job/${run}$`));
  await page.goBack();
  // a place with no job is no button: pressing it goes nowhere
  await post.locator(".hit.pad").click();
  await post.locator(".station").click({ position: { x: 6, y: 6 } });   // and open space is nothing at all
  await expect(page).toHaveURL(/#activity$/);
  await expect(post.locator('.hit[role="button"]')).toHaveCount(6);   // two figures, two machines, two rooms
  await expect(post.locator('.hit[role="img"]')).toHaveCount(10);
});

test("a job that finishes while the page is open: its room plays the finish once, and its crew member walks home", async ({ page }) => {
  await page.route("**/fixtures/running.json", async (route) => {
    const doc = await (await route.fetch()).json();
    await route.fulfill({ json: { ...doc, stream: doc.stream.map((e: { after_ms: number }) => ({ ...e, after_ms: e.after_ms + 3000 })) } });
  });
  const { post, fig, asked, errors, csp } = await station(page, "running");
  await expect(fig("LINEMAN")).toHaveAttribute("title", /^LINEMAN is working at the press: “Backing up this server” .*40 %\) is running\./);
  expect(asked.filter((p) => /-done\.mp4$/.test(p)), "nothing is finished yet").toEqual([]);
  // the record moves on: the ring is the record's 90 %
  await expect(post.locator(".act svg.ring:not([hidden]) .fill")).toHaveAttribute("stroke-dasharray", "90.0 100", { timeout: 10_000 });
  // and ends well: the print shop's finish clip, the press's finished loop, the burst, and LINEMAN is free
  await expect(post.locator('video[src="/post/pod-e-done.mp4"]')).toHaveClass(/\bon\b/, { timeout: 10_000 });
  await expect(post.locator('.mach img[src="/post/m-press-done.webp"]')).toBeVisible();
  expect(await post.locator("svg.fx ellipse:not(.fail)").count()).toBeGreaterThan(0);
  await expect(fig("LINEMAN")).toHaveAttribute("title", /^LINEMAN is walking back to the quarters\./);
  await expect(post.locator(".hit.fig[data-job]")).toHaveCount(0);
  // the finish is shown once: the room goes quiet again, the burst is gone, and LINEMAN gets home on the floor
  await expect(post.locator('video[src="/post/pod-e-idle.mp4"]')).toHaveClass(/\bon\b/, { timeout: 10_000 });
  await expect(post.locator("svg.fx ellipse")).toHaveCount(0);
  const stops = chart(pack.map, rooms(pack.map));
  let worst = 0;
  await expect(async () => {
    for (const p of await feet(page)) worst = Math.max(worst, offPath(stops, p));
    await expect(fig("LINEMAN")).toHaveAttribute("title", /is resting in the quarters/, { timeout: 100 });
  }).toPass({ timeout: 30_000, intervals: [150] });
  expect(worst, "the worst distance of a crew member from the floor on the way home").toBeLessThan(0.5);
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});

test("nothing is replayed on load: a job that ended before the page opened shows no finish", async ({ page }) => {
  const { post, asked } = await station(page, "healthy");
  await expect(post.locator(".hit.fig[data-job]")).toHaveCount(0);
  await expect(post.locator('.hit.fig[role="img"][title*="is resting in the quarters"]')).toHaveCount(3);
  await page.waitForTimeout(600);
  await expect(post.locator("svg.fx ellipse")).toHaveCount(0);
  await expect(post.locator("video.on")).toHaveCount(6);
  for (const v of await post.locator("video.on").all()) await expect(v).toHaveAttribute("src", /-idle\.mp4$/);
  expect(asked.filter((p) => /-(done|work)\.mp4$|-(run|done)\.webp$/.test(p))).toEqual([]);
});

test("a job that fails while the page is open: its room flashes red once, and no finish plays", async ({ page }) => {
  await page.route("**/fixtures/running.json", async (route) => {
    const doc = await (await route.fetch()).json();
    const last = doc.stream[doc.stream.length - 1].data;
    const failed = { ...last, state: "failed", pct: 40, result: { ok: false, summary: "It stopped at Copying what changed.", undo: null }, error: { step: "copy", words: "the destination didn't answer", code: "exit", fix: null } };
    await route.fulfill({ json: { ...doc, stream: [{ after_ms: 2500, event: "job", data: failed }] } });
  });
  const { post, fig, asked } = await station(page, "running");
  await expect(fig("LINEMAN")).toHaveAttribute("data-job", /backup\.run/);
  await expect(post.locator(".hit.room.failed")).toHaveCount(1, { timeout: 10_000 });
  await expect(post.locator(".hit.room.failed")).toHaveAttribute("title", /^The print shop, with the press/);
  expect(await post.locator("svg.fx ellipse.fail").count()).toBeGreaterThan(0);
  await expect(post.locator(".hit.fig[data-job]")).toHaveCount(0);
  await expect(post.locator(".hit.room.failed")).toHaveCount(0, { timeout: 10_000 });   // once
  expect(asked.filter((p) => /-done\.mp4$/.test(p)), "a failed job plays no finish").toEqual([]);
});

test("four jobs for three crew: each job keeps its crew member, and the fourth runs its room with nobody there", async ({ page }) => {
  const { post, fig, errors, csp } = await station(page, "post");
  const ask = idOf("post", "storage.add", "needs-you"), run = idOf("post", "backup.run", "running"), image = idOf("post", "lab.image", "running"), feed = idOf("post", "lab.pipeline", "running");
  // by id, oldest first: the disk, the backup, the picture; the pipeline run has nobody
  await expect(fig("LINEMAN")).toHaveAttribute("data-job", ask);
  await expect(fig("OWL")).toHaveAttribute("data-job", run);
  await expect(fig("EXO")).toHaveAttribute("data-job", image);
  await expect(fig("EXO")).toHaveAttribute("title", /^EXO is working at the server rack: “Image: .*68 %\) is running\./);
  await expect(post.locator(`.hit.fig[data-job="${feed}"]`)).toHaveCount(0);
  // the rack runs for both, and says the other is there too; the queued and the ended ones aren't drawn
  await expect(post.locator('.mach img[src="/post/m-rack-run.webp"]')).toBeVisible();
  await expect(post.locator('video[src="/post/pod-b-work.mp4"]')).toHaveClass(/\bon\b/);
  await expect(post.locator(`.hit.mach[data-job="${image}"]`)).toHaveAttribute("title", /1 more job is here too\. Press to open this job\.$/);
  await expect(post.locator(".hit.fig[data-job]")).toHaveCount(3);
  // the picture's ring is its record's 68 %; a job that never said a share gets the arc that turns, never a number
  await expect(post.locator('.act svg.ring:not([hidden]) .fill[stroke-dasharray="68.0 100"]')).toHaveCount(1);
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});

test("the crew walk only on the floor, also when re-sent part-way", async ({ page }) => {
  // jobs that start, end and start again while crew are still walking: each is the service's own record, moved on
  await page.route("**/fixtures/post.json", async (route) => {
    const doc = await (await route.fetch()).json();
    const by = (kind: string, state: string) => doc.activity.find((j: { kind: string; state: string }) => j.kind === kind && j.state === state);
    const backup = by("backup.run", "running"), disk = by("storage.add", "needs-you"), image = by("lab.image", "running"), feed = by("lab.pipeline", "running");
    let at = backup.updated_at;
    const as = (j: object, over: object) => ({ ...j, updated_at: ++at, ...over });
    const fresh = { steps: [], step: null, stage: null, subject: null, children: [], question: null, can: [] };
    await route.fulfill({ json: { ...doc, stream: [
      { after_ms: 1500, event: "job", data: as(backup, { state: "succeeded", pct: 100, can: [], result: { ok: true, summary: "Backed up: the copy checks out.", undo: null } }) },   // OWL leaves the press for the pipeline run at the rack
      { after_ms: 2600, event: "job", data: as(feed, { state: "succeeded", can: [], result: { ok: true, summary: "Done.", undo: null } }) },                                  // OWL is re-sent part-way: home
      { after_ms: 3300, event: "job", data: as(backup, { ...fresh, id: "20261110-0601-app.install-photos-0001", kind: "app.install", title: "Adding Photos", state: "running", pct: null }) },   // and again: the print bench
      { after_ms: 4200, event: "job", data: as(disk, { state: "running", question: null, can: [] }) },                                                                          // LINEMAN starts working where it stands
      { after_ms: 5000, event: "job", data: as(image, { state: "cancelled", can: [], result: null }) },                                                                         // EXO walks home
      { after_ms: 5600, event: "job", data: as(backup, { ...fresh, id: "20261110-0602-server.update-myserver-0002", kind: "server.update", title: "Updating this server", state: "running", pct: 10 }) },   // EXO is re-sent part-way: the pad
    ] } });
  });
  const { post, fig, asked, errors, csp } = await station(page, "post");
  expect(asked.filter((p) => p.includes("/ship-") || p.includes("/crate")), "no job at the pad yet: no shuttle and no crate is fetched").toEqual([]);
  const stops = chart(pack.map, rooms(pack.map));
  let worst = 0, moved = 0, last = await feet(page);
  const until = Date.now() + 24_000;
  let settled = false;
  while (Date.now() < until && !settled) {
    await page.waitForTimeout(90);
    const now = await feet(page);
    now.forEach((p, i) => { worst = Math.max(worst, offPath(stops, p)); if (Math.hypot(p[0] - last[i][0], p[1] - last[i][1]) > 1) moved++; });
    last = now;
    settled = Date.now() > until - 16_000 && (await post.locator('.hit.fig[title*="is walking"]').count()) === 0;
  }
  expect(moved, "the crew really walked").toBeGreaterThan(40);
  expect(worst, "the worst distance of any crew member from the floor").toBeLessThan(0.5);
  // and everyone ended where their job is: the print bench, the power core (working now), and the pad with the shuttle down
  await expect(fig("OWL")).toHaveAttribute("title", /^OWL is working at the print bench: “Adding Photos” is running\./);
  await expect(fig("LINEMAN")).toHaveAttribute("title", /^LINEMAN is working at the power core: “Adding a disk: sdc”/);
  await expect(fig("EXO")).toHaveAttribute("title", /^EXO is working at the landing pad: “Updating this server” \(.*10 %\) is running\./);
  // the shuttle came for it: in the air with its legs folded away, unfolding them as it settled (the strip), and parked now
  await expect(post.locator(".ship")).toBeVisible();
  await expect(post.locator('.ship img[src="/post/ship-idle.webp"]')).toBeVisible();
  await expect(post.locator(".ship .fold")).toBeHidden();
  await expect(post.locator('.ship img[src="/post/ship-fly.webp"]')).toBeHidden();
  const strip = await post.locator(".ship .fold").evaluate((e: HTMLElement) => [e.style.backgroundImage, e.style.backgroundSize, e.style.backgroundPositionX]);
  expect(strip.slice(0, 2)).toEqual(['url("/post/ship-fold.webp")', "2500% 100%"]);
  expect(parseFloat(strip[2]), "the last frame it showed: its legs all but down").toBeLessThan(13);
  expect([...new Set(asked.filter((p) => p.includes("/ship-")))].sort()).toEqual(["/post/ship-fly.webp", "/post/ship-fold.webp", "/post/ship-idle.webp"]);
  // and EXO unloads it: at the hatch with its back to us, across with a crate in its arms, bent at the stack, where the crates pile up
  await expect(post.locator(".crate:not([hidden])")).toHaveCount(3, { timeout: 20_000 });
  await expect(post.locator('.act img.carry[src="/post/crate.webp"]')).toHaveCount(1);
  expect(asked).toEqual(expect.arrayContaining(["/post/crate.webp", "/post/exo-work.webp", "/post/exo-lift.webp"]));
  const stretch = [stops.get("ps")!.p, stops.get("pk")!.p];
  const exo = (await feet(page))[2];
  expect(Math.hypot(exo[0] - stretch[0][0], exo[1] - stretch[0][1]) + Math.hypot(exo[0] - stretch[1][0], exo[1] - stretch[1][1]), "EXO is between the ramp and the stack").toBeLessThan(Math.hypot(stretch[0][0] - stretch[1][0], stretch[0][1] - stretch[1][1]) + 1);
  await expect(post.locator('.act svg.ring.turn:not([hidden])')).toHaveCount(2);   // the two that never said a share done
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});

test("off screen or with the page hidden, the loop stops; back on screen it goes on", async ({ page }) => {
  const { post } = await station(page, "jobs");
  const running = () => page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length);
  await expect(post).not.toHaveClass(/\bidle\b/);
  expect(await running()).toBeGreaterThan(0);
  // hidden: what loops is paused, and no frame is asked for
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(post).toHaveClass(/\bidle\b/);
  await expect.poll(async () => page.evaluate(() => [...document.querySelectorAll(".post, .post *")].flatMap((e) => e.getAnimations()).filter((a) => a.playState === "running").length)).toBe(0);
  expect(await page.evaluate(() => [...document.querySelectorAll<HTMLVideoElement>(".post video")].every((v) => v.paused))).toBe(true);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(post).not.toHaveClass(/\bidle\b/);
  // scrolled away: the same
  await page.evaluate(() => { const hero = document.querySelector<HTMLElement>(".post-hero")!; hero.style.setProperty("margin-top", "-4000px"); });
  await expect(post).toHaveClass(/\bidle\b/);
  await page.evaluate(() => document.querySelector<HTMLElement>(".post-hero")!.style.removeProperty("margin-top"));
  await expect(post).not.toHaveClass(/\bidle\b/);
  expect(await running()).toBeGreaterThan(0);
});

test.describe("with reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("nobody walks and no clip plays: the crew stand at their places", async ({ page }) => {
    await page.route("**/fixtures/running.json", async (route) => {
      const doc = await (await route.fetch()).json();
      await route.fulfill({ json: { ...doc, stream: doc.stream.map((e: { after_ms: number }) => ({ ...e, after_ms: e.after_ms + 2500 })) } });
    });
    const { post, fig, asked, errors, csp } = await station(page, "running");
    await expect(post).toHaveClass(/\breduced\b/);
    await expect(fig("LINEMAN")).toHaveAttribute("title", /^LINEMAN is working at the press/);
    // each loop is held on one frame (a canvas in the picture's place), no clip is made, and nothing animates
    await expect(post.locator(".act canvas:not([hidden])")).toHaveCount(3);
    await expect(post.locator(".act img:not([hidden]), .mach img:not([hidden])")).toHaveCount(0);
    await expect(post.locator(".mach canvas:not([hidden])")).toHaveCount(6);
    await expect(post.locator("video")).toHaveCount(0);
    await expect(post.locator(".chase")).toHaveCount(0);
    expect(await page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length)).toBe(0);
    // the job ends: LINEMAN is at once back in the quarters, with no walk, no burst and no finish clip
    await expect(fig("LINEMAN")).toHaveAttribute("title", /is resting in the quarters/, { timeout: 10_000 });
    await expect(post.locator('.hit.fig[title*="walking"]')).toHaveCount(0);
    await expect(post.locator("svg.fx ellipse")).toHaveCount(0);
    expect(await page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length)).toBe(0);
    expect(asked.filter((p) => p.endsWith(".mp4"))).toEqual([]);
    expect(errors).toEqual([]);
    expect(await csp()).toEqual([]);
  });
});

test("the station's drawing doesn't arrive: the hero's frame keeps the jobs' plain state, and the list stands", async ({ page }) => {
  await page.route("**/post/post.json", (route) => route.abort());
  await open(page, "jobs", "activity");
  const frame = page.locator(".post-wait");
  await expect(frame.locator(".post-line")).toHaveText("1 JOB RUNNING · 1 NEEDS YOU");
  await expect(frame.locator(".post-line")).toHaveClass(/warn/);
  await page.waitForTimeout(1000);
  await expect(frame).toBeVisible();   // it stays: the station was never drawn
  await expect(page.locator(".post-hero.on")).toHaveCount(0);
  await expect(page.locator(".post .station")).toHaveCount(0);
  await expect(page.locator(".ac-group .job")).toHaveCount(4);
  expect(await page.locator(".broken").count()).toBe(0);
});

test("the post's script doesn't arrive: the same plain state", async ({ page }) => {
  // the scripts a page without the hero loads; any other script (the post's) is then refused
  const shell = new Set<string>();
  let refuse = false;
  page.on("request", (r) => void (!refuse && r.url().includes("/_next/static/") && shell.add(r.url())));
  await page.goto("/?fixture=healthy#supply");
  await expect(page.locator(".shell")).toBeVisible({ timeout: 15_000 });
  await page.waitForLoadState("networkidle");
  refuse = true;
  await page.route("**/_next/static/**", (route) => (shell.has(route.request().url()) ? route.fallback() : route.abort()));
  await page.evaluate(() => (window.location.hash = "activity"));
  await expect(page.locator(".post-wait .post-line")).toHaveText("NOTHING IS RUNNING");
  await page.waitForTimeout(1000);
  await expect(page.locator(".post-wait")).toBeVisible();
  await expect(page.locator(".post")).toHaveCount(0);
  await expect(page.locator(".ac-group .job")).toHaveCount(1);
  expect(await page.locator(".broken").count()).toBe(0);
});

test("the list under the post stays as it is", async ({ page }) => {
  await station(page, "jobs");
  await expect(page.locator(".ac-rd .rd .v")).toHaveText(["1", "1", "2", "live"]);
  await expect(page.locator(".ac-group")).toHaveCount(3);
  // the hero comes first, over the readings and the groups
  const hero = (await page.locator(".post-hero").boundingBox())!, list = (await page.locator(".ac-rd").boundingBox())!;
  expect(hero.y + hero.height).toBeLessThanOrEqual(list.y);
});
