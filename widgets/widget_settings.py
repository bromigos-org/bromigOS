"""A widget's own settings (docs/widgets.md, "A widget's settings"): what a panel declares
in its `settings` list, and the values in ~/.config/bromigos/widgets/<name>.toml.

A panel declares its fields:

    settings = [
        {"key": "place", "label": "Place", "kind": "text", "default": "", "hint": "A city or town"},
        {"key": "hosts", "label": "Hosts", "kind": "list", "default": [], "hint": "One per line"},
        {"key": "every", "label": "Every (s)", "kind": "number", "default": 60, "min": 10, "max": 3600},
        {"key": "units", "label": "Units", "kind": "choice", "default": "metric",
         "choices": [["metric", "°C and km/h"], ["imperial", "°F and mph"]]},
        {"key": "glow", "label": "Glow", "kind": "bool", "default": True},
        {"key": "account", "label": "GitHub", "kind": "secret-signin", "provider": "github"},
    ]

and reads them with `self.setting(key)` (panels.Panel), which takes, last wins: the
field's default, the panel's keys in layout.json, then <name>.toml. The file is read
again when it changes. A `secret-signin` field is never a value: it's a sign-in through
bromigos_account, whose tokens live in the keyring.

Settings › Widgets draws a form from the list, and `bromigos panels settings|set|unset`
read and write the file. Writes replace the file in one step and keep a symlink a
symlink, like layout.json.
"""
import json
import os

KINDS = ("text", "list", "number", "bool", "choice", "secret-signin")


def path(name):
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(cfg, "bromigos", "widgets", f"{name}.toml")


def fields(schema):
    """The well-formed fields of a panel's `settings`: dicts with a key and a known kind."""
    out = []
    for f in schema or []:
        if isinstance(f, dict) and f.get("key") and f.get("kind", "text") in KINDS:
            out.append(dict(f, kind=f.get("kind", "text"), label=f.get("label") or f["key"]))
    return out


def read_file(name):
    try:
        import tomllib
        with open(path(name), "rb") as f:
            d = tomllib.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def values(name, schema, layout=None, stored=None):
    """{key: value} for every value field: its default, then layout.json's key, then the
    file's (stored, when already read)."""
    stored = read_file(name) if stored is None else stored
    out = {}
    for f in fields(schema):
        if f["kind"] == "secret-signin":
            continue
        k = f["key"]
        v = f.get("default", [] if f["kind"] == "list" else "" if f["kind"] in ("text", "choice") else None)
        if layout and k in layout:
            v = layout[k]
        if k in stored:
            v = stored[k]
        out[k] = v
    return out


def parse(field, raw):
    """A value for a field from what the user typed (str, or a list for a list field).
    Raises ValueError with a sentence when it doesn't fit."""
    kind = field.get("kind", "text")
    label = field.get("label") or field["key"]
    if kind == "text":
        v = str(raw if not isinstance(raw, list) else " ".join(raw)).strip()
        if "\n" in v or len(v) > 500:
            raise ValueError(f"{label}: one line, up to 500 characters")
        return v
    if kind == "list":
        items = raw if isinstance(raw, list) else str(raw).replace(",", "\n").splitlines()
        return [str(x).strip() for x in items if str(x).strip()]
    if kind == "number":
        try:
            v = float(raw[0] if isinstance(raw, list) else raw)
        except (TypeError, ValueError, IndexError):
            raise ValueError(f"{label}: a number")
        lo, hi = field.get("min"), field.get("max")
        if lo is not None and v < lo or hi is not None and v > hi:
            raise ValueError(f"{label}: from {lo} to {hi}")
        return int(v) if v == int(v) and not isinstance(field.get("default"), float) else v
    if kind == "bool":
        s = str(raw[0] if isinstance(raw, list) else raw).strip().lower()
        if s in ("1", "true", "on", "yes"):
            return True
        if s in ("0", "false", "off", "no"):
            return False
        raise ValueError(f"{label}: on or off")
    if kind == "choice":
        s = str(raw[0] if isinstance(raw, list) else raw).strip()
        allowed = [c[0] if isinstance(c, (list, tuple)) else c for c in field.get("choices") or []]
        if s not in allowed:
            raise ValueError(f"{label}: one of {', '.join(map(str, allowed))}")
        return s
    raise ValueError(f"{label}: a sign-in, not a value (use the form's Sign in)")


def _toml(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def dump(d, header=""):
    lines = [f"# {line}" for line in header.splitlines()] if header else []
    for k in sorted(d):
        if isinstance(d[k], dict):
            continue
        key = k if k.replace("_", "").replace("-", "").isalnum() else json.dumps(k)
        lines.append(f"{key} = {_toml(d[k])}")
    return "\n".join(lines) + "\n"


def write(name, d, title=None):
    """The whole file in one step; a symlink stays a symlink (its target is replaced, keeping
    its mode). An empty d removes the file (a link's target is emptied instead)."""
    p = path(name)
    target = os.path.realpath(p)
    if not d and not os.path.islink(p):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
        return p
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".bromigos.tmp"
    with open(tmp, "w") as f:
        f.write(dump(d, f"{title or name}'s settings (Settings › Widgets; bromigos panels set {name} KEY VALUE)"))
    try:
        os.chmod(tmp, os.stat(target).st_mode & 0o7777)
    except FileNotFoundError:
        pass
    os.replace(tmp, target)
    return p


def set_value(name, schema, key, raw, title=None):
    """Writes one field's value (typed and checked) into the file; returns every value."""
    field = next((f for f in fields(schema) if f["key"] == key), None)
    if field is None:
        raise KeyError(key)
    stored = read_file(name)
    stored[key] = parse(field, raw)
    write(name, stored, title)
    return values(name, schema, stored=stored)


def unset(name, key, title=None):
    stored = read_file(name)
    stored.pop(key, None)
    write(name, stored, title)
    return stored


class Reader:
    """A panel's values, read again when the file changes (a stat per call, no more)."""

    def __init__(self, name, schema, layout=None):
        self.name, self.schema, self.layout = name, schema, layout or {}
        self._mtime, self._vals = None, None

    def get(self):
        try:
            m = os.stat(path(self.name)).st_mtime_ns
        except OSError:
            m = 0
        if m != self._mtime or self._vals is None:
            self._mtime = m
            self._vals = values(self.name, self.schema, self.layout)
        return self._vals
