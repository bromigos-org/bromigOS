"""SUPER+SHIFT+H — the Lab deck: the homelab console as a hologram (bromigos-live lab).

The server rack (homelab/holo, VECTOR's renderer) stands in the middle with its parts lit
by the console's own readings, the same cards `bromigos lab status` prints:

  SWITCH     the services (ComfyUI, the voice service, the model servers): red when one is down
  NODES      every node: red when one is down or its disk is nearly full
  GPU SERVER the GPUs: amber when hot, and pulsing while one is busy
  STORAGE    disks and NAS shares, fullest first
  POWER      what the GPUs draw
  FRAME      GitOps apps and firing alerts

Around it the nodes orbit as stations, each GPU node ringed by its VRAM (a spinning ring
while the GPU works), a tensor-parallel pair joined by a beam, the pods holding each GPU
named under it. Below, the GPU job queue: the media GPU's VRAM (what others hold, what's
kept for the voice service, what's free) and the jobs, running, waiting and done.

Click a rack part, a node or a card on the right to drill into it: the side panel lists
its items as `bromigos lab status --card ID` does, each with its hover hint. < ALL CARDS
(or Backspace) goes back. Without VECTOR's renderer the rack is drawn as a wireframe, lit the same way.

Polling (only while open): the console's cards every 10 s, the queue every 2 s.
Verbs (VECTOR, `bromigos-live lab VERB`): focus <card or node>, clear; open, close; bare
`bromigos-live lab` toggles it (the key).
"""
import math
import threading
import time

import numpy as np

from . import gadgets, glkit
from .deckkit import TAU, Deck3D, ascii_, frame_panel, wrap
from .glkit import col
from .homelab import H

COLOUR = {"ok": "phosphor", "warn": "amber", "crit": "danger", "unreachable": "danger", "empty": "dim",
          "unknown": "dim", "off": "static"}
LEVEL = {"ok": "ok", "warn": "warn", "crit": "crit", "unreachable": "crit", "empty": "off", "unknown": "off"}
# rack part id (homelab/holo/manifest.json) -> the card it shows, and its hover's what-it-is
PART_CARD = {"switch": "services", "nodes": "nodes", "gpu": "gpus", "storage": "storage", "ups": "gpus",
             "frame": "deployments"}
PART_WHAT = {"switch": "SERVICES: COMFYUI, VOICE, MODEL SERVERS", "nodes": "THE LAB'S NODES",
             "gpu": "THE GPUS", "storage": "DISKS AND NAS SHARES", "ups": "WHAT THE GPUS DRAW",
             "frame": "GITOPS APPS AND ALERTS"}


def _gib(b):
    return f"{(b or 0) / 2**30:.1f}"


class LabHolo:
    """The rack from VECTOR's shared renderer, its part readings replaced every frame by the
    console's (the same cards as `bromigos lab status`)."""

    def __new__(cls, names, scale, readings_fn):
        from . import holoview

        class _Holo(holoview.CompactHolo):
            def _ensure(self, w, h):
                super()._ensure(w, h)
                st = self.stage
                if not getattr(st, "_lab_wrapped", False):
                    orig = st.update

                    def update(dt, interacting=False):
                        orig(dt, interacting)
                        r = readings_fn(st)
                        if r:
                            st.readings = r
                    st.update = update
                    st._lab_wrapped = True
        return _Holo(names, scale=scale)


