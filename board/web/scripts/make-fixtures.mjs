// Writes fixtures/*.json: one page state of the whole lab per file, in the API's shapes
// (lib/api/types.ts; the tile is DESIGN.md §3, the job record DESIGN.md §4 as
// lib/bromigos_activity.py writes it). Everything here is example data for the tests and for
// building pages before the service answers; names are the catalogue's
// (homelab/share/provision-catalogue.toml). Run: node scripts/make-fixtures.mjs
import { writeFileSync } from "node:fs";

const dir = new URL("../fixtures/", import.meta.url).pathname;
const NOW = Date.UTC(2026, 10, 10, 22, 2, 0); // 10 Nov 2026, 14:02 Pacific
const SEC = 1000, MIN = 60 * SEC, H = 60 * MIN, D = 24 * H;
const GB = 1024 ** 3;

const lab = { name: "MYLAB", address: "https://mylab.local" };
const server = { name: "myserver" };

// ---------------------------------------------------------------- tiles (DESIGN §3)
const tile = (id, job, app, holo, group, port, extra = {}) => ({
  id, job, app, holo, group,
  installed: true, version: extra.version ?? null, recipe: 12, household: extra.household ?? !!port,
  state: "ok", state_word: "Running", since: NOW - 6 * D,
  reading: null,
  open: port ? { url: `https://${id}-myserver.local`, port } : null,
  update: { available: false, to: null, manual: false, note: "" },
  measured: { ram_bytes: extra.ram ?? null, disk_bytes: extra.disk ?? null },
  requires: { cpu: 1, ram_gb: 1, disk_gb: 2 },
  can: port ? ["open", "restart", "update", "rollback", "logs", "remove"] : ["restart", "update", "rollback", "logs", "remove"],
  needed_by: [], machine: "myserver",
  ...extra.over,
});
const reading = (text, source, ago, max = 900) => ({ text, source, at: NOW - ago, max_age_s: max });

const APPS = [
  tile("photos", "Photos", "Immich", "photos", "home", 2283, { version: "v3.3.5", ram: 2.04 * GB, disk: 38 * GB,
    over: { reading: reading("Last photo backed up 2 hours ago", "adapter:immich", 4 * MIN), requires: { cpu: 2, ram_gb: 4, disk_gb: 20 },
      update: { available: true, to: "v3.3.6", manual: false, note: "" } } }),
  tile("passwords", "Passwords", "Vaultwarden", "passwords", "home", 8222, { version: "1.34.3", ram: 0.06 * GB, disk: 0.1 * GB }),
  tile("documents", "Documents", "Paperless-ngx", "documents", "home", 8010, { version: "2.18.4", ram: 0.9 * GB, disk: 6 * GB,
    over: { reading: reading("1,204 documents", "adapter:paperless", 6 * MIN) } }),
  tile("uptime", "Uptime", "Uptime Kuma", "uptime", "home", 3001, { version: "2.5.8", ram: 0.15 * GB, disk: 0.2 * GB,
    over: { update: { available: true, to: "2.5.9", manual: false, note: "" } } }),
  tile("jellyfin", "Films and shows", "Jellyfin", "films", "media", 8096, { version: "10.11.2", ram: 1.1 * GB, disk: 2 * GB,
    over: { reading: reading("Nothing playing", "adapter:jellyfin", 2 * MIN, 300) } }),
  tile("seerr", "Requests", "Seerr", "requests", "media", 5055, { version: "2.7.3", ram: 0.3 * GB, disk: 0.2 * GB }),
  tile("adblock", "Ad blocking", "AdGuard Home", "ad-blocking", "network", 3000, { version: "0.107.69", ram: 0.1 * GB, disk: 0.1 * GB,
    over: { household: false, reading: reading("14 % of lookups blocked today", "adapter:adguard", 3 * MIN) } }),
  tile("backups", "Backups", "restic", "backups", "lab-core", null, { version: "0.18.1" }),
  tile("caddy", "Front door", "Caddy", "front-door", "lab-core", null, { version: "2.10.2" }),
  tile("brodec-machine", "This server on BRODEC", "brodec-machine", "phone", "brodec", null, {}),
];

