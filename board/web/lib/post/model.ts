// The post's state, with no page in it: which job is drawn where, which crew member has it,
// where everyone is on the floor, and what each room and machine is doing. The page (post.ts)
// only draws this; the tests run it without a browser.
//
// It is moved by two things only: set(), with the job records as the page has them now, and
// step(), with the time that passed. Nothing here invents a job, a share done or a finish.
import { type Machine, type Room, type Stops, type Walk, chart, head, offPath, pad, place, rooms, stopId, walk } from "./floor";
import { type Act, type Mode, type PlaceId, drawn, ending, placeFor, placeRule } from "./places";
import type { PostData, PostJob, PostMap, Pt } from "./types";

/**
 * The crew: STATIC's shells that work the post. Each loop was painted facing one way: -1 faces
 * screen-left, 1 faces screen-right. A loop is mirrored whenever the walk needs the other way,
 * so everyone faces where they are going. `tall` is a share of the stage's height.
 */
export const CREW = [
  { id: "lineman", name: "LINEMAN", tall: 0.0505, side: { to: -1, away: 1, work: 1 } },
  { id: "owl", name: "OWL", tall: 0.042, side: { to: -1, away: 1, work: -1 } },
  { id: "exo", name: "EXO", tall: 0.063, side: { to: -1, away: 1, work: 1 } },
] as const;

/** Stage pixels a second. */
export const SPEED = 135;
/**
 * How long the shuttle takes to come down or leave, how long it waits on the pad after the last
 * job there, and how close to the pad (in seconds) its legs and ramp are out: it flies with them
 * folded away, unfolds them as it settles, and folds them again as it lifts off.
 */
const FLIGHT = 3.4, LINGER = 1.6;
export const LEGS = 1.3;
/**
 * Work on the pad is carried: crates go one at a time from the foot of the shuttle's ramp to a
 * stack on the pad. How many crates the stack shows, how long reaching into the ship or bending
 * to the stack takes, and how fast someone walks with a crate and back without one.
 */
export const CRATES = 3;
const HANDLE = 0.8, LOADED = 0.55, EMPTY = 0.8;
/** How long a finish shows: the room's clip, a machine's finished loop, and the flash. */
export const SHOWS = { room: 3, machine: 2.2, flash: 1.3 };

export type Loop = "to" | "away" | "idle" | Act;

export interface Figure extends Walk {
  i: number;
  id: string;
  name: string;
  tall: number;
  side: { to: number; away: number; work: number };
  /** Where they rest. */
  home: string;
  /** idle: resting; walk: on the way; work: at a running job; wait: standing at a job that asks. */
  state: "idle" | "walk" | "work" | "wait";
  /** The job they were given. */
  job: string | null;
  /** The loop they are seen in now, and whether it is mirrored. */
  look: Loop;
  flip: boolean;
  /** A crate in their arms: 0 none, else the side it is held to (-1 screen-left, 1 screen-right). */
  carry: -1 | 0 | 1;
  /**
   * The trip in hand on the pad: reaching into the shuttle, carrying a crate to the stack, bending
   * to set it down, walking back. `last`: the job ended or asks, so this trip is finished and
   * no other is begun.
   */
  haul: { step: "reach" | "carry" | "bend" | "back"; t: number; did: boolean; last: boolean } | null;
}

/** A job on the picture. */
export interface Live {
  job: PostJob;
  mode: Mode;
  place: PlaceId;
  act: Act;
  /** The crew member it was given: kept for as long as it is drawn. null: all three were busy. */
  who: number | null;
  /** Where that crew member stands for it. */
  stop: string | null;
  face: 1 | -1;
}

/** A place on the station: its room and machine (the pad has neither), and where someone can stand for it. */
export interface Spot {
  place: PlaceId;
  room: Room | null;
  machine: Machine | null;
  /** The stops to stand at, the place's own first; a second and a third job there stand at the next. */
  stops: string[];
  face: 1 | -1;
  /** Where a finish there is shown. */
  at: Pt;
}

