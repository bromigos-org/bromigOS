// The post: a relay station of the Wick's class (never the Wick itself: no black flame on its
// mast, no codec deck, no gas giant at its window). This file turns `LamplightData` into what the
// scene draws: which compartment each machine rides, what each part of the station says, where
// each shell of the crew stands and why, the one status line, the readouts and the alarm.
//
// The station's parts mean what BRODEC's LAB hero says they mean (brodec lib/src/widgets/
// lab_hero.dart), so the phone and this page agree: mast = network, dish = AI, whips = game
// servers, arrays = nodes, rack room = services (and every alert that isn't storage-shaped),
// dock = media, hull = storage (and storage-shaped alerts). BRODEC maps no part to backups, power
// or the broadcast, so those ride the decks: the hold (D1), the battery (D1) and the booth (D3).
import { KIND_WORD, modelFor } from "./base";
import type { DeckId, LampKind, LampMachine, LampNeed, LampState, LamplightAssets, LamplightData, PartId, Shell } from "./types";

type V3 = [number, number, number];

/** The station model's z shift: its hull is cut open off-centre, so its decks sit this far back. */
export const ZC = -0.0388;
/** The station's resting turn: its cut toward you. */
export const YAW0 = -0.32;
/** The station model's part indices (wick-cut.json). */
export const STATION_PART: Record<string, number> = { decks: 0, mast: 1, dish: 2, whips: 3, solar_l: 4, solar_r: 5, rackroom: 6, dock: 7, hull: 8 };

export const DECKS: { id: DeckId; name: string; hint: string }[] = [
  { id: "D3", name: "COMMS", hint: "The comms deck under the mast: the router, and the booth the roll-call goes out from" },
  { id: "D2", name: "RACK ROOM", hint: "The rack room: the lab's servers" },
  { id: "D1", name: "HOLD", hint: "The hold: storage, where the copies land, the battery, and the crew's quarters" },
  { id: "DOCK", name: "DOCKING RING", hint: "The docking ring: machines docked to the lab, and the open berth a new one joins at" },
];

/** Where machines stand on each deck's tray, in the station model's own units. */
const SLOTS: Record<DeckId, V3[]> = {
  D3: [[-0.07, 0.403, 0.14 + ZC]],
  D2: [[-0.08, 0.273, 0.15 + ZC], [0.1, 0.273, 0.16 + ZC], [0.19, 0.273, 0.22 + ZC]],
  D1: [[-0.09, 0.133, 0.17 + ZC], [0.03, 0.133, 0.17 + ZC], [-0.18, 0.133, 0.23 + ZC]],
  DOCK: [[-0.34, 0.03, 0.16 + ZC], [-0.22, 0.03, 0.3 + ZC]],
};
const BOOTH: V3 = [0.075, 0.403, 0.2 + ZC];
const QUARTERS: V3 = [0.15, 0.133, 0.24 + ZC];
const BERTH: V3 = [0.3, 0.06, 0.12 + ZC];
export const MAST_FOOT: V3 = [0.03, 0.5, 0.02 + ZC];
export const MONITOR_AT: V3 = [-0.03, 0.47, 0.2 + ZC];
export const BOOTH_EDGE: V3 = [0.13, 0.43, 0.2 + ZC];

const DECK_OF: Record<LampKind, DeckId> = { router: "D3", server: "D2", node: "D2", storage: "D1", ups: "D1", other: "D1", desktop: "DOCK" };
const SIZE: Record<LampKind, number> = { server: 0.125, node: 0.085, storage: 0.075, ups: 0.065, desktop: 0.13, router: 0.045, other: 0.07 };
const YAW: Record<LampKind, number> = { server: 0.25, node: -0.2, storage: 0.15, ups: -0.2, desktop: 0.5, router: 0.2, other: 0 };
/** Where a shell stands beside a machine, by deck. */
const BESIDE: Record<DeckId, V3> = { D3: [0.06, 0, 0.05], D2: [0.11, 0, 0.07], D1: [-0.1, 0, 0.05], DOCK: [0.1, 0, 0.04] };

