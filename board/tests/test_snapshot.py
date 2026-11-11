"""The root-run snapshot against the fixtures' stand-in `bromigos`: what it reads, what it does
when a command is missing or fails, that it never writes a secret, its file's mode, and that it
stops when nobody looks."""
import json
import os
import stat
import subprocess
import threading
import time
import unittest
from unittest import mock

from common import BOARD, Root

from bromigos_board import paths, snapshot


class GatherTests(Root):
    def test_every_part_from_its_command(self):
        doc = snapshot.gather()
        self.assertEqual([n for n, _ in snapshot.SOURCES], ["system", "storage", "backups", "activity", "alerts", "apps", "budget"])
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

    def test_written_for_the_boards_group_only(self):
        snapshot.write(snapshot.gather())
        st = os.stat(self.path(paths.SNAPSHOT))
        self.assertEqual(oct(st.st_mode & 0o777), "0o640")
        # nothing else left behind: no temporary file
        self.assertEqual(sorted(p.name for p in self.path(paths.RUN).iterdir()), ["board.json", "door", "wanted"])

    def test_on_a_server_the_commands_are_whole_paths(self):
        """Root's reader never looks a command up in PATH on a server; in a stand-in root it does."""
        self.assertEqual(paths.tool("bromigos"), "bromigos")
        with mock.patch.object(paths, "really_root", lambda: True):
            self.assertEqual(paths.root(), "/")                      # BROMIGOS_ROOT isn't honoured as root
            self.assertEqual(paths.tool("bromigos"), "/usr/bin/bromigos")
            self.assertEqual(paths.tool("bromigos-activity"), "/usr/lib/bromigos/bin/bromigos-activity")
        # a whole path is run as it is, or not at all: PATH is never asked
        with mock.patch.object(paths, "tool", lambda name: "/nonexistent/bromigos"):
            doc, note = snapshot.run_source(["bromigos", "alerts", "--json"])
            self.assertEqual((doc, note["rc"], note["why"]), (None, 127, "bromigos isn't installed"))
        from common import FIXTURES
        with mock.patch.object(paths, "tool", lambda name: str(FIXTURES / "bromigos")), \
                mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):          # the stand-in is not on it
            doc, note = snapshot.run_source(["bromigos", "alerts", "--json"], env=dict(os.environ))
            self.assertTrue(note["ok"])

    def test_the_test_switches_are_not_honoured_as_root(self):
        os.environ["BROMIGOS_BOARD_HOSTNAME"] = "elsewhere"
        os.environ["BROMIGOS_BOARD_NOW_MS"] = "5"
        self.assertEqual((paths.hostname(), paths.now_ms(), paths.stand_in()), ("elsewhere", 5, True))
        with mock.patch.object(paths, "really_root", lambda: True):
            self.assertNotEqual(paths.hostname(), "elsewhere")
            self.assertGreater(paths.now_ms(), 5)
            self.assertEqual((paths.root(), paths.stand_in(), paths.at("/run/x")), ("/", False, "/run/x"))


