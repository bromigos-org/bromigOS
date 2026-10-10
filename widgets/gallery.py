"""The widget gallery's list: every panel there is, with what it shows, who made it, what
it reads and where it sits (docs/widgets.md, "The widget gallery").

Edit mode's tray (editmode.py) and Settings › Widgets (through `bromigos panels gallery`)
both read it. Each entry:

    name, title, description, category, reads    the panel's own words (panels.Panel)
    source       "bromigos" (built in), "homelab" (bromigos-homelab's), "extension"
                 (installed with `bromigos ext`) or "yours" (a file in your plugin folder)
    author       "bromigOS", the extension's authors, or "you"
    extension    the extension it came from, with its licence and homepage (or None)
    visible, x, y, width, height    as layout.json has it
    min_size, max_size              the sizes edit mode lets it take
    settings     where its own settings are (Settings' page and row), or None

`bromigos-widgets gallery [--previews DIR]` prints it as JSON; with --previews, it draws
each panel once to DIR/<name>.png (demo readings when BROMIGOS_WIDGETS_DEMO=1).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import arrange as A  # noqa: E402

CATEGORIES = ("system", "network", "homelab", "media", "notes", "fun")
CATEGORY_NAMES = {"system": "System", "network": "Network", "homelab": "Homelab", "media": "Media",
                  "notes": "Notes and work", "fun": "Fun and extras"}
# FIELD NOTES isn't a Panel (it's a text box): its words, here
NOTES = {"title": "FIELD NOTES", "description": "A notepad on your desktop that saves as you type",
         "category": "notes", "reads": "your notes file", "min_size": (280, 160), "max_size": (1200, 1200),
         "width": 470, "height": 268}
# the panels with settings of their own, and where Settings keeps them
SETTINGS = {"weather": {"page": "widgets", "key": "weather-place", "what": "the place, units and label"},
            "lab": {"page": "lab", "key": None, "what": "the homelab's sources"},
            "network": {"page": "widgets", "key": "layout", "what": "the hosts the radar pings (layout.json)"}}
ORDER = ("system", "network", "storage", "shortcuts", "workbench", "notes", "weather", "connections")


def core_classes():
    import panels as P
    return P.CORE


def classes_of(obj):
    """A panel's size classes, [(name, min, max, start)] (panels.Panel.size_classes):
    FIELD NOTES' one class when obj is None."""
    inner = getattr(obj, "inner", obj)
    if inner is not None and hasattr(inner, "size_classes"):
        try:
            return [(n, tuple(lo), tuple(hi), tuple(st)) for n, lo, hi, st in inner.size_classes()]
        except Exception:                      # a plugin's bad `sizes`: its plain limits
            pass
    src = NOTES if inner is None else {"min_size": getattr(inner, "min_size", (240, 120)),
                                        "max_size": getattr(inner, "max_size", (1600, 1400)),
                                        "width": getattr(inner, "width", 470), "height": getattr(inner, "height", 200)}
    return [("standard", tuple(src["min_size"]), tuple(src["max_size"]), (src["width"], src["height"]))]


def availability(obj, cache=None):
    """(available, reason) from a panel's available() (panels.Panel.available): True,
    False or (bool, reason); an error in it counts as available. cache: a dict kept for one
    opening of the gallery, so each class is asked once."""
    inner = getattr(obj, "inner", obj)
    key = inner if isinstance(inner, type) else type(inner)
    if cache is not None and key in cache:
        return cache[key]
    try:
        got = inner.available() if hasattr(inner, "available") else True
    except Exception:
        got = True
    ok, why = (bool(got[0]), str(got[1]) if len(got) > 1 and got[1] else "") if isinstance(got, tuple) else (bool(got), "")
    if cache is not None:
        cache[key] = (ok, why)
    return ok, why


