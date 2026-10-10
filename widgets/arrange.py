"""Arranging the panels: the geometry and the file behind edit mode (editmode.py), with no
GTK, so it's tested on its own (widgets/tests/test_arrange.py).

  * snap_move() and snap_resize(): a dragged panel snaps to the other panels' edges (and
    16 px gaps beside them, and the usable area's edges) within 8 px, else to an 8 px
    grid. They return the guides to draw: the lines it snapped to.
  * free_spot(): the first place a panel fits, clear of the others by 16 px; place(): the
    spot a panel being switched on gets (strict: None when there's no room, never stacked).
  * History: undo and redo inside one edit session.
  * Monitors: each panel's own monitor, found by its make, model and serial (else its
    connector's name) with find_output(); where a panel shows while its monitor isn't
    connected (fallback_spot) and what layout.json keeps for it then (kept_place).
  * read() and write(): layout.json. write() replaces the file in one step and, when
    ~/.config/bromigos/widgets/layout.json is a symlink (into a dotfiles repository, say),
    writes through it, so the link stays a link. migrate() brings a layout from before
    each panel had its own monitor up to date.

A state is {name: {"x", "y", "width", "height", "visible"}}, and "output" when the panel
has a monitor of its own: where each panel is. Positions are px from the top left of the
usable area (under the bar) of the panel's monitor, as in layout.json.
"""
import copy
import json
import os
import time

HERE = os.path.dirname(os.path.realpath(__file__))
GRID = 8            # px: the grid a dragged panel snaps to
SNAP = 8            # px: how close an edge must be to snap to another
GAP = 16            # px: the gap between panels that snapping offers, and free_spot keeps
MARGIN = (28, 16)   # the default layout's left and top margins: where free_spot starts
KEYS = ("x", "y", "width", "height", "visible")
VERSION = 2         # layout.json's: 2 gives each panel its own "output"
ID_KEYS = ("make", "model", "serial")


# ------------------------------------------------------------------ snapping
def _lines(others, area, gap=GAP):
    """The lines an edge can snap to: (x lines, y lines), each (pos, (lo, hi), what)
    where (lo, hi) is the extent along the other axis, for drawing the guide."""
    W, H = area
    xs = [(0, (0, H), "area"), (W, (0, H), "area")]
    ys = [(0, (0, W), "area"), (H, (0, W), "area")]
    for ox, oy, ow, oh in others:
        span_y, span_x = (oy, oy + oh), (ox, ox + ow)
        xs += [(ox, span_y, "edge"), (ox + ow, span_y, "edge"), (ox - gap, span_y, "gap"),
               (ox + ow + gap, span_y, "gap"), (ox + ow / 2, span_y, "centre")]
        ys += [(oy, span_x, "edge"), (oy + oh, span_x, "edge"), (oy - gap, span_x, "gap"),
               (oy + oh + gap, span_x, "gap"), (oy + oh / 2, span_x, "centre")]
    return xs, ys


def _best(edges, lines, tol):
    """The smallest move (within tol) that puts one of `edges` (offset, pos) on a line:
    (delta, line pos, its span) or None. Centre lines only take a centre edge."""
    best = None
    for kind, pos in edges:
        for lp, span, what in lines:
            if (what == "centre") != (kind == "centre"):
                continue
            d = lp - pos
            if abs(d) <= tol and (best is None or abs(d) < abs(best[0])):
                best = (d, lp, span)
    return best


def _grid(v, grid=GRID):
    return int(round(v / grid) * grid)


def _guide(axis, pos, span, own):
    lo, hi = min(span[0], own[0]), max(span[1], own[1])
    return (axis, pos, lo, hi)


