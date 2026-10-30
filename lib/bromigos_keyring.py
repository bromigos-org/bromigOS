"""bromigos_keyring: the keyring that keeps sign-ins, and the login that unlocks it.

bromigOS keeps sign-ins (`bromigos login`, `bromigos account`, the widgets' accounts) in the
login keyring, through the Secret Service: the D-Bus name org.freedesktop.secrets. Its
provider is oo7 (the `oo7` package: oo7-daemon and pam_oo7.so). Every session starts the
daemon, and PAM hands it the login password, so the keyring is unlocked without a prompt:

    auth      `-auth      optional     pam_oo7.so`             keeps the password you typed
    session   `-session   optional     pam_oo7.so auto_start`  unlocks the keyring with it
    password  `-password  optional     pam_oo7.so`             a new password re-encrypts it to match

The `-` before a line makes PAM skip it quietly when the module isn't installed, and
`optional` means it never decides whether you get in. They go in /etc/pam.d/login (a text
console login), /etc/pam.d/sddm (the login screen) and /etc/pam.d/passwd.

    K.status()                 everything below, for `bromigos keyring status`
    K.service()                {"bus", "running", "activatable", "provider", "locked"}
    K.ready()                  None, or why a sign-in can't be kept here, in plain words
    K.explain(error)           plain words for a keyring error, never a raw D-Bus error
    K.pam_plan(root="/")       [{"name", "path", "exists", "missing", "new", "text", "note"}]
    K.pam_apply(plan)          writes each changed file in place (as root), atomically
    K.pam_edit(text, kinds)    the text with the missing lines added after their kind's last line
    K.kwallet_api(home)        True/False/None: KWallet's own Secret Service is on, off, unset
    K.kwallet_api_off(home)    turns it off in ~/.config/kwalletrc (KWallet itself stays)

Command line: bin/bromigos-keyring (`bromigos keyring status|setup`).
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

NAME = "org.freedesktop.secrets"
MODULE = "pam_oo7.so"
PAM_DIR = "etc/pam.d"
MODULE_DIRS = ("usr/lib/security", "lib/security", "usr/lib64/security")

# (kind, arguments) per file. login: the text console; sddm: the login screen; passwd: a
# password change re-encrypts the keyring to match.
WANT = {
    "login": (("auth", ""), ("session", "auto_start")),
    "sddm": (("auth", ""), ("session", "auto_start")),
    "passwd": (("password", ""),),
}
# login must exist (it's util-linux's); the others are changed only where they exist.
REQUIRED = ("login",)

PROVIDERS = {"oo7-daemon": "oo7", "gnome-keyring-d": "gnome-keyring", "gnome-keyring-daemon": "gnome-keyring",
             "ksecretd": "KWallet", "kwalletd6": "KWallet", "kwalletd5": "KWallet", "keepassxc": "KeePassXC"}

INSTALL = "sudo pacman -S bromigos/oo7"


class PamError(Exception):
    """A PAM file this module won't change, in plain words."""


# ------------------------------------------------------------------ PAM files
def _fields(line):
    """(kind without its '-', control, module, arguments) of a PAM line, or None for a
    comment, a blank line or one this parser doesn't read. A control can be [a=b c=d]."""
    s = line.split("#", 1)[0].strip()
    if not s:
        return None
    parts = s.split(None, 1)
    if len(parts) < 2:
        return None
    kind, rest = parts[0], parts[1].strip()
    if rest.startswith("["):
        end = rest.find("]")
        if end < 0:
            return None
        control, rest = rest[:end + 1], rest[end + 1:].strip()
    else:
        parts = rest.split(None, 1)
        control, rest = parts[0], (parts[1] if len(parts) > 1 else "")
    parts = rest.split(None, 1)
    if not parts:
        return None
    module, args = parts[0], (parts[1].split() if len(parts) > 1 else [])
    return kind.lstrip("-").lower(), control, module, args


def _is_module(module, name=MODULE):
    return module == name or module.endswith("/" + name)


def pam_has(text, kind, module=MODULE):
    """Whether a line of this kind (auth, session, password) runs the module, with or
    without the '-', as written by bromigOS or by hand."""
    for line in text.splitlines():
        f = _fields(line)
        if f and f[0] == kind and _is_module(f[2], module):
            return True
    return False


