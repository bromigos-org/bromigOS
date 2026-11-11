// Writes fixtures/*.json: one page state of the whole lab per file, for ?fixture=NAME in a test
// build (lib/api/fixtures.ts) and for building pages without a server.
//
// Every document starts from a real answer of the service (tests/contract/service.json, made by
// scripts/make-contract.py from the service's and the commands' own code), so a fixture has the
// shapes the service sends by construction; tests/shapes.spec.ts checks it. On top of a real
// answer a fixture may only: install more of the catalogue's apps on the example server, and
// add what the page has asked the service for and the service doesn't send yet (a machine's
// readings, a tile's reading and update, trends, the actions the page may take,
// more machines). Those additions are example data, and each is named below.
//
//   node scripts/make-fixtures.mjs
import { mkdirSync, readFileSync, readdirSync, unlinkSync, writeFileSync } from "node:fs";

const dir = new URL("../fixtures/", import.meta.url).pathname;
const real = JSON.parse(readFileSync(new URL("../tests/contract/service.json", import.meta.url), "utf8"));
const NOW = real.now;
const SEC = 1000, MIN = 60 * SEC, H = 60 * MIN, D = 24 * H, GB = 1024 ** 3;
const copy = (x) => structuredClone(x);

/** The jobs of a real activity stream's first event. */
const jobsOf = (name) => JSON.parse(real.http[name].body.split("\n").find((l) => l.startsWith("data: ")).slice(6)).jobs;

// ---------------------------------------------------------------- the example server's apps
// Catalogue items installed on the example server beyond the three the real answer has (Caddy,
// Photos, Passwords): each real tile is turned into an installed one, as the apps list prints
// one. `reading` and `update` are null in every real answer today; the two set here are the
// tile contract's (DESIGN §3), for the pages that show them.
const RUNS = {
  photos: { reading: ["Last photo backed up 2 hours ago", "adapter:immich", 4 * MIN], update: "v3.3.6", ram: 2.04, disk: 38 },
  passwords: { ram: 0.06, disk: 0.1 },
  documents: { version: "2.18.4", port: 8010, ram: 0.9, disk: 6, reading: ["1,204 documents", "adapter:paperless", 6 * MIN] },
  uptime: { version: "2.5.8", port: 3001, ram: 0.15, disk: 0.2, update: "2.5.9" },
  jellyfin: { version: "10.11.2", port: 8096, ram: 1.1, disk: 2 },
  seerr: { version: "2.7.3", port: 5055, ram: 0.3, disk: 0.2 },
  adblock: { version: "0.107.69", port: 3000, ram: 0.1, disk: 0.1 },
  backups: { version: "0.18.1" },
  caddy: {},
  "brodec-machine": {},
};

function apps(list, { readings = true } = {}) {
  return list.map((t) => {
    const r = RUNS[t.id];
    if (!r) return t;
    const was = t.installed;
    const out = { ...t, installed: true, state: "ok", state_word: "Running", since: t.since ?? NOW - 6 * D, version: t.version ?? r.version ?? null,
      open: t.open ?? (r.port ? { url: `https://${t.id}-myserver.local`, port: r.port } : null),
      measured: { ram_bytes: r.ram ? Math.round(r.ram * GB) : t.measured?.ram_bytes ?? null, disk_bytes: r.disk ? Math.round(r.disk * GB) : t.measured?.disk_bytes ?? null },
      can: was ? t.can : r.port ? ["open", "restart", "logs", "remove"] : ["restart", "logs", "remove"] };
    if (readings && r.reading) out.reading = { text: r.reading[0], source: r.reading[1], at: NOW - r.reading[2], max_age_s: 900 };
    if (readings && r.update) out.update = { available: true, to: r.update, manual: false, note: "" };
    return out;
  });
}

const doorOf = (board) => ({ ...copy(real.doors.healthy),
  tiles: board.apps.filter((t) => t.installed && t.open && t.household !== false && t.id !== "adblock")
    .map(({ id, job, app, holo, group, open }) => ({ id, job, app, holo: holo ?? "", group: group ?? "", open: { url: open.url } })) });

