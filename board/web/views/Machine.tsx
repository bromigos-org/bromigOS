// A machine (IA.md §2): Overview ("What is this machine doing, and does it need me?"), Vitals ("Is
// it this machine, and which app?"), Hardware ("What is in this box?") and Set-up (first run).
// Every figure is the server's: the board's machine row, its tiles, and the drive, backup and
// update documents as their commands print them. What isn't read yet says so, or is planned.
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Boundary } from "@/components/Boundary";
import { MachineStation } from "@/components/Lamplight";
import { NoBoard } from "@/components/NoBoard";
import { Trend } from "@/components/Trend";
import { Icon, IconLink, Planned, State } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { BackupsStatus, Board, DriveHealth, Machine as M, SeriesName, Shape, Tile, UpdatesStatus, Vitals, VitalsRange } from "@/lib/api/types";
import { holoIcon } from "@/lib/icons";
import { useLab } from "@/lib/lab";
import { href } from "@/lib/routes";
import { ago, clock, span, stale, when } from "@/lib/time";
import { shownUrl } from "@/lib/url";
import { BACKUP_SHAPE, BACKUP_WORD, DRIVE_ALARM, DRIVE_SHAPE, headline, lastGoodCopy, worstDrive } from "@/lib/words";
import { Tabs } from "@/shell/Shell";

// ---------------------------------------------------------------- shared

const GB = 1024 ** 3;
const gb = (b: number) => (b / GB >= 10 ? Math.round(b / GB) : Math.round((b / GB) * 10) / 10);

/** A part of the board the server couldn't read this time: said plainly, with why when it said. */
export function Unread({ what, why }: { what: string; why?: string }) {
  return (
    <p className="small muted unread" role="status">
      {what} couldn't be read on the server{why ? `: ${why}` : ""}. The page asks again every 15 seconds.
    </p>
  );
}

function Fresh({ at, now }: { at: number; now: number }) {
  if (at <= 0)
    return (
      <span className="chip" title="The server hasn't said when it last read this">
        NOT READ YET
      </span>
    );
  return (
    <span className="chip" title={`When the server last read this: ${clock(at)}, in this browser's time zone. The page reads again every 15 seconds.`}>
      {clock(at)} · {ago(at, now).toUpperCase()}
    </span>
  );
}

/** An app's state as a shape: on its way (starting, updating) is the half ring, never the lit dot. */
export const tileShape = (t: Tile): Shape | "busy" =>
  t.state === "ok" ? "ok" : t.state === "starting" || t.state === "updating" ? "busy" : t.state === "degraded" ? "warn" : t.state === "down" ? "down" : "unknown";

// ---------------------------------------------------------------- Overview: the hero

// The hero is Lamplight's (components/Lamplight.tsx): the machine on its deck tray, pulled out of
// the station. Under it, this page's own status line and a module for each group of apps.

/** The catalogue's eight groups (provision-catalogue.toml), as the machine's modules under its hero. */
const GROUPS: { id: string; name: string; glyph: string; go?: string }[] = [
  { id: "lab-core", name: "LAB CORE", glyph: "g-rack" },
  { id: "network", name: "NETWORK", glyph: "g-cloud", go: "#network" },
  { id: "games", name: "GAMES", glyph: "g-gamepad", go: "#den/play" },
  { id: "media", name: "MEDIA", glyph: "g-monitor", go: "#den" },
  { id: "ai", name: "AI", glyph: "g-gpu" },
  { id: "storage", name: "STORAGE", glyph: "g-drive", go: "#data" },
  { id: "home", name: "HOME APPS", glyph: "g-house" },
  { id: "brodec", name: "BRODEC", glyph: "g-phone" },
];
function Hero({ b, m, apps, now }: { b: Board; m: M; apps: Tile[] | null; now: number }) {
  const { stale: old, settling } = useLab();
  const v = headline(b, { stale: old, settling, now, machine: m });
  const mods = GROUPS.map((g) => {
    const mine = (apps ?? []).filter((t) => t.installed && t.group === g.id);
    const up = mine.filter((t) => t.state === "ok").length;
    const bad = mine.some((t) => t.state === "degraded" || t.state === "down");
    return { ...g, n: mine.length, up, bad, names: mine.map((t) => t.job) };
  });
  const lit = mods.filter((x) => x.n).length;
  return (
    <MachineStation board={b} machine={m}>
      <div className="mgroups">
        <div className="st-top">
          <span className="over" title={`${lit} of the catalogue's eight groups have apps on ${m.name}`}>
            {apps ? `${lit} OF 8 GROUPS LIT` : "APPS NOT READ"}
          </span>
          <p className={`verdict${v.look ? ` ${v.look}` : ""}`} role="status" title={v.hint}>
            {v.words}
          </p>
          <Fresh at={b.at} now={now} />
        </div>
        <div className="mods">
          {mods.map((x) => {
            const body = (
              <>
                <svg className={`gl${x.n ? (x.bad ? " warn" : " live") : ""}`} viewBox="0 0 100 100" aria-hidden="true">
                  <use href={`#${x.glyph}`} />
                </svg>
                <span>
                  <b>{x.name}</b>
                  <i>{!apps ? "not read" : x.n ? (x.up === x.n ? `${x.n} running` : `${x.up} of ${x.n} running`) : "empty"}</i>
                </span>
                <Icon id={x.n && x.up === x.n ? "s-ok" : x.bad ? "s-warn" : "s-unk"} size={16} />
              </>
            );
            const hint = !apps
              ? `${x.name[0] + x.name.slice(1).toLowerCase()}: the apps couldn't be read, so this module can't say.`
              : x.n
              ? `${x.name[0] + x.name.slice(1).toLowerCase()}: ${x.names.join(", ")}. ${x.up === x.n ? "All running." : `${x.up} of ${x.n} running.`}${x.go ? " Press to open it." : ""}`
              : `${x.name[0] + x.name.slice(1).toLowerCase()}: nothing installed. Its module stays dim: an empty slot, not a lit prop.`;
            const cls = `mod${x.n ? " on" : ""}`;
            return x.go && x.n ? (
              <a key={x.id} className={cls} href={x.go} title={hint}>
                {body}
              </a>
            ) : (
              <div key={x.id} className={cls} title={hint}>
                {body}
              </div>
            );
          })}
        </div>
      </div>
    </MachineStation>
  );
}