def pam_line(kind, args=""):
    """The line bromigOS adds: '-auth      optional     pam_oo7.so', in Arch's columns."""
    return f"{'-' + kind:<11}{'optional':<13}{MODULE}{(' ' + args) if args else ''}"


def pam_edit(text, kinds):
    """The text with a line for each (kind, args) it lacks, after the last line of that
    kind (an include of the system's stack, usually). Lines already there, the '-' or not,
    and every other line are kept as they are. Raises PamError when a kind has no line to
    follow, rather than guess where it goes."""
    lines = text.splitlines()
    for kind, args in kinds:
        if pam_has("\n".join(lines), kind):
            continue
        last = None
        for i, line in enumerate(lines):
            f = _fields(line)
            if f and f[0] == kind:
                last = i
        if last is None:
            raise PamError(f"it has no {kind} lines, so bromigOS doesn't know where {MODULE} goes")
        lines.insert(last + 1, pam_line(kind, args))
    out = "\n".join(lines)
    return out + "\n" if text.endswith("\n") or not text else out


def _check_edit(old, new):
    """The new text is the old one with only bromigOS's lines added: anything else is a bug,
    and a broken PAM file can lock everyone out, so it stops the write."""
    ours = {pam_line(k, a) for kinds in WANT.values() for k, a in kinds}
    kept = [line for line in new.splitlines() if line not in ours or line in old.splitlines()]
    if kept != old.splitlines():
        raise PamError("the edit would change more than bromigOS's own lines; nothing was written")
    for line in set(new.splitlines()) - set(old.splitlines()):
        if _fields(line) is None:
            raise PamError(f"the edit would leave a line PAM can't read ({line!r}); nothing was written")


def module_installed(root="/"):
    return any(os.path.exists(os.path.join(root, d, MODULE)) for d in MODULE_DIRS)


def pam_plan(root="/"):
    """What each PAM file needs: [{"name", "path", "exists", "missing": [kind], "new": the
    text to write or None, "text": the text now, "note": why it's left alone, or ""}]."""
    plan = []
    for name, kinds in WANT.items():
        path = os.path.join(root, PAM_DIR, name)
        item = {"name": name, "path": path, "exists": os.path.isfile(path), "missing": [], "new": None,
                "text": None, "note": ""}
        plan.append(item)
        if not item["exists"]:
            if name in REQUIRED:
                item["note"] = f"{path} isn't there: the text console login has no PAM file to add {MODULE} to"
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            item["note"] = f"can't read it: {getattr(e, 'strerror', None) or e}"
            continue
        item["text"] = text
        item["missing"] = [k for k, _ in kinds if not pam_has(text, k)]
        if not item["missing"]:
            continue
        try:
            new = pam_edit(text, kinds)
            _check_edit(text, new)
        except PamError as e:
            item["note"] = str(e)
            continue
        item["new"] = new
    return plan


def pam_apply(plan):
    """Write each planned file: a new file beside it with the same owner and mode, then a
    rename over it, so a reader sees the old file or the new one, never half of one.
    Returns the paths written. Needs to run as root for /etc."""
    done = []
    for item in plan:
        if not item.get("new"):
            continue
        path = item["path"]
        with open(path, encoding="utf-8") as f:
            if f.read() != item["text"]:
                raise PamError(f"{path} changed while bromigOS was reading it; nothing was written")
        st = os.stat(path)
        fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".bromigos", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(item["new"])
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, stat.S_IMODE(st.st_mode))
            if os.geteuid() == 0:
                os.chown(tmp, st.st_uid, st.st_gid)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        done.append(path)
    return done


# ------------------------------------------------------------------ KWallet's Secret Service
def _kwalletrc(home=None):
    config = os.environ.get("XDG_CONFIG_HOME") if home is None else None
    return os.path.join(config or os.path.join(home or os.path.expanduser("~"), ".config"), "kwalletrc")


