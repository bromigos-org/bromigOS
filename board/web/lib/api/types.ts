// The documents the board's API serves, as the page's views read them. Nothing here is trusted
// as it arrives: lib/api/read.ts turns each answer into these types, checking every field, so a
// part the server couldn't read, or a document shaped another way, is `null` (and named in
// `unread`), never a crash. The shapes are the service's (board/lib/bromigos_board: door.py,
// board.py, api.py) around the commands' own --json; tests/contract/service.json holds real
// answers, and tests/contract.spec.ts runs the page against them.
// All times are milliseconds since the epoch, UTC, unless a field says seconds.

export const WORLDS = [
  "wick",
  "mire",
  "tidewell",
  "rime",
  "sunder",
  "cinder",
  "lowtown",
  "highwind",
  "deepvein",
  "wick-tidewell",
  "wick-mire",
] as const;
export type World = (typeof WORLDS)[number];

/** A state word's shape: lit dot, broken diamond, crossed square, dotted ring (DESIGN §5). */
export type Shape = "ok" | "warn" | "down" | "unknown";

// ---------------------------------------------------------------- the door (no session)

export interface DoorTile {
  id: string;
  job: string;
  app: string;
  holo: string | null;
  open: { url: string };
}

export interface Door {
  lab: { name: string; address: string | null };
  server: { name: string };
  world: string;
  /** false: the owner turned the door's app list off ([board] door in server.toml). */
  door: boolean;
  tiles: DoorTile[];
  signin: { code: boolean; phone: boolean; account: boolean };
}

// ---------------------------------------------------------------- the session

export interface Browser {
  id: string;
  name: string;
  signed_in_at: number | null;
  last_seen_at: number | null;
  current: boolean;
}

export interface Session {
  signed_in: boolean;
  role: "owner" | "viewer" | null;
  browser: { id: string; name: string } | null;
  expires_at: number | null;
  browsers: Browser[];
}

// ---------------------------------------------------------------- a tile (DESIGN §3)

export type TileState = "ok" | "starting" | "updating" | "degraded" | "down" | "unknown";

export interface Reading {
  text: string;
  source: string;
  at: number;
  max_age_s: number;
}

export interface Tile {
  id: string;
  job: string;
  app: string;
  holo: string | null;
  group: string;
  installed: boolean;
  version: string | null;
  /** null while not installed. */
  state: TileState | null;
  /** Running, Starting, Updating, Degraded, Down, Unknown, or "Set up" for an item with no service. */
  state_word: string | null;
  since: number | null;
  reading: Reading | null;
  /** Only an http or https address ever gets here (lib/url.ts). */
  open: { url: string; port: number | null } | null;
  /** null: the app doesn't report updates. */
  update: { available: boolean; to: string | null; manual: boolean; note: string } | null;
  measured: { ram_bytes: number | null; disk_bytes: number | null };
  requires: { cpu: number; ram_gb: number; disk_gb: number } | null;
  /** open, restart, update, rollback, logs, remove; add when not installed. */
  can: string[];
  needed_by: string[];
  /** The machine it runs on, when the lab has several. */
  machine: string | null;
}

// ---------------------------------------------------------------- the board

export type MachineKind = "server" | "storage" | "node" | "desktop" | "other";

export interface MachineReadings {
  cpu_pct: number | null;
  ram_pct: number | null;
  temp_c: number | null;
  ram_used_bytes: number | null;
  ram_total_bytes: number | null;
  load1: number | null;
  net_in_mbps: number | null;
  net_out_mbps: number | null;
  /** When they were measured, and how old they may get. */
  at: number;
  max_age_s: number;
}

/** What is in the box: the salvage scan's own keys (provcatalog.py). */
export interface Hardware {
  cpu: number | null;
  ram_gb: number | null;
  gpu: boolean;
  gpu_name: string | null;
  gpu_vram_gb: number | null;
  drives: { device: string; model: string; size_bytes: number; kind: string }[];
}

export interface Machine {
  name: string;
  kind: MachineKind;
  here: boolean;
  state: Shape;
  state_word: string;
  roles: string[];
  updates: { count: number; security: boolean } | null;
  readings: MachineReadings | null;
  apps: number | null;
  hardware: Hardware | null;
}

export interface NeedsYou {
  id: string;
  machine: string;
  subject: { type: string; id: string; name: string } | null;
  severity: "warn" | "critical";
  words: string;
  detail: string | null;
  since: number | null;
  /** The route that owns the fact (lib/routes.ts), or null. */
  go: string | null;
  job: string | null;
}

export interface Fixed {
  id: string;
  machine: string;
  words: string;
  at: number | null;
}

export type DriveVerdict = "healthy" | "watch" | "checking" | "worse" | "replace" | "unknown";

/** `bromigos storage health --json` (docs/storage.md, Scripting): the keys the page reads. */
export interface Drive {
  key: string;
  device: string;
  model: string;
  kind: string;
  present: boolean;
  verdict: DriveVerdict;
  words: string;
  summary: string;
  advice: string;
  since: number | null;
  reasons: { level: string; text: string }[];
}
export interface DriveHealth {
  checked_at: number | null;
  drives: Drive[];
}

