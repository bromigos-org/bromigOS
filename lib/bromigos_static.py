"""STATIC, the Bromigos mascot, drawn in code: a rig of parts, his screen faces, his poses
and their short loops, as SVG in the theme's colours (docs/ASSETS.md, "STATIC, the mascot").

One STATIC for every surface: bromigOS's Den TV guide and media TUI, BRODEC's Den remote and
the watch all draw him from these parts. Nothing here is a generated image: every shape is
written below, so the art is ours to ship (the concept sheets that inspired it are lab-only).

  svg(pose="stand", face=None, frame=0, pal=None, level="glow", hc=False, size=None, crop=None)
      the whole figure as an SVG document; pose from POSES, face from FACES (or the pose's own),
      frame picks a step of the pose's loop (LOOPS), level is DRIFTGLASS's: ember (flat, no
      glow), glow (the default) or flare (a stronger glow and an emitter under him); hc is
      high contrast (white outline, solid fills, no glow or scanlines).
  face_grid(name, frame=0, mini=False) -> list of strings ('#' lit, '+' soft, 'a' amber, '.' off)
  parts()  -> {name: (svg body in local coords, pivot, children)}: the rig, for Lottie and Flutter
  roles(pal=None, hc=False) -> the colours every shape uses, from the theme's palette

Pure Python, no dependencies: bromigOS, the TUIs and the art tools import it as is.
"""
import math
import random

# The Wick's palette (the default theme); a theme passes its own roles.
WICK = {"void": "#000500", "panel": "#001300", "selection": "#003b00", "primary": "#39ff14",
        "soft": "#9cff8a", "dim": "#159b09", "text": "#c4f5bb", "muted": "#7e927e",
        "faint": "#4e6b4e", "warn": "#d4af37", "danger": "#ff766f", "white": "#e8ffe0"}

# The figure's box, in rig units (y down, the ground at 0, his middle at x 0).
BOX = (-110, -340, 220, 360)


# ------------------------------------------------------------------ colours
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def mix(a, b, f):
    """a towards b by f (0..1)."""
    a, b = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * f for x, y in zip(a, b)))


def roles(pal=None, hc=False):
    """The colours of every shape, from a theme's roles: the outline is the primary, the body
    a dark tint of it on the void, the face pixels the primary and soft, the tally lamp amber."""
    p = dict(WICK)
    p.update(pal or {})
    r = {
        "line": p["primary"], "fill": mix(p["void"], p["primary"], 0.20),
        "fill2": mix(p["void"], p["primary"], 0.11), "detail": mix(p["void"], p["primary"], 0.62),
        "screen": mix(p["void"], p["primary"], 0.035), "px": p["primary"], "px2": p["soft"],
        "amber": p["warn"], "amberhot": mix(p["warn"], "#ffffff", 0.35), "shine": p["white"],
        "void": p["void"], "glow": p["primary"], "danger": p.get("danger", "#ff766f"),
    }
    if hc:
        r.update(line=p.get("white", "#ffffff"), fill=p["panel"], fill2=p["void"], detail=p["text"],
                 screen=p["void"], px=p.get("white", "#ffffff"), px2=p["text"])
    return r


# ------------------------------------------------------------------ the faces
# Each face is a 20x13 grid of the screen's pixels: '#' lit, '+' soft, 'a' amber, '.' off.
# The first six are the faces BLACKFLAME approved (2026-10-31); the rest are Den TV's.
FACES = {
    "neutral": [
        "....................",
        "....................",
        "....................",
        "...####......####...",
        "...####......####...",
        "...####......####...",
        "...####......####...",
        "....................",
        "....................",
        "........####........",
        "....................",
        "....................",
        "...................."],
    "happy": [
        "....................",
        "....................",
        "....................",
        "....###......###....",
        "...##.##....##.##...",
        "..##...##..##...##..",
        "....................",
        "....................",
        "....................",
        "....................",
        "....................",
        "....................",
        "...................."],
    "smug": [
        "....................",
        "....................",
        "....................",
        "....................",
        "..######....######..",
        ".....##........##...",
        ".....##........##...",
        "....................",
        "................#...",
        ".......#.......#....",
        "........#######.....",
        "....................",
        "...................."],
    "startled": [
        "....................",
        "....................",
        "...#####....#####...",
        "...#####....#####...",
        "...##.##....##.##...",
        "...##.##....##.##...",
        "...#####....#####...",
        "...#####....#####...",
        "....................",
        ".........##.........",
        "........#..#........",
        ".........##.........",
        "...................."],
    "suspicious": [
        "....................",
        "....................",
        "....................",
        "....................",
        "..######....######..",
        "..##........##......",
        "....................",
        "....................",
        "....................",
        "....................",
        "....................",
        "....................",
        "...................."],
    "glum": [
        "....................",
        "....................",
        "......##....##......",
        "...###........###...",
        "....###......###....",
        "....###......###....",
        "....................",
        ".....+........+.....",
        "....................",
        "....+..........+....",
        "....................",
        ".....+........+.....",
        "...................."],
    # listening is drawn: a sound-wave across the screen (it moves)
    "listening": None,
    # Den TV's own faces
    "watching": [
        "....................",
        "....................",
        "....................",
        "....###......###....",
        "....#.#......#.#....",
        "....###......###....",
        "....................",
        "....................",
        "....................",
        ".........##.........",
        "....................",
        "....................",
        "...................."],
    "laughing": [
        "....................",
        "....................",
        "....###......###....",
        "...##.##....##.##...",
        "..##...##..##...##..",
        "....................",
        "....................",
        "......########......",
        "......#++++++#......",
        ".......#++++#.......",
        "........####........",
        "....................",
        "...................."],
    "asleep": [
        "................###.",
        ".................#..",
        "................###.",
        "....................",
        "....................",
        "...#..#......#..#...",
        "....##........##....",
        "....................",
        "....................",
        "........+++.........",
        "....................",
        "....................",
        "...................."],
    "snow": [],                       # all noise: the channel changing
    "onair": [
        "....................",
        "....................",
        "....................",
        "...####......####...",
        "...####......####...",
        "...####......####...",
        "....................",
        "....................",
        "...#............#...",
        "....############....",
        "....................",
        "....................",
        "...................."],
    "popcorn": [
        "....................",
        "....................",
        "...#####....#####...",
        "...#...#....#...#...",
        "...#.###....#.###...",
        "...#####....#####...",
        "....................",
        "....................",
        "....................",
        ".......#.##.#.......",
        "........#..#........",
        "......+......+......",
        "...................."],
    "whack": [
        "....................",
        "....................",
        "...#..#......#..#...",
        "....##........##....",
        "....##........##....",
        "...#..#......#..#...",
        "....................",
        "....................",
        "....................",
        "......#.#.#.#.......",
        ".......#.#.#.#......",
        "....................",
        "...................."],
    "fiddle": [
        "....................",
        "...####......####...",
        "...#..#......#..#...",
        "....................",
        "....................",
        "....................",
        "....................",
        "....................",
        "....................",
        "........####........",
        "..........##........",
        "..........++........",
        "...................."],
}
APPROVED = ("happy", "smug", "startled", "suspicious", "glum", "listening")
DEN = ("watching", "laughing", "asleep", "snow", "onair", "popcorn", "whack", "fiddle")
# noise over the screen, as a share of its pixels (soft), per face
SNOW = {"startled": 0.05, "asleep": 0.04, "snow": 0.55, "whack": 0.08, "fiddle": 0.07}
GW, GH = 20, 13

