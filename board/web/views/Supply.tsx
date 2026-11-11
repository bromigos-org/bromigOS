// Supply (IA.md §2): what runs, what the lab can run, and what changes tonight. Installed and
// Browse read the board's tiles (`bromigos lab apps list --json`: every catalogue item, installed
// or not; DESIGN.md §3); Updates reads each tile's `update` and the system's update. The Add
// sheet shows what an app asks of the server and the exact command, and adds it from the page
// when the server says the page may (board.actions; the service's POST /api/actions).
import { useMemo, useState } from "react";
import { Boundary } from "@/components/Boundary";
import { NoBoard } from "@/components/NoBoard";
import { Icon, IconButton, IconLink, Planned, State } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import type { Board, Tile } from "@/lib/api/types";
import { holoIcon } from "@/lib/icons";
import { useLab } from "@/lib/lab";
import { href } from "@/lib/routes";
import { when } from "@/lib/time";
import { Sheet, Tabs } from "@/shell/Shell";
import { AppTile, PHASE, tileShape, Unread } from "./Machine";

const GB = 1024 ** 3;
const gb = (b: number) => (b / GB >= 10 ? Math.round(b / GB) : Math.round((b / GB) * 10) / 10);

/** The catalogue's groups, in the order Browse shows them (provision-catalogue.toml). */
const GROUPS: [string, string][] = [
  ["home", "HOME APPS"],
  ["media", "MEDIA"],
  ["games", "GAMES"],
  ["ai", "AI"],
  ["network", "NETWORK"],
  ["storage", "STORAGE"],
  ["lab-core", "LAB CORE"],
  ["brodec", "BRODEC"],
];

function Installed({ apps, server, scope }: { apps: Tile[]; server: string; scope: string | null }) {
  const { now } = useLab();
  const [sort, setSort] = useState<"name" | "memory">("name");
  const mine = apps.filter((t) => t.installed && (!scope || (t.machine ?? server) === scope));
  const ram = mine.map((t) => t.measured.ram_bytes).filter((x): x is number => typeof x === "number");
  const disk = mine.map((t) => t.measured.disk_bytes).filter((x): x is number => typeof x === "number");
  const up = mine.filter((t) => t.state === "ok").length;
  const sorted = [...mine].sort((a, z) => (sort === "memory" ? (z.measured.ram_bytes ?? -1) - (a.measured.ram_bytes ?? -1) : a.job.localeCompare(z.job)));
  return (
    <>
      <section className="panel" title="What runs: how many, and what they use, measured on the server">
        <div className="rdrow su-rd">
          <div className="rd" title="Installed apps, and how many are well: running, or set up when they have no service of their own">
            <span className="k">Well</span>
            <span className="v">
              {up}
              <small>of {mine.length}</small>
            </span>
          </div>
          <div className="rd" title="Memory the apps use now, from their services' cgroups. Apps that can't be measured aren't counted.">
            <span className="k">Memory</span>
            <span className={`v${ram.length ? "" : " q"}`}>
              {ram.length ? gb(ram.reduce((x, y) => x + y, 0)) : "·"}
              {ram.length > 0 && <small>GB</small>}
            </span>
            <span className="s">{ram.length < mine.length ? `${ram.length} of ${mine.length} measured` : "all measured"}</span>
          </div>
          <div className="rd" title="Disk the apps' data folders use, counted as du counts">
            <span className="k">Data</span>
            <span className={`v${disk.length ? "" : " q"}`}>
              {disk.length ? gb(disk.reduce((x, y) => x + y, 0)) : "·"}
              {disk.length > 0 && <small>GB</small>}
            </span>
            <span className="s">{disk.length < mine.length ? `${disk.length} of ${mine.length} measured` : "all measured"}</span>
          </div>
          <div className="rd" title="Sort the tiles">
            <span className="k">Sort</span>
            <span className="seg" role="radiogroup" aria-label="Sort the apps">
              {(["name", "memory"] as const).map((k) => (
                <span key={k}>
                  <input type="radio" name="su-sort" id={`su-sort-${k}`} checked={sort === k} onChange={() => setSort(k)} title={`Sort by ${k}`} />
                  <label htmlFor={`su-sort-${k}`} title={k === "name" ? "Sort by name" : "Hungriest first: the most memory at the top"}>
                    {k === "name" ? "Name" : "Memory"}
                  </label>
                </span>
              ))}
            </span>
          </div>
        </div>
      </section>
      {sorted.length ? (
        <div className="tiles apps">
          {sorted.map((t) => (
            <AppTile key={t.id} t={t} now={now()} />
          ))}
        </div>
      ) : (
        <div className="stub" title="Nothing installed yet">
          <Icon id="i-supply" size={40} />
          <p>Nothing is installed yet.</p>
          <a className="hw-go" href="#supply/browse" title="Supply › Browse: what this server can run">
            BROWSE
          </a>
        </div>
      )}
    </>
  );
}

