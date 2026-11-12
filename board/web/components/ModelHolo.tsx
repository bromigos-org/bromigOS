// A lab job's 3D model on the projection table: the GLB a generation made (Pixal3D, Hunyuan3D),
// read with three.js's own GLTFLoader and drawn by the shipped hologram renderer (lib/holo, the
// same as the station's machines): materialise, a slow turn on its table, drag to turn. Where the
// page can't draw (no WebGL), the model's name and a link to the file stand in its place.
"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ui";
import { putMesh, type HoloMesh } from "@/lib/holo/format";

const EDGE_TRIS_MAX = 300_000; // above this many triangles the feature edges are left out (they take seconds)

/** A GLB as the renderer's mesh: every mesh's triangles in world space, stood on the floor and
 *  centred, with its feature edges (30°) as the outline. */
export async function glbMesh(buf: ArrayBuffer): Promise<{ mesh: HoloMesh; height: number; radius: number }> {
  const THREE = await import("three");
  const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
  const gltf = await new GLTFLoader().parseAsync(buf, "");
  gltf.scene.updateMatrixWorld(true);
  const pos: number[] = [], nrm: number[] = [], tri: number[] = [], edges: number[] = [];
  const meshes: import("three").BufferGeometry[] = [];
  gltf.scene.traverse((o) => {
    const m = o as import("three").Mesh;
    if (m.isMesh && m.geometry?.attributes?.position) meshes.push(m.geometry.clone().applyMatrix4(m.matrixWorld));
  });
  let tris = 0;
  for (const g of meshes) tris += (g.index ? g.index.count : g.attributes.position.count) / 3;
  for (const g of meshes) {
    if (!g.attributes.normal) g.computeVertexNormals();
    const p = g.attributes.position, n = g.attributes.normal, base = pos.length / 3;
    for (let i = 0; i < p.count; i++) {
      pos.push(p.getX(i), p.getY(i), p.getZ(i));
      nrm.push(n.getX(i), n.getY(i), n.getZ(i));
    }
    if (g.index) for (let i = 0; i < g.index.count; i++) tri.push(base + g.index.getX(i));
    else for (let i = 0; i < p.count; i++) tri.push(base + i);
    if (tris <= EDGE_TRIS_MAX) {
      const e = new THREE.EdgesGeometry(g, 30).attributes.position, eb = pos.length / 3;
      for (let i = 0; i < e.count; i++) {
        pos.push(e.getX(i), e.getY(i), e.getZ(i));
        nrm.push(0, 1, 0);
      }
      for (let k = 0; k + 1 < e.count; k += 2) edges.push(eb + k, eb + k + 1);
    }
  }
  if (!tri.length) throw new Error("the model has no triangles");
  // stand it on the floor, centred over the table
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < pos.length; i += 3)
    for (let k = 0; k < 3; k++) {
      lo[k] = Math.min(lo[k], pos[i + k]);
      hi[k] = Math.max(hi[k], pos[i + k]);
    }
  const cx = (lo[0] + hi[0]) / 2, cz = (lo[2] + hi[2]) / 2;
  let radius = 0;
  for (let i = 0; i < pos.length; i += 3) {
    pos[i] -= cx;
    pos[i + 1] -= lo[1];
    pos[i + 2] -= cz;
    radius = Math.max(radius, Math.hypot(pos[i], pos[i + 2]));
  }
  const V = pos.length / 3, IA = V > 65535 ? Uint32Array : Uint16Array;
  return {
    mesh: { pos: new Float32Array(pos), nrm: new Float32Array(nrm), part: new Float32Array(V), tri: new IA(tri), edge: new IA(edges), nparts: 1 },
    height: Math.max(1e-3, hi[1] - lo[1]),
    radius: Math.max(radius, 1e-3),
  };
}

type Look = "loading" | "ready" | "flat";

export function ModelHolo({ url, name, hint }: { url: string; name: string; hint: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [look, setLook] = useState<Look>("loading");
  useEffect(() => {
    let dead = false;
    let view: { dispose(): void } | null = null;
    (async () => {
      try {
        const buf = await (await fetch(url, { credentials: "same-origin" })).arrayBuffer();
        const { mesh, height, radius } = await glbMesh(buf);
        if (dead) return;
        const key = `lab:${url}`;
        putMesh(key, mesh);
        const { HoloView } = await import("@/lib/holo/view");
        const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
        const v = await HoloView.create(host.current!, {
          camera: { target: [0, 0.42, 0], dist: 3.0, pitch: 0.22, fov: 30 },
          pieces: [{ id: "m", src: key, info: { name, height, radius, parts: [] }, at: [0, 0, 0], size: 0.9, spin: reduced ? 0 : 0.3, tablePower: 0.3, state: "ok" }],
          reduced,
          bloom: 0.8,
        });
        if (dead) return v.dispose();
        view = v;
        setLook("ready");
      } catch {
        if (!dead) setLook("flat");
      }
    })();
    return () => {
      dead = true;
      view?.dispose();
    };
  }, [url, name]);
  return (
    <div className={`lab-holo ${look}`} title={hint}>
      <div ref={host} className="lab-holo-gl" aria-hidden="true" />
      {look !== "ready" && (
        <span className="lab-holo-flat">
          <Icon id="i-models" size={40} className={look === "loading" ? "pulse" : ""} />
          <span className="small">{look === "loading" ? "Putting it on the table…" : "This browser can't draw it here: open the file instead."}</span>
        </span>
      )}
    </div>
  );
}
