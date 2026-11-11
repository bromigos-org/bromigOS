// The page's state in one place: the door, the session, the board (re-read every 15 s while
// signed in, as DESIGN.md §1 says), the activity jobs (live from the stream), the route and
// the machine the places are scoped to. Components read it with useLab().
"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, byNewest } from "./api/client";
import { ApiError } from "./api/errors";
import type { ActivityEvent, Board, Door, JobRecord, Session } from "./api/types";
import { parse, type Route } from "./routes";
import { wearWorld } from "./world";

const BOARD_EVERY_MS = 15_000;

export type Load<T> = { state: "loading" } | { state: "ok"; doc: T } | { state: "error"; error: ApiError };

export interface Lab {
  door: Load<Door>;
  session: Load<Session>;
  board: Load<Board>;
  jobs: JobRecord[];
  /** The activity stream is connected (false while it reconnects). */
  live: boolean;
  route: Route;
  /** The machine picked in the rail: the lab-wide places show only its things. */
  scope: string | null;
  clearScope(): void;
  signIn(code: string): Promise<void>;
  signOut(): Promise<void>;
  signOutBrowser(id: string): Promise<void>;
  refresh(): void;
  now(): number;
  /** The Activity and Depth drawers. */
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
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [live, setLive] = useState(false);
  const [scope, setScope] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<"activity" | "depth" | null>(null);
  const route = useHashRoute();
  const signedIn = session.state === "ok" && session.doc.signed_in;

  const loadBoard = useCallback(() => {
    if (!a) return;
    a.board().then(
      (doc) => setBoard({ state: "ok", doc }),
      (e) => {
        const error = err(e);
        if (error.status === 401) {
          // the session ended elsewhere (signed out on the phone, STOP ALL): back to the door
          a.session().then((doc) => setSession({ state: "ok", doc }), () => {});
        }
        setBoard((b) => (b.state === "ok" ? b : { state: "error", error }));
      },
    );
  }, [a]);

  useEffect(() => {
    if (!a) return;
    a.door().then(
      (doc) => {
        wearWorld(doc.world);
        setDoor({ state: "ok", doc });
      },
      (e) => setDoor({ state: "error", error: err(e) }),
    );
    a.session().then(
      (doc) => setSession({ state: "ok", doc }),
      (e) => setSession({ state: "error", error: err(e) }),
    );
  }, [a]);

  // signed in: the board every 15 s, and the activity stream
  useEffect(() => {
    if (!a || !signedIn) return;
    loadBoard();
    const t = window.setInterval(loadBoard, BOARD_EVERY_MS);
    const close = a.activity(
      (ev: ActivityEvent) => {
        if (ev.event === "snapshot") setJobs([...ev.data.jobs].sort(byNewest));
        else if (ev.event === "job") setJobs((js) => [ev.data, ...js.filter((j) => j.id !== ev.data.id)].sort(byNewest));
        else setJobs((js) => js.filter((j) => j.id !== ev.data.id));
      },
      setLive,
    );
    return () => {
      window.clearInterval(t);
      close();
      setLive(false);
    };
  }, [a, signedIn, loadBoard]);

  // the scope follows the rail: a machine's page picks it, Home lets go of it
  const lastPlace = useRef(route.place);
  useEffect(() => {
    if (route.place === "machine" && route.id) setScope(route.id);
    else if (route.place === "home") setScope(null);
    if (lastPlace.current !== route.place) window.scrollTo(0, 0);
    lastPlace.current = route.place;
    setDrawer((d) => (d === "activity" && route.place === "activity" ? null : d));
  }, [route]);

  const lab: Lab = {
    door,
    session,
    board,
    jobs,
    live,
    route,
    scope,
    clearScope: () => setScope(null),
    async signIn(code) {
      if (!a) return;
      const doc = await a.signIn(code);
      setSession({ state: "ok", doc });
    },
    async signOut() {
      if (!a) return;
      const doc = await a.signOut();
      setBoard({ state: "loading" });
      setJobs([]);
      setDrawer(null);
      setSession({ state: "ok", doc });
      window.location.hash = "";
    },
    async signOutBrowser(id) {
      if (!a) return;
      const doc = await a.signOutBrowser(id);
      setSession({ state: "ok", doc });
    },
    refresh: loadBoard,
    now: () => (a ? a.now() : Date.now()),
    drawer,
    setDrawer,
  };
  return <Ctx.Provider value={lab}>{children}</Ctx.Provider>;
}
