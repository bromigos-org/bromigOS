// The station's floor: where each room module sits, and where the crew can walk.
//
// A room is a painting on its own grid. Docking it is placing that grid on the station's: on the
// corridor it was not painted for, the room is the same picture mirrored, with its two floor
// axes swapped. Everything here is plain geometry on `PostMap` (post.json), with no page in it,
// so the tests walk it without a browser.
//
// Every spot someone can stand is a stop, and stops are joined only where there is floor between
// them: along each corridor, through a room's doorway to the middle of its floor, and from there
// to its work spots. A walk is always the shortest chain of stops, so nobody crosses a wall or
// open space, wherever they set off from.
import type { Dock, PostMap, Pt, RoomType } from "./types";

/** A room painting's own canvas, and where its grid's origin was when it was painted. */
const PAINT: Pt = [1472, 1104], PAINT_O: Pt = [700, 300];

export interface Machine {
  kind: string;
  /** Which of the room's anchors it stands on. */
  n: number;
  /** Its foot on the stage, and where someone stands to work it. */
  at: Pt;
  stand: Pt;
  /** Its height, as a share of the stage's. */
  tall: number;
}

export interface Room {
  id: string;
  on: Dock["on"];
  type: string;
  T: RoomType;
  name: string;
  /** Mirrored: docked on the corridor it was not painted for. */
  flip: boolean;
  /** Far rooms first: the sum of its near corner's grid position. */
  depth: number;
  /** Its footprint on the station's grid: x, y, w, h. */
  box: [number, number, number, number];
  /** Its painting on the stage, in stage pixels: x, y, w, h. */
  rect: [number, number, number, number];
  /** Its place in the one depth order (set by `rooms`). */
  z: number;
  /** The corridor at its doorway, the doorway, the middle of its floor, and its own work spot. */
  corr: Pt;
  door: Pt;
  inside: Pt;
  spot: Pt;
  face: 1 | -1;
  rest: Pt[];
  machines: Machine[];
  /** Its floor's four corners on the stage. */
  poly: Pt[];
}

/** Stage pixels from the station's grid. */
export const toStage = (map: PostMap) => (gx: number, gy: number): Pt => [map.O[0] + (gx - gy) * map.T[0], map.O[1] + (gx + gy) * map.T[1]];

/** The depth band of the corridors, the pad and anyone on them: over every room. */
export const CORRIDOR_Z = 21000;

function dock(map: PostMap, d: Dock): Room | null {
  const built = map.start[d.id], T = built && map.types[built[0]];
  if (!built || !T) return null;
  const F = toStage(map), [type, machines] = built;
  const flip = (T.side === "y") !== (d.on === "spine");
  const w = flip ? T.h : T.w, h = flip ? T.w : T.h;                       // its footprint on the station's grid
  const X0 = d.on === "spine" ? d.d - w / 2 : map.branchEdge - w, Y0 = d.on === "spine" ? map.spineEdge - h : d.d - h / 2;
  const G = (g: Pt): Pt => (flip ? F(X0 + g[1], Y0 + g[0]) : F(X0 + g[0], Y0 + g[1]));
  const [ox, oy] = T.off, k = T.k, cx = map.O[0] + (X0 - Y0) * map.T[0];
  const rect: Room["rect"] = [flip ? cx - ((PAINT[0] + ox) / k - PAINT_O[0]) : ox / k - PAINT_O[0] + cx, oy / k - PAINT_O[1] + map.O[1] + (X0 + Y0) * map.T[1], PAINT[0] / k, PAINT[1] / k];
  const out: Room = {
    id: d.id, on: d.on, type, T, name: T.name, flip, depth: X0 + Y0, box: [X0, Y0, w, h], rect, z: 0,
    corr: d.on === "spine" ? F(d.d, map.spineY) : F(map.branchX, d.d),
    door: G(T.side === "y" ? [T.w / 2, T.h + 0.6] : [T.w + 0.6, T.h / 2]),
    inside: G(T.side === "y" ? [T.w / 2, T.h - 1.3] : [T.w - 1.3, T.h / 2]),
    spot: G(T.spot), face: flip ? (-T.face as 1 | -1) : T.face, rest: T.rest.map(G), machines: [],
    poly: [G([0, 0]), G([T.w, 0]), G([T.w, T.h]), G([0, T.h])],
  };
  T.anchors.forEach((a, n) => {
    const kind = machines[n];
    if (kind) out.machines.push({ kind, n, at: G(a), stand: G([a[0] + 1.3, a[1] + 0.5]), tall: map.machTall[kind] ?? 0.07 });
  });
  return out;
}

