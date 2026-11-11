"""Signing in to the board with no account system (docs/board.md, "Signing in").

A one-time code, printed at the server by root (`sudo bromigos server board code`), becomes a
session: a random 256-bit token in a cookie, kept on the server only as its SHA-256. A code is
good for ten minutes and one use. A session lasts 30 days, names the browser it was made in, and
ends when its file is deleted (`bromigos server board sessions --end ID`).

Files, in /var/lib/bromigos-board (the service's own, 0700):
  codes/<sha256 of the code>.json      {made_at, expires_at}; used up by deleting it
  sessions/<id>.json                    {id, hash, browser, created_at, expires_at, last_seen_at, via}
"""
import collections
import contextlib
import hashlib
import hmac
import os
import pwd
import re
import secrets
import threading
import time

from . import paths

CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no I, O, 0 or 1: nothing to misread
CODE_LEN = 8                                          # 40 bits, shown ABCD-EFGH
CODE_MS = 10 * 60_000
SESSION_MS = 30 * 24 * 3600_000
SEEN_EVERY_MS = 10 * 60_000                           # how often last_seen_at is written again
COOKIE = "__Host-bromigos-board"                      # __Host-: Secure, Path=/, no Domain
SESSION_ID = re.compile(r"^[0-9a-f]{16}$")
# tries at a code: per source address a minute, and in all over ten minutes. 20 wrong guesses in
# ten minutes against 32^8 codes is a 1 in 55 billion chance.
TRIES_PER_SOURCE = (5, 60.0)
TRIES_IN_ALL = (20, 600.0)


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _owner():
    """The service's user, so it can read what root writes; None in a stand-in or without it."""
    if paths.root() != "/" or os.geteuid() != 0:
        return None
    try:
        pw = pwd.getpwnam(paths.USER)
        return pw.pw_uid, pw.pw_gid
    except KeyError:
        return None


def _dir(path):
    path = paths.at(path)
    if not os.path.isdir(path):
        os.makedirs(path, mode=0o700, exist_ok=True)
        owner = _owner()
        if owner:
            os.chown(path, *owner)
    return path


def _save(path, doc):
    paths.write_json(path, doc, mode=0o600)
    owner = _owner()
    if owner:
        os.chown(path, *owner)


def normalise_code(text):
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def show_code(code):
    return f"{code[:4]}-{code[4:]}"


# ---------------------------------------------------------------- codes
def new_code(now=None):
    """(code as shown, expires_at): a fresh one-time code. Root runs this."""
    now = paths.now_ms() if now is None else now
    prune(now)
    code = "".join(secrets.choice(CODE_LETTERS) for _ in range(CODE_LEN))
    exp = now + CODE_MS
    _save(os.path.join(_dir(paths.CODES), _sha(code) + ".json"), {"made_at": now, "expires_at": exp})
    return show_code(code), exp


def use_code(text, now=None):
    """True once for a right code inside its ten minutes; "expired" for a right one that's late
    (it's gone after that too); False for anything else, a code used already included."""
    now = paths.now_ms() if now is None else now
    code = normalise_code(text)
    if len(code) != CODE_LEN or any(c not in CODE_LETTERS for c in code):
        return False
    path = os.path.join(paths.at(paths.CODES), _sha(code) + ".json")
    doc = paths.read_json(path)
    try:
        os.unlink(path)               # one use: whoever deletes it first has it
    except FileNotFoundError:
        return False
    if isinstance(doc, dict) and isinstance(doc.get("expires_at"), int) and now < doc["expires_at"]:
        return True
    return "expired"


def codes_waiting(now=None):
    now = paths.now_ms() if now is None else now
    out = []
    with contextlib.suppress(OSError):
        for name in os.listdir(paths.at(paths.CODES)):
            doc = paths.read_json(os.path.join(paths.at(paths.CODES), name))
            if isinstance(doc, dict) and doc.get("expires_at", 0) > now:
                out.append(doc["expires_at"])
    return sorted(out)


def end_codes():
    """Every code waiting is used up (too many wrong tries)."""
    with contextlib.suppress(OSError):
        for name in os.listdir(paths.at(paths.CODES)):
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(paths.at(paths.CODES), name))


# ---------------------------------------------------------------- sessions
def browser_name(user_agent):
    """"Firefox on Linux": enough to tell one's own browsers apart in the list."""
    ua = str(user_agent or "")
    name = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                ("Safari/", "Safari"), ("curl/", "curl")) if k in ua), "A browser")
    system = next((n for k, n in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
                                  ("Mac OS X", "a Mac"), ("CrOS", "ChromeOS"), ("Linux", "Linux")) if k in ua), "")
    return f"{name} on {system}" if system else name