// ---------------------------------------------------------------- what the service doesn't send yet
// A machine's readings and its trends (board-contracts.md, "what a machine's page reads"). Its
// hardware is the service's own (`machines[].hardware`, from the app manager's scan).
const READ = { cpu_pct: 23, ram_pct: 49, temp_c: 38, ram_used_bytes: 7.8 * GB, ram_total_bytes: 16 * GB, load1: 0.9, net_in_mbps: 6, net_out_mbps: 28, at: NOW - 20 * SEC, max_age_s: 45 };
const wave = (base, amp, k) => Array.from({ length: 97 }, (_, i) => [NOW - 24 * H + i * 15 * MIN, Math.round((base + amp * Math.sin(i / k) + (amp / 3) * Math.sin(i / 2.3)) * 10) / 10]);
const VITALS = { "myserver/24h": { schema: 1, machine: "myserver", range: "24h", step_s: 900, at: NOW - 20 * SEC,
  series: { cpu_pct: wave(22, 9, 9), ram_pct: wave(48, 4, 14), net_in_mbps: wave(8, 5, 6), net_out_mbps: wave(24, 12, 7), temp_c: wave(36, 3, 16) } } };

/** A real board with the example server on it. measured: also the readings the service doesn't send yet.
 *  The example server lets the page do nothing ([board] actions = [] in its server.toml), so these
 *  pages show the command and no control; the `actions` fixture is the one whose server allows it. */
function board(name, { measured = true, more = {} } = {}) {
  const b = copy(real.boards[name]);
  b.actions = [];
  if (Array.isArray(b.apps)) b.apps = apps(b.apps, { readings: measured });
  const n = Array.isArray(b.apps) ? b.apps.filter((t) => t.installed).length : null;
  b.machines = b.machines.map((m) => ({ ...m, apps: n, ...(measured ? { readings: { ...READ, at: b.at - 15 * SEC }, updates: { count: 2, security: false } } : {}) }));
  return { ...b, ...more };
}

const session = (n = 2) => {
  const s = copy(real.http.session_signed_in.body), mine = s.browsers[0];
  s.browsers = [mine,
    { ...mine, id: "00000000000000a2", name: "Safari on a Mac", signed_in_at: NOW - 12 * D, last_seen_at: NOW - 2 * D, current: false },
    { ...mine, id: "00000000000000a3", name: "Chrome on Windows", signed_in_at: NOW - 20 * D, last_seen_at: NOW - 9 * D, current: false }].slice(0, n);
  return s;
};
const SIGNED_OUT = real.http.session_signed_out.body;

// a lab of several machines: a layout check for the rail (one server is what the service serves today)
const others = (me) => [
  { ...me, name: "vault", kind: "storage", here: false, page: false, roles: ["storage"], apps: 3, updates: { count: 0, security: false }, readings: { ...READ, cpu_pct: 12, ram_pct: 31, temp_c: 36 } },
  { ...me, name: "node3", kind: "node", here: false, page: false, state: "unknown", state_word: "not seen for 2 h", roles: ["lab-node"], apps: 2, updates: null, readings: null, hardware: null },
  { ...me, name: "mydesk", kind: "desktop", here: false, page: false, roles: [], apps: 0, updates: { count: 1, security: true }, readings: { ...READ, cpu_pct: 12, ram_pct: 31, temp_c: 36 } }];

// the running backup's later records, played back on the stream: its copy finishes, then the job does
const running = jobsOf("activity_running");
const run = running.find((j) => j.state === "running");
const moved = (over, steps) => ({ ...run, ...over, steps: run.steps.map((s) => ({ ...s, ...(steps[s.id] ?? {}) })) });

// the example server also carries a backup drive away (a real answer's backups, with the Go Bag)
const healthy = { ...board("healthy"), backups: real.boards.backups_gobag.backups };
const needs = board("needs_you");
// no job asks here: the board's own list of jobs is the healthy one's, as its stream's is
const alertOnly = { ...needs, needs_you: needs.needs_you.filter((n) => !n.job), status: { ...needs.status, words: "1 thing needs you." }, activity: board("healthy").activity };
const cantRead = { ...board("healthy", { measured: false }), apps: null, storage: null, backups: null, updates: null, ups: null, system: null,
  sources: { ...real.boards.healthy.sources, ...Object.fromEntries(["apps", "storage", "backups", "system"].map((k) => [k, real.boards[`${k}_missing`].sources[k]])) } };
cantRead.machines = cantRead.machines.map((m) => ({ ...m, apps: null }));

