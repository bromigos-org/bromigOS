"""Where the board keeps its files, and how root writes one where someone else can read it.

Two users work here: root (the reader, and `bromigos server board code` before it steps down) and
bromigos-board (the API). The rule that keeps them apart: **root never writes in a folder the
board's user can write in**. /run/bromigos-board is root's, and the board's user only reads it;
/var/lib/bromigos-board is the board's user's, and root becomes that user before it touches it
(cli.become_board_user).

BROMIGOS_ROOT is a stand-in root for the tests, with BROMIGOS_BOARD_HOSTNAME and
BROMIGOS_BOARD_NOW_MS. None of the three is honoured when the process really is root: a server
has one root, /.
"""
import json
import os
import secrets
import time

RUN = "/run/bromigos-board"                 # root's, group bromigos-board, 0750: the board's user only reads here
SNAPSHOT = RUN + "/board.json"              # written by the root-run reader, group bromigos-board, 0640
WANTED = RUN + "/wanted"                    # made by tmpfiles; touched by the API while a signed-in browser is connected
DOOR = RUN + "/door"                        # made by tmpfiles; touched by the API for the door, every few minutes at most
STATE = "/var/lib/bromigos-board"           # the board's user's, 0700: sessions and console codes
SESSIONS = STATE + "/sessions"
CODES = STATE + "/codes"
SERVER_TOML = "/etc/bromigos/server.toml"   # root's: the [board] table
PROVISION_STATE = "/var/lib/bromigos/lab/provision-local.json"
WEB = "/usr/share/bromigos-board/web"
USER = "bromigos-board"
# the commands root runs, by their whole path on a server (never looked up in PATH there)
TOOLS = {"bromigos": "/usr/bin/bromigos", "bromigos-activity": "/usr/lib/bromigos/bin/bromigos-activity"}
# the worlds the page can wear ([board] world in server.toml; the Wick when it's not one of these)
WORLDS = ("wick", "mire", "tidewell", "rime", "sunder", "cinder", "lowtown", "highwind", "deepvein", "wick-tidewell",
          "wick-mire")


def really_root():
    return os.geteuid() == 0


def _switch(name):
    """A test's switch from the environment; never when this process is root."""
    return None if really_root() else (os.environ.get(name) or None)


def root():
    return _switch("BROMIGOS_ROOT") or "/"


def stand_in():
    return root() != "/"


def at(path):
    r = root()
    return path if r == "/" else os.path.join(r, path.lstrip("/"))


def tool(name):
    """A command root runs: its whole path on a server; in a stand-in root, its name (the tests'
    own stand-in is first on PATH)."""
    return name if stand_in() else TOOLS[name]


def hostname():
    """This server's name (myserver); BROMIGOS_BOARD_HOSTNAME in a stand-in."""
    import socket
    return _switch("BROMIGOS_BOARD_HOSTNAME") or socket.gethostname().split(".")[0]


def names():
    """The names the board's page answers at: <server>.local, and the old start page's."""
    h = hostname().lower()
    return (f"{h}.local", f"home-{h}.local")


def now_ms():
    fixed = _switch("BROMIGOS_BOARD_NOW_MS")
    return int(fixed) if fixed else int(time.time() * 1000)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def open_folder(path):
    """A descriptor for the folder at `path`, which must be a folder of its own: a link in its
    place is refused (NotADirectoryError), never followed."""
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as e:
        if os.path.islink(path):
            raise NotADirectoryError(f"{path} is a link, not a folder of its own") from e
        raise


def write_at(dfd, name, data, mode=0o600, group=None, replace=True):
    """Write `data` as the file `name` in the folder `dfd`, whole and atomically, without ever
    following a link or trusting a name someone else could have made:

    - the temporary file has a random name and is created exclusively (O_EXCL) and without
      following a link (O_NOFOLLOW), relative to the folder's descriptor;
    - its group and mode are set on the descriptor (fchown, fchmod), never by path;
    - it is renamed over `name`, which replaces a link there rather than writing through it.

    replace=False: fail (FileExistsError) when `name` is there already."""
    tmp = f".{name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dfd)
    try:
        try:
            if group is not None:
                os.fchown(fd, -1, group)
            os.fchmod(fd, mode)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)
        if replace:
            os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        else:
            os.link(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
            os.unlink(tmp, dir_fd=dfd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dfd)
        except OSError:
            pass
        raise


def dump(doc):
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode()


def write_json(path, doc, mode=0o600, group=None):
    """`doc` as the file at `path`: write_at in its folder, which must be there and must not be
    a link. A reader sees the old file or the new one, never half of one."""
    folder, name = os.path.split(path)
    dfd = open_folder(folder)
    try:
        write_at(dfd, name, dump(doc), mode, group)
    finally:
        os.close(dfd)


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
