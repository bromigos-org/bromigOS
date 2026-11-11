// How a job (the activity record, DESIGN.md §4) reads on the page: its icon, its state's word
// and chip, a step's look, and which job the strip shows.
import type { Board, JobRecord, JobState, StepState } from "./api/types";
import { FINAL_STATES } from "./api/types";

const KIND_ICON: Record<string, string> = {
  "app.install": "i-add",
  "app.update": "i-update",
  "app.remove": "i-remove",
  "app.rollback": "i-rollback",
  "backup.run": "i-backup",
  "backup.restore": "i-restore",
  "backup.test-restore": "i-testrestore",
  "drive.test": "i-find",
  "drive.replace": "i-swap",
  "pool.check": "i-find",
  "server.update": "i-update",
  "salvage.scan": "i-chip",
};
export const jobIcon = (j: JobRecord) => (j.children.length > 1 && j.kind === "app.update" ? "i-updateall" : KIND_ICON[j.kind] ?? "i-job");

/** The words the activity command uses for each state (bin/bromigos-activity). */
export const STATE_WORD: Record<JobState, string> = {
  queued: "queued",
  running: "running",
  "needs-you": "needs you",
  waiting: "waiting",
  succeeded: "done",
  failed: "failed",
  "rolled-back": "put back",
  cancelled: "cancelled",
  interrupted: "interrupted",
};

export const STATE_HINT: Record<JobState, string> = {
  queued: "queued: it starts when what it waits for is free",
  running: "running: the job is going now",
  "needs-you": "needs you: the job carries on when you answer",
  waiting: "waiting: it carries on by itself when what it waits for is back",
  succeeded: "done: the job finished",
  failed: "failed: it stopped before it finished, and says why",
  "rolled-back": "put back: it failed and put things back as they were, by itself",
  cancelled: "cancelled: someone stopped it",
  interrupted: "interrupted: it stopped with no word of how it ended, as after a power cut",
};

/** The chip's look: a Reading (plain, lit) or a State colour, which always carries its shape. */
export const STATE_CHIP: Record<JobState, string> = {
  queued: "chip",
  running: "chip lit",
  "needs-you": "chip amber",
  waiting: "chip",
  succeeded: "chip",
  failed: "chip red",
  "rolled-back": "chip amber",
  cancelled: "chip",
  interrupted: "chip amber",
};

export const waitWord = (j: JobRecord) =>
  j.state === "waiting" && j.waiting_for ? `waiting for ${j.waiting_for === "you" ? "you" : j.waiting_for === "another job" ? "another job" : `the ${j.waiting_for}`}` : STATE_WORD[j.state];

/** A step's class in ol.steps and its shape. */
export const STEP: Record<StepState, { cls: string; icon: string; word: string }> = {
  todo: { cls: "todo", icon: "s-todo", word: "todo" },
  running: { cls: "now", icon: "s-start", word: "running" },
  waiting: { cls: "ask", icon: "s-wait", word: "waiting" },
  done: { cls: "done", icon: "s-done", word: "done" },
  failed: { cls: "fail", icon: "s-fail", word: "failed" },
  skipped: { cls: "skip", icon: "s-skip", word: "skipped" },
};

export const isOpen = (j: JobRecord) => !FINAL_STATES.includes(j.state);
const BAD: JobState[] = ["failed", "rolled-back", "interrupted"];

export type StripPick =
  | { kind: "job"; job: JobRecord; look: "run" | "ask" | "fail" | "" }
  | { kind: "alert"; words: string; detail: string | null; machine: string; go: string | null }
  | { kind: "idle"; last: JobRecord | null };

/**
 * What the strip shows, most urgent first: a job that asks you; an alert that needs you; a job
 * that runs (or waits, or is queued); one that ended badly in the last day; else the last job.
 */
export function stripPick(jobs: JobRecord[], board: Board | null, now: number): StripPick {
  const top = jobs.filter((j) => !j.parent);
  const ask = top.find((j) => j.state === "needs-you");
  if (ask) return { kind: "job", job: ask, look: "ask" };
  const alert = board?.needs_you.find((n) => !n.job);
  if (alert) return { kind: "alert", words: alert.words, detail: alert.detail, machine: alert.machine, go: alert.go };
  const run = top.find((j) => j.state === "running") ?? top.find(isOpen);
  if (run) return { kind: "job", job: run, look: run.state === "running" ? "run" : "" };
  const bad = top.find((j) => BAD.includes(j.state) && now - (j.ended_at ?? j.updated_at) < 86_400_000);
  if (bad) return { kind: "job", job: bad, look: "fail" };
  return { kind: "idle", last: top[0] ?? null };
}

/** "step 2 of 4 · Copying what changed" or the stage words. */
export function progressWords(j: JobRecord): string {
  const parts: string[] = [];
  if (j.steps.length && j.step !== null) parts.push(`step ${j.step + 1} of ${j.steps.length}`, j.steps[j.step]?.label ?? "");
  else if (j.stage) parts.push(j.stage);
  if (j.pct !== null) parts.push(`${j.pct} %`);
  return parts.filter(Boolean).join(" · ");
}
