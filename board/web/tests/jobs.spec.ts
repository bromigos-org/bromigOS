// A job's controls: its answers, Stop and Start again, on the job cards (the drawer, Activity, a
// job's own sheet). Each is a control only when the server lets the page (board.actions holds
// "job.answer", "job.cancel", "job.retry") and the job's record says it may be done now (`can`);
// otherwise the card shows the command. A choice that can't be undone asks for a fresh code.
import { expect, test, type Page } from "@playwright/test";
import { open } from "./helpers";
import { Answer, copy, openReal, real, realAnswer, Service, whole } from "./service";

const card = (page: Page, text: string) => page.locator("#view .job", { hasText: text });
const ID = (kind: string, state: string) => real.boards.jobs_controls.activity.jobs.find((j: { kind: string; state: string }) => j.kind === kind && j.state === state).id as string;
const ASKS = ID("storage.add", "needs-you"), RUNS = ID("backup.run", "running"), FAILED = ID("backup.run", "failed");
const BUSY_WORDS = "The server is busy: many codes are being tried at once. Your code wasn't used. Try it again in a moment.";
const BUSY = new Answer(503, { headers: { "retry-after": "5" }, body: { error: { code: "busy", words: BUSY_WORDS } } });

test("with the server's leave: the answers, Stop and Start again are controls, and no command is shown for them", async ({ page }) => {
  await open(page, "jobs", "activity");
  const ask = card(page, "Adding a disk: sdc");
  await expect(ask.getByRole("group", { name: /Answers to/ }).getByRole("button")).toHaveText(["Wipe sdc and use it", "Leave sdc as it is"]);
  await expect(ask.getByRole("button", { name: "Wipe sdc and use it" })).toHaveClass(/danger/);
  await expect(ask.locator("pre", { hasText: "activity answer" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Stop Backing up this server" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Start Backing up this server again" })).toHaveCount(1);
  // a job that ended well offers nothing
  await expect(card(page, "Backed up: the copy checks out.").getByRole("button")).toHaveCount(0);
});

test("a choice that can't be undone asks for a fresh code first, and Back sends nothing", async ({ page }) => {
  await open(page, "jobs", "activity");
  const ask = card(page, "Adding a disk: sdc");
  await ask.getByRole("button", { name: "Wipe sdc and use it" }).click();
  await expect(ask).toContainText("can't be undone. It needs a fresh code from sudo bromigos server board code");
  const go = ask.getByRole("button", { name: "Wipe sdc and use it" });
  await expect(go).toHaveAttribute("aria-disabled", "true");
  await ask.getByLabel("One-time code").fill("kx7 42q");
  await expect(go).toHaveAttribute("aria-disabled", "false");
  await ask.getByRole("button", { name: "Back" }).click();
  await expect(ask.getByLabel("One-time code")).toHaveCount(0);
  await expect(ask.getByRole("button", { name: "Leave sdc as it is" })).toBeVisible();
});

test("without the server's leave: the question, its answers and the command, and no control", async ({ page }) => {
  await open(page, "needs-you", "activity");
  const ask = card(page, "Replacing a drive: sdb");
  await expect(ask.getByRole("button")).toHaveCount(0);
  await expect(ask.locator("pre").first()).toHaveText(/^sudo bromigos activity answer \S+ swapped$/);
  await expect(ask.locator(".job-q .pl")).toHaveCount(1);
});