function BrowseTile({ t }: { t: Tile }) {
  const ic = holoIcon(t.holo);
  const r = t.requires;
  return (
    <div className={`tile${t.installed ? " in" : ""}`} data-id={t.id} title={`${t.job}: ${t.app}.${t.installed ? " Installed." : ""}${r ? ` It asks for ${r.cpu} cores, ${r.ram_gb} GB of memory and ${r.disk_gb} GB of disk.` : ""}`}>
      {t.installed && <Icon id="s-done" size={16} className="tick" />}
      <span className={`plate${ic.known ? "" : " off"}`} aria-hidden="true">
        <Icon id={ic.id} />
      </span>
      <span className="nm">
        <b>{t.job}</b>
        <span className="app">{t.app}</span>
      </span>
      {r && (
        <span className="specs">
          <span className="spec" title={`It asks for ${r.ram_gb} GB of memory`}>
            <Icon id="i-memory" size={16} />
            {r.ram_gb} GB
          </span>
          <span className="spec" title={`It asks for ${r.disk_gb} GB of disk`}>
            <Icon id="i-drive" size={16} />
            {r.disk_gb} GB
          </span>
        </span>
      )}
      <span className="foot">
        {t.installed ? <State shape={tileShape(t)} word={t.state_word ?? "Unknown"} hint="Installed; its state as the server reads it" /> : <span />}
        {t.installed ? (
          <IconLink icon="i-open" href={href("app", "", t.id)} label={`${t.job}'s page`} hint={`${t.job}'s page: restart, logs, roll back, remove`} />
        ) : (
          <IconLink icon="i-add" move="drop" href={`#supply/add/${t.id}`} label={`Add ${t.job}`} hint={`Add ${t.job} (${t.app}): what it adds, what it asks of the server, and where it goes`} />
        )}
      </span>
    </div>
  );
}

function Browse({ apps }: { apps: Tile[] }) {
  const [q, setQ] = useState("");
  const words = q.trim().toLowerCase();
  const shown = useMemo(() => apps.filter((t) => !words || `${t.job} ${t.app} ${t.id}`.toLowerCase().includes(words)), [apps, words]);
  const known = new Set(GROUPS.map(([g]) => g));
  const groups: [string, string][] = [...GROUPS, ...[...new Set(shown.map((t) => t.group))].filter((g) => !known.has(g)).map((g): [string, string] => [g, (g || "other").toUpperCase()])];
  return (
    <>
      <label className="search" title="Find an app by its job or its name">
        <input className="field" type="search" placeholder="Find an app" aria-label="Find an app" title="Find an app by its job or its name" value={q} onChange={(e) => setQ(e.target.value)} />
      </label>
      {groups.map(([g, name]) => {
        const ts = shown.filter((t) => t.group === g);
        if (!ts.length) return null;
        return (
          <section key={g} className="su-group" aria-label={name}>
            <div className="grouphead" title={`${name}: ${ts.length} app${ts.length === 1 ? "" : "s"}`}>
              {name}
              <span className="meta">
                {ts.filter((t) => t.installed).length} of {ts.length} installed
              </span>
            </div>
            <div className="tiles">
              {ts.map((t) => (
                <BrowseTile key={t.id} t={t} />
              ))}
            </div>
          </section>
        );
      })}
      {!shown.length && <p className="muted">No app by that name in the catalogue.</p>}
    </>
  );
}

