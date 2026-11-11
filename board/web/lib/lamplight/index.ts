// LAMPLIGHT: the lab as a living station, for a page to host.
//
//   import "…/lamplight.css";                      // the host links the stylesheet (scoped under .lp)
//   const home = mount(el, { data, assets, onNavigate, onError });
//   home.update(data);                             // new data: no remount, no model reloaded
//   const hero = mountMachine(el, { machine: "myserver", data, assets });
//   const rack = mountRack(el, { kind: "server", state: "ok", assets });
//   home.unmount();                                // or unmount(el)
//
// The station is drawn only from `LamplightData` (types.ts). It works under
// `Content-Security-Policy: default-src 'self'`: no injected <style>, no style attributes, no
// inline handlers, no data: URLs. Every mount lives under one root (.lp, ids prefixed per mount),
// sets nothing page-level, and removes every listener it added outside its root on unmount. All
// mounts on a page share one WebGL context, and a still scene draws nothing.
import { Home } from "./home";
import { Machine, Rack } from "./machine";
import type { LamplightHandle, LamplightOptions, MachineHandle, MachineOptions, RackHandle, RackOptions } from "./types";

type Mounted = { unmount(): void };
const live = new WeakMap<Element, Mounted>();
function take<T extends Mounted>(el: HTMLElement, make: () => T): T {
  live.get(el)?.unmount();
  const h = make();
  live.set(el, h);
  return h;
}

/** Home's hero: the whole station. */
export function mount(el: HTMLElement, options: LamplightOptions): LamplightHandle { return take(el, () => new Home(el, options)); }
/** A machine's page hero: its deck tray pulled out of the station. */
export function mountMachine(el: HTMLElement, options: MachineOptions): MachineHandle { return take(el, () => new Machine(el, options)); }
/** One machine's hologram on its emitter, with no station. */
export function mountRack(el: HTMLElement, options: RackOptions): RackHandle { return take(el, () => new Rack(el, options)); }
export function unmount(el: HTMLElement): void { live.get(el)?.unmount(); live.delete(el); }

export { fromBoard } from "./from-board";
export const version = "lamplight/2";
export type * from "./types";
