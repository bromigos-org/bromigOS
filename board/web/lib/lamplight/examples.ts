// Example labs for the design pages and the tests: each scenario as `LamplightData`, as a host
// would build it, with every optional layer. No page of the Lab board imports this file: the
// board builds its data from its own document (from-board.ts).
//
// The example lab: myserver (a server, the lab home, 18 apps), node3 (a small server), vault
// (storage), a battery on vault, the router, and mydesk (the desktop this browser is on). Its one
// trouble: myserver's drive sdb has 8 reallocated sectors. Its last good copy landed at 06:14.
import type { LampGoals, LampHub, LampLogEntry, LampMachine, LampShow, LampSky, LamplightData } from "./types";

export type Scenario = "needs" | "calm" | "quiet" | "goal" | "setup";
export const SCENARIOS: { id: Scenario; label: string; hint: string }[] = [
  { id: "needs", label: "NEEDS YOU", hint: "Needs you: myserver's drive sdb is getting worse. The alarm, the hull amber, interference, LINEMAN beside myserver, a copy being carried, VECTOR's plan" },
  { id: "calm", label: "ALL CALM", hint: "All calm: a clear field, the watch kept, the roll-call ready" },
  { id: "quiet", label: "QUIET HOURS", hint: "Quiet hours: the night side, lights low, nobody speaks" },
  { id: "goal", label: "A GOAL REACHED", hint: "A goal reached: the first proven restore; PROVEN rises among the stars and the beam grows a step" },
  { id: "setup", label: "SET-UP", hint: "Just installed: one server with nothing on it yet. Lit, no alarm, and none of the optional layers" },
];

const machines = (): LampMachine[] => [
  { id: "router", name: "router", kind: "router", role: "Equipment, read-only", state: "ok", word: "read-only", reading: "21 clients", page: false },
  { id: "myserver", name: "myserver", kind: "server", role: "Home services · Media · Game server", state: "ok", word: "online", reading: "18 apps · lab home", page: true },
  { id: "node3", name: "node3", kind: "node", role: "Lab node", state: "ok", word: "online", reading: "2 apps · cluster", page: true },
  { id: "vault", name: "vault", kind: "storage", role: "Storage", state: "ok", word: "online", reading: "can lose one drive · copy 06:14", page: true },
  { id: "battery", name: "battery", kind: "ups", role: "Equipment on vault's USB", state: "ok", word: "on mains", reading: "battery on watch", page: false },
  { id: "mydesk", name: "mydesk", kind: "desktop", role: "bromigOS desktop", state: "ok", word: "you are here", reading: "docked", here: true, page: true },
];

