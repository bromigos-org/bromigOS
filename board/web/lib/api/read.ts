// Every answer of the API passes through here before a view sees it. Nothing is assumed: each
// field is checked and given its type, a part that is missing, null or shaped another way (a
// command's error document, an older or newer service) becomes null and is named in `unread`,
// and a server-given address becomes a link only when it is http or https (lib/url.ts). A view
// can then read what these functions return without a single guard, and one bad document
// costs its own panel a "couldn't be read", never the page.
import { webUrl } from "../url";
import type {
  ActionAnswer, ActivityEvent, BackupsStatus, Board, Browser, CarriedDrive, Door, DoorTile, Drive, DriveHealth, DriveVerdict, Fixed,
  Hardware, JobRecord, JobState, JobStep, Machine, MachineKind, MachineReadings, NeedsYou, Part, Reading, SeriesName, Session, Shape,
  StepState, Tile, TileState, UpdatesStatus, Vitals, VitalsRange,
  Channel, Check, Notify,
} from "./types";
import { JOB_STATES, STEP_STATES } from "./types";

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj | null => (v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown, or = ""): string => (typeof v === "string" ? v : or);
const strOrNull = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const bool = (v: unknown, or = false): boolean => (typeof v === "boolean" ? v : or);
const strs = (v: unknown): string[] => arr(v).filter((x): x is string => typeof x === "string");
const oneOf = <T extends string>(v: unknown, all: readonly T[], or: T): T => ((all as readonly unknown[]).includes(v) ? (v as T) : or);
const each = <T>(v: unknown, read: (o: Obj) => T | null): T[] =>
  arr(v).flatMap((x) => {
    const o = obj(x);
    const got = o ? read(o) : null;
    return got === null ? [] : [got];
  });

// ---------------------------------------------------------------- the door and the session

function doorTile(o: Obj): DoorTile | null {
  const id = str(o.id), url = webUrl(obj(o.open)?.url);
  if (!id || !url) return null;
  return { id, job: str(o.job, id), app: str(o.app), holo: strOrNull(o.holo), open: { url } };
}

export function readDoor(doc: unknown): Door {
  const d = obj(doc) ?? {};
  const lab = obj(d.lab) ?? {}, signin = obj(d.signin) ?? {};
  const server = str(obj(d.server)?.name, "this server");
  return {
    lab: { name: str(lab.name, server), address: webUrl(lab.address) },
    server: { name: server },
    world: str(d.world, "wick"),
    door: bool(d.door, true),
    tiles: each(d.tiles, doorTile),
    signin: { code: bool(signin.code), phone: bool(signin.phone), account: bool(signin.account) },
  };
}

function browser(o: Obj): Browser | null {
  const id = str(o.id);
  if (!id) return null;
  return { id, name: str(o.name, "A browser"), signed_in_at: num(o.signed_in_at), last_seen_at: num(o.last_seen_at), expires_at: num(o.expires_at), current: bool(o.current) };
}

export function readSession(doc: unknown): Session {
  const d = obj(doc) ?? {};
  const b = obj(d.browser);
  const signed = d.signed_in === true;
  return {
    signed_in: signed,
    role: signed ? oneOf(d.role, ["owner", "viewer"] as const, "owner") : null,
    browser: signed && b && str(b.id) ? { id: str(b.id), name: str(b.name, "This browser") } : null,
    expires_at: num(d.expires_at),
    browsers: signed ? each(d.browsers, browser) : [],
  };
}

// ---------------------------------------------------------------- a tile

const TILE_STATES: readonly TileState[] = ["ok", "starting", "updating", "degraded", "down", "unknown"];

function reading(v: unknown): Reading | null {
  const o = obj(v);
  const text = str(o?.text), at = num(o?.at);
  return o && text && at !== null ? { text, source: str(o.source, "the app"), at, max_age_s: num(o.max_age_s) ?? 900 } : null;
}