const doorTiles = (apps) => apps.filter((t) => t.household && t.open).map(({ id, job, app, holo, open }) => ({ id, job, app, holo, open: { url: open.url } }));

const door = (apps = APPS, extra = {}) => ({ schema: 1, lab, server, world: "wick", tiles: doorTiles(apps), signin: { code: true, phone: false, account: false }, ...extra });

const SIGNED_OUT = { schema: 1, signed_in: false, role: null, browser: null, expires_at: null, browsers: [] };
const signedIn = (n = 2) => ({
  schema: 1, signed_in: true, role: "owner", browser: { id: "b-3f9a", name: "Firefox on Linux" }, expires_at: NOW + 30 * D,
  browsers: [
    { id: "b-3f9a", name: "Firefox on Linux", signed_in_at: NOW - 3 * D, last_seen_at: NOW, current: true },
    { id: "b-81c0", name: "Safari on a Mac", signed_in_at: NOW - 12 * D, last_seen_at: NOW - 2 * D, current: false },
    { id: "b-0d77", name: "Chrome on Windows", signed_in_at: NOW - 20 * D, last_seen_at: NOW - 9 * D, current: false },
  ].slice(0, n),
});

// ---------------------------------------------------------------- machines and the board
const machine = (name, kind, extra = {}) => ({
  name, kind, here: name === "myserver", page: name === "myserver", state: "ok", state_word: "online",
  roles: kind === "server" ? ["Home services", "Media"] : kind === "storage" ? ["Storage"] : kind === "node" ? ["Lab node"] : [],
  updates: { count: 0, security: false },
  readings: { cpu_pct: 12, ram_pct: 31, temp_c: 36, at: NOW - 20 * SEC, max_age_s: 45 },
  apps: 0, ...extra,
});
const HW = { cpu: 4, ram_gb: 16, gpu: false, gpu_name: null, gpu_vram_gb: 0, drives: [
  { device: "nvme0", model: "Samsung SSD 970 EVO Plus 500GB", size_bytes: 500107862016, kind: "nvme" },
  { device: "sda", model: "WDC WD10EZEX", size_bytes: 1000204886016, kind: "ata" },
  { device: "sdb", model: "WDC WD10EZEX", size_bytes: 1000204886016, kind: "ata" }] };
const MYSERVER = machine("myserver", "server", { updates: { count: 2, security: false }, apps: APPS.length, hardware: HW,
  readings: { cpu_pct: 23, ram_pct: 49, temp_c: 38, ram_used_bytes: 7.8 * GB, ram_total_bytes: 16 * GB, load1: 0.9, net_in_mbps: 6, net_out_mbps: 28, at: NOW - 20 * SEC, max_age_s: 45 } });

// the pass-through documents, in their commands' own keys (docs/storage.md, lib/bromigos_backups.py, bromigos-server)
const drive = (device, model, kind, verdict, words, summary) => ({ key: `${kind}-${model.replace(/\W+/g, "_")}-${device}`, device, model, kind, present: true, verdict, words, summary });
const STORAGE = { schema: 1, checked_at: NOW - 12 * MIN, history: "/var/lib/bromigos/drives/history.json", rules: {}, drives: [
  drive("nvme0", "Samsung SSD 970 EVO Plus 500GB", "nvme", "healthy", "healthy", "nothing to report"),
  drive("sda", "WDC WD10EZEX", "ata", "healthy", "healthy", "nothing to report"),
  drive("sdb", "WDC WD10EZEX", "ata", "healthy", "healthy", "nothing to report")] };
const STORAGE_WORSE = { ...STORAGE, drives: STORAGE.drives.map((d) => (d.device === "sdb" ? { ...d, verdict: "worse", words: "getting worse", summary: "reallocated sectors rose from 0 to 8 in the last 3 days" } : d)) };
const S = (ms) => Math.round(ms / 1000);
const BACKUPS = { schema: 1, ok: true, server: true, configured: true, to: "s3:backups.example.org/myserver", destination: {},
  health: { state: "ok", verdict: "Backups are healthy: the last copy was made today and checks out.", problems: [] },
  last_backup: { phase: "ok", ts: S(NOW - 8 * H + 6 * MIN), age_s: 8 * 3600 }, last_success: { ts: S(NOW - 8 * H + 6 * MIN), age_s: 8 * 3600 },
  last_check: null, last_check_passed: null, last_read_back: null, last_test: { phase: "ok", ts: S(NOW - 12 * D) }, last_test_passed: { ts: S(NOW - 12 * D) },
  snapshots: { count: 41 }, drives: [], restore: null, running: null, checked_at: "2026-11-10T22:01:40Z", now: S(NOW) };
