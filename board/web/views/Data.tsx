// Data (IA.md §2): "is my stuff safe?" as one place. Drives: can the lab lose a drive today? Backups:
// when was the last good copy, and was a restore proven? Both read the server's own documents
// (`bromigos storage health --json`, `bromigos lab backups status --json`) as they print them.
// What the API can't do yet (the pool's layout, getting files back from the page, a new disk)
// is drawn with its planned mark, never with made-up figures.
import { Icon, Planned, State } from "@/components/ui";
import type { BackupsStatus, Board, DriveHealth, Shape } from "@/lib/api/types";
import { useLab } from "@/lib/lab";
import { ago, clock, when } from "@/lib/time";
import { Tabs } from "@/shell/Shell";

type Drive = DriveHealth["drives"][number] & {
  advice?: string;
  since?: number | null;
  reasons?: { level: string; text: string }[];
};

export const DRIVE_SHAPE: Record<Drive["verdict"], Shape> = { healthy: "ok", watch: "ok", checking: "warn", worse: "warn", replace: "down", unknown: "unknown" };
const RANK: Shape[] = ["ok", "unknown", "warn", "down"];
const worse = (a: Shape, b: Shape) => (RANK.indexOf(b) > RANK.indexOf(a) ? b : a);

function Unread({ what }: { what: string }) {
  return (
    <div className="unreach" title={`${what} couldn't be read on the server`}>
      <Icon id="s-unk" size={40} />
      <p>{what} couldn't be read on the server. The page tries again every 15 seconds.</p>
    </div>
  );
}

// ---------------------------------------------------------------- Drives