/** A carried backup drive (the Go Bag): lib/bromigos_backup_drive.py's view(). Times in seconds. */
export interface CarriedDrive {
  name: string;
  label: string;
  model: string;
  plugged_in: boolean | null;
  last_good_ts: number | null;
  last_failed: boolean;
  stale: boolean;
}

/** `bromigos lab backups status --json` (lib/bromigos_backups.py, status_doc). Times in seconds. */
export interface BackupsStatus {
  configured: boolean;
  to: string;
  health: { state: "ok" | "attention" | "waiting" | "off" | "unknown"; verdict: string };
  /** The last backup that worked. */
  last_success_ts: number | null;
  /** The last backup tried, and whether it failed. */
  last_backup: { ts: number | null; failed: boolean } | null;
  /** The last test restore, and the last one that passed. */
  last_test: { ts: number | null; failed: boolean } | null;
  proven_ts: number | null;
  snapshots: number | null;
  drives: CarriedDrive[];
}

/** The `updates` of `bromigos server status --json`, with its rollbacks. */
export interface UpdatesStatus {
  phase: string;
  finished_at: number | null;
  mode: string;
  window: string;
  auto: boolean;
  rollbacks: number;
}

/** A part of the board the server reads with one command. */
export type Part = "apps" | "drives" | "backups" | "updates" | "alerts" | "jobs";

export interface Board {
  /** When the server read itself, how old that was when it answered, and whether it calls that stale. */
  at: number;
  age_s: number;
  max_age_s: number;
  stale: boolean;
  lab: { name: string; address: string | null };
  server: { name: string; kind: MachineKind; roles: string[] };
  status: { state: "ok" | "needs-you" | "setup" | "unknown"; words: string };
  machines: Machine[];
  needs_you: NeedsYou[];
  fixed: Fixed[];
  /** The jobs as `bromigos activity list` printed them when the board was read (the stream has
   *  them live); null when that list couldn't be read. */
  jobs: JobRecord[] | null;
  /** Every catalogue item, installed or not; null when the apps list couldn't be read. */
  apps: Tile[] | null;
  storage: DriveHealth | null;
  backups: BackupsStatus | null;
  updates: UpdatesStatus | null;
  /** The parts the server couldn't read this time, each with why when it said. */
  unread: Part[];
  why: Partial<Record<Part, string>>;
  /** What the server lets the page do, in the words of root's [board] actions: "add", "restart",
   *  "remove", and "delete-data" (removing an app with its data). Empty until the service says. */
  actions: string[];
}

// ---------------------------------------------------------------- a machine's trends

export type VitalsRange = "24h" | "7d" | "30d";
export type SeriesName = "cpu_pct" | "ram_pct" | "net_in_mbps" | "net_out_mbps" | "temp_c";

export interface Vitals {
  machine: string;
  range: VitalsRange;
  series: Partial<Record<SeriesName, [number, number | null][]>>;
}

// ---------------------------------------------------------------- the activity record (DESIGN §4)

export const JOB_STATES = ["queued", "running", "needs-you", "waiting", "succeeded", "failed", "rolled-back", "cancelled", "interrupted"] as const;
export type JobState = (typeof JOB_STATES)[number];
export const STEP_STATES = ["todo", "running", "waiting", "done", "failed", "skipped"] as const;
export type StepState = (typeof STEP_STATES)[number];

export interface JobStep {
  id: string;
  label: string;
  state: StepState;
  ended_at: number | null;
  detail: string | null;
  progress: { done: number; total: number; unit: string } | null;
}

export interface JobQuestion {
  id: string;
  text: string;
  choices: { id: string; label: string; danger: boolean }[];
}

export interface JobRecord {
  id: string;
  kind: string;
  title: string;
  subject: { type: string; id: string; name: string } | null;
  state: JobState;
  waiting_for: string | null;
  question: JobQuestion | null;
  steps: JobStep[];
  step: number | null;
  pct: number | null;
  stage: string | null;
  started_at: number;
  updated_at: number;
  ended_at: number | null;
  via: string;
  result: { ok: boolean; summary: string } | null;
  error: { step: string | null; words: string; fix: string | null } | null;
  parent: string | null;
  children: string[];
  /** What the job said along the way, oldest first. */
  notes: { words: string; at: number | null }[];
  /** What the record says may be done to it now: answer, cancel, retry. */
  can: string[];
  /** Why stopping it now isn't safe, when it says. */
  cancel_note: string | null;
  /** For looking closer at the server: the command it runs, its unit and its log file. */
  command: string[];
  unit: string | null;
  log: string | null;
}

export const FINAL_STATES: JobState[] = ["succeeded", "failed", "rolled-back", "cancelled", "interrupted"];

/** One event of `GET /api/activity` (Server-Sent Events), read. */
export type ActivityEvent =
  | { event: "snapshot"; jobs: JobRecord[] }
  | { event: "job"; job: JobRecord }
  | { event: "gone"; id: string }
  | { event: "signed-out" };

/** What `POST /api/actions` answers (the service's actions): the job it started, when it knows. */
export interface ActionAnswer {
  job: string | null;
  words: string;
}