/** Something that just happened, for the page to show once: a job ended, or the shuttle set down. */
export interface News { what: "ok" | "fail" | "land"; place: PlaceId; at: Pt }

export class Model {
  readonly rooms: Room[];
  readonly stops: Stops;
  readonly spots: Record<PlaceId, Spot>;
  readonly crew: Figure[];
  readonly live = new Map<string, Live>();
  /**
   * The shuttle. `far`: 0 on the pad, 1 far off. `look`: parked on its legs, flying with them
   * folded away, or folding them; `folded` is then how far, 0 (down) to 1 (away).
   */
  readonly ship: { state: "away" | "in" | "landed" | "out"; t: number; wait: number; at: Pt; home: Pt; far: number; look: "idle" | "fly" | "fold"; folded: number };
  /** The model's own clock, in seconds: it runs only while step() is called. */
  clock = 0;
  known = false;
  /** What to show once; the page takes these. */
  news: News[] = [];
  /** How many crates lie stacked on the pad: the ones carried there while the shuttle is down. */
  stack = 0;
  private ends: { how: "ok" | "fail"; place: PlaceId; t: number }[] = [];
  private fresh = true;

  constructor(readonly map: PostMap) {
    this.rooms = rooms(map);
    this.stops = chart(map, this.rooms);
    const P = pad(map), spots = {} as Record<PlaceId, Spot>;
    // the pad: the foot of the shuttle's ramp, facing the ship; a second and a third job there stand by on the pad
    spots.pad = { place: "pad", room: null, machine: null, stops: [stopId.pad, ...P.rest.map((_, n) => stopId.padRest(n))], face: 1, at: P.spot };
    for (const R of this.rooms)
      for (const m of R.machines) {
        const id = m.kind as PlaceId;
        if (spots[id]) continue;
        spots[id] = { place: id, room: R, machine: m, stops: [stopId.machine(R.id, m.n), stopId.spot(R.id), stopId.inside(R.id)], face: R.flip ? 1 : -1, at: m.stand };
      }
    this.spots = spots;
    // the crew rest in the first quarters there is, or out on the pad
    const q = this.rooms.find((R) => R.rest.length);
    this.crew = CREW.map((c, i): Figure => {
      const home = q ? stopId.rest(q.id, i % q.rest.length) : stopId.padRest(i % P.rest.length);
      return { ...c, i, home, pos: [...this.stops.get(home)!.p] as Pt, stop: home, path: [], state: "idle", job: null, look: "idle", flip: false, carry: 0, haul: null };
    });
    this.ship = { state: "away", t: 0, wait: 0, at: [...P.ship] as Pt, home: P.ship, far: 1, look: "fly", folded: 1 };
  }

  /** Where the crew rest, in words: the quarters' own name, or the pad. */
  get restName(): string {
    return this.rooms.find((R) => R.rest.length)?.name.toLowerCase() ?? "landing pad";
  }

  // ---------------------------------------------------------------- the jobs, as the page has them now

