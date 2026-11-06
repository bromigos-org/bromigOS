"""`bromigos lab link` (accountlink.py): it hands the link to the lab bridge's
`brodec-lab connect` through sudo, then starts the bridge's service once paired. Nothing
here runs sudo, systemctl or the bridge: the runner is a fake.

    PYTHONPATH=lib python -m unittest tests.test_accountlink
"""
import contextlib
import io
import json
import os
import subprocess
import unittest

from bromigos_homelab import accountlink as L

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(os.path.dirname(HERE), "bin", "bromigos-lab")


class Runner:
    """Records each command; answers from a table of argv prefixes."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, argv, **_):
        self.calls.append(argv)
        for prefix, rc in self.answers:
            if argv[:len(prefix)] == prefix:
                return subprocess.CompletedProcess(argv, rc)
        return subprocess.CompletedProcess(argv, 0)


def cli(argv, runner, installed=True):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = L.main(argv, run=runner, which=lambda n: "/usr/bin/" + n if installed else None)
    return rc, out.getvalue()


class Argv(unittest.TestCase):
    def test_connect_goes_through_sudo_unless_root(self):
        a = L.parse(["--name", "Attic box", "--json", "--timeout", "600"])
        self.assertEqual(L.connect_argv(a, euid=1000), [
            "sudo", "brodec-lab", "connect", "--kind", "cli", "--intent", "self-hosted",
            "--name", "Attic box", "--json", "--timeout", "600"])
        self.assertEqual(L.connect_argv(L.parse(["--intent", "hosted"]), euid=0),
                         ["brodec-lab", "connect", "--kind", "cli", "--intent", "hosted"])
        self.assertEqual(L.service_argv(euid=1000), ["sudo", "systemctl", "enable", "--now", "brodec-lab"])

    def test_unknown_intent_is_refused(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            L.parse(["--intent", "both"])


class Link(unittest.TestCase):
    def test_paired_then_the_service_starts(self):
        r = Runner([(["systemctl", "is-active"], 3)])
        rc, out = cli([], r)
        self.assertEqual(rc, 0)
        self.assertEqual(r.calls[0][-6:], ["brodec-lab", "connect", "--kind", "cli", "--intent", "self-hosted"])
        self.assertEqual(r.calls[-1][-4:], ["systemctl", "enable", "--now", "brodec-lab"])
        self.assertIn("VECTOR answers from this computer", out)

    def test_a_running_service_is_left_alone(self):
        r = Runner([])
        rc, out = cli(["--json"], r)
        self.assertEqual(rc, 0)
        self.assertFalse(any("enable" in c for c in r.calls))
        self.assertEqual(json.loads(out.strip().splitlines()[-1]), {"event": "service", "state": "running"})

    def test_not_linked_passes_the_bridges_exit_code_and_starts_nothing(self):
        r = Runner([(["sudo", "brodec-lab"], 1), (["brodec-lab"], 1)])
        rc, _ = cli([], r)
        self.assertEqual(rc, 1)
        self.assertEqual(len(r.calls), 1)

    def test_hosted_and_no_start_start_nothing(self):
        for argv in (["--intent", "hosted"], ["--no-start"]):
            r = Runner([(["systemctl", "is-active"], 3)])
            rc, _ = cli(argv, r)
            self.assertEqual(rc, 0)
            self.assertEqual(len(r.calls), 1, argv)

    def test_a_service_that_wont_start_says_how(self):
        r = Runner([(["systemctl", "is-active"], 3), (["sudo", "systemctl"], 1), (["systemctl", "enable"], 1)])
        rc, out = cli([], r)
        self.assertEqual(rc, 1)
        self.assertIn("sudo systemctl enable --now brodec-lab", out)

    def test_without_the_bridge_it_says_how_to_install_it(self):
        r = Runner([])
        rc, out = cli(["--json"], r, installed=False)
        self.assertEqual(rc, 3)
        self.assertEqual(r.calls, [])
        ev = json.loads(out)
        self.assertEqual(ev["code"], "not_installed")
        self.assertIn("pacman -S brodec-lab", ev["message"])


class FrontDoor(unittest.TestCase):
    def test_bromigos_lab_routes_link_and_lists_it(self):
        with open(LAB) as f:
            src = f.read()
        self.assertIn('if cmd == "link":', src)
        self.assertIn("bromigos lab link [--intent self-hosted|hosted]", src)


if __name__ == "__main__":
    unittest.main()
