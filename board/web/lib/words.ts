// The page's headlines: one line that says the worst of what is under it. The rule they all
// keep: a headline never rounds up. "All … nominal" or "healthy" is said only when every
// part under it was read and is; a part that couldn't be read, a drive that can't tell or is
// on watch, an app whose state is unknown each get their own words. Old readings say how old.
import type { BackupsStatus, Board, Drive, DriveVerdict, Machine, Part, Shape, Tile } from "./api/types";
import { span } from "./time";

/** How a headline is drawn: plain (the world's colour), a warning, or quiet grey (not known). */
export type Look = "" | "warn" | "q";
export interface Headline {
  words: string;
  look: Look;
  hint: string;
}

const n = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

// ---------------------------------------------------------------- drives

/** A verdict's shape (DESIGN §5: watch is the broken diamond) and whether it is an alarm. */
export const DRIVE_SHAPE: Record<DriveVerdict, Shape> = { healthy: "ok", watch: "warn", checking: "warn", worse: "warn", replace: "down", unknown: "unknown" };
export const DRIVE_ALARM: Record<DriveVerdict, boolean> = { healthy: false, watch: false, checking: true, worse: true, replace: true, unknown: false };
const DRIVE_RANK: DriveVerdict[] = ["healthy", "watch", "unknown", "checking", "worse", "replace"];
const DRIVE_HEAD: Record<DriveVerdict, [string, string]> = {
  healthy: ["HEALTHY", "HEALTHY"],
  watch: ["TO WATCH", "TO WATCH"],
  unknown: ["CAN'T BE READ", "CAN'T BE READ"],
  checking: ["HAS ERRORS, STILL CHECKING", "HAVE ERRORS, STILL CHECKING"],
  worse: ["GETTING WORSE", "GETTING WORSE"],
  replace: ["TO REPLACE SOON", "TO REPLACE SOON"],
};

/** The worst drive that is connected, or null when all are healthy (or there are none). */
export function worstDrive(drives: Drive[]): Drive | null {
  const here = drives.filter((d) => d.present && d.verdict !== "healthy");
  return here.sort((a, b) => DRIVE_RANK.indexOf(b.verdict) - DRIVE_RANK.indexOf(a.verdict))[0] ?? null;
}

export function drivesHeadline(drives: Drive[]): Headline {
  const here = drives.filter((d) => d.present);
  if (!here.length) return { words: "NO DRIVES READ", look: "q", hint: "No connected drive has been read" };
  const worst = worstDrive(here);
  if (!worst) return { words: "ALL DRIVES HEALTHY", look: "", hint: "Every connected drive was read, and each is healthy" };
  const same = here.filter((d) => d.verdict === worst.verdict).length;
  const others = here.filter((d) => d.verdict !== "healthy" && d.verdict !== worst.verdict).length;
  const [one, many] = DRIVE_HEAD[worst.verdict];
  return {
    words: `${same} ${same === 1 ? one : many}${others ? ` · ${others} MORE NOT HEALTHY` : ""}`,
    look: DRIVE_ALARM[worst.verdict] ? "warn" : worst.verdict === "unknown" ? "q" : "",
    hint: "The drives' one line: the worst verdict among the connected drives, in its own words",
  };
}

// ---------------------------------------------------------------- the lab and a machine

const PART: Record<Part, string> = { apps: "THE APPS", drives: "THE DRIVES", backups: "THE BACKUPS", updates: "THE UPDATES", alerts: "THE ALERTS", jobs: "THE JOBS" };
export const PART_WORDS: Record<Part, string> = { apps: "the apps", drives: "the drives' health", backups: "the backups", updates: "the updates", alerts: "the alerts", jobs: "the jobs" };

const notRunning = (apps: Tile[] | null, machine?: string) =>
  (apps ?? []).filter((t) => t.installed && t.state !== "ok" && t.state !== "starting" && t.state !== "updating" && (!machine || !t.machine || t.machine === machine));

/** Old readings: how old, or that the page is still reading after a pause. Null when fresh. */
export function oldHeadline(b: Board, stale: boolean, settling: boolean, now: number): Headline | null {
  if (!stale) return null;
  if (settling) return { words: "READING THE SERVER", look: "q", hint: "The page was just opened or looked at again: the server is reading itself, and the board follows in a few seconds" };
  if (b.at <= 0) return { words: "NOT READ YET", look: "q", hint: "The server hasn't said when it last read itself" };
  return {
    words: `NOT READ FOR ${span(now - b.at).toUpperCase()}`,
    look: "q",
    hint: "The last reading is older than the server allows: what the page shows may be out of date",
  };
}

/**
 * The one status line of the lab (Home), or of one machine (its page). In order: old readings;
 * a first run; what needs a person; apps that aren't running; machines or parts that couldn't
 * be checked; drives on watch or unreadable; and only then "nominal".
 */
