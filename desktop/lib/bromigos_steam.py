"""Steam and Proton on this machine, read from Steam's own files (package bromigos-desktop,
/usr/lib/bromigos/lib). `bromigos game proton` and `bromigos game check` use it.

Steam keeps its state in Valve's text KeyValues format ("VDF"): quoted keys, quoted values
and `{ }` blocks. The parser here keeps every token's place in the text, so a change
rewrites one value and leaves the rest of the file byte for byte as it was. Keys may
repeat in VDF, and a lookup takes the first, as Steam does. A change replaces a value in
place and never appends a second copy of the key.

Nothing here starts, stops or signals Steam. A change to Steam's files is refused while
Steam runs, because Steam writes its config back when it exits and would undo it.

Paths: Steam's root is `~/.steam/root` (a link Steam makes), else
`$XDG_DATA_HOME/Steam`. `BROMIGOS_FS_ROOT` moves `/` (for /proc, /etc, /usr) for tests.
"""
import hashlib
import json
import os
import platform
import re
import shutil
import tarfile
import time
import urllib.request

# ------------------------------------------------------------------ paths

HOME = os.path.expanduser("~")


def fs_root():
    return os.environ.get("BROMIGOS_FS_ROOT") or "/"


def sys_path(path):
    """An absolute system path under BROMIGOS_FS_ROOT (tests), else as it is."""
    return os.path.join(fs_root(), path.lstrip("/"))


def _xdg(var, default):
    v = os.environ.get(var) or ""
    return v if os.path.isabs(v) else os.path.join(HOME, default)


def state_dir():
    return os.path.join(_xdg("XDG_STATE_HOME", ".local/state"), "bromigos", "game")


def steam_root():
    """Steam's root folder, or None when Steam has never run here."""
    for p in (os.path.join(HOME, ".steam", "root"), os.path.join(HOME, ".steam", "steam"),
              os.path.join(_xdg("XDG_DATA_HOME", ".local/share"), "Steam")):
        if os.path.isdir(os.path.join(p, "steamapps")) or os.path.isfile(os.path.join(p, "config", "config.vdf")):
            return os.path.realpath(p)
    return None


def compat_dir(root):
    """Where Steam looks for compatibility tools of the user's own (GE-Proton)."""
    return os.path.join(root, "compatibilitytools.d")


# ------------------------------------------------------------------ VDF

class VdfError(ValueError):
    pass


class Entry:
    """One key and its value: a string, or a Block. `span` is the value token's place in
    the text: the quoted string with its quotes, or a block from `{` to `}` inclusive."""
    __slots__ = ("key", "value", "span")

    def __init__(self, key, value, span):
        self.key, self.value, self.span = key, value, span


class Block:
    """A `{ }` block. `span` is its place in the text, from `{` to `}` inclusive (None for
    the file's top level)."""

    def __init__(self, span=None):
        self.entries = []
        self.span = span

    def get(self, key, default=None):
        """The first value under `key`, any case (Steam's own lookups ignore case)."""
        e = self.entry(key)
        return e.value if e else default

    def entry(self, key):
        k = key.lower()
        for e in self.entries:
            if e.key.lower() == k:
                return e
        return None

    def block(self, *keys):
        """The block at keys…, or None when any is missing or isn't a block."""
        b = self
        for k in keys:
            b = b.get(k) if isinstance(b, Block) else None
        return b if isinstance(b, Block) else None

    def items(self):
        return [(e.key, e.value) for e in self.entries]

    def to_dict(self):
        """Plain dicts (the first of repeated keys), for reading and for JSON."""
        out = {}
        for e in self.entries:
            if e.key not in out:
                out[e.key] = e.value.to_dict() if isinstance(e.value, Block) else e.value
        return out


_ESC = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


def _tokens(text):
    """(kind, value, start, end): kind is "s" (a string), "{" or "}"."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n﻿":
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        elif c in "{}":
            yield c, c, i, i + 1
            i += 1
        elif c == "[":                       # a platform condition ([$WIN32]): skipped
            j = text.find("]", i)
            if j < 0:
                raise VdfError(f"unclosed [ at {i}")
            i = j + 1
        elif c == '"':
            out, j = [], i + 1
            while True:
                if j >= n:
                    raise VdfError(f"unclosed string at {i}")
                ch = text[j]
                if ch == "\\" and j + 1 < n:
                    out.append(_ESC.get(text[j + 1], "\\" + text[j + 1]))
                    j += 2
                elif ch == '"':
                    break
                else:
                    out.append(ch)
                    j += 1
            yield "s", "".join(out), i, j + 1
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in " \t\r\n{}\"":
                j += 1
            yield "s", text[i:j], i, j
            i = j


def parse(text):
    """The whole file as a Block (its top level: usually one key, such as "AppState")."""
    stack = [Block()]
    key = None
    for kind, value, start, end in _tokens(text):
        if kind == "s":
            if key is None:
                key = (value, start)
            else:
                stack[-1].entries.append(Entry(key[0], value, (start, end)))
                key = None
        elif kind == "{":
            if key is None:
                raise VdfError(f"a block with no key at {start}")
            b = Block([start, None])
            stack[-1].entries.append(Entry(key[0], b, b.span))
            stack.append(b)
            key = None
        else:
            if key is not None or len(stack) == 1:
                raise VdfError(f"unexpected }} at {start}")
            stack.pop().span[1] = end
    if len(stack) != 1 or key is not None:
        raise VdfError("the file ends inside a block")
    return stack[0]


def load(path):
    """The file parsed, or None when it's missing or isn't VDF."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return parse(f.read())
    except (OSError, VdfError):
        return None


