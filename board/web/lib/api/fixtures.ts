// Fixture mode: a fixture build (BOARD_FIXTURES=1) reads `?fixture=NAME` and answers every API
// call from fixtures/NAME.json (copied to /fixtures/ by scripts/postbuild.mjs). The package's
// build leaves this off, so the installed page always talks to the server.
//
// A fixture file is one page state of the whole lab:
//   { "about": "…", "now": ms,                       what it shows; the clock it is written against
//     "door": Door, "session": Session, "board": Board | {"$status": 401},
//     "signin": { "code": "…", "session": Session } | absent,
//     "activity": [JobRecord…],
//     "stream": [ { "after_ms": 600, "event": "job" | "gone", "data": … } ] }  replayed after connecting
// Any document may be {"$status": N, "$error": {"code", "words"}} to stand for an error answer.

import type { Api } from "./client";
import { ApiError, cleanCode } from "./errors";
import type { ActivityEvent, Board, Door, JobRecord, Session } from "./types";

type Err = { $status: number; $error?: { code: string; words: string } };
type Doc<T> = T | Err;

export interface Fixture {
  about: string;
  now: number;
  door: Doc<Door>;
  session: Doc<Session>;
  board: Doc<Board>;
  signin?: { code: string; session: Session };
  activity: JobRecord[];
  stream?: { after_ms: number; event: "job" | "gone"; data: JobRecord | { id: string } }[];
}

export const fixturesOn = () => process.env.NEXT_PUBLIC_BOARD_FIXTURES === "1";

export function fixtureName(): string | null {
  if (!fixturesOn() || typeof window === "undefined") return null;
  const name = new URLSearchParams(window.location.search).get("fixture");
  return name && /^[a-z0-9-]{1,64}$/.test(name) ? name : null;
}

const SIGNED_OUT: Session = { schema: 1, signed_in: false, role: null, browser: null, expires_at: null, browsers: [] };

export function fixtureApi(name: string): Api {
  const loaded = performance.now();
  let fx: Promise<Fixture> | null = null;
  const load = () => (fx ??= fetch(`/fixtures/${name}.json`, { cache: "no-store" }).then((r) => {
    if (!r.ok) throw new ApiError(0, "no-fixture", `No fixture named ${name}.`);
    return r.json() as Promise<Fixture>;
  }));
  let session: Session | null = null;
  let clock = Date.now();
  load().then((f) => (clock = f.now)).catch(() => {});

  const answer = <T>(d: Doc<T>): T => {
    if (d && typeof d === "object" && "$status" in (d as object)) {
      const e = d as Err;
      throw new ApiError(e.$status, e.$error?.code ?? `http-${e.$status}`, e.$error?.words ?? "The server couldn't do that.");
    }
    return d as T;
  };
  const owner = () => {
    if (session && !session.signed_in) throw new ApiError(401, "signed-out", "Sign in first.");
  };

  return {
    door: async () => answer((await load()).door),
    session: async () => session ?? answer((await load()).session),
    async signIn(code) {
      const f = await load();
      if (!f.signin || cleanCode(code) !== cleanCode(f.signin.code))
        throw new ApiError(401, "bad-code", "That code isn't right. Make a new one at the server and type it here.");
      return (session = f.signin.session);
    },
    signOut: async () => (session = SIGNED_OUT),
    async signOutBrowser(id) {
      const s = session ?? answer((await load()).session);
      return (session = { ...s, browsers: s.browsers.filter((b) => b.id !== id) });
    },
    async board() {
      owner();
      return answer((await load()).board);
    },
    activity(on, connected) {
      const timers: number[] = [];
      let open = true;
      load().then((f) => {
        if (!open) return;
        connected(true);
        on({ event: "snapshot", data: { schema: 1, jobs: f.activity } });
        for (const s of f.stream ?? [])
          timers.push(window.setTimeout(() => on({ event: s.event, data: s.data } as ActivityEvent), s.after_ms));
      }, () => connected(false));
      return () => {
        open = false;
        timers.forEach(clearTimeout);
      };
    },
    answer: async () => {},
    cancel: async () => {},
    retry: async () => {},
    now: () => clock + (performance.now() - loaded),
  };
}
