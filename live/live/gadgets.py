"""The holographic gadgets, as instance batches.

Each builder adds primitives to a Batch from a data snapshot. Motion lives in
the shaders (ring spin, packets, depth rotation, assembly reveals), so builders
run only when readings change. Every value drawn here is a real reading; when a
reading is missing the gadget says so instead of inventing one.

  rings          concentric segmented arc gauges: CPU, GPU, RAM, VRAM + per-thread
  constellation  the homelab nodes in space; packets scale with real activity
  hologram       this workstation as a wireframe; parts glow by load/temperature
"""
import math

from .glkit import col, level

TAU = 2 * math.pi


def fmt_bytes(n, unit="B"):
    if n is None:
        return "--"
    for u in ("", "K", "M", "G", "T"):
        if abs(n) < 1000:
            return f"{n:.0f} {u}{unit}" if u == "" or n >= 100 else f"{n:.1f} {u}{unit}"
        n /= 1000.0
    return f"{n:.1f} P{unit}"


def fmt_rate(bps):
    return fmt_bytes(bps, "B/S")


def pct(v):
    return "--" if v is None else f"{v:.0f}%"


def temp(v):
    return "--" if v is None else f"{v:.0f}°C"


# ---------------------------------------------------------------- panel frame
def frame(b, x, y, w, h, title, t0=0.0, sub=None, plate=0.82, accent="phosphor"):
    """A holo panel: dark plate, 1px rule, targeting brackets, wide-tracked title.
    With t0 > 0 it assembles: rules draw in, brackets land, title types on."""
    b.plate(x, y, w, h, plate)
    c = col("dim", 0.9)
    r = lambda k: (t0 + k) if t0 else 0.0  # noqa: E731
    b.line((x, y), (x + w, y), c, reveal=r(0.0))
    b.line((x + w, y + h), (x, y + h), c, reveal=r(0.1))
    b.line((x, y + h), (x, y), col("dim", 0.5), reveal=r(0.15))
    b.line((x + w, y), (x + w, y + h), col("dim", 0.5), reveal=r(0.15))
    b.brackets(x - 4, y - 4, w + 8, h + 8, col(accent, 1.0), l=16, width=1.6, reveal=r(0.25))
    b.text(title, x + 16, y + 26, col("soft"), font="m", track=3.0, reveal=r(0.3), type_rate=0.018)
    if sub:
        b.text(sub, x + w - 16, y + 26, col("dim"), font="xs", track=1.5, align="r", reveal=r(0.45),
               type_rate=0.01)
    b.line((x + 16, y + 38), (x + w - 16, y + 38), col("guard", 1.0), reveal=r(0.35))


# ---------------------------------------------------------------- arc rings
RING_SPEC = (  # name, key, width, segments, spin rad/s
    ("CPU", "cpu", 18, 64, 0.06),
    ("GPU", "gpu", 15, 52, -0.08),
    ("RAM", "mem", 13, 44, 0.10),
    ("VRAM", "vram", 11, 36, -0.12),
)


