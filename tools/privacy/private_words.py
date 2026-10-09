"""The private words the repository's checks look for, without the repository spelling them.

The tests, the screenshot renderer and the release notes' guard all refuse a few names: the
operator's lab, its machines, and internal projects that aren't bromigOS. This public
repository must not carry those names, even in a deny list. So the checks get them two ways:

- From the private overlay, at run time. That is the operator's decrypted
  `~/.config/bromigos/private/config.json` (or `$BROMIGOS_PRIVATE_CONFIG`). Its lab name
  (`homelab.name`), its machines (`homelab.constellation`) and its host names (the
  `endpoints` and `lan` values) are held in memory only, never printed or written. Without an
  overlay, as in CI or on another machine, there are none and those checks are skipped.
- As salted SHA-256 hashes of single words (HASHED), for names the overlay doesn't hold.
  Text is split into words, and each word is hashed and looked up.

A finding names its reason ("the lab's name"), never the matched text.

    import private_words as P
    words = P.Finder()
    words.reasons("some text")      # ["an internal project's name", ...] or []
    words.search("some text")       # the first reason, or None
"""
import hashlib
import json
import os
import re
from urllib.parse import urlsplit

SALT = "bromigos:private-words:1:"

# sha256(SALT + the lower-case word) -> why it's private
HASHED = {
    "0b845031ede26b8cebb9487c7e34a9b5b72d878027b6e905c21f89ebc747619b": "an internal project's name",
    "91fdc38441616dcc060f1fc1b2f4735aa07278e56336800f7ab8f0972ff768a3": "a private roster's name",
}

_WORD = re.compile(r"[a-z0-9]+")
_HOSTNAME = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")
_IP = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")


def digest(word):
    return hashlib.sha256((SALT + word.lower()).encode()).hexdigest()


def overlay_path():
    """Where bromigOS reads the overlay (lib/bromigos_private.py)."""
    return os.environ.get("BROMIGOS_PRIVATE_CONFIG") or os.path.expanduser("~/.config/bromigos/private/config.json")


def overlay():
    """The overlay as a dict, or {} when there is none."""
    try:
        with open(overlay_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def lab_name_pattern(data=None):
    """A regex source for the lab's name, with an optional space, _ or - between any two of its
    letters (it is written several ways), or None without an overlay."""
    name = ((data if data is not None else overlay()).get("homelab") or {}).get("name") or ""
    chars = [c for c in name.lower() if c.isalnum()]
    if len(chars) < 3:
        return None
    return "[ _-]?".join(re.escape(c) for c in chars)


def overlay_terms(data=None):
    """[(compiled regex, why)]: the lab's name, its machines and its host names."""
    data = data if data is not None else overlay()
    out = []
    lab = lab_name_pattern(data)
    if lab:
        out.append((re.compile(lab, re.I), "the lab's name"))
    con = (data.get("homelab") or {}).get("constellation") or {}
    nodes = [con.get("hub")] + list(con.get("ai") or []) + [
        p.get("node") for p in con.get("positions") or [] if isinstance(p, dict)]
    hosts = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k != "label":
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            h = (urlsplit(o).hostname or "") if "://" in o else o.strip().lower()
            if h and _HOSTNAME.fullmatch(h) and not _IP.fullmatch(h):
                hosts.add(h)
    walk(data.get("endpoints"))
    walk(data.get("lan"))
    for n in sorted({n.strip().lower() for n in nodes if isinstance(n, str) and len(n.strip()) >= 3}):
        if n.isalpha():
            continue        # a plain word is everyday English too ("relay"); a host name isn't
        out.append((re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", re.I), "a lab machine's name"))
    for h in sorted(hosts):
        out.append((re.compile(r"(?<![\w-])" + re.escape(h) + r"(?![\w-])", re.I), "a LAN host name"))
    return out


def hashed_hits(text):
    """The reasons for each word of `text` whose hash is in HASHED."""
    return [HASHED[d] for d in (digest(w) for w in _WORD.findall(text.lower())) if d in HASHED]


class HashedWords:
    """HASHED as a regex-like rule: finditer(), search() and sub(), for lists of (label, regex) rules."""

    def __init__(self, why=None):
        self.why = why      # only the words with this reason, or all of them

    def _hit(self, word):
        why = HASHED.get(digest(word))
        return why is not None and (self.why is None or why == self.why)

    def finditer(self, text):
        return (m for m in re.finditer(r"[A-Za-z0-9]+", text) if self._hit(m.group()))

    def search(self, text):
        return next(self.finditer(text), None)

    def sub(self, repl, text):
        return re.sub(r"[A-Za-z0-9]+", lambda m: repl if self._hit(m.group()) else m.group(), text)


class Finder:
    """Every private word: the hashed ones always, the overlay's when this machine has one."""

    def __init__(self, data=None):
        self.terms = overlay_terms(data)

    @property
    def have_overlay(self):
        return bool(self.terms)

    def reasons(self, text):
        return hashed_hits(text) + [why for rx, why in self.terms for _ in rx.finditer(text)]

    def search(self, text):
        r = self.reasons(text)
        return r[0] if r else None
