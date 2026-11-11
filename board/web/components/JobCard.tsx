// One job as the activity drawer draws it (the prototype's .job card): its icon, title, state
// and where it came from; its steps (the one Steps list, IA.md §4); the question it asks; and
// what it ended with.
//
// Answer, Stop and Start again are the service's job actions (POST /api/activity/<id>/<verb>).
// Each is a control only when the server lets the page (board.actions holds "job.answer",
// "job.cancel" or "job.retry") and the job's own record says it may be done now (its `can`).
// Otherwise the card shows the command that does it at the server. A choice the job marks as
// can't be undone (`danger`) also asks for a fresh one-time code, as deleting an app's data does.
import { useState, type CSSProperties } from "react";
import { Icon, IconButton, Planned } from "@/components/ui";
import { ApiError, cleanCode } from "@/lib/api/errors";
import type { JobRecord, JobVerb } from "@/lib/api/types";
import { isOpen, jobIcon, progressWords, STATE_CHIP, STATE_HINT, STATE_WORD, STEP, waitWord } from "@/lib/jobs";
import { useLab } from "@/lib/lab";
import { clock, took, when } from "@/lib/time";

const VIA: Record<string, string> = { board: "via board", phone: "via phone", cli: "from the command line", timer: "via timer", vector: "via VECTOR" };

type Said = { at: "idle" | "asking" | "done" | "refused"; words: string; code?: string; job?: string | null };
const IDLE: Said = { at: "idle", words: "" };

/** What the page may do to this job now: the server's leave and the job's own word, both. */
export function useJobMay(job: JobRecord): Record<JobVerb, boolean> {
  const { board } = useLab();
  const allowed = board.state === "ok" ? board.doc.actions : [];
  const may = (v: JobVerb) => allowed.includes(`job.${v}`) && job.can.includes(v);
  return { answer: may("answer") && job.state === "needs-you" && !!job.question, cancel: may("cancel") && isOpen(job), retry: may("retry") && !isOpen(job) };
}

/** The question's answers as controls; a choice that can't be undone opens a field for a fresh code first. */
function Answer({ job, send, said }: { job: JobRecord; send: (verb: JobVerb, body: { question: string; choice: string; code?: string }) => void; said: Said }) {
  const q = job.question!;
  const [picked, setPicked] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const busy = said.at === "asking";
  const danger = q.choices.find((c) => c.id === picked && c.danger) ?? null;
  if (danger)
    return (
      <form
        className="job-danger confirm"
        onSubmit={(e) => {
          e.preventDefault();
          if (busy || !cleanCode(code)) return;
          send("answer", { question: q.id, choice: danger.id, code: cleanCode(code) });
        }}
      >
        <p>
          <Icon id="i-alert" size={16} /> <b>{danger.label}</b> can't be undone. It needs a fresh code from <code>sudo bromigos server board code</code>; the one that signed this browser in doesn't count.
        </p>
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
            title="A fresh code from sudo bromigos server board code, at the server"
          />
        </label>
        <span className="job-ans">
          <button type="submit" className={`wordbtn${cleanCode(code) ? " armed" : ""}`} aria-disabled={busy || !cleanCode(code)} title={`${danger.label}: this can't be undone`}>
            {danger.label}
          </button>
          <button type="button" className="wordbtn back" title="Back to the question: nothing is sent" onClick={() => setPicked(null)}>
            Back
          </button>
        </span>
      </form>
    );
  return (
    <span className="job-ans" role="group" aria-label={`Answers to: ${q.text}`}>
      {q.choices.map((c) => (
        <button
          key={c.id}
          type="button"
          className={`wordbtn${c.danger ? " danger" : ""}`}
          aria-disabled={busy}
          title={c.danger ? `${c.label}: this can't be undone, and asks for a fresh code first` : `Answer: ${c.label}`}
          onClick={() => {
            if (busy) return;
            if (c.danger) setPicked(c.id);
            else send("answer", { question: q.id, choice: c.id });
          }}
        >
          {c.label}
        </button>
      ))}
    </span>
  );
}

/** `full`: the Activity page's card, with what the job said, how to look closer, and the
 *  commands that stop or restart it when the job says they may be used. */
export function JobCard({ job, children = [], full = false }: { job: JobRecord; children?: JobRecord[]; full?: boolean }) {
  const { now, jobAct } = useLab();
  const t = now();
  const may = useJobMay(job);
  const [said, setSaid] = useState<Said>(IDLE);
  const send = (verb: JobVerb, body: { question: string; choice: string; code?: string } | Record<string, never>) => {
    if (said.at === "asking") return;
    setSaid({ at: "asking", words: "" });
    jobAct(verb, job.id, body).then(
      (a) => setSaid({ at: "done", words: a.words || "Asked.", job: a.job }),
      (e) => setSaid({ at: "refused", words: e instanceof ApiError ? e.words : "The server couldn't do that.", code: e instanceof ApiError ? e.code : undefined }),
    );
  };
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
        <div className="job-q" title={may.answer ? "The job waits for an answer: pick one" : "The job waits for an answer. This server doesn't take answers from the page: the command below answers it at the server."}>
          <p className="warn">{job.question.text}</p>
          {may.answer ? (
            <Answer job={job} send={send} said={said} />
          ) : (
            <>
              <ul className="job-as">
                {job.question.choices.map((c) => (
                  <li key={c.id}>
                    <code>{c.id}</code> {c.label}
                    {c.danger && <span className="small warn"> · can't be undone</span>}
                  </li>
                ))}
              </ul>
              <pre>{`sudo bromigos activity answer ${job.id} ${job.question.choices[0]?.id ?? "CHOICE"}`}</pre>
              <Planned hint="This server doesn't take answers from the page (root's [board] actions in /etc/bromigos/server.toml): the command above answers it, at the server or over SSH." />
            </>
          )}
        </div>
      )}
      {(may.cancel || may.retry) && (
        <div className="job-acts">
          {may.cancel && (
            <IconButton
              icon="i-stop"
              move="beat"
              label={`Stop ${job.title}`}
              hint={`Stop it: the job says stopping it now is safe${job.cancel_note ? ` (${job.cancel_note})` : ""}`}
              aria-disabled={said.at === "asking"}
              onClick={() => send("cancel", {})}
            />
          )}
          {may.retry && (
            <IconButton
              icon="i-restart"
              move="turn"
              label={`Start ${job.title} again`}
              hint="Start it again, as it was started: a new job, with its own card"
              aria-disabled={said.at === "asking"}
              onClick={() => send("retry", {})}
            />
          )}
        </div>
      )}
      {said.at !== "idle" && (
        <p className={`job-said ${said.at === "refused" ? "signin-err" : "small"}`} role="status">
          {said.at === "asking" ? "Asking the server…" : said.words}
          {said.at === "done" && said.job && said.job !== job.id && (
            <>
              {" "}
              <a href={`#job/${said.job}`} title="The new job's card: its steps as it runs">
                Open the new job
              </a>
            </>
          )}
        </p>
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
          {going && job.can.includes("cancel") && !may.cancel && (
            <p className="small" title="The job says stopping it now is safe. This server doesn't let the page stop jobs: the command does it at the server.">
              Stopping it now is safe: <code>sudo bromigos activity cancel {job.id}</code>
            </p>
          )}
          {going && !job.can.includes("cancel") && job.cancel_note && (
            <p className="small" title="The job says stopping it now isn't safe, and why">
              Not safe to stop now: {job.cancel_note}
            </p>
          )}
          {!going && job.can.includes("retry") && !may.retry && (
            <p className="small" title="The job can be started again. This server doesn't let the page start jobs again: the command does it at the server.">
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
