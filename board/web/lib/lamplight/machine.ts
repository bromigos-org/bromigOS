// A machine's page hero (its deck tray pulled out of the station, its hologram at full detail, the
// cause lit, the shell that is working on it beside it), and the bare mount: one machine's
// hologram on its emitter with no station. Both share the page's one WebGL context.
//
// A machine kind with no model in the manifest is drawn as its kind's icon on the tray: the same
// top line, the same state word, no hologram asked for.
import { HoloView, type PieceSpec, type Seg } from "../holo/view";
import { KIND_WORD, addHtml, artUrl, createRoot, html, icon, join, kicoClass, kindIcon, modelFor, oneOf, put, reducedNow, setHtml, stateWord, viewState } from "./base";
import { SHELL_NAME, buildScene, type Scene } from "./station";
import { KINDS, STATES, sane } from "./sane";
import type { LamplightData, MachineHandle, MachineOptions, RackHandle, RackOptions } from "./types";

type El = HTMLElement;

export class Machine implements MachineHandle {
  private root: El;
  private P: string;
  private view: HoloView | null = null;
  private scene!: Scene;
  private off: (() => void)[] = [];
  private dead = false;
  private key = "";
  private modelKey = "";
  private sig = "";
  private settle = 0;
  private topH = "";
  private ovH = "";

  constructor(private host: El, private o: MachineOptions) {
    this.o = o = { ...o, data: sane(o.data), machine: String(o.machine) };
    const { root, prefix } = createRoot(host, o.world);
    this.root = root; this.P = prefix;
    addHtml(root, html`<div class="mhero" data-k="mh"><div class="scene" data-k="scene"></div><span class="loading" data-k="loading" title="The hologram is loading; what it says is already here in words">TUNING IN…</span><div class="ov" data-k="ov"></div><div class="mh-top" data-k="top"></div><span class="h-scan" aria-hidden="true"></span><span class="h-edge" aria-hidden="true"></span></div>`);
    const click = (ev: Event) => { const t = (ev.target as Element).closest<El>("[data-nav]"); if (t && root.contains(t)) this.o.onNavigate?.(t.dataset.nav!, { machine: this.o.machine }); };
    root.addEventListener("click", click); this.off.push(() => root.removeEventListener("click", click));
    const mq = matchMedia("(prefers-reduced-motion: reduce)"), mqf = () => this.setReduced(!!this.o.reduced);
    mq.addEventListener("change", mqf); this.off.push(() => mq.removeEventListener("change", mqf));
    const ro = new ResizeObserver(() => { this.fit(); if (!this.view) this.place(null); });
    ro.observe(this.q("mh")!); this.off.push(() => ro.disconnect());
    this.render();
  }
  private q<T extends Element = El>(k: string): T | null { return this.root.querySelector<T>(`[data-k="${k}"]`); }
  private get reduced() { return reducedNow(this.o.reduced); }

