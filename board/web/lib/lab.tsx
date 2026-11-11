// The page's state in one place, and its one connection to the server. Components read it with
// useLab().
//
// The connection model:
// - The door and the session are read once, and again when the tab is looked at again.
// - Signed in, the board is read every 15 seconds and the jobs arrive on the activity stream.
//   Both stop while the tab is hidden (a forgotten tab must not keep the server reading
//   itself) and start again, with an immediate read, when it is looked at.
// - How old a reading is comes from the server (`age_s`, `stale`), never from this browser's
//   clock against the server's: the page keeps the server's time and adds what has passed
//   since the answer came. A wrong clock here changes nothing.
// - A read that fails is state: the board says the server isn't answering, and its age keeps
//   growing until it reads "not read for…". A read the server calls stale is asked again in
//   3 seconds (its first answer after a pause is its last, old one).
// - The stream reopens by itself on a timer, whatever ended it (lib/api/client.ts). A stream
//   the server refuses makes the page ask whether it is still signed in.
"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, byNewest } from "./api/client";
import { ApiError } from "./api/errors";
import type { ActionAnswer, ActivityEvent, Board, Door, JobRecord, Session } from "./api/types";
import { parse, type Route } from "./routes";
import { wearWorld } from "./world";

const BOARD_EVERY_MS = 15_000;
const STALE_AGAIN_MS = 3_000;
const FAILED_AGAIN_MS = 5_000;
const SETTLE_MS = 12_000;
const TICK_MS = 5_000;

export type Load<T> = { state: "loading" } | { state: "ok"; doc: T } | { state: "error"; error: ApiError };

export interface Lab {
  door: Load<Door>;
  session: Load<Session>;
  board: Load<Board>;
  /** The server stopped answering: since the last good read, in its words. */
  lost: string | null;
  /** The board in hand is older than the server allows (it said so, or it grew old since). */
  stale: boolean;
  /** Just opened or just looked at again: the first, old answer isn't called stale yet. */
  settling: boolean;
  jobs: JobRecord[];
  /** The jobs have been read at least once; `live`: the stream is connected now. */
  jobsKnown: boolean;
  live: boolean;
  route: Route;
  /** The machine picked in the rail: the lab-wide places show only its things. */
  scope: string | null;
  clearScope(): void;
  signIn(code: string): Promise<void>;
  signOut(): Promise<void>;
  signOutBrowser(id: string): Promise<void>;
  refresh(): void;
  /** The server's clock, in ms: every "ago" on the page is measured against it. */
  now(): number;
  /** Add, restart or remove an app, when the server lets the page (board.actions). */
  act(verb: "add" | "restart" | "remove", app: string): Promise<ActionAnswer>;
  drawer: "activity" | "depth" | null;
  setDrawer(d: "activity" | "depth" | null): void;
}

const Ctx = createContext<Lab | null>(null);

export function useLab(): Lab {
  const lab = useContext(Ctx);
  if (!lab) throw new Error("useLab outside LabProvider");
  return lab;
}

const err = (e: unknown) => (e instanceof ApiError ? e : new ApiError(0, "unknown", "Something went wrong reading the server."));