def quote(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_value(text, block, key, value):
    """`text` with `key` in `block` (parsed from that same text) set to `value`. The key's
    first value is replaced in place; a missing key is added as the block's last line, in
    the file's own indentation. Nothing else in the text changes."""
    e = block.entry(key)
    if e is not None:
        if isinstance(e.value, Block):
            raise VdfError(f"{key} is a block, not a value")
        a, b = e.span
        return text[:a] + quote(value) + text[b:]
    if block.span is None or text[block.span[1] - 1:block.span[1]] != "}":
        raise VdfError("the block isn't in this text")
    close = block.span[1] - 1                         # the block's }
    line_start = text.rfind("\n", 0, close) + 1
    indent = text[line_start:close]
    if indent.strip():                                # } shares a line with something
        return text[:close] + f" {quote(key)} {quote(value)} " + text[close:]
    return text[:line_start] + f"{indent}\t{quote(key)}\t\t{quote(value)}\n" + text[line_start:]


# ------------------------------------------------------------------ libraries and apps

# Steam's container runtimes: a Proton runs inside one. Each needs its entry point and
# pressure-vessel, the tool that starts the container.
RUNTIMES = {
    "1070560": "Steam Linux Runtime 1.0 (scout)",
    "1391110": "Steam Linux Runtime 2.0 (soldier)",
    "1628350": "Steam Linux Runtime 3.0 (sniper)",
    "4183110": "Steam Linux Runtime 4.0",
}
CONTAINER_RUNTIMES = {"1391110", "1628350", "4183110"}
INSTALLED = 4                                          # StateFlags: fully installed
UPDATE_REQUIRED = 2                                    # an update is waiting (files whole)


def libraries(root):
    """Every Steam library folder (libraryfolders.vdf), the root first, each once."""
    out, seen = [], set()

    def add(p):
        if p and os.path.isdir(os.path.join(p, "steamapps")):
            real = os.path.realpath(p)
            if real not in seen:
                seen.add(real)
                out.append(real)

    add(root)
    for f in (os.path.join(root, "steamapps", "libraryfolders.vdf"),
              os.path.join(root, "config", "libraryfolders.vdf")):
        doc = load(f)
        lf = doc and (doc.block("libraryfolders") or doc.block("LibraryFolders"))
        if not lf:
            continue
        for _, v in lf.items():
            if isinstance(v, Block):
                add(v.get("path"))
            elif isinstance(v, str) and os.path.isabs(v):  # the old format: "1" "/path"
                add(v)
    return out


class App:
    def __init__(self, library, appid, name, installdir, state):
        self.library, self.appid, self.name, self.installdir = library, appid, name, installdir
        self.state = state

    @property
    def manifest(self):
        return os.path.join(self.library, "steamapps", f"appmanifest_{self.appid}.acf")

    @property
    def path(self):
        return os.path.join(self.library, "steamapps", "common", self.installdir) if self.installdir else None

    @property
    def installed(self):
        """Steam counts it as fully installed (it may still want an update)."""
        return bool(self.state and self.state & INSTALLED)

    @property
    def busy(self):
        """Steam is in the middle of downloading, updating or checking it."""
        return bool(self.state and self.state & ~(INSTALLED | UPDATE_REQUIRED))


def apps(root):
    """Every app with a manifest in any library: {appid: App} (the first library wins)."""
    out = {}
    for lib in libraries(root):
        d = os.path.join(lib, "steamapps")
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for f in names:
            m = re.fullmatch(r"appmanifest_(\d+)\.acf", f)
            if not m or m.group(1) in out:
                continue
            doc = load(os.path.join(d, f))
            st = doc and doc.block("AppState")
            if not st:
                out[m.group(1)] = App(lib, m.group(1), None, None, None)
                continue
            try:
                flags = int(st.get("StateFlags", "0"))
            except ValueError:
                flags = 0
            out[m.group(1)] = App(lib, m.group(1), st.get("name"), st.get("installdir"), flags)
    return out


def tool_manifest(path):
    """A tool's toolmanifest.vdf "manifest" block as a dict, or None."""
    doc = load(os.path.join(path, "toolmanifest.vdf")) if path else None
    m = doc and doc.block("manifest")
    return m.to_dict() if m else None


def runtime_problems(app):
    """What's wrong with an installed runtime or tool's folder: [] when it looks whole."""
    p = app.path
    if not p or not os.path.isdir(p):
        return [f"its folder {p or '(none named)'} is missing"]
    missing = []
    manifest = tool_manifest(p)
    if manifest is None:
        missing.append("toolmanifest.vdf")
    else:
        cmd = (manifest.get("commandline") or "").split()
        entry = cmd[0] if cmd else ""
        if entry.startswith("/") and not os.path.exists(os.path.join(p, entry.lstrip("/"))):
            missing.append(entry.lstrip("/"))
    if app.appid in CONTAINER_RUNTIMES:
        if "_v2-entry-point" not in missing and not os.path.exists(os.path.join(p, "_v2-entry-point")):
            missing.append("_v2-entry-point")
        pv = os.path.join(p, "pressure-vessel")
        if not os.path.isdir(pv) or not os.listdir(pv):
            missing.append("pressure-vessel/ (empty)" if os.path.isdir(pv) else "pressure-vessel/")
    return [f"{m} is missing" if not m.endswith("(empty)") else m.replace(" (empty)", " is empty")
            for m in missing]


# ------------------------------------------------------------------ compatibility tools

class Tool:
    """A compatibility tool: Proton from Steam (an app), or one of the user's own."""

    def __init__(self, name, display, path, kind, appid=None):
        self.name, self.display, self.path, self.kind, self.appid = name, display, path, kind, appid
        self.manifest = tool_manifest(path)

    @property
    def requires(self):
        return (self.manifest or {}).get("require_tool_appid") or None

    def doc(self):
        return {"name": self.name, "display_name": self.display, "path": self.path, "kind": self.kind,
                "appid": self.appid, "requires": self.requires}


def custom_tools(root):
    """The tools in compatibilitytools.d (the user's) and /usr/share/steam's (packages')."""
    out = []
    for base, kind in ((compat_dir(root), "user"),
                       (sys_path("/usr/share/steam/compatibilitytools.d"), "system")):
        try:
            dirs = sorted(os.listdir(base))
        except OSError:
            continue
        for d in dirs:
            here = os.path.join(base, d)
            doc = load(os.path.join(here, "compatibilitytool.vdf"))
            tools = doc and doc.block("compatibilitytools", "compat_tools")
            if not tools:
                continue
            for name, v in tools.items():
                if not isinstance(v, Block):
                    continue
                inst = v.get("install_path") or "."
                path = os.path.normpath(os.path.join(here, inst))
                out.append(Tool(name, v.get("display_name") or name, path, kind))
    return out


def steam_tools(root, installed=None):
    """Proton and other tools Steam installed as apps (their folder has a toolmanifest.vdf)."""
    out = []
    for appid, a in sorted((installed if installed is not None else apps(root)).items()):
        if appid in RUNTIMES or not a.path or not os.path.isfile(os.path.join(a.path, "toolmanifest.vdf")):
            continue
        out.append(Tool(a.installdir, a.name or a.installdir, a.path, "steam", appid))
    return out


def config_path(root):
    return os.path.join(root, "config", "config.vdf")


def compat_mapping(root):
    """(text, parsed root, the CompatToolMapping block) of config.vdf; (None, None, None)
    when there's no config, and (text, root, None) when it has no mapping."""
    try:
        with open(config_path(root), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None, None, None
    try:
        doc = parse(text)
    except VdfError:
        return text, None, None
    return text, doc, doc.block("InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping")


def mapping_entries(block):
    """{appid: {name, config, priority}} of a CompatToolMapping block ("0": every game)."""
    out = {}
    if block is None:
        return out
    for k, v in block.items():
        if isinstance(v, Block) and k not in out:
            out[k] = {"name": v.get("name") or "", "config": v.get("config") or "",
                      "priority": v.get("priority") or ""}
    return out


# Steam's own value for the default tool ("0"): per-game choices use 250, which is higher.
DEFAULT_PRIORITY = "75"


# ------------------------------------------------------------------ Steam running

def steam_running():
    """Steam's pid when it runs (its client process), else None."""
    proc = sys_path("/proc")
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return None
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "comm")) as f:
                comm = f.read().strip()
        except OSError:
            continue
        if comm in ("steam", "steamwebhelper", "steam.sh"):
            return int(pid)
        if comm in ("bash", "sh"):
            try:
                with open(os.path.join(proc, pid, "cmdline"), "rb") as f:
                    argv = f.read().split(b"\0")
            except OSError:
                continue
            if any(a.endswith(b"/steam.sh") for a in argv[:2]):
                return int(pid)
    return None