const UPDATES = { hold: null, waiting: null, phase: "ok", started: "2026-11-10 03:18", finished: "2026-11-10 03:21", finished_ts: S(Date.UTC(2026, 10, 10, 11, 21)),
  pre: 40, post: 41, packages: 12, reason: "", kernel: false, auto: true, mode: "auto", window: "03:00-05:00", channel: "stable", notify: true,
  cluster_reboots: false, timer: "active", rollbacks: [] };

// a machine's trends, a reading every 15 minutes for a day (GET /api/vitals)
const wave = (base, amp, k) => Array.from({ length: 97 }, (_, i) => [NOW - 24 * H + i * 15 * MIN, Math.round((base + amp * Math.sin(i / k) + (amp / 3) * Math.sin(i / 2.3)) * 10) / 10]);
const VITALS = { "myserver/24h": { schema: 1, machine: "myserver", range: "24h", step_s: 900, at: NOW - 20 * SEC,
  series: { cpu_pct: wave(22, 9, 9), ram_pct: wave(48, 4, 14), net_in_mbps: wave(8, 5, 6), net_out_mbps: wave(24, 12, 7), temp_c: wave(36, 3, 16) } } };

const board = (over = {}) => ({
  schema: 1, at: NOW - 20 * SEC, max_age_s: 45, lab, server: { name: "myserver", kind: "server", roles: ["home", "media"] },
  status: { state: "ok", words: "Everything is running.", checked_at: NOW - 20 * SEC },
  machines: [MYSERVER], needs_you: [], fixed: [], apps: APPS,
  storage: STORAGE, backups: BACKUPS, updates: UPDATES, ups: null,
  ...over,
});

// ---------------------------------------------------------------- jobs (DESIGN §4)
let seq = 0;
const step = (id, label, state, started, ended, detail = null, progress = null) => ({ id, label, state, started_at: started, ended_at: ended, detail, progress });
const job = (kind, subject, title, state, started, over = {}) => {
  const d = new Date(started);
  const stamp = `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, "0")}${String(d.getUTCDate()).padStart(2, "0")}-${String(d.getUTCHours()).padStart(2, "0")}${String(d.getUTCMinutes()).padStart(2, "0")}`;
  const id = `${stamp}-${kind}-${subject?.id ?? "server"}-${(0xa1b0 + ++seq).toString(16)}`;
  return {
    schema: 1, id, kind, title, subject, state, waiting_for: null, question: null, steps: [], step: null, pct: null, stage: null, notes: [],
    started_at: started, updated_at: started, ended_at: null, requested_by: { via: "board", device: null },
    unit: `bromigos-job-${id}.service`, locks: [], can: [], cancel_safe: false, cancel_note: null,
    result: null, error: null, exit_code: null, command: ["bromigos", "activity", "run"], log: `/var/lib/bromigos/activity/jobs/${id}.log`,
    parent: null, children: [], ...over,
  };
};

const backupDone = job("backup.run", { type: "backup", id: "myserver", name: "this server" }, "Backing up this server", "succeeded", NOW - 8 * H, {
  requested_by: { via: "timer", device: null }, ended_at: NOW - 8 * H + 6 * MIN, updated_at: NOW - 8 * H + 6 * MIN, exit_code: 0,
  steps: [
    step("snapshot", "Taking a snapshot", "done", NOW - 8 * H, NOW - 8 * H + MIN),
    step("copy", "Copying what changed", "done", NOW - 8 * H + MIN, NOW - 8 * H + 5 * MIN, "1.2 GB to s3"),
    step("check", "Checking the copy", "done", NOW - 8 * H + 5 * MIN, NOW - 8 * H + 6 * MIN),
  ],
  result: { ok: true, summary: "Backed up: 1.2 GB changed, the copy checks out.", undo: null },
});

