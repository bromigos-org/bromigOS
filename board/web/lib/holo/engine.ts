// The hologram renderer on the web: the projection table, part-indexed models drawn as
// the desktop draws them (depth prepass, fresnel shell with slices and the scan band, fat
// feature edges bright in front and ghosted behind), free lines, bloom and the soft
// tone-mapped composite. A port of vector's holo/render.py; geometry never changes after
// upload, all motion is uniforms.
import * as THREE from "three";
import type { HoloMesh } from "./format";
import {
  BLUR_FS,
  COMP_FS,
  CONE_FS,
  CONE_VS,
  DEPTH_FS,
  DISC_FS,
  DISC_VS,
  DOWN_FS,
  FILL_FS,
  FILL_VS,
  LINE_FS,
  LINE_VS,
  MAXP,
  POST_VS,
} from "./shaders";

export type Rgb = [number, number, number];

/** A #rrggbb colour in linear light (the scene is linear HDR), as the desktop's lin(). */
export function hexLin(hex: string, k = 1): Rgb {
  const h = hex.replace("#", "");
  const v = (i: number) => Math.pow(parseInt(h.slice(i, i + 2), 16) / 255, 2.2) * k;
  return [v(0), v(2), v(4)];
}

/** The page's colour for a CSS variable on an element, as #rrggbb, or null. */
export function cssHex(el: Element | null, name: string): string | null {
  if (!el) return null;
  const v = getComputedStyle(el).getPropertyValue(name).trim();
  if (/^#[0-9a-f]{6}$/i.test(v)) return v;
  if (/^#[0-9a-f]{3}$/i.test(v)) return `#${v[1]}${v[1]}${v[2]}${v[2]}${v[3]}${v[3]}`;
  const m = v.match(/^rgba?\((\d+)[ ,]+(\d+)[ ,]+(\d+)/);
  if (m) return `#${[m[1], m[2], m[3]].map((x) => Number(x).toString(16).padStart(2, "0")).join("")}`;
  return null;
}

const ADD = {
  transparent: true,
  depthWrite: false,
  blending: THREE.CustomBlending,
  blendEquation: THREE.AddEquation,
  blendSrc: THREE.OneFactor,
  blendDst: THREE.OneFactor,
  blendSrcAlpha: THREE.OneFactor,
  blendDstAlpha: THREE.OneFactor,
} as const;

function quadLines(): THREE.InstancedBufferGeometry {
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute([0, -1, 0, 0, 1, 0, 1, -1, 0, 1, 1, 0], 3));
  g.setIndex([0, 2, 1, 2, 3, 1]);
  return g;
}

/** Per-part state shared by a model's four passes: matrices, colours, line widths. */
export class PartUniforms {
  pmat = { value: Array.from({ length: MAXP }, () => new THREE.Matrix4()) };
  pcol = { value: Array.from({ length: MAXP }, () => new THREE.Vector4(0, 0, 0, 0)) };
  pw = { value: new Array<number>(MAXP).fill(1) };
  scan = { value: new THREE.Vector4(0, 0.02, 0, 0) };
}

export type DrawParams = { fill: number; width: number; slices: number; ghost: number };

/** A part-indexed mesh on the GPU, in its own group (whose matrix is the model matrix). */
export class GpuModel {
  group = new THREE.Group();
  u = new PartUniforms();
  private mats: THREE.ShaderMaterial[] = [];
  private geoms: THREE.BufferGeometry[] = [];
  private fill: THREE.ShaderMaterial;
  private edges: THREE.ShaderMaterial;
  private ghostMat: THREE.ShaderMaterial;
  readonly mesh: HoloMesh;

  constructor(mesh: HoloMesh, px: { value: THREE.Vector2 }) {
    this.mesh = mesh;
    this.group.matrixAutoUpdate = false;
    const surf = new THREE.BufferGeometry();
    surf.setAttribute("position", new THREE.BufferAttribute(mesh.pos, 3));
    surf.setAttribute("normal", new THREE.BufferAttribute(mesh.nrm, 3));
    surf.setAttribute("aPart", new THREE.BufferAttribute(mesh.part, 1));
    surf.setIndex(new THREE.BufferAttribute(mesh.tri, 1));
    const E = mesh.edge.length / 2;
    const a = new Float32Array(E * 3);
    const b = new Float32Array(E * 3);
    const ep = new Float32Array(E);
    for (let i = 0; i < E; i++) {
      const i0 = mesh.edge[i * 2];
      const i1 = mesh.edge[i * 2 + 1];
      for (let k = 0; k < 3; k++) {
        a[i * 3 + k] = mesh.pos[i0 * 3 + k];
        b[i * 3 + k] = mesh.pos[i1 * 3 + k];
      }
      ep[i] = mesh.part[i0];
    }
    const lines = quadLines();
    lines.setAttribute("aA", new THREE.InstancedBufferAttribute(a, 3));
    lines.setAttribute("aB", new THREE.InstancedBufferAttribute(b, 3));
    lines.setAttribute("aPart", new THREE.InstancedBufferAttribute(ep, 1));
    lines.instanceCount = E;
    this.geoms.push(surf, lines);
    const u = this.u;
    const partU = { uPmat: u.pmat, uPcol: u.pcol };
    // 1. depth prepass (pushed back so edges on the surface win)
    const depth = new THREE.ShaderMaterial({
      vertexShader: FILL_VS,
      fragmentShader: DEPTH_FS,
      uniforms: { ...partU },
      colorWrite: false,
      depthWrite: true,
      depthFunc: THREE.LessDepth,
      polygonOffset: true,
      polygonOffsetFactor: 1.5,
      polygonOffsetUnits: 2.0,
      side: THREE.DoubleSide,
    });
    // 2. the shell, front-most surface only
    this.fill = new THREE.ShaderMaterial({
      vertexShader: FILL_VS,
      fragmentShader: FILL_FS,
      uniforms: { ...partU, uScan: u.scan, uFill: { value: 0.55 }, uSlices: { value: 48 } },
      ...ADD,
      depthTest: true,
      depthFunc: THREE.LessEqualDepth,
      polygonOffset: true,
      polygonOffsetFactor: 1.5,
      polygonOffsetUnits: 2.0,
      side: THREE.DoubleSide,
    });
    // 3. edges: visible, then hidden ones ghosted
    const lineU = { ...partU, uPw: u.pw, uPx: px, uScan: u.scan };
    this.edges = new THREE.ShaderMaterial({
      vertexShader: LINE_VS,
      fragmentShader: LINE_FS,
      uniforms: { ...lineU, uWidth: { value: 1.3 }, uGain: { value: 1.0 } },
      ...ADD,
      depthTest: true,
      depthFunc: THREE.LessEqualDepth,
    });
    this.ghostMat = new THREE.ShaderMaterial({
      vertexShader: LINE_VS,
      fragmentShader: LINE_FS,
      uniforms: { ...lineU, uWidth: this.edges.uniforms.uWidth, uGain: { value: 0.12 } },
      ...ADD,
      depthTest: true,
      depthFunc: THREE.GreaterDepth,
    });
    this.mats.push(depth, this.fill, this.edges, this.ghostMat);
    const parts: [THREE.BufferGeometry, THREE.ShaderMaterial, number][] = [
      [surf, depth, 0],
      [surf, this.fill, 1],
      [lines, this.edges, 2],
      [lines, this.ghostMat, 3],
    ];
    for (const [g, m, order] of parts) {
      const o = new THREE.Mesh(g, m);
      o.frustumCulled = false;
      o.renderOrder = order;
      this.group.add(o);
    }
  }

  params(p: DrawParams, dpr: number) {
    this.fill.uniforms.uFill.value = p.fill;
    this.fill.uniforms.uSlices.value = p.slices;
    this.edges.uniforms.uWidth.value = p.width * dpr;
    this.ghostMat.uniforms.uGain.value = p.ghost;
  }

  setMatrix(m: THREE.Matrix4) {
    this.group.matrix.copy(m);
    this.group.matrixWorldNeedsUpdate = true;
  }

  dispose() {
    this.geoms.forEach((g) => g.dispose());
    this.mats.forEach((m) => m.dispose());
  }
}

/** Free 3D segments with a colour at each end (linear rgb + alpha): beams, stubs. */
export class FreeLines {
  object: THREE.Mesh;
  private geom: THREE.InstancedBufferGeometry;
  private mat: THREE.ShaderMaterial;
  private a: THREE.InstancedBufferAttribute;
  private b: THREE.InstancedBufferAttribute;
  private ca: THREE.InstancedBufferAttribute;
  private cb: THREE.InstancedBufferAttribute;

  constructor(max: number, px: { value: THREE.Vector2 }, depthFade?: { center: { value: number }; radius: { value: number } }) {
    this.geom = quadLines();
    this.a = new THREE.InstancedBufferAttribute(new Float32Array(max * 3), 3);
    this.b = new THREE.InstancedBufferAttribute(new Float32Array(max * 3), 3);
    this.ca = new THREE.InstancedBufferAttribute(new Float32Array(max * 4), 4);
    this.cb = new THREE.InstancedBufferAttribute(new Float32Array(max * 4), 4);
    for (const at of [this.a, this.b, this.ca, this.cb]) at.setUsage(THREE.DynamicDrawUsage);
    this.geom.setAttribute("aA", this.a);
    this.geom.setAttribute("aB", this.b);
    this.geom.setAttribute("aColA", this.ca);
    this.geom.setAttribute("aColB", this.cb);
    this.geom.instanceCount = 0;
    this.mat = new THREE.ShaderMaterial({
      vertexShader: LINE_VS,
      fragmentShader: LINE_FS,
      defines: depthFade ? { FREE: "", DEPTHFADE: "" } : { FREE: "" },
      uniforms: {
        uPx: px,
        uWidth: { value: 2 },
        uScan: { value: new THREE.Vector4(0, 1, 0, 0) },
        uGain: { value: 1 },
        ...(depthFade ? { uCenterDepth: depthFade.center, uFadeR: depthFade.radius } : {}),
      },
      ...ADD,
      depthTest: true,
    });
    this.object = new THREE.Mesh(this.geom, this.mat);
    this.object.frustumCulled = false;
    this.object.renderOrder = 4;
    this.object.matrixAutoUpdate = false;
  }

  set(segs: { a: number[]; b: number[]; ca: number[]; cb: number[] }[], width: number, dpr: number) {
    if (segs.length > this.a.count) segs = segs.slice(0, this.a.count);
    segs.forEach((s, i) => {
      this.a.setXYZ(i, s.a[0], s.a[1], s.a[2]);
      this.b.setXYZ(i, s.b[0], s.b[1], s.b[2]);
      this.ca.setXYZW(i, s.ca[0], s.ca[1], s.ca[2], s.ca[3]);
      this.cb.setXYZW(i, s.cb[0], s.cb[1], s.cb[2], s.cb[3]);
    });
    for (const at of [this.a, this.b, this.ca, this.cb]) at.needsUpdate = true;
    this.geom.instanceCount = segs.length;
    this.mat.uniforms.uWidth.value = width * dpr;
  }

  dispose() {
    this.geom.dispose();
    this.mat.dispose();
  }
}

/** The projection table: the emitter bed with its rings, and the light cone. */
export class Table {
  group = new THREE.Group();
  private disc: THREE.Mesh;
  private cone: THREE.Mesh;
  private dm: THREE.ShaderMaterial;
  private cm: THREE.ShaderMaterial;

  constructor() {
    this.group.matrixAutoUpdate = false;
    const q = new THREE.BufferGeometry();
    q.setAttribute(
      "position",
      new THREE.Float32BufferAttribute([-1, 0, -1, 1, 0, -1, 1, 0, 1, -1, 0, -1, 1, 0, 1, -1, 0, 1], 3),
    );
    this.dm = new THREE.ShaderMaterial({
      vertexShader: DISC_VS,
      fragmentShader: DISC_FS,
      uniforms: {
        uCol: { value: new THREE.Vector3() },
        uTime: { value: 0 },
        uR: { value: 1 / 1.25 },
        uPower: { value: 1 },
      },
      ...ADD,
      depthTest: true,
      depthFunc: THREE.LessEqualDepth,
      side: THREE.DoubleSide,
    });
    this.disc = new THREE.Mesh(q, this.dm);
    this.disc.matrixAutoUpdate = false;
    this.disc.frustumCulled = false;
    const n = 96;
    const pts: number[] = [];
    const idx: number[] = [];
    for (let i = 0; i <= n; i++) {
      const a = (i / n) * Math.PI * 2;
      pts.push(Math.cos(a), 0, Math.sin(a), Math.cos(a), 1, Math.sin(a));
      if (i < n) {
        const k = i * 2;
        idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2);
      }
    }
    const cg = new THREE.BufferGeometry();
    cg.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    cg.setIndex(idx);
    this.cm = new THREE.ShaderMaterial({
      vertexShader: CONE_VS,
      fragmentShader: CONE_FS,
      uniforms: {
        uCol: { value: new THREE.Vector3() },
        uTime: { value: 0 },
        uPower: { value: 1 },
        uR0: { value: 0.5 },
        uR1: { value: 0.5 },
        uH: { value: 1 },
      },
      ...ADD,
      depthTest: true,
      depthFunc: THREE.LessEqualDepth,
      side: THREE.DoubleSide,
    });
    this.cone = new THREE.Mesh(cg, this.cm);
    this.cone.frustumCulled = false;
    this.group.add(this.disc, this.cone);
  }

  /** draw_table(model_mat, radius, cone_top, cone_h, power, colour). */
  update(m: THREE.Matrix4, t: number, radius: number, coneTop: number, coneH: number, power: number, col: Rgb) {
    this.group.matrix.copy(m);
    this.group.matrixWorldNeedsUpdate = true;
    this.disc.matrix.makeScale(radius * 1.25, radius * 1.25, radius * 1.25);
    this.disc.matrixWorldNeedsUpdate = true;
    this.dm.uniforms.uCol.value.set(col[0], col[1], col[2]);
    this.dm.uniforms.uTime.value = t;
    this.dm.uniforms.uPower.value = power * 1.6;
    this.cm.uniforms.uCol.value.set(col[0], col[1], col[2]);
    this.cm.uniforms.uTime.value = t;
    this.cm.uniforms.uPower.value = power;
    this.cm.uniforms.uR0.value = radius * 0.92;
    this.cm.uniforms.uR1.value = coneTop;
    this.cm.uniforms.uH.value = coneH;
  }

  dispose() {
    this.disc.geometry.dispose();
    this.cone.geometry.dispose();
    this.dm.dispose();
    this.cm.dispose();
  }
}

/** One WebGL context: a table scene, a model scene, bloom and the composite. */
export class HoloEngine {
  renderer: THREE.WebGLRenderer;
  camera = new THREE.PerspectiveCamera(30, 1, 0.05, 20);
  tableScene = new THREE.Scene();
  modelScene = new THREE.Scene();
  table = new Table();
  px = { value: new THREE.Vector2(1, 1) };
  dpr = 1;
  width = 1;
  height = 1;
  /** A software rasteriser (SwiftShader, llvmpipe): draw one still frame, never animate. */
  software = false;
  private rt: THREE.WebGLRenderTarget;
  private half: THREE.WebGLRenderTarget;
  private qa: THREE.WebGLRenderTarget;
  private qb: THREE.WebGLRenderTarget;
  private post = new THREE.Scene();
  private postCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  private quad: THREE.Mesh;
  private down: THREE.ShaderMaterial;
  private blur: THREE.ShaderMaterial;
  private comp: THREE.ShaderMaterial;

  maxDpr = 1.5;
  blurPasses = 2;
  constructor(canvas: HTMLCanvasElement, o: { maxDpr?: number; samples?: number; blurPasses?: number } = {}) {
    this.maxDpr = o.maxDpr ?? 1.5;
    this.blurPasses = o.blurPasses ?? 2;
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      premultipliedAlpha: true,
      antialias: false,
      powerPreference: "high-performance",
    });
    this.renderer.autoClear = false;
    // The desktop composites its linear values straight to the window; so does this.
    this.renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    this.renderer.setClearColor(0x000000, 0);
    const gl = this.renderer.getContext();
    this.software = isSoftwareGl(gl);
    const float = !!(gl.getExtension("EXT_color_buffer_float") || gl.getExtension("EXT_color_buffer_half_float"));
    const opts = {
      type: float ? THREE.HalfFloatType : THREE.UnsignedByteType,
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      depthBuffer: false,
    };
    this.rt = new THREE.WebGLRenderTarget(1, 1, { ...opts, depthBuffer: true, samples: o.samples ?? 4 });
    this.half = new THREE.WebGLRenderTarget(1, 1, opts);
    this.qa = new THREE.WebGLRenderTarget(1, 1, opts);
    this.qb = new THREE.WebGLRenderTarget(1, 1, opts);
    const mk = (fs: string, uniforms: Record<string, THREE.IUniform>) =>
      new THREE.ShaderMaterial({ vertexShader: POST_VS, fragmentShader: fs, uniforms, depthTest: false, depthWrite: false });
    this.down = mk(DOWN_FS, { uTex: { value: null }, uTexel: { value: new THREE.Vector2() } });
    this.blur = mk(BLUR_FS, { uTex: { value: null }, uDir: { value: new THREE.Vector2() } });
    this.comp = mk(COMP_FS, {
      uScene: { value: null },
      uBloom: { value: null },
      uBloomK: { value: 1.15 },
      uFade: { value: 1 },
      uEdge: { value: new THREE.Vector2(0.1, 0.1) },
    });
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.down);
    this.quad.frustumCulled = false;
    this.post.add(this.quad);
    this.tableScene.add(this.table.group);
  }

  setSize(w: number, h: number) {
    this.dpr = Math.min(window.devicePixelRatio || 1, this.maxDpr);
    this.width = Math.max(1, Math.round(w));
    this.height = Math.max(1, Math.round(h));
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.setSize(this.width, this.height, false);
    const W = Math.max(1, Math.round(this.width * this.dpr));
    const H = Math.max(1, Math.round(this.height * this.dpr));
    this.px.value.set(W, H);
    this.rt.setSize(W, H);
    this.half.setSize(Math.max(1, W >> 1), Math.max(1, H >> 1));
    this.qa.setSize(Math.max(1, W >> 2), Math.max(1, H >> 2));
    this.qb.setSize(Math.max(1, W >> 2), Math.max(1, H >> 2));
    this.camera.aspect = this.width / this.height;
    this.camera.updateProjectionMatrix();
  }

  lookAt(eye: number[], target: number[], fov: number) {
    this.camera.fov = fov;
    this.camera.updateProjectionMatrix();
    this.camera.position.set(eye[0], eye[1], eye[2]);
    this.camera.up.set(0, 1, 0);
    this.camera.lookAt(target[0], target[1], target[2]);
    this.camera.updateMatrixWorld();
  }

  /** World points -> CSS pixels inside the canvas (top-left origin). */
  project(p: THREE.Vector3, out: THREE.Vector2): THREE.Vector2 {
    const v = p.clone().project(this.camera);
    return out.set((v.x * 0.5 + 0.5) * this.width, (1 - (v.y * 0.5 + 0.5)) * this.height);
  }

  render(bloom = 1.15, fade = 1) {
    const r = this.renderer;
    r.setRenderTarget(this.rt);
    r.clear(true, true, false);
    r.render(this.tableScene, this.camera);
    r.render(this.modelScene, this.camera);
    // bloom: full -> half -> quarter, then a separable blur twice
    const pass = (m: THREE.ShaderMaterial, target: THREE.WebGLRenderTarget | null) => {
      this.quad.material = m;
      r.setRenderTarget(target);
      r.render(this.post, this.postCam);
    };
    this.down.uniforms.uTex.value = this.rt.texture;
    this.down.uniforms.uTexel.value.set(1 / this.rt.width, 1 / this.rt.height);
    pass(this.down, this.half);
    this.down.uniforms.uTex.value = this.half.texture;
    this.down.uniforms.uTexel.value.set(1 / this.half.width, 1 / this.half.height);
    pass(this.down, this.qa);
    for (let i = 0; i < this.blurPasses; i++) {
      this.blur.uniforms.uTex.value = this.qa.texture;
      this.blur.uniforms.uDir.value.set(1 / this.qa.width, 0);
      pass(this.blur, this.qb);
      this.blur.uniforms.uTex.value = this.qb.texture;
      this.blur.uniforms.uDir.value.set(0, 1 / this.qa.height);
      pass(this.blur, this.qa);
    }
    r.setRenderTarget(null);
    r.clear(true, true, false);
    this.comp.uniforms.uScene.value = this.rt.texture;
    this.comp.uniforms.uBloom.value = this.qa.texture;
    this.comp.uniforms.uBloomK.value = bloom;
    this.comp.uniforms.uFade.value = fade;
    this.comp.uniforms.uEdge.value.set(Math.min(0.2, 48 / this.width), Math.min(0.2, 48 / this.height));
    pass(this.comp, null);
  }

  dispose() {
    this.table.dispose();
    [this.rt, this.half, this.qa, this.qb].forEach((t) => t.dispose());
    [this.down, this.blur, this.comp].forEach((m) => m.dispose());
    this.quad.geometry.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}

