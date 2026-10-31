"""The installer's back end, the same for both front ends: reading the disks, running the
install (bromigos-iso-install --answers) and turning its output into progress.

The graphical installer runs as the live user and reaches root through sudo (the live
user has it without a password); the text installer runs as root. Either way the work is
one root command, so both installers install exactly alike.

BROMIGOS_ISO_INSTALL_EXTRA adds options to the install (the test harness's --ssh-key).
BROMIGOS_INSTALLER_FAKE=1 swaps the disks and the install for stand-ins (a recorded probe,
BROMIGOS_INSTALLER_PROBE=FILE, and a few seconds of made-up progress), for pictures and
the front ends' own tests: nothing is read from or written to a disk.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

from . import common


def _read(path):
    with open(path) as f:
        return f.read()

INSTALL = os.environ.get("BROMIGOS_ISO_INSTALL", "/usr/local/bin/bromigos-iso-install")
DISKS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "disks.py")
FAKE = bool(os.environ.get("BROMIGOS_INSTALLER_FAKE"))
STAGE = re.compile(r"^::stage (\d+) (.*)$")
ERROR = re.compile(r"^::error (.*)$")
# Secure Boot set up for the new system (bromigos-secureboot): the code that approves its key
# at the first start, for the last page
SECUREBOOT = re.compile(r"^::secureboot ([0-9]{4,8})$")
SECUREBOOT_CODE = None


def as_root(argv):
    return argv if os.geteuid() == 0 else ["sudo", "-n", *argv]


def probe():
    """The disks (disks.py probe), or a plain error in {"error": ...}."""
    if FAKE:
        path = os.environ.get("BROMIGOS_INSTALLER_PROBE")
        if path:
            return json.loads(_read(path))
        return {"firmware": "uefi", "disks": [], "other_os": False}
    try:
        r = subprocess.run(as_root([sys.executable, DISKS, "probe", "--json"]), capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": f"Reading the disks didn't finish ({e}).", "disks": []}
    if r.returncode != 0:
        return {"error": "Reading the disks failed: " + (r.stderr.strip().splitlines() or ["no reason given"])[-1], "disks": []}
    return json.loads(r.stdout)


def answers_file(doc):
    """The answers, in a file only its owner reads (the password is in it); removed when the
    install ends."""
    base = "/run/bromigos-iso" if os.geteuid() == 0 else (os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    os.makedirs(base, mode=0o700, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="answers-", suffix=".json", dir=base)
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f)
    os.chmod(path, 0o600)
    return path


class Install:
    """One install, in a thread: on_stage(pct, text), on_line(text), on_done(ok, error)."""

    def __init__(self, doc, on_stage, on_line, on_done):
        self.doc, self.on_stage, self.on_line, self.on_done = doc, on_stage, on_line, on_done
        self.pct, self.error, self.proc = 0, None, None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _stage(self, pct, text):
        self.pct = max(self.pct, pct)                     # never backwards
        self.on_stage(self.pct, text)

    def _run(self):
        if FAKE:
            return self._fake()
        path = answers_file(self.doc)
        try:
            # BROMIGOS_ISO_INSTALL_EXTRA: more of bromigos-iso-install's options (the test
            # harness's --ssh-key, so it can sign in to what it installed)
            extra = os.environ.get("BROMIGOS_ISO_INSTALL_EXTRA", "").split()
            argv = as_root([INSTALL, "--answers", path, "--no-reboot", *extra])
            self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                m = STAGE.match(line)
                if m:
                    self._stage(int(m.group(1)), m.group(2))
                    continue
                m = ERROR.match(line)
                if m:
                    self.error = self.error or m.group(1)       # the first is the cause
                    continue
                m = SECUREBOOT.match(line)
                if m:
                    global SECUREBOOT_CODE
                    SECUREBOOT_CODE = m.group(1)
                    continue
                self.on_line(line)
            rc = self.proc.wait()
        finally:
            try:
                os.unlink(path)
            except OSError:
                subprocess.run(as_root(["rm", "-f", path]))
        if rc == 0:
            self._stage(100, "bromigOS is installed")
            self.on_done(True, None)
        else:
            self.on_done(False, self.error or "The install stopped before it finished.")

    def _fake(self):
        for pct, text in ((3, "Checking your choices"), (12, "Preparing the disk"), (30, "Copying bromigOS (412 of 1180)"),
                          (68, "Copying bromigOS (1180 of 1180)"), (78, "Setting up your account and desktop"),
                          (90, "Setting up the boot menu and snapshots"), (97, "Finishing")):
            self._stage(pct, text)
            self.on_line(f"[fake] {text}")
            time.sleep(float(os.environ.get("BROMIGOS_INSTALLER_FAKE_DELAY", "0.4")))
        if os.environ.get("BROMIGOS_INSTALLER_FAKE_FAIL"):
            self.on_done(False, "Installing the system didn't finish: the disk stopped answering. "
                                "Nothing else on the disk was changed.")
            return
        self._stage(100, "bromigOS is installed")
        self.on_done(True, None)


def save_report(answers=None):
    """(path or None, plain words): a problem report on a USB drive (report.py, as root)."""
    if FAKE:
        return "/run/media/usb/bromigos-problem-fake.tar.gz", "Saved to the USB drive as bromigos-problem-fake.tar.gz."
    argv = [sys.executable, os.path.join(os.path.dirname(DISKS), "report.py")]
    path = None
    if answers:
        safe = {k: v for k, v in answers.items() if k not in ("password", "password2", "passphrase")}
        path = answers_file(safe)
        argv += ["--answers", path]
    try:
        r = subprocess.run(as_root(argv), capture_output=True, text=True, timeout=300)
        lines = r.stdout.strip().splitlines()
        return (lines[0] or None if lines else None), (lines[-1] if lines else "The report couldn't be saved.")
    finally:
        if path:
            os.unlink(path)


def preview(doc):
    """What the install will run and write, before it does: (config JSON text, credentials
    with secrets hidden, the command lines) or an error in words. Nothing touches a disk:
    answers.py only reads the disk's size and table."""
    if FAKE:
        with open(os.path.join(common.LIB, "..", "..", "share", "bromigos-iso", "archinstall.json")) as f:
            cfg = json.load(f)
        cfg.pop("_comment", None)
        creds = {"users": [{"username": doc.get("user"), "enc_password": "$6$…", "sudo": True}], "root_enc_password": "$6$…"}
        return json.dumps(cfg, indent=2), json.dumps(common.redact_creds(creds), indent=2), common.what_will_run(doc)
    path = answers_file(doc)
    out = tempfile.mkdtemp(prefix="bromigos-preview-")
    try:
        argv = as_root([sys.executable, os.path.join(os.path.dirname(os.path.dirname(DISKS)), "answers.py"),
                        "--answers", path, "--out", out])
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return None, None, ["The preview couldn't be made: " + (r.stderr.strip().splitlines() or ["no reason given"])[-1]]
        rd = subprocess.run(as_root(["cat", os.path.join(out, "config.json"), os.path.join(out, "creds.json")]),
                            capture_output=True, text=True, timeout=30).stdout
        dec = json.JSONDecoder()
        cfg, end = dec.raw_decode(rd)
        creds, _ = dec.raw_decode(rd[end:].lstrip())
        return json.dumps(cfg, indent=2), json.dumps(common.redact_creds(creds), indent=2), common.what_will_run(doc)
    finally:
        os.unlink(path)
        subprocess.run(as_root(["rm", "-rf", out]), capture_output=True)


