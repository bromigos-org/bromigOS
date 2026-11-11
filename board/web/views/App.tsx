// One app (IA.md §2): "What is it doing, what does it hold, how do I go back?" All of it is
// one tile of `bromigos lab apps list --all --json` as the board carries it, the server's
// backups as the board read them, and the jobs about this app.
//
// Restart and Remove are the service's actions (POST /api/actions). Each control is there only
// when the server says the page may (board.actions) and the app says it can (the tile's `can`);
// otherwise the page shows the command that does it at the server. Deleting an app's data has
// its own word in root's list ("delete-data"), and asks for the app's id typed and a fresh
// one-time code, which root checks and uses up.
import { useState } from "react";
import { Boundary } from "@/components/Boundary";
import { JobCard } from "@/components/JobCard";
import { NoBoard } from "@/components/NoBoard";
import { Icon, IconButton, IconLink, Planned, State } from "@/components/ui";
import { ApiError, cleanCode } from "@/lib/api/errors";
import type { Board, JobRecord, Tile } from "@/lib/api/types";
import { holoIcon } from "@/lib/icons";
import { isOpen } from "@/lib/jobs";
import { useLab } from "@/lib/lab";
import { ago, when } from "@/lib/time";
import { shownUrl } from "@/lib/url";
import { BACKUP_SHAPE, BACKUP_WORD, backupsHeadline, lastGoodCopy } from "@/lib/words";
import { Sheet } from "@/shell/Shell";
import { tileShape, Unread } from "./Machine";

const K = 1024;
/** A size as a person reads it, in the units the rest of the page uses (1 GB = 1024³ bytes). */
export function size(b: number): [string, string] {
  if (b >= K ** 4) return [String(Math.round((b / K ** 4) * 10) / 10), "TB"];
  if (b >= 10 * K ** 3) return [String(Math.round(b / K ** 3)), "GB"];
  if (b >= K ** 3) return [String(Math.round((b / K ** 3) * 10) / 10), "GB"];
  if (b >= K ** 2) return [String(Math.round(b / K ** 2)), "MB"];
  return [String(Math.round(b / K)), "kB"];
}
const sizeWords = (b: number) => size(b).join(" ");

type Asked = { at: "idle" | "asking" | "started" | "refused"; words: string };
const IDLE: Asked = { at: "idle", words: "" };
const refusal = (e: unknown) => (e instanceof ApiError ? e.words : "The server couldn't do that.");

/** The jobs about this app that haven't ended: an add, a restart, a removal. */
const about = (jobs: JobRecord[], id: string) => jobs.filter((j) => j.subject?.type === "app" && j.subject.id === id && isOpen(j));

function Head({ b, t, now }: { b: Board; t: Tile; now: number }) {
  const { act } = useLab();
  const [said, setSaid] = useState<Asked>(IDLE);
  const ic = holoIcon(t.holo);
  const shape = tileShape(t);
  const mayRestart = t.installed && b.actions.includes("restart") && t.can.includes("restart");
  return (
    <section className="panel" title={`${t.job}: ${t.app}${t.version ? ` ${t.version}` : ""}`}>
      <div className="apphead">
        <span className={`plate big${t.installed && ic.known ? "" : " off"}${shape === "warn" || shape === "down" ? " amber" : ""}`} aria-hidden="true">
          <Icon id={ic.id} size={40} className={shape === "busy" ? "pulse" : ""} />
        </span>
        <div className="nm">
          <h2>{t.job.toUpperCase()}</h2>
          <div className="chips">
            {t.app && (
              <span className="chip" title={`The software that does this job${t.version ? `, and the version installed` : ""}`}>
                {t.app.toUpperCase()}
                {t.version ? ` · ${t.version}` : ""}
              </span>
            )}
            {t.installed ? (
              <State shape={shape} word={t.state_word ?? "Unknown"} hint={`${t.job}'s state, as the server last read it`} />
            ) : (
              <span className="chip" title={`${t.job} is in the catalogue and isn't installed on this server`}>
                NOT INSTALLED
              </span>
            )}
            {t.installed && t.since !== null && (
              <span className="small muted" title={`${t.state_word ?? "This state"} since ${new Date(t.since).toLocaleString("en-GB")}`}>
                since {when(t.since, now)}
              </span>
            )}
          </div>
        </div>
        <div className="ap-do">
          {t.installed && t.open && <IconLink kind="big" icon="i-open" href={t.open.url} label={`Open ${t.job}`} hint={`Open ${t.job} (${t.app}) at ${t.open.url}`} rel="noreferrer" />}
          {mayRestart && (
            <IconButton
              icon="i-restart"
              move="turn"
              label={`Restart ${t.job}`}
              hint={`Restart ${t.job} (${t.app}): the server stops its services and starts them again, as one job in the activity strip`}
              aria-disabled={said.at === "asking"}
              onClick={() => {
                if (said.at === "asking") return;
                setSaid({ at: "asking", words: "" });
                act("restart", t.id).then(
                  (a) => setSaid({ at: "started", words: a.words || `Restarting ${t.job}.` }),
                  (e) => setSaid({ at: "refused", words: refusal(e) }),
                );
              }}
            />
          )}
          {t.installed && <IconLink icon="i-logs" move="slide" href="#app-commands" label={`${t.job}'s logs`} hint={`${t.job}'s logs: the command that prints them, further down this page`} />}
          {t.installed && t.can.includes("remove") && (
            <IconLink
              kind="danger"
              icon="i-remove"
              move="beat"
              href={`#app/${t.id}/remove`}
              label={`Remove ${t.job}`}
              hint={`Remove ${t.job}: opens a sheet that says what stays and what goes. Nothing is removed until you choose there`}
            />
          )}
          {!t.installed && <IconLink kind="big" icon="i-add" move="drop" href={`#supply/add/${t.id}`} label={`Add ${t.job}`} hint={`Add ${t.job}: opens its sheet in Supply`} />}
        </div>
      </div>
      {said.at !== "idle" && (
        <p className={`ap-said ${said.at === "refused" ? "signin-err" : "small"}`} role="status">
          {said.at === "asking" ? "Asking the server…" : said.at === "started" ? `${said.words} Its steps are in the activity strip.` : said.words}
        </p>
      )}
    </section>
  );
}