# ------------------------------------------------------------------ backups

def stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def backup_file(path):
    """A copy of `path` in ~/.local/state/bromigos/game/backup/<time>/; its path."""
    d = os.path.join(state_dir(), "backup", stamp())
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, os.path.basename(path))
    shutil.copy2(path, dest)
    return dest


def move_aside(library, rel_paths):
    """Moves each existing <library>/<rel> into <library>/bromigos-backup/<time>/<rel> (same
    drive, so nothing is copied); the backup folder, or None when nothing was there."""
    dest = os.path.join(library, "bromigos-backup", stamp())
    moved = False
    for rel in rel_paths:
        src = os.path.join(library, rel)
        if not os.path.lexists(src):
            continue
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.rename(src, target)
        moved = True
    return dest if moved else None


def runtime_paths(app):
    """A runtime's files a reinstall replaces, relative to its library."""
    rel = [os.path.join("steamapps", "common", app.installdir)] if app.installdir else []
    return rel + [os.path.join("steamapps", "downloading", app.appid),
                  os.path.join("steamapps", "temp", app.appid),
                  os.path.join("steamapps", f"appmanifest_{app.appid}.acf")]


# ------------------------------------------------------------------ GE-Proton

GE_REPO = "GloriousEggroll/proton-ge-custom"
GE_RELEASES = f"https://api.github.com/repos/{GE_REPO}/releases"
GE_DOWNLOADS = f"https://github.com/{GE_REPO}/releases/download/"
GE_TAG = re.compile(r"GE-Proton\d+-\d+")


