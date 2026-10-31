#!/usr/bin/env python3
"""End to end: nothing is drawn over a working window at partial opacity, and nothing idles
over the installer, the welcome card, the welcome tour or a full-screen app.

The nested Hyprland is e2e_keys_nested.py's (kwin_wayland --virtual hosting it, a runtime
directory, HOME and D-Bus of its own; nothing reaches the desktop it's run from). This
checkout's live layer runs in it, and a plain window (overlay_probe.py) fills a tile in one
solid colour. Each check grabs the nested screen with grim and sorts the window's area into:

  clear        the window's own colour, as it paints it: nothing over it;
  covered      none of its colour: something opaque over it (the frozen screen counts, so
               the probe changes colour once an overlay is up, and only the live window has
               the new one);
  dimmed       its colour, evenly darker all over: an empty void over it at partial
               opacity, with nothing drawn in it;
  translucent  its colour, mixed unevenly: something drawn over it at partial opacity.

It checks:

  - the intercept (sign-in and unlock) at full, reduced and still motion: covered while it
    plays, clear after, and never translucent: no ghost and no card fading over the window.
    Full motion cuts back to the desktop; reduced and still can't cut (a cut is a flash),
    so the empty void lifts: dimmed, for no longer than its half second;
  - the screensaver, started by a real hypridle after a few idle seconds: covered once its
    fade-in is done, for as long as it runs; input ends it and the window is clear;
  - the welcome card, the installer, the welcome tour and a full-screen window each hold an
    idle inhibitor (Hyprland's idle_inhibit window rules, hyprland.lua): idle well past the
    timeout, no screensaver; with the window gone the screensaver starts.

hypridle runs on a private system bus with no logind, its D-Bus and logind inhibitors
ignored: only the compositor's count, and nothing of the machine running the test is read
or held.

Not part of `unittest discover` (it needs kwin_wayland, Hyprland, hypridle, grim and a GPU):

    python3 desktop/tests/e2e_overlay_nested.py [--keep] [--shots DIR] [--only intercept|screensaver|inhibit]
"""
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from e2e_keys_nested import REPO, Nest, Run, wait_for  # noqa: E402
import vptr  # noqa: E402

PROBE = os.path.join(HERE, "overlay_probe.py")
ISO_LIB = os.path.join(REPO, "iso", "profile", "airootfs", "usr", "local", "lib", "bromigos-iso")
IDLE_SECONDS = 5
CYAN = (0, 255, 255)


def classify(img, rect, rgb=CYAN):
    """(kind, exact, mixed): the share of the window's area in its own colour, and in a
    mix of it with something else."""
    x, y, w, h = rect
    reg = img[y:y + h, x:x + w].astype(np.int16)
    r, g, b = reg[..., 0], reg[..., 1], reg[..., 2]
    exact = (np.abs(r - rgb[0]) <= 10) & (np.abs(g - rgb[1]) <= 10) & (np.abs(b - rgb[2]) <= 10)
    # cyan mixed with the live layer's void, its greens or a theme's colours: green and
    # blue both well over red, and not the colour itself
    mixed = (g - r >= 24) & (b - r >= 24) & ~exact
    e, m = float(exact.mean()), float(mixed.mean())
    if e >= 0.98:
        kind = "clear"
    elif m <= 0.01 and e <= 0.01:
        kind = "covered"
    elif m >= 0.98 and float(reg.reshape(-1, 3).std(axis=0).max()) < 4.0:
        kind = "dimmed"
    else:
        kind = "translucent"
    return kind, e, m


