"""The board's one reader (docs/board.md, "Where the readings come from").

Root runs it (bromigos-board-snapshot.service, started by bromigos-board-snapshot.path when the
service touches /run/bromigos-board/wanted). It runs the commands that already say these things
with --json, every 15 seconds while a browser is connected, and writes what they said to
/run/bromigos-board/board.json, readable by the service's group only. When nobody has looked for
45 seconds it stops. The service never runs a command itself.

A command that isn't there, fails or doesn't print JSON is noted in `sources` with why, and its
part of the board is null: the page says "can't check" rather than guessing.
"""
import concurrent.futures
import grp
import json
import os
import re
import shutil
import subprocess
import sys
import time

from . import SCHEMA, paths

# (part of the board, the command): every one is a command that ships, run as root
SOURCES = (
    ("system", ["bromigos", "server", "status", "--json"]),
    ("storage", ["bromigos", "storage", "health", "--json"]),
    ("backups", ["bromigos", "lab", "backups", "status", "--json"]),
    ("activity", ["bromigos", "activity", "list", "--json"]),
    ("alerts", ["bromigos", "alerts", "--json"]),
    # the app manager's list (DESIGN's tile contract): read when this server's bromigos has it
    ("apps", ["bromigos", "lab", "apps", "list", "--json"]),
)
INTERVAL_S = 15
IDLE_S = 45                     # nobody looked for this long: stop
TIMEOUT_S = 60
NOT_ON_DOOR = ("board", "start-page")     # the page itself, and the one it replaces

# a value under one of these names is never written, whatever command printed it: the board
# shows no secret (DESIGN §1, "What it must never expose"). true/false and numbers stay
# ("passwords": false says whether SSH takes passwords; it holds none).
SECRET_NAME = re.compile(r"(pass(word|wd|phrase)?s?|secret|token|api[-_]?key|apikey|private[-_]?key|access[-_]?key"
                         r"|recovery|join[-_]?code|bundle|unseal|credential)", re.I)
USERINFO = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^/@\s]+@", re.I)


def scrub(doc):
    """doc without any value whose name says it's a secret, and with no user:password@ in a URL."""
    if isinstance(doc, dict):
        out = {}
        for k, v in doc.items():
            if SECRET_NAME.search(str(k)) and not isinstance(v, (bool, int, float)) and v is not None:
                continue
            out[k] = scrub(v)
        return out
    if isinstance(doc, list):
        return [scrub(v) for v in doc]
    if isinstance(doc, str):
        return USERINFO.sub(r"\1", doc)
    return doc


def run_source(argv, timeout=TIMEOUT_S, env=None):
    """(document or None, {ok, rc, at, command, why})."""
    started = paths.now_ms()
    note = {"command": argv, "at": started}
    exe = shutil.which(argv[0], path=(env or os.environ).get("PATH"))
    if not exe:
        return None, dict(note, ok=False, rc=127, why=f"{argv[0]} isn't installed")
    try:
        r = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, dict(note, ok=False, rc=124, why=f"no answer in {timeout} seconds")
    except OSError as e:
        return None, dict(note, ok=False, rc=126, why=str(e)[:200])
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        doc = None
    if doc is None:
        last = next((x.strip() for x in reversed((r.stderr or r.stdout or "").splitlines()) if x.strip()), "")
        return None, dict(note, ok=False, rc=r.returncode, why=(last or f"it ended with {r.returncode} and printed no JSON")[:200])
    # a command that found a problem still answered: exit 1 with its JSON is a reading
    return doc, dict(note, ok=True, rc=r.returncode)


def door_fallback(host):
    """Tiles for the door when the apps list isn't there: the catalogue's web apps that
    `bromigos lab provision --local` set up (provision-local.json says done), as Homepage lists
    them today."""
    state = paths.read_json(paths.at(paths.PROVISION_STATE), {}) or {}
    items = state.get("items") if isinstance(state.get("items"), dict) else {}
    done = [i for i, s in items.items() if (s.get("state") if isinstance(s, dict) else s) == "done"]
    if not done:
        return []
    try:
        from bromigos_homelab import provcatalog
        cat = provcatalog.by_id()
    except Exception:          # no lab package, or no catalogue: no tiles, rather than a guess
        return []
    out = []
    for i in done:
        it = cat.get(i)
        web = (it or {}).get("web") or {}
        if not it or i in NOT_ON_DOOR or not web.get("port"):
            continue
        url = (f"https://{web['name']}-{host}.local" if web.get("name")
               else f"http://{host}.local:{web['port']}{web.get('path') or ''}")
        out.append({"id": i, "job": it.get("job") or it["name"], "app": it.get("app") or "", "holo": it.get("holo") or "",
                    "group": it.get("group") or "", "installed": True, "open": {"url": url}})
    return out


def gather(env=None):
    host = paths.hostname()
    doc = {"schema": SCHEMA, "host": host, "settings": paths.board_settings(), "sources": {}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        futures = {name: pool.submit(run_source, argv, TIMEOUT_S, env) for name, argv in SOURCES}
        for name, _ in SOURCES:
            part, note = futures[name].result()
            doc[name] = scrub(part)
            doc["sources"][name] = note
    if doc["apps"] is None:
        doc["door_fallback"] = door_fallback(host)
    doc["at"] = paths.now_ms()
    return doc


def board_gid():
    if paths.root() != "/":
        return None
    try:
        return grp.getgrnam(paths.USER).gr_gid
    except KeyError:
        return None


def write(doc):
    paths.write_json(paths.at(paths.SNAPSHOT), doc, mode=0o640, group=board_gid())


def wanted_age_s():
    try:
        return time.time() - os.stat(paths.at(paths.WANTED)).st_mtime
    except OSError:
        return None


def run(once=False, interval=INTERVAL_S, idle=IDLE_S, sleep=time.sleep, log=None):
    """Gather and write; again every `interval` seconds while someone looked in the last `idle`."""
    log = log or (lambda words: print(words, file=sys.stderr))
    n = 0
    while True:
        t0 = time.monotonic()
        doc = gather()
        write(doc)
        n += 1
        bad = [k for k, v in doc["sources"].items() if not v["ok"]]
        if n == 1 or bad:
            log("bromigos-board: board.json written" + (f"; can't read {', '.join(bad)}" if bad else ""))
        age = wanted_age_s()
        if once or age is None or age > idle:
            return 0
        sleep(max(0.0, interval - (time.monotonic() - t0)))
