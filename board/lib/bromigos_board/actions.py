"""Actions from the board's page (docs/board.md, "Actions"): a fixed verb on a catalogue app, run
as root by a helper of root's own, never as free text.

The API runs as the board's user and has no rights on systemd or anywhere else. Two folders
carry a request across to root and its answer back, each written by one side only:

  /run/bromigos-board/requests   the board's user's. The API puts <id>.json here, whole.
  /run/bromigos-board/results    root's (group bromigos-board reads). The helper puts <id>.json
                                 here: {schema, ok, job, words} or {schema, ok: false, code, words}.

1. The API checks the request's shape and writes it (ask). It starts nothing: it can't.
2. bromigos-board-act.path sees the folder isn't empty and starts bromigos-board-act.service: as
   root, `bromigos-board act`, in a sandbox that can write those two folders, the code stores and
   the activity records, and nothing else.
3. The helper takes every request out of the folder (drain), one at a time. It reads each once,
   through a descriptor and never a link, deletes it, and checks it again: the board's user wrote
   it, it's recent, the verb is one of VERBS, the app is an id in the provisioning catalogue, and
   root's [board] actions in /etc/bromigos/server.toml lists the verb. It builds the command
   itself, from those checked words only:

     bromigos-activity run --kind KIND --title WORDS --subject app:ID:NAME --lock apps --via board
       --device BROWSER --detach --json -- /usr/bin/bromigos lab apps VERB ID [--delete-data --yes]

4. It writes its answer in root's folder. The answer's words are fixed: nothing a request said is
   ever quoted in it. The API reads the answer back for the page. The job's record and its steps
   then come through the activity stream like any other job's.

Deleting an app's data needs a code from `sudo bromigos server board code`, typed again for it.
Root notes each code it makes in a folder only root can read (/var/lib/bromigos-board-root/codes),
besides the board's own record. The helper takes a code for a deletion only when both records are
there, and removes both: the board's user can't make such a code, and a code that signed a
browser in can't delete anything.
"""
import contextlib
import json
import os
import pwd
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time

from . import SCHEMA, auth, paths

REQUESTS = paths.RUN + "/requests"          # the board's user's: requests, waiting for root's helper
RESULTS = paths.RUN + "/results"            # root's: the helper's answers, for the board's group to read
ROOT_STATE = "/var/lib/bromigos-board-root"     # root's only (0700): what the board's user must not be able to write
ROOT_CODES = ROOT_STATE + "/codes"          # each code root made, as its SHA-256: {expires_at}
# (\Z, not $: an id is 16 hex digits and nothing after them, not even a newline)
REQUEST_ID = re.compile(r"[0-9a-f]{16}\Z")
REQUEST_FILE = re.compile(r"([0-9a-f]{16})\.json\Z")
APP_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
# the closed list: `bromigos lab apps`'s own verbs, each with its activity kind and title.
# Removing keeps the app's data; with delete_data it goes for good (`remove --delete-data --yes`),
# which needs a fresh console code in the request, checked by root (DESIGN §1: destructive
# actions ask for a fresh approval even inside a session)
VERBS = {
    "restart": ("app.restart", "Restarting {name}"),
    "add": ("app.install", "Adding {name}"),
    "remove": ("app.remove", "Removing {name}, keeping its data"),
}
DELETE_TITLE = "Removing {name} and deleting its data"
DELETE_DATA = "delete-data"             # its word in [board] actions
DEFAULT_ACTIONS = (*VERBS, DELETE_DATA)
REQUEST_MAX_AGE_MS = 60_000
REQUEST_MAX_BYTES = 4096
RESULT_WAIT_S = 10.0
RESULT_KEEP_S = 60.0                    # an answer older than this is swept by the helper
TEMP_KEEP_S = 60.0                      # so is a request left half-written
LINGER_S = 3.0                          # the helper waits this long for more requests before it ends
RUN_MAX_S = 300.0                       # and ends anyway after this long: the path unit starts it again if need be
# Every refusal's words, fixed: nothing a request said is ever quoted in an answer
REFUSALS = {
    "unknown-verb": "The board can't do that: it can restart, add and remove apps.",
    "unknown-app": "That isn't an app in the catalogue.",
    "bad-request": "The request isn't one the board makes.",
    "no-request": "There's no such request (it was used already, or never made).",
    "too-old": "The request is too old: ask again from the page.",
    "not-allowed": "This server doesn't let the board do that ([board] actions in /etc/bromigos/server.toml).",
    "needs-code": "Deleting an app's data needs a fresh code: run sudo bromigos server board code at the server, "
                  "and type it here. A code that signed a browser in doesn't count.",
    "job-failed": "The job didn't start. The server's log says why: journalctl -u bromigos-board-act.service",
}


