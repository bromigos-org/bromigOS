// The documents the board's API serves, as the page reads them. The shapes are the shared
// contracts: the tile is DESIGN.md §3 (`bromigos lab apps list --json`), the activity record is
// DESIGN.md §4 as `lib/bromigos_activity.py` writes it (schema 1), and the rest is written down
// in the service's API reference (docs/board.md, "The API"). All times are milliseconds since
// the epoch, UTC; the page shows them in local time.

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
  schema: 1;
  lab: { name: string; address: string | null };
  server: { name: string };
  world: string;
  tiles: DoorTile[];
  signin: { code: boolean; phone: boolean; account: boolean };
}

// ---------------------------------------------------------------- the session

export interface Browser {
  id: string;
  name: string;
  signed_in_at: number;
  last_seen_at: number | null;
  current: boolean;
}

export interface Session {
  schema: 1;
  signed_in: boolean;
  role: "owner" | "viewer" | null;
  browser: { id: string; name: string } | null;
  expires_at: number | null;
  browsers: Browser[];
}

export interface ApiErrorDoc {
  error: { code: string; words: string };
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
  recipe: number;
  /** null until the catalogue says (lab-apps' note in the shared contracts). */
  household: boolean | null;
  /** null while not installed. */
  state: TileState | null;
  /** Running, Starting, Updating, Degraded, Down, Unknown, or "Set up" for an item with no service. */
  state_word: string | null;
  since: number | null;
  reading: Reading | null;
  open: { url: string; port: number | null } | null;
  update: { available: boolean; to: string | null; manual: boolean; note: string } | null;
  measured: { ram_bytes: number | null; disk_bytes: number | null } | null;
  requires: { cpu: number; ram_gb: number; disk_gb: number } | null;
  /** open, restart, update, rollback, logs, remove; add when not installed. */
  can: string[];
  needed_by: string[];
  /** The machine it runs on; the lab's places mark each tile with it. */
  machine?: string;
}

// ---------------------------------------------------------------- the board

export type MachineKind = "server" | "storage" | "node" | "desktop" | "other";

export interface MachineReadings {
  cpu_pct: number | null;
  ram_pct: number | null;
  temp_c: number | null;
  ram_used_bytes?: number | null;
  ram_total_bytes?: number | null;
  load1?: number | null;
  net_in_mbps?: number | null;
  net_out_mbps?: number | null;
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
  page: boolean;
  state: Shape;
  state_word: string;
  roles: string[];
  updates: { count: number; security: boolean } | null;
  readings: MachineReadings | null;
  apps: number | null;
  hardware?: Hardware | null;
}

export interface NeedsYou {
  id: string;
  machine: string;
  subject: { type: string; id: string; name: string } | null;
  severity: "warn" | "danger";
  words: string;
  detail: string | null;
  since: number | null;
  go: string | null;
  job: string | null;
}

export interface Fixed {
  id: string;
  machine: string;
  words: string;
  at: number;
}

export interface Board {
  schema: 1;
  at: number;
  max_age_s: number;
  lab: { name: string; address: string | null };
  server: { name: string; kind: MachineKind; roles: string[] };
  status: { state: "ok" | "needs-you" | "setup" | "unknown"; words: string; checked_at: number | null };
  machines: Machine[];
  needs_you: NeedsYou[];
  fixed: Fixed[];
  apps: Tile[];
  /** `bromigos storage health --json`, passed through unchanged; null when it couldn't run. */
  storage: unknown;
  /** `bromigos lab backups status --json`, passed through unchanged. */
  backups: unknown;
  /** The updates and rollbacks of `bromigos server status --json`. */
  updates: unknown;
  ups: unknown;
}

// ---------------------------------------------------------------- a machine's trends

export type VitalsRange = "24h" | "7d" | "30d";
export type SeriesName = "cpu_pct" | "ram_pct" | "net_in_mbps" | "net_out_mbps" | "temp_c";

export interface Vitals {
  schema: 1;
  machine: string;
  range: VitalsRange;
  step_s: number;
  at: number;
  series: Partial<Record<SeriesName, [number, number | null][]>>;
}

// ---------------------------------------------------------------- what the board passes through

/** `bromigos storage health --json`: the keys the page reads (docs/storage.md, Scripting). */
export interface DriveHealth {
  schema: number;
  checked_at: number | null;
  drives: { key: string; device: string; model: string; kind: string; present: boolean; verdict: "healthy" | "watch" | "checking" | "worse" | "replace" | "unknown"; words: string; summary: string }[];
}

/** `bromigos lab backups status --json`: the keys the page reads. Times are Unix seconds. */
export interface BackupsStatus {
  configured: boolean;
  to: string;
  health: { state: "ok" | "attention" | "waiting" | "off" | "unknown"; verdict: string };
  last_success: { ts: number | null } | null;
  last_test_passed: { ts: number | null } | null;
}

/** The updates of `bromigos server status --json`, and its rollbacks. */
export interface UpdatesStatus {
  phase: string;
  finished: string | null;
  finished_ts?: number | null;
  mode: string;
  window: string;
  auto: boolean;
  rollbacks: unknown[];
}

// ---------------------------------------------------------------- the activity record (DESIGN §4)

export type JobState =
  | "queued"
  | "running"
  | "needs-you"
  | "waiting"
  | "succeeded"
  | "failed"
  | "rolled-back"
  | "cancelled"
  | "interrupted";

export type StepState = "todo" | "running" | "waiting" | "done" | "failed" | "skipped";

export interface JobStep {
  id: string;
  label: string;
  state: StepState;
  started_at: number | null;
  ended_at: number | null;
  detail: string | null;
  progress: { done: number; total: number; unit: string } | null;
}

export interface JobQuestion {
  id: string;
  text: string;
  choices: { id: string; label: string; danger: boolean }[];
  asked_at: number;
}

export interface JobRecord {
  schema: 1;
  id: string;
  kind: string;
  title: string;
  subject: { type: string; id: string; name: string } | null;
  state: JobState;
  waiting_for: "network" | "another job" | "you" | "drive" | null;
  question: JobQuestion | null;
  steps: JobStep[];
  step: number | null;
  pct: number | null;
  stage: string | null;
  notes: { id: string | null; words: string; at: number }[];
  started_at: number;
  updated_at: number;
  ended_at: number | null;
  requested_by: { via: "board" | "phone" | "cli" | "timer" | "vector"; device: string | null };
  unit: string | null;
  locks: string[];
  can: ("cancel" | "answer" | "retry" | "undo")[];
  cancel_safe: boolean;
  cancel_note: string | null;
  result: { ok: boolean; summary: string; undo: { until: number; command: string[] } | null } | null;
  error: { step: string | null; words: string; code: string; fix: { label: string; command: string[] } | null } | null;
  exit_code: number | null;
  command: string[];
  log: string | null;
  parent: string | null;
  children: string[];
}

export const FINAL_STATES: JobState[] = ["succeeded", "failed", "rolled-back", "cancelled", "interrupted"];

/** One event of `GET /api/activity` (Server-Sent Events). */
export type ActivityEvent =
  | { event: "snapshot"; data: { schema: 1; jobs: JobRecord[] } }
  | { event: "job"; data: JobRecord }
  | { event: "gone"; data: { id: string } };
