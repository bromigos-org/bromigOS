"""The LAB panel: the lab snapshot at a glance (bromigos-homelab; docs/homelab.md).

Nodes, pods, Argo, alerts, services, storage: whatever the homelab's snapshot carries (a
Lab API's, or one assembled from the capabilities). Drawn with the widgets' own
primitives (draw.py), like every panel. It exists only when homelab.toml has a snapshot
source (homelab_panels.py decides); a source that's down reads "LAB UNREACHABLE".
"""
import importlib.util
import math
import os
import threading
import time
import urllib.error

import draw as D
import sources as S
from panels import Panel, copy_text, open_url

import bromigos_homelab as H


OBJECT_STORE = "rustfs"                  # the object store's service id, and its namespace


def store_share(nas):
    """The NAS share that holds the object store's volumes, found in the snapshot (each share
    lists the claims bound on it, as namespace/name), or None. The share's name is the lab's
    own; nothing here knows it."""
    for sh in nas.get("shares") or []:
        claims = [v.get("claim") or "" for v in sh.get("volumes") or []]
        if sh.get("usage") is not None and any(c.split("/", 1)[0] == OBJECT_STORE for c in claims):
            return sh
    return None


def disk_node(nd, i):
    """A node disk's node, as the snapshot names it: its node, else its hostname, instance
    (without the port), address or label; else "node N" (its place in the list), never "?"."""
    for k in ("node", "hostname", "host", "instance", "address", "label", "name"):
        v = str(nd.get(k) or "").strip()
        if k == "instance" and v.count(":") == 1:
            v = v.split(":", 1)[0]
        if v and v.lower() not in ("?", "unknown", "none", "null", "-"):
            return v
    return f"node {i + 1}"


class LabSource(threading.Thread):
    """Polls the snapshot every `every` s. state: 'ok' | 'stale' | 'unauthorized' | 'down'."""

    def __init__(self, every=20, on_update=None):
        super().__init__(daemon=True)
        self.every = every
        self.on_update = on_update
        self.data = None
        self.state = "down"
        self.error = ""
        self.fetched = 0
        self.where = H.snapshot_source() or "none"

    def run(self):
        while True:
            self.poll()
            time.sleep(self.every)

    def poll(self):
        self.where = H.snapshot_source() or "none"
        try:
            d = H.snapshot()
            if d is None:
                self.state, self.error = "down", "nothing in homelab.toml provides a snapshot"
                return
            self.data = d
            self.fetched = time.time()
            age = time.time() - float(d.get("generatedAt") or 0)
            self.state = "stale" if age > 120 else "ok"
            self.error = ""
        except urllib.error.HTTPError as e:
            self.state = "unauthorized" if e.code in (401, 403) else "down"
            self.error = f"HTTP {e.code}"
        except (OSError, ValueError) as e:
            self.state, self.error = "down", str(e)[:80]
        if self.on_update:
            self.on_update()