/**
 * The station as it stands (`map.start`): every docked room, far to near. Each room's `z` is its
 * band in the one depth order: a room's painting, its machines and whoever is inside it share
 * the band, so a nearer room's walls cover a figure standing behind them.
 */
export function rooms(map: PostMap): Room[] {
  const all = map.docks.map((d) => dock(map, d)).filter((r): r is Room => !!r).sort((a, b) => a.depth - b.depth);
  all.forEach((R, r) => (R.z = 2000 * (r + 1)));
  return all;
}

/** Whose depth a spot on the floor belongs to: the room it is inside, or the corridors. */
export function band(map: PostMap, all: Room[], p: Pt): number {
  const u = (p[0] - map.O[0]) / map.T[0], v = (p[1] - map.O[1]) / map.T[1], gx = (u + v) / 2, gy = (v - u) / 2;
  for (const R of all) { const [x, y, w, h] = R.box; if (gx >= x && gx <= x + w && gy >= y && gy <= y + h) return R.z; }
  return CORRIDOR_Z;
}

// ---------------------------------------------------------------- the pad

/** On the pad: where the shuttle sets down, where someone unloads it, the way onto it, and where others stand. */
export function pad(map: PostMap): { ship: Pt; spot: Pt; way: Pt; rest: Pt[] } {
  const F = toStage(map);
  return { ship: F(70.2, 30.6), spot: F(66.2, 34.6), way: F(64.8, 31.5), rest: [F(65, 30.2), F(64.3, 31.6), F(64.6, 33)] };
}

// ---------------------------------------------------------------- the stops

export interface Stop { p: Pt; to: string[] }
export type Stops = Map<string, Stop>;

/** A machine's stop, a room's own spot, the middle of its floor, a rest spot. */
export const stopId = {
  machine: (room: string, n: number) => `m:${room}:${n}`,
  spot: (room: string) => `s:${room}`,
  inside: (room: string) => `i:${room}`,
  rest: (room: string, n: number) => `r:${room}:${n}`,
  pad: "ps",
  padRest: (n: number) => `pr${n}`,
};

/** Every stop, joined only where there is floor between two of them. */
export function chart(map: PostMap, all: Room[]): Stops {
  const stops: Stops = new Map(), P = pad(map);
  const stop = (id: string, p: Pt) => { stops.set(id, { p, to: [] }); return id; };
  const link = (a: string, b: string) => { stops.get(a)!.to.push(b); stops.get(b)!.to.push(a); };
  stop("j", map.junction); stop("p0", map.pad[0]); stop("pw", P.way); stop(stopId.pad, P.spot);
  const F = toStage(map);
  const line = (on: Dock["on"]) => map.docks.filter((d) => d.on === on).sort((a, b) => a.d - b.d).map((d) => stop(`c:${d.id}`, on === "spine" ? F(d.d, map.spineY) : F(map.branchX, d.d)));
  for (const l of [[...line("spine"), "j", "p0"], ["j", ...line("branch")]]) for (let i = 1; i < l.length; i++) link(l[i - 1], l[i]);
  link("p0", "pw"); link("pw", stopId.pad);
  P.rest.forEach((q, i) => link("pw", stop(stopId.padRest(i), q)));
  for (const R of all) {
    const mid = stop(stopId.inside(R.id), R.inside);
    link(`c:${R.id}`, stop(`d:${R.id}`, R.door)); link(`d:${R.id}`, mid); link(mid, stop(stopId.spot(R.id), R.spot));
    for (const m of R.machines) link(mid, stop(stopId.machine(R.id, m.n), m.stand));
    R.rest.forEach((q, n) => link(mid, stop(stopId.rest(R.id, n), q)));
  }
  return stops;
}

