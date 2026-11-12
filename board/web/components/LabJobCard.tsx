// One lab job (docs/activity.md, "Lab jobs"): a ComfyUI generation, or a job feed's run (a
// multi-step tool such as an asset pipeline). The same record as a server's job, with a picture:
// while it runs, the preview ComfyUI streams as it samples, on glass (the Scanline, the lit
// corners), with a progress ring and the stage it's at; once it ends, what it made (a picture, a
// clip, or a 3D model on the projection table). The queue behind a running generation is listed
// under it (`queue`).
//
// Stop is the job's own action (POST /api/activity/<id>/cancel), shown only when the server lets
// the page (board.actions "job.cancel") and the record says it may be done now (`can`). A queued
// generation leaves the queue at once; a running one is interrupted, which asks first: what it
// made so far is lost. Without the server's leave, the card shows the command instead.
import { useState, type CSSProperties } from "react";
import { useJobMay } from "@/components/JobCard";
import { ModelHolo } from "@/components/ModelHolo";
import { Icon, IconButton } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import type { JobRecord, LabMedia } from "@/lib/api/types";
import { isOpen, jobIcon, STATE_CHIP, STATE_HINT, STATE_WORD, STEP } from "@/lib/jobs";
import { useLab } from "@/lib/lab";
import { ago, when } from "@/lib/time";

type Said = { at: "idle" | "asking" | "done" | "refused"; words: string };