const backupRunning = job("backup.run", { type: "backup", id: "myserver", name: "this server" }, "Backing up this server", "running", NOW - 3 * MIN, {
  cancel_safe: true, can: ["cancel"], step: 1, pct: 40, updated_at: NOW - 10_000,
  steps: [
    step("snapshot", "Taking a snapshot", "done", NOW - 3 * MIN, NOW - 2 * MIN),
    step("copy", "Copying what changed", "running", NOW - 2 * MIN, null, null, { done: 480, total: 1200, unit: "MB" }),
    step("check", "Checking the copy", "todo", null, null),
  ],
});

const rolledBack = job("app.update", { type: "app", id: "photos", name: "Photos" }, "Updating Photos", "rolled-back", NOW - 8 * H - 32 * MIN, {
  requested_by: { via: "timer", device: null }, ended_at: NOW - 8 * H - 31 * MIN, updated_at: NOW - 8 * H - 31 * MIN, exit_code: 1, can: ["retry"],
  steps: [
    step("snapshot", "Keeping a way back", "done", NOW - 8 * H - 32 * MIN, NOW - 8 * H - 32 * MIN),
    step("install", "Installing the new version", "done", NOW - 8 * H - 32 * MIN, NOW - 8 * H - 31 * MIN),
    step("check", "Checking that it answers", "failed", NOW - 8 * H - 31 * MIN, NOW - 8 * H - 31 * MIN),
    step("back", "Putting the old version back", "done", NOW - 8 * H - 31 * MIN, NOW - 8 * H - 31 * MIN),
  ],
  error: { step: "check", words: "no answer in 2 minutes", code: "health", fix: null },
  result: { ok: false, summary: "Put back: Photos runs v3.3.5 again, with its data as it was.", undo: null },
});

const askReplace = job("drive.replace", { type: "drive", id: "ata-WDC_WD10EZEX_ab12", name: "sdb" }, "Replacing a drive: WDC WD10EZEX (sdb)", "needs-you", NOW - 22 * MIN, {
  waiting_for: "you", can: ["answer"], step: 2, updated_at: NOW - 9 * MIN,
  question: { id: "swapped", text: "Swap the drive now. It is safe to pull sdb; the server stays on.", asked_at: NOW - 9 * MIN,
    choices: [{ id: "done", label: "I've swapped it", danger: false }, { id: "undo", label: "Put sdb back in use", danger: false }] },
  steps: [
    step("backup", "Backing up first", "done", NOW - 22 * MIN, NOW - 10 * MIN),
    step("out", "Taking sdb out of use", "done", NOW - 10 * MIN, NOW - 9 * MIN),
    step("swap", "Swap the drive now", "waiting", NOW - 9 * MIN, null, "The server stays on. sda keeps working."),
    step("check", "Checking the new drive", "todo", null, null),
    step("copy", "Copying everything onto it", "todo", null, null),
  ],
});

const DRIVE_ALERT = { id: "drive-sdb", machine: "myserver", subject: { type: "drive", id: "ata-WDC_WD10EZEX_ab12", name: "sdb" }, severity: "warn",
  words: "A drive is getting worse", detail: "back up, then plan to replace it", since: NOW - 3 * D, go: "data", job: null };

