// The lab's jobs on Activity (docs/activity.md, "Lab jobs"; docs/board.md, "The lab's jobs"): the
// generation ComfyUI makes now as the page's hero (its live picture, ring, stage and the queue
// behind it), the filter, stopping a generation (interrupting asks first), what ended jobs made
// (a picture, a clip, a 3D model on the table), the estimate where ComfyUI sends no progress,
// and the phone. The fixtures are the service's own answers (tests/contract/service.json,
// activity_lab), with the repository's own art as the pictures.
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { open } from "./helpers";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.json`, import.meta.url), "utf8"));
type Job = { id: string; kind: string; state: string; title: string; lab?: { source: string } };
const jobs = (name: string) => fixture(name).activity as Job[];
const hero = (page: Page) => page.locator(".ac-making .job.lab");
const card = (page: Page, id: string) => page.locator(`.job[data-job="${id}"]`);

test("the generation that runs now: its picture, ring, stage and the queue behind it", async ({ page }) => {
  const { errors, csp } = await open(page, "making", "activity");
  const run = jobs("making").find((j) => j.lab?.source === "comfyui" && j.state === "running")!;
  await expect(hero(page)).toHaveAttribute("data-job", run.id);
  await expect(hero(page)).toContainText("Image: Qwen-Image-2512");
  await expect(hero(page).locator(".lab-pv img")).toHaveAttribute("src", /^\/fixtures\/lab\/pv-[0-9a-f]{16}\.webp$/);
  await expect(hero(page).locator(".chip", { hasText: "LIVE" })).toBeVisible();
  // the stream moves it on: the sampler's next steps, and a new picture
  await expect(hero(page).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "88", { timeout: 10_000 });
  await expect(hero(page).locator(".lab-stage")).toHaveText("Sample · 46 of 50 steps");
  await expect(hero(page).locator(".lab-steps li.now")).toHaveText("Sample");
  await expect(hero(page).locator(".lab-queue")).toContainText("NEXT · 1");
  await expect(hero(page).locator(".lab-queue a")).toContainText("Cut-out: Lucida");
  await expect(page.locator(".ac-lab")).toContainText("ComfyUI studio · live");
  // the pipeline run is a job too, with its step's thumbnail
  await expect(card(page, "feed-ships-20261110")).toContainText("Universe assets: ships");
  await expect(card(page, "feed-ships-20261110").locator(".lab-steps li.now")).toHaveText("Shape ship-a");
  expect(errors).toEqual([]);
  expect(await csp()).toEqual([]);
});

test("all jobs, this server's, or the lab's", async ({ page }) => {
  await open(page, "making", "activity");
  const server = jobs("making").find((j) => !j.lab)!;
  await expect(card(page, server.id)).toBeVisible();
  await page.getByRole("button", { name: "The lab's jobs" }).click();
  await expect(page.getByRole("button", { name: "The lab's jobs" })).toHaveAttribute("aria-pressed", "true");
  await expect(card(page, server.id)).toHaveCount(0);
  await expect(hero(page)).toBeVisible();
  await page.getByRole("button", { name: "This server's jobs" }).click();
  await expect(page.locator(".ac-making")).toHaveCount(0);
  await expect(page.locator(".job.lab")).toHaveCount(0);
  await expect(card(page, server.id)).toBeVisible();
  // it stays as it was picked when the page comes back
  await page.reload();
  await expect(page.getByRole("button", { name: "This server's jobs" })).toHaveAttribute("aria-pressed", "true");
});

test("stopping: a queued one leaves the queue, a running one asks first", async ({ page }) => {
  await open(page, "making", "activity");
  const queued = jobs("making").find((j) => j.lab && j.state === "queued")!;
  await hero(page).getByRole("button", { name: /^Interrupt / }).click();
  const ask = hero(page).getByRole("group", { name: "Interrupt it?" });
  await expect(ask).toContainText("what it made so far is lost");
  await ask.getByRole("button", { name: "Back" }).click();
  await expect(ask).toHaveCount(0);
  await hero(page).getByRole("button", { name: /^Interrupt / }).click();
  await ask.getByRole("button", { name: "Interrupt" }).click();
  await expect(hero(page).getByRole("status")).toHaveText("cancel: a fixture changes no job.");
  await card(page, queued.id).getByRole("button", { name: /out of the queue$/ }).click();
  await expect(card(page, queued.id).getByRole("status")).toHaveText("cancel: a fixture changes no job.");
  // a pipeline run is the program's own: no control stops it
  await expect(card(page, "feed-ships-20261110").getByRole("button", { name: /Interrupt|queue/ })).toHaveCount(0);
});

test("what ended jobs made: a picture, a clip, a 3D model on the table", async ({ page }) => {
  const { errors } = await open(page, "making", "activity");
  const all = jobs("making");
  const pic = all.find((j) => j.kind === "lab.image" && j.state === "succeeded")!;
  await expect(card(page, pic.id).locator(".lab-pv img")).toHaveAttribute("src", /^\/fixtures\/lab\/of-[0-9a-f]{16}\.webp$/);
  await expect(card(page, pic.id).getByRole("link", { name: /^Open / })).toHaveAttribute("target", "_blank");
  const clip = all.find((j) => j.kind === "lab.video")!;
  await expect(card(page, clip.id).locator("video")).toHaveAttribute("src", /^\/fixtures\/lab\/of-[0-9a-f]{16}\.mp4$/);
  await expect(card(page, clip.id).locator("video")).toHaveJSProperty("muted", true);
  const model = all.find((j) => j.kind === "lab.model3d")!;
  await card(page, model.id).getByRole("button", { name: "On the table" }).click();
  // WebGL is off in this spec (tests/webgl.ts): the file's name and a way to it stand in
  await expect(card(page, model.id).locator(".lab-holo")).toContainText(/Putting it on the table|can't draw it here/);
  await expect(card(page, model.id).locator(".lab-holo.flat")).toBeVisible({ timeout: 15_000 });
  // its sheet puts the model on the table at once
  await page.evaluate((id) => (window.location.hash = `job/${id}`), model.id);
  const sheet = page.getByRole("dialog");
  await expect(sheet.locator(".lab-holo")).toBeVisible();
  await expect(sheet).toContainText(`bromigos activity show ${model.id}`);
  expect(errors).toEqual([]);
});

test("without the relay node: an estimate, no picture yet, and the commands where the page may not act", async ({ page }) => {
  await open(page, "making-estimate", "activity");
  const run = jobs("making-estimate").find((j) => j.lab?.source === "comfyui" && j.state === "running")!;
  await expect(hero(page).locator(".chip", { hasText: "ESTIMATE" })).toBeVisible();
  await expect(hero(page).locator(".lab-ring")).toHaveAttribute("title", /an estimate from how long this workflow took before/);
  await expect(hero(page).locator(".lab-pv")).toHaveAttribute("title", /No live picture/);
  await expect(hero(page).getByRole("button", { name: /^Interrupt / })).toHaveCount(0);
  await hero(page).locator("summary").click();
  await expect(hero(page).locator("dl.kv")).toContainText(`bromigos activity cancel ${run.id}`);
  await expect(page.locator(".ac-lab")).toContainText("ComfyUI studio · queue and results");
});

test("a media name the follower doesn't make never reaches a URL", async ({ page }) => {
  await page.route("**/fixtures/making.json", async (route) => {
    const doc = await (await route.fetch()).json();
    for (const j of doc.activity) if (j.lab?.preview) j.lab.preview.media = "../../api/session";
    doc.stream = [];
    await route.fulfill({ json: doc });
  });
  await open(page, "making", "activity");
  await expect(hero(page)).toBeVisible();
  await expect(page.locator('img[src*="api/session"], video[src*="api/session"]')).toHaveCount(0);
});

test("every control on a lab card says what it does", async ({ page }) => {
  await open(page, "making", "activity");
  const controls = page.locator(".job.lab").locator("button, a, summary");
  const n = await controls.count();
  expect(n).toBeGreaterThan(10);
  for (let i = 0; i < n; i++) {
    const c = controls.nth(i);
    const hint = (await c.getAttribute("title")) ?? (await c.locator("[title]").first().getAttribute("title").catch(() => null));
    expect(hint, await c.evaluate((e) => e.outerHTML.slice(0, 120))).toBeTruthy();
  }
});

test("at phone width: the picture above the words, and nothing scrolls sideways", async ({ page }, info) => {
  test.skip(info.project.name !== "phone", "the phone layout");
  await open(page, "making", "activity");
  await expect(hero(page)).toBeVisible();
  const w = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(w[0], "sideways scroll").toBeLessThanOrEqual(w[1]);
  const pic = (await hero(page).locator(".lab-pv").boundingBox())!, words = (await hero(page).locator(".lab-body").boundingBox())!;
  expect(words.y).toBeGreaterThanOrEqual(pic.y + pic.height - 1);
});
