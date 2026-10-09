"""Shared by the small system commands Settings drives (`bromigos sound`, `display`, `net`,
`bluetooth`, `power`, `notifications`, `default-apps`, `startup`, `clock`, `panels`,
`about`, `vector-data`; package bromigos-desktop, /usr/lib/bromigos/lib).

Each is a thin layer over the established tool for its job (pactl and wpctl, hyprctl,
nmcli, bluetoothctl, powerprofilesctl, dunstctl, xdg-mime, timedatectl) with one shape:

    bromigos <cmd> [status] [--json]          the whole state, as one document
    bromigos <cmd> <verb> ARGS… [--json]      a change; the document after it, with ok and said

A refusal or a failure is `{"ok": false, "error": "…"}` and exit status 1; with --json
the document is the only thing on stdout. The tool each one wraps is found on PATH (tests
put stand-ins there).

    from bromigos_cli import Fail, run, main
    def status(args): return {...}
    def set_x(args): ...; return dict(status([]), said="X set")
    main({"status": status, "set": set_x}, USAGE)
"""
import json
import os
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")


def _xdg(var, default):
    v = os.environ.get(var) or ""
    return v if os.path.isabs(v) else os.path.join(HOME, default)


CONFIG = _xdg("XDG_CONFIG_HOME", ".config")
STATE = _xdg("XDG_STATE_HOME", ".local/state")
DATA = _xdg("XDG_DATA_HOME", ".local/share")


class Fail(Exception):
    """A refusal or a failure: its message is the document's `error`."""


def run(argv, timeout=10, input=None, env=None):
    """(returncode, stdout, stderr); 127 when the program isn't installed, 124 on a timeout.
    Never raises."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=input, env=env)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"{argv[0]} isn't installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]} didn't answer in {timeout} s"
    except OSError as e:
        return 126, "", f"{argv[0]}: {e.strerror}"


def must(argv, timeout=10, input=None, what=None):
    """stdout of argv, or Fail with what it said."""
    rc, out, err = run(argv, timeout=timeout, input=input)
    if rc != 0:
        msg = (err or out).strip().splitlines()
        raise Fail(f"{what or ' '.join(argv[:3])}: {msg[-1] if msg else f'exit {rc}'}")
    return out


def have(tool):
    return shutil.which(tool) is not None


def need(tool, package=None):
    if not have(tool):
        raise Fail(f"{tool} isn't installed" + (f" (pacman -S {package})" if package else ""))


def write_file(path, text, mode=None):
    """The whole file at once (a watcher never sees half of it); a symlink stays one (its
    target is replaced). None removes it."""
    if text is None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return
    target = os.path.realpath(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".bromigos.tmp"
    with open(tmp, "w") as f:
        f.write(text)
    if mode is not None:
        os.chmod(tmp, mode)
    else:
        try:
            os.chmod(tmp, os.stat(target).st_mode & 0o7777)
        except FileNotFoundError:
            pass
    os.replace(tmp, target)


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except (FileNotFoundError, NotADirectoryError):
        return None


def toml_value(v):
    """A TOML literal for a str, bool, int, float or list of them."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return json.dumps(str(v))


def write_toml(path, doc, header=""):
    """A flat TOML file of top-level keys and one level of tables (what these commands keep:
    small files they own), written whole."""
    lines = [header.rstrip() + "\n"] if header else []
    for k, v in doc.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {toml_value(v)}\n")
    for k, v in doc.items():
        if isinstance(v, dict):
            lines.append(f"\n[{k}]\n")
            for kk, vv in v.items():
                lines.append(f"{json.dumps(kk) if not kk.replace('_', '').replace('-', '').isalnum() else kk} = {toml_value(vv)}\n")
    write_file(path, "".join(lines))


def read_toml(path):
    import tomllib
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise Fail(f"{path}: {e}")


_TABLE = None


def _table_of(line):
    import re
    global _TABLE
    if _TABLE is None:
        _TABLE = re.compile(r"^\s*\[\s*([A-Za-z0-9_.\-\"]+)\s*\]\s*(#.*)?$")
    m = _TABLE.match(line)
    return m.group(1).replace('"', "") if m else None


def toml_set(text, section, key, value):
    """`text` (a TOML file) with [section] key = value, everything else as it was: the key's
    line replaced, else added at the end of its table, else the table appended."""
    import re
    lit = toml_value(value)
    lines = (text or "").splitlines(keepends=True)
    cur, start, last = None, None, None
    keyre = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    for i, line in enumerate(lines):
        t = _table_of(line)
        if t is not None or line.lstrip().startswith("[["):
            if cur == section and start is not None:
                break
            cur = t
            if t == section:
                start = last = i
            continue
        if cur == section:
            if keyre.match(line):
                lines[i] = f"{key} = {lit}\n"
                return "".join(lines)
            if line.strip() and not line.lstrip().startswith("#"):
                last = i
    if start is not None:
        lines.insert(last + 1, f"{key} = {lit}\n")
        return "".join(lines)
    body = "".join(lines)
    if body and not body.endswith("\n"):
        body += "\n"
    return body + ("\n" if body.strip() else "") + f"[{section}]\n{key} = {lit}\n"


