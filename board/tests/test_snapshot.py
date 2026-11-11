"""The root-run snapshot against the fixtures' stand-in `bromigos`: what it reads, what it does
when a command is missing or fails, that it never writes a secret, its file's mode, and that it
stops when nobody looks."""
import json
import os
import time
import unittest

from common import Root

from bromigos_board import paths, snapshot


class GatherTests(Root):
    def test_every_part_from_its_command(self):
        doc = snapshot.gather()
        self.assertEqual([n for n, _ in snapshot.SOURCES], ["system", "storage", "backups", "activity", "alerts", "apps"])
        for name, argv in snapshot.SOURCES:
            self.assertEqual(argv[0], "bromigos")
            self.assertEqual(argv[-1], "--json")
            self.assertTrue(doc["sources"][name]["ok"], name)
            self.assertIsNotNone(doc[name], name)
        self.assertEqual(doc["host"], "myserver")
        self.assertEqual(doc["settings"], {"door": True, "world": "wick"})
        self.assertNotIn("door_fallback", doc)
        self.assertEqual(doc["sources"]["alerts"]["rc"], 1)

    def test_a_missing_command_is_noted_and_its_part_is_null(self):
        os.environ["BOARD_MISSING"] = "lab apps"
        doc = snapshot.gather()
        self.assertIsNone(doc["apps"])
        s = doc["sources"]["apps"]
        self.assertEqual((s["ok"], s["rc"]), (False, 2))
        self.assertIn("no command", s["why"])
        self.assertEqual(doc["door_fallback"], [])          # nothing set up in this stand-in root

    def test_no_bromigos_at_all(self):
        os.environ["PATH"] = str(self.root)
        doc = snapshot.gather()
        for name, _ in snapshot.SOURCES:
            self.assertIsNone(doc[name])
            self.assertEqual(doc["sources"][name]["rc"], 127)
            self.assertEqual(doc["sources"][name]["why"], "bromigos isn't installed")

    def test_no_secret_is_ever_written(self):
        snapshot.write(snapshot.gather())
        text = self.path(paths.SNAPSHOT).read_text()
        for secret in ("should-never-reach-the-board", "hunter2", "backupuser:"):
            self.assertNotIn(secret, text)
        doc = json.loads(text)
        self.assertNotIn("repository_password", doc["system"]["backup"])
        self.assertNotIn("admin_token", doc["apps"][1])

    def test_scrub(self):
        self.assertEqual(snapshot.scrub({"password": "x", "passwords": False, "api_key": "k", "API-Key": "k", "token": None,
                                         "join_code": "j", "recovery_bundle": {"a": 1}, "ok": "fine", "n": 3,
                                         "list": [{"secret": "s", "keep": "sftp:me@host:/srv"}],
                                         "url": "https://u:p@example.org/x and http://a@b.local"}),
                         {"passwords": False, "token": None, "ok": "fine", "n": 3,
                          "list": [{"keep": "sftp:me@host:/srv"}], "url": "https://example.org/x and http://b.local"})

    def test_written_for_the_boards_group_only(self):
        snapshot.write(snapshot.gather())
        st = os.stat(self.path(paths.SNAPSHOT))
        self.assertEqual(oct(st.st_mode & 0o777), "0o640")
        self.assertEqual([p.name for p in self.path(paths.RUN).iterdir()], ["board.json"])     # no temp file left


class LoopTests(Root):
    def test_once(self):
        self.assertEqual(snapshot.run(once=True, log=lambda w: None), 0)
        self.assertTrue(self.path(paths.SNAPSHOT).exists())

    def test_it_reads_while_a_browser_is_connected_then_stops(self):
        wanted = self.path(paths.WANTED)
        wanted.touch()
        naps = []

        def sleep(s):
            naps.append(s)
            if len(naps) == 2:            # the browser went away: nobody touched it for a minute
                old = time.time() - 60
                os.utime(wanted, (old, old))
        self.assertEqual(snapshot.run(interval=15, idle=45, sleep=sleep, log=lambda w: None), 0)
        self.assertEqual(len(naps), 2)
        self.assertTrue(all(0 <= s <= 15 for s in naps))

    def test_nobody_asked(self):
        naps = []
        snapshot.run(sleep=naps.append, log=lambda w: None)
        self.assertEqual(naps, [])


if __name__ == "__main__":
    unittest.main()