def rings(b, d, st, cx, cy, R, t0=0.0, legend="right"):
    rv = lambda k: (t0 + k) if t0 else 0.0  # noqa: E731
    b.disc_plate((cx, cy), R + 40, 0.8)
    # bezel and dial scales
    b.arc((cx, cy), R + 30, R + 31, 0, TAU, col("dim", 0.8), reveal=rv(0.0))
    b.arc((cx, cy), R + 14, R + 22, 0, TAU, col("dim", 0.75), segs=120, gap=0.78, spin=0.025, reveal=rv(0.05))
    b.arc((cx, cy), R + 10, R + 25, 0, TAU, col("soft", 0.85), segs=12, gap=0.93, spin=0.025, reveal=rv(0.1))
    radii = []
    r_out = R
    for i, (name, key, w, segs, spin) in enumerate(RING_SPEC):
        v = d.get(key)
        r_in = r_out - w
        radii.append((r_in, r_out))
        b.arc((cx, cy), r_in, r_out, 0, TAU, col("guard", 0.6), segs=segs, gap=0.22, spin=spin,
              reveal=rv(0.15 + i * 0.1))
        if v is not None:
            frac = max(min(v / 100.0, 1.0), 0.004)
            b.arc((cx, cy), r_in, r_out, 0, frac * TAU, col(level(v, 70, 90), 1.0), segs=segs, gap=0.22,
                  spin=spin, reveal=rv(0.35 + i * 0.12))
            # leading edge marker: a bright hairline just outside the fill end
            b.arc((cx, cy), r_out + 2, r_out + 4, frac * TAU - 0.01, frac * TAU + 0.01, col("white", 0.9),
                  spin=spin, reveal=rv(0.5 + i * 0.12))
        r_out = r_in - 9
    # per-thread loads: one radial bar per logical CPU
    cores = d.get("cores") or []
    n = len(cores)
    r0 = r_out - 30
    if n:
        b.arc((cx, cy), r0, r0 + 26, 0, TAU, col("guard", 0.6), segs=n, gap=0.3, reveal=rv(0.6))
        for i, v in enumerate(cores):
            a0 = i * TAU / n + 0.035
            a1 = (i + 1) * TAU / n - 0.035
            b.arc((cx, cy), r0, r0 + 3 + 23 * min(v, 100) / 100.0, a0, a1, col(level(v, 75, 95), 0.95),
                  reveal=rv(0.7 + i * 0.01))
    # hub
    hub = r0 - 10
    b.arc((cx, cy), hub - 1, hub, 0, TAU, col("dim", 0.8), reveal=rv(0.4))
    b.arc((cx, cy), hub - 9, hub - 6, 0, TAU, col("dim", 0.5), segs=4, gap=0.6, spin=-0.3, reveal=rv(0.45))
    cpu = d.get("cpu")
    b.text("CPU", cx, cy - 34, col("dim"), font="xs", track=3, align="c", reveal=rv(0.5))
    b.text(pct(cpu), cx, cy + 14, col("soft"), font="xl", track=0, align="c", reveal=rv(0.55))
    b.text(temp(d.get("cpu_temp")), cx, cy + 40, col(level(d.get("cpu_temp"), 75, 88)), font="s",
           track=1, align="c", reveal=rv(0.6))
    # legend with elbow leaders out of each ring at 3 o'clock
    rows = [
        ("CPU", pct(cpu), f"{temp(d.get('cpu_temp'))}  {(d.get('cpu_freq') or 0) / 1000:.2f} GHZ"),
        ("GPU", pct(d.get("gpu")), f"{temp(d.get('gpu_temp'))}  {(d.get('gpu_power') or 0):.0f} W"),
        ("RAM", pct(d.get("mem")), f"{fmt_bytes(d.get('mem_used'))} / {fmt_bytes(d.get('mem_total'))}"),
        ("VRAM", pct(d.get("vram")), f"{(d.get('vram_used') or 0) / 1024:.1f} / {(d.get('vram_total') or 0) / 1024:.0f} GB"
         if d.get("vram_total") else "--"),
    ]
    side = 1 if legend == "right" else -1
    lx = cx + side * (R + 60)
    ly0 = cy - 96
    for i, ((name, val, extra), (ri, ro)) in enumerate(zip(rows, radii)):
        ly = ly0 + i * 64
        rr = (ri + ro) / 2
        ang = math.asin(max(min((ly - cy) / rr, 0.98), -0.98))
        px, py = cx + side * rr * math.cos(ang), cy + rr * math.sin(ang)
        c = col("dim", 0.9)
        b.arc((px, py), 0, 2.2, 0, TAU, col("soft", 1.0), reveal=rv(0.8 + i * 0.08))
        b.line((px, py), (lx - side * 18, ly), c, reveal=rv(0.8 + i * 0.08))
        b.line((lx - side * 18, ly), (lx, ly), c, reveal=rv(0.9 + i * 0.08))
        v = d.get(RING_SPEC[i][1])
        tx = lx + side * 8
        al = "l" if side > 0 else "r"
        b.text(name, tx, ly - 7, col("dim"), font="xs", track=2.5, align=al, reveal=rv(0.95 + i * 0.08), type_rate=0.02)
        b.text(val, tx, ly + 24, col(level(v, 70, 90)), font="l", track=0.5, align=al, reveal=rv(1.0 + i * 0.08))
        b.text(extra, tx + side * 92, ly + 21, col("soft", 0.85), font="xs", track=1.2, align=al,
               reveal=rv(1.05 + i * 0.08), type_rate=0.01)


