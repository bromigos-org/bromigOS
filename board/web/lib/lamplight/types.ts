// Lamplight's contract: what the host hands the station, and what it gets back.
//
// The station is drawn only from `LamplightData`. Nothing in the module is example data: the Lab
// board builds its data from the board's own document with fromBoard() (from-board.ts), and a
// design page's example labs are data of its own. Every optional layer is simply not drawn when it is
// absent: with machines and what needs you alone, the station, its decks, its readouts and its
// alarm are complete.

import type { ModelInfo } from "../holo/view";

/** A machine's state, as its shape and colour: the board's four, plus set-up and busy. */
export type LampState = "ok" | "warn" | "down" | "unknown" | "setup" | "busy";

/** What kind of machine: decides its deck and its hologram (or its icon, with no model). */
export type LampKind = "server" | "storage" | "node" | "desktop" | "router" | "ups" | "other";

/** The station's decks, top to bottom, and the docking ring. */
export type DeckId = "D3" | "D2" | "D1" | "DOCK";

/** The station's own parts, with the meanings BRODEC's LAB gives them (lab_hero.dart). */
export type PartId = "mast" | "dish" | "whips" | "arrays" | "rackroom" | "dock" | "hull";

/** STATIC's shells that crew the station. */
export type Shell = "owl" | "lineman" | "noir" | "spark" | "hermit" | "exo";

export interface LampMachine {
  /** The machine's name on the lab (the board's `machines[].name`): the id every intent carries. */
  id: string;
  name: string;
  kind: LampKind;
  /** Its one role line, in plain words: "Home services · Media". */
  role: string;
  state: LampState;
  /** The word beside its shape: "online", "needs you", "set up", "not seen for 2 h". */
  word: string;
  /** One short reading under its name: "10 apps", "nothing installed yet". Never made up. */
  reading?: string | null;
  /** The machine this browser is on. */
  here?: boolean;
  /** It has a page of its own to open (the board's `machines[].page`). */
  page?: boolean;
  /** The part of its hologram that is the cause, by the model's part id ("storage" on the rack). */
  cause?: string | null;
  /** Where it rides, when the host knows; otherwise its kind decides. */
  deck?: DeckId;
}

export interface LampNeed {
  id: string;
  /** The machine it is about (a `LampMachine.id`). */
  machine: string;
  /** The alert's own words: "A drive is getting worse". */
  words: string;
  detail?: string | null;
  severity: "warn" | "danger";
  /** What it is about: decides the station part that lights and the shell that goes there. */
  subject?: { type: string; name: string } | null;
  /** The place that owns the fact, in the board's words: "data", "data/backups", "supply/updates". */
  go?: string | null;
  /** An activity job waiting for an answer. */
  job?: string | null;
  since?: number | null;
}

/** A job running now that the crew should show: a backup puts EXO in the hold. */
export interface LampJob {
  id: string;
  machine: string;
  kind: string;
  title: string;
  pct?: number | null;
}

export interface LampPlan {
  title: string;
  steps: { words: string; detail?: string; hint?: string }[];
  /** Where it came from: "From the alert disk.smart:sdb". */
  from?: string;
  /** The choices offered. Each is an intent; none is run by the module. */
  can: ("approve" | "change" | "no")[];
}

export interface LampLogEntry {
  /** The time as it should read in the tubes: "03:12" or "11-02". */
  at: string;
  title: string;
  detail: string;
  /** An arc (an incident with nights), a copy, or another event. */
  kind: "arc" | "copy" | "event" | "goal";
  /** open: an arc still forming; fresh: happened just now. */
  mark?: "open" | "fresh" | null;
}

export interface LampSky {
  /** Ended and open arcs, as constellations named by their outcome. */
  arcs: { name: string; hint: string; stars: number; open?: boolean; fresh?: boolean }[];
  /** Goals reached, as named stars. */
  goals: { name: string; hint: string }[];
  /** The backups, as loose stars until a restore proves them. */
  copies?: { proven: boolean; fresh?: boolean; hint: string } | null;
}

export interface LampGoals {
  rank?: { title: string; xp: number; from: number; to: number; next: string; gained?: number } | null;
  list: { state: "done" | "progress" | "todo"; title: string; detail: string; xp: number; cap: string; fresh?: boolean }[];
}

export interface LampCard {
  kind?: "open" | "bump" | "card";
  over: string;
  title: string;
  detail?: string;
  /** VECTOR's line, on the sign-off. */
  vector?: string;
  /** Art by its manifest name: "loop/host", "bump/right-back", "crew/exo". Text alone without it. */
  art?: string;
  hint: string;
}

export interface LampShow {
  /** "composed 20:30", "aired 20:30 · watched". */
  when: string;
  aired?: boolean;
  cards: LampCard[];
  /** The open arc the show follows, night by night. */
  thread?: { title: string; night: string; steps: { when: string; date?: string; title: string; detail: string; next?: boolean }[] } | null;
}

export interface LampFriend {
  id: string;
  name: string;
  lit: boolean;
  decks: number;
  stars: number;
  last: string;
}

export interface LampHub {
  name: string;
  line: string;
  members: { id: string; name: string; state: "lit" | "out" | "new"; you?: boolean; hint: string }[];
  docks: { name: string; lit?: boolean; hint: string }[];
  /** A field op in progress: a ship out and back. */
  op?: { words: string; hint: string } | null;
  /** A favour between two members (planned): a beam through the hub. */
  favour?: { words: string; hint: string } | null;
  sector?: { name: string; here?: boolean; hint: string }[];
}

export interface LampExchange {
  /** STATIC's screen: happy, smug, startled, suspicious, glum, listening. */
  mood: string;
  thought: string;
  vector: string;
  /** The real event that caused it. */
  why: string;
}