function Updates({ b, apps }: { b: Board; apps: Tile[] | null }) {
  const { now } = useLab();
  const installed = (apps ?? []).filter((t) => t.installed);
  const reporting = installed.filter((t) => t.update);
  const waiting = reporting.filter((t) => t.update!.available);
  const sys = b.updates;
  const [words, shape] = sys ? (PHASE[sys.phase] ?? [sys.phase, "unknown" as const]) : ["couldn't be read", "unknown" as const];
  return (
    <>
      <section className="panel" title="The system's own update: snapshot, update, check, and roll back by itself if it doesn't come back healthy">
        <h2 className="ph">
          <span>
            <Icon id="i-update" size={16} />
            THE SYSTEM
          </span>
          <State shape={shape} word={words} />
        </h2>
        {sys ? (
          <p className="small">
            {sys.auto ? "Updates by itself" : "Waits for you"}
            {sys.window ? `, restarting only between ${sys.window.replace("-", " and ")}` : ""}
            {sys.finished_at ? `; the last one finished ${when(sys.finished_at, now())}` : ""}.
            {sys.rollbacks > 0 ? ` ${sys.rollbacks} update${sys.rollbacks === 1 ? " was" : "s were"} rolled back.` : ""}
          </p>
        ) : (
          <Unread what="The system's update" why={b.why.updates} />
        )}
      </section>
      <section className="panel" title="The apps' updates: each behind a snapshot, with a way back. Planned: the update path (DESIGN.md §2).">
        <h2 className="ph">
          <span>
            <Icon id="i-updateall" size={16} />
            THE APPS
          </span>
          {apps && !reporting.length && <Planned hint="Planned: app updates behind a snapshot, with a way back (DESIGN.md §7, PR 5)" />}
        </h2>
        {!apps ? (
          <Unread what="The apps" why={b.why.apps} />
        ) : !reporting.length ? (
          <p className="small muted">The apps don't report updates yet.</p>
        ) : (
          <>
            {waiting.length > 0 && (
              <ul className="rows wide">
                {waiting.map((t) => (
                  <li key={t.id} title={`${t.job}: ${t.version ?? "?"} to ${t.update!.to ?? "?"}${t.update!.note ? `. ${t.update!.note}` : ""}`}>
                    <Icon id={holoIcon(t.holo).id} size={20} />
                    <span className="grow">
                      <b>{t.job}</b> {t.version} → {t.update!.to}
                      {t.update!.manual && <span className="small warn"> · by hand</span>}
                    </span>
                    <a className="hw-go" href={href("app", "", t.id)} title={`${t.job}'s page`}>
                      OPEN
                    </a>
                  </li>
                ))}
              </ul>
            )}
            {/* "up to date" is said only of the apps that report; the rest are named as not reporting */}
            <p className="small">
              {waiting.length ? "" : reporting.length === installed.length ? "Every app is up to date." : `No update is waiting for the ${reporting.length} app${reporting.length === 1 ? "" : "s"} that report${reporting.length === 1 ? "s" : ""} one.`}
              {reporting.length < installed.length ? ` ${installed.length - reporting.length} of ${installed.length} don't report updates yet.` : ""}
            </p>
          </>
        )}
      </section>
    </>
  );
}

function AddIt({ t }: { t: Tile }) {
  const { act } = useLab();
  const [state, setState] = useState<{ at: "idle" | "asking" | "started" | "refused"; words: string }>({ at: "idle", words: "" });
  return (
    <div className="su-add">
      <IconButton
        icon="i-add"
        move="drop"
        kind={state.at === "idle" || state.at === "refused" ? "big" : "off"}
        label={`Add ${t.job}`}
        hint={`Add ${t.job} (${t.app}): the server adds it, with what it needs, as one job in the activity strip`}
        aria-disabled={state.at === "asking" || state.at === "started"}
        onClick={() => {
          if (state.at === "asking" || state.at === "started") return;
          setState({ at: "asking", words: "" });
          act("add", t.id).then(
            (said) => setState({ at: "started", words: said.words || `Adding ${t.job}.` }),
            (e) => setState({ at: "refused", words: e instanceof ApiError ? e.words : "The server couldn't do that." }),
          );
        }}
      />
      <p className={state.at === "refused" ? "signin-err" : "small"} role="status">
        {state.at === "asking" ? "Asking the server…" : state.at === "started" ? `${state.words} Its steps are in the activity strip.` : state.words}
      </p>
    </div>
  );
}

