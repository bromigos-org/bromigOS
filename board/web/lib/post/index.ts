// THE POST: the lab's jobs as a station's crew at work, for a page to host.
//
//   import "…/post.css";                           // the host links the stylesheet (scoped under .post)
//   const post = mountPost(el, { data, base: "/post/", onNavigate, onError, onReady });
//   post.update(data);                             // new jobs: no remount, no art fetched again
//   post.setReduced(true);                         // nobody walks, no clip plays
//   post.unmount();                                // or unmountPost(el)
//
// It is drawn only from `PostData` (types.ts): the job records, as the page has them. Which job
// stands where is one table (places.ts). What it is handed is untrusted: it is made to fit the
// types at the door (sane.ts), and its text reaches the page only as an attribute's value, never
// as markup. It works under `Content-Security-Policy: default-src 'self'`: no injected <style>,
// no style attribute in markup, no inline handler, no data: URL. Every mount lives under one
// root (.post), sets nothing page-level, and removes every listener it added outside its root
// on unmount. Its loop stops while it is off screen, while the page is hidden, and under
// reduced motion.
import { Post } from "./post";
import type { PostHandle, PostOptions } from "./types";

const live = new WeakMap<Element, PostHandle>();

/** The Activity view's hero: the station, with a crew member at each job that runs or asks. */
export function mountPost(el: HTMLElement, options: PostOptions): PostHandle {
  live.get(el)?.unmount();
  const h = new Post(el, options);
  live.set(el, h);
  return h;
}
export function unmountPost(el: HTMLElement): void { live.get(el)?.unmount(); live.delete(el); }

export { fromJobs } from "./from-jobs";
export { PLACES, RULES, STATES, placeFor } from "./places";
export const version = "post/1";
export type * from "./types";
