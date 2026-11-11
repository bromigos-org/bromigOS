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

export const esc = (s: unknown): string =>
  String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** A hidden <svg> of icons and a root for one mount, appended to the host. */
export function createRoot(host: HTMLElement, world: string | null | undefined): { root: HTMLElement; prefix: string } {
  const prefix = `lp${++uid}-`;
  const root = document.createElement("div");
  root.className = "lp";
  if (world) root.dataset.world = world;
  root.innerHTML = `<svg class="lp-defs" width="0" height="0" aria-hidden="true" focusable="false"><defs>${symbolDefs(prefix)}</defs></svg>`;
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

export const icon = (prefix: string, id: string, cls = "s16"): string =>
  `<svg class="i ${cls}" aria-hidden="true" focusable="false"><use href="#${prefix}${id}"/></svg>`;

export const stateWord = (prefix: string, state: LampState | "dim", word: string): string =>
  `<span class="st ${SHAPE[state][1]}">${icon(prefix, SHAPE[state][0])}${esc(word)}</span>`;

/** How a machine's state tints its hologram. */
export function viewState(state: LampState, quiet: boolean): ViewState {
  if (quiet) return "dim";
  return state === "warn" ? "warn" : state === "down" ? "down" : state === "unknown" ? "off" : state === "setup" ? "join" : "ok";
}

/** A machine kind's icon: drawn on its deck tray when there is no hologram for it. */
export const KIND_ICON: Record<LampKind, string> = {
  server: "i-rack", storage: "i-storage", node: "i-node", desktop: "i-desktop", router: "i-router", ups: "i-power", other: "i-box",
};
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
export function tubes(s: string, small = false): string {
  return `<span class="tubes${small ? " sm" : ""}">${[...s].map((c) => (/[:\-]/.test(c) ? `<span class="tube sep"><b>${c}</b></span>` : `<span class="tube"><b>${esc(c)}</b></span>`)).join("")}</span>`;
}
