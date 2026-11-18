// The post on the page: the station's paintings, its crew, and what the pointer reaches. It
// draws the model (model.ts) and nothing else, so a figure, a ring or a lit room is always a job
// record's doing.
//
// Under `Content-Security-Policy: default-src 'self'`: every element is made with
// createElement, text reaches the page only through `title`, `aria-label` and a data attribute
// (never as markup), every position and size is set through the CSSOM, and every picture and
// clip is asked for under the art folder's own address, by a name this module made.
import { CORRIDOR_Z, type Room, band } from "./floor";
import { type Figure, type Live, type Loop, type News, Model } from "./model";
import { type PlaceId, PLACES, RULES, placeRule } from "./places";
import { sane, sanePack } from "./sane";
import type { PostData, PostHandle, PostOptions, PostPack, Pt } from "./types";

const NS = "http://www.w3.org/2000/svg";
const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls = ""): HTMLElementTagNameMap[K] => { const e = document.createElement(tag); if (cls) e.className = cls; return e; };
const svg = <K extends keyof SVGElementTagNameMap>(tag: K, cls = ""): SVGElementTagNameMap[K] => { const e = document.createElementNS(NS, tag); if (cls) e.setAttribute("class", cls); return e; };
/** Set declarations through the CSSOM, which the policy allows (a style attribute in markup it does not). */
const css = (e: HTMLElement | SVGElement, props: Record<string, string>) => { for (const k in props) e.style.setProperty(k, props[k]); };
const play = (v: HTMLVideoElement) => { v.play().catch(() => { /* a clip that can't play leaves the room's still */ }); };

/**
 * A loop: an animated picture that can be held still. Under reduced motion its first frame is
 * drawn once on a canvas in its place, because an animated picture can't be paused. It is
 * fetched the first time it is wanted.
 */
class Pic {
  readonly img = el("img");
  private cv: HTMLCanvasElement | null = null;
  private up = false;
  private still = false;
  constructor(private parent: HTMLElement, private src: string) {
    this.img.alt = ""; this.img.hidden = true; this.img.decoding = "async";
    this.img.addEventListener("load", () => this.sync());
    parent.append(this.img);
  }
  /** Ask for the picture now, so it is there when it is first shown. */
  warm(): void { if (!this.img.getAttribute("src")) this.img.src = this.src; }
  show(up: boolean, still: boolean): void { this.up = up; this.still = still; if (up) this.warm(); this.sync(); }
  private sync(): void {
    const frozen = this.up && this.still;
    this.img.hidden = !this.up || this.still;
    if (frozen && this.img.complete && this.img.naturalWidth) {
      if (!this.cv) {
        this.cv = el("canvas");
        this.cv.width = this.img.naturalWidth; this.cv.height = this.img.naturalHeight;
        css(this.cv, { height: this.img.style.getPropertyValue("height") });
        this.cv.getContext("2d")?.drawImage(this.img, 0, 0);
        this.parent.insertBefore(this.cv, this.img);
      }
    }
    if (this.cv) this.cv.hidden = !frozen;
  }
}

type Clip = "idle" | "work" | "done";
interface RoomView { R: Room; glow: HTMLImageElement; clips: Partial<Record<Clip, HTMLVideoElement>>; clip: Clip | null; hit: HTMLElement; after: Element }
interface MachView { place: PlaceId; pics: Record<"idle" | "run" | "done", Pic>; shown: "idle" | "run" | "done"; hit: HTMLElement; mark: SVGSVGElement }
interface FigView { c: Figure; node: HTMLElement; pics: Partial<Record<Loop, Pic>>; shown: Loop | null; ring: SVGSVGElement; fill: SVGEllipseElement; hit: HTMLElement; spark: number }

/** How often each kind of work throws something off, in seconds. */
const EVERY: Record<string, number> = { weld: 0.12, crank: 0.15, holo: 0.32, work: 0.2, scan: 1.15, pack: 0.8, lift: 1.1 };
const quote = (title: string) => `“${title || "a job with no title"}”`;