  private render() {
    const d = this.o.data, a = this.o.assets;
    this.scene = buildScene(d, a);
    this.root.classList.toggle("reduced", this.reduced);
    this.root.classList.toggle("mascot-off", (d.mascot ?? "on") === "off");
    const c = this.scene.compartments.find((x) => x.id === this.o.machine && x.machine), top = this.q("top")!, ov = this.q("ov")!, mh = this.q("mh")!;
    if (!c || !c.machine) {
      setHtml(top, html`<div title="This machine isn't on the lab's list"><b>${this.o.machine.toUpperCase()}</b><small>NOT ON THIS LAB</small></div>`);
      setHtml(ov, ""); this.topH = this.ovH = ""; this.view?.dispose(); this.view = null; this.modelKey = ""; mh.classList.add("ready");
      return;
    }
    const m = c.machine, deck = c.deck === "DOCK" ? "THE DOCKING RING" : c.deck;
    const need = d.needs.find((n) => n.machine === m.id);
    const crew = this.scene.crew.find((x) => x.where === m.id && x.duty);
    const topH = html`${[html`<div title="${c.hint}"><b>${c.code} · ${c.name}</b><small>${[KIND_WORD[m.kind].replace(/^(a|an|the) /, ""), m.role, m.reading].filter(Boolean).join(" · ").toUpperCase()}</small></div>`
      , html`<span title="${need ? `${need.words}${need.detail ? `: ${need.detail}` : ""}` : `Its state: ${m.word}`}">${stateWord(this.P, c.state, need ? `${c.word} · ${need.words.toUpperCase()}` : c.word)}</span>`]}`;
    if (topH.s !== this.topH) { setHtml(top, topH); this.topH = topH.s; }
    const model = modelFor(a, m.kind);
    const cut = crew ? artUrl(a, `crew/${crew.shell}-${crew.pose}`) ?? artUrl(a, `crew/${crew.shell}`) : null, still = crew && !cut ? artUrl(a, `still/${crew.shell}`) : null;
    const ovH = html`${[html`<button type="button" class="mh-tag pin" data-nav="home" data-k="dock" title="Its compartment on the station, behind: ${c.code}. Press to go back to the whole station.">DOCKS AT ${deck}</button>`
      , (model ? "" : html`<span class="kico big pin ${kicoClass(c.state)}" data-k="kico" title="${`${m.name}, ${KIND_WORD[m.kind]}: ${m.word}. Shown by its icon on its deck tray.`}">${icon(this.P, kindIcon(m.kind), "")}</span>`)
      , (model && m.cause ? html`<span class="tgt2 pin" data-k="tgt" title="The cause, lit on the machine itself"></span>` : "")
      , (crew && (d.mascot ?? "on") !== "off" ? [(cut ? html`<img class="crewx pin ${this.reduced ? "" : "bob"}" data-k="crew" src="${cut}" alt="" decoding="async" title="${`STATIC as ${SHELL_NAME[crew.shell]}: ${crew.hint}`}">`
        : still ? html`<img class="crewp pin" data-k="crew" src="${still}" alt="" decoding="async" title="${`STATIC as ${SHELL_NAME[crew.shell]}: ${crew.hint}`}">` : "")
        , html`<span class="cap2 pin ${crew.tone === "warn" ? "warn" : ""}" data-k="cap" title="${crew.hint}">${crew.caption}</span>`] : "")]}`;
    if (ovH.s !== this.ovH) { setHtml(ov, ovH); this.ovH = ovH.s; this.sig = ""; }   // a poll that found nothing new rewrites nothing
    const mk = `${m.kind}|${model}`;
    if (mk !== this.modelKey) { this.modelKey = mk; this.view?.dispose(); this.view = null; void this.mount(); }
    else if (this.view) {
      const full = model ? a.models[model].full ?? a.models[model] : null, ci = full && m.cause ? full.info.parts.findIndex((p) => p.id === m.cause) : -1;
      if (model) this.view.set("m", { state: viewState(m.state, this.scene.quiet), cause: ci >= 0 ? ci : null });
      this.view.set("wick", { state: this.scene.quiet ? "dim" : "ok" });
      this.view.setReduced(this.reduced);
    }
  }
  private async mount() {
    const a = this.o.assets, wick = a.models["wick-cut"], c = this.scene.compartments.find((x) => x.id === this.o.machine)!, m = c.machine!;
    const model = modelFor(a, m.kind), full = model ? a.models[model].full ?? a.models[model] : null, red = this.reduced;
    const pieces: PieceSpec[] = [];
    if (wick) pieces.push({ id: "wick", src: join(a.base, wick.src), info: wick.info, at: [-0.75, 0, -0.9], size: 0.9, yaw: -0.5, gain: 0.32, tablePower: 0.06, state: this.scene.quiet ? "dim" : "ok" });
    if (full) {
      const ci = m.cause ? full.info.parts.findIndex((p) => p.id === m.cause) : -1;
      pieces.push({ id: "m", src: join(a.base, full.src), info: full.info, at: [0.28, 0.04, 0.2], size: m.kind === "server" ? 0.9 : 0.5, yaw: -0.5, spin: red ? 0 : 0.08, tablePower: 0.3, state: viewState(m.state, this.scene.quiet), cause: ci >= 0 ? ci : null, causeOnly: true });
    }
    const key = (this.key = `${Date.now()}${Math.random()}`);
    if (!pieces.length) { this.q("mh")!.classList.add("ready"); this.place(null); return; }
    try {
      const v = await HoloView.create(this.q("scene")!, { camera: { target: [0, 0.42, 0], dist: 3.2, pitch: 0.2, fov: 30 }, pieces, reduced: red, bloom: 0.8 });
      if (this.dead || key !== this.key) { v.dispose(); return; }
      this.view = v;
      v.lines(() => {   // the tray under the machine, and its dashed run back to its deck on the station
        const ph = v.pal("--phosphor"), out: Seg[] = [], c4 = (c: number[], al: number) => [c[0], c[1], c[2], al], push = (p: number[], q: number[], col: number[]) => out.push({ a: p, b: q, ca: col, cb: col });
        const x0 = -0.15, x1 = 0.7, z0 = -0.15, z1 = 0.55, y = 0.03;
        for (const [p, q, r, s] of [[x0, z0, x1, z0], [x1, z0, x1, z1], [x1, z1, x0, z1], [x0, z1, x0, z0]]) push([p, y, q], [r, y, s], c4(ph, 0.7));
        if (wick) for (let k = 0; k < 16; k += 2) { const at = (u: number) => [x0 + (-0.62 - x0) * u, y + (0.27 - y) * u, z0 + (-0.8 - z0) * u]; push(at(k / 16), at((k + 1) / 16), c4(ph, 0.45)); }
        return out;
      });
      v.onFrame((s) => this.place(s));
      this.fit();
      clearTimeout(this.settle);
      this.settle = window.setTimeout(() => this.view?.set("m", { spin: 0 }), 20_000);   // it turns for a while, then rests: a still scene draws nothing
      this.q("mh")!.classList.add("ready");
      this.o.onReady?.();
    } catch (e) { this.q("mh")!.classList.add("ready", "nogl"); this.place(null); this.o.onError?.(e); }
  }
  /** A narrow hero (a phone): the camera steps back so the tray and the shell beside it stay in frame. */
  private fit() {
    const w = this.q("mh")!.clientWidth;
    this.view?.camera(w < 600 ? { dist: 4.7, target: [0.14, 0.34, 0] } : { dist: 3.2, target: [0, 0.42, 0] });
    this.sig = "";
  }
  private place(s: HoloView | null) {
    const mh = this.q("mh")!, W = mh.clientWidth, H = mh.clientHeight, m = s?.pieces.get("m");
    const sig = `${m ? (m.spec.yaw ?? 0).toFixed(3) : ""}|${W}|${H}|${!!s}`;
    if (sig === this.sig) return; this.sig = sig;
    const pt = (w: number[]) => (s ? s.point(w) : { x: W * (0.5 + w[0] * 0.28), y: H * (0.78 - w[1] * 0.6) });
    const dock = pt([-0.62, 0.3, -0.8]); put(this.q<El>("dock"), s ? dock.x : W * 0.24, s ? dock.y : H * 0.5);
    const ki = this.q("kico"); if (ki) { const p = pt([0.28, 0.04, 0.2]); put(ki, p.x, p.y); }
    const t = this.q("tgt"); if (t && s && m && m.spec.cause != null) { const an = s.anchors("m")[m.spec.cause]; if (an) put(t, an.x, an.y, "-50%", "-50%"); }
    const cr = this.q("crew"), cap = this.q("cap"), p = pt([0.62, 0.03, 0.42]);
    if (cr) put(cr, p.x, p.y);
    if (cap) put(cap, p.x, p.y + 10, "-50%", "0");
  }
  update(data: LamplightData, machine?: string) { this.o.data = sane(data); if (machine != null) this.o.machine = String(machine); this.render(); }
  setReduced(on: boolean) { this.o.reduced = on; this.view?.set("m", { spin: this.reduced ? 0 : 0.08 }); this.render(); }
  setWorld(world: string | null) { if (world) this.root.dataset.world = world; else delete this.root.dataset.world; this.refresh(); }
  refresh() { this.view?.refresh(); }
  unmount() { if (this.dead) return; this.dead = true; clearTimeout(this.settle); for (const f of this.off) f(); this.view?.dispose(); this.root.remove(); }
}

