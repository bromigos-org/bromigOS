// Lamplight on the Lab board: Home's hero (the lab as a living station, a relay station of the
// Wick's class) and a machine's hero (its deck tray pulled out of the station). The station is a
// module with no React in it (lib/lamplight/): it is handed the board's own document as its data
// (fromBoard), the manifest of what it may draw (lib/lamplight-assets.ts) and this page's status
// line, and it draws nothing the server didn't send.
//
// The module and three.js load only when a hero is on screen. Until they have, and whenever they
// can't (a script that didn't arrive), the hero's frame carries the lab's plain state: the same
// status line, how many machines, and when the server read itself. Without WebGL the module still
// stands: its line, readouts, alarm and deck list need no hologram.
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Board, Machine } from "@/lib/api/types";
import { useLab } from "@/lib/lab";
import { fromBoard } from "@/lib/lamplight/from-board";
import type { LamplightAssets, LamplightData } from "@/lib/lamplight/types";
import { ago, clock } from "@/lib/time";
import { headline, type Headline } from "@/lib/words";

type Module = typeof import("@/lib/lamplight");
interface Handle {
  refresh(): void;
  unmount(): void;
}

/** Where the station's intents go: the board's own routes; "ask" is the top bar's box. */
function go(route: string) {
  if (route === "ask") {
    document.querySelector<HTMLInputElement>('input[aria-label="Ask VECTOR or search"]')?.focus();
    return;
  }
  window.location.hash = route;
}

/** The board's document as the station's data, with what only this page knows. */
function useStationData(board: Board, v: Headline): LamplightData {
  const { now, stale, jobs } = useLab();
  return fromBoard(board, {
    jobs,
    stale,
    headline: { words: v.words, tone: v.look === "" ? "ok" : v.look, hint: v.hint },
    clock: board.at > 0 ? clock(board.at) : "--:--",
    age: board.at > 0 ? ago(board.at, now()) : "not read yet",
  });
}

/**
 * Mounts a Lamplight view in `el` once, hands it each new reading, recolours it when the world
 * changes, and unmounts it with the component. `again` names what needs a fresh mount.
 */
function useMount<H extends Handle>(data: LamplightData, make: (lp: Module, el: HTMLDivElement, assets: LamplightAssets, first: LamplightData) => H, sync: (h: H, d: LamplightData) => void, again = "") {
  const el = useRef<HTMLDivElement>(null);
  const handle = useRef<H | null>(null);
  const latest = useRef({ data, make, sync });
  latest.current = { data, make, sync };
  const [on, setOn] = useState(false);
  useEffect(() => {
    let gone = false;
    const world = new MutationObserver(() => handle.current?.refresh()); // new tokens: recolour once
    Promise.all([import("@/lib/lamplight"), import("@/lib/lamplight-assets")])
      .then(([lp, { ASSETS }]) => {
        if (gone || !el.current) return;
        handle.current = latest.current.make(lp, el.current, ASSETS, latest.current.data);
        world.observe(document.documentElement, { attributes: true, attributeFilter: ["data-world"] });
        setOn(true);
      })
      .catch((e) => console.warn("Lamplight couldn't be loaded; the hero keeps the lab's plain state:", e));
    return () => {
      gone = true;
      world.disconnect();
      handle.current?.unmount();
      handle.current = null;
      setOn(false);
    };
  }, [again]);
  const key = JSON.stringify(data);
  useEffect(() => {
    if (handle.current) latest.current.sync(handle.current, latest.current.data);
  }, [key]);
  return { el, on };
}

// a hologram that couldn't be drawn (no WebGL, a model that didn't arrive) isn't an error on the
// page: the module's words stand, and the next page that shows one asks again
const quiet = () => {};

function Fresh({ at, now }: { at: number; now: number }) {
  if (at <= 0)
    return (
      <span className="chip" title="The server hasn't said when it last read itself">
        NOT READ YET
      </span>
    );
  return (
    <span className="chip" title={`When the server last read itself: ${clock(at)}, in this browser's time zone`}>
      {clock(at)} · {ago(at, now).toUpperCase()}
    </span>
  );
}

/** Home's hero: the whole station. */
export function Lamplight({ board }: { board: Board }) {
  const { now, stale, settling } = useLab();
  const t = now();
  const v = headline(board, { stale, settling, now: t });
  const data = useStationData(board, v);
  const { el, on } = useMount(
    data,
    (lp, host, assets, first) => lp.mount(host, { data: first, assets, onNavigate: go, onError: quiet }),
    (h, d) => h.update(d),
  );
  const n = board.machines.length;
  return (
    <section className={`lamp${on ? " on" : ""}`} aria-label="The lab">
      <div className="lamp-mount" data-lamplight="mount" ref={el} />
      {!on && (
        <div className="stage lamp-wait" title="Lamplight, the lab as a living station: each machine a compartment of the post. While its scene loads, the lab's state shows here.">
          <div className="st-top">
            <span className="over" title={`${n} bromigOS machine${n === 1 ? " is" : "s are"} in this lab`}>
              {n} MACHINE{n === 1 ? "" : "S"}
            </span>
            <p className={`verdict${v.look ? ` ${v.look}` : ""}`} title={v.hint} role="status">
              {v.words}
            </p>
            <Fresh at={board.at} now={t} />
          </div>
          <span className="h-scan" aria-hidden="true" />
          <span className="h-edge" aria-hidden="true" />
        </div>
      )}
    </section>
  );
}

/**
 * A machine's hero: its deck tray pulled out of the station, its hologram at full detail (or its
 * kind's icon, for a kind with no cleared model), the cause lit, the shell at work beside it.
 * `children` is what the page says under it (its status line and its groups of apps).
 */
export function MachineStation({ board, machine, children }: { board: Board; machine: Machine; children?: ReactNode }) {
  const { now, stale, settling } = useLab();
  const v = headline(board, { stale, settling, now: now(), machine });
  const data = useStationData(board, v);
  const name = machine.name;
  const { el, on } = useMount(
    data,
    (lp, host, assets, first) => lp.mountMachine(host, { machine: name, data: first, assets, onNavigate: go, onError: quiet }),
    (h, d) => h.update(d, name),
    name,
  );
  return (
    <div className={`mc-hero${on ? " on" : ""}`} role="group" aria-label={`${name} on its deck tray, pulled out of the station, with a module for each group of apps`}>
      <div className="lamp-mount" data-lamplight="machine" ref={el} />
      {children}
    </div>
  );
}