function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(""));
  useEffect(() => {
    const read = () => setRoute(parse(window.location.hash));
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  return route;
}

export function LabProvider({ children }: { children: ReactNode }) {
  const a = useMemo(() => (typeof window === "undefined" ? null : api()), []);
  const [door, setDoor] = useState<Load<Door>>({ state: "loading" });
  const [session, setSession] = useState<Load<Session>>({ state: "loading" });
  const [board, setBoard] = useState<Load<Board>>({ state: "loading" });
  const [lost, setLost] = useState<string | null>(null);
  const [settling, setSettling] = useState(true);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [jobsKnown, setJobsKnown] = useState(false);
  const [live, setLive] = useState(false);
  const [scope, setScope] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<"activity" | "depth" | null>(null);
  const [, setTick] = useState(0);
  const route = useHashRoute();
  const signedIn = session.state === "ok" && session.doc.signed_in;
  // the server's clock when the last board came, and this page's own stopwatch then
  const clock = useRef<{ server: number; perf: number } | null>(null);
  const pollNow = useRef<() => void>(() => {});

  const now = useCallback(() => (clock.current ? clock.current.server + (performance.now() - clock.current.perf) : Date.now()), []);

  const readDoorAndSession = useCallback(() => {
    if (!a) return;
    a.door().then(
      (doc) => {
        wearWorld(doc.world);
        setDoor({ state: "ok", doc });
      },
      (e) => setDoor((d) => (d.state === "ok" ? d : { state: "error", error: err(e) })),
    );
    a.session().then(
      (doc) => setSession({ state: "ok", doc }),
      (e) => setSession((s) => (s.state === "ok" ? s : { state: "error", error: err(e) })),
    );
  }, [a]);

  useEffect(() => {
    readDoorAndSession();
    const seen = () => !document.hidden && readDoorAndSession();
    document.addEventListener("visibilitychange", seen);
    return () => document.removeEventListener("visibilitychange", seen);
  }, [readDoorAndSession]);

  // a door or a session that couldn't be read is asked for again, while the tab is looked at
  const unread = door.state === "error" || session.state === "error";
  useEffect(() => {
    if (!unread) return;
    const t = window.setInterval(() => !document.hidden && readDoorAndSession(), 10_000);
    return () => window.clearInterval(t);
  }, [unread, readDoorAndSession]);

  // signed in: the board on a timer and the jobs on the stream, both only while the tab is looked at
  useEffect(() => {
    if (!a || !signedIn) return;
    let over = false, timer = 0, settle = 0, asking = false, fails = 0, lastSessionCheck = -Infinity;
    let stream: { close(): void } | null = null;

    const checkSession = () => {
      if (performance.now() - lastSessionCheck < 5_000) return;
      lastSessionCheck = performance.now();
      a.session().then((doc) => !over && setSession({ state: "ok", doc }), () => {});
    };

    const poll = async () => {
      window.clearTimeout(timer);
      if (over || document.hidden || asking) return;
      asking = true;
      let again = BOARD_EVERY_MS;
      try {
        const doc = await a.board();
        if (over) return;
        clock.current = { server: doc.at > 0 ? doc.at + doc.age_s * 1000 : Date.now(), perf: performance.now() };
        fails = 0;
        setBoard({ state: "ok", doc });
        setLost(null);
        if (doc.stale) again = STALE_AGAIN_MS;
        else setSettling(false);
      } catch (e) {
        if (over) return;
        const error = err(e);
        if (error.status === 401) checkSession(); // the session ended elsewhere: back to the door
        if (error.code === "gathering") {
          // the server is reading itself for the first time: not a failure, ask again soon
          again = Math.min(error.retryAfter ?? 3, 5) * 1000;
          setBoard((b) => (b.state === "ok" ? b : { state: "error", error }));
        } else {
          fails += 1;
          again = fails < 4 ? FAILED_AGAIN_MS : BOARD_EVERY_MS;
          setLost(error.words);
          setBoard((b) => (b.state === "ok" ? b : { state: "error", error }));
        }
      } finally {
        asking = false;
      }
      if (!over && !document.hidden) timer = window.setTimeout(poll, again);
    };
    pollNow.current = () => void poll();

    const onEvent = (ev: ActivityEvent) => {
      if (ev.event === "snapshot") {
        setJobs([...ev.jobs].sort(byNewest));
        setJobsKnown(true);
      } else if (ev.event === "job") setJobs((js) => [ev.job, ...js.filter((j) => j.id !== ev.job.id)].sort(byNewest));
      else if (ev.event === "gone") setJobs((js) => js.filter((j) => j.id !== ev.id));
      else checkSession();
    };

    const start = () => {
      setSettling(true);
      window.clearTimeout(settle);
      settle = window.setTimeout(() => !over && setSettling(false), SETTLE_MS);
      void poll();
      stream ??= a.activity(onEvent, (up) => !over && setLive(up), checkSession);
    };
    const stop = () => {
      window.clearTimeout(timer);
      stream?.close();
      stream = null;
      setLive(false);
    };
    const seen = () => (document.hidden ? stop() : start());
    document.addEventListener("visibilitychange", seen);
    // ages on the page move on while it is looked at ("just now" becomes "1 min ago")
    const tick = window.setInterval(() => !document.hidden && setTick((n) => n + 1), TICK_MS);
    if (!document.hidden) start();
    return () => {
      over = true;
      document.removeEventListener("visibilitychange", seen);
      window.clearInterval(tick);
      window.clearTimeout(settle);
      stop();
      pollNow.current = () => {};
    };
  }, [a, signedIn]);

  // the scope follows the rail: a machine's page picks it, Home lets go of it
  const lastPlace = useRef(route.place);
  useEffect(() => {
    if (route.place === "machine" && route.id) setScope(route.id);
    else if (route.place === "home") setScope(null);
    if (lastPlace.current !== route.place) window.scrollTo(0, 0);
    lastPlace.current = route.place;
    setDrawer((d) => (d === "activity" && route.place === "activity" ? null : d));
  }, [route]);

  const doc = board.state === "ok" ? board.doc : null;
  // every job the page knows: the stream's, and the ones the board's own list has that the stream
  // doesn't (or has older); a record with the later change wins
  const listed = doc?.jobs ?? null;
  const everyJob = useMemo(() => {
    const by = new Map((listed ?? []).map((j) => [j.id, j]));
    for (const j of jobs) if (!by.has(j.id) || j.updated_at >= by.get(j.id)!.updated_at) by.set(j.id, j);
    return [...by.values()].sort(byNewest);
  }, [jobs, listed]);
  const stale = !!doc && (doc.stale || (now() - doc.at) / 1000 > doc.max_age_s);

  const lab: Lab = {
    door,
    session,
    board,
    lost,
    stale,
    settling,
    jobs: everyJob,
    jobsKnown: jobsKnown || listed !== null,
    live,
    route,
    scope,
    clearScope: () => setScope(null),
    async signIn(code) {
      if (!a) return;
      const s = await a.signIn(code);
      setSession({ state: "ok", doc: s });
    },
    async signOut() {
      if (!a) return;
      const s = await a.signOut();
      clock.current = null;
      setBoard({ state: "loading" });
      setJobs([]);
      setJobsKnown(false);
      setLost(null);
      setDrawer(null);
      setSession({ state: "ok", doc: s });
      window.location.hash = "";
    },
    async signOutBrowser(id) {
      if (!a) return;
      const s = await a.signOutBrowser(id);
      setSession({ state: "ok", doc: s });
    },
    refresh: () => pollNow.current(),
    now,
    async act(verb, app) {
      if (!a) throw new ApiError(0, "unreachable", "The server isn't answering.");
      const said = await a.act(verb, app);
      pollNow.current();
      return said;
    },
    drawer,
    setDrawer,
  };
  return <Ctx.Provider value={lab}>{children}</Ctx.Provider>;
}