# The same faces at half size (10x7), drawn by hand: for heads too small for the full grid.
MINI = {
    "neutral": ["..........", ".##....##.", ".##....##.", "..........", "...####...", "..........", ".........."],
    "happy": ["..........", "..#....#..", ".#.#..#.#.", "..........", "..........", "..........", ".........."],
    "smug": ["..........", ".###..###.", "..##...##.", "..........", ".......#..", "...####...", ".........."],
    "startled": [".###..###.", ".#.#..#.#.", ".###..###.", "..........", "....##....", "....##....", ".........."],
    "suspicious": ["..........", "..........", ".###..###.", ".#....#...", "..........", "..........", ".........."],
    "glum": ["..........", "..#....#..", ".##....##.", ".##....##.", ".+......+.", "..........", ".+......+."],
    "watching": ["..........", ".###..###.", ".#.#..#.#.", ".###..###.", "..........", "....##....", ".........."],
    "laughing": ["..........", "..#....#..", ".#.#..#.#.", "..........", "..######..", "...#++#...", "....##...."],
    "asleep": ["........#.", ".......#..", "........#.", ".###..###.", "..........", "....++....", ".........."],
    "onair": ["..........", ".###..###.", ".###..###.", "..........", "#........#", ".########.", ".........."],
    "popcorn": [".###..###.", ".#.#..#.#.", ".###..###.", "..........", "...#..#...", "....##....", "..+....+.."],
    "whack": [".#.#..#.#.", "..#....#..", ".#.#..#.#.", "..........", "..#.#.#.#.", "...#.#.#..", ".........."],
    "fiddle": [".##....##.", ".##....##.", "..........", "..........", "...####...", ".....##...", ".....++..."],
    "snow": [],
}
MW, MH = 10, 7


def _wave(frame, w=GW, h=GH):
    """The listening face: a sound-wave along the middle row, moving with the frame."""
    g = [["."] * w for _ in range(h)]
    rnd = random.Random(7 + frame * 31)
    mid = h // 2
    for x in range(1, w - 1):
        env = math.sin(math.pi * x / (w - 1))
        hh = int(round(env * rnd.choice((0, 1, 1, 2, 3, 4)) * h / GH))
        for y in range(mid - hh, mid + hh + 1):
            g[y][x] = "#" if abs(y - mid) < max(1, hh) or hh == 0 else "+"
    return ["".join(r) for r in g]


def face_grid(name, frame=0, mini=False):
    """A face's pixels (rows of '#', '+', 'a', '.'), the snow it carries mixed in for this
    frame. mini: the hand-drawn half-size set (10x7), for heads drawn very small."""
    w, h = (MW, MH) if mini else (GW, GH)
    if name == "listening":
        g = _wave(frame, w, h)
    else:
        g = list((MINI if mini else FACES).get(name) or [])
        if not g:
            g = ["." * w] * h
    rows = [list(r) for r in g]
    amount = SNOW.get(name, 0) * (0.6 if mini and name != "snow" else 1)
    if amount:
        rnd = random.Random(1000 + frame * 7919 + sum(map(ord, name)) + (5 if mini else 0))
        for y in range(h):
            for x in range(w):
                if rows[y][x] == "." and rnd.random() < amount:
                    rows[y][x] = "+"
        if name == "snow":                       # the roll bar: a brighter band moving down
            band = (frame * (2 if mini else 4)) % (h + 3) - 1
            for y in (band, band + 1):
                if 0 <= y < h:
                    for x in range(w):
                        if rnd.random() < 0.7:
                            rows[y][x] = "#"
    return ["".join(r) for r in rows]


# ------------------------------------------------------------------ shapes
def _f(v):
    return ("%.2f" % v).rstrip("0").rstrip(".")


def rrect(x0, y0, x1, y1, r):
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    return (f"M{_f(x0 + r)},{_f(y0)} H{_f(x1 - r)} A{_f(r)},{_f(r)} 0 0 1 {_f(x1)},{_f(y0 + r)} "
            f"V{_f(y1 - r)} A{_f(r)},{_f(r)} 0 0 1 {_f(x1 - r)},{_f(y1)} H{_f(x0 + r)} "
            f"A{_f(r)},{_f(r)} 0 0 1 {_f(x0)},{_f(y1 - r)} V{_f(y0 + r)} A{_f(r)},{_f(r)} 0 0 1 {_f(x0 + r)},{_f(y0)} Z")


def poly(pts, close=True):
    return "M" + " L".join(f"{_f(x)},{_f(y)}" for x, y in pts) + (" Z" if close else "")


def ellipse(cx, cy, rx, ry):
    return (f"M{_f(cx - rx)},{_f(cy)} A{_f(rx)},{_f(ry)} 0 1 0 {_f(cx + rx)},{_f(cy)} "
            f"A{_f(rx)},{_f(ry)} 0 1 0 {_f(cx - rx)},{_f(cy)} Z")


class Ink:
    """Shapes for one part, in its own coordinates: body (fill + outline), shade (darker
    fill + outline), detail (thin inner lines), lit (glowing fills) and raw SVG."""

    def __init__(self, R, ol, lod):
        self.R, self.ol, self.lod, self.out = R, ol, lod, []

    def body(self, d, fill="fill", w=1.0):
        self.out.append(f'<path d="{d}" fill="{self.R[fill]}" stroke="{self.R["line"]}" '
                        f'stroke-width="{_f(self.ol * w)}" stroke-linejoin="round"/>')

    def shade(self, d, w=1.0):
        self.body(d, "fill2", w)

    def detail(self, d, w=0.5, role="detail", min_lod=1):
        if self.lod >= min_lod:
            self.out.append(f'<path d="{d}" fill="none" stroke="{self.R[role]}" stroke-width="{_f(self.ol * w)}" '
                            f'stroke-linecap="round" stroke-linejoin="round"/>')

    def lit(self, d, role="px", opacity=1.0):
        self.out.append(f'<path d="{d}" fill="{self.R[role]}"' +
                        (f' fill-opacity="{_f(opacity)}"' if opacity < 1 else "") + "/>")

    def raw(self, s):
        self.out.append(s)

    def svg(self):
        return "".join(self.out)


# ------------------------------------------------------------------ the parts
# Every part is drawn in its own coordinates around its pivot (0, 0); the joints its children
# hang from are in JOINTS. Units: the figure stands about 330 tall.
JOINTS = {
    "torso": {"neck": (0, -76), "shoulder_l": (-41, -60), "shoulder_r": (41, -60)},
    "head": {"antenna": (40, -108), "screen": (0, 0), "cable": (62, -44)},
    "upperarm": {"elbow": (0, 34)},
    "forearm": {"wrist": (0, 30)},
    "hip": {"hip_l": (-18, 8), "hip_r": (18, 8)},
    "thigh": {"knee": (0, 36)},
    "shin": {"ankle": (0, 32)},
}
LEG_TO_GROUND = 36 + 32 + 22          # hip joint to the ground, standing