export class Post implements PostHandle {
  private root: HTMLElement;
  private base: string;
  private data: PostData;
  private model: Model | null = null;
  private rel: Record<string, number> = {};
  private stage!: HTMLElement;
  private fx!: SVGSVGElement;
  private size: Pt = [1, 1];
  private roomViews: RoomView[] = [];
  private machViews: MachView[] = [];
  private figViews: FigView[] = [];
  private padHit!: HTMLElement;
  private padGlow!: HTMLImageElement;
  private padMark!: SVGSVGElement;
  private ship!: { node: HTMLElement; shade: HTMLElement; pics: { idle: Pic; fly: Pic }; fold: HTMLElement; frames: number; frame: number; strip: string | null; warmed: boolean };
  private lights: Animation[] = [];
  private sparks = 0;
  private undo: (() => void)[] = [];
  private dead = false;
  private seen = true;
  private raf = 0;
  private last = 0;
  private painted = 0;

  constructor(host: HTMLElement, private o: PostOptions) {
    this.data = sane(o.data);
    this.base = (o.base ?? "/post/").replace(/\/?$/, "/");
    this.root = el("div", "post");
    this.root.setAttribute("role", "group");
    this.root.setAttribute("aria-label", "The post: the lab's jobs as a station's crew at work. The list under it says the same in words.");
    host.appendChild(this.root);
    void this.load();
  }