class OverlayNest(Nest):
    def __init__(self, keep=False, shots=None):
        super().__init__(keep=keep, shots=shots)
        cfg = os.path.join(self.home, ".config")
        os.makedirs(os.path.join(cfg, "bromigos-live"))
        state = os.path.join(self.home, ".local", "state", "bromigos-live")
        os.makedirs(state)
        open(os.path.join(state, "muted"), "w").close()          # no sound, whatever the config says
        self.live_cfg = os.path.join(cfg, "bromigos-live", "config.toml")
        self.den = os.path.join(REPO, "desktop", "wallpaper", "bromigos-den-empty-2560x1440.jpg")
        with open(os.path.join(self.stubs, "bromigos-live"), "w") as f:
            f.write("#!/bin/sh\ncase \"$1\" in start|stop|restart) exit 0;; esac\nexec "
                    + shlex.quote(os.path.join(REPO, "live", "bin", "bromigos-live")) + ' "$@"\n')
        os.chmod(os.path.join(self.stubs, "bromigos-live"), 0o755)
        self.live = self.idle = None
        self.probes = []

    def start(self):
        super().start()
        self.ptr = vptr.VirtualPointer(os.path.join(self.run, "wayland-1"), *self.SIZE)
        self.env["NO_AT_BRIDGE"] = "1"

    # -- the live layer
    def start_live(self, motion="full"):
        self.stop_live()
        with open(self.live_cfg, "w") as f:
            f.write(f'[general]\nmonitor = "WAYLAND-1"\nmotion = "{motion}"\n\n'
                    f'[background]\nunderlay = "{self.den}"\n\n'
                    '[events]\nintercept_on_login = false\nintercept_on_unlock = false\nlock_emblem = false\n'
                    'critical_flash = false\n\n[sounds]\nenabled = false\n\n[codec]\non_lab_alert = false\n')
        env = dict(self.env, XDG_SESSION_TYPE="wayland",
                   PYTHONPATH=os.pathsep.join(filter(None, [os.path.join(REPO, "lib"), os.environ.get("PYTHONPATH")])))
        log = open(os.path.join(self.home, "live.log"), "a")
        self.live = subprocess.Popen([sys.executable, "-m", "live.app"], cwd=os.path.join(REPO, "live"), env=env,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.procs.append(self.live)
        if not wait_for(lambda: self.ctl_live("ping") == "pong", 40):
            raise RuntimeError("the live layer didn't start (see live.log)")
        wait_for(lambda: self.ctl_live("background-active") == "on", 30)

    def stop_live(self):
        if self.live and self.live.poll() is None:
            self.ctl_live("quit")
            try:
                self.live.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(self.live.pid, signal.SIGKILL)
        self.live = None

    def ctl_live(self, cmd, timeout=5):
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(timeout)
                s.connect(os.path.join(self.run, "bromigos-live.sock"))
                s.sendall(cmd.encode())
                out = b""
                while True:
                    b = s.recv(65536)
                    if not b:
                        break
                    out += b
            return out.decode()
        except OSError:
            return None

    # -- hypridle: the screensaver after IDLE_SECONDS, only the compositor's inhibitors
    def start_idle(self):
        conf = os.path.join(self.home, "hypridle-test.conf")
        live = os.path.join(self.stubs, "bromigos-live")
        with open(conf, "w") as f:
            f.write("general {\n    ignore_dbus_inhibit = true\n    ignore_systemd_inhibit = true\n}\n"
                    f"listener {{\n    timeout = {IDLE_SECONDS}\n    on-timeout = {live} ctl screensaver open\n"
                    f"    on-resume = {live} screensaver-off\n}}\n")
        # hypridle needs a system bus. It gets a private one with no logind on it: on the real
        # one it would take a sleep inhibitor, and follow the locks, of the session running
        # the test
        env = dict(self.env, DBUS_SYSTEM_BUS_ADDRESS=self.private_bus("system_bus"))
        log = open(os.path.join(self.home, "hypridle.log"), "a")
        # /usr/bin's: the nest stubs hypridle out for the other tests
        self.idle = subprocess.Popen(["/usr/bin/hypridle", "-c", conf], env=env, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        self.procs.append(self.idle)
        time.sleep(1.0)
        return self.idle.poll() is None

    def private_bus(self, name):
        """A D-Bus daemon of the nest's own, by its address."""
        bus = os.path.join(self.run, name)
        if not os.path.exists(bus):
            self.procs.append(subprocess.Popen(["dbus-daemon", "--session", "--nofork", f"--address=unix:path={bus}"],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                               start_new_session=True))
            wait_for(lambda: os.path.exists(bus), 5)
        return f"unix:path={bus}"

    def wake(self):
        """Input: the pointer moves across the screen (resets idle, ends a screensaver)."""
        for i in range(6):
            self.ptr.move(300 + 60 * i, 300 + 30 * i)
            time.sleep(0.05)

    # -- windows
    def clients(self):
        try:
            return json.loads(self.ctl("clients", "-j") or "[]")
        except ValueError:
            return []

    def client(self, cls):
        return next((c for c in self.clients() if c.get("class") == cls and c.get("mapped", True)), None)

    def open_probe(self, cls="bk-probe", fullscreen=False):
        p = subprocess.Popen([sys.executable, PROBE, cls] + (["--fullscreen"] if fullscreen else []), env=self.env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        self.probes.append(p)
        if not wait_for(lambda: self.client(cls), 15):
            raise RuntimeError(f"the probe window {cls} didn't map")
        time.sleep(0.8)                                    # Hyprland's open animation
        return p

    def open_app(self, argv, cls, env_extra=None):
        p = subprocess.Popen(argv, env=dict(self.env, **(env_extra or {})), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        ok = wait_for(lambda: self.client(cls) or p.poll() is not None, 25)
        return p if ok and self.client(cls) else None

    def close(self, p):
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
                p.wait(5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass

    def rect(self, cls, inset=24):
        c = self.client(cls)
        mon = json.loads(self.ctl("monitors", "-j") or "[]")[0]
        x, y = c["at"][0] - mon["x"] + inset, c["at"][1] - mon["y"] + inset
        return (x, y, c["size"][0] - 2 * inset, c["size"][1] - 2 * inset)

    def grab(self):
        out = subprocess.run(["grim", "-t", "ppm", "-"], env=self.env, capture_output=True, timeout=10).stdout
        head, rest = out.split(b"\n", 1)
        dims, rest = rest.split(b"\n", 1)
        _maxv, data = rest.split(b"\n", 1)
        w, h = (int(v) for v in dims.split())
        return np.frombuffer(data, dtype=np.uint8)[:w * h * 3].reshape(h, w, 3)

    def save(self, img, name):
        if not self.shots:
            return
        os.makedirs(self.shots, exist_ok=True)
        h, w = img.shape[:2]
        path = os.path.join(self.shots, name + ".ppm")
        with open(path, "wb") as f:
            f.write(b"P6\n%d %d\n255\n" % (w, h) + img.tobytes())
        png = path[:-4] + ".png"
        if subprocess.run(["magick", path, png], capture_output=True).returncode == 0:
            os.unlink(path)


def watch(n, rect, until, after=1.5, limit=25.0):
    """Grab and sort frames until until() holds, then `after` seconds more. [(t, kind, exact, mixed, img)]."""
    out, t0, done_at = [], time.monotonic(), None
    while time.monotonic() - t0 < limit:
        img = n.grab()
        kind, e, m = classify(img, rect)
        out.append((time.monotonic() - t0, kind, e, m, img))
        if done_at is None and until():
            done_at = time.monotonic()
        if done_at is not None and time.monotonic() - done_at >= after:
            break
    return out


def summary(frames):
    """Each frame as `.` clear, `#` covered, `t(share mixed)` translucent."""
    mark = {"clear": ".", "covered": "#", "dimmed": "d"}
    return " ".join(f"{t:.1f}s:{mark.get(k) or f't({m:.0%})'}" for t, k, e, m, _ in frames)


def intercept(n, r):
    probe = n.open_probe("bk-probe")
    rect = n.rect("bk-probe")
    for motion in ("full", "reduced", "still"):
        n.start_live(motion)
        n.ctl("dispatch", "focuswindow", "class:bk-probe")
        os.kill(probe.pid, signal.SIGUSR2)                 # magenta: the screen the intercept freezes
        time.sleep(0.6)
        n.ctl_live("intercept open")
        up = wait_for(lambda: n.layer("bromigos-live-intercept"), 15)
        os.kill(probe.pid, signal.SIGUSR1)                 # cyan: only the live window is cyan now
        frames = watch(n, rect, lambda: not n.layer("bromigos-live-intercept"), after=2.0) if up else []
        kinds = [k for _, k, _, _, _ in frames]
        bad = [f for f in frames if f[1] == "translucent"]
        if bad:
            worst = max(bad, key=lambda f: f[3])
            n.save(worst[4], f"intercept-{motion}-translucent")
        covered = [f for f in frames if f[1] == "covered"]
        if covered:
            n.save(covered[len(covered) // 2][4], f"intercept-{motion}-covered")
        if frames:
            n.save(frames[-1][4], f"intercept-{motion}-after")
        r.check(f"intercept ({motion}): it came up", up)
        r.check(f"intercept ({motion}): opaque while it plays (covered frames)", "covered" in kinds, summary(frames))
        r.check(f"intercept ({motion}): never drawn over the window at partial opacity", not bad,
                f"{len(bad)} of {len(frames)} frames translucent: " + summary(frames))
        dim = [f[0] for f in frames if f[1] == "dimmed"]
        if motion == "full":
            r.check("intercept (full): a cut back to the desktop, no fade", not dim, summary(frames))
        else:
            r.check(f"intercept ({motion}): only the empty void lifts, in half a second",
                    not dim or dim[-1] - dim[0] <= 0.8, summary(frames))
        r.check(f"intercept ({motion}): gone, and the window clear after it",
                bool(frames) and kinds[-1] == "clear" and not n.layer("bromigos-live-intercept"), summary(frames[-3:]))
    n.close(probe)


def screensaver(n, r):
    n.start_live("full")
    probe = n.open_probe("bk-probe")
    rect = n.rect("bk-probe")
    os.kill(probe.pid, signal.SIGUSR1)
    if n.idle is None:
        r.check("hypridle runs in the nest", n.start_idle())
    n.wake()
    up = wait_for(lambda: n.layer("bromigos-live-screensaver"), IDLE_SECONDS + 15)
    r.check(f"screensaver: hypridle starts it after {IDLE_SECONDS} idle seconds", up)
    if not up:
        n.close(probe)
        return
    time.sleep(1.2)                                         # its fade-in (0.8 s) is done
    frames, t0 = [], time.monotonic()
    while time.monotonic() - t0 < 4.0:
        img = n.grab()
        frames.append((time.monotonic() - t0, *classify(img, rect), img))
    n.save(frames[len(frames) // 2][4], "screensaver-up")
    bad = [f for f in frames if f[1] != "covered"]
    if bad:
        n.save(max(bad, key=lambda f: f[3])[4], "screensaver-not-covered")
    r.check("screensaver: full screen and opaque over the window for as long as it runs", not bad,
            f"{len(bad)} of {len(frames)} frames not covered: " + summary(frames))
    n.wake()
    gone = wait_for(lambda: not n.layer("bromigos-live-screensaver"), 6)
    time.sleep(0.6)
    img = n.grab()
    kind, _e, _m = classify(img, rect)
    n.save(img, "screensaver-ended")
    r.check("screensaver: input ends it and the window is clear", gone and kind == "clear", kind)
    n.close(probe)


def no_screensaver_while(n, r, what, cls, opener):
    p = opener()
    if p is None:
        r.check(f"{what}: it opened in the nest", False, cls)
        return
    c = n.client(cls) or {}
    r.check(f"{what}: holds an idle inhibitor (Hyprland: inhibitingIdle)", c.get("inhibitingIdle") is True,
            {k: c.get(k) for k in ("class", "fullscreen", "inhibitingIdle")})
    n.wake()
    seen = wait_for(lambda: n.layer("bromigos-live-screensaver"), IDLE_SECONDS + 5)
    if seen:
        time.sleep(1.2)                                    # the screensaver faded in, over it
        n.save(n.grab(), f"inhibit-{cls}-screensaver")
        n.ctl_live("screensaver-off")
    else:
        n.save(n.grab(), f"inhibit-{cls}-awake")
    r.check(f"{what}: idle {IDLE_SECONDS + 5} s with it open, and no screensaver", not seen)
    n.close(p)
    wait_for(lambda: not n.client(cls), 5)


def inhibit(n, r):
    if n.live is None:
        n.start_live("full")
    if n.idle is None:
        r.check("hypridle runs in the nest", n.start_idle())
    # the medium's own welcome card, from this checkout. The installer is a stand-in with its
    # class: it reads the disks as root the moment it opens
    # (a GTK application takes its window class from its ID once it's on a session bus)
    iso_env = {"PYTHONPATH": os.pathsep.join([ISO_LIB, os.path.join(REPO, "lib")]),
               "DBUS_SESSION_BUS_ADDRESS": n.private_bus("session_bus")}

    def iso_app(module, cls):
        return n.open_app([sys.executable, "-m", f"bromigos_installer.{module}"], cls, iso_env)

    no_screensaver_while(n, r, "the live welcome card", "org.bromigos.InstallerWelcome",
                         lambda: iso_app("welcome", "org.bromigos.InstallerWelcome"))
    no_screensaver_while(n, r, "the installer", "org.bromigos.Installer",
                         lambda: n.open_probe("org.bromigos.Installer"))
    no_screensaver_while(n, r, "the welcome tour", "org.bromigos.Welcome",
                         lambda: n.open_probe("org.bromigos.Welcome"))
    no_screensaver_while(n, r, "a full-screen window", "bk-fullscreen",
                         lambda: n.open_probe("bk-fullscreen", fullscreen=True))
    # and with none of them: an ordinary window doesn't hold idle off
    p = n.open_probe("bk-probe")
    c = n.client("bk-probe") or {}
    r.check("an ordinary tiled window holds no inhibitor", c.get("inhibitingIdle") is False, c.get("inhibitingIdle"))
    n.wake()
    r.check("with them gone, the screensaver starts", wait_for(lambda: n.layer("bromigos-live-screensaver"),
                                                               IDLE_SECONDS + 15))
    n.wake()
    wait_for(lambda: not n.layer("bromigos-live-screensaver"), 6)
    n.close(p)


def main():
    keep = "--keep" in sys.argv
    shots = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    r = Run()
    n = OverlayNest(keep=keep, shots=shots)
    try:
        n.start()
        for name, fn in (("intercept", intercept), ("screensaver", screensaver), ("inhibit", inhibit)):
            if only in (None, name):
                fn(n, r)
    finally:
        for p in n.probes:
            n.close(p)
        n.stop_live()
        n.stop()
        if keep:
            print("kept:", n.tmp)
    failed = [x for x in r.results if not x[1]]
    print(f"{len(r.results) - len(failed)} of {len(r.results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