def part_head(k, view="front", lamp=False):
    """The monitor: a chunky portable CRT, a little turned so its right side shows. Pivot: the
    middle of its base, where it sits on the collar."""
    if view == "back":
        k.shade(poly([(-58, -100), (-42, -109), (70, -109), (70, -15), (54, -6), (-58, -6)]))
        k.body(rrect(-58, -100, 54, -6, 12))
        k.detail(rrect(-46, -88, 42, -18, 8))
        for i in range(5):
            y = -76 + i * 10
            k.detail(poly([(-30, y), (26, y)], close=False), w=0.6)
        k.body(ellipse(-50, -53, 5, 9), "fill2")          # the knob, seen from behind
    elif view == "side":
        k.shade(poly([(-46, -100), (-38, -106), (40, -106), (46, -98), (46, -10), (40, -6), (-46, -6)]))
        k.body(rrect(-46, -100, 40, -6, 10))
        k.body(rrect(40, -92, 54, -14, 6), "fill2")         # the screen's bulge, edge on
        k.detail(poly([(52, -86), (52, -20)], close=False), w=0.6, role="px")
        for i in range(4):
            y = -80 + i * 9
            k.detail(poly([(-34, y), (-12, y - 4)], close=False), w=0.6)
        k.body(ellipse(-4, -50, 9, 9), "fill2")
        k.lit(ellipse(-4, -50, 4, 4), "px")
    else:
        # the box behind the front face: the top and the right side
        k.shade(poly([(-58, -100), (-42, -109), (70, -109), (70, -15), (54, -6), (-58, -6)]))
        k.detail(poly([(54, -100), (70, -109)], close=False), w=0.7, role="line", min_lod=0)
        k.detail(poly([(-42, -109), (70, -109)], close=False), w=0.0)
        for i in range(3):                                   # vents on the side
            y = -88 + i * 7
            k.detail(poly([(59, y), (66, y - 4)], close=False), w=0.6)
        k.body(rrect(-58, -100, 54, -6, 12))
        k.detail(rrect(-53, -95, 49, -11, 9), w=0.45)        # the bezel's inner edge
        # the knob and the earpiece socket on the side
        k.body(ellipse(62, -52, 6.5, 10), "fill2")
        k.lit(ellipse(62.5, -52, 3, 5), "px")
    # the tally lamp: amber, lit when he's on air
    if view != "back":
        lx = -30 if view == "front" else -24
        k.body(rrect(lx - 7, -110, lx + 7, -104, 2), "fill2", w=0.8)
        k.body(f"M{lx - 6},-110 A6,6 0 0 1 {lx + 6},-110 Z", "amberhot" if lamp else "amber", w=0.8)
    return k


def part_screen(k, face="neutral", frame=0, R=None, hc=False, lod=2):
    """The screen: the glass, its scanlines and the face's pixels (head coordinates). The face
    area is x -44..40, y -81..-24: a 20x13 grid of 4.2-unit pixels."""
    k.raw(f'<path d="{rrect(-48, -90, 44, -16, 9)}" fill="{k.R["screen"]}" stroke="{k.R["line"]}" '
          f'stroke-width="{_f(k.ol * 0.7)}"/>')
    grid = face_grid(face, frame, mini=lod == 0)
    gw, gh = len(grid[0]) if grid else GW, len(grid)
    px = 84.0 / gw
    ox, oy = -44.0, -52.5 - gh * px / 2
    lit, soft, amber = [], [], []
    for y, row in enumerate(grid):
        for x, c in enumerate(row):
            if c == ".":
                continue
            d = f"M{_f(ox + x * px + 0.3)},{_f(oy + y * px + 0.3)}h{_f(px - 0.6)}v{_f(px - 0.6)}h{_f(-(px - 0.6))}z"
            (lit if c == "#" else amber if c == "a" else soft).append(d)
    if soft:
        k.lit("".join(soft), "px2", 0.45)
    if lit:
        k.lit("".join(lit), "px")
    if amber:
        k.lit("".join(amber), "amber")
    if not hc and lod >= 1:
        lines = "".join(f"M-47,{_f(y)}H43" for y in [-88 + i * 3.2 for i in range(23)])
        k.raw(f'<path d="{lines}" stroke="{k.R["void"]}" stroke-opacity="0.35" stroke-width="1.1"/>')
        # the glass's shine, and a flicker band that moves with the frame
        k.raw(f'<path d="M-40,-86 Q-46,-60 -42,-34 L-38,-34 Q-41,-60 -35,-86 Z" fill="{k.R["shine"]}" '
              f'fill-opacity="0.07"/>')
        band = -88 + (frame * 17) % 70
        k.raw(f'<rect x="-47" y="{_f(band)}" width="90" height="5" fill="{k.R["px"]}" fill-opacity="0.06"/>')
    return k


def part_antenna(k):
    """One telescoping antenna and its bead. Pivot: its foot on the monitor's top; it points
    straight up here and the pose turns it (about 30 degrees, jauntily, by default)."""
    k.body(ellipse(0, 0, 7, 3.5), "fill2", w=0.8)
    k.raw(f'<path d="M0,-3 V-40" stroke="{k.R["line"]}" stroke-width="{_f(k.ol * 1.25)}" stroke-linecap="round"/>')
    k.raw(f'<path d="M0,-40 V-58" stroke="{k.R["line"]}" stroke-width="{_f(k.ol * 0.9)}" stroke-linecap="round"/>')
    k.body(ellipse(0, -61, 5, 5), "fill", w=0.8)
    return k


def part_cable(k, lod=2):
    """The earpiece's coiled wire, from the socket on the monitor's side down to the collar
    (head coordinates; pivot at the socket)."""
    pts = []
    p0, p1, p2 = (0, 0), (8, 22), (-22, 44)
    n = 90
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        dx = 2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
        dy = 2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
        ln = math.hypot(dx, dy) or 1
        a = 3.2 * math.sin(t * math.pi * 2 * 9) if lod >= 1 else 0
        pts.append((x - dy / ln * a, y + dx / ln * a))
    k.raw(f'<path d="{poly(pts, close=False)}" fill="none" stroke="{k.R["line"]}" '
          f'stroke-width="{_f(k.ol * 0.5)}" stroke-linecap="round"/>')
    return k


