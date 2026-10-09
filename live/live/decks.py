"""Every deck there is, and the Tab cycle through them.

bromigOS's own decks, bromigos-homelab's (when it's installed) and any deck a plugin
folder adds (a `<kind>_deck.py` beside the user's other live plugins, or an extension's:
live.PLUGINS). Nothing here names a deck of the user's own: a plugin deck brings its own
words, read from its file without running it:

    deck_label = "Trades"             what menus, the shortcuts panel and the Tab hint call it
    deck_hint = "the trading floor"   a few words after it in the menu

(on its DECK class or at module level). Without them: its `title` before " //", else
"<Kind> deck".

The Tab cycle is the live config's `[decks] cycle` (deck kinds, in order; a kind that
isn't installed is passed over), by default bromigOS's own and the homelab's.

    python3 -m live.decks [--json]       the catalog (bromigos-live decks)
"""
import json
import os
import re
import sys

from . import HOMELAB, PLUGINS

# (kind, label, hint): bromigOS's own, then bromigos-homelab's
BUILTIN = [("holodeck", "Holo deck", "this machine"), ("driftmap", "Drift map", "the star chart"),
           ("timeline", "Timeline", "the last 72 h"), ("swarm", "Swarm", "repos and agents")]
# bromigos-homelab's decks are its live/<kind>_deck.py files (labels below, else their own)
HOMELAB_LABELS = {"lab": ("Lab", "the homelab console: the rack, GPUs, jobs (SUPER+SHIFT+H)"),
                  "mind": ("Mind", "VECTOR's memory"), "ops": ("Ops theater", "pushes, CI, Argo, pods"),
                  "netmap": ("Network map", "the LAN")}
DEFAULT_CYCLE = ["holodeck", "timeline", "mind", "ops", "swarm", "netmap"]

_STR = r"""\s*=\s*(?P<q>["'])(?P<v>.*?)(?P=q)"""


def _attr(text, name):
    """A string `name = "…"` at module or class level (not one inside a method)."""
    m = re.search(r"^(?:    )?" + name + _STR, text, re.M)
    return m.group("v").strip() if m else ""


def _deck_files(dirs):
    """{kind: path} of the folders' <kind>_deck.py (the first folder wins)."""
    out = {}
    for d in dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for f in names:
            if f.endswith("_deck.py") and f[:-8].isidentifier():
                out.setdefault(f[:-8], os.path.join(d, f))
    return out


def _described(kind, path, source, known=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    if known:
        return {"kind": kind, "label": known[0], "hint": known[1], "source": source}
    title = _attr(text, "title").split(" //")[0].strip()
    label = _attr(text, "deck_label") or (title.capitalize() if title else f"{kind.capitalize()} deck")
    return {"kind": kind, "label": label, "hint": _attr(text, "deck_hint"), "source": source}


def catalog():
    """[{kind, label, hint, source}] in menu order: bromigOS's, the homelab's, the plugins'."""
    out = [{"kind": k, "label": label, "hint": hint, "source": "bromigos"} for k, label, hint in BUILTIN]
    groups = []
    if HOMELAB:
        groups.append(("homelab", _deck_files([os.path.join(HOMELAB, "live")])))
    groups.append(("plugin", _deck_files(PLUGINS)))
    for source, files in groups:
        for kind, path in sorted(files.items(), key=lambda kv: (kv[0] not in HOMELAB_LABELS, kv[0])):
            if any(d["kind"] == kind for d in out):
                continue
            d = _described(kind, path, source, HOMELAB_LABELS.get(kind) if source == "homelab" else None)
            if d:
                out.append(d)
    return out


def label(kind):
    """What a deck is called ("<Kind> deck" when it isn't installed)."""
    return next((d["label"] for d in catalog() if d["kind"] == kind), f"{kind.capitalize()} deck")


def cycle(cfg=None):
    """The Tab cycle: [decks] cycle's kinds that are installed."""
    if cfg is None:
        from . import config
        cfg = config.load()
    want = (cfg.get("decks") or {}).get("cycle") or DEFAULT_CYCLE
    have = {d["kind"] for d in catalog()}
    return [k for k in want if isinstance(k, str) and k in have]


def next_deck(kind, cfg=None):
    """The deck after `kind` in the cycle (the first when `kind` isn't in it), or None."""
    cyc = cycle(cfg)
    rest = [k for k in cyc if k != kind]
    if not rest:
        return None
    if kind not in cyc:
        return rest[0]
    i = cyc.index(kind)
    return cyc[(i + 1) % len(cyc)]


def main(argv):
    cat = catalog()
    if "--json" in argv:
        print(json.dumps({"decks": cat, "cycle": cycle()}))
    else:
        for d in cat:
            print(f"{d['kind']:<12} {d['label']}" + (f" ({d['hint']})" if d["hint"] else "") +
                  (f" [{d['source']}]" if d["source"] != "bromigos" else ""))
        print("Tab: " + " → ".join(cycle()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