def snap_move(rect, others, area, snap=True, tol=SNAP, grid=GRID):
    """Where a panel dragged to rect = (x, y, w, h) lands: (x, y, guides). With snap off
    (Ctrl held), only kept inside the area. guides: [("v"|"h", pos, lo, hi)]."""
    x, y, w, h = rect
    W, H = area
    guides = []
    if snap:
        xs, ys = _lines(others, area)
        bx = _best((("edge", x), ("edge", x + w), ("centre", x + w / 2)), xs, tol)
        by = _best((("edge", y), ("edge", y + h), ("centre", y + h / 2)), ys, tol)
        if bx:
            x += bx[0]
        else:
            x = _grid(x, grid)
        if by:
            y += by[0]
        else:
            y = _grid(y, grid)
        x, y = int(round(x)), int(round(y))
        if bx:
            guides.append(_guide("v", bx[1], bx[2], (y, y + h)))
        if by:
            guides.append(_guide("h", by[1], by[2], (x, x + w)))
    x = max(0, min(int(round(x)), max(0, W - w)))
    y = max(0, min(int(round(y)), max(0, H - h)))
    return x, y, guides


def clamp_size(w, h, limits):
    (lw, lh), (hw, hh) = limits
    return max(lw, min(hw, int(w))), max(lh, min(hh, int(h)))


def snap_resize(rect, corner, px, py, others, area, limits, snap=True, tol=SNAP, grid=GRID):
    """A panel resized by dragging `corner` ("nw", "ne", "sw" or "se") to (px, py): its
    new (x, y, w, h) and the guides. The opposite corner stays put; the size stays within
    limits ((min w, min h), (max w, max h)) and the panel inside the area."""
    x, y, w, h = rect
    W, H = area
    left, top, right, bottom = x, y, x + w, y + h
    guides = []
    xs, ys = _lines(others, area) if snap else ([], [])

    def edge(v, lines, axis, own):
        if not snap:
            return int(round(v))
        b = _best((("edge", v),), lines, tol)
        if b:
            guides.append(_guide(axis, b[1], b[2], own))
            return int(round(b[1]))
        return _grid(v, grid)
    if "w" in corner:
        left = edge(max(0, px), xs, "v", (top, bottom))
    else:
        right = edge(min(W, px), xs, "v", (top, bottom))
    if "n" in corner:
        top = edge(max(0, py), ys, "h", (left, right))
    else:
        bottom = edge(min(H, py), ys, "h", (left, right))
    nw, nh = clamp_size(right - left, bottom - top, limits)
    # the dragged edges give way to the limits and the area; the fixed ones stay
    if "w" in corner:
        left = max(0, right - nw)
        nw = right - left
    else:
        nw = min(nw, W - left) if W > left else nw
    if "n" in corner:
        top = max(0, bottom - nh)
        nh = bottom - top
    else:
        nh = min(nh, H - top) if H > top else nh
    nw, nh = clamp_size(nw, nh, ((1, 1), limits[1]))
    return (left, top, nw, nh), guides


def fit_class(classes, w, h):
    """(w, h) moved into the nearest size class: classes are [(name, min, max, ...)].
    Inside a class it stays as it is; between two it goes to the closer one's edge.
    Returns (w, h, the class's name)."""
    best = None
    for c in classes:
        name, lo, hi = c[0], c[1], c[2]
        cw, ch = max(lo[0], min(hi[0], w)), max(lo[1], min(hi[1], h))
        d = (cw - w) ** 2 + (ch - h) ** 2
        if best is None or d < best[0]:
            best = (d, int(cw), int(ch), name)
    return (best[1], best[2], best[3]) if best else (int(w), int(h), None)


def resize_in_classes(rect, corner, classes, area):
    """A resized rect (from snap_resize) fitted into its nearest size class, the corner
    opposite `corner` kept where it is and the panel kept inside the area."""
    x, y, w, h = rect
    W, H = area
    nw, nh, name = fit_class(classes, w, h)
    if "w" in corner:
        x = max(0, x + w - nw)
    if "n" in corner:
        y = max(0, y + h - nh)
    x, y = min(x, max(0, W - nw)), min(y, max(0, H - nh))
    return (x, y, nw, nh), name


