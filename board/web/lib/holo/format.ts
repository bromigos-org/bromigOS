// Reader for the site's hologram format, `bromigos-holo-web/1` (the .bin files that
// scripts/sitemedia/holograms.py bakes from the desktop's .holo.npz models).

export type HoloPart = {
  id: string;
  label: string;
  hint: string;
  explode: [number, number, number];
  anchor: [number, number, number];
};

export type HoloModelInfo = {
  name: string;
  title: string;
  subtitle: string;
  hint: string;
  src: string;
  bytes: number;
  codeDrawn: boolean;
  credit: string | null;
  height: number;
  radius: number;
  lore: string[];
  worlds: string[];
  parts: HoloPart[];
};

export type HoloManifest = {
  format: string;
  models: HoloModelInfo[];
  pending: string[];
};

export type HoloMesh = {
  pos: Float32Array; // V*3
  nrm: Float32Array; // V*3
  part: Float32Array; // V
  tri: Uint16Array | Uint32Array; // T*3
  edge: Uint16Array | Uint32Array; // E*2
  nparts: number;
};

const MANIFEST_URL = "/holo/data/holograms.json";
let manifestPromise: Promise<HoloManifest | null> | null = null;

/** The published holograms (one fetch per page). Null when there are none. */
export function loadManifest(): Promise<HoloManifest | null> {
  if (!manifestPromise) {
    manifestPromise = fetch(MANIFEST_URL)
      .then((r) => (r.ok ? (r.json() as Promise<HoloManifest>) : null))
      .catch(() => null);
  }
  return manifestPromise;
}

const meshes = new Map<string, Promise<HoloMesh>>();

export function loadMesh(src: string): Promise<HoloMesh> {
  let p = meshes.get(src);
  if (!p) {
    // NAME.bin.json ({format, bytes, data: base64}), because the artifact host refuses raw binary:
    // fetched once, decoded once by the browser (a data: URL), cached for every state and view
    p = fetch(src)
      .then((r) => {
        if (!r.ok) throw new Error(`hologram ${src}: ${r.status}`);
        return /\.json(\?|$)/.test(src) ? r.json().then((j: { data: string }) => fetch(`data:application/octet-stream;base64,${j.data}`)).then((d) => d.arrayBuffer()) : r.arrayBuffer();
      })
      .then(parse);
    meshes.set(src, p);
  }
  return p;
}

export function parse(buf: ArrayBuffer): HoloMesh {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== "BHW1") throw new Error("not a bromigos hologram");
  const V = dv.getUint32(4, true);
  const T = dv.getUint32(8, true);
  const E = dv.getUint32(12, true);
  const P = dv.getUint32(16, true);
  const wide = (dv.getUint32(20, true) & 1) === 1;
  const lo = [dv.getFloat32(24, true), dv.getFloat32(28, true), dv.getFloat32(32, true)];
  const hi = [dv.getFloat32(36, true), dv.getFloat32(40, true), dv.getFloat32(44, true)];
  let off = 48;
  const align = () => {
    off += (4 - (off % 4)) % 4;
  };
  const q = new Uint16Array(buf, off, V * 3);
  off += V * 6;
  align();
  const n8 = new Int8Array(buf, off, V * 3);
  off += V * 3;
  align();
  const p8 = new Uint8Array(buf, off, V);
  off += V;
  align();
  const IA = wide ? Uint32Array : Uint16Array;
  const isz = wide ? 4 : 2;
  const tri = new IA(buf.slice(off, off + T * 3 * isz));
  off += T * 3 * isz;
  align();
  const edge = new IA(buf.slice(off, off + E * 2 * isz));

  const pos = new Float32Array(V * 3);
  const nrm = new Float32Array(V * 3);
  const part = new Float32Array(V);
  for (let i = 0; i < V; i++) {
    for (let k = 0; k < 3; k++) {
      pos[i * 3 + k] = lo[k] + (q[i * 3 + k] / 65535) * (hi[k] - lo[k]);
      nrm[i * 3 + k] = n8[i * 3 + k] / 127;
    }
    part[i] = p8[i];
  }
  return { pos, nrm, part, tri, edge, nparts: P };
}