  private get reduced(): boolean {
    return !!this.o.reduced || (typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  }
  /** The loop runs only while there is something to see: the hero on screen, the page showing, motion allowed. */
  private get running(): boolean { return !this.dead && !!this.model && !this.reduced && this.seen && !document.hidden; }
  private url(name: string): string { return this.base + name; }
  private left = (p: Pt) => `${((p[0] / this.size[0]) * 100).toFixed(3)}%`;
  private top = (p: Pt) => `${((p[1] / this.size[1]) * 100).toFixed(3)}%`;

  /** The station's drawing is the art folder's own post.json. Until it is here, and if it never is, the host's plain state stands. */
  private async load(): Promise<void> {
    try {
      const r = await fetch(this.url("post.json"), { credentials: "same-origin" });
      if (!r.ok) throw new Error(`The post's drawing didn't arrive (${r.status}).`);
      const pack = sanePack(await r.json());
      if (!pack) throw new Error("The post's drawing isn't one the page can draw.");
      if (this.dead) return;
      this.build(pack);
      this.o.onReady?.();
    } catch (e) {
      if (!this.dead) this.o.onError?.(e);
    }
  }

  // ---------------------------------------------------------------- building: once, when the drawing arrives

  private build(pack: PostPack): void {
    const m = (this.model = new Model(pack.map)), map = pack.map, [W, H] = (this.size = map.size);
    this.rel = pack.crew;
    const stage = (this.stage = el("div", "station"));
    css(stage, { "--ar": String(W / H) });

    // the stars: three layers that breathe out of step
    for (let k = 0; k < 3; k++) {
      const cv = el("canvas", "stars"), g = cv.getContext("2d");
      cv.width = W / 2; cv.height = H / 2; cv.setAttribute("aria-hidden", "true");
      css(cv, { "--d": `${2.4 + k * 1.3}s`, "--w": `${-k * 1.1}s` });
      let seed = 11 + k * 97;
      const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
      if (g) for (let i = 0; i < 190; i++) {
        const r = rnd() < 0.12 ? 0.8 : 0.45;
        g.fillStyle = ["#ffffff", "#bfe9ff", "#ffe3b0"][i % 3]; g.globalAlpha = 0.35 + rnd() * 0.65;
        g.beginPath(); g.arc(rnd() * cv.width, rnd() * cv.height, r, 0, 7); g.fill();
      }
      stage.append(cv);
    }

    // the rooms, far to near: each room's painting, its lights, and (made when first wanted) its living clips
    const pods = el("div", "pods"), hits = el("div", "hits");
    pods.setAttribute("aria-hidden", "true");
    stage.append(pods);
    m.rooms.forEach((R, i) => {
      const rect = (e: HTMLElement) => {
        css(e, { left: `${(R.rect[0] / W) * 100}%`, top: `${(R.rect[1] / H) * 100}%`, width: `${(R.rect[2] / W) * 100}%`, height: `${(R.rect[3] / H) * 100}%`, "z-index": String(R.z) });
        if (R.flip) e.classList.add("flip");
      };
      const still = el("img", "pod"), glow = el("img", "glow");
      still.alt = ""; still.src = this.url(`pod-${R.type}.webp`); rect(still);
      glow.alt = ""; glow.src = this.url(`glow-${R.type}.webp`); rect(glow);
      css(glow, { "--d": `${2.1 + ((i * 0.83) % 2.4)}s`, "--w": `${-(i * 1.37)}s` });
      pods.append(still, glow);
      const hit = this.hit(hits, "room");
      this.shape(hit, R.poly);
      this.roomViews.push({ R, glow, clips: {}, clip: null, hit, after: still });
    });

    // the machines: separate pieces with their own idle, running and finished loops
    for (const place of PLACES.map((p) => p.place)) {
      const spot = m.spots[place], mach = spot?.machine, R = spot?.room;
      if (!mach || !R) continue;
      const node = el("div", `mach${R.flip ? " flip" : ""}`), z = String(R.z + 1 + Math.round(mach.at[1]));
      node.setAttribute("aria-hidden", "true");
      css(node, { left: this.left(mach.at), top: this.top(mach.at), height: `${mach.tall * 100}%`, "z-index": z });
      const pics = { idle: new Pic(node, this.url(`m-${place}-idle.webp`)), run: new Pic(node, this.url(`m-${place}-run.webp`)), done: new Pic(node, this.url(`m-${place}-done.webp`)) };
      stage.append(node);
      const hit = this.hit(hits, "mach at");
      css(hit, { left: this.left(mach.at), top: this.top(mach.at), height: `${mach.tall * 100}%` });
      this.machViews.push({ place, pics, shown: "idle", hit, mark: this.mark(spot.at, R.z + 1 + Math.round(spot.at[1])) });
    }

    // the corridors, the pad and the arrays: one painting over the rooms, and its lights
    const frame = el("img", "frame");
    frame.alt = ""; frame.setAttribute("aria-hidden", "true"); frame.src = this.url("frame.webp");
    stage.append(frame);
    ["x1", "x2", "x3", "pad"].forEach((k, i) => {
      const g = el("img", `glow fr${k === "pad" ? "" : " tw"}`);
      g.alt = ""; g.setAttribute("aria-hidden", "true"); g.src = this.url(`glow-${k}.webp`);
      css(g, { "--d": `${4.3 + i * 1.7}s`, "--w": `${-(i * 1.9)}s` });
      stage.append(g);
      if (k === "pad") this.padGlow = g;
    });
    this.padHit = this.hit(hits, "pad");
    this.shape(this.padHit, map.padPoly);
    this.padMark = this.mark(m.spots.pad.at, CORRIDOR_Z + 1 + Math.round(m.spots.pad.at[1]));

    // the shuttle: parked on its legs, flying with them folded away, and between the two one strip of frames of them folding
    const node = el("div", "ship"), shade = el("div", "shipshade"), fold = el("div", "fold");
    node.setAttribute("aria-hidden", "true"); node.hidden = true; shade.hidden = true; fold.hidden = true;
    css(node, { width: `${(236 / W) * 100}%` });
    if (pack.ship) { css(node, { "aspect-ratio": `${pack.ship.w} / ${pack.ship.h}` }); css(fold, { "background-size": `${pack.ship.frames * 100}% 100%` }); }
    css(shade, { left: this.left(m.ship.home), top: this.top([m.ship.home[0], m.ship.home[1] + 26]) });
    this.ship = { node, shade, pics: { idle: new Pic(node, this.url("ship-idle.webp")), fly: new Pic(node, this.url("ship-fly.webp")) }, fold, frames: pack.ship?.frames ?? 0, frame: -1, strip: pack.ship ? this.url("ship-fold.webp") : null, warmed: false };
    node.append(fold);
    stage.append(shade, node);

    // the crew: each with the ring of light that shows under them while they work
    for (const c of m.crew) {
      const node = el("div", "act"), ring = svg("svg", "ring"), track = svg("ellipse", "track"), fill = svg("ellipse", "fill");
      node.setAttribute("aria-hidden", "true");
      ring.setAttribute("viewBox", "-36 -18 72 36"); ring.setAttribute("hidden", "");
      css(ring, { height: `${(36 / (c.tall * H)) * 100}%` });
      fill.setAttribute("pathLength", "100");
      for (const e of [track, fill]) { e.setAttribute("rx", "32"); e.setAttribute("ry", "16"); ring.append(e); }
      node.append(ring);
      stage.append(node);
      const hit = this.hit(hits, "fig at");
      css(hit, { height: `${c.tall * 100}%` });
      const v: FigView = { c, node, pics: {}, shown: null, ring, fill, hit, spark: 0 };
      for (const k of ["to", "away", "idle"] as const) this.loop(v, k).warm();
      this.figViews.push(v);
    }

    this.fx = svg("svg", "fx");
    this.fx.setAttribute("viewBox", `0 0 ${W} ${H}`); this.fx.setAttribute("aria-hidden", "true");
    stage.append(this.fx, hits);
    this.root.append(stage);

    // the loop stops while the hero is off screen or the page is hidden, and under reduced motion
    if (typeof IntersectionObserver === "function") {
      const io = new IntersectionObserver((es) => { this.seen = es[es.length - 1].isIntersecting; this.sync(); }, { rootMargin: "60px" });
      io.observe(this.root);
      this.undo.push(() => io.disconnect());
    }
    const hidden = () => this.sync();
    document.addEventListener("visibilitychange", hidden);
    this.undo.push(() => document.removeEventListener("visibilitychange", hidden));
    if (typeof matchMedia === "function") {
      const mq = matchMedia("(prefers-reduced-motion: reduce)"), changed = () => this.still();
      mq.addEventListener("change", changed);
      this.undo.push(() => mq.removeEventListener("change", changed));
    }
    this.still();
  }

  /** Something the pointer and the keyboard reach. With a job it is a button that opens it; without, a picture with a hint. */
  private hit(layer: HTMLElement, cls: string): HTMLElement {
    const h = el("div", `hit ${cls}`);
    const go = () => { const id = h.dataset.job; if (id) this.o.onNavigate?.(`job/${id}`, { job: id }); };
    h.addEventListener("click", go);
    h.addEventListener("keydown", (e) => { if (h.dataset.job && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); go(); } });
    layer.append(h);
    return h;
  }

