"""Where the board keeps its files. BROMIGOS_ROOT is a stand-in root (tests); on a server it's /."""
import json
import os
import time

RUN = "/run/bromigos-board"                 # the service's: the snapshot and the request to read one
SNAPSHOT = RUN + "/board.json"              # written by the root-run snapshot, group bromigos-board, 0640
WANTED = RUN + "/wanted"                    # touched by the service while a browser is connected
STATE = "/var/lib/bromigos-board"           # the service's, 0700: sessions and console codes
SESSIONS = STATE + "/sessions"
CODES = STATE + "/codes"
SERVER_TOML = "/etc/bromigos/server.toml"   # root's: the [board] table
PROVISION_STATE = "/var/lib/bromigos/lab/provision-local.json"
WEB = "/usr/share/bromigos-board/web"
USER = "bromigos-board"
# the worlds the page can wear ([board] world in server.toml; the Wick when it's not one of these)
WORLDS = ("wick", "mire", "tidewell", "rime", "sunder", "cinder", "lowtown", "highwind", "deepvein", "wick-tidewell",
          "wick-mire")


def root():
    return os.environ.get("BROMIGOS_ROOT") or "/"


def at(path):
    r = root()
    return path if r == "/" else os.path.join(r, path.lstrip("/"))


def hostname():
    """This server's name (myserver); BROMIGOS_BOARD_HOSTNAME in a stand-in."""
    import socket
    return os.environ.get("BROMIGOS_BOARD_HOSTNAME") or socket.gethostname().split(".")[0]


def now_ms():
    fixed = os.environ.get("BROMIGOS_BOARD_NOW_MS")
    return int(fixed) if fixed else int(time.time() * 1000)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, doc, mode=0o600, group=None):
    """Whole and atomic: a reader sees the old file or the new one, never half of one."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
            f.write("\n")
        os.chmod(tmp, mode)
        if group is not None:
            try:
                os.chown(tmp, -1, group)
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def board_settings():
    """Root's [board] table in /etc/bromigos/server.toml, with its defaults. Read by root (the
    snapshot and the action helper), never by the service."""
    import tomllib
    try:
        with open(at(SERVER_TOML), "rb") as f:
            doc = tomllib.load(f)
    except (OSError, ValueError):
        doc = {}
    b = doc.get("board") if isinstance(doc.get("board"), dict) else {}
    world = b.get("world")
    return {"door": b.get("door", True) is not False, "world": world if world in WORLDS else "wick"}
