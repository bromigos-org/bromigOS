// The door: whatever the post is handed is made to fit its types before anything is drawn from
// it. The jobs are a server's answer, and much of a record is some command's own output, so it
// is not trusted to have the right shape:
//
//   - a state that isn't one of the record's words becomes "unknown", which is never drawn, so no
//     word from the data ever picks a place, a loop or a class;
//   - a field that should be text and isn't is absent, a share done that isn't a number from 0 to
//     100 is absent (the ring then turns, it never guesses), and a job with no id is dropped;
//   - nothing is added: a job the host didn't send is never drawn.
//
// The station's own drawing (post.json) comes through saneMap() the same way: it is the page's
// own file, but a file that arrived broken must stop at the door, not half-way through a walk.
import { PLACES } from "./places";
import { JOB_STATES, type Dock, type PostData, type PostJob, type PostMap, type PostPack, type Pt, type RoomType } from "./types";

type Rec = Record<string, unknown>;
const rec = (v: unknown): Rec | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Rec) : null);
const recs = (v: unknown): Rec[] => (Array.isArray(v) ? v.filter((x): x is Rec => !!rec(x)) : []);
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pt = (v: unknown): Pt | null => (Array.isArray(v) && v.length === 2 && num(v[0]) !== null && num(v[1]) !== null ? [v[0], v[1]] : null);
const pts = (v: unknown): Pt[] => (Array.isArray(v) ? v.map(pt).filter((p): p is Pt => !!p) : []);

/** A job's words are short on the page: a hint is a sentence, not a log. */
const MAX = 240;
const words = (v: unknown): string | null => { const s = str(v); return s === null ? null : s.length > MAX ? `${s.slice(0, MAX - 1)}…` : s; };

export function saneJob(input: unknown): PostJob | null {
  const j = rec(input), id = j && str(j.id);
  if (!j || !id) return null;
  const pct = num(j.pct);
  return {
    id, kind: str(j.kind) ?? "", title: words(j.title) ?? "",
    state: (JOB_STATES as readonly unknown[]).includes(j.state) ? (j.state as PostJob["state"]) : "unknown",
    step: words(j.step), pct: pct !== null && pct >= 0 && pct <= 100 ? pct : null,
    agent: str(j.agent), parent: str(j.parent), ok: typeof j.ok === "boolean" ? j.ok : null,
  };
}

export function sane(input: unknown): PostData {
  const d = rec(input) ?? {};
  return { known: d.known === true, jobs: (Array.isArray(d.jobs) ? d.jobs : []).map(saneJob).filter((j): j is PostJob => !!j) };
}

// ---------------------------------------------------------------- the station's drawing

function roomType(v: unknown): RoomType | null {
  const t = rec(v);
  if (!t) return null;
  const w = num(t.w), h = num(t.h), k = num(t.k), off = pt(t.off), spot = pt(t.spot);
  if (w === null || h === null || k === null || w <= 0 || h <= 0 || k <= 0 || !off || !spot || (t.side !== "x" && t.side !== "y")) return null;
  return {
    name: str(t.name) ?? "Room", w, h, side: t.side, k, off, spot, face: t.face === 1 ? 1 : -1, rest: pts(t.rest), anchors: pts(t.anchors),
    clips: (Array.isArray(t.clips) ? t.clips : []).filter((c): c is string => c === "idle" || c === "work" || c === "done"),
  };
}

/** A name that may become part of a file's address: lower-case letters only. */
const NAME = /^[a-z]{1,16}$/;

/** post.json's `map`, or null when it isn't a station the post can draw. */
export function saneMap(input: unknown): PostMap | null {
  const m = rec(input);
  if (!m) return null;
  const size = pt(m.size), O = pt(m.O), T = pt(m.T), junction = pt(m.junction), pad = pts(m.pad);
  const n = { spineY: num(m.spineY), branchX: num(m.branchX), spineEdge: num(m.spineEdge), branchEdge: num(m.branchEdge) };
  if (!size || size[0] <= 0 || size[1] <= 0 || !O || !T || T[0] <= 0 || T[1] <= 0 || !junction || pad.length !== 2) return null;
  if (n.spineY === null || n.branchX === null || n.spineEdge === null || n.branchEdge === null) return null;
  const types: Record<string, RoomType> = {};
  for (const [id, v] of Object.entries(rec(m.types) ?? {})) { const t = NAME.test(id) ? roomType(v) : null; if (t) types[id] = t; }
  const docks: Dock[] = recs(m.docks).flatMap((d) => {
    const id = str(d.id), at = num(d.d);
    return id && /^[a-z0-9]{1,8}$/.test(id) && at !== null && (d.on === "spine" || d.on === "branch") ? [{ id, on: d.on, d: at }] : [];
  });
  const kinds = new Set<string>(PLACES.map((p) => p.place));
  const start: PostMap["start"] = {};
  for (const d of docks) {
    const b = rec(m.start)?.[d.id];
    if (!Array.isArray(b) || typeof b[0] !== "string" || !types[b[0]]) continue;
    // a machine the post has no place for isn't drawn: its name would otherwise become a file's address
    start[d.id] = [b[0], (Array.isArray(b[1]) ? b[1] : []).map((k) => (typeof k === "string" && kinds.has(k) && k !== "pad" ? k : null))];
  }
  const machTall: Record<string, number> = {};
  for (const [k, v] of Object.entries(rec(m.machTall) ?? {})) { const t = num(v); if (kinds.has(k) && t !== null && t > 0 && t < 1) machTall[k] = t; }
  const lanes = (Array.isArray(m.lanes) ? m.lanes : []).flatMap((l): PostMap["lanes"] => {
    const a = Array.isArray(l) ? pt(l[0]) : null, b = Array.isArray(l) ? pt(l[1]) : null, c = Array.isArray(l) ? num(l[2]) : null;
    return a && b && c !== null && c >= 1 && c <= 12 ? [[a, b, Math.floor(c)]] : [];
  });
  const map: PostMap = { size, types, O, T, spineY: n.spineY, branchX: n.branchX, spineEdge: n.spineEdge, branchEdge: n.branchEdge, docks, start, machTall, junction, pad: [pad[0], pad[1]], padPoly: pts(m.padPoly), lanes };
  // every place in the table must stand somewhere, or a job of its kind would have nowhere to be drawn
  const placed = new Set(Object.values(start).flatMap((b) => b[1]));
  return PLACES.every((p) => p.place === "pad" || placed.has(p.place)) && map.padPoly.length >= 3 ? map : null;
}

/** post.json whole: the drawing, each crew loop's height beside the plain standing one, and the shuttle's strip of frames. */
export function sanePack(input: unknown): PostPack | null {
  const p = rec(input), map = p && saneMap(p.map);
  if (!p || !map) return null;
  const crew: Record<string, number> = {};
  for (const [k, v] of Object.entries(rec(p.crew) ?? {})) { const r = num(v); if (/^[a-z]+-[a-z]+$/.test(k) && r !== null && r > 0.5 && r < 2) crew[k] = r; }
  const s = rec(p.ship), frames = s && num(s.frames), w = s && num(s.w), h = s && num(s.h);
  const ship = frames && w && h && Number.isInteger(frames) && frames >= 2 && frames <= 200 && w > 0 && h > 0 ? { frames, w, h } : null;
  return { map, crew, ship };
}
