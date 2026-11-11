// One job as the activity drawer draws it (the prototype's .job card): its icon, title, state
// and where it came from; its steps (the one Steps list, IA.md §4); the question it asks; and
// what it ended with. The page can't answer, cancel or retry a job yet (the service has no
// route for it), so it shows the question and its answers with the command that gives one.
import type { CSSProperties } from "react";
import { Icon, Planned } from "@/components/ui";
import type { JobRecord } from "@/lib/api/types";
import { isOpen, jobIcon, progressWords, STATE_CHIP, STATE_HINT, STATE_WORD, STEP, waitWord } from "@/lib/jobs";
import { useLab } from "@/lib/lab";
import { clock, took, when } from "@/lib/time";

const VIA: Record<string, string> = { board: "via board", phone: "via phone", cli: "from the command line", timer: "via timer", vector: "via VECTOR" };

/** `full`: the Activity page's card, with what the job said, how to look closer, and the
 *  commands that stop or restart it when the job says they may be used. */
export function JobCard({ job, children = [], full = false }: { job: JobRecord; children?: JobRecord[]; full?: boolean }) {
  const { now } = useLab();
  const t = now();
  const look = job.state === "needs-you" ? " ask" : job.state === "failed" ? " fail" : "";
  const going = isOpen(job);
  const stoppedAt = job.error?.step ? job.steps.find((s) => s.id === job.error!.step)?.label : null;
  const sub = [
    waitWord(job),
    job.kind,
    `started ${when(job.started_at, t)}`,
    VIA[job.via] ?? "",
    children.length ? `${children.filter((c) => c.state === "succeeded").length} of ${children.length} done` : "",
    job.ended_at ? `after ${took(job.ended_at - job.started_at)}` : "",
  ].filter(Boolean);
  return (
    <article className={`job${look}`} title={`${job.title}: ${STATE_HINT[job.state]}`} data-job={job.id}>
      <div className="head">
        <Icon id={jobIcon(job)} className={job.state === "needs-you" || job.state === "rolled-back" ? "warn" : ""} />
        <span>
          <b>{job.title}</b>
          <span className="sub">{sub.join(" · ")}</span>
        </span>
        <span className="tags">
          <span className={STATE_CHIP[job.state]} title={STATE_HINT[job.state]}>
            {STATE_WORD[job.state].toUpperCase()}
          </span>
        </span>
      </div>
      {(children.length > 0 || job.steps.length > 0) && (
        <ol className="steps">
          {children.length
            ? children.map((c) => {
                const s = c.state === "succeeded" ? STEP.done : c.state === "running" ? STEP.running : c.state === "needs-you" || c.state === "waiting" ? STEP.waiting : c.state === "queued" ? STEP.todo : STEP.failed;
                return (
                  <li key={c.id} className={s.cls} title={`${c.title}: ${STATE_HINT[c.state]}`}>
                    <Icon id={s.icon} size={20} className={c.state === "running" ? "pulse" : ""} />
                    <span>
                      {c.title}
                      {progressWords(c) && <span className="d">{progressWords(c)}</span>}
                    </span>
                    <span className="small">{c.ended_at ? clock(c.ended_at) : STATE_WORD[c.state]}</span>
                  </li>
                );
              })
            : job.steps.map((s) => {
                const k = STEP[s.state];
                return (
                  <li key={s.id} className={k.cls} title={`${s.label}: ${k.word}`}>
                    <Icon id={k.icon} size={20} className={s.state === "running" && job.state === "running" ? "pulse" : ""} />
                    <span>
                      {s.label}
                      {s.detail && <span className="d">{s.detail}</span>}
                      {s.progress && (
                        <span className="d">
                          {s.progress.done} of {s.progress.total} {s.progress.unit}
                        </span>
                      )}
                    </span>
                    <span className={`small${s.state === "done" ? " muted" : ""}`}>{s.state === "done" && s.ended_at ? clock(s.ended_at) : k.word}</span>
                  </li>
                );
              })}
        </ol>
      )}
      {job.pct !== null && job.state === "running" && (
        <div className="prog" title={`${job.pct} % done, as the job measures it`} role="progressbar" aria-label="How far" aria-valuenow={job.pct} aria-valuemin={0} aria-valuemax={100}>
          <i style={{ "--v": `${Math.max(0, Math.min(100, job.pct))}%` } as CSSProperties} />
        </div>
      )}
      {job.question && job.state === "needs-you" && (
        <div className="job-q" title="The job waits for an answer. Answering from this page is planned; the command below answers it at the server.">
          <p className="warn">{job.question.text}</p>
          <ul className="job-as">
            {job.question.choices.map((c) => (
              <li key={c.id}>
                <code>{c.id}</code> {c.label}
              </li>
            ))}
          </ul>
          <pre>{`sudo bromigos activity answer ${job.id} ${job.question.choices[0]?.id ?? "CHOICE"}`}</pre>
          <Planned hint="Planned: answering a job from this page. Today the command above answers it, at the server or over SSH." />
        </div>
      )}
      {job.error && (job.state === "failed" || job.state === "rolled-back" || job.state === "interrupted") && (
        <p className="small job-why" title="Why it stopped, in plain words">
          {stoppedAt ? `Stopped at ${stoppedAt}: ` : ""}
          {job.error.words}
          {job.error.fix && <span className="muted"> · {job.error.fix}</span>}
        </p>
      )}
      {job.result && job.result.summary && (job.state === "succeeded" || job.state === "rolled-back") && (
        <p className="small muted job-why" title={job.state === "succeeded" ? "What it did" : "How it ended"}>
          {job.result.summary}
        </p>
      )}
      {full && (
        <div className="job-closer">
          {job.notes.length > 0 && (
            <ul className="job-notes" title="What the job said along the way">
              {job.notes.map((n, i) => (
                <li key={i}>
                  <span className="muted">{n.at ? clock(n.at) : ""}</span> {n.words}
                </li>
              ))}
            </ul>
          )}
          {going && job.can.includes("cancel") && (
            <p className="small" title="The job says stopping it now is safe. Stopping it from this page is planned.">
              Stopping it now is safe: <code>sudo bromigos activity cancel {job.id}</code>
            </p>
          )}
          {going && !job.can.includes("cancel") && job.cancel_note && (
            <p className="small" title="The job says stopping it now isn't safe, and why">
              Not safe to stop now: {job.cancel_note}
            </p>
          )}
          {!going && job.can.includes("retry") && (
            <p className="small" title="The job can be started again. Starting it again from this page is planned.">
              It can be started again: <code>sudo bromigos activity retry {job.id}</code>
            </p>
          )}
          <pre title="The command that shows this job in full at the server: its steps, what it said, and the end of its log">{`bromigos activity show ${job.id}`}</pre>
          <details className="depth">
            <summary title="Depth: the job's unit, its log file and the command it ran">
              <Icon id="i-chev" size={16} />
              Its unit, log and command
            </summary>
            <dl className="kv">
              <dt>Job</dt>
              <dd>{job.id}</dd>
              {job.unit && (
                <>
                  <dt>Unit</dt>
                  <dd>
                    <code>systemctl status {job.unit}</code>
                  </dd>
                </>
              )}
              {job.log && (
                <>
                  <dt>Log</dt>
                  <dd>
                    <code>{job.log}</code>
                  </dd>
                </>
              )}
              {job.command.length > 0 && (
                <>
                  <dt>Command</dt>
                  <dd>
                    <code>{job.command.join(" ")}</code>
                  </dd>
                </>
              )}
            </dl>
          </details>
        </div>
      )}
    </article>
  );
}