test.describe("the real client, the service's real answers", () => {
  test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "the contract is the same at every width"));

  const posts = (s: Service) => s.seen.filter((x) => x.method === "POST" && x.path.startsWith("/api/activity/"));

  test("an answer: sent as the service asks, and its words shown", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.jobs_controls;
    s.jobAnswers = [{ schema: 1, ok: true, job: ASKS, request: "r1", words: "Answered." }];
    const w = await openReal(page, s, "activity");
    const ask = card(page, "Adding a disk: sdc");
    await ask.getByRole("button", { name: "Leave sdc as it is" }).click();
    await expect(ask.locator("[role=status]")).toHaveText("Answered.");
    const p = posts(s);
    expect(p.map((x) => x.path)).toEqual([`/api/activity/${ASKS}/answer`]);
    expect(JSON.parse(p[0].body!)).toEqual({ question: "wipe", choice: "keep" });
    expect(p[0].headers["x-bromigos-board"]).toBe("1");
    expect(p[0].headers["content-type"]).toMatch(/^application\/json/);
    await whole(page, w, "a job answered");
  });

  test("a choice that can't be undone: the code goes with it, a wrong one is said in the service's words, busy keeps the code", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.jobs_controls;
    s.jobAnswers = [realAnswer("job_answer_danger_wrong_code"), BUSY, { schema: 1, ok: true, job: ASKS, request: "r3", words: "Answered." }];
    await openReal(page, s, "activity", { quiet: /403|503/ });
    const ask = card(page, "Adding a disk: sdc");
    await ask.getByRole("button", { name: "Wipe sdc and use it" }).click();
    await ask.getByLabel("One-time code").fill("wxyz 9999");
    await ask.getByRole("button", { name: "Wipe sdc and use it" }).click();
    await expect(ask.locator("[role=status]")).toHaveText(real.http.job_answer_danger_wrong_code.body.error.words);
    await ask.getByLabel("One-time code").fill("kx7-42q");
    await ask.getByRole("button", { name: "Wipe sdc and use it" }).click();
    await expect(ask.locator("[role=status]")).toHaveText(BUSY_WORDS);
    await expect(ask.getByLabel("One-time code")).toHaveValue("kx7-42q");
    await ask.getByRole("button", { name: "Wipe sdc and use it" }).click();
    await expect(ask.locator("[role=status]")).toHaveText("Answered.");
    expect(posts(s).map((x) => JSON.parse(x.body!))).toEqual([
      { question: "wipe", choice: "wipe", code: "WXYZ9999" },
      { question: "wipe", choice: "wipe", code: "KX7-42Q" },
      { question: "wipe", choice: "wipe", code: "KX7-42Q" },
    ]);
  });

  test("Stop: sent with nothing in it; a job that ended meanwhile is said in the service's words", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.jobs_controls;
    s.jobAnswers = [realAnswer("job_cancel_ended"), { schema: 1, ok: true, job: RUNS, request: "r2", words: "Stopped." }];
    await openReal(page, s, "activity", { quiet: /409/ });
    const stop = page.getByRole("button", { name: "Stop Backing up this server" });
    const runs = page.locator(`#view .job[data-job='${RUNS}']`);
    await stop.click();
    await expect(runs.locator("[role=status]")).toHaveText(real.http.job_cancel_ended.body.error.words);
    await stop.click();
    await expect(runs.locator("[role=status]")).toHaveText("Stopped.");
    expect(posts(s).map((x) => [x.path, JSON.parse(x.body!)])).toEqual([[`/api/activity/${RUNS}/cancel`, {}], [`/api/activity/${RUNS}/cancel`, {}]]);
  });

  test("Start again: the new job's card is a link away", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.jobs_controls;
    s.jobAnswers = [{ schema: 1, ok: true, job: "20261110-0601-backup.run-myserver-aa11", request: "r4", words: "Started again." }];
    await openReal(page, s, "activity");
    const failed = page.locator(`#view .job[data-job='${FAILED}']`);
    await failed.getByRole("button", { name: "Start Backing up this server again" }).click();
    await expect(failed.locator("[role=status]")).toContainText("Started again.");
    await expect(failed.getByRole("link", { name: "Open the new job" })).toHaveAttribute("href", "#job/20261110-0601-backup.run-myserver-aa11");
    expect(posts(s).map((x) => x.path)).toEqual([`/api/activity/${FAILED}/retry`]);
  });

  test("each control needs its own word from the server, and the job's own leave", async ({ page }) => {
    const s = new Service();
    s.board = { ...copy(real.boards.jobs_controls), actions: ["restart", "job.answer"] };
    await openReal(page, s, "activity");
    await expect(card(page, "Adding a disk: sdc").getByRole("button", { name: "Leave sdc as it is" })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Stop |again$/ })).toHaveCount(0);
    // the commands stand in for the controls the server doesn't allow
    await expect(page.locator(`#view .job[data-job='${RUNS}']`)).toContainText(`sudo bromigos activity cancel ${RUNS}`);
    await expect(page.locator(`#view .job[data-job='${FAILED}']`)).toContainText(`sudo bromigos activity retry ${FAILED}`);
    // an upgraded server that lists nothing: no control anywhere, and nothing but GETs
    s.board = { ...copy(real.boards.jobs_controls), actions: [] };
    await page.reload();
    await expect(page.locator("#view .job").getByRole("button")).toHaveCount(0);
    expect(s.seen.filter((x) => x.method !== "GET")).toEqual([]);
  });

  test("the drawer's cards have the same controls", async ({ page }) => {
    const s = new Service();
    s.board = real.boards.jobs_controls;
    s.jobAnswers = [{ schema: 1, ok: true, job: ASKS, request: "r5", words: "Answered." }];
    await openReal(page, s, "home");
    await page.getByRole("button", { name: "Raise the drawer of jobs" }).click();
    const drawer = page.getByRole("complementary", { name: "Activity" });
    await drawer.getByRole("button", { name: "Leave sdc as it is" }).click();
    await expect(drawer.locator(".job", { hasText: "Adding a disk: sdc" }).locator("[role=status]")).toHaveText("Answered.");
  });
});