def meta_of(obj, name=None):
    """A panel class's or instance's gallery words (a plugin's SafePanel too)."""
    inner = getattr(obj, "inner", obj)
    cat = getattr(inner, "category", "system")
    cs = classes_of(obj)
    default = getattr(inner, "default_size", "standard")
    start = next((c[3] for c in cs if c[0] == default), cs[0][3])
    return {"title": str(getattr(inner, "title", None) or (name or "").upper()),
            "description": str(getattr(inner, "description", "") or ""),
            "category": cat if cat in CATEGORIES else "fun",
            "reads": str(getattr(inner, "reads", "") or ""),
            "min_size": (min(c[1][0] for c in cs), min(c[1][1] for c in cs)),
            "max_size": (max(c[2][0] for c in cs), max(c[2][1] for c in cs)),
            "sizes": [{"name": n, "min": list(lo), "max": list(hi), "start": list(st)} for n, lo, hi, st in cs],
            "default_size": default if any(c[0] == default for c in cs) else cs[0][0],
            "start": list(start)}


# ------------------------------------------------------------------ who made it
def _ledger():
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    try:
        with open(os.path.join(state, "bromigos", "ext", "ledger.json")) as f:
            return (json.load(f) or {}).get("extensions") or {}
    except (OSError, ValueError):
        return {}


def _manifest(root):
    try:
        import tomllib
        with open(os.path.join(root, "bromigos-ext.toml"), "rb") as f:
            return tomllib.load(f).get("extension") or {}
    except (OSError, ValueError, ImportError):
        return {}


def extensions():
    """{widget name: the extension that provides it} from `bromigos ext`'s ledger and each
    extension's manifest: name, authors, licence, homepage, source, enabled."""
    out = {}
    for name, e in _ledger().items():
        if not isinstance(e, dict):
            continue
        m = _manifest(e.get("root") or e.get("dir") or "")
        src = e.get("source") or {}
        info = {"name": name, "version": e.get("version"), "description": e.get("description") or m.get("description"),
                "authors": m.get("authors") or [], "licence": m.get("licence") or m.get("license"),
                "homepage": m.get("homepage") or (src.get("url") if str(src.get("url", "")).startswith("https://") else None),
                "source": src.get("url"), "enabled": bool(e.get("enabled", True)), "code": True}
        for p in e.get("parts") or []:
            if p.get("kind") == "widget":
                out[p.get("name")] = info
    return out


def source_of(path):
    """Where a plugin file came from: bromigos, homelab, extension or yours."""
    import plugins as PL
    p = (path or "").split("#", 1)[0]
    if p.startswith(os.path.join(HERE, "plugins") + os.sep):
        return "bromigos"
    if PL._HOMELAB and p.startswith(PL._HOMELAB + os.sep):
        return "homelab"
    if p.startswith(PL.EXT + os.sep):
        return "extension"
    return "yours"


# ------------------------------------------------------------------ the list
def notes_meta():
    return dict(NOTES, **{k: v for k, v in meta_of(None, "notes").items() if k not in ("title", "description",
                                                                                     "category", "reads")})


def entry(name, meta, source, state, ext=None):
    s = state.get(name) or {}
    author = {"bromigos": "bromigOS", "homelab": "bromigOS (homelab)", "yours": "you"}.get(source)
    if source == "extension":
        author = ", ".join(a.split(" <")[0] for a in (ext or {}).get("authors") or []) or (ext or {}).get("name") or "?"
    width, height = s.get("width", meta.get("width")), s.get("height", meta.get("height"))
    cls = None
    if width and height and meta.get("sizes"):
        import arrange
        cls = arrange.fit_class([(c["name"], c["min"], c["max"]) for c in meta["sizes"]], width, height)[2]
    return dict(meta, name=name, source=source, author=author, extension=ext,
                visible=bool(s.get("visible", True)),
                x=s.get("x"), y=s.get("y"), width=width, height=height, size_class=cls,
                min_size=list(meta["min_size"]), max_size=list(meta["max_size"]),
                settings=SETTINGS.get(name))


def addable(e):
    """Whether the gallery offers this entry to add: available, or already on the desktop
    (then it's shown greyed out with the reason, so it can be taken off)."""
    return e.get("available", True) or e.get("visible")