function tile(o: Obj): Tile | null {
  const id = str(o.id);
  if (!id) return null;
  const installed = bool(o.installed, true);
  const open = obj(o.open), url = webUrl(open?.url);
  const update = obj(o.update), measured = obj(o.measured), requires = obj(o.requires);
  return {
    id,
    job: str(o.job, id),
    app: str(o.app),
    holo: strOrNull(o.holo),
    group: str(o.group),
    installed,
    version: strOrNull(o.version),
    // an installed app whose state the server didn't say is unknown, never "ok"
    state: installed ? oneOf(o.state, TILE_STATES, "unknown") : null,
    state_word: strOrNull(o.state_word),
    since: num(o.since),
    reading: reading(o.reading),
    open: url ? { url, port: num(open?.port) } : null,
    update: update ? { available: bool(update.available), to: strOrNull(update.to), manual: bool(update.manual), note: str(update.note) } : null,
    measured: { ram_bytes: num(measured?.ram_bytes), disk_bytes: num(measured?.disk_bytes) },
    requires: requires ? { cpu: num(requires.cpu) ?? 0, ram_gb: num(requires.ram_gb) ?? 0, disk_gb: num(requires.disk_gb) ?? 0 } : null,
    can: strs(o.can),
    needed_by: strs(o.needed_by),
    machine: strOrNull(o.machine),
  };
}

/** The apps list: a bare array of tiles, or {apps: [...]}. Anything else (an error document) is null. */
function tiles(v: unknown): Tile[] | null {
  const list = Array.isArray(v) ? v : obj(v) && Array.isArray(obj(v)!.apps) ? (obj(v)!.apps as unknown[]) : null;
  return list ? each(list, tile) : null;
}

// ---------------------------------------------------------------- the commands' documents

const VERDICTS: readonly DriveVerdict[] = ["healthy", "watch", "checking", "worse", "replace", "unknown"];

function drive(o: Obj): Drive | null {
  const key = str(o.key) || str(o.device);
  if (!key) return null;
  const verdict = oneOf(o.verdict, VERDICTS, "unknown");
  return {
    key,
    device: str(o.device, key),
    model: str(o.model, "A drive"),
    kind: str(o.kind),
    present: bool(o.present, true),
    verdict,
    // its own word; a verdict this page doesn't know reads "cannot tell", never "healthy"
    words: verdict === "unknown" && o.verdict !== "unknown" ? "cannot tell" : str(o.words, verdict),
    summary: str(o.summary),
    advice: str(o.advice),
    since: num(o.since),
    reasons: each(o.reasons, (r) => (str(r.text) ? { level: str(r.level), text: str(r.text) } : null)),
  };
}

function storage(v: unknown): DriveHealth | null {
  const o = obj(v);
  return o && Array.isArray(o.drives) ? { checked_at: num(o.checked_at), drives: each(o.drives, drive) } : null;
}

const ts = (v: unknown): number | null => num(obj(v)?.ts) ?? num(v);
const failed = (v: unknown): boolean => str(obj(v)?.phase) === "failed";

function carried(o: Obj): CarriedDrive | null {
  return {
    name: str(o.name, "The backup drive"),
    label: str(o.label),
    model: str(o.model),
    plugged_in: typeof o.plugged_in === "boolean" ? o.plugged_in : null,
    last_good_ts: ts(o.last_good_copy),
    last_failed: failed(o.last_copy),
    stale: bool(o.stale),
  };
}

function backups(v: unknown): BackupsStatus | null {
  const o = obj(v), health = obj(o?.health);
  if (!o || !health || typeof health.state !== "string") return null; // an error document (not a server), or nothing
  const test = obj(o.last_test), run = obj(o.last_backup);
  // the last test that passed: the command's own field, else the last test when that one passed
  const proven = ts(o.last_test_passed) ?? (test && str(test.phase) === "ok" ? ts(test) : null);
  return {
    configured: bool(o.configured),
    to: str(o.to),
    health: { state: oneOf(health.state, ["ok", "attention", "waiting", "off", "unknown"] as const, "unknown"), verdict: str(health.verdict) },
    last_success_ts: ts(o.last_success),
    last_backup: run ? { ts: ts(run), failed: failed(run) } : null,
    last_test: test ? { ts: ts(test), failed: failed(test) } : null,
    proven_ts: proven,
    snapshots: num(obj(o.snapshots)?.count) ?? num(o.snapshots),
    drives: each(o.drives, carried),
  };
}

