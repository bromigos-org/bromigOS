// The activity strip and its drawer (DESIGN.md §4, IA.md §4): one strip along the bottom of every
// page, the job that most needs a look; pressed, it rises into the drawer of jobs; the drawer's
// Show all opens the Activity page. Live from /api/activity (Server-Sent Events).
import { JobCard } from "@/components/JobCard";
import { Icon, IconButton, Planned } from "@/components/ui";
import type { JobRecord } from "@/lib/api/types";
import { isOpen, progressWords, STATE_WORD, stripPick } from "@/lib/jobs";
import { useLab } from "@/lib/lab";
import { clock } from "@/lib/time";

export function Strip() {
  const { jobs, jobsKnown, live, board, now, drawer, setDrawer } = useLab();
  const pick = stripPick(jobs, board.state === "ok" ? board.doc : null, now());
  let look = "", icon = "s-done", iconCls = "muted", title = "", sub = "", hint = "";
  if (pick.kind === "job") {
    const j = pick.job;
    look = pick.look;
    icon = j.state === "needs-you" ? "i-alert" : j.state === "rolled-back" ? "i-undo" : j.state === "failed" ? "s-fail" : j.state === "interrupted" ? "s-unk" : "s-start";
    iconCls = pick.look === "run" ? "lit" : pick.look === "" ? "muted" : pick.look === "fail" && j.state === "failed" ? "bad" : "warn";
    title = j.title;
    sub = [STATE_WORD[j.state], j.state === "needs-you" ? j.question?.text : progressWords(j), j.error?.words].filter(Boolean).join(" · ");
    hint = j.state === "needs-you" ? "The activity strip: a job waits for an answer. Press the arrow to see it." : "The activity strip: the job that most needs a look now. Press the arrow to raise the drawer of jobs.";
  } else if (pick.kind === "alert") {
    look = "ask";
    icon = "i-alert";
    iconCls = "warn";
    title = `${pick.machine} · ${pick.words}`;
    sub = ["needs you", pick.detail].filter(Boolean).join(" · ");
    hint = "The activity strip: the alarm that most needs you, with the machine it is on";
  } else if (!jobsKnown) {
    // never "nothing running" before the jobs have been read
    icon = "s-unk";
    title = "Reading the jobs";
    sub = "connecting to the server";
    hint = "The activity strip: the jobs haven't been read yet";
  } else {
    title = "Nothing running";
    sub = pick.last ? `Last: ${pick.last.title} · ${STATE_WORD[pick.last.state]} ${pick.last.ended_at ? clock(pick.last.ended_at) : ""}` : "No jobs yet";
    hint = "The activity strip when nothing runs: the last job that finished";
  }
  // the list in hand is the last one read: say so while the stream is away
  if (jobsKnown && !live) sub = [sub, "not live · reconnecting"].filter(Boolean).join(" · ");
  const up = drawer === "activity";
  return (
    <section className="sh-strip" aria-label="Activity strip">
      <div className={`strip ${look}`} title={hint}>
        <Icon id={icon} size={20} className={`strip-i ${iconCls}${pick.kind === "job" && pick.job.state === "running" ? " pulse" : ""}`} />
        <span className="what">
          <b className={pick.kind === "idle" ? "idle" : ""}>{title}</b>
          <span>{sub}</span>
        </span>
        <IconButton
          icon="i-chev"
          move="lift"
          className="strip-up"
          label={up ? "Lower the drawer of jobs" : "Raise the drawer of jobs"}
          hint={up ? "Lower the drawer of jobs" : "Show every job and its steps: raises the activity drawer"}
          aria-expanded={up}
          aria-controls="sh-actd"
          onClick={() => setDrawer(up ? null : "activity")}
        />
      </div>
    </section>
  );
}

/** Top-level jobs with their children beside them ("Update all" is a parent with a child per app). */
export function family(jobs: JobRecord[]): { job: JobRecord; children: JobRecord[] }[] {
  const byId = new Map(jobs.map((j) => [j.id, j]));
  return jobs.filter((j) => !j.parent || !byId.has(j.parent)).map((j) => ({ job: j, children: j.children.map((c) => byId.get(c)).filter((c): c is JobRecord => !!c) }));
}

export function ActivityDrawer() {
  const { jobs, jobsKnown, live, drawer, setDrawer } = useLab();
  if (drawer !== "activity") return null;
  const all = family(jobs);
  const open = all.filter((f) => isOpen(f.job));
  const done = all.filter((f) => !isOpen(f.job)).slice(0, Math.max(1, 3 - open.length));
  return (
    <aside className="sh-drawer sh-dbottom" id="sh-actd" aria-label="Activity">
      <div className="sh-sheethead">
        <b>
          <Icon id="i-job" size={16} />
          ACTIVITY
        </b>
        <span className="tags">
          <span className="sh-tab on" title="Now: running, waiting and the last finished jobs">
            Now
          </span>
          <span className="sh-tab off" title="History: who did what, and when, with undo while its window is open. Planned.">
            History
            <Planned />
          </span>
          <span className="sh-tab off" title="Reports: the weekly lab report, sent to BRODEC. Planned.">
            Reports
            <Planned />
          </span>
        </span>
        <span className="sh-live" title={live ? "Live: jobs update here as they move" : "Reconnecting to the server: what you see may be a few seconds old"}>
          <Icon id={live ? "s-ok" : "s-unk"} size={16} />
          {live ? "LIVE" : "RECONNECTING"}
        </span>
        <a className="ib" href="#activity" title="Show all: the Activity page, every job" aria-label="Show all jobs">
          <Icon id="i-open" move="out" />
        </a>
        <IconButton icon="i-chev" move="drop" label="Lower the drawer" hint="Lower the drawer" onClick={() => setDrawer(null)} />
      </div>
      <div className="pg">
        <div className="body">
          {!all.length && (
            <p className="muted" title="Jobs appear here when something long runs: an install, an update, a backup, a drive test">
              {jobsKnown ? "No jobs yet." : "The jobs haven't been read yet."}
            </p>
          )}
          {[...open, ...done].map((f) => (
            <JobCard key={f.job.id} job={f.job} children={f.children} />
          ))}
        </div>
      </div>
    </aside>
  );
}