def part_torso(k, view="front"):
    """The jacket, the belt and the top of the trousers. Pivot: the middle of the hips."""
    k.shade(rrect(-36, -6, 36, 18, 10))                                    # trousers' seat
    k.body(rrect(-40, -8, 40, 2, 3), "fill2", w=0.9)                       # the belt
    if view != "back":
        k.body(rrect(-6, -9, 6, 3, 2), "fill", w=0.7)                      # its buckle
    if view == "side":
        k.shade(rrect(-26, -6, 26, 18, 10))
        k.body(rrect(-28, -8, 28, 2, 3), "fill2", w=0.9)
        k.body("M-30,-8 C-34,-30 -34,-52 -28,-64 C-22,-72 22,-72 28,-64 C34,-52 34,-30 30,-8 C16,-4 -16,-4 -30,-8 Z")
        k.body("M-10,-86 L14,-86 L18,-68 L-14,-68 Z", w=0.9)
        k.detail("M14,-66 C16,-46 16,-28 14,-10", w=0.5)
        k.body(rrect(8, -48, 28, -30, 3), w=0.7)
        return k
    jacket = ("M-42,-8 C-46,-24 -47,-44 -44,-56 C-42,-64 -36,-70 -24,-73 L24,-73 "
              "C36,-70 42,-64 44,-56 C47,-44 46,-24 42,-8 C28,-4 -28,-4 -42,-8 Z")
    k.body(jacket)
    if view == "side":
        k.detail("M-10,-70 C-4,-50 -4,-26 -8,-10", w=0.5)
        k.body(rrect(-2, -48, 22, -30, 3), w=0.7)
        return k
    k.detail("M-36,-14 C-20,-10 20,-10 36,-14", w=0.45)                    # the hem's puff
    if view == "back":
        k.detail("M-30,-60 C-10,-54 10,-54 30,-60", w=0.45)
        k.body(rrect(-24, -84, 24, -68, 8), "fill2", w=0.9)                # the collar from behind
        return k
    k.raw(f'<path d="{rrect(-12, -84, 12, -70, 4)}" fill="{k.R["void"]}"/>')  # the dark neck
    # the stand-up collar, open at the front
    k.body("M-24,-72 L-22,-86 L-6,-80 L-4,-68 Z", w=0.9)
    k.body("M24,-72 L22,-86 L6,-80 L4,-68 Z", w=0.9)
    k.detail("M-1,-68 C0,-48 1,-28 1,-9", w=0.5)                           # the zip
    k.detail("M-3,-66 h6", w=0.7, role="line")
    for x0 in (-34, 11):                                                   # chest pockets with flaps
        k.detail(rrect(x0, -50, x0 + 22, -30, 2.5), w=0.5)
        k.detail(f"M{x0 - 1},-45 H{x0 + 23}", w=0.5)
    return k


def part_upperarm(k, patch=False):
    """A puffy sleeve, shoulder to elbow. Pivot: the shoulder; the elbow is 34 down."""
    k.body(rrect(-14, -8, 14, 40, 13))
    k.detail("M-10,22 C-4,25 4,25 10,22", w=0.45, min_lod=2)
    if patch:                                                              # the shoulder patch
        k.body("M-7,0 L7,-2 L9,12 L1,19 L-8,12 Z", "fill2", w=0.6)
        k.lit("M-3,3 L5,1 L-1,14 Z", "px", 0.75)
    return k


def part_forearm(k, cuff=False):
    """The sleeve, elbow to wrist. Pivot: the elbow; the wrist is 30 down. cuff: his wrist unit
    (a CUFF of his own), with its little lit screen."""
    k.body(rrect(-12.5, -6, 12.5, 32, 11.5))
    k.detail("M-11,24 H11", w=0.45)
    if cuff:
        k.body(rrect(-14, 13, 14, 31, 3), "fill2", w=0.8)
        k.lit(rrect(-9, 17, 9, 27, 1.5), "px", 0.9)
    return k


def part_hand(k, kind="open"):
    """A gloved hand. Pivot: the wrist. open, fist or grip (closed round something)."""
    if kind == "fist" or kind == "grip":
        k.body(rrect(-11, -2, 11, 19, 8))
        k.detail("M-7,12 H7 M-7,7 H7", w=0.4, min_lod=2)
        k.body(ellipse(-9, 8, 4.5, 6.5), w=0.7)                            # the thumb
    else:
        k.body("M-10,0 C-13,6 -12,18 -6,22 C-2,25 4,25 8,21 C12,16 12,6 9,0 Z")
        k.body("M8,4 C14,2 17,6 15,11 C13,14 10,13 9,11 Z", w=0.7)         # the thumb
        k.detail("M-5,12 V20 M0,13 V22 M5,12 V20", w=0.4, min_lod=2)
    return k


def part_thigh(k, pocket=False):
    """A cargo trouser leg, hip to knee. Pivot: the hip joint; the knee is 36 down."""
    k.body(rrect(-16, -6, 16, 42, 14))
    if pocket:
        k.detail(rrect(-19, 12, -7, 30, 2), w=0.5)
    return k


def part_shin(k):
    """The trouser leg, knee to ankle, bunched over the boot. Pivot: the knee."""
    k.body(rrect(-15, -6, 15, 34, 12))
    k.detail("M-12,24 C-6,27 6,27 12,24 M-11,29 C-4,31 4,31 11,29", w=0.4, min_lod=2)
    return k


def part_boot(k):
    """A chunky laced boot, toe to the right (the pose mirrors it). Pivot: the ankle."""
    k.body(rrect(-14, -6, 14, 12, 4), "fill2")
    k.body("M-17,6 L-17,19 C-17,21 -15,22 -13,22 L22,22 C26,22 27,18 25,14 C22,8 14,7 8,6 Z")
    k.body(rrect(-18, 18, 26, 24, 3), "fill2", w=0.8)                       # the sole
    k.detail("M-6,0 L6,2 M-6,5 L6,7 M2,10 L10,11", w=0.45, min_lod=2)
    return k


# ------------------------------------------------------------------ props
def prop_remote(k, pressed=False, beam=False):
    """The Den remote, held in a grip. Pivot: the grip, so a hand's grip holds it."""
    k.body(rrect(-6, -26, 6, 14, 3.5), "fill2")
    k.lit(rrect(-3.5, -23, 3.5, -19, 1), "amber" if pressed else "px", 1 if pressed else 0.8)
    for y in (-15, -10, -5):
        k.lit(f"M-3,{y}h2.4v2.4h-2.4z M0.6,{y}h2.4v2.4h-2.4z", "px", 0.55)
    if beam:                                                                # the IR click, as rings
        for i, r in enumerate((7, 13, 19)):
            k.raw(f'<path d="M{_f(-r * 0.7)},{_f(-28 - r * 0.7)} A{r},{r} 0 0 1 {_f(r * 0.7)},{_f(-28 - r * 0.7)}" '
                  f'fill="none" stroke="{k.R["px"]}" stroke-opacity="{_f(0.9 - i * 0.25)}" '
                  f'stroke-width="{_f(k.ol * 0.6)}" stroke-linecap="round"/>')
    return k


def prop_armchair_back(k):
    """A small, worn armchair: its back and seat, drawn behind him. Pivot: the seat's front
    middle, on the floor's line at y 0 being the seat top."""
    k.body("M-70,-128 C-72,-140 -60,-148 0,-148 C60,-148 72,-140 70,-128 L66,6 L-66,6 Z", "fill2")
    k.detail("M-50,-120 C-20,-128 20,-128 50,-120 M-52,-80 C-20,-86 20,-86 52,-80", w=0.45)
    k.body(rrect(-62, -10, 62, 16, 8), "fill")                               # the seat cushion
    return k