function Takes({ t }: { t: Tile }) {
  const ram = t.measured.ram_bytes !== null ? size(t.measured.ram_bytes) : null;
  const disk = t.measured.disk_bytes !== null ? size(t.measured.disk_bytes) : null;
  return (
    <section className="panel" title={`What ${t.job} uses on this server now, beside what its recipe asks for`}>
      <h2 className="ph">
        <span>WHAT IT TAKES</span>
      </h2>
      <div className="rdrow ap-rd">
        <div className="rd" title={ram ? "Memory its services use now, measured on the server" : "Memory: not measured. Not every part of it could be read"}>
          <span className="k">
            <Icon id="i-memory" size={16} />
            Memory
          </span>
          {ram ? (
            <span className="v">
              {ram[0]}
              <small>{ram[1]}</small>
            </span>
          ) : (
            <span className="v q">·</span>
          )}
          <span className="s">{ram ? "used now" : t.installed ? "not measured" : "not installed"}{t.requires ? ` · asks for ${t.requires.ram_gb} GB` : ""}</span>
        </div>
        <div className="rd" title={disk ? "The size of its data folders, counted on the server" : "Disk: not measured. It keeps no data folder, or one of them couldn't be read"}>
          <span className="k">
            <Icon id="i-drive" size={16} />
            Disk
          </span>
          {disk ? (
            <span className="v">
              {disk[0]}
              <small>{disk[1]}</small>
            </span>
          ) : (
            <span className="v q">·</span>
          )}
          <span className="s">{disk ? "of data" : t.installed ? "not measured" : "not installed"}{t.requires ? ` · asks for ${t.requires.disk_gb} GB to start` : ""}</span>
        </div>
        <div className="rd" title="The cores its recipe asks for. They are shared with everything else on the server">
          <span className="k">
            <Icon id="i-chip" size={16} />
            Processor
          </span>
          {t.requires ? (
            <span className="v">
              {t.requires.cpu}
              <small>{t.requires.cpu === 1 ? "core" : "cores"}</small>
            </span>
          ) : (
            <span className="v q">·</span>
          )}
          <span className="s">{t.requires ? "asked for · shared" : "its recipe doesn't say"}</span>
        </div>
        <div className="rd" title={t.open ? `Where ${t.job} answers: ${t.open.url}` : `${t.job} has no page of its own to open`}>
          <span className="k">
            <Icon id="i-net" size={16} />
            Address
          </span>
          {t.open ? (
            <a className="v addr" href={t.open.url} rel="noreferrer" title={`Open ${t.job} at ${t.open.url}`}>
              {shownUrl(t.open.url)}
            </a>
          ) : (
            <span className="v q">·</span>
          )}
          <span className="s">{t.open ? (t.open.port !== null ? `port ${t.open.port}` : "its own name on the network") : t.installed ? "no page to open" : "not installed"}</span>
        </div>
      </div>
    </section>
  );
}