// ------------------------------------------------------------------ small matrix helpers
const _m = new THREE.Matrix4();

export const M = {
  T: (x: number, y: number, z: number) => new THREE.Matrix4().makeTranslation(x, y, z),
  S: (s: number) => new THREE.Matrix4().makeScale(s, s, s),
  Rx: (a: number) => new THREE.Matrix4().makeRotationX(a),
  Ry: (a: number) => new THREE.Matrix4().makeRotationY(a),
  Rz: (a: number) => new THREE.Matrix4().makeRotationZ(a),
  /** a @ b @ c ... (left to right, like the desktop's numpy chains) */
  chain: (...ms: THREE.Matrix4[]) => {
    const out = new THREE.Matrix4();
    for (const m of ms) out.multiply(m);
    return out;
  },
  into: (target: THREE.Matrix4, ...ms: THREE.Matrix4[]) => {
    target.identity();
    for (const m of ms) target.multiply(_m.copy(m));
    return target;
  },
};

export function approach(cur: number, target: number, dt: number, rate: number) {
  return target + (cur - target) * Math.exp(-rate * dt);
}

export function ease(x: number) {
  const c = Math.min(Math.max(x, 0), 1);
  return c * c * (3 - 2 * c);
}

/** True for a software WebGL rasteriser: Lighthouse's and CI's headless Chrome, VMs without a GPU. */
export function isSoftwareGl(gl: WebGLRenderingContext | WebGL2RenderingContext): boolean {
  try {
    // Firefox unmasks RENDERER itself (and warns about the extension); Chrome needs the extension
    const firefox = typeof navigator !== "undefined" && /Firefox\//.test(navigator.userAgent);
    const ext = firefox ? null : gl.getExtension("WEBGL_debug_renderer_info");
    const name = String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER) ?? "");
    return /SwiftShader|llvmpipe|softpipe|Software|Microsoft Basic Render/i.test(name);
  } catch {
    return false;
  }
}

/** Frame pacing: true when at least 1/fps has passed since the last drawn frame. */
export function frameDue(last: { t: number }, now: number, fps = 30): boolean {
  if (now - last.t < 1 / fps - 0.004) return false;
  last.t = now;
  return true;
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
