// Activity (IA.md §2), the strip's full view: "Is anything waiting for me?" Every job the page
// knows, from the live stream and from the list the board read: the ones that ask, the ones that
// run or wait, and the ones that ended, each with its steps, what it asked, how it ended, and
// the exact command that looks closer at the server.
//
// The lab's jobs show here too (docs/activity.md, "Lab jobs"): each ComfyUI generation and each
// job feed's run, with its picture. A generation that runs now is the page's hero (MAKING NOW):
// the picture as it's made, its ring, its stage and the queue behind it. Three toggles pick all
// jobs, this server's, or the lab's.
//
// A job's answers, Stop and Start again are controls where the server lets the page; otherwise
// each job shows the command that does it at the server. `#job/ID` opens one job in a sheet.
import { useEffect, useState } from "react";
import { Boundary } from "@/components/Boundary";
import { JobCard } from "@/components/JobCard";
import { LabJobCard } from "@/components/LabJobCard";
import { Icon, Planned, State } from "@/components/ui";
import type { JobRecord } from "@/lib/api/types";
import { inFilter, isOpen, type JobFilter } from "@/lib/jobs";
import { useLab } from "@/lib/lab";
import { family } from "@/shell/Activity";
import { Sheet, Tabs } from "@/shell/Shell";
import { Unread } from "./Machine";

type Fam = { job: JobRecord; children: JobRecord[] };

