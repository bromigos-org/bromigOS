// The app shell (IA.md §2, the prototype's .shell): the rail, the top bar, one page at a time,
// the activity strip along the bottom, and the two drawers. Signed out, it is the door: no rail,
// no strip, no search, no You.
import { useEffect, type ReactNode } from "react";
import { Icon, IconButton, Planned } from "@/components/ui";
import { depthFor } from "@/lib/depth";
import { useLab } from "@/lib/lab";
import { href, TABS, type Place } from "@/lib/routes";
import { ActivityDrawer, Strip } from "./Activity";
import { Rail } from "./Rail";
import { TopBar } from "./TopBar";

export function DepthDrawer({ signedIn }: { signedIn: boolean }) {
  const { route, drawer, setDrawer } = useLab();
  if (drawer !== "depth") return null;
  return (
    <aside className="sh-drawer sh-dright" id="sh-depthd" aria-label="Depth">
      <div className="sh-sheethead">
        <b>
          <Icon id="i-layers" size={16} />
          DEPTH
        </b>
        <IconButton icon="i-cancel" label="Close Depth" hint="Close the Depth drawer" onClick={() => setDrawer(null)} />
      </div>
      {depthFor(route, signedIn).map((d) => (
        <div className="dp-item" key={d.title} title={d.hint}>
          <h3>
            <span>{d.title}</span>
          </h3>
          <pre>
            {d.lines.map((l) => (
              <span key={l.text} className="dp-line">
                {l.text}
                {l.note && <span className="muted">{`   # ${l.note}`}</span>}
                {l.planned && <Planned hint="Planned: not on main yet" />}
                {"\n"}
              </span>
            ))}
          </pre>
        </div>
      ))}
    </aside>
  );
}

/** A place's tabs, as one row: the lit one is where you are; a planned one is dim and not a link. */
export function Tabs({ place, id, label }: { place: Place; id?: string | null; label: string }) {
  const { route } = useLab();
  const tabs = TABS[place] ?? [];
  const cur = place === "machine" && route.tab === "setup" ? "" : route.tab; // Set-up stands in for Overview
  return (
    <nav className="sh-tabs" aria-label={label}>
      {tabs.map((t) =>
        t.planned ? (
          <span key={t.id} className="sh-tab off" title={t.hint}>
            {t.label}
            <Planned hint={t.hint} />
          </span>
        ) : (
          <a
            key={t.id}
            className={`sh-tab${cur === t.id ? " on" : ""}`}
            href={href(place, t.id, id ?? null)}
            title={t.hint}
            aria-current={cur === t.id ? "page" : undefined}
          >
            {t.label}
          </a>
        ),
      )}
    </nav>
  );
}

/** A sheet over its page (Add, Stacks, Remove, a job): the page under it dims. */
export function Sheet({ title, close, closeHint, children }: { title: string; close: string; closeHint: string; children: ReactNode }) {
  return (
    <section className="page sh-sheet" aria-label={title} role="dialog">
      <div className="sh-sheethead">
        <h2>{title}</h2>
        <a className="ib" href={close} title={closeHint} aria-label="Close">
          <Icon id="i-cancel" move="beat" />
        </a>
      </div>
      {children}
    </section>
  );
}

export function Shell({ signedIn, children }: { signedIn: boolean; children: ReactNode }) {
  const { drawer, setDrawer } = useLab();
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(null);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [setDrawer]);
  return (
    <div className="proto">
      <div className={`shell${signedIn ? "" : " signed-out"}${drawer === "activity" ? " act-open" : ""}${drawer === "depth" ? " depth-open" : ""}`}>
        {signedIn && <Rail />}
        <div className="sh-main">
          <TopBar signedIn={signedIn} />
          <main className="sh-view" id="view">
            {children}
          </main>
          {signedIn && <Strip />}
        </div>
      </div>
      <DepthDrawer signedIn={signedIn} />
      {signedIn && <ActivityDrawer />}
    </div>
  );
}