# ---------------------------------------------------------------- constellation
# the lab's nodes from its snapshot, laid out by constellation.py (no machine named here)
from .constellation import WAN, node_layout  # noqa: E402


def node_health(n, ready_all):
    if n is None:
        return ("phosphor" if ready_all else "amber"), None
    cpu, mem = n.get("cpuPct"), n.get("memPct")
    worst = max(cpu or 0, mem or 0)
    return level(worst, 85, 95), worst


def constellation(b, d, cx, cy, size, space=2, t0=0.0, labels=True, mini=False):
    rv = lambda k: (t0 + k) if t0 else 0.0  # noqa: E731
    cl = d.get("cluster") or {}
    nodes = {n["name"]: n for n in (cl.get("nodes") or []) if n.get("name")}
    c_ = cl.get("cluster") or {}
    ready_all = c_.get("nodesReady") is not None and c_.get("nodesReady") == c_.get("nodesTotal")
    layout, links, ai_link = node_layout(d)
    pos = dict(layout)
    pos[WAN[0]] = WAN[1]
    # orbit shells for depth
    for k, (tilt, r) in enumerate(((0.0, 1.05), (1.2, 1.05), (2.2, 0.75))):
        pts = []
        for i in range(73):
            a = i / 72 * TAU
            x, y, z = math.cos(a) * r, 0.0, math.sin(a) * r
            ct, sn = math.cos(tilt), math.sin(tilt)
            pts.append((x, y * ct - z * sn, y * sn + z * ct))
        for i in range(72):
            b.line(pts[i], pts[i + 1], col("guard", 0.9 if not mini else 0.7), space=space,
                   reveal=rv(0.05 * k + i * 0.004))
    ai = d.get("cluster") and (d["cluster"].get("ai") or {})
    net = (d.get("cluster") or {}).get("network") or {}
    # links + packets
    for a, z in links:
        pa, pz = pos[a], pos[z]
        if z == "uplink":
            act = min(((net.get("wanDownBps") or 0) + (net.get("wanUpBps") or 0)) / 50e6, 1.0)
            live = net.get("wanDownBps") is not None
        elif (a, z) == ai_link:                 # the models' link: their requests/min
            rpm = (ai or {}).get("rpmNow")
            act = min((rpm or 0) / 30.0, 1.0)
            live = rpm is not None
        else:
            n = nodes.get(z)
            live = n is not None and n.get("cpuPct") is not None
            act = min(((n or {}).get("cpuPct") or 0) / 60.0, 1.0) if live else 0.0
        b.line(pa, pz, col("dim" if live else "guard", 0.9), space=space, dash=0 if live else 6,
               reveal=rv(0.3))
        if live:
            npk = 1 + int(round(act * 4))
            speed = 0.12 + act * 0.55
            for k in range(npk):
                fwd = k % 2 == 0
                b.arc(pa if fwd else pz, 0, 2.6 if not mini else 2.0, 0, TAU,
                      col("soft" if fwd else "amber", 0.95), kind=2, space=space,
                      end=pz if fwd else pa, speed=speed, phase=k / npk, reveal=rv(0.8))
    # nodes
    for i, (name, p) in enumerate(list(layout.items()) + [WAN]):
        n = nodes.get(name)
        if name == "uplink":
            hc, worst = ("phosphor" if net.get("wanDownBps") is not None else "static"), None
        else:
            hc, worst = node_health(n, ready_all)
        r = rv(0.4 + i * 0.07)
        b.arc(p, 0, 5.5 if not mini else 3.5, 0, TAU, col(hc, 1.0), kind=2, space=space, reveal=r)
        b.arc(p, 11, 12.5, 0, TAU, col(hc, 0.85), segs=10, gap=0.35, spin=0.6 if i % 2 else -0.6,
              space=space, reveal=r)
        if hc in ("amber", "danger"):
            b.arc(p, 17, 18.5, 0, TAU, col(hc, 0.8), segs=3, gap=0.5, spin=1.2, space=space, reveal=r)
        if not labels:
            continue
        b.text(name.upper(), p[0], p[1], col("soft"), font="s", track=1.5, space=space, z=p[2],
               dx=18, dy=-2, reveal=rv(0.6 + i * 0.07), type_rate=0.015)
        if name == "uplink":
            sub = f"↓ {fmt_bytes((net.get('wanDownBps') or 0) / 8, 'B/S')}  ↑ {fmt_bytes((net.get('wanUpBps') or 0) / 8, 'B/S')}" \
                if net.get("wanDownBps") is not None else "NO READING"
        elif n is None:
            sub = "NO NODE TELEMETRY" + (" · READY" if ready_all else "")
        else:
            sub = f"CPU {pct(n.get('cpuPct'))}  MEM {pct(n.get('memPct'))}  {n.get('cores') or '?'}C"
        b.text(sub, p[0], p[1], col("dim" if n is None and name != "uplink" else "phosphor", 0.95),
               font="xs", track=1.0, space=space, z=p[2], dx=18, dy=14, reveal=rv(0.7 + i * 0.07))