const F = {
  "door-empty": { about: "Signed out, nothing installed yet: the door says apps appear here.", door: real.doors.no_snapshot, session: SIGNED_OUT, board: { $status: 401 }, activity: [] },
  door: { about: "Signed out: the door with the household's apps; the code KX7-42Q signs in.", door: doorOf(healthy), session: SIGNED_OUT, board: { $status: 401 },
    signin: { code: "KX7-42Q", session: session() }, activity: jobsOf("activity_healthy") },
  unreachable: { about: "The page loaded but the board service doesn't answer.", door: { $status: 503, $error: { code: "unavailable", words: "The board's service isn't answering." } },
    session: { $status: 503 }, board: { $status: 503 }, activity: [] },
  "as-served": { about: "Signed in; exactly what the service answers today, untouched: no readings, no trends, three apps.", door: real.doors.healthy, session: session(1),
    board: real.boards.healthy, activity: jobsOf("activity_healthy") },
  "cant-read": { about: "Signed in; the server couldn't read its apps, drives, backups or updates this time.", door: real.doors.apps_missing, session: session(1),
    board: cantRead, activity: jobsOf("activity_healthy") },
  healthy: { about: "Signed in, one server, everything running; with the readings, trends and tile readings the page has asked for.", door: doorOf(healthy), session: session(),
    board: healthy, activity: jobsOf("activity_healthy"), vitals: VITALS },
  actions: { about: "Signed in; the server lets the page add, restart and remove apps (board.actions).", door: doorOf(healthy), session: session(),
    board: { ...healthy, actions: ["add", "restart", "remove", "delete-data"] }, activity: jobsOf("activity_healthy") },
  running: { about: "Signed in; a backup runs and finishes while you watch (the stream).", door: doorOf(healthy), session: session(), board: board("running"),
    activity: running,
    stream: [
      { after_ms: 900, event: "job", data: moved({ step: 2, pct: 90, updated_at: NOW }, { copy: { state: "done", ended_at: NOW }, check: { state: "running", started_at: NOW } }) },
      { after_ms: 1800, event: "job", data: { ...moved({ state: "succeeded", can: [], cancel_safe: false, pct: 100, ended_at: NOW + 2000, updated_at: NOW + 2000, exit_code: 0,
        result: { ok: true, summary: "Backed up: the copy checks out.", undo: null } }, {}), steps: run.steps.map((s) => ({ ...s, state: "done", ended_at: NOW + 2000 })) } },
    ] },
  "needs-you": { about: "Signed in; a drive is getting worse; a drive replacement asks; Photos' update was put back.", door: doorOf(needs), session: session(3),
    board: needs, activity: jobsOf("activity_needs_you") },
  alert: { about: "Signed in; a drive is getting worse, and no job asks: the strip shows the alarm.", door: doorOf(needs), session: session(),
    board: alertOnly, activity: jobsOf("activity_healthy") },
  watch: { about: "Signed in; one drive on watch and one that gives no health records: neither is called healthy.", door: doorOf(healthy), session: session(),
    board: board("drives_watch_unknown"), activity: jobsOf("activity_healthy") },
  lab: { about: "Signed in to a lab of four machines (a layout check for the rail).", door: doorOf(healthy), session: session(),
    board: { ...healthy, machines: [healthy.machines[0], ...others(healthy.machines[0])] }, activity: jobsOf("activity_healthy") },
  setup: { about: "Signed in to a server with nothing installed yet (first run).", door: real.doors.no_snapshot, session: session(1),
    board: real.boards.setup, activity: jobsOf("activity_setup") },
  stale: { about: "Signed in, but the server's reading is five minutes old.", door: doorOf(healthy), session: session(), board: board("stale"), activity: jobsOf("activity_healthy") },
  channels: { about: "Signed in; alerts go to Discord (with quiet hours) and to a webhook whose last message didn't go; a third channel is off.", door: doorOf(healthy), session: session(),
    board: { ...healthy, alerts: real.boards.alerts_channels.alerts }, activity: jobsOf("activity_healthy") },
  cameras: { about: "Signed in; a machine runs the Cameras app, so Cameras is in the rail.", door: doorOf(healthy), session: session(),
    board: { ...healthy, apps: [...healthy.apps, { ...healthy.apps.find((t) => t.id === "photos"), id: "cameras", job: "Cameras", app: "Frigate", holo: "", group: "cameras",
      version: "0.16.2", reading: null, update: null, open: { url: "https://cameras-myserver.local", port: 5000 } }] }, activity: [] },
};

mkdirSync(dir, { recursive: true }); // the folder isn't in the repository: it is made here
for (const f of readdirSync(dir)) if (f.endsWith(".json")) unlinkSync(dir + f);
for (const [name, f] of Object.entries(F)) writeFileSync(`${dir}${name}.json`, JSON.stringify(f) + "\n");
console.log(`wrote ${Object.keys(F).length} fixtures to ${dir}`);
