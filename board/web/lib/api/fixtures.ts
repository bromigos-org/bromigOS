// Fixture mode: a fixture build (BOARD_FIXTURES=1) reads `?fixture=NAME` and answers every API
// call from fixtures/NAME.json (copied to /fixtures/ by scripts/postbuild.mjs). The package's
// build leaves this out, so the installed page always talks to the server.
//
// A fixture file is one page state of the whole lab, in the documents the service sends (the
// same shapes: tests/shapes.spec.ts checks them against real answers), read by the same reader
// as the real ones (lib/api/read.ts):
//   { "about": "…",
//     "door": <GET /api/door>, "session": <GET /api/session>, "board": <GET /api/board>,
//     "signin": { "code": "…", "session": <the session after it> } | absent,
//     "activity": [<job record>…],                  the stream's first snapshot
//     "stream": [ { "after_ms": 600, "event": "job" | "gone", "data": … } ],  replayed after it
//     "vitals": { "myserver/24h": <GET /api/vitals> } }
// Any document may be {"$status": N, "$error": {"code", "words"}} to stand for an error answer.

import type { Api } from "./client";
import { ApiError, cleanCode } from "./errors";
import { readAction, readBoard, readDoor, readEvent, readSession, readVitals } from "./read";
import type { Session } from "./types";

type Err = { $status: number; $error?: { code: string; words: string } };

interface Fixture {
  door: unknown;
  session: unknown;
  board: unknown;
  signin?: { code: string; session: unknown };
  activity: unknown[];
  stream?: { after_ms: number; event: string; data: unknown }[];
  vitals?: Record<string, unknown>;
}

export function fixtureName(): string | null {
  if (typeof window === "undefined") return null;
  const name = new URLSearchParams(window.location.search).get("fixture");
  return name && /^[a-z0-9-]{1,64}$/.test(name) ? name : null;
}

const SIGNED_OUT = readSession(null);

export function fixtureApi(name: string): Api {
  let fx: Promise<Fixture> | null = null;
  const load = () =>
    (fx ??= fetch(`/fixtures/${name}.json`, { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new ApiError(0, "no-fixture", `No fixture named ${name}.`);
      return r.json() as Promise<Fixture>;
    }));
  let session: Session | null = null;

  const answer = (d: unknown): unknown => {
    if (d && typeof d === "object" && "$status" in (d as object)) {
      const e = d as Err;
      throw new ApiError(e.$status, e.$error?.code ?? `http-${e.$status}`, e.$error?.words ?? "The server couldn't do that.");
    }
    return d;
  };
  const owner = () => {
    if (session && !session.signed_in) throw new ApiError(401, "signed-out", "Sign in first.");
  };

  return {
    door: async () => readDoor(answer((await load()).door)),
    session: async () => session ?? readSession(answer((await load()).session)),
    async signIn(code) {
      const f = await load();
      if (!f.signin || cleanCode(code) !== cleanCode(f.signin.code))
        throw new ApiError(401, "bad-code", "That code isn't right, or it was used already. Run sudo bromigos server board code at the server for a new one.");
      return (session = readSession(f.signin.session));
    },
    signOut: async () => (session = SIGNED_OUT),
    async signOutBrowser(id) {
      const s = session ?? readSession(answer((await load()).session));
      return (session = { ...s, browsers: s.browsers.filter((b) => b.id !== id) });
    },
    async board() {
      owner();
      return readBoard(answer((await load()).board));
    },
    async vitals(machine, range) {
      owner();
      const v = (await load()).vitals?.[`${machine}/${range}`];
      if (!v) throw new ApiError(404, "http-404", "The server couldn't do that.");
      return readVitals(v, machine, range);
    },
    activity(on, up) {
      const timers: number[] = [];
      let open = true;
      const say = (event: string, data: unknown) => {
        const ev = readEvent(event, data);
        if (ev && open) on(ev);
      };
      load().then(
        (f) => {
          if (!open) return;
          up(true);
          say("snapshot", { schema: 1, jobs: f.activity });
          for (const s of f.stream ?? []) timers.push(window.setTimeout(() => say(s.event, s.data), s.after_ms));
        },
        () => up(false),
      );
      return {
        close() {
          open = false;
          timers.forEach(clearTimeout);
        },
      };
    },
    act: async (verb, app, more) => readAction({ ok: true, job: null, words: `${verb} ${app}${more?.delete_data ? " and delete its data" : ""}: a fixture starts nothing.` }),
  };
}
