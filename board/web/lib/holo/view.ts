// Lamplight's hologram layer: bromigos.org's renderer (engine.ts, shaders.ts, format.ts, copied from
// app/ui/holo) with one shared WebGL context for the whole page. Every view (the station, the hub,
// a machine's hero) has its own scenes; the one canvas moves to whichever view is most on screen,
// and the others keep a still copy of their last frame. It renders only when something changed or
// moves, at a capped rate; never while hidden or off screen; once per change under reduced motion.
//
//   const v = await HoloView.create(el, { camera, pieces, bed?, fps?: () => number })
//   v.set(id, { state, cause, yaw, hover, spin, explode }); v.lines(fn); v.onFrame(cb)
//   v.point([x,y,z]) / v.rect(id) / v.anchors(id) -> CSS px in el; v.refresh() after a world change
//   v.dispose()
import * as THREE from "three";
import { FreeLines, GpuModel, HoloEngine, M, Table, approach, cssHex, ease, hexLin, type Rgb } from "./engine";
import { loadMesh, type HoloMesh } from "./format";

export type PartInfo = { id: string; label: string; hint: string; explode: number[]; anchor: number[] };
export type ModelInfo = { name: string; height: number; radius: number; parts: PartInfo[] };
export type State = "ok" | "warn" | "off" | "join" | "dim";
export type PieceSpec = {
  id: string; src: string; info: ModelInfo; at: [number, number, number]; size: number;
  yaw?: number; spin?: number; state?: State; cause?: number | null; table?: boolean; explode?: number; gain?: number;
  parent?: string; local?: [number, number, number]; localYaw?: number; localSize?: number;
  tablePower?: number; causeOnly?: boolean;
};
export type Seg = { a: number[]; b: number[]; ca: number[]; cb: number[] };
export type ViewOpts = {
  camera: { target: number[]; dist: number; pitch: number; yaw?: number; fov?: number };
  pieces: PieceSpec[];
  bloom?: number;
  reduced?: boolean;
  bed?: { radius: number; at?: number[]; power?: number; coneH?: number } | null;
  fps?: () => number; // extra animation the host wants (0: none)
};
const TOK = { ok: "--phosphor", warn: "--amber", off: "--static", join: "--soft", dim: "--dim" } as const;

// ------------------------------------------------------------------ one context for the page
const phone = () => matchMedia("(pointer: coarse)").matches || Math.min(screen.width, innerWidth) < 700;
class Shared {
  eng: HoloEngine | null = null;
  canvas: HTMLCanvasElement | null = null;
  views = new Set<HoloView>();
  active: HoloView | null = null;
  raf = 0;
  tm = 0;
  private onVis = () => this.kick();
  engine() {
    if (!this.eng) {
      const cv = document.createElement("canvas");
      cv.style.cssText = "position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none";
      cv.setAttribute("aria-hidden", "true");
      this.canvas = cv;
      const low = phone();
      this.eng = new HoloEngine(cv, { maxDpr: low ? 1 : 1.5, samples: low ? 0 : 4, blurPasses: low ? 1 : 2 });
      document.addEventListener("visibilitychange", this.onVis);
    }
    return this.eng;
  }
  add(v: HoloView) { this.views.add(v); this.pick(); }
  remove(v: HoloView) {
    this.views.delete(v);
    if (this.active === v) { this.active = null; this.pick(); }
    if (!this.views.size && this.eng) {
      cancelAnimationFrame(this.raf); this.raf = 0; clearTimeout(this.tm); this.tm = 0;
      document.removeEventListener("visibilitychange", this.onVis);
      this.eng.dispose(); this.canvas?.remove(); this.eng = null; this.canvas = null;
    }
  }
  /** The view with most of itself on screen gets the canvas; the one it leaves keeps a still. */
  pick() {
    let best: HoloView | null = null, area = 0;
    for (const v of this.views) { const a = v.onScreen(); if (a > area || (!best && a === 0 && !this.active)) { best = v; area = a; } }
    if (!best || best === this.active || (area === 0 && this.active)) { this.kick(); return; }
    const old = this.active;
    if (old && this.eng) { old.draw(this.eng, true); old.keepStill(this.canvas!); }
    this.active = best;
    best.el.prepend(this.canvas!);
    best.dropStill();
    best.resize();
  }
  kick() {
    if (this.tm) { clearTimeout(this.tm); this.tm = 0; }
    if (!this.raf && this.eng) this.raf = requestAnimationFrame((t) => this.loop(t));
  }
  private loop(now: number) {
    this.raf = 0;
    const v = this.active, eng = this.eng;
    if (!v || !eng || document.hidden) return;
    // a view without the canvas still shows its state: one frame, copied into its own still
    let swapped = false;
    for (const w of this.views) if (w !== v && w.ready && w.dirty && w.visible && w.el.offsetParent !== null) {
      w.resize(true); w.draw(eng, false); w.keepStill(this.canvas!); swapped = true;
    }
    if (swapped) { v.resize(true); v.dirty = true; }
    const fps = v.wantFps();
    if (v.dirty || (fps > 0 && now - v.lastDraw >= 850 / fps)) { v.draw(eng, false); v.lastDraw = now; }
    if (fps > 0 && v.visible) {
      // a slow animation (a pulse, a dot) waits on a timer between frames, not on every display frame
      if (fps >= 50) this.raf = requestAnimationFrame((t) => this.loop(t));
      else this.tm = window.setTimeout(() => { this.tm = 0; this.raf = requestAnimationFrame((t) => this.loop(t)); }, Math.max(0, 1000 / fps - (performance.now() - v.lastDraw) - 8));
    }
  }
}
const shared = new Shared();

