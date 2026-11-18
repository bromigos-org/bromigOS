// The post's contract: what the host hands it, and what it gets back.
//
// The post is drawn only from `PostData`: the lab's job records, as the page knows them. Nothing
// it draws is example data. Whatever a host hands over is made to fit these types first
// (sane.ts), and its text is only ever text (dom.ts). The station's own drawing (`PostMap`,
// post.json in the art folder) is checked the same way before anything is placed from it.

/** A job's state, as the activity record names it (docs/activity.md, "States"). */
export const JOB_STATES = ["queued", "running", "needs-you", "waiting", "succeeded", "failed", "rolled-back", "cancelled", "interrupted"] as const;
export type PostJobState = (typeof JOB_STATES)[number];

/** One job record, as far as the post reads it. */
export interface PostJob {
  id: string;
  /** The record's dotted kind: "backup.run", "lab.image". It picks the job's place (places.ts). */
  kind: string;
  /** The record's title, in its own words. */
  title: string;
  /** "unknown": a state that isn't one of the record's words. It is never drawn. */
  state: PostJobState | "unknown";
  /** Where it is, in the record's words: "step 2 of 4 · Copying what changed". */
  step: string | null;
  /** The share done, 0 to 100, when the record says one. null: the job never said. */
  pct: number | null;
  /** The AI agent that asked for it, when one did. */
  agent: string | null;
  /** The job this one is a part of. */
  parent: string | null;
  /** How it ended, once it has: the record's `result.ok`. */
  ok: boolean | null;
}

export interface PostData {
  /** false: the jobs haven't been read, so nothing is shown as known and nobody is drawn. */
  known: boolean;
  jobs: PostJob[];
}

// ---------------------------------------------------------------- the station's drawing (post.json)

export type Pt = [number, number];

/** A room module: a painting on its own grid (w × h floor tiles), with where things stand on it. */
export interface RoomType {
  name: string;
  w: number;
  h: number;
  /** The corridor it was painted for: "y" the spine, "x" the branch. On the other it is mirrored. */
  side: "x" | "y";
  /** The painting's scale and where its grid's corner is in it. */
  k: number;
  off: Pt;
  /** Where someone stands for the room's own fittings, and the way they face there. */
  spot: Pt;
  face: 1 | -1;
  /** Where the crew rest (the quarters). */
  rest: Pt[];
  /** Where its machines stand. */
  anchors: Pt[];
  /** The living clips it has: "idle", "work", "done". */
  clips: string[];
}

export interface Dock {
  id: string;
  on: "spine" | "branch";
  /** How far along its corridor. */
  d: number;
}

export interface PostMap {
  size: Pt;
  types: Record<string, RoomType>;
  /** The grid's origin and a tile's half size, in stage pixels. */
  O: Pt;
  T: Pt;
  spineY: number;
  branchX: number;
  spineEdge: number;
  branchEdge: number;
  docks: Dock[];
  /** The station as it stands: the room at each doorway, and the machine at each of its anchors. */
  start: Record<string, [string, (string | null)[]]>;
  /** How tall each machine is drawn, as a share of the stage's height. */
  machTall: Record<string, number>;
  junction: Pt;
  pad: [Pt, Pt];
  padPoly: Pt[];
  /** The corridors' running lights: from, to, how many. */
  lanes: [Pt, Pt, number][];
}

/**
 * post.json: the station's drawing, how tall each crew loop's picture is beside the plain
 * standing one, and the shuttle's legs folding: one strip of `frames` pictures side by side,
 * each `w` by `h` (frame 0: legs down; the last: folded away). null: the strip isn't there.
 */
export interface PostPack {
  map: PostMap;
  crew: Record<string, number>;
  ship: { frames: number; w: number; h: number } | null;
}

// ---------------------------------------------------------------- what the host passes and gets

export interface PostOptions {
  data: PostData;
  /** Where the art folder is served: "/post/". Every picture and clip is asked for under it. */
  base?: string;
  /** Hold everything still (the host's own switch; the browser's setting is honoured as well). */
  reduced?: boolean;
  /** Every intent: `job/<id>`, in the board's own route words (no leading #). */
  onNavigate?: (route: string, detail: Record<string, unknown>) => void;
  /** The station couldn't be drawn (its drawing didn't arrive, or isn't one). The host's plain state stands. */
  onError?: (error: unknown) => void;
  /** The station is drawn. */
  onReady?: () => void;
}

export interface PostHandle {
  /** New data: the crew are re-sent in place. Nothing is remounted and no art is fetched again. */
  update(data: PostData): void;
  setReduced(on: boolean): void;
  unmount(): void;
}
