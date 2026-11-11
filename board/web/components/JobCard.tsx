// One job as the activity drawer and the Activity page draw it (the prototype's .job card): its
// icon, title, state and where it came from; its steps (the one Steps list, IA.md §4); its
// question with the answers as controls; and what it ended with.
import { useState, type CSSProperties } from "react";
import { Icon, IconButton } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { JobRecord } from "@/lib/api/types";
import { jobIcon, progressWords, STATE_CHIP, STATE_HINT, STATE_WORD, STEP, waitWord } from "@/lib/jobs";
import { useLab } from "@/lib/lab";
import { clock, took, when } from "@/lib/time";

const VIA: Record<string, string> = { board: "via board", phone: "via phone", cli: "from the command line", timer: "via timer", vector: "via VECTOR" };

export function JobCard({ job, children = [] }: { job: JobRecord; children?: JobRecord[] }) {
  const { now } = useLab();
  const [said, setSaid] = useState<string | null>(null);
  const t = now();
  const look = job.state === "needs-you" ? " ask" : job.state === "failed" ? " fail" : "";
  const sub = [
    waitWord(job),
    job.kind,
    `started ${when(job.started_at, t)}`,
    VIA[job.requested_by.via] ?? "",
    children.length ? `${children.filter((c) => c.state === "succeeded").length} of ${children.length} done` : "",
    job.ended_at ? `after ${took(job.ended_at - job.started_at)}` : "",
  ].filter(Boolean);
  const act = (what: Promise<void>) =>
    what.then(
      () => setSaid(null),
      (e) => setSaid(e instanceof ApiError ? e.words : "The server couldn't do that."),
    );
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
                const s = c.state === "succeeded" ? STEP.done : c.state === "running" ? STEP.running : c.state === "needs-you" ? STEP.waiting : c.state === "failed" || c.state === "rolled-back" ? STEP.failed : STEP.todo;
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
                    <Icon id={k.icon} size={20} className={s.state === "running" ? "pulse" : ""} />
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
          <i style={{ "--v": `${job.pct}%` } as CSSProperties} />
        </div>
      )}
      {job.question && job.state === "needs-you" && (
        <div className="job-q">
          <p className="warn">{job.question.text}</p>
          <div className="acts">
            {job.question.choices.map((c) => (
              <button
                key={c.id}
                type="button"
                className={`wordbtn${c.danger ? " danger" : ""}`}
                title={`Answer “${c.label}”: the job carries on with this answer`}
                onClick={() => act(api().answer(job.id, c.id))}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {job.error && (job.state === "failed" || job.state === "rolled-back" || job.state === "interrupted") && (
        <p className="small job-why" title="Why it stopped, in plain words">
          {job.error.words}
          {job.error.fix && <span className="muted"> · {job.error.fix.label}</span>}
        </p>
      )}
      {job.result && job.state === "succeeded" && (
        <p className="small muted job-why" title="What it did">
          {job.result.summary}
        </p>
      )}
      {(job.can.includes("cancel") || job.can.includes("retry")) && (
        <div className="acts job-acts">
          {job.can.includes("retry") && <IconButton icon="i-restart" move="turn" label="Retry" hint="Retry: start the job again from where it can safely start" onClick={() => act(api().retry(job.id))} />}
          {job.can.includes("cancel") && <IconButton icon="i-cancel" label="Cancel" hint={`Cancel: stop the job now. It is safe to stop it here.`} onClick={() => act(api().cancel(job.id))} />}
        </div>
      )}
      {said && <p className="signin-err">{said}</p>}
    </article>
  );
}
