// The typed client for the board's API: /api/door, /api/session, /api/board and the activity
// stream /api/activity (Server-Sent Events). Same origin only; the session is the service's
// HttpOnly cookie, which this code never reads. Every request that changes something carries
// X-Bromigos-Board: 1 (the service refuses one without it: no other site can set it).
//
// In a fixture build (BOARD_FIXTURES=1, never the package's) `?fixture=NAME` swaps the API
// for fixtures/NAME.json, so pages can be built and tested before the service answers.

import type { ActivityEvent, ApiErrorDoc, Board, Door, JobRecord, Session } from "./types";
import { fixtureApi, fixtureName } from "./fixtures";
import { ApiError, cleanCode } from "./errors";

export { ApiError, cleanCode } from "./errors";

/** The calls the page makes. The real one talks to the service; the fixture one reads a file. */
export interface Api {
  door(): Promise<Door>;
  session(): Promise<Session>;
  signIn(code: string): Promise<Session>;
  signOut(): Promise<Session>;
  signOutBrowser(id: string): Promise<Session>;
  board(): Promise<Board>;
  /** Opens the activity stream; returns a function that closes it. */
  activity(on: (ev: ActivityEvent) => void, connected: (up: boolean) => void): () => void;
  answer(job: string, choice: string): Promise<void>;
  cancel(job: string): Promise<void>;
  retry(job: string): Promise<void>;
  /** The clock the page reads times against: the fixture's own in a fixture build. */
  now(): number;
}

const HEADERS = { "X-Bromigos-Board": "1", "Content-Type": "application/json" };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { credentials: "same-origin", cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, "unreachable", "The server didn't answer.");
  }
  const text = await res.text();
  let doc: unknown = null;
  try {
    doc = text ? JSON.parse(text) : null;
  } catch {
    doc = null;
  }
  if (!res.ok) {
    const err = (doc as ApiErrorDoc | null)?.error;
    throw new ApiError(res.status, err?.code ?? `http-${res.status}`, err?.words ?? "The server couldn't do that.");
  }
  return doc as T;
}

const send = <T>(method: string, path: string, body?: unknown) =>
  call<T>(path, { method, headers: HEADERS, body: JSON.stringify(body ?? {}) });

const realApi: Api = {
  door: () => call<Door>("/api/door"),
  session: () => call<Session>("/api/session"),
  signIn: (code) => send<Session>("POST", "/api/session", { code: cleanCode(code) }),
  signOut: () => send<Session>("DELETE", "/api/session"),
  signOutBrowser: (id) => send<Session>("DELETE", `/api/session/${encodeURIComponent(id)}`),
  board: () => call<Board>("/api/board"),
  activity(on, connected) {
    const es = new EventSource("/api/activity");
    const pass = (event: ActivityEvent["event"]) => (m: MessageEvent) => {
      try {
        on({ event, data: JSON.parse(m.data) } as ActivityEvent);
      } catch {
        /* a broken event is skipped; the next snapshot puts it right */
      }
    };
    es.addEventListener("snapshot", pass("snapshot"));
    es.addEventListener("job", pass("job"));
    es.addEventListener("gone", pass("gone"));
    es.onopen = () => connected(true);
    es.onerror = () => connected(false); // EventSource reconnects by itself
    return () => es.close();
  },
  answer: (job, choice) => send("POST", `/api/activity/${encodeURIComponent(job)}/answer`, { choice }),
  cancel: (job) => send("POST", `/api/activity/${encodeURIComponent(job)}/cancel`),
  retry: (job) => send("POST", `/api/activity/${encodeURIComponent(job)}/retry`),
  now: () => Date.now(),
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

/** Newest first; children after nothing in particular. */
export const byNewest = (a: JobRecord, b: JobRecord) => b.started_at - a.started_at || (a.id < b.id ? 1 : -1);