function updates(v: unknown): UpdatesStatus | null {
  const o = obj(v), u = obj(o?.updates);
  if (!u || typeof u.phase !== "string") return null;
  const secs = num(u.finished_ts);
  const parsed = typeof u.finished === "string" ? Date.parse(u.finished) : NaN;
  return {
    phase: u.phase,
    finished_at: secs !== null ? secs * 1000 : Number.isFinite(parsed) ? parsed : null,
    mode: str(u.mode),
    window: str(u.window),
    auto: bool(u.auto),
    rollbacks: arr(o!.rollbacks).length,
  };
}

// ---------------------------------------------------------------- the board

const KINDS: readonly MachineKind[] = ["server", "storage", "node", "desktop", "other"];
const SHAPES: readonly Shape[] = ["ok", "warn", "down", "unknown"];

function readings(v: unknown): MachineReadings | null {
  const o = obj(v), at = num(o?.at);
  if (!o || at === null) return null;
  return {
    cpu_pct: num(o.cpu_pct), ram_pct: num(o.ram_pct), temp_c: num(o.temp_c), ram_used_bytes: num(o.ram_used_bytes),
    ram_total_bytes: num(o.ram_total_bytes), load1: num(o.load1), net_in_mbps: num(o.net_in_mbps), net_out_mbps: num(o.net_out_mbps),
    at, max_age_s: num(o.max_age_s) ?? 45,
  };
}

function hardware(v: unknown): Hardware | null {
  const o = obj(v);
  if (!o) return null;
  return {
    cpu: num(o.cpu), ram_gb: num(o.ram_gb), disk_gb: num(o.disk_gb),
    // a card is there only when the scan said so; its kind and memory only as the scan said them
    gpu: o.gpu === true, gpu_kind: strOrNull(o.gpu_kind), gpu_name: strOrNull(o.gpu_name), gpu_vram_gb: num(o.gpu_vram_gb),
  };
}

function machine(o: Obj): Machine | null {
  const name = str(o.name);
  if (!name) return null;
  const up = obj(o.updates);
  // a machine whose state the server didn't say is unknown, never "ok"
  const state = oneOf(o.state, SHAPES, "unknown");
  return {
    name, kind: oneOf(o.kind, KINDS, "other"), here: bool(o.here), state,
    state_word: str(o.state_word, state === "ok" ? "online" : state === "unknown" ? "can't check" : "needs you"),
    roles: strs(o.roles),
    updates: up && num(up.count) !== null ? { count: num(up.count)!, security: bool(up.security) } : null,
    readings: readings(o.readings),
    apps: num(o.apps),
    hardware: hardware(o.hardware),
  };
}

const subject = (v: unknown) => {
  const o = obj(v);
  return o && str(o.name || o.id) ? { type: str(o.type), id: str(o.id), name: str(o.name) || str(o.id) } : null;
};
/** A place on this page: letters, digits, "/", "-", ".". Never an address. */
const route = (v: unknown): string | null => (typeof v === "string" && /^[a-z][a-z0-9/._-]{0,80}$/.test(v) ? v : null);

function need(o: Obj): NeedsYou | null {
  const words = str(o.words);
  if (!words) return null;
  return {
    id: str(o.id, words), machine: str(o.machine), subject: subject(o.subject),
    severity: o.severity === "critical" || o.severity === "danger" ? "critical" : "warn",
    words, detail: strOrNull(o.detail), since: num(o.since), go: route(o.go), job: strOrNull(o.job),
  };
}

function fixedRow(o: Obj): Fixed | null {
  const id = str(o.id);
  return id ? { id, machine: str(o.machine), title: strOrNull(o.title), words: str(o.words), at: num(o.at) } : null;
}