const GOAL_STARS = [
  { name: "FIRST LIGHT", hint: "the post answered its first roll-call" }, { name: "FIRST COPY", hint: "the first backup landed" }, { name: "TWO COPIES", hint: "two copies of everything" },
  { name: "MEDIA WIRED", hint: "the media stack wired" }, { name: "MORE MACHINES", hint: "vault and node3 joined" },
];
const sky = (s: Scenario): LampSky => ({
  arcs: [
    { name: "THE POWER CUT", stars: 3, hint: "10-21: power back after 41 minutes; vault shut down cleanly on battery. An ended arc, named by its outcome." },
    { name: "THE FULL DISK", stars: 4, hint: "10-02, 4 nights: ended when the films moved to vault." },
    { name: "A NEW SIGNAL", stars: 2, hint: "09-28: a new phone joined; ended when you approved it." },
    ...(s === "needs" ? [{ name: "THE SDB ARC · FORMING", stars: 3, open: true, hint: "The sdb arc, forming: one amber star a night. When it ends with a verified fix it turns white and takes its name from the outcome: SURVIVED A DRIVE SWAP." }] : []),
  ],
  goals: GOAL_STARS,
  copies: s === "goal" ? { proven: true, fresh: true, hint: "PROVEN: tonight's test restore proved your copies, so their stars joined into a constellation. It stays for good." }
    : { proven: false, hint: "Your copies: one faint star per backup. Loose until a restore proves them; then they join into a constellation." },
});
const log = (s: Scenario): LampLogEntry[] => [
  ...(s === "goal" ? [{ at: "20:12", title: "PROVEN · THE FIRST RESTORE", detail: "a sample came back, was read and removed; your copies' stars joined into PROVEN", kind: "arc" as const, mark: "fresh" as const }] : []),
  ...(s === "needs" ? [{ at: "11-08", title: "THE SDB ARC · FORMING", detail: "night 3: 8 reallocated sectors; three amber stars, one a night", kind: "arc" as const, mark: "open" as const }] : []),
  { at: "06:14", title: "LAST GOOD COPY", detail: "today, to vault · 412 GB · one more loose star", kind: "copy" },
  { at: "03:00", title: "NEXT COPY", detail: "tonight, by its timer", kind: "copy" },
  { at: "11-02", title: "ROLLED BACK BY ITSELF", detail: "an update didn't come back healthy; the station returned to snapshot 205", kind: "event" },
  { at: "10-21", title: "THE POWER CUT", detail: "power back after 41 minutes; vault shut down cleanly on battery", kind: "arc" },
  { at: "10-02", title: "THE FULL DISK", detail: "4 nights; ended when the films moved to vault", kind: "arc" },
  { at: "09-28", title: "A NEW SIGNAL", detail: "a new phone joined; ended when you approved it", kind: "arc" },
];
const goals = (s: Scenario): LampGoals => {
  const g = s === "goal", base = 2950;
  return {
    rank: { title: "WAYFINDER", xp: g ? base + 300 : base, from: 2200, to: 3300, next: "LINEWALKER", gained: g ? 300 : 0 },
    list: [
      { state: "done", title: "First light", detail: "a named star: FIRST LIGHT", xp: 100, cap: "once" },
      { state: "done", title: "First copy in the hold", detail: "a named star: FIRST COPY", xp: 150, cap: "once" },
      { state: g ? "done" : "progress", fresh: g, title: "The first proven restore", detail: g ? "tonight: the copies join as PROVEN" : "joins your copies into a constellation", xp: 300, cap: "once" },
      { state: "done", title: "Two copies of everything", detail: "a named star: TWO COPIES", xp: 300, cap: "once" },
      { state: "progress", title: "A copy off-site", detail: "the Go Bag, or later a friend's station", xp: 400, cap: "once" },
      { state: "progress", title: "A month with no failed backup", detail: "19 of 30 days", xp: 250, cap: "1 a month" },
      { state: "done", title: "The media stack wired", detail: "a named star: MEDIA WIRED", xp: 150, cap: "once" },
      { state: "done", title: "More machines joined", detail: "each docks a new compartment", xp: 200, cap: "2 in all" },
      { state: "todo", title: "A restore proven again", detail: "a new star in PROVEN", xp: 100, cap: "1 a quarter" },
    ],
  };
};
const OPEN = { kind: "open" as const, over: "ROLL-CALL", title: "142.59", detail: "MYLAB'S POST · 11-10 · NOIR HOSTING", art: "loop/host", hint: "The open: NOIR hosts from his pod." };
const show = (s: Scenario): LampShow => {
  if (s === "needs") return { when: "composed 20:30", cards: [OPEN,
    { over: "THE SDB ARC · NIGHT 3", title: "SDB HOLDS AT 8", detail: "8 reallocated sectors, the same as last night. LINEMAN is staying in the bay.", art: "loop/whack", hint: "From bromigos storage health --json." },
    { kind: "bump", over: "BUMP", title: "BACK IN A MOMENT", art: "bump/right-back", hint: "A shipped bump: right-back." },
    { over: "THE HOLD", title: "A COPY IS RUNNING · 64 %", detail: "Step one of VECTOR's plan. The last good copy landed at 06:14.", art: "crew/exo-work", hint: "From bromigos activity list --json and backup.json." },
    { over: "SIGN-OFF", title: "LIT · ONE THING NEEDS YOU", vector: "Night three. The plan is docked at the booth whenever you are.", art: "bump/sign-off", hint: "The sign-off. VECTOR has the last line." }],
    thread: { title: "THE THREAD · THE SDB ARC", night: "night 3", steps: [
      { when: "NIGHT 1", date: "11-08", title: "FOUND: GETTING WORSE", detail: "8 reallocated sectors appeared in 3 days. The alarm sounded; LINEMAN went to the bay. The first amber star." },
      { when: "NIGHT 2", date: "11-09", title: "THE COPY CHECKED", detail: "5 % read back, clean. sdb held at 8." },
      { when: "NIGHT 3", date: "11-10", title: "STILL AT 8 · A COPY RUNNING", detail: "No new sectors. VECTOR's plan is docked at the booth." },
      { when: "ENDS", title: "SWAP · REBUILD · SCRUB · COPY", detail: "Then the alarm and the interference clear and the amber stars turn white as SURVIVED A DRIVE SWAP: a named arc in your sky. A fix never pays XP.", next: true }] } };
  if (s === "goal") return { when: "composed 20:30", cards: [OPEN,
    { over: "A FIRST", title: "A PROVEN RESTORE", detail: "At 20:12 a sample came back, was read and removed. Your copies are a constellation now.", art: "crew/exo-rest", hint: "From restore-test.json test_ok." },
    { kind: "bump", over: "NEW IN YOUR SHOW", title: "THE CREW", art: "bump/crew", hint: "A growth reward: the shipped crew bump joins your roll-call." },
    { over: "THE STATION GROWS", title: "PROVEN · BEAM 6 OF 10", detail: "+300 field XP, ENGINEER. WAYFINDER: 50 to LINEWALKER.", art: "crew/hermit", hint: "Growth: a named constellation, a beam step, capped field XP." },
    { over: "SIGN-OFF", title: "STILL LIT", vector: "Classification: a proven restore. The crew may stand down.", art: "bump/still-lit", hint: "The sign-off." }] };
  return { when: s === "quiet" ? "aired 20:30 · watched" : "composed 20:30", aired: s === "quiet", cards: [OPEN,
    { over: "THE HOLD", title: "COPY IN THE HOLD · 06:14", detail: "412 GB to vault. One more loose star.", art: "crew/exo-rest", hint: "From backup.json run_ok." },
    { over: "THE RACK ROOM", title: "MYSERVER UPDATED", detail: "214 packages, a restore point before and after.", art: "loop/whack", hint: "From bromigos server status --json." },
    { kind: "bump", over: "BUMP", title: "STAY TUNED", art: "bump/late-night", hint: "A shipped bump: late-night." },
    { over: "SIGN-OFF", title: "STILL LIT", vector: "Nothing went wrong today, and I have recorded all of it.", art: "bump/still-lit", hint: "The sign-off, STILL LIT." }] };
};
const FRIENDS = [
  { id: "rivet", name: "RIVET", lit: true, decks: 3, stars: 7, last: "STILL LIT · 2 nights ago" }, { id: "kestrel", name: "KESTREL", lit: true, decks: 2, stars: 4, last: "STILL LIT · tonight" },
  { id: "moth", name: "MOTH", lit: true, decks: 4, stars: 9, last: "STILL LIT · tonight" }, { id: "tallow", name: "TALLOW", lit: false, decks: 2, stars: 3, last: "not in yet tonight" },
  { id: "spool", name: "SPOOL", lit: true, decks: 3, stars: 6, last: "STILL LIT · tonight" }, { id: "ferro", name: "FERRO", lit: true, decks: 2, stars: 5, last: "STILL LIT · last night" },
];
const HUB: LampHub = {
  name: "NIGHTSHIFT", line: "A LAB CLUB FACTION · 6 STATIONS IN ORBIT · PLANNED",
  members: [
    { id: "you", name: "YOU · MYLAB'S POST", state: "lit", you: true, hint: "Your own post, as the faction sees it: its lamp, its decks as shapes, the goals you chose to show." },
    { id: "rivet", name: "RIVET", state: "lit", hint: "RIVET's station: lit tonight. Shapes and states only, by RIVET's choice." }, { id: "kestrel", name: "KESTREL", state: "lit", hint: "KESTREL's station: lit tonight." },
    { id: "moth", name: "MOTH", state: "lit", hint: "MOTH's station: lit. MOTH is out on tonight's field op." }, { id: "tallow", name: "TALLOW", state: "out", hint: "TALLOW's station: not in yet tonight. Said plainly, never as a warning." },
    { id: "spool", name: "SPOOL · NEW BERTH", state: "new", hint: "SPOOL joined the faction today: a new berth on the orbit." },
  ],
  docks: [
    { name: "CODEC · THE BRIDGE", lit: true, hint: "A voice channel is the hub's bridge: lit while people are in it. 3 in now." }, { name: "WATCH PARTY · BIG SCREEN", lit: true, hint: "A watch party is the hub's big screen; 2 den TVs are linked to it." },
    { name: "#LAB-CLUB", hint: "A text channel: a dock on the hub's ring." }, { name: "#OPS · FORUM", hint: "A forum channel: field ops are planned here." }, { name: "#GENERAL", hint: "A text channel: a dock on the hub's ring." },
  ],
  op: { words: "FIELD OP · 2 OUT", hint: "A field op in progress: two members are out on a relight; the ship leaves the hub and comes back when the op ends." },
  favour: { words: "FAVOUR · PLANNED", hint: "Planned: RIVET holds your off-site copy, so a beam runs between your stations through the hub. Not built yet." },
  sector: [{ name: "NIGHTSHIFT · HERE", here: true, hint: "NIGHTSHIFT: you are here" }, { name: "LAB CLUB · WEST", hint: "Another faction you belong to: a hub further off in your sector" }, { name: "DRIFTERS 9", hint: "Another faction you belong to" }],
};