export const SHELL_NAME: Record<Shell, string> = { owl: "RECON OWL", lineman: "RIG LINEMAN", noir: "NOIR", spark: "SPARK", hermit: "HERMIT", exo: "EXO" };
const SHELLS: Shell[] = ["owl", "lineman", "noir", "spark", "hermit", "exo"];

export interface Compartment {
  id: string;
  code: string;
  deck: DeckId;
  name: string;
  /** A machine, or one of the crew's places. */
  what: "machine" | "booth" | "quarters" | "berth";
  machine: LampMachine | null;
  /** Its place on the tray, or null when the deck is full (it is still in the list). */
  at: V3 | null;
  /** Where a shell stands when it works here. */
  foot: V3 | null;
  /** The hologram's model name, or null: then its kind icon stands on the tray. */
  model: string | null;
  size: number;
  yaw: number;
  state: LampState | "dim";
  word: string;
  reading: string;
  hint: string;
  /** The intent pressing it sends, or null. */
  route: string | null;
}

export interface PartView {
  id: PartId;
  name: string;
  /** "idle": this board has no reading for it. */
  state: LampState | "dim" | "idle";
  word: string;
  hint: string;
  route: string;
}

export interface CrewPlace {
  shell: Shell;
  /** A compartment id, or "mast". */
  where: string;
  /** Working there (a caption shows), or off duty in quarters. */
  duty: boolean;
  /** The painting's pose, when the manifest has more than one. */
  pose: "work" | "rest";
  caption: string;
  tone: "ok" | "warn" | "busy" | "dim";
  hint: string;
}

export interface Scene {
  quiet: boolean;
  compartments: Compartment[];
  parts: PartView[];
  crew: CrewPlace[];
  line: { words: string; tone: "ok" | "warn" | "low" | "q"; hint: string };
  sub: { words: string; hint: string };
  /** Interference while something needs you; the night side in quiet hours; no signal when unread. */
  weather: "clear" | "interference" | "night" | "nosignal";
  tubes: { online: number; alarms: number; clock: string };
  alarm: { words: string; route: string; hint: string; danger: boolean } | null;
  /** Steps of the mast's beam, of ten: one per goal reached; null when the host has no goals. */
  beam: number | null;
  brighter: boolean;
  /** The station part lit as the cause, by index, and its colour. */
  cause: { part: number; state: "warn" | "down" } | null;
}

const storageShaped = (n: LampNeed): boolean =>
  /^(drive|disk|volume|filesystem|pool|storage)$/.test(n.subject?.type ?? "") || n.go === "data";

/** The shell a need calls: LINEMAN fixes, SPARK recharges, EXO lifts (backups), OWL watches. */
function shellFor(n: LampNeed): Shell {
  const t = n.subject?.type ?? "";
  if (/^(ups|power|battery)$/.test(t)) return "spark";
  if (/^backup/.test(t) || n.go === "data/backups") return "exo";
  if (/^(network|device)$/.test(t) || n.go === "network") return "owl";
  return "lineman";
}