  /**
   * The job records as they are now. A job that newly runs or asks is given a place and, when one
   * is free, a crew member; one that ended is let go, and how it ended is shown once. `still`:
   * nobody walks and nothing is shown once, everyone simply stands where they belong (reduced
   * motion). The first reading is taken the same way: nothing that happened before the page was
   * open is replayed.
   */
  set(data: PostData, still = false): void {
    if (!data.known) {
      this.live.clear(); this.ends = []; this.news = []; this.known = false; this.fresh = true;
      for (const c of this.crew) { c.job = null; this.rest(c); }
      this.ship.state = "away"; this.stack = 0;
      return;
    }
    const instant = still || this.fresh;
    this.known = true; this.fresh = false;
    const byId = new Map(data.jobs.map((j) => [j.id, j]));
    const want = new Map<string, { job: PostJob; mode: Mode }>();
    for (const job of data.jobs) { const mode = drawn(job, (id) => byId.has(id)); if (mode && !want.has(job.id)) want.set(job.id, { job, mode }); }

    // the ones that left the picture: how each ended, shown once, and its crew member is free
    for (const [id, L] of this.live) {
      if (want.has(id)) continue;
      this.live.delete(id);
      const now = byId.get(id), how = now ? ending(now) : null;
      if (how && !instant) {
        const c = L.who !== null ? this.crew[L.who] : null;
        this.ends.push({ how, place: L.place, t: this.clock });
        this.news.push({ what: how, place: L.place, at: c && c.state !== "walk" ? [...c.pos] as Pt : this.spots[L.place].at });
      }
      if (L.who !== null) this.crew[L.who].job = null;
    }
    // the ones that stay, and the new ones: each at its place
    for (const [id, w] of want) {
      const L = this.live.get(id);
      if (L) { L.job = w.job; L.mode = w.mode; continue; }
      const rule = placeFor(w.job), spot = this.spots[rule.place] ?? this.spots.pad;
      this.live.set(id, { job: w.job, mode: w.mode, place: spot.place, act: placeRule(spot.place).act, who: null, stop: null, face: spot.face });
    }
    this.dispatch(instant);
    if (instant) { this.ends = []; this.news = []; this.stack = 0; this.ship.state = this.wanted ? "landed" : "away"; this.ship.wait = 0; this.fly(); }
  }

  /**
   * Who has which job, and where each goes. A job with nobody gets the next free crew member,
   * the ones at rest first. Someone with a crate in their arms is not free, and is not sent
   * anywhere, until it is set down.
   */
  private dispatch(instant: boolean): void {
    if (instant) for (const c of this.crew) { c.haul = null; c.carry = 0; }
    for (const L of this.byId()) {
      if (L.who !== null) continue;
      const free = (x: Figure) => !x.job && !x.haul;
      const c = this.crew.find((x) => free(x) && x.state === "idle") ?? this.crew.find(free);
      if (!c) break;
      const taken = new Set([...this.live.values()].map((x) => x.stop));
      L.who = c.i; L.stop = this.spots[L.place].stops.find((s) => !taken.has(s)) ?? this.spots[L.place].stops[0];
      c.job = L.job.id;
    }
    for (const c of this.crew) {
      const L = c.job ? this.live.get(c.job) : undefined;
      if (c.haul) {
        // carrying on the pad: on with it while its job runs; otherwise this trip is the last
        if (!(L && L.mode === "run" && this.hauls(L))) c.haul.last = true;
        continue;
      }
      if (L?.stop) {
        if (instant) { place(this.stops, c, L.stop); this.stand(c, L); }
        else if (c.stop === L.stop && !c.path.length) this.stand(c, L);
        else { head(this.stops, c, L.stop); c.state = "walk"; }
      } else if (instant) this.rest(c);
      else if (c.stop !== c.home || c.path.length) { head(this.stops, c, c.home); c.state = "walk"; }
      else this.rest(c);
    }
  }

  private byId(): Live[] { return [...this.live.values()].sort((a, b) => (a.job.id < b.job.id ? -1 : a.job.id > b.job.id ? 1 : 0)); }

  private rest(c: Figure): void { place(this.stops, c, c.home); c.state = "idle"; c.look = "idle"; c.flip = false; c.carry = 0; c.haul = null; }

  /** The job whose crew member carries the crates: the one standing at the foot of the shuttle's ramp. */
  private hauls(L: Live): boolean { return L.place === "pad" && L.stop === stopId.pad; }

  /**
   * Standing at a job: at work in the place's own loop, facing the thing worked on, or waiting in
   * the plain standing one. On the pad the work is carried (haul); standing there, the worker
   * reaches into the shuttle with their back to us. A second job at the pad has its crew member
   * stand by: one carries at a time.
   */
  private stand(c: Figure, L: Live): void {
    c.carry = 0;
    if (L.mode !== "run") { c.state = "wait"; c.look = "idle"; c.flip = false; return; }
    c.state = "work";
    if (L.place !== "pad") { c.look = L.act; c.flip = L.face !== c.side.work; }
    else if (this.hauls(L)) { c.look = "work"; c.flip = L.face !== c.side.work; }
    else { c.look = "idle"; c.flip = false; }
  }