def _releases_base():
    """GitHub's API, or a folder of recorded answers (BROMIGOS_PROTON_RELEASES, tests)."""
    return os.environ.get("BROMIGOS_PROTON_RELEASES") or GE_RELEASES


def _open(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "bromigos-game-proton",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def machine():
    """The CPU architecture as GE-Proton names its builds: x86_64 or aarch64."""
    m = platform.machine().lower()
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(m, m)


def ge_release(tag=None):
    """{tag, top, tarball, sha512sum, size} of the latest GE-Proton release, or of `tag`.
    Newer releases have one build per architecture (GE-Proton11-11-x86_64.tar.gz), older
    ones a single GE-Proton10-25.tar.gz; `top` is the build's name, which is also the folder
    it unpacks to."""
    if tag is not None and not GE_TAG.fullmatch(tag):
        raise ValueError(f"{tag!r} isn't a GE-Proton version (such as GE-Proton10-25)")
    url = f"{_releases_base()}/latest" if tag is None else f"{_releases_base()}/tags/{tag}"
    with _open(url) as r:
        rel = json.load(r)
    name = rel.get("tag_name") or ""
    if not GE_TAG.fullmatch(name):
        raise ValueError(f"the release's tag {name!r} isn't a GE-Proton version")
    assets = {a.get("name"): a for a in rel.get("assets") or []}
    for top in (f"{name}-{machine()}", name):
        tar, sha = assets.get(f"{top}.tar.gz"), assets.get(f"{top}.sha512sum")
        if tar and sha:
            break
    else:
        raise ValueError(f"{name} has no build for {machine()} with its checksum "
                         f"({name}-{machine()}.tar.gz or {name}.tar.gz, and its .sha512sum)")
    official = not os.environ.get("BROMIGOS_PROTON_RELEASES")
    for a in (tar, sha):
        u = a.get("browser_download_url") or ""
        if official and not u.startswith(GE_DOWNLOADS + name + "/"):
            raise ValueError(f"unexpected download address {u!r}")
    return {"tag": name, "top": top, "tarball": tar["browser_download_url"], "sha512sum": sha["browser_download_url"],
            "size": tar.get("size")}


def published_sha512(text, filename):
    """The hash a .sha512sum file gives for `filename` (sha512sum's own format)."""
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{128}", parts[0]) \
                and os.path.basename(parts[1].lstrip("*")) == filename:
            return parts[0].lower()
    if re.fullmatch(r"[0-9a-fA-F]{128}", text.strip()):
        return text.strip().lower()
    raise ValueError(f"the published checksum file has no line for {filename}")


def download(url, dest, progress=None):
    """Streams `url` into `dest`; its SHA-512."""
    h = hashlib.sha512()
    with _open(url, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return h.hexdigest()


def extract(tarball, dest, top):
    """Unpacks `tarball` into `dest`, refusing anything outside `top/` (the release's own
    folder) and links that point out of it (tarfile's data filter)."""
    with tarfile.open(tarball) as t:
        for m in t.getmembers():
            name = os.path.normpath(m.name)
            if os.path.isabs(name) or (name != top and not name.startswith(top + "/")):
                raise ValueError(f"the archive holds {m.name!r}, outside {top}/")
        t.extractall(dest, filter="data")
