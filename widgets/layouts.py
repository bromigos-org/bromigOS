"""Widget layouts: ready-made arrangements of the desktop's panels ("templates"), each
theme's own, and fitting one to any screen (docs/widgets.md, "Layouts"). No GTK, so it's
tested on its own (widgets/tests/test_layout_templates.py).

A layout is a TOML file: a title, a one-line description, an archetype and its widgets.
Each widget is placed by anchors, not pixels, so one file fits a 1366x768 laptop and a
3840x2160 screen alike:

    title = "Homelab"
    description = "Your servers at a glance"
    archetype = "homelab"
    budget = 0.33                 # at most this much of the screen covered (default a third)

    [[widget]]
    name = "lab"                  # or a list: the first that can show something here
    size = "large"                # its size class; `small` and `big` for small and big screens
    small = "standard"
    side = "left"                 # left or right: a column (lane 1 by the edge, 2 beside it…)
    lane = 1                      #   stacked in file order, from = "top" or "bottom"
    priority = 1                  # 1 matters most: the last to be shrunk or left out
    fit = "content"               # its height: what its content needs, within its size class
                                  #   (the default for a widget that fits its content);
                                  #   "fixed": its class's start height

    side = "top" | "bottom"       # a row along that edge, from = "left" or "right"
    at = [0.1, 0.2]               # a place as fractions of the area (a saved layout's)

A widget that fits its content (panels.Panel.fit, "content": LAB, ALERTS, CI…) gets the
height its content needs at that width, kept inside its size class: the catalog's
"natural" heights, which the running panels publish from their data (the health file) and
the picture tools measure from demo data. A widget whose content needs more than its class
allows gets the most it allows, and folds what it shows (it never cuts a section in half).

Bigger is never the answer: a widget that doesn't fit goes down a size class, then is left
out, lowest priority first, and the result says what was left out and why. The same
happens when the widgets would cover more than the budget: the scene behind them is the
point of the desktop. `pack = true` (Everything) puts every widget that can show something
in, as tidily as it can; it may cover more than the budget, and says so.

Where the layouts are:

    /usr/share/bromigos/widgets/layouts/<id>.toml     bromigOS's (widgets/layouts/ here)
    ~/.config/bromigos/widgets/layouts/<id>.toml      yours (`bromigos panels layout save`)
    <theme>/widgets/layout.toml                        a theme's own: its keep-clear areas
                                                       and the layout made for its scene

A theme's file also says where its scene's focal points are ([[clear]]: rects as fractions
of the 2560x1440 picture; soft = true: kept clear while there's room elsewhere). Layouts,
Tidy up and adding a widget keep off them. A theme without a file of its own draws the
Wick's den (the colour themes), so it takes the Wick's file and shares the Wick's
remembered layout; a world without one keeps the middle of the screen clear. Giving a
theme a file of its own makes it a scene of its own: no code changes.

The desktop remembers a layout per scene (~/.config/bromigos/widgets/scenes/<scene>.json:
each widget's place, size and whether it's on). Switching theme saves the one in force
for the old scene and puts back the new scene's, or fits its recommended layout the first
time (the theme-set hook runs `bromigos panels layout theme NAME`).
"""
import copy
import json
import os
import re
import time

try:
    import tomllib
except ImportError:                       # Python < 3.11
    tomllib = None

import arrange as A

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(HERE)
MARGIN = 24             # px from the area's edges
GAP = 16                # px between widgets (arrange.GAP)
STEP = 8                # px: the search steps (arrange.GRID)
BUDGET = 1 / 3          # the share of the screen a layout may cover
SMALL = (1600, 900)     # a usable area smaller than this takes each widget's `small` size
BIG = (3200, 1800)      # one at least this big takes its `big` size
PLATE = (2560.0, 1440.0)
SIDES = ("left", "right", "top", "bottom")
# a world without a layout of its own: its middle kept clear
CENTRE = [{"name": "the middle of the scene", "rect": [0.3, 0.22, 0.4, 0.56], "soft": False}]
# widgets' names as a sentence says them (their own titles are in capitals)
TITLES = {"github": "GitHub", "gitlab": "GitLab", "ci": "CI & PRs", "gpu": "GPU", "vector": "VECTOR",
          "youtube": "YouTube", "nowplaying": "Now playing", "labjobs": "Lab jobs", "games": "Game servers",
          "game_servers": "Game servers", "notes": "Field notes", "lab": "Lab"}
PROVIDERS = {"github": "GitHub", "gitlab": "GitLab", "spotify": "Spotify", "twitch": "Twitch"}
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")


# ------------------------------------------------------------------ where things are
def _config():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def _state():
    return os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")


def _share():
    return os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos"


def system_dirs():
    """bromigOS's layouts: the installed ones, else this checkout's."""
    out = [os.path.join(_share(), "widgets", "layouts")]
    out.append(os.path.join(HERE, "layouts"))
    return [d for d in dict.fromkeys(out) if os.path.isdir(d)]


def user_dir():
    return os.path.join(_config(), "bromigos", "widgets", "layouts")


def scenes_dir():
    return os.path.join(_config(), "bromigos", "widgets", "scenes")


def undo_path():
    return os.path.join(_state(), "bromigos", "widgets", "layout-undo.json")