def prop_armchair_front(k):
    """The armchair's arms and its skirt, drawn in front of his hips."""
    for s in (-1, 1):
        x0, x1 = (-84, -54) if s < 0 else (54, 84)
        k.body(rrect(x0, -44, x1, 46, 12), "fill")
        k.detail(f"M{x0 + 6},-30 C{(x0 + x1) / 2},-36 {(x0 + x1) / 2},-36 {x1 - 6},-30", w=0.45)
    k.body(rrect(-58, 14, 58, 46, 6), "fill2")
    for x in (-74, 74):
        k.body(rrect(x - 4, 46, x + 4, 58, 2), "fill2", w=0.7)
    return k


def prop_desk(k, sign=True):
    """A little broadcast desk: the front panel with a scanline stripe, a mic on a stem and
    the ON AIR box. Pivot: the desk top's front middle."""
    k.body(rrect(-112, -6, 112, 6, 3), "fill")                               # the desktop
    k.body("M-104,6 L104,6 L96,96 L-96,96 Z", "fill2")
    k.detail("M-98,30 H98 M-96,38 H96", w=0.45)
    k.lit(rrect(-60, 52, 60, 58, 2), "px", 0.6)
    k.lit(rrect(-40, 64, 40, 67, 1.5), "px", 0.35)
    # the mic on its stem
    k.raw(f'<path d="M58,-6 C58,-20 62,-30 70,-38" fill="none" stroke="{k.R["line"]}" '
          f'stroke-width="{_f(k.ol * 0.9)}" stroke-linecap="round"/>')
    k.body(rrect(64, -52, 80, -34, 7), "fill2", w=0.8)
    k.detail("M66,-46 H78 M66,-41 H78", w=0.4)
    if sign:                                                                 # the ON AIR box: lit amber
        k.body(rrect(-104, -36, -50, -8, 4), "fill2", w=0.8)
        k.lit(rrect(-100, -32, -54, -12, 2.5), "amber")
        k.raw(f'<text x="-77" y="-17.5" font-family="Geist Mono, DejaVu Sans Mono, monospace" font-size="12" '
              f'font-weight="700" text-anchor="middle" fill="{k.R["void"]}">ON AIR</text>')
    return k


def prop_cards(k):
    """A stack of cue cards in a hand. Pivot: the grip."""
    k.body("M-18,-40 L14,-44 L18,4 L-14,8 Z", "fill")
    k.body("M-16,-36 L16,-40 L20,6 L-12,10 Z", "fill")
    k.detail("M-10,-28 L10,-31 M-9,-20 L11,-23 M-8,-12 L8,-14", w=0.45)
    return k


def prop_popcorn(k):
    """A striped popcorn tub. Pivot: its base's middle."""
    k.body("M-16,0 L-20,-34 L20,-34 L16,0 Z", "fill2")
    k.lit("M-12,-1 L-15,-33 L-9,-33 L-7,-1 Z M3,-1 L3,-33 L9,-33 L7,-1 Z", "px", 0.35)
    for x, y in ((-14, -38), (-6, -42), (3, -40), (11, -38), (-2, -36), (8, -44), (15, -35)):
        k.body(ellipse(x, y, 5, 4.5), "fill", w=0.6)
    return k


def prop_zzz(k, frame=0):
    """Three Zs drifting up from a sleeping head (pixel letters, soft)."""
    for i, (x, y, s) in enumerate(((0, 0, 5), (12, -16, 6.5), (26, -36, 8))):
        y -= (frame % 4) * 2
        op = 0.35 + 0.2 * i
        k.raw(f'<path d="M{x},{y} h{s} l-{s},{s} h{s}" fill="none" stroke="{k.R["px2"]}" '
              f'stroke-opacity="{_f(op)}" stroke-width="{_f(k.ol * 0.7)}" stroke-linejoin="round"/>')
    return k


def prop_rabbit_ears(k, spread=0):
    """A set-top rabbit-ear antenna, held up by its base for better reception. Pivot: the grip
    (the base's middle); the rods point up and out in a V."""
    for side in (-1, 1):
        a = math.radians(side * (24 + spread))
        tip = (math.sin(a) * 78, -10 - math.cos(a) * 78)
        k.raw(f'<path d="M{side * 4},-10 L{_f(tip[0])},{_f(tip[1])}" stroke="{k.R["line"]}" '
              f'stroke-width="{_f(k.ol * 0.85)}" stroke-linecap="round"/>')
        k.body(ellipse(tip[0], tip[1], 4, 4), "fill", w=0.7)
    k.body("M-16,6 C-16,-14 16,-14 16,6 Z", "fill2")
    k.body(rrect(-18, 4, 18, 12, 3), "fill", w=0.8)
    k.lit(ellipse(0, -2, 2.5, 2.5), "amber")
    return k


def prop_spark(k):
    """The whack: three short impact lines."""
    for a in (-35, 0, 35):
        r = math.radians(a)
        x0, y0 = math.cos(r) * 10, math.sin(r) * 10
        x1, y1 = math.cos(r) * 22, math.sin(r) * 22
        k.raw(f'<path d="M{_f(x0)},{_f(y0)} L{_f(x1)},{_f(y1)}" stroke="{k.R["amber"]}" '
              f'stroke-width="{_f(k.ol * 0.8)}" stroke-linecap="round"/>')
    return k


# ------------------------------------------------------------------ poses
# A pose: where the hips are, how each joint turns (degrees, clockwise; 0 hangs straight
# down), which hand, the face, the props, and its loop (the frames vary a few numbers).
STAND = {
    "hip": (0, -LEG_TO_GROUND), "torso": 0, "head": 0, "antenna": 32,
    "arm_l": (14, -10, 0, "fist"), "arm_r": (-14, 10, 0, "fist"),
    "leg_l": (6, -6, 1, 1.0), "leg_r": (-6, 6, 1, 1.0),       # thigh, shin, boot facing, thigh length
    "face": "neutral", "props": [], "z_arm_l": "back", "z_arm_r": "front",
}


def _pose(**kw):
    p = dict(STAND)
    p.update(kw)
    return p


SEAT_HIP = (0, -66)
_CHAIR = [("armchair_back", None, (0, -60, 0), "back"), ("armchair_front", None, (0, -60, 0), "legs")]
_SEAT = dict(hip=SEAT_HIP, leg_l=(4, -4, 1, 0.38), leg_r=(-6, 6, 1, 0.38), z_legs="over", z_arm_l="front",
             ik={"arm_l": ("world", -66, -104, 1), "arm_r": ("world", 66, -104, -1)},
             arm_l=(0, 0, 0, "open"), arm_r=(0, 0, 0, "open"))