def kwallet_api(home=None):
    """KWallet's own Secret Service (kwalletrc [org.freedesktop.secrets] apiEnabled):
    True or False as set, None when unset (KWallet then offers it, and can take the name
    from oo7 when it starts first)."""
    try:
        with open(_kwalletrc(home), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    section = None
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1]
        elif section == NAME and s.split("=", 1)[0].strip() == "apiEnabled" and "=" in s:
            return s.split("=", 1)[1].strip().lower() == "true"
    return None


def kwallet_api_edit(text):
    """kwalletrc's text with apiEnabled=false in [org.freedesktop.secrets]; the rest kept."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == f"[{NAME}]"), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{NAME}]", "apiEnabled=false"]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        for i in range(start + 1, end):
            if lines[i].split("=", 1)[0].strip() == "apiEnabled":
                lines[i] = "apiEnabled=false"
                break
        else:
            lines.insert(start + 1, "apiEnabled=false")
    return "\n".join(lines) + "\n"


def kwallet_api_off(home=None):
    """Turn KWallet's Secret Service off, so oo7 alone answers to org.freedesktop.secrets.
    KWallet's own interface, which KDE apps use, stays. Returns True when it changed."""
    if kwallet_api(home) is False:
        return False
    path = _kwalletrc(home)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".bromigos-new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(kwallet_api_edit(text))
    os.replace(tmp, path)
    return True


