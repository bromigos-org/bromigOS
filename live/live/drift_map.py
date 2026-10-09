"""SUPER+M — the Drift map: the lore catalog as an interactive star chart.

Source: the public lore catalog that ships with bromigos-live (live/lore/catalog.json,
bromigos.org's public lore export: entries, relationships, timeline), or the file
[driftmap] catalog in config.toml names (the canon's own agents/lore/catalog.json reads
the same way).
The Drift keeps no survey, so the chart's positions are not canon: they come
from a deterministic force layout of the catalog's own relationships (said
plainly on the chart). Places and settings are stars, organisations and
factions are amber markers, the characters the entries point at are the
small crew lights, and every relationship is a faint lane.

The Wick appears as an unplaceable shimmer: no fixed coordinate, drifting,
marked with the burn-in — never with a callsign or a frequency. It is the
catalog's own `the_wick` entry, kept out of the layout (so it isn't also drawn
as a star); hovering it lights the entries it links to.

Scroll zooms toward the cursor (zoomcam.py): the minor entries' names appear as
there is room for them, drag pans while zoomed in (Shift+drag turns), + and - zoom,
double-click empty space or 0 resets.

The relay network is real: the homelab's live services (the lab snapshot)
are the lit relays on the outer ring; a down service goes dark red, and the
relay beam rises from the network only while every service is up.
"""
import hashlib
import json
import math
import os
import time

import numpy as np

from . import glkit
from .config import lore_catalog
from .glkit import col
from .emblem import BRAND
from .overlays import Base
from .zoomcam import ZoomCam, lod

TAU = 2 * math.pi
WICK = "the_wick"
WICK_ENTRY = {"id": WICK, "name": "The Wick", "kind": "place", "status": "unplaceable",   # if the catalog lacks it
              "summary": ("A decommissioned relay station whose position appears in no sector's survey. "
                          "Those who claim to have been there describe the same three things and nothing else: "
                          "a mast with a black flame burned into its housing; a room of racks that hum like a "
                          "held note and run hot enough to heat the place (the Lab, where the network's "
                          "constructed worlds are kept running); and one codec "
                          "deck on a desk, volume low, channel open."),
              "rel": [{"target": "echo_craft", "relation": "keeps running"},
                      {"target": "bromigos", "relation": "keeps lit"}]}
STAR = {"place", "setting", "constructed_world"}
MARK = {"organization", "faction", "institution", "accord"}
CREW = {"person", "support_character", "artificial_intelligence"}
EVENT = {"event", "era", "event_class"}
THING = {"technology", "project", "organism", "artifact", "ship", "designation", "currency"}
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "bromigos-live")


def _h(s, k=0):
    return int.from_bytes(hashlib.blake2b(f"{s}:{k}".encode(), digest_size=4).digest(), "little") / 2 ** 32


def _ascii(s, n=None):
    s = "".join(ch if 32 <= ord(ch) < 127 or ch in "·→" else ("-" if ch in "—–" else "") for ch in (s or ""))
    s = " ".join(s.split())
    return s[:n] if n else s


def _wrap(s, n):
    out, line = [], ""
    for w in s.split():
        if len(line) + len(w) + 1 > n:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


def _title(i):
    return i.replace("_", " ").upper()


def load_catalog(path):
    with open(path) as f:
        cat = json.load(f)
    nodes = {}
    for e in cat.get("entries", []):
        nodes[e["id"]] = {"id": e["id"], "name": e.get("name") or _title(e["id"]), "kind": e.get("kind", "?"),
                          "status": e.get("status", ""), "summary": e.get("summary", ""),
                          "rel": e.get("relationships") or []}
    edges = set()
    for e in list(nodes.values()):
        for r in e["rel"]:
            t = r.get("target")
            if not t:
                continue
            if t not in nodes:          # a character or thing the catalog points at
                nodes[t] = {"id": t, "name": _title(t), "kind": "person", "status": "referenced",
                            "summary": "", "rel": []}
            edges.add(tuple(sorted((e["id"], t))))
    return cat, nodes, sorted(edges)


