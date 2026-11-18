// Where a job is drawn on the post, and whether it is drawn at all. This file is the whole
// mapping from a job record to the picture: one table of places, one table of states. Each rule
// has a sentence, and that sentence is also the hover hint on the page, so the page says the
// rule it follows.
//
// The table was written against the kinds bromigOS has (docs/activity.md):
//
//   started by its own commands today   app.install, app.remove, app.restart, app.models;
//                                       backup.drive; and the lab follower's lab.image, lab.edit,
//                                       lab.cutout, lab.upscale, lab.video, lab.model3d,
//                                       lab.comfyui and lab.pipeline (a job feed may name any lab.*)
//   named by the docs, the page's icons app.update, app.update-all, app.rollback; backup.run,
//   and the tests                       backup.restore, backup.test-restore; drive.test,
//                                       drive.replace, pool.check, storage.add, salvage.scan;
//                                       server.update, server.install
//
// A kind is any dotted words (`bromigos activity run --kind`), so a kind nobody listed here still
// has a place: the last rule.
import type { PostJob } from "./types";

/** A place a job is worked at: one of the six machines, or the landing pad. */
export type PlaceId = "rack" | "holotable" | "pad" | "fabricator" | "press" | "core" | "terminal";
/**
 * What the crew member is seen doing there: one standing loop each (the art folder's
 * NAME-ACT.webp), at the thing and facing it. The pad's work is carried instead: a crate at a
 * time from the shuttle to a stack, with "lift" the loop for bending to set one down (model.ts).
 */
export type Act = "scan" | "holo" | "lift" | "weld" | "pack" | "crank" | "work";

export interface PlaceRule {
  place: PlaceId;
  /** The place's name on the page. */
  name: string;
  act: Act;
  /** Whether a job belongs here. The first rule that says yes wins. */
  takes: (job: Pick<PostJob, "kind" | "agent">) => boolean;
  /** The rule in a sentence: the place's hover hint. */
  says: string;
}

const starts = (...words: string[]) => (job: Pick<PostJob, "kind">) => words.some((w) => job.kind.startsWith(`${w}.`));

/** The places, in order: a job goes to the first one that takes it. */
export const PLACES: readonly PlaceRule[] = [
  {
    place: "rack", name: "server rack", act: "scan",
    takes: starts("lab"),
    says: "The lab's creation jobs are worked here: every kind that starts with lab., such as a picture, a clip, a 3D model or a pipeline run.",
  },
  {
    place: "holotable", name: "hologram table", act: "holo",
    takes: (job) => !!job.agent || starts("agent", "plan", "ask", "vector")(job),
    says: "A job an AI agent asked for is worked here, and so are planning and asking jobs: the kinds that start with agent., plan., ask. or vector.",
  },
  {
    place: "pad", name: "landing pad", act: "lift",
    takes: (job) => starts("server", "system", "package", "update", "download")(job) || job.kind === "app.models",
    says: "Updates of the system and downloads arrive here, by shuttle: the kinds that start with server., system., package., update. or download., and the Creation studio's models (app.models).",
  },
  {
    place: "fabricator", name: "print bench", act: "weld",
    takes: starts("app"),
    says: "Work on an app is done here: every other kind that starts with app., such as installing, updating, restarting or removing one.",
  },
  {
    place: "press", name: "press", act: "pack",
    takes: starts("backup", "snapshot", "restore"),
    says: "Backups, snapshots and restores are packed here: the kinds that start with backup., snapshot. or restore.",
  },
  {
    place: "core", name: "power core", act: "crank",
    takes: starts("drive", "pool", "storage", "disk", "power", "ups", "hardware", "salvage"),
    says: "Work on drives, storage, power and hardware is done here: the kinds that start with drive., pool., storage., disk., power., ups., hardware. or salvage.",
  },
  {
    place: "terminal", name: "terminal", act: "work",
    takes: () => true,
    says: "A job of any other kind is worked here.",
  },
];

/** The rule a job falls under. There is always one: the last takes everything. */
export const placeFor = (job: Pick<PostJob, "kind" | "agent">): PlaceRule => PLACES.find((p) => p.takes(job)) ?? PLACES[PLACES.length - 1];
export const placeRule = (place: PlaceId): PlaceRule => PLACES.find((p) => p.place === place)!;

/** How a job is drawn: at work, standing and waiting for an answer, or not at all. */
export type Mode = "run" | "ask";

/** The states, each with its sentence. `mode` null: the job isn't drawn. */
export const STATES: readonly { state: PostJob["state"]; mode: Mode | null; says: string }[] = [
  { state: "running", mode: "run", says: "A job that is running has one of the crew working at its place, on a ring of light." },
  { state: "needs-you", mode: "ask", says: "A job that waits for a person's answer has one of the crew standing at its place, not working, on an amber ring." },
  { state: "queued", mode: null, says: "A job that is queued isn't drawn: nobody is working on it yet." },
  { state: "waiting", mode: null, says: "A job that waits for the internet or for another job isn't drawn: nobody is working on it." },
  { state: "succeeded", mode: null, says: "A job that finishes while the page is open lights its room once. One that ended before isn't drawn." },
  { state: "failed", mode: null, says: "A job that fails while the page is open flashes its room red once. One that failed before isn't drawn." },
  { state: "rolled-back", mode: null, says: "A job that failed and put things back flashes its room red once, like one that failed." },
  { state: "interrupted", mode: null, says: "A job that was interrupted flashes its room red once, like one that failed." },
  { state: "cancelled", mode: null, says: "A job that was stopped leaves quietly: its crew member walks back to the quarters." },
  { state: "unknown", mode: null, says: "A job in a state the page doesn't know isn't drawn." },
];

/** The other rules the picture follows, each a sentence the page can say. */
export const RULES = {
  part: "A job that is a part of another is drawn as that job, not beside it.",
  crew: "There are three crew. A job keeps the one it was given. A fourth job at once runs its room and its machine with nobody standing there.",
  rest: "With no job to work on, the crew rest in the quarters.",
  ring: "The ring fills with the job's own share done. A job that never said one gets a short arc that turns.",
} as const;

/**
 * How a job is drawn: "run", "ask", or null for not at all. A job that is a part of another
 * the page also has is not drawn by itself (RULES.part).
 */
export function drawn(job: PostJob, has: (id: string) => boolean): Mode | null {
  if (job.parent && has(job.parent)) return null;
  return STATES.find((s) => s.state === job.state)?.mode ?? null;
}

/** How a job that left the picture ended: well, badly, or with nothing to show. */
export function ending(job: PostJob): "ok" | "fail" | null {
  if (job.state === "succeeded") return job.ok === false ? "fail" : "ok";
  if (job.state === "failed" || job.state === "rolled-back" || job.state === "interrupted") return "fail";
  return null;
}
