"""Shared by the desktop's menu and setup tools (package bromigos-desktop, /usr/lib/bromigos/lib).

- rofi: `dmenu()` runs rofi in dmenu mode with the bromigOS theme and returns the choice.
- The user's hyprland.lua: `with_block()` keeps a marked block in it (the same markers
  `bromigos setup monitors` uses). `save()` writes files and makes Hyprland take them the
  safe way: auto-reload off first, each file written whole, `Hyprland --verify-config`, one
  `hyprctl reload`, no new `configerrors`, an optional check of the result, auto-reload back
  as it was; anything wrong puts every file back (and reloads it). `apply()` is the reload
  half alone, for a file the user just edited. (A half-written config picked up by
  auto-reload trips Hyprland's emergency mode.)
- `spawn()` starts a program detached from the caller (a rofi script exits at once).
"""
import json
import os
import shlex
import subprocess
import time

HOME = os.path.expanduser("~")
CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
STATE = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local/state")
HYPRLAND_LUA = os.path.join(CONFIG, "hypr/hyprland.lua")
DEFAULTS = "/usr/share/bromigos/default"
THEME_CURRENT = os.path.join(STATE, "bromigos/theme/current")


def terminal():
    """The terminal command (argv prefix) for a command that needs one."""
    t = os.environ.get("TERMINAL") or "kitty"
    return shlex.split(t)


def terminal_run(argv, hold=False, title=None):
    """argv for running `argv` in the user's terminal; `hold` keeps the window after exit."""
    term = terminal()
    if os.path.basename(term[0]) == "kitty":
        out = term + (["--hold"] if hold else []) + (["--title", title] if title else []) + ["-e"]
    else:
        out = term + ["-e"]
    return out + list(argv)