function clockOf(d: LamplightData): string {
  if (d.clock) return d.clock;
  if (d.at == null) return "--:--";
  const t = new Date(d.at);
  return `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
}

export function buildScene(d: LamplightData, assets: LamplightAssets): Scene {
  const quiet = !!d.quiet?.on;
  const mascot = d.mascot ?? "on";
  const needs = d.needs ?? [];
  const lost = d.status.state === "unknown";
  const dimIf = (s: LampState): LampState | "dim" => (quiet ? "dim" : s);

  // ---- the compartments: each machine on its deck, by kind (or where the host says)
  const compartments: Compartment[] = [];
  const used: Record<DeckId, number> = { D3: 0, D2: 0, D1: 0, DOCK: 0 };
  const count: Record<DeckId, number> = { D3: 0, D2: 0, D1: 0, DOCK: 0 };
  const code = (deck: DeckId): string => (deck === "DOCK" ? `DOCK·${++count.DOCK}` : `${deck}·${String.fromCharCode(65 + count[deck]++)}`);
  for (const m of d.machines) {
    const deck = m.deck ?? DECK_OF[m.kind] ?? "D1";
    const at = SLOTS[deck][used[deck]] ?? null;
    if (at) used[deck]++;
    const b = BESIDE[deck], first = at === SLOTS[deck][0];
    const mine = needs.filter((n) => n.machine === m.id);
    const hint = [
      `${m.name}, ${KIND_WORD[m.kind]}${m.here ? ", the machine this browser is on" : ""}: ${m.word}.`,
      m.role ? `${m.role}.` : "",
      m.reading ? `${m.reading}.` : "",
      ...mine.map((n) => `${n.words}${n.subject?.name ? ` (${n.subject.name})` : ""}${n.detail ? `: ${n.detail}` : ""}.`),
      m.state === "setup" ? "Just installed: nothing runs on it yet, and nothing is wrong." : "",
      m.page ? "Press to open its page." : "",
    ].filter(Boolean).join(" ");
    compartments.push({
      id: m.id, code: code(deck), deck, name: m.name.toUpperCase(), what: "machine", machine: m, at,
      foot: at ? [at[0] + (deck === "D1" && !first ? 0.04 : b[0]), at[1], at[2] + b[2]] : null,
      model: modelFor(assets, m.kind), size: SIZE[m.kind], yaw: YAW[m.kind],
      state: dimIf(lost ? "unknown" : m.state), word: m.word.toUpperCase(), reading: m.reading ?? m.role ?? "", hint,
      route: m.page === false ? null : `m/${m.id}`,
    });
  }

  // ---- the crew: a shell stands only where a real event needs it; the rest wait in quarters
  const crew: CrewPlace[] = [];
  const placed = new Set<Shell>();
  const place = (c: CrewPlace) => { if (!placed.has(c.shell)) { placed.add(c.shell); crew.push(c); } };
  const cmpOf = (id: string) => compartments.find((c) => c.id === id && c.at);
  if (mascot !== "off") {
    // OWL listens on the mast while all is well, and leans in to look while something needs you
    place({ shell: "owl", where: "mast", duty: true, pose: needs.length && !quiet && !lost ? "work" : "rest", caption: "OWL", tone: quiet ? "dim" : "ok",
      hint: quiet ? "RECON OWL still keeps the watch in quiet hours, in the dark. Real alerts keep their own channel; the crew stays silent." : "RECON OWL keeps the watch on the mast: the one post that is always crewed." });
    if (!quiet) {
      for (const n of needs) {
        const s = shellFor(n), c = cmpOf(n.machine);
        if (!c || s === "owl") continue;
        place({ shell: s, where: c.id, duty: true, pose: "work", tone: "warn",
          caption: `${SHELL_NAME[s].split(" ").pop()}${n.subject?.name ? ` · ${n.subject.name.toUpperCase()}` : ""}`,
          hint: `${SHELL_NAME[s]} is at ${c.name.toLowerCase()} because: ${n.words}${n.subject?.name ? ` (${n.subject.name})` : ""}. It stays until that is fixed.` });
      }
      for (const j of d.jobs ?? []) {
        if (!/^backup|\.backup|restore/.test(j.kind)) continue;
        const c = compartments.find((x) => x.machine?.kind === "storage" && x.at) ?? cmpOf(j.machine);
        if (c) place({ shell: "exo", where: c.id, duty: true, pose: "work", tone: "busy", caption: `EXO${j.pct != null ? ` · ${Math.round(j.pct)} %` : ""}`,
          hint: `EXO carries a copy into the hold: ${j.title}${j.pct != null ? `, ${Math.round(j.pct)} %` : ""}. It carries only while a backup runs.` });
      }
      if (d.show) place({ shell: "noir", where: "booth", duty: true, pose: "work", caption: "", tone: "ok", hint: "NOIR hosts tonight's roll-call from the booth." });
    }
    for (const s of SHELLS) place({ shell: s, where: "quarters", duty: false, pose: "rest", caption: "", tone: quiet ? "dim" : "ok", hint: `${SHELL_NAME[s]} waits in quarters: nothing real needs it now.` });
  }
  const offDuty = crew.filter((c) => c.where === "quarters");

  // ---- the crew's own places: the booth (with a show), quarters, the open berth
  if (d.show) {
    compartments.push({ id: "booth", code: code("D3"), deck: "D3", name: "BOOTH", what: "booth", machine: null, at: BOOTH, foot: BOOTH, model: null, size: 0, yaw: 0,
      state: quiet ? "dim" : d.plan ? "warn" : "ok", word: d.plan ? "PLAN DOCKED" : d.show.aired ? "AIRED" : "READY", reading: `roll-call · ${d.show.when}`,
      hint: `The booth: tonight's roll-call, ${d.show.when}.${d.plan ? " VECTOR's plan is docked beside it." : ""} Press to play it; it is never pushed.`, route: "show" });
  }
  if (offDuty.length) {
    compartments.push({ id: "quarters", code: code("D1"), deck: "D1", name: "QUARTERS", what: "quarters", machine: null, at: QUARTERS, foot: QUARTERS, model: null, size: 0, yaw: 0,
      state: quiet ? "dim" : "ok", word: quiet ? "LIGHTS LOW" : `${offDuty.length} OFF DUTY`,
      reading: quiet ? (d.quiet?.until ? `until ${d.quiet.until}` : "quiet hours") : offDuty.map((c) => SHELL_NAME[c.shell].split(" ").pop()).join(", "),
      hint: quiet ? "Quarters, lights low: the crew is asleep. Nothing moves and nothing is said." : "Quarters: the shells with no real job wait here. A bored crew is the sign of a healthy lab.", route: null });
  }
  if (d.joining) {
    const j = d.joining[0];
    compartments.push({ id: "berth", code: code("DOCK"), deck: "DOCK", name: j ? j.name.toUpperCase() : "OPEN BERTH", what: "berth", machine: null, at: BERTH, foot: null, model: null, size: 0, yaw: 0,
      state: quiet ? "dim" : j ? "busy" : "ok", word: j ? j.word.toUpperCase() : "EMPTY", reading: j ? "at the open berth" : "no one joining",
      hint: j ? `${j.name} is joining: it waits at the open berth until you approve it.` : "The open berth: a machine that uses a join code docks here until you approve it.", route: j ? "network" : null });
  }

  // ---- the station's parts, as BRODEC lights them
  const P = (id: PartId, name: string, route: string, hint: string): PartView => ({ id, name, state: "idle", word: "", hint, route });
  const parts: PartView[] = [
    P("mast", "MAST · NETWORK", "network", "The mast: the network."),
    P("dish", "DISH · AI", "supply", "The dish: the lab's AI and its models."),
    P("whips", "WHIPS · GAMES", "supply", "The whips: the game servers."),
    P("arrays", "ARRAYS · NODES", "network", "The arrays, both wings: the lab's machines as nodes."),
    P("rackroom", "RACK ROOM · SERVICES", "supply", "The rack room: services, and every alert that isn't about storage."),
    P("dock", "DOCK · MEDIA", "den", "The docking ring: media."),
    P("hull", "HULL · STORAGE", "data", "The hull: storage. A drive or volume alert lights it. Opens Data › Drives."),
  ];
  const part = (id: PartId) => parts.find((p) => p.id === id)!;
  if (d.machines.length) {
    const up = d.machines.filter((m) => m.state !== "down" && m.state !== "unknown").length;
    Object.assign(part("arrays"), { state: up === d.machines.length ? "ok" : "warn", word: `${up} OF ${d.machines.length}` });
  }
  let cause: Scene["cause"] = null;
  for (const n of needs) {
    const p = part(storageShaped(n) ? "hull" : "rackroom"), st = n.severity === "danger" ? "down" : "warn";
    if (p.state !== "down") Object.assign(p, { state: st, word: st === "down" ? "DOWN" : "NEEDS A LOOK" });
    p.hint += ` Lit because: ${n.words}${n.subject?.name ? ` (${n.subject.name})` : ""}.`;
    p.route = n.go ?? p.route;
    if (!cause || st === "down") cause = { part: STATION_PART[p.id === "hull" ? "hull" : "rackroom"], state: st };
  }
  for (const [id, v] of Object.entries(d.parts ?? {})) if (v) Object.assign(part(id as PartId), v);
  for (const p of parts) {
    if (p.state === "idle") p.hint += " This board has no reading for it yet.";
    else if (quiet || lost) p.state = "dim";
  }

  // ---- the one line, the readouts, the alarm
  const n = needs.length, clock = clockOf(d);
  const reached = d.goals ? d.goals.list.filter((g) => g.state === "done").length : null;
  const brighter = !!d.goals?.list.some((g) => g.fresh && g.state === "done") && !quiet && !n;
  let line: Scene["line"], weather: Scene["weather"] = "clear";
  if (lost) { line = { words: "NO SIGNAL", tone: "q", hint: "The board's last reading is older than it should be: what the station shows may be out of date." }; weather = "nosignal"; }
  else if (quiet) { line = { words: "LOW · QUIET HOURS", tone: "low", hint: "Quiet hours: the station holds its night side to you, lights low. Real alerts keep their own channel." }; weather = "night"; }
  else if (n) { line = { words: `LIT · ${n === 1 ? "ONE THING NEEDS" : `${n} THINGS NEED`} YOU`, tone: "warn", hint: "The post's one line: the worst state wins. Lit with something needing you is still lit: nothing is lost." }; weather = "interference"; }
  else if (d.status.state === "setup") line = { words: "LIT · NOTHING INSTALLED YET", tone: "ok", hint: "The post is lit and nothing is installed on it yet. Nothing is wrong." };
  else line = { words: brighter ? "STILL LIT · BRIGHTER" : "STILL LIT", tone: "ok", hint: "The post's one line: every machine answers and nothing needs you." };
  // the host's own status line says it instead, in the host's words; the weather stays the scene's
  if (d.headline) line = { words: d.headline.words, tone: d.headline.tone, hint: d.headline.hint ?? line.hint };
  const first = needs[0], firstCmp = first ? compartments.find((c) => c.id === first.machine) : null;
  const alarm: Scene["alarm"] = first && !quiet && !lost ? {
    words: `${storageShaped(first) ? "HULL ALARM" : "ALARM"} · ${firstCmp ? `${firstCmp.code} ${firstCmp.name}` : first.machine.toUpperCase()} · ${first.words.toUpperCase()}${first.subject?.name ? ` · ${first.subject.name.toUpperCase()}` : ""}`,
    route: first.go ?? `m/${first.machine}`, danger: first.severity === "danger",
    hint: `The alarm: ${first.words}${first.detail ? `: ${first.detail}` : ""}. It flashes three times when it starts, then stays lit until it is dealt with.`,
  } : null;
  return {
    quiet, compartments, parts, crew, line, weather, alarm, beam: reached, brighter, cause: quiet || lost ? null : cause,
    sub: { words: [clock, d.age?.toUpperCase(), d.headline ? null : d.status.words].filter(Boolean).join(" · "), hint: weather === "interference" ? "Interference runs across the station while something needs you. It clears when that is fixed. Never a flash, never a sound: the alert keeps its own channel." : "When the board was last read, and its own words." },
    tubes: { online: d.machines.filter((m) => !lost && m.state !== "down" && m.state !== "unknown").length, alarms: n, clock },
  };
}

/**
 * What a poll that found nothing new still changes: when it was read, how long ago, and the words
 * said about it. Two readings with the same key differ only in the head and the readouts.
 */
export const dataKey = (d: LamplightData): string =>
  JSON.stringify({ ...d, at: null, clock: null, age: null, headline: null, status: { state: d.status.state } });

/** The key that says whether the holograms in the scene changed (not just their states). */
export const sceneKey = (s: Scene): string => s.compartments.filter((c) => c.model && c.at).map((c) => `${c.id}:${c.model}:${c.at}`).join("|");