def split_wick(nodes, edges):
    """Take the Wick out of the chart: it has no position, so it gets no star and
    no lanes. Returns (wick entry, the ids it links to, the remaining edges)."""
    wick = nodes.pop(WICK, None) or dict(WICK_ENTRY)
    near = {a if b == WICK else b for a, b in edges if WICK in (a, b)}
    near = {k for k in near if k in nodes}
    rest = [(a, b) for a, b in edges if WICK not in (a, b)]
    # an entry only the Wick pointed at would float free: drop it with the Wick
    linked = {k for ab in rest for k in ab}
    for k in [k for k in near if nodes[k]["status"] == "referenced" and k not in linked]:
        nodes.pop(k)
        near.discard(k)
    return wick, near, rest


def layout(nodes, edges, iters=500):
    """Fruchterman-Reingold, seeded from the ids (deterministic), radius ~1."""
    ids = sorted(nodes)
    n = len(ids)
    ix = {k: i for i, k in enumerate(ids)}
    pos = np.array([[_h(k, 1) * 2 - 1, _h(k, 2) * 2 - 1] for k in ids], dtype=np.float64)
    E = np.array([(ix[a], ix[b]) for a, b in edges], dtype=np.int64).reshape(-1, 2)
    k = math.sqrt(4.0 / n)
    temp = 0.25
    for it in range(iters):
        d = pos[:, None, :] - pos[None, :, :]
        dist = np.sqrt((d ** 2).sum(-1)) + 1e-6
        rep = (k * k / dist ** 2)[..., None] * d
        disp = rep.sum(1)
        if len(E):
            de = pos[E[:, 0]] - pos[E[:, 1]]
            dl = np.sqrt((de ** 2).sum(-1))[:, None] + 1e-6
            att = de * dl / k
            np.add.at(disp, E[:, 0], -att)
            np.add.at(disp, E[:, 1], att)
        disp -= pos * 0.06 * np.sqrt((pos ** 2).sum(-1, keepdims=True))   # gentle gravity
        L = np.sqrt((disp ** 2).sum(-1, keepdims=True)) + 1e-9
        pos += disp / L * np.minimum(L, temp)
        temp *= 0.992
    pos -= pos.mean(0)
    # even out density: keep each entry's angle and its order outward, but give
    # the radii a uniform-area spread (rank-based), so the dense core opens up
    r = np.sqrt((pos ** 2).sum(-1)) + 1e-9
    order = np.argsort(np.argsort(r))
    r_new = 0.12 + 0.88 * np.sqrt((order + 0.5) / n)
    # and the angles halfway to an even spread (keeping their order round the
    # chart), so a tightly linked group opens into a sector instead of a knot
    a = np.arctan2(pos[:, 1], pos[:, 0])
    a_even = (np.argsort(np.argsort(a)) + 0.5) / n * TAU - math.pi
    a_new = a + 0.5 * (a_even - a)
    pos = np.stack([np.cos(a_new), np.sin(a_new)], -1) * r_new[:, None]
    return {k: (float(pos[i, 0]), float(pos[i, 1])) for k, i in ix.items()}


