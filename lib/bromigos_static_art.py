"""STATIC's art, wherever it comes from (docs/ASSETS.md, "STATIC, the mascot"). The art is a
folder holding a manifest.json that names each pose's frames at a few heights, as rendered
images or an animated WebP. New renders drop in without a code change. Without a folder,
the code-drawn placeholder (bromigos_static.py) stands in.

  manifest.json:
    {"schema": 1, "fps": 6,
     "art": {"<name>": {"<height px>": ["frame-00.png", "frame-01.png", ...]  or  "loop.webp"}}}

  <name>: a pose ("host"), a pose wearing a face ("remote:snow"), or the monitor alone
  ("head:watching", "head"). Paths are relative to the manifest. A name may also carry
  its own "fps".

  folders(env=None)                     where art is looked for; the first that has a name wins:
                                        $BROMIGOS_STATIC_ART, ~/.local/share/bromigos/static,
                                        /usr/share/bromigos/static
  find(pose, face=None, height=0, head=False, env=None) -> Art or None
      Art.frames: [paths] (one animated file is a single path, Art.animated True); Art.fps
  names(env=None) -> {name: [heights]}  everything the folders offer (the tests, `--list`)
"""
import json
import os

ANIMATED = (".webp", ".gif", ".apng")


class Art:
    def __init__(self, name, height, frames, fps, folder):
        self.name, self.height, self.frames, self.fps, self.folder = name, height, frames, fps, folder
        self.animated = len(frames) == 1 and frames[0].lower().endswith(ANIMATED)

    def __repr__(self):
        return f"Art({self.name!r}, {self.height}, {len(self.frames)} frames)"


def folders(env=None):
    env = os.environ if env is None else env
    data = env.get("XDG_DATA_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "share")
    out = []
    for d in (env.get("BROMIGOS_STATIC_ART"), os.path.join(data, "bromigos", "static"), "/usr/share/bromigos/static"):
        if d and d not in out:
            out.append(d)
    return out


_CACHE = {}


def _manifest(folder):
    path = os.path.join(folder, "manifest.json")
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return None
    hit = _CACHE.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(path) as f:
            doc = json.load(f)
        if not isinstance(doc, dict) or doc.get("schema") != 1 or not isinstance(doc.get("art"), dict):
            doc = None
    except (OSError, ValueError):
        doc = None
    _CACHE[path] = (mtime, doc)
    return doc


def _pick(sizes, height):
    """The smallest height at least this tall, else the tallest there is."""
    hs = sorted(int(h) for h in sizes if str(h).isdigit())
    if not hs:
        return None
    return next((h for h in hs if h >= height), hs[-1])


def find(pose, face=None, height=0, head=False, env=None):
    if head:
        names = ([f"head:{face}"] if face else []) + ["head"]
    else:
        names = ([f"{pose}:{face}"] if face else []) + [pose]
    for folder in folders(env):
        doc = _manifest(folder)
        if not doc:
            continue
        for name in names:
            entry = doc["art"].get(name)
            if not isinstance(entry, dict):
                continue
            h = _pick([k for k in entry if k != "fps"], height)
            if h is None:
                continue
            files = entry[str(h)]
            files = [files] if isinstance(files, str) else list(files or [])
            paths = [os.path.join(folder, f) for f in files]
            if paths and all(os.path.isfile(p) for p in paths):
                return Art(name, h, paths, entry.get("fps") or doc.get("fps") or 6, folder)
    return None


def names(env=None):
    out = {}
    for folder in folders(env):
        doc = _manifest(folder) or {"art": {}}
        for name, entry in doc["art"].items():
            if isinstance(entry, dict):
                out.setdefault(name, sorted(int(h) for h in entry if str(h).isdigit()))
    return out