class Refused(Exception):
    """A refusal: its code, and that code's own fixed words."""

    def __init__(self, code):
        super().__init__(REFUSALS[code])
        self.code, self.words = code, REFUSALS[code]


def check_shape(verb, app, delete_data=False, code=None):
    """What both sides check first: a verb on the list, an app id that is a plain word, and
    deleting data only with remove and a code."""
    if not isinstance(verb, str) or verb not in VERBS:
        raise Refused("unknown-verb")
    if not isinstance(app, str) or not APP_ID.match(app):
        raise Refused("unknown-app")
    if delete_data not in (True, False):
        raise Refused("bad-request")
    if delete_data and verb != "remove":
        raise Refused("unknown-verb")
    if delete_data and not (isinstance(code, str) and 0 < len(code) <= 32):
        raise Refused("needs-code")


def browser_words(text):
    """The browser's name as the job's device: plain letters only, short."""
    return re.sub(r"[^A-Za-z0-9 .-]", "", str(text or ""))[:40] or "a browser"


def _old(dfd, name, seconds):
    try:
        return time.time() - os.stat(name, dir_fd=dfd, follow_symlinks=False).st_mtime > seconds
    except OSError:
        return False


# ---------------------------------------------------------------- the API's side
def ask(verb, app, session, now=None, delete_data=False, code=None):
    """Write the request, whole, into the board's own folder; its id. bromigos-board-act.path
    sees it there. Nothing is started from here: the API has no right to start anything."""
    check_shape(verb, app, delete_data, code)
    now = paths.now_ms() if now is None else now
    rid = secrets.token_hex(8)
    doc = {"schema": SCHEMA, "id": rid, "verb": verb, "app": app, "at": now, "session": session.get("id"),
           "browser": session.get("browser"), "delete_data": bool(delete_data)}
    if delete_data:
        doc["code"] = code           # root checks it and uses it up; the request lives a few seconds
    dfd = paths.open_folder(paths.at(REQUESTS))
    try:
        # (never over a request that is there: an id is used once)
        paths.write_at(dfd, rid + ".json", paths.dump(doc), 0o640, replace=False)
    finally:
        os.close(dfd)
    return rid


def result(rid):
    """The helper's answer to request rid, from root's folder; None while there is none."""
    if not REQUEST_ID.match(str(rid)):
        return None
    doc = paths.read_json(os.path.join(paths.at(RESULTS), rid + ".json"))
    return doc if isinstance(doc, dict) else None


def wait(rid, timeout=RESULT_WAIT_S, sleep=time.sleep, poll=0.1):
    """The helper's answer, or None when it hasn't given one in time. The answer is left where
    it is: the folder is root's, and the helper sweeps it."""
    end = time.monotonic() + timeout
    while True:
        doc = result(rid)
        if doc is not None or time.monotonic() >= end:
            return doc
        sleep(poll)


# ---------------------------------------------------------------- root's side
def board_ids():
    """(uid, gid) of the board's user; in a stand-in root, this process's own (the tests' one
    user plays both parts). (None, None) when the server has no such user."""
    if paths.stand_in():
        return os.getuid(), None
    try:
        pw = pwd.getpwnam(paths.USER)
        return pw.pw_uid, pw.pw_gid
    except KeyError:
        return None, None


def board_uid():
    return board_ids()[0]


@contextlib.contextmanager
def root_folder(path, mode, gid=None):
    """A descriptor of one of root's own folders, made when it's missing (its parent is root's)."""
    path = paths.at(path)
    if not os.path.lexists(path):
        os.makedirs(path, mode=mode, exist_ok=True)
        fd = paths.open_folder(path)
        try:
            if gid is not None:
                os.fchown(fd, -1, gid)
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
    dfd = paths.open_folder(path)
    try:
        yield dfd
    finally:
        os.close(dfd)


def note_code(code, expires_at, now=None):
    """Root, as it makes a sign-in code and before it steps down: note the code in root's own
    folder too. Only a code noted here can ever approve a deletion."""
    now = paths.now_ms() if now is None else now
    code = auth.valid_code(code)
    if not code:
        raise ValueError("not a code")
    with root_folder(ROOT_CODES, 0o700) as dfd:
        for name in os.listdir(dfd):                        # the out-of-date ones go
            doc = auth._read(dfd, name) if auth.RECORD.match(name) else None
            if auth.RECORD.match(name) and (not doc or not isinstance(doc.get("expires_at"), int) or doc["expires_at"] <= now):
                auth._drop(dfd, name)
        paths.write_at(dfd, auth._sha(code) + ".json", paths.dump({"made_at": now, "expires_at": int(expires_at)}), 0o600)


