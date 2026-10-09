#!/usr/bin/env python3
"""The live layer on a software renderer, as after a graphics driver update (live/software.py):
the real daemon (python -m live.app) on Mesa's llvmpipe, measured.

It runs in a sandbox: a throwaway HOME and runtime directory, a private D-Bus, its own
/proc (unshare: the desktop's screen locker isn't the sandbox's), and a headless kwin
(kwin_wayland --virtual: no window, no output) as the compositor. kwin and the daemon get
LIBGL_ALWAYS_SOFTWARE=1 and Mesa's EGL only, so GTK's GL context is llvmpipe, as it was on
2026-10-09. Nothing touches the running desktop or its live layer.

Two runs:
  held     [general] allow_software = false (the default): the log names llvmpipe, the
           status says NO GPU and motion still, one notification goes out, and the
           process stays under MAX_HELD of one CPU core
  control  allow_software = true: full motion on llvmpipe, measured for comparison
           (--no-control skips it: it loads every core for its few seconds)

    python3 live/tests/software_session.py [--size WxH] [--seconds N] [--no-control]

Exits 1 when a check fails. Needs kwin_wayland and dbus-daemon.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # live/
MESA_EGL = "/usr/share/glvnd/egl_vendor.d/50_mesa.json"
MAX_HELD = 5.0           # % of one core, on average, while the background holds still
SETTLE = 20.0            # seconds after the first frame before measuring
TICK = os.sysconf("SC_CLK_TCK")
# kwin on llvmpipe too: it presents the daemon's frames (with QPainter it sent none, and
# GTK's swap waited forever)
KWIN_ENV = {"LIBGL_ALWAYS_SOFTWARE": "1", "__EGL_VENDOR_LIBRARY_FILENAMES": MESA_EGL}


def arg(flag, default):
    if flag in sys.argv:
        return sys.argv[sys.argv.index(flag) + 1]
    return default


def cpu_ticks(pid):
    with open(f"/proc/{pid}/stat") as f:
        rest = f.read().rsplit(") ", 1)[1].split()
    return int(rest[11]) + int(rest[12])            # utime + stime, every thread


def threads(pid):
    return len(os.listdir(f"/proc/{pid}/task"))


def ask(run, cmd):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    s.connect(os.path.join(run, "bromigos-live.sock"))
    s.sendall(cmd.encode())
    out = b""
    while True:
        b = s.recv(65536)
        if not b:
            break
        out += b
    s.close()
    return out.decode(errors="replace")


class FakeHyprland:
    """Hyprland's request and event sockets, answering for one output with nothing on it:
    the daemon asks Hyprland where to draw and whether its surface is mapped, and without an
    answer it waits for an output that never comes."""

    def __init__(self, run, size):
        self.dir = os.path.join(run, "hypr", "sandbox")
        os.makedirs(self.dir)
        w, h = size
        self.answers = {
            "j/monitors": [{"name": "Virtual-1", "id": 0, "x": 0, "y": 0, "width": w, "height": h,
                            "focused": True, "dpmsStatus": True, "activeWorkspace": {"id": 1},
                            "specialWorkspace": {"id": 0}}],
            "j/clients": [],
            "j/layers": {"Virtual-1": {"levels": {"0": [{"namespace": "bromigos-live"}]}}},
        }
        self.socks = []
        for name, fn in ((".socket.sock", self._answer), (".socket2.sock", self._hold)):
            srv = socket.socket(socket.AF_UNIX)
            srv.bind(os.path.join(self.dir, name))
            srv.listen(16)
            self.socks.append(srv)
            threading.Thread(target=self._serve, args=(srv, fn), daemon=True).start()

    @staticmethod
    def _serve(srv, fn):
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=fn, args=(conn,), daemon=True).start()

    def _answer(self, conn):
        with conn:
            try:
                cmd = conn.recv(4096).decode(errors="replace").strip()
                a = self.answers.get(cmd, {} if cmd.startswith("j/") else "ok")
                conn.sendall((json.dumps(a) if cmd.startswith("j/") else str(a)).encode())
            except OSError:
                pass

    @staticmethod
    def _hold(conn):                                    # the event socket: no events
        try:
            conn.recv(1)
        except OSError:
            pass

    def close(self):
        for s in self.socks:
            s.close()


def wait(fn, t):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return fn()


def session(base, name, allow, size, seconds):
    """One sandboxed daemon on llvmpipe; returns what was measured."""
    d = os.path.join(base, name)
    home, run, stubs = (os.path.join(d, x) for x in ("home", "run", "stubs"))
    for p in (home, run, stubs):
        os.makedirs(p)
    os.chmod(run, 0o700)
    sent = os.path.join(d, "notified")
    with open(os.path.join(stubs, "notify-send"), "w") as f:
        f.write(f'#!/bin/sh\necho "$*" >> "{sent}"\n')
    os.chmod(os.path.join(stubs, "notify-send"), 0o755)
    cfg = os.path.join(d, "live.toml")
    with open(cfg, "w") as f:
        f.write(f"[general]\nallow_software = {'true' if allow else 'false'}\n"
                "[sounds]\nenabled = false\n[codec]\nenabled = false\ntts_url = \"\"\n"
                "[events]\nintercept_on_login = false\n[world]\nambient_sounds = false\n"
                "[cluster]\nurl = \"\"\n[fills]\nurl = \"\"\n")
    bus = os.path.join(run, "bus")
    dconf = os.path.join(d, "dbus.conf")
    with open(dconf, "w") as f:
        f.write('<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN" '
                '"http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">\n'
                f'<busconfig><type>session</type><listen>unix:path={bus}</listen>'
                '<policy context="default"><allow send_destination="*" eavesdrop="true"/>'
                '<allow eavesdrop="true"/><allow own="*"/></policy></busconfig>\n')
    env = {"HOME": home, "XDG_RUNTIME_DIR": run, "PATH": f"{stubs}:/usr/bin:/bin", "LANG": "C.UTF-8",
           "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus}", "BROMIGOS_LIVE_VIRT": "none"}
    procs = []

    def start(argv, extra, log):
        lf = open(os.path.join(d, log), "w")
        p = subprocess.Popen(argv, env=dict(env, **extra), stdout=lf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, cwd=HERE, start_new_session=True)
        procs.append(p)
        return p

    try:
        start(["dbus-daemon", f"--config-file={dconf}", "--nofork", "--nopidfile"], {}, "dbus.log")
        if not wait(lambda: os.path.exists(bus), 5):
            raise RuntimeError("the private D-Bus didn't start")
        w, h = size
        start(["kwin_wayland", "--virtual", "--width", str(w), "--height", str(h), "--socket", "kw",
               "--no-lockscreen", "--no-global-shortcuts"], KWIN_ENV, "kwin.log")
        if not wait(lambda: os.path.exists(os.path.join(run, "kw")), 20):
            raise RuntimeError("kwin_wayland --virtual didn't start")
        # its own /proc (a PID namespace): the desktop's processes, a screen locker among
        # them, aren't the sandbox's
        ns = ["unshare", "--user", "--map-current-user", "--pid", "--fork", "--mount-proc"] \
            if shutil.which("unshare") else []
        hypr = FakeHyprland(run, size)
        live = start(ns + [sys.executable, "-m", "live.app"],
                     {"WAYLAND_DISPLAY": "kw", "HYPRLAND_INSTANCE_SIGNATURE": "sandbox", "GDK_BACKEND": "wayland", "BROMIGOS_LIVE_CONFIG": cfg,
                      "LIBGL_ALWAYS_SOFTWARE": "1", "__EGL_VENDOR_LIBRARY_FILENAMES": MESA_EGL,
                      "PYTHONUNBUFFERED": "1"}, "live.log")
        logf = os.path.join(d, "live.log")

        def renderer():
            with open(logf) as f:
                return next((ln.strip() for ln in f if "GL renderer:" in ln), None)
        line = wait(renderer, 60)
        if not line:
            raise RuntimeError(f"no GL renderer in the log ({logf})")
        pid = live.pid
        if ns:                                          # the daemon is unshare's child
            with open(f"/proc/{live.pid}/task/{live.pid}/children") as f:
                pid = int(f.read().split()[0])

        def first_frame():
            with open(logf) as f:
                text = f.read()
            return "plate " in text or "world" in text
        wait(first_frame, 60)
        time.sleep(SETTLE)                              # the scene's start-up work (the den's plate)
        t0, c0 = time.monotonic(), cpu_ticks(pid)
        time.sleep(seconds)
        t1, c1 = time.monotonic(), cpu_ticks(pid)
        state = ask(run, "state")
        n = 0
        if os.path.exists(sent):
            with open(sent) as f:
                n = len(f.read().splitlines())
        return {"renderer": line, "cpu": 100.0 * (c1 - c0) / TICK / (t1 - t0), "threads": threads(pid),
                "state": state, "notified": n, "alive": live.poll() is None, "log": logf}
    finally:
        if "hypr" in locals():
            hypr.close()
        for p in reversed(procs):
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass
        for p in procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)


def main():
    for tool in ("kwin_wayland", "dbus-daemon"):
        if not shutil.which(tool):
            print(f"SKIP: {tool} isn't installed")
            return 0
    size = tuple(int(x) for x in arg("--size", "1920x1080").split("x"))
    seconds = float(arg("--seconds", "30"))
    base = tempfile.mkdtemp(prefix="bromigos-live-software.")
    fails = []

    def check(ok, what):
        print(("PASS  " if ok else "FAIL  ") + what)
        if not ok:
            fails.append(what)
    try:
        h = session(base, "held", False, size, seconds)
        print(f"held: {h['renderer']}")
        print(f"held: {h['cpu']:.1f}% of one core over {seconds:.0f} s, {h['threads']} threads")
        print("held: status:\n  " + "\n  ".join(h["state"].splitlines()[:3]))
        check("llvmpipe" in h["renderer"], "the daemon's GL context is llvmpipe")
        check("held to" not in h["renderer"] and "still frame" in h["renderer"], "the log says why it holds still")
        check("NO GPU" in h["state"] and "motion still" in h["state"], "status: NO GPU, motion still")
        check("target=0fps" in h["state"], "no frame timer (a still frame, drawn again only on a change)")
        check(h["notified"] == 1, f"one notification ({h['notified']})")
        check(h["alive"], "the daemon keeps running")
        check(h["cpu"] < MAX_HELD, f"under {MAX_HELD:.0f}% of one core ({h['cpu']:.1f}%)")
        if "--no-control" not in sys.argv:
            c = session(base, "control", True, size, min(seconds, 10.0))
            print(f"control: {c['renderer']}")
            print(f"control: {c['cpu']:.1f}% of one core, {c['threads']} threads (full motion on llvmpipe)")
            check(c["notified"] == 0 and "allowed full motion" in c["renderer"], "allow_software = true: full motion, no notice")
            check(c["cpu"] > 4 * max(h["cpu"], 1.0), "full motion costs far more than the still frame")
    finally:
        if fails:
            print(f"logs kept in {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