// ---------------------------------------------------------------- Overview: the reading tiles

function StorageTile({ doc, why }: { doc: DriveHealth | null; why?: string }) {
  const drives = doc?.drives.filter((d) => d.present) ?? [];
  const worst = doc ? worstDrive(drives) : null;
  const alarm = !!worst && DRIVE_ALARM[worst.verdict];
  return (
    <a className={`panel rt wide${alarm ? " is-warn" : ""}`} href="#data" title="Storage: each drive's verdict, from bromigos storage health. Press for every drive (Data › Drives).">
      <h3>
        <span>
          <Icon id="i-storage" size={16} />
          STORAGE
        </span>
        {!doc ? (
          <State shape="unknown" word="couldn't be read" />
        ) : !drives.length ? (
          <State shape="unknown" word="no drives read" />
        ) : worst ? (
          <State shape={DRIVE_SHAPE[worst.verdict]} word={worst.words} />
        ) : (
          <State shape="ok" word="healthy" hint="Every connected drive was read, and each is healthy" />
        )}
      </h3>
      {doc ? (
        <ul className="dv">
          {drives.map((d) => (
            <li key={d.key} title={`${d.model} (${d.device}): ${d.words}. ${d.summary}`}>
              <Icon id="i-drive" size={16} />
              <span>
                <b>{d.device}</b> <span className="muted">{d.model}</span>
              </span>
              <State shape={DRIVE_SHAPE[d.verdict]} word={d.words} />
            </li>
          ))}
        </ul>
      ) : (
        <Unread what="The drives' health" why={why} />
      )}
    </a>
  );
}

function BackupsTile({ doc, why, now }: { doc: BackupsStatus | null; why?: string; now: number }) {
  const good = doc ? lastGoodCopy(doc) : null;
  const last = good !== null ? good * 1000 : null;
  const proven = doc?.proven_ts != null ? doc.proven_ts * 1000 : null;
  const testFailed = !!doc?.last_test?.failed;
  return (
    <a className={`panel rt${doc?.health.state === "attention" ? " is-warn" : ""}`} href="#data/backups" title={`Backups: ${doc ? doc.health.verdict : "they couldn't be read."} Press for Data › Backups.`}>
      <h3>
        <span>
          <Icon id="i-backup" size={16} />
          BACKUPS
        </span>
        <State shape={doc ? BACKUP_SHAPE[doc.health.state] : "unknown"} word={doc ? BACKUP_WORD[doc.health.state] : "couldn't be read"} />
      </h3>
      {doc ? (
        <>
          <div className="rd" title={last ? `The last good copy: ${when(last, now)}` : "No good copy yet"}>
            <span className="k">Last good copy</span>
            <span className={`v${last ? "" : " q"}`}>{last ? clock(last) : "none"}</span>
            <span className="s">{last ? ago(last, now) : doc.configured || doc.drives.length ? "not yet" : "backups are off"}</span>
          </div>
          <div className="tags">
            {doc.to && (
              <span className="chip" title={`Where the copies go: ${doc.to}`}>
                TO {doc.to.split(":")[0].toUpperCase()}
              </span>
            )}
            {testFailed ? (
              <span className="chip amber" title={`The last test restore failed${proven ? `; the last one that passed was ${ago(proven, now)}` : ""}`}>
                LAST TEST FAILED
              </span>
            ) : (
              <span className={`chip${proven ? " lit" : ""}`} title={proven ? `A test restore last proved the backup ${ago(proven, now)}` : "No restore has been proven yet"}>
                {proven ? `PROVEN ${ago(proven, now).toUpperCase()}` : "NOT PROVEN YET"}
              </span>
            )}
          </div>
        </>
      ) : (
        <Unread what="The backups" why={why} />
      )}
    </a>
  );
}

/** bromigos-server's PHASE_WORDS, the update's state as the server says it. Only "ok" and
 *  "nothing" are well; a phase on its way is the half ring; one this page doesn't know is unknown. */
export const PHASE: Record<string, [string, Shape | "busy"]> = {
  never: ["no update yet", "unknown"],
  updating: ["updating now", "busy"],
  reboot: ["restarting to check", "busy"],
  verify: ["checking", "busy"],
  ok: ["came back healthy", "ok"],
  nothing: ["nothing to update", "ok"],
  "rolled-back": ["rolled back", "warn"],
  attention: ["needs attention", "down"],
  failed: ["didn't finish", "warn"],
  waiting: ["waiting for you", "warn"],
  "reboot-waiting": ["restart waits for its window", "busy"],
};