def use_delete_code(text, now=None):
    """True once for a code that root made, that is inside its ten minutes, and that hasn't
    signed a browser in: its record is in root's folder and in the board's. Both are removed."""
    now = paths.now_ms() if now is None else now
    code = auth.valid_code(text)
    if not code:
        return False
    name = auth._sha(code) + ".json"
    try:
        with root_folder(ROOT_CODES, 0o700) as rfd:
            doc = auth._read(rfd, name)
            if not doc:
                return False                     # root never made it (or it was used): whatever the board's folder says
            if not auth._drop(rfd, name):
                return False                     # of two that try, one has it
            # the board's own record goes when the code signs a browser in: it must still be there
            try:
                with auth.folder(paths.CODES, make=False) as bfd:
                    there = auth._drop(bfd, name)
            except OSError:
                there = False
    except OSError:
        return False
    return bool(there and isinstance(doc.get("expires_at"), int) and now < doc["expires_at"])


def _remove(dfd, name):
    """Whatever is at `name` in the requests folder, gone: a file, a link (never followed), or a
    folder with all that is in it. A request that couldn't be removed would be read again at the
    helper's next look, and the next, for as long as it ran."""
    try:
        os.unlink(name, dir_fd=dfd)
    except FileNotFoundError:
        pass
    except (IsADirectoryError, PermissionError):
        # (unlink of a folder: EISDIR on Linux, EPERM elsewhere). rmtree opens through dir_fd and
        # never follows a link inside it
        shutil.rmtree(name, dir_fd=dfd, ignore_errors=True)
    except OSError:
        pass


def read_request(dfd, rid):
    """Request rid, read once and deleted. It must be a plain, small file that the board's user
    wrote: a link is never followed, and a FIFO never waited on."""
    name = rid + ".json"
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dfd)
    except FileNotFoundError:
        raise Refused("no-request") from None
    except OSError:
        _remove(dfd, name)
        raise Refused("bad-request") from None
    try:
        st = os.fstat(fd)
        uid = board_uid()
        if not stat.S_ISREG(st.st_mode) or st.st_size > REQUEST_MAX_BYTES or uid is None or st.st_uid != uid:
            raise Refused("bad-request")
        raw = os.read(fd, REQUEST_MAX_BYTES + 1)
    finally:
        os.close(fd)
        _remove(dfd, name)
    try:
        doc = json.loads(raw)
    except ValueError:
        raise Refused("bad-request") from None
    if not isinstance(doc, dict) or doc.get("id") != rid:
        raise Refused("bad-request")
    return doc


def allowed_verbs():
    """Root's [board] actions: the verbs the page may use on this server (all of them when left
    out; [] turns actions off)."""
    import tomllib
    try:
        with open(paths.at(paths.SERVER_TOML), "rb") as f:
            b = tomllib.load(f).get("board") or {}
    except (OSError, ValueError):
        b = {}
    v = b.get("actions", list(DEFAULT_ACTIONS)) if isinstance(b, dict) else list(DEFAULT_ACTIONS)
    return [x for x in v if x in DEFAULT_ACTIONS] if isinstance(v, list) else []


def offered():
    """What the page may ask for on this server, for the board's document (`actions`): root's
    [board] actions, and nothing while actions aren't set up (no requests folder). Root reads
    this as it gathers the readings; the page shows a control only for what is listed."""
    return allowed_verbs() if os.path.isdir(paths.at(REQUESTS)) else []


def catalogue():
    from bromigos_homelab import provcatalog
    return provcatalog.by_id()


def command(verb, app, name, browser, delete_data=False):
    """The job's argv, built here from checked words only. On a server every command is its
    whole path (paths.tool)."""
    kind, title = VERBS[verb]
    title = DELETE_TITLE if delete_data else title
    return [paths.tool("bromigos-activity"), "run", "--kind", kind, "--title", title.format(name=name),
            "--subject", f"app:{app}:{name}", "--lock", "apps", "--via", "board", "--device", browser_words(browser),
            "--detach", "--json", "--", paths.tool("bromigos"), "lab", "apps", verb, app] + (["--delete-data", "--yes"] if delete_data else [])