function Add({ b, apps, id }: { b: Board; apps: Tile[]; id: string | null }) {
  const t = apps.find((x) => x.id === id);
  const may = !!t && !t.installed && b.actions.includes("add") && t.can.includes("add");
  return (
    <Sheet title={t ? `Add ${t.job}` : "Add"} close="#supply/browse" closeHint="Close: back to Supply › Browse">
      {!t ? (
        <p className="muted">No app called {id} is in the catalogue.</p>
      ) : (
        <div className="stack">
          <section className="panel" title={`${t.job}: ${t.app}`}>
            <div className="apphead">
              <span className="plate big" aria-hidden="true">
                <Icon id={holoIcon(t.holo).id} size={40} />
              </span>
              <div className="nm">
                <h2>{t.job.toUpperCase()}</h2>
                {t.app && <span className="chip">{t.app.toUpperCase()}</span>}
              </div>
            </div>
            {t.requires && (
              <div className="rdrow su-rd">
                <div className="rd" title="Cores it asks for">
                  <span className="k">Processor</span>
                  <span className="v">
                    {t.requires.cpu}
                    <small>cores</small>
                  </span>
                </div>
                <div className="rd" title="Memory it asks for">
                  <span className="k">Memory</span>
                  <span className="v">
                    {t.requires.ram_gb}
                    <small>GB</small>
                  </span>
                </div>
                <div className="rd" title="Disk it asks for to start">
                  <span className="k">Disk</span>
                  <span className="v">
                    {t.requires.disk_gb}
                    <small>GB</small>
                  </span>
                </div>
              </div>
            )}
          </section>
          <section className="panel" title="What adding it does: the plan first, then the install as one job in the activity strip">
            <h2 className="ph">
              <span>{t.installed ? "INSTALLED" : "ADD IT"}</span>
              {!may && !t.installed && <Planned hint="This server doesn't take adds from the page yet. Today: the commands below, at the server." />}
            </h2>
            {may && <AddIt t={t} />}
            {t.installed ? (
              <p className="small">{t.job} is installed already.</p>
            ) : (
              <pre>{`sudo bromigos lab apps add ${t.id} --plan   # what it adds, and what it asks of the server\nsudo bromigos lab apps add ${t.id}          # add it`}</pre>
            )}
          </section>
        </div>
      )}
    </Sheet>
  );
}

export function Supply({ tab, sheet, sheetId }: { tab: string; sheet: string | null; sheetId: string | null }) {
  const { board, scope } = useLab();
  if (board.state === "loading") return null;
  if (board.state === "error")
    return (
      <section className="page" aria-label="Supply">
        <Tabs place="supply" label="Supply" />
        <NoBoard error={board.error} />
      </section>
    );
  const b = board.doc;
  const apps = b.apps;
  return (
    <>
      <section className={`page${sheet ? " sh-under" : ""}`} aria-label="Supply" inert={sheet ? true : undefined}>
        <Tabs place="supply" label="Supply" />
        <Boundary what="Supply" again={tab}>
          {tab === "updates" ? (
            <Updates b={b} apps={apps} />
          ) : !apps ? (
            <div className="unreach" role="status">
              <Icon id="s-unk" size={40} />
              <Unread what="The apps" why={b.why.apps} />
            </div>
          ) : tab === "browse" ? (
            <Browse apps={apps} />
          ) : (
            <Installed apps={apps} server={b.server.name} scope={scope} />
          )}
        </Boundary>
      </section>
      {sheet === "add" && (
        <Boundary what="The Add sheet" again={sheetId ?? ""}>
          <Add b={b} apps={apps ?? []} id={sheetId} />
        </Boundary>
      )}
      {sheet === "stacks" && (
        <Sheet title="Stacks · Media" close="#supply/browse" closeHint="Close: back to Supply › Browse">
          <p className="muted" title="The media stack: films, shows and music wired together. Planned.">
            The media stack, wired for you <Planned hint="Planned: the Stacks sheet" />
          </p>
        </Sheet>
      )}
    </>
  );
}