def cached_layout(path, nodes, edges):
    key = hashlib.sha1((open(path, "rb").read())).hexdigest()[:16]
    fn = os.path.join(CACHE, f"driftmap-{key}-v4.json")
    try:
        with open(fn) as f:
            return {k: tuple(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        pass
    lay = layout(nodes, edges)
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(fn, "w") as f:
            json.dump(lay, f)
    except OSError:
        pass
    return lay


class DriftMap(Base):
    name = "driftmap"
    rebuild_every = 2.0
    emblem_kit = BRAND         # the map marks the Wick itself: always the burn-in, whatever the theme

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        s = self.h / 1440.0
        self.s = s
        path = lore_catalog(self.cfg)
        self.ok = os.path.exists(path)
        self.nodes, self.edges, self.timeline = {}, [], []
        self.wick, self.wick_near, self.degree = dict(WICK_ENTRY), set(), {}
        if self.ok:
            cat, self.nodes, self.edges = load_catalog(path)
            self.timeline = sorted(cat.get("timeline") or [], key=lambda t: t.get("order", 0))
            self.wick, self.wick_near, self.edges = split_wick(self.nodes, self.edges)
            for a_, b_ in self.edges:
                self.degree[a_] = self.degree.get(a_, 0) + 1
                self.degree[b_] = self.degree.get(b_, 0) + 1
            lay = cached_layout(path, self.nodes, self.edges)
            for k, (x, z) in lay.items():
                nd = self.nodes[k]
                y = (_h(k, 3) - 0.5) * (0.05 if nd["kind"] in STAR else 0.12)
                nd["p"] = (x * 0.95, y, z * 0.95)
        self.ids = sorted(self.nodes)
        self.pts = np.array([self.nodes[k]["p"] for k in self.ids], dtype=np.float32).reshape(-1, 3)
        self.L = {"chart": (420 * s, 150 * s, 1520 * s, 1180 * s), "center": (1180 * s, 740 * s, 470 * s),
                  "side": (60 * s, 150 * s, 340 * s, 1180 * s), "card": (1960 * s, 150 * s, 540 * s, 1180 * s)}
        self.yaw, self.pitch = 0.3, 0.82
        self.drag = None
        self.last_input = -10.0
        self.hover = None
        self.selected = None
        self.sel_t = 0.0
        self.wick_px = None
        self.settled = False
        self.mods = 0
        self.t_prev = None
        cx, cy, R = self.L["center"]
        self.cam = ZoomCam(self.L["chart"], (cx, cy), R, zmin=0.7, zmax=7.0)

    # ------------------------------------------------------------------ style
    def style(self, nd):
        k = nd["kind"]
        if k in STAR:
            return col("soft"), 5.0, True
        if k in MARK:
            return col("amber"), 3.6, True
        if k in CREW:
            return col("phosphor", 0.85), 2.0, False
        if k in EVENT:
            return col("white", 0.8), 2.2, False
        if k in THING:
            return col("dim"), 2.2, False
        return col("static", 0.9), 2.4, False

    def services(self, d):
        return sorted(((k, (v or {}).get("status", "unknown")) for k, v in
                       ((d.get("cluster") or {}).get("services") or {}).items()))

    # ------------------------------------------------------------------ build
    def build(self, b, d, t):
        s = self.s
        T = 0.05
        b.text("THE DRIFT // STAR CHART", 60 * s, 110 * s, col("soft"), font="l", track=6, reveal=T, type_rate=0.02)
        b.text("FROM THE LORE CATALOG · POSITIONS FOLLOW ITS RELATIONSHIPS: THE DRIFT KEEPS NO SURVEY",
               self.w - 60 * s, 108 * s, col("dim"), font="xs", track=2, align="r", reveal=T + 0.2, type_rate=0.006)
        b.line((60 * s, 130 * s), (self.w - 60 * s, 130 * s), col("guard"), reveal=T)
        if not self.ok:
            b.text("LORE CATALOG NOT FOUND (driftmap.catalog in config.toml)", self.w / 2, self.h / 2, col("amber"),
                   font="m", track=2, align="c")
            return
        # graticule
        for i, r in enumerate((0.35, 0.7, 1.05)):
            pts = [(math.cos(a / 96 * TAU) * r, 0.0, math.sin(a / 96 * TAU) * r) for a in range(97)]
            for k in range(96):
                b.line(pts[k], pts[k + 1], col("guard", 0.9), space=2, reveal=T + 0.1 + i * 0.05)
        for k in range(12):
            a = k / 12 * TAU
            b.line((math.cos(a) * 0.12, 0, math.sin(a) * 0.12), (math.cos(a) * 1.05, 0, math.sin(a) * 1.05),
                   col("guard", 0.6), space=2, dash=6, reveal=T + 0.2)
        focus = self.selected or self.hover
        rel = set()
        if focus == WICK:                     # no lanes to draw; light what it links to
            rel = set(self.wick_near)
        elif focus:
            for a_, b_ in self.edges:
                if focus in (a_, b_):
                    rel.update((a_, b_))
        # lanes (relationships)
        for a_, b_ in self.edges:
            hot = focus in (a_, b_)
            b.line(self.nodes[a_]["p"], self.nodes[b_]["p"], col("soft" if hot else "dim", 0.85 if hot else 0.22),
                   space=2, reveal=T + 0.3)
        # entries; labels by room (zoomed out: the stars and markers; zooming in: the rest)
        z = self.cam.z
        minor = lod(z, 1.35, 2.2)
        p = self.stage.painter
        labels = self.cam.labels(self.stage.atlas, p, s, cap=int(40 + 50 * minor))
        for i, k in enumerate(self.ids):
            nd = self.nodes[k]
            c, size, label = self.style(nd)
            on = (not focus) or k in rel
            cc = (c[0], c[1], c[2], c[3] * (1.0 if on else 0.35))
            b.arc(nd["p"], 0, size * s, 0, TAU, cc, kind=2, space=2, reveal=T + 0.3 + (i % 40) * 0.01)
            if nd["kind"] in STAR:
                b.arc(nd["p"], size * s + 4, size * s + 5.2, 0, TAU, (c[0], c[1], c[2], 0.7 * cc[3]), segs=12,
                      gap=0.35, spin=0.15, space=2, reveal=T + 0.5)
            elif nd["kind"] in MARK:
                b.arc(nd["p"], size * s + 3, size * s + 4.4, 0, TAU, cc, segs=4, gap=0.55, spin=0.0, phase=0.785,
                      space=2, reveal=T + 0.5)
            name = _ascii(nd["name"], 30).upper()
            font = "s" if nd["kind"] in STAR else "xs"
            rv = T + 0.7 + (i % 40) * 0.01
            if k == focus or k == self.hover or k in rel:
                labels.add(9, nd["p"], name, font, 1.4, colour=cc if k != focus else col("white"), reveal=rv,
                           force=True)
            elif label and on:                        # stars and markers first, the most linked first;
                labels.add(5 + size + 0.01 * self.degree.get(k, 0), nd["p"], name, font, 1.4, colour=cc,
                           reveal=rv)                  # where they crowd, zooming in makes room
            elif on and minor > 0.0:                   # the minor entries, as zooming makes room
                labels.add(1 + size, nd["p"], name, font, 1.4, colour=(cc[0], cc[1], cc[2], cc[3] * minor),
                           reveal=rv)
        labels.place(b)
        self.cam.readout(b, s, T + 0.6)
        if self.hover == WICK and self.wick_px:
            wx, wy = self.wick_px
            b.plate(wx + 28 * s, wy - 22 * s, 470 * s, 44 * s, 0.85)
            b.text("THE WICK · NO SURVEY HAS ITS POSITION", wx + 36 * s, wy - 4 * s, col("amber"), font="xs", track=1.5)
            b.text("A DECOMMISSIONED RELAY STATION · CLICK FOR THE ENTRY", wx + 36 * s, wy + 14 * s, col("dim"),
                   font="xs", track=1.2)
        elif self.hover and self.hover != self.selected:
            nd = self.nodes[self.hover]
            b.text(f"{_ascii(nd['kind']).upper().replace('_', ' ')} · CLICK FOR THE ENTRY", *nd["p"][:2],
                   col("dim"), font="xs", track=1.2, space=2, z=nd["p"][2], dx=10, dy=12)
        self._relays(b, d, T)
        self._side(b, T)
        self._card(b, T)
        b.text("SCROLL ZOOMS · DRAG TURNS (PANS WHEN ZOOMED) · HOVER A LIGHT · CLICK FOR ITS ENTRY · ESC CLOSES",
               self.w / 2, self.h - 22 * s,
               col("dim", 0.85), font="xs", track=2.5, align="c", reveal=T + 1.2)

    def _relays(self, b, d, T):
        s = self.s
        sv = self.services(d)
        n = max(len(sv), 1)
        R = 1.22
        pts = [(math.cos(i / n * TAU) * R, 0.0, math.sin(i / n * TAU) * R) for i in range(n)]
        up = sum(1 for _, st in sv if st == "up")
        green = bool(sv) and up == len(sv) and (d.get("cluster_ok") is not False)
        for i, (name, st) in enumerate(sv):
            c = {"up": "soft", "warn": "amber", "down": "danger"}.get(st, "static")
            b.arc(pts[i], 0, (3.2 if st == "up" else 4.2) * s, 0, TAU, col(c, 0.95 if st == "up" else 1.0), kind=2,
                  space=2, reveal=T + 0.6 + i * 0.01)
            if st != "up":
                b.text(f"{_title(name)} · {st.upper()}", *pts[i][:2], col(c), font="xs", track=1.2, space=2,
                       z=pts[i][2], dx=10, dy=-6)
            j = (i + 1) % n
            b.line(pts[i], pts[j], col("soft" if green else "dim", 0.55 if green else 0.3), space=2, dash=0 if green else 5,
                   reveal=T + 0.7)
            if green:
                b.arc(pts[i], 0, 1.8 * s, 0, TAU, col("white", 0.9), kind=2, space=2, end=pts[j], speed=0.5,
                      phase=_h(name), reveal=T + 0.9)
        # the relay beam: up from the network while everything is lit
        net = self.nodes.get("bromigos")
        if net and green:
            p0 = net["p"]
            b.line(p0, (p0[0], p0[1] + 1.3, p0[2]), col("soft", 1.0), space=2, width=2.5, reveal=T + 0.9)
            b.line(p0, (p0[0], p0[1] + 1.3, p0[2]), col("phosphor", 0.35), space=2, width=9.0, reveal=T + 0.9)
            b.arc((p0[0], p0[1] + 1.3, p0[2]), 0, 5 * s, 0, TAU, col("white"), kind=2, space=2, reveal=T + 1.0)
            for k in range(3):
                b.arc(p0, 0, 2.4 * s, 0, TAU, col("white"), kind=2, space=2, end=(p0[0], p0[1] + 1.3, p0[2]),
                      speed=0.4, phase=k / 3, reveal=T + 1.0)
        self.relay_line = (f"RELAYS {up}/{len(sv)} LIT · " + ("BEAM UP" if green else "BEAM DOWN")) if sv else \
            "RELAYS · NO LAB SNAPSHOT"
        self.relay_green = green

    def _side(self, b, T):
        s = self.s
        x, y, w, h = self.L["side"]
        from . import gadgets
        gadgets.frame(b, x, y, w, h, "LEGEND", T + 0.1)
        rows = [("soft", 5.0, "PLACES · SETTINGS", STAR), ("amber", 3.6, "ORGANISATIONS · FACTIONS", MARK),
                ("phosphor", 2.0, "CREW AND CHARACTERS", CREW), ("white", 2.2, "EVENTS · ERAS", EVENT),
                ("dim", 2.2, "TECHNOLOGY · SHIPS · PROJECTS", THING)]
        for i, (c, sz, lab, kinds) in enumerate(rows):
            yy = y + 70 * s + i * 30 * s
            n = sum(1 for nd in self.nodes.values() if nd["kind"] in kinds)
            b.arc((x + 28 * s, yy - 5 * s), 0, sz * s, 0, TAU, col(c), kind=2, reveal=T + 0.3 + i * 0.05)
            b.text(f"{lab}", x + 46 * s, yy, col("soft"), font="xs", track=1.2, reveal=T + 0.35 + i * 0.05)
            b.text(str(n), x + w - 18 * s, yy, col("dim"), font="xs", track=1, align="r", reveal=T + 0.35)
        yy = y + 70 * s + len(rows) * 30 * s + 10 * s
        b.arc((x + 28 * s, yy - 5 * s), 0, 3.2 * s, 0, TAU, col("soft"), kind=2)
        b.text("LIT RELAY (A LIVE SERVICE)", x + 46 * s, yy, col("soft"), font="xs", track=1.2, reveal=T + 0.6)
        b.text(getattr(self, "relay_line", ""), x + 46 * s, yy + 18 * s, col("soft" if getattr(self, "relay_green", False)
               else "amber"), font="xs", track=1, reveal=T + 0.7)
        b.text("THE WICK: NO FIXED POSITION", x + 46 * s, yy + 48 * s, col("amber"), font="xs", track=1.2,
               reveal=T + 0.65)
        # the timeline
        ty = yy + 96 * s
        b.text("TIMELINE", x + 18 * s, ty, col("dim"), font="xs", track=3, reveal=T + 0.7)
        b.line((x + 18 * s, ty + 8 * s), (x + w - 18 * s, ty + 8 * s), col("guard"), reveal=T + 0.7)
        yy = ty + 32 * s
        for i, ev in enumerate(self.timeline):
            if yy > y + h - 30 * s:
                break
            b.text(_ascii(ev.get("period"), 34).upper(), x + 18 * s, yy, col("amber", 0.95), font="xs", track=1,
                   reveal=T + 0.8 + i * 0.04)
            yy += 18 * s
            for ln in _wrap(_ascii(ev.get("event")).upper(), 38)[:3]:
                b.text(ln, x + 18 * s, yy, col("soft", 0.85), font="xs", track=0.5, reveal=T + 0.85 + i * 0.04,
                       type_rate=0.002)
                yy += 17 * s
            yy += 10 * s

    def _card(self, b, T):
        s = self.s
        x, y, w, h = self.L["card"]
        from . import gadgets
        if not self.selected:
            gadgets.frame(b, x, y, w, 120 * s, "ENTRY", T + 0.2)
            b.text("CLICK A LIGHT TO READ ITS ENTRY", x + 18 * s, y + 80 * s, col("dim"), font="xs", track=2,
                   reveal=T + 0.6)
            return
        nd = self.wick if self.selected == WICK else self.nodes[self.selected]
        rv = self.sel_t
        gadgets.frame(b, x, y, w, h, "ENTRY", rv)
        b.text(_ascii(nd["name"], 34).upper(), x + 18 * s, y + 76 * s, col("white"), font="m", track=1.5, reveal=rv,
               type_rate=0.01)
        b.text(f"{_ascii(nd['kind']).upper().replace('_', ' ')} · {_ascii(nd['status']).upper()}", x + 18 * s,
               y + 100 * s, col("dim"), font="xs", track=2, reveal=rv + 0.05)
        yy = y + 136 * s
        for ln in _wrap(_ascii(nd["summary"] or "Referenced by the catalog; this one has no entry of its own yet."),
                        52)[:18]:
            b.text(ln, x + 18 * s, yy, col("soft", 0.95), font="xs", track=0.6, reveal=rv + 0.1, type_rate=0.002)
            yy += 19 * s
        yy += 16 * s
        rels = list(nd["rel"]) + [{"target": a if a != nd["id"] else c, "relation": "named by"}
                                  for a, c in self.edges if nd["id"] in (a, c) and not nd["rel"]]
        if nd["id"] == WICK:
            b.text("POSITION: UNLISTED · THE CHART CANNOT HOLD IT STILL", x + 18 * s, yy, col("amber"), font="xs",
                   track=1.5, reveal=rv + 0.15)
            yy += 30 * s
        if rels:
            b.text("LANES", x + 18 * s, yy, col("dim"), font="xs", track=3, reveal=rv + 0.2)
            yy += 24 * s
            for r in rels[:14]:
                tgt = self.wick if r.get("target") == WICK else self.nodes.get(r.get("target"), {})
                ln = f"{_ascii(r.get('relation') or '', 22)} → {_ascii(tgt.get('name') or r.get('target'), 28)}".upper()
                b.text(ln, x + 18 * s, yy, col("amber" if tgt.get("kind") in MARK else "soft", 0.95), font="xs",
                       track=0.6, reveal=rv + 0.25, type_rate=0.002)
                yy += 19 * s

    # ------------------------------------------------------------------ frame
    def frame(self, t, d):
        s = self.s
        p = self.stage.painter
        dt = 0.0 if self.t_prev is None else min(t - self.t_prev, 0.1)
        self.t_prev = t
        if self.drag is None and t - self.last_input > 4.0 and not self.cam.zoomed and not self.reduced:
            self.yaw += 0.0012                     # idle drift (none under reduced motion)
        cx, cy, R = self.L["center"]
        p.rot[2] = glkit.rot_matrix(self.yaw, self.pitch)
        self.cam.step(dt, p.rot[2], 3.6)
        p.ctr[2] = self.cam.ctr(3.6)
        p.clip[2] = self.cam.clip()
        fade = min(t / 0.25, 1.0)
        if self.closing_at is not None:
            fade = max(0.0, 1.0 - (t - self.closing_at) / 0.25)
        u = {"backdrop": 0.86, "glow": 0.95, "fade": fade,
             "space": (1.0, -1.0, 0.0, 0.0), "space_rect": (0.0, 0.0, float(self.w), float(self.h))}
        # the Wick: no fixed coordinate — it drifts, and shimmers in and out
        x, y, w, h = self.L["chart"]
        wx = cx + math.sin(t * 0.071) * w * 0.33 + math.sin(t * 0.193) * 40 * s
        wy = cy + math.sin(t * 0.053 + 1.3) * h * 0.27 + math.cos(t * 0.17) * 30 * s
        flick = 0.35 + 0.3 * (0.5 + 0.5 * math.sin(t * 2.3)) * (0.6 + 0.4 * math.sin(t * 7.9 + 1.1))
        sz = 46 * s
        self.wick_px = (wx, wy)
        u["emblems"] = [{"rect": (wx - sz / 2, wy - sz / 2, sz, sz), "angle": -t * TAU / 24, "alpha": flick * fade,
                         "small": True}]
        if self.closing_at is not None and t - self.closing_at > 0.26:
            u["finished"] = True
        return u

    def build_wick_label(self, b):
        pass

    def rebuild_due(self, t):
        every = 0.06 if self.hover == WICK else self.rebuild_every       # the label follows the drift
        if not self.settled and self.built_at is not None:   # once more right away: the first build
            self.settled = True                              # can run before the view is set, and
            return True                                      # labels are placed by where they land
        return self.built_at is None or t - self.built_at >= every

    def render(self, fbo, fps):
        if self.built_at is not None and self.cam.build_due(self.now()):
            self.built_at = None                 # labels follow the zoom
        before = self.built_at
        super().render(fbo, fps)
        if self.built_at is not before:
            self.cam.mark_built(self.built_at)

    # ------------------------------------------------------------------ input
    def _pick(self, x, y):
        if self.wick_px and math.hypot(x - self.wick_px[0], y - self.wick_px[1]) < 30 * self.s:
            return WICK
        if not len(self.pts):
            return None
        p = self.stage.painter
        pr = glkit.project(self.pts, p.rot[2], p.ctr[2])
        dd = np.hypot(pr[:, 0] - x, pr[:, 1] - y)
        i = int(np.argmin(dd))
        return self.ids[i] if dd[i] < 12 * self.s + 3 else None

    def _in_chart(self, x, y):
        x0, y0, w, h = self.L["chart"]
        return x0 <= x <= x0 + w and y0 <= y <= y0 + h

    def click(self, x, y, button):
        self.last_input = self.now()
        if self._in_chart(x, y):
            pan = self.cam.zoomed != bool(self.mods & 1)        # Shift swaps turn and pan
            pan = True if button == 2 else False if button == 3 else pan
            self.drag = (x, y, self.yaw, self.pitch, False, "pan" if pan else "turn", x, y)
            return True
        inside = any(px <= x <= px + w and py <= y <= py + h for (px, py, w, h) in (self.L["side"], self.L["card"]))
        if not inside:
            self.close()
        return True

    def motion(self, x, y, buttons):
        self.last_input = self.now()
        if self.drag:
            x0, y0, yaw, pitch, moved, mode, lx, ly = self.drag
            moved = moved or abs(x - x0) + abs(y - y0) > 4
            if mode == "pan":
                self.cam.pan_by(x - lx, y - ly)
            else:
                self.yaw = yaw + (x - x0) * 0.006
                self.pitch = max(0.25, min(1.5, pitch + (y - y0) * 0.005))
            self.drag = (x0, y0, yaw, pitch, moved, mode, x, y)
            return
        h = self._pick(x, y) if self._in_chart(x, y) else None
        if h != self.hover:
            self.hover = h
            self.built_at = None

    def release(self, x, y):
        if self.drag and not self.drag[4]:
            n = self._pick(x, y)
            self.selected = None if n == self.selected else n
            self.sel_t = self.now() + 0.01
            self.built_at = None
        self.drag = None

    def scroll(self, x, y, dy):
        if not self._in_chart(x, y):
            return False
        self.last_input = self.now()
        self.cam.wheel(x, y, dy)
        return True

    def dclick(self, x, y):
        if self._in_chart(x, y) and self._pick(x, y) is None:
            self.cam.reset()
            self.last_input = self.now()

    def key(self, name):
        if name in ("Escape", "q"):
            self.close()
        elif name in ("plus", "equal", "KP_Add"):
            self.cam.key_zoom(+1)
        elif name in ("minus", "KP_Subtract"):
            self.cam.key_zoom(-1)
        elif name in ("0", "KP_0", "Home"):
            self.cam.reset()
        elif name in ("Left", "h"):
            self.yaw -= 0.2
        elif name in ("Right", "l"):
            self.yaw += 0.2
        self.last_input = self.now()
        return True
