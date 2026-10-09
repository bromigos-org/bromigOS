"""SUPER+SHIFT+N — the network map: the real LAN, as UniFi and Prometheus see it.

Topology is read, not drawn by hand: every wired or wireless client's attachment comes
from UniFi (unpoller_client_uptime_seconds: sw_name/sw_port or ap_name); a client whose
MAC is a Proxmox VE virtual NIC (bc:24:11) sits behind the Proxmox host. The AP hangs
off the switch port that powers it (unpoller_device_port_poe_watts), the switch off the
gateway's SFP+ uplink.

Traffic on each link (packets scale with it): the switch port the device is on
(unpoller_device_port_*_rate_bytes), the WAN (unpoller_device_wan_rate_bytes), the AP
radio (unpoller_device_rate_bytes), the VMs' own node-exporter counters, and this
machine's wifi from psutil. Latency: one ping per node every 4 s (the radar's method).

Verb: trace <name|ip> runs a path from this workstation hop by hop, pings each hop and
lights the slowest one, and the camera frames the path. clear. Scroll zooms toward
the cursor; the IP and latency lines and the link rates make way when crowded.
"""
import concurrent.futures as cf
import math
import re
import time

import numpy as np

from . import sources
from .homelab import H
from .deckkit import TAU, Deck3D, ascii_, frame_panel
from .glkit import col

# The LAN (device models, addresses, which hosts to show, their roles and display names)
# comes from homelab.toml's [netmap] (references to the private overlay keep the
# addresses out of a public repo); without it the map shows only what UniFi reports and
# no host filter matches. Readings: UniFi Poller's metrics through the metrics capability.
_NM = (H.config.table("netmap") if H else {}) or {}
GW = (_NM.get("gateway") or {}).get("model", "")
SWITCH = (_NM.get("switch") or {}).get("model", "")
AP = (_NM.get("ap") or {}).get("model", "")
GW_IP = (_NM.get("gateway") or {}).get("ip", "")
SWITCH_IP = (_NM.get("switch") or {}).get("ip", "")
AP_IP = (_NM.get("ap") or {}).get("ip", "")
PVE_OUI = "bc:24:11"
ROLE = {r["ip"]: r["role"] for r in _NM.get("roles") or [] if r.get("ip")}
NAMES = {a["name"]: a["alias"] for a in _NM.get("aliases") or [] if a.get("name")}
SHOW_PREFIXES = tuple(_NM.get("show_prefixes") or ())      # client IPs shown: the lab and this machine
SHOW_HOSTS = set(_NM.get("show_hosts") or ())


def fmt_rate(v):
    if v is None:
        return "--"
    for u in ("B/S", "KB/S", "MB/S", "GB/S"):
        if v < 1000:
            return f"{v:.0f} {u}"
        v /= 1000.0
    return f"{v:.1f} TB/S"