/** One machine's hologram on its emitter, with no station: the door, a page's hero, a sheet. */
export class Rack implements RackHandle {
  private root: El;
  private P: string;
  private view: HoloView | null = null;
  private dead = false;
  private settle = 0;
  private off: (() => void)[] = [];

  constructor(private host: El, private o: RackOptions) {
    // the options are a host's words too: a kind or a state that isn't one is "other" / "unknown"
    this.o = o = { ...o, kind: oneOf(o.kind, KINDS, "other"), state: o.state == null ? undefined : oneOf(o.state, STATES, "unknown") };
    const { root, prefix } = createRoot(host, o.world);
    this.root = root; this.P = prefix;
    root.classList.add("lp-bare");
    const model = modelFor(o.assets, o.kind), label = o.label ?? `${KIND_WORD[o.kind]}, as a hologram`;
    addHtml(root, html`<div class="rackm" data-k="rk" role="img" aria-label="${label}" title="${label}"><div class="scene" data-k="scene"></div>${model ? "" : html`<span class="kico big ${kicoClass(o.state ?? "ok")}" data-k="kico">${icon(prefix, kindIcon(o.kind), "")}</span>`}</div>`);
    const mq = matchMedia("(prefers-reduced-motion: reduce)"), mqf = () => this.setReduced(!!this.o.reduced);
    mq.addEventListener("change", mqf); this.off.push(() => mq.removeEventListener("change", mqf));
    if (model) void this.mount(model); else this.o.onReady?.();
  }
  /** The old sprite strip named a side by its angle; 210 is the gallery's three-quarter view. */
  private yaw() { return (-((this.o.angle ?? 210) - 180) * Math.PI) / 180; }
  private async mount(model: string) {
    const a = this.o.assets, e = a.models[model], use = this.o.full && e.full ? e.full : e, red = reducedNow(this.o.reduced);
    const ci = this.o.cause ? use.info.parts.findIndex((p) => p.id === this.o.cause) : -1;
    try {
      // a wide model (a storage server, a router) is sized by its width, so it stays in frame
      const size = Math.min(1, (1.05 * (use.info.height || 1)) / (2 * (use.info.radius || 0.5)));
      const v = await HoloView.create(this.root.querySelector<El>('[data-k="scene"]')!, {
        camera: { target: [0, 0.5 * size + 0.5 * (1 - size) * 0.5, 0], dist: 2.6, pitch: 0.18, fov: 30 }, reduced: red, bloom: 0.9,
        pieces: [{ id: "m", src: join(a.base, use.src), info: use.info, at: [0, 0, 0], size, yaw: this.yaw(), spin: this.o.turn && !red ? 0.25 : 0, state: viewState(this.o.state ?? "ok", false), cause: ci >= 0 ? ci : null, causeOnly: true }],
      });
      if (this.dead) { v.dispose(); return; }
      this.view = v;
      if (this.o.turn) this.settle = window.setTimeout(() => this.view?.set("m", { spin: 0 }), 20_000);
      this.root.querySelector('[data-k="rk"]')!.classList.add("ready");
      this.o.onReady?.();
    } catch (err) { this.o.onError?.(err); }
  }
  update(patch: { state?: RackOptions["state"]; cause?: string | null; angle?: number }) {
    Object.assign(this.o, patch);
    if (this.o.state != null) this.o.state = oneOf(this.o.state, STATES, "unknown");
    const model = modelFor(this.o.assets, this.o.kind);
    const ki = this.root.querySelector('[data-k="kico"]'); if (ki) ki.className = `kico big ${kicoClass(this.o.state ?? "ok")}`;
    if (!this.view || !model) return;
    const e = this.o.assets.models[model], use = this.o.full && e.full ? e.full : e, ci = this.o.cause ? use.info.parts.findIndex((p) => p.id === this.o.cause) : -1;
    this.view.set("m", { state: viewState(this.o.state ?? "ok", false), cause: ci >= 0 ? ci : null, ...(patch.angle != null ? { yaw: this.yaw() } : {}) });
  }
  setReduced(on: boolean) { this.o.reduced = on; this.view?.setReduced(reducedNow(on)); if (reducedNow(on)) this.view?.set("m", { spin: 0 }); }
  setWorld(world: string | null) { if (world) this.root.dataset.world = world; else delete this.root.dataset.world; this.refresh(); }
  refresh() { this.view?.refresh(); }
  unmount() { if (this.dead) return; this.dead = true; clearTimeout(this.settle); for (const f of this.off) f(); this.view?.dispose(); this.root.remove(); }
}