// ------------------------------------------------------------------ a model in a view
class Piece {
  spec: Required<Omit<PieceSpec, "cause" | "parent" | "local" | "localYaw" | "localSize">> & PieceSpec & { cause: number | null };
  gm: GpuModel; table: Table | null; n: number; mesh: HoloMesh; explode = 0; born: number; hover = false;
  mm = new THREE.Matrix4(); centroid: THREE.Vector3[]; lo = new THREE.Vector3(); hi = new THREE.Vector3();
  constructor(v: HoloView, spec: PieceSpec, mesh: HoloMesh, t: number) {
    this.spec = { yaw: -0.55, spin: 0, state: "ok", cause: null, table: true, explode: 0, gain: 1, tablePower: 1, causeOnly: false, ...spec } as Piece["spec"];
    this.mesh = mesh;
    this.n = Math.max(1, Math.min(spec.info.parts.length || mesh.nparts, 24));
    this.born = t - 30;
    this.explode = this.spec.explode;
    this.gm = new GpuModel(mesh, v.px);
    v.models.add(this.gm.group);
    this.table = this.spec.table ? new Table() : null;
    if (this.table) v.tables.add(this.table.group);
    const sum = Array.from({ length: this.n }, () => new THREE.Vector3()), cnt = new Array(this.n).fill(0);
    this.lo.set(Infinity, Infinity, Infinity); this.hi.set(-Infinity, -Infinity, -Infinity);
    const p = new THREE.Vector3();
    for (let i = 0; i < mesh.part.length; i++) {
      const k = Math.min(mesh.part[i], this.n - 1);
      p.set(mesh.pos[i * 3], mesh.pos[i * 3 + 1], mesh.pos[i * 3 + 2]);
      sum[k].add(p); cnt[k]++; this.lo.min(p); this.hi.max(p);
    }
    this.centroid = sum.map((c, i) => c.multiplyScalar(1 / Math.max(cnt[i], 1)));
  }
  /** True while this piece is moving by itself (arriving, exploding, turning, a warn pulse). */
  moving(t: number, reduced: boolean) {
    if (reduced) return false;
    const sp = this.spec;
    return t - this.born < 1.4 || Math.abs(this.explode - sp.explode) > 1e-3 || sp.spin !== 0 || (sp.state === "warn" && sp.cause != null);
  }
  frame(v: HoloView, t: number, dt: number, reduced: boolean, dpr: number) {
    const sp = this.spec;
    if (!reduced) sp.yaw += sp.spin * dt;
    this.explode = reduced ? sp.explode : approach(this.explode, sp.explode, dt, 5);
    const h = sp.info.height || 1, s = sp.size / h;
    M.into(this.mm, M.T(sp.at[0], sp.at[1] + 0.02 * sp.size, sp.at[2]), M.Ry(sp.yaw), M.S(s));
    this.gm.setMatrix(this.mm);
    const st = sp.state as State;
    const col = v.pal(TOK[st === "warn" && sp.causeOnly ? "ok" : st]);
    const warm = st === "warn" ? v.pal(TOK.warn) : col;
    const off = st === "off";
    if (this.table) {
      const r = Math.max((sp.info.radius || 0.5) * s * 1.15, 0.32 * sp.size), tt = reduced ? 0 : t;
      M.into(this.table.group.matrix, M.T(sp.at[0], sp.at[1], sp.at[2]), M.Ry(-tt * 0.05));
      this.table.update(this.table.group.matrix.clone(), tt, r, r * 1.12, h * s * 1.05, (off ? 0.12 : st === "join" ? 0.5 : 0.85) * (sp.tablePower ?? 1), st === "warn" && sp.causeOnly ? col : warm);
    }
    const u = this.gm.u, age = t - this.born;
    for (let i = 0; i < this.n; i++) {
      const pi = sp.info.parts[i];
      const arrive = reduced ? 1 : ease((age - 0.08 * i) / 0.9);
      const e = this.explode * (0.7 + 0.3 * ease(this.explode * 1.4 - i * 0.04)) + (1 - arrive) * 1.6;
      const ex = pi ? pi.explode : [0, 0, 0];
      const m = u.pmat.value[i];
      m.makeTranslation(ex[0] * e, ex[1] * e, ex[2] * e);
      if (this.explode > 0.01) {
        const c = this.centroid[i], tip = 0.06 * this.explode * (i % 2 ? 1 : -1);
        m.multiply(M.T(c.x, c.y, c.z)).multiply(M.Rx(tip * 0.4)).multiply(M.Rz(tip)).multiply(M.T(-c.x, -c.y, -c.z));
      }
      let k = 0.95 * 0.96 * (sp.gain ?? 1);              // no shimmer: a still model costs no frames
      if (this.hover) k *= 1.3;
      let c = col, w = 1;
      const pulse = reduced ? 1.6 : 1.35 + 0.3 * Math.sin(t * 3.2);
      if (st === "warn" && sp.causeOnly) { if (sp.cause === i) { c = warm; k *= pulse; w = 1.8; } }
      else if (st === "warn") { c = warm; if (sp.cause === i) { k *= pulse + 0.1; w = 1.8; } else k *= 0.8; }
      let a = arrive;
      if (off) { a *= 0.3; k *= 0.7; }
      if (st === "join") a *= 0.75;
      if (st === "dim") a *= 0.55;
      u.pcol.value[i].set(c[0] * k, c[1] * k, c[2] * k, a);
      u.pw.value[i] = w + (this.hover ? 0.35 : 0);
    }
    const x = age / 2.4;
    if (reduced || x > 1.15) u.scan.value.set(0, 0.02, 0, 0);
    else u.scan.value.set(-0.05 + x * (h + 0.1), 0.006 + 0.006 * h, 0.9 * (1 - Math.max(0, x - 1) / 0.15), 0);
    this.gm.params({ fill: off ? 0.25 : 0.55, width: 1.3, slices: 48, ghost: 0.12 }, dpr);
  }
  dispose(v: HoloView) {
    v.models.remove(this.gm.group); this.gm.dispose();
    if (this.table) { v.tables.remove(this.table.group); this.table.dispose(); }
  }
}