def record_path():
    """Which scene layout.json was last arranged for, and the layout applied everywhere."""
    return os.path.join(_state(), "bromigos", "widgets", "layout-scene.json")


def theme_dirs(name):
    """A theme's directories: bromigOS's, an extension's, the user's, and this checkout's
    (bromigos-core's own search, theme.rs theme_dirs, plus the checkout for tests)."""
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    cands = [os.path.join(_share(), "themes", name),
             os.path.join(data, "bromigos", "ext", "active", "themes", name),
             os.path.join(_config(), "bromigos", "themes", name),
             os.path.join(REPO, "themes", name)]
    return [d for d in dict.fromkeys(cands) if os.path.isdir(d)]


def current_dir():
    return os.path.join(_state(), "bromigos", "theme", "current")


def current_theme():
    """The theme in force (`bromigos theme set` writes its palette.json), else the Wick."""
    try:
        with open(os.path.join(current_dir(), "palette.json")) as f:
            return str(json.load(f).get("theme") or "wick")
    except (OSError, ValueError, AttributeError):
        return "wick"


def _toml(path):
    if tomllib is None:
        raise ValueError("Python's tomllib is missing (Python 3.11 or newer)")
    with open(path, "rb") as f:
        return tomllib.load(f)


# ------------------------------------------------------------------ reading a layout
def parse(doc, ident, source="bromigos", path=None):
    """A layout file's contents as a template: {"id", "title", "description", "archetype",
    "budget", "pack", "widgets": [entry], "source", "path"}. Raises ValueError on a
    mistake, naming it."""
    if not isinstance(doc, dict):
        raise ValueError(f"{ident}: not a table")
    t = {"id": ident, "title": str(doc.get("title") or ident.replace("-", " ").title()),
         "description": str(doc.get("description") or ""), "archetype": str(doc.get("archetype") or ident),
         "budget": doc.get("budget"), "pack": bool(doc.get("pack")), "source": source, "path": path,
         "exclude": [str(x) for x in doc.get("exclude") or []], "widgets": []}
    if t["budget"] is not None and not (isinstance(t["budget"], (int, float)) and 0 < t["budget"] <= 1):
        raise ValueError(f"{ident}: budget is a share of the screen, above 0 and at most 1")
    for i, w in enumerate(doc.get("widget") or []):
        if not isinstance(w, dict):
            raise ValueError(f"{ident}: widget {i + 1} isn't a table")
        names = w.get("name")
        names = [names] if isinstance(names, str) else list(names or [])
        if not names or not all(isinstance(n, str) and n for n in names):
            raise ValueError(f"{ident}: widget {i + 1} has no name")
        e = {"names": names, "size": w.get("size"), "small": w.get("small"), "big": w.get("big"),
             "side": w.get("side"), "lane": int(w.get("lane", 1)), "from": w.get("from"),
             "at": w.get("at"), "priority": int(w.get("priority", 5)), "order": i,
             "width": w.get("width"), "height": w.get("height"), "fit": w.get("fit")}
        if e["fit"] not in (None, "content", "fixed"):
            raise ValueError(f"{ident}: {names[0]}: fit is \"content\" or \"fixed\"")
        if e["at"] is not None:
            if not (isinstance(e["at"], list) and len(e["at"]) == 2 and all(isinstance(v, (int, float)) for v in e["at"])):
                raise ValueError(f"{ident}: {names[0]}: at is [x, y], fractions of the area")
        elif e["side"] not in SIDES:
            raise ValueError(f"{ident}: {names[0]}: side is one of {', '.join(SIDES)} (or give at = [x, y])")
        if e["from"] is None:
            e["from"] = "top" if e["side"] in ("left", "right") else "left"
        if e["side"] in ("left", "right") and e["from"] not in ("top", "bottom"):
            raise ValueError(f"{ident}: {names[0]}: a column goes from the top or the bottom")
        if e["side"] in ("top", "bottom") and e["from"] not in ("left", "right"):
            raise ValueError(f"{ident}: {names[0]}: a row goes from the left or the right")
        if e["lane"] < 1:
            raise ValueError(f"{ident}: {names[0]}: lane counts from 1, by the edge")
        t["widgets"].append(e)
    if not t["widgets"] and not t["pack"]:
        raise ValueError(f"{ident}: no widgets")
    return t


def load(path, ident=None, source="bromigos"):
    ident = ident or os.path.splitext(os.path.basename(path))[0]
    try:
        doc = _toml(path)
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: {e}")
    return parse(doc, ident, source, path)


def templates(errors=None):
    """{id: template}: bromigOS's, then yours (one of yours with the same id wins)."""
    out = {}
    for d, src in [(d, "bromigos") for d in reversed(system_dirs())] + [(user_dir(), "yours")]:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".toml"):
                continue
            ident = f[:-5]
            if not ID.fullmatch(ident):
                continue
            try:
                out[ident] = load(os.path.join(d, f), ident, src)
            except ValueError as e:
                if errors is not None:
                    errors.append(str(e))
    order = {a: i for i, a in enumerate(("minimal", "developer", "homelab", "streamer", "media", "gamer", "everything"))}
    return dict(sorted(out.items(), key=lambda kv: (kv[1]["source"] == "yours", order.get(kv[0], 50), kv[0])))


