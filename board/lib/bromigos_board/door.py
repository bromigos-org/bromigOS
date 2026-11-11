"""The door: what the board shows before anyone signs in (docs/board.md, "The door").

The server's name and the household's app tiles: an icon, the job, the app's name and a link that
opens it; the world the page wears, and which ways to sign in it offers. Nothing else: no state, no readings, no versions, no addresses beyond the app links.
Every key is copied one by one from the allow-lists below, so a new field in the apps list never
reaches the door by itself; the tests check each key.
"""
import re
import urllib.parse

from . import SCHEMA, paths

DOOR_KEYS = ("schema", "lab", "server", "world", "door", "tiles", "signin")
TILE_KEYS = ("id", "job", "app", "holo", "group", "open")
OPEN_KEYS = ("url",)
# the ways in this server offers now: the console code. Approving on the phone and signing in
# with a Bromigos account come later (docs/board.md, "Not built yet")
SIGNIN = {"code": True, "phone": False, "account": False}
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
TEXT_MAX = 40


def _text(value):
    """A short name, or "": a job, an app's name."""
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())
    return value[:TEXT_MAX]


def app_url(value):
    """An app's link, when it's a plain web address on this network: http or https, a .local
    name, no user or password in it. Anything else is left out."""
    if not isinstance(value, str) or len(value) > 200:
        return ""
    try:
        u = urllib.parse.urlsplit(value)
        port = u.port
    except ValueError:
        return ""
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or u.username or u.password or "@" in u.netloc:
        return ""
    if not host.endswith(".local") or not all(LABEL.match(x) for x in host.split(".")):
        return ""
    if u.query or u.fragment or (u.path and not re.fullmatch(r"(/[A-Za-z0-9._~-]*)*/?", u.path)):
        return ""
    return urllib.parse.urlunsplit((u.scheme, host + (f":{port}" if port else ""), u.path, "", ""))


def tile(entry):
    """One door tile from one apps-list entry (DESIGN's tile contract), or None."""
    if not isinstance(entry, dict) or entry.get("installed") is False or entry.get("household") is False:
        return None
    opened = entry.get("open") if isinstance(entry.get("open"), dict) else {}
    url = app_url(opened.get("url") or entry.get("url"))
    tid = entry.get("id")
    if not url or not isinstance(tid, str) or not ID.match(tid):
        return None
    t = {"id": tid, "job": _text(entry.get("job")) or _text(entry.get("name")), "app": _text(entry.get("app")),
         "holo": entry["holo"] if isinstance(entry.get("holo"), str) and ID.match(entry["holo"]) else "",
         "group": entry["group"] if isinstance(entry.get("group"), str) and ID.match(entry["group"]) else "",
         "open": {"url": url}}
    return {k: t[k] for k in TILE_KEYS}


def entries(snapshot):
    """The apps the door may list: the apps list when it answered, else the snapshot's fallback
    (the catalogue's web apps that are set up)."""
    apps = (snapshot or {}).get("apps")
    if isinstance(apps, dict) and isinstance(apps.get("apps"), list):
        return apps["apps"]
    if isinstance(apps, list):
        return apps
    fb = (snapshot or {}).get("door_fallback")
    return fb if isinstance(fb, list) else []


def door(snapshot):
    """The door's JSON, built key by key."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    host = snapshot.get("host")
    host = host if isinstance(host, str) and HOST.match(host) else paths.hostname()
    settings = snapshot.get("settings") if isinstance(snapshot.get("settings"), dict) else {}
    on = settings.get("door", True) is not False
    world = settings.get("world") if settings.get("world") in paths.WORLDS else "wick"
    tiles, seen = [], set()
    for e in entries(snapshot) if on else []:
        t = tile(e)
        if t and t["id"] not in seen:
            seen.add(t["id"])
            tiles.append(t)
    doc = {"schema": SCHEMA, "lab": lab(host), "server": {"name": host}, "world": world, "door": on, "tiles": tiles,
           "signin": dict(SIGNIN)}
    return {k: doc[k] for k in DOOR_KEYS}


def lab(host):
    """The lab this page belongs to. A single server is its own lab home (DESIGN §8, decision
    6): its name and address are the server's until labs of several servers land."""
    return {"name": host, "address": f"https://{host}.local"}
