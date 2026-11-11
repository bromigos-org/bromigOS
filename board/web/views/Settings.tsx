// Settings (IA.md §2): "How is the lab set to…?" Only what is real today, and all of it
// read-only: the page shows how the server is set, and the file or command that changes it.
//
// - Lab: the lab's name and address, the door, the world the page wears, and what root lets
//   this page do ([board] in /etc/bromigos/server.toml, as the board carries it).
// - Notifications: where alerts go and each channel's quiet hours (`bromigos alerts channels`,
//   which `bromigos alerts --json` carries), and the checks that raise them.
// - Mascot: STATIC's three modes, and the command that sets them on a computer.
//
// Nothing here is a switch: the service has no route that changes a setting.
import { Boundary } from "@/components/Boundary";
import { NoBoard } from "@/components/NoBoard";
import { Icon, Planned, State } from "@/components/ui";
import type { Board, Channel, Check } from "@/lib/api/types";
import { useLab } from "@/lib/lab";
import { ago, when } from "@/lib/time";
import { shownUrl } from "@/lib/url";
import { Unread } from "./Machine";

// ---------------------------------------------------------------- Lab

/** What the page may ask of the server, in root's own words, with what each one does. */
const ACTIONS: { word: string; name: string; does: string }[] = [
  { word: "restart", name: "Restart an app", does: "stops an app's services and starts them again" },
  { word: "add", name: "Add an app", does: "installs an app from the catalogue" },
  { word: "remove", name: "Remove an app", does: "removes an app and keeps its data" },
  { word: "delete-data", name: "Delete an app's data", does: "removes an app with its data; each time it also asks for a fresh code from the server" },
];