def new_session(user_agent="", via="code", now=None):
    """(cookie value, session record)."""
    now = paths.now_ms() if now is None else now
    sid, token = secrets.token_hex(8), secrets.token_urlsafe(32)
    rec = {"id": sid, "hash": _sha(token), "browser": browser_name(user_agent),
           "via": via, "created_at": now, "expires_at": now + SESSION_MS, "last_seen_at": now}
    _save(os.path.join(_dir(paths.SESSIONS), sid + ".json"), rec)
    return f"{sid}.{token}", rec


def session_for(cookie, now=None):
    """The session a cookie names, or None (no cookie, a wrong token, ended or out of date)."""
    now = paths.now_ms() if now is None else now
    sid, _, token = str(cookie or "").partition(".")
    if not SESSION_ID.match(sid) or not token:
        return None
    path = os.path.join(paths.at(paths.SESSIONS), sid + ".json")
    rec = paths.read_json(path)
    if not isinstance(rec, dict) or not hmac.compare_digest(str(rec.get("hash", "")), _sha(token)):
        return None
    if now >= rec.get("expires_at", 0):
        with contextlib.suppress(OSError):
            os.unlink(path)
        return None
    if now - rec.get("last_seen_at", 0) > SEEN_EVERY_MS:
        rec["last_seen_at"] = now
        with contextlib.suppress(OSError):
            if os.path.exists(path):          # not brought back after an end
                _save(path, rec)
    return rec


def public(rec):
    """A session as the lists show it: never its hash."""
    return {k: rec.get(k) for k in ("id", "browser", "via", "created_at", "expires_at", "last_seen_at")}


def sessions(now=None):
    now = paths.now_ms() if now is None else now
    out = []
    with contextlib.suppress(OSError):
        for name in sorted(os.listdir(paths.at(paths.SESSIONS))):
            rec = paths.read_json(os.path.join(paths.at(paths.SESSIONS), name))
            if isinstance(rec, dict) and SESSION_ID.match(str(rec.get("id"))) and rec.get("expires_at", 0) > now:
                out.append(public(rec))
    return sorted(out, key=lambda r: -r.get("last_seen_at", 0))


def end_session(sid):
    """True when a session with that id was there and is gone now."""
    if not SESSION_ID.match(str(sid)):
        return False
    try:
        os.unlink(os.path.join(paths.at(paths.SESSIONS), sid + ".json"))
        return True
    except FileNotFoundError:
        return False


def end_all():
    n = 0
    for rec in sessions():
        n += end_session(rec["id"])
    return n


def prune(now=None):
    """Out-of-date codes and sessions, deleted."""
    now = paths.now_ms() if now is None else now
    for d in (paths.CODES, paths.SESSIONS):
        with contextlib.suppress(OSError):
            for name in os.listdir(paths.at(d)):
                p = os.path.join(paths.at(d), name)
                doc = paths.read_json(p)
                if not isinstance(doc, dict) or doc.get("expires_at", 0) <= now:
                    with contextlib.suppress(OSError):
                        os.unlink(p)


# ---------------------------------------------------------------- tries
class Tries:
    """Wrong codes, counted per source address and in all. Kept in the service's memory: only
    the browser's side of the socket can make tries, and nothing it sends restarts the service."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.by_source = collections.defaultdict(collections.deque)
        self.all = collections.deque()
        self.lock = threading.Lock()

    @staticmethod
    def _trim(q, window, now):
        while q and now - q[0] > window:
            q.popleft()

    def blocked(self, src):
        with self.lock:
            now = self.clock()
            q = self.by_source[src]
            self._trim(q, TRIES_PER_SOURCE[1], now)
            self._trim(self.all, TRIES_IN_ALL[1], now)
            if len(q) >= TRIES_PER_SOURCE[0]:
                return "Too many wrong codes from this device. Wait a minute, then try again."
            if len(self.all) >= TRIES_IN_ALL[0]:
                return ("Too many wrong codes. Every code waiting was cancelled: wait ten minutes, then get a new one "
                        "with sudo bromigos server board code.")
            return None

    def wrong(self, src):
        with self.lock:
            now = self.clock()
            self.by_source[src].append(now)
            self.all.append(now)
            self._trim(self.all, TRIES_IN_ALL[1], now)
            too_many = len(self.all) >= TRIES_IN_ALL[0]
        if too_many:
            end_codes()
