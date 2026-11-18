// The board's job records (`JobRecord`, lib/api/types.ts) as the post's data. Nothing is added
// that a record didn't say.
//
// The types here are only the keys this reads, so the board's own records can be passed as they
// are. The result goes through sane() (sane.ts): a state that isn't one becomes "unknown", and a
// share done that isn't a number from 0 to 100 is absent.
import { sane } from "./sane";
import type { PostData } from "./types";

export interface JobLike {
  id: string;
  kind: string;
  title: string;
  state: string;
  pct: number | null;
  stage: string | null;
  step: number | null;
  steps: { label: string }[];
  agent: string | null;
  parent: string | null;
  result: { ok: boolean } | null;
}

const text = (v: unknown): string => (typeof v === "string" ? v : "");

/** Where a job is, in its record's own words: its step by number and name, or its stage. */
function where(j: JobLike): string | null {
  const steps = Array.isArray(j?.steps) ? j.steps : [];
  if (steps.length && typeof j.step === "number" && steps[j.step]) return [`step ${j.step + 1} of ${steps.length}`, text(steps[j.step]?.label)].filter(Boolean).join(" · ");
  return text(j?.stage) || null;
}

/** `known`: whether the page has read the jobs at all. Until it has, the post shows nobody. */
export function fromJobs(jobs: JobLike[] | null | undefined, known: boolean): PostData {
  const list = Array.isArray(jobs) ? jobs.filter((j) => j && typeof j === "object") : [];
  return sane({
    known,
    jobs: list.map((j) => ({ id: j.id, kind: j.kind, title: j.title, state: j.state, step: where(j), pct: j.pct, agent: j.agent, parent: j.parent, ok: j.result && typeof j.result === "object" ? j.result.ok : null })),
  });
}