/** One scenario as the data a host would pass. */
export function example(s: Scenario, mascot: "on" | "quiet" | "off" = "on"): LamplightData {
  if (s === "setup") {
    return { lab: { name: "MYLAB", address: "https://mylab.local" }, clock: "20:41", mascot, status: { state: "setup", words: "Nothing installed yet." }, needs: [],
      machines: [{ id: "myserver", name: "myserver", kind: "server", role: "Home services · Media", state: "setup", word: "set up", reading: "nothing installed yet", here: true, page: true }] };
  }
  const m = machines(), needs = s === "needs";
  const d: LamplightData = {
    lab: { name: "MYLAB", address: "https://mylab.local" }, clock: s === "quiet" ? "23:40" : "20:41", mascot,
    status: needs ? { state: "needs-you", words: "1 thing needs you." } : { state: "ok", words: s === "goal" ? "Everything is running. A restore was proven tonight." : "Everything is running." },
    machines: m, needs: [], joining: [], quiet: s === "quiet" ? { on: true, until: "08:00" } : null,
    sky: sky(s), log: log(s), goals: goals(s), show: show(s), friends: FRIENDS, hub: HUB,
  };
  if (needs) {
    Object.assign(m[1], { state: "warn", word: "needs you", cause: "storage" });
    d.needs = [{ id: "drive-sdb", machine: "myserver", words: "A drive is getting worse", detail: "8 reallocated sectors appeared in the last 3 days. Back up, then plan to replace it.", severity: "warn", subject: { type: "drive", name: "sdb" }, go: "data" }];
    d.jobs = [{ id: "job-backup", machine: "myserver", kind: "backup.run", title: "a backup of myserver to vault", pct: 64 }];
    d.plan = { title: "VECTOR'S PLAN · SDB", from: "From the alert disk.smart:sdb · choosing pays nothing", can: ["approve", "change", "no"], steps: [
      { words: "Finish the copy to vault", detail: "running · 64 %", hint: "Step 1 runs now: bromigos lab backups run" },
      { words: "Read 5 % of the copy back", detail: "after step 1 · changes nothing", hint: "Step 2 on approval: bromigos server backup check --data. It reads; it changes nothing" },
      { words: "Replace sdb", detail: "your hands · the steps on the board", hint: "Step 3 is yours: the board shows the swap steps; the pool rebuilds and scrubs by itself after" }] };
    d.exchange = { mood: "suspicious", thought: "sdb has eight scars and I don't trust it with a ninth. I'm staying in the bay until it's swapped.", vector: "Eight reallocated sectors, unchanged since yesterday. My plan is docked at the booth. Protocol is wise.", why: "the drive check says sdb has 8 reallocated sectors and is getting worse" };
  }
  if (s === "goal") d.exchange = { mood: "happy", thought: "It came BACK. The files came back. Look at the stars!", vector: "Classification: a proven restore. Your copies are now a constellation. Point to the backup.", why: "the first test restore passed" };
  return d;
}