def constellation_panel(b, d, x, y, w, h, t0=0.0):
    cl = d.get("cluster") or {}
    c = cl.get("cluster") or {}
    ok = d.get("cluster_ok")
    from .homelab import lab_name
    frame(b, x, y, w, h, f"{lab_name()} // RELAY MAP", t0,
          sub="LIVE /API/STATUS" if ok else "LINK DOWN · LAST KNOWN")
    rv = lambda k: (t0 + k) if t0 else 0.0  # noqa: E731
    if not cl:
        b.text("WAITING FOR THE FIRST SNAPSHOT", x + 16, y + h - 20, col("amber"), font="xs", track=2)
        return
    argo = cl.get("argocd") or {}
    stats = [
        ("NODES", f"{c.get('nodesReady', '?')}/{c.get('nodesTotal', '?')}",
         "phosphor" if c.get("nodesReady") == c.get("nodesTotal") else "danger"),
        ("PODS", f"{c.get('podsRunning') or 0:.0f}", "phosphor"),
        ("ALERTS", f"{c.get('alertsFiring') or 0:.0f}", "amber" if (c.get("alertsFiring") or 0) else "phosphor"),
        ("ARGO", f"{argo.get('healthy', '?')}/{argo.get('total', '?')}",
         "phosphor" if argo.get("healthy") == argo.get("total") else "amber"),
        ("CLUSTER CPU", pct(c.get("cpuNow")), level(c.get("cpuNow"), 70, 90)),
    ]
    sx = x + 16
    for i, (k, v, cc) in enumerate(stats):
        b.text(k, sx, y + h - 40, col("dim"), font="xs", track=2, reveal=rv(0.9 + i * 0.06))
        b.text(v, sx, y + h - 16, col(cc), font="m", track=1, reveal=rv(0.95 + i * 0.06))
        sx += max(len(k), len(v)) * 9 + 34
    hive = " · HIVE ∝ LITELLM RPM" if node_layout(d)[2] else ""
    b.text(f"PACKETS ∝ NODE CPU{hive} · UPLINK ∝ WAN BPS", x + w - 16, y + 54, col("dim", 0.9),
           font="xs", track=1, align="r", reveal=rv(1.1))