POSES = {
    "stand": _pose(),
    "stand_back": _pose(view="back", arm_l=(10, -6, 0, "fist"), arm_r=(-10, 6, 0, "fist"),
                        z_arm_l="front", z_arm_r="front"),
    "stand_side": _pose(view="side", leg_l=(10, -8, 1, 1.0), leg_r=(-8, 4, 1, 1.0),
                        arm_l=(-6, 18, 0, "fist"), arm_r=(10, 12, 0, "fist")),
    # clicking the remote at the screen: his right arm out, the remote in his grip
    "remote": _pose(arm_r=(0, 0, 0, "grip"), arm_l=(18, -16, 0, "fist"), face="watching", antenna=28, head=-3,
                    ik={"arm_r": ("world", 104, -150, 1)},
                    props=[("remote", "hand_r", (0, 12, 180), "front")]),
    # slouched in the armchair, watching
    "armchair": _pose(**_SEAT, torso=-4, head=-4, face="watching", props=list(_CHAIR)),
    "popcorn": _pose(**{**_SEAT, "ik": {"arm_l": ("world", -66, -104, 1), "arm_r": ("world", 10, -96, -1)}},
                     torso=-2, head=-2, face="popcorn",
                     props=_CHAIR + [("popcorn", None, (8, -52, 0), "front")]),
    "laughing": _pose(**{**_SEAT, "ik": {"arm_l": ("world", -66, -104, 1), "arm_r": ("world", 30, -80, -1)}},
                      torso=-8, head=-12, face="laughing", props=list(_CHAIR)),
    "asleep": _pose(**{**_SEAT, "ik": {"arm_l": ("world", -40, -70, 1), "arm_r": ("world", 36, -66, -1)},
                       "leg_r": (-10, 10, 1, 0.38)}, torso=3, head=11, antenna=50, face="asleep",
                    props=_CHAIR + [("zzz", "head", (-40, -136, 0), "front")]),
    # presenting "coming up next" at a little broadcast desk, the tally lamp lit
    "host": _pose(hip=(0, -84), arm_r=(0, 0, -150, "open"), arm_l=(0, 0, -20, "grip"), face="onair",
                  lamp=True, antenna=26, z_arm_l="front",
                  ik={"arm_r": ("world", 112, -168, 1), "arm_l": ("world", -26, -76, -1)},
                  props=[("cards", "hand_l", (0, 4, 200), "front"), ("desk", None, (0, -66, 0), "desk")]),
    # fiddling with the antenna for better reception: head cocked, a hand on the rod
    "antenna": _pose(arm_r=(0, 0, 180, "grip"), z_arm_r="front", face="fiddle", antenna=30, head=6, torso=2,
                     arm_l=(16, -24, 0, "fist"), ik={"arm_r": ("world", 98, -196, -1)},
                     props=[("rabbit_ears", "hand_r", (0, 8, 0), "front")]),
    # the error state: he whacks the side of his own set
    "whack": _pose(arm_r=(0, 0, 200, "open"), z_arm_r="front", head=-12, torso=-5, antenna=44, face="whack",
                   arm_l=(20, -16, 0, "fist"), ik={"arm_r": ("head", 80, -58, -1)},
                   props=[("spark", "head", (84, -84, 0), "front")]),
    # the six approved faces, standing
    **{f"face_{n}": _pose(face=n) for n in APPROVED},
    # listening: two fingers to the earpiece (his signature)
    "listening": _pose(face="listening", arm_r=(0, 0, 170, "fist"), z_arm_r="front",
                       ik={"arm_r": ("head", 70, -46, -1)}),
    # snow: the channel changing (standing, the face all noise)
    "snow": _pose(face="snow"),
    "watching": _pose(face="watching"),
}
# each pose's frame, in rig units (x, y, w, h)
BOXES = {"remote": (-100, -340, 250, 360), "host": (-136, -332, 272, 340), "antenna": (-104, -350, 250, 370),
         "whack": (-100, -340, 230, 360), "listening": (-100, -340, 220, 360),
         **{p: (-104, -324, 208, 348) for p in ("armchair", "popcorn", "laughing", "asleep")}}

# Each loop: frames as small changes to the pose (and the frame number, which the faces and
# the screen's flicker band read). Short: three to six frames, at about 6 frames a second.
LOOPS = {
    "breathe": [{"breath": 0}, {"breath": -1.2}, {"breath": -2}, {"breath": -1.2}],
    "flicker": [{"flicker": 0}, {"flicker": 1}, {"flicker": 2}],
    "antenna": [{"antenna": -22, "ears": 0, "ik_arm_r": ("world", 110, -184, -1)},
                {"antenna": -32, "ears": 8, "ik_arm_r": ("world", 114, -180, -1)},
                {"antenna": -12, "ears": -6, "ik_arm_r": ("world", 106, -188, -1)},
                {"antenna": -26, "ears": 4, "ik_arm_r": ("world", 112, -182, -1)}],
    "wiggle": [{"antenna": 32}, {"antenna": 38}, {"antenna": 26}, {"antenna": 34}],
    "click": [{}, {"press": True}, {"press": True, "beam": True}, {"beam": True}],
    "snow": [{}, {}, {}, {}],
    "whack": [{"ik_arm_r": ("head", 104, -86, -1), "spark": False}, {"ik_arm_r": ("head", 80, -58, -1), "spark": True},
              {"ik_arm_r": ("head", 92, -70, -1), "spark": False}],
    "zzz": [{}, {}, {}, {}],
    "host": [{"ik_arm_r": ("world", 112, -168, 1)}, {"ik_arm_r": ("world", 116, -178, 1)},
             {"ik_arm_r": ("world", 114, -173, 1)}],
}
POSE_LOOP = {"stand": "breathe", "remote": "click", "armchair": "breathe", "popcorn": "breathe",
             "laughing": "breathe", "asleep": "zzz", "host": "host", "antenna": "antenna", "whack": "whack",
             "snow": "snow", "listening": "flicker", "watching": "flicker", **{f"face_{n}": "flicker" for n in APPROVED}}


def frames(pose):
    return len(LOOPS.get(POSE_LOOP.get(pose, "flicker"), [{}]))


# ------------------------------------------------------------------ composing
def _g(transform, body):
    return f'<g transform="{transform}">{body}</g>' if transform else body


def _tr(x=0, y=0, rot=0, sx=1, sy=1):
    t = []
    if x or y:
        t.append(f"translate({_f(x)} {_f(y)})")
    if rot:
        t.append(f"rotate({_f(rot)})")
    if sx != 1 or sy != 1:
        t.append(f"scale({_f(sx)} {_f(sy)})")
    return " ".join(t)


def _rot(pt, deg):
    a = math.radians(deg)
    x, y = pt
    return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


ARM = (34, 40)            # shoulder to elbow; elbow to the middle of the hand