def decide(doc, now, run, cat, log):
    """A request that was read: checked again, and its job started. The answer."""
    verb, app, delete_data = doc.get("verb"), doc.get("app"), doc.get("delete_data", False)
    check_shape(verb, app, delete_data, doc.get("code"))
    if not isinstance(doc.get("at"), int) or isinstance(doc.get("at"), bool) or not 0 <= now - doc["at"] <= REQUEST_MAX_AGE_MS:
        raise Refused("too-old")
    allowed = allowed_verbs()
    if verb not in allowed or (delete_data and DELETE_DATA not in allowed):
        raise Refused("not-allowed")
    cat = catalogue() if cat is None else cat
    if app not in cat:
        raise Refused("unknown-app")
    if delete_data and not use_delete_code(doc.get("code"), now):
        raise Refused("needs-code")
    name = cat[app].get("job") or cat[app].get("name") or app
    argv = command(verb, app, name, doc.get("browser"), delete_data)
    run = run or (lambda a: subprocess.run(a, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL))
    try:
        r = run(argv)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"bromigos-board: the job's command didn't run: {e}")
        raise Refused("job-failed") from None
    if r.returncode != 0:
        log("bromigos-board: the job didn't start: " + ((r.stderr or r.stdout or "").strip().splitlines() or ["no word why"])[-1][:300])
        raise Refused("job-failed")
    try:
        job = json.loads(r.stdout).get("id")
    except (ValueError, AttributeError):
        job = None
    # the app's name here is the catalogue's own, root's: not the request's
    return {"schema": SCHEMA, "ok": True, "job": job if isinstance(job, str) else None,
            "words": (DELETE_TITLE if delete_data else VERBS[verb][1]).format(name=name) + "."}


def answer(rid, out):
    """The helper's answer, in root's folder, for the board's group to read."""
    with root_folder(RESULTS, 0o750, board_ids()[1]) as dfd:
        paths.write_at(dfd, rid + ".json", paths.dump(out), 0o640, board_ids()[1])


def act(rid, run=None, now=None, cat=None, log=None, dfd=None):
    """Root: take request `rid` out of the folder, check it again and start its job. The answer,
    also written in root's results folder for the API."""
    log = log or (lambda words: print(words, file=sys.stderr))
    now = paths.now_ms() if now is None else now
    if not REQUEST_ID.match(str(rid)):
        return {"schema": SCHEMA, "ok": False, "code": "bad-request", "words": REFUSALS["bad-request"]}
    own = dfd is None
    try:
        if own:
            dfd = paths.open_folder(paths.at(REQUESTS))
        try:
            out = decide(read_request(dfd, rid), now, run, cat, log)
        finally:
            if own:
                os.close(dfd)
    except Refused as e:
        out = {"schema": SCHEMA, "ok": False, "code": e.code, "words": e.words}
    except OSError as e:
        log(f"bromigos-board: request {rid}: {e}")
        out = {"schema": SCHEMA, "ok": False, "code": "bad-request", "words": REFUSALS["bad-request"]}
    log(f"bromigos-board: request {rid}: " + ("started " + str(out.get("job")) if out["ok"] else "refused (" + out["code"] + ")"))
    try:
        answer(rid, out)
    except OSError as e:
        log(f"bromigos-board: request {rid}: its answer couldn't be written: {e}")
    return out


def sweep_results(now=None):
    """Answers older than a minute, removed (the API read them long ago, or stopped waiting)."""
    with contextlib.suppress(OSError):
        with root_folder(RESULTS, 0o750, board_ids()[1]) as dfd:
            for name in os.listdir(dfd):
                if _old(dfd, name, RESULT_KEEP_S):
                    with contextlib.suppress(OSError):
                        os.unlink(name, dir_fd=dfd)


def drain(run=None, cat=None, linger=None, poll=0.1, sleep=time.sleep, clock=time.monotonic, log=None,
          run_max=RUN_MAX_S):
    """Root: take every request out of the folder, one at a time, until the folder has had none
    for `linger` seconds. Returns how many it handled.

    Each request is handled once: it is deleted as it is read. None is lost: one that arrives
    while this runs is seen on the next look, and one that arrives as this ends starts the helper
    again (bromigos-board-act.path looks at the folder when the service stops). Anything else in
    the folder is removed: a request left half-written a minute ago, a link, a folder."""
    log = log or (lambda words: print(words, file=sys.stderr))
    linger = LINGER_S if linger is None else linger
    handled, quiet_since = 0, clock()
    started = quiet_since
    dfd = paths.open_folder(paths.at(REQUESTS))
    try:
        while True:
            busy = False
            for name in sorted(os.listdir(dfd)):
                if clock() - started >= run_max:
                    return handled               # long enough: what's left starts the helper again
                m = REQUEST_FILE.match(name)
                if m:
                    act(m.group(1), run=run, cat=cat, log=log, dfd=dfd)
                    handled += 1
                    busy = True
                elif name.startswith(".") and name.endswith(".tmp") and not _old(dfd, name, TEMP_KEEP_S):
                    continue                     # the API is writing it now
                else:
                    log(f"bromigos-board: removed what isn't a request from the requests folder ({len(name)} letters long)")
                    _remove(dfd, name)
                    busy = True
            sweep_results()
            if busy:
                quiet_since = clock()
            elif clock() - quiet_since >= linger:
                return handled
            else:
                sleep(poll)
    finally:
        os.close(dfd)