def toml_unset(text, section, key):
    """`text` without [section] key (an emptied table stays)."""
    import re
    out, cur = [], None
    keyre = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    for line in (text or "").splitlines(keepends=True):
        t = _table_of(line)
        if t is not None:
            cur = t
        elif cur == section and keyre.match(line):
            continue
        out.append(line)
    return "".join(out)


def bromigos(*args, timeout=20):
    """A `bromigos … --json` document (or None)."""
    rc, out, _ = run(["bromigos", *args], timeout=timeout)
    try:
        return json.loads(out) if out.strip() else None
    except ValueError:
        return None


# ------------------------------------------------------------------ the manual
# Where Settings (F1, each page's manual link) and About open the manual, first found:
#  1. the copy bromigos-manual installs: this machine's own version, and it works offline;
#  2. the one published beside the packages: manual/publish.sh uploads the built book to
#     <bucket>/${PKGS_REPO:-bromigos}/manual, which the repository serves at
#     <base>/bromigos/manual/ (base: `bromigos channel`'s; test_manual_url reads the
#     publisher's default to check MANUAL_REPO);
#  3. the source on GitHub.
MANUAL_DIR = "/usr/share/doc/bromigos/manual"      # packaging/bromigos-manual installs it
MANUAL_REPO = "bromigos"
MANUAL_SOURCE = "https://github.com/bromigos-org/bromigOS/blob/main/manual/src/"


def manual_dir():
    """The installed manual's folder (BROMIGOS_MANUAL_DIR for tests), or None."""
    d = os.environ.get("BROMIGOS_MANUAL_DIR") or MANUAL_DIR
    return d if os.path.isfile(os.path.join(d, "index.html")) else None


def manual_online(base):
    """The manual published beside the packages at `base` (https://host), or None."""
    return f"{base.rstrip('/')}/{MANUAL_REPO}/manual/" if base else None


def manual_url(base=None, page=None):
    """The manual, at `page` ("settings.md#sound"; None: its first page): the installed copy
    (file://), else the published one beside the packages at `base`, else the source."""
    name, _, anchor = (page or "").partition("#")
    html = (name[:-3] + ".html" if name.endswith(".md") else name) + (f"#{anchor}" if anchor else "")
    d = manual_dir()
    if d:
        return "file://" + os.path.join(d, html or "index.html")
    if base:
        return manual_online(base) + html
    return MANUAL_SOURCE + (page or "")


def flag(args, name, default=None, takes=True):
    """Removes --name [VALUE] from args; its value (True for a switch), else default."""
    if name not in args:
        return default
    i = args.index(name)
    if not takes:
        del args[i]
        return True
    if i + 1 >= len(args):
        raise Fail(f"{name} needs a value")
    v = args[i + 1]
    del args[i:i + 2]
    return v


def on_off(word):
    w = (word or "").lower()
    if w in ("on", "true", "yes", "1", "enable", "enabled"):
        return True
    if w in ("off", "false", "no", "0", "disable", "disabled"):
        return False
    raise Fail(f"{word!r}: on or off")


def text_of(doc):
    """A document as lines for a terminal (when --json isn't asked for)."""
    if doc.get("said"):
        return doc["said"]
    out = []

    def walk(v, ind=""):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in ("schema", "ok"):
                    continue
                if isinstance(x, (dict, list)) and x:
                    out.append(f"{ind}{k}:")
                    walk(x, ind + "  ")
                else:
                    out.append(f"{ind}{k}: {x}")
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, dict):
                    head = x.get("title") or x.get("name") or x.get("description") or x.get("key") or x.get("id") or ""
                    rest = ", ".join(f"{k}={y}" for k, y in x.items() if not isinstance(y, (dict, list))
                                     and y != head)
                    out.append(f"{ind}- {head}" + (f"  ({rest})" if rest else ""))
                else:
                    out.append(f"{ind}- {x}")
    walk(doc)
    return "\n".join(out)


def main(verbs, usage, argv=None, default="status"):
    """Dispatches argv[1:] to verbs[name](args) -> document; prints it (JSON with --json);
    exit 0, or 1 with {"ok": false, "error"} on Fail."""
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if args and args[0] in ("-h", "--help", "help"):
        print(usage)
        return 0
    verb = args.pop(0) if args and not args[0].startswith("--") else default
    fn = verbs.get(verb)
    if fn is None:
        doc = {"schema": 1, "ok": False, "error": f"unknown command {verb!r}\n{usage}"}
        print(json.dumps(doc) if as_json else doc["error"], file=sys.stdout if as_json else sys.stderr)
        return 2
    try:
        doc = fn(args)
        doc = dict({"schema": 1, "ok": True}, **(doc or {}))
        code = 0 if doc.get("ok", True) else 1
    except Fail as e:
        doc, code = {"schema": 1, "ok": False, "error": str(e)}, 1
    if as_json:
        print(json.dumps(doc))
    elif code:
        print(doc["error"], file=sys.stderr)
    else:
        print(text_of(doc))
    return code
