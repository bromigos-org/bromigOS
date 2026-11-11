// Activity (IA.md §2), the strip's full view: "Is anything waiting for me?" Every job the page
// knows, from the live stream and from the list the board read: the ones that ask, the ones that
// run or wait, and the ones that ended, each with its steps, what it asked, how it ended, and
// the exact command that looks closer at the server.
//
// The page is read-only. The service has no route yet to answer, cancel or retry a job, so
// each job shows the command that does it at the server. `#job/ID` opens one job in a sheet.
import { Boundary } from "@/components/Boundary";
import { JobCard } from "@/components/JobCard";
import { Icon, Planned, State } from "@/components/ui";
import type { JobRecord } from "@/lib/api/types";
import { isOpen } from "@/lib/jobs";
import { useLab } from "@/lib/lab";
import { family } from "@/shell/Activity";
import { Sheet, Tabs } from "@/shell/Shell";
import { Unread } from "./Machine";

type Fam = { job: JobRecord; children: JobRecord[] };

function Group({ title, hint, jobs, warn, empty }: { title: string; hint: string; jobs: Fam[]; warn?: boolean; empty: string }) {
  return (
    <section className={`panel ac-group${warn && jobs.length ? " is-warn" : ""}`} title={hint}>
      <h2 className="ph">
        <span>
          {title} · {jobs.length}
        </span>
      </h2>
      {jobs.length ? (
        jobs.map((f) => (
          <Boundary key={f.job.id} what={`The job “${f.job.title}”`}>
            <JobCard job={f.job} children={f.children} full />
          </Boundary>
        ))
      ) : (
        <p className="small muted">{empty}</p>
      )}
    </section>
  );
}

/** Why there is no list to show, when there is none: not read yet, or the server couldn't read it. */
function Reading() {
  const { board, jobsKnown } = useLab();
  const b = board.state === "ok" ? board.doc : null;
  if (!jobsKnown)
    return b?.unread.includes("jobs") ? (
      <Unread what="The jobs" why={b.why.jobs} />
    ) : (
      <p className="small muted" role="status">
        The jobs haven't been read yet.
      </p>
    );
  return null;
}

export function Activity({ sheetId }: { sheetId: string | null }) {
  const { jobs, jobsKnown, live } = useLab();
  const all = family(jobs);
  const asks = all.filter((f) => f.job.state === "needs-you");
  const going = all.filter((f) => isOpen(f.job) && f.job.state !== "needs-you");
  const ended = all.filter((f) => !isOpen(f.job));
  const one = sheetId ? jobs.find((j) => j.id === sheetId) : null;
  const oneFam = one ? { job: one, children: one.children.map((c) => jobs.find((j) => j.id === c)).filter((c): c is JobRecord => !!c) } : null;
  return (
    <>
      <section className={`page${sheetId ? " sh-under" : ""}`} aria-label="Activity" inert={sheetId ? true : undefined}>
        <Tabs place="activity" label="Activity" />
        <section className="panel" title="The jobs this server knows: the long things it does, each a record with named steps (docs/activity.md)">
          <div className="rdrow ac-rd">
            <div className="rd" title="Jobs that wait for a person's answer">
              <span className="k">Need you</span>
              <span className={`v${!jobsKnown ? " q" : asks.length ? " w" : ""}`}>{jobsKnown ? asks.length : "·"}</span>
            </div>
            <div className="rd" title="Jobs that run now, wait for something, or are queued">
              <span className="k">Going</span>
              <span className={`v${jobsKnown ? "" : " q"}`}>{jobsKnown ? going.length : "·"}</span>
            </div>
            <div className="rd" title="Jobs that ended, of the ones the server still lists: it keeps the newest">
              <span className="k">Ended</span>
              <span className={`v${jobsKnown ? "" : " q"}`}>{jobsKnown ? ended.length : "·"}</span>
            </div>
            <div className="rd" title={live ? "Live: jobs change here as they move" : "Not live: the page is reconnecting to the server, and what you see is the last list it read"}>
              <span className="k">The list</span>
              <span className="v m">{jobsKnown ? <State shape={live ? "ok" : "unknown"} word={live ? "live" : "not live · reconnecting"} /> : <State shape="unknown" word="not read" />}</span>
            </div>
          </div>
          <Reading />
        </section>
        {jobsKnown && (
          <>
            {asks.length > 0 && <Group title="NEED YOU" hint="Jobs that wait for a person's answer: each shows its question and the command that answers it" jobs={asks} warn empty="" />}
            <Group title="GOING" hint="Jobs that run now, wait for something, or are queued" jobs={going} empty="Nothing is running or waiting." />
            <Group title="ENDED" hint="Jobs that ended, newest first: what each did, or why it stopped" jobs={ended} empty="No job has ended yet." />
          </>
        )}
        <section className="panel quiet" title="Upcoming jobs: the nightly backup, the update window, the monthly test restore, each with Run now. Planned.">
          <h2 className="ph muted">
            <span>
              <Icon id="i-snooze" size={16} />
              UPCOMING
            </span>
            <Planned hint="Planned: the timers' next runs, with Run now (IA.md, item 16)" />
          </h2>
          <p className="small muted">The next runs of the timed jobs will be listed here.</p>
        </section>
      </section>
      {sheetId && (
        <Sheet title={oneFam ? oneFam.job.title : "A job"} close="#activity" closeHint="Close: back to Activity">
          {oneFam ? (
            <JobCard job={oneFam.job} children={oneFam.children} full />
          ) : (
            <p className="muted" role="status">
              {jobsKnown ? "The server no longer lists a job with that id: it keeps the newest. " : "The jobs haven't been read yet. "}
              <code>bromigos activity show {sheetId}</code>
            </p>
          )}
        </Sheet>
      )}
    </>
  );
}
