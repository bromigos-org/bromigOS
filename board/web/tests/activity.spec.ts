// Activity's own page: every job the page knows (the stream's and the board's list), in three
// groups, each job with its steps, what it asks, how it ended and the command that looks
// closer. Read-only: no control answers, stops or restarts a job, and nothing but GETs is sent.
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { open } from "./helpers";
import { Answer, copy, live, openReal, real, Service, whole } from "./service";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.json`, import.meta.url), "utf8"));
const group = (page: import("@playwright/test").Page, name: string) => page.locator(".ac-group", { hasText: name });

test("the three groups, and what each job says", async ({ page }) => {
  const jobs = fixture("needs-you").activity as { id: string; state: string }[];
  await open(page, "needs-you", "activity");
  await expect(page.locator(".ac-rd .rd .v")).toHaveText(["1", "0", "2", "live"]);
  // the one that asks: its question, its answers, and the command that answers it
  const asks = group(page, "NEED YOU · 1").locator(".job");
  await expect(asks).toHaveCount(1);
  await expect(asks).toContainText("Swap the drive now. It is safe to pull sdb.");
  await expect(asks.locator(".job-as li")).toHaveText(["swapped I've swapped it", "undo Put sdb back in use"]);
  const asking = jobs.find((j) => j.state === "needs-you")!.id;
  await expect(asks.locator(".job-q pre")).toHaveText(`sudo bromigos activity answer ${asking} swapped`);
  await expect(group(page, "GOING · 0")).toContainText("Nothing is running or waiting.");
  // the ones that ended: what it did, or where and why it stopped, and how it ended
  const ended = group(page, "ENDED · 2").locator(".job");
  await expect(ended).toHaveCount(2);
  await expect(ended.filter({ hasText: "Backing up this server" })).toContainText("Backed up: the copy checks out.");
  const back = ended.filter({ hasText: "Updating Photos" });
  await expect(back).toContainText("Stopped at Checking that it answers: no answer in 2 minutes");
  await expect(back).toContainText("It failed and put things back by itself.");
  await expect(back).toContainText("PUT BACK");
  // every job: the exact command to look closer, and its log behind Depth
  for (const j of jobs) await expect(page.locator(`.job[data-job="${j.id}"] .job-closer > pre`)).toHaveText(`bromigos activity show ${j.id}`);
  await back.locator("summary").click();
  await expect(back.locator("dl.kv")).toContainText(`/var/lib/bromigos/activity/jobs/${jobs.find((j) => j.state === "rolled-back")!.id}.log`);
  // read-only: nothing here answers, stops or restarts a job
  await expect(page.locator("#view").getByRole("button", { name: /swapped|answer|cancel|retry|stop|again/i })).toHaveCount(0);
  await expect(page.locator(".panel", { hasText: "UPCOMING" }).locator(".pl")).toHaveCount(1);
});

test("a running job: how far, that stopping is safe, and its end when it comes", async ({ page }) => {
  await page.route("**/fixtures/running.json", async (route) => {
    const doc = await (await route.fetch()).json();
    await route.fulfill({ json: { ...doc, stream: doc.stream.map((e: { after_ms: number }) => ({ ...e, after_ms: e.after_ms + 2500 })) } });
  });
  const id = (fixture("running").activity as { id: string; state: string }[]).find((j) => j.state === "running")!.id;
  await open(page, "running", "activity");
  const going = group(page, "GOING · 1").locator(".job");
  await expect(going).toContainText("Copying what changed");
  await expect(going.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
  await expect(going).toContainText(`Stopping it now is safe: sudo bromigos activity cancel ${id}`);
  await expect(group(page, "ENDED · 2")).toContainText("Backed up: the copy checks out.", { timeout: 10_000 });
  await expect(group(page, "GOING · 0")).toBeVisible();
});

test("one job by its address, and a job the server no longer lists", async ({ page }) => {
  const id = (fixture("needs-you").activity as { id: string; state: string }[]).find((j) => j.state === "rolled-back")!.id;
  await open(page, "needs-you", `job/${id}`);
  const sheet = page.getByRole("dialog", { name: "Updating Photos" });
  await expect(sheet).toContainText("Stopped at Checking that it answers");
  await expect(sheet.locator(".job-closer > pre")).toHaveText(`bromigos activity show ${id}`);
  await sheet.getByRole("link", { name: "Close" }).click();
  await expect(page.locator(".sh-crumb")).toHaveText(/Activity › Now$/);
  await page.evaluate(() => (window.location.hash = "job/20200101-0000-backup.run-gone-0000"));
  await expect(page.getByRole("dialog", { name: "A job" })).toContainText("The server no longer lists a job with that id");
  await expect(page.getByRole("dialog", { name: "A job" })).toContainText("bromigos activity show 20200101-0000-backup.run-gone-0000");
});

test("what needs you, and what fixed itself, open their job", async ({ page }) => {
  const jobs = fixture("needs-you").activity as { id: string; state: string }[];
  await open(page, "needs-you", "home");
  await page.locator(".hm-needs .lb-need", { hasText: "Replacing a drive" }).getByRole("link").click();
  await expect(page).toHaveURL(new RegExp(`#job/${jobs.find((j) => j.state === "needs-you")!.id.replace(/\./g, "\\.")}$`));
  await expect(page.getByRole("dialog", { name: "Replacing a drive: sdb" })).toBeVisible();
  await page.evaluate(() => (window.location.hash = "m/myserver"));
  await page.locator(".panel", { hasText: "FIXED BY ITSELF" }).getByRole("link").click();
  await expect(page.getByRole("dialog", { name: "Updating Photos" })).toBeVisible();
});