export interface LamplightData {
  lab: { name: string; address?: string | null };
  /** When this was read (ms since the epoch); the bridge clock shows it in local time. */
  at?: number | null;
  /** The bridge clock as text, when the host would rather say it ("20:41"). */
  clock?: string | null;
  /** How long ago that was, in the host's words ("just now", "5 min ago"): said after the clock. */
  age?: string | null;
  /** The board's own status: its state and its words. "unknown": the reading is too old to trust. */
  status: { state: "ok" | "needs-you" | "setup" | "unknown"; words: string };
  /**
   * The host's own status line, when it has one ("ALL MACHINES NOMINAL", "1 MACHINE NEEDS YOU",
   * "NOT READ FOR 5 MIN"): it is shown as the station's one line, in place of the line the
   * module derives, so the page says one thing in one voice.
   */
  headline?: { words: string; tone: "ok" | "warn" | "q"; hint?: string } | null;
  machines: LampMachine[];
  needs: LampNeed[];
  jobs?: LampJob[];
  /** VECTOR's plan for what needs you, docked to the station. */
  plan?: LampPlan | null;
  /** Quiet hours: the night side, lights low, nobody speaks. */
  quiet?: { on: boolean; until?: string | null } | null;
  /** Settings › Mascot. */
  mascot?: "on" | "quiet" | "off";
  /** A part's own reading, when the host has one; otherwise what needs you lights the parts. */
  parts?: Partial<Record<PartId, { state: LampState; word: string }>>;
  /** A machine joining: a ghost at the open berth until it is approved. */
  joining?: { name: string; word: string }[];
  exchange?: LampExchange | null;
  // ---- the optional layers: each is not drawn when absent
  sky?: LampSky | null;
  log?: LampLogEntry[] | null;
  goals?: LampGoals | null;
  show?: LampShow | null;
  friends?: LampFriend[] | null;
  hub?: LampHub | null;
}

// ---------------------------------------------------------------- the assets manifest

/** One hologram: the light mesh the station draws, and the full one for a close-up. */
export interface ModelEntry {
  src: string;
  info: ModelInfo;
  full?: { src: string; info: ModelInfo };
}

/**
 * What may be drawn. A machine kind with no model here is drawn as its icon on its deck tray,
 * and art that isn't named here is never asked for. When a new mesh or painting is cleared it is
 * added here and nothing else changes.
 */
export interface LamplightAssets {
  /** Put before every relative `src`. */
  base?: string;
  /** By model name: "wick-cut" (the station), "wick" (the hub's stations), "rack", "workstation", … */
  models: Record<string, ModelEntry>;
  /** Which model a machine kind uses. */
  kinds: Partial<Record<LampKind, string>>;
  /** Paintings and clips by name: "crew/lineman", "still/whack", "loop/host", "bump/crew", "poster/crew". */
  art?: Record<string, string>;
}

// ---------------------------------------------------------------- what the host passes and gets

/** Where an intent wants to go, in the board's own route words (no leading #). */
export type LampRoute = string;

export interface LamplightOptions {
  data: LamplightData;
  assets: LamplightAssets;
  /** Hold everything still (the host's own switch; the browser's setting is honoured as well). */
  reduced?: boolean;
  /** A world's name sets the tokens on the module's root; leave it out to use the host's. */
  world?: string | null;
  /** Which panel is open under the station, when there are any. */
  tab?: string;
  /** What to draw under the station: every layer that has data ("auto"), or nothing. */
  under?: "auto" | "none";
  /** Every intent: `m/<machine>`, `data`, `ask`, `activity`, `network`, `supply`, `den`, `people`, `home`. */
  onNavigate?: (route: LampRoute, detail: Record<string, unknown>) => void;
  /** Anything that went wrong drawing (no WebGL, a model that didn't load). The words still show. */
  onError?: (error: unknown) => void;
  /** The station is drawn. */
  onReady?: () => void;
}

export interface LamplightHandle {
  /**
   * New data: re-renders in place, with no remount and no model reloaded. When only the reading's
   * time or the status words changed (a poll that found nothing new), only the head and the
   * readouts are rewritten: the scene, the crew and the turn are left as they are.
   */
  update(data: LamplightData): void;
  setReduced(on: boolean): void;
  setWorld(world: string | null): void;
  setTab(tab: string): void;
  /** The host's tokens changed (its world): recolour once. */
  refresh(): void;
  unmount(): void;
}

export interface MachineOptions {
  /** The machine to show: one of `data.machines`. */
  machine: string;
  data: LamplightData;
  assets: LamplightAssets;
  reduced?: boolean;
  world?: string | null;
  onNavigate?: LamplightOptions["onNavigate"];
  onError?: LamplightOptions["onError"];
  onReady?: () => void;
}

export interface MachineHandle {
  update(data: LamplightData, machine?: string): void;
  setReduced(on: boolean): void;
  setWorld(world: string | null): void;
  refresh(): void;
  unmount(): void;
}

export interface RackOptions {
  kind: LampKind;
  state?: LampState;
  assets: LamplightAssets;
  /** The side it shows, in degrees (the old sprite's angle), and whether it turns for a while. */
  angle?: number;
  turn?: boolean;
  /** Light one part, by the model's part id. */
  cause?: string | null;
  /** The full mesh, for a large mount. */
  full?: boolean;
  reduced?: boolean;
  world?: string | null;
  label?: string;
  onError?: LamplightOptions["onError"];
  onReady?: () => void;
}

export interface RackHandle {
  update(patch: { state?: LampState; cause?: string | null; angle?: number }): void;
  setReduced(on: boolean): void;
  setWorld(world: string | null): void;
  refresh(): void;
  unmount(): void;
}