# ---------------------------------------------------------------- hologram
PARTS = ("CASE", "BOARD", "CPU", "RAM", "GPU", "NVME0", "NVME1", "SSD", "PSU", "FANS")
P = {n: i for i, n in enumerate(PARTS)}


def _box(x0, x1, y0, y1, z0, z1):
    v = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    e = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
    return [(v[a], v[b]) for a, b in e]


def _circle(c, r, plane="xy", n=28):
    pts = []
    for i in range(n + 1):
        a = i / n * TAU
        u, v = math.cos(a) * r, math.sin(a) * r
        if plane == "xy":
            pts.append((c[0] + u, c[1] + v, c[2]))
        elif plane == "xz":
            pts.append((c[0] + u, c[1], c[2] + v))
        else:
            pts.append((c[0], c[1] + u, c[2] + v))
    return list(zip(pts, pts[1:]))


def machine_model():
    """Wireframe of a mid-tower like this one (layout is schematic; parts real)."""
    segs = []
    add = lambda part, ss: segs.extend((a, b, P[part]) for a, b in ss)  # noqa: E731
    add("CASE", _box(-0.28, 0.28, -0.56, 0.56, -0.5, 0.5))
    add("CASE", [((-0.28, 0.42, -0.42), (-0.28, 0.42, 0.42)), ((-0.28, -0.34, -0.42), (-0.28, -0.34, 0.42)),
                 ((-0.28, 0.42, -0.42), (-0.28, -0.34, -0.42)), ((-0.28, 0.42, 0.42), (-0.28, -0.34, 0.42))])
    add("CASE", [((-0.2, 0.56, 0.5), (0.2, 0.56, 0.5)), ((-0.05, 0.5, 0.5), (0.05, 0.5, 0.5))])
    add("BOARD", _box(0.235, 0.245, -0.26, 0.48, -0.44, 0.34))
    for k in range(6):  # traces
        y = -0.2 + k * 0.11
        add("BOARD", [((0.234, y, -0.40), (0.234, y, -0.10 + 0.05 * (k % 3)))])
    # CPU tower cooler: block + fins
    add("CPU", _box(0.02, 0.235, 0.17, 0.42, -0.08, 0.16))
    for k in range(8):
        y = 0.19 + k * 0.03
        add("CPU", [((0.02, y, -0.08), (0.02, y, 0.16)), ((0.02, y, 0.16), (0.235, y, 0.16))])
    add("CPU", _circle((0.12, 0.295, -0.085), 0.09, "xy"))
    for z in (0.21, 0.25):
        add("RAM", _box(0.13, 0.235, 0.12, 0.44, z, z + 0.014))
    add("GPU", _box(-0.09, 0.235, -0.10, -0.01, -0.46, 0.30))
    add("GPU", _circle((0.07, -0.10, -0.24), 0.10, "xz"))
    add("GPU", _circle((0.07, -0.10, 0.08), 0.10, "xz"))
    add("GPU", [((-0.09, -0.055, -0.46), (-0.09, -0.055, 0.30))])
    add("NVME0", _box(0.215, 0.235, 0.05, 0.085, -0.38, -0.10))
    add("NVME1", _box(0.215, 0.235, -0.22, -0.185, -0.38, -0.10))
    add("SSD", _box(-0.22, 0.02, -0.52, -0.49, 0.18, 0.46))
    add("PSU", _box(-0.27, 0.27, -0.555, -0.38, -0.49, -0.04))
    add("PSU", _circle((0.0, -0.38, -0.27), 0.08, "xz"))
    add("FANS", _circle((0.0, 0.17, 0.5), 0.12, "xy"))
    add("FANS", _circle((0.0, -0.15, 0.5), 0.12, "xy"))
    add("FANS", _circle((0.0, 0.30, -0.5), 0.10, "xy"))
    return segs