def open_shell(where="wayland"):
    """A shell, one keystroke from either installer (Ctrl+Alt+T, F12): a terminal on the desktop."""
    for argv in (["kitty", "--title", "Shell (the installer stays open)"], ["foot"], ["xterm"]):
        try:
            subprocess.Popen(argv, start_new_session=True)
            return True
        except OSError:
            continue
    return False


def reboot():
    if FAKE:
        return
    subprocess.Popen(as_root(["systemctl", "reboot"]))


def log_path():
    return "/var/log/bromigos-iso-install.log"


def keyboard_live(kb_id, where):
    """Try the layout now: in the live desktop's Hyprland (graphical) or the text console."""
    kb = common.KEYBOARD.get(kb_id)
    if not kb or FAKE:
        return
    if where == "wayland":
        code = f'hl.config({{ input = {{ kb_layout = "{kb[3]}", kb_variant = "{kb[4]}" }} }})'
        subprocess.run(["hyprctl", "eval", code], capture_output=True)
    elif where == "console" and os.geteuid() == 0:
        subprocess.run(["loadkeys", kb[2]], capture_output=True)


# ── how the person is guided (the first step): the screen reader and the console's font ──
ORCA_MISSING = ("Orca, the screen reader, isn't on this USB stick. To hear the installer, restart and choose "
                "Install with the screen reader (speech) in the boot menu: it reads the text installer aloud.")
SPEAKUP_MISSING = ("The console's screen reader (espeakup) isn't on this USB stick. Restart and choose "
                   "Install with the screen reader (speech) in the boot menu.")


def screen_reader(on, where):
    """Start or stop the screen reader: Orca on the live desktop (as the live user, who runs
    the graphical installer), speakup's espeakup on the console (the text installer is root).
    Returns (ok, plain words: what happened, or what to do)."""
    import shutil
    if FAKE:
        return True, "Screen reader " + ("on." if on else "off.")
    if where == "wayland":
        if on and not shutil.which("orca"):
            return False, ORCA_MISSING
        subprocess.run(["gsettings", "set", "org.gnome.desktop.a11y.applications", "screen-reader-enabled",
                        "true" if on else "false"], capture_output=True)
        try:
            if on:
                subprocess.Popen(["orca", "--replace"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            else:
                subprocess.run(["orca", "--quit"], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return True, "Orca is reading the screen. Insert and the arrow keys move it; Insert+S stops it talking." if on \
            else "Orca is off."
    if on and not shutil.which("espeakup"):
        return False, SPEAKUP_MISSING
    r = subprocess.run(as_root(["systemctl", "start" if on else "stop", "espeakup.service"]), capture_output=True, text=True)
    if r.returncode != 0:
        return False, "The screen reader didn't start: " + ((r.stderr or r.stdout).strip().splitlines() or ["no reason given"])[-1]
    return True, "The screen reader is on: it reads what's on the console." if on else "The screen reader is off."


CONSOLE_FONTS = ("ter-v32n", "ter-v24b")     # bigger letters, and the text installer's usual (bromigos-iso-text-console)


def console_font(big, tty=None):
    """Bigger letters on the Linux console (setfont, terminus-font's): only a real console
    can; a terminal window or SSH has its own font. (ok, plain words)."""
    if FAKE:
        return True, "Bigger letters." if big else "The usual letters."
    if tty is None:
        try:
            tty = os.ttyname(0)
        except OSError:
            tty = ""
    if os.environ.get("TERM") != "linux" or not re.match(r"^/dev/tty\d+$", tty or ""):
        return False, ("This terminal can't change its letters from here. Make them bigger in the terminal's own "
                       "settings (often Ctrl and +).")
    r = subprocess.run(as_root(["setfont", CONSOLE_FONTS[0] if big else CONSOLE_FONTS[1]]), capture_output=True, text=True)
    if r.returncode != 0:
        return False, "The bigger letters aren't on this USB stick, so the console keeps its font."
    return True, "Bigger letters." if big else "The usual letters."
