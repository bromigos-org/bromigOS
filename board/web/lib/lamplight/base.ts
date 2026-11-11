// What every Lamplight mount shares: its root element, its icons, the state shapes, and the rule
// that nothing it writes breaks `Content-Security-Policy: default-src 'self'`.
//
// The module never injects a <style> element and never writes a style="…" attribute: the host
// links lamplight.css, markup built here carries classes only, and everything that must be set
// from script (a position, a size, a colour) goes through the CSSOM (`el.style.setProperty`),
// which the policy allows. Markup that needs a few static declarations names them in `data-css`
// and applyCss() sets them the same way.
import type { State as ViewState } from "../holo/view";
import { symbolDefs } from "./symbols";
import type { LampKind, LampState, LamplightAssets } from "./types";

let uid = 0;

// ---------------------------------------------------------------- markup, and what may enter it
//
// Every string the station is handed is untrusted text: on the Lab board a name, a word, a hint or
// a detail is some command's output. So markup is only ever made by html`…`, which escapes every
// value put into it, and reaches the page only through setHtml()/addHtml(). A value passes
// unescaped only if it is itself a piece html`…` made (`Safe`); no function marks a string as safe.
// Nothing else in the module writes innerHTML, and the only other `Safe` is the icons' own constant
// (symbols.ts); the hostile-data test holds both.