PART_ANCHOR = {"CPU": (0.13, 0.30, 0.04), "GPU": (0.07, -0.06, -0.08), "RAM": (0.18, 0.30, 0.23),
               "NVME0": (0.225, 0.07, -0.24), "NVME1": (0.225, -0.2, -0.24), "SSD": (-0.1, -0.5, 0.32),
               "PSU": (0.0, -0.47, -0.27), "BOARD": (0.24, 0.0, 0.2), "CASE": (-0.28, 0.5, 0.0),
               "FANS": (0.0, 0.17, 0.5)}


def hologram(b, d, st, space=3, t0=0.0, model=None):
    rv = lambda k: (t0 + k) if t0 else 0.0  # noqa: E731
    model = model or machine_model()
    n = len(model)
    for i, (a, z, part) in enumerate(model):
        b.line(a, z, col("phosphor", 0.95), space=space, part=part, width=1.0,
               reveal=rv(0.1 + (i / n) * 0.9))
    # holo pad under the model
    for k, r in enumerate((0.62, 0.48, 0.30)):
        for a, z in _circle((0, -0.66, 0), r, "xz", 48):
            b.line(a, z, col("dim", 0.8 - k * 0.15), space=space, reveal=rv(0.05 * k))
    b.arc((0, -0.66, 0), 0, 3, 0, TAU, col("soft"), kind=2, space=space)
    for x, z in ((-0.28, -0.5), (0.28, -0.5), (-0.28, 0.5), (0.28, 0.5)):
        b.line((x * 1.6, -0.66, z * 1.1), (x, -0.56, z), col("dim", 0.45), space=space, dash=5, reveal=rv(0.3))
    for name in ("CPU", "GPU", "RAM", "NVME0", "NVME1", "SSD"):
        p = PART_ANCHOR[name]
        b.text(name, p[0], p[1], col("soft", 0.9), font="xs", track=1.5, space=space, z=p[2], dx=10, dy=-8,
               reveal=rv(1.0))


def part_readings(name, d, st):
    """(title, [lines]) for the selected part — all real readings."""
    drives = {x["name"]: x for x in st.get("drives", [])}
    disks = d.get("disks") or {}
    mounts = d.get("mounts") or []
    nv = d.get("nvme_temps") or {}

    def mounts_on(dev):
        return ", ".join(sorted({m["mount"] for m in mounts if m["dev"].startswith(dev)})) or "UNMOUNTED"

    def io(dev):
        x = disks.get(dev) or {}
        return f"R {fmt_rate(x.get('r', 0))}  W {fmt_rate(x.get('w', 0))}"
    if name == "CPU":
        return st["cpu_model"].upper(), [
            f"{st['cores_phys']}C / {st['threads']}T  {(d.get('cpu_freq') or 0) / 1000:.2f} GHZ",
            f"LOAD {pct(d.get('cpu'))}   TCTL {temp(d.get('cpu_temp'))}"]
    if name == "GPU":
        return st["gpu_name"].upper(), [
            f"LOAD {pct(d.get('gpu'))}   {temp(d.get('gpu_temp'))}   {(d.get('gpu_power') or 0):.0f} W",
            f"VRAM {(d.get('vram_used') or 0) / 1024:.1f} / {(d.get('vram_total') or 0) / 1024:.0f} GB   FAN {pct(d.get('gpu_fan'))}"]
    if name == "RAM":
        return "SYSTEM MEMORY", [f"{fmt_bytes(d.get('mem_used'))} / {fmt_bytes(d.get('mem_total'))}  ({pct(d.get('mem'))})",
                                 f"SWAP {pct(d.get('swap'))}"]
    if name in ("NVME0", "NVME1"):
        dev = "nvme0n1" if name == "NVME0" else "nvme1n1"
        dr = drives.get(dev, {})
        idx = 0 if name == "NVME0" else 1
        return (dr.get("model") or dev).upper(), [
            f"{fmt_bytes(dr.get('size'))}   {temp(nv.get(idx))}   {io(dev)}", f"MOUNTS {mounts_on(dev)}"]
    if name == "SSD":
        dr = drives.get("sda", {})
        return (dr.get("model") or "SATA").upper(), [f"{fmt_bytes(dr.get('size'))}   {io('sda')}",
                                                      f"MOUNTS {mounts_on('sda')}"]
    if name == "PSU":
        return "POWER", [f"GPU DRAW {(d.get('gpu_power') or 0):.0f} W", "PSU HAS NO TELEMETRY"]
    if name == "BOARD":
        return "MAINBOARD", [f"BOARD {temp(d.get('board_temp'))}   CHIPSET {temp(d.get('chipset_temp'))}"]
    if name == "FANS":
        return "AIRFLOW", [f"GPU FAN {pct(d.get('gpu_fan'))}", "CASE FANS HAVE NO TELEMETRY"]
    return "CASE", [f"{st['sys'].upper()} {st['kernel']} {st['arch']}"]