export function headline(b: Board, o: { stale: boolean; settling: boolean; now: number; machine?: Machine }): Headline {
  const m = o.machine;
  const old = oldHeadline(b, o.stale, o.settling, o.now);
  if (old) return old;
  const here = !m || m.here; // the parts below are this server's
  if (here && b.status.state === "setup" && b.apps) return { words: "NOTHING INSTALLED YET", look: "q", hint: "Nothing is installed on this server yet: its Set-up shows what to do first" };
  const needs = b.needs_you.filter((x) => !m || x.machine === m.name);
  if (m) {
    if (needs.length) return { words: `${n(needs.length, "THING NEEDS", "THINGS NEED")} YOU`, look: "warn", hint: "What on this machine needs a person: the list is below" };
    if (m.state === "warn" || m.state === "down") return { words: m.state_word.toUpperCase(), look: "warn", hint: "This machine's state, as the server says it" };
    if (m.state === "unknown") return { words: m.state_word.toUpperCase(), look: "q", hint: "This machine's state isn't known" };
  } else {
    const bad = new Set(b.machines.filter((x) => x.state === "warn" || x.state === "down").map((x) => x.name));
    for (const x of needs) bad.add(x.machine);
    if (bad.size) return { words: `${n(bad.size, "MACHINE NEEDS", "MACHINES NEED")} YOU`, look: "warn", hint: "The lab's one status line: the worst state across its machines" };
    const dark = b.machines.filter((x) => x.state === "unknown").length;
    if (dark) return { words: `${n(dark, "MACHINE", "MACHINES")} CAN'T BE CHECKED`, look: "q", hint: "A machine whose state isn't known: it hasn't reported" };
  }
  if (here) {
    const down = notRunning(b.apps, m?.name);
    if (down.length) return { words: `${n(down.length, "APP ISN'T", "APPS AREN'T")} RUNNING`, look: "warn", hint: `Not running, or not known to be: ${down.map((t) => t.job).join(", ")}` };
    if (b.backups?.health.state === "attention") return { words: "THE BACKUPS NEED A LOOK", look: "warn", hint: b.backups.health.verdict };
    if (b.unread.length)
      return {
        words: b.unread.length > 2 ? `${b.unread.length} PARTS COULDN'T BE READ` : `COULDN'T READ ${b.unread.map((p) => PART[p]).join(" OR ")}`,
        look: "q",
        hint: `The server couldn't read ${b.unread.map((p) => PART_WORDS[p]).join(", ")} this time, so the page can't say all is well`,
      };
    const worst = b.storage ? worstDrive(b.storage.drives) : null;
    if (worst) return drivesHeadline(b.storage!.drives);
  }
  return m
    ? { words: "ALL SYSTEMS NOMINAL", look: "", hint: "Everything on this machine was read, and nothing needs you" }
    : { words: "ALL MACHINES NOMINAL", look: "", hint: "The lab's one status line: everything was read, and nothing needs you on any machine" };
}

// ---------------------------------------------------------------- backups

/** The newest good copy anywhere: the nightly destination's, or a carried drive's. Seconds. */
export const lastGoodCopy = (d: BackupsStatus): number | null => {
  const all = [d.last_success_ts, ...d.drives.map((c) => c.last_good_ts)].filter((x): x is number => x !== null);
  return all.length ? Math.max(...all) : null;
};

export function backupsHeadline(d: BackupsStatus, now: number): Headline {
  const last = lastGoodCopy(d);
  const ago = last !== null ? span(now - last * 1000).toUpperCase() : null;
  const hint = d.health.verdict || "The backups' one line";
  if (!d.configured && !d.drives.length) return { words: "BACKUPS ARE OFF", look: "q", hint };
  switch (d.health.state) {
    case "attention":
      return { words: ago ? `NEEDS A LOOK · LAST GOOD COPY ${ago} AGO` : "NEEDS A LOOK · NO GOOD COPY YET", look: "warn", hint };
    case "ok":
      return ago ? { words: `BACKED UP ${ago} AGO`, look: "", hint } : { words: "NO GOOD COPY YET", look: "q", hint };
    case "waiting":
      return { words: "WAITING FOR THE FIRST BACKUP", look: "q", hint };
    case "off":
      return { words: "BACKUPS ARE OFF", look: "q", hint };
    default:
      return { words: "CAN'T TELL", look: "q", hint };
  }
}

export const BACKUP_SHAPE: Record<BackupsStatus["health"]["state"], Shape> = { ok: "ok", attention: "warn", waiting: "unknown", off: "unknown", unknown: "unknown" };
/** The state's own word beside its shape. */
export const BACKUP_WORD: Record<BackupsStatus["health"]["state"], string> = { ok: "ok", attention: "needs a look", waiting: "waiting", off: "off", unknown: "can't tell" };