const ESC: Record<string, string> = { "&": "&amp;", '"': "&quot;", "'": "&#39;", "<": "&lt;", ">": "&gt;" };
/** Text, safe between tags and inside a quoted attribute. */
export const esc = (s: unknown): string => String(s ?? "").replace(/[&"'<>]/g, (c) => ESC[c]);

/** A piece of markup the module made itself with html`…`. */
export class Safe {
  constructor(readonly s: string) {}
  toString(): string { return this.s; }
}
/** What html`…` and setHtml() take: pieces pass as they are, lists are joined, anything else is text. */
export type Part = Safe | string | number | boolean | null | undefined | Part[];
const part = (v: unknown): string =>
  v instanceof Safe ? v.s : Array.isArray(v) ? v.map(part).join("") : v == null || v === false || v === true ? "" : esc(v);

/** Markup with every value escaped where it lands: html`<b title="${hint}">${name}</b>`. */
export function html(strings: TemplateStringsArray, ...values: unknown[]): Safe {
  let out = strings[0];
  for (let i = 0; i < values.length; i++) out += part(values[i]) + strings[i + 1];
  return new Safe(out);
}
export function setHtml(el: Element, ...parts: Part[]): void { el.innerHTML = part(parts); }
export function addHtml(el: Element, ...parts: Part[]): void { el.insertAdjacentHTML("beforeend", part(parts)); }

/** A value from data that picks a class or a shape: one of the allowed words, or the fallback. Never the data's own word. */
export const oneOf = <const T extends string>(v: unknown, allowed: readonly T[], fallback: NoInfer<T>): T =>
  (allowed as readonly unknown[]).includes(v) ? (v as T) : fallback;
/** A number from data, for a size or a position: finite, or the fallback. */
export const num = (v: unknown, fallback = 0): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);

/** A hidden <svg> of icons and a root for one mount, appended to the host. */
export function createRoot(host: HTMLElement, world: string | null | undefined): { root: HTMLElement; prefix: string } {
  const prefix = `lp${++uid}-`;
  const root = document.createElement("div");
  root.className = "lp";
  if (world) root.dataset.world = world;
  setHtml(root, html`<svg class="lp-defs" width="0" height="0" aria-hidden="true" focusable="false"><defs>${symbolDefs(prefix)}</defs></svg>`);
  host.appendChild(root);
  return { root, prefix };
}

/** Set the declarations named in `data-css="left:5%;top:44%"` through the CSSOM. */
export function applyCss(scope: ParentNode): void {
  scope.querySelectorAll<HTMLElement | SVGElement>("[data-css]").forEach((el) => {
    for (const d of (el.getAttribute("data-css") ?? "").split(";")) {
      const i = d.indexOf(":");
      if (i > 0) el.style.setProperty(d.slice(0, i).trim(), d.slice(i + 1).trim());
    }
    el.removeAttribute("data-css");
  });
}

/** Move a placed element: one transform, from the element's own (0, 0). */
export function put(el: HTMLElement | SVGElement | null | undefined, x: number, y: number, ax = "-50%", ay = "-100%"): void {
  if (el) el.style.setProperty("transform", `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) translate(${ax},${ay})`);
}

/** A state's shape and its class: lit dot, broken diamond, crossed square, dotted ring, half ring. */
const SHAPE: Record<LampState | "dim", [string, string]> = {
  ok: ["s-ok", "ok"], warn: ["s-warn", "warn"], down: ["s-down", "down"], unknown: ["s-unk", "unk"],
  setup: ["s-start", "busy"], busy: ["s-start", "busy"], dim: ["s-wait", "unk"],
};
/** A state's class, by lookup: a word that isn't a state is drawn as unknown, never as a class of its own. */
export const stateClass = (state: unknown): string => (SHAPE[state as LampState] ?? SHAPE.unknown)[1];

/** An icon by its id in symbols.ts. The id and the class are the module's own words, never data. */
export const icon = (prefix: string, id: string, cls = "s16"): Safe =>
  html`<svg class="i ${cls}" aria-hidden="true" focusable="false"><use href="#${prefix}${id}"/></svg>`;

export const stateWord = (prefix: string, state: LampState | "dim", word: string): Safe =>
  html`<span class="st ${stateClass(state)}">${icon(prefix, (SHAPE[state] ?? SHAPE.unknown)[0])}${word}</span>`;

/** How a machine's state tints its hologram. */
export function viewState(state: LampState, quiet: boolean): ViewState {
  if (quiet) return "dim";
  return state === "warn" ? "warn" : state === "down" ? "down" : state === "unknown" ? "off" : state === "setup" ? "join" : "ok";
}

/** A machine kind's icon: drawn on its deck tray when there is no hologram for it. */
export const KIND_ICON: Record<LampKind, string> = {
  server: "i-rack", storage: "i-storage", node: "i-node", desktop: "i-desktop", router: "i-router", ups: "i-power", other: "i-box",
};
/** A kind's icon, by lookup: a kind that isn't one gets the plain box. */
export const kindIcon = (kind: unknown): string => KIND_ICON[kind as LampKind] ?? "i-box";
/** The class an icon on a deck tray wears for its state: the state's own word when it is one, else "unknown". */
export const kicoClass = (state: unknown): string => oneOf(state, ["ok", "warn", "down", "unknown", "setup", "busy", "dim"], "unknown");
export const KIND_WORD: Record<LampKind, string> = {
  server: "a server", storage: "a storage server", node: "a small server", desktop: "a bromigOS desktop", router: "the router", ups: "a battery backup", other: "a machine",
};

/** A named file from the manifest, or null: nothing that isn't in the manifest is ever asked for. */
export function artUrl(assets: LamplightAssets, name: string): string | null {
  const v = assets.art?.[name];
  return v ? join(assets.base, v) : null;
}
export function join(base: string | undefined, src: string): string {
  if (!base || /^(?:[a-z]+:)?\//i.test(src)) return src;
  return base.replace(/\/?$/, "/") + src;
}

/** The model a kind is drawn with, or null when the manifest has none (its icon is drawn instead). */
export function modelFor(assets: LamplightAssets, kind: LampKind): string | null {
  const name = assets.kinds[kind];
  return name && assets.models[name] ? name : null;
}

export const reducedNow = (asked: boolean | undefined): boolean =>
  !!asked || (typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches);

export const isPhone = (): boolean =>
  typeof matchMedia === "function" && (matchMedia("(pointer: coarse)").matches || Math.min(screen.width, innerWidth) < 700);

/** Lit digits in tubes: the station's readouts. */
export function tubes(s: string, small = false): Safe {
  return html`<span class="tubes${small ? " sm" : ""}">${[...String(s)].map((c) => (/[:\-]/.test(c) ? html`<span class="tube sep"><b>${c}</b></span>` : html`<span class="tube"><b>${c}</b></span>`))}</span>`;
}