function Group({ title, hint, jobs, warn, empty, compact }: { title: string; hint: string; jobs: Fam[]; warn?: boolean; empty: string; compact?: boolean }) {
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
            <JobCard job={f.job} children={f.children} full compact={compact} />
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

const FILTERS: { id: JobFilter; icon: string; label: string; hint: string }[] = [
  { id: "all", icon: "i-layers", label: "All jobs", hint: "All jobs: this server's and the lab's" },
  { id: "server", icon: "i-rack", label: "This server's jobs", hint: "This server's own jobs: installs, updates, backups, drive tests" },
  { id: "lab", icon: "i-lab", label: "The lab's jobs", hint: "The lab's jobs: ComfyUI's generations (pictures, clips, 3D models) and pipeline runs" },
];
const FILTER_KEY = "board.activity.filter";

/** Which jobs the page shows, kept for this browser (a convenience: it reads "all" without it). */
function useFilter(): [JobFilter, (f: JobFilter) => void] {
  const [f, setF] = useState<JobFilter>("all");
  useEffect(() => {
    try {
      const v = sessionStorage.getItem(FILTER_KEY);
      if (v === "server" || v === "lab") setF(v);
    } catch {
      /* no storage here: all jobs */
    }
  }, []);
  return [
    f,
    (v) => {
      setF(v);
      try {
        sessionStorage.setItem(FILTER_KEY, v);
      } catch {
        /* kept for this page only */
      }
    },
  ];
}

function Filter({ value, set, counts }: { value: JobFilter; set: (f: JobFilter) => void; counts: Record<JobFilter, number> }) {
  return (
    <div className="ac-filter" role="group" aria-label="Which jobs">
      {FILTERS.map((f) => (
        <button key={f.id} type="button" className={`ib${value === f.id ? " on" : ""}`} aria-pressed={value === f.id} aria-label={f.label} title={`${f.hint} · ${counts[f.id]}`} onClick={() => set(f.id)}>
          <Icon id={f.icon} move="beat" />
          <span className="count">{counts[f.id]}</span>
        </button>
      ))}
    </div>
  );
}

/** The ComfyUIs the lab follower follows: answering or not, and whether their progress is live. */
function LabLine() {
  const { labStatus } = useLab();
  if (!labStatus || (!labStatus.following && !labStatus.instances.length)) return null;
  return (
    <div className="chips ac-lab" title="The lab's ComfyUIs, as the server's lab follower reads them (/etc/bromigos/labjobs.toml)">
      {!labStatus.following && <State shape="unknown" word="lab: not read yet" hint="The server's lab follower starts while the page is open: its first look comes in a few seconds" />}
      {labStatus.instances.map((i) => (
        <State
          key={i.name}
          shape={i.state === "ok" ? (i.relay ? "ok" : "busy") : "down"}
          word={`ComfyUI ${i.name} · ${i.state !== "ok" ? "not answering" : i.relay ? "live" : "queue and results"}`}
          hint={
            i.state !== "ok"
              ? `ComfyUI ${i.name} isn't answering${i.words ? `: ${i.words}` : ""}`
              : i.relay
                ? `ComfyUI ${i.name}: its progress and previews come live`
                : `ComfyUI ${i.name}: its queue, its ends and what it made. Progress is estimated until the relay node is installed there (docs/activity.md, "Live progress and previews")`
          }
        />
      ))}
    </div>
  );
}

export function Activity({ sheetId }: { sheetId: string | null }) {
  const { jobs: every, jobsKnown, live } = useLab();
  const [filter, setFilter] = useFilter();
  const counts = { all: every.filter((j) => !j.parent).length, server: every.filter((j) => !j.parent && !j.lab).length, lab: every.filter((j) => j.lab).length };
  const jobs = every.filter((j) => inFilter(j, filter));
  // the hero: the lab's generation that runs now, with the queue behind it on the same ComfyUI
  // (a ComfyUI generation first: it has the picture being made; else a pipeline run's step)
  const making = filter === "server" ? undefined : jobs.find((j) => j.lab?.source === "comfyui" && j.state === "running") ?? jobs.find((j) => j.lab && j.state === "running");
  const behind = making ? jobs.filter((j) => j.lab && j.state === "queued" && j.lab.instance === making.lab!.instance).sort((a, b) => (a.lab!.position ?? 0) - (b.lab!.position ?? 0)) : [];
  const all = family(jobs.filter((j) => j !== making));
  const asks = all.filter((f) => f.job.state === "needs-you");
  const going = all.filter((f) => isOpen(f.job) && f.job.state !== "needs-you");
  const ended = all.filter((f) => !isOpen(f.job));
  const one = sheetId ? every.find((j) => j.id === sheetId) : null;
  const oneFam = one ? { job: one, children: one.children.map((c) => every.find((j) => j.id === c)).filter((c): c is JobRecord => !!c) } : null;
  return (
    <>
      <section className={`page${sheetId ? " sh-under" : ""}`} aria-label="Activity" inert={sheetId ? true : undefined}>
        <Tabs place="activity" label="Activity" />
        <section className="panel" title="The jobs this server knows: the long things it does, each a record with named steps, and the lab's creation jobs (docs/activity.md)">
          <div className="ac-top">
            <Filter value={filter} set={setFilter} counts={counts} />
            <LabLine />
          </div>
          <div className="rdrow ac-rd">
            <div className="rd" title="Jobs that wait for a person's answer">
              <span className="k">Need you</span>
              <span className={`v${!jobsKnown ? " q" : asks.length ? " w" : ""}`}>{jobsKnown ? asks.length : "·"}</span>
            </div>
            <div className="rd" title="Jobs that run now, wait for something, or are queued">
              <span className="k">Going</span>
              <span className={`v${jobsKnown ? "" : " q"}`}>{jobsKnown ? going.length + (making ? 1 : 0) : "·"}</span>
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
        {jobsKnown && making && (
          <section className="panel ac-making" title="What the lab is making now: the picture as ComfyUI makes it, how far it is, and what waits behind it">
            <h2 className="ph">
              <span>
                <Icon id="i-lab" size={16} />
                MAKING NOW
              </span>
            </h2>
            <Boundary what={`The job “${making.title}”`}>
              <LabJobCard job={making} queue={behind} hero full />
            </Boundary>
          </section>
        )}
        {jobsKnown && (
          <>
            {asks.length > 0 && <Group title="NEED YOU" hint="Jobs that wait for a person's answer: each shows its question and the command that answers it" jobs={asks} warn empty="" />}
            <Group title="GOING" hint="Jobs that run now, wait for something, or are queued" jobs={going} empty={making ? "Nothing else is running or waiting." : "Nothing is running or waiting."} />
            <Group title="ENDED" hint="Jobs that ended, newest first: what each did, or why it stopped" jobs={ended} empty="No job has ended yet." compact />
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
            <JobCard job={oneFam.job} children={oneFam.children} full big />
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