export const far = (a: Pt, b: Pt): number => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** The stops from one to another by the shortest walk, both ends included. */
export function way(stops: Stops, from: string, to: string): string[] {
  const dist = new Map<string, number>([[from, 0]]), prev = new Map<string, string>(), open = new Set<string>([from]);
  while (open.size) {
    let u: string | null = null;
    for (const k of open) if (u === null || dist.get(k)! < dist.get(u)!) u = k;
    open.delete(u!);
    if (u === to) break;
    for (const v of stops.get(u!)?.to ?? []) {
      const d = dist.get(u!)! + far(stops.get(u!)!.p, stops.get(v)!.p);
      if (!dist.has(v) || d < dist.get(v)!) { dist.set(v, d); prev.set(v, u!); open.add(v); }
    }
  }
  const out = [to];
  while (out[0] !== from && prev.has(out[0])) out.unshift(prev.get(out[0])!);
  return out[0] === from ? out : [from];
}

/** Someone on the floor: where they are, the last stop they reached, and the stops still ahead. */
export interface Walk { pos: Pt; stop: string; path: string[] }

const length = (stops: Stops, ids: string[]): number => ids.reduce((sum, id, i) => (i ? sum + far(stops.get(id)!.p, stops.get(ids[i - 1])!.p) : 0), 0);

/**
 * Send someone to a stop. Part-way between two stops they may only go on to the one ahead or
 * back to the one behind, whichever makes the shorter walk: they never leave the floor.
 */
export function head(stops: Stops, c: Walk, target: string): void {
  const back = way(stops, c.stop, target), ahead = c.path.length ? way(stops, c.path[0], target) : null;
  if (ahead && far(c.pos, stops.get(c.path[0])!.p) + length(stops, ahead) <= far(c.pos, stops.get(c.stop)!.p) + length(stops, back)) c.path = ahead;
  else { if (c.path.length) c.stop = c.path[0]; c.path = back; }
}

/** Put someone on a stop at once, with no walk. */
export function place(stops: Stops, c: Walk, target: string): void {
  c.pos = [...stops.get(target)!.p]; c.stop = target; c.path = [];
}

/**
 * Walk someone along their path by `go` stage pixels. Returns the way they moved last (dx, dy),
 * or null when they didn't.
 */
export function walk(stops: Stops, c: Walk, go: number): Pt | null {
  let moved: Pt | null = null;
  while (go > 0 && c.path.length) {
    const to = stops.get(c.path[0])!.p, dx = to[0] - c.pos[0], dy = to[1] - c.pos[1], d = Math.hypot(dx, dy);
    if (d > 0.5) moved = [dx, dy];
    if (d <= go) { c.pos = [...to]; c.stop = c.path.shift()!; go -= d; }
    else { c.pos = [c.pos[0] + (dx / d) * go, c.pos[1] + (dy / d) * go]; go = 0; }
  }
  return moved;
}

/** How far a point is from the nearest stretch of floor between two joined stops. 0: it is on a path. */
export function offPath(stops: Stops, p: Pt): number {
  let best = Infinity;
  for (const [, a] of stops) {
    best = Math.min(best, far(p, a.p));
    for (const id of a.to) {
      const b = stops.get(id)!.p, vx = b[0] - a.p[0], vy = b[1] - a.p[1];
      const t = Math.max(0, Math.min(1, ((p[0] - a.p[0]) * vx + (p[1] - a.p[1]) * vy) / (vx * vx + vy * vy || 1)));
      best = Math.min(best, far(p, [a.p[0] + vx * t, a.p[1] + vy * t]));
    }
  }
  return best;
}
