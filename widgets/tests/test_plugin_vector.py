"""plugins/vector.py: his state file, the audit log (values never shown, secrets redacted),
his pull requests, the switch's click, and the empty states."""
import json
import os
import tempfile
import unittest
from unittest import mock

import plugintest as PT
import vector as V


class Audit(unittest.TestCase):
    def test_values_never_come_through(self):
        lines = [json.dumps({"t": "2026-10-09T14:47:38-0700", "tool": "run_shell",
                             "args": {"command": "curl -H 'Authorization: Bearer abc' https://x", "cwd": "/home/me"},
                             "ok": False, "err": "refused: token=ghp_" + "a" * 36}),
                 "not json", "",
                 json.dumps({"t": "2026-10-09T19:02:30-0700", "tool": "memory.refresh", "ok": True, "items": 88})]
        got = V.parse_audit(lines)
        self.assertEqual([a["tool"] for a in got], ["memory.refresh", "run_shell"])     # newest first
        shell = got[1]
        self.assertEqual(shell["keys"], ["command", "cwd"])
        self.assertFalse(shell["ok"])
        self.assertNotIn("ghp_", shell["err"])
        self.assertIn("redacted", shell["err"])
        self.assertNotIn("curl", json.dumps(got))

    def test_tail_of_a_big_log(self):
        path = os.path.join(tempfile.mkdtemp(), "vector-audit.log")
        with open(path, "w") as f:
            for i in range(4000):
                f.write(json.dumps({"t": "2026-10-09T10:00:00-0700", "tool": f"t{i}", "ok": True, "args": {"x": i}}) + "\n")
        got = V.read_audit(path, limit=5)
        self.assertEqual([a["tool"] for a in got], ["t3999", "t3998", "t3997", "t3996", "t3995"])
        self.assertIsNone(V.read_audit(path + ".missing"))


class Status(unittest.TestCase):
    def test_read(self):
        path = os.path.join(tempfile.mkdtemp(), "s.json")
        self.assertIsNone(V.read_status(path))
        with open(path, "w") as f:
            json.dump({"state": "idle", "switch": "off"}, f)
        self.assertEqual(V.read_status(path)["switch"], "off")


class Prs(unittest.TestCase):
    def test_parse(self):
        got = V.parse_prs([{"number": 3, "title": "a", "url": "u3", "isDraft": True, "updatedAt": "2026-10-01T00:00:00Z",
                            "repository": {"name": "r", "nameWithOwner": "o/r"}},
                           {"number": 4, "title": "b", "url": "u4", "isDraft": False, "updatedAt": "2026-10-02T00:00:00Z",
                            "repository": {"nameWithOwner": "o/r"}}])
        self.assertEqual([p["number"] for p in got], [4, 3])
        self.assertEqual((got[1]["draft"], got[1]["repo"]), (True, "o/r"))

    def test_gh_not_signed_in(self):
        with mock.patch.object(V.shutil, "which", lambda n: "/usr/bin/gh"), \
                mock.patch.object(V.subprocess, "run", lambda *a, **k: mock.Mock(
                    returncode=4, stdout="", stderr="To get started with GitHub CLI, please run:  gh auth login")):
            with self.assertRaises(V.GhError) as c:
                V.fetch_prs("someone")
        self.assertIn("gh auth login", str(c.exception))


class Panel(unittest.TestCase):
    def test_every_size_class(self):
        PT.every_class(self, PT.make(V.VectorPanel, demo=True))

    def test_switch_only_toggles(self):
        p = PT.make(V.VectorPanel, demo=True)
        with mock.patch.object(V.K, "spawn") as sp:
            p.toggle_switch()
        self.assertEqual(sp.call_args[0][0], ["bromigos", "vector", "switch", "toggle"])
        tips = PT.draw(p, 460, 300)
        self.assertTrue(any("YES first" in t for t in tips) or any("switch him OFF" in t for t in tips))
        p.status = dict(p.status, switch="off")
        tips = PT.draw(p, 460, 300)
        self.assertTrue(any("asks for YES first" in t for t in tips))

    def test_available(self):
        with mock.patch.object(V.shutil, "which", lambda n: None), mock.patch.object(V.os.path, "exists", lambda p: False), \
                mock.patch.object(V.K, "demo", lambda: False):
            ok = V.VectorPanel.available()
        self.assertEqual(ok[0], False)
        self.assertIn("isn't installed", ok[1])
        with mock.patch.object(V.shutil, "which", lambda n: "/usr/bin/" + n):
            self.assertIs(V.VectorPanel.available(), True)

    def test_not_installed(self):
        p = PT.make(V.VectorPanel, demo=True)
        p.installed = False
        self.assertTrue(any("bromigos-vector" in t for t in PT.draw(p, 460, 300)))

    def test_not_running_and_no_prs(self):
        p = PT.make(V.VectorPanel, demo=True)
        p.status, p.audit, p.demo_prs = None, [], None
        p.prs = mock.Mock(data=None, error="gh isn't signed in: run gh auth login", at=0)
        tips = PT.draw(p, 800, 600)
        self.assertTrue(any("isn't running" in t for t in tips))
        self.assertTrue(any("gh auth login" in t for t in tips))


if __name__ == "__main__":
    unittest.main()
