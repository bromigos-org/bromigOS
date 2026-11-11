// Home's hero: Lamplight, the living station (bromigos-living-post, CONCEPT.md §E). Its module
// is being made mountable (`LampLight.mount(el, {...})`, `mountMachine`); until it lands, this
// is the mount point with the lab's plain state in the hero's frame: the verdict, how many
// machines, and when it was read. Nothing here is drawn from data the server didn't send.
import { useEffect, useRef } from "react";
import type { Board } from "@/lib/api/types";
import { useLab } from "@/lib/lab";
import { ago, clock, stale } from "@/lib/time";

/** The hero's one line: the worst state across the lab's machines (the phone's labStatusLine). */
export function verdict(b: Board, now: number): { words: string; look: "ok" | "warn" | "q"; hint: string } {
  if (b.status.state === "setup") return { words: "NOTHING INSTALLED YET", look: "q", hint: "Nothing is installed on this server yet: its Set-up shows what to do first" };
  if (b.status.state === "unknown" || stale(b.at, b.max_age_s, now))
    return { words: `NOT READ FOR ${ago(b.at, now).replace(" ago", "").toUpperCase()}`, look: "q", hint: "The board's last reading is older than it should be: what it shows may be out of date" };
  const bad = new Set(b.machines.filter((m) => m.state === "warn" || m.state === "down").map((m) => m.name));
  for (const n of b.needs_you) bad.add(n.machine);
  if (bad.size) return { words: `${bad.size} MACHINE${bad.size === 1 ? "" : "S"} NEED${bad.size === 1 ? "S" : ""} YOU`, look: "warn", hint: "The lab's one status line: the worst state across its machines" };
  return { words: "ALL MACHINES NOMINAL", look: "ok", hint: "The lab's one status line: nothing needs you on any machine" };
}

export function Lamplight({ board }: { board: Board }) {
  const { now } = useLab();
  const mount = useRef<HTMLDivElement>(null);
  const t = now();
  const v = verdict(board, t);
  const n = board.machines.length;
  useEffect(() => {
    // LampLight.mount(mount.current, { world, machines, needs, reduced }) goes here when the
    // module lands; it returns a handle whose update() takes each new board.
  }, []);
  return (
    <section className="stage lamp" aria-label="The lab" title="Lamplight, the lab as a living station: each machine a module of the post. Its scene is being built; the lab's state shows here meanwhile.">
      <div className="lamp-mount" ref={mount} data-lamplight="mount">
        <p className="lamp-wait" title="Lamplight's scene isn't built into this page yet. Planned.">
          <span className="pl" title="Planned: Lamplight, the living station, mounts here">planned</span>
          LAMPLIGHT
        </p>
      </div>
      <div className="st-top">
        <span className="over" title={`${n} bromigOS machine${n === 1 ? " is" : "s are"} in this lab`}>
          {n} MACHINE{n === 1 ? "" : "S"}
        </span>
        <p className={`verdict${v.look === "warn" ? " warn" : v.look === "q" ? " q" : ""}`} title={v.hint} role="status">
          {v.words}
        </p>
        <span className="chip" title={`When the board was last read: ${clock(board.at)}, in this browser's time`}>
          {clock(board.at)} · {ago(board.at, t).toUpperCase()}
        </span>
      </div>
      <span className="h-scan" aria-hidden="true" />
      <span className="h-edge" aria-hidden="true" />
    </section>
  );
}
