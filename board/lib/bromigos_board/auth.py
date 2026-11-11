"""Signing in to the board with no account system (docs/board.md, "Signing in").

A one-time code, printed at the server (`sudo bromigos server board code`), becomes a session: a
random 256-bit token in a cookie, kept on the server only as its SHA-256. A code is good for ten
minutes and one use. A session lasts 30 days, names the browser it was made in, and ends when its
file is deleted (`bromigos server board sessions --end ID`).

Files, in /var/lib/bromigos-board (the board's user's own, 0700):
  codes/<sha256 of the code>.json      {made_at, expires_at}; used up by deleting it
  sessions/<id>.json                    {id, hash, browser, created_at, expires_at, via}; the file's
                                        own time is when the session was last used

Only the board's user works in these folders. `bromigos server board code` and `sessions` are
run by root, and become that user first (cli.become_board_user): root never follows a path the
board's user controls. Every file here is reached through a descriptor of its folder, opened
without following a link, so a link planted where `codes` or `sessions` should be is refused.
"""
import collections
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

from . import paths

CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no I, O, 0 or 1: nothing to misread
CODE_LEN = 8                                          # 40 bits, shown ABCD-EFGH
CODE_MS = 10 * 60_000
SESSION_MS = 30 * 24 * 3600_000
SEEN_EVERY_MS = 10 * 60_000                           # how often a session's last use is noted again
COOKIE = "__Host-bromigos-board"                      # __Host-: Secure, Path=/, no Domain
SESSION_ID = re.compile(r"[0-9a-f]{16}\Z")
RECORD = re.compile(r"[0-9a-f]{16,64}\.json\Z")       # a session's or a code's file; nothing else is read
STALE_TEMP_S = 60                                     # a half-written file older than this is swept
# wrong codes. Each address may send 5 a minute. Besides that, wrong codes are answered at most
# one every 200 ms, whoever sends them: a wrong answer waits its turn, a second at most. A right
# code is never held up or refused because of someone else's wrong ones. (A code is 40 bits and
# lives ten minutes: at 5 guesses a second the chance of hitting one is about 3 in a billion.)
TRIES_PER_SOURCE = (5, 60.0)
WRONG_EVERY_S = 0.2
WRONG_WAIT_MAX_S = 1.0


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


@contextlib.contextmanager
def folder(path, make=True):
    """A descriptor of one of the board's own folders. A link in its place is refused."""
    path = paths.at(path)
    if make and not os.path.lexists(path):
        os.makedirs(path, mode=0o700, exist_ok=True)
    dfd = paths.open_folder(path)
    try:
        yield dfd
    finally:
        os.close(dfd)


def _read(dfd, name):
    """The record `name` in the folder: a plain file, read without following a link; else None."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dfd)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as f:
            doc = json.loads(f.read(65536))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _drop(dfd, name):
    """True when `name` was there and this call removed it: of two that try, one wins."""
    try:
        os.unlink(name, dir_fd=dfd)
        return True
    except OSError:
        return False


def _records(dfd):
    with contextlib.suppress(OSError):
        return sorted(n for n in os.listdir(dfd) if RECORD.match(n))
    return []


def normalise_code(text):
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def show_code(code):
    return f"{code[:4]}-{code[4:]}"


def fresh_code():
    return "".join(secrets.choice(CODE_LETTERS) for _ in range(CODE_LEN))


def valid_code(text):
    """The code as its eight letters, or None when it can't be one."""
    code = normalise_code(text)
    return code if len(code) == CODE_LEN and all(c in CODE_LETTERS for c in code) else None


# ---------------------------------------------------------------- codes
def new_code(now=None, code=None):
    """(code as shown, expires_at): a fresh one-time code, noted in the board's folder. The
    board's user runs this (root, after it stepped down)."""
    now = paths.now_ms() if now is None else now
    prune(now)
    code = code or fresh_code()
    exp = now + CODE_MS
    with folder(paths.CODES) as dfd:
        paths.write_at(dfd, _sha(code) + ".json", paths.dump({"made_at": now, "expires_at": exp}), 0o600)
    return show_code(code), exp


def use_code(text, now=None):
    """True once for a right code inside its ten minutes; "expired" for a right one that's late
    (it's gone after that too); False for anything else, a code used already included."""
    now = paths.now_ms() if now is None else now
    code = valid_code(text)
    if not code:
        return False
    try:
        with folder(paths.CODES, make=False) as dfd:
            name = _sha(code) + ".json"
            doc = _read(dfd, name)
            if not _drop(dfd, name):          # one use: whoever deletes it first has it
                return False
    except OSError:
        return False
    if isinstance(doc, dict) and isinstance(doc.get("expires_at"), int) and now < doc["expires_at"]:
        return True
    return "expired"


def codes_waiting(now=None):
    now = paths.now_ms() if now is None else now
    out = []
    with contextlib.suppress(OSError):
        with folder(paths.CODES, make=False) as dfd:
            for name in _records(dfd):
                doc = _read(dfd, name)
                if doc and isinstance(doc.get("expires_at"), int) and doc["expires_at"] > now:
                    out.append(doc["expires_at"])
    return sorted(out)


# ---------------------------------------------------------------- sessions
def browser_name(user_agent):
    """"Firefox on Linux": enough to tell one's own browsers apart in the list."""
    ua = str(user_agent or "")
    name = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                ("Safari/", "Safari"), ("curl/", "curl")) if k in ua), "A browser")
    system = next((n for k, n in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
                                  ("Mac OS X", "a Mac"), ("CrOS", "ChromeOS"), ("Linux", "Linux")) if k in ua), "")
    return f"{name} on {system}" if system else name