function Data({ b, t, now }: { b: Board; t: Tile; now: number }) {
  const d = b.backups;
  const last = d ? lastGoodCopy(d) : null;
  const head = d ? backupsHeadline(d, now) : null;
  return (
    <section className="panel" title={`Where ${t.job} keeps what it holds, and whether a backup has it`}>
      <h2 className="ph">
        <span>WHERE ITS DATA LIVES</span>
      </h2>
      <ul className="rows wide">
        <li title={`Every app keeps its data under /srv/apps, in a folder of its own name. bromigos lab apps show ${t.id} lists each folder with its size`}>
          <Icon id="i-drive" size={20} />
          <span className="grow">
            <b>Its folder</b>
            <br />
            <code>/srv/apps/{t.id}</code>
          </span>
          <span className="chip">{t.measured.disk_bytes !== null ? sizeWords(t.measured.disk_bytes).toUpperCase() : "SIZE NOT MEASURED"}</span>
        </li>
        <li title={head ? `${head.hint}. This is the server's backup as a whole: the page doesn't know each app's own last backup yet` : "The backups couldn't be read on the server"}>
          <Icon id="i-backup" size={20} />
          <span className="grow">
            <b>This server's backups</b>
            <br />
            {d ? (
              <span className={head!.look === "warn" ? "warn" : ""}>
                {head!.words.toLowerCase().replace(/^./, (c) => c.toUpperCase())}
                {last !== null ? ` · ${when(last * 1000, now)}` : ""}
              </span>
            ) : (
              <span className="muted">not read{b.why.backups ? `: ${b.why.backups}` : ""}</span>
            )}
          </span>
          <a className="hw-go" href="#data/backups" title="Data › Backups: when the last backup ran, where it goes, and the last test restore">
            OPEN
          </a>
        </li>
      </ul>
      {d && (
        <p className="small muted ap-note">
          <State shape={BACKUP_SHAPE[d.health.state]} word={`backups: ${BACKUP_WORD[d.health.state]}`} hint={d.health.verdict || "The backups' state"} />
          {/* only what is known: the board carries the last good backup's time, and not when this app
              was installed, so the page can't say that backup holds this folder */}
          {d.configured && (
            <span title="The board says when the last good backup was taken, and not when this app was installed. So the page can't say whether that backup was taken after the app came">
              The server's backups include <code>/srv/apps</code>. Whether the last one holds this app depends on when the app was installed, which the board doesn't say.
            </span>
          )}
        </p>
      )}
    </section>
  );
}

function Updates({ t }: { t: Tile }) {
  const u = t.update;
  return (
    <section className="panel" title={`${t.job}'s version, and whether a newer one is waiting`}>
      <h2 className="ph">
        <span>UPDATES</span>
        {!u && <Planned hint="Planned: app updates behind a snapshot, with a way back. This app doesn't report updates yet" />}
      </h2>
      {u?.available ? (
        <>
          <p className="vers ap-vers" title={`Installed: ${t.version ?? "?"}. Waiting: ${u.to ?? "?"}`}>
            {t.version ?? "?"} <span aria-hidden="true">→</span> <b>{u.to ?? "?"}</b>
          </p>
          <p className="small">
            {u.manual ? "This one is done by hand. " : ""}
            {u.note}
          </p>
        </>
      ) : (
        <>
          <p className="vers" title={`Installed: ${t.version ?? "the version isn't known"}`}>
            <b>{t.version ?? "·"}</b>
          </p>
          <p className="small">{u ? "No update is waiting." : `${t.job} doesn't report updates yet, so the page can't say whether a newer version exists.`}</p>
        </>
      )}
    </section>
  );
}