class RootWritesNothingThroughALink(Root):
    """The reader is root, and writes board.json in a folder the board's user can only read. Even
    so, the write itself trusts nothing in that folder: a random name made exclusively and without
    following a link, mode and group set on the descriptor, then a rename (paths.write_at)."""

    def victim(self, name="shadow"):
        v = self.root / "etc" / name
        v.write_text("root's file\n")
        v.chmod(0o600)
        return v

    def untouched(self, v):
        return v.read_text() == "root's file\n" and stat.S_IMODE(v.stat().st_mode) == 0o600

    def test_a_link_at_the_old_temporary_name_is_never_opened(self):
        """What was: board.json.<pid>.tmp, opened O_CREAT|O_TRUNC, so a link there was written
        through, and its target chmod'ed."""
        v = self.victim()
        run = self.path(paths.RUN)
        for pid in range(os.getpid() - 2, os.getpid() + 3):
            os.symlink(v, run / f"board.json.{pid}.tmp")
        snapshot.write({"schema": 1, "at": paths.now_ms()})
        self.assertTrue(self.untouched(v))
        self.assertTrue(self.path(paths.SNAPSHOT).is_file() and not self.path(paths.SNAPSHOT).is_symlink())

    def test_a_link_where_board_json_goes_is_replaced_not_followed(self):
        v = self.victim()
        os.symlink(v, self.path(paths.SNAPSHOT))
        snapshot.write({"schema": 1, "at": 7})
        self.assertTrue(self.untouched(v))
        self.assertFalse(self.path(paths.SNAPSHOT).is_symlink())
        self.assertEqual(json.loads(self.path(paths.SNAPSHOT).read_text())["at"], 7)

    def test_a_fifo_swapped_for_a_link_gives_nobody_a_root_file(self):
        """The review's proof: a FIFO at the temporary name, swapped for a link once root has
        opened it, made root chmod and chown the link's target by path."""
        v = self.victim()
        run = self.path(paths.RUN)
        tmp = run / f"board.json.{os.getpid()}.tmp"
        os.mkfifo(tmp)
        os.symlink(v, run / "x")
        opened = []

        def board_user():
            try:
                fd = os.open(tmp, os.O_RDONLY | os.O_NONBLOCK)      # (the proof waits here for root's open)
                time.sleep(0.3)
                opened.append(os.read(fd, 65536))
                os.close(fd)
            except OSError as e:
                opened.append(e)
        t = threading.Thread(target=board_user)
        t.start()
        snapshot.write({"schema": 1, "at": paths.now_ms(), "big": "x" * 200_000})
        t.join(10)
        self.assertEqual(opened, [b""], "root never opened the FIFO")
        self.assertTrue(self.untouched(v))
        self.assertFalse(self.path(paths.SNAPSHOT).is_symlink())

    def test_the_temporary_file_is_exclusive_and_never_follows_and_nothing_is_set_by_path(self):
        opens, real_open = [], os.open

        def spy(path, flags, mode=0o777, *, dir_fd=None):
            opens.append((path, flags, dir_fd))
            return real_open(path, flags, mode, dir_fd=dir_fd)

        def by_path(*a, **k):
            raise AssertionError("mode and owner are set on the descriptor, never by path")
        with mock.patch.object(os, "open", spy), mock.patch.object(os, "chmod", by_path), \
                mock.patch.object(os, "chown", by_path), mock.patch.object(os, "lchown", by_path):
            snapshot.write({"schema": 1})
        folder, temp = opens
        self.assertEqual(folder[0], str(self.path(paths.RUN)))
        self.assertTrue(folder[1] & os.O_DIRECTORY and folder[1] & os.O_NOFOLLOW)
        want = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        self.assertEqual(temp[1] & want, want)
        self.assertFalse(temp[1] & os.O_TRUNC)
        self.assertIsNotNone(temp[2], "made relative to the folder's descriptor")
        self.assertRegex(temp[0], r"^\.board\.json\.[0-9a-f]{16}\.tmp$")
        self.assertNotIn(str(os.getpid()), temp[0].split(".")[3:4])

    def test_two_writes_never_share_a_name(self):
        names = set()
        real = os.open

        def spy(path, flags, mode=0o777, *, dir_fd=None):
            if dir_fd is not None:
                names.add(path)
            return real(path, flags, mode, dir_fd=dir_fd)
        with mock.patch.object(os, "open", spy):
            for _ in range(20):
                snapshot.write({"schema": 1})
        self.assertEqual(len(names), 20)

    def test_a_link_where_the_folder_should_be_is_refused(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        run = self.path(paths.RUN)
        for f in run.iterdir():
            f.unlink()
        run.rmdir()
        os.symlink(elsewhere, run)
        with self.assertRaises(NotADirectoryError):
            snapshot.write({"schema": 1})
        self.assertEqual(os.listdir(elsewhere), [])

    def test_the_group_is_set_on_the_descriptor(self):
        calls = []
        with mock.patch.object(os, "fchown", lambda fd, uid, gid: calls.append((uid, gid))):
            paths.write_json(str(self.path(paths.SNAPSHOT)), {"schema": 1}, mode=0o640, group=os.getgid())
        self.assertEqual(calls, [(-1, os.getgid())])
        self.assertEqual(stat.S_IMODE(self.path(paths.SNAPSHOT).stat().st_mode), 0o640)

    def test_a_write_that_fails_leaves_nothing_behind(self):
        with mock.patch.object(os, "replace", side_effect=OSError("no")), self.assertRaises(OSError):
            snapshot.write({"schema": 1})
        self.assertEqual(sorted(p.name for p in self.path(paths.RUN).iterdir()), ["door", "wanted"])


class FilterTests(Root):
    """The second line, best effort: what a command printed anyway (docs/board.md)."""

    def test_names(self):
        for name in ("password", "passwords", "passphrase", "pwd", "secret", "client_secret", "token", "admin_token", "API_KEY",
                     "apiKey", "authkey", "key", "keys", "ssh_key", "psk", "pin", "otp_seed", "cookie", "credentials",
                     "recovery_bundle", "join_code", "joinCode", "unseal_key", "Authorization", "DB_PASSWORD",
                     "HTTPToken", "JOIN_CODE", "X-Api-Key"):
            self.assertTrue(snapshot.secret_name(name), name)
        for name in ("password_hash", "token_b64", "keyFile", "password-file", "secret_id", "access_key_id", "SECRET_VALUE", "password2",
                     "token_1"):
            self.assertTrue(snapshot.secret_name(name), name)       # a secret's word, then the form it is in
        for name in ("exit_code", "code", "passed", "last_check_passed", "monkey", "spin", "pinned", "hotkeys", "seeded_from",
                     "id", "to", "model", "verdict", "state", "open", "household", "", "_"):
            self.assertFalse(snapshot.secret_name(name), name)

    def test_a_name_is_read_by_its_words_and_the_last_one_says_what_the_value_is(self):
        # words, never a run of letters inside one: "passed" isn't "pass", "monkey" isn't "key"
        for name in ("last_test_passed", "last_check_passed", "passes", "bypass", "compass", "tokenizer", "keyboard", "pinned_at"):
            self.assertFalse(snapshot.secret_name(name), name)
        # a count, a time, a place or a yes/no about a secret is not the secret
        for name in ("token_count", "key_count", "secret_store", "token_ttl", "key_age_days", "password_changed_at", "keys_total",
                     "password_required", "token_expires", "key_kind", "public_key", "ssh_public_key"):
            self.assertFalse(snapshot.secret_name(name), name)

    def test_the_backups_last_passed_test_and_check_reach_the_page(self):
        """`bromigos lab backups status --json` as it is printed: the last test restore and the
        last check that passed are records, and the page reads their times."""
        rec = {"phase": "ok", "at": "2026-10-29T05:53:20+00:00", "ts": 1793253200.0, "age_s": 1036800, "files": 100}
        doc = {"schema": 1, "server": True, "configured": True, "to": "s3:https://s3.example/backups/myserver",
               "last_test": dict(rec), "last_test_passed": dict(rec), "last_check": dict(rec, files=None),
               "last_check_passed": dict(rec, files=None), "token_count": 2, "key_count": 1, "secret_store": "the system keyring",
               "snapshots": {"count": 17, "oldest": "2026-05-14T05:53:20+00:00", "newest": "2026-11-09T22:53:20+00:00"}}
        self.assertEqual(snapshot.scrub(doc, "backups"), doc)
        got = snapshot.scrub(dict(doc, password="hunter2", repository_password_file="/etc/x", last_test_passed=dict(rec, token="t0k")))
        self.assertEqual(got, dict(doc, last_test_passed=rec))

    def test_only_yes_no_and_nothing_stay_under_a_secrets_name(self):
        self.assertEqual(snapshot.scrub({"password": "x", "passwords": False, "token": None, "join_code": 482913, "pin": 1234,
                                         "key": {"a": 1}, "keys": ["a"], "secret": 0.5, "has_key": True, "ok": "fine", "n": 3}),
                         {"passwords": False, "token": None, "has_key": True, "ok": "fine", "n": 3})

    def test_whether_a_secret_is_set_stays(self):
        # `bromigos alerts --json`, a channel: its address and key are only ever said to be set or not
        ch = {"name": "ops", "type": "webhook", "address": "set", "key": "set", "token": "not set", "password": None}
        self.assertEqual(snapshot.scrub({"channels": [ch]}, "alerts"), {"channels": [ch]})
        self.assertEqual(snapshot.scrub({"key": "set ", "token": "unset", "secret": ["set"]}), {})

    def test_the_shapes_the_review_named(self):
        doc = {
            "key": "restic-repository-key", "authkey": "tskey-auth-kABCDEF", "psk": "wireguard-preshared", "pin": "482913",
            "otp_seed": "JBSWY3DPEHPK3PXP", "cookie": "sid=abc", "join_code": 482913,
            "env": ["ADMIN_TOKEN=hunter2", "DB_PASSWORD=hunter3"], "args": "--password hunter4",
            "argv": ["restic", "--password-file", "/etc/x", "-r", "repo", "--password", "hunter7"],
            "fields": [{"name": "admin_token", "value": "hunter5"}, {"name": "colour", "value": "blue"}],
            "url": "https://example.org/hook?token=hunter6", "to": "s3:https://user:hunter8@s3.example.org/x",
        }
        out = json.dumps(snapshot.scrub(doc))
        for secret in ("restic-repository-key", "tskey-auth", "wireguard-preshared", "482913", "JBSWY3DPEHPK3PXP", "sid=abc",
                       "hunter2", "hunter3", "hunter4", "hunter5", "hunter6", "hunter7", "hunter8", "/etc/x"):
            self.assertNotIn(secret, out, secret)
        self.assertIn('"value": "blue"', out)
        self.assertIn("s3:https://s3.example.org/x", out)

    def test_what_isnt_a_secret_stays(self):
        doc = {"drives": [{"key": "samsung-ssd-980-pro-2tb-0f1c3b46", "model": "x"}], "error": {"code": "not-a-server"},
               "exit_code": 3, "last_check_passed": True, "how": "keys and a password", "title": "Backups: fine",
               "command": ["bromigos", "lab", "apps", "restart", "photos"]}
        self.assertEqual(snapshot.scrub(doc, "storage"), doc)
        self.assertEqual(snapshot.scrub({"key": "abc"}, "storage"), {})          # only a drive's id, in the drives' list

    def test_a_failed_commands_last_line_goes_through_the_filter(self):
        fake = self.root / "bin"
        fake.mkdir()
        (fake / "bromigos").write_text("#!/bin/sh\necho 'Fatal: unable to open repository at "
                                       "s3:https://backupuser:hunter2@s3.example.org/x' >&2\n"
                                       "echo 'repository password=hunter3 was refused' >&2\nexit 1\n")
        (fake / "bromigos").chmod(0o755)
        os.environ["PATH"] = f"{fake}:{os.environ['PATH']}"
        doc = snapshot.gather()
        snapshot.write(doc)
        text = self.path(paths.SNAPSHOT).read_text()
        self.assertNotIn("hunter", text)
        self.assertIn("password=***", doc["sources"]["backups"]["why"])


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