class LabDeck(Deck3D):
    name = "lab"
    deck_label = "Lab"
    deck_hint = "the homelab console: the rack, GPUs, jobs (SUPER+SHIFT+H)"
    title = "LAB // THE HOMELAB CONSOLE"
    hint = "VECTOR: bromigos-live lab focus <card or node>"
    rebuild_every = 0.5

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        s = self.s
        self.yaw, self.pitch, self.persp, self.spin = 0.35, 0.46, 4.6, 0.02
        self.L["center"] = (900 * s, 520 * s, 470 * s)
        self.gauge_hits = []         # (x, y, r, card id, hint)
        self.gauge_hover = None
        self.doc = None              # bromigos lab status
        self.jobs = []
        self.view = None             # the media GPU, as the queue sees it
        self.reserve = 2048
        self.drill = None            # a card id shown in the side panel
        self.drill_node = None
        self.side_rows = []          # (y0, y1, kind, key, hint)
        self.side_hover = None
        self.hv_hover = None
        self.opened = None
        self.ready_ = False
        self.err = ""
        self.lock = threading.Lock()
        from . import holoview
        try:
            self.hv = LabHolo(["rack"], s, self._rack_readings) if "rack" in holoview.available() else None
        except Exception:
            self.hv = None
        self.poll_every(self._read_status, 10, "status")
        self.poll_every(self._read_jobs, 2, "jobs")

    def ready(self):
        return self.ready_

    # ------------------------------------------------------------------ data
    def _read_status(self):
        if not H:
            self.err = "bromigos-homelab isn't installed"
            return
        from bromigos_homelab import console
        try:
            doc = console.status()
        except Exception as e:                 # keep the last good cards; say why
            self.err = f"{type(e).__name__}: {str(e)[:80]}"
            return
        with self.lock:
            self.doc = doc
            self.err = ""
        self.ready_ = True
        self.built_at = None

    def _read_jobs(self):
        if not H:
            return
        from bromigos_homelab import jobqueue
        try:
            js = jobqueue.list_jobs(limit=14)
            info = jobqueue.service_info()
        except Exception:
            return
        self.jobs = js
        self.view = (info or {}).get("gpu") or self.view
        self.reserve = (info or {}).get("voice_reserve_mib") or self.reserve
        self.built_at = None

    def card(self, cid):
        return next((c for c in (self.doc or {}).get("cards", []) if c["id"] == cid), None)

    # ------------------------------------------------------------------ the rack's parts
    def _rack_readings(self, st):
        """(level, value, lines, age) per rack part, from the console's cards."""
        if not self.doc:
            return None
        t = self.now()
        out = []
        for p in st.parts:
            pid = p.get("id")
            if pid == "frame":
                dep, al = self.card("deployments"), self.card("alerts")
                states = [c["state"] for c in (dep, al) if c]
                lv = "crit" if "crit" in states or "unreachable" in states else "warn" if "warn" in states else "ok"
                lines = [c["summary"] for c in (dep, al) if c] or ["no GitOps or alert source"]
                out.append((lv, 0.5, lines, None))
                continue
            if pid == "ups":
                g = self.card("gpus")
                watts = sum(i.get("power_w") or 0 for i in (g or {}).get("items", []))
                out.append(("ok" if g else "off", min(watts / 900.0, 1.0) * 0.6 + 0.3,
                            [f"GPUs draw {watts:.0f} W"] if g else ["no GPU readings"], None))
                continue
            c = self.card(PART_CARD.get(pid, ""))
            if not c:
                out.append(("off", 0.2, ["nothing here reports it"], None))
                continue
            lv = LEVEL.get(c["state"], "off")
            v = 0.55
            if pid == "gpu":
                busy = [i for i in c["items"] if i.get("busy")]
                if busy and not self.reduced:          # a GPU at work: the part breathes
                    v = 0.62 + 0.38 * math.sin(t * 3.2)
                elif busy:
                    v = 1.0
            bad = [i for i in c["items"] if i.get("state") in ("warn", "crit")]
            lines = [c.get("summary") or ""] + [f"{i.get('name')}: {i.get('detail') or i.get('state')}" for i in bad[:2]]
            out.append((lv, v, lines, None))
        return out

    # ------------------------------------------------------------------ verbs
    def command(self, verb, args):
        a = (args or "").strip().lower()
        if verb == "clear":
            self.drill = self.drill_node = None
            self.built_at = None
            return "cleared"
        if verb == "focus":
            if not self.doc:
                return "reading the lab…"
            for c in self.doc["cards"]:
                if a in (c["id"], c["title"].lower()):
                    self.drill, self.drill_node = c["id"], None
                    self.built_at = None
                    return f"showing {c['title']}"
            nodes = self.card("nodes")
            for i in (nodes or {}).get("items", []):
                if a and a in str(i.get("name")).lower():
                    self.drill, self.drill_node = "nodes", i["name"]
                    self.fly_to(f"node:{i['name']}", 1.0)
                    self.built_at = None
                    return f"showing {i['name']}"
            return f"no card or node {args}"
        return "lab verbs: focus <card or node>, clear (open and close: bromigos-live lab open|close)"

    # ------------------------------------------------------------------ layout of the orbit
    def _nodes(self):
        c = self.card("nodes")
        return list((c or {}).get("items", []))

    def _gpus_by_host(self):
        out = {}
        for g in (self.card("gpus") or {}).get("items", []):
            out.setdefault(g.get("host"), []).append(g)
        return out

    def _positions(self, names):
        n = max(len(names), 1)
        pos = {}
        for i, name in enumerate(names):
            a = -math.pi / 2 + i * TAU / n
            pos[name] = (1.02 * math.cos(a), 0.10 * math.sin(i * 1.7), 1.02 * math.sin(a))
        return pos

    # ------------------------------------------------------------------ build
    def rebuild_due(self, t):
        if self.built_at is None:
            return True
        busy = any(g.get("busy") for g in (self.card("gpus") or {}).get("items", []))
        return t - self.built_at >= (0.12 if busy and not self.reduced else self.rebuild_every)

    def build(self, b, d, t):
        T = 0.05
        doc = self.doc or {}
        when = time.strftime("%H:%M:%S", time.localtime(doc.get("generatedAt") or time.time()))
        n_src = len({x for c in doc.get("cards", []) for x in c.get("sources") or []})
        self.header(b, f"LIVE: BROMIGOS LAB STATUS · {n_src} SOURCES · READ {when}" if doc else "READING THE LAB…")
        x, y, w, h = self.L["panel"]
        st = doc.get("state", "empty")
        frame_panel(b, x, y, w, h, "THE RACK", T + 0.05,
                    sub={"ok": "ALL WELL", "warn": "SOMETHING TO LOOK AT", "crit": "NEEDS ATTENTION",
                         "unreachable": "SOMETHING DOESN'T ANSWER"}.get(st, "NO LAB CONNECTED" if doc else "READING…"))
        if not doc:
            b.text(self.err.upper() or "READING THE LAB…", x + w / 2, y + h / 2, col("dim"), font="m", track=2,
                   align="c")
            self._side(b, t, T)
            return
        if not doc.get("configured", True):
            b.text("NO HOMELAB CONNECTED · BROMIGOS LAB CONNECT", x + w / 2, y + h / 2, col("amber"), font="m",
                   track=2, align="c")
            self._side(b, t, T)
            return
        pts, ids = [], []
        self._orbit(b, t, T, pts, ids)
        if self.hv is None:
            self._wire_rack(b, t, T, pts, ids)
        self._alerts_ring(b, t, T)
        self._gauges(b, t, T)
        self._queue_lane(b, t, T)
        self.pick_pts = np.array(pts, np.float32).reshape(-1, 3)
        self.pick_ids = ids
        if self.hover and self.hover.startswith(("node:", "part:")):
            lab, lines, hint = self._describe(self.hover)
            self.hover_tip(b, lab, lines, hint)
        self._rack_tip(b)
        self._side(b, t, T)

    def _orbit(self, b, t, T, pts, ids):
        s = self.s
        nodes = self._nodes()
        gpus = self._gpus_by_host()
        pos = self._positions([n["name"] for n in nodes])
        # the orbit and a faint inner deck ring
        for r, a in ((1.02, 0.95), (0.72, 0.55)):
            ring = [(r * math.cos(k / 96 * TAU), 0.0, r * math.sin(k / 96 * TAU)) for k in range(97)]
            for k in range(96):
                b.line(ring[k], ring[k + 1], col("guard", a), space=2, reveal=T + 0.1 + k * 0.003)
        hub = (0.0, -0.05, 0.0)
        groups = {}
        pr = self.stage.painter
        cx0 = self.L["center"][0]
        for i, n in enumerate(nodes):
            p = pos[n["name"]]
            left = glkit.project([p], pr.rot[2], pr.ctr[2])[0][0] < cx0      # labels away from the rack
            al, dx = ("r", -22 * s) if left else ("l", 22 * s)
            c = COLOUR.get(n.get("state"), "dim")
            sel = self.drill_node == n["name"]
            r = T + 0.3 + i * 0.06
            b.line(hub, p, col("guard", 0.8), space=2, dash=5, reveal=r)
            gadgets_box(b, p, 0.055, 0.032, 0.04, col(c, 0.95), reveal=r)
            b.arc(p, 13 * s, 14.5 * s, 0, TAU, col(c, 0.9 if sel else 0.6), segs=12, gap=0.35,
                  spin=0.4 if i % 2 else -0.4, space=2, reveal=r)
            if n.get("state") in ("warn", "crit"):
                b.arc(p, 20 * s, 21.5 * s, 0, TAU, col(c, 0.85), segs=3, gap=0.5, spin=1.2, space=2, reveal=r)
            b.text(ascii_(n["name"], 18).upper(), *p[:2], col("white" if sel else "soft"), font="s", track=1.5,
                   space=2, z=p[2], dx=dx, dy=-6 * s, align=al, reveal=r + 0.1, type_rate=0.012)
            sub = (f"CPU {n.get('cpu_pct') or 0:.0f}%  MEM {n.get('mem_pct') or 0:.0f}%  DISK {n.get('disk_pct') or 0:.0f}%"
                   if n.get("cpu_pct") is not None else ("DOWN" if n.get("up") is False else "UP"))
            b.text(sub, *p[:2], col(c, 0.95), font="xs", track=0.8, space=2, z=p[2], dx=dx, dy=11 * s, align=al,
                   reveal=r + 0.15)
            pts.append(p)
            ids.append(f"node:{n['name']}")
            # its GPUs: a VRAM ring each (spinning while busy), what holds it under the label
            for k, g in enumerate(gpus.get(n["name"], [])):
                gr = (24 + 9 * k) * s
                frac = (g["vram_used"] / g["vram_total"]) if g.get("vram_used") and g.get("vram_total") else 0
                gc = COLOUR.get(g.get("state"), "phosphor")
                b.arc(p, gr, gr + 4 * s, 0, TAU, col("guard", 0.9), segs=36, gap=0.25, space=2, reveal=r + 0.2)
                b.arc(p, gr, gr + 4 * s, 0, max(frac, 0.01) * TAU, col(gc, 1.0 if g.get("busy") else 0.8), segs=36,
                      gap=0.25, spin=(1.6 if g.get("busy") and not self.reduced else 0.0), space=2, reveal=r + 0.3)
                holds = ascii_((g.get("holds") or "").split(" (")[0], 34 if left else 46).upper()
                b.text(f"{ascii_(g['name'], 12).upper()}  {ascii_(g.get('vram') or '', 26).upper()}", *p[:2],
                       col(gc), font="xs", track=0.8, space=2, z=p[2], dx=dx, dy=(28 + 32 * k) * s, align=al,
                       reveal=r + 0.35)
                if holds and holds != "-":
                    b.text(holds, *p[:2], col("dim"), font="xs", track=0.5, space=2, z=p[2], dx=dx,
                           dy=(44 + 32 * k) * s, align=al, reveal=r + 0.4)
                if g.get("group"):
                    groups.setdefault(g["group"], []).append(p)
        # a model served across GPUs: a beam between its nodes, packets riding it
        for gname, ps in groups.items():
            for a_, z_ in zip(ps, ps[1:]):
                b.line(a_, z_, col("cyan", 0.85), width=1.8, space=2, reveal=T + 0.8)
                for k in range(3):
                    b.arc(a_, 0, 2.6 * s, 0, TAU, col("cyan", 0.95), kind=2, space=2, end=z_, speed=0.35,
                          phase=k / 3, reveal=T + 0.9)
                mid = tuple((u + v) / 2 for u, v in zip(a_, z_))
                left = glkit.project([mid], pr.rot[2], pr.ctr[2])[0][0] < cx0
                b.text(ascii_(gname, 40).upper() + " · TENSOR PARALLEL", *mid[:2], col("cyan"), font="xs", track=1,
                       space=2, z=mid[2], dx=-14 * s if left else 14 * s, dy=-10 * s, align="r" if left else "l",
                       reveal=T + 1.0)

    def _wire_rack(self, b, t, T, pts, ids):
        """The rack without VECTOR's renderer: six shelves, lit the same way."""
        if not self.doc:
            return
        parts = [("switch", 0.86, 0.99), ("nodes", 0.56, 0.84), ("gpu", 0.40, 0.56), ("storage", 0.24, 0.40),
                 ("ups", 0.07, 0.24)]

        class _P:
            parts = [{"id": p[0]} for p in parts] + [{"id": "frame"}]
        rd = self._rack_readings(_P) or []
        H_, W_ = 0.62, 0.22
        for k, (pid, y0, y1) in enumerate(parts):
            lv = rd[k][0] if k < len(rd) else "off"
            c = col({"ok": "phosphor", "warn": "amber", "crit": "danger"}.get(lv, "dim"), 0.9)
            cy = -0.3 + (y0 + y1) / 2 * H_
            gadgets_box(b, (0.0, cy, 0.0), W_, (y1 - y0) / 2 * H_ * 0.9, 0.16, c, reveal=T + 0.2 + k * 0.05)
            pts.append((W_ + 0.02, cy, 0.0))
            ids.append(f"part:{pid}")
        lv = rd[5][0] if len(rd) > 5 else "off"
        gadgets_box(b, (0.0, -0.3 + H_ / 2, 0.0), W_ + 0.03, H_ / 2 + 0.03, 0.19,
                    col({"ok": "dim", "warn": "amber", "crit": "danger"}.get(lv, "guard"), 0.8), reveal=T + 0.1)

    def _alerts_ring(self, b, t, T):
        al = self.card("alerts")
        firing = [i for i in (al or {}).get("items", []) if i.get("firing") == "firing"]
        if not firing:
            return
        s = self.s
        cx, cy, _ = self.L["center"]
        crit = any(i.get("state") == "crit" for i in firing)
        c = "danger" if crit else "amber"
        b.arc((cx, cy - 20 * s), 300 * s, 302 * s, 0, TAU, col(c, 0.7), segs=24, gap=0.4,
              spin=0.0 if self.reduced else 0.25, reveal=T + 0.4)
        b.text(f"{len(firing)} ALERT{'S' if len(firing) != 1 else ''} FIRING: " +
               ascii_(", ".join(i.get("name") or "?" for i in firing[:3]), 60).upper(),
               cx, cy - 340 * s, col(c), font="s", track=1.5, align="c", reveal=T + 0.5)

    def _gauges(self, b, t, T):
        """A row of dials under the rack: nodes up, the biggest GPU's VRAM, GitOps apps healthy,
        the fullest disk, alerts. Each is its card at a glance; hover says what, click drills in."""
        s = self.s
        x, y, w, h = self.L["panel"]
        self.gauge_hits = []
        dials = []
        nodes = self.card("nodes")
        if nodes and nodes["items"]:
            up = sum(1 for i in nodes["items"] if i.get("up") is not False)
            dials.append(("nodes", "NODES UP", up / len(nodes["items"]), f"{up}/{len(nodes['items'])}", nodes))
        gpus = self.card("gpus")
        big = max((i for i in (gpus or {}).get("items", []) if i.get("vram_total") and not i.get("unified")),
                  key=lambda i: i["vram_total"], default=None)
        if big:
            dials.append(("gpus", f"{ascii_(big['name'], 10).upper()} VRAM", big["vram_used"] / big["vram_total"],
                          f"{big['vram_used'] / 2**30:.1f}G", gpus))
        dep = self.card("deployments")
        if dep and dep["items"]:
            ok = sum(1 for i in dep["items"] if i.get("state") == "ok")
            dials.append(("deployments", "GITOPS HEALTHY", ok / len(dep["items"]), f"{ok}/{len(dep['items'])}", dep))
        sto = self.card("storage")
        if sto and sto["items"]:
            full = sto["items"][0]
            dials.append(("storage", "FULLEST DISK", (full.get("used_pct") or 0) / 100,
                          f"{full.get('used_pct') or 0:.0f}%", sto))
        al = self.card("alerts")
        if al:
            firing = sum(1 for i in al["items"] if i.get("firing") == "firing")
            dials.append(("alerts", "ALERTS FIRING", min(firing / 5.0, 1.0), f"{firing}", al))
        if not dials:
            return
        r = 54 * s
        gap = (w - 120 * s) / max(len(dials), 1)
        gy = y + h - 230 * s
        for k, (cid, label, frac, val, c) in enumerate(dials):
            gx = x + 60 * s + gap * (k + 0.5)
            cc = COLOUR.get(c["state"], "phosphor")
            hov = self.gauge_hover == cid
            rv = T + 0.6 + k * 0.08
            b.disc_plate((gx, gy), r + 16 * s, 0.82)
            b.arc((gx, gy), r + 8 * s, r + 9 * s, 0, TAU, col("dim", 0.8), reveal=rv)
            b.arc((gx, gy), r + 4 * s, r + 7 * s, 0, TAU, col("dim", 0.6), segs=48, gap=0.7, spin=0.02, reveal=rv)
            b.arc((gx, gy), r - 10 * s, r, 0, TAU, col("guard", 0.7), segs=40, gap=0.22, reveal=rv)
            b.arc((gx, gy), r - 10 * s, r, -math.pi / 2, -math.pi / 2 + max(frac, 0.004) * TAU,
                  col(cc, 1.0 if hov else 0.9), segs=40, gap=0.22, reveal=rv + 0.15)
            b.text(val, gx, gy + 8 * s, col("white" if hov else "soft"), font="l", track=0.5, align="c",
                   reveal=rv + 0.2)
            b.text(label, gx, gy + r + 34 * s, col(cc if cc != "phosphor" else "dim"), font="xs", track=1.8,
                   align="c", reveal=rv + 0.25)
            self.gauge_hits.append((gx, gy, r + 16 * s, cid, f"{c['title']}: {c.get('summary') or ''}. "
                                    f"{c.get('hint') or ''}"))
        if self.gauge_hover:
            hit = next((g for g in self.gauge_hits if g[3] == self.gauge_hover), None)
            if hit:
                lines = wrap(ascii_(hit[4]), 64)[:4] + ["CLICK TO DRILL IN"]
                tw, th = 560 * s, (18 + 18 * len(lines)) * s
                tx = min(max(hit[0] - tw / 2, x + 10 * s), x + w - tw - 10 * s)
                ty = hit[1] - hit[2] - th - 10 * s
                b.plate(tx, ty, tw, th, 0.95)
                b.brackets(tx, ty, tw, th, col("soft"), l=8)
                for k, ln in enumerate(lines):
                    b.text(ln.upper() if k == len(lines) - 1 else ln, tx + 12 * s, ty + 22 * s + k * 18 * s,
                           col("dim" if k == len(lines) - 1 else "soft"), font="xs", track=0.4)

    def _gauge_at(self, x, y):
        return next((g[3] for g in self.gauge_hits if math.hypot(x - g[0], y - g[1]) <= g[2]), None)

    def _queue_lane(self, b, t, T):
        """The media GPU's VRAM and the job queue, along the bottom of the panel."""
        s = self.s
        x, y, w, h = self.L["panel"]
        lx, ly, lw = x + 24 * s, y + h - 96 * s, w - 48 * s
        b.plate(lx - 8 * s, ly - 34 * s, lw + 16 * s, 118 * s, 0.86)
        b.text("THE GPU QUEUE", lx, ly - 12 * s, col("soft"), font="s", track=2.5, reveal=T + 0.6)
        v = self.view
        bw = 520 * s
        if v and v.get("total"):
            tot = float(v["total"])
            used = max(0.0, tot - v["free"] - v.get("holds", 0))
            seg = [("held by others", used, "static"), ("comfyui holds", v.get("holds", 0), "soft"),
                   ("kept for the voice service", min(self.reserve, v["free"]), "amber"),
                   ("free for a job", max(0.0, v["free"] - self.reserve), "phosphor")]
            bx = lx
            for label, mib, c in seg:
                ww = bw * mib / tot
                if ww > 0.5:
                    b.line((bx, ly + 18 * s), (bx + ww, ly + 18 * s), col(c, 0.95), width=9 * s)
                bx += ww
            b.rect(lx - 2 * s, ly + 11 * s, bw + 4 * s, 14 * s, col("dim", 0.7))
            b.text(f"{v.get('source', 'GPU').upper()} VRAM  {(tot - v['free']) / 1024:.1f} / {tot / 1024:.1f} GIB  ·  "
                   f"{max(0.0, v['free'] - self.reserve) / 1024:.1f} FREE FOR A JOB  ·  "
                   f"{self.reserve / 1024:.1f} KEPT FOR THE VOICE", lx, ly + 46 * s, col("dim"), font="xs", track=1)
        else:
            b.text("THE QUEUE'S SERVICE ISN'T RUNNING · BROMIGOS LAB RUN STARTS IT", lx, ly + 22 * s, col("dim"),
                   font="xs", track=1.2)
        jx = lx + bw + 40 * s
        live = [j for j in self.jobs if j["state"] in ("running", "waiting", "queued")]
        done = [j for j in self.jobs if j["state"] not in ("running", "waiting", "queued")][:max(0, 5 - len(live))]
        if not live and not done:
            b.text("NO JOBS YET · BROMIGOS LAB RUN IMAGE --PROMPT ...", jx, ly + 22 * s, col("dim"), font="xs", track=1)
        for k, j in enumerate((live + done)[:6]):
            cx = jx + k * 160 * s + 20 * s
            cy = ly + 18 * s
            stt = j["state"]
            c = {"running": "phosphor", "waiting": "amber", "queued": "dim", "succeeded": "soft", "failed": "danger",
                 "cancelled": "static"}.get(stt, "dim")
            b.arc((cx, cy), 13 * s, 15 * s, 0, TAU, col("guard", 0.9))
            frac = j.get("progress") or (1.0 if stt == "succeeded" else 0.0)
            if stt == "running":
                b.arc((cx, cy), 13 * s, 15 * s, 0, max(frac, 0.04) * TAU, col(c), spin=0.0)
                b.arc((cx, cy), 18 * s, 19 * s, 0, TAU, col(c, 0.6), segs=6, gap=0.5,
                      spin=0.0 if self.reduced else 0.9)
            else:
                b.arc((cx, cy), 13 * s, 15 * s, 0, TAU * (1.0 if stt in ("succeeded", "failed") else 0.25), col(c, 0.9))
            b.arc((cx, cy), 0, 4 * s, 0, TAU, col(c), kind=2)
            b.text(ascii_(j.get("preset") or j["kind"], 14).upper(), cx + 24 * s, cy - 2 * s, col(c), font="xs", track=1)
            sub = (f"{int(frac * 100)}% {j.get('progress_text') or ''}" if stt == "running" else stt)
            b.text(ascii_(sub, 16).upper(), cx + 24 * s, cy + 14 * s, col("dim"), font="xs", track=0.8)

    # ------------------------------------------------------------------ hover readouts
    def _describe(self, ident):
        if ident.startswith("node:"):
            name = ident[5:]
            n = next((i for i in self._nodes() if i["name"] == name), {})
            lines = [n.get("hint") or ""]
            for g in self._gpus_by_host().get(name, []):
                lines.append(f"{g['name']}: {g.get('vram')}, {g.get('temp_c') or 0:.0f} C, {g.get('power_w') or 0:.0f} W")
            return name, lines, "CLICK: THE NODES CARD, THIS NODE FIRST"
        pid = ident[5:]
        c = self.card(PART_CARD.get(pid, ""))
        return PART_WHAT.get(pid, pid), [c["summary"]] if c else ["nothing reports it"], "CLICK TO DRILL IN"

    def _rack_tip(self, b):
        i = self.hv_hover
        if self.hv is None or i is None or self.hv.stage is None or i >= len(self.hv.stage.parts):
            return
        s = self.s
        label, level, lines, hint = self.hv.reading(i)
        pid = self.hv.stage.parts[i].get("id")
        c = {"ok": "phosphor", "warn": "amber", "crit": "danger"}.get(level, "static")
        rx, ry, rw, rh = self._rack_rect()
        tw = 520 * s
        th = (64 + 20 * min(len(lines), 3)) * s
        px, py = rx + rw - 30 * s, ry + 40 * s
        b.plate(px, py, tw, th, 0.93)
        b.brackets(px, py, tw, th, col(c), l=10)
        b.text(f"{label} · {PART_WHAT.get(pid, '')}"[:52], px + 12 * s, py + 24 * s, col("white"), font="s", track=1.2)
        for k, ln in enumerate(lines[:3]):
            b.text(ascii_(ln, 60).upper(), px + 12 * s, py + 46 * s + k * 20 * s, col(c), font="xs", track=0.6)
        b.text("CLICK TO DRILL IN", px + 12 * s, py + th - 10 * s, col("dim"), font="xs", track=1)

    # ------------------------------------------------------------------ the side panel: cards, or one card
    def _side(self, b, t, T):
        s = self.s
        x, y, w, h = self.L["side"]
        self.side_rows = []
        doc = self.doc or {}
        if self.drill and self.card(self.drill):
            c = self.card(self.drill)
            frame_panel(b, x, y, w, h, ascii_(c["title"], 30).upper(), T + 0.1, sub="< ALL CARDS")
            self.side_rows.append((y, y + 40 * s, "back", None, "Back to every card"))
            yy = y + 66 * s
            for ln in wrap(ascii_(c.get("summary") or "").upper(), 62)[:2]:
                b.text(ln, x + 18 * s, yy, col(COLOUR.get(c["state"], "soft")), font="s", track=0.8)
                yy += 22 * s
            for ln in wrap(ascii_(c.get("hint") or ""), 78)[:3]:
                b.text(ln, x + 18 * s, yy, col("dim"), font="xs", track=0.3)
                yy += 17 * s
            yy += 10 * s
            cols = [k for k in (c.get("columns") or []) if k not in ("state", "name")][:3]
            items = list(c.get("items", []))
            if self.drill_node:
                items.sort(key=lambda i: i.get("name") != self.drill_node)
            for k, it in enumerate(items[:22]):
                hov = self.side_hover == ("item", k)
                cc = COLOUR.get(it.get("state"), "dim")
                if hov or it.get("name") == self.drill_node:
                    b.plate(x + 8 * s, yy - 16 * s, w - 16 * s, 38 * s, 0.95)
                b.arc((x + 24 * s, yy - 5 * s), 0, 4 * s, 0, TAU, col(cc), kind=2)
                b.text(ascii_(it.get("name"), 30).upper(), x + 38 * s, yy, col("white" if hov else "soft"), font="xs",
                       track=0.8)
                vals = "  ".join(ascii_(_cell(it.get(k_)), 28) for k_ in cols if it.get(k_) not in (None, "", "-"))
                b.text(vals.upper()[:84], x + 38 * s, yy + 16 * s, col("dim"), font="xs", track=0.4)
                self.side_rows.append((yy - 16 * s, yy + 22 * s, "item", k, it.get("hint") or vals))
                yy += 42 * s
                if yy > y + h - 60 * s:
                    break
            for src, e in (c.get("errors") or {}).items():
                if yy > y + h - 40 * s:
                    break
                b.text(f"{ascii_(src, 20).upper()}: {ascii_(e, 44).upper()}", x + 18 * s, yy, col("danger"), font="xs",
                       track=0.5)
                yy += 20 * s
            if not items and not c.get("errors"):
                b.text("NOTHING HERE", x + 18 * s, yy, col("dim"), font="xs", track=2)
        else:
            frame_panel(b, x, y, w, h, "THE LAB", T + 0.1, sub="CLICK A CARD")
            yy = y + 72 * s
            for k, c in enumerate(doc.get("cards", [])):
                hov = self.side_hover == ("card", c["id"])
                cc = COLOUR.get(c["state"], "dim")
                if hov:
                    b.plate(x + 8 * s, yy - 18 * s, w - 16 * s, 44 * s, 0.95)
                b.arc((x + 24 * s, yy - 6 * s), 0, 5 * s, 0, TAU, col(cc), kind=2, reveal=T + 0.3 + k * 0.04)
                if c["state"] in ("warn", "crit", "unreachable"):
                    b.arc((x + 24 * s, yy - 6 * s), 9 * s, 10 * s, 0, TAU, col(cc, 0.8), segs=4, gap=0.4,
                          spin=0.0 if self.reduced else 0.8)
                b.text(ascii_(c["title"], 26).upper(), x + 42 * s, yy, col("white" if hov else "soft"), font="s",
                       track=1.5, reveal=T + 0.3 + k * 0.04)
                b.text(ascii_(c.get("summary") or "", 70).upper(), x + 42 * s, yy + 18 * s, col(cc if cc != "phosphor"
                                                                                                else "dim"),
                       font="xs", track=0.5, reveal=T + 0.35 + k * 0.04)
                self.side_rows.append((yy - 18 * s, yy + 26 * s, "card", c["id"], c.get("hint") or ""))
                yy += 50 * s
                if yy > y + h - 40 * s:
                    break
        if self.side_hover is not None:
            row = next((r for r in self.side_rows if (r[2], r[3]) == self.side_hover), None)
            if row and row[4]:
                lines = wrap(ascii_(row[4]), 70)[:4]
                tw, th = w - 30 * s, (20 + 18 * len(lines)) * s
                ty = min(row[1] + 6 * s, y + h - th - 6 * s)
                b.plate(x + 15 * s, ty, tw, th, 0.96)
                b.brackets(x + 15 * s, ty, tw, th, col("soft"), l=8)
                for k, ln in enumerate(lines):
                    b.text(ln, x + 26 * s, ty + 22 * s + k * 18 * s, col("soft"), font="xs", track=0.3)

    def _card_index(self, cid):
        return next((k for k, c in enumerate((self.doc or {}).get("cards", [])) if c["id"] == cid), None)

    # ------------------------------------------------------------------ input
    def _in_side(self, x, y):
        sx, sy, sw, sh = self.L["side"]
        return sx <= x <= sx + sw and sy <= y <= sy + sh

    def _side_row(self, y):
        return next((r for r in self.side_rows if r[0] <= y <= r[1]), None)

    def side_click(self, x, y):
        if not self._in_side(x, y):
            return False
        r = self._side_row(y)
        if not r:
            return True
        if r[2] == "back":
            self.drill = self.drill_node = None
        elif r[2] == "card":
            self.drill, self.drill_node = r[3], None
        self.side_hover = None
        return True

    def _rack_rect(self):
        s = self.s
        cx, cy, _ = self.L["center"]
        return (cx - 270 * s, cy - 400 * s, 540 * s, 720 * s)

    def motion(self, x, y, buttons):
        if self._in_side(x, y) and not self.drag:
            r = self._side_row(y)
            hv = (r[2], r[3]) if r and r[2] in ("item", "card") else None
            if hv != self.side_hover:
                self.side_hover = hv
                self.built_at = None
            return
        if self.side_hover is not None:
            self.side_hover = None
            self.built_at = None
        g = None if self.drag else self._gauge_at(x, y)
        if g != self.gauge_hover:
            self.gauge_hover = g
            self.built_at = None
        if g:
            return
        if self.hv is not None and not self.drag:
            rx, ry, rw, rh = self._rack_rect()
            i = self.hv.pick(x - rx, y - ry) if (rx <= x <= rx + rw and ry <= y <= ry + rh) else None
            if i != self.hv_hover:
                self.hv_hover = i
                self.hv.hover(i)
                self.built_at = None
            if i is not None:
                self.last_input = self.now()
                return
        super().motion(x, y, buttons)

    def release(self, x, y):
        clicked = self.drag and not self.drag[4]
        g = self._gauge_at(x, y) if clicked else None
        if g:
            self.drill, self.drill_node = g, None
            self.drag = None
            self.built_at = None
            return
        if clicked and self.hv is not None and self.hv_hover is not None and self.hv.stage is not None:
            pid = self.hv.stage.parts[self.hv_hover].get("id")
            self.drill, self.drill_node = PART_CARD.get(pid), None
            self.drag = None
            self.built_at = None
            return
        if clicked:
            n = self.pick(x, y)
            if n and n.startswith("node:"):
                self.drill, self.drill_node = "nodes", n[5:]
                self.drag = None
                self.built_at = None
                return
            if n and n.startswith("part:"):
                self.drill, self.drill_node = PART_CARD.get(n[5:]), None
                self.drag = None
                self.built_at = None
                return
        super().release(x, y)

    def extra_key(self, name):
        if name in ("BackSpace", "Left") and self.drill:
            self.drill = self.drill_node = None
            self.built_at = None
        elif name in ("r", "R"):
            threading.Thread(target=self._read_status, daemon=True).start()
            self.toast = ("reading the lab again", self.now(), "soft")
        return True

    # ------------------------------------------------------------------ the rack hologram
    def animate(self, t, d):
        if self.hv is not None:
            _, _, rw, rh = self._rack_rect()
            self.hv.render(rw, rh, t)

    def post_composite(self, u):
        if self.hv is not None and self.hv.target is not None:
            self.hv.composite((float(self.w), float(self.h)), self._rack_rect(), u.get("fade", 1.0))

    def close(self):
        super().close()


def _cell(v):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.1f}"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v)


def gadgets_box(b, c, sx, sy, sz, color, space=2, reveal=0.0):
    """A wireframe box (a node, a shelf) in the deck's 3D space."""
    x, y, z = c
    v = [(x + dx * sx, y + dy * sy, z + dz * sz) for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)]
    for a, b_ in ((0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)):
        b.line(v[a], v[b_], color, space=space, reveal=reveal)


_ = gadgets
DECK = LabDeck