def part_state(d):
    """Per-part (intensity, heat) from real readings."""
    def lin(v, a, b_):
        return 0.0 if v is None else max(0.0, min(1.0, (v - a) / (b_ - a)))
    disks = d.get("disks") or {}

    def io(dev):
        x = disks.get(dev) or {}
        r = x.get("r", 0) + x.get("w", 0)
        return min(math.log10(1 + r) / 8.0, 1.0)
    nv = d.get("nvme_temps") or {}
    s = {
        "CASE": (0.55, 0.0), "BOARD": (0.5, lin(d.get("board_temp"), 50, 75)),
        "CPU": (0.55 + 0.45 * lin(d.get("cpu"), 0, 100), lin(d.get("cpu_temp"), 60, 90)),
        "RAM": (0.5 + 0.5 * lin(d.get("mem"), 0, 100), lin(d.get("mem"), 80, 98)),
        "GPU": (0.55 + 0.45 * lin(d.get("gpu"), 0, 100), lin(d.get("gpu_temp"), 60, 88)),
        "NVME0": (0.5 + 0.5 * io("nvme0n1"), lin(nv.get(0), 55, 75)),
        "NVME1": (0.5 + 0.5 * io("nvme1n1"), lin(nv.get(1), 55, 75)),
        "SSD": (0.5 + 0.5 * io("sda"), 0.0),
        "PSU": (0.4 + 0.6 * lin(d.get("gpu_power"), 0, 250), 0.0),
        "FANS": (0.45 + 0.55 * lin(d.get("gpu_fan"), 0, 100), 0.0),
    }
    return [s[n] for n in PARTS]


# ---------------------------------------------------------------- health + space
def health(d):
    """0 nominal, 1 degraded (amber), 2 failing (red) — from real readings only."""
    cl = d.get("cluster") or {}
    c = cl.get("cluster") or {}
    svc = cl.get("services") or {}
    down = sum(1 for v in svc.values() if (v or {}).get("status") == "down")
    if cl and ((c.get("nodesReady") is not None and c.get("nodesReady") < (c.get("nodesTotal") or 0)) or down):
        return 2
    hot = (d.get("cpu_temp") or 0) >= 90 or (d.get("gpu_temp") or 0) >= 87
    stale = d.get("cluster_at") and not d.get("cluster_ok")
    return 1 if (hot or stale) else 0


def all_green(d):
    cl = d.get("cluster") or {}
    c = cl.get("cluster") or {}
    svc = cl.get("services") or {}
    return bool(d.get("cluster_ok") and c and c.get("nodesReady") == c.get("nodesTotal") and svc
                and all((v or {}).get("status") == "up" for v in svc.values()))


def traffic_level(d):
    v = (d.get("rx") or 0.0) + (d.get("tx") or 0.0)
    return max(0.0, min(1.0, math.log10(1.0 + v) / 7.3))