function Commands({ t, may }: { t: Tile; may: { restart: boolean } }) {
  return (
    <section className="panel" id="app-commands" title={`The commands that look closer at ${t.job}, at the server`}>
      <h2 className="ph">
        <span>LOGS AND A CLOSER LOOK</span>
      </h2>
      <pre>{`# its services' journal, as it is written\nbromigos lab apps logs ${t.id} -f\n# its units, its data folders with their sizes, its health check\nbromigos lab apps show ${t.id}${
        may.restart ? "" : `\n# stop its services and start them again\nsudo bromigos lab apps restart ${t.id}`
      }`}</pre>
    </section>
  );
}

function Needs({ t, apps }: { t: Tile; apps: Tile[] }) {
  const by = t.needed_by.map((id) => apps.find((a) => a.id === id) ?? null).filter((a): a is Tile => !!a && a.installed);
  if (!by.length) return null;
  return (
    <section className="panel" title={`The installed apps that need ${t.job}: removing it is refused while they are here`}>
      <h2 className="ph">
        <span>NEEDED BY · {by.length}</span>
      </h2>
      <ul className="rows wide">
        {by.map((a) => (
          <li key={a.id} title={`${a.job} (${a.app}) needs ${t.job}`}>
            <Icon id={holoIcon(a.holo).id} size={20} />
            <span className="grow">
              <b>{a.job}</b>
            </span>
            <a className="hw-go" href={`#app/${a.id}`} title={`${a.job}'s page`}>
              OPEN
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RemoveSheet({ b, t, apps, now }: { b: Board; t: Tile; apps: Tile[]; now: number }) {
  const { act } = useLab();
  const [said, setSaid] = useState<Asked>(IDLE);
  const [typed, setTyped] = useState("");
  const [code, setCode] = useState("");
  const can = t.installed && t.can.includes("remove");
  const may = can && b.actions.includes("remove");
  const mayDelete = may && b.actions.includes("delete-data");
  const by = t.needed_by.map((id) => apps.find((a) => a.id === id)).filter((a): a is Tile => !!a && a.installed);
  const armed = typed.trim().toLowerCase() === t.id.toLowerCase() && cleanCode(code).length > 0;
  const busy = said.at === "asking" || said.at === "started";
  const last = b.backups ? lastGoodCopy(b.backups) : null;
  const go = (del: boolean) => {
    if (busy || (del && !armed)) return;
    setSaid({ at: "asking", words: "" });
    act("remove", t.id, del ? { delete_data: true, code: cleanCode(code) } : undefined).then(
      (a) => setSaid({ at: "started", words: a.words || `Removing ${t.job}.` }),
      (e) => setSaid({ at: "refused", words: refusal(e) }),
    );
  };
  return (
    <Sheet title={`Remove ${t.job}`} close={`#app/${t.id}`} closeHint={`Close: back to ${t.job}, and nothing is removed`}>
      {!t.installed ? (
        <p className="muted" role="status">
          {t.job} isn't installed on this server, so there is nothing to remove.
        </p>
      ) : !can ? (
        <section className="panel" title={`Why ${t.job} can't be removed`}>
          <h3>
            <span>{t.job.toUpperCase()} STAYS</span>
          </h3>
          <p>
            The server doesn't offer removing {t.job}.{" "}
            {by.length ? `${by.map((a) => a.job).join(", ")} ${by.length === 1 ? "needs" : "need"} it: remove ${by.length === 1 ? "that" : "those"} first.` : "It is one of the lab's own parts, or another app needs it."}
          </p>
          <pre>{`# what would stop, what would stay, and why it refuses\nsudo bromigos lab apps remove ${t.id} --plan`}</pre>
        </section>
      ) : (
        <section className="panel confirm" title={`Removing ${t.job} and deleting its data are two decisions`}>
          <h3>
            <span>REMOVE {t.job.toUpperCase()}</span>
            {!may && <Planned hint="This server doesn't take removals from the page. Today: the commands below, at the server. Root's [board] actions in /etc/bromigos/server.toml decides" />}
          </h3>
          <div className="two">
            <div>
              <ul className="keeps">
                <li>
                  <Icon id="i-stop" size={20} />
                  <span>{t.job} stops and comes off this server</span>
                </li>
                <li>
                  <Icon id="s-ok" size={20} />
                  <span>
                    <b>Its data stays</b> · <code>/srv/apps/{t.id}</code>
                    {t.measured.disk_bytes !== null ? ` · ${sizeWords(t.measured.disk_bytes)}` : ""}
                  </span>
                </li>
                <li>
                  <Icon id="i-backup" size={20} />
                  <span>{last !== null ? `The last good backup of this server: ${ago(last * 1000, now)}` : b.backups ? "This server has no good backup yet" : "The backups couldn't be read"}</span>
                </li>
              </ul>
              {may ? (
                <button type="button" className="wordbtn" aria-disabled={busy} title={`Remove ${t.job} and keep its data: adding it again picks the data up`} onClick={() => go(false)}>
                  Remove, keep its data
                </button>
              ) : (
                <pre>{`# what stops, and what stays\nsudo bromigos lab apps remove ${t.id} --plan\n# remove it, and keep its data\nsudo bromigos lab apps remove ${t.id}`}</pre>
              )}
            </div>
            <div>
              <ul className="keeps">
                <li>
                  <Icon id="i-alert" size={20} />
                  <span>
                    <b>Deleting the data too</b> can't be undone. Only a backup that holds it brings it back
                  </span>
                </li>
                {mayDelete && (
                  <li>
                    <Icon id="i-signin" size={20} />
                    <span>
                      Type the app's id, and a fresh code from <code>sudo bromigos server board code</code>
                    </span>
                  </li>
                )}
              </ul>
              {mayDelete ? (
                <form
                  className="ap-del"
                  onSubmit={(e) => {
                    e.preventDefault();
                    go(true);
                  }}
                >
                  <label className="fld">
                    <span className="k">The app's id</span>
                    <input
                      className="field"
                      name="app"
                      autoComplete="off"
                      autoCapitalize="none"
                      spellCheck={false}
                      maxLength={64}
                      placeholder={t.id}
                      value={typed}
                      onChange={(e) => setTyped(e.target.value)}
                      title={`Type ${t.id} to allow deleting its data`}
                    />
                  </label>
                  <label className="fld">
                    <span className="k">One-time code</span>
                    <input
                      className="field"
                      name="code"
                      autoComplete="off"
                      autoCapitalize="characters"
                      spellCheck={false}
                      maxLength={64}
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                      title="A fresh code from sudo bromigos server board code. The one that signed this browser in doesn't work twice"
                    />
                  </label>
                  <button type="submit" className={`wordbtn${armed ? " armed" : ""}`} aria-disabled={busy || !armed} title={`Remove ${t.job} and delete /srv/apps/${t.id}. This can't be undone`}>
                    Remove and delete data
                  </button>
                </form>
              ) : (
                <pre>{`# it asks you to type the app's id\nsudo bromigos lab apps remove ${t.id} --delete-data`}</pre>
              )}
            </div>
          </div>
          {said.at !== "idle" && (
            <p className={`ap-said ${said.at === "refused" ? "signin-err" : "small"}`} role="status">
              {said.at === "asking" ? "Asking the server…" : said.at === "started" ? `${said.words} Its steps are in the activity strip.` : said.words}
            </p>
          )}
        </section>
      )}
    </Sheet>
  );
}

export function App({ id, sheet }: { id: string; sheet: string | null }) {
  const { board, jobs, now: clock } = useLab();
  const now = clock();
  if (board.state === "loading") return null;
  if (board.state === "error")
    return (
      <section className="page" aria-label={`App ${id}`}>
        <NoBoard error={board.error} />
      </section>
    );
  const b = board.doc;
  const t = b.apps?.find((x) => x.id === id) ?? null;
  const going = about(jobs, id);
  const remove = sheet === "remove" && !!t;
  return (
    <>
      <section className={`page${remove ? " sh-under" : ""}`} aria-label={t ? t.job : `App ${id}`} inert={remove ? true : undefined}>
        {!b.apps ? (
          <div className="unreach" role="status">
            <Icon id="s-unk" size={40} />
            <Unread what="The apps" why={b.why.apps} />
          </div>
        ) : !t ? (
          <div className="unreach" role="status">
            <Icon id="s-unk" size={40} />
            <p className="muted">
              No app called {id} is in the catalogue. <a href="#supply">Supply</a> lists the ones that are.
            </p>
          </div>
        ) : (
          <Boundary what={`${t.job}'s page`} again={id}>
            <div className="stack">
              <Head b={b} t={t} now={now} />
              {going.length > 0 && (
                <section className="panel" title={`The jobs about ${t.job} that haven't ended`}>
                  <h2 className="ph">
                    <span>GOING ON · {going.length}</span>
                  </h2>
                  {going.map((j) => (
                    <JobCard key={j.id} job={j} />
                  ))}
                </section>
              )}
              <Takes t={t} />
              {t.installed && (
                <div className="two ap-two">
                  <Data b={b} t={t} now={now} />
                  <Updates t={t} />
                </div>
              )}
              {t.installed && <Needs t={t} apps={b.apps} />}
              {t.installed && <Commands t={t} may={{ restart: b.actions.includes("restart") && t.can.includes("restart") }} />}
              {t.installed && (
                <section className="panel quiet" title="Restore points: an app's snapshots before each update, and rolling back to one. Planned.">
                  <h2 className="ph muted">
                    <span>
                      <Icon id="i-rollback" size={16} />
                      RESTORE POINTS
                    </span>
                    <Planned hint="Planned: a snapshot before each update, and rolling back to it (bromigos lab apps update and rollback aren't built yet)" />
                  </h2>
                  <p className="small muted">The points this app can go back to will be listed here.</p>
                </section>
              )}
            </div>
          </Boundary>
        )}
      </section>
      {remove && t && (
        <Boundary what="The Remove sheet" again={id}>
          <RemoveSheet b={b} t={t} apps={b.apps ?? []} now={now} />
        </Boundary>
      )}
    </>
  );
}
