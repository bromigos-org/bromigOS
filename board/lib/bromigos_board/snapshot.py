"""The board's one reader (docs/board.md, "Where the readings come from").

Root runs it (bromigos-board-snapshot.service, started by bromigos-board-snapshot.path when the
API marks /run/bromigos-board/wanted or /run/bromigos-board/door). It runs the commands that
already say these things with --json and writes what they said to /run/bromigos-board/board.json,
readable by the board's group only: every 15 seconds while a signed-in browser is connected
(`wanted` is fresh), once when only the door asked. When nobody has looked for 45 seconds it
stops. The API never runs a command itself, and can't write in that folder: it is root's.

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

from . import SCHEMA, actions, paths

# (part of the board, the command): every one is a command that ships, run as root
SOURCES = (
    ("system", ["bromigos", "server", "status", "--json"]),
    ("storage", ["bromigos", "storage", "health", "--json"]),
    ("backups", ["bromigos", "lab", "backups", "status", "--json"]),
    ("activity", ["bromigos", "activity", "list", "--json"]),
    ("alerts", ["bromigos", "alerts", "--json"]),
    # the app manager's list (DESIGN's tile contract): read when this server's bromigos has it
    ("apps", ["bromigos", "lab", "apps", "list", "--json"]),
    # what is in the box (cores, memory, free disk, a graphics card): the scan the app manager
    # fits apps against, which is the only shipped command that prints it
    ("budget", ["bromigos", "lab", "apps", "budget", "--json"]),
)
INTERVAL_S = 15
IDLE_S = 45                     # nobody looked for this long: stop
TIMEOUT_S = 60
NOT_ON_DOOR = ("board", "start-page")     # the page itself, and the one it replaces

# The filter. The board is the second line here, not the first: the commands it runs don't
# print secrets, and only signed-in browsers see what it writes. This catches what a command
# printed anyway, as well as it can (docs/board.md, "Where the readings come from"):
#
# - a value under a name that says it's a secret is dropped, unless it's true, false or null
#   ("passwords": false says whether SSH takes passwords; it holds none), or the words "set" and
#   "not set";
# - {"name": "<a secret's name>", "value": …} loses its value;
# - every piece of text, a command's error line included, loses a user:password@ in an address
#   and goes through the activity records' own filter (bromigos_activity.redact: NAME=value, a
#   secret in a link's query, tokens by their shape); an option that names a secret takes the
#   next word with it.
#
# A name says so by its words, never by a run of letters inside one: "last_test_passed" isn't
# "pass". And by where the word stands: the name's last word is what the value is, so "api_key"
# and "db_password" are secrets while "key_count", "token_ttl" and "secret_store" are a count, a
# time and a place (secret_name).
SECRET_WORDS = frozenset("""pass password passwords passwd passphrase passphrases pwd secret secrets token tokens key keys
    apikey authkey psk pin otp totp seed cookie cookies credential credentials recovery unseal bundle bearer
    authorization""".split())
# after a secret's word, these still name the secret itself, in another form or where it is kept
# (password_hash, token_b64, key_file, secret_id); any other last word names something about it
SECRET_FORMS = frozenset("""value values hash plain plaintext text string str raw data material pem b64 base64 hex enc
    encrypted new old current file path id""".split())
# under a secret's name these say whether there is one, as true and false do, and stay
# (`bromigos alerts --json`: a channel's "key": "set")
SAYS_WHETHER = ("set", "not set")
# "code" is a secret after one of these (join_code), and not otherwise (exit_code, an error's code)
CODE_OF = frozenset("join recovery pairing pair auth device user unseal backup otp invite access signin sign".split())
USERINFO = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^/@\s]+@", re.I)
OPTION = re.compile(r"(?<![\w-])(--?[\w-]*)(\s+)(?!-)(\S+)")
WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Za-z][a-z]*|[0-9]+")        # DB_PASSWORD, dbPassword, HTTPToken2
DRIVE_KEY = re.compile(r"[a-z0-9][a-z0-9._:-]{0,95}\Z")


def secret_name(name):
    """Whether a field's name says its value is a secret: by its last word (api_key, password2),
    by the whole name run together (apiKey, authkey), by a secret's word and then its form
    (token_b64), or a code that lets someone in (join_code)."""
    words = [w.lower() for w in WORD.findall(str(name))]
    if any(words[i - 1] in SECRET_WORDS and "".join(words[i:]) in SECRET_FORMS for i in range(1, len(words))):
        return True
    while len(words) > 1 and words[-1].isdigit():           # password2, token_1: still the password, the token
        words.pop()
    if not words:
        return False
    if words[-1] in SECRET_WORDS or "".join(words) in SECRET_WORDS:
        return words[-2:] != ["public", "key"]
    return words[-1] in ("code", "codes") and len(words) > 1 and words[-2] in CODE_OF


def _redact():
    try:
        import bromigos_activity
        return bromigos_activity.redact
    except Exception:          # no bromigos-core beside it: the rules here only
        return lambda text: text


def scrub_text(text, redact=None):
    text = USERINFO.sub(r"\1", text)
    text = OPTION.sub(lambda m: f"{m.group(1)}{m.group(2)}***" if secret_name(m.group(1)) else m.group(0), text)
    return (redact or _redact())(text)


def scrub(doc, parent=None, redact=None):
    """doc without what looks like a secret (the rules above). `parent`: the name doc is under."""
    redact = redact or _redact()
    if isinstance(doc, dict):
        named = doc.get("name") if isinstance(doc.get("name"), str) and secret_name(doc["name"]) else None
        out = {}
        for k, v in doc.items():
            if parent == "drives" and k == "key" and isinstance(v, str) and DRIVE_KEY.match(v):
                out[k] = v                    # a drive's own id in the drive reports, not a key that opens anything
                continue
            if (secret_name(k) or (named and k == "value")) and v is not None and not isinstance(v, bool) and v not in SAYS_WHETHER:
                continue
            out[k] = scrub(v, k, redact)
        return out
    if isinstance(doc, list):
        out, hide = [], False
        for v in doc:
            if isinstance(v, str):
                # ["--password", "x"]: an option that names a secret takes the next word with it
                out.append("***" if hide and not v.startswith("-") else scrub_text(v, redact))
                hide = v.startswith("-") and "=" not in v and secret_name(v)
            else:
                out.append(scrub(v, parent, redact))
                hide = False
        return out
    if isinstance(doc, str):
        return scrub_text(doc, redact)
    return doc


def run_source(argv, timeout=TIMEOUT_S, env=None):
    """(document or None, {ok, rc, at, command, why})."""
    started = paths.now_ms()
    note = {"command": argv, "at": started}
    # on a server the command's whole path, never a name looked up in PATH (paths.tool)
    exe = paths.tool(argv[0])
    exe = exe if os.path.isabs(exe) and os.access(exe, os.X_OK) else \
        shutil.which(exe, path=(env or os.environ).get("PATH")) if not os.path.isabs(exe) else None
    if not exe:
        return None, dict(note, ok=False, rc=127, why=f"{argv[0]} isn't installed")
    try:
        r = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, dict(note, ok=False, rc=124, why=f"no answer in {timeout} seconds")
    except OSError as e:
        return None, dict(note, ok=False, rc=126, why=scrub_text(str(e))[:200])
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        doc = None
    if doc is None:
        last = next((x.strip() for x in reversed((r.stderr or r.stdout or "").splitlines()) if x.strip()), "")
        # the command's own last line, through the filter like everything else it said
        return None, dict(note, ok=False, rc=r.returncode,
                          why=scrub_text(last or f"it ended with {r.returncode} and printed no JSON")[:200])
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
    doc = {"schema": SCHEMA, "host": host, "settings": paths.board_settings(), "actions": actions.offered(), "sources": {}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        futures = {name: pool.submit(run_source, argv, TIMEOUT_S, env) for name, argv in SOURCES}
        for name, _ in SOURCES:
            part, note = futures[name].result()
            doc[name] = scrub(part, name)
            doc["sources"][name] = note
    if doc["apps"] is None:
        doc["door_fallback"] = door_fallback(host)
    doc["at"] = paths.now_ms()
    return doc


def board_gid():
    if paths.stand_in():
        return None
    try:
        return grp.getgrnam(paths.USER).gr_gid
    except KeyError:
        return None


def write(doc):
    """board.json, for the board's group to read. The folder is root's (tmpfiles:
    /run/bromigos-board, root:bromigos-board 0750), so nobody else can put anything in root's
    way there; paths.write_json wouldn't follow it if someone had."""
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