def entries(doc=None, plugins=True):
    """Every panel: bromigOS's, then the plugins (homelab's, extensions', yours), each with
    its place in the layout (doc: a layout.json; the user's, else bromigOS's)."""
    if doc is None:
        try:
            doc = A.read()[0]
        except (OSError, ValueError):
            doc = {"panels": []}
    state = A.state_of(doc)
    out = []
    core = core_classes()
    asked = {}
    for name in ORDER:
        if name == "notes":
            meta = notes_meta()
            ok, why = True, ""
        else:
            cls = core[name]
            meta = dict(meta_of(cls, name), width=cls.width, height=cls.height)
            ok, why = availability(cls, asked)
        out.append(dict(entry(name, meta, "bromigos", state), available=ok, unavailable=why))
    if not plugins:
        return out
    import plugins as PL
    exts = extensions()
    for name, (path, _m) in sorted(PL.files().items()):
        if name in core or name == "notes":
            continue
        src = source_of(path)
        try:
            cls, layout = PL.load(os.path.realpath(path) if "#" not in path else path)
            meta = dict(meta_of(cls, name), width=layout.get("width", cls.width),
                        height=layout.get("height", cls.height))
            err = None
        except Exception as e:                        # listed, with why it can't load
            meta = dict(meta_of(object(), name), width=470, height=200, category="fun")
            err = f"{type(e).__name__}: {str(e)[:160]}"
        e = entry(name, meta, src, state, exts.get(name) if src == "extension" else None)
        e["error"] = err
        e["available"], e["unavailable"] = availability(cls, asked) if err is None else (False, err)
        if name not in state:
            e["visible"] = bool(layout.get("visible", True)) if err is None else False
        out.append(e)
    return out


def render_previews(items, outdir, ticks=2):
    """Draws each panel once to outdir/<name>.png at its size: instantiated together,
    sampled `ticks` times a second apart, then drawn (a second or two for all of them)."""
    import cairo

    import plugins as PL
    os.makedirs(outdir, exist_ok=True)
    core = core_classes()
    made = {}
    for it in items:
        name = it["name"]
        try:
            if name == "notes":
                made[name] = None
                continue
            if name in core:
                cls, layout = core[name], {}
            else:
                path = PL.files()[name][0]
                cls, layout = PL.load(os.path.realpath(path) if "#" not in path else path)
            cfg = dict(layout, name=name)
            made[name] = PL.make(cls, cfg, lambda p: None)
        except Exception:
            continue
    for i in range(max(1, ticks)):
        for p in made.values():
            try:
                p and p.tick()
            except Exception:
                pass
        if i < ticks - 1:
            time.sleep(1.0)
    paths = {}
    for it in items:
        name = it["name"]
        if name not in made:
            continue
        w, h = int(it.get("width") or 470), int(it.get("height") or 200)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        try:
            if made[name] is None:
                draw_notes(cr, w, h)
            else:
                cr.push_group()
                made[name].render(cr, w, h)
                cr.pop_group_to_source()
                cr.paint()
        except Exception:
            continue
        out = os.path.join(outdir, f"{name}.png")
        surf.write_to_png(out)
        paths[name] = out
    return paths


def notes_text(limit=12):
    path = os.path.expanduser("~/.local/share/bromigos/notes.md")
    try:
        with open(path) as f:
            return f.read().splitlines()[-limit:]
    except OSError:
        return []


def draw_notes(cr, w, h, lines=None):
    """FIELD NOTES drawn as a picture (the gallery's card; the panel itself is a text box)."""
    import draw as D
    top = D.frame(cr, w, h, "FIELD NOTES", f"{len(lines or [])} LINES" if lines is not None else "")
    y = top
    for ln in (lines if lines is not None else notes_text()):
        if y > h - 28:
            break
        D.text(cr, 16, y, ln or " ", 13, "soft")
        y += 19


def main(argv):
    previews = argv[argv.index("--previews") + 1] if "--previews" in argv else None
    items = entries()
    if previews:
        got = render_previews(items, previews)
        for it in items:
            it["preview"] = got.get(it["name"])
    print(json.dumps({"widgets": items, "categories": [{"id": c, "title": CATEGORY_NAMES[c]} for c in CATEGORIES]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