  /** A hit area the shape of a patch of floor: its box, cut to its corners. */
  private shape(h: HTMLElement, poly: Pt[]): void {
    const [W, H] = this.size, xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]);
    const x0 = Math.min(...xs), y0 = Math.min(...ys), w = Math.max(...xs) - x0 || 1, hh = Math.max(...ys) - y0 || 1;
    css(h, {
      left: `${(x0 / W) * 100}%`, top: `${(y0 / H) * 100}%`, width: `${(w / W) * 100}%`, height: `${(hh / H) * 100}%`,
      "clip-path": `polygon(${poly.map((p) => `${(((p[0] - x0) / w) * 100).toFixed(2)}% ${(((p[1] - y0) / hh) * 100).toFixed(2)}%`).join(", ")})`,
    });
  }

  /** The amber ring alone on the floor: a job asks at this place and nobody is free to stand there. */
  private mark(at: Pt, z: number): SVGSVGElement {
    const ring = svg("svg", "ring ask"), track = svg("ellipse", "track"), fill = svg("ellipse", "fill"), node = el("div", "mark");
    ring.setAttribute("viewBox", "-36 -18 72 36");
    fill.setAttribute("pathLength", "100");
    for (const e of [track, fill]) { e.setAttribute("rx", "32"); e.setAttribute("ry", "16"); ring.append(e); }
    css(ring, { height: `${(36 / (0.05 * this.size[1])) * 100}%` });
    css(node, { left: this.left(at), top: this.top(at), "z-index": String(z) });
    node.setAttribute("aria-hidden", "true"); node.hidden = true;
    node.append(ring);
    this.stage.append(node);
    return ring;
  }

  /** A crew member's loop, made the first time it is wanted (each has ten or so, and most days use a few). */
  private loop(v: FigView, k: Loop): Pic {
    let key = k;
    if (key !== "to" && key !== "away" && !this.rel[`${v.c.id}-${key}`]) key = key === "idle" ? "idle" : "work";      // a loop that was never made
    let pic = v.pics[key];
    if (!pic) {
      pic = v.pics[key] = new Pic(v.node, this.url(`${v.c.id}-${key}.webp`));
      css(pic.img, { height: `${(this.rel[`${v.c.id}-${key}`] ?? 1) * 100}%` });
    }
    return pic;
  }

  // ---------------------------------------------------------------- the host's calls

  update(data: PostData): void {
    this.data = sane(data);
    const m = this.model;
    if (!m) return;
    m.set(this.data, this.reduced);
    if (!this.running) m.news = [];        // nobody saw it happen: nothing is played later
    this.paint(); this.draw();
  }

  setReduced(on: boolean): void { this.o.reduced = on; if (this.model) this.still(); }

  unmount(): void {
    this.dead = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    for (const a of this.lights) a.cancel();
    for (const v of this.roomViews) for (const c of Object.values(v.clips)) c.pause();
    for (const f of this.undo) f();
    this.undo = [];
    this.root.remove();
  }

  /** Motion was turned on or off (or this is the first drawing): everyone stands where they belong, and what loops starts or stops. */
  private still(): void {
    const m = this.model!, r = this.reduced;
    this.root.classList.toggle("reduced", r);
    m.set(this.data, r);
    m.news = [];
    if (r) {
      for (const a of this.lights) a.cancel();
      this.lights = [];
      for (const v of this.roomViews) { for (const c of Object.values(v.clips)) { c.classList.remove("on"); c.pause(); } v.clip = null; }
    } else if (!this.lights.length) this.chase();
    this.paint(); this.draw(); this.sync();
  }

  /** The corridors' running lights. */
  private chase(): void {
    this.model!.map.lanes.forEach((ln, i) => {
      for (let k = 0; k < ln[2]; k++) {
        const d = el("div", "chase");
        d.setAttribute("aria-hidden", "true");
        this.stage.append(d);
        const a = d.animate(
          [{ left: this.left(ln[0]), top: this.top(ln[0]), opacity: 0 }, { opacity: 1, offset: 0.08 }, { opacity: 1, offset: 0.92 }, { left: this.left(ln[1]), top: this.top(ln[1]), opacity: 0 }],
          { duration: ln[2] * 3000, iterations: Infinity, delay: -(k * 3000 + i * 700) });
        a.addEventListener("cancel", () => d.remove());
        this.lights.push(a);
      }
    });
  }

  /** Start or stop the loop, the clips and the lights, to match whether there is anything to see. */
  private sync(): void {
    const on = this.running;
    this.root.classList.toggle("idle", !on && !this.reduced);
    if (on && !this.raf) {
      for (const a of this.lights) a.play();
      for (const v of this.roomViews) { const c = v.clip && v.clips[v.clip]; if (c) play(c); }
      this.last = performance.now();
      this.raf = requestAnimationFrame(this.tick);
    } else if (!on && this.raf) {
      cancelAnimationFrame(this.raf); this.raf = 0;
      for (const a of this.lights) a.pause();
      for (const v of this.roomViews) for (const c of Object.values(v.clips)) c.pause();
    }
  }

  private tick = (now: number): void => {
    this.raf = 0;
    if (!this.running) return;
    const m = this.model!, dt = Math.min(0.25, Math.max(0, (now - this.last) / 1000));
    this.last = now;
    m.step(dt);
    for (const n of m.news.splice(0)) this.burst(n);
    for (const v of this.figViews) if (v.c.state === "work") this.effect(v, dt);
    this.draw();
    if (now - this.painted > 200) this.paint();
    this.raf = requestAnimationFrame(this.tick);
  };

  // ---------------------------------------------------------------- drawing: every frame

  private draw(): void {
    const m = this.model!, map = m.map, r = this.reduced;
    this.root.classList.toggle("unknown", !m.known);
    for (const v of this.figViews) {
      const c = v.c, at = { left: this.left(c.pos), top: this.top(c.pos) };
      v.node.hidden = !m.known; v.hit.hidden = !m.known;
      css(v.node, { ...at, height: `${c.tall * 100}%`, "z-index": String(band(map, m.rooms, c.pos) + 1 + Math.round(c.pos[1])) });
      css(v.hit, at);
      const want = this.loop(v, c.look);
      if (v.shown !== c.look) { for (const p of Object.values(v.pics)) if (p !== want) p.show(false, r); v.shown = c.look; }
      want.show(true, r);
      v.node.classList.toggle("flip", c.flip);
      this.ring(v);
    }
    const s = m.ship, away = s.state === "away", S = this.ship;
    S.node.hidden = away; S.shade.hidden = away;
    if (!away) {
      // its pictures are asked for when it is first called, so its legs are there by the time it is near the pad
      if (!S.warmed) { S.warmed = true; S.pics.idle.warm(); S.pics.fly.warm(); if (S.strip) { const strip = new Image(); strip.src = S.strip; css(S.fold, { "background-image": `url("${S.strip}")` }); } }
      const look = s.look === "fold" && !S.strip ? "fly" : s.look;
      S.pics.idle.show(look === "idle", r); S.pics.fly.show(look === "fly", r);
      S.fold.hidden = look !== "fold";
      if (look === "fold") {
        const f = Math.round(s.folded * (S.frames - 1));
        if (f !== S.frame) { S.frame = f; css(S.fold, { "background-position-x": `${(f / (S.frames - 1)) * 100}%` }); }
      }
      css(S.node, { left: this.left(s.at), top: this.top(s.at), "z-index": String(s.far > 0.02 ? 39000 : CORRIDOR_Z - 10 + Math.round(s.home[1])) });
      css(S.shade, { opacity: String(Math.max(0, 1 - s.far * 2.2)) });
    }
    this.padGlow.classList.toggle("busy", s.state === "in" || s.state === "out");
  }

  /** The ring under a crew member: the job's own share done, a short arc that turns when it never said one, amber when it asks. */
  private ring(v: FigView): void {
    const c = v.c, L = c.job ? this.model!.live.get(c.job) : undefined, on = !!L && (c.state === "work" || c.state === "wait");
    if (on) v.ring.removeAttribute("hidden"); else v.ring.setAttribute("hidden", "");
    if (!on || !L) return;
    const ask = c.state === "wait", pct = L.job.pct;
    v.ring.classList.toggle("ask", ask);
    v.ring.classList.toggle("turn", !ask && pct === null);
    if (!ask && pct !== null) v.fill.setAttribute("stroke-dasharray", `${pct.toFixed(1)} 100`); else v.fill.removeAttribute("stroke-dasharray");
  }

  // ---------------------------------------------------------------- painting: on new data, and five times a second

  private paint(): void {
    const m = this.model!, r = this.reduced;
    this.painted = performance.now();
    for (const v of this.roomViews) {
      const look = m.roomLook(v.R);
      if (!r) this.clip(v, look);
      v.glow.classList.toggle("busy", look === "work");
      v.glow.classList.toggle("flash", m.flash(v.R, "ok"));
      v.hit.classList.toggle("failed", m.flash(v.R, "fail"));
      this.say(v.hit, m.inRoom(v.R), () => this.roomHint(v.R), { R: v.R });
    }
    for (const v of this.machViews) {
      const want = m.machineLook(v.place);
      if (want !== "idle") v.pics.done.warm();          // a machine's finished loop is asked for when a job first runs at it
      for (const k of ["idle", "run", "done"] as const) v.pics[k].show(k === want, r);
      v.shown = want;
      this.toggle(v.mark, m.asksAlone(v.place));
      const rule = placeRule(v.place);
      this.say(v.hit, m.at(v.place), () => `The ${rule.name}. ${rule.says} Nothing is running here now.`);
    }
    const padRule = placeRule("pad");
    this.padGlow.classList.toggle("flash", m.flash(null, "ok"));
    this.padHit.classList.toggle("failed", m.flash(null, "fail"));
    this.toggle(this.padMark, m.asksAlone("pad"));
    this.say(this.padHit, m.at("pad"), () => `The ${padRule.name}. ${padRule.says} Nothing is arriving now.`);
    for (const v of this.figViews) {
      const c = v.c, L = c.job ? m.live.get(c.job) : undefined;
      this.say(v.hit, L ? [L] : [], () => (c.state === "walk" ? `${c.name} is walking back to the ${m.restName}. ${RULES.rest}` : `${c.name}, one of the crew, is resting in the ${m.restName}. ${RULES.rest}`), { c });
    }
  }

  private toggle(ring: SVGSVGElement, on: boolean): void { (ring.parentElement as HTMLElement).hidden = !on; }

  /** A job in a sentence: its own title, where it is, and its share done when it said one. */
  private words(L: Live): string {
    const j = L.job, bits = [j.step, j.pct !== null ? `${Math.round(j.pct)} %` : null].filter(Boolean).join(" · ");
    return `${quote(j.title)}${bits ? ` (${bits})` : ""}`;
  }

  /**
   * A hit area's hint, and whether it is a button. With a job there it says the job's real title
   * and step and opens it; without, it says what the place is for. The job's words are only ever
   * an attribute's value.
   */
  private say(h: HTMLElement, jobs: Live[], idle: () => string, by: { c?: Figure; R?: Room } = {}): void {
    const L = jobs[0], m = this.model!, c = by.c;
    let text: string;
    if (!m.known) text = "The jobs haven't been read yet, so nobody is shown at work.";
    else if (!L) text = idle();
    else {
      const name = placeRule(L.place).name, more = jobs.length > 1 ? ` ${jobs.length - 1} more job${jobs.length > 2 ? "s are" : " is"} here too.` : "";
      const what = L.mode === "ask" ? `${this.words(L)} needs you` : `${this.words(L)} is running`;
      const who = c
        ? (c.state === "walk" ? `${c.name} is walking to the ${name}: ${what}.` : c.state === "wait" ? `${c.name} stands at the ${name}, not working: ${what}.` : `${c.name} is working at the ${name}: ${what}.`)
        : `${by.R ? `The ${by.R.name.toLowerCase()}, at the ${name}` : `The ${name}`}: ${what}.${L.who === null ? " All three crew are busy, so nobody stands here." : ""}${more}`;
      text = `${who} Press to open this job.`;
    }
    const job = m.known && L ? L.job.id : "";
    if (h.title !== text) { h.title = text; h.setAttribute("aria-label", text); }
    if ((h.dataset.job ?? "") !== job) {
      if (job) { h.dataset.job = job; h.setAttribute("role", "button"); h.tabIndex = 0; }
      else { delete h.dataset.job; h.setAttribute("role", "img"); h.removeAttribute("tabindex"); }
    } else if (!h.hasAttribute("role")) h.setAttribute("role", "img");
  }

  private roomHint(R: Room): string {
    const m = this.model!, here = PLACES.filter((p) => m.spots[p.place]?.room === R).map((p) => `the ${p.name}`);
    if (here.length) return `The ${R.name.toLowerCase()}, with ${here.join(" and ")}. Nothing is running here now.`;
    return R.rest.length ? `The ${R.name.toLowerCase()}. ${RULES.rest}` : `The ${R.name.toLowerCase()}. No kind of job is worked here yet.`;
  }

  /** A room's living clip: quiet, busy, or a job finishing. Each is made and fetched the first time the room needs it. */
  private clip(v: RoomView, look: Clip): void {
    const want = v.R.T.clips.includes(look) ? look : v.R.T.clips.includes("idle") ? "idle" : null;
    if (want === v.clip) return;
    const now = v.clip && v.clips[v.clip];
    if (now) { now.classList.remove("on"); now.pause(); }
    v.clip = want;
    if (!want) return;
    let next = v.clips[want];
    if (!next) {
      const R = v.R, [W, H] = this.size, c = (next = v.clips[want] = el("video", `pod${R.flip ? " flip" : ""}`));
      c.muted = true; c.defaultMuted = true; c.playsInline = true; c.loop = want !== "done"; c.preload = "auto"; c.disablePictureInPicture = true;
      c.setAttribute("aria-hidden", "true");
      css(c, { left: `${(R.rect[0] / W) * 100}%`, top: `${(R.rect[1] / H) * 100}%`, width: `${(R.rect[2] / W) * 100}%`, height: `${(R.rect[3] / H) * 100}%`, "z-index": String(R.z), "--m": `url("${this.url(`pod-${R.type}.webp`)}")` });
      c.addEventListener("error", () => c.classList.add("dead"));
      c.src = this.url(`pod-${R.type}-${want}.mp4`);
      v.after.after(c);
    }
    try { next.currentTime = 0; } catch { /* not loaded yet: it starts at its start anyway */ }
    next.classList.add("on");
    if (this.running) play(next);
  }

  // ---------------------------------------------------------------- what is shown once

  /** The burst when a job ends (cyan when it went well, red when it failed), and when the shuttle sets down. */
  private burst(n: News): void {
    if (this.reduced) return;
    const size = n.what === "land" ? 2.2 : 1;
    for (let i = 0; i < 2; i++) {
      const e = svg("ellipse", n.what === "ok" ? "" : n.what);
      e.setAttribute("cx", String(n.at[0])); e.setAttribute("cy", String(n.at[1] - 2)); e.setAttribute("rx", String(32 * size)); e.setAttribute("ry", String(16 * size));
      this.fx.append(e);
      const a = e.animate([{ transform: "scale(1)", opacity: 1 }, { transform: "scale(3.4)", opacity: 0 }], { duration: 900, delay: i * 220, easing: "ease-out", fill: "both" });
      a.finished.then(() => e.remove(), () => e.remove());
    }
  }

  /** What the work throws off, by its kind: sparks, floating panes, a sweep of light, parcels, dust, keystrokes. */
  private effect(v: FigView, dt: number): void {
    const c = v.c, L = c.job ? this.model!.live.get(c.job) : undefined, every = L && EVERY[L.act];
    if (!L || !every) return;
    v.spark += dt;
    if (v.spark < every || this.sparks > 40) return;
    v.spark = 0;
    const u = v.node.offsetHeight, side = L.face, r = Math.random, kind = L.act === "work" ? "type" : L.act, e = el("div", `p p-${kind}`);
    const at = (ax: number, ay: number) => css(e, { left: `calc(${this.left(c.pos)} + ${(side * ax * u).toFixed(1)}px)`, top: `calc(${this.top(c.pos)} - ${(ay * u).toFixed(1)}px)` });
    const T = (x: number, y: number, more = "") => `translate(${(x * u).toFixed(1)}px, ${(y * u).toFixed(1)}px) ${more}`;
    let fr: Keyframe[], ms = 700, ease = "ease-out";
    if (kind === "weld") { at(0.3, 0.55); fr = [{ transform: T(0, 0), opacity: 1 }, { transform: T(side * (0.1 + r() * 0.3), -(0.08 + r() * 0.34), "scale(.3)"), opacity: 0 }]; ms = 420 + r() * 380; }
    else if (kind === "crank") { at(0.34, 0.6); const an = r() * 6.283; fr = [{ transform: T(0, 0), opacity: 1 }, { transform: T(Math.cos(an) * 0.5, Math.sin(an) * 0.34, "scale(.4)"), opacity: 0 }]; ms = 520; }
    else if (kind === "holo") { at(0.15 + r() * 0.5, 0.7 + r() * 0.5); const sk = `skewY(${side * -26}deg)`; fr = [{ transform: T(0, 0.1, sk), opacity: 0 }, { transform: T(0, 0, sk), opacity: 1, offset: 0.25 }, { transform: T((r() - 0.5) * 0.4, -0.22, sk), opacity: 0 }]; ms = 1300; }
    else if (kind === "type") { at(0.28 + r() * 0.28, 0.82); fr = [{ transform: T(0, 0), opacity: 1 }, { transform: T(0, -0.45), opacity: 0 }]; ms = 900; }
    else if (kind === "scan") { at(0.42, 1.2); const sk = `translateX(-50%) skewY(${side * -26}deg)`; fr = [{ transform: T(0, 0, sk), opacity: 0.9 }, { transform: T(0, 1.0, sk), opacity: 0.9 }, { transform: T(0, 0, sk), opacity: 0.2 }]; ms = 1100; ease = "ease-in-out"; }
    else if (kind === "pack") { at(0.3, 0.5); fr = [{ transform: T(0, 0), opacity: 1 }, { transform: T(side * 0.3, -0.3), opacity: 1, offset: 0.45 }, { transform: T(side * 0.62, 0.12), opacity: 0 }]; ms = 780; ease = "linear"; }
    else { at((r() - 0.5) * 0.5, 0.03); fr = [{ transform: "translate(-50%, 0) scale(1)", opacity: 0.8 }, { transform: "translate(-50%, 0) scale(3.2)", opacity: 0 }]; ms = 800; }
    e.setAttribute("aria-hidden", "true");
    this.stage.append(e);
    this.sparks++;
    const gone = () => { e.remove(); this.sparks--; };
    e.animate(fr, { duration: ms, easing: ease }).finished.then(gone, gone);
  }
}
