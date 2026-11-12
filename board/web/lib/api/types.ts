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
  /** When its sign-in ends by itself. */
  expires_at: number | null;
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

/** What is in the box, as the app manager's scan has it (`bromigos lab apps budget --json`, its
 *  `hardware`). The drives aren't here: `storage.drives` lists them, and no command prints their
 *  sizes yet. */
export interface Hardware {
  cpu: number | null;
  ram_gb: number | null;
  /** The free space where apps keep their data. */
  disk_gb: number | null;
  gpu: boolean;
  /** "nvidia", "amd", or null when the scan didn't say. */
  gpu_kind: string | null;
  /** Always null today: the scan doesn't print the card's name. */
  gpu_name: string | null;
  gpu_vram_gb: number | null;
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
  /** The job's own title ("Updating Photos"); null from a service that doesn't send it. */
  title: string | null;
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

/** A channel alerts go to, as `bromigos alerts channels --json` lists it (docs/alerts.md). The
 *  address and the signing key are never in it: only whether the address is set. */
export interface Channel {
  name: string;
  /** discord, webhook, or brodec (the paired phone: its own rules, set on the phone). */
  type: string;
  label: string;
  on: boolean;
  read_only: boolean;
  /** A read-only channel's rules, in its own words. */
  rules: string | null;
  detail: string | null;
  severities: string[];
  sources: string[];
  /** "22:00-07:00" by the server's clock, or "" for none. */
  quiet: string;
  critical_in_quiet: boolean;
  /** "set", "not set", or "unknown" (only root may look); null when the server didn't say. */
  address: string | null;
  last_ok: number | null;
  last_error: { at: number | null; why: string } | null;
  /** Settings the server found wrong and doesn't use, in its words. */
  problems: string[];
}

/** One check of the alerts' last pass: whether it could look. */
export interface Check {
  check: string;
  state: "ran" | "skipped" | "failed" | "unknown";
  ran_at: number | null;
  error: string | null;
}

/** Where alerts go and what raises them: `bromigos alerts --json`, as the board carries it. */
export interface Notify {
  /** The channels; null when this server's alerts don't list them. */
  channels: Channel[] | null;
  checks: Check[];
  checked_at: number | null;
  /** How many alerts each check has raised now. */
  raised: Record<string, number>;
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
  /** Why the machines' hardware couldn't be read (the budget command's reason), or null. */
  hardwareWhy: string | null;
  /** The parts the server couldn't read this time, each with why when it said. */
  unread: Part[];
  why: Partial<Record<Part, string>>;
  /** What the server lets the page do, in the words of root's [board] actions: "add", "restart",
   *  "remove", and "delete-data" (removing an app with its data). Empty until the service says. */
  actions: string[];
  /** Whether the server said what the page may do at all (an empty list is an answer too). */
  actionsSaid: boolean;
  /** Root's [board] table, as the server read it: the door and the world. null when it didn't say. */
  settings: { door: boolean; world: string } | null;
  /** The alerts' channels and checks; null when the alerts couldn't be read. */
  notify: Notify | null;
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
  /** A lab job's own facts (a ComfyUI generation, a job feed's run); null for this server's jobs. */
  lab: LabInfo | null;
}

// ---------------------------------------------------------------- the lab's jobs (docs/activity.md, "Lab jobs")

/** A picture, clip or 3D model the lab follower keeps: `media` is the file's name in GET
 *  /api/lab/media/NAME, `thumb` a small picture of it; both null when it wasn't kept. */
export interface LabMedia {
  kind: "image" | "video" | "model3d" | "file";
  name: string;
  media: string | null;
  thumb: string | null;
  width: number | null;
  height: number | null;
  step: string | null;
}

export interface LabInfo {
  source: "comfyui" | "feed";
  /** The ComfyUI it runs on (its name in labjobs.toml), or null for a feed. */
  instance: string | null;
  workflow: string | null;
  /** What it makes, in a word: Image, Edit, Cut-out, Upscale, Video, 3D, Pipeline. */
  label: string;
  prompt: string | null;
  /** Who queued it (a tool's name), when it said. */
  client: string | null;
  position: number | null;
  ahead: number | null;
  elapsed_ms: number | null;
  estimate_ms: number | null;
  /** The progress is an estimate from earlier runs: ComfyUI doesn't send this one's. */
  estimated: boolean;
  /** The websocket said something of it: its stage and progress are ComfyUI's own. */
  live: boolean;
  /** The picture being made now (a running generation), or a feed step's thumbnail. */
  preview: LabMedia | null;
  /** What it made (with the result's own outputs, for a generation that ended). */
  outputs: LabMedia[];
  /** Stopping it means interrupting it (it runs now), not taking it out of the queue. */
  interrupt: boolean;
}

/** GET /api/lab: the lab follower's word on each ComfyUI it follows. */
export interface LabStatus {
  /** The follower has written in the last 15 seconds. */
  following: boolean;
  at: number | null;
  instances: { name: string; state: "ok" | "down"; words: string; live: boolean; relay: boolean }[];
}

export const FINAL_STATES: JobState[] = ["succeeded", "failed", "rolled-back", "cancelled", "interrupted"];

/** One event of `GET /api/activity` (Server-Sent Events), read. */
export type ActivityEvent =
  | { event: "snapshot"; jobs: JobRecord[] }
  | { event: "job"; job: JobRecord }
  | { event: "gone"; id: string }
  | { event: "signed-out" };

/** A job's own actions, as the service names them in its route and in `board.actions` ("job.answer"). */
export type JobVerb = "answer" | "cancel" | "retry";
/** What each sends: the question and the choice for an answer (and a fresh code for a choice that
 *  can't be undone), nothing for the others. */
export type JobBody = { question: string; choice: string; code?: string } | Record<string, never>;

/** What `POST /api/actions` answers (the service's actions): the job it started, when it knows. */
export interface ActionAnswer {
  job: string | null;
  words: string;
}
