"""The X-ray schematic the scanner sweep reveals: this machine's real parts as a
ghostly board blueprint, labelled with live readings. Redrawn (Cairo) just
before each pass, so the values on it are the ones of that moment."""
import math

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

from .gadgets import fmt_bytes, pct, temp  # noqa: E402

W, H = 860, 660
SOFT = (0.612, 1.0, 0.541)
PHOS = (0.2235, 1.0, 0.0784)
DIM = (0.0824, 0.608, 0.0353)
AMBER = (0.831, 0.686, 0.216)


def _text(cr, s, x, y, size=13, rgb=SOFT, weight=Pango.Weight.MEDIUM, a=1.0, spacing=1.0):
    lay = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription.from_string("Geist Mono")
    fd.set_absolute_size(size * Pango.SCALE)
    fd.set_weight(weight)
    lay.set_font_description(fd)
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_letter_spacing_new(int(spacing * Pango.SCALE)))
    lay.set_attributes(attrs)
    lay.set_text(s, -1)
    cr.set_source_rgba(*rgb, a)
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, lay)
    return lay.get_pixel_extents()[1].width


def _rect(cr, x, y, w, h, rgb=SOFT, a=0.9, dash=None):
    cr.set_source_rgba(*rgb, a)
    cr.set_line_width(1.0)
    if dash:
        cr.set_dash(dash)
    cr.rectangle(x + 0.5, y + 0.5, w, h)
    cr.stroke()
    cr.set_dash([])


def _line(cr, pts, rgb=SOFT, a=0.8, w=1.0):
    cr.set_source_rgba(*rgb, a)
    cr.set_line_width(w)
    cr.move_to(pts[0][0] + 0.5, pts[0][1] + 0.5)
    for p in pts[1:]:
        cr.line_to(p[0] + 0.5, p[1] + 0.5)
    cr.stroke()