# ------------------------------------------------------------------ the running service
class SessionBus:
    """The session bus, asked through busctl (systemd's), without starting anything."""

    def _busctl(self, *args, timeout=5):
        if not shutil.which("busctl"):
            raise OSError("busctl isn't installed")
        try:
            r = subprocess.run(["busctl", "--user", "--json=short", *args], capture_output=True, text=True,
                               timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise OSError("the session bus didn't answer") from None
        if r.returncode:
            raise OSError((r.stderr.strip().splitlines() or ["busctl failed"])[-1])
        try:
            return json.loads(r.stdout)["data"]
        except (ValueError, KeyError, TypeError):
            raise OSError("busctl gave an answer bromigOS can't read") from None

    def _dbus(self, method, *args):
        return self._busctl("call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                            method, *(["s" * len(args), *args] if args else []))[0]

    def has_owner(self):
        return bool(self._dbus("NameHasOwner", NAME))

    def activatable(self):
        return NAME in (self._dbus("ListActivatableNames") or [])

    def owner(self):
        """The running provider's process name (oo7-daemon, gnome-keyring-d, ksecretd…)."""
        pid = int(self._dbus("GetConnectionUnixProcessID", NAME))
        with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
            return f.read().strip()

    def locked(self):
        """The default keyring's Locked; raises OSError when there's no default keyring yet."""
        return bool(self._busctl("get-property", NAME, "/org/freedesktop/secrets/aliases/default",
                                 "org.freedesktop.Secret.Collection", "Locked"))


def _activation_provider(root="/"):
    """Who D-Bus would start for the name: oo7, gnome-keyring, or "unknown"."""
    for d in ("usr/share/dbus-1/services", "usr/local/share/dbus-1/services"):
        try:
            with open(os.path.join(root, d, NAME + ".service"), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        if "gnome-keyring" in text:
            return "gnome-keyring"
        if "dbus-org.freedesktop.secrets" in text or "oo7" in text:
            return "oo7"
        return "unknown"
    return None


def service(bus=None):
    """The Secret Service as the session bus sees it, without starting it:
    {"bus": reachable, "running", "activatable", "provider": oo7|gnome-keyring|KWallet|…|None,
     "locked": the default keyring is locked (None: unknown, or no default keyring yet),
     "error": why the bus couldn't be asked}."""
    bus = bus or SessionBus()
    out = {"bus": False, "running": False, "activatable": False, "provider": None, "locked": None, "error": ""}
    try:
        out["running"] = bus.has_owner()
        out["bus"] = True
        out["activatable"] = bus.activatable()
    except OSError as e:
        out["error"] = str(e)
        return out
    if out["running"]:
        try:
            comm = bus.owner()
            out["provider"] = PROVIDERS.get(comm, comm)
        except (OSError, ValueError):
            pass
        try:
            out["locked"] = bus.locked()
        except OSError:
            out["locked"] = None
    elif out["activatable"]:
        out["provider"] = _activation_provider()
    return out


def libsecret():
    """Whether this computer can talk to a keyring: libsecret's bindings or secret-tool."""
    try:
        import gi
        gi.require_version("Secret", "1")
        from gi.repository import Secret  # noqa: F401
        return True
    # AttributeError: a `gi` with no PyGObject, only another package's overrides in it
    # (at-spi2-core's Atspi.py makes one)
    except (ImportError, ValueError, AttributeError):
        return bool(shutil.which("secret-tool"))


def can_prompt(env=None, session_env=None):
    """Whether the keyring could show its password window: a desktop in this terminal's
    environment, or in the one the session's services start in (where the window opens)."""
    env = os.environ if env is None else env
    if env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"):
        return True
    if session_env is None:
        try:
            r = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True,
                               timeout=5, stdin=subprocess.DEVNULL)
            session_env = r.stdout if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            session_env = ""
    return any(line.startswith(("WAYLAND_DISPLAY=", "DISPLAY=")) for line in session_env.splitlines())


def _credential(home=None):
    """oo7's systemd credential (oo7.keyring-encryption-password), which unlocks it without PAM."""
    home = home or os.path.expanduser("~")
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.exists(os.path.join(config, "credstore.encrypted", "oo7.keyring-encryption-password"))


NO_KEYRING = ("No keyring is running, so a sign-in can't be kept. Install oo7, bromigOS's keyring "
              f"({INSTALL}), run bromigos keyring setup, then sign out and in again. The manual "
              "explains it under Your Bromigos account › Your keyring.")
NO_BUS = ("Can't reach a keyring: this terminal has no session bus. Sign in on this computer (the desktop "
          "or a text console starts one), then try again.")
LOCKED = ("Your keyring is locked, and there's no desktop here to ask for its password. Sign out and in "
          "again so your login password unlocks it (bromigos keyring setup turns that on), or run this in "
          "your desktop session.")


def ready(svc=None, has_libsecret=None, prompt=None, credential=None):
    """None when a sign-in can be kept in the keyring here, else why not and what to do, in
    plain words. Asked before a sign-in starts, so an approval isn't wasted."""
    has_libsecret = libsecret() if has_libsecret is None else has_libsecret
    if not has_libsecret:
        return "Can't reach a keyring: libsecret isn't installed. Install it (sudo pacman -S libsecret), then try again."
    svc = service() if svc is None else svc
    if not svc["bus"]:
        return NO_BUS
    if not svc["running"] and not svc["activatable"]:
        return NO_KEYRING
    if svc["running"] and svc["locked"] is False:
        return None
    # locked, no default keyring yet, or not started: storing needs the password window
    if (can_prompt() if prompt is None else prompt) or (_credential() if credential is None else credential):
        return None
    return LOCKED


def explain(error):
    """Plain words for a keyring error (a GLib error from libsecret, secret-tool's words, a
    timeout), never a raw D-Bus error name."""
    text = str(getattr(error, "message", None) or error or "")
    low = text.lower()
    if any(s in low for s in ("not activatable", "serviceunknown", "was not provided by any .service",
                              "no such name", "name has no owner")):
        return NO_KEYRING
    if any(s in low for s in ("cannot autolaunch", "could not connect", "failed to connect to", "no session bus",
                              "dbus_session_bus_address")):
        return NO_BUS
    if any(s in low for s in ("dismiss", "cancel")):
        return "The keyring's password window was closed, so nothing was stored. Try again and unlock the keyring."
    if "locked" in low or "unlock" in low or "prompter" in low or "no prompt backend" in low:
        return LOCKED               # it had to ask for the password, and nothing could show the window
    if "timed out" in low or "timeout" in low or "no reply" in low:
        return ("The keyring didn't answer (it may be waiting for its password in a window that can't show "
                "here), so nothing was stored. Try again in your desktop session.")
    detail = re.sub(r"^(g-[\w-]+-quark:\s*)?(GDBus\.Error:)?([\w.]+\.Error\.\w+:\s*)?", "", text).strip()
    detail = re.sub(r"\s*\(\d+\)$", "", detail)
    return f"The keyring couldn't store it ({detail or 'no reason given'}). bromigos keyring status checks the keyring."


# ------------------------------------------------------------------ status
def kwallet_installed(root="/"):
    return any(os.path.exists(os.path.join(root, "usr/bin", b)) for b in ("ksecretd", "kwalletd6"))


def status(root="/", home=None, svc=None):
    """`bromigos keyring status`: {"ok", "service", "libsecret", "module", "pam": [...],
    "kwallet": {"installed", "secret_service"}, "problems": [plain words, each with its fix]}."""
    svc = service() if svc is None else svc
    plan = pam_plan(root)
    installed = module_installed(root)
    kwallet = {"installed": kwallet_installed(root), "secret_service": kwallet_api(home)}
    problems = []
    if not installed:
        problems.append(f"oo7 isn't installed: {INSTALL}, then bromigos keyring setup")
    if svc["running"] and svc["provider"] not in (None, "oo7"):
        problems.append(f"{svc['provider']} answers for the keyring, not oo7: bromigos keyring setup, "
                        "then sign out and in again")
    if svc["bus"] and not svc["running"] and not svc["activatable"]:
        problems.append("no keyring is running, and none can start: " + INSTALL)
    for p in plan:
        if p["exists"] and p["missing"] and not p["note"]:
            what = "carry a new password over to the keyring" if p["name"] == "passwd" else "unlock the keyring"
            problems.append(f"{p['path']} doesn't {what} (no {' or '.join(p['missing'])} line for oo7): "
                            "bromigos keyring setup")
        elif p["note"] and (p["exists"] or p["name"] in REQUIRED):
            problems.append(f"{p['path']}: {p['note']}")
    if kwallet["installed"] and kwallet["secret_service"] is not False:
        problems.append("KWallet's own Secret Service is on, so it can take the keyring's name from oo7: "
                        "bromigos keyring setup")
    if svc["running"] and svc["locked"]:
        problems.append("the keyring is locked: sign out and in again, so your login password unlocks it")
    return {"ok": not problems, "service": svc, "libsecret": libsecret(), "module": installed,
            "pam": [{k: p[k] for k in ("name", "path", "exists", "missing", "note")} for p in plan],
            "kwallet": kwallet, "problems": problems}


def _say_status(st, say=print):
    svc = st["service"]
    if not svc["bus"]:
        say(f"Keyring: can't tell, there's no session bus here ({svc['error'] or 'none'}).")
    elif svc["running"]:
        lock = {True: "locked", False: "unlocked", None: "with no default keyring yet"}[svc["locked"]]
        say(f"Keyring: {svc['provider'] or 'a Secret Service'} is running, {lock}.")
    elif svc["activatable"]:
        say(f"Keyring: {svc['provider'] or 'a Secret Service'} starts when something needs it.")
    else:
        say("Keyring: none is running, and none can start.")
    say(f"oo7: {'installed' if st['module'] else 'not installed'}.")
    for p in st["pam"]:
        if p["exists"]:
            done = "a new password carries over to the keyring." if p["name"] == "passwd" else \
                "this login unlocks the keyring."
            say(f"{p['path']}: " + (done if not p["missing"] else f"no {' or '.join(p['missing'])} line for oo7."))
    if st["kwallet"]["installed"]:
        say("KWallet: " + ("its own Secret Service is off, so oo7 alone answers." if
                           st["kwallet"]["secret_service"] is False else
                           "its own Secret Service is on, and it can take the keyring's name from oo7."))
    if st["ok"]:
        say("All set: your login unlocks the keyring.")
    for p in st["problems"]:
        say(f"To fix: {p}")


def pam_step(root="/", dry=False, say=print):
    """The PAM half of setup, as root: plan, say, write. 0 done or nothing to do (a file
    left alone is said, not an error), 3 when a write failed."""
    plan = pam_plan(root)
    for p in plan:
        if p["note"] and (p["exists"] or p["name"] in REQUIRED):
            say(f"{p['path']}: left alone: {p['note']}")
    todo = [p for p in plan if p["new"]]
    if not todo:
        say("PAM: every login already unlocks the keyring.")
        return 0
    for p in todo:
        added = [pam_line(k, a) for k, a in WANT[p["name"]] if k in p["missing"]]
        say(f"{p['path']}: {'would add' if dry else 'adding'}: " + "; ".join(added))
    if dry:
        return 0
    try:
        pam_apply(todo)
    except (OSError, PamError) as e:
        say(f"PAM: stopped, nothing more was changed: {getattr(e, 'strerror', None) or e}")
        return 3
    return 0


def _helper():
    """This command's own path, for sudo to run its root half (an installed copy, or a
    checkout's bin/ when run from one)."""
    me = os.path.realpath(sys.argv[0]) if sys.argv and os.path.basename(sys.argv[0]) == "bromigos-keyring" else ""
    return me or "/usr/lib/bromigos/bin/bromigos-keyring"


def setup(root="/", dry=False, say=print, home=None, run=subprocess.run, interactive=None):
    """`bromigos keyring setup`: the PAM lines (through sudo unless this is root) and
    KWallet's own Secret Service off. Returns 0 when done, 75 when it can't finish yet
    (oo7 isn't installed, or sudo didn't run: the next bromigos update tries again)."""
    rc = 0
    if not module_installed(root):
        say(f"oo7 isn't installed yet ({INSTALL}): the login lines go in once it is.")
        rc = 75
    elif not any(p["new"] for p in pam_plan(root)):
        rc = pam_step(root, dry, say)
    elif dry or root != "/" or os.geteuid() == 0:
        rc = pam_step(root, dry, say)
        rc = 75 if rc == 3 else rc
    else:
        # on a terminal sudo may ask for the password; without one (an unattended install)
        # only sudo that needs none (-n), else the next update tries again
        interactive = sys.stdin.isatty() if interactive is None else interactive
        if not shutil.which("sudo"):
            say("PAM: changing /etc/pam.d needs sudo, and it isn't installed.")
            rc = 75
        else:
            if interactive:
                say("PAM: so your login unlocks the keyring, sudo asks for your password to change /etc/pam.d.")
            r = run(["sudo", *([] if interactive else ["-n"]), sys.executable, "-I", _helper(), "pam"])
            if r.returncode:
                say("PAM: unchanged (sudo didn't run, or the change stopped). Run bromigos keyring setup in a "
                    "terminal; the next bromigos update tries again too.")
                rc = 75
    if not dry and kwallet_installed(root):
        try:
            if kwallet_api_off(home):
                say("KWallet: its own Secret Service is off now, so oo7 alone answers for the keyring.")
        except OSError as e:
            say(f"KWallet: couldn't change kwalletrc ({e.strerror or e}).")
            rc = rc or 75
    return rc


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="bromigos keyring", description="The keyring that keeps your sign-ins "
                                "(oo7, the Secret Service), and the login that unlocks it.")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("status", help="whether a keyring is running and unlocked, and your login unlocks it")
    s.add_argument("--json", action="store_true", help="print it as JSON")
    s.add_argument("--root", default="/", help=argparse.SUPPRESS)
    u = sub.add_parser("setup", help="make your login unlock the keyring: the PAM lines (asks sudo), and "
                       "KWallet's own Secret Service off")
    u.add_argument("--dry-run", action="store_true", help="say what it would change; change nothing")
    u.add_argument("--root", default="/", help=argparse.SUPPRESS)
    m = sub.add_parser("pam", help=argparse.SUPPRESS)          # setup's root half, run through sudo
    m.add_argument("--root", default="/")
    m.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "status":
        st = status(args.root)
        if args.json:
            print(json.dumps(st))
        else:
            _say_status(st)
        return 0 if st["ok"] else 1
    if args.cmd == "setup":
        return setup(args.root, args.dry_run)
    if args.cmd == "pam":
        if args.root == "/" and os.geteuid() != 0 and not args.dry_run:
            print("bromigos keyring pam: it changes /etc/pam.d, so it runs as root (bromigos keyring setup "
                  "runs it through sudo)", file=sys.stderr)
            return 1
        return pam_step(args.root, args.dry_run)
    p.print_help()
    return 2