def resolve(pose, frame=0):
    """A pose at a frame: its loop step applied, and every arm with an IK target turned into
    joint angles (the hand reaches the point: in the world, on the head, or on the antenna)."""
    p = dict(POSES[pose])
    loop = LOOPS.get(POSE_LOOP.get(pose, "flicker"), [{}])
    step = loop[frame % len(loop)]
    p["ik"] = dict(p.get("ik") or {})
    for k, v in step.items():
        if k.startswith("ik_"):
            p["ik"][k[3:]] = v
        elif k in p or k == "antenna":
            p[k] = v
    p["_step"] = step
    hip, torso, breath = p["hip"], p["torso"], step.get("breath", 0)

    def torso_to_world(pt):
        return _add(hip, _rot(_add(pt, (0, breath)), torso))

    def head_to_world(pt):
        return torso_to_world(_add(JOINTS["torso"]["neck"], _rot(pt, p["head"])))

    for side, (space, x, y, bend) in p["ik"].items():
        if space == "world":
            target = (x, y)
        elif space == "head":
            target = head_to_world((x, y))
        else:                                     # a point up the antenna's rod
            target = head_to_world(_add(JOINTS["head"]["antenna"], _rot((x, y), p["antenna"])))
        # into the torso's frame
        t = _rot((target[0] - hip[0], target[1] - hip[1]), -torso)
        t = (t[0], t[1] - breath)
        s = JOINTS["torso"]["shoulder_" + side[-1]]
        dx, dy = t[0] - s[0], t[1] - s[1]
        l1, l2 = ARM
        d = max(1e-3, min(math.hypot(dx, dy), l1 + l2 - 0.5))
        base = math.atan2(dy, dx)
        off = math.acos(max(-1, min(1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
        phi1 = base + bend * off
        e = (s[0] + l1 * math.cos(phi1), s[1] + l1 * math.sin(phi1))
        phi2 = math.atan2(t[1] - e[1], t[0] - e[0])
        up = math.degrees(phi1) - 90
        fore = math.degrees(phi2) - 90 - up
        _u, _f2, hand_rot, hand = p[side]
        p[side] = (up, fore, hand_rot, hand)
    return p


def figure(pose="stand", face=None, frame=0, R=None, ol=3.0, lod=2, hc=False):
    """The figure's SVG body (no document), in rig units."""
    p = resolve(pose, frame)
    step = p["_step"]
    view = p.get("view", "front")
    face = face or p["face"]
    R = R or roles()

    def ink():
        return Ink(R, ol, lod)

    def arm(side):
        up, fore, hand_rot, hand = p["arm_" + side]
        sh = JOINTS["torso"]["shoulder_" + side]
        if view == "side":
            sh = (4 if side == "r" else -6, sh[1])
        front_detail = view == "front" or (view == "side" and side == "r")
        hand_body = part_hand(ink(), hand).svg()
        for name, attach, (px_, py_, pr), _z in p["props"]:
            if attach == "hand_" + side and name == "remote":
                hand_body = _g(_tr(px_, py_, pr), prop_remote(ink(), pressed=step.get("press"),
                                                               beam=step.get("beam")).svg()) + hand_body
            elif attach == "hand_" + side and name == "rabbit_ears":
                upright = -(p["torso"] + up + fore + hand_rot) + step.get("ears", 0) * 0.6
                hand_body = hand_body + _g(_tr(px_, py_, upright), prop_rabbit_ears(ink(), step.get("ears", 0)).svg())
            elif attach == "hand_" + side and name == "cards":
                hand_body = _g(_tr(px_, py_, pr), prop_cards(ink()).svg()) + hand_body
        wrist = _g(_tr(*JOINTS["forearm"]["wrist"], hand_rot), hand_body)
        fore_g = _g(_tr(*JOINTS["upperarm"]["elbow"], fore),
                    part_forearm(ink(), cuff=(side == "r" and front_detail)).svg() + wrist)
        return _g(_tr(*sh, up), part_upperarm(ink(), patch=(side == "r" and front_detail)).svg() + fore_g)

    def leg(side):
        thigh, shin, facing, length = p["leg_" + side]
        hip = JOINTS["hip"]["hip_" + side]
        if view == "side":
            hip = (-4 if side == "l" else 4, hip[1])
        boot = _g(_tr(*JOINTS["shin"]["ankle"], -shin - thigh,
                      sx=(1 if side == "r" or view == "side" else -1) * facing),
                  part_boot(ink()).svg())
        shin_g = _g(_tr(0, 36 * length, shin), part_shin(ink()).svg() + boot)
        thigh_g = _g(_tr(0, 0, 0, 1, length), part_thigh(ink(), pocket=(side == "l")).svg())
        return _g(_tr(*hip, thigh), thigh_g + shin_g)

    breath = step.get("breath", 0)
    ant = p["antenna"]
    head_parts = (part_head(ink(), view, lamp=p.get("lamp")).svg()
                  + (part_screen(ink(), face, frame, R, hc, lod).svg() if view == "front" else "")
                  + _g(_tr(*JOINTS["head"]["antenna"], ant if view != "back" else -ant), part_antenna(ink()).svg()))
    if view == "front":
        head_parts += _g(_tr(*JOINTS["head"]["cable"]), part_cable(ink(), lod).svg())
    for name, attach, (px_, py_, pr), _z in p["props"]:
        if attach == "head" and name == "zzz":
            head_parts += _g(_tr(px_, py_, -p["head"]), prop_zzz(ink(), frame).svg())
        if attach == "head" and name == "spark" and step.get("spark", True):
            head_parts += _g(_tr(px_, py_, pr), prop_spark(ink()).svg())
    head = _g(_tr(*JOINTS["torso"]["neck"], p["head"]), head_parts)

    back_arms = "".join(arm(s) for s in ("l", "r") if p.get("z_arm_" + s) == "back")
    front_arms = "".join(arm(s) for s in ("l", "r") if p.get("z_arm_" + s) != "back")
    torso = _g(_tr(0, breath, p["torso"]), back_arms + part_torso(ink(), view).svg() + head + front_arms)
    legs = leg("l") + leg("r")

    def props(z):
        out = ""
        for name, attach, (px_, py_, pr), zz in p["props"]:
            if attach or zz != z:
                continue
            body = {"armchair_back": prop_armchair_back, "armchair_front": prop_armchair_front,
                    "desk": prop_desk, "popcorn": prop_popcorn}[name](ink()).svg()
            out += _g(_tr(px_, py_, pr), body)
        return out

    hx, hy = p["hip"]
    upper = _g(_tr(hx, hy), _g(_tr(0, breath, p["torso"]), back_arms + part_torso(ink(), view).svg() + head))
    arms_over = _g(_tr(hx, hy), _g(_tr(0, breath, p["torso"]), front_arms))
    if p.get("z_legs") == "over":
        # sitting, facing us: the chair's back, him, the chair's arms over his hips, then his
        # thighs (coming towards us) and his arms on top
        return props("back") + upper + props("legs") + _g(_tr(hx, hy), legs) + arms_over + props("front")
    if any(z == "desk" for *_x, z in p["props"]):
        # behind the desk: his legs are hidden; the hand with the cards rests over the desk top
        return props("back") + upper + props("desk") + arms_over + props("front")
    return props("back") + _g(_tr(hx, hy), legs + torso) + props("front")


GLOW = {"ember": None, "glow": (2.2, 0.55), "flare": (4.5, 0.85)}


def svg(pose="stand", face=None, frame=0, pal=None, level="glow", hc=False, size=None, crop=None,
        mirror=False, background=None, line_px=None):
    """A whole SVG document of STATIC. size: the pixel height it's meant for (it picks the
    line weight and how much detail shows); crop: "head" for the monitor alone, or a
    (x, y, w, h) box in rig units. mirror: facing the other way. line_px: the outline's width in
    pixels (for pixel art at terminal sizes)."""
    R = roles(pal, hc)
    box = BOXES.get(pose, BOX) if crop is None else ((-70, -188, 172, 192) if crop == "head" else crop)
    px_per_unit = (size / box[3]) if size else 1.0
    ol = max(3.0, 1.15 / px_per_unit) if size else 3.0
    if size and line_px:                          # pixel art: lines exactly this many pixels wide
        ol = line_px / px_per_unit
    lod = 2 if not size or size >= 160 else (1 if size >= 72 else 0)
    if crop == "head" and size:
        lod = 2 if size >= 96 else (1 if size >= 40 else 0)
    body = figure(pose, face, frame, R, ol, lod, hc)
    if crop == "head":
        p = POSES[pose]
        neck = JOINTS["torso"]["neck"]
        hip = p["hip"]
        # the head alone: drawn upright, the antenna in, centred in the box
        fr = LOOPS.get(POSE_LOOP.get(pose, "flicker"), [{}])
        step = fr[frame % len(fr)]
        ant = step.get("antenna", p["antenna"])
        k = Ink(R, ol, lod)
        hp = (part_head(k, lamp=p.get("lamp")).svg() + part_screen(Ink(R, ol, lod), face or p["face"], frame, R, hc, lod).svg()
              + _g(_tr(*JOINTS["head"]["antenna"], ant), part_antenna(Ink(R, ol, lod)).svg()))
        body = hp
        del neck, hip
    if mirror:
        cx = box[0] + box[2] / 2
        body = _g(f"translate({_f(2 * cx)} 0) scale(-1 1)", body)
    g = GLOW.get(level) if not hc else None
    defs = ""
    if g:
        std, op = g
        defs = (f'<defs><filter id="glow" x="-20%" y="-20%" width="140%" height="140%">'
                f'<feGaussianBlur in="SourceAlpha" stdDeviation="{_f(std)}" result="b"/>'
                f'<feFlood flood-color="{R["glow"]}" flood-opacity="{_f(op)}"/>'
                f'<feComposite in2="b" operator="in" result="g"/>'
                f'<feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>')
        body = f'<g filter="url(#glow)">{body}</g>'
    if level == "flare" and not hc and crop is None:
        emitter = (f'<ellipse cx="0" cy="4" rx="96" ry="12" fill="{R["px"]}" fill-opacity="0.12"/>'
                   f'<ellipse cx="0" cy="4" rx="70" ry="7" fill="none" stroke="{R["px"]}" stroke-opacity="0.5" '
                   f'stroke-width="2"/>')
        body = emitter + body
    bg = f'<rect x="{_f(box[0])}" y="{_f(box[1])}" width="{_f(box[2])}" height="{_f(box[3])}" fill="{background}"/>' \
        if background else ""
    w = round(box[2] * px_per_unit) if size else box[2]
    h = round(box[3] * px_per_unit) if size else box[3]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_f(box[0])} {_f(box[1])} {_f(box[2])} {_f(box[3])}" '
            f'width="{w}" height="{h}">{defs}{bg}{body}</svg>')


# ------------------------------------------------------------------ the rig, for other tools
def parts(pal=None, hc=False):
    """Every part on its own, in its local coordinates with the pivot at (0, 0): {name:
    {"svg": body, "pivot": [0, 0], "joints": {child: [x, y]}}}. Lottie and Flutter rigs
    hang them together with the same JOINTS and the poses' angles."""
    R = roles(pal, hc)

    def k():
        return Ink(R, 3.0, 2)
    out = {
        "head": (part_head(k()).svg(), JOINTS["head"]),
        "head_back": (part_head(k(), "back").svg(), {}),
        "head_side": (part_head(k(), "side").svg(), {}),
        "screen": (part_screen(k(), "neutral", 0, R, hc).svg(), {}),
        "screen_blank": (part_screen(k(), "snow", 0, R, hc).svg().split("<path", 2)[0] +
                         f'<path d="{rrect(-48, -90, 44, -16, 9)}" fill="{R["screen"]}" stroke="{R["line"]}" stroke-width="2.1"/>', {}),
        "antenna": (part_antenna(k()).svg(), {}),
        "cable": (part_cable(k()).svg(), {}),
        "torso": (part_torso(k()).svg(), {**JOINTS["torso"], **JOINTS["hip"]}),
        "torso_back": (part_torso(k(), "back").svg(), {}),
        "upperarm": (part_upperarm(k()).svg(), JOINTS["upperarm"]),
        "upperarm_patch": (part_upperarm(k(), True).svg(), JOINTS["upperarm"]),
        "forearm": (part_forearm(k()).svg(), JOINTS["forearm"]),
        "forearm_cuff": (part_forearm(k(), True).svg(), JOINTS["forearm"]),
        "hand_open": (part_hand(k(), "open").svg(), {}),
        "hand_fist": (part_hand(k(), "fist").svg(), {}),
        "thigh": (part_thigh(k()).svg(), JOINTS["thigh"]),
        "thigh_pocket": (part_thigh(k(), True).svg(), JOINTS["thigh"]),
        "shin": (part_shin(k()).svg(), JOINTS["shin"]),
        "boot": (part_boot(k()).svg(), {}),
        "remote": (prop_remote(k()).svg(), {}),
        "remote_click": (prop_remote(k(), True, True).svg(), {}),
        "armchair_back": (prop_armchair_back(k()).svg(), {}),
        "armchair_front": (prop_armchair_front(k()).svg(), {}),
        "desk": (prop_desk(k()).svg(), {}),
        "cards": (prop_cards(k()).svg(), {}),
        "popcorn": (prop_popcorn(k()).svg(), {}),
        "zzz": (prop_zzz(k()).svg(), {}),
        "spark": (prop_spark(k()).svg(), {}),
    }
    return {n: {"svg": s, "pivot": [0, 0], "joints": {c: list(v) for c, v in j.items()}} for n, (s, j) in out.items()}


# ------------------------------------------------------------------ on, quiet or off
def mode(env=None):
    """on, quiet or off (MASCOT.md, "Mute the mascot"): BROMIGOS_MASCOT decides outright, else
    `mode` in ~/.config/bromigos/mascot.toml. quiet keeps his sprite and its faces (no thought
    bubbles); off draws nothing of him anywhere."""
    import os
    env = os.environ if env is None else env
    v = (env.get("BROMIGOS_MASCOT") or "").strip().lower()
    if v in ("on", "quiet", "off"):
        return v
    path = os.path.join(env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or "~", ".config"),
                        "bromigos", "mascot.toml")
    try:
        import tomllib
        with open(os.path.expanduser(path), "rb") as f:
            v = str(tomllib.load(f).get("mode", "on")).lower()
        return v if v in ("on", "quiet", "off") else "on"
    except (OSError, ValueError):
        return "on"


def mode_path(env=None):
    import os
    env = os.environ if env is None else env
    return os.path.join(env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"),
                                                                     ".config"), "bromigos", "mascot.toml")


def set_mode(value, env=None):
    """Writes ~/.config/bromigos/mascot.toml's mode (on, quiet or off), atomically; returns
    the mode before."""
    import os
    if value not in ("on", "quiet", "off"):
        raise ValueError("the mascot is on, quiet or off")
    before = mode(dict(env or os.environ, BROMIGOS_MASCOT=""))
    path = mode_path(env)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("# STATIC, the mascot: on, quiet (no thought bubbles) or off (nowhere). "
                "Settings › Mascot, or bromigos mascot on|quiet|off\n" f'mode = "{value}"\n')
    os.replace(tmp, path)
    return before