# ------------------------------------------------------------------ scenes: a theme's keep-clear areas
def scene_info(theme=None, directory=None):
    """What a theme's scene needs of the widgets: {"scene" (the id its layout is remembered
    by), "theme", "clear" (keep-clear areas), "recommended" (a template or None), "focus"
    (the picture's point a non-16:9 screen centres on), "kind" (den, world), "file"}.
    `directory`: the theme's files (the current theme's: theme/current), else found by name."""
    theme = theme or current_theme()
    dirs = [directory] if directory else []
    if theme == current_theme() and not directory and os.path.isdir(current_dir()):
        dirs.append(current_dir())
    dirs += theme_dirs(theme)
    lay = next((os.path.join(d, "widgets", "layout.toml") for d in dirs
                if os.path.isfile(os.path.join(d, "widgets", "layout.toml"))), None)
    world = next((os.path.join(d, "live", "world.toml") for d in dirs
                  if os.path.isfile(os.path.join(d, "live", "world.toml"))), None)
    info = {"theme": theme, "scene": theme, "kind": "world" if world else "den", "clear": [], "recommended": None,
            "focus": None, "file": lay, "title": theme.title(), "errors": []}
    if world:
        try:
            focus = (_toml(world).get("view") or {}).get("focus")
            if isinstance(focus, list) and len(focus) == 2:
                info["focus"] = (float(focus[0]), float(focus[1]))
        except (OSError, ValueError):
            pass
    if lay is None and not world:
        # a colour theme: the Wick's den recoloured, so the Wick's file and the Wick's memory
        wick = next((os.path.join(d, "widgets", "layout.toml") for d in theme_dirs("wick")
                     if os.path.isfile(os.path.join(d, "widgets", "layout.toml"))), None)
        info.update(scene="wick", file=wick, title="Wick")
        lay = wick
    if lay is None:
        info["clear"] = copy.deepcopy(CENTRE)
        return info
    try:
        doc = _toml(lay)
    except (OSError, ValueError) as e:
        info["errors"].append(f"{lay}: {e}")
        info["clear"] = copy.deepcopy(CENTRE)
        return info
    info["scene"] = str(doc.get("scene") or info["scene"])
    info["title"] = str(doc.get("scene_title") or info["title"])
    for c in doc.get("clear") or []:
        r = c.get("rect") if isinstance(c, dict) else None
        if isinstance(r, list) and len(r) == 4 and all(isinstance(v, (int, float)) for v in r):
            info["clear"].append({"name": str(c.get("name") or "the scene"), "rect": [float(v) for v in r],
                                  "soft": bool(c.get("soft"))})
    if doc.get("widget"):
        try:
            t = parse(doc, f"theme-{info['scene']}", "theme", lay)
            t["title"] = str(doc.get("title") or f"Made for {info['title']}")
            t["made_for"] = info["title"]
            info["recommended"] = t
        except ValueError as e:
            info["errors"].append(str(e))
    return info


# ------------------------------------------------------------------ the screen
class Screen:
    """A monitor as the panels see it: the usable area (W, H) under the bar, where panel
    positions start, and the whole screen (SW, SH) with the area's offset in it (ox, oy),
    all in logical px. The scene covers the whole screen (live/live/cover.py)."""

    def __init__(self, W, H, SW=None, SH=None, ox=0, oy=0):
        self.W, self.H = int(W), int(H)
        self.SW, self.SH = int(SW or W), int(SH or H)
        self.ox, self.oy = int(ox), int(oy)

    @classmethod
    def of(cls, m):
        """From Hyprland's monitor entry (hyprctl monitors -j)."""
        x, y, w, h = A.bounds(m)
        ux, uy, uw, uh = A.usable(m)
        return cls(uw, uh, w, h, ux - x, uy - y)

    @classmethod
    def size(cls, w, h, bar=34):
        """A w x h screen with the bar along the top."""
        return cls(w, h - bar, w, h, 0, bar)

    def __repr__(self):
        return f"Screen({self.W}x{self.H} of {self.SW}x{self.SH})"


def scene_rects(clear, scr, focus=None):
    """The keep-clear areas in the area's px: [(x, y, w, h, name, soft)]. The scene is
    painted for 16:9 and drawn to cover the screen, centred on its focus (cover.py), so a
    rect follows it onto a 21:9 or 16:10 screen."""
    aspect = PLATE[0] / PLATE[1]
    if scr.SW / max(1, scr.SH) >= aspect:
        cw, ch = scr.SW, max(scr.SH, round(scr.SW / aspect))
    else:
        cw, ch = max(scr.SW, round(scr.SH * aspect)), scr.SH
    fx, fy = focus or (PLATE[0] / 2, PLATE[1] / 2)
    x0 = min(max(fx / PLATE[0] * cw - scr.SW / 2, 0), cw - scr.SW)
    y0 = min(max(fy / PLATE[1] * ch - scr.SH / 2, 0), ch - scr.SH)
    out = []
    for c in clear or []:
        rx, ry, rw, rh = c["rect"]
        x, y = rx * cw - x0 - scr.ox, ry * ch - y0 - scr.oy
        w, h = rw * cw, rh * ch
        out.append((int(x), int(y), int(round(w)), int(round(h)), c.get("name", ""), bool(c.get("soft"))))
    return out


