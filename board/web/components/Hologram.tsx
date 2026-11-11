// A machine's hologram on its emitter: the bromigos.org renderer (lib/holo/, three.js), through
// Lamplight's shared view (lib/holo/view.ts: one WebGL context for the page, drawing only when
// something moves), with a licence-clear model from /holo/ (the rack, the workstation). It loads
// only when a page shows one, turns for 20 seconds and then settles (a calm scene draws
// nothing), holds still under reduced motion and on a software renderer, and leaves the
// sprite's glyph in place when WebGL isn't there.
//
// Only machine kinds with a cleared model get one. The storage, node, router, battery, phone and
// dish meshes were made with Pixal3D, whose DINOv3 licence isn't cleared, so those kinds keep
// their kind's glyph until it is (docs/ASSETS.md).
import { useEffect, useRef, useState } from "react";
import type { MachineKind, Shape } from "@/lib/api/types";

const MODEL: Partial<Record<MachineKind, string>> = { server: "rack", desktop: "workstation" };
const GLYPH: Record<MachineKind, string> = { server: "g-rack", node: "g-rack", storage: "g-drive", desktop: "g-tower", other: "g-rack" };

const reducedNow = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function Hologram({ kind, state, label }: { kind: MachineKind; state: Shape; label: string }) {
  const el = useRef<HTMLDivElement>(null);
  const [drawn, setDrawn] = useState(false);
  const model = MODEL[kind];
  useEffect(() => {
    if (!model || !el.current) return;
    let view: { dispose(): void; set(id: string, p: { spin: number }): void; refresh(): void } | null = null;
    let gone = false, settle = 0;
    const world = new MutationObserver(() => view?.refresh()); // new tokens: recolour once
    (async () => {
      try {
        const [{ HoloView }, info] = await Promise.all([import("@/lib/holo/view"), fetch(`/holo/${model}.json`).then((r) => r.json())]);
        if (gone || !el.current) return;
        const v = await HoloView.create(el.current, {
          camera: { target: [0, 0.5, 0], dist: 2.6, pitch: 0.18, fov: 30 },
          reduced: reducedNow(),
          bloom: 0.9,
          pieces: [{ id: model, src: `/holo/${model}.bin`, info, at: [0, 0, 0], size: 1, spin: 0.25, state: state === "ok" ? "ok" : state === "unknown" ? "off" : "warn" }],
        });
        if (gone) return v.dispose();
        view = v;
        setDrawn(true);
        settle = window.setTimeout(() => v.set(model, { spin: 0 }), 20_000);
        world.observe(document.documentElement, { attributes: true, attributeFilter: ["data-world"] });
      } catch {
        setDrawn(false); // no WebGL, or the model didn't load: the glyph stays
      }
    })();
    return () => {
      gone = true;
      clearTimeout(settle);
      world.disconnect();
      view?.dispose();
    };
  }, [model, state]);
  return (
    <div className={`holo-mount${drawn ? " drawn" : ""}`} ref={el} role="img" aria-label={label}>
      {!drawn && (
        <svg className={`gl${state === "unknown" ? "" : state === "ok" ? " live" : " warn"}`} viewBox="0 0 100 100" aria-hidden="true" focusable="false">
          <use href={`#${GLYPH[kind]}`} />
        </svg>
      )}
    </div>
  );
}
