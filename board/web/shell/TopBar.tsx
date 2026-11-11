// The top bar (IA.md §2): where you are, the scope chip when a machine is picked, Ask or search,
// Depth and You. Signed out it keeps only the crumb and Depth (the door shows no more).
import { useEffect, useMemo, useRef, useState } from "react";
import { Icon, IconButton, Planned } from "@/components/ui";
import { useLab } from "@/lib/lab";
import { href, PLACE_NAME, TABS, type Place } from "@/lib/routes";
import { KIND_ICON } from "./Rail";

function crumb(place: Place, tab: string, id: string | null, sheet: string | null): string {
  if (place === "machine") return (TABS.machine ?? []).find((t) => t.id === tab)?.label ?? (tab === "setup" ? "Set-up" : "Overview");
  if (place === "app") return `Supply › ${id}`;
  if (place === "home") return sheet === "add-machine" ? "Add a machine" : "Home";
  const t = (TABS[place] ?? []).find((x) => x.id === tab);
  return t ? `${PLACE_NAME[place]} › ${t.label}` : PLACE_NAME[place];
}

type Hit = { key: string; icon: string; name: string; what: string; to: string };

function Search() {
  const { board } = useLab();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLLabelElement>(null);
  const all = useMemo<Hit[]>(() => {
    const out: Hit[] = (["den", "supply", "data", "network", "people", "activity", "settings"] as Place[]).flatMap((p) =>
      (TABS[p] ?? []).filter((t) => !t.planned).map((t) => ({ key: `${p}/${t.id}`, icon: "i-layers", name: `${PLACE_NAME[p]} › ${t.label}`, what: "place", to: href(p, t.id) })),
    );
    if (board.state === "ok") {
      for (const m of board.doc.machines) out.push({ key: `m/${m.name}`, icon: KIND_ICON[m.kind], name: m.name, what: "machine", to: href("machine", "", m.name) });
      for (const t of board.doc.apps)
        if (t.installed) out.push({ key: `app/${t.id}`, icon: t.holo ? `i-${t.holo}` : "i-module", name: `${t.job} · ${t.app}`, what: "app", to: href("app", "", t.id) });
    }
    return out;
  }, [board]);
  const words = q.trim().toLowerCase();
  const hits = words ? all.filter((h) => h.name.toLowerCase().includes(words)).slice(0, 8) : [];
  useEffect(() => {
    const away = (e: PointerEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, []);
  const go = (to: string) => {
    window.location.hash = to;
    setQ("");
    setOpen(false);
  };
  return (
    <label
      ref={box}
      className="sh-search"
      title="Ask or search: type a name to find an app, a machine or a place. Asking VECTOR in plain words (“make room for photos”) for a plan you approve is planned."
    >
      <Icon id="i-ask" size={20} />
      <input
        type="search"
        placeholder="Ask VECTOR or search"
        aria-label="Ask VECTOR or search"
        title="Ask VECTOR or search the lab"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && hits[0]) go(hits[0].to);
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && words && (
        <ul className="sh-found" aria-label="Found">
          {hits.map((h) => (
            <li key={h.key}>
              <a href={h.to} title={`Open ${h.name}`} onClick={() => go(h.to)}>
                <Icon id={h.icon} size={20} />
                <span>{h.name}</span>
                <span className="muted">{h.what}</span>
              </a>
            </li>
          ))}
          {!hits.length && (
            <li className="none">
              Nothing by that name. Asking VECTOR <Planned hint="Planned: VECTOR's plans you approve (IA.md, item 4)" />
            </li>
          )}
        </ul>
      )}
    </label>
  );
}

function You() {
  const { session, signOut } = useLab();
  const s = session.state === "ok" ? session.doc : null;
  const others = s ? s.browsers.length : 0;
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const away = (e: PointerEvent) => ref.current?.open && !ref.current.contains(e.target as Node) && (ref.current.open = false);
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, []);
  const close = () => ref.current && (ref.current.open = false);
  return (
    <details className="menu end um" ref={ref}>
      <summary title={`You: signed in on this browser${s?.browser ? ` (${s.browser.name})` : ""} as this lab's owner. Press for your signed-in browsers and sign out.`} aria-label="You">
        <Icon id="i-user" move="beat" />
      </summary>
      <div className="menu-list">
        <a href="#people/ways" onClick={close} title="This browser: signed in as the lab's owner with a one-time code from the server. Opens People › Ways in.">
          <span className="face" aria-hidden="true">
            <Icon id="i-user" size={16} />
          </span>
          <span>{s?.browser?.name ?? "This browser"}</span>
          <span className="st ok">
            <Icon id="s-ok" size={16} />
            OWNER
          </span>
        </a>
        <a href="#people/ways" onClick={close} title={`Your signed-in browsers: ${others}, each with a sign-out (People › Ways in)`}>
          <Icon id="i-browser" size={20} />
          <span>Signed-in browsers</span>
          <span className="st unk">{others}</span>
        </a>
        <a
          href="#home"
          title="Sign out here: this browser goes back to the door"
          onClick={(e) => {
            e.preventDefault();
            close();
            void signOut();
          }}
        >
          <Icon id="i-signout" size={20} />
          <span>Sign out</span>
          <span />
        </a>
      </div>
    </details>
  );
}

export function TopBar({ signedIn }: { signedIn: boolean }) {
  const { route, board, scope, clearScope, drawer, setDrawer } = useLab();
  const machinePage = route.place === "machine";
  const scoped = signedIn && !!scope && !machinePage && route.place !== "home" && !!TABS[route.place];
  const labName = board.state === "ok" ? board.doc.lab.name : "MYLAB";
  const page = signedIn ? crumb(route.place, route.tab, route.id, route.sheet) : route.place === "signin" ? "Sign in" : "The door";
  return (
    <header className="sh-top">
      <h1 className="sh-crumb" title="Where you are: the lab or a machine, then the place">
        <a href={machinePage ? href("machine", "", route.id) : "#home"} title={machinePage ? `${route.id}'s page` : "Back to Home"}>
          {machinePage ? route.id : labName}
        </a>
        <span className="sh-csep" aria-hidden="true">
          ›
        </span>
        <span>{page}</span>
      </h1>
      {scoped && (
        <span className="sh-scope" title="These places are lab-wide; you picked a machine in the rail, so only its things are shown">
          <Icon id="i-filter" size={16} />
          <span>
            only <b>{scope}</b>
          </span>
          <IconButton icon="i-cancel" size={16} label="Show the whole lab" hint="Show the whole lab again" onClick={clearScope} />
        </span>
      )}
      {signedIn && <Search />}
      <IconButton
        icon="i-layers"
        label="Depth"
        hint="Depth: the commands, files, units and logs behind this page, one press away"
        className="sh-depth has"
        kind={drawer === "depth" ? "on" : undefined}
        aria-expanded={drawer === "depth"}
        aria-controls="sh-depthd"
        onClick={() => setDrawer(drawer === "depth" ? null : "depth")}
      />
      {signedIn && <You />}
    </header>
  );
}