# ------------------------------------------------------------------ free space
def overlaps(a, b, gap=0):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw + gap <= bx or bx + bw + gap <= ax or ay + ah + gap <= by or by + bh + gap <= ay)


def free_spot(w, h, taken, area, avoid=(), gap=GAP, grid=GRID, start=MARGIN):
    """The first free top left for a w x h panel inside area (W, H), clear of the taken
    and avoided rects by `gap`: down each column, the columns beside the panels first
    (so a new panel lines up with them), then every grid step from the left. None when
    nothing fits."""
    W, H = area
    rects = list(taken) + list(avoid)

    def clear(x, y):
        return all(not overlaps((x, y, w, h), r, gap) for r in rects)
    cols = sorted({start[0]} | {rx + rw + gap for rx, ry, rw, rh in taken})
    cols += [c for c in range(start[0], max(start[0] + 1, W - w), grid * 4) if c not in cols]
    for x in cols:
        if x + w > W - gap:
            continue
        for y in range(start[1], max(start[1] + 1, H - h - gap + 1), grid):
            if clear(x, y):
                return x, y
    return None


def place(w, h, taken, area, avoid=(), soft=(), strict=False):
    """Where a panel being added goes: a free spot clear of the panels and of `avoid`
    (VECTOR's corner, the notifications, the scene's focal points); else one clear of the
    panels only, still keeping off `soft` (edit mode's tray); else one clear of the panels.
    taken: the panels shown on that monitor, and nothing else (a hidden one takes no room).
    When nothing is clear of them: None with strict (say "no room", never stack), else the
    top left, inside the area (a panel that must show somewhere: its monitor went away)."""
    spot = free_spot(w, h, taken, area, avoid) or free_spot(w, h, taken, area, soft) or free_spot(w, h, taken, area)
    if spot or strict:
        return spot
    W, H = area
    return min(MARGIN[0], max(0, W - w)), min(MARGIN[1], max(0, H - h))


def no_room(title):
    """What to say when a panel has no room anywhere."""
    return f"No room for {title}: hide something or try a smaller size"


def fits(rect, taken, area, gap=0):
    """Whether rect is inside the area and clear of every taken rect."""
    x, y, w, h = rect
    W, H = area
    return x >= 0 and y >= 0 and x + w <= W and y + h <= H and not any(overlaps(rect, t, gap) for t in taken)


# ------------------------------------------------------------------ monitors
def _live(monitors):
    return [m for m in monitors or [] if isinstance(m, dict) and m.get("name") and not m.get("disabled")]


def identity(m):
    """A monitor as layout.json remembers it: its make, model and serial, which stay the
    same on any port, and its connector's name ("DP-1"), the fallback."""
    return {**{k: str(m.get(k) or "") for k in ID_KEYS}, "name": str(m.get("name") or "")}


def find_output(monitors, want):
    """The connector of the monitor `want` names, or None when it isn't connected. want is
    a panel's "output" ({"make", "model", "serial", "name"}) or a connector's name. The
    make, model and serial come first, so a monitor plugged into another port is still
    found; of several alike (no serial), the one on the same connector, else the first.
    Then the connector's name alone."""
    mons = _live(monitors)
    if isinstance(want, str):
        want = {"name": want}
    if not isinstance(want, dict) or not mons:
        return None
    key = tuple(str(want.get(k) or "") for k in ID_KEYS)
    name = str(want.get("name") or "")
    if any(key):
        same = [m for m in mons if tuple(str(m.get(k) or "") for k in ID_KEYS) == key]
        if same:
            return next((m["name"] for m in same if m["name"] == name),
                        min(same, key=lambda m: m.get("id", 0))["name"])
    return name if name and any(m["name"] == name for m in mons) else None


def bounds(m):
    """A monitor's whole rect in the desktop's layout, in logical px: (x, y, w, h)."""
    scale = float(m.get("scale") or 1) or 1
    w, h = (m.get("width") or 0) / scale, (m.get("height") or 0) / scale
    if (m.get("transform") or 0) % 2:
        w, h = h, w
    return int(m.get("x") or 0), int(m.get("y") or 0), int(w), int(h)