function UpdatesTile({ doc, why, now }: { doc: UpdatesStatus | null; why?: string; now: number }) {
  const [words, shape] = doc ? (PHASE[doc.phase] ?? [doc.phase, "unknown" as Shape]) : ["couldn't be read", "unknown" as Shape];
  const at = doc?.finished_at ?? null;
  return (
    <a className={`panel rt${shape === "warn" || shape === "down" ? " is-warn" : ""}`} href="#supply/updates" title="Updates: the system's last update, as bromigos server status says it. Press for Supply › Updates.">
      <h3>
        <span>
          <Icon id="i-update" size={16} />
          UPDATES
        </span>
        <State shape={shape} word={words} />
      </h3>
      {doc ? (
        <>
          <div className="rd" title={at ? `The last update finished ${when(at, now)}` : "When the last update finished isn't known"}>
            <span className="k">Last update</span>
            <span className={`v${at ? "" : " q"}`}>{at ? clock(at) : "·"}</span>
            <span className="s">{at ? ago(at, now) : "not known"}</span>
          </div>
          <div className="tags">
            <span className="chip" title={`Updates are ${doc.mode || "set at the server"}${doc.window ? `, restarting only in the window ${doc.window}` : ""}`}>
              {doc.window ? `WINDOW ${doc.window}` : (doc.mode || "SET AT THE SERVER").toUpperCase()}
            </span>
            {doc.rollbacks > 0 && (
              <span className="chip amber" title={`${doc.rollbacks} update${doc.rollbacks === 1 ? " was" : "s were"} rolled back: the system didn't come back healthy, and put itself back`}>
                {doc.rollbacks} ROLLED BACK
              </span>
            )}
            <span className="chip" title="Apps update after the system, each behind a snapshot. Planned.">
              APPS AFTER IT
            </span>
            <Planned hint="Planned: app updates behind a snapshot (DESIGN.md §2)" />
          </div>
        </>
      ) : (
        <Unread what="The updates" why={why} />
      )}
    </a>
  );
}

// ---------------------------------------------------------------- Overview: apps

export function AppTile({ t, now }: { t: Tile; now: number }) {
  const ic = holoIcon(t.holo);
  const shape = tileShape(t);
  const old = t.reading && stale(t.reading.at, t.reading.max_age_s, now);
  return (
    <div className="tile in" data-id={t.id} title={`${t.job}: ${t.app}${t.version ? ` ${t.version}` : ""}. ${t.state_word ?? "Unknown"}.`}>
      <span className={`plate${ic.known ? "" : " off"}${shape === "warn" || shape === "down" ? " amber" : ""}`} aria-hidden="true">
        <Icon id={ic.id} className={shape === "busy" ? "pulse" : ""} />
      </span>
      <span className="nm">
        <a href={href("app", "", t.id)} title={`${t.job} (${t.app}): its page: what it takes, where its data lives, its logs, restart and remove`}>
          <b>{t.job}</b>
        </a>
        <State shape={shape} word={t.state_word ?? "Unknown"} />
      </span>
      {t.reading && (
        <span className={`read${old ? " muted" : ""}`} title={`${t.reading.text}: from ${t.reading.source}, ${ago(t.reading.at, now)}`}>
          {t.reading.text}
          {old && ` · ${ago(t.reading.at, now)}`}
        </span>
      )}
      <span className="foot">
        <span className="addr">{t.open ? shownUrl(t.open.url) : ""}</span>
        {t.open && <IconLink icon="i-open" href={t.open.url} label={`Open ${t.job}`} hint={`Open ${t.job} (${t.app}) at ${t.open.url}`} rel="noreferrer" />}
      </span>
    </div>
  );
}

