#!/usr/bin/env python3
"""End to end: `bromigos keys` in a nested Hyprland nobody sees.

kwin_wayland --virtual (a compositor with no screen) hosts a nested Hyprland running the
template user config over this checkout's defaults, in a runtime directory, HOME and D-Bus
of its own: nothing reaches the desktop it's run from (no window, no reload, no
notification, no env). A kwin window rule keeps the nested Hyprland full screen at
Nest.SIZE, and the run stops at once (WrongSize) if its screen comes up at another size
(kwin 6.8 had shrunk it to 1280x720). The rule and the check are the theme previews' own
(desktop/lib/bromigos_previews.py). The defaults' autostart programs are stubs;
bromigos-widgets logs what it was asked, so a bind firing shows. Keys are typed by a
virtual keyboard (vkbd.py), which Hyprland's binds see like a real one. It checks:

  - the capture window: Hyprland's binds held back while it listens (SUPER + W reaches it,
    the panels don't toggle), Esc cancels, Backspace clears, a killed window doesn't leave
    Hyprland in the submap (the watchdog);
  - bind from the command line (no clash, a swap, a clash refused, a lockout refused) and
    from the picker in rofi (a default moved; a clash answered with Replace), each saved the
    safe way and checked in Hyprland's live table and by pressing the new keys;
  - a config Hyprland won't verify: every file back, Hyprland untouched;
  - reset: the user's hyprland.lua back byte for byte, the defaults live again;
  - the Settings app's Shortcuts page (settings_shortcuts_driver.py): its own Change…
    button opens the capture window and the keys pressed are saved, the toast's Undo, Remove,
    Reset….

Not part of `unittest discover` (it needs kwin_wayland, Hyprland, rofi and a GPU):

    python3 desktop/tests/e2e_keys_nested.py [--keep] [--shots DIR]
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
REPO = os.path.dirname(DESKTOP)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(DESKTOP, "lib"))
import bromigos_previews as PV  # noqa: E402
import vkbd  # noqa: E402

STUB = "#!/bin/sh\nexit 0\n"
STUBS = {
    "waybar": STUB, "dunst": STUB, "hypridle": STUB, "swaybg": STUB, "bromigos-windows": STUB,
    "bromigos-live": STUB, "xembedsniproxy": STUB, "bromigos-bar": STUB,
    # its monitor hook restarts swaybg: never near the desktop's own (it once found it by name)
    "bromigos-wallpaper": STUB,
    "bromigos-widgets": '#!/bin/sh\necho "$*" >> "$HOME/widgets.log"\n',
    "notify-send": '#!/bin/sh\necho "$*" >> "$HOME/notify.log"\n',
    # the session's own commands stay in the sandbox; the rest is the real CLI
    "bromigos": '#!/bin/sh\ncase "$1 $2" in "session adopt"|"session import"|"game --watch"|"wallpaper "*) exit 0;; esac\n'
                'exec @BROMIGOS@ "$@"\n',
    # a verify that fails on request (the restore test)
    "Hyprland": '#!/bin/sh\nif [ -n "$BK_FAIL_VERIFY" ] && [ "$1" = "--verify-config" ]; then\n'
                '  echo "error: injected by the test"; exit 1\nfi\nexec /usr/bin/Hyprland "$@"\n',
}
LINKS = {"bromigos-keys": "desktop/bin/bromigos-keys", "bromigos-menu": "desktop/bin/bromigos-menu",
         "bromigos-webapp": "desktop/bin/bromigos-webapp", "bromigos-setup-config": "desktop/bin/bromigos-setup-config"}


def wait_for(fn, timeout=8.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


class Nest:
    SIZE = (1600, 900)          # the virtual screen kwin hosts the nested Hyprland in; its output is this size

    def __init__(self, keep=False, shots=None):
        self.keep, self.shots = keep, shots
        self.tmp = tempfile.mkdtemp(prefix="bk-", dir="/tmp")
        self.run = os.path.join(self.tmp, "run")
        self.home = os.path.join(self.tmp, "home")
        self.stubs = os.path.join(self.tmp, "stubs")
        share = os.path.join(self.tmp, "share", "default")
        for d in (self.run, self.stubs, share, os.path.join(self.home, ".config", "hypr")):
            os.makedirs(d)
        os.chmod(self.run, 0o700)
        os.symlink(os.path.join(DESKTOP, "hypr"), os.path.join(share, "hypr"))
        built = os.path.join(REPO, "core", "target", "debug", "bromigos")   # this checkout's CLI, if built
        for name, text in STUBS.items():
            p = os.path.join(self.stubs, name)
            with open(p, "w") as f:
                f.write(text.replace("@BROMIGOS@", built if os.access(built, os.X_OK) else "/usr/bin/bromigos"))
            os.chmod(p, 0o755)
        for name, rel in LINKS.items():
            os.symlink(os.path.join(REPO, rel), os.path.join(self.stubs, name))
        with open(os.path.join(DESKTOP, "user", "hypr", "hyprland.lua")) as f:
            conf = f.read()
        conf = conf.replace('dofile("/usr/share/bromigos/default/hypr/hyprland.lua")',
                            'dofile(os.getenv("BROMIGOS_SHARE_DIR") .. "/default/hypr/hyprland.lua")')
        conf = conf.replace("bromigos = {\n", "bromigos = {\n    polkit = false,\n"
                            "    config = { xwayland = { enabled = false } },\n", 1)
        self.lua = os.path.join(self.home, ".config", "hypr", "hyprland.lua")
        with open(self.lua, "w") as f:
            f.write(conf)
        self.original = conf
        self.base = {"HOME": self.home, "XDG_RUNTIME_DIR": self.run, "LANG": "C.UTF-8",
                     "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                     "XDG_STATE_HOME": os.path.join(self.home, ".local", "state"),
                     "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
                     "BROMIGOS_SHARE_DIR": os.path.join(self.tmp, "share"),
                     "DBUS_SESSION_BUS_ADDRESS": "disabled:", "KWIN_COMPOSE": "O2",
                     **PV.NO_SEAT}                  # no login session or seat, whatever runs seatd or logind
        self.procs = []

    def start(self):
        env = dict(self.base, PATH="/usr/bin")
        env.pop("DBUS_SESSION_BUS_ADDRESS")
        PV.write_kwin_rules(self.base["XDG_CONFIG_HOME"])      # full screen: kwin 6.8 would shrink it to 1280x720
        self.kwin = subprocess.Popen(["dbus-run-session", "--", "kwin_wayland", "--virtual", "--width", str(self.SIZE[0]),
                                      "--height", str(self.SIZE[1]), "--socket", "kw", "--no-lockscreen", "--no-global-shortcuts"],
                                     env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
        if not wait_for(lambda: os.path.exists(os.path.join(self.run, "kw")), 15):
            raise RuntimeError("kwin_wayland --virtual didn't start")
        # The socket appears before KWin finishes initialising EGL. Hyprland needs
        # dmabuf, so wait for that global rather than racing compositor startup.
        if shutil.which("wayland-info"):
            def dmabuf_ready():
                try:
                    info = subprocess.run(["wayland-info"], env=dict(env, WAYLAND_DISPLAY="kw"),
                                          capture_output=True, text=True, timeout=3)
                    return "zwp_linux_dmabuf_v1" in info.stdout
                except subprocess.TimeoutExpired:
                    return False
            if not wait_for(dmabuf_ready, 15):
                raise RuntimeError("the virtual compositor did not advertise dmabuf")
        else:
            time.sleep(1)
        env = dict(self.base, WAYLAND_DISPLAY="kw", PATH=f"{self.stubs}:/usr/bin", HYPRLAND_NO_SD_VARS="1",
                   AQ_FORCE_LINEAR_BLIT="0")
        self.log = open(os.path.join(self.tmp, "hyprland.out"), "w")
        self.hypr = subprocess.Popen(["/usr/bin/Hyprland", "-c", self.lua], env=env, stdout=self.log,
                                     stderr=subprocess.STDOUT, start_new_session=True)

        def sig():
            d = os.path.join(self.run, "hypr")
            for n in (os.listdir(d) if os.path.isdir(d) else []):
                if os.path.exists(os.path.join(d, n, ".socket.sock")):
                    return n
            return None
        self.sig = wait_for(sig, 20)
        if not self.sig:
            raise RuntimeError("the nested Hyprland didn't start (see hyprland.out)")
        self.env = dict(self.base, WAYLAND_DISPLAY="wayland-1", HYPRLAND_INSTANCE_SIGNATURE=self.sig,
                        PATH=f"{self.stubs}:/usr/bin", GDK_BACKEND="wayland")
        if not wait_for(lambda: "WAYLAND-1" in self.ctl("monitors"), 15):
            raise RuntimeError("the nested Hyprland has no output")
        PV.wait_for_size(self.ctl, self.SIZE)                   # WrongSize: every check after it would be off
        self.kb = vkbd.VirtualKeyboard(os.path.join(self.run, "wayland-1"))
        time.sleep(0.5)

    def stop(self):
        for p in [*self.procs, getattr(self, "hypr", None), getattr(self, "kwin", None)]:
            if p is not None and p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    pass
        for p in [getattr(self, "hypr", None), getattr(self, "kwin", None)]:
            if p is None:
                continue
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                pass

            def group_alive(pgid=p.pid):           # kwin outlives dbus-run-session a moment
                try:
                    os.killpg(pgid, 0)
                    return True
                except OSError:
                    return False
            if wait_for(lambda: not group_alive(), 5) is False:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
        if not self.keep:
            shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers
    def ctl(self, *args):
        r = subprocess.run(["hyprctl", *args], env=self.env, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()

    def binds(self):
        out = {}
        for b in json.loads(self.ctl("binds", "-j") or "[]"):
            if b.get("submap") or b.get("release"):
                continue
            mods = [n for n, bit in (("SUPER", 64), ("ALT", 8), ("CTRL", 4), ("SHIFT", 1)) if b["modmask"] & bit]
            out.setdefault(" + ".join(mods + [b["key"].upper()]), []).append(b.get("description", ""))
        return out

    def bound(self, keys, needle):
        return any(needle in d for d in self.binds().get(keys, []))

    def submap(self):
        return self.ctl("submap")

    def keys(self, *args, extra_env=None, **kw):
        env = dict(self.env, **(extra_env or {}))
        return subprocess.run(["bromigos-keys", *args], env=env, capture_output=True, text=True, timeout=60, **kw)

    def spawn(self, *args):
        p = subprocess.Popen(["bromigos-keys", *args], env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.procs.append(p)
        return p

    def layer(self, namespace):
        try:
            doc = json.loads(self.ctl("layers", "-j") or "{}")
        except ValueError:
            return False
        for mon in doc.values():
            for level in mon.get("levels", {}).values():
                if any(l.get("namespace") == namespace for l in level):
                    return True
        return False

    def widgets_log(self):
        try:
            with open(os.path.join(self.home, "widgets.log")) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def shot(self, name):
        if not self.shots:
            return
        os.makedirs(self.shots, exist_ok=True)
        subprocess.run(["grim", os.path.join(self.shots, name + ".png")], env=self.env, capture_output=True)

    def read(self, rel):
        try:
            with open(os.path.join(self.home, rel)) as f:
                return f.read()
        except FileNotFoundError:
            return None


class Run:
    def __init__(self):
        self.results = []

    def check(self, name, ok, detail=""):
        self.results.append((name, bool(ok), detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""), flush=True)
        return ok


def capture_started(n, p):
    return wait_for(lambda: n.submap() == "bromigos-capture" and n.layer("bromigos-keys") or p.poll() is not None, 10)


def scenarios(n, r):
    kb = n.kb
    # the defaults are live, and a bind fires
    r.check("defaults live: SUPER + SPACE opens the menu", n.bound("SUPER + SPACE", "bromigos-menu"))
    kb.combo("SUPER + W")
    r.check("a default fires: SUPER + W toggles the panels",
            wait_for(lambda: "toggle all" in n.widgets_log(), 3), n.widgets_log())

    # 1. the capture window holds Hyprland's binds back
    before = len(n.widgets_log())
    p = n.spawn("capture", "--for", "Test")
    r.check("capture: Hyprland enters the submap, the window is up", capture_started(n, p), n.submap())
    n.kb.key(vkbd.MODS["SUPER"][0], True)
    n.kb.modifiers(64)
    n.kb.key(vkbd.MODS["SHIFT"][0], True)
    n.kb.modifiers(65)
    time.sleep(0.4)
    n.shot("capture-holding")
    n.kb.key(vkbd.MODS["SHIFT"][0], False)
    n.kb.modifiers(64)
    n.kb.key(vkbd.KEYS["W"], True)
    time.sleep(0.3)
    n.shot("capture-combo")
    n.kb.key(vkbd.KEYS["W"], False)
    n.kb.key(vkbd.MODS["SUPER"][0], False)
    n.kb.modifiers(0)
    out, err = p.communicate(timeout=10)
    got = json.loads(out) if out.strip() else {}
    r.check("capture: SUPER + W reached the window", got.get("keys") == "SUPER + W", (p.returncode, out, err))
    r.check("capture: SUPER + W's own bind didn't fire", len(n.widgets_log()) == before, n.widgets_log()[before:])
    r.check("capture: Hyprland back out of the submap", wait_for(lambda: n.submap() == "default", 3), n.submap())
    kb.combo("SUPER + W")
    r.check("after the capture the binds work again", wait_for(lambda: len(n.widgets_log()) > before, 3))

    # 2. Esc cancels
    p = n.spawn("capture", "--for", "Test")
    capture_started(n, p)
    kb.tap("ESCAPE")
    p.communicate(timeout=10)
    r.check("capture: Esc cancels (exit 1)", p.returncode == 1, p.returncode)
    r.check("capture: Esc leaves the submap", wait_for(lambda: n.submap() == "default", 3), n.submap())

    # 3. Backspace clears, then another combo
    p = n.spawn("capture", "--for", "Test")
    capture_started(n, p)
    kb.combo("SUPER + CTRL + K")
    kb.tap("BACKSPACE")
    kb.combo("ALT + J")
    out, _ = p.communicate(timeout=10)
    got = json.loads(out) if out.strip() else {}
    r.check("capture: Backspace clears, the next combo is taken", got.get("keys") == "ALT + J", out)

    # 4. a killed window can't leave Hyprland in the submap
    p = n.spawn("capture", "--for", "Test")
    capture_started(n, p)
    r.check("capture: in the submap before the kill", n.submap() == "bromigos-capture", n.submap())
    os.kill(p.pid, signal.SIGKILL)
    p.wait()
    r.check("capture: killed with SIGKILL, the watchdog leaves the submap",
            wait_for(lambda: n.submap() == "default", 5), n.submap())

    # 5. bind a command by pressing its keys (no clash)
    p = n.spawn("bind", "--exec", f"touch {n.home}/fired-custom", "--what", "Custom test")
    capture_started(n, p)
    kb.combo("SUPER + CTRL + J")
    out, err = p.communicate(timeout=30)
    r.check("bind --exec: saved", p.returncode == 0, (out, err))
    r.check("bind --exec: live in Hyprland", n.bound("SUPER + CTRL + J", "fired-custom"), n.binds().get("SUPER + CTRL + J"))
    r.check("bind --exec: no config errors", n.ctl("configerrors").strip() == "", n.ctl("configerrors"))
    r.check("bind --exec: auto-reload is back on", '"bool": false' in n.ctl("getoption", "misc:disable_autoreload", "-j"))
    kb.combo("SUPER + CTRL + J")
    r.check("bind --exec: the new keys run it", wait_for(lambda: os.path.exists(os.path.join(n.home, "fired-custom")), 3))
    lua = n.read(".config/hypr/hyprland.lua")
    r.check("bind --exec: written in the marked block", "-- >>> bromigos keys\n" in lua and "fired-custom" in lua)
    sc = subprocess.run([sys.executable, os.path.join(REPO, "widgets", "keybinds.py")], env=n.env,
                        capture_output=True, text=True, timeout=30).stdout
    r.check("SHORTCUTS lists it under YOURS by its name", "YOURS" in sc and "Custom test" in sc, sc[:400])

    # 6. a swap from the command line
    res = n.keys("bind", "SUPER + W", "--default", "SUPER + SPACE", "--swap")
    r.check("bind --swap: saved", res.returncode == 0, (res.stdout, res.stderr))
    r.check("bind --swap: SUPER + W opens the menu", n.bound("SUPER + W", "bromigos-menu"), n.binds().get("SUPER + W"))
    r.check("bind --swap: SUPER + SPACE toggles the panels", n.bound("SUPER + SPACE", "toggle all"),
            n.binds().get("SUPER + SPACE"))
    before = len(n.widgets_log())
    kb.combo("SUPER + SPACE")
    r.check("bind --swap: pressing SUPER + SPACE toggles the panels", wait_for(lambda: len(n.widgets_log()) > before, 3))

    # 7. refused without being asked
    res = n.keys("bind", "SUPER + D", "--exec", "foo")
    r.check("a taken key is refused without --swap/--replace", res.returncode == 1 and "taken" in res.stderr, res.stderr)
    res = n.keys("unbind", "SUPER + W")
    r.check("the menu's last key isn't unbound without --yes", res.returncode == 1 and "menu" in res.stderr, res.stderr)

    # 8. a config Hyprland won't verify: everything back
    lua_before, rec_before, binds_before = n.read(".config/hypr/hyprland.lua"), n.read(".config/bromigos/keys.toml"), n.binds()
    res = n.keys("bind", "SUPER + CTRL + U", "--exec", "bar", extra_env={"BK_FAIL_VERIFY": "1"})
    r.check("verify fails: not saved", res.returncode == 1 and "didn't accept" in res.stderr, res.stderr)
    r.check("verify fails: hyprland.lua byte for byte as before", n.read(".config/hypr/hyprland.lua") == lua_before)
    r.check("verify fails: keys.toml as before", n.read(".config/bromigos/keys.toml") == rec_before)
    r.check("verify fails: Hyprland's binds as before", n.binds() == binds_before)
    r.check("verify fails: auto-reload back on", '"bool": false' in n.ctl("getoption", "misc:disable_autoreload", "-j"))

    # 9. the picker in rofi: move a default
    p = n.spawn()
    r.check("picker: rofi is up", wait_for(lambda: n.layer("rofi") or p.poll() is not None, 15))
    time.sleep(0.5)
    kb.type("default storage")
    time.sleep(0.4)
    n.shot("picker")
    kb.tap("RETURN")
    capture_started(n, p)
    n.shot("picker-capture")
    kb.combo("SUPER + CTRL + D")
    out, err = p.communicate(timeout=30)
    r.check("picker: a default moved by pressing its keys", p.returncode == 0, (out, err))
    r.check("picker: SUPER + CTRL + D toggles storage", n.bound("SUPER + CTRL + D", "toggle storage"),
            n.binds().get("SUPER + CTRL + D"))
    r.check("picker: SUPER + D is free", "SUPER + D" not in n.binds(), n.binds().get("SUPER + D"))

    # 10. a clash answered in rofi
    p = n.spawn("bind", "--exec", f"touch {n.home}/fired-clash", "--what", "Clash test")
    capture_started(n, p)
    kb.combo("SUPER + B")
    r.check("clash: rofi asks", wait_for(lambda: n.layer("rofi") or p.poll() is not None, 10))
    time.sleep(0.4)
    n.shot("clash")
    kb.type("replace")
    kb.tap("RETURN")
    out, err = p.communicate(timeout=30)
    r.check("clash: replaced and saved", p.returncode == 0, (out, err))
    kb.combo("SUPER + B")
    r.check("clash: SUPER + B runs the new command",
            wait_for(lambda: os.path.exists(os.path.join(n.home, "fired-clash")), 3))
    r.check("clash: the workbench default is off", not n.bound("SUPER + B", "workbench"), n.binds().get("SUPER + B"))

    lst = n.keys("list")
    r.check("list: shows yours and the default turned off",
            "Custom test" in lst.stdout and "Workbench panel" in lst.stdout and "OFF" in lst.stdout, lst.stdout)

    # 11. reset: everything as it was
    res = n.keys("reset", "--yes")
    r.check("reset: saved", res.returncode == 0, (res.stdout, res.stderr))
    r.check("reset: hyprland.lua byte for byte as it started", n.read(".config/hypr/hyprland.lua") == n.original)
    r.check("reset: the defaults are live again", n.bound("SUPER + SPACE", "bromigos-menu") and
            n.bound("SUPER + D", "toggle storage") and n.bound("SUPER + W", "toggle all"))

    # 12. the Settings app's Shortcuts page: its own Change…, Undo, Remove and Reset… buttons
    n.keys("bind", "SUPER + ALT + T", "--exec", "kitty -e btop", "--what", "System monitor")
    env = dict(n.env, PYTHONPATH=os.pathsep.join([os.path.join(REPO, "lib"), os.path.join(REPO, "widgets")]))
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "settings_shortcuts_driver.py"),
                          os.path.join(DESKTOP, "settings")], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    n.procs.append(p)
    r.check("Settings: Change… opens the capture window", capture_started(n, p) and p.poll() is None,
            (n.submap(), p.poll()))
    time.sleep(0.3)
    n.shot("settings-capture")
    kb.combo("SUPER + CTRL + M")
    try:
        out, err = p.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out, err = p.communicate()
    steps = [ln for ln in out.splitlines() if ln.startswith(("PASS", "FAIL"))]
    for ln in steps:
        r.check("Settings: " + ln.split(" ", 1)[1].split(" | ")[0], ln.startswith("PASS"), ln)
    r.check("Settings: every step ran", len(steps) == 4, (out[-800:], err[-800:]))
    r.check("no config errors at the end", n.ctl("configerrors").strip() == "", n.ctl("configerrors"))


def main():
    keep = "--keep" in sys.argv
    shots = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    for tool in ("kwin_wayland", "dbus-run-session", "Hyprland", "rofi", "lua"):
        if not shutil.which(tool):
            print(f"SKIP: needs {tool}")
            return 0
    n = Nest(keep, shots)
    r = Run()
    try:
        n.start()
        scenarios(n, r)
    finally:
        n.stop()
        if keep:
            print(f"kept: {n.tmp}")
    failed = [x for x in r.results if not x[1]]
    print(f"\n{len(r.results) - len(failed)}/{len(r.results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