// ---------------------------------------------------------------- the page states
const F = {
  "door-empty": { about: "Signed out, nothing installed yet: the door says apps appear here.", door: door([]), session: SIGNED_OUT, board: { $status: 401 }, activity: [] },
  door: { about: "Signed out: the door with the household's apps; the code KX7-42Q signs in.", door: door(), session: SIGNED_OUT, board: { $status: 401 },
    signin: { code: "KX7-42Q", session: signedIn() }, activity: [backupDone] },
  unreachable: { about: "The page loaded but the board service doesn't answer.", door: { $status: 503, $error: { code: "unavailable", words: "The board service isn't answering." } },
    session: { $status: 503 }, board: { $status: 503 }, activity: [] },
  healthy: { about: "Signed in, one server, everything running, nothing running now; a day of trends.", door: door(), session: signedIn(), board: board({ fixed: [] }), activity: [backupDone, rolledBack], vitals: VITALS },
  running: { about: "Signed in; a backup runs and finishes while you watch (the stream).", door: door(), session: signedIn(), board: board(),
    activity: [backupRunning, backupDone],
    stream: [
      { after_ms: 900, event: "job", data: { ...backupRunning, step: 2, pct: 90, updated_at: NOW, steps: backupRunning.steps.map((s) => (s.id === "copy" ? { ...s, state: "done", ended_at: NOW, progress: { done: 1200, total: 1200, unit: "MB" } } : s.id === "check" ? { ...s, state: "running", started_at: NOW } : s)) } },
      { after_ms: 1800, event: "job", data: { ...backupRunning, state: "succeeded", can: [], cancel_safe: false, pct: 100, ended_at: NOW + 2000, updated_at: NOW + 2000, exit_code: 0,
        steps: backupRunning.steps.map((s) => ({ ...s, state: "done", ended_at: NOW + 2000 })), result: { ok: true, summary: "Backed up: 1.2 GB changed, the copy checks out.", undo: null } } },
    ] },
  "needs-you": { about: "Signed in; a drive is getting worse; a drive replacement asks you; Photos' update was put back.", door: door(), session: signedIn(3),
    board: board({ status: { state: "needs-you", words: "1 thing needs you.", checked_at: NOW - MIN },
      machines: [{ ...MYSERVER, state: "warn", state_word: "needs you" }], needs_you: [DRIVE_ALERT], storage: STORAGE_WORSE,
      fixed: [{ id: rolledBack.id, machine: "myserver", words: "Photos' update was put back", at: rolledBack.ended_at }] }),
    activity: [askReplace, rolledBack, backupDone] },
  alert: { about: "Signed in; a drive is getting worse, and no job asks yet: the strip shows the alarm.", door: door(), session: signedIn(),
    board: board({ status: { state: "needs-you", words: "1 thing needs you.", checked_at: NOW - MIN },
      machines: [{ ...MYSERVER, state: "warn", state_word: "needs you" }], needs_you: [DRIVE_ALERT] }),
    activity: [backupDone] },
  lab: { about: "Signed in to a lab of four machines (a layout check for the rail; one server is today's scope).", door: door(), session: signedIn(),
    board: board({ machines: [MYSERVER, machine("vault", "storage", { apps: 3 }), machine("node3", "node", { apps: 2, state: "unknown", state_word: "not seen for 2 h", readings: null }), machine("mydesk", "desktop", { updates: { count: 1, security: true } })] }),
    activity: [backupDone] },
  setup: { about: "Signed in to a server with nothing installed yet (first run).", door: door([]), session: signedIn(1),
    board: board({ status: { state: "setup", words: "Nothing installed yet.", checked_at: NOW - MIN }, apps: [], machines: [{ ...MYSERVER, apps: 0, updates: { count: 0, security: false } }] }),
    activity: [] },
  stale: { about: "Signed in, but the snapshot is 20 minutes old: readings go static grey with their age.", door: door(), session: signedIn(),
    board: board({ at: NOW - 20 * MIN, status: { state: "unknown", words: "Last read 20 min ago.", checked_at: NOW - 20 * MIN },
      machines: [{ ...MYSERVER, state: "unknown", state_word: "not read for 20 min", readings: { ...MYSERVER.readings, at: NOW - 20 * MIN } }] }),
    activity: [backupDone] },
  cameras: { about: "Signed in; a machine runs the Cameras app, so Cameras is in the rail.", door: door(), session: signedIn(),
    board: board({ apps: [...APPS, tile("cameras", "Cameras", "Frigate", null, "cameras", 5000, { version: "0.16.2" })] }), activity: [] },
};

for (const [name, f] of Object.entries(F)) {
  writeFileSync(`${dir}${name}.json`, JSON.stringify({ now: NOW, ...f }, null, 1) + "\n");
}
console.log(`wrote ${Object.keys(F).length} fixtures to ${dir}`);
