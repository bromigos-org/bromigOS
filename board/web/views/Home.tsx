// Home (IA.md §2): "Is the lab all right, and what do I do first?" The hero (Lamplight), one
// status line, NEEDS YOU (only what a person can act on, each with its machine), This week
// (planned), and a tile per machine with its readings.
import { Boundary } from "@/components/Boundary";
import { Lamplight } from "@/components/Lamplight";
import { NoBoard } from "@/components/NoBoard";
import { Icon, Planned, State } from "@/components/ui";
import type { Board, Machine, NeedsYou } from "@/lib/api/types";
import { useLab } from "@/lib/lab";
import { href } from "@/lib/routes";
import { ago, stale } from "@/lib/time";
import { PART_WORDS } from "@/lib/words";
import { KIND_ICON } from "@/shell/Rail";

function NeedRow({ n, machine }: { n: NeedsYou; machine?: Machine }) {
  const go = n.go ? `#${n.go}` : href("machine", "", n.machine);
  return (
    <div className="lb-need" title={`On ${n.machine}: ${n.words}.${n.detail ? ` ${n.detail}` : ""}`}>
      <span className="hm-ic" title={`On ${n.machine}`}>
        <Icon id={machine ? KIND_ICON[machine.kind] : "i-module"} size={20} />
      </span>
      <span>
        {n.words} · {n.machine}
        {n.detail && <span className="d">{n.detail}</span>}
      </span>
      <a className="ib" href={go} title={`Open it where it is${n.go ? "" : `: ${n.machine}'s page`}`} aria-label={`Open: ${n.words}`}>
        <Icon id="i-open" move="out" />
      </a>
    </div>
  );
}

function Needs({ b }: { b: Board }) {
  const byName = new Map(b.machines.map((m) => [m.name, m]));
  const items = b.needs_you;
  if (b.status.state === "setup") {
    const here = b.machines.find((m) => m.here) ?? b.machines[0];
    return (
      <section className="panel hm-needs" title="What to do first: this server has nothing installed yet">
        <h2 className="ph">
          <span>FIRST</span>
        </h2>
        <div className="lb-need" title={`${here?.name}'s Set-up: does the plan fit, and what is still off`}>
          <span className="hm-ic">
            <Icon id="i-rack" size={20} />
          </span>
          <span>
            Set up <b>{here?.name}</b>: pick what it runs
          </span>
          <a className="ib" href={href("machine", "setup", here?.name ?? null)} title={`Open ${here?.name}'s Set-up`} aria-label={`Set up ${here?.name}`}>
            <Icon id="i-open" move="out" />
          </a>
        </div>
      </section>
    );
  }
  // "nothing needs you" is said only when both the alerts and the jobs were read
  const blind = b.unread.filter((p) => p === "alerts" || p === "jobs");
  return (
    <section className={`panel hm-needs${items.length ? " is-warn" : ""}`} title="Needs you, across the lab: only what a person can act on, each with its machine">
      <h2 className="ph">
        <span>NEEDS YOU · {items.length}</span>
        {!items.length && !blind.length && <State shape="ok" word="nothing" hint="Nothing needs you: the alerts and the jobs were read, and none waits for a person" />}
        {blind.length > 0 && <State shape="unknown" word="can't check" hint={`The server couldn't read ${blind.map((p) => PART_WORDS[p]).join(" or ")} this time, so there may be more that needs you`} />}
      </h2>
      {blind.map((p) => (
        <p key={p} className="small muted hm-blind">
          {PART_WORDS[p][0].toUpperCase() + PART_WORDS[p].slice(1)} couldn't be read{b.why[p] ? `: ${b.why[p]}` : ""}.
        </p>
      ))}
      {items.map((n) => (
        <NeedRow key={n.id} n={n} machine={byName.get(n.machine)} />
      ))}
      {!!items.length && (
        <p className="small muted hm-plans" title="VECTOR's plans: he reads an alarm, writes the steps as a job, checks what it needs, and waits for your approval. Planned.">
          VECTOR's plans for these <Planned hint="Planned: VECTOR's plans you approve (IA.md, item 4)" />
        </p>
      )}
    </section>
  );
}

const WEEK = [
  ["Uptime", "Uptime across the lab's apps this week, from Uptime's checks"],
  ["Backups", "Nightly backups that worked this week, of seven"],
  ["Updates", "Updates applied this week"],
  ["Fixed itself", "What bromigOS put right by itself this week"],
  ["Power", "Watts across the lab, and the month's cost as an estimate"],
];

function Week() {
  return (
    <section className="panel hm-week" title="This week in the lab: what ran, what was proven, what fixed itself; sent to BRODEC on Mondays if you want it. Planned: the weekly lab report.">
      <h2 className="ph">
        <span>
          <Icon id="i-snooze" size={16} />
          THIS WEEK
        </span>
        <Planned hint="Planned: the weekly lab report (IA.md, item 17)" />
      </h2>
      <div className="hm-wk">
        {WEEK.map(([k, hint]) => (
          <div className="rd" key={k} title={`${hint}. Planned: nothing is measured for it yet.`}>
            <span className="k">{k}</span>
            <span className="v q">
              ·
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function MachineTile({ m, now }: { m: Machine; now: number }) {
  const r = m.readings;
  const old = !!r && stale(r.at, r.max_age_s, now);
  const warn = m.state === "warn" || m.state === "down";
  const read = (icon: string, v: number | null, unit: string, what: string) =>
    v === null ? null : (
      <span className={`spec${old ? " q" : ""}`} title={`${what}: ${v} ${unit}, read ${ago(r!.at, now)}${old ? ", older than it should be" : ""}`}>
        <Icon id={icon} size={16} />
        {v} {unit}
      </span>
    );
  return (
    <a
      className={`hm-m${warn ? " warn" : ""}`}
      href={href("machine", "", m.name)}
      title={`${m.name}${m.roles.length ? `: ${m.roles.join(", ")}` : ""}. ${m.state_word}.${m.here ? " This page is served by it." : ""} Opens its page.`}
    >
      <span className="hm-mh">
        <Icon id={KIND_ICON[m.kind]} />
        <b>{m.name}</b>
        <State shape={m.state} word={m.state_word} />
      </span>
      <span className="hm-mr">
        {r ? (
          <>
            {read("i-chip", r.cpu_pct, "%", "Processor busy")}
            {read("i-memory", r.ram_pct, "%", "Memory in use")}
            {read("i-temp", r.temp_c, "°C", "Hottest drive")}
          </>
        ) : (
          <span className="spec q" title="Processor, memory and heat aren't measured for this machine yet">
            <Icon id="s-unk" size={16} />
            no readings
          </span>
        )}
      </span>
      <span className="hm-mf">
        {m.here && (
          <span className="hm-ic" title="The lab's page is on this machine right now">
            <Icon id="i-lab" size={16} />
          </span>
        )}
        <span>
          {m.apps === null ? "apps unknown" : `${m.apps} app${m.apps === 1 ? "" : "s"}`}
          {r && ` · ${ago(r.at, now)}`}
        </span>
      </span>
    </a>
  );
}

export function Home() {
  const { board, now } = useLab();
  if (board.state === "loading") return null;
  if (board.state === "error") return <NoBoard error={board.error} />;
  const b = board.doc;
  const t = now();
  return (
    <>
      <Boundary what="The lab's status">
        <Lamplight board={b} />
      </Boundary>
      <div className="hm-grid">
        <Boundary what="What needs you">
          <Needs b={b} />
        </Boundary>
        <Boundary what="This week">
          <Week />
        </Boundary>
      </div>
      <Boundary what="The machines">
        <div className="hm-ms" role="list" aria-label="The machines">
          {b.machines.map((m) => (
            <div role="listitem" key={m.name} className="hm-mi">
              <MachineTile m={m} now={t} />
            </div>
          ))}
        </div>
      </Boundary>
    </>
  );
}
