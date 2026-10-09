#!/usr/bin/env python3
"""Build the swarm's starship as a bromigos-holo/1 model (.holo.npz), procedurally.

An original design for the Drift: a long arrowhead hull in stacked plates (no trench,
no stepped bridge), a swept relay-mast spire with the burn-in's narrowing crossbars and
a beacon at its tip, an engine bank of octagonal nozzles across the stern, and running
lights. Parts: hull, spire, engines, lights — so status can light each one separately.

  tools/make-starship.py [OUT]     default: models/starship.holo.npz
Coordinates: nose +z, y up, base near y=0, length ~1.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "models", "starship.holo.npz")

PARTS = [("hull", "HULL", "The plates of the hull"), ("spire", "SPIRE", "Command spire, the relay mast"),
         ("engines", "ENGINES", "Engine bank"), ("lights", "LIGHTS", "Running lights"),
         ("beacon", "BEACON", "The spire's beacon: amber when the agent waits on the operator")]


class Mesh:
    def __init__(self):
        self.v = {p: [] for p, _, _ in PARTS}
        self.e = {p: [] for p, _, _ in PARTS}
        self.t = {p: [] for p, _, _ in PARTS}

    def vert(self, part, p):
        self.v[part].append(tuple(float(x) for x in p))
        return len(self.v[part]) - 1

    def poly(self, part, pts, closed=True):
        ix = [self.vert(part, p) for p in pts]
        for a, b in zip(ix, ix[1:] + (ix[:1] if closed else [])):
            self.e[part].append((a, b))
        return ix

    def seg(self, part, a, b):
        self.poly(part, [a, b], closed=False)

    def fan(self, part, ix):
        c = np.mean([self.v[part][i] for i in ix], axis=0)
        ci = self.vert(part, c)
        for a, b in zip(ix, ix[1:] + ix[:1]):
            self.t[part].append((ci, a, b))


def arrow(w, y, nose, tail, notch=0.05, shoulder=0.38):
    """An arrowhead plate outline: nose, shoulders, swept tail corners, a shallow stern notch."""
    zs = tail + (nose - tail) * shoulder
    return [(0, y, nose), (w, y, zs), (w * 0.86, y, tail), (w * 0.18, y, tail + notch * 0.4),
            (0, y, tail + notch), (-w * 0.18, y, tail + notch * 0.4), (-w * 0.86, y, tail), (-w, y, zs)]


def build():
    m = Mesh()
    # hull: a keel, the main plate and two stacked upper plates, stepped and joined
    plates = [arrow(0.30, -0.035, 0.40, -0.44, 0.05), arrow(0.36, 0.0, 0.52, -0.50),
              arrow(0.27, 0.035, 0.40, -0.47), arrow(0.17, 0.066, 0.24, -0.43, 0.03)]
    rings = [m.poly("hull", p) for p in plates]
    for r in rings[1:3]:
        m.fan("hull", r)
    for a, b in zip(plates, plates[1:]):
        for k in (0, 1, 2, 6, 7):                           # step edges between the layers
            m.seg("hull", a[k], b[k])
    for f in (0.2, 0.36, 0.52, 0.68):                       # plate seams across the main deck
        z = 0.52 + (-0.50 - 0.52) * f
        half = 0.36 * min(1.0, (0.52 - z) / ((0.52 + 0.50) * 0.62)) * 0.96
        m.seg("hull", (-half, 0.002, z), (half, 0.002, z))
    m.seg("hull", (0, 0.0, 0.52), (0, 0.066, 0.24))         # spine from the nose up the plates
    # spire: a swept blade with the relay mast's narrowing crossbars, beacon at the tip
    base_f, base_r, top_f, top_r = (0, 0.066, -0.06), (0, 0.066, -0.31), (0, 0.25, -0.22), (0, 0.25, -0.29)
    m.poly("spire", [base_f, top_f, top_r, base_r])
    for y, hw in ((0.13, 0.055), (0.18, 0.04), (0.225, 0.025)):
        z = -0.06 + (y - 0.066) / (0.25 - 0.066) * (-0.22 + 0.06) - 0.03
        m.seg("spire", (-hw, y, z), (hw, y, z))
    m.fan("spire", m.poly("spire", [base_f, top_f, top_r, base_r]))
    # engines: four octagonal nozzles across the stern, each a short barrel
    for x in (-0.2, -0.07, 0.07, 0.2):
        for dz in (0.0, 0.05):
            m.poly("engines", [(x + 0.032 * math.cos(a), 0.01 + 0.032 * math.sin(a), -0.49 + dz)
                               for a in np.linspace(0, 2 * math.pi, 9)[:-1]])
        for a in np.linspace(0, 2 * math.pi, 5)[:-1]:
            m.seg("engines", (x + 0.032 * math.cos(a), 0.01 + 0.032 * math.sin(a), -0.49),
                  (x + 0.032 * math.cos(a), 0.01 + 0.032 * math.sin(a), -0.44))
    # running lights: small diamonds at the tips, along the shoulders, and the spire beacon
    for (x, y, z) in ((0.31, 0.0, -0.43), (-0.31, 0.0, -0.43), (0, 0.004, 0.53), (0.36, 0.0, -0.07),
                      (-0.36, 0.0, -0.07), (0.18, 0.04, 0.12), (-0.18, 0.04, 0.12)):
        r = 0.012
        m.poly("lights", [(x + r, y, z), (x, y + r, z), (x - r, y, z), (x, y - r, z)])
    x, y, z, r = 0, 0.266, -0.255, 0.02
    m.poly("beacon", [(x + r, y, z), (x, y + r, z), (x - r, y, z), (x, y - r, z)])
    m.poly("beacon", [(x, y, z + r), (x, y + r, z), (x, y, z - r), (x, y - r, z)])
    return m


def save(m, path):
    y0 = min(p[1] for vs in m.v.values() for p in vs)
    m.v = {k: [(x, y - y0, z) for x, y, z in vs] for k, vs in m.v.items()}     # base on y = 0
    pos, part, tri, edge, meta_parts = [], [], [], [], []
    for pi, (pid, label, hint) in enumerate(PARTS):
        base = len(pos)
        pos += m.v[pid]
        part += [pi] * len(m.v[pid])
        edge += [(a + base, b + base) for a, b in m.e[pid]]
        tri += [(a + base, b + base, c + base) for a, b, c in m.t[pid]]
        P = np.array(m.v[pid], np.float32)
        meta_parts.append({"id": pid, "label": label, "bind": f"ship.{pid}", "hint": hint,
                           "centroid": P.mean(0).round(4).tolist(), "extent": (P.max(0) - P.min(0)).round(4).tolist(),
                           "explode": {"hull": [0, -0.08, 0], "spire": [0, 0.18, 0], "engines": [0, 0, -0.2],
                                       "lights": [0, 0.05, 0], "beacon": [0, 0.26, 0]}[pid],
                           "anchor": P[np.argmax(P[:, 1])].round(4).tolist(), "tris": len(m.t[pid]),
                           "edges": len(m.e[pid])})
    pos = np.array(pos, np.float32)
    h = float(pos[:, 1].max())
    meta = {"format": "bromigos-holo/1", "name": "starship", "title": "STARSHIP",
            "subtitle": "the swarm's hull: one herdr agent each", "source": "tools/make-starship.py (procedural)",
            "up": "+y", "front": "+z", "height": h, "radius": float(np.abs(pos[:, [0, 2]]).max()),
            "counts": {"vertices": len(pos), "edges": len(edge), "triangles": len(tri)}, "parts": meta_parts}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez_compressed(path, meta=np.frombuffer(json.dumps(meta).encode(), np.uint8),
                        pos=pos, nrm=np.zeros_like(pos, dtype=np.float16), part=np.array(part, np.uint8),
                        tri=np.array(tri, np.uint32).reshape(-1, 3), edge=np.array(edge, np.uint32).reshape(-1, 2))
    return meta


if __name__ == "__main__":
    meta = save(build(), OUT)
    print(OUT, meta["counts"], [(p["id"], p["edges"]) for p in meta["parts"]])