def local_sun_angle():
    """The terminator follows local time: noon faces the viewer, midnight away."""
    import time as _t
    lt = _t.localtime()
    hours = lt.tm_hour + lt.tm_min / 60.0 + lt.tm_sec / 3600.0
    return (hours / 24.0) * TAU          # 0 = midnight (sun behind), pi = noon (facing)


def drift_station(b, d, space=1, t0=0.0, labels=True):
    """The orbital Drift relay: a ring station whose spokes are the lab's real
    services (lit = up, red = down), on a mast cut like the burn-in's."""
    rv = lambda k: (t0 + k) if t0 else 0.0  # noqa: E731
    svc = sorted(((k, (v or {}).get("status", "unknown")) for k, v in
                  ((d.get("cluster") or {}).get("services") or {}).items()))
    n = max(len(svc), 12)
    for y, r, a in ((0.05, 1.0, 0.95), (-0.05, 1.0, 0.95), (0.0, 0.86, 0.6)):
        pts = [(math.cos(i / 96 * TAU) * r, y, math.sin(i / 96 * TAU) * r) for i in range(97)]
        for i in range(96):
            b.line(pts[i], pts[i + 1], col("phosphor", a), space=space, reveal=rv(0.1 + i * 0.004))
    for i in range(0, 96, 4):   # ring struts
        a = i / 96 * TAU
        p0 = (math.cos(a), 0.05, math.sin(a))
        p1 = (math.cos(a), -0.05, math.sin(a))
        b.line(p0, p1, col("dim", 0.8), space=space, reveal=rv(0.4))
    for i in range(n):
        a = i / n * TAU
        name, st = svc[i] if i < len(svc) else ("", "unknown")
        c = {"up": "phosphor", "down": "danger", "warn": "amber"}.get(st, "guard")
        hub = (math.cos(a) * 0.14, 0.0, math.sin(a) * 0.14)
        rim = (math.cos(a) * 0.86, 0.0, math.sin(a) * 0.86)
        b.line(hub, rim, col(c, 0.75 if st == "up" else 0.95), space=space, reveal=rv(0.5 + i * 0.01))
        if st == "up":
            b.arc(hub, 0, 1.8, 0, TAU, col("soft", 0.9), kind=2, space=space, end=rim, speed=0.18 + 0.1 * (i % 3),
                  phase=i / n, reveal=rv(0.9))
        elif st == "down":
            b.arc(rim, 0, 4.5, 0, TAU, col("danger"), kind=2, space=space, reveal=rv(0.9))
    # hub + the mast (the first relay), with three narrowing crossbars
    for y, r in ((0.08, 0.14), (-0.08, 0.14)):
        pts = [(math.cos(i / 32 * TAU) * r, y, math.sin(i / 32 * TAU) * r) for i in range(33)]
        for i in range(32):
            b.line(pts[i], pts[i + 1], col("soft", 0.9), space=space, reveal=rv(0.3))
    b.line((0, -0.75, 0), (0, 0.9, 0), col("soft", 0.95), space=space, reveal=rv(0.2))
    for y, w in ((0.25, 0.22), (0.48, 0.16), (0.68, 0.10)):
        b.line((-w, y, 0), (w, y, 0), col("soft", 0.9), space=space, reveal=rv(0.35))
        b.line((0, y, -w), (0, y, w), col("dim", 0.7), space=space, reveal=rv(0.35))
    b.arc((0, 0.9, 0), 0, 3.0, 0, TAU, col("danger" if health(d) == 2 else "soft"), kind=2, space=space)
    if labels:
        up = sum(1 for _, s in svc if s == "up")
        b.text("THE DRIFT // RELAY ZERO", 0, -0.75, col("soft"), font="s", track=3, space=space, dx=-110, dy=40,
               reveal=rv(1.0), type_rate=0.015)
        b.text(f"{up}/{len(svc)} SERVICES LIT" if svc else "NO LAB SNAPSHOT", 0, -0.75,
               col("phosphor" if svc and up == len(svc) else "amber"), font="xs", track=2, space=space, dx=-110, dy=62,
               reveal=rv(1.1))