def usable(m):
    """A monitor's usable area (under the bar), where the panels' x and y start: (x, y) in
    the desktop's layout and its (w, h), in logical px."""
    x, y, w, h = bounds(m)
    rl, rt, rr, rb = (list(m.get("reserved") or []) + [0, 0, 0, 0])[:4]
    return int(x + rl), int(y + rt), int(w - rl - rr), int(h - rt - rb)


def monitor_at(monitors, gx, gy):
    """The connector of the monitor under (gx, gy) in the desktop's layout, or None."""
    for m in _live(monitors):
        x, y, w, h = bounds(m)
        if x <= gx < x + w and y <= gy < y + h:
            return m["name"]
    return None


def fallback_spot(rect, taken, area, avoid=()):
    """Where a panel shows on the primary monitor while its own isn't connected: its own
    place when that's inside the area and clear of the panels there, else a free spot."""
    x, y, w, h = rect
    if fits((x, y, w, h), taken, area):
        return x, y
    return place(w, h, taken, area, avoid)


def kept_place(now, pin, fell=None, home=None, monitors=()):
    """What layout.json keeps for a panel: (output, x, y). now = (connector, x, y), where
    it shows; pin = its own monitor (its "output"), or None for one that goes on the
    primary. fell = (connector, x, y) where it was shown on the primary because its own
    monitor wasn't connected, and home its saved (x, y) then: untouched there, it keeps
    its own monitor and place. Otherwise it keeps where it is, its monitor by make, model
    and serial."""
    if fell and home and tuple(now) == tuple(fell):
        return pin, int(home[0]), int(home[1])
    conn, x, y = now
    if pin is None and not fell:
        return None, int(x), int(y)
    m = next((m for m in _live(monitors) if m["name"] == conn), None)
    return (identity(m) if m else {"name": conn}), int(x), int(y)


# ------------------------------------------------------------------ undo
class History:
    """Undo and redo for one edit session: push(before) ahead of each change. Changes
    with the same `key` within `merge` seconds (a run of arrow-key nudges) undo as one."""

    def __init__(self, merge=1.0, clock=time.monotonic):
        self.undos, self.redos = [], []
        self.merge, self.clock = merge, clock
        self._last = (None, 0.0)

    def push(self, before, key=None):
        now = self.clock()
        if key is not None and self._last[0] == key and now - self._last[1] <= self.merge and self.undos:
            self._last = (key, now)
            return False
        self.undos.append(copy.deepcopy(before))
        self.redos.clear()
        self._last = (key, now)
        return True

    def undo(self, current):
        """The state to go back to (None: nothing to undo); `current` goes on the redo stack."""
        if not self.undos:
            return None
        self.redos.append(copy.deepcopy(current))
        self._last = (None, 0.0)
        return self.undos.pop()

    def redo(self, current):
        if not self.redos:
            return None
        self.undos.append(copy.deepcopy(current))
        self._last = (None, 0.0)
        return self.redos.pop()

    def can_undo(self):
        return bool(self.undos)

    def can_redo(self):
        return bool(self.redos)


# ------------------------------------------------------------------ layout.json
def _config():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def user_path():
    return os.path.join(_config(), "bromigos", "widgets", "layout.json")