function channel(o: Obj): Channel | null {
  const name = str(o.name);
  if (!name) return null;
  const e = obj(o.last_error);
  return {
    name, type: str(o.type, name), label: str(o.label, name), on: o.on === true, read_only: o.read_only === true,
    rules: strOrNull(o.rules), detail: strOrNull(o.detail), severities: strs(o.severities), sources: strs(o.sources),
    quiet: str(o.quiet), critical_in_quiet: o.critical_in_quiet === true, address: strOrNull(o.address),
    last_ok: num(o.last_ok), last_error: e && str(e.why) ? { at: num(e.at), why: str(e.why) } : null, problems: strs(o.problems),
  };
}

function check(o: Obj): Check | null {
  const name = str(o.check);
  if (!name) return null;
  return { check: name, state: oneOf(o.state, ["ran", "skipped", "failed"] as const, "unknown"), ran_at: num(o.ran_at), error: strOrNull(o.error) };
}

/** `bromigos alerts --json`: its channels, its checks, and how many alerts each check raised. */
function notify(v: unknown): Notify | null {
  const a = obj(v);
  if (!a) return null;
  const ch = obj(a.channels);
  const raised: Record<string, number> = {};
  for (const x of arr(a.alerts)) {
    const c = str(obj(x)?.check);
    if (c) raised[c] = (raised[c] ?? 0) + 1;
  }
  return { channels: ch && Array.isArray(ch.channels) ? each(ch.channels, channel) : null, checks: each(a.checks, check), checked_at: num(a.system_checked_at), raised };
}

export function readBoard(doc: unknown): Board {
  const d = obj(doc) ?? {};
  const lab = obj(d.lab) ?? {}, server = obj(d.server) ?? {}, status = obj(d.status) ?? {}, sources = obj(d.sources) ?? {};
  const name = str(server.name) || str(d.host, "this server");
  const at = num(d.at) ?? 0, max = num(d.max_age_s) ?? 45;
  // how old the server says its reading was when it answered; a board that doesn't say is treated as old
  const age = num(d.age_s) ?? max + 1;
  const parts: Record<Part, unknown> = {
    apps: tiles(d.apps), drives: storage(d.storage), backups: backups(d.backups), updates: updates(d.updates),
    // what needs you comes from the alerts, the jobs from the activity list: unread when its command didn't answer
    alerts: obj(d.alerts) ? true : null, jobs: Array.isArray(obj(d.activity)?.jobs) ? jobs(obj(d.activity)!.jobs) : null,
  };
  const SOURCE: Record<Part, string> = { apps: "apps", drives: "storage", backups: "backups", updates: "system", alerts: "alerts", jobs: "activity" };
  const unread = (Object.keys(parts) as Part[]).filter((p) => parts[p] === null);
  const why: Board["why"] = {};
  for (const p of unread) {
    const said = strOrNull(obj(sources[SOURCE[p]])?.why) ?? (p === "backups" ? strOrNull(obj(obj(d.backups)?.error)?.message) : null);
    if (said) why[p] = said;
  }
  const machines = each(d.machines, machine);
  return {
    at, age_s: age, max_age_s: max, stale: bool(d.stale, age > max),
    lab: { name: str(lab.name, name), address: webUrl(lab.address) },
    server: { name, kind: oneOf(server.kind, KINDS, "server"), roles: strs(server.roles) },
    status: { state: oneOf(status.state, ["ok", "needs-you", "setup", "unknown"] as const, "unknown"), words: str(status.words) },
    machines,
    needs_you: each(d.needs_you, need),
    fixed: each(d.fixed, fixedRow),
    jobs: parts.jobs as JobRecord[] | null,
    apps: parts.apps as Tile[] | null,
    storage: parts.drives as DriveHealth | null,
    backups: parts.backups as BackupsStatus | null,
    updates: parts.updates as UpdatesStatus | null,
    hardwareWhy: obj(sources.budget)?.ok === false ? (strOrNull(obj(sources.budget)?.why) ?? "the scan didn't answer") : null,
    unread, why,
    actions: strs(d.actions),
    actionsSaid: Array.isArray(d.actions),
    settings: obj(d.settings) ? { door: obj(d.settings)!.door !== false, world: str(obj(d.settings)!.world, "wick") } : null,
    notify: notify(d.alerts),
  };
}

