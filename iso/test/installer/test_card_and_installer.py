"""The live desktop's welcome card and the graphical installer, one at a time (welcome.py,
gui.App.send_card_away). A card that opens over the installer takes it out of full screen: a
slow computer draws the card late, after someone found "Install bromigOS" in the launcher
(seen in CI, 2026-11-10: the typing test's clicks missed a window that had moved).

The real programs, on a session bus and a headless weston of their own: no window reaches the
desktop you're on. Skipped where weston, dbus-run-session or GTK isn't installed (the ISO
workflow's typing test covers both orders on the medium itself: iso/test.sh gui-type).
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LIB = ROOT / "iso/profile/airootfs/usr/local/lib/bromigos-iso"

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    HAVE_GTK = True
except Exception:
    HAVE_GTK = False
NEEDS = all(shutil.which(t) for t in ("weston", "dbus-run-session")) and HAVE_GTK


@unittest.skipUnless(NEEDS, "needs weston, dbus-run-session and GTK 4")
class OneAtATime(unittest.TestCase):
    def setUp(self):
        self.rt = tempfile.mkdtemp(prefix="bci.")
        os.chmod(self.rt, 0o700)
        self.addCleanup(shutil.rmtree, self.rt, True)
        store = Path(self.rt, "store/bromigos/x86_64")
        store.mkdir(parents=True)
        for p in ("bromigos-1-1-x86_64", "bromigos-desktop-1-1-x86_64", "bromigos-core-1-1-x86_64", "bromigos-lab-1-1-any"):
            (store / f"{p}.pkg.tar.zst").touch()
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
        env.update(XDG_RUNTIME_DIR=self.rt, HOME=self.rt, GDK_BACKEND="wayland", GSK_RENDERER="cairo",
                   BROMIGOS_INSTALLER_PROBE=str(HERE / "fixtures/probe-windows-uefi.json"),
                   BROMIGOS_EDITION_DIRS=str(LIB.parent.parent / "share/bromigos-iso/editions"),
                   BROMIGOS_REDUCED_MOTION="1", BROMIGOS_ISO_REPO_DIR=str(Path(self.rt, "store")), BROMIGOS_NO_USB="1",
                   BROMIGOS_HOMELAB_LIB=str(ROOT / "homelab/lib"),
                   # nothing of a desktop is started on this bus: no portals, no file service, no screen reader's bus
                   GDK_DEBUG="no-portals", GTK_USE_PORTAL="0", GIO_USE_VFS="local", NO_AT_BRIDGE="1", GTK_A11Y="none",
                   PYTHONPATH=f"{LIB}:{ROOT / 'lib'}:{ROOT / 'desktop/lib'}", PYTHONDONTWRITEBYTECODE="1")
        self.weston = subprocess.Popen(
            ["weston", "--backend=headless", "--renderer=pixman", "--shell=kiosk", "--width=1280", "--height=800",
             "--socket=wl-card", "--no-config", "--idle-time=0"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop, self.weston)
        for _ in range(100):
            if os.path.exists(os.path.join(self.rt, "wl-card")):
                break
            time.sleep(0.1)
        else:
            self.skipTest("weston didn't start")
        env["WAYLAND_DISPLAY"] = "wl-card"
        # one bus for both programs: its address printed by a helper that then waits to be stopped
        self.bus = subprocess.Popen(["dbus-run-session", "--", "sh", "-c", 'echo "$DBUS_SESSION_BUS_ADDRESS"; exec sleep 600'],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        self.addCleanup(self.stop_bus)
        env["DBUS_SESSION_BUS_ADDRESS"] = self.bus.stdout.readline().strip()
        self.assertTrue(env["DBUS_SESSION_BUS_ADDRESS"], "no session bus")
        self.env = env

    @staticmethod
    def stop(p):
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()

    def stop_bus(self):
        """The bus and whatever it started, as one group: none of it outlives the test."""
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.bus.pid, sig)
            except ProcessLookupError:
                break
            try:
                self.bus.wait(5)
            except subprocess.TimeoutExpired:
                continue
            time.sleep(0.3)
        self.bus.stdout.close()

    def start(self, module, *args):
        p = subprocess.Popen([sys.executable, "-m", module, *args], env=self.env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop, p)
        return p

    def owned(self, name):
        out = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus",
                              "--method", "org.freedesktop.DBus.NameHasOwner", name], env=self.env, capture_output=True, text=True,
                             timeout=10)
        return "true" in out.stdout

    def wait(self, what, yes, seconds=30):
        for _ in range(seconds * 5):
            if yes():
                return
            time.sleep(0.2)
        self.fail(what)

    def test_a_card_that_was_there_goes_when_the_installer_opens(self):
        card = self.start("bromigos_installer.welcome")
        self.wait("the card never opened", lambda: self.owned("org.bromigos.InstallerWelcome"))
        self.assertIsNone(card.poll())
        installer = self.start("bromigos_installer.gui", "--fake")
        self.wait("the card stayed open over the installer", lambda: card.poll() is not None)
        self.assertEqual(card.returncode, 0)
        self.assertIsNone(installer.poll(), "the installer went too")

    def test_a_late_card_never_opens_over_the_installer(self):
        installer = self.start("bromigos_installer.gui", "--fake")
        self.wait("the installer never opened", lambda: self.owned("org.bromigos.Installer"))
        card = self.start("bromigos_installer.welcome")
        self.wait("the card opened over the installer and stayed", lambda: card.poll() is not None)
        self.assertEqual(card.returncode, 0)
        self.assertFalse(self.owned("org.bromigos.InstallerWelcome"))
        self.assertIsNone(installer.poll(), "the installer went too")

    def test_alone_the_card_opens_and_stays(self):
        card = self.start("bromigos_installer.welcome")
        self.wait("the card never opened", lambda: self.owned("org.bromigos.InstallerWelcome"))
        time.sleep(2)
        self.assertIsNone(card.poll(), "the card closed by itself with no installer open")


if __name__ == "__main__":
    unittest.main()