  /**
   * One step of the carrying, while the shuttle is down: reach into the ship, walk to the stack
   * with a crate, bend to set it down, walk back, and again for as long as the job runs. The
   * record says how far the job is, never this routine. When the job ends, the trip in hand is
   * finished (a crate in the arms is set down) and no other is begun.
   */
  private carryOn(c: Figure, dt: number): void {
    const h = (c.haul ??= { step: "reach", t: 0, did: false, last: false });
    if (h.step === "reach") {
      if (h.last) return this.setDown(c);
      if ((h.t += dt) >= HANDLE) { h.step = "carry"; h.t = 0; }
    } else if (h.step === "carry" || h.step === "back") {
      const loaded = h.step === "carry";
      if (!loaded && h.last) return this.setDown(c);
      if (!c.path.length) c.path = [loaded ? stopId.padStack : stopId.pad];
      walk(this.stops, c, SPEED * (loaded ? LOADED : EMPTY) * dt);
      if (!c.path.length) { h.step = loaded ? "bend" : "reach"; h.t = 0; h.did = false; }
    } else {
      h.t += dt;
      if (!h.did && h.t >= HANDLE / 2) { h.did = true; this.stack = Math.min(CRATES, this.stack + 1); }
      if (h.t >= HANDLE) { if (h.last) return this.setDown(c); h.step = "back"; h.t = 0; }
    }
    // how each part of a trip looks: back to us at the hatch; walking, with the crate held to the
    // side walked toward; bent at the stack, the crate in the arms until it is set down
    if (h.step === "reach") { c.look = "work"; c.flip = this.spots.pad.face !== c.side.work; c.carry = 0; }
    else if (h.step === "bend") { c.look = "lift"; c.flip = false; c.carry = h.did ? 0 : -1; }
    else {
      const to = this.stops.get(h.step === "carry" ? stopId.padStack : stopId.pad)!.p, dir = to[0] >= c.pos[0] ? 1 : -1;
      c.look = "to"; c.flip = dir !== c.side.to; c.carry = h.step === "carry" ? dir : 0;
    }
  }

  /** The last trip is done: the crew member is free again, for the job they still have, another, or home. */
  private setDown(c: Figure): void {
    c.haul = null; c.carry = 0;
    this.dispatch(false);
  }

  // ---------------------------------------------------------------- time

  step(dt: number): void {
    this.clock += dt;
    for (const c of this.crew) {
      if (c.state === "work") {
        // on the pad there is nothing to carry until the shuttle is down
        const L = c.job ? this.live.get(c.job) : undefined;
        if (c.haul || (L && L.mode === "run" && this.hauls(L) && !c.path.length)) {
          if (c.haul || this.ship.state === "landed") this.carryOn(c, dt);
          else { c.look = "idle"; c.flip = false; }
        }
        continue;
      }
      if (c.state !== "walk") continue;
      const moved = walk(this.stops, c, SPEED * dt);
      // down the screen is toward us (the front loop), up is away (the back loop); left or right picks the mirror
      if (moved) { const kind = moved[1] > 0 ? "to" : "away"; c.look = kind; c.flip = (moved[0] >= 0 ? 1 : -1) !== c.side[kind]; }
      if (c.path.length) continue;
      const L = c.job ? this.live.get(c.job) : undefined;
      if (L) this.stand(c, L);
      else { c.state = "idle"; c.look = "idle"; c.flip = false; }
    }
    this.shuttle(dt);
    this.ends = this.ends.filter((e) => this.clock - e.t < SHOWS.room);
  }

  /** A job at the pad calls the shuttle in; it sets down, waits while there is one (and while a last crate is carried), and leaves. */
  private get wanted(): boolean {
    for (const L of this.live.values()) if (L.place === "pad") return true;
    return this.crew.some((c) => c.haul);
  }