function Overview({ b, m, now }: { b: Board; m: M; now: number }) {
  const { jobs } = useLab();
  const apps = b.apps ? b.apps.filter((t) => (t.machine ?? b.server.name) === m.name) : null;
  const needs = b.needs_you.filter((n) => n.machine === m.name);
  const fixed = b.fixed.filter((f) => f.machine === m.name);
  const pages = (apps ?? []).filter((t) => t.installed && t.open);
  const parts = (apps ?? []).filter((t) => t.installed && !t.open);
  const title = (id: string) => jobs.find((j) => j.id === id)?.title;
  return (
    <>
      <Boundary what={`${m.name}'s status`}>
        <Hero b={b} m={m} apps={apps} now={now} />
      </Boundary>
      {(needs.length > 0 || fixed.length > 0) && (
        <div className="mc-cols">
          {needs.length > 0 && (
            <section className="panel is-warn" title={`What on ${m.name} needs a person, cheapest step first`}>
              <h2 className="ph">
                <span>NEEDS YOU · {needs.length}</span>
              </h2>
              {needs.map((n) => (
                <div className="lb-need" key={n.id} title={`${n.words}${n.detail ? `: ${n.detail}` : ""}`}>
                  <Icon id="i-alert" size={20} className="warn" />
                  <span>
                    {n.words}
                    {n.detail && <span className="d">{n.detail}</span>}
                  </span>
                  <IconLink icon="i-open" href={n.job ? `#job/${n.job}` : n.go ? `#${n.go}` : "#activity"} label={`Open: ${n.words}`} hint="Open it where it is fixed" />
                </div>
              ))}
            </section>
          )}
          {fixed.length > 0 && (
            <section className="panel" title="What bromigOS put right by itself, and how to look closer">
              <h2 className="ph">
                <span>FIXED BY ITSELF · {fixed.length}</span>
              </h2>
              {fixed.map((f) => (
                <div className="lb-need" key={f.id} title={`${f.title ?? title(f.id) ?? "A job"}: ${f.words}${f.at ? `, ${when(f.at, now)}` : ""}`}>
                  <Icon id="i-undo" size={20} />
                  <span>
                    {f.title ?? title(f.id) ?? "A job"}
                    <span className="d">
                      {f.words}
                      {f.at ? ` · ${when(f.at, now)}` : ""}
                    </span>
                  </span>
                  <IconLink icon="i-open" href={`#job/${f.id}`} label={`Look closer: ${f.title ?? title(f.id) ?? f.words}`} hint="Look closer: the job's steps, and how it ended" />
                </div>
              ))}
            </section>
          )}
        </div>
      )}
      {m.here ? (
        <Boundary what="The storage, backups and updates readings">
          <div className="rtiles three">
            <StorageTile doc={b.storage} why={b.why.drives} />
            <BackupsTile doc={b.backups} why={b.why.backups} now={now} />
            <UpdatesTile doc={b.updates} why={b.why.updates} now={now} />
          </div>
        </Boundary>
      ) : (
        <p className="small muted mc-parts" title={`${m.name} serves this same page at its own name, with its drives, backups and updates`}>
          {m.name}'s drives, backups and updates are on its own page, at its own name.
        </p>
      )}
      <Boundary what="The apps">
        <div className="mc-apps">
          <div className="grouphead" title={`The apps on ${m.name} with a page of their own`}>
            <Icon id="i-supply" size={16} />
            APPS
            {apps && (
              <span className="meta">
                {pages.filter((t) => t.state === "ok").length} of {pages.length} running
              </span>
            )}
          </div>
          {!apps ? (
            <Unread what="The apps" why={b.why.apps} />
          ) : pages.length ? (
            <div className="tiles apps">
              {pages.map((t) => (
                <AppTile key={t.id} t={t} now={now} />
              ))}
            </div>
          ) : (
            <p className="small muted">Nothing with a page of its own yet. Supply › Browse has what this machine can run.</p>
          )}
        </div>
        {parts.length > 0 && (
          <div className="mc-parts">
            <div className="grouphead" title="Parts that run without a page of their own">
              <Icon id="i-module" size={16} />
              ALWAYS-ON PARTS
              <span className="meta">
                {parts.filter((t) => t.state === "ok").length} of {parts.length} running
              </span>
            </div>
            <div className="tags">
              {parts.map((t) => {
                const shape = tileShape(t);
                return (
                  <a key={t.id} className={`chip part${shape === "ok" ? "" : shape === "busy" ? " lit" : " amber"}`} href={href("app", "", t.id)} title={`${t.job} (${t.app}): ${t.state_word ?? "Unknown"}. Opens its page.`}>
                    <Icon id={holoIcon(t.holo).id} size={16} />
                    {shape !== "ok" && <span>{(t.state_word ?? "Unknown").toUpperCase()}</span>}
                    <span className="sr-only">
                      {t.job}: {t.state_word ?? "Unknown"}
                    </span>
                  </a>
                );
              })}
            </div>
          </div>
        )}
      </Boundary>
    </>
  );
}

// ---------------------------------------------------------------- Vitals

/** A ring of twenty cells (the installer's budget meter bent round): `lit` of them on. */
function ring(lit: number) {
  const n = Math.max(0, Math.min(20, Math.round(lit)));
  return n ? `${"8 2 ".repeat(n - 1)}8 ${200 - 10 * (n - 1) - 8}` : "0 200";
}

type Gauge = { key: string; icon: string; name: string; fig: string | null; unit: string; sub: string; cells: number; shape: Shape; word: string; s: string; hint: string };