def session_env():
    """The live Hyprland session's environment (WAYLAND_DISPLAY, HYPRLAND_INSTANCE_SIGNATURE…)."""
    env = dict(os.environ)
    try:
        out = subprocess.run(["bromigos", "session"], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            k, _, v = line.partition("=")
            if k and v:
                env[k] = v
    except (OSError, subprocess.SubprocessError):
        pass
    return env


def spawn(argv, env=None):
    """Start `argv` in its own session, detached, with the live session's environment."""
    subprocess.Popen(argv, env=env or session_env(), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def notify(title, body="", urgency="low", icon=None, ms=2500):
    cmd = ["notify-send", "-a", "bromigos", "-u", urgency, "-t", str(ms)]
    if icon:
        cmd += ["-i", icon]
    subprocess.run(cmd + [title, body], check=False)


def palette():
    """The theme's colours (palette.json), {} without a theme."""
    try:
        with open(os.path.join(THEME_CURRENT, "palette.json")) as f:
            d = json.load(f)
        return d.get("colors") or d
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------------- rofi
def dmenu(rows, prompt="", mesg=None, theme_str="", allow_custom=False, markup=False, icons=False, extra=None):
    """rofi -dmenu with the bromigOS theme. `rows` are strings (a row may carry
    `\\0icon\\x1f<name>`). Returns the chosen row's text (or the typed text), or None."""
    cmd = ["rofi", "-dmenu", "-i", "-p", prompt]
    if not allow_custom:
        cmd.append("-no-custom")
    if markup:
        cmd.append("-markup-rows")
    if icons:
        cmd.append("-show-icons")
    if mesg:
        cmd += ["-mesg", mesg]
    if theme_str:
        cmd += ["-theme-str", theme_str]
    cmd += extra or []
    r = subprocess.run(cmd, input="\n".join(rows) + "\n", capture_output=True, text=True, env=session_env())
    if r.returncode != 0:
        return None
    return r.stdout.rstrip("\n").split("\0")[0] or None


# One quoted string per line: rofi's lexer reads a string to the line's last quote, so
# `str: "A"; font: "B"` made the title `A"; font: "B` (rofi 1.7.9).
# The title expands (rofi's default for a textbox). rofi lays out a vertical box only when
# its fixed-height children fit in it, and with a fixed-height title they didn't: the title
# was drawn under the input (rofi 1.7.9 and 2.0.0). Expanding, it takes what's left.
TITLE_THEME = '''
box-header {{ children: [ icon-emblem, box-headerbody ]; }}
box-headerbody {{ children: [ textbox-title, inputbar ]; }}
textbox-title {{ str: "{title}"; text-color: @primary; }}
textbox-title {{ font: "Geist Mono Bold 12"; }}
icon-emblem {{ size: 64px; }}
inputbar {{ children: [ textbox-prompt, entry ]; }}
'''


def title_theme(title, width=560, lines=None):
    """A rofi theme-str with a titled header (the power menu's look)."""
    s = TITLE_THEME.format(title=title.replace('"', ""))
    s += f"window {{ width: {width}px; }}\n"
    if lines:
        s += f"listview {{ lines: {lines}; }}\n"
    return s


# ------------------------------------------------------- the user's hyprland.lua
def markers(name):
    return f"-- >>> bromigos {name}", f"-- <<< bromigos {name}"


def find_marker(lua, marker, start=0):
    """Where the line that is exactly `marker` starts, or -1 (whole lines: the marker of
    "keys" isn't found inside "keys-unbind")."""
    import re
    m = re.compile(r"^" + re.escape(marker) + r"[ \t]*$", re.M).search(lua, start)
    return m.start() if m else -1


def with_block(lua, name, body, before_dofile):
    """`lua` with the marked block `name` holding `body`: the existing one replaced, else
    inserted before the line that loads bromigOS's defaults (settings the defaults read) or
    appended (binds, which need the defaults' helpers). `body` has no markers."""
    begin, end = markers(name)
    block = f"{begin}\n{body.rstrip()}\n{end}\n"
    b = find_marker(lua, begin)
    e = find_marker(lua, end, b + 1) if b >= 0 else -1
    if b >= 0 and e > b:
        tail = lua[e:]
        nl = tail.find("\n")
        rest = tail[nl + 1:] if nl >= 0 else ""
        return lua[:b] + block + rest
    if before_dofile:
        off = 0
        for line in lua.splitlines(keepends=True):
            if line.lstrip().startswith("dofile(") and "/default/hypr/hyprland.lua" in line:
                return lua[:off] + block + "\n" + lua[off:]
            off += len(line)
        raise ValueError("hyprland.lua doesn't load bromigOS's defaults (no dofile(\".../default/hypr/hyprland.lua\"))")
    sep = "" if lua.endswith("\n") or not lua else "\n"
    return lua + sep + "\n" + block


def without_block(lua, name):
    begin, end = markers(name)
    b = find_marker(lua, begin)
    e = find_marker(lua, end, b + 1) if b >= 0 else -1
    if b < 0 or e < b:
        return lua
    tail = lua[e:]
    nl = tail.find("\n")
    rest = tail[nl + 1:] if nl >= 0 else ""
    out = lua[:b].rstrip("\n") + "\n" + rest
    return out


def read_lua(path=HYPRLAND_LUA):
    with open(path) as f:
        return f.read()


def write_lua(text, path=HYPRLAND_LUA):
    write_file(path, text)


def verify(path=HYPRLAND_LUA):
    """(ok, output) of Hyprland --verify-config."""
    r = subprocess.run(["Hyprland", "--verify-config", "-c", path], capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    return ("config ok" in out and r.returncode == 0), out


def hyprctl(*args, env=None):
    r = subprocess.run(["hyprctl", *args], capture_output=True, text=True, env=env or session_env())
    return r.stdout.strip()


def apply(path=HYPRLAND_LUA):
    """Make the running Hyprland take `path`: auto-reload off while the file settles,
    verify, one reload, then the config errors (empty = good). Returns (ok, detail)."""
    env = session_env()
    if "HYPRLAND_INSTANCE_SIGNATURE" not in env:
        return False, "no running Hyprland session"
    hyprctl("eval", "hl.config({ misc = { disable_autoreload = true } })", env=env)
    ok, out = verify(path)
    if not ok:
        hyprctl("eval", "hl.config({ misc = { disable_autoreload = false } })", env=env)
        return False, out
    hyprctl("reload", env=env)
    errs = hyprctl("configerrors", env=env)
    return (errs == ""), (errs or "reloaded")


class Hyprctl:
    """The running Hyprland, through hyprctl (tests give a stand-in with the same methods)."""

    def __init__(self, env=None):
        self._env = env

    @property
    def env(self):
        if self._env is None:
            self._env = session_env()
        return self._env

    def run(self, *args, timeout=10):
        try:
            r = subprocess.run(["hyprctl", *args], capture_output=True, text=True, env=self.env, timeout=timeout)
            return r.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def running(self):
        return "HYPRLAND_INSTANCE_SIGNATURE" in self.env and self.run("version", "-j").startswith("{")

    def eval(self, code):
        return self.run("eval", code)

    def reload(self):
        return self.run("reload")

    def config_errors(self):
        try:
            errs = json.loads(self.run("configerrors", "-j") or "[]")
        except ValueError:
            errs = [self.run("configerrors")]
        return [e for e in errs if isinstance(e, str) and e.strip()]

    def autoreload_off(self):
        """Whether misc.disable_autoreload is on now."""
        try:
            return bool(json.loads(self.run("getoption", "misc:disable_autoreload", "-j") or "{}").get("bool"))
        except ValueError:
            return False

    def set_autoreload_off(self, off):
        return self.eval(f"hl.config({{ misc = {{ disable_autoreload = {'true' if off else 'false'} }} }})")

    def verify(self, path):
        """(ok, output) of Hyprland --verify-config."""
        try:
            r = subprocess.run(["Hyprland", "--verify-config", "-c", path], capture_output=True, text=True,
                               env=self.env, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"Hyprland --verify-config: {e}"
        out = (r.stdout + r.stderr).strip()
        return ("config ok" in out and r.returncode == 0), out


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def write_file(path, text):
    """The whole file at once (Hyprland's watcher never sees half of it); None removes it.
    A symlink (a config kept in dotfiles, linked into ~/.config) stays a symlink: the file
    it points at is the one replaced."""
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
        f.flush()
        os.fsync(f.fileno())
    try:
        os.chmod(tmp, os.stat(target).st_mode & 0o7777)
    except FileNotFoundError:
        pass
    os.replace(tmp, target)


def save(files, lua=HYPRLAND_LUA, hypr=None, check=None, wait=1.5):
    """Write `files` ({path: text, or None to remove}) and make the running Hyprland take
    `lua` the safe way. `check()` (optional) runs after the reload and returns None when
    the result is right, else what's wrong (it's retried for `wait` seconds). Returns
    (ok, detail); not ok means every file is as it was and Hyprland runs what it ran."""
    hypr = hypr or Hyprctl()
    old = {p: read_file(p) for p in files}
    if all(files[p] == old[p] for p in files):
        return True, "nothing to change"
    live = hypr.running()
    was_off = hypr.autoreload_off() if live else False
    errors_before = set(hypr.config_errors()) if live else set()
    state = {"reloaded": False}

    def undo(why):
        if live:
            hypr.set_autoreload_off(True)
        for p in files:
            write_file(p, old[p])
        if live and state["reloaded"]:
            hypr.reload()
        if live:
            hypr.set_autoreload_off(was_off)
        return False, f"{why}; nothing changed (the files are as they were)"

    if live:
        hypr.set_autoreload_off(True)
    try:
        for p in sorted(files, key=lambda p: p == lua):      # the Hyprland config last
            if files[p] != old[p]:
                write_file(p, files[p])
    except OSError as e:
        return undo(f"couldn't write {e.filename}: {e.strerror}")
    ok, out = hypr.verify(lua)
    if not ok:
        tail = " | ".join([ln for ln in out.splitlines() if ln.strip()][-3:])
        return undo(f"Hyprland didn't accept the new config ({tail or 'no output'})")
    if not live:
        return True, "saved; Hyprland takes it when it next starts"
    hypr.reload()
    state["reloaded"] = True
    new_errors = [e for e in hypr.config_errors() if e not in errors_before]
    if new_errors:
        return undo(f"Hyprland reported: {new_errors[0][:200]}")
    if check is not None:
        deadline = time.monotonic() + wait
        while True:
            wrong = check()
            if wrong is None or time.monotonic() >= deadline:
                break
            time.sleep(0.15)
        if wrong is not None:
            return undo(wrong)
    hypr.set_autoreload_off(was_off)
    return True, "reloaded"


def update_block(name, body, before_dofile, path=HYPRLAND_LUA):
    """Write the block and make Hyprland take it the safe way (save()); on any failure
    the old file is back."""
    old = read_lua(path)
    return save({path: with_block(old, name, body, before_dofile)}, lua=path)
