// Lamplight on Home: the lab as a living station. One scene (the station cut open, each machine's
// hologram or icon on its deck, the crew where real events need them, the readouts, the alarm,
// VECTOR's plan when there is one), and under it only the layers the data carries (the deck plan,
// the booth's roll-call, the log and goals, the hub).
//
// It draws only from `LamplightData` (types.ts); update() re-renders in place. It shares the
// page's one WebGL context (holo/view.ts) and draws a frame only when something moves.
import { HoloView, type PieceSpec, type Seg } from "../holo/view";
import { type Part, type Safe, addHtml, applyCss, artUrl, createRoot, html, icon, isPhone, join, kicoClass, kindIcon, put, reducedNow, setHtml, stateWord, tubes, viewState } from "./base";
import { DECKS, BOOTH_EDGE, MAST_FOOT, MONITOR_AT, SHELL_NAME, YAW0, ZC, buildScene, dataKey, sceneKey, type Compartment, type CrewPlace, type Scene } from "./station";
import { sane } from "./sane";
import type { LampCard, LamplightData, LamplightHandle, LamplightOptions } from "./types";

type El = HTMLElement;
type Pt = { x: number; y: number };
// (clear of the head, the visit card and the exchange, which stand down the stage's left side)
const FAR_SPOTS: [number, number][] = [[0.06, 0.64], [0.31, 0.56], [0.3, 0.8], [0.7, 0.3], [0.75, 0.6], [0.58, 0.95], [0.4, 0.08], [0.9, 0.2]];
const ARC_SPOTS: [number, number][] = [[64, 240], [180, 262], [290, 150], [60, 470], [330, 320]];
const TAB_ORDER = ["decks", "booth", "log", "hub"] as const;
type Tab = (typeof TAB_ORDER)[number];

export class Home implements LamplightHandle {
  private o: LamplightOptions & { tab: string; under: "auto" | "none" };
  private root: El;
  private P: string;
  private scene!: Scene;
  private view: HoloView | null = null;
  private hub: HoloView | null = null;
  private hubRO: ResizeObserver | null = null;
  private hubKey = "";
  private off: (() => void)[] = [];
  private dead = false;
  private phone = isPhone();
  private sig = "";
  private key = "";
  private dataKey = "";
  private structKey = "";
  private alarmKey = "";
  private planGone = "";
  private turnUntil = 0;
  private yawT = 0;
  private yawLast = 0;
  private rows: { id: string; x: number; y: number }[] | null = null;
  private partW: number[] | null = null;
  private paths: SVGPathElement[] = [];
  private pins: { parts: El[]; icons: { c: Compartment; el: El }[]; crew: { p: CrewPlace; i: number; n: number; el: El; cap: El | null }[]; mon: El | null; tgt: El | null; lamp: El | null; beam: El | null; wx: El | null; l2: SVGElement | null } =
    { parts: [], icons: [], crew: [], mon: null, tgt: null, lamp: null, beam: null, wx: null, l2: null };
  private visiting: string | null = null;
  private built: Partial<Record<Tab, boolean>> = {};
  private cur = 0;
  private playing = false;
  private timer = 0;

  constructor(private host: El, opts: LamplightOptions) {
    this.o = { tab: "decks", under: "auto", ...opts, data: sane(opts.data) };
    this.dataKey = JSON.stringify(this.o.data); this.structKey = dataKey(this.o.data);
    const { root, prefix } = createRoot(host, this.o.world);
    this.root = root; this.P = prefix;
    addHtml(root, this.skeleton());
    this.render(true);
    void this.mountScene();
    this.wire();
  }

  // ---------------------------------------------------------------- small helpers
  private q<T extends Element = El>(k: string): T | null { return this.root.querySelector<T>(`[data-k="${k}"]`); }
  private ic(id: string, cls = "s16") { return icon(this.P, id, cls); }
  private st(s: Parameters<typeof stateWord>[1], w: string) { return stateWord(this.P, s, w); }
  private art(name: string) { return artUrl(this.o.assets, name); }
  private get data(): LamplightData { return this.o.data; }
  private get reduced() { return reducedNow(this.o.reduced); }
  private get mascot() { return this.data.mascot ?? "on"; }
  private fail(e: unknown) { this.o.onError?.(e); }
  private nav(route: string | null, detail: Record<string, unknown> = {}) {
    if (!route) return;
    if (route === "show") { this.setTab("booth"); this.play(); return; }
    this.o.onNavigate?.(route, detail);
  }
  private tabs(): Tab[] {
    if (this.o.under === "none") return [];
    const d = this.data, t: Tab[] = ["decks"];
    if (d.show) t.push("booth");
    if (d.log?.length || d.goals) t.push("log");
    if (d.hub) t.push("hub");
    return t;
  }

  private skeleton(): Safe {
    return html`<div class="wrap" data-k="wrap">
      <div class="stage space" data-k="stage" data-flare>
        <div class="sky" data-k="sky"><canvas data-k="dust" aria-hidden="true"></canvas><svg class="stars" data-k="stars" viewBox="0 0 1000 620" preserveAspectRatio="xMinYMin slice" aria-hidden="true"></svg></div>
        <div data-k="far"></div>
        <div class="scene" data-k="scene" role="img" aria-label="The lab as a station, cut open: each machine a compartment on its deck. The list beside it says the same in words."></div>
        <span class="loading" data-k="loading" title="The station's hologram is loading; everything it says is already here in words">TUNING IN…</span>
        <div data-k="wthr"></div>
        <div class="ov" data-k="ov"></div>
        <div class="head" data-k="head"></div>
        <div class="tubesrow"><div class="row" data-k="tubes"></div><div data-k="alarm"></div></div>
        <span class="skyhint" data-k="skyhint" hidden></span>
        <span class="h-scan" aria-hidden="true"></span><span class="h-edge" aria-hidden="true"></span>
      </div>
      <div class="deckcol" data-k="decks" aria-label="Every deck and its compartments"></div>
      <svg class="lead" data-k="lead" aria-hidden="true"></svg>
      <div class="aside l" data-k="asl"></div>
      <div class="aside r" data-k="asr"></div>
      <div class="aside t" data-k="ast"></div>
    </div>
    <div class="tabs" role="tablist" aria-label="Under the station" data-k="tabs" hidden></div>
    ${TAB_ORDER.map((k) => html`<div class="tp tp-${k}" role="tabpanel" data-p="${k}"></div>`)}`;
  }

  // ---------------------------------------------------------------- render: on new data, never per frame
  private render(first = false) {
    const d = this.data, s = (this.scene = buildScene(d, this.o.assets)), r = this.root;
    r.classList.toggle("reduced", this.reduced);
    r.classList.toggle("mascot-off", this.mascot === "off");
    r.classList.toggle("mascot-quiet", this.mascot === "quiet");
    const stage = this.q("stage")!;
    stage.classList.toggle("quiet", s.quiet);
    stage.classList.toggle("alarm", !!s.alarm);
    stage.classList.toggle("nosignal", s.weather === "nosignal");
    this.q("sky")!.classList.toggle("turn", !this.reduced && !s.quiet);
    this.stars(); this.far();
    this.head();
    const wx = this.q("wthr")!, want = s.weather === "interference" ? "intf" : s.weather === "night" ? "night" : "";
    if ((wx.firstElementChild?.className ?? "").split(" ")[0] !== want) setHtml(wx, want ? html`<div class="${want} pin" data-k="wx" title="${s.weather === "night" ? s.line.hint : s.sub.hint}"></div>` : "");
    this.overlay(); this.deckList(); this.asides();
    // the panels under the station: only the layers the data carries
    const tabs = this.tabs();
    if (!tabs.includes(this.o.tab as Tab)) this.o.tab = tabs[0] ?? "";
    const names: Record<Tab, [string, string, string]> = {
      decks: ["i-module", "DECK PLAN", "The deck plan: the station in side elevation, a box per compartment"],
      booth: ["i-tv", "BOOTH", "Tonight's roll-call, and the open arc it follows"],
      log: ["i-logs", "LOG & GOALS", "The station log, and the goals that grow the station"],
      hub: ["i-net", "THE HUB", "Your faction as a place: a hub with its members' stations in orbit"],
    };
    const bar = this.q("tabs")!;
    bar.hidden = tabs.length < 2;
    setHtml(bar, tabs.map((k) => html`<button type="button" role="tab" data-tab="${k}" aria-selected="${k === this.o.tab}" title="${names[k][2]}">${this.ic(names[k][0])}${names[k][1]}</button>`));
    r.dataset.tab = this.o.tab;
    for (const k of TAB_ORDER) {
      if (k === "hub" && this.hub && JSON.stringify(d.hub ?? null) === this.hubKey && tabs.includes("hub")) continue;
      if (k === "booth" && this.playing && tabs.includes("booth")) continue;
      if (k === "hub") this.dropHub();
      this.built[k] = false;
      if (!tabs.includes(k)) { const p = this.root.querySelector<El>(`[data-p="${k}"]`); if (p && p.firstChild) setHtml(p, ""); }
    }
    if (this.o.tab) this.buildTab(this.o.tab as Tab);
    if (!first) this.syncModels();
    this.motion();
  }