function gauges(m: M): Gauge[] {
  const r = m.readings, hw = m.hardware;
  const g = (o: Omit<Gauge, "shape" | "word"> & { high: boolean }): Gauge => ({ ...o, shape: o.fig === null ? "unknown" : o.high ? "warn" : "ok", word: o.fig === null ? "not measured" : o.high ? "high" : "normal" });
  const cpu = r?.cpu_pct ?? null, used = r?.ram_used_bytes ?? null, total = r?.ram_total_bytes ?? (hw?.ram_gb ? hw.ram_gb * GB : null);
  const heat = r?.temp_c ?? null, nin = r?.net_in_mbps ?? null, nout = r?.net_out_mbps ?? null;
  const net = nin === null && nout === null ? null : (nin ?? 0) + (nout ?? 0);
  return [
    g({ key: "cpu", icon: "i-chip", name: "Processor", fig: cpu === null ? null : String(cpu), unit: "%", sub: hw?.cpu ? `OF ${hw.cpu} CORES` : "BUSY", cells: (cpu ?? 0) / 5, high: (cpu ?? 0) >= 90, s: r?.load1 != null ? `load ${r.load1}` : "", hint: `Processor: ${cpu ?? "not measured"}${cpu === null ? "" : " % busy"}. Each cell of the ring is a twentieth.` }),
    g({ key: "mem", icon: "i-memory", name: "Memory", fig: used === null ? (r?.ram_pct != null ? String(r.ram_pct) : null) : String(gb(used)), unit: used === null ? "%" : "GB", sub: total ? `OF ${gb(total)} GB` : "IN USE", cells: (r?.ram_pct ?? 0) / 5, high: (r?.ram_pct ?? 0) >= 90, s: used !== null && total ? `${gb(total - used)} GB free` : "", hint: "Memory in use: measured use, not what the apps' recipes ask for." }),
    g({ key: "heat", icon: "i-temp", name: "Heat", fig: heat === null ? null : String(heat), unit: "°C", sub: "HOTTEST DRIVE", cells: heat === null ? 0 : ((heat - 20) / 45) * 20, high: (heat ?? 0) >= 55, s: "", hint: "Heat: the hottest drive. The ring runs from 20 to 65 °C; 55 °C is where the disk watch notes it." }),
    g({ key: "net", icon: "i-net", name: "Network", fig: net === null ? null : String(Math.round(net)), unit: "", sub: "MBIT/S", cells: net === null ? 0 : Math.max(net > 0 ? 1 : 0, (net / 1000) * 20), high: false, s: net === null ? "" : `${Math.round(nin ?? 0)} in · ${Math.round(nout ?? 0)} out`, hint: "Network: megabits a second now, in and out. The ring counts against one gigabit a second." }),
  ];
}

const SERIES: { id: SeriesName; name: string; unit: string; icon: string; max?: number }[] = [
  { id: "cpu_pct", name: "Processor", unit: "%", icon: "i-chip", max: 100 },
  { id: "ram_pct", name: "Memory", unit: "%", icon: "i-memory", max: 100 },
  { id: "net_in_mbps", name: "Network in", unit: "Mbit/s", icon: "i-net" },
  { id: "net_out_mbps", name: "Network out", unit: "Mbit/s", icon: "i-net" },
  { id: "temp_c", name: "Drive heat", unit: "°C", icon: "i-temp" },
];
const RANGES: { id: VitalsRange; label: string; hint: string }[] = [
  { id: "24h", label: "24 H", hint: "The last 24 hours" },
  { id: "7d", label: "7 D", hint: "The last 7 days" },
  { id: "30d", label: "30 D", hint: "The last 30 days" },
];