def scene_avoid(scr, info=None):
    """The scene's keep-clear areas on a screen, for adding a widget: (hard, soft) lists of
    (x, y, w, h) in the area's px. The current theme's when info isn't given."""
    try:
        info = info or scene_info()
    except Exception:                                  # noqa: BLE001  a broken theme file: nothing kept clear
        return [], []
    rects = scene_rects(info["clear"], scr, info.get("focus"))
    return [r[:4] for r in rects if not r[5]], [r[:4] for r in rects if r[5]]


# ------------------------------------------------------------------ what each widget can be
def catalog_of(entries, signed_in=None, naturals=None):
    """{name: {"title", "classes": [(name, min, max, start)], "default", "available",
    "why", "account", "fit", "natural"}} from the gallery's entries (gallery.entries). A
    widget with an account sign-in (a "secret-signin" setting) nobody is signed in to counts
    as unavailable; signed_in(provider) answers (default: lib/bromigos_account; with demo
    readings, yes). naturals: {name: {class: height}}, what each widget's content needs in
    each class (the running panels' health file, or gallery.naturals_of); an entry's own
    "natural" is used when it has one."""
    out = {}
    naturals = naturals or {}
    for e in entries:
        provider = next((f.get("provider") for f in e.get("form") or [] if f.get("kind") == "secret-signin"), None)
        title = TITLES.get(e["name"]) or _sentence(e.get("title") or e["name"])
        ok, why = bool(e.get("available", True)), e.get("unavailable") or ""
        if ok and provider and not (signed_in or _signed_in)(provider):
            ok, why = False, f"nobody is signed in to {PROVIDERS.get(provider, provider.title())}"
        if e.get("error"):
            ok, why = False, e["error"]
        out[e["name"]] = {"title": title, "available": ok, "why": why, "account": provider,
                          "classes": [(c["name"], tuple(c["min"]), tuple(c["max"]), tuple(c["start"]))
                                      for c in e.get("sizes") or []] or
                          [("standard", tuple(e.get("min_size") or (240, 120)), tuple(e.get("max_size") or (1600, 1400)),
                            (int(e.get("width") or 470), int(e.get("height") or 300)))],
                          "default": e.get("default_size") or "standard", "category": e.get("category"),
                          "fit": e.get("fit"),
                          "natural": {str(k): int(v) for k, v in (naturals.get(e["name"]) or e.get("natural") or {}).items()
                                      if isinstance(v, (int, float)) and v > 0}}
    return out


def content_height(cat, cls, fit=None):
    """The height a widget's content needs in size class cls (cls: (name, min, max, start)),
    kept inside the class; None when it has no natural height there or fit is "fixed"."""
    if fit == "fixed" or (fit is None and cat.get("fit") != "content" and not cat.get("natural")):
        return None
    nat = (cat.get("natural") or {}).get(cls[0])
    if not nat:
        return None
    return int(max(cls[1][1], min(cls[2][1], nat)))


def _sentence(title):
    """A title in capitals as a sentence says it: "LAB JOBS" -> "Lab jobs"."""
    t = str(title).replace("_", " ")
    return t[:1].upper() + t[1:].lower() if t.isupper() or t.islower() else t


def _signed_in(provider):
    if os.environ.get("BROMIGOS_WIDGETS_DEMO") == "1":
        return True
    try:
        import sys
        for p in (os.path.join(REPO, "lib"), "/usr/lib/bromigos/lib"):
            if os.path.isdir(p) and p not in sys.path:
                sys.path.append(p)
        import bromigos_account as AC
        if hasattr(AC, "accounts"):                  # several accounts per service: any one will do
            return any(a.get("signed_in") for a in AC.accounts(provider))
        return bool(AC.status(provider).get("signed_in"))
    except Exception:                              # noqa: BLE001  no keyring, no library
        return False


# ------------------------------------------------------------------ fitting a layout to a screen
def _area(r):
    return r[2] * r[3]


