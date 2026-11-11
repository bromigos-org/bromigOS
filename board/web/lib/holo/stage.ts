// A model on the projection table: the desktop gallery's Stage (vector holo/stage.py)
// without the live readings: materialise, slow turn, drag to turn, explode, isolate a
// part, the scan sweep, hover lighting and picking.
import * as THREE from "three";
import type { HoloMesh, HoloModelInfo } from "./format";
import { GpuModel, HoloEngine, M, approach, ease, type Rgb } from "./engine";

const V = new THREE.Vector4();

export class ModelStage {
  gm: GpuModel;
  info: HoloModelInfo;
  mesh: HoloMesh;
  n: number;
  yaw = -0.55;
  pitch = 0.16;
  spin = 0.1; // rad/s while idle
  explode = 0;
  explodeTo = 0;
  iso: number | null = null;
  isoAmt: number[];
  hover: number | null = null;
  dragging = false;
  born: number;
  scanT0: number;
  scanDur = 2.4;
  fade = 0;
  fadeTo = 1;
  size = 0.95;
  mm = new THREE.Matrix4();
  centroid: THREE.Vector3[];
  private s = 1;

  constructor(
    private engine: HoloEngine,
    info: HoloModelInfo,
    mesh: HoloMesh,
    t: number,
    private reduced: boolean,
  ) {
    this.info = info;
    this.mesh = mesh;
    this.n = Math.max(1, Math.min(info.parts.length || mesh.nparts, 24));
    this.isoAmt = new Array(this.n).fill(0);
    this.born = reduced ? t - 30 : t;
    this.scanT0 = reduced ? t - 30 : t;
    this.fade = reduced ? 1 : 0;
    this.gm = new GpuModel(mesh, engine.px);
    engine.modelScene.add(this.gm.group);
    // part centroids (the tip of an exploded part turns about its own centre)
    const sum = Array.from({ length: this.n }, () => new THREE.Vector3());
    const cnt = new Array(this.n).fill(0);
    for (let i = 0; i < mesh.part.length; i++) {
      const p = Math.min(mesh.part[i], this.n - 1);
      sum[p].x += mesh.pos[i * 3];
      sum[p].y += mesh.pos[i * 3 + 1];
      sum[p].z += mesh.pos[i * 3 + 2];
      cnt[p]++;
    }
    this.centroid = sum.map((v, i) => v.multiplyScalar(1 / Math.max(cnt[i], 1)));
  }

  dispose() {
    this.engine.modelScene.remove(this.gm.group);
    this.gm.dispose();
  }

  scan(t: number) {
    this.scanT0 = t;
  }

  busy(t: number) {
    return (
      this.dragging ||
      Math.abs(this.explode - this.explodeTo) > 0.002 ||
      Math.abs(this.fade - this.fadeTo) > 0.002 ||
      this.isoAmt.some((a, i) => Math.abs(a - (this.iso === i ? 1 : 0)) > 0.002) ||
      t - this.born < 2
    );
  }

  update(dt: number) {
    if (!this.dragging && this.iso === null && !this.reduced) this.yaw += this.spin * dt;
    this.explode = approach(this.explode, this.explodeTo, dt, 5);
    for (let i = 0; i < this.n; i++) {
      const tgt = this.iso === i ? 1 : 0;
      this.isoAmt[i] = tgt + (this.isoAmt[i] - tgt) * Math.exp(-7 * dt);
    }
    this.fade = approach(this.fade, this.fadeTo, dt, 4);
  }

  /** The camera: the gallery's framing, pulled back to fit the element's aspect. */
  camera(aspect: number) {
    const tan = Math.tan((30 * Math.PI) / 360);
    const d = Math.max(2.35, 0.86 / (tan * aspect));
    const tgt = [0, 0.48, 0];
    const eye = [tgt[0], tgt[1] + d * Math.sin(this.pitch), tgt[2] + d * Math.cos(this.pitch)];
    this.engine.lookAt(eye, tgt, 30);
  }