  /** The head, the readouts and the alarm: all a poll that found nothing new rewrites. */
  private head() {
    const d = this.data, s = this.scene;
    setHtml(this.q("head")!, html`<h2 title="Lamplight: your lab as a living station">LAMPLIGHT</h2>
      <small title="The post's own name. A relay station of the Wick's class, never the Wick itself">${d.lab.name.toUpperCase()}'S POST · A RELAY STATION OF THE WICK'S CLASS</small>
      <span class="line ${s.line.tone === "warn" ? "warn" : s.line.tone === "q" ? "q" : ""}" role="status" title="${s.line.hint}">${s.line.words}</span>
      <small class="readat${s.line.tone === "warn" ? " warn" : ""}" title="${s.sub.hint}">${s.sub.words}</small>
      ${s.beam != null ? html`<small title="One goal reached is one step of the mast's beam. It only grows.">BEAM ${s.beam} OF 10</small>` : ""}`);
    const two = (n: number) => String(Math.min(99, n)).padStart(2, "0");
    const read = (v: string, w: string, warn: boolean, hint: string) => html`<span class="readout${warn ? " warn" : ""}" title="${hint}">${tubes(v)}<span>${w}</span></span>`;
    setHtml(this.q("tubes")!, read(two(s.tubes.online), "COMPARTMENTS ONLINE", false, `${s.tubes.online} of ${d.machines.length} machine${d.machines.length === 1 ? " answers" : "s answer"} now`)
      , read(two(s.tubes.alarms), "ALARMS", s.tubes.alarms > 0, s.tubes.alarms ? `${s.tubes.alarms} thing${s.tubes.alarms === 1 ? "" : "s"} need${s.tubes.alarms === 1 ? "s" : ""} you` : "Nothing needs you")
      , read(s.tubes.clock, "BRIDGE CLOCK", false, "The bridge clock: when the board was last read, in this browser's time"));
    const ak = s.alarm ? s.alarm.words : "";
    if (ak !== this.alarmKey) {   // rebuilt only when the alarm itself changes, so it flashes once, not on every reading
      this.alarmKey = ak;
      setHtml(this.q("alarm")!, s.alarm ? html`<button type="button" class="alarm-bar${s.alarm.danger ? " danger" : ""}" data-nav="${s.alarm.route}" title="${s.alarm.hint}">${this.ic("s-warn")}<span>${s.alarm.words}</span></button>` : "");
    }
    this.tone();
  }
  /** The lamp and the beam wear the line's tone. */
  private tone() {
    const s = this.scene, t = s.line.tone;
    this.pins.lamp?.classList.toggle("warn", t === "warn");
    this.pins.lamp?.classList.toggle("low", s.quiet || t === "low" || t === "q");
    this.pins.beam?.classList.toggle("warn", t === "warn");
  }

