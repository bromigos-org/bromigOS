"""preview.py's VM can't outlive the preview: QEMU runs through test/vm/vm-keeper.py, owned
by the preview's process. A stand-in QEMU (a few lines of Python named qemu-system-x86_64)
takes the VM's place, so no machine boots.

  python -m unittest discover -s settings/grub/tests      (from the repository root)

The checks that start the stand-in need what the keeper needs before any test VM: at least
14 GiB free (`free -g`) and room in the test-VM budget. They're skipped otherwise.
"""

import importlib.machinery
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
GRUB = os.path.dirname(HERE)


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


preview = load("grub_preview", os.path.join(GRUB, "preview.py"))

# the stand-in: answers to the name qemu-system-x86_64 (the keeper counts it as a VM),
# writes -pidfile, opens the -qmp socket (the keeper's "up") and waits to be stopped
FAKE_QEMU = r"""#!/bin/sh
exec -a qemu-system-x86_64 python3 -c '
import os, socket, sys, time
a = sys.argv[1:]
sock = a[a.index("-qmp") + 1].split("unix:", 1)[1].split(",")[0]
with open(a[a.index("-pidfile") + 1], "w") as f:
    f.write(str(os.getpid()))
s = socket.socket(socket.AF_UNIX)
s.bind(sock)
s.listen(1)
time.sleep(600)
' "$@"
"""

OWNER = r"""
import importlib.machinery, importlib.util, sys, time
loader = importlib.machinery.SourceFileLoader("grub_preview", sys.argv[1])
spec = importlib.util.spec_from_loader("grub_preview", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
work = sys.argv[2]
mod.launch(work, ["qemu-system-x86_64", "-m", "512", "-display", "none",
                  "-qmp", "unix:qmp.sock,server,nowait", "-pidfile", work + "/qemu.pid", "-daemonize"])
print("up", flush=True)
time.sleep(600)
"""


def free_gib():
    try:
        out = subprocess.check_output(["free", "-g"], text=True)
    except (OSError, subprocess.CalledProcessError):
        return 0
    return int(next(line for line in out.splitlines() if line.startswith("Mem:")).split()[-1])


def alive(pid):
    """Running, not a zombie waiting for its parent."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(") ", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def gone_within(seconds, pid):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


def parent(pid):
    with open(f"/proc/{pid}/stat") as f:
        return int(f.read().rsplit(") ", 1)[1].split()[1])


def cmdline(pid):
    with open(f"/proc/{pid}/cmdline", "rb") as f:
        return f.read().replace(b"\0", b" ").decode(errors="replace")


class LaunchArgs(unittest.TestCase):
    def test_launch_goes_through_the_keeper_owned_by_the_preview(self):
        with tempfile.TemporaryDirectory() as work, \
                mock.patch.object(preview.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            preview.launch(work, ["qemu-system-x86_64", "-m", "512", "-daemonize", "-pidfile", "p"])
        argv = run.call_args.args[0]
        self.assertEqual(argv[1], preview.KEEPER)
        self.assertTrue(os.path.isfile(preview.KEEPER), preview.KEEPER)
        self.assertEqual(argv[argv.index("--owner") + 1], str(os.getpid()))
        self.assertEqual(argv[argv.index("--ready") + 1], os.path.join(work, "qmp.sock"))
        qemu = argv[argv.index("--") + 1:]
        self.assertEqual(qemu[0], "qemu-system-x86_64")
        self.assertNotIn("-daemonize", qemu)

    def test_a_qemu_that_does_not_start_stops_the_preview(self):
        with tempfile.TemporaryDirectory() as work, \
                mock.patch.object(preview.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 1, "", "vm-keeper: failed: budget")):
            with self.assertRaises(SystemExit) as e:
                preview.launch(work, ["qemu-system-x86_64"])
        self.assertIn("budget", str(e.exception))


@unittest.skipUnless(sys.platform.startswith("linux"), "the keeper reads /proc")
class KilledPreview(unittest.TestCase):
    def setUp(self):
        if free_gib() < 14:
            self.skipTest("the keeper starts a test VM only with at least 14 GiB free")
        base = os.environ.get("TMPDIR", "/tmp")
        if len(base) > 60:
            base = "/tmp"                       # a socket's path has 108 bytes at most
        self.dir = tempfile.mkdtemp(prefix="grub-preview-test.", dir=base)
        self.addCleanup(self.cleanup)
        bin_ = os.path.join(self.dir, "bin")
        os.mkdir(bin_)
        fake = os.path.join(bin_, "qemu-system-x86_64")
        with open(fake, "w") as f:
            f.write(FAKE_QEMU)
        os.chmod(fake, 0o755)
        self.work = os.path.join(self.dir, "work")
        os.mkdir(self.work)
        env = dict(os.environ, PATH=bin_ + os.pathsep + os.environ.get("PATH", ""))
        env.pop("BROMIGOS_VM_OWNER", None)
        self.owner = subprocess.Popen([sys.executable, "-c", OWNER, os.path.join(GRUB, "preview.py"), self.work],
                                      env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = self.owner.stdout.readline().strip()
        if line != "up":
            self.owner.wait(10)
            err = self.owner.stderr.read()
            if "budget" in err or "available" in err:
                self.skipTest(f"the keeper refused a test VM: {err.strip()}")
            self.fail(f"the preview didn't start its stand-in QEMU: {err}")
        with open(os.path.join(self.work, "qemu.pid")) as f:
            self.qemu = int(f.read().strip())

    def cleanup(self):
        for pid in (getattr(self, "qemu", None), getattr(self.owner, "pid", None) if hasattr(self, "owner") else None):
            if pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        if hasattr(self, "owner"):
            self.owner.wait(10)
            self.owner.stdout.close()
            self.owner.stderr.close()
        subprocess.run(["rm", "-rf", self.dir])

    def test_qemu_runs_under_the_keeper_without_daemonize(self):
        self.assertTrue(alive(self.qemu))
        self.assertIn("vm-keeper.py", cmdline(parent(self.qemu)))
        self.assertNotIn("-daemonize", cmdline(self.qemu))

    def test_preview_killed_qemu_stops(self):
        self.owner.kill()
        self.owner.wait(10)
        self.assertTrue(gone_within(5, self.qemu), "QEMU outlived the killed preview")
        with open(os.path.join(self.work, "keeper.log")) as f:
            self.assertIn(f"its owner (PID {self.owner.pid}) is gone", f.read())

    def test_keeper_killed_qemu_stops(self):
        os.kill(parent(self.qemu), signal.SIGKILL)
        self.assertTrue(gone_within(5, self.qemu), "QEMU outlived its killed keeper (PR_SET_PDEATHSIG)")


if __name__ == "__main__":
    unittest.main()