function Trends({ m, now }: { m: M; now: number }) {
  const [range, setRange] = useState<VitalsRange>("24h");
  const [series, setSeries] = useState<SeriesName>("cpu_pct");
  const [doc, setDoc] = useState<{ state: "loading" } | { state: "ok"; v: Vitals } | { state: "none" } | { state: "error"; words: string }>({ state: "loading" });
  useEffect(() => {
    let live = true;
    setDoc({ state: "loading" });
    api()
      .vitals(m.name, range)
      .then(
        (v) => live && setDoc({ state: "ok", v }),
        (e) => live && setDoc(e instanceof ApiError && e.status === 404 ? { state: "none" } : { state: "error", words: e instanceof ApiError ? e.words : "The trends couldn't be read." }),
      );
    return () => {
      live = false;
    };
  }, [m.name, range]);
  const s = SERIES.find((x) => x.id === series)!;
  const pts = doc.state === "ok" ? doc.v.series[series] : undefined;
  const last = pts?.filter((p) => p[1] !== null).at(-1);
  return (
    <section className="panel vt-trends" title="One trend chart: pick the series and the range">
      <h2 className="ph">
        <span>
          <Icon id="i-uptime" size={16} />
          TRENDS
        </span>
        <span className="seg" role="radiogroup" aria-label="The range the trend shows">
          {RANGES.map((r) => (
            <span key={r.id}>
              <input type="radio" name="vt-range" id={`vt-r-${r.id}`} checked={range === r.id} onChange={() => setRange(r.id)} title={r.hint} />
              <label htmlFor={`vt-r-${r.id}`} title={r.hint}>
                {r.label}
              </label>
            </span>
          ))}
        </span>
      </h2>
      <span className="seg vt-series" role="radiogroup" aria-label="Which trend">
        {SERIES.map((x) => (
          <span key={x.id}>
            <input type="radio" name="vt-s" id={`vt-s-${x.id}`} checked={series === x.id} onChange={() => setSeries(x.id)} title={`Show the ${x.name.toLowerCase()} trend`} />
            <label htmlFor={`vt-s-${x.id}`} title={`Show the ${x.name.toLowerCase()} trend`}>
              {x.name}
            </label>
          </span>
        ))}
      </span>
      {doc.state === "ok" && pts ? (
        <div className="vt-ch">
          <div className="vt-chh">
            <span className="k">
              <Icon id={s.icon} size={16} />
              {s.name}
            </span>
            <b title={last ? `The newest reading, ${when(last[0], now)}` : "No reading in this range"}>{last ? `${last[1]} ${s.unit}` : "·"}</b>
          </div>
          <Trend name={s.name} unit={s.unit} points={pts} max={s.max} now={now} />
        </div>
      ) : (
        <div className="vt-none" title={doc.state === "none" ? "This server doesn't keep trends for the page yet. Planned." : undefined}>
          {doc.state === "loading" && <span>Reading…</span>}
          {doc.state === "none" && (
            <>
              <span>Trends aren't kept on this server yet.</span>
              <Planned hint="Planned: the board's trend history (GET /api/vitals)" />
            </>
          )}
          {doc.state === "error" && <span>{doc.words}</span>}
          {doc.state === "ok" && <span>This server doesn't keep the {s.name.toLowerCase()} trend.</span>}
        </div>
      )}
    </section>
  );
}

function VitalsTab({ b, m, now }: { b: Board; m: M; now: number }) {
  const gs = gauges(m);
  const hot = gs.filter((g) => g.shape === "warn");
  const r = m.readings;
  const old = !r || stale(r.at, r.max_age_s, now);
  const apps = (b.apps ?? []).filter((t) => t.installed && (t.machine ?? b.server.name) === m.name && t.measured.ram_bytes);
  const hungry = [...apps].sort((a, z) => (z.measured.ram_bytes ?? 0) - (a.measured.ram_bytes ?? 0))[0];
  const watching = b.needs_you.filter((n) => n.machine === m.name).length;
  const blind = b.unread.includes("alerts");
  const grafana = b.apps?.find((t) => t.id === "monitoring" && t.installed);
  const missing = gs.filter((g) => g.fig === null).length;
  return (
    <>
      <div className="stage vt-stage" role="group" aria-label={`${m.name}'s vital signs as four gauges`}>
        <div className="tilt">
          <div className="vt-gauges">
            {gs.map((g) => (
              <div key={g.key} className={`vt-g${g.fig === null || old ? " q" : ""}${g.shape === "warn" ? " warn" : ""}`} title={g.hint}>
                <span className="over">
                  <Icon id={g.icon} size={16} />
                  {g.name}
                </span>
                <svg className="vt-ring" viewBox="0 0 180 196" role="img" aria-label={g.fig === null ? `${g.name}: not measured` : `${g.name}: ${g.fig} ${g.unit} ${g.sub.toLowerCase()}`}>
                  <path className="g-beam vt-cone" d="M32 178H148L170 30H10z" />
                  <ellipse className="vt-em" cx="90" cy="178" rx="58" ry="10" />
                  <circle className="ring-track ring-cells" cx="90" cy="88" r="58" pathLength="200" strokeDasharray="8 2" strokeDashoffset="-1" transform="rotate(-90 90 88)" />
                  {g.fig !== null && <circle className="ring-done ring-cells" cx="90" cy="88" r="58" pathLength="200" strokeDasharray={ring(g.cells)} strokeDashoffset="-1" transform="rotate(-90 90 88)" />}
                  <text className="vt-fig" x="90" y="96">
                    {g.fig ?? "·"}
                    <tspan className="vt-u">{g.fig === null ? "" : g.unit}</tspan>
                  </text>
                  <text className="vt-sub" x="90" y="116">
                    {g.sub}
                  </text>
                </svg>
                <State shape={old && g.fig !== null ? "unknown" : g.shape} word={old && g.fig !== null ? `read ${ago(r!.at, now)}` : g.word} />
                <span className="vt-s">{g.s}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="st-top">
          <span className="over" title="Whose vitals these are">
            {[m.name.toUpperCase(), m.hardware?.cpu ? `${m.hardware.cpu} CORES` : "", m.hardware?.ram_gb ? `${m.hardware.ram_gb} GB` : ""].filter(Boolean).join(" · ")}
          </span>
          <p className={`verdict${old || (!hot.length && missing) ? " q" : hot.length ? " warn" : ""}`} role="status" title="The four gauges' one status line: the worst of them. Nominal is said only when all four are measured.">
            {!r || missing === gs.length
              ? "NOT MEASURED"
              : old
                ? `NOT READ FOR ${span(now - r.at).toUpperCase()}`
                : hot.length
                  ? `${hot.map((g) => g.name.toUpperCase()).join(", ")} HIGH`
                  : missing
                    ? `${gs.length - missing} OF ${gs.length} MEASURED`
                    : "VITALS NOMINAL"}
          </p>
          {r && <Fresh at={r.at} now={now} />}
        </div>
        <span className="h-scan" aria-hidden="true" />
        <span className="h-edge" aria-hidden="true" />
      </div>
      <Boundary what="The trend chart">
        <Trends m={m} now={now} />
      </Boundary>
      <div className="vt-row2">
        <section className="panel" title="Watts now, and the month's cost as an estimate at your price per kWh. Planned.">
          <h2 className="ph">
            <span>
              <Icon id="i-power" size={16} />
              POWER
            </span>
            <Planned hint="Planned: energy (IA.md, item 9)" />
          </h2>
          <div className="rd">
            <span className="v q">·</span>
            <span className="s">not measured yet</span>
          </div>
        </section>
        {hungry ? (
          <a className="panel vt-link" href={href("app", "", hungry.id)} title={`The app using the most memory on ${m.name}: ${hungry.job} (${hungry.app}). Opens its page.`}>
            <h2 className="ph">
              <span>
                <Icon id="i-supply" size={16} />
                HUNGRIEST
              </span>
            </h2>
            <div className="rd">
              <span className="v m">{hungry.job}</span>
              <span className="s">{gb(hungry.measured.ram_bytes ?? 0)} GB of memory</span>
            </div>
          </a>
        ) : (
          <section className="panel" title="No app's memory use is measured yet">
            <h2 className="ph">
              <span>HUNGRIEST</span>
            </h2>
            <div className="rd">
              <span className="v q">·</span>
              <span className="s">nothing measured</span>
            </div>
          </section>
        )}
        <a className="panel vt-link" href="#settings" title="The watches: what raises an alert, and its line (disk full, heat, backup age). They are set in Settings › Notifications.">
          <h2 className="ph">
            <span>
              <Icon id="i-alert" size={16} />
              WATCHES
            </span>
          </h2>
          <div className="rd">
            <span className={`v m${watching ? " w" : blind ? " q" : ""}`}>{watching ? `${watching} need${watching === 1 ? "s" : ""} you` : blind ? "can't check" : "all quiet"}</span>
            <span className="s">opens Settings</span>
          </div>
        </a>
        {grafana?.open ? (
          <a className="vt-graf" href={grafana.open.url} title={`Grafana, the lab's monitoring: every reading in depth. Opens it at ${grafana.open.url}.`} rel="noreferrer">
            <Icon id="i-gauge" />
            <span>
              <b>GRAFANA</b>
              <State shape="ok" word="installed" />
            </span>
            <Icon id="i-open" />
          </a>
        ) : (
          <div className="vt-graf" title="Grafana, the lab's monitoring, isn't installed: Monitoring in Supply adds it">
            <Icon id="i-gauge" />
            <span>
              <b>GRAFANA</b>
              <State shape="unknown" word="not installed" />
            </span>
            <IconLink icon="i-add" href="#supply/add/monitoring" label="Add Monitoring" hint="Add Monitoring (Prometheus and Grafana) from Supply" move="drop" />
          </div>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------- Hardware

function cellsOf(pct: number) {
  return <span className="cells" aria-hidden="true"><i style={{ "--lit": `${Math.max(0, Math.min(100, Math.round(pct / 5) * 5))}%` } as CSSProperties} /></span>;
}

/** The card's kind as the scan says it; its model isn't printed by any command yet. */
const GPU_KIND: Record<string, string> = { nvidia: "An NVIDIA card", amd: "An AMD card", intel: "An Intel card" };

function HardwareTab({ b, m, now }: { b: Board; m: M; now: number }) {
  const hw = m.hardware;
  // a reading older than it may be is not shown as how busy the machine is now
  const r = m.readings && !stale(m.readings.at, m.readings.max_age_s, now) ? m.readings : null;
  const unmeasured = m.readings ? `read ${ago(m.readings.at, now)}` : "not measured";
  // the drives are the drive-health report's (this server's only: it reads the drives it is on)
  const storage = m.here ? b.storage : null;
  const worst = storage ? worstDrive(storage.drives) : null;
  const drives = storage ? storage.drives.filter((d) => d.present) : null;
  const notRead = hw ? null : m.here && b.hardwareWhy ? `couldn't be read on the server: ${b.hardwareWhy}` : "not read";
  return (
    <>
      <div className="hw-parts">
        <section className="panel hw-part" title="The processor: its cores, and how busy they are now">
          <h2 className="ph">
            <span>
              <Icon id="i-chip" size={16} />
              PROCESSOR
            </span>
          </h2>
          <div className="rd">
            <span className={`v${hw?.cpu ? "" : " q"}`}>
              {hw?.cpu ?? "·"}
              <small>cores</small>
            </span>
            {r?.cpu_pct != null && cellsOf(r.cpu_pct)}
            <span className="s">{r?.cpu_pct != null ? `${r.cpu_pct} % busy` : unmeasured}</span>
            {notRead && <span className="s">{`What is in the box: ${notRead}`}</span>}
          </div>
          <a className="hw-go" href={href("machine", "vitals", m.name)} title="Vitals: how busy, over time">
            <Icon id="i-gauge" size={16} />
            VITALS
          </a>
        </section>
        <section className="panel hw-part" title="The memory: how much, and how much is in use">
          <h2 className="ph">
            <span>
              <Icon id="i-memory" size={16} />
              MEMORY
            </span>
          </h2>
          <div className="rd">
            <span className={`v${hw?.ram_gb ? "" : " q"}`}>
              {hw?.ram_gb ?? "·"}
              <small>GB</small>
            </span>
            {r?.ram_pct != null && cellsOf(r.ram_pct)}
            <span className="s">{r?.ram_pct != null ? `${r.ram_pct} % in use` : unmeasured}</span>
          </div>
          <a className="hw-go" href="#supply" title="Supply › Installed: the apps, and what each uses">
            <Icon id="i-supply" size={16} />
            BY APP
          </a>
        </section>
        <section className={`panel hw-part${worst && DRIVE_ALARM[worst.verdict] ? " is-warn" : ""}`} title="The drives in this box, and their verdicts in Data › Drives">
          <h2 className="ph">
            <span>
              <Icon id="i-drive" size={16} />
              DRIVES
            </span>
            {worst && <State shape={DRIVE_SHAPE[worst.verdict]} word={worst.words} />}
          </h2>
          <div className="rd">
            <span className={`v${drives?.length ? "" : " q"}`}>
              {drives?.length || "·"}
              <small>drives</small>
            </span>
            {drives?.length ? (
              <ul className="hw-drives">
                {drives.map((d) => (
                  <li key={d.key} title={`${d.device}: ${d.model}. ${d.words}`}>
                    <b>{d.device}</b> {d.model}
                  </li>
                ))}
              </ul>
            ) : (
              <span className="s">{drives ? "none connected" : m.here ? (b.unread.includes("drives") ? `couldn't be read${b.why.drives ? `: ${b.why.drives}` : ""}` : "not read") : "not read from here"}</span>
            )}
            {hw?.disk_gb != null && <span className="s" title="The free space where apps keep their data (/srv/apps), as the app manager's scan measured it">{`${hw.disk_gb} GB free for apps' data`}</span>}
          </div>
          <a className="hw-go" href="#data" title="Data › Drives: every drive's health">
            <Icon id="i-storage" size={16} />
            DATA
          </a>
        </section>
        <section className="panel hw-part" title="The graphics card, and who it is given to: the desktop, apps or virtual machines">
          <h2 className="ph">
            <span>
              <Icon id="i-gpu" size={16} />
              GRAPHICS CARD
            </span>
            {/* "none" only when the scan was read and found none */}
            {hw && !hw.gpu && <State shape="unknown" word="none" hint="The app manager's scan found no graphics card in this box" />}
            {!hw && <State shape="unknown" word="not read" hint="What is in the box couldn't be read this time" />}
          </h2>
          <p className="hw-no small">{hw?.gpu ? `${hw.gpu_name ?? GPU_KIND[hw.gpu_kind ?? ""] ?? "A graphics card"}${hw.gpu_vram_gb ? ` · ${hw.gpu_vram_gb} GB of its own memory` : ""}` : hw ? "The scan found no graphics card" : "Not read"}</p>
          <div className="seg hw-owner" title="Who the card is given to: the desktop, apps or virtual machines (Settings › Graphics on a desktop; hw vfio). Planned on this page.">
            <span className="chip">Desktop</span>
            <span className="chip">Apps</span>
            <span className="chip">VMs</span>
          </div>
          <Planned hint="Planned: giving the card to apps, games or VMs from this page (IA.md, item 18)" />
        </section>
      </div>
      <section className="panel" title="System versions: each update keeps a snapshot to go back to. Pin one, or boot the previous one. Planned on this page.">
        <h2 className="ph">
          <span>
            <Icon id="i-rollback" size={16} />
            SYSTEM VERSIONS
          </span>
          <Planned hint="Planned: the snapshots and going back, on this page (IA.md, item 11). Every update already snapshots, checks and rolls back by itself." />
        </h2>
        <p className="small muted">Every update takes a snapshot, checks the system came back, and rolls back by itself if not.</p>
      </section>
      <div className="hw-row">
        <span className="hw-dim" title="A docked phone at the server: its battery, signal and the apps it holds. Planned.">
          <Icon id="i-phone" size={20} />
          no docked phone
        </span>
        <Planned hint="Planned: the home phone at the server (IA.md, item 22)" />
      </div>
    </>
  );
}

// ---------------------------------------------------------------- Set-up

function SetUp({ m }: { m: M }) {
  return (
    <section className="panel" title={`${m.name}'s Set-up: does the plan fit, and what is still off?`}>
      <h2 className="ph">
        <span>SET-UP</span>
      </h2>
      <ol className="flow">
        <li title="Pick what this server runs: Supply › Browse shows what fits">
          <span>
            <span className="num">1</span>
            <Icon id="i-supply" size={20} />
          </span>
          Pick what it runs
          <a href="#supply/browse" title="Open Supply › Browse">
            Supply › Browse
          </a>
        </li>
        <li title="Pick where the nightly backup goes. Planned on this page; today it is set at the server.">
          <span>
            <span className="num">2</span>
            <Icon id="i-backup" size={20} />
          </span>
          Pick a backup place
          <Planned />
        </li>
        <li title="Pair your phone, so BRODEC reaches this server from anywhere. Planned on this page.">
          <span>
            <span className="num">3</span>
            <Icon id="i-phone" size={20} />
          </span>
          Pair a phone
          <Planned />
        </li>
      </ol>
    </section>
  );
}

// ---------------------------------------------------------------- the page

export function Machine({ name, tab }: { name: string; tab: string }) {
  const { board, now } = useLab();
  const t = now();
  const doc = board.state === "ok" ? board.doc : null;
  const m = useMemo(() => doc?.machines.find((x) => x.name === name) ?? null, [doc, name]);
  if (board.state === "loading") return null;
  if (board.state === "error") return <NoBoard error={board.error} />;
  if (!doc) return null;
  if (!m)
    return (
      <div className="unreach" title="No machine of this lab has that name">
        <Icon id="s-unk" size={40} />
        <p>No machine called {name} is in this lab.</p>
      </div>
    );
  const setup = tab === "setup" || (tab === "" && doc.status.state === "setup" && m.here);
  return (
    <>
      <Tabs place="machine" id={m.name} label={`${m.name}'s tabs`} />
      {tab === "vitals" ? <VitalsTab b={doc} m={m} now={t} /> : tab === "hardware" ? <HardwareTab b={doc} m={m} now={t} /> : setup ? <SetUp m={m} /> : <Overview b={doc} m={m} now={t} />}
    </>
  );
}
