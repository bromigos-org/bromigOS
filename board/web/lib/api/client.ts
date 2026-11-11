// The client for the board's API: /api/door, /api/session, /api/board, /api/vitals, the activity
// stream /api/activity (Server-Sent Events) and /api/actions. Same origin only; the session is
// the service's HttpOnly cookie, which this code never reads. Every request that changes
// something carries X-Bromigos-Board: 1 and a JSON body (the service refuses one without them).
// Every answer goes through lib/api/read.ts before anything else sees it.
//
// In a fixture build (BOARD_FIXTURES=1, never the package's) `?fixture=NAME` swaps the API
// for fixtures/NAME.json, so pages can be built and tested without a server.

import { ApiError, cleanCode } from "./errors";
import { fixtureApi, fixtureName } from "./fixtures";
import { readAction, readBoard, readDoor, readEvent, readSession, readVitals } from "./read";
import type { ActionAnswer, ActivityEvent, Board, Door, JobRecord, Session, Vitals, VitalsRange } from "./types";

export { ApiError, cleanCode } from "./errors";

/** The stream as the page sees it: open, or closed and trying again. */
export interface Stream {
  close(): void;
}

/** The calls the page makes. The real one talks to the service; the fixture one reads a file. */
export interface Api {
  door(): Promise<Door>;
  session(): Promise<Session>;
  signIn(code: string): Promise<Session>;
  signOut(): Promise<Session>;
  signOutBrowser(id: string): Promise<Session>;
  board(): Promise<Board>;
  /** One machine's trends; ApiError 404 while the server keeps none. */
  vitals(machine: string, range: VitalsRange): Promise<Vitals>;
  /** Opens the activity stream, and reopens it whenever it ends, until close(). `up` says
   *  whether it is connected; `ended` is called each time a connection is refused or lost. */
  activity(on: (ev: ActivityEvent) => void, up: (connected: boolean) => void, ended: () => void): Stream;
  /** Add, restart or remove an app (the service's actions). Removing keeps the app's data,
   *  unless `more` asks to delete it: that takes a fresh one-time code, which root checks. */
  act(verb: "add" | "restart" | "remove", app: string, more?: { delete_data: true; code: string }): Promise<ActionAnswer>;
}

const HEADERS = { "X-Bromigos-Board": "1", "Content-Type": "application/json" };
const TIMEOUT_MS = 20_000;

/** What the page says to a 503 `busy`: the server is fine, and the same request works in a moment. */
export const BUSY_WORDS = "The server is busy. Try again in a moment.";

async function call(path: string, init?: RequestInit): Promise<unknown> {
  let res: Response;
  try {
    res = await fetch(path, { credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(TIMEOUT_MS), ...init });
  } catch {
    throw new ApiError(0, "unreachable", "The server isn't answering.");
  }
  let doc: unknown = null;
  try {
    doc = JSON.parse(await res.text());
  } catch {
    doc = null; // not JSON: a proxy's error page, or a route the service doesn't have
  }
  if (!res.ok) {
    const err = (doc as { error?: { code?: unknown; words?: unknown } } | null)?.error;
    const retry = Number(res.headers.get("Retry-After"));
    const said = typeof err?.words === "string" && err.words ? err.words : null;
    // 503 `busy`: many codes were being checked at once and this one waited too long for its turn.
    // Nothing was wrong with it, and nothing was used up: the same request works in a moment.
    // (A 503 without words stays "couldn't answer": it may be the service restarting.)
    const busy = res.status === 503 && err?.code === "busy";
    throw new ApiError(
      res.status,
      busy ? "busy" : typeof err?.code === "string" ? err.code : `http-${res.status}`,
      busy ? BUSY_WORDS : (said ?? (res.status >= 500 ? "The server couldn't answer just now." : "The server couldn't do that.")),
      Number.isFinite(retry) && retry > 0 ? retry : null,
    );
  }
  if (doc === null) throw new ApiError(res.status, "not-json", "The server's answer couldn't be read.");
  return doc;
}

const send = (method: string, path: string, body?: unknown) => call(path, { method, headers: HEADERS, body: JSON.stringify(body ?? {}) });

const REOPEN_MS = [1_000, 3_000, 5_000, 15_000];

const realApi: Api = {
  door: async () => readDoor(await call("/api/door")),
  session: async () => readSession(await call("/api/session")),
  signIn: async (code) => readSession(await send("POST", "/api/session", { code: cleanCode(code) })),
  signOut: async () => readSession(await send("DELETE", "/api/session")),
  signOutBrowser: async (id) => readSession(await send("DELETE", `/api/session/${encodeURIComponent(id)}`)),
  board: async () => readBoard(await call("/api/board")),
  vitals: async (machine, range) => readVitals(await call(`/api/vitals?machine=${encodeURIComponent(machine)}&range=${range}`), machine, range),
  activity(on, up, ended) {
    let es: EventSource | null = null, timer = 0, tries = 0, closed = false;
    const open = () => {
      if (closed) return;
      const src = (es = new EventSource("/api/activity"));
      const pass = (event: string) => (m: MessageEvent) => {
        let data: unknown = null;
        try {
          data = JSON.parse(m.data);
        } catch {
          return; // a broken event is skipped; the next snapshot puts it right
        }
        const ev = readEvent(event, data);
        if (ev) on(ev);
      };
      for (const e of ["snapshot", "job", "gone", "signed-out"]) src.addEventListener(e, pass(e));
      src.onopen = () => {
        tries = 0;
        up(true);
      };
      // An error ends this connection. The browser retries a dropped one by itself, but not one
      // the server refused (a 502 while the service restarts, a 401): either way this one is
      // closed and a new one opened on a timer, so the stream always comes back.
      src.onerror = () => {
        src.close();
        if (closed || es !== src) return;
        up(false);
        ended();
        timer = window.setTimeout(open, REOPEN_MS[Math.min(tries++, REOPEN_MS.length - 1)]);
      };
    };
    open();
    return {
      close() {
        closed = true;
        window.clearTimeout(timer);
        es?.close();
      },
    };
  },
  act: async (verb, app, more) => readAction(await send("POST", "/api/actions", { verb, app, ...(more ?? {}) })),
};

let chosen: Api | null = null;

/** The API for this page load: the fixture's when a fixture build names one, else the server's. */
export function api(): Api {
  if (!chosen) {
    // compiled to `null` outside a fixture build, so the fixture code isn't in the package at all
    const name = process.env.NEXT_PUBLIC_BOARD_FIXTURES === "1" ? fixtureName() : null;
    chosen = name ? fixtureApi(name) : realApi;
  }
  return chosen;
}

/** Newest first. */
export const byNewest = (a: JobRecord, b: JobRecord) => b.started_at - a.started_at || (a.id < b.id ? 1 : -1);