def default_path():
    p = os.path.join(os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos", "widgets", "layout.json")
    return p if os.path.isfile(p) else os.path.join(HERE, "layout.json")


def read():
    """(layout, its path, whether it's the user's). The user's file, else bromigOS's.
    Raises ValueError when the file there isn't a layout."""
    for path, mine in ((user_path(), True), (default_path(), False)):
        if os.path.isfile(path):
            with open(path) as f:
                d = json.load(f)
            if not isinstance(d, dict) or not isinstance(d.get("panels"), list):
                raise ValueError(f"{path}: no \"panels\" list")
            return d, path, mine
    return {"monitor": "", "panels": []}, None, False


def read_default():
    with open(default_path()) as f:
        return json.load(f)


def write(doc, path=None):
    """layout.json in one step (a reader never sees half of it). A symlink stays a
    symlink: its target is replaced, keeping its mode. Returns the file written."""
    path = path or user_path()
    target = os.path.realpath(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".bromigos.tmp"
    with open(tmp, "w") as f:
        f.write(json.dumps(doc, indent=2) + "\n")
    try:
        os.chmod(tmp, os.stat(target).st_mode & 0o7777)
    except FileNotFoundError:
        pass
    os.replace(tmp, target)
    return target


def migrate(doc, monitors=()):
    """A layout from before each panel had its own monitor (version 1: one "monitor" for
    them all) as version 2: each panel without an "output" gets that monitor, by its make,
    model and serial when it's connected (else by its connector's name), so the panels
    stay where they were and follow that monitor to another port. "monitor" stays: where
    the panels without a monitor of their own go. Returns (layout, whether any panel got
    one); a layout that's version 2 already comes back as it is."""
    if not isinstance(doc, dict) or not isinstance(doc.get("version", 1), int) or doc.get("version", 1) >= VERSION:
        return doc, False
    d = copy.deepcopy(doc)
    d["version"] = VERSION
    name = str(d.get("monitor") or "")
    if not name:
        return d, False
    m = next((m for m in _live(monitors) if m["name"] == name), None)
    out = identity(m) if m else {"name": name}
    entries = [p for p in d.get("panels") or [] if isinstance(p, dict) and p.get("name")]
    entries += [p for p in (d.get("plugins") or {}).values() if isinstance(p, dict)] \
        if isinstance(d.get("plugins"), dict) else []
    got = False
    for p in entries:
        if not p.get("output"):
            p["output"] = dict(out)
            got = True
    return d, got


def state_of(doc):
    """{name: {x, y, width, height, visible, output}} as layout.json places them (its
    "plugins" map over its "panels" entries); a key the layout doesn't give is left out."""
    out = {}
    for p in doc.get("panels") or []:
        if isinstance(p, dict) and p.get("name"):
            out[p["name"]] = {k: p[k] for k in KEYS + ("output",) if k in p}
    for name, p in (doc.get("plugins") or {}).items():
        if isinstance(p, dict):
            out.setdefault(name, {}).update({k: p[k] for k in KEYS + ("output",) if k in p})
    for s in out.values():
        s.setdefault("visible", True)
    return out


def apply(doc, state, monitor=None):
    """A copy of the layout with `state` written in: each panel's place, size, visibility
    and monitor where layout.json keeps it (its "plugins" entry when it has one, else its
    "panels" entry, else a new "panels" entry). An "output" of None takes the panel's own
    monitor away (it goes on the primary). Every other key stays as it was."""
    d = copy.deepcopy(doc)
    d["version"] = VERSION
    panels = d.setdefault("panels", [])
    plugins = d.get("plugins") if isinstance(d.get("plugins"), dict) else {}
    for name, s in state.items():
        vals = {k: (bool(s[k]) if k == "visible" else int(s[k])) for k in KEYS if k in s}
        if name in plugins and isinstance(plugins[name], dict):
            entry = plugins[name]
        else:
            entry = next((p for p in panels if isinstance(p, dict) and p.get("name") == name), None)
            if entry is None:
                entry = {"name": name}
                panels.append(entry)
        entry.update(vals)
        if "output" in s:
            if s["output"]:
                entry["output"] = dict(s["output"]) if isinstance(s["output"], dict) else {"name": str(s["output"])}
            else:
                entry.pop("output", None)
    if monitor is not None:
        d["monitor"] = monitor
    return d


def changed(before, after):
    """The panels whose place, size or visibility differ between two states."""
    return {n: s for n, s in after.items() if before.get(n) != s}