class NetDeck(Deck3D):
    name = "netmap"
    title = "NETWORK // THE LAN AS IT IS WIRED"
    hint = "VECTOR: bromigos-live netmap trace <host>"
    zoom = (0.7, 5.0)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pitch, self.yaw, self.persp, self.spin = 0.22, 0.0, 4.0, 0.0
        s = self.s
        self.L["center"] = (890 * s, 640 * s, 560 * s)
        self.nodes = {}        # id -> {name, ip, kind, parent, role}
        self.pos = {}
        self.rate = {}         # node id -> bytes/s on its uplink
        self.lat = {}          # node id -> ms
        self.trace = None      # {path, t0, hops: [(id, ms)], slow}
        self.ready_ = False
        self.poll_every(self._topology, 60, "topology")
        self.poll_every(self._traffic, 5, "traffic")
        self.poll_every(self._pings, 4, "ping")

    def ready(self):
        return self.ready_ and bool(self.rate) and bool(self.lat)

    # ------------------------------------------------------------------ data
    def _topology(self):
        n = {"wan": {"name": "WAN", "ip": "1.1.1.1", "kind": "wan", "parent": None},
             "gw": {"name": "GATEWAY", "ip": GW_IP, "kind": "gw", "parent": "wan", "role": GW.upper()}}
        dev = {}
        for r in sources.prom("unpoller_device_info"):
            m = r["metric"]
            dev[m.get("name")] = m.get("ip")
        n["sw"] = {"name": "SWITCH", "ip": dev.get(SWITCH, SWITCH_IP), "kind": "sw", "parent": "gw",
                   "role": SWITCH.upper(), "port": None}
        poe = {r["metric"].get("port_num") for r in sources.prom(f'unpoller_device_port_poe_watts{{name="{SWITCH}"}} > 0')}
        n["ap"] = {"name": "ACCESS POINT", "ip": dev.get(AP, AP_IP), "kind": "ap", "parent": "sw",
                   "role": AP.upper(), "port": sorted(poe)[0] if poe else None}
        for r in sources.prom("unpoller_client_uptime_seconds"):
            m = r["metric"]
            ip = m.get("ip") or ""
            if not ((SHOW_PREFIXES and ip.startswith(SHOW_PREFIXES)) or ip in SHOW_HOSTS):
                continue                                        # the lab and this machine; not every phone
            name = NAMES.get(m.get("name"), m.get("name"))
            if m.get("sw_name") == SWITCH:
                parent, port = "sw", m.get("sw_port")
            elif m.get("ap_name"):
                parent, port = "ap", None
            elif (m.get("mac") or "").startswith(PVE_OUI) or m.get("sw_name") == "proxmox":
                parent, port = "proxmox", None
            else:
                parent, port = "sw", m.get("sw_port")
            nid = "proxmox" if name == "proxmox" else name
            n[nid] = {"name": name.upper(), "ip": ip, "kind": "host", "parent": parent, "port": port,
                      "role": ROLE.get(ip, "")}
        self.nodes = n
        self._layout()
        self.built_at = None

    def _layout(self):
        tiers = {}
        for k, v in self.nodes.items():
            depth, p = 0, v
            while p.get("parent"):
                depth += 1
                p = self.nodes.get(p["parent"], {})
            tiers.setdefault(depth, []).append(k)
        pos = {}
        for depth in sorted(tiers):
            ks = sorted(tiers[depth], key=lambda k: (pos.get(self.nodes[k].get("parent"), (0,))[0], k))
            n = len(ks)
            for i, k in enumerate(ks):
                px = pos.get(self.nodes[k].get("parent"), (0, 0, 0))[0]
                spread = 0.42 if depth >= 4 else 0.36
                x = (i - (n - 1) / 2) * spread if depth <= 3 else px + (i - (n - 1) / 2) * 0.0
                pos[k] = (x, 0.62 - depth * 0.3, (i % 2) * 0.12 - 0.06)
            if depth >= 4:                                       # children fan under their parent
                by = {}
                for k in ks:
                    by.setdefault(self.nodes[k]["parent"], []).append(k)
                for par, kids in by.items():
                    px = pos.get(par, (0, 0, 0))[0]
                    for i, k in enumerate(kids):
                        pos[k] = (px + (i - (len(kids) - 1) / 2) * 0.34, 0.62 - depth * 0.3, (i % 2) * 0.12 - 0.06)
        self.pos = pos

    def _traffic(self):
        if not self.nodes:
            return
        rate = {}
        port = {}
        for r in sources.prom(f'unpoller_device_port_receive_rate_bytes{{name="{SWITCH}"}} + '
                              f'unpoller_device_port_transmit_rate_bytes{{name="{SWITCH}"}}'):
            port[r["metric"].get("port_num")] = float(r["value"][1])
        for k, v in self.nodes.items():
            if v.get("parent") == "sw" and v.get("port") in port:
                rate[k] = port[v["port"]]
        gwp = {r["metric"].get("port_name"): float(r["value"][1]) for r in sources.prom(
            f'unpoller_device_port_receive_rate_bytes{{name="{GW}"}} + unpoller_device_port_transmit_rate_bytes{{name="{GW}"}}')}
        rate["sw"] = max(gwp.values()) if gwp else None
        w = sources.prom(f'unpoller_device_wan_rate_bytes{{name="{GW}"}}')
        rate["gw"] = float(w[0]["value"][1]) if w else None
        ap = sources.prom(f'unpoller_device_rate_bytes{{name="{AP}"}}')
        rate["ap"] = float(ap[0]["value"][1]) if ap else rate.get("ap")
        ne = {}
        for r in sources.prom('sum by (instance)(rate(node_network_receive_bytes_total{device!~"lo|veth.*|cali.*|'
                              'flannel.*|cni.*|docker.*|br.*|tailscale.*"}[1m]) + rate(node_network_transmit_bytes_total'
                              '{device!~"lo|veth.*|cali.*|flannel.*|cni.*|docker.*|br.*|tailscale.*"}[1m]))'):
            ne[r["metric"].get("instance", "").split(":")[0]] = float(r["value"][1])
        for k, v in self.nodes.items():
            if v.get("parent") == "proxmox" and v["ip"] in ne:
                rate[k] = ne[v["ip"]]
        d = self.data.snapshot()
        if "workstation" in self.nodes:
            rate["workstation"] = (d.get("rx") or 0) + (d.get("tx") or 0)
        self.rate = rate
        self.built_at = None

    def _pings(self):
        if not self.nodes:
            return
        with cf.ThreadPoolExecutor(8) as ex:
            res = dict(zip(self.nodes, ex.map(lambda k: sources.ping(self.nodes[k]["ip"]), self.nodes)))
        self.lat = res
        self.ready_ = True
        self.built_at = None

    # ------------------------------------------------------------------ verbs
    def path_to(self, nid):
        """Hops from this workstation to nid through the tree (via their common ancestor)."""
        def up(k):
            out = []
            while k:
                out.append(k)
                k = self.nodes.get(k, {}).get("parent")
            return out
        a, b = up("workstation"), up(nid)
        common = next((k for k in a if k in b), None)
        if common is None:
            return None
        return a[:a.index(common) + 1] + list(reversed(b[:b.index(common)]))

    def command(self, verb, args):
        if verb == "trace":
            q = args.lower().strip()
            nid = next((k for k, v in self.nodes.items() if q in (k, v["ip"], v["name"].lower())), None) or \
                next((k for k, v in self.nodes.items() if q and (q in k or q in v.get("role", "").lower())), None)
            if q in ("internet", "wan", "1.1.1.1"):
                nid = "wan"
            if not nid:
                return f"no host '{args}' on the map"
            path = self.path_to(nid)
            if not path:
                return f"no path to {nid}"
            import threading
            self.trace = {"path": path, "t0": self.now(), "hops": [], "slow": None}
            if self.cam and not getattr(self, "clicked", False):   # VECTOR's trace; a click keeps the view
                pp = self.stage.painter
                self.cam.fit([self.pos[k] for k in path if k in self.pos], pp.rot[2], self.persp, zmax=2.6)
            threading.Thread(target=self._run_trace, args=(self.trace,), daemon=True).start()
            return f"tracing workstation → {self.nodes[nid]['name'].lower()} ({len(path) - 1} hops)"
        if verb == "clear":
            self.trace = None
            if self.cam:
                self.cam.reset()
            return "cleared"
        return "netmap verbs: trace <host>, clear"

    def _run_trace(self, tr):
        prev = 0.0
        worst = (None, -1.0)
        for k in tr["path"]:
            ms = None
            for _ in range(3):
                v = sources.ping(self.nodes[k]["ip"])
                if v is not None:
                    ms = v if ms is None else min(ms, v)
            hop = (ms - prev) if ms is not None else None
            tr["hops"].append((k, ms, hop))
            if hop is not None and hop > worst[1] and k != "workstation":
                worst = (k, hop)
            prev = ms if ms is not None else prev
            self.built_at = None
        tr["slow"] = worst[0]
        tr["done"] = self.now()
        self.toast = (f"slowest hop: {self.nodes[worst[0]]['name'].lower()} {worst[1]:+.1f} ms" if worst[0]
                      else "no hop answered", self.now(), "amber")

    # ------------------------------------------------------------------ build
    def rebuild_due(self, t):
        return self.built_at is None or t - self.built_at >= (0.1 if self.trace else 0.5)

    def build(self, b, d, t):
        s = self.s
        T = 0.05
        self.header(b, "TOPOLOGY + TRAFFIC FROM UNIFI (UNPOLLER) AND NODE-EXPORTER · LATENCY BY PING")
        x, y, w, h = self.L["panel"]
        frame_panel(b, x, y, w, h, "THE LAN", T + 0.05, sub="PACKETS = LINK TRAFFIC · RING = PING LATENCY")
        pts, ids = [], []
        pp = self.stage.painter
        labels = self.cam.labels(self.stage.atlas, pp, s, cap=80)
        on_path = set()
        if self.trace:
            p = self.trace["path"]
            on_path = {(p[i], p[i + 1]) for i in range(len(p) - 1)} | {(p[i + 1], p[i]) for i in range(len(p) - 1)}
        for k, v in self.nodes.items():
            if k not in self.pos:
                continue
            c = self.pos[k]
            par = v.get("parent")
            if par in self.pos:
                pc = self.pos[par]
                r = self.rate.get(k)
                lv = min(math.log10(1 + (r or 0)) / 8.0, 1.0)
                hot = (k, par) in on_path
                b.line(pc, c, col("white" if hot else "soft" if r else "dim", 0.9 if hot else 0.35 + 0.5 * lv),
                       width=1.0 + 2.5 * lv + (1.5 if hot else 0), space=2, reveal=T + 0.2)
                if r:
                    npk = 1 + int(lv * 5)
                    for i in range(npk):
                        fwd = i % 2 == 0
                        b.arc(pc if fwd else c, 0, 2.6 * s, 0, TAU, col("soft" if fwd else "amber", 0.95), kind=2,
                              space=2, end=c if fwd else pc, speed=0.2 + 0.8 * lv, phase=i / npk, reveal=T + 0.5)
                mid = tuple((np.array(pc) + np.array(c)) / 2)
                if r is not None:
                    labels.add(3 + lv, mid, fmt_rate(r), "xs", 0.8, dx=8, dy=4, colour=col("dim"))
            ms = self.lat.get(k)
            lc = "static" if ms is None else "phosphor" if ms < 5 else "amber" if ms < 40 else "danger"
            big = v["kind"] in ("gw", "sw", "wan")
            b.arc(c, 0, (8 if big else 5.5) * s, 0, TAU, col("white" if k == "workstation" else "soft"), kind=2,
                  space=2, reveal=T + 0.3)
            b.arc(c, (14 if big else 11) * s, (15.6 if big else 12.4) * s, 0, TAU, col(lc), segs=12, gap=0.3,
                  spin=0.2, space=2, reveal=T + 0.35)
            labels.add(9, c, v["name"], "s", 1.5, dx=18, dy=-6, colour=col("soft"), reveal=T + 0.4, force=True)
            labels.add(6 if big else 5, c, f"{v['ip']} · {'--' if ms is None else f'{ms:.1f} MS'}", "xs", 0.8,
                       dx=18, dy=12, colour=col(lc), reveal=T + 0.45, force=k == self.hover or k == self.selected)
            pts.append(c)
            ids.append(k)
        labels.place(b)
        self._trace_fx(b, t)
        self.pick_pts = np.array(pts, np.float32).reshape(-1, 3)
        self.pick_ids = ids
        if self.hover and self.hover in self.nodes:
            v = self.nodes[self.hover]
            self.hover_tip(b, f"{v['name']} · {v['ip']}", [
                v.get("role") or v["kind"].upper(),
                f"UPLINK {self.nodes.get(v.get('parent'), {}).get('name', '-')}" +
                (f" PORT {v['port']}" if v.get("port") else ""),
                f"TRAFFIC {fmt_rate(self.rate.get(self.hover))} · PING "
                f"{'--' if self.lat.get(self.hover) is None else f'{self.lat[self.hover]:.1f} MS'}"],
                "CLICK TO TRACE THE PATH FROM HERE")
        self._side(b, t, T)

    def select(self, ident):
        super().select(ident)
        if ident:
            self.clicked = True
            try:
                self.command("trace", ident)
            finally:
                self.clicked = False

    def _trace_fx(self, b, t):
        s = self.s
        tr = self.trace
        if not tr:
            return
        path = tr["path"]
        for i, (k, ms, hop) in enumerate(tr["hops"]):
            c = self.pos.get(k)
            if c is None:
                continue
            slow = tr.get("slow") == k
            b.arc(c, 0, (14 if slow else 9) * s, 0, TAU, col("amber" if slow else "white", 0.9), kind=2, space=2)
            if i > 0 and path[i - 1] in self.pos:
                b.line(self.pos[path[i - 1]], c, col("amber" if slow else "white", 0.95), width=3 if slow else 2,
                       space=2)
            if hop is not None:
                b.text(f"{hop:+.1f} MS", *c[:2], col("amber" if slow else "white"), font="s", track=1, space=2,
                       z=c[2], dx=-80, dy=-22)
        if len(tr["hops"]) < len(path):                     # the probe travelling to the next hop
            k0 = tr["hops"][-1][0] if tr["hops"] else path[0]
            k1 = path[len(tr["hops"])]
            if k0 in self.pos and k1 in self.pos:
                b.arc(self.pos[k0], 0, 5 * s, 0, TAU, col("white"), kind=2, space=2, end=self.pos[k1], speed=1.5)

    def _side(self, b, t, T):
        s = self.s
        x, y, w, h = self.L["side"]
        frame_panel(b, x, y, w, h, "LINKS", T + 0.1, sub="BUSIEST FIRST")
        yy = y + 70 * s
        for k, r in sorted(self.rate.items(), key=lambda kv: -(kv[1] or 0))[:10]:
            v = self.nodes.get(k)
            if not v:
                continue
            up = self.nodes.get(v.get("parent"), {}).get("name", "WAN")
            b.text(f"{v['name']} - {up}".upper()[:34], x + 18 * s, yy, col("soft"), font="xs", track=1)
            b.text(fmt_rate(r), x + w - 18 * s, yy, col("white"), font="xs", track=1, align="r")
            yy += 22 * s
        yy += 16 * s
        b.text("TRACE", x + 18 * s, yy, col("dim"), font="xs", track=3)
        yy += 24 * s
        tr = self.trace
        if not tr:
            b.text("CLICK A HOST, OR VECTOR: netmap trace <host>", x + 18 * s, yy, col("dim"), font="xs", track=1)
        else:
            for k, ms, hop in tr["hops"]:
                slow = tr.get("slow") == k
                b.text(f"{self.nodes[k]['name']}".upper()[:24], x + 18 * s, yy, col("amber" if slow else "soft"),
                       font="xs", track=1)
                b.text("NO ANSWER" if ms is None else f"{ms:.1f} MS  ({hop:+.1f})", x + w - 18 * s, yy,
                       col("amber" if slow else "white"), font="xs", track=1, align="r")
                yy += 22 * s
            if tr.get("slow"):
                b.text(f"SLOWEST HOP: {self.nodes[tr['slow']]['name']}".upper(), x + 18 * s, yy + 8 * s,
                       col("amber"), font="s", track=1.5)


DECK = NetDeck
