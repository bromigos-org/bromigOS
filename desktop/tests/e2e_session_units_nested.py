#!/usr/bin/env python3
"""End to end: the bar and the live layer come back by themselves, in a nested Hyprland and
a systemd user manager nobody else uses.

The nested desktop is the keys test's (e2e_keys_nested.Nest: kwin_wayland --virtual hosting
a nested Hyprland, its own runtime directory, HOME and D-Bus). Beside it runs a private
`systemd --user` for that runtime directory, in a cgroup of its own, that knows only this
checkout's two units (desktop/systemd/bromigos-bar.service, live/systemd/bromigos-live.
service, their paths pointed at this checkout). Nothing reaches the desktop this runs from:
no reload, no hyprctl to it, no window on it, no unit in its user manager. The real Waybar
runs with a small config of the sandbox's own; the real live layer runs muted. It checks:

  - login: the defaults' hyprland.lua starts the bar and the live layer as the services;
  - a killed bar (SIGKILL) and a killed live supervisor come back by themselves;
  - every output removed (Hyprland's FALLBACK) and a new one added: both still run, on it;
  - the phone's update path: `bromigos restart waybar live widgets` run in a transient unit
    (as brodec-machine's systemd-run runs `bromigos update`) restarts them, and after the
    unit ends, systemd having killed what was left in it, they still run, outside it.
    A control shows a plain detached child of such a unit is killed;
  - `bromigos status --json` says what runs and, with the bar stopped, the fix; the fix
    (`bromigos restart waybar`) brings it back.

Not part of `unittest discover` (it needs kwin_wayland, Hyprland, waybar, systemd and a GPU):

    python3 desktop/tests/e2e_session_units_nested.py [--keep]
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from e2e_keys_nested import Nest, Run, REPO, DESKTOP, wait_for  # noqa: E402
from e2e_game_nested import private_bus  # noqa: E402

LIVE = os.path.join(REPO, "live")
BROMIGOS = os.path.join(REPO, "core", "target", "debug", "bromigos")
SYSTEMD = "/usr/lib/systemd/systemd"
WAYBAR_CONFIG = {"layer": "top", "position": "top", "height": 30,
                 "modules-left": ["hyprland/workspaces"], "modules-right": ["clock"]}


def pids_named(name, run_dir):
    """This sandbox's processes called NAME (their XDG_RUNTIME_DIR is the sandbox's)."""
    out = []
    for p in subprocess.run(["pgrep", "-x", "-u", str(os.getuid()), name], capture_output=True,
                            text=True).stdout.split():
        try:
            with open(f"/proc/{p}/environ", "rb") as f:
                if f"XDG_RUNTIME_DIR={run_dir}".encode() in f.read().split(b"\0"):
                    out.append(int(p))
        except OSError:
            pass
    return sorted(out)


def live_daemons(run_dir):
    out = []
    for p in subprocess.run(["pgrep", "-f", "-u", str(os.getuid()), "python3 -m live[.]app"], capture_output=True,
                            text=True).stdout.split():
        try:
            with open(f"/proc/{p}/environ", "rb") as f:
                if f"XDG_RUNTIME_DIR={run_dir}".encode() in f.read().split(b"\0"):
                    out.append(int(p))
        except OSError:
            pass
    return sorted(out)


def layer_on(n, namespace, monitor):
    """A layer surface of NAMESPACE mapped on MONITOR of the nested Hyprland."""
    try:
        doc = json.loads(n.ctl("layers", "-j") or "{}")
    except ValueError:
        return False
    levels = (doc.get(monitor) or {}).get("levels", {}).values()
    return any(l.get("namespace") == namespace for level in levels for l in level)


def cgroup(pid):
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            return f.read().strip().split("::", 1)[-1]
    except OSError:
        return ""


class Manager:
    """A private `systemd --user` for the nest's runtime directory, in its own cgroup (a
    child of this one, removed after), loading only the units it's given."""

    def __init__(self, n, env):
        self.n = n
        self.units = os.path.join(n.tmp, "units")
        os.makedirs(self.units)
        self.env = env
        here = cgroup(os.getpid())
        self.cg = f"/sys/fs/cgroup{here}/bromigos-e2e-{os.getpid()}"

    def unit(self, src, subs):
        with open(src) as f:
            text = f.read()
        for a, b in subs:
            text = text.replace(a, b)
        with open(os.path.join(self.units, os.path.basename(src)), "w") as f:
            f.write(text)

    # systemd's own units a manager needs (the slices, the targets every service is ordered
    # after, the exit path), copied without their .wants folders: nothing else of this
    # machine's (sockets, timers, the packages' services) ever starts here
    CORE = ("app.slice", "background.slice", "session.slice", "basic.target", "sockets.target", "timers.target",
            "paths.target", "shutdown.target", "exit.target", "systemd-exit.service")

    def start(self):
        with open(os.path.join(self.units, "bromigos-e2e.target"), "w") as f:
            f.write("[Unit]\nDescription=the e2e test's default target\n")
        for u in self.CORE:
            shutil.copy(os.path.join("/usr/lib/systemd/user", u), self.units)
        os.makedirs(self.cg)
        env = dict(self.env, SYSTEMD_UNIT_PATH=self.units)
        self.log = open(os.path.join(self.n.tmp, "systemd.out"), "w")
        # into its own cgroup before it starts: it takes over the cgroup it runs in
        self.p = subprocess.Popen(["sh", "-c", f'echo $$ > "{self.cg}/cgroup.procs" && exec "$0" --user '
                                   '--unit=bromigos-e2e.target --log-target=console', SYSTEMD],
                                  env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        if not wait_for(lambda: os.path.exists(os.path.join(self.n.run, "systemd", "private")), 15):
            raise RuntimeError("the private user manager didn't start (see systemd.out)")

    def ctl(self, *args):
        r = subprocess.run(["systemctl", "--user", *args], env=self.env, capture_output=True, text=True,
                           timeout=30)
        return r.stdout.strip()

    def main_pid(self, unit):
        v = self.ctl("show", "-p", "MainPID", "--value", unit)
        return int(v) if v.isdigit() and v != "0" else None

    def stop(self):
        if getattr(self, "p", None) and self.p.poll() is None:
            self.p.send_signal(signal.SIGTERM)            # stops its units, then exits
            try:
                self.p.wait(20)
            except subprocess.TimeoutExpired:
                pass
        # whatever is left in its cgroup (nothing, normally), then the cgroup itself
        for _ in range(20):
            try:
                with open(os.path.join(self.cg, "cgroup.kill"), "w") as f:
                    f.write("1")
            except OSError:
                pass
            try:
                for root, dirs, _files in os.walk(self.cg, topdown=False):
                    for d in dirs:
                        os.rmdir(os.path.join(root, d))
                os.rmdir(self.cg)
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(0.25)


def main():
    keep = "--keep" in sys.argv
    if not os.access(BROMIGOS, os.X_OK):
        sys.exit("build the CLI first: (cd core && cargo build)")
    n, r = Nest(keep), Run()
    mgr = None
    try:
        private_bus(n)
        # this checkout's commands instead of the keys test's stubs; the real Waybar
        libbin = os.path.join(n.tmp, "libbin")
        os.makedirs(libbin)
        for name, rel in (("bromigos-bar", "desktop/bin/bromigos-bar"),
                          ("bromigos-dispatch", "desktop/bin/bromigos-dispatch")):
            os.symlink(os.path.join(REPO, rel), os.path.join(libbin, name))
        for name in ("waybar", "bromigos-bar", "bromigos-live", "bromigos-wallpaper"):
            os.unlink(os.path.join(n.stubs, name))
        for name, rel in (("bromigos-bar", "desktop/bin/bromigos-bar"), ("bromigos-live", "live/bin/bromigos-live"),
                          ("bromigos-wallpaper", "desktop/bin/bromigos-wallpaper")):
            os.symlink(os.path.join(REPO, rel), os.path.join(n.stubs, name))
        # the panels: a long-running stand-in, to see where a restart puts it
        with open(os.path.join(n.stubs, "bromigos-widgets"), "w") as f:
            f.write("#!/bin/sh\nexec sleep 3600\n")
        os.makedirs(os.path.join(n.home, ".config", "waybar"))
        with open(os.path.join(n.home, ".config", "waybar", "config"), "w") as f:
            json.dump(WAYBAR_CONFIG, f)
        # the live layer muted, its first-login tour off
        os.makedirs(os.path.join(n.home, ".local", "state", "bromigos-live"))
        open(os.path.join(n.home, ".local", "state", "bromigos-live", "muted"), "w").close()
        extra = {"BROMIGOS_LIB_BIN": libbin, "BROMIGOS_LIVE_BIN": os.path.join(n.stubs, "bromigos-live"),
                 "BROMIGOS_WALLPAPER_BIN": os.path.join(n.stubs, "bromigos-wallpaper")}
        n.base.update(extra)
        menv = dict(n.base, PATH=f"{n.stubs}:/usr/bin")
        mgr = Manager(n, menv)
        stub_bromigos = os.path.join(n.stubs, "bromigos")
        mgr.unit(os.path.join(DESKTOP, "systemd", "bromigos-bar.service"),
                 [("/usr/bin/bromigos ", stub_bromigos + " ")])
        mgr.unit(os.path.join(LIVE, "systemd", "bromigos-live.service"),
                 [("/usr/bin/bromigos ", stub_bromigos + " "),
                  ("/usr/bin/bromigos-live", os.path.join(n.stubs, "bromigos-live")),
                  ("/usr/bin/bromigos-wallpaper", os.path.join(n.stubs, "bromigos-wallpaper"))])
        mgr.start()
        r.check("the private manager knows both units",
                mgr.ctl("show", "-p", "LoadState", "--value", "bromigos-bar.service", "bromigos-live.service").split()
                == ["loaded", "loaded"])
        n.start()
        n.env.update(extra)
        run = n.run

        # 1. login
        bar = wait_for(lambda: mgr.main_pid("bromigos-bar.service"), 20)
        r.check("login: the bar runs as bromigos-bar.service", bar and pids_named("waybar", run) == [bar],
                (bar, pids_named("waybar", run), mgr.ctl("status", "bromigos-bar.service")))
        r.check("login: the bar is mapped", wait_for(lambda: n.layer("waybar"), 15))
        sup = wait_for(lambda: mgr.main_pid("bromigos-live.service"), 20)
        r.check("login: the live layer runs as bromigos-live.service", sup and wait_for(lambda: live_daemons(run), 30),
                mgr.ctl("status", "bromigos-live.service"))
        r.check("login: the live background is mapped", wait_for(lambda: n.layer("bromigos-live"), 30))
        r.check("login: the bar's cgroup is its unit's", cgroup(bar).endswith("/bromigos-bar.service"), cgroup(bar))

        # 2. killed: back by themselves
        os.kill(bar, signal.SIGKILL)
        bar2 = wait_for(lambda: (lambda p: p if p and p != bar and pids_named("waybar", run) == [p] else None)(
            mgr.main_pid("bromigos-bar.service")), 15)
        r.check("a killed bar comes back by itself", bar2, mgr.ctl("status", "bromigos-bar.service"))
        r.check("the bar is mapped again", wait_for(lambda: n.layer("waybar"), 15))
        os.kill(sup, signal.SIGKILL)
        for d in live_daemons(run):
            os.kill(d, signal.SIGKILL)
        sup2 = wait_for(lambda: (lambda p: p if p and p != sup else None)(mgr.main_pid("bromigos-live.service")), 15)
        r.check("a killed live layer comes back by itself", sup2 and wait_for(lambda: live_daemons(run), 30),
                (sup, sup2, live_daemons(run), mgr.ctl("status", "bromigos-live.service")))
        r.check("the live background is mapped again", wait_for(lambda: n.layer("bromigos-live"), 30))

        # 3. the output swapped: a second one, then the first one gone
        n.ctl("output", "create", "wayland", "WAYLAND-9")
        r.check("a second output: the bar is on both",
                wait_for(lambda: layer_on(n, "waybar", "WAYLAND-1") and layer_on(n, "waybar", "WAYLAND-9"), 15))
        n.ctl("output", "remove", "WAYLAND-1")
        r.check("the first output gone: the bar and the live background are on the one left",
                wait_for(lambda: layer_on(n, "waybar", "WAYLAND-9") and layer_on(n, "bromigos-live", "WAYLAND-9"), 30),
                n.ctl("layers"))
        r.check("the first output gone: both still run as their services",
                mgr.ctl("is-active", "bromigos-bar.service", "bromigos-live.service").split() == ["active", "active"])

        # 4. the phone's update path, in a transient unit, and the unit's end
        def transient(name, *cmd, during=None):
            # as brodec-machine starts its update: a transient service, collected when done
            # (systemd-run's own connection: the manager's private socket, no D-Bus)
            env = {k: v for k, v in menv.items() if k != "DBUS_SESSION_BUS_ADDRESS"}
            t = subprocess.run(["systemd-run", "--user", "--collect", "--quiet", "--unit", name,
                                "-p", "TimeoutStopSec=5", *cmd], env=env, capture_output=True, text=True,
                               timeout=60)
            r.check(f"{name}: started", t.returncode == 0, t.stderr.strip())
            if during:
                during()
            wait_for(lambda: mgr.ctl("is-active", name) not in ("active", "activating", "deactivating"), 90, 0.5)
            return t

        transient("brodec-machine-update-control", "/bin/sh", "-c",
                  "setsid -f python3 -c 'import ctypes,time; ctypes.CDLL(None).prctl(15,b\"e2e-control\",0,0,0); "
                  "time.sleep(600)'; sleep 3",
                  during=lambda: r.check("control: its detached child runs while the unit does",
                                         wait_for(lambda: pids_named("e2e-control", run), 3)))
        r.check("control: a detached child of the transient unit dies with it",
                wait_for(lambda: not pids_named("e2e-control", run), 10), pids_named("e2e-control", run))
        bar_before, sup_before = mgr.main_pid("bromigos-bar.service"), mgr.main_pid("bromigos-live.service")
        transient("brodec-machine-update-e2e", "/bin/sh", "-c",
                  f'"{BROMIGOS}" restart waybar live widgets --json > "{n.tmp}/restart.json" 2>&1; sleep 1')
        try:
            with open(os.path.join(n.tmp, "restart.json")) as f:
                done = json.load(f).get("done", [])
        except (OSError, ValueError):
            done = []
        r.check("the update path restarted the bar, the live layer and the panels",
                sorted(d["what"] for d in done if d.get("ok")) == ["live", "waybar", "widgets"], done)
        time.sleep(3)                         # the unit is over, and its leftovers killed
        bar3, sup3 = mgr.main_pid("bromigos-bar.service"), mgr.main_pid("bromigos-live.service")
        r.check("after the unit's end: a new bar still runs", bar3 and bar3 != bar_before
                and pids_named("waybar", run) == [bar3], (bar_before, bar3, pids_named("waybar", run)))
        r.check("after the unit's end: a new live layer still runs", sup3 and sup3 != sup_before
                and live_daemons(run), (sup_before, sup3))
        r.check("after the unit's end: the bar and the live background are mapped",
                wait_for(lambda: n.layer("waybar") and n.layer("bromigos-live"), 30))
        widgets = pids_named("sleep", run)
        r.check("after the unit's end: the panels still run, in the session, not the unit",
                widgets and all("brodec-machine-update" not in cgroup(p) for p in widgets),
                [(p, cgroup(p)) for p in widgets])

        # 5. status and its fix
        def status():
            p = subprocess.run([BROMIGOS, "status", "--json"], env=n.env, capture_output=True, text=True, timeout=30)
            return json.loads(p.stdout or "{}")
        st = status()
        r.check("status: the bar and the live layer run, as services, nothing to fix",
                st.get("bar", {}).get("running") and st["bar"].get("service") and st.get("live", {}).get("running")
                and st["live"].get("service") and st.get("fix") is None, {k: st.get(k) for k in ("bar", "live", "fix")})
        subprocess.run([os.path.join(REPO, "desktop/bin/bromigos-bar"), "stop"], env=n.env, timeout=30)
        st = status()
        r.check("status: a stopped bar is said, with its fix", not st.get("bar", {}).get("running")
                and st.get("fix") == "bromigos restart waybar", {k: st.get(k) for k in ("bar", "fix")})
        subprocess.run([BROMIGOS, "restart", "waybar"], env=n.env, capture_output=True, timeout=60)
        r.check("the fix brings the bar back as the service",
                wait_for(lambda: mgr.main_pid("bromigos-bar.service"), 15) and wait_for(lambda: n.layer("waybar"), 15))
        # 6. every output gone (Hyprland's FALLBACK), then a new one. Waybar and the live layer
        # keep running and their units stay up. (Whether they draw on the new output can't be
        # seen here: a headless output never presents a frame, and kwin doesn't configure a
        # new nested output once the last one has gone. The swap above shows the drawing.)
        n.ctl("output", "create", "headless", "HEADLESS-9")
        time.sleep(1.5)
        n.ctl("output", "remove", "WAYLAND-9")
        time.sleep(1.5)
        n.ctl("output", "remove", "HEADLESS-9")
        time.sleep(3)
        mons = [m["name"] for m in json.loads(n.ctl("monitors", "all", "-j") or "[]")]
        r.check("no outputs: only Hyprland's fallback", mons == ["FALLBACK"], mons)
        bar_now, sup_now = mgr.main_pid("bromigos-bar.service"), mgr.main_pid("bromigos-live.service")
        n.ctl("output", "create", "headless", "HEADLESS-8")
        time.sleep(5)
        r.check("no outputs and a new one: the same bar still runs, its unit up",
                bar_now and mgr.main_pid("bromigos-bar.service") == bar_now and pids_named("waybar", run) == [bar_now]
                and mgr.ctl("is-active", "bromigos-bar.service") == "active")
        r.check("no outputs and a new one: the same live layer still runs, its unit up",
                sup_now and mgr.main_pid("bromigos-live.service") == sup_now and live_daemons(run)
                and mgr.ctl("is-active", "bromigos-live.service") == "active")
    finally:
        if mgr:
            mgr.stop()
        n.stop()
    failed = [x for x in r.results if not x[1]]
    print(f"\n{len(r.results) - len(failed)}/{len(r.results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