def draw(d, st):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    # board
    bx, by, bw, bh = 40, 60, 470, 560
    cr.set_source_rgba(0.0, 0.06, 0.0, 0.55)
    cr.rectangle(bx, by, bw, bh)
    cr.fill()
    _rect(cr, bx, by, bw, bh, SOFT, 0.95)
    for hx, hy in ((bx + 14, by + 14), (bx + bw - 14, by + 14), (bx + 14, by + bh - 14), (bx + bw - 14, by + bh - 14),
                   (bx + bw / 2, by + 14), (bx + bw / 2, by + bh - 14)):
        cr.arc(hx, hy, 5, 0, 2 * math.pi)
        cr.set_source_rgba(*DIM, 0.9)
        cr.stroke()
    for k in range(9):   # traces
        y = by + 70 + k * 52
        _line(cr, [(bx + 20, y), (bx + 60 + (k % 3) * 20, y), (bx + 90 + (k % 3) * 20, y + 18), (bx + 150, y + 18)], DIM, 0.6)
    # CPU socket with a pin field
    cx, cy, cs = 220, 120, 130
    _rect(cr, cx, cy, cs, cs, SOFT, 1.0)
    _rect(cr, cx + 14, cy + 14, cs - 28, cs - 28, PHOS, 0.7)
    cr.set_source_rgba(*PHOS, 0.55)
    for i in range(12):
        for j in range(12):
            cr.rectangle(cx + 22 + i * 7.6, cy + 22 + j * 7.6, 1.6, 1.6)
    cr.fill()
    # DIMM slots
    for k in range(4):
        _rect(cr, 390 + k * 22, 80, 12, 250, SOFT if k % 2 else DIM, 0.85)
    # M.2 slots
    _rect(cr, 90, 290, 150, 18, SOFT, 0.95)
    _rect(cr, 90, 520, 150, 18, SOFT, 0.95)
    # PCIe + GPU outline
    _rect(cr, 70, 360, 420, 12, DIM, 0.9)
    _rect(cr, 60, 380, 440, 110, SOFT, 0.9, dash=[6, 4])
    for fx in (170, 360):
        cr.arc(fx, 435, 42, 0, 2 * math.pi)
        cr.set_source_rgba(*SOFT, 0.7)
        cr.stroke()
        for s in range(7):
            a = s / 7 * 2 * math.pi
            _line(cr, [(fx, 435), (fx + 40 * math.cos(a), 435 + 40 * math.sin(a))], DIM, 0.6)
    # SATA + the 2.5" SSD off-board
    _rect(cr, 470, 560, 26, 30, SOFT, 0.9)
    _rect(cr, 560, 540, 150, 80, SOFT, 0.9)
    _line(cr, [(496, 575), (530, 575), (530, 580), (560, 580)], DIM, 0.8)
    # labels with leader lines
    drives = {x["name"]: x for x in st.get("drives", [])}
    mounts = d.get("mounts") or []
    nv = d.get("nvme_temps") or {}

    def mnt(dev):
        ms = sorted({m["mount"] for m in mounts if m["dev"].startswith(dev)})
        return " ".join(ms) if ms else "UNMOUNTED"

    def mpct(dev):
        ms = [m for m in mounts if m["dev"].startswith(dev)]
        return f"{ms[0]['pct']:.0f}% FULL" if ms else ""
    vt = d.get("vram_total")
    rows = [
        ((cx + cs, cy + 40), "CPU", st["cpu_model"].upper().replace(" PROCESSOR", ""),
         f"LOAD {pct(d.get('cpu'))}  TCTL {temp(d.get('cpu_temp'))}  {st['cores_phys']}C/{st['threads']}T"),
        ((478, 120), "RAM", f"{fmt_bytes(d.get('mem_total'))} SYSTEM MEMORY",
         f"IN USE {fmt_bytes(d.get('mem_used'))}  ({pct(d.get('mem'))})"),
        ((240, 299), "NVME0", f"{drives.get('nvme0n1', {}).get('model', 'NVME0').upper()}",
         f"{temp(nv.get(0))}  {mnt('nvme0n1')}  {mpct('nvme0n1')}"),
        ((500, 410), "GPU", st["gpu_name"].upper().replace("NVIDIA ", ""),
         f"LOAD {pct(d.get('gpu'))}  {temp(d.get('gpu_temp'))}  VRAM {(d.get('vram_used') or 0) / 1024:.1f}/{(vt or 0) / 1024:.0f} GB"),
        ((240, 529), "NVME1", f"{drives.get('nvme1n1', {}).get('model', 'NVME1').upper()}",
         f"{temp(nv.get(1))}  {mnt('nvme1n1')}"),
        ((710, 560), "SSD", f"{drives.get('sda', {}).get('model', 'SATA').upper()}",
         f"{mnt('sda')}  {mpct('sda')}"),
    ]
    lx = 560
    for i, ((ax, ay), tag, l1, l2) in enumerate(rows[:5]):
        ty = 70 + i * 90
        cr.set_source_rgba(0.0, 0.05, 0.0, 0.82)
        cr.rectangle(lx - 8, ty - 6, 300, 58)
        cr.fill()
        _rect(cr, lx - 8, ty - 6, 300, 58, DIM, 0.9)
        _line(cr, [(ax, ay), (lx - 30, ty + 20), (lx - 8, ty + 20)], SOFT, 0.85)
        cr.arc(ax, ay, 3, 0, 2 * math.pi)
        cr.set_source_rgba(*SOFT, 1)
        cr.fill()
        w = _text(cr, tag, lx, ty - 2, 13, PHOS, Pango.Weight.BOLD, spacing=2.5)
        _text(cr, l1[:26], lx + w + 10, ty - 1, 12, SOFT, spacing=0.6)
        _text(cr, l2[:36], lx, ty + 24, 12, AMBER if tag in ("CPU", "GPU") and (d.get(tag.lower()) or 0) > 85 else SOFT,
              spacing=0.6, a=0.95)
    (ax, ay), tag, l1, l2 = rows[5]
    _text(cr, f"{tag}  {l1}", 560, 628, 12, SOFT, spacing=0.6)
    _text(cr, l2, 560, 644, 11, DIM, spacing=0.6)
    _text(cr, "SCAN // WORKSTATION INTERNALS", 40, 22, 14, SOFT, Pango.Weight.SEMIBOLD, spacing=3)
    _text(cr, f"{st['sys'].upper()} {st['kernel']} {st['arch']}", 510, 24, 11, DIM, spacing=1, a=0.9)
    surf.flush()
    return surf
