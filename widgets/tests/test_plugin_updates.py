"""plugins/updates.py: reading `bromigos update --check --json`, the cache that keeps checks
sparse, and the empty states."""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import plugintest as PT
import updates as U

DOC = {"schema": 1, "check": {
    "packages": [{"name": "waybar", "from": "0.15.0-3", "to": "0.15.1-1"}],
    "aur": {"enabled": True, "note": None, "packages": ["zen-browser-bin 1.16.1b-1 -> 1.16.2b-1"]},
    "migrations": ["20261008120200-desktop-user-configs"],
    "restarts": [{"what": "kernel", "need": "reboot", "why": "newer kernel", "pids": []},
                 {"what": "dunst", "need": "reload", "why": "newer config", "pids": [3]}],
    "channel": "edge", "boot": "GRUB",
    "snapshots": {"snapper": True, "config": True, "snap_pac": True},
    "rollbacks": [{"at": "2026-10-09T21:35:24.786947466-07:00", "channel": "edge", "rolled_back": False,
                   "snapshot": {"pre": 216, "post": 217},
                   "packages": ["bromigos-core 0.1.2.r144.g421add4-1 -> 0.1.2.r145.g9df93cb-1"]},
                  {"at": "2026-10-01T10:00:00-07:00", "rolled_back": True, "snapshot": {"pre": 1, "post": 2},
                   "packages": []}]}}


class Parse(unittest.TestCase):
    def test_the_check(self):
        d = U.parse(DOC)
        self.assertEqual(d["packages"], [{"name": "waybar", "from": "0.15.0-3", "to": "0.15.1-1"}])
        self.assertEqual(d["aur"], [{"name": "zen-browser-bin", "from": "1.16.1b-1", "to": "1.16.2b-1"}])
        self.assertEqual(U.pending(d), 2)
        self.assertTrue(d["reboot"])
        self.assertFalse(d["relogin"])
        self.assertTrue(d["snapper"])
        self.assertEqual(d["channel"], "edge")
        self.assertEqual(len(d["rollbacks"]), 1)                       # the rolled-back one is left out
        rb = d["rollbacks"][0]
        self.assertEqual((rb["pre"], rb["post"]), (216, 217))
        self.assertEqual(rb["packages"][0]["name"], "bromigos-core")
        self.assertAlmostEqual(rb["at"], 1791606924.787, places=2)     # nanoseconds read

    def test_unknown_packages_stay_unknown(self):
        d = U.parse({"check": {"packages": None}})
        self.assertIsNone(d["packages"])
        self.assertEqual(d["aur"], [])
        self.assertEqual(d["rollbacks"], [])


class Sparse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p = [mock.patch.object(U, "CACHE_FILE", os.path.join(self.tmp, "updates.json")),
                  mock.patch.object(U, "PACMAN_DB", os.path.join(self.tmp, "local"))]
        for p in self.p:
            p.start()
        os.makedirs(U.PACMAN_DB)
        os.utime(U.PACMAN_DB, (time.time() - 7200, time.time() - 7200))
        self.runs = 0

    def tearDown(self):
        for p in self.p:
            p.stop()

    def fake_run(self, argv, **kw):
        self.runs += 1
        self.assertEqual(argv, ["bromigos", "update", "--check", "--json"])
        return mock.Mock(stdout=json.dumps(DOC), stderr="", returncode=0)

    def test_a_fresh_answer_is_reused(self):
        with mock.patch.object(U.subprocess, "run", self.fake_run):
            d1, at1 = U.check()
            d2, at2 = U.check()
        self.assertEqual(self.runs, 1)
        self.assertEqual(at1, at2)
        self.assertEqual(U.pending(d2), 2)

    def test_force_and_age_and_a_pacman_change_check_again(self):
        with mock.patch.object(U.subprocess, "run", self.fake_run):
            U.check()
            U.check(force=True)
            self.assertEqual(self.runs, 2)
            U.check(now=time.time() + U.EVERY + 5)
            self.assertEqual(self.runs, 3)
            os.utime(U.PACMAN_DB, None)                                 # an update ran
            time.sleep(0.01)
            U.check()
            self.assertEqual(self.runs, 4)

    def test_a_failed_check_says_why(self):
        with mock.patch.object(U.subprocess, "run",
                               lambda *a, **k: mock.Mock(stdout="", stderr="error: no network\n", returncode=1)):
            with self.assertRaises(RuntimeError) as c:
                U.check(force=True)
        self.assertIn("no network", str(c.exception))


class Panel(unittest.TestCase):
    def test_every_size_class(self):
        PT.every_class(self, PT.make(U.UpdatesPanel, demo=True))

    def test_empty_states(self):
        p = PT.make(U.UpdatesPanel, demo=True)
        p.poll = mock.Mock(data=None, error="the bromigos command isn't installed", busy=False)
        self.assertTrue(any("bromigos command" in t for t in PT.draw(p, 460, 280)))
        p.poll = mock.Mock(data=(U.parse({"check": {"packages": None}}), time.time()), error=None, busy=False)
        self.assertTrue(any("pacman-contrib" in t for t in PT.draw(p, 460, 280)))
        p.poll = mock.Mock(data=None, error=None, busy=True)
        self.assertTrue(any("CHECKING" in t.upper() for t in PT.draw(p, 460, 280)))

    def test_update_runs_in_a_terminal(self):
        p = PT.make(U.UpdatesPanel, demo=True)
        with mock.patch.object(U.K, "spawn") as sp:
            p.update()
        self.assertEqual(sp.call_args[0][0][-2:], ["bromigos", "update"])
        self.assertEqual(sp.call_args[0][0][:2], ["bromigos", "terminal"])


if __name__ == "__main__":
    unittest.main()