// ---------------------------------------------------------------- the real client

test.describe("against the service's real answers", () => {
  test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "the contract is the same at every width"));

  test("every job from the stream and from the board's list, the later record winning", async ({ page }) => {
    const s = new Service();
    const b = copy(real.boards.needs_you);
    const [asks, done, back] = b.activity.jobs;
    // the board's list holds the backup and the rolled-back update; the stream holds the job that
    // asks and a later record of the backup
    b.activity.jobs = [{ ...done, title: "Backing up this server (as the board read it)" }, back];
    s.board = b;
    s.activity = `event: snapshot\ndata: ${JSON.stringify({ schema: 1, jobs: [asks, { ...done, updated_at: done.updated_at + 1000, title: "Backing up this server (as the stream has it)" }] })}\n\n`;
    const w = await openReal(page, s, "activity");
    await expect(page.locator(".ac-group .job")).toHaveCount(3);
    await expect(group(page, "NEED YOU · 1")).toContainText("Replacing a drive: sdb");
    await expect(group(page, "ENDED · 2")).toContainText("Backing up this server (as the stream has it)");
    await expect(group(page, "ENDED · 2")).toContainText("Updating Photos");
    await whole(page, w, "activity");
    expect(s.seen.filter((x) => x.method !== "GET")).toEqual([]);
  });

  test("the stream refused, the board's list read: the jobs, said to be not live", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.needs_you;
    s.activity = new Answer(502, { text: "Bad Gateway" });
    await openReal(page, s, "activity", { quiet: /EventSource|event-stream/ });
    await expect(page.locator(".ac-group .job")).toHaveCount(3);
    await expect(page.locator(".ac-rd .rd .v").last()).toHaveText("not live · reconnecting");
  });

  test("neither the stream nor the list: the jobs couldn't be read, and nothing is claimed", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.activity_missing;
    s.activity = new Answer(502, { text: "Bad Gateway" });
    await openReal(page, s, "activity", { quiet: /EventSource|event-stream/ });
    await expect(page.locator("#view")).toContainText("The jobs couldn't be read on the server: bromigos: no such command");
    await expect(page.locator(".ac-rd .rd .v")).toHaveText(["·", "·", "·", "not read"]);
    await expect(page.locator(".ac-group")).toHaveCount(0);
    await expect(page.locator("#view")).not.toContainText("Nothing is running");
  });

  test("the board's list of jobs as anything but a list: the stream's jobs stand, and nothing blanks", async ({ page }) => {
    const s = new Service();
    s.activity = live("activity_needs_you");
    const w = await openReal(page, s, "activity");
    for (const value of [null, {}, [], "x", 7, true, { jobs: "x" }, { jobs: [null, 7, "x", {}, { id: 3 }, []] }, { schema: 1, ok: false, error: "it could not be read" }]) {
      s.board = { ...copy(real.boards.needs_you), activity: value };
      await page.reload();
      await expect(page.locator(".ac-group .job")).toHaveCount(3);
      await whole(page, w, `activity = ${JSON.stringify(value)}`);
    }
  });

  for (const name of ["healthy", "needs_you", "running", "setup"])
    test(`the real stream "${name}" on the page`, async ({ page }) => {
      const s = new Service();
      s.board = real.boards[name];
      s.activity = live(`activity_${name}`);
      const w = await openReal(page, s, "activity");
      await expect(page.locator(".ac-rd .rd .v").last()).toHaveText("live");
      await expect(page.locator(".ac-group .job")).toHaveCount(real.boards[name].activity.jobs.length);
      await whole(page, w, `activity, ${name}`);
    });
});
