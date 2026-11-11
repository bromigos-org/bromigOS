// Home's hero: the mount point for Lamplight, the living station. Its module mounts here in its
// own change; until then the hero's frame carries the lab's plain state: its one status line
// (lib/words.ts), how many machines, and when the server read itself. Nothing here is drawn
// from data the server didn't send.
import type { Board } from "@/lib/api/types";
import { useLab } from "@/lib/lab";
import { ago, clock } from "@/lib/time";
import { headline } from "@/lib/words";

export function Lamplight({ board }: { board: Board }) {
  const { now, stale, settling } = useLab();
  const t = now();
  const v = headline(board, { stale, settling, now: t });
  const n = board.machines.length;
  return (
    <section className="stage lamp" aria-label="The lab" title="Lamplight, the lab as a living station: each machine a module of the post. Its scene is being built; the lab's state shows here meanwhile.">
      <div className="lamp-mount" data-lamplight="mount">
        <p className="lamp-wait" title="Lamplight's scene isn't built into this page yet. Planned.">
          <span className="pl" title="Planned: Lamplight, the living station, mounts here">planned</span>
          LAMPLIGHT
        </p>
      </div>
      <div className="st-top">
        <span className="over" title={`${n} bromigOS machine${n === 1 ? " is" : "s are"} in this lab`}>
          {n} MACHINE{n === 1 ? "" : "S"}
        </span>
        <p className={`verdict${v.look ? ` ${v.look}` : ""}`} title={v.hint} role="status">
          {v.words}
        </p>
        {board.at > 0 ? (
          <span className="chip" title={`When the server last read itself: ${clock(board.at)}, in this browser's time zone`}>
            {clock(board.at)} · {ago(board.at, t).toUpperCase()}
          </span>
        ) : (
          <span className="chip" title="The server hasn't said when it last read itself">
            NOT READ YET
          </span>
        )}
      </div>
      <span className="h-scan" aria-hidden="true" />
      <span className="h-edge" aria-hidden="true" />
    </section>
  );
}