def _pref(e, cat, scr):
    """The size classes an entry tries, best first: the one asked for (small or big by the
    screen), then each smaller one."""
    classes = cat["classes"]
    by = {c[0]: c for c in classes}
    small = scr.W < SMALL[0] or scr.H < SMALL[1]
    big = scr.W >= BIG[0] and scr.H >= BIG[1]
    if e.get("width") and e.get("height"):          # a saved layout's or Tidy's own size
        w, h = int(e["width"]), int(e["height"])
        first = ("own", (min(w, 240), min(h, 100)), (max(w, 240), max(h, 100)), (w, h))
    else:
        want = (e.get("small") if small else None) or (e.get("big") if big else None) or e.get("size") or cat["default"]
        first = by.get(want) or by.get(cat["default"]) or classes[0]
    out = []
    for c in [first] + sorted((c for c in classes if c is not first and _sq(c[3]) < _sq(first[3])),
                              key=lambda c: -_sq(c[3])):
        nat = content_height(cat, c, e.get("fit")) if c[0] != "own" else None
        if nat:                                         # as tall as its content, inside the class
            c = (c[0], c[1], c[2], (c[3][0], -(-nat // STEP) * STEP if nat + STEP <= c[2][1] else nat))
        out.append(c)
        snug = (max(c[1][0], int(c[3][0] * 0.85) // STEP * STEP), max(c[1][1], int(c[3][1] * 0.85) // STEP * STEP))
        if snug != tuple(c[3]) and c[0] != "own":       # the same class, a little smaller
            out.append((c[0], c[1], c[2], snug))
    return out


def _sq(wh):
    return wh[0] * wh[1]


class _Fit:
    def __init__(self, scr, hard, soft):
        self.scr, self.hard, self.soft = scr, hard, soft
        self.placed = {}                  # name -> (x, y, w, h)

    def clear(self, r, soft=True):
        x, y, w, h = r
        if x < 0 or y < 0 or x + w > self.scr.W or y + h > self.scr.H:
            return False
        if any(A.overlaps(r, p, GAP) for p in self.placed.values()):
            return False
        if any(A.overlaps(r, c[:4]) for c in self.hard):
            return False
        return not (soft and any(A.overlaps(r, c[:4]) for c in self.soft))

    def column(self, x, w, h, ys, ok):
        for y in ys:
            if ok((x, y, w, h)):
                return x, y
        return None

    def search(self, cands, w, h):
        for soft in (True, False):
            for x, y in cands:
                if self.clear((x, y, w, h), soft):
                    return x, y
        return None

    def spots(self, w, h, near=None):
        """Every place worth trying for a w x h widget: against the area's margins, beside
        each widget placed (a gap away) and each keep-clear area. Top to bottom, left to
        right; or nearest `near` first."""
        W, H = self.scr.W, self.scr.H
        xs, ys = {MARGIN, W - MARGIN - w}, {MARGIN, H - MARGIN - h}
        for r in self.placed.values():
            xs.update((r[0] + r[2] + GAP, r[0] - GAP - w, r[0]))
            ys.update((r[1] + r[3] + GAP, r[1] - GAP - h, r[1]))
        for c in self.hard + self.soft:
            xs.update((c[0] + c[2], c[0] - w))
            ys.update((c[1] + c[3], c[1] - h))
        if near:
            xs.add(near[0])
            ys.add(near[1])
        xs = [x for x in xs if MARGIN <= x <= W - MARGIN - w]
        ys = [y for y in ys if MARGIN <= y <= H - MARGIN - h]
        out = [(x, y) for y in sorted(ys) for x in sorted(xs)]
        if near:
            out.sort(key=lambda p: (p[0] - near[0]) ** 2 + (p[1] - near[1]) ** 2)
        return out


def fit(tpl, scr, catalog, clear=(), focus=None, budget=None, keep=None):
    """Fits a template to a screen. Returns {"placed": {name: {"x", "y", "width", "height",
    "size"}}, "left_out": [{"name", "title", "why"}], "coverage" (the share of the area
    covered), "budget", "over_budget", "order": [names placed, in the template's order]}.

    catalog: catalog_of(); clear: the scene's keep-clear areas (scene_info()["clear"]);
    keep: names to keep at their current size and order (Tidy up), already in `tpl`."""
    W, H = scr.W, scr.H
    rects = scene_rects(clear, scr, focus)
    hard = [r for r in rects if not r[5]]
    soft = [r for r in rects if r[5]]
    budget = tpl.get("budget") if budget is None else budget
    if budget is None:
        budget = 1.0 if tpl.get("pack") else BUDGET
    left_out = []
    entries = []
    seen = set()
    for e in _entries(tpl, catalog):
        names = [n for n in e["names"] if n not in seen]
        if not names:
            continue
        pick = next((n for n in names if n in catalog and catalog[n]["available"]), None)
        if pick is None:
            left_out.append(_why(names, catalog))
            seen.update(names)
            continue
        seen.add(pick)
        entries.append(dict(e, name=pick, prefs=_pref(e, catalog[pick], scr), ci=0))
    alive = list(entries)
    for _round in range(200):
        f = _Fit(scr, hard, soft)
        failed = _place_all(f, alive)
        cov = sum(_area(r) for r in f.placed.values()) / float(max(1, W * H))
        over = cov > budget + 1e-6
        if not failed and not over:
            break
        if failed:
            # the failed, and what's ahead of them in their own column or row
            cands = list(failed)
            for e in failed:
                cands += [o for o in alive if o is not e and o["side"] == e["side"] and o["side"] != "flow"
                          and o["lane"] == e["lane"] and o["order"] < e["order"] and o["name"] in f.placed]
        else:
            cands = [e for e in alive if e["name"] in f.placed]
        victim = max(cands, key=lambda e: (e["priority"], e["order"]))
        if victim["ci"] + 1 < len(victim["prefs"]):
            victim["ci"] += 1
            continue
        alive.remove(victim)
        title = catalog[victim["name"]]["title"]
        left_out.append({"name": victim["name"], "title": title,
                         "why": "no room for it here, even at its smallest size" if failed and victim in failed else
                         "left out so the scene shows: it would cover more than "
                         f"{round(budget * 100)}% of the screen" if not failed else
                         "no room for it beside the widgets that matter more here"})
    placed = {}
    for e in alive:
        r = f.placed.get(e["name"])
        if r:
            c = e["prefs"][e["ci"]]
            placed[e["name"]] = {"x": int(r[0]), "y": int(r[1]), "width": int(r[2]), "height": int(r[3]),
                                 "size": c[0] if c[0] != "own" else None}
    cov = sum(p["width"] * p["height"] for p in placed.values()) / float(max(1, W * H))
    return {"placed": placed, "left_out": left_out, "coverage": round(cov, 3), "budget": round(budget, 3),
            "over_budget": cov > BUDGET + 1e-6, "order": [e["name"] for e in alive if e["name"] in placed],
            "clear": [{"x": r[0], "y": r[1], "width": r[2], "height": r[3], "name": r[4], "soft": r[5]} for r in rects]}


def _why(names, catalog):
    titles = list(dict.fromkeys(catalog[n]["title"] if n in catalog else TITLES.get(n) or _sentence(n) for n in names))
    whys = []
    for n in names:
        c = catalog.get(n)
        if c is None:
            whys.append("it isn't here (a homelab widget needs bromigos-homelab and a source for it)"
                        if n in ("lab", "alerts", "labjobs", "games", "game_servers", "solar") else "it isn't installed")
        else:
            whys.append(c["why"] or "it can't show anything here")
    title = " or ".join(titles)
    why = whys[0] if len(set(whys)) == 1 or len(titles) == 1 else "; ".join(f"{t}: {w}" for t, w in zip(titles, whys))
    return {"name": names[0], "title": title, "why": why}


def _entries(tpl, catalog):
    """The template's widget entries; Everything's (pack) are every widget that can show
    something, bromigOS's own first, each flowing into the next free column."""
    if not tpl.get("pack"):
        return tpl["widgets"]
    listed = {n for e in tpl["widgets"] for n in e["names"]}
    out = list(tpl["widgets"])
    rank = {c: i for i, c in enumerate(("system", "network", "homelab", "notes", "media", "fun"))}
    rest = sorted((n for n in catalog if n not in listed and n not in tpl.get("exclude", [])),
                  key=lambda n: (rank.get(catalog[n].get("category"), 9), n))
    for i, n in enumerate(rest):
        out.append({"names": [n], "size": "compact", "small": "compact", "big": None, "side": "flow", "lane": 1,
                    "from": "top", "at": None, "priority": 6 + i // 4, "order": 1000 + i, "width": None, "height": None})
    return out


def _place_all(f, entries):
    """Places the entries in turn: the left columns lane by lane, then the right ones, the
    rows, the fixed places and the flowing ones. A column's or a row's widget with no room
    on its own side tries the other side at the same size, keeping off the soft areas
    first. Returns the entries that found no place."""
    W, H = f.scr.W, f.scr.H
    failed = []
    edge = {"left": {0: MARGIN - GAP}, "right": {0: W - MARGIN + GAP}}   # lane -> its inner edge
    groups = {}
    for e in entries:
        groups.setdefault((e["side"], e["lane"] if e["side"] in ("left", "right") else 0), []).append(e)
    rank = ["left", "right", "top", "bottom", None, "flow"]
    for key in sorted(groups, key=lambda k: (rank.index(k[0]), k[1])):
        side, lane = key
        grp = groups[key]
        if side in ("left", "right"):
            prev = max((k for k in edge[side] if k < lane), default=0)
            base = edge[side][prev]
            cursor = {"top": MARGIN, "bottom": H - MARGIN}
            inner = base
            for e in grp:
                w, h = e["prefs"][e["ci"]][3]
                x = base + GAP if side == "left" else base - GAP - w
                if e["from"] == "top":
                    cands = [(x, y) for y in range(cursor["top"], H - MARGIN - h + 1, STEP)]
                else:
                    cands = [(x, y) for y in range(cursor["bottom"] - h, MARGIN - 1, -STEP)]
                other = "right" if side == "left" else "left"
                spot = _try(f, e, w, h, cands, other)
                if spot is None:
                    failed.append(e)
                    continue
                f.placed[e["name"]] = (spot[0], spot[1], w, h)
                if spot[0] != x:
                    continue                          # it went to the other side
                if e["from"] == "top":
                    cursor["top"] = spot[1] + h + GAP
                else:
                    cursor["bottom"] = spot[1] - GAP
                inner = max(inner, spot[0] + w) if side == "left" else min(inner, spot[0])
            edge[side][lane] = inner
        elif side in ("top", "bottom"):
            cursor = {"left": MARGIN, "right": W - MARGIN}
            for e in grp:
                w, h = e["prefs"][e["ci"]][3]
                y = MARGIN if side == "top" else H - MARGIN - h
                if e["from"] == "left":
                    cands = [(x, y) for x in range(cursor["left"], W - MARGIN - w + 1, STEP)]
                else:
                    cands = [(x, y) for x in range(cursor["right"] - w, MARGIN - 1, -STEP)]
                spot = _try(f, e, w, h, cands, "right" if e["from"] == "left" else "left")
                if spot is None:
                    failed.append(e)
                    continue
                f.placed[e["name"]] = (spot[0], spot[1], w, h)
                if spot[1] != y:
                    continue
                if e["from"] == "left":
                    cursor["left"] = spot[0] + w + GAP
                else:
                    cursor["right"] = spot[0] - GAP
        elif side == "flow":
            for e in grp:
                w, h = e["prefs"][e["ci"]][3]
                spot = _flow_spot(f, w, h, e.get("prefer") or "left", anywhere=True)
                if spot is None:
                    failed.append(e)
                    continue
                f.placed[e["name"]] = (spot[0], spot[1], w, h)
        else:                                       # at = [fx, fy]: as near there as it can
            for e in grp:
                w, h = e["prefs"][e["ci"]][3]
                tx = min(max(0, int(round(e["at"][0] * W))), max(0, W - w))
                ty = min(max(0, int(round(e["at"][1] * H))), max(0, H - h))
                spot = f.search(f.spots(w, h, (tx, ty)), w, h)
                if spot is None:
                    failed.append(e)
                    continue
                f.placed[e["name"]] = (spot[0], spot[1], w, h)
    return failed


def _try(f, e, w, h, cands, other):
    """Its own column (or row) keeping off the soft areas, then the other side's columns,
    then its own over a soft area, then the other side's."""
    for soft in (True, False):
        for x, y in cands:
            if f.clear((x, y, w, h), soft):
                return x, y
        spot = _flow_spot(f, w, h, other, soft=soft, sides=1)
        if spot:
            return spot
    return None


def _flow_spot(f, w, h, prefer, soft=None, sides=2, anywhere=False):
    """Where a flowing widget goes: down the first column with room on its own half of the
    screen (`prefer`), the column by the edge first and then the ones beside the widgets
    already placed; then the other half; then (anywhere) any clear place."""
    W, H = f.scr.W, f.scr.H
    order = [prefer, "right" if prefer == "left" else "left"][:sides]
    for sf in ((True, False) if soft is None else (soft,)):
        for side in order:
            for x in _lane_xs(f, side, w):
                for y in range(MARGIN, H - MARGIN - h + 1, STEP):
                    if f.clear((x, y, w, h), sf):
                        return x, y
    if anywhere:
        return f.search(f.spots(w, h), w, h)
    return None


def _lane_xs(f, side, w):
    """The columns a w-wide widget can flow into on one half: by the edge, then beside each
    widget placed on that half, nearest the edge first."""
    W = f.scr.W
    if side == "left":
        xs = [MARGIN] + sorted({r[0] + r[2] + GAP for r in f.placed.values() if r[0] + r[2] / 2 < W / 2})
        return [x for x in dict.fromkeys(xs) if x + w <= W - MARGIN and x < W / 2]
    xs = [W - MARGIN - w] + sorted({r[0] - GAP - w for r in f.placed.values() if r[0] + r[2] / 2 >= W / 2},
                                   reverse=True)
    return [x for x in dict.fromkeys(xs) if x >= MARGIN and x + w > W / 2]


# ------------------------------------------------------------------ Tidy up
def tidy_template(state, scr):
    """The widgets on now (a state: {name: {x, y, width, height, visible}}) as a flowing
    template: each keeps its size and goes to its own half of the screen, in the order it
    was in (down each column, the columns from the edge in)."""
    vis = [(n, s) for n, s in state.items() if s.get("visible", True) and s.get("width") and s.get("height")]

    def side(s):
        return "left" if s.get("x", 0) + s["width"] / 2 <= scr.W / 2 else "right"

    def key(item):
        n, s = item
        sd = side(s)
        edge_dist = s.get("x", 0) if sd == "left" else scr.W - (s.get("x", 0) + s["width"])
        return (sd != "left", edge_dist // 160, s.get("y", 0), n)
    out = []
    for i, (n, s) in enumerate(sorted(vis, key=key)):
        out.append({"names": [n], "size": None, "small": None, "big": None, "side": "flow", "lane": 1, "from": "top",
                    "at": None, "priority": 1, "order": i, "width": s["width"], "height": s["height"],
                    "prefer": side(s)})
    return {"id": "tidy", "title": "Tidy up", "description": "", "archetype": "tidy", "budget": 1.0, "pack": False,
            "widgets": out, "source": "bromigos", "path": None}


def tidy(state, scr, catalog, clear=(), focus=None):
    """Tidy up: the widgets on now packed without overlapping, their order kept, off the
    scene's focal points where it can (every keep-clear area is soft here: the widgets are
    the ones you chose); one that fits its content as tall as its content needs, inside its
    size class. Returns fit()'s result (left_out: those with no room at all)."""
    clear = [dict(c, soft=True) for c in clear or []]
    cat = dict(catalog)
    state = {n: dict(s) for n, s in state.items()}
    for n, s in state.items():                 # a widget that fits its content: as tall as it needs
        c = cat.get(n)
        if c and s.get("width") and s.get("height"):
            name = A.fit_class([k[:3] for k in c["classes"]], s["width"], s["height"])[2]
            cls = next((k for k in c["classes"] if k[0] == name), None)
            nat = content_height(c, cls) if cls else None
            if nat:
                s["height"] = nat
    for n, s in state.items():               # a widget the catalog doesn't know keeps its own size only
        if n not in cat and s.get("visible", True):
            cat[n] = {"title": TITLES.get(n) or _sentence(n), "available": True, "why": "", "account": None, "default": "own",
                      "classes": [("own", (s["width"], s["height"]), (s["width"], s["height"]),
                                   (s["width"], s["height"]))]}
        elif n in cat:
            cat[n] = dict(cat[n], available=True)     # it's on: tidy it, whatever it can show
    return fit(tidy_template(state, scr), scr, cat, clear, focus, budget=1.0)


# ------------------------------------------------------------------ saving one of yours
def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48]
    return s or "mine"


def from_state(state, scr, catalog, title, description=""):
    """The widgets on now as a layout file's text: each at its place as fractions of the
    area, at its size, so it comes back where it was on this screen and near there on
    another."""
    lines = [f"# Saved with `bromigos panels layout save` on {time.strftime('%Y-%m-%d')}, from a "
             f"{scr.W}x{scr.H} area (docs/widgets.md, \"Layouts\")",
             f"title = {json.dumps(title)}", f"description = {json.dumps(description or 'Your own layout')}",
             'archetype = "yours"', "budget = 1.0", ""]
    vis = sorted(((n, s) for n, s in state.items() if s.get("visible", True) and s.get("width")),
                 key=lambda kv: (kv[1].get("y", 0), kv[1].get("x", 0)))
    for i, (n, s) in enumerate(vis):
        fx, fy = round(s.get("x", 0) / max(1, scr.W), 5), round(s.get("y", 0) / max(1, scr.H), 5)
        cls = None
        if n in catalog:
            cls = A.fit_class([(c[0], c[1], c[2]) for c in catalog[n]["classes"]], s["width"], s["height"])[2]
        lines += ["[[widget]]", f"name = {json.dumps(n)}", f"at = [{fx}, {fy}]",
                  f"width = {int(s['width'])}", f"height = {int(s['height'])}"]
        if cls:
            lines.append(f"size = {json.dumps(cls)}")
        lines += [f"priority = {i + 1}", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ a fit as layout.json's state
def to_state(result, names_on_monitor, output=None):
    """A fit's placements as an arrange state: each placed widget on, at its place and
    size (and `output`, its monitor: an identity dict, or None for the primary); every
    other widget on that monitor off. Widgets on other monitors aren't touched."""
    st = {}
    for n in names_on_monitor:
        if n not in result["placed"]:
            st[n] = {"visible": False}
    for n, p in result["placed"].items():
        st[n] = {"x": p["x"], "y": p["y"], "width": p["width"], "height": p["height"], "visible": True,
                 "output": output}
    return st


def overlapping(state, gap=0):
    """The pairs of shown widgets that overlap, on the same monitor: [(a, b)]."""
    vis = [(n, s) for n, s in state.items() if s.get("visible", True) and all(k in s for k in ("x", "y", "width", "height"))]
    out = []
    for i, (a, sa) in enumerate(vis):
        for b, sb in vis[i + 1:]:
            if _mon(sa) != _mon(sb):
                continue
            if A.overlaps((sa["x"], sa["y"], sa["width"], sa["height"]), (sb["x"], sb["y"], sb["width"], sb["height"]), gap):
                out.append((a, b))
    return out


def _mon(s):
    o = s.get("output")
    if isinstance(o, dict):
        return tuple(str(o.get(k) or "") for k in ("make", "model", "serial")) if any(
            o.get(k) for k in ("make", "model", "serial")) else o.get("name") or ""
    return o or ""


# ------------------------------------------------------------------ memory: per scene, undo
def _read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(json.dumps(doc, indent=2) + "\n")
    os.replace(tmp, path)


def record():
    """{"scene": the scene layout.json is arranged for, "everywhere": a layout applied to every
    theme, or None}."""
    d = _read_json(record_path(), {}) or {}
    return {"scene": d.get("scene"), "everywhere": d.get("everywhere")}


def set_record(**kw):
    d = record()
    d.update(kw)
    _write_json(record_path(), d)
    return d


def placement(state):
    """Only what a layout decides: each widget's place, size, monitor and whether it's on."""
    out = {}
    for n, s in state.items():
        out[n] = {k: s[k] for k in ("x", "y", "width", "height", "visible", "output") if k in s}
    return out


def remember(scene, state):
    if not scene or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", scene):
        return None
    path = os.path.join(scenes_dir(), f"{scene}.json")
    _write_json(path, {"scene": scene, "saved": int(time.time()), "panels": placement(state)})
    return path


def recall(scene):
    if not scene or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", scene):
        return None
    d = _read_json(os.path.join(scenes_dir(), f"{scene}.json"))
    return d.get("panels") if isinstance(d, dict) and isinstance(d.get("panels"), dict) else None


def forget_scenes(keep=()):
    d = scenes_dir()
    if not os.path.isdir(d):
        return []
    gone = []
    for f in os.listdir(d):
        if f.endswith(".json") and f[:-5] not in keep:
            os.unlink(os.path.join(d, f))
            gone.append(f[:-5])
    return gone


def save_undo(state, what, scene=None):
    _write_json(undo_path(), {"panels": placement(state), "what": what, "scene": scene, "at": int(time.time())})


def take_undo():
    d = _read_json(undo_path())
    if not isinstance(d, dict) or not isinstance(d.get("panels"), dict):
        return None
    os.unlink(undo_path())
    return d


def peek_undo():
    d = _read_json(undo_path())
    return d if isinstance(d, dict) and isinstance(d.get("panels"), dict) else None


def restore(doc, saved, monitor_names=None):
    """A layout with a remembered placement put back: each widget it lists as it was, and
    every other widget off (on the monitors it speaks for)."""
    st = {}
    for n, s in saved.items():
        st[n] = dict(s)
    for n in A.state_of(doc):
        if n not in st and (monitor_names is None or n in monitor_names):
            st[n] = {"visible": False}
    return A.apply(doc, st)