function Drives({ doc, now }: { doc: DriveHealth | null; now: number }) {
  if (!doc) return <Unread what="The drives' health" />;
  const drives = doc.drives as Drive[];
  const here = drives.filter((d) => d.present);
  const bad = here.filter((d) => DRIVE_SHAPE[d.verdict] === "warn" || DRIVE_SHAPE[d.verdict] === "down");
  const worst = here.reduce<Shape>((w, d) => worse(w, DRIVE_SHAPE[d.verdict]), "ok");
  const verdict = bad.length ? `${bad.length} ${bad.length === 1 ? bad[0].words.toUpperCase() : "NEED A LOOK"}` : here.length ? "ALL DRIVES HEALTHY" : "NO DRIVES READ";
  const checked = doc.checked_at;
  return (
    <>
      <div className="stage dt-stage" role="group" aria-label="This server's drives, each with its verdict">
        <div className="dt-bays">
          {here.map((d) => {
            const sh = DRIVE_SHAPE[d.verdict];
            return (
              <div key={d.key} className={`dt-bay${sh === "ok" ? "" : ` ${sh}`}`} title={`${d.model} (${d.device}): ${d.words}. ${d.summary}`}>
                <svg className={`gl${sh === "ok" ? " live" : sh === "unknown" ? "" : " warn"}`} viewBox="0 0 100 100" aria-hidden="true">
                  <use href="#g-drive" />
                </svg>
                <b>{d.device}</b>
                <span className="muted">{d.model}</span>
                <State shape={sh} word={d.words} />
              </div>
            );
          })}
        </div>
        <div className="st-top">
          <span className="over" title="The drives this server reads">
            {here.length} DRIVE{here.length === 1 ? "" : "S"}
          </span>
          <p className={`verdict${worst === "ok" ? "" : worst === "unknown" ? " q" : " warn"}`} role="status" title="The drives' one status line: the worst verdict">
            {verdict}
          </p>
          {checked ? (
            <span className="chip" title={`The system checks read the drives every 15 minutes; this was ${clock(checked)}`}>
              READ {ago(checked, now).toUpperCase()}
            </span>
          ) : (
            <span className="chip">NOT READ YET</span>
          )}
        </div>
        <span className="h-scan" aria-hidden="true" />
        <span className="h-edge" aria-hidden="true" />
      </div>
      <div className="dt-cols">
        {bad.map((d) => (
          <section key={d.key} className="panel is-warn" title={`What changed on ${d.device}, and what to do`}>
            <h2 className="ph">
              <span>
                <Icon id="i-alert" size={16} />
                {d.device} · WHAT CHANGED
              </span>
              <State shape={DRIVE_SHAPE[d.verdict]} word={d.words} />
            </h2>
            <p className="dt-sum">{d.summary}</p>
            {d.reasons && d.reasons.length > 0 && (
              <ul className="rows">
                {d.reasons.map((r, i) => (
                  <li key={i} title={`${r.level}: ${r.text}`}>
                    <Icon id={r.level === "critical" ? "s-fail" : "s-warn"} size={16} />
                    <span className="grow">{r.text}</span>
                    <span className="small muted">{r.level}</span>
                  </li>
                ))}
              </ul>
            )}
            {d.advice && <p className="note wrap">{d.advice}</p>}
            {d.since && <p className="small muted">since {when(d.since, now)}</p>}
            <div className="tags">
              <span className="chip" title="Replacing the drive as one job with named steps, from this page. Today: back up, then swap it with the server off.">
                REPLACE {d.device.toUpperCase()}
              </span>
              <Planned hint="Planned: the replace-a-drive job (drive.replace)" />
            </div>
          </section>
        ))}
        <section className="panel" title="The pool: how many copies it keeps and how many drives it can lose. Planned on this page.">
          <h2 className="ph">
            <span>
              <Icon id="i-storage" size={16} />
              THE POOL
            </span>
            <Planned hint="Planned: the pool's layout, use and copies from the server's storage document" />
          </h2>
          <ul className="rows">
            {here.map((d) => (
              <li key={d.key} title={`${d.model} (${d.device}), ${d.kind}`}>
                <Icon id="i-drive" size={16} />
                <span className="grow">
                  <b>{d.device}</b> {d.model}
                </span>
                <State shape={DRIVE_SHAPE[d.verdict]} word={d.words} />
              </li>
            ))}
          </ul>
        </section>
      </div>
      <section className="panel quiet" title="A disk with files on it, found and not in use: keep it as it is, copy it into the pool, or erase it. Planned (IA.md, item 1).">
        <h2 className="ph muted">
          <span>
            <Icon id="i-drive" size={16} />
            NEW DISK FOUND
          </span>
          <Planned hint="Planned: keep my drives (IA.md, item 1)" />
        </h2>
        <p className="small muted">A disk that already holds files is shown here, with keep, copy in or erase.</p>
      </section>
      <section className="panel" title="Layouts beyond two copies: three copies, parity, a media vault; ZFS later. Planned (IA.md, item 10).">
        <h2 className="ph">
          <span>
            <Icon id="i-storage" size={16} />
            LAYOUT · WHAT MATTERS MOST
          </span>
          <Planned hint="Planned: pool layouts (IA.md, item 10)" />
        </h2>
        <div className="dt-lay">
          {[
            ["TWO COPIES", "loses 1", "today · repairs itself", false],
            ["THREE COPIES", "loses 2", "a third of the space", true],
            ["PARITY", "loses 1", "repairs come from the backup", true],
            ["MEDIA VAULT", "loses 1", "media only", true],
            ["ZFS", "later", "needs our own module", true],
          ].map(([n, lose, s, pl]) => (
            <div key={n as string} className={`dt-l${pl ? "" : " on"}`} title={`${n}: ${lose}; ${s}${pl ? ". Planned." : ". What the installer makes today."}`}>
              <b>{n}</b>
              <span className="small">{lose}</span>
              <span className="small muted">{s}</span>
              {pl && <Planned />}
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

// ---------------------------------------------------------------- Backups

type Carried = { name: string; label: string; model: string; plugged_in: boolean | null; last_good_copy: { ts: number | null } | null; stale: boolean };
type BackupsDoc = BackupsStatus & { snapshots?: { count: number } | null; drives?: Carried[] };
const SHAPE: Record<BackupsStatus["health"]["state"], Shape> = { ok: "ok", attention: "warn", waiting: "unknown", off: "unknown", unknown: "unknown" };

function Backups({ doc, now }: { doc: BackupsDoc | null; now: number }) {
  if (!doc) return <Unread what="The backups" />;
  const last = doc.last_success?.ts ? doc.last_success.ts * 1000 : null;
  const test = doc.last_test_passed?.ts ? doc.last_test_passed.ts * 1000 : null;
  const carried = doc.drives ?? [];
  const sh = SHAPE[doc.health.state];
  return (
    <>
      <div className="stage bk-stage" role="group" aria-label="This server's backups: the last good copy, and how many are kept">
        <div className="bk-big" title={last ? `The last good copy: ${when(last, now)}` : "No good copy yet"}>
          <span className="over">LAST GOOD COPY</span>
          <b className={last ? "" : "q"}>{last ? clock(last) : "NONE"}</b>
          <span className="small muted">{last ? `${when(last, now)} · ${ago(last, now)}` : doc.configured ? "not yet" : "backups are off"}</span>
        </div>
        <div className="st-top">
          <span className="over" title="Where copies go, and how many are kept">
            {(doc.configured ? 1 : 0) + carried.length} DESTINATION{(doc.configured ? 1 : 0) + carried.length === 1 ? "" : "S"}
            {doc.snapshots ? ` · ${doc.snapshots.count} KEPT` : ""}
          </span>
          <p className={`verdict${sh === "ok" ? "" : sh === "warn" ? " warn" : " q"}`} role="status" title={doc.health.verdict}>
            {!doc.configured && !carried.length ? "BACKUPS ARE OFF" : last ? `BACKED UP ${ago(last, now).toUpperCase()}` : "NO GOOD COPY YET"}
          </p>
          <span className="chip" title="The server's own words for its backups">
            {doc.health.state.toUpperCase()}
          </span>
        </div>
        <span className="h-scan" aria-hidden="true" />
        <span className="h-edge" aria-hidden="true" />
      </div>
      <p className="bk-verdict">{doc.health.verdict}</p>
      <div className="dt-cols">
        <section className="panel" title="Where the copies go, each with its last good copy">
          <h2 className="ph">
            <span>
              <Icon id="i-backup" size={16} />
              WHERE THEY GO
            </span>
          </h2>
          <ul className="rows wide">
            {doc.configured && (
              <li title={`The nightly backup goes to ${doc.to}`}>
                <Icon id="i-net" size={20} />
                <span className="grow">
                  <b>{doc.to.split(":")[0].toUpperCase()}</b>
                  <span className="d small muted"> {doc.to}</span>
                </span>
                <State shape={last ? "ok" : "unknown"} word={last ? when(last, now) : "no copy yet"} />
              </li>
            )}
            {carried.map((c) => {
              const g = c.last_good_copy?.ts ? c.last_good_copy.ts * 1000 : null;
              return (
                <li key={c.name + c.label} title={`The ${c.name} drive (${c.model || c.label}): ${c.plugged_in ? "plugged in now" : "carried away"}. ${g ? `Its last good copy: ${when(g, now)}.` : "No good copy yet."}`}>
                  <Icon id="i-usb" size={20} />
                  <span className="grow">
                    <b>{c.name}</b>
                    <span className="d small muted"> {c.plugged_in ? "plugged in" : "carried away"}</span>
                  </span>
                  <State shape={c.stale ? "warn" : g ? "ok" : "unknown"} word={g ? ago(g, now) : "no copy yet"} />
                </li>
              );
            })}
            <li title="A friend's lab as a backup place: your copies, end to end encrypted, on their server. Planned.">
              <Icon id="i-people" size={20} />
              <span className="grow">A friend's lab</span>
              <Planned hint="Planned: a friend's lab as a backup place (IA.md, item 15)" />
            </li>
          </ul>
        </section>
        <section className="panel" title="The proof: a test restore brings a sample of files back to a scratch folder and compares them. Nothing of yours changes.">
          <h2 className="ph">
            <span>
              <Icon id="i-testrestore" size={16} />
              THE PROOF
            </span>
            <State shape={test ? "ok" : "unknown"} word={test ? `passed ${ago(test, now)}` : "not proven yet"} />
          </h2>
          <div className="tags">
            <span className="chip" title="A test restore takes a sample of files from the backup and compares them">
              A SAMPLE OF FILES
            </span>
            <span className="chip lit" title="The sample goes to a scratch folder, is compared, and is cleaned up">
              NOTHING OF YOURS CHANGES
            </span>
          </div>
        </section>
      </div>
      <section className="panel" title="Get files back: pick a backup, pick what, and where it goes (beside, or in place). From this page: planned. Today: bromigos lab backups restore.">
        <h2 className="ph">
          <span>
            <Icon id="i-restore" size={16} />
            GET FILES BACK
          </span>
          <Planned hint="Planned: getting files back from the page (backup.restore). The Depth drawer has the commands." />
        </h2>
        <ol className="flow three">
          <li title="Pick a backup: one of the kept snapshots">
            <span>
              <span className="num">1</span>
            </span>
            Pick a backup
          </li>
          <li title="Pick what: a folder or a file">
            <span>
              <span className="num">2</span>
            </span>
            Pick what
          </li>
          <li title="Where it goes: beside the original in /srv/restore, or in place after showing what it replaces">
            <span>
              <span className="num">3</span>
            </span>
            Beside, or in place
          </li>
        </ol>
      </section>
    </>
  );
}

// ---------------------------------------------------------------- Move in

function MoveIn() {
  return (
    <section className="panel" title="Move in: what is still in someone else's cloud or box, and a guided move for each. Planned (IA.md, item 5).">
      <h2 className="ph">
        <span>
          <Icon id="i-download" size={16} />
          MOVE IN
        </span>
        <Planned hint="Planned: Move in (IA.md, item 5)" />
      </h2>
      <ul className="rows wide">
        {[
          ["i-photos", "Photos", "from Google Photos, into Photos"],
          ["i-documents", "Files", "from Google Drive, into File sync"],
          ["i-passwords", "Passwords", "from a browser, into Passwords"],
          ["i-storage", "A NAS at home", "a Synology, TrueNAS or Unraid found on the network"],
        ].map(([ic, n, s]) => (
          <li key={n} title={`${n}: ${s}. Planned.`}>
            <Icon id={ic} size={20} />
            <span className="grow">
              <b>{n}</b> <span className="small muted">{s}</span>
            </span>
            <Planned />
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Data({ tab }: { tab: string }) {
  const { board, now } = useLab();
  const t = now();
  const b: Board | null = board.state === "ok" ? board.doc : null;
  return (
    <>
      <Tabs place="data" label="Data" />
      {board.state === "loading" ? null : !b ? (
        <Unread what="The board" />
      ) : tab === "backups" ? (
        <Backups doc={b.backups as BackupsDoc | null} now={t} />
      ) : tab === "move" ? (
        <MoveIn />
      ) : (
        <Drives doc={b.storage as DriveHealth | null} now={t} />
      )}
    </>
  );
}
