"""One live daemon per user, stopped exactly (live/instance.py, bin/bromigos-live).

    cd live && python -m unittest discover -s tests

The real bin/bromigos-live runs here against a stand-in daemon (tests/fake_live_app.py,
copied in as live/app.py beside the real live/instance.py) in a throwaway runtime dir,
state dir and HOME, with no Wayland or Hyprland in its environment: nothing here can
reach a running desktop, and every process it starts is found again by its working
directory (the throwaway tree) and stopped by PID. The checks:

  - restart leaves exactly one daemon, a new one: right after start, while the daemon is
    still starting (before its socket exists: the SIGTERM a start-up used to lose), and
    when the daemon ignores both quit and SIGTERM (SIGKILL, waited for);
  - a daemon and supervisor from before the lock (a bare PID file, no lock): restart stops
    that daemon, found as the supervisor's child, and starts one;
  - start while running, and two starts at once: one daemon;
  - a second daemon finds the lock held and exits 4;
  - stop leaves another runtime dir's daemon, and a process whose command line merely
    looks like the daemon's, alone (no pattern match);
  - the real daemon (live/app.py, when GTK's bindings are there) takes the lock before
    anything else, exits 4 without it, and leaves on SIGTERM while it waits for a display.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)

from live import instance  # noqa: E402

PY = "/usr/bin/python3"


def tree_procs(root):
    """Processes running in `root` (their cwd): the stand-in daemons and supervisors (not a
    zombie: in a container whose PID 1 doesn't reap, a killed process lingers as one)."""
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit() or instance.starttime(d) is None:
            continue
        try:
            cwd = os.readlink(f"/proc/{d}/cwd")
        except OSError:
            continue
        if cwd == root or cwd.startswith(root + "/"):
            out.append(int(d))
    return out


def daemons(root):
    return [p for p in tree_procs(root) if instance.is_daemon(instance.cmdline(p))]


class Sandbox:
    """A throwaway tree: bin/bromigos-live (the real one), live/instance.py (the real one),
    live/app.py (the stand-in), and its own runtime and state dirs."""

    def __init__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="bromigos-live-inst-"))
        os.makedirs(os.path.join(self.root, "bin"))
        os.makedirs(os.path.join(self.root, "live"))
        shutil.copy(os.path.join(LIVE, "bin", "bromigos-live"), os.path.join(self.root, "bin"))
        shutil.copy(os.path.join(LIVE, "live", "instance.py"), os.path.join(self.root, "live"))
        shutil.copy(os.path.join(HERE, "fake_live_app.py"), os.path.join(self.root, "live", "app.py"))
        open(os.path.join(self.root, "live", "__init__.py"), "w").close()
        self.run_dir = os.path.join(self.root, "run")
        os.makedirs(self.run_dir, mode=0o700)
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY",
                                 "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_ID")}
        self.env.update(XDG_RUNTIME_DIR=self.run_dir, HOME=self.root,
                        XDG_STATE_HOME=os.path.join(self.root, "state"),
                        XDG_CONFIG_HOME=os.path.join(self.root, "config"),
                        PYTHONDONTWRITEBYTECODE="1")

    def live(self, *args, env=None, timeout=60):
        e = dict(self.env, **(env or {}))
        return subprocess.run([os.path.join(self.root, "bin", "bromigos-live"), *args], env=e,
                              capture_output=True, text=True, timeout=timeout, cwd=self.root)

    def wait_daemons(self, n, seconds=10.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            ds = daemons(self.root)
            if len(ds) == n and (n == 0 or instance.read(os.path.join(self.run_dir, "bromigos-live.lock"))):
                return ds
            time.sleep(0.05)
        return daemons(self.root)

    def serving(self, seconds=10.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if os.path.exists(os.path.join(self.run_dir, "bromigos-live.sock")):
                return True
            time.sleep(0.05)
        return False

    def cleanup(self):
        for _ in range(3):                    # by PID: only what runs in this tree
            procs = tree_procs(self.root)
            if not procs:
                break
            for p in procs:
                try:
                    os.kill(p, signal.SIGKILL)
                except OSError:
                    pass
            time.sleep(0.2)
        shutil.rmtree(self.root, ignore_errors=True)


class ScriptTest(unittest.TestCase):
    def setUp(self):
        self.s = Sandbox()
        self.addCleanup(self.s.cleanup)

    def start(self, **env):
        r = self.s.live("start", "--login", env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ds = self.s.wait_daemons(1)
        self.assertEqual(len(ds), 1, f"one daemon after start: {ds}")
        return ds[0]

    def test_restart_leaves_exactly_one_new_daemon(self):
        old = self.start()
        self.assertTrue(self.s.serving())
        r = self.s.live("restart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("stopped", r.stdout)
        ds = self.s.wait_daemons(1)
        self.assertEqual(len(ds), 1, ds)
        self.assertNotEqual(ds[0], old)
        time.sleep(1.0)                                # and it stays one
        self.assertEqual(daemons(self.s.root), ds)

    def test_restart_while_the_daemon_is_still_starting(self):
        # the login's daemon hasn't opened its socket yet: quit can't reach it, SIGTERM must
        old = self.start(FAKE_START_DELAY="4")
        r = self.s.live("restart", env={"FAKE_START_DELAY": "0"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ds = self.s.wait_daemons(1)
        self.assertEqual(len(ds), 1, ds)
        self.assertNotEqual(ds[0], old)
        time.sleep(4.5)                                # past the old one's start-up: no second
        self.assertEqual(daemons(self.s.root), ds)

    def test_a_daemon_ignoring_quit_and_term_is_killed(self):
        old = self.start(FAKE_IGNORE_TERM="1", FAKE_IGNORE_QUIT="1")
        self.assertTrue(self.s.serving())
        t0 = time.monotonic()
        r = self.s.live("restart", env={"FAKE_IGNORE_TERM": "", "FAKE_IGNORE_QUIT": ""})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ds = self.s.wait_daemons(1)
        self.assertEqual(len(ds), 1, ds)
        self.assertNotEqual(ds[0], old)
        self.assertFalse(os.path.exists(f"/proc/{old}") and instance.starttime(old) is not None
                         and instance.is_daemon(instance.cmdline(old)), "the old daemon is gone")
        self.assertLess(time.monotonic() - t0, 20)

    def test_a_daemon_from_before_the_lock(self):
        # an older supervisor: a bare PID file, its child daemon holding no lock
        pidf = os.path.join(self.s.run_dir, "bromigos-live.pid")
        # the old supervisor's subshell: `bash …/bromigos-live start --login` running the
        # daemon as its child (a script of that name, so its command line reads the same)
        old_dir = os.path.join(self.s.root, "old")
        os.makedirs(old_dir)
        script = os.path.join(old_dir, "bromigos-live")
        with open(script, "w") as f:
            f.write(f'cd "{self.s.root}" && "{PY}" -m live.app --login\nsleep 30\n')
        sup = subprocess.Popen(["bash", script, "start", "--login"], cwd=self.s.root,
                               env=dict(self.s.env, FAKE_NO_LOCK="1"),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: sup.poll() is None and (sup.kill(), sup.wait()))
        with open(pidf, "w") as f:
            f.write(f"{sup.pid}\n")
        old = self.s.wait_daemons(1)
        self.assertEqual(len(old), 1, old)
        self.assertIsNone(instance.read(os.path.join(self.s.run_dir, "bromigos-live.lock")))
        r = self.s.live("restart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(str(old[0]), r.stdout)
        ds = self.s.wait_daemons(1)
        self.assertEqual(len(ds), 1, ds)
        self.assertNotEqual(ds, old)
        sup.wait(5)                                    # the old supervisor was stopped too

    def test_start_while_running_and_two_starts_at_once(self):
        first = self.start()
        r = self.s.live("start")
        self.assertIn("already running", r.stdout)
        self.assertEqual(daemons(self.s.root), [first])
        self.s.live("stop")
        self.assertEqual(self.s.wait_daemons(0), [])
        e = dict(self.s.env)
        ps = [subprocess.Popen([os.path.join(self.s.root, "bin", "bromigos-live"), "start"], env=e,
                               cwd=self.s.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
              for _ in range(3)]
        outs = [p.communicate(timeout=60)[0] for p in ps]
        self.assertEqual(sum("already running" in o for o in outs), 2, outs)
        ds = self.s.wait_daemons(1)
        time.sleep(1.0)
        self.assertEqual(daemons(self.s.root), ds)
        self.assertEqual(len(ds), 1)

    def test_a_second_daemon_exits_4(self):
        self.start()
        r = subprocess.run([PY, "-m", "live.app"], cwd=self.s.root, env=self.s.env, timeout=30,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, instance.TAKEN, r.stdout + r.stderr)
        self.assertEqual(len(daemons(self.s.root)), 1)

    def test_stop_leaves_other_instances_and_lookalikes_alone(self):
        other = Sandbox()                              # another runtime dir, its own daemon
        self.addCleanup(other.cleanup)
        r = other.live("start")
        self.assertEqual(r.returncode, 0)
        theirs = other.wait_daemons(1)
        self.assertEqual(len(theirs), 1)
        # a process whose command line is the daemon's, `/usr/bin/python3 -m live.app`, run
        # from elsewhere: what the old `pkill -f "^/usr/bin/python3 -m live.app"` also killed
        look_dir = os.path.realpath(tempfile.mkdtemp(prefix="bromigos-live-lookalike-"))
        self.addCleanup(shutil.rmtree, look_dir, True)
        os.makedirs(os.path.join(look_dir, "live"))
        open(os.path.join(look_dir, "live", "__init__.py"), "w").close()
        with open(os.path.join(look_dir, "live", "app.py"), "w") as f:
            f.write("import time\ntime.sleep(60)\n")
        look = subprocess.Popen([PY, "-m", "live.app"], cwd=look_dir, env=self.s.env)
        self.addCleanup(lambda: look.poll() is None and (look.kill(), look.wait()))
        self.start()
        r = self.s.live("stop")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.s.wait_daemons(0), [])
        self.assertIsNone(look.poll(), "the look-alike still runs")
        self.assertEqual(other.wait_daemons(1), theirs, "the other runtime dir's daemon still runs")
        other.live("stop")


class RealDaemonTest(unittest.TestCase):
    """live/app.py itself, without a display (GTK can't open one in a throwaway runtime dir)."""

    def setUp(self):
        try:
            subprocess.run([PY, "-c", "import gi; gi.require_version('Gtk', '3.0'); "
                            "gi.require_version('GtkLayerShell', '0.1'); "
                            "from gi.repository import Gtk, GtkLayerShell; import OpenGL, numpy"],
                           check=True, capture_output=True, timeout=30)
        except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
            self.skipTest("needs GTK 3, gtk-layer-shell, PyOpenGL and numpy")
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="bromigos-live-real-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        run = os.path.join(self.tmp, "run")
        os.makedirs(run, mode=0o700)
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY",
                                 "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_ID")}
        self.env.update(XDG_RUNTIME_DIR=run, HOME=self.tmp, XDG_STATE_HOME=os.path.join(self.tmp, "state"),
                        XDG_CONFIG_HOME=os.path.join(self.tmp, "config"), XDG_CACHE_HOME=os.path.join(self.tmp, "cache"),
                        GDK_BACKEND="wayland", PYTHONDONTWRITEBYTECODE="1")
        self.lock = os.path.join(run, "bromigos-live.lock")

    def daemon(self):
        p = subprocess.Popen([PY, "-m", "live.app"], cwd=LIVE, env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(lambda: p.poll() is None and (p.kill(), p.wait()))
        return p

    def test_sigterm_while_waiting_for_a_display(self):
        p = self.daemon()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and instance.read(self.lock) is None:
            time.sleep(0.05)
        rec = instance.read(self.lock)
        self.assertIsNotNone(rec, "the daemon took its lock")
        self.assertEqual(rec[0], p.pid)
        time.sleep(1.0)                                # in its wait for a display
        p.send_signal(signal.SIGTERM)
        out, _ = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, out)

    def test_without_the_lock_it_exits_4(self):
        held = instance.acquire(self.lock)
        self.addCleanup(held.close)
        p = self.daemon()
        out, _ = p.communicate(timeout=30)
        self.assertEqual(p.returncode, instance.TAKEN, out)
        self.assertIn("another live daemon runs", out)


if __name__ == "__main__":
    unittest.main()