  private shuttle(dt: number): void {
    const s = this.ship, wanted = this.wanted;
    if (s.state === "away" && wanted) { s.state = "in"; s.t = 0; }
    else if (s.state === "in") { s.t += dt; if (s.t >= FLIGHT) { s.state = "landed"; s.wait = 0; this.news.push({ what: "land", place: "pad", at: [s.home[0], s.home[1] + 30] }); } }
    else if (s.state === "landed") { s.wait = wanted ? 0 : s.wait + dt; if (s.wait > LINGER) { s.state = "out"; s.t = 0; } }
    else if (s.state === "out") { s.t += dt; if (wanted && s.t < FLIGHT * 0.3) { s.state = "in"; s.t = FLIGHT - s.t; } else if (s.t >= FLIGHT) { s.state = "away"; this.stack = 0; } }
    this.fly();
  }

  /** Where the shuttle is, and what it shows. It comes in fast and settles slowly, and leaves the other way round. */
  private fly(): void {
    const s = this.ship;
    // seconds off the pad, either way
    const up = s.state === "landed" ? 0 : s.state === "in" ? FLIGHT - s.t : s.state === "out" ? s.t : FLIGHT;
    s.far = Math.pow(Math.max(0, Math.min(1, up / FLIGHT)), 2.4);
    s.look = s.state === "landed" ? "idle" : up < LEGS ? "fold" : "fly";
    s.folded = s.state === "landed" ? 0 : Math.max(0, Math.min(1, up / LEGS));
    s.at = [s.home[0] + 330 * s.far, s.home[1] - 900 * s.far + (s.far > 0 ? Math.sin(this.clock * 5) * 2 : 0)];
  }

  // ---------------------------------------------------------------- what the page draws

  /** The jobs at a place, oldest id first. */
  at(place: PlaceId): Live[] { return this.byId().filter((L) => L.place === place); }
  /** The jobs in a room, across its machines. */
  inRoom(R: Room): Live[] { return this.byId().filter((L) => this.spots[L.place].room === R); }

  private ended(how: "ok" | "fail", within: number, on: (place: PlaceId) => boolean): boolean {
    return this.ends.some((e) => e.how === how && this.clock - e.t < within && on(e.place));
  }

  /** A room's clip: the finish, for a moment after a job there ended well; busy while one runs; else quiet. */
  roomLook(R: Room): "done" | "work" | "idle" {
    const mine = (p: PlaceId) => this.spots[p].room === R;
    if (this.ended("ok", SHOWS.room, mine)) return "done";
    return [...this.live.values()].some((L) => L.mode === "run" && mine(L.place)) ? "work" : "idle";
  }

  /** A machine's loop: running while a job runs at it, finished for a moment after one ended well. */
  machineLook(place: PlaceId): "run" | "done" | "idle" {
    if ([...this.live.values()].some((L) => L.mode === "run" && L.place === place)) return "run";
    return this.ended("ok", SHOWS.machine, (p) => p === place) ? "done" : "idle";
  }

  /** A room's (or, with null, the pad's) flash: a job there just ended well, or badly. */
  flash(R: Room | null, how: "ok" | "fail"): boolean {
    return this.ended(how, SHOWS.flash, (p) => this.spots[p].room === R);
  }

  /** A job that asks with nobody free to stand there: its place is marked instead. */
  asksAlone(place: PlaceId): boolean {
    return [...this.live.values()].some((L) => L.place === place && L.mode === "ask" && L.who === null);
  }

  get shuttleWanted(): boolean { return this.wanted; }

  /**
   * How a job is on the picture: a crew member has it, its room is lit (it runs, and all three
   * crew were busy), its place is marked (it asks, likewise), or it isn't drawn.
   */
  shows(id: string): "figure" | "room" | "mark" | null {
    const L = this.live.get(id);
    return !L ? null : L.who !== null ? "figure" : L.mode === "run" ? "room" : "mark";
  }

  /** How far the worst-placed crew member is from the floor (0: everyone is on a path). */
  off(): number { return Math.max(...this.crew.map((c) => offPath(this.stops, c.pos))); }
}
