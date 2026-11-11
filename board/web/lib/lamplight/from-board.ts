// The Lab board's own document (`GET /api/board`, docs/board.md) as Lamplight's data. Nothing is
// added that the board didn't send: no stars, goals, show, friends or plan, so none is drawn.
//
// The types here are only the keys this reads, so the board's own `Board` and `JobRecord` types
// (lib/api/types.ts) can be passed as they are.
import { sane } from "./sane";
import type { LampJob, LampKind, LampMachine, LampNeed, LampState, LamplightData } from "./types";

export interface BoardLike {
  at: number;
  lab: { name: string; address?: string | null };
  status: { state: "ok" | "needs-you" | "setup" | "unknown"; words: string };
  machines: { name: string; kind: string; here?: boolean; page?: boolean; state: string; state_word: string; roles: string[]; apps: number | null }[];
  needs_you: { id: string; machine: string; subject: { type: string; id?: string; name: string } | null; severity: string; words: string; detail: string | null; since: number | null; go: string | null; job: string | null }[];
}
export interface JobLike {
  id: string;
  kind: string;
  title: string;
  state: string;
  pct: number | null;
}

const list = <T>(v: T[] | null | undefined): T[] => (Array.isArray(v) ? v.filter((x) => x && typeof x === "object") : []);
const text = (v: unknown): string => (typeof v === "string" ? v : "");

/** What the board's document doesn't carry, and its page knows. */
export interface BoardExtras {
  jobs?: JobLike[];
  mascot?: "on" | "quiet" | "off";
  quiet?: { on: boolean; until?: string | null } | null;
  /** The page's own status line (lib/words.ts): shown as the station's one line. */
  headline?: LamplightData["headline"];
  /** The reading's time and its age, in the page's own words ("21:53", "just now"). */
  clock?: string | null;
  age?: string | null;
  /** The reading is older than the server allows: the station shows no signal, and no state as known. */
  stale?: boolean;
}

/**
 * The board's document as the station's data. It is a server's answer, so nothing in it is taken
 * on trust: a list that isn't one is empty, a word that isn't text is absent, and the result goes
 * through sane() (sane.ts), where a state or a kind that isn't one becomes "unknown" or "other".
 */
export function fromBoard(board: BoardLike, more: BoardExtras = {}): LamplightData {
  const status = board?.status ?? { state: "unknown", words: "" }, all = list(board?.machines);
  const setup = status.state === "setup";
  const needs: LampNeed[] = list(board?.needs_you).map((n) => ({
    id: n.id, machine: n.machine, words: n.words, detail: n.detail, severity: n.severity === "warn" ? "warn" : "danger",
    subject: n.subject ? { type: n.subject.type, name: n.subject.name } : null, go: n.go, job: n.job, since: n.since,
  }));
  const machines: LampMachine[] = all.map((m) => {
    // a server with nothing installed yet is being set up: its own word, and never an alarm
    const fresh = setup && (m.here || all.length === 1) && !needs.some((n) => n.machine === m.name);
    const drive = needs.find((n) => n.machine === m.name && n.subject?.type === "drive");
    return {
      id: m.name, name: m.name, kind: m.kind as LampKind, role: (Array.isArray(m.roles) ? m.roles : []).map(text).filter(Boolean).join(" · "),
      state: fresh ? "setup" : (m.state as LampState),
      word: fresh ? "set up" : m.state_word,
      // a desktop hosts nothing: its line is where it is, not an app count
      reading: fresh ? "nothing installed yet" : m.kind === "desktop" ? (m.here ? "this browser is on it" : null) : typeof m.apps !== "number" ? null : `${m.apps} app${m.apps === 1 ? "" : "s"}`,
      here: !!m.here, page: m.page !== false,
      // the rack's drive module is the part a drive alert lights
      cause: drive && m.kind === "server" ? "storage" : null,
    };
  });
  const here = all.find((m) => m.here)?.name ?? all[0]?.name ?? "";
  const jobs: LampJob[] = list(more.jobs).filter((j) => j.state === "running").map((j) => ({ id: j.id, machine: here, kind: j.kind, title: j.title, pct: j.pct }));
  return sane({
    lab: { name: board?.lab?.name, address: board?.lab?.address ?? null }, at: board?.at, clock: more.clock ?? null, age: more.age ?? null,
    status: { state: more.stale ? "unknown" : status.state, words: status.words }, headline: more.headline ?? null,
    machines, needs, jobs, mascot: more.mascot ?? "on", quiet: more.quiet ?? null,
  });
}
