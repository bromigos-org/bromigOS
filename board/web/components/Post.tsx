// The post on the Lab board: Activity's hero. The lab's jobs as a station's crew at work: a
// crew member walks to each job that runs or asks and stands at its place, and nothing is drawn
// that a job record didn't say. The post is a module with no React in it (lib/post/): it is
// handed the jobs the page has (fromJobs) and where its art is served, and Activity's list
// under it stays the place that says everything in words.
//
// The module loads only when the hero is on screen. Until it has, and whenever it can't (a
// script or the station's drawing that didn't arrive), the hero's frame carries the jobs' plain
// state: how many run, how many ask, or that the jobs haven't been read.
import { useEffect, useRef, useState } from "react";
import { isOpen } from "@/lib/jobs";
import { useLab } from "@/lib/lab";
import { fromJobs } from "@/lib/post/from-jobs";
import type { PostData, PostHandle } from "@/lib/post/types";

/** Where the art is served: board/web/public/post/ (docs/ASSETS.md). */
const BASE = "/post/";

/** Where the post's intents go: the board's own routes. `job/ID` opens a job as Activity's list does. */
function go(route: string) {
  window.location.hash = route;
}

/** Mounts the post in `el` once it is on screen, hands it each new list of jobs, and unmounts it with the component. */
function usePost(data: PostData) {
  const el = useRef<HTMLDivElement>(null);
  const handle = useRef<PostHandle | null>(null);
  const latest = useRef(data);
  latest.current = data;
  const [on, setOn] = useState(false);
  useEffect(() => {
    const host = el.current;
    if (!host) return;
    let gone = false;
    const load = () =>
      import("@/lib/post")
        .then((post) => {
          if (gone) return;
          // the fixture build's tests draw the module from data of their own (tests/post-hostile.spec.ts); compiled out of the real build
          if (process.env.NEXT_PUBLIC_BOARD_FIXTURES === "1") (window as unknown as { __post?: unknown }).__post = post;
          handle.current = post.mountPost(host, {
            data: latest.current,
            base: BASE,
            onNavigate: go,
            onReady: () => !gone && setOn(true),
            onError: (e) => console.warn("The post couldn't be drawn; the hero keeps the jobs' plain state:", e),
          });
        })
        .catch((e) => console.warn("The post couldn't be loaded; the hero keeps the jobs' plain state:", e));
    // only when the hero is on screen: a page opened on a job's sheet, or scrolled past it, loads nothing
    let io: IntersectionObserver | null = null;
    if (typeof IntersectionObserver === "function") {
      io = new IntersectionObserver((es) => {
        if (!es.some((e) => e.isIntersecting)) return;
        io?.disconnect();
        void load();
      });
      io.observe(host.parentElement ?? host);
    } else void load();
    return () => {
      gone = true;
      io?.disconnect();
      handle.current?.unmount();
      handle.current = null;
      setOn(false);
    };
  }, []);
  const key = JSON.stringify(data);
  useEffect(() => {
    handle.current?.update(latest.current);
  }, [key]);
  return { el, on };
}

/** Activity's hero: the station, with a crew member at each job that runs or asks. */
export function Post() {
  const { jobs, jobsKnown } = useLab();
  const data = fromJobs(jobs, jobsKnown);
  const { el, on } = usePost(data);
  const top = jobs.filter((j) => !j.parent && isOpen(j));
  const running = top.filter((j) => j.state === "running").length;
  const asking = top.filter((j) => j.state === "needs-you").length;
  const words = !jobsKnown
    ? "THE JOBS HAVEN'T BEEN READ YET"
    : running || asking
      ? [running ? `${running} JOB${running === 1 ? "" : "S"} RUNNING` : "", asking ? `${asking} NEED${asking === 1 ? "S" : ""} YOU` : ""].filter(Boolean).join(" · ")
      : "NOTHING IS RUNNING";
  return (
    <section className={`post-hero${on ? " on" : ""}`} aria-label="The post">
      <div className="post-mount" data-post="mount" ref={el} />
      {!on && (
        <div className="post-wait" title="The post: the lab's jobs as a station's crew at work. While its picture loads, or if it can't, the jobs' state shows here. The list under it has every job.">
          <p className={`post-line${asking ? " warn" : !jobsKnown ? " q" : ""}`} role="status">
            {words}
          </p>
        </div>
      )}
    </section>
  );
}