// ------------------------------------------------------------------ a view
export class HoloView {
  el: HTMLElement;
  tables = new THREE.Scene();
  models = new THREE.Scene();
  pieces = new Map<string, Piece>();
  px = { value: new THREE.Vector2(1, 1) };
  reduced: boolean;
  bloom: number;
  cam: ViewOpts["camera"];
  dirty = true;
  ready = false;
  visible = true;
  lastDraw = -1e9;
  private ratio = 1;
  private free: FreeLines;
  private segFn: ((t: number) => Seg[]) | null = null;
  private bed: { t: Table; o: NonNullable<ViewOpts["bed"]> } | null = null;
  private frameCbs: ((v: HoloView) => void)[] = [];
  private beforeCbs: ((v: HoloView, t: number) => void)[] = [];
  private t0 = performance.now() / 1000;
  private last = 0;
  private still: HTMLCanvasElement | null = null;
  private ro: ResizeObserver;
  private io: IntersectionObserver;
  private palette = new Map<string, Rgb>();
  private extra: () => number;
  private disposed = false;
  private camW = 0; private camH = 0;
  private proj = new THREE.Matrix4();
  private cam3 = new THREE.PerspectiveCamera(30, 1, 0.05, 20);

  static async create(el: HTMLElement, opts: ViewOpts) {
    const v = new HoloView(el, opts);
    try {
      await Promise.all(opts.pieces.map((p) => v.add(p)));
    } catch (e) {
      v.dispose(); // the board's change to the copied file: a view whose model didn't load is let go, not left behind
      throw e;
    }
    v.ready = true;
    v.kick();
    return v;
  }
  private constructor(el: HTMLElement, opts: ViewOpts) {
    this.el = el;
    this.cam = { yaw: 0, fov: 30, ...opts.camera };
    this.bloom = opts.bloom ?? 1.15;
    this.extra = opts.fps ?? (() => 0);
    const eng = shared.engine();
    this.reduced = !!opts.reduced || eng.software;
    this.free = new FreeLines(4000, this.px);
    this.models.add(this.free.object);
    if (opts.bed) { const t = new Table(); this.tables.add(t.group); this.bed = { t, o: opts.bed }; }
    this.ro = new ResizeObserver(() => { this.camW = 0; if (shared.active === this) this.resize(); else shared.pick(); this.kick(); });
    this.ro.observe(el);
    this.io = new IntersectionObserver((e) => {
      for (const x of e) { this.visible = x.isIntersecting; this.ratio = x.intersectionRatio; }
      shared.pick(); this.kick();
    }, { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] });
    this.io.observe(el);
    shared.add(this);
  }
  /** How much of the view is on screen, in CSS px² (0 when hidden). */
  onScreen() { if (!this.visible || this.el.offsetParent === null) return 0; const r = this.el.getBoundingClientRect(); return r.width * r.height * this.ratio; }
  now() { return performance.now() / 1000 - this.t0; }
  resize(quiet = false) {
    const eng = shared.eng; if (!eng) return;
    const r = this.el.getBoundingClientRect();
    eng.setSize(r.width, r.height);
    this.px.value.copy(eng.px.value);
    this.camW = 0; if (!quiet) this.kick();
  }
  kick() { this.dirty = true; shared.kick(); }
  wantFps() {
    if (this.reduced || !this.visible) return 0;
    const t = this.now();
    let f = this.extra();
    for (const p of this.pieces.values()) if (p.moving(t, false)) { f = Math.max(f, p.spec.state === "warn" && p.spec.spin === 0 && t - p.born > 1.4 && Math.abs(p.explode - p.spec.explode) < 1e-3 ? 8 : 30); }
    return f;
  }
  setReduced(on: boolean) { this.reduced = on || !!shared.eng?.software; this.kick(); }
  /** A token's colour, cached: call refresh() after the world (the tokens) change. */
  pal(token: string, k = 1): Rgb {
    let c = this.palette.get(token);
    if (!c) { c = hexLin(cssHex(this.el, token) ?? "#39ff14"); this.palette.set(token, c); }
    return k === 1 ? c : [c[0] * k, c[1] * k, c[2] * k];
  }
  colour(token: string, k = 1) { return this.pal(token, k); }
  refresh() { this.palette.clear(); this.kick(); }
  onFrame(cb: (v: HoloView) => void) { this.frameCbs.push(cb); this.kick(); }
  /** Called before each frame is drawn (move things here, so the words placed after match). */
  beforeDraw(cb: (v: HoloView, t: number) => void) { this.beforeCbs.push(cb); }
  lines(fn: (t: number) => Seg[]) { this.segFn = fn; this.kick(); }
  async add(spec: PieceSpec) {
    const mesh = await loadMesh(spec.src);
    if (this.disposed) return;
    this.pieces.get(spec.id)?.dispose(this);
    this.pieces.set(spec.id, new Piece(this, spec, mesh, this.now()));
    this.kick();
  }
  remove(id: string) { this.pieces.get(id)?.dispose(this); this.pieces.delete(id); this.kick(); }
  set(id: string, patch: Partial<PieceSpec> & { hover?: boolean }) {
    const p = this.pieces.get(id); if (!p) return;
    const { hover, ...rest } = patch;
    Object.assign(p.spec, rest);
    if (hover !== undefined) p.hover = hover;
    this.kick();
  }
  camera(patch: Partial<ViewOpts["camera"]>) { Object.assign(this.cam, patch); this.camW = 0; this.kick(); }
  /** Draw one frame into the shared context (the canvas must be this view's, unless snapshotting). */
  draw(eng: HoloEngine, snapshot: boolean) {
    if (this.disposed) return;
    this.dirty = false;
    const t = this.now(), dt = Math.min(0.1, t - this.last); this.last = t;
    const tt = this.reduced ? 0 : t;
    eng.tableScene = this.tables; eng.modelScene = this.models;
    if (!snapshot) for (const cb of this.beforeCbs) cb(this, t);
    this.place(eng);
    for (const p of this.pieces.values()) {
      const sp = p.spec, par = sp.parent ? this.pieces.get(sp.parent) : null;
      if (par && sp.local) {
        const ps = par.spec.size / (par.spec.info.height || 1), a = par.spec.yaw, L = sp.local;
        sp.at = [par.spec.at[0] + ps * (L[0] * Math.cos(a) + L[2] * Math.sin(a)), par.spec.at[1] + ps * L[1] + 0.02 * par.spec.size - 0.02 * (sp.localSize ?? 0.1) * ps,
          par.spec.at[2] + ps * (-L[0] * Math.sin(a) + L[2] * Math.cos(a))];
        sp.yaw = a + (sp.localYaw ?? 0); sp.size = (sp.localSize ?? 0.1) * ps; sp.spin = 0;
      }
      p.frame(this, tt, this.reduced ? 0 : dt, this.reduced, eng.dpr);
    }
    if (this.bed) {
      const o = this.bed.o, at = o.at ?? [0, 0, 0];
      M.into(this.bed.t.group.matrix, M.T(at[0], at[1], at[2]), M.Ry(-tt * 0.02));
      this.bed.t.update(this.bed.t.group.matrix.clone(), tt, o.radius, o.radius * 1.02, o.coneH ?? 0.05, o.power ?? 0.55, this.pal("--phosphor"));
    }
    this.free.set(this.segFn ? this.segFn(tt) : [], 1.6, eng.dpr);
    eng.render(this.bloom, 1);
    if (!snapshot) for (const cb of this.frameCbs) cb(this);
  }
  private place(eng: HoloEngine) {
    const c = this.cam, d = c.dist, pt = c.pitch, yw = c.yaw ?? 0;
    eng.lookAt([c.target[0] + d * Math.cos(pt) * Math.sin(yw), c.target[1] + d * Math.sin(pt), c.target[2] + d * Math.cos(pt) * Math.cos(yw)], c.target, c.fov ?? 30);
    this.cam3.copy(eng.camera); this.camW = eng.width; this.camH = eng.height;
  }
  keepStill(gl: HTMLCanvasElement) {
    if (!this.still) { this.still = document.createElement("canvas"); this.still.style.cssText = gl.style.cssText; this.still.setAttribute("aria-hidden", "true"); }
    this.still.width = gl.width; this.still.height = gl.height;
    this.still.getContext("2d")?.drawImage(gl, 0, 0);
    this.el.prepend(this.still);
  }
  dropStill() { this.still?.remove(); }
  /** A world point in CSS pixels inside the element (this view's own camera, even when inactive). */
  point(w: number[]) {
    const v = new THREE.Vector3(w[0], w[1], w[2]).project(this.cam3);
    return { x: (v.x * 0.5 + 0.5) * this.camW, y: (1 - (v.y * 0.5 + 0.5)) * this.camH };
  }
  rect(id: string) {
    const p = this.pieces.get(id); if (!p) return null;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const v = new THREE.Vector3();
    for (let i = 0; i < 8; i++) {
      v.set(i & 1 ? p.hi.x : p.lo.x, i & 2 ? p.hi.y : p.lo.y, i & 4 ? p.hi.z : p.lo.z).applyMatrix4(p.mm);
      const o = this.point([v.x, v.y, v.z]);
      x0 = Math.min(x0, o.x); y0 = Math.min(y0, o.y); x1 = Math.max(x1, o.x); y1 = Math.max(y1, o.y);
    }
    const b = this.point(p.spec.at);
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0, bx: b.x, by: b.y };
  }
  anchors(id: string) {
    const p = this.pieces.get(id); if (!p) return [];
    const out: { id: string; x: number; y: number }[] = [], w = new THREE.Vector3();
    for (let i = 0; i < p.n; i++) {
      const pi = p.spec.info.parts[i], a = pi?.anchor ?? [0, 0, 0];
      w.set(a[0], a[1], a[2]).applyMatrix4(p.gm.u.pmat.value[i]).applyMatrix4(p.mm);
      const o = this.point([w.x, w.y, w.z]); out.push({ id: pi?.id ?? String(i), x: o.x, y: o.y });
    }
    return out;
  }
  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.ro.disconnect(); this.io.disconnect();
    for (const p of this.pieces.values()) p.dispose(this);
    this.pieces.clear();
    this.free.dispose();
    if (this.bed) this.bed.t.dispose();
    this.still?.remove();
    shared.remove(this);
  }
}
export { shared as _shared };