// ---------------------------------------------------------------- trends

const SERIES: readonly SeriesName[] = ["cpu_pct", "ram_pct", "net_in_mbps", "net_out_mbps", "temp_c"];

export function readVitals(doc: unknown, machineName: string, range: VitalsRange): Vitals {
  const s = obj(obj(doc)?.series) ?? {};
  const series: Vitals["series"] = {};
  for (const k of SERIES) {
    if (!Array.isArray(s[k])) continue;
    series[k] = (s[k] as unknown[]).flatMap((p) => (Array.isArray(p) && num(p[0]) !== null ? [[p[0] as number, num(p[1])] as [number, number | null]] : []));
  }
  return { machine: machineName, range, series };
}

// ---------------------------------------------------------------- jobs

function step(o: Obj): JobStep | null {
  const id = str(o.id);
  if (!id) return null;
  const p = obj(o.progress);
  return {
    id, label: str(o.label, id), state: oneOf<StepState>(o.state, STEP_STATES, "todo"), ended_at: num(o.ended_at), detail: strOrNull(o.detail),
    progress: p && num(p.done) !== null && num(p.total) !== null ? { done: num(p.done)!, total: num(p.total)!, unit: str(p.unit) } : null,
  };
}

export function readJob(v: unknown): JobRecord | null {
  const o = obj(v);
  const id = str(o?.id);
  // a record in a state this page doesn't know is left out, not shown as something it isn't
  if (!o || !id || !(JOB_STATES as readonly unknown[]).includes(o.state)) return null;
  const q = obj(o.question), result = obj(o.result), error = obj(o.error);
  const started = num(o.started_at) ?? num(o.updated_at) ?? 0;
  const steps = each(o.steps, step);
  const at = num(o.step);
  return {
    id, kind: str(o.kind), title: str(o.title, id), subject: subject(o.subject), state: o.state as JobState,
    waiting_for: strOrNull(o.waiting_for),
    question: q && str(q.text)
      ? { id: str(q.id), text: str(q.text), choices: each(q.choices, (c) => (str(c.id) ? { id: str(c.id), label: str(c.label, str(c.id)), danger: bool(c.danger) } : null)) }
      : null,
    steps, step: at !== null && at >= 0 && at < steps.length ? at : null,
    pct: num(o.pct), stage: strOrNull(o.stage),
    started_at: started, updated_at: num(o.updated_at) ?? started, ended_at: num(o.ended_at),
    via: str(obj(o.requested_by)?.via, "cli"),
    result: result ? { ok: bool(result.ok), summary: str(result.summary) } : null,
    error: error && str(error.words) ? { step: strOrNull(error.step), words: str(error.words), fix: strOrNull(obj(error.fix)?.label) } : null,
    parent: strOrNull(o.parent), children: strs(o.children),
    notes: each(o.notes, (n) => (str(n.words) ? { words: str(n.words), at: num(n.at) } : null)),
    can: strs(o.can),
    cancel_note: strOrNull(o.cancel_note),
    command: strs(o.command), unit: strOrNull(o.unit), log: strOrNull(o.log),
  };
}

const jobs = (v: unknown): JobRecord[] => arr(v).flatMap((j) => readJob(j) ?? []);

/** One event of the activity stream, or null for one this page doesn't know. */
export function readEvent(event: string, data: unknown): ActivityEvent | null {
  if (event === "snapshot") return { event, jobs: jobs(obj(data)?.jobs) };
  if (event === "job") {
    const job = readJob(data);
    return job ? { event, job } : null;
  }
  if (event === "gone") return str(obj(data)?.id) ? { event, id: str(obj(data)!.id) } : null;
  if (event === "signed-out") return { event };
  return null;
}

export function readAction(doc: unknown): ActionAnswer {
  const d = obj(doc) ?? {};
  return { job: strOrNull(d.job), words: str(d.words) };
}