/** "2 min 5 s", "40 s": a generation's time, to the second (they're short). */
export function secs(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min ${s % 60} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** The progress ring: how far, as ComfyUI measures it, or estimated (dashed) from earlier runs. */
export function Ring({ pct, estimated, size = 64 }: { pct: number | null; estimated: boolean; size?: number }) {
  const r = 26, c = 2 * Math.PI * r, v = pct === null ? 0 : Math.max(0, Math.min(100, pct));
  const hint = pct === null ? "How far: ComfyUI hasn't said yet" : estimated
    ? `About ${v} % done: an estimate from how long this workflow took before (ComfyUI doesn't send this one's progress)`
    : `${v} % done, as ComfyUI measures it`;
  return (
    <span className={`lab-ring${estimated ? " est" : ""}`} title={hint} role="progressbar" aria-label="How far" aria-valuenow={pct ?? undefined} aria-valuemin={0} aria-valuemax={100}>
      <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true">
        <circle className="ring-track" cx="32" cy="32" r={r} />
        <circle className="ring-done" cx="32" cy="32" r={r} strokeDasharray={`${(c * v) / 100} ${c}`} transform="rotate(-90 32 32)" />
      </svg>
      <b>{pct === null ? "·" : `${v}%`}</b>
    </span>
  );
}

const KIND_WORD: Record<LabMedia["kind"], string> = { image: "picture", video: "clip", model3d: "3D model", file: "file" };

/** A picture, clip or model the lab keeps, as large as its frame allows. */
function Media({ m, big, url, alt }: { m: LabMedia; big: boolean; url: (n: string) => string; alt: string }) {
  const [turn, setTurn] = useState(big);
  if (!m.media) return <Icon id={m.kind === "video" ? "i-film" : m.kind === "model3d" ? "i-models" : "i-photos"} size={40} className="lab-none" />;
  if (m.kind === "video")
    return <video className="lab-img" src={url(m.media)} muted loop playsInline autoPlay preload="metadata" aria-label={alt} title={`${alt}: the clip it made, playing without sound`} />;
  if (m.kind === "model3d")
    return turn ? (
      <ModelHolo url={url(m.media)} name={m.name} hint={`${alt}: the 3D model it made, on the projection table. It turns slowly; it's the file itself, drawn as a hologram`} />
    ) : (
      <button type="button" className="lab-turn" title={`Put ${m.name} on the projection table: the 3D model it made, as a turning hologram`} onClick={() => setTurn(true)}>
        <Icon id="i-models" size={40} />
        <span className="small">On the table</span>
      </button>
    );
  return <img className="lab-img" src={url(m.thumb && !big ? m.thumb : m.media)} alt={alt} decoding="async" />;
}

/** `compact`: an ended job in the list, its picture small and its stages left out (they all went). */
export function LabJobCard({ job, queue = [], full = false, hero = false, big = false, compact = false }: { job: JobRecord; queue?: JobRecord[]; full?: boolean; hero?: boolean; big?: boolean; compact?: boolean }) {
  const { now, jobAct, mediaUrl } = useLab();
  const t = now();
  const lab = job.lab!;
  const may = useJobMay(job);
  const [confirm, setConfirm] = useState(false);
  const [said, setSaid] = useState<Said>({ at: "idle", words: "" });
  const going = isOpen(job);
  const running = job.state === "running";
  const outs = lab.outputs;
  const shown = running ? lab.preview : outs[0] ?? lab.preview;
  const stop = () => {
    if (said.at === "asking") return;
    setSaid({ at: "asking", words: "" });
    jobAct("cancel", job.id, {}).then(
      (a) => {
        setConfirm(false);
        setSaid({ at: "done", words: a.words || (lab.interrupt ? "Interrupted." : "Taken out of the queue.") });
      },
      (e) => setSaid({ at: "refused", words: e instanceof ApiError ? e.words : "The server couldn't do that." }),
    );
  };
  const where = lab.source === "comfyui" ? `ComfyUI ${lab.instance ?? ""}`.trim() : "a job feed";
  const sub = [
    STATE_WORD[job.state],
    lab.workflow && lab.source === "comfyui" ? lab.workflow : null,
    where,
    lab.client ? `from ${lab.client}` : null,
    `queued ${when(job.started_at, t)}`,
  ].filter(Boolean);
  const time = [
    lab.elapsed_ms !== null && job.state !== "queued" ? `${secs(running && lab.estimated ? lab.elapsed_ms : lab.elapsed_ms)} ${going ? "so far" : "to make"}` : null,
    lab.estimate_ms && going ? `usually ${secs(lab.estimate_ms)}` : null,
    lab.estimate_ms && running && lab.elapsed_ms !== null && lab.estimate_ms > lab.elapsed_ms ? `about ${secs(lab.estimate_ms - lab.elapsed_ms)} left` : null,
    job.ended_at ? `ended ${ago(job.ended_at, t)}` : null,
  ].filter(Boolean);
  const look = job.state === "failed" ? " fail" : running ? " run" : "";
  const picHint = running
    ? lab.preview ? "The picture as ComfyUI makes it: its preview, updated as it samples" : "No live picture: this ComfyUI sends none for this job (docs/activity.md, \"Live progress and previews\")"
    : shown ? `What it made: ${shown.name}` : going ? "It hasn't started: the picture comes when it runs" : "It made nothing to show";
  return (
    <article className={`job lab${hero ? " hero" : ""}${big ? " big" : ""}${compact ? " compact" : ""}${look}`} title={`${job.title}: ${STATE_HINT[job.state]}`} data-job={job.id}>
      <div className="lab-grid">
        <figure className={`lab-pv holo${running ? " live" : ""}`} title={picHint}>
          {shown ? (
            <Media m={shown} big={big || hero} url={mediaUrl} alt={`${lab.label}: ${KIND_WORD[shown.kind]} ${shown.name}`} />
          ) : (
            <Icon id={jobIcon(job)} size={40} className={`lab-none${running ? " pulse" : ""}`} />
          )}
          <span className="h-scan" aria-hidden="true" />
          <span className="h-edge" aria-hidden="true" />
          {running && (lab.source === "comfyui" || job.pct !== null) && <Ring pct={job.pct} estimated={lab.estimated} size={hero ? 72 : compact ? 40 : 56} />}
        </figure>
        <div className="lab-body">
          <div className="head">
            <Icon id={jobIcon(job)} className={job.state === "failed" ? "bad" : running ? "lit" : ""} />
            <span>
              <b>{job.title}</b>
              <span className="sub">{sub.join(" · ")}</span>
            </span>
            <span className="tags">
              {running && lab.source === "comfyui" && (
                <span className={`chip${lab.estimated ? "" : " lit"}`} title={lab.estimated ? "Estimated: ComfyUI sends this job's progress only to whoever queued it. The relay node sends it here too (docs/activity.md)" : "Live: ComfyUI's own word on the node that runs and the sampler's steps"}>
                  {lab.estimated ? "ESTIMATE" : "LIVE"}
                </span>
              )}
              <span className={STATE_CHIP[job.state]} title={STATE_HINT[job.state]}>
                {STATE_WORD[job.state].toUpperCase()}
              </span>
            </span>
          </div>
          {job.stage && going && (
            <p className={`lab-stage${running ? "" : " muted"}`} title={running ? "The stage it's at now" : "Its place in the queue"}>
              {job.stage}
            </p>
          )}
          {job.steps.length > 0 && !(compact && job.state === "succeeded") && (
            <ol className="lab-steps" aria-label="Its stages">
              {job.steps.map((s) => {
                const k = STEP[s.state];
                return (
                  <li key={s.id} className={k.cls} title={`${s.label}: ${k.word}${s.detail ? ` (${s.detail})` : ""}`}>
                    <Icon id={k.icon} size={16} className={s.state === "running" && running ? "pulse" : ""} />
                    {s.label}
                  </li>
                );
              })}
            </ol>
          )}
          {running && job.pct !== null && !hero && (
            <div className="prog" title={lab.estimated ? `About ${job.pct} %: estimated` : `${job.pct} % done`} aria-hidden="true">
              <i style={{ "--v": `${Math.max(0, Math.min(100, job.pct))}%` } as CSSProperties} />
            </div>
          )}
          {time.length > 0 && <p className="small muted lab-time" title="How long it has taken, and how long this workflow usually takes here">{time.join(" · ")}</p>}
          {lab.prompt && (full || hero) && !compact && (
            <p className="small lab-prompt" title="What it was asked to make (the prompt), or the picture it was given">
              {lab.prompt}
            </p>
          )}
          {hero && queue.length > 0 && (
            <div className="lab-queue" title="The queue behind it, in the order ComfyUI will run them">
              <span className="k">NEXT · {queue.length}</span>
              <ol>
                {queue.slice(0, 5).map((q) => (
                  <li key={q.id}>
                    <a href={`#job/${q.id}`} title={`${q.title}: ${q.stage ?? "queued"}. Opens it`}>
                      <Icon id={jobIcon(q)} size={16} />
                      {q.title}
                    </a>
                  </li>
                ))}
                {queue.length > 5 && <li className="muted">and {queue.length - 5} more</li>}
              </ol>
            </div>
          )}
          {outs.length > 1 && (
            <ul className="lab-outs" aria-label="What it made">
              {outs.slice(0, 8).map((o, i) => (
                <li key={`${o.name}-${i}`}>
                  {o.media ? (
                    <a href={mediaUrl(o.media)} target="_blank" rel="noopener" title={`Open ${o.name}: the ${KIND_WORD[o.kind]} it made, full size`}>
                      {o.kind === "image" && o.thumb ? <img src={mediaUrl(o.thumb)} alt={o.name} decoding="async" /> : <Icon id={o.kind === "video" ? "i-film" : o.kind === "model3d" ? "i-models" : "i-photos"} />}
                    </a>
                  ) : (
                    <span title={`${o.name}: the lab didn't keep this one`}>
                      <Icon id="i-photos" className="muted" />
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {job.error && job.state === "failed" && (
            <p className="small job-why" title="Why it stopped, in ComfyUI's words">
              {job.error.words}
            </p>
          )}
          {job.result?.summary && !going && (
            <p className="small muted job-why" title={job.state === "succeeded" ? "What it made" : "How it ended"}>
              {job.result.summary}
            </p>
          )}
          {going && may.cancel && !confirm && (
            <div className="job-acts">
              {lab.interrupt ? (
                <IconButton icon="i-stop" move="beat" label={`Interrupt ${job.title}`} hint="Interrupt it: ComfyUI stops this generation where it is. It asks first" aria-disabled={said.at === "asking"} onClick={() => setConfirm(true)} />
              ) : (
                <IconButton icon="i-cancel" move="beat" label={`Take ${job.title} out of the queue`} hint="Take it out of the queue: it never runs. Nothing else changes" aria-disabled={said.at === "asking"} onClick={stop} />
              )}
              {shown?.media && (
                <a className="ib" href={mediaUrl(shown.media)} target="_blank" rel="noopener" title="Open the picture full size" aria-label="Open the picture full size">
                  <Icon id="i-open" move="out" />
                </a>
              )}
            </div>
          )}
          {!going && shown?.media && (
            <div className="job-acts">
              <a className="ib" href={mediaUrl(shown.media)} target="_blank" rel="noopener" title={`Open ${shown.name}: the ${KIND_WORD[shown.kind]} it made, full size`} aria-label={`Open ${shown.name}`}>
                <Icon id="i-open" move="out" />
              </a>
              {!full && (
                <a className="ib" href={`#job/${job.id}`} title="Look closer: the job's sheet, with what it made as large as it goes" aria-label="Look closer">
                  <Icon id="i-eye" move="beat" />
                </a>
              )}
            </div>
          )}
          {confirm && (
            <div className="job-danger confirm" role="group" aria-label="Interrupt it?">
              <p>
                <Icon id="i-alert" size={16} /> <b>Interrupt this generation?</b> ComfyUI stops it where it is, and what it made so far is lost. The queue behind it carries on.
              </p>
              <span className="job-ans">
                <button type="button" className="wordbtn armed" aria-disabled={said.at === "asking"} title="Interrupt it now" onClick={stop}>
                  Interrupt
                </button>
                <button type="button" className="wordbtn back" title="Back: nothing is sent, and it carries on" onClick={() => setConfirm(false)}>
                  Back
                </button>
              </span>
            </div>
          )}
          {said.at !== "idle" && (
            <p className={`job-said ${said.at === "refused" ? "signin-err" : "small"}`} role="status">
              {said.at === "asking" ? "Asking the server…" : said.words}
            </p>
          )}
          {full && (
            <details className="depth">
              <summary title="Depth: where it runs, its ids, and the commands for it at a terminal">
                <Icon id="i-chev" size={16} />
                Where it runs, and the commands
              </summary>
              <dl className="kv">
                <dt>Job</dt>
                <dd>{job.id}</dd>
                <dt>Runs on</dt>
                <dd>{where}</dd>
                {lab.workflow && (
                  <>
                    <dt>Workflow</dt>
                    <dd>{lab.workflow}</dd>
                  </>
                )}
                <dt>Look closer</dt>
                <dd>
                  <code>bromigos activity show {job.id}</code>
                </dd>
                {going && job.can.includes("cancel") && (
                  <>
                    <dt>{lab.interrupt ? "Interrupt" : "Unqueue"}</dt>
                    <dd>
                      <code>bromigos activity cancel {job.id}</code>
                    </dd>
                  </>
                )}
                <dt>Watch</dt>
                <dd>
                  <code>bromigos activity watch {job.id}</code>
                </dd>
              </dl>
            </details>
          )}
        </div>
      </div>
    </article>
  );
}