class LabPanel(Panel):
    name, title = "lab", "LAB"
    description = "Your homelab at a glance: hosts, workloads, deployments, models and alerts"
    category, reads = "homelab", "your homelab's sources"
    height = 640
    sizes = {"compact": ((240, 100), (460, 200), (320, 120)),
             "standard": ((420, 600), (780, 1200), (470, 640)),
             "large": ((820, 520), (1500, 1200), (980, 700))}
    interval = 1.0                       # redraw cadence for the freshness clock; data every 20 s
    fit = "content"                      # as tall as the lab it shows (natural_height)

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg)
        src = H.source_of("lab")
        label = (src.opts.get("title") if src else None) or (self.cfg or {}).get("label")
        self.title = f"LAB · {label.upper()}" if label else "LAB"
        self.lab = LabSource(every=20, on_update=self._new)
        self.pulse_at = 0
        self._wake = wake
        self.drawn = "standard"
        self.lab.start()

    def _new(self):
        self.pulse_at = time.time()
        if self._wake:
            self._wake(self)

    @property
    def animating(self):
        # the hologram turns at the large size (the heartbeat redraws it at 10 fps, and not
        # at all while it's hidden or covered); reduced motion holds it still
        spin = self.drawn == "large" and D.T.motion() == "full" and self.lab.state in ("ok", "stale")
        return spin or time.time() - self.pulse_at < 1.6

    @animating.setter
    def animating(self, _v):
        pass

    def draw(self, cr, w, h):
        L, d = self.lab, self.lab.data
        age = time.time() - L.fetched if L.fetched else None
        state_txt = {"ok": f"SYNC {int(age)}s AGO" if age is not None else "SYNC",
                     "stale": "SNAPSHOT STALE", "no-token": "NO TOKEN",
                     "unauthorized": "TOKEN REFUSED", "down": "LAB UNREACHABLE"}[L.state]
        state_col = {"ok": "static", "stale": "amber"}.get(L.state, "danger")
        top = D.frame(cr, w, h, self.title, state_txt, state_col)
        if L.state == "ok":
            pulse = max(0.0, 1 - (time.time() - self.pulse_at) / 1.6)
            tw = D.layout(cr, state_txt.upper(), 11, "semibold", 0.18).get_pixel_size()[0]
            D.dot(cr, w - 16 - tw - 10, 18, 2.5 + 2 * pulse, "phosphor", glow=True)
        self.region(0, 0, w, 34, f"The lab snapshot ({L.where}, every 20 s; homelab.toml). "
                    f"State: {L.state}{' - ' + L.error if L.error else ''}."
                    + (" Click to open the Lab." if H.lab_url() else ""),
                    (lambda: open_url(H.lab_url())) if H.lab_url() else None)
        x0, x1 = 16, w - 16
        self.drawn = self.size_class(w, h)
        if not d:
            D.text(cr, x0, top + 10, L.error or "waiting for the first snapshot", 12, "amber", width=x1 - x0)
            return
        if self.drawn == "compact":
            return self._summary(cr, d, x0, x1, top)
        if self.drawn == "large":
            side = min(h - top - 16, int(w * 0.48))
            self._hologram(cr, d, x0, top, side, h - top - 16)
            x0 = x0 + side + 20
        self._body(cr, d, x0, x1, top, h - self.BOTTOM)

    def _summary(self, cr, d, x0, x1, y):
        """The cluster in four numbers: nodes ready, pods, Argo apps healthy, alerts firing."""
        c = d.get("cluster", {})
        # --- summary strip
        alerts = int(c.get("alertsFiring") or 0)
        argo = d.get("argocd") or {}
        items = [
            ("NODES", f"{c.get('nodesReady', 0)}/{c.get('nodesTotal', 0)}",
             "phosphor" if c.get("nodesReady") == c.get("nodesTotal") else "amber",
             "Kubernetes nodes Ready / total"),
            ("PODS", f"{int(c.get('podsRunning') or 0)}", "danger" if c.get("podsNotRunning") else "phosphor",
             f"Pods running; {int(c.get('podsNotRunning') or 0)} not running"),
            ("ARGO", f"{argo.get('healthy', 0)}/{argo.get('total', 0)}",
             "phosphor" if argo.get("healthy") == argo.get("total") else "amber",
             "ArgoCD applications healthy / total. Click to open ArgoCD."),
            ("ALERTS", f"{alerts}", "amber" if alerts else "phosphor",
             "Prometheus alerts firing. Click to open Alertmanager."),
        ]
        acts = [None, None, lambda: open_url(self._svc_url(d, "argocd")),
                lambda: open_url(self._svc_url(d, "alertmanager"))]
        if (x1 - x0) / len(items) < 80:              # narrow: the three that say most
            items, acts = [items[0], items[1], items[3]], [acts[0], acts[1], acts[3]]
        cw = (x1 - x0) / len(items)
        for i, (k, v, col, tip) in enumerate(items):
            ix = x0 + i * cw
            D.label(cr, ix, y, k, "dim")
            D.text(cr, ix, y + 14, v, 20 if cw > 70 else 15, col, "bold", glow=True)
            self.region(ix, y, cw - 6, 40, tip, acts[i])
        return y + 50

    # ------------------------------------------------------------ fitting the room it has
    # The body's sections, under the summary strip. When they don't all fit, they fold to a
    # summary in this order (SERVICES to "36/36 UP" and the ones that aren't up, the node map
    # to one chip per node, STORAGE POOLS to one line); still too tall, the node map and then
    # SERVICES are left out. A section is never cut in half.
    SECTIONS = ("nodes", "services", "pools")
    FOLD = ("services", "nodes", "pools")
    DROP = ("nodes", "services")
    BOTTOM = 10                          # px kept under the last line

    def plan(self, cr, d, x0, x1, room):
        """{section: "full" | "fold" | None} that fits in `room` px under the summary strip
        (starting at its top), and the height it takes."""
        hs = {s: {m: self._section(cr, d, s, m, x0, x1, 0, draw=False) for m in ("full", "fold")}
              for s in self.SECTIONS}
        mode = {s: "full" for s in self.SECTIONS}

        def total():
            return 50 + sum(10 + hs[s][mode[s]] for s in self.SECTIONS if mode[s])
        for s in self.FOLD:
            if total() <= room:
                break
            mode[s] = "fold"
        for s in self.DROP:
            if total() <= room:
                break
            mode[s] = None
        return mode, total()

    def natural_height(self, width, cls=None):
        """Everything in full: the summary strip and each section's own height at this width
        (at the large size, beside the hologram, and never shorter than the class allows)."""
        d = self.lab.data
        cls = cls or self.size_class(width, self.height)
        if not d or cls == "compact":
            return None if not d else 44 + 50 + self.BOTTOM
        import cairo
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4))
        x0, x1 = 16, width - 16
        if cls == "large":
            x0 += int(width * 0.48) + 20
        hs = sum(10 + self._section(cr, d, s, "full", x0, x1, 0, draw=False) for s in self.SECTIONS)
        return 44 + 50 + hs + self.BOTTOM

    def frame_height(self, width, cls, room):
        """Shrink unused space after whole sections have folded to fit the available room."""
        if not self.lab.data or cls == "compact":
            return room
        import cairo
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4))
        x0, x1 = 16, width - 16
        if cls == "large":
            return room                 # the hologram also needs this height
        _, need = self.plan(cr, self.lab.data, x0, x1, room - 44 - self.BOTTOM)
        return min(room, 44 + need + self.BOTTOM)

    def _section(self, cr, d, name, mode, x0, x1, y, draw=True):
        """One section from y, full or folded; the y under it."""
        return {"nodes": self._nodes, "services": self._services, "pools": self._pools}[name](
            cr, d, x0, x1, y, mode=mode, draw=draw) - y

    def _body(self, cr, d, x0, x1, y, bottom=None):
        mode, _need = self.plan(cr, d, x0, x1, (bottom or 10 ** 6) - y)
        self.folded = {s: m for s, m in mode.items() if m != "full"}
        y = self._summary(cr, d, x0, x1, y)
        for s in self.SECTIONS:
            if not mode[s]:
                continue
            D.rule(cr, x0, y, x1)
            y += 10
            y = self._section(cr, d, s, mode[s], x0, x1, y) + y
        return y

    # ------------------------------------------------------------ the hologram
    @staticmethod
    def _layout_module():
        """The live layer's constellation layout (live/live/constellation.py), the one the
        holo deck draws: loaded from its file alone, so the panels never start the live
        layer's package. None without bromigos-live."""
        here = os.path.dirname(os.path.realpath(__file__))
        for base in (os.path.join(os.path.dirname(os.path.dirname(here)), "live"), "/usr/lib/bromigos/live"):
            path = os.path.join(base, "live", "constellation.py")
            if os.path.isfile(path):
                spec = importlib.util.spec_from_file_location("bromigos_lab_constellation", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
        return None

    def _constellation(self, d):
        """(positions, links, the models' link) as the holo deck lays them out."""
        names = [n.get("name") for n in d.get("nodes") or [] if n.get("name")]
        if not hasattr(self, "_cmod"):
            try:
                self._cmod = self._layout_module()
            except Exception:
                self._cmod = None
        try:
            conf = H.config.table("constellation")
        except Exception:
            conf = {}
        if self._cmod:
            pos, links, ai = self._cmod.layout(names, conf)
            return dict(pos), links, ai, self._cmod.WAN
        pos = {}
        for i, n in enumerate(names):                    # without the live layer: a ring round the first
            if i == 0:
                pos[n] = (0.0, 0.08, 0.0)
                continue
            a = 2 * math.pi * (i - 1) / max(1, len(names) - 1) + 0.35
            yy = 0.72 * math.sin((i - 1) * 2.4 + 0.6)
            r = 0.9 * math.sqrt(max(0.0, 1 - yy * yy))
            pos[n] = (r * math.cos(a), yy, r * math.sin(a))
        hub = names[0] if names else None
        wan = ("uplink", (-0.15, -0.20, -0.95))
        return pos, [(hub, n) for n in names[1:]] + ([(hub, wan[0])] if hub else []), None, wan

    def _hologram(self, cr, d, x, y, w, h):
        """The lab's nodes as the holo deck's constellation: orbit shells, the links with
        packets that run faster as each node works harder, the uplink, and each node's
        health. It turns slowly (10 fps, only while shown); reduced motion holds it still."""
        motion = D.T.motion()
        t = time.time()
        spin = (t * 0.18) % (2 * math.pi) if motion == "full" else 0.6
        tilt = 0.38
        cx, cy = x + w / 2, y + h / 2 - 4
        scale = min(w, h - 40) * 0.40
        cs, sn, ct, st = math.cos(spin), math.sin(spin), math.cos(tilt), math.sin(tilt)

        def proj(p):
            px, py, pz = p
            px, pz = px * cs - pz * sn, px * sn + pz * cs           # turn about the vertical
            py, pz = py * ct - pz * st, py * st + pz * ct           # then tip toward the viewer
            k = 2.8 / (2.8 + pz)
            return cx + px * scale * k, cy - py * scale * k, pz, k
        D.src(cr, "void", 0.85)
        cr.rectangle(x, y, w, h)
        cr.fill()
        D.brackets(cr, x, y, w, h, 12, "dim", 1.2, 0.9)
        D.label(cr, x + 10, y + 8, "CONSTELLATION", "dim", size=10)
        D.label(cr, x + w / 2, y + h - 20, "PACKETS ∝ NODE CPU · UPLINK ∝ WAN TRAFFIC", "static", size=9,
                align="center")
        cr.save()
        cr.rectangle(x + 1, y + 24, w - 2, h - 48)
        cr.clip()
        cr.set_line_width(1)
        for tilt_k, r in ((0.0, 1.05), (1.2, 1.05), (2.2, 0.75)):     # the orbit shells, for depth
            c2, s2 = math.cos(tilt_k), math.sin(tilt_k)
            pts = [proj((math.cos(a) * r, -math.sin(a) * r * s2, math.sin(a) * r * c2))
                   for a in (i / 72 * 2 * math.pi for i in range(73))]
            D.src(cr, "guard", 0.9)
            cr.move_to(pts[0][0], pts[0][1])
            for p in pts[1:]:
                cr.line_to(p[0], p[1])
            cr.stroke()
        pos, links, ai_link, wan = self._constellation(d)
        pos = dict(pos)
        pos[wan[0]] = wan[1]
        nodes = {n.get("name"): n for n in d.get("nodes") or []}
        net = d.get("network") or (d.get("cluster") or {}).get("network") or {}
        ai = d.get("ai") or (d.get("cluster") or {}).get("ai") or {}
        for a, z in links:
            if a not in pos or z not in pos:
                continue
            pa, pz = proj(pos[a]), proj(pos[z])
            if z == wan[0]:
                act = min(((net.get("wanDownBps") or 0) + (net.get("wanUpBps") or 0)) / 50e6, 1.0)
                live = net.get("wanDownBps") is not None
            elif (a, z) == ai_link:
                act, live = min((ai.get("rpmNow") or 0) / 30.0, 1.0), ai.get("rpmNow") is not None
            else:
                n = nodes.get(z) or {}
                live = n.get("cpuPct") is not None
                act = min((n.get("cpuPct") or 0) / 60.0, 1.0)
            D.src(cr, "dim" if live else "guard", 0.9)
            cr.set_dash([] if live else [5, 4])
            cr.set_line_width(1.2)
            cr.move_to(pa[0], pa[1])
            cr.line_to(pz[0], pz[1])
            cr.stroke()
            cr.set_dash([])
            if live:                                   # packets, as many and as fast as the work
                npk = 1 + int(round(act * 4))
                speed = 0.12 + act * 0.55
                for k in range(npk):
                    f = ((t * speed if motion == "full" else 0) + k / npk) % 1.0
                    fwd = k % 2 == 0
                    s0, s1 = (pa, pz) if fwd else (pz, pa)
                    D.dot(cr, s0[0] + (s1[0] - s0[0]) * f, s0[1] + (s1[1] - s0[1]) * f, 2.2,
                          "soft" if fwd else "amber", glow=False)
        order = sorted(pos.items(), key=lambda kv: proj(kv[1])[2], reverse=True)   # far ones first
        for name, p in order:
            px, py, pz, k = proj(p)
            n = nodes.get(name)
            if name == wan[0]:
                col = "phosphor" if net.get("wanDownBps") is not None else "static"
                sub = (f"↓ {S.rate((net.get('wanDownBps') or 0) / 8)}  ↑ {S.rate((net.get('wanUpBps') or 0) / 8)}"
                       if net.get("wanDownBps") is not None else "NO READING")
            elif n is None:
                col, sub = "static", "NO TELEMETRY"
            else:
                cpu, mem = (n.get("cpuPct") or 0) / 100, (n.get("memPct") or 0) / 100
                col = max(D.level(cpu, 0.85, 0.95), D.level(mem, 0.9, 0.97),
                          key=["phosphor", "amber", "danger", "static"].index)
                sub = f"CPU {n.get('cpuPct', 0):.0f}%  MEM {n.get('memPct', 0):.0f}%"
            r = 4.5 * k
            D.dot(cr, px, py, r, col, glow=True)
            D.src(cr, col, 0.8)
            cr.set_line_width(1)
            cr.arc(px, py, r + 6 * k, 0, 2 * math.pi)
            cr.stroke()
            D.label(cr, px + 12, py - 12, name.replace("k8s-", ""), "soft", size=10)
            D.label(cr, px + 12, py + 2, sub, col if col != "phosphor" else "dim", size=9)
            if x <= px - 10 and px + 10 <= x + w and y <= py - 10 and py + 10 <= y + h:
                self.region(px - 10, py - 10, 20, 20, (f"The uplink: {sub.lower()}" if name == wan[0] else
                            f"Node {name}: " + (sub.lower() if n else "no telemetry") + ". Packets on its link "
                            "run faster as it works harder."))
        cr.restore()
        self.region(x, y, w, 22, "The lab's nodes as the holo deck's constellation: links carry packets in "
                    "proportion to each node's CPU, the uplink to the WAN traffic"
                    + ("." if motion == "full" else "; held still (reduced motion)."))

    def _svc_url(self, d, sid):
        for g in d.get("config", {}).get("groups", []):
            for s in g.get("services", []):
                if s.get("id") == sid:
                    return s.get("lan") or s.get("wan") or H.lab_url()
        dom = H.config.setting("services", "domain", "")
        return f"https://{sid}.{dom}" if dom else H.lab_url()

    @staticmethod
    def _node_name(nd):
        return (nd.get("name") or "?").replace("k8s-", "").upper()

    def _node_tip(self, nd):
        return (f"Node {nd.get('name')}: CPU {nd.get('cpuPct', 0):.0f}%, memory {nd.get('memPct', 0):.0f}%, load "
                f"{nd.get('load1', 0):.2f} on {nd.get('cores')} cores. Amber: memory past 90% or CPU past 85%.")

    @staticmethod
    def _node_worst(nd):
        cpu, mem = (nd.get("cpuPct") or 0) / 100, (nd.get("memPct") or 0) / 100
        return max(D.level(cpu, 0.85, 0.95), D.level(mem, 0.9, 0.97), key=["phosphor", "amber", "danger", "static"].index)

    def _node_grid(self, cr, nodes, width):
        """(columns, box width): as many boxes to a row as fit each node's whole name, the
        rows evened out (six nodes: two rows of three, not four and two)."""
        n = max(1, len(nodes))
        need = max([D.layout(cr, self._node_name(nd), 10, "semibold", 0.08).get_pixel_size()[0] + 28
                    for nd in nodes] + [104])
        k = n
        while k > 1 and (width - (k - 1) * 8) / k < need:
            k -= 1
        rows = math.ceil(n / k)
        k = math.ceil(n / rows)
        return k, (width - (k - 1) * 8) / k

    def _nodes(self, cr, d, x0, x1, y, mode="full", draw=True):
        nodes = d.get("nodes") or []
        cl = d.get("cluster", {})
        if draw:
            D.label(cr, x0, y, "NODE MAP", "dim")
            D.label(cr, x1, y, f"CLUSTER CPU {cl.get('cpuNow', 0):.0f}%", "static", align="right")
        y += 20
        if mode == "fold":
            return self._node_chips(cr, nodes, x0, x1, y, draw)
        k, bw = self._node_grid(cr, nodes, x1 - x0)
        pulse = max(0.0, 1 - (time.time() - self.pulse_at) / 1.6) if draw else 0
        rows = [nodes[i:i + k] for i in range(0, len(nodes), k)] or [[]]
        for r, row in enumerate(rows):
            bus_y = y + 4
            if draw:
                D.src(cr, "dim", 0.6)
                cr.set_line_width(1)
                cr.move_to(x0, bus_y + 0.5)
                cr.line_to(x1, bus_y + 0.5)
                cr.stroke()
            for i, nd in enumerate(row):
                if draw:
                    self._node_box(cr, nd, x0 + i * (bw + 8), bus_y, bw, pulse)
            y = bus_y + 10 + 76 + (12 if r == len(rows) - 1 else 6)
        return y

    def _node_box(self, cr, nd, bx, bus_y, bw, pulse):
        cx = bx + bw / 2
        cpu, mem = (nd.get("cpuPct") or 0) / 100, (nd.get("memPct") or 0) / 100
        worst = self._node_worst(nd)
        D.src(cr, "dim", 0.6)
        cr.move_to(cx + 0.5, bus_y)
        cr.line_to(cx + 0.5, bus_y + 10)
        cr.stroke()
        by = bus_y + 10
        D.src(cr, "void", 0.7)
        cr.rectangle(bx, by, bw, 76)
        cr.fill()
        D.brackets(cr, bx, by, bw, 76, 6, worst, 1.2, 0.9)
        D.dot(cr, bx + 9, by + 11, 2.5 + 1.5 * pulse, worst, glow=True)
        D.text(cr, bx + 18, by + 4, self._node_name(nd), 10, "soft", "semibold", spacing=0.08, width=bw - 22)
        D.label(cr, bx + 6, by + 25, "CPU", "dim", size=10)
        D.bar(cr, bx + 40, by + 30, bw - 46, 5, cpu, D.level(cpu, 0.85, 0.95))
        D.label(cr, bx + 6, by + 41, "MEM", "dim", size=10)
        D.bar(cr, bx + 40, by + 46, bw - 46, 5, mem, D.level(mem, 0.9, 0.97))
        D.label(cr, bx + 6, by + 57, f"L{nd.get('load1', 0):.1f} · {nd.get('cores', '?')}C", "static", size=10)
        self.region(bx, by, bw, 76, self._node_tip(nd))

    def _node_chips(self, cr, nodes, x0, x1, y, draw=True):
        """The node map folded: one chip per node, its health's colour and its name (whole
        when it fits the row), the readings in its hover hint."""
        cx, ch = x0, 20
        for nd in nodes:
            name = self._node_name(nd)
            cw = min(x1 - x0, D.layout(cr, name, 10, "semibold", 0.08).get_pixel_size()[0] + 26)
            if cx > x0 and cx + cw > x1:
                cx, y = x0, y + ch + 4
            if draw:
                col = self._node_worst(nd)
                D.src(cr, col, 0.12)
                cr.rectangle(cx, y, cw, ch)
                cr.fill()
                D.src(cr, col, 0.6)
                cr.set_line_width(1)
                cr.rectangle(cx + 0.5, y + 0.5, cw - 1, ch - 1)
                cr.stroke()
                D.dot(cr, cx + 9, y + ch / 2, 2.5, col, glow=False)
                D.text(cr, cx + 17, y + 3, name, 10, "soft", "semibold", spacing=0.08, width=cw - 21)
                self.region(cx, y, cw, ch, self._node_tip(nd))
            cx += cw + 6
        return y + ch + 10

    def _service_cols(self, cr, services, width):
        """As many service columns (four at most, two at least) as fit each name whole."""
        need = max([D.layout(cr, (s.get("name") or s["id"]).upper(), 10, "semibold", 0.06).get_pixel_size()[0] + 20
                    for s in services] + [60])
        k = 4
        while k > 2 and (width - (k - 1) * 4) / k < need:
            k -= 1
        return k, (width - (k - 1) * 4) / k

    def _services(self, cr, d, x0, x1, y, mode="full", draw=True):
        groups = d.get("config", {}).get("groups", [])
        status = d.get("services", {})
        every = [s for g in groups for s in g.get("services", [])]
        total = len(every)
        up = sum(1 for s in every if status.get(s["id"], {}).get("status") == "up")
        if draw:
            D.label(cr, x0, y, "SERVICES", "dim")
            D.label(cr, x1, y, f"{up}/{total} UP", "phosphor" if up == total else "amber", align="right")
            if mode == "fold":
                self.region(x0, y, x1 - x0, 16, f"{up} of {total} services answering"
                            + (": the ones that aren't are listed under it" if up < total else "")
                            + ". Make the panel taller to see every service.")
        y += 20
        if not every:
            return y + 4
        cols, cw = self._service_cols(cr, every, x1 - x0)
        ch = 21
        if mode == "fold":
            bad = [s for s in every if status.get(s["id"], {}).get("status") != "up"]
            for i, s in enumerate(bad):
                r, c = divmod(i, cols)
                if draw:
                    self._service(cr, s, status, x0 + c * (cw + 4), y + r * (ch + 3), cw, ch)
            return y + math.ceil(len(bad) / cols) * (ch + 3) + 4
        for g in groups:
            if draw:
                D.label(cr, x0, y, g.get("name", ""), "static", size=10)
            y += 16
            for i, s in enumerate(g.get("services", [])):
                r, c = divmod(i, cols)
                if draw:
                    self._service(cr, s, status, x0 + c * (cw + 4), y + r * (ch + 3), cw, ch)
            rows = math.ceil(len(g.get("services", [])) / cols)
            y += rows * (ch + 3) + 4
        return y + 4

    def _service(self, cr, s, status, cx, cy, cw, ch):
        st = status.get(s["id"], {})
        state = st.get("status")
        col = {"up": "phosphor", "down": "danger"}.get(state, "amber")
        D.src(cr, col, 0.10 if state == "up" else 0.22)
        cr.rectangle(cx, cy, cw, ch)
        cr.fill()
        D.src(cr, col, 0.55 if state == "up" else 1)
        cr.set_line_width(1)
        cr.rectangle(cx + 0.5, cy + 0.5, cw - 1, ch - 1)
        cr.stroke()
        D.src(cr, col)
        cr.rectangle(cx + 5, cy + ch / 2 - 2, 4, 4)
        cr.fill()
        D.text(cr, cx + 14, cy + 3, s.get("name", s["id"]).upper(), 10,
               "soft" if state == "up" else col, "semibold", spacing=0.06, width=cw - 18)
        url = s.get("lan") or s.get("wan")
        ms = st.get("ms")
        tip = (f"{s.get('name')} ({s.get('role', '')}): {state or 'unknown'}"
               + (f", answered in {ms:.0f} ms" if isinstance(ms, (int, float)) else "")
               + (f". Click to open {url}" if url else (f". Address {s.get('address')}" if s.get("address") else "")))
        act = (lambda u=url: open_url(u)) if url else \
            ((lambda a=s.get("address"): copy_text(a)) if s.get("address") else None)
        self.region(cx, cy, cw, ch, tip, act)

    def _pools(self, cr, d, x0, x1, y, mode="full", draw=True):
        nas = d.get("nas") or {}
        pool = nas.get("pool") or {}
        rf = store_share(nas)
        disks = d.get("nodeDisks") or []
        if mode == "fold":
            if draw:
                self._pools_line(cr, d, nas, pool, rf, disks, x0, x1, y)
            return y + 20
        if draw:
            D.label(cr, x0, y, "STORAGE POOLS", "dim")
        y += 20
        if pool.get("total"):
            if draw:
                self._nas_row(cr, nas, pool, x0, x1, y)
            y += 34
        if rf:
            if draw:
                where = f"the NAS share {rf['name']}" if rf.get("name") else "the NAS"
                quota = f"quota {S.human(rf['quota'])}" if (rf.get("quota") or 0) > 0 else "no quota"
                D.label(cr, x0, y, "RUSTFS", "phosphor")
                D.label(cr, x0 + 70, y, f"{S.human(rf['usage'], digits=1)} on {where}", "soft")
                st = (d.get("services") or {}).get(OBJECT_STORE, {}).get("status")
                D.dot(cr, x1 - 4, y + 7, 3, "phosphor" if st == "up" else "danger")
                self.region(x0, y, x1 - x0, 16, f"RustFS object store: {S.human(rf['usage'])} used on {where} "
                            f"({quota}); console {st or 'unknown'}. Click to open.",
                            lambda: open_url(self._svc_url(d, OBJECT_STORE)))
            y += 22
        for i, nd in enumerate(disks):
            if draw:
                frac = (nd.get("pct") or 0) / 100
                name = disk_node(nd, i)
                D.text(cr, x0, y, name.replace("k8s-", "").upper(), 10, "static", "semibold", spacing=0.18, width=104)
                D.bar(cr, x0 + 110, y + 4, x1 - x0 - 210, 5, frac, D.level(frac, 0.8, 0.9))
                D.label(cr, x1, y, f"{S.human(nd.get('used') or 0, digits=0)}/{S.human(nd.get('capacity') or 0, digits=0)}",
                        "soft", size=9, align="right")
                self.region(x0, y, x1 - x0, 15, f"Local disk on {name}: {frac * 100:.0f}% used, "
                            f"{S.human(nd.get('used') or 0)} of {S.human(nd.get('capacity') or 0)}")
            y += 16
        return y

    def _nas_row(self, cr, nas, pool, x0, x1, y):
        frac = pool["used"] / pool["total"]
        D.label(cr, x0, y, "NAS", "phosphor")
        D.label(cr, x0 + 44, y, f"{S.human(pool['used'], digits=1)} / {S.human(pool['total'], digits=1)}", "soft")
        disks = nas.get("disks") or []
        # disk bays as small cells at the right
        bx = x1 - len(disks) * 16
        for i, dk in enumerate(disks):
            bad = dk.get("health") != "good" or dk.get("state") != "normal"
            col = "danger" if bad else D.level(dk.get("tempC") or 0, 45, 55)
            D.src(cr, col, 0.9)
            cr.rectangle(bx + i * 16, y + 1, 12, 12)
            cr.fill()
            self.region(bx + i * 16, y, 14, 14, f"NAS bay {dk.get('slot')}: {dk.get('model', '')} "
                        f"{S.human(dk.get('size'))}, {dk.get('health')}, {dk.get('tempC')} °C, "
                        f"{dk.get('hours', 0)} power-on hours")
        D.cells(cr, x0, y + 18, x1 - x0, 7, frac, n=48, warn=0.8, crit=0.9)
        dev = nas.get("device") or {}
        self.region(x0, y, bx - x0 - 6, 28, f"{dev.get('name', 'NAS')}: RAID pool ({pool.get('raidMembers')} disks, "
                    f"{pool.get('health')}) {S.human(pool['used'])} used of {S.human(pool['total'])}")

    def _pools_line(self, cr, d, nas, pool, rf, disks, x0, x1, y):
        """STORAGE POOLS folded to one line: the NAS pool's use, the object store's and the
        fullest node disk; the whole of each in the hover hint."""
        parts, tips, col = [], [], "soft"
        if pool.get("total"):
            frac = pool["used"] / pool["total"]
            parts.append(f"NAS {frac * 100:.0f}%")
            col = D.level(frac, 0.8, 0.9) if frac >= 0.8 else col
            bad = [dk for dk in nas.get("disks") or [] if dk.get("health") != "good" or dk.get("state") != "normal"]
            if bad:
                parts[-1] += f" · {len(bad)} DISK{'S' if len(bad) > 1 else ''} BAD"
                col = "danger"
            tips.append(f"NAS pool {S.human(pool['used'])} used of {S.human(pool['total'])} ({pool.get('health')})"
                        + (f"; {len(bad)} disk(s) not healthy" if bad else ""))
        if rf:
            parts.append(f"RUSTFS {S.human(rf['usage'], digits=0)}")
            tips.append(f"RustFS object store {S.human(rf['usage'])}")
        if disks:
            most = max(nd.get("pct") or 0 for nd in disks)
            parts.append(f"DISKS ≤{most:.0f}%")
            if most >= 80:
                col = "danger" if most >= 90 else ("amber" if col != "danger" else col)
            tips.append("node disks: " + ", ".join(f"{disk_node(nd, i)} {nd.get('pct') or 0:.0f}%"
                                                   for i, nd in enumerate(disks)))
        lw = D.label(cr, x0, y, "STORAGE POOLS", "dim")[0]
        room = x1 - x0 - lw - 12
        while parts and D.layout(cr, " · ".join(parts), 10, "semibold", 0.18).get_pixel_size()[0] > room:
            parts.pop()
        if parts:
            D.label(cr, x1, y, " · ".join(parts), col, size=10, align="right")
        self.region(x0, y, x1 - x0, 16, ("Storage, folded to one line (make the panel taller for each pool): "
                                         + "; ".join(tips) + ".") if tips else "No storage pools in the snapshot.")


# =================================================================== SWITCHBOARD