  /** The log among the stars: arcs as constellations, goals as named stars, copies as loose stars. */
  private stars() {
    const sky = this.data.sky, st = this.q<SVGElement>("stars")!, hintEl = this.q("skyhint")!;
    if (!sky) { setHtml(st, ""); st.removeAttribute("aria-label"); st.removeAttribute("role"); st.setAttribute("aria-hidden", "true"); hintEl.hidden = true; return; }
    const con = (name: string, pts: number[][], lx: number, ly: number, cls: string, hint: string, links?: number[][]) =>
      html`<g class="con ${cls}" tabindex="0" title="${hint}"><title>${hint}</title>${(links ?? pts.slice(1).map((_, i) => [i, i + 1])).map(([a, b]) => html`<path d="M${pts[a][0]} ${pts[a][1]}L${pts[b][0]} ${pts[b][1]}"/>`)}${pts.map(([x, y], i) => html`<circle cx="${x}" cy="${y}" r="${i ? 2 : 2.6}"/>`)}<text x="${lx}" y="${ly}">${name}</text></g>`;
    const g: Part[] = []; let spot = 0;
    for (const a of sky.arcs) {
      const [ax, ay] = a.open ? [240, 410] : ARC_SPOTS[spot++ % ARC_SPOTS.length];
      const pts = Array.from({ length: Math.max(2, Math.min(6, a.stars)) }, (_, j) => [ax + 34 * j, ay + (j % 2 ? -18 : 6) + j * 4]);
      g.push(con(a.name, pts, ax - 10, ay + 42, a.open ? "form" : a.fresh && !this.reduced ? "rising" : "", a.hint));
    }
    if (sky.goals.length) {
      const off = [[0, 0], [32, 10], [62, -6], [82, 22], [16, 30], [48, 40], [96, 2], [70, 52], [112, 30], [28, 58]];
      g.push(html`<g class="named">${sky.goals.slice(0, 10).map((x, i) => html`<circle cx="${48 + off[i][0]}" cy="${140 + off[i][1]}" r="3" tabindex="0" title="${`${x.name}: ${x.hint}`}"><title>${x.name}: ${x.hint}</title></circle>`)}<text x="44" y="216">${sky.goals.length} GOAL${sky.goals.length === 1 ? "" : "S"} · NAMED STARS</text></g>`);
    }
    if (sky.copies) {
      const cp = [[74, 330], [106, 314], [132, 336], [164, 320], [190, 344], [118, 362], [154, 370]];
      g.push(sky.copies.proven
        ? con("PROVEN", cp, 64, 392, sky.copies.fresh && !this.reduced ? "rising" : "", sky.copies.hint, [[0, 1], [1, 2], [2, 3], [3, 4], [2, 5], [5, 6], [6, 4]])
        : html`<g class="loose" tabindex="0" title="${sky.copies.hint}"><title>${sky.copies.hint}</title>${cp.map(([x, y]) => html`<circle cx="${x}" cy="${y}" r="1.8"/>`)}<text x="64" y="392">THE COPIES · NOT PROVEN YET</text></g>`);
    }
    setHtml(st, g);
    st.removeAttribute("aria-hidden"); st.setAttribute("role", "img");
    st.setAttribute("aria-label", `The stars, your log: ${sky.arcs.length} arc${sky.arcs.length === 1 ? "" : "s"} as constellations, ${sky.goals.length} goals as named stars.`);
    hintEl.hidden = false;
    hintEl.textContent = this.data.friends?.length ? "THE STARS ARE YOUR LOG · CROSSED LIGHTS ARE FRIENDS" : "THE STARS ARE YOUR LOG";
    hintEl.title = "The starfield is your log: ended arcs are constellations named by their outcome, goals reached are named stars, an open arc forms in amber. Nothing in it is ever taken away.";
  }
  /** The dust behind the stars: one canvas, drawn once per size. */
  private dust() {
    const cv = this.q<HTMLCanvasElement>("dust"); if (!cv) return;
    const r = cv.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 1.5);
    if (!r.width) return;
    cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
    const c = cv.getContext("2d"); if (!c) return;
    c.fillStyle = getComputedStyle(this.root).getPropertyValue("--soft").trim() || "#9cff8a";
    let seed = 11; const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
    for (let i = 0; i < 260; i++) { c.globalAlpha = rnd() * 0.45 + 0.1; c.beginPath(); c.arc(rnd() * cv.width, rnd() * cv.height, (rnd() * 0.9 + 0.3) * dpr, 0, 6.283); c.fill(); }
    this.q("stars")?.setAttribute("preserveAspectRatio", r.width < 860 ? "xMidYMin meet" : "xMinYMin slice");
  }
  /** Friends' stations and the faction's hub: distant lights, pressed to visit. */
  private far() {
    const d = this.data, box = this.q("far")!;
    setHtml(box, (d.friends ?? []).slice(0, FAR_SPOTS.length).map((f, i) =>
      html`<button type="button" class="far ${f.lit ? "" : "out"} ${this.visiting === f.id ? "on" : ""}" data-f="${f.id}" data-css="left:${FAR_SPOTS[i][0] * 100}%;top:${FAR_SPOTS[i][1] * 100}%" title="${f.name}'s station, far off: ${f.last}. Press to visit, read-only."><i></i><span>${f.name}</span></button>`)
      , (d.hub ? html`<button type="button" class="far hubm" data-hubm data-css="left:34%;top:92%" title="${d.hub.name}, your faction's hub, far off: opens THE HUB below"><i></i><span>${d.hub.name} · HUB</span></button>` : ""));
    applyCss(box);
  }

  /** Words, icons, crew and markers over the scene: built here, moved by one transform each in layout(). */
  private overlay() {
    const s = this.scene, d = this.data;
    const h: Part[] = [s.parts.map((p) => html`<button type="button" class="part pin ${p.state === "warn" || p.state === "down" ? p.state : ""} ${p.state === "dim" ? "dim" : ""} ${p.state === "idle" ? "idle" : ""}" data-part="${p.id}" title="${`${p.name}${p.word ? `: ${p.word}` : ""}. ${p.hint}`}" aria-label="${`${p.name}${p.word ? `: ${p.word}` : ""}`}"><i></i><span>${p.name}${p.word ? ` · ${p.word}` : ""}</span></button>`)];
    // a machine with no hologram in the manifest: its kind's icon on its deck tray
    const icons = s.compartments.filter((c) => c.at && !c.model && (c.what === "machine" || (c.what === "berth" && d.joining?.length)));
    h.push(icons.map((c) => html`<button type="button" class="kico pin ${kicoClass(c.state)} ${c.what === "berth" ? "ghost" : ""}" data-c="${c.id}" title="${`${c.code} ${c.name}: ${c.word}. ${c.hint}`}" aria-label="${`${c.name}: ${c.word}`}">${this.ic(c.machine ? kindIcon(c.machine.kind) : "i-box", "")}</button>`));
    if (d.show) {
      const still = this.art(s.quiet || d.show.aired ? "still/asleep" : "still/host") ?? this.art("still/host");
      h.push(html`<button type="button" class="monx pin${still ? "" : " bare"}" data-k="mon" title="The booth's monitor: ${d.show.aired ? "the roll-call aired; press to replay it" : "tonight's roll-call; press to play it"}">${still ? html`<img src="${still}" alt="" decoding="async"><span class="tint"></span>` : ""}<span>${d.show.aired ? "AIRED" : "ROLL-CALL ▶"}</span></button>`);
    }
    if (s.cause && s.compartments.some((c) => c.machine?.cause && c.model && c.at)) h.push(html`<span class="tgt2 pin" data-k="tgt" title="The cause, lit on the machine itself"></span>`);
    h.push(html`<span class="beamx pin ${s.brighter && !this.reduced ? "grow" : ""}" data-k="beam" title="The relay beam from the mast${s.beam != null ? ": one step per goal reached. It only grows." : "."}"></span>`
      , html`<span class="lampx pin" data-k="lamp" title="The post's lamp on the mast's tip: lit while every machine answers; lit with something needing you is still lit. Low only in quiet hours."></span>`
      , html`<svg class="leads2" data-k="l2" aria-hidden="true"></svg><span data-k="crew"></span>`);
    const ov = this.q("ov")!;
    setHtml(ov, h);
    this.pins = {
      parts: [...ov.querySelectorAll<El>(".part")], icons: [...ov.querySelectorAll<El>(".kico")].map((el, i) => ({ c: icons[i], el })), crew: [],
      mon: this.q("mon"), tgt: this.q("tgt"), lamp: this.q("lamp"), beam: this.q("beam"), wx: this.q("wx"), l2: this.q<SVGElement>("l2"),
    };
    this.rows = null; this.partW = null; this.sig = "";
    this.tone();
    if (this.view) this.addCrew();
  }
  /** The crew: after the station's first frame, never before it. A cut-out when the manifest has
      one, else the shell's shipped portrait in a porthole, else its name alone. */
  private addCrew() {
    const box = this.q("crew"); if (!box || box.childElementCount || this.mascot === "off") return;
    const s = this.scene, groups = new Map<string, CrewPlace[]>();
    for (const c of s.crew) { if (c.where !== "mast" && !s.compartments.some((x) => x.id === c.where && x.foot)) continue; groups.set(c.where, [...(groups.get(c.where) ?? []), c]); }
    const h: Part[] = [];
    const list: { p: CrewPlace; i: number; n: number }[] = [];
    for (const g of groups.values()) g.forEach((p, i) => {
      const cut = this.art(`crew/${p.shell}-${p.pose}`) ?? this.art(`crew/${p.shell}`);
      const still = cut ? null : this.art(`still/${p.shell}`);
      if (!cut && !still && !p.duty) return;         // off duty with no painting: named in quarters' row, not drawn
      list.push({ p, i, n: g.length });
      const cls = `${!this.reduced && !s.quiet && cut ? "bob" : ""} ${p.tone === "dim" ? "dark" : ""} d${i % 5}`;
      h.push(cut ? html`<img class="crewx pin ${cls}" src="${cut}" alt="" decoding="async" title="${`STATIC as ${SHELL_NAME[p.shell]}: ${p.hint}`}">`
        : still ? html`<img class="crewp pin ${cls}${p.duty ? "" : " sm"}" src="${still}" alt="" decoding="async" title="${`STATIC as ${SHELL_NAME[p.shell]}: ${p.hint}`}">`
        : html`<span class="crewn pin" title="${`STATIC as ${SHELL_NAME[p.shell]}: ${p.hint}`}">${this.ic("i-crew")}</span>`);
      h.push(p.duty && p.caption ? html`<span class="cap2 pin ${p.tone === "warn" ? "warn" : p.tone === "busy" ? "busy" : ""}" title="${p.hint}">${p.caption}</span>` : html`<i hidden></i>`);
    });
    setHtml(box, h);
    const kids = [...box.children] as El[];
    this.pins.crew = list.map((x, j) => ({ ...x, el: kids[j * 2], cap: kids[j * 2 + 1].tagName === "SPAN" ? kids[j * 2 + 1] : null }));
    this.sig = ""; this.view?.kick();
  }
  /** The deck list: every compartment by deck, its code, its state and one reading. */
  private deckList() {
    const s = this.scene;
    setHtml(this.q("decks")!, DECKS.map((dk) => {
      const cs = s.compartments.filter((c) => c.deck === dk.id);
      if (!cs.length) return "";
      return html`<div><b title="${dk.hint}">${dk.id} · ${dk.name}<span>${cs.length}</span></b>${cs.map((c) =>
        html`<button type="button" class="crow ${c.state === "warn" || c.state === "down" ? c.state : ""} ${c.state === "dim" ? "dim" : ""}" data-c="${c.id}" title="${`${c.code} ${c.name}: ${c.word}. ${c.hint}`}"><i>${c.code}</i><span><b>${c.name}</b><small>${c.reading}</small></span>${this.st(c.state, c.word)}</button>`)}</div>`;
    }));
    this.rows = null;
  }
  private asides() {
    const d = this.data, s = this.scene, x = d.exchange;
    const face = this.art("still/snow");
    setHtml(this.q("asl")!, x && this.mascot !== "off" && !s.quiet
      ? html`<div class="xch${face ? "" : " noface"}" title="${`An exchange, because something real happened: ${x.why}. Settings › Mascot sets On, Quiet or Off.`}">${face ? html`<span class="xface"><img src="${face}" alt="" decoding="async"><span class="tint"></span></span>` : ""}<p class="bub" role="status" aria-live="polite"><em>[${x.mood}]</em><span class="sr">STATIC thinks: </span>${x.thought}</p><p class="vec"><b>VECTOR</b>${x.vector}</p></div>` : "");
    const p = d.plan, pk = p ? JSON.stringify(p) : "";
    setHtml(this.q("asr")!, p && pk !== this.planGone && !s.quiet ? html`<div class="vplan" data-k="plan" title="VECTOR's plan: the one thing to act on in the scene. While you choose, STATIC steps away. Choosing pays nothing.">
      <h3><span>${p.title}</span><span>${p.steps.length} STEP${p.steps.length === 1 ? "" : "S"}</span></h3>
      <ol>${p.steps.map((t) => html`<li title="${t.hint ?? t.words}">${t.words}${t.detail ? html`<small>${t.detail}</small>` : ""}</li>`)}</ol>
      <div class="acts">${p.can.includes("approve") ? html`<button class="tx go" type="button" data-plan="approve" title="Approve: VECTOR runs the steps that change nothing by themselves; the activity drawer shows them">APPROVE</button>` : ""}${p.can.includes("change") ? html`<button class="tx" type="button" data-plan="change" title="Change: talk the plan over with VECTOR">CHANGE</button>` : ""}${p.can.includes("no") ? html`<button class="tx" type="button" data-plan="no" title="No: VECTOR does nothing. The alert stays until it is fixed; nothing worse happens because you said no.">NO</button>` : ""}</div>
      ${p.from ? html`<p>${p.from}</p>` : ""}</div>` : "");
    const f = (d.friends ?? []).find((q) => q.id === this.visiting);
    setHtml(this.q("ast")!, f ? html`<div class="visitc" title="A read-only visit: shapes and states only. ${f.name} chose to share; they can stop at any time.">
      <h3><span>${f.name}'S STATION</span>${this.st(f.lit ? "ok" : "unknown", f.lit ? "LIT" : "NOT IN")}</h3><small>${f.decks} decks · ${f.stars} named stars · ${f.last}</small>
      <div class="mini-st" title="Their station as shapes: one box per deck, lit where a shell stands">${Array.from({ length: Math.min(6, f.decks) }, (_, i) => html`<span class="${i ? "" : "on"}" title="Deck ${i + 1}: ${i ? "quiet" : "the watch is kept"}">${i ? i + 1 : "W"}</span>`)}</div>
      <ul class="perm"><li title="What a visitor sees">${this.ic("i-eye")}<span>The beacon, the decks, which have a shell, their stars.</span></li><li title="What a visitor never sees">${this.ic("i-noeye")}<span class="muted">Machine names, addresses, apps, files, the show's words.</span></li></ul>
      <div class="acts"><button class="tx" type="button" data-nav="people" title="Who can visit your own station: People › Ways in">WHO CAN VISIT YOURS</button></div></div>` : "");
    this.sig = "";
  }

  // ---------------------------------------------------------------- the hologram scene
  private piecesOf(): PieceSpec[] {
    const s = this.scene, a = this.o.assets, wick = a.models["wick-cut"];
    const out: PieceSpec[] = [];
    if (!wick) return out;
    out.push({ id: "wick", src: join(a.base, wick.src), info: wick.info, at: [0, 0, 0], size: 0.92, yaw: YAW0, gain: 0.62, tablePower: 0.1, causeOnly: true,
      state: s.quiet ? "dim" : s.weather === "nosignal" ? "off" : s.cause ? s.cause.state : "ok", cause: s.cause ? s.cause.part : null });
    for (const c of s.compartments) {
      if (!c.model || !c.at || !c.machine) continue;
      const m = a.models[c.model], ci = c.machine.cause ? m.info.parts.findIndex((p) => p.id === c.machine!.cause) : -1;
      out.push({ id: `m:${c.id}`, parent: "wick", src: join(a.base, m.src), info: m.info, at: [0, 0, 0], size: 0.1, local: c.at, localSize: c.size, localYaw: c.yaw, table: false,
        gain: c.machine.kind === "router" || c.machine.kind === "ups" ? 0.7 : 0.9, causeOnly: true,
        state: c.state === "dim" ? "dim" : viewState(c.state, false), cause: ci >= 0 ? ci : null });
    }
    return out;
  }
  private async mountScene() {
    const pieces = this.piecesOf();
    this.key = sceneKey(this.scene);
    if (!pieces.length) { this.fail(new Error("lamplight: the manifest has no station model (wick-cut)")); return; }
    try {
      const v = await HoloView.create(this.q("scene")!, { camera: { target: [0.02, 0.46, 0.04], dist: 2.2, pitch: 0.2, fov: 30 }, pieces, reduced: this.reduced, bloom: this.scene.quiet ? 0.35 : 0.7, fps: () => this.fps() });
      if (this.dead) { v.dispose(); return; }
      this.view = v;
      v.lines((t) => this.lines(t));
      v.beforeDraw((vv) => { const w = vv.pieces.get("wick"); if (w) w.spec.yaw = this.yawNow(performance.now()); });
      v.onFrame((vv) => this.layout(vv));
      this.q("stage")!.classList.add("ready");
      this.fit();
      if (sceneKey(this.scene) !== this.key) this.syncModels();
      requestAnimationFrame(() => { if (!this.dead) this.addCrew(); });
      this.o.onReady?.();
    } catch (e) {
      // no WebGL, or the station's model didn't load: the words (the line, the readouts, the alarm,
      // the deck list, the deck plan) stand without the hologram, and the host is told
      this.q("stage")!.classList.add("nogl");
      this.fail(e);
    }
  }
  /** New data: the same holograms get their new states; machines that came or went are added or removed. */
  private syncModels() {
    const v = this.view; if (!v) return;
    const want = this.piecesOf(), key = sceneKey(this.scene);
    if (key !== this.key) {
      this.key = key;
      const ids = new Set(want.map((p) => p.id));
      for (const id of [...v.pieces.keys()]) if (!ids.has(id)) v.remove(id);
      for (const p of want) if (!v.pieces.has(p.id)) v.add(p).catch((e) => this.fail(e));
    }
    for (const p of want) if (v.pieces.has(p.id)) v.set(p.id, p.id === "wick" ? { state: p.state, cause: p.cause } : { state: p.state, cause: p.cause, local: p.local, localSize: p.localSize });
    v.bloom = this.scene.quiet ? 0.35 : 0.7;
    v.setReduced(this.reduced);
    this.sig = ""; v.kick();
  }
  private yawNow(now: number): number {
    const night = this.scene.quiet ? 0.5 : 0;
    if (this.reduced) return YAW0 + night;
    if (now < this.turnUntil) this.yawT += Math.min(0.1, (now - (this.yawLast || now)) / 1000);
    this.yawLast = now;
    return YAW0 + night + 0.28 * Math.sin(this.yawT * 0.21);
  }
  /** The turn runs for 20 s after a change or the pointer; then only a warn pulse or a carried copy moves. */
  private fps(): number {
    if (this.reduced) return 0;
    const turning = performance.now() < this.turnUntil;
    this.root.classList.toggle("idle", !turning);
    const moving = this.scene.weather === "interference" || this.pins.crew.some((c) => c.p.tone === "busy");
    return turning ? (this.phone ? 15 : 24) : moving && !this.scene.quiet ? 8 : 0;
  }
  private motion() { this.turnUntil = performance.now() + 20_000; this.view?.kick(); }
  private lines(t: number): Seg[] {
    const v = this.view, out: Seg[] = [], w = v?.pieces.get("wick"); if (!v || !w) return out;
    const k = w.spec.size / (w.spec.info.height || 1), a = w.spec.yaw ?? 0, s = this.scene;
    const W = (L: number[]) => [k * (L[0] * Math.cos(a) + L[2] * Math.sin(a)), k * L[1] + 0.02 * w.spec.size, k * (-L[0] * Math.sin(a) + L[2] * Math.cos(a))];
    const ph = v.pal("--phosphor"), so = v.pal("--soft"), cy = v.pal("--cyan"), q = s.quiet ? 0.3 : 1;
    const c4 = (c: number[], al: number) => [c[0], c[1], c[2], al], push = (p: number[], r: number[], c: number[]) => out.push({ a: p, b: r, ca: c, cb: c });
    const lerp = (p: number[], r: number[], u: number) => p.map((x, i) => x + (r[i] - x) * u);
    const dash = (p: number[], r: number[], n: number, c: number[], al: number) => { for (let j = 0; j < n; j += 2) push(W(lerp(p, r, j / n)), W(lerp(p, r, (j + 1) / n)), c4(c, al)); };
    const ring = [0, 0.05, 0.09 + ZC];
    for (const c of s.compartments) if (c.deck === "DOCK" && c.at) dash([c.at[0] + (c.at[0] < 0 ? 0.06 : -0.06), c.at[1] + 0.03, c.at[2]], ring, 12, ph, (c.what === "berth" ? 0.35 : 0.5) * q);
    // the copy EXO carries: dots from the machine being copied into the hold, while the backup runs
    const exo = s.crew.find((c) => c.shell === "exo" && c.duty), hold = exo && s.compartments.find((c) => c.id === exo.where);
    const job = exo && (this.data.jobs ?? []).find((j) => /backup|restore/.test(j.kind)), from = job && s.compartments.find((c) => c.id === job.machine && c.at);
    if (hold?.at && from?.at && from !== hold) {
      const p0 = [from.at[0] + 0.04, from.at[1] + 0.03, from.at[2] + 0.05], p1 = [hold.at[0] - 0.03, hold.at[1] + 0.03, hold.at[2] + 0.03];
      dash(p0, p1, 10, cy, 0.7);
      if (!this.reduced) { const f = (t * 0.45) % 1; push(W(lerp(p0, p1, f)), W(lerp(p0, p1, Math.min(1, f + 0.08))), c4(so, 1.5)); }
    }
    return out;
  }
  private fit() {
    const v = this.view; if (!v) return;
    const st = this.q("stage")!, w = st.clientWidth, h = st.clientHeight, asp = w / Math.max(1, h), tan = Math.tan((15 * Math.PI) / 180), narrow = w < 860;
    let H = narrow ? 1.16 : 1.08; if (H * asp < (narrow ? 1.2 : 1.3)) H = (narrow ? 1.2 : 1.3) / asp;
    v.camera({ dist: H / (2 * tan), target: [0.02, narrow ? 0.47 : 0.46, 0.04], pitch: 0.2, yaw: 0 });
    this.rows = null; this.partW = null; this.sig = "";
  }
  /** Place the overlay from the scene's projection: only when the view changed, one transform each. */
  private layout(v: HoloView) {
    const w = v.pieces.get("wick"); if (!w) return;
    const st = this.q("stage")!, W0 = st.clientWidth, s = this.scene;
    const yaw = w.spec.yaw ?? 0;
    const sig = `${yaw.toFixed(4)}|${W0}|${st.clientHeight}|${v.cam.dist.toFixed(3)}|${this.pins.crew.length}`;
    if (sig === this.sig) return;
    this.sig = sig;
    const k = w.spec.size / (w.spec.info.height || 1), ca = Math.cos(yaw), sa = Math.sin(yaw);
    const pt = (L: number[]): Pt => v.point([k * (L[0] * ca + L[2] * sa), k * L[1] + 0.02 * w.spec.size, k * (-L[0] * sa + L[2] * ca)]);
    const unit = Math.abs(pt([0, 0.1, ZC]).y - pt([0, 0, ZC]).y) * 10;
    const anchor = Object.fromEntries(w.spec.info.parts.map((p) => [p.id, p.anchor]));
    const PART_AT: Record<string, number[]> = {
      mast: anchor.mast && [anchor.mast[0], anchor.mast[1] - 0.08, anchor.mast[2]], dish: anchor.dish, whips: anchor.whips, arrays: anchor.solar_l, rackroom: anchor.rackroom,
      dock: anchor.dock && [anchor.dock[0] + 0.08, anchor.dock[1] - 0.02, anchor.dock[2] + 0.2],
      hull: anchor.hull && (W0 < 860 ? [anchor.hull[0] + 0.02, anchor.hull[1] - 0.16, anchor.hull[2] + 0.2] : [anchor.hull[0] + 0.3, anchor.hull[1] - 0.13, anchor.hull[2] + 0.06]),
    };
    // a part's label stays inside the stage (its width is measured once per layout, before anything is moved)
    const pw = (this.partW ??= this.pins.parts.map((e) => e.offsetWidth));
    s.parts.forEach((p, i) => {
      const a = PART_AT[p.id]; if (!a) return;
      const q = pt(a), half = pw[i] / 2 + 4;
      put(this.pins.parts[i], Math.min(Math.max(q.x, half), Math.max(half, W0 - half)), q.y, "-50%", "-50%");
    });
    for (const { c, el } of this.pins.icons) {
      const q = pt([c.at![0], c.at![1], c.at![2]]), px = Math.max(26, unit * (c.size || 0.07) * 0.9);
      el.style.setProperty("--k", `${px.toFixed(0)}px`);
      put(el, q.x, q.y);
    }
    for (const x of this.pins.crew) {
      const c = s.compartments.find((q) => q.id === x.p.where), f = x.p.where === "mast" ? MAST_FOOT : c?.foot; if (!f) continue;
      const spread = c?.what === "quarters" || x.n > 1;
      const L = spread ? [f[0] - 0.05 + (x.n > 1 ? (0.1 * x.i) / (x.n - 1) : 0), f[1], f[2]] : f;
      const b = pt(L), cut = x.el.classList.contains("crewx");
      const hpx = cut ? Math.max(22, unit * (c?.what === "quarters" ? 0.06 : x.p.where === "mast" ? 0.07 : 0.1)) : Math.max(18, unit * (x.p.duty ? 0.055 : 0.035));
      x.el.style.setProperty("height", `${hpx.toFixed(0)}px`);
      if (!cut) x.el.style.setProperty("width", `${hpx.toFixed(0)}px`);
      put(x.el, b.x, b.y);
      if (x.cap) put(x.cap, b.x, b.y + 12, "-50%", "0");
    }
    if (this.pins.mon) { const q = pt(MONITOR_AT); this.pins.mon.style.setProperty("width", `${Math.max(48, unit * 0.13).toFixed(0)}px`); put(this.pins.mon, q.x, q.y); }
    if (this.pins.tgt) {
      const c = s.compartments.find((q) => q.machine?.cause && q.model && q.at), piece = c && v.pieces.get(`m:${c.id}`);
      const ci = piece ? piece.spec.cause : null, an = c && ci != null ? v.anchors(`m:${c.id}`)[ci] : null;
      if (an) put(this.pins.tgt, an.x, an.y, "-50%", "-50%");
    }
    const tip = anchor.mast ? pt([anchor.mast[0], 0.93, anchor.mast[2]]) : pt([0, 0.93, 0]);
    put(this.pins.lamp, tip.x, tip.y, "-50%", "-50%");
    if (this.pins.beam) {
      const bh = (Math.max(30, tip.y - 30) * (s.beam ?? 4)) / 10;
      this.pins.beam.style.setProperty("height", `${bh.toFixed(0)}px`);
      this.pins.beam.style.setProperty("--h0", `${((bh * Math.max(1, (s.beam ?? 4) - 1)) / Math.max(1, s.beam ?? 4)).toFixed(0)}px`);
      put(this.pins.beam, tip.x, tip.y);
    }
    if (this.pins.wx) {
      const r = v.rect("wick");
      if (r) {
        const band = this.pins.wx.classList.contains("intf"), box = band ? [r.x - 30, r.y + r.h * 0.38, r.w + 60, r.h * 0.4] : [r.x - 20, r.y - 10, r.w + 40, r.h + 20];
        this.pins.wx.style.setProperty("width", `${box[2].toFixed(0)}px`); this.pins.wx.style.setProperty("height", `${box[3].toFixed(0)}px`);
        put(this.pins.wx, box[0], box[1], "0", "0");
      }
    }
    // leaders from the deck list's rows to their compartments (row positions measured once per layout)
    const wide = W0 >= 860, l2 = this.pins.l2;
    if (wide && l2) {
      if (!this.rows) {
        const sr = st.getBoundingClientRect();
        this.rows = [...this.root.querySelectorAll<El>(".crow")].filter((r) => s.compartments.some((c) => c.id === r.dataset.c && c.at))
          .map((r) => { const b = r.getBoundingClientRect(); return { id: r.dataset.c!, x: b.left - sr.left, y: b.top - sr.top + b.height / 2 }; });
        setHtml(l2, this.rows.map((r) => { const c = s.compartments.find((q) => q.id === r.id)!; return html`<path class="${c.state === "warn" || c.state === "down" ? "warn" : ""}" data-l="${r.id}"/>`; }));
        this.paths = [...l2.querySelectorAll("path")];
      }
      this.rows.forEach((r, i) => {
        const c = s.compartments.find((q) => q.id === r.id)!, p = pt(c.what === "machine" ? [c.at![0], c.at![1] + 0.05, c.at![2]] : c.at!);
        this.paths[i].setAttribute("d", `M${r.x.toFixed(0)} ${r.y.toFixed(0)}H${(r.x - 14).toFixed(0)}L${p.x.toFixed(0)} ${p.y.toFixed(0)}`);
      });
    } else if (l2 && l2.firstChild) { setHtml(l2, ""); this.rows = null; }
    const plan = this.q("plan"), lead = this.q<SVGElement>("lead")!;
    if (plan && wide) {
      const wr = this.q("wrap")!.getBoundingClientRect(), cr = plan.getBoundingClientRect(), sr = st.getBoundingClientRect();
      const need = this.data.needs[0], nc = need && s.compartments.find((c) => c.id === need.machine && c.at);
      const p = pt(this.data.show ? BOOTH_EDGE : nc ? [nc.at![0] + 0.05, nc.at![1] + 0.04, nc.at![2]] : BOOTH_EDGE);
      const ax = p.x + sr.left - wr.left, ay = p.y + sr.top - wr.top, bx = cr.left - wr.left, by = cr.top - wr.top + 20;
      setHtml(lead, html`<path d="M${ax.toFixed(0)} ${ay.toFixed(0)}L${(bx - 24).toFixed(0)} ${ay.toFixed(0)}L${bx.toFixed(0)} ${by.toFixed(0)}"/><circle cx="${ax.toFixed(0)}" cy="${ay.toFixed(0)}" r="3"/>`);
    } else if (lead.firstChild) setHtml(lead, "");
  }
  /** Hover-link: a deck row, a deck-plan box, a leader, an icon and the hologram light together. */
  private hot(id: string, on: boolean) {
    this.view?.set(`m:${id}`, { hover: on });
    this.root.querySelectorAll(`[data-c="${CSS.escape(id)}"], [data-cmp="${CSS.escape(id)}"], [data-l="${CSS.escape(id)}"]`).forEach((e) => e.classList.toggle("hot", on));
  }

  // ---------------------------------------------------------------- the panels under the station
  setTab(t: string) {
    if (!this.tabs().includes(t as Tab) || t === this.o.tab) return;
    if (this.o.tab === "hub") this.dropHub();
    if (this.o.tab === "booth") this.stop();
    this.o.tab = t;
    this.root.dataset.tab = t;
    this.root.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String((b as El).dataset.tab === t)));
    this.buildTab(t as Tab);
  }
  private buildTab(t: Tab) {
    if (this.built[t]) return;
    const p = this.root.querySelector<El>(`[data-p="${t}"]`); if (!p) return;
    this.built[t] = true;
    if (t === "decks") setHtml(p, this.deckPlan());
    if (t === "booth") { setHtml(p, this.boothHTML()); this.cur = 0; this.show(0); }
    if (t === "log") setHtml(p, this.logHTML());
    if (t === "hub") { setHtml(p, this.hubHTML()); void this.mountHub(); }
    applyCss(p);
  }
  /** The deck plan: the station in side elevation, a box per compartment, lit by its state. */
  private deckPlan(): Safe {
    const s = this.scene;
    const row = (deck: string, y: number, h: number, x0: number, x1: number): Part => {
      const cs = s.compartments.filter((c) => c.deck === deck), n = cs.length; if (!n) return "";
      const w = (x1 - x0 - 4 * (n - 1)) / n;
      return cs.map((c, i) => this.box(c, x0 + i * (w + 4), y, w, h));
    };
    const dock = s.compartments.filter((c) => c.deck === "DOCK"), dx = [10, 220, 115, 10, 220];
    const g: Part[] = [html`<path class="ol" d="M150 12V70M138 30H162M136 44H164M140 58H160"/><path class="ol" d="M78 92H222L232 112V196L210 222H90L68 196V112Z"/><path class="ol2" d="M68 152H232M70 112H230M90 222L104 252H196L210 222"/>`
      , html`<path class="ol" d="M68 140H14V156H68M232 140H286V156H232"/><path class="ol" d="M196 70a24 24 0 1 0 30 -26"/><text x="10" y="134">ARRAYS</text><text x="234" y="40">DISH</text><text x="156" y="24">MAST</text>`
      , html`<text x="236" y="106">D3</text><text x="236" y="148">D2</text><text x="236" y="190">D1</text><text x="112" y="268">DOCKING RING</text>`
      , row("D3", 94, 16, 84, 216), row("D2", 114, 36, 82, 222), row("D1", 156, 36, 82, 222)
      , dock.slice(0, 5).map((c, i) => this.box(c, dx[i], i < 3 ? 232 : 272, 70, i === 2 ? 0 : 36))
      , html`<text x="10" y="${dock.length > 3 ? 322 : 292}">SIDE ELEVATION · NOT TO SCALE</text>`];
    return html`<div class="planpanel"><div class="panel" title="The deck plan: the station in side elevation, a box per compartment, lit by its state. Point at one to light it on the station; press a machine to open its page."><h3><span>${this.ic("i-module")}DECK PLAN</span><span class="muted hnote">hover links to the station</span></h3>
      <svg class="elev" viewBox="0 0 300 ${dock.length > 3 ? 330 : 300}" role="img" aria-label="The deck plan: the station in side elevation, a box for each compartment on its deck">${g}</svg></div>
      <div class="panel" title="How to read the deck plan and the deck list"><h3><span>${this.ic("i-idea")}READING IT</span></h3><ul class="perm">
      <li title="A box's colour">${this.ic("s-ok")}<span>A box is a compartment: one machine. Lit when fine, amber when it needs you, red when it is down, dotted when it hasn't been read.</span></li>
      <li title="A machine just installed">${this.ic("s-start")}<span>A half ring is a machine being set up, or a job running on it. Nothing is wrong.</span></li>
      <li title="Dashed boxes">${this.ic("s-todo")}<span>Dashed boxes hold crew, not machines.</span></li>
      <li title="Codes">${this.ic("i-logs")}<span>Codes such as D2·A name a deck and a place on it. They match the list beside the station.</span></li>
      <li title="Pressing">${this.ic("i-open")}<span>Press a machine to open its page. Press the hull on the station for the drives.</span></li></ul></div></div>`;
  }
  private box(c: Compartment, x: number, y: number, w: number, h: number): Part {
    if (!h) return "";
    const cls = [c.state === "warn" || c.state === "down" ? c.state : c.state === "busy" || c.state === "setup" ? "busy" : c.state === "dim" ? "dim" : c.state === "unknown" ? "unk" : "", c.what === "machine" ? "" : "crew"].join(" ");
    return html`<rect class="cmp ${cls}" data-cmp="${c.id}" x="${x.toFixed(1)}" y="${y}" width="${w.toFixed(1)}" height="${h}"><title>${`${c.code} ${c.name}: ${c.word}. ${c.hint}`}</title></rect><text class="k" x="${(x + 4).toFixed(1)}" y="${y + 11}">${c.code}</text>${h > 20 && w > 38 ? html`<text x="${(x + 4).toFixed(1)}" y="${y + h - 5}">${c.name.split(" ")[0].slice(0, Math.floor(w / 6.5))}</text>` : ""}`;
  }
  /** One log: tube times and each entry's mark among the stars; and the goals. */
  private logHTML(): Safe {
    const d = this.data, log = d.log ?? [], g = d.goals;
    const sg = (k: string) => k === "arc" ? html`<svg class="sg" viewBox="0 0 22 22" aria-hidden="true"><path d="M3 15L10 6L18 12"/><circle cx="3" cy="15" r="2"/><circle cx="10" cy="6" r="2"/><circle cx="18" cy="12" r="2"/></svg>` : html`<svg class="sg" viewBox="0 0 22 22" aria-hidden="true"><circle class="star" cx="11" cy="11" r="3"/></svg>`;
    const ic = { done: "s-done", progress: "s-start", todo: "s-todo" } as const;
    const h: Part[] = [html`<div class="two">`];
    if (log.length) h.push(html`<div class="panel" title="The station log: when each thing happened, and its mark among the stars. Nothing in it is ever taken away."><h3><span>${this.ic("i-logs")}STATION LOG</span><span class="muted hnote">${log.length} entr${log.length === 1 ? "y" : "ies"}</span></h3>
      <ul class="log">${log.map((e) => html`<li class="${e.mark === "open" ? "warn" : e.mark === "fresh" ? "fresh" : ""}" title="${`${e.at} · ${e.title}: ${e.detail}`}">${tubes(e.at, true)}${sg(e.kind)}<span><b>${e.title}</b><small>${e.detail}</small></span></li>`)}</ul></div>`);
    if (g) {
      const r = g.rank, pct = (v: number) => (r ? (((v - r.from) / (r.to - r.from)) * 100).toFixed(1) : "0");
      h.push(html`<div class="panel" title="Goals: real good practice. Each pays capped field XP, names a star and grows the station. Clearance is never earned here."><h3><span>${this.ic("i-lamp")}GOALS · THE STATION GROWS</span><span class="muted hnote">${g.list.filter((x) => x.state === "done").length} of ${g.list.length} reached</span></h3>
        ${r ? html`<div class="rank" title="Field rank: earned only. The lab's goals add to it. Clearance is the paid ladder and is never earned here."><b>${r.title}</b><span class="bar"><i data-css="width:${pct(r.xp - (r.gained ?? 0))}%"></i>${r.gained ? html`<i class="add" data-css="left:${pct(r.xp - r.gained)}%;width:${((r.gained / (r.to - r.from)) * 100).toFixed(1)}%"></i>` : ""}</span><span class="muted n">${r.xp.toLocaleString("en-US")} / ${r.to.toLocaleString("en-US")}</span><small>${r.to - r.xp} XP to ${r.next}${r.gained ? ` · +${r.gained} tonight` : ""}</small></div>` : ""}
        <ul class="goals">${g.list.map((x) => html`<li class="${x.state === "done" ? "done" : x.state === "progress" ? "going" : "todo"}${x.fresh ? " fresh" : ""}" title="${`${x.title}: ${x.detail}. ${x.xp} field XP, capped at ${x.cap}.`}">${this.ic(ic[x.state])}<b>${x.title}</b><span class="xp">${x.xp} XP<em>${x.cap}</em></span><small>${x.detail}</small></li>`)}</ul>
        <ul class="never" aria-label="Never paid"><li title="Deleting, erasing or formatting never pays">NO XP FOR DELETING</li><li title="Restarting never pays">NO XP FOR REBOOTS</li><li title="A loop of test restores pays nothing">NO XP FOR TEST LOOPS</li><li title="Approving a plan or a device never pays">NO XP FOR APPROVING</li><li title="Looking, watching and visiting pay nothing">NO XP FOR LOOKING</li><li title="No streaks, no daily reward, nothing for sale">NO STREAKS</li></ul></div>`);
    }
    return html`${h}</div>`;
  }

  // ---- the booth: the roll-call (built when its tab opens; a clip is never fetched before it plays)
  private boothHTML(): Safe {
    const sh = this.data.show!, th = sh.thread;
    return html`<div class="show"><div><div class="scr" data-k="scr" role="region" aria-roledescription="show" aria-label="Tonight's roll-call"></div>
      <div class="ctl"><button class="ib sm" type="button" data-show="prev" title="The card before">${this.ic("i-prev", "s20")}</button><button class="ib" type="button" data-show="play" data-k="play" title="Play the roll-call: about a minute, silent. Nothing plays by itself.">${this.ic("i-play", "")}</button><button class="ib sm" type="button" data-show="next" title="The next card">${this.ic("i-next", "s20")}</button><span class="dots" data-k="dots"></span><span class="muted when" title="When the roll-call was made">${sh.when}</span></div></div>
      ${th ? html`<div class="panel is-warn" title="The open arc is the show's thread: one card a night until it ends with a verified outcome"><h3><span>${this.ic("i-drive")}${th.title}</span>${this.st("warn", th.night)}</h3><ol class="thread">${th.steps.map((x) => html`<li class="${x.next ? "next" : ""}" title="${`${x.title}: ${x.detail}`}"><span>${x.when}${x.date ? html`<br>${x.date}` : ""}</span><div><b>${x.title}</b><small>${x.detail}</small></div></li>`)}</ol></div>`
        : html`<div class="panel" title="Tonight's cards, as text"><h3><span>${this.ic("i-tv")}TONIGHT'S CARDS</span></h3><ol class="cards">${sh.cards.map((c, k) => html`<li class="${c.kind === "bump" ? "bump" : ""}" data-card="${k}" title="${c.hint}"><span>${String(k + 1).padStart(2, "0")}</span><b>${c.over}${c.kind === "bump" ? "" : ` · ${c.title}`}</b><small>${c.kind === "bump" ? `${c.title}: a short clip, silent` : c.detail || c.vector || c.title}</small></li>`)}</ol></div>`}</div><p class="sr" aria-live="polite" data-k="live"></p>`;
  }
  private media(c: LampCard): Part {
    const a = c.art ?? "", [kind, name] = a.split("/");
    if (kind === "bump") {
      const mp4 = this.art(a), poster = this.art(`poster/${name}`);
      if (mp4 && !this.reduced) return html`<video class="media" src="${mp4}"${poster ? html` poster="${poster}"` : ""} muted playsinline preload="none"></video>`;
      return poster ? html`<img class="media" src="${poster}" alt="">` : "";
    }
    if (kind === "loop") { const u = (this.reduced ? null : this.art(a)) ?? this.art(`still/${name}`); return u ? html`<img class="media" src="${u}" alt="" decoding="async">` : ""; }
    const u = a ? this.art(a) ?? (kind === "crew" ? this.art(`still/${name.split("-")[0]}`) : null) : null;
    return u ? html`<img class="media ${kind === "crew" && this.art(a) ? "cutout" : ""}" src="${u}" alt="" decoding="async">` : "";
  }
  private show(i: number) {
    const sh = this.data.show, scr = this.q("scr"); if (!sh || !scr) return;
    const C = sh.cards; this.cur = (i + C.length) % C.length; const c = C[this.cur];
    const hold = sh.aired && !this.playing && this.cur === 0, held = this.art("still/asleep");
    scr.className = `scr${c.kind === "open" && !hold ? " title" : ""}`; scr.title = c.hint;
    setHtml(scr, hold
      ? html`${held ? html`<img class="media" src="${held}" alt="">` : ""}<span class="tint"></span><span class="vig"></span><span class="ch">142.59</span><span class="ch r">${sh.when.toUpperCase()}</span><div class="cap"><span class="k">ALREADY AIRED</span><span class="t">NOTHING AIRS NOW</span><span class="d">Tonight's roll-call stays here to replay. Nothing plays unless you press play.</span></div>`
      : html`${this.media(c)}<span class="tint"></span><span class="vig"></span><span class="ch">142.59 · ${this.data.lab.name.toUpperCase()}</span><span class="ch r">${this.cur + 1} / ${C.length}</span><div class="cap"><span class="k">${c.over}</span><span class="t">${c.title}</span>${c.detail ? html`<span class="d">${c.detail}</span>` : ""}${c.vector ? html`<span class="v"><b>VECTOR</b>${c.vector}</span>` : ""}</div>`);
    const v = scr.querySelector("video");
    if (v) { v.addEventListener("ended", () => { if (this.playing) this.next(); }); if (this.playing) v.play().catch(() => {}); }
    setHtml(this.q("dots")!, C.map((x, k) => html`<button type="button" data-dot="${k}" class="${k === this.cur ? "on" : ""}${x.kind === "bump" ? " bump" : ""}" title="${`Card ${k + 1}: ${x.over}, ${x.title}`}" aria-label="Card ${k + 1}"></button>`));
    this.root.querySelectorAll<El>("[data-card]").forEach((li) => li.classList.toggle("on", Number(li.dataset.card) === this.cur));
    this.q("live")!.textContent = `Card ${this.cur + 1} of ${C.length}: ${c.over}. ${c.title}. ${c.detail ?? ""} ${c.vector ? `VECTOR: ${c.vector}` : ""}`;
    clearTimeout(this.timer);
    if (this.playing && !v) this.timer = window.setTimeout(() => this.next(), 6000);
  }
  private next() { if (this.cur === (this.data.show?.cards.length ?? 1) - 1) { this.stop(); return; } this.show(this.cur + 1); }
  private stop() {
    this.playing = false; clearTimeout(this.timer);
    const b = this.q("play"); if (b) { setHtml(b, this.ic("i-play", "")); b.title = "Play the roll-call: about a minute, silent. Nothing plays by itself."; }
    this.root.querySelector<HTMLVideoElement>('[data-k="scr"] video')?.pause();
  }
  private play() {
    if (!this.data.show) return;
    this.buildTab("booth"); this.playing = true;
    const b = this.q("play"); if (b) { setHtml(b, this.ic("i-pause", "")); b.title = "Pause"; }
    this.show(this.cur === this.data.show.cards.length - 1 ? 0 : this.cur);
    this.q("scr")?.scrollIntoView({ behavior: this.reduced ? "auto" : "smooth", block: "center" });
  }

  // ---- the hub: a faction as a place. Its view exists only while its tab is open.
  private hubHTML(): Safe {
    const hb = this.data.hub!;
    return html`<div class="hubwrap"><div class="stage hubstage" data-k="hubstage" role="img" aria-label="${`${hb.name}: the faction's server as a larger structure of the same class, its channels as docks, ${hb.members.length} members' stations in orbit`}">
      <div class="scene" data-k="hubscene"></div><span class="loading" title="The hub's hologram is loading">TUNING IN…</span><div class="ov" data-k="hubov"></div>
      <div class="hubhead" title="The faction you are in, as a place. Everything here is what the faction already shows its members, or what each member chose to share."><b>${hb.name} · THE HUB</b><small>${hb.line}</small></div><span class="h-scan" aria-hidden="true"></span><span class="h-edge" aria-hidden="true"></span></div>
      <div class="panel hubside" title="How the hub reads"><h3><span>${this.ic("i-net")}READING THE HUB</span></h3><ul class="perm">
      <li title="The server is the hub">${this.ic("i-star")}<span>The faction's server is the hub. Its channels are docks on its ring.</span></li>
      <li title="A voice channel">${this.ic("i-star")}<span>A voice channel is the bridge, lit while people are in it. A stream or a watch party is the big screen.</span></li>
      <li title="Members">${this.ic("i-star")}<span>Members' stations orbit it. A lamp is lit when that post checked in. A new member is a new berth.</span></li>
      <li title="What nobody sees">${this.ic("i-noeye")}<span class="muted">Never names, addresses, apps or contents of anyone's lab. Read-only, off by default, no rankings.</span></li></ul>
      ${hb.sector?.length ? html`<h3 class="sec"><span>YOUR SECTOR</span></h3><div class="tags">${hb.sector.map((x) => html`<span class="chip ${x.here ? "lit" : ""}" title="${x.hint}">${x.name}</span>`)}</div>` : ""}</div></div>`;
  }
  private async mountHub() {
    const hb = this.data.hub, a = this.o.assets, wick = a.models.wick, host = this.q("hubscene");
    if (!hb || !host) return;
    this.hubKey = JSON.stringify(hb);
    if (!wick) { this.q("hubstage")?.classList.add("ready"); return; }
    const OR = 1.55, M = hb.members.slice(0, 8), D = hb.docks.slice(0, 6);
    const ang = (i: number, n: number, o = 0.35) => o + (i * 6.2832) / Math.max(1, n);
    const pos = (i: number): [number, number, number] => [Math.cos(ang(i, M.length)) * OR, 0, Math.sin(ang(i, M.length)) * OR];
    const src = join(a.base, wick.src);
    const pieces: PieceSpec[] = [{ id: "hub", src, info: wick.info, at: [0, 0, 0], size: 0.95, yaw: -0.3, gain: 0.7, tablePower: 0.2 },
      ...M.map((m, i): PieceSpec => ({ id: `m${i}`, src, info: wick.info, at: pos(i), size: 0.3, yaw: ang(i, M.length), tablePower: 0.15, gain: m.state === "out" ? 0.4 : 0.7, state: m.state === "new" ? "join" : m.state === "lit" ? "ok" : "off" }))];
    try {
      const v = await HoloView.create(host, { camera: { target: [0, 0.3, 0.1], dist: 5.2, pitch: 0.42, fov: 30 }, pieces, reduced: this.reduced, bloom: 0.6, fps: () => (this.reduced || !hb.op ? 0 : 12) });
      if (this.o.tab !== "hub" || this.dead) { v.dispose(); return; }
      this.hub = v;
      const da = (i: number) => ang(i, D.length, 1.2);
      v.lines((t) => {
        const out: Seg[] = [], ph = v.pal("--phosphor"), so = v.pal("--soft"), cy = v.pal("--cyan"), am = v.pal("--amber"), R = 0.78, Y = 0.32;
        const c4 = (c: number[], al: number) => [c[0], c[1], c[2], al], push = (p: number[], q: number[], c: number[]) => out.push({ a: p, b: q, ca: c, cb: c });
        for (let i = 0; i < 96; i++) { const a0 = (i / 96) * 6.2832, a1 = ((i + 1) / 96) * 6.2832; push([Math.cos(a0) * R, Y, Math.sin(a0) * R], [Math.cos(a1) * R, Y, Math.sin(a1) * R], c4(ph, 0.55)); }
        D.forEach((dk, i) => push([Math.cos(da(i)) * 0.22, Y, Math.sin(da(i)) * 0.22], [Math.cos(da(i)) * R, Y, Math.sin(da(i)) * R], c4(dk.lit ? so : ph, dk.lit ? 0.8 : 0.35)));
        for (let i = 0; i < 120; i += 2) { const a0 = (i / 120) * 6.2832, a1 = ((i + 1) / 120) * 6.2832; push([Math.cos(a0) * OR, 0.05, Math.sin(a0) * OR], [Math.cos(a1) * OR, 0.05, Math.sin(a1) * OR], c4(ph, 0.2)); }
        if (hb.op) {
          const s0 = [0.2, 0.4, 0.2], s1 = [2.6, 0.9, 1.4], at = (u: number) => s0.map((x, i) => x + (s1[i] - x) * u);
          for (let k = 0; k < 20; k += 2) push(at(k / 20), at((k + 1) / 20), c4(cy, 0.6));
          if (!this.reduced) { const f = Math.abs(((t * 0.12) % 2) - 1); push(at(f), at(Math.min(1, f + 0.03)), c4(so, 1.6)); }
        }
        if (hb.favour && M.length > 1) {
          const you = pos(Math.max(0, M.findIndex((m) => m.you))), other = pos(M.findIndex((m) => !m.you)), mid = [0, 0.6, 0];
          for (const [p, q] of [[[you[0], 0.1, you[2]], mid], [mid, [other[0], 0.1, other[2]]]]) for (let k = 0; k < 14; k += 2) push(p.map((x, i) => x + (q[i] - x) * (k / 14)), p.map((x, i) => x + (q[i] - x) * ((k + 1) / 14)), c4(am, 0.5));
        }
        return out;
      });
      const ov = this.q("hubov")!;
      setHtml(ov, M.map((m) => html`<span class="hlab pin ${m.state === "out" ? "out" : ""} ${m.you ? "you" : ""}" title="${m.hint}"><i></i>${m.name}</span>`)
        , D.map((dk) => html`<span class="hdock pin ${dk.lit ? "lit" : ""}" title="${dk.hint}">${dk.name}</span>`)
        , (hb.op ? html`<span class="hdock op pin" data-k="op" title="${hb.op.hint}">${hb.op.words}</span>` : ""), (hb.favour ? html`<span class="hdock fav pin" data-k="fav" title="${hb.favour.hint}">${hb.favour.words}</span>` : ""));
      const labs = [...ov.querySelectorAll<El>(".hlab")], docks = [...ov.querySelectorAll<El>(".hdock:not(.op):not(.fav)")];
      let sig = "";
      v.onFrame((s) => {
        const sg = `${s.el.clientWidth}|${s.cam.dist}`; if (sg === sig) return; sig = sg;
        M.forEach((_, i) => { const r = s.rect(`m${i}`); if (r) put(labs[i], r.bx, r.y + r.h + 4, "-50%", "0"); });
        D.forEach((_, i) => { const p = s.point([Math.cos(da(i)) * 0.78, 0.32, Math.sin(da(i)) * 0.78]); put(docks[i], p.x, p.y, "-50%", "-120%"); });
        const op = s.point([1.4, 0.68, 0.85]), fp = s.point([0, 0.62, 0]);
        put(this.q<El>("op"), op.x, op.y, "-50%", "-120%"); put(this.q<El>("fav"), fp.x, fp.y - 40, "-50%", "-120%");
      });
      const stage = this.q("hubstage")!, fitH = () => v.camera(stage.clientWidth < 600 ? { dist: 7.4, pitch: 0.7 } : { dist: 5.2, pitch: 0.42 });
      fitH(); this.hubRO = new ResizeObserver(() => { fitH(); sig = ""; }); this.hubRO.observe(stage);
      stage.classList.add("ready");
    } catch (e) { this.fail(e); }
  }
  private dropHub() {
    this.hubRO?.disconnect(); this.hubRO = null; this.hub?.dispose(); this.hub = null; this.built.hub = false; this.hubKey = "";
    const p = this.root.querySelector<El>('[data-p="hub"]'); if (p) setHtml(p, "");
  }

  // ---------------------------------------------------------------- events: all on the root, all removed on unmount
  private wire() {
    const r = this.root;
    const on = <K extends keyof HTMLElementEventMap>(t: EventTarget, e: K | string, f: (ev: Event) => void, o?: AddEventListenerOptions) => { t.addEventListener(e, f, o); this.off.push(() => t.removeEventListener(e, f, o)); };
    on(r, "click", (ev) => {
      const t = (ev.target as Element).closest<El>("[data-tab],[data-nav],[data-part],[data-c],[data-cmp],[data-f],[data-hubm],[data-k='mon'],[data-plan],[data-dot],[data-card],[data-show]");
      if (!t || !r.contains(t)) return;
      const d = t.dataset, s = this.scene;
      if (d.tab) return this.setTab(d.tab);
      if (d.nav) return this.nav(d.nav);
      if (d.part) return this.nav(s.parts.find((p) => p.id === d.part)?.route ?? null, { part: d.part });
      const cid = d.c ?? d.cmp;
      if (cid) { const c = s.compartments.find((q) => q.id === cid); return this.nav(c?.route ?? null, { compartment: cid, machine: c?.machine?.id }); }
      if (d.f) { this.visiting = this.visiting === d.f ? null : d.f; this.far(); this.asides(); this.view?.kick(); return; }
      if (d.hubm !== undefined) { this.setTab("hub"); this.root.querySelector('[data-p="hub"]')?.scrollIntoView({ behavior: this.reduced ? "auto" : "smooth", block: "center" }); return; }
      if (d.k === "mon") return this.nav("show");
      if (d.plan) {
        if (d.plan === "no") { this.planGone = JSON.stringify(this.data.plan); this.asides(); this.view?.kick(); }
        return this.o.onNavigate?.(d.plan === "approve" ? "activity" : d.plan === "change" ? "ask" : "home", { intent: d.plan, plan: this.data.plan?.title });
      }
      if (d.dot) { this.stop(); return this.show(Number(d.dot)); }
      if (d.card) { this.stop(); return this.show(Number(d.card)); }
      if (d.show === "prev") { this.stop(); return this.show(this.cur - 1); }
      if (d.show === "next") { this.stop(); return this.show(this.cur + 1); }
      if (d.show === "play") return this.playing ? this.stop() : this.play();
    });
    const hov = (ev: Event, onn: boolean) => {
      const t = ev.target as Element, c = t.closest?.<El>("[data-c],[data-cmp]");
      if (c) this.hot(c.dataset.c ?? c.dataset.cmp ?? "", onn);
      if (t.closest?.("[data-plan]")) r.classList.toggle("confirming", onn);   // STATIC steps away while you choose
    };
    on(r, "pointerover", (e) => hov(e, true)); on(r, "pointerout", (e) => hov(e, false));
    on(r, "focusin", (e) => hov(e, true)); on(r, "focusout", (e) => hov(e, false));
    let lastMove = 0;
    on(this.q("stage")!, "pointermove", () => { const n = performance.now(); if (n - lastMove > 500) { lastMove = n; if (n > this.turnUntil - 15_000) this.motion(); } });
    const ro = new ResizeObserver(() => { this.dust(); this.fit(); this.view?.kick(); });
    ro.observe(this.q("stage")!); this.off.push(() => ro.disconnect());
    on(matchMedia("(prefers-reduced-motion: reduce)"), "change", () => this.setReduced(!!this.o.reduced));
  }

  // ---------------------------------------------------------------- the host's handle
  update(input: LamplightData) {
    const data = sane(input), k = JSON.stringify(data);
    if (k === this.dataKey) return;
    this.dataKey = k; this.o.data = data;
    const sk = dataKey(data);
    if (sk === this.structKey) {   // only when it was read, or the words about it: the scene, the crew and the turn stay
      this.scene = buildScene(data, this.o.assets);
      this.head();
      return;
    }
    this.structKey = sk;
    this.render();
  }
  setReduced(on: boolean) { this.o.reduced = on; if (this.playing) this.stop(); this.render(); }
  setWorld(world: string | null) { if (world) this.root.dataset.world = world; else delete this.root.dataset.world; this.refresh(); }
  refresh() { this.dust(); this.view?.refresh(); this.hub?.refresh(); }
  unmount() {
    if (this.dead) return;
    this.dead = true; this.stop(); this.dropHub();
    for (const f of this.off) f();
    this.view?.dispose(); this.view = null;
    this.root.remove();
  }
}