function Lab({ b }: { b: Board }) {
  const s = b.settings;
  return (
    <div className="stack st-set">
      <section className="panel" title="How this lab is named and reached, and what the page shows before sign-in">
        <h2 className="ph">
          <span>THIS LAB</span>
          <span className="tags">
            <span className="chip" title="These are read from the server. They are changed in its settings file, as root, not from this page">
              READ ONLY
            </span>
          </span>
        </h2>
        <div className="rdrow st-rd">
          <div className="rd" title="The lab's name. A single server is its own lab, so this is the server's name">
            <span className="k">Name</span>
            <span className="v m">{b.lab.name}</span>
            <span className="s">the server's name</span>
          </div>
          <div className="rd" title={b.lab.address ? `Where the lab answers on the home network: ${b.lab.address}` : "The server didn't say where the lab answers"}>
            <span className="k">Address</span>
            <span className={`v m${b.lab.address ? "" : " q"}`}>{b.lab.address ? shownUrl(b.lab.address) : "·"}</span>
            <span className="s">{b.lab.address ? "on the home network" : "not said"}</span>
          </div>
          <div className="rd" title={s ? (s.door ? "Before sign-in the page shows the door: the ways in and the household's apps to open" : "Before sign-in the page shows the ways in and no app") : "The server didn't say how the door is set"}>
            <span className="k">The door</span>
            <span className={`v m${s ? "" : " q"}`}>{s ? (s.door ? "shows the apps" : "shows no app") : "·"}</span>
            <span className="s">{s ? "before sign-in" : "not said"}</span>
          </div>
          <div className="rd" title={s ? `The world the page wears: ${s.world}. One of the eleven themes' names` : "The server didn't say which world the page wears"}>
            <span className="k">World</span>
            <span className={`v m${s ? "" : " q"}`}>{s ? s.world : "·"}</span>
            <span className="s">{s ? "the page's colours" : "not said"}</span>
          </div>
        </div>
        <pre>{`# /etc/bromigos/server.toml, as root\n[board]\ndoor = ${s ? s.door : true}        # false: the page shows no app before sign-in\nworld = "${s ? s.world : "wick"}"    # a theme's name`}</pre>
      </section>
      <section className="panel" title="What root lets this page ask the server to do. The page shows a control only for what is allowed, and root checks again on every request">
        <h2 className="ph">
          <span>WHAT THIS PAGE MAY DO</span>
          {!b.actionsSaid && <Planned hint="This server doesn't say what the page may do yet, so the page offers no control that changes anything" />}
        </h2>
        <ul className="rows wide st-may">
          {ACTIONS.map((a) => {
            const on = b.actions.includes(a.word);
            return (
              <li key={a.word} title={`${a.name}: ${a.does}. ${!b.actionsSaid ? "The server doesn't say whether the page may" : on ? "This server lets the page" : "This server doesn't let the page"}`}>
                <Icon id={a.word === "restart" ? "i-restart" : a.word === "add" ? "i-add" : "i-remove"} size={20} />
                <span className="grow">
                  <b>{a.name}</b>
                  <br />
                  <span className="small muted">{a.does}</span>
                </span>
                {!b.actionsSaid ? <State shape="unknown" word="not said" /> : on ? <State shape="ok" word="allowed" /> : <State shape="unknown" word="not allowed" />}
              </li>
            );
          })}
        </ul>
        <p className="small muted st-note">
          The page can't run a command, read a file or change a setting. Root decides the rest, in the same file:
        </p>
        <pre>{`# /etc/bromigos/server.toml, as root\n[board]\n${
          b.actionsSaid ? `# as this server has it now\nactions = ${JSON.stringify(b.actions.filter((w) => ACTIONS.some((a) => a.word === w)))}\n# for only restarts:  ` : ""
        }actions = ["restart"]\n# [] turns every action off; left out, it means ["restart", "add", "remove", "delete-data"]`}</pre>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- Notifications

const SEVERITY: Record<string, string> = { critical: "critical", needs_you: "needs you", info: "info" };
const list = (v: string[], none: string) => (v.length ? v.join(", ") : none);

function ChannelRow({ c, now }: { c: Channel; now: number }) {
  const broken = c.problems.length > 0 || !!c.last_error;
  const state = !c.on ? <State shape="unknown" word={c.read_only ? "not on this server" : "off"} /> : broken ? <State shape="warn" word="needs a look" /> : <State shape="ok" word="on" />;
  const what = c.read_only
    ? c.rules ?? "Its own rules, set on the phone"
    : `${list(c.severities.map((s) => SEVERITY[s] ?? s), "nothing")} · ${c.sources.length === 1 && c.sources[0] === "alerts" ? "every alert" : list(c.sources, "no source")}${c.detail ? ` · ${c.detail} detail` : ""}`;
  return (
    <li title={`${c.label}${c.read_only ? "" : ` (${c.name})`}: ${what}`}>
      <Icon id={c.type === "brodec" ? "i-phone" : "i-net"} size={20} />
      <span className="grow">
        <b>{c.read_only ? c.label : `${c.label} · ${c.name}`}</b>
        <br />
        <span className="small">{what}</span>
        {!c.read_only && (
          <>
            <br />
            <span className="small muted">
              {c.quiet ? `quiet ${c.quiet}${c.critical_in_quiet ? ", critical still goes" : ""}` : "no quiet hours"}
              {c.address ? ` · address ${c.address === "unknown" ? "not shown here" : c.address}` : ""}
              {` · last sent ${c.last_ok !== null ? ago(c.last_ok, now) : "never"}`}
            </span>
          </>
        )}
        {c.last_error && (
          <>
            <br />
            <span className="small warn">
              last problem{c.last_error.at !== null ? ` ${ago(c.last_error.at, now)}` : ""}: {c.last_error.why}
            </span>
          </>
        )}
        {c.problems.map((p) => (
          <span key={p} className="small warn st-prob">
            setting not used: {p}
          </span>
        ))}
      </span>
      {state}
    </li>
  );
}

const CHECK: Record<string, [string, "ok" | "unknown" | "warn"]> = { ran: ["looked", "ok"], skipped: ["doesn't apply here", "unknown"], failed: ["couldn't look", "warn"] };

function CheckRow({ c, now, raised }: { c: Check; now: number; raised: number }) {
  const [word, shape] = CHECK[c.state] ?? ["unknown", "unknown"];
  return (
    <li title={`The check ${c.check}: ${word}${c.error ? `. ${c.error}` : ""}${c.ran_at !== null ? `. ${when(c.ran_at, now)}` : ""}`}>
      <Icon id="i-gauge" size={20} />
      <span className="grow">
        <b>{c.check}</b>
        {c.error && (
          <>
            <br />
            <span className="small warn">{c.error}</span>
          </>
        )}
      </span>
      <span className="st-chk">
        {raised > 0 && <State shape="warn" word={`${raised} raised`} />}
        <State shape={shape} word={`${word}${c.ran_at !== null ? ` · ${ago(c.ran_at, now)}` : ""}`} />
      </span>
    </li>
  );
}

function Notifications({ b, now }: { b: Board; now: number }) {
  const n = b.notify;
  if (!n)
    return (
      <div className="unreach" role="status">
        <Icon id="s-unk" size={40} />
        <Unread what="The alerts and their channels" why={b.why.alerts} />
      </div>
    );
  const channels = n.channels ?? [];
  const own = channels.filter((c) => !c.read_only);
  const quiet = own.filter((c) => c.on && c.quiet);
  return (
    <div className="stack st-set">
      <section className="panel" title="Where alerts go, besides the computer's own notification. Each channel picks its severities, its sources and its quiet hours">
        <h2 className="ph">
          <span>
            <Icon id="i-phone" size={16} />
            CHANNELS · {channels.filter((c) => c.on).length} on
          </span>
          <span className="tags">
            <span className="chip" title="Channels are set at the server with sudo bromigos alerts channels. This page shows them and changes nothing">
              READ ONLY
            </span>
          </span>
        </h2>
        {n.channels ? (
          <ul className="rows wide st-ch">
            {channels.map((c) => (
              <ChannelRow key={c.name} c={c} now={now} />
            ))}
          </ul>
        ) : (
          <p className="small muted" role="status">
            This server's alerts don't list their channels.
          </p>
        )}
        {n.channels && !own.length && <p className="small muted st-note">No channel of this server's own yet. BRODEC's phone is one by itself when it is paired.</p>}
        <pre>{`bromigos alerts channels                        # each channel, its last message and last problem\nsudo bromigos alerts channels add discord       # asks for the webhook address, and never shows it\nsudo bromigos alerts channels test NAME         # sends one test message`}</pre>
      </section>
      <section className="panel" title="Quiet hours are each channel's own: what comes in them waits until they end. They are this server's clock">
        <h2 className="ph">
          <span>
            <Icon id="i-snooze" size={16} />
            QUIET HOURS
          </span>
        </h2>
        {quiet.length ? (
          <ul className="rows wide">
            {quiet.map((c) => (
              <li key={c.name} title={`${c.label} (${c.name}) is quiet ${c.quiet}, by the server's clock. ${c.critical_in_quiet ? "A critical alert still goes" : "A critical alert waits too"}`}>
                <Icon id="i-snooze" size={20} />
                <span className="grow">
                  <b>{c.quiet}</b> · {c.label} · {c.name}
                </span>
                <span className="chip">{c.critical_in_quiet ? "CRITICAL STILL GOES" : "EVERYTHING WAITS"}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="small">{own.some((c) => c.on) ? "No channel that is on has quiet hours: alerts go at any hour." : "No channel of this server's own is on, so there are no quiet hours to keep."}</p>
        )}
        <p className="small muted st-note">BRODEC's quiet hours are set on the phone. A channel's are set when it is added:</p>
        <pre>{`sudo bromigos alerts channels add webhook NAME --quiet 22:00-07:00 --critical-in-quiet`}</pre>
      </section>
      <section className="panel" title="The checks that raise alerts, and whether each could look the last time it ran">
        <h2 className="ph">
          <span>
            <Icon id="i-alert" size={16} />
            THE CHECKS · {n.checks.length}
          </span>
          {n.checked_at !== null && <span className="small muted">last pass {ago(n.checked_at, now)}</span>}
        </h2>
        {n.checks.length ? (
          <ul className="rows wide">
            {n.checks.map((c) => (
              <CheckRow key={c.check} c={c} now={now} raised={n.raised[c.check] ?? 0} />
            ))}
          </ul>
        ) : (
          <p className="small muted">The server listed no check.</p>
        )}
        <pre>{`bromigos alerts                 # what is raised now, and what each check found\n/etc/bromigos/alerts.toml       # thresholds, checks turned off, and the channels`}</pre>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- Mascot

const MODES: { word: string; does: string }[] = [
  { word: "on", does: "STATIC shows up, with his thought bubbles" },
  { word: "quiet", does: "his face, and no thought bubbles" },
  { word: "off", does: "he is nowhere, and Den TV's bumps are off too" },
];

function Mascot() {
  return (
    <div className="stack st-set">
      <section className="panel" title="STATIC, the Bromigos mascot: on, quiet or off. He is set on each computer, for each person who uses it">
        <h2 className="ph">
          <span>STATIC</span>
          <Planned hint="Planned: this page doesn't read or set STATIC yet. He isn't on the board's pages, and his setting lives on each computer. Today: the command below" />
        </h2>
        <ul className="rows wide">
          {MODES.map((m) => (
            <li key={m.word} title={`bromigos mascot ${m.word}: ${m.does}`}>
              <Icon id="i-user" size={20} />
              <span className="grow">
                <b>{m.word}</b>
                <br />
                <span className="small muted">{m.does}</span>
              </span>
              <code>bromigos mascot {m.word}</code>
            </li>
          ))}
        </ul>
        <p className="small muted st-note">He hosts Den TV's guide on a desktop. He is never on a confirmation, a password or an alert.</p>
        <pre>{`bromigos mascot                      # what he is now, and where his art comes from\n~/.config/bromigos/mascot.toml       # where the choice is kept, for each person`}</pre>
      </section>
    </div>
  );
}

/** The tabs of Settings that are built: Lab, Notifications ("") and Mascot. */
export const SETTINGS_BUILT = ["lab", "", "mascot"];

export function Settings({ tab }: { tab: string }) {
  const { board, now: clock } = useLab();
  const now = clock();
  if (board.state === "loading") return null;
  if (board.state === "error") return <NoBoard error={board.error} />;
  const b = board.doc;
  return (
    <Boundary what="Settings" again={tab}>
      {tab === "lab" ? <Lab b={b} /> : tab === "mascot" ? <Mascot /> : <Notifications b={b} now={now} />}
    </Boundary>
  );
}