  frame(t: number, colour: Rgb) {
    const info = this.info;
    const h = info.height || 1;
    const s = this.size / Math.max(h, 1.6 * (info.radius || 0.5), 0.6);
    this.s = s;
    const lift = this.reduced ? 0.06 : 0.06 + 0.012 * Math.sin(t * 0.8);
    M.into(this.mm, M.T(0, lift, 0), M.Ry(this.yaw), M.S(s));
    this.gm.setMatrix(this.mm);
    // the table
    const r = Math.max((info.radius || 0.5) * s * 1.15, 0.32 * this.size);
    const tt = this.reduced ? 0 : t;
    this.engine.table.update(M.Ry(-tt * 0.05), tt, r, r * 1.12, h * s * 1.05, this.fade, colour);
    // parts
    const u = this.gm.u;
    const age = t - this.born;
    const anyIso = Math.max(...this.isoAmt);
    for (let i = 0; i < this.n; i++) {
      const p = info.parts[i];
      const arrive = ease((age - 0.08 * i) / 0.9);
      let e = this.explode * (0.7 + 0.3 * ease(this.explode * 1.4 - i * 0.04)) + (1 - arrive) * 1.6;
      e += 0.45 * this.isoAmt[i];
      const ex = p ? p.explode : [0, 0, 0];
      const m = u.pmat.value[i];
      m.makeTranslation(ex[0] * e, ex[1] * e, ex[2] * e);
      if (this.explode > 0.01) {
        const c = this.centroid[i];
        const tip = 0.06 * this.explode * (i % 2 ? 1 : -1);
        m.multiply(M.T(c.x, c.y, c.z)).multiply(M.Rx(tip * 0.4)).multiply(M.Rz(tip)).multiply(M.T(-c.x, -c.y, -c.z));
      }
      let k = (0.5 + 0.75 * 0.6) * (this.reduced ? 0.97 : 0.94 + 0.06 * Math.sin(t * 9 + i * 1.7));
      if (this.hover === i) k *= 1.35;
      const alpha = arrive * this.fade * (1 - 0.86 * anyIso * (1 - this.isoAmt[i]));
      u.pcol.value[i].set(colour[0] * k, colour[1] * k, colour[2] * k, alpha);
      u.pw.value[i] = 1 + 0.7 * this.isoAmt[i] + (this.hover === i ? 0.35 : 0);
    }
    // the scan sweep
    const x = (t - this.scanT0) / this.scanDur;
    if (this.reduced || x > 1.15) u.scan.value.set(0, 0.02, 0, 0);
    else u.scan.value.set(-0.05 + x * (h + 0.1), 0.006 + 0.006 * h, 0.9 * (1 - Math.max(0, x - 1) / 0.15), 0);
    this.gm.params({ fill: 0.55, width: 1.3, slices: 48, ghost: 0.12 }, this.engine.dpr);
  }

  /** Where each part's callout anchor lands, in CSS pixels. */
  anchors(out: THREE.Vector2[]) {
    const pm = this.gm.u.pmat.value;
    const w = new THREE.Vector3();
    for (let i = 0; i < this.n; i++) {
      const a = this.info.parts[i]?.anchor ?? [0, 0, 0];
      w.set(a[0], a[1], a[2]).applyMatrix4(pm[i]).applyMatrix4(this.mm);
      out[i] = out[i] ?? new THREE.Vector2();
      this.engine.project(w, out[i]);
    }
    return out;
  }

  /** The part under (x, y) in CSS pixels, or null: the desktop's triangle test. */
  pick(x: number, y: number): number | null {
    const eng = this.engine;
    const cam = eng.camera;
    const vp = new THREE.Matrix4().multiplyMatrices(cam.projectionMatrix, cam.matrixWorldInverse);
    const pm = this.gm.u.pmat.value;
    const per = Array.from({ length: this.n }, (_, i) => new THREE.Matrix4().multiplyMatrices(vp, this.mm).multiply(pm[i]).elements);
    const { pos, part, tri } = this.mesh;
    const nv = part.length;
    const sx = new Float32Array(nv);
    const sy = new Float32Array(nv);
    const sz = new Float32Array(nv);
    const W = eng.width;
    const H = eng.height;
    for (let i = 0; i < nv; i++) {
      const e = per[Math.min(part[i], this.n - 1)];
      const px = pos[i * 3];
      const py = pos[i * 3 + 1];
      const pz = pos[i * 3 + 2];
      V.set(
        e[0] * px + e[4] * py + e[8] * pz + e[12],
        e[1] * px + e[5] * py + e[9] * pz + e[13],
        e[2] * px + e[6] * py + e[10] * pz + e[14],
        e[3] * px + e[7] * py + e[11] * pz + e[15],
      );
      const w = Math.abs(V.w) < 1e-6 ? 1e-6 : V.w;
      sx[i] = (V.x / w * 0.5 + 0.5) * W;
      sy[i] = (1 - (V.y / w * 0.5 + 0.5)) * H;
      sz[i] = V.z / w;
    }
    let best = Infinity;
    let hit: number | null = null;
    for (let t = 0; t < tri.length; t += 3) {
      const a = tri[t];
      const b = tri[t + 1];
      const c = tri[t + 2];
      const v0x = sx[b] - sx[a];
      const v0y = sy[b] - sy[a];
      const v1x = sx[c] - sx[a];
      const v1y = sy[c] - sy[a];
      const den = v0x * v1y - v1x * v0y;
      if (Math.abs(den) < 1e-6) continue;
      const v2x = x - sx[a];
      const v2y = y - sy[a];
      const u = (v2x * v1y - v1x * v2y) / den;
      if (u < 0) continue;
      const v = (v0x * v2y - v2x * v0y) / den;
      if (v < 0 || u + v > 1) continue;
      const pa = Math.min(part[a], this.n - 1);
      if (this.iso !== null && pa !== this.iso) continue;
      const d = (sz[a] + sz[b] + sz[c]) / 3;
      if (d < best) {
        best = d;
        hit = pa;
      }
    }
    return hit;
  }

  scale() {
    return this.s;
  }
}