def _seen(dfd, name, now):
    """Note when the session was last used, as its file's own time. It never makes the file: one
    that was ended in the meantime stays ended (FileNotFoundError)."""
    os.utime(name, (now / 1000, now / 1000), dir_fd=dfd, follow_symlinks=False)


def new_session(user_agent="", via="code", now=None):
    """(cookie value, session record)."""
    now = paths.now_ms() if now is None else now
    sid, token = secrets.token_hex(8), secrets.token_urlsafe(32)
    rec = {"id": sid, "hash": _sha(token), "browser": browser_name(user_agent),
           "via": via, "created_at": now, "expires_at": now + SESSION_MS}
    with folder(paths.SESSIONS) as dfd:
        paths.write_at(dfd, sid + ".json", paths.dump(rec), 0o600, replace=False)
        _seen(dfd, sid + ".json", now)
    return f"{sid}.{token}", dict(rec, last_seen_at=now)


def _last_seen(dfd, name, rec):
    try:
        return int(os.stat(name, dir_fd=dfd, follow_symlinks=False).st_mtime * 1000)
    except OSError:
        return rec.get("created_at", 0)


def session_for(cookie, now=None):
    """The session a cookie names, or None (no cookie, a wrong token, ended or out of date)."""
    now = paths.now_ms() if now is None else now
    sid, _, token = str(cookie or "").partition(".")
    if not SESSION_ID.match(sid) or not token:
        return None
    name = sid + ".json"
    try:
        with folder(paths.SESSIONS, make=False) as dfd:
            rec = _read(dfd, name)
            if not rec or not hmac.compare_digest(str(rec.get("hash", "")), _sha(token)):
                return None
            if now >= rec.get("expires_at", 0):
                _drop(dfd, name)
                return None
            seen = _last_seen(dfd, name, rec)
            if now - seen > SEEN_EVERY_MS:
                _seen(dfd, name, now)             # raises when it was ended just now: then it is ended
                seen = now
    except OSError:
        return None
    return dict(rec, last_seen_at=seen)


def public(rec):
    """A session as the lists show it: never its hash."""
    return {k: rec.get(k) for k in ("id", "browser", "via", "created_at", "expires_at", "last_seen_at")}


def sessions(now=None):
    now = paths.now_ms() if now is None else now
    out = []
    with contextlib.suppress(OSError):
        with folder(paths.SESSIONS, make=False) as dfd:
            for name in _records(dfd):
                rec = _read(dfd, name)
                if rec and SESSION_ID.match(str(rec.get("id"))) and rec["id"] + ".json" == name \
                        and rec.get("expires_at", 0) > now:
                    out.append(public(dict(rec, last_seen_at=_last_seen(dfd, name, rec))))
    return sorted(out, key=lambda r: -r.get("last_seen_at", 0))


def end_session(sid):
    """True when a session with that id was there and is gone now."""
    if not SESSION_ID.match(str(sid)):
        return False
    try:
        with folder(paths.SESSIONS, make=False) as dfd:
            return _drop(dfd, sid + ".json")
    except OSError:
        return False


def end_all():
    n = 0
    for rec in sessions():
        n += end_session(rec["id"])
    return n


def prune(now=None):
    """Out-of-date codes and sessions, deleted; and files left half-written long ago. Only the
    records' own names are looked at: nothing else in the folder is read or removed."""
    now = paths.now_ms() if now is None else now
    for d in (paths.CODES, paths.SESSIONS):
        with contextlib.suppress(OSError):
            with folder(d, make=False) as dfd:
                for name in os.listdir(dfd):
                    if RECORD.match(name):
                        doc = _read(dfd, name)
                        if not doc or not isinstance(doc.get("expires_at"), int) or doc["expires_at"] <= now:
                            _drop(dfd, name)
                    elif name.startswith(".") and name.endswith(".tmp"):
                        with contextlib.suppress(OSError):
                            if time.time() - os.stat(name, dir_fd=dfd, follow_symlinks=False).st_mtime > STALE_TEMP_S:
                                _drop(dfd, name)


# ---------------------------------------------------------------- tries
class Tries:
    """Wrong codes: counted for each source address, and slowed for everyone.

    blocked(src) says when that address has sent too many itself. wrong(src) counts one and gives
    how long its answer waits, so wrong answers leave 200 ms apart, never more than a second
    late. Nothing here refuses or delays a right code that someone else's wrong ones came before.
    Kept in the service's memory; an address's entry is dropped once its tries are a minute old."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.by_source = {}
        self.next_answer = None
        self.swept = None
        self.lock = threading.Lock()

    def _sweep(self, now):
        """Drop the tries older than a minute, and the addresses left with none."""
        if self.swept is not None and now - self.swept < TRIES_PER_SOURCE[1] / 4 and len(self.by_source) < 256:
            return
        self.swept = now
        for src in list(self.by_source):
            q = self.by_source[src]
            while q and now - q[0] > TRIES_PER_SOURCE[1]:
                q.popleft()
            if not q:
                del self.by_source[src]

    def blocked(self, src):
        with self.lock:
            now = self.clock()
            self._sweep(now)
            q = self.by_source.get(src)
            while q and now - q[0] > TRIES_PER_SOURCE[1]:
                q.popleft()
            if q is not None and len(q) >= TRIES_PER_SOURCE[0]:
                return "Too many wrong codes from this device. Wait a minute, then try again."
            return None

    def wrong(self, src):
        """Count a wrong code from src. Returns the seconds its answer waits."""
        with self.lock:
            now = self.clock()
            self._sweep(now)
            self.by_source.setdefault(src, collections.deque()).append(now)
            at = now if self.next_answer is None else max(now, self.next_answer)
            wait = min(at - now, WRONG_WAIT_MAX_S)
            self.next_answer = now + wait + WRONG_EVERY_S
            return wait
