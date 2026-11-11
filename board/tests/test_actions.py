"""Actions from the page. The API writes a request in its own folder and can start nothing; root's
helper takes requests out of that folder, checks each again, builds the job's command itself and
leaves its answer in root's folder.

Every refusal: no session, CSRF, a verb off the list, an id that isn't the catalogue's, free text,
[board] actions, an old, reused, linked, forged or foreign request. And the line between the
board's user and root: where the answer goes and how it's written, that no answer quotes a
request, that a code the board's user made deletes nothing, and the helper's sandbox. No unit
starts and no command runs here: both are stand-ins."""
import contextlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from common import BOARD, LAN, NOW, REPO, Root

from starlette.testclient import TestClient

from bromigos_board import actions, api, auth, board, cli, paths, snapshot

ORIGIN = "https://myserver.local"
PAGE = {"x-bromigos-board": "1", "origin": ORIGIN}
JOB = "20261110-1200-app.restart-photos-1a2b"
UNITS = BOARD / "systemd"


def unit(name):
    out = {}
    for line in (UNITS / name).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), []).append(v.strip())
    return out


def tmpfiles():
    out = {}
    for line in (BOARD / "bromigos-board.tmpfiles").read_text().splitlines():
        if line and not line.startswith("#"):
            kind, path, mode, user, group = line.split()[:5]
            out[path] = (kind, mode, user, group)
    return out


class Base(Root):
    def setUp(self):
        super().setUp()
        # as tmpfiles leaves them: the board's folder of requests, root's of answers and of codes
        for d in (actions.REQUESTS, actions.RESULTS, actions.ROOT_CODES):
            self.path(d).mkdir(parents=True)
        self.ran, self.waits, self.logged = [], [], []
        self.tries = auth.Tries(clock=lambda: 1000.0)
        self.app = api.make_app(tries=self.tries, sleep=self.sleep, after_ask=self.helper, action_wait_s=2)
        self.c = TestClient(self.app, base_url=ORIGIN, headers={"x-forwarded-for": LAN})

    async def sleep(self, seconds):
        self.waits.append(seconds)

    def fake_run(self, argv):
        self.ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"schema": 1, "id": JOB, "unit": "u"}), "")

    def helper(self, rid):
        """Root's helper, stood in for: it runs as its unit would once the request is there."""
        actions.act(rid, run=self.fake_run, log=self.logged.append)

    def sign_in(self):
        code, _ = self.new_code()
        self.assertEqual(self.c.post("/api/session", json={"code": code}, headers=PAGE).status_code, 200)

    def new_code(self):
        """sudo bromigos server board code: root's own note of the code, then the board's record."""
        now, code = paths.now_ms(), auth.fresh_code()
        actions.note_code(code, now + auth.CODE_MS, now)
        return auth.new_code(now, code)

    def post(self, body, headers=PAGE):
        return self.c.post("/api/actions", json=body, headers=headers)

    def left(self, folder=actions.REQUESTS):
        d = self.path(folder)
        return sorted(os.listdir(d)) if d.is_dir() else []

    def write(self, rid, **doc):
        rec = {"schema": 1, "id": rid, "verb": "restart", "app": "photos", "at": paths.now_ms(), "browser": "Firefox"}
        rec.update(doc)
        p = self.path(f"{actions.REQUESTS}/{rid}.json")
        p.write_text(json.dumps(rec))
        return p

    def act(self, rid):
        return actions.act(rid, run=self.fake_run, log=self.logged.append)

    def answer(self, rid):
        return json.loads(self.path(f"{actions.RESULTS}/{rid}.json").read_text())


class AskTests(Base):
    def test_a_restart_becomes_a_job_with_a_command_built_by_root(self):
        self.sign_in()
        r = self.post({"verb": "restart", "app": "photos"})
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(r.json()["job"], JOB)
        self.assertEqual(r.json()["words"], "Restarting Photos.")
        self.assertEqual(self.ran, [["bromigos-activity", "run", "--kind", "app.restart", "--title", "Restarting Photos",
                                     "--subject", "app:photos:Photos", "--lock", "apps", "--via", "board",
                                     "--device", "A browser", "--detach", "--json", "--",
                                     "bromigos", "lab", "apps", "restart", "photos"]])
        self.assertEqual(self.left(), [], "the request is used up")
        self.assertEqual(self.left(actions.RESULTS), [r.json()["request"] + ".json"], "the answer is in root's folder")

    def test_on_a_server_the_command_is_whole_paths(self):
        with mock.patch.object(paths, "stand_in", lambda: False):
            argv = actions.command("restart", "photos", "Photos", "x")
        self.assertEqual(argv[0], "/usr/lib/bromigos/bin/bromigos-activity")
        self.assertEqual(argv[argv.index("--") + 1:], ["/usr/bin/bromigos", "lab", "apps", "restart", "photos"])

    def test_add_and_remove(self):
        self.sign_in()
        self.assertEqual(self.post({"verb": "add", "app": "uptime"}).status_code, 202)
        self.assertEqual(self.post({"verb": "remove", "app": "uptime"}).status_code, 202)
        self.assertEqual([a[-3:] for a in self.ran], [["apps", "add", "uptime"], ["apps", "remove", "uptime"]])
        self.assertNotIn("--delete-data", self.ran[1])
        self.assertEqual(self.ran[1][self.ran[1].index("--kind") + 1], "app.remove")

    def test_the_api_starts_nothing(self):
        """It has no right over systemd, and asks for none: no systemctl, no polkit rule."""
        text = (BOARD / "lib" / "bromigos_board" / "api.py").read_text() + \
            (BOARD / "lib" / "bromigos_board" / "actions.py").read_text().split("# ---------------------------------------------------------------- root's side")[0]
        for word in ("systemctl", "subprocess.run", "polkit"):
            self.assertNotIn(word, text.split('"""', 2)[2], word)
        self.assertFalse((BOARD / "polkit").exists())
        self.assertNotIn("polkit", (REPO / "packaging" / "bromigos-board" / "PKGBUILD").read_text().split("\npkgname=")[1])
        self.assertFalse((UNITS / "bromigos-board-act@.service").exists())

    def test_no_session_no_action(self):
        r = self.post({"verb": "restart", "app": "photos"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual((self.ran, self.left(), self.left(actions.RESULTS)), ([], [], []))

    def test_csrf(self):
        self.sign_in()
        for h in ({"origin": ORIGIN}, {**PAGE, "origin": "https://evil.example.org"}, {**PAGE, "sec-fetch-site": "cross-site"}):
            self.assertEqual(self.post({"verb": "restart", "app": "photos"}, headers=h).status_code, 403, h)
        r = self.c.post("/api/actions", content="verb=restart&app=photos",
                        headers={**PAGE, "content-type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 415)
        self.assertEqual((self.ran, self.left()), ([], []))

    def test_a_verb_off_the_list_or_free_text_never_leaves_the_api(self):
        self.sign_in()
        for body in ({"verb": "logs", "app": "photos"}, {"verb": "remove --delete-data", "app": "photos"},
                     {"verb": "restart", "app": "photos; rm -rf /"}, {"verb": "restart", "app": "../../etc"},
                     {"verb": "restart", "app": "-x"}, {"verb": "restart"}, {"verb": ["restart"], "app": "photos"},
                     {"verb": "run", "app": "photos", "command": "id"}, {"verb": "restart", "app": "photos\n"}):
            r = self.post(body)
            self.assertEqual(r.status_code, 400, body)
            self.assertIn(r.json()["error"]["code"], ("unknown-verb", "unknown-app"))
        self.assertEqual((self.ran, self.left(), self.left(actions.RESULTS)), ([], [], []))

    def test_an_app_that_isnt_in_the_catalogue_is_refused_by_root(self):
        self.sign_in()
        r = self.post({"verb": "restart", "app": "not-an-app"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "unknown-app"))
        self.assertEqual(self.ran, [])

    def test_roots_board_table_decides(self):
        self.sign_in()
        self.path("etc/bromigos/server.toml").write_text('[board]\nactions = ["restart"]\n')
        self.assertEqual(self.post({"verb": "restart", "app": "photos"}).status_code, 202)
        r = self.post({"verb": "remove", "app": "photos"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "not-allowed"))
        self.path("etc/bromigos/server.toml").write_text('[board]\nactions = []\n')
        self.assertEqual(self.post({"verb": "restart", "app": "photos"}).status_code, 403)
        self.assertEqual(len(self.ran), 1)

    def test_the_board_says_which_actions_the_page_may_offer(self):
        """`actions` in the board's document: root's [board] actions, as the reader read them."""
        def offered():
            snapshot.write(snapshot.gather())
            return self.c.get("/api/board").json()["actions"]
        self.sign_in()
        self.assertEqual(offered(), list(actions.DEFAULT_ACTIONS))           # left out: all of them
        self.assertEqual(offered()[:4], ["restart", "add", "remove", "delete-data"])
        self.path("etc/bromigos/server.toml").write_text('[board]\nactions = ["restart", "reboot", 7]\n')
        self.assertEqual(offered(), ["restart"], "only words the board knows")
        self.path("etc/bromigos/server.toml").write_text('[board]\nactions = []\n')
        self.assertEqual(offered(), [])
        self.path("etc/bromigos/server.toml").write_text('[board]\nactions = "restart"\n')
        self.assertEqual(offered(), [], "not a list: nothing")
        self.path("etc/bromigos/server.toml").unlink()
        self.path(actions.REQUESTS).rmdir()
        self.assertEqual(offered(), [], "actions aren't set up: nothing is offered")
        # an old reading without the key, or with something else under it
        self.assertEqual(board.shape({"at": 1, "actions": "restart"}, 1)["actions"], [])
        self.assertEqual(board.shape({"at": 1}, 1)["actions"], [])

    def test_when_the_helper_is_slow_the_page_is_told_to_watch_activity(self):
        self.sign_in()
        self.app.app.state.after_ask = None
        self.app.app.state.action_wait_s = 0.2
        r = self.post({"verb": "restart", "app": "photos"})
        self.assertEqual(r.status_code, 202)
        self.assertIsNone(r.json()["job"])
        self.assertEqual(len(self.left()), 1, "the request waits for the helper")

    def test_without_the_folder_actions_arent_set_up(self):
        self.sign_in()
        self.path(actions.REQUESTS).rmdir()
        r = self.post({"verb": "restart", "app": "photos"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (503, "no-actions"))

    def test_a_request_is_written_whole_and_never_over_another(self):
        seen = []
        real = os.link

        def spy(src, dst, **k):
            seen.append((src, dst, json.loads(open(os.path.join(str(self.path(actions.REQUESTS)), src)).read())["id"]))
            return real(src, dst, **k)
        with mock.patch.object(os, "link", spy):
            rid = actions.ask("restart", "photos", {"id": "s", "browser": "b"})
        (tmp, name, inside), = seen
        self.assertEqual((name, inside), (rid + ".json", rid), "it was whole before it took its name")
        self.assertTrue(tmp.startswith(".") and tmp.endswith(".tmp"))
        self.assertEqual(self.left(), [rid + ".json"])
        with mock.patch("secrets.token_hex", lambda n: rid if n == 8 else "0" * (2 * n)), self.assertRaises(FileExistsError):
            actions.ask("remove", "photos", {"id": "s", "browser": "b"})
        self.assertEqual(json.loads(self.path(f"{actions.REQUESTS}/{rid}.json").read_text())["verb"], "restart")
        self.assertEqual(self.left(), [rid + ".json"])


class RootWritesItsAnswerInItsOwnFolder(Base):
    """H1. The answer never goes into the folder the board's user owns, is never written through a
    link, and never quotes the request."""

    def test_where_the_answer_goes(self):
        self.assertEqual(os.path.dirname(actions.RESULTS), paths.RUN)
        t = tmpfiles()
        self.assertEqual(t[actions.RESULTS], ("d", "0750", "root", "bromigos-board"))
        self.assertEqual(t[actions.REQUESTS], ("d", "0750", "bromigos-board", "bromigos-board"))
        self.assertEqual(t[paths.RUN], ("d", "0750", "root", "bromigos-board"))
        self.write("00000000000000aa", verb="nonsense")
        self.act("00000000000000aa")
        self.assertEqual(self.left(), [], "nothing of root's is left in the board's folder")
        self.assertEqual(self.left(actions.RESULTS), ["00000000000000aa.json"])
        self.assertEqual(stat.S_IMODE(self.path(f"{actions.RESULTS}/00000000000000aa.json").stat().st_mode), 0o640)

    def test_a_link_planted_at_the_old_answers_names_is_never_written_through(self):
        """The review's proof: links at <id>.result.json.<pid>.tmp in the requests folder, pointing
        at a file of root's; and a request whose verb is text meant for that file."""
        victim = self.root / "etc" / "ld.so.preload"
        victim.write_text("root's file\n")
        victim.chmod(0o600)
        rid, req = "00000000000000aa", self.path(actions.REQUESTS)
        evil = "x /var/lib/bromigos-board/evil.so x"
        self.write(rid, verb=evil)
        for pid in range(os.getpid() - 3, os.getpid() + 4):
            os.symlink(victim, req / f"{rid}.result.json.{pid}.tmp")
        os.symlink(victim, req / f"{rid}.result.json")
        out = actions.act(rid, run=lambda a: self.fail("nothing may run"), log=self.logged.append)
        self.assertEqual(out["code"], "unknown-verb")
        self.assertEqual(victim.read_text(), "root's file\n")
        self.assertEqual(stat.S_IMODE(victim.stat().st_mode), 0o600)
        answer = self.path(f"{actions.RESULTS}/{rid}.json")
        self.assertTrue(answer.is_file() and not answer.is_symlink())

    def test_no_answer_quotes_the_request(self):
        marker = "/var/lib/bromigos-board/evil.so"
        cases = [{"verb": f"x {marker} x"}, {"app": marker}, {"app": "photos", "verb": "restart", "browser": marker, "at": 1},
                 {"verb": "remove", "delete_data": True, "code": marker}, {"id": marker}, {"delete_data": marker},
                 {"verb": "restart", "app": "not-an-app-" + "x" * 20}]
        for i, doc in enumerate(cases):
            rid = f"{i:016x}"
            self.write(rid, **doc)
            out = self.act(rid)
            self.assertFalse(out["ok"], doc)
            text = self.path(f"{actions.RESULTS}/{rid}.json").read_text()
            self.assertNotIn("evil", text, doc)
            self.assertNotIn("not-an-app", text, doc)
            self.assertEqual(out["words"], actions.REFUSALS[out["code"]], "the words are that refusal's own, fixed")
        # and through the API: what the page is told comes from the fixed words too
        self.sign_in()
        r = self.post({"verb": "restart", "app": "not-an-app"})
        self.assertEqual(r.json()["error"]["words"], actions.REFUSALS["unknown-app"])
        # a job that didn't start: its own last line goes to the log, not into the answer
        self.write("00000000000000ee")
        out = actions.act("00000000000000ee", log=self.logged.append,
                          run=lambda a: subprocess.CompletedProcess(a, 1, "", f"activity: {marker} no root\n"))
        self.assertEqual((out["code"], out["words"]), ("job-failed", actions.REFUSALS["job-failed"]))
        self.assertTrue(any(marker in line for line in self.logged))

    def test_the_answers_file_is_exclusive_and_never_follows(self):
        opens, real_open = [], os.open

        def spy(path, flags, mode=0o777, *, dir_fd=None):
            opens.append((str(path), flags, dir_fd))
            return real_open(path, flags, mode, dir_fd=dir_fd)

        def by_path(*a, **k):
            raise AssertionError("mode and owner are set on the descriptor, never by path")
        self.write("00000000000000aa")
        with mock.patch.object(os, "open", spy), mock.patch.object(os, "chmod", by_path), mock.patch.object(os, "chown", by_path):
            self.act("00000000000000aa")
        made = [o for o in opens if o[1] & os.O_CREAT]
        self.assertEqual(len(made), 1)
        want = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        self.assertEqual(made[0][1] & want, want)
        self.assertRegex(made[0][0], r"^\.00000000000000aa\.json\.[0-9a-f]{16}\.tmp$")
        self.assertIsNotNone(made[0][2])
        read = next(o for o in opens if o[0] == "00000000000000aa.json")
        self.assertTrue(read[1] & os.O_NOFOLLOW and read[1] & os.O_NONBLOCK)

    def test_the_helpers_unit_is_sandboxed(self):
        svc = unit("bromigos-board-act.service")
        for key, want in (("ProtectSystem", "strict"), ("ProtectHome", "yes"), ("PrivateTmp", "yes"), ("NoNewPrivileges", "yes"),
                          ("ProtectKernelTunables", "yes"), ("ProtectKernelModules", "yes"), ("ProtectControlGroups", "yes"),
                          ("RestrictSUIDSGID", "yes"), ("LockPersonality", "yes"), ("SystemCallArchitectures", "native"),
                          ("RestrictAddressFamilies", "AF_UNIX"), ("IPAddressDeny", "any")):
            self.assertEqual(svc.get(key), [want], key)
        writable = " ".join(svc["ReadWritePaths"]).split()
        self.assertEqual(set(writable), {actions.REQUESTS, actions.RESULTS, paths.STATE, actions.ROOT_STATE,
                                         "-/var/lib/bromigos/activity", "-/var/lib/bromigos/server/activity"})
        # nothing wider: not /run/bromigos-board whole, not /var/lib/bromigos whole, nothing of /etc or /usr
        for path in writable:
            self.assertNotIn(path.lstrip("-"), ("/", "/run", "/run/bromigos-board", "/var", "/var/lib", "/var/lib/bromigos", "/etc", "/usr"))
        # no folder it may write has a last name the board's user could swap for a link:
        # /var/lib/bromigos-board is given whole (its parent is root's), never .../codes inside it
        self.assertNotIn(paths.CODES, writable)
        self.assertEqual(svc["ReadOnlyPaths"], ["/run"], "said outright: strict alone leaves /run writable on some systemd versions")
        self.assertNotIn("User", svc)
        # the folders it makes for the activity records must be readable by the API's user
        self.assertEqual(svc["UMask"], ["0022"])
        self.assertEqual(svc["ExecStart"], ["/usr/lib/bromigos/board/bromigos-board act"])
        self.assertEqual(svc["ExecStartPre"], ["+/usr/lib/bromigos/board/bromigos-board activity-folder"])
        api_writes = " ".join(unit("bromigos-board.service")["ReadWritePaths"]).split()
        self.assertEqual(set(api_writes), {paths.STATE, paths.WANTED, paths.DOOR, actions.REQUESTS})
        self.assertNotIn(actions.RESULTS, api_writes)


class TheDeleteCodeIsRoots(Base):
    """H4. A code approves deleting an app's data only when root made it: its record is in root's
    own folder, which the board's user can't write, as well as in the board's."""

    def delete(self, code, rid="00000000000000bb"):
        self.write(rid, verb="remove", app="passwords", delete_data=True, code=code)
        return self.act(rid)

    def test_a_code_the_boards_user_made_deletes_nothing(self):
        """The review's proof: a record written straight into the board's own codes folder."""
        made_up = "AAAAAAAA"
        p = self.path(paths.CODES) / (auth._sha(made_up) + ".json")
        p.write_text(json.dumps({"made_at": paths.now_ms(), "expires_at": paths.now_ms() + 600_000}))
        out = self.delete(made_up)
        self.assertEqual((out["ok"], out["code"]), (False, "needs-code"))
        self.assertEqual(self.ran, [])

    def test_roots_store_is_roots_only(self):
        t = tmpfiles()
        self.assertEqual(t[actions.ROOT_STATE], ("d", "0700", "root", "root"))
        self.assertEqual(t[actions.ROOT_CODES], ("d", "0700", "root", "root"))
        self.assertFalse(actions.ROOT_STATE.startswith(paths.STATE + "/"), "not inside the board's own folder")
        code, exp = self.new_code()
        name = auth._sha(auth.normalise_code(code)) + ".json"
        rec = self.path(actions.ROOT_CODES) / name
        self.assertEqual(stat.S_IMODE(rec.stat().st_mode), 0o600)
        self.assertEqual(json.loads(rec.read_text())["expires_at"], exp)
        self.assertNotIn(auth.normalise_code(code), rec.read_text() + name)       # kept as its hash, there too

    def test_a_code_root_made_deletes_once_and_both_records_go(self):
        code, _ = self.new_code()
        out = self.delete(code)
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.ran[0][-7:], ["bromigos", "lab", "apps", "remove", "passwords", "--delete-data", "--yes"])
        self.assertEqual((self.left(actions.ROOT_CODES), self.left(paths.CODES)), ([], []))
        self.assertEqual(self.delete(code, "00000000000000bc")["code"], "needs-code")
        self.assertFalse(auth.use_code(code), "and it can't sign a browser in afterwards")
        self.assertEqual(len(self.ran), 1)

    def test_a_code_that_signed_a_browser_in_deletes_nothing(self):
        code, _ = self.new_code()
        self.assertTrue(auth.use_code(code))
        self.assertEqual(self.delete(code)["code"], "needs-code")
        self.assertEqual(self.left(actions.ROOT_CODES), [], "and it is spent for good")
        # ... even if the board's user puts its own record back
        code, _ = self.new_code()
        name = auth._sha(auth.normalise_code(code)) + ".json"
        kept = (self.path(paths.CODES) / name).read_bytes()
        self.assertTrue(auth.use_code(code))
        (self.path(paths.CODES) / name).write_bytes(kept)
        self.assertTrue(self.delete(code, "00000000000000bd")["ok"])      # root can't tell: it never sees a sign-in
        self.assertFalse(self.delete(code, "00000000000000be")["ok"])     # but once, and only a code root made

    def test_a_late_code_and_a_roots_record_alone(self):
        os.environ["BROMIGOS_BOARD_NOW_MS"] = str(NOW)
        code, _ = self.new_code()
        os.environ["BROMIGOS_BOARD_NOW_MS"] = str(NOW + auth.CODE_MS)
        self.assertEqual(self.delete(code)["code"], "needs-code")
        os.environ["BROMIGOS_BOARD_NOW_MS"] = str(NOW)
        code, _ = self.new_code()
        for f in self.path(paths.CODES).iterdir():
            f.unlink()
        self.assertEqual(self.delete(code, "00000000000000bf")["code"], "needs-code")
        self.assertEqual(self.ran, [])

    def test_the_codes_folder_as_a_link_is_refused(self):
        code, _ = self.new_code()
        elsewhere = self.root / "elsewhere"
        self.path(paths.CODES).rename(elsewhere)
        os.symlink(elsewhere, self.path(paths.CODES))
        self.assertEqual(self.delete(code)["code"], "needs-code")
        self.assertEqual(len(os.listdir(elsewhere)), 1, "nothing was removed through the link")

    def test_through_the_api(self):
        self.sign_in()
        r = self.post({"verb": "remove", "app": "photos", "delete_data": True})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "needs-code"))
        r = self.post({"verb": "remove", "app": "photos", "delete_data": True, "code": "AAAA-AAAA"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "needs-code"))
        self.assertEqual((self.ran, len(self.waits)), ([], 1), "a wrong code here waits its turn like one at sign-in")
        code, _ = self.new_code()
        r = self.post({"verb": "remove", "app": "photos", "delete_data": True, "code": code})
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(r.json()["words"], "Removing Photos and deleting its data.")
        argv = self.ran[0]
        self.assertEqual(argv[-6:], ["lab", "apps", "remove", "photos", "--delete-data", "--yes"])
        self.assertEqual(argv[argv.index("--title") + 1], "Removing Photos and deleting its data")
        r = self.post({"verb": "remove", "app": "photos", "delete_data": True, "code": code})
        self.assertEqual(r.status_code, 403, "a code works once")
        self.assertEqual(len(self.ran), 1)
        for _ in range(3):
            self.post({"verb": "remove", "app": "photos", "delete_data": True, "code": "BBBB-BBBB"})
        code, _ = self.new_code()
        r = self.post({"verb": "remove", "app": "photos", "delete_data": True, "code": code})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (429, "too-many"), "five wrong from one address")

    def test_deleting_data_only_with_remove_and_only_when_allowed(self):
        self.sign_in()
        code, _ = self.new_code()
        for body in ({"verb": "restart", "app": "photos", "delete_data": True, "code": code},
                     {"verb": "remove", "app": "photos", "delete_data": "yes", "code": code}):
            self.assertEqual(self.post(body).status_code, 400, body)
        self.path("etc/bromigos/server.toml").write_text('[board]\nactions = ["restart", "add", "remove"]\n')
        r = self.post({"verb": "remove", "app": "photos", "delete_data": True, "code": code})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "not-allowed"))
        self.assertEqual(self.ran, [])
        self.assertIn(auth._sha(auth.normalise_code(code)) + ".json", self.left(actions.ROOT_CODES),
                      "a refused request leaves the code")

    def test_sudo_bromigos_server_board_code_notes_it_for_root_before_stepping_down(self):
        import collections
        import pwd
        did = []
        Pw = collections.namedtuple("Pw", "pw_uid pw_gid pw_dir")
        note = lambda name: (lambda *a, **k: did.append(name))            # noqa: E731
        with mock.patch.object(paths, "really_root", lambda: True), mock.patch.object(paths, "stand_in", lambda: False), \
                mock.patch.object(pwd, "getpwnam", lambda name: Pw(987, 986, "/var/lib/bromigos-board")), \
                mock.patch.object(os, "setgroups", note("setgroups")), mock.patch.object(os, "setgid", note("setgid")), \
                mock.patch.object(os, "setuid", note("setuid")), mock.patch.object(os, "umask", note("umask")), \
                mock.patch.dict(os.environ), mock.patch.object(actions, "note_code", note("roots note")), \
                mock.patch.object(cli, "own_folders", note("the board's folders")), \
                mock.patch.object(auth, "new_code", lambda now, code: did.append("the board's record") or ("AAAA-BBBB", 1)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["code", "--json"]), 0)
        self.assertEqual(did, ["roots note", "setgroups", "setgid", "setuid", "umask", "the board's folders", "the board's record"])

    def test_the_command_line_makes_both_records(self):
        r = subprocess.run([os.sys.executable, str(BOARD / "bin" / "bromigos-board"), "code", "--json"], capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        code = json.loads(r.stdout)["code"]
        self.assertEqual(self.left(actions.ROOT_CODES), self.left(paths.CODES))
        self.assertTrue(self.delete(code)["ok"])


class JobActions(Base):
    """A job's own actions from the page: answer, stop, start again (docs/board.md, "A job's own
    actions"). The records are real ones, written by the activity library in the stand-in root."""

    def setUp(self):
        super().setUp()
        import bromigos_activity
        self.A = bromigos_activity
        self.env = bromigos_activity.Env(dict(os.environ))
        self.jobs = []
        self.addCleanup(lambda: [j.close() for j in self.jobs])
        self.said = None                    # what the stand-in `bromigos activity` prints, and how it ends
        self.asks = self.job("drive.replace", "Replacing a drive: sdb", ["::ask swapped Swap the drive now. [swapped] I've swapped it [undo] Put sdb back"])
        self.runs = self.job("backup.run", "Backing up this server", ["::cancel safe", "::step copy running Copying"])
        self.busy = self.job("pool.grow", "Growing the pool", ["::cancel unsafe The pool is being rewritten."])
        self.failed = self.job("app.update", "Updating Photos", end={"exit_code": 1}, retry=self.A.retry_spec(["true"], "/"))
        self.done = self.job("backup.run", "Backing up this server", end={"exit_code": 0})
        self.once = self.job("app.update", "Updating Films and TV", end={"exit_code": 1})      # not safe to start again

    def job(self, kind, title, lines=(), end=None, **kw):
        j = self.A.Job(self.env, kind, title, command=["bromigos", *kind.split(".")], via="timer", **kw).open()
        j.begin()
        for line in lines:
            j.feed(line)
        if end is not None:
            j.finish(**end)
        j.save(force=True)
        self.jobs.append(j)
        return j.id

    def fake_run(self, argv):
        self.ran.append(argv)
        rc, out = self.said or (0, {"schema": 1, "ok": True, "refused": None, "words": "Answered: I've swapped it"})
        return subprocess.CompletedProcess(argv, rc, json.dumps(out), "")

    def do(self, job, verb, body=None, headers=PAGE):
        return self.c.post(f"/api/activity/{job}/{verb}", json=body or {}, headers=headers)

    def refused(self, r, status, code):
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (status, code), r.text)
        self.assertEqual(r.json()["error"]["words"], actions.REFUSALS[code])

    def test_an_answer_is_passed_on_with_the_id_and_the_choice_root_checked(self):
        self.sign_in()
        r = self.do(self.asks, "answer", {"question": "swapped", "choice": "swapped"})
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual({k: v for k, v in r.json().items() if k != "request"},
                         {"schema": 1, "ok": True, "job": self.asks, "words": "Answered."})
        self.assertEqual(self.ran, [["bromigos-activity", "answer", self.asks, "swapped", "--json"]])
        self.assertEqual(self.left(), [], "the request was taken out")

    def test_an_answer_only_to_the_question_that_is_asked_and_only_one_of_its_choices(self):
        self.sign_in()
        self.refused(self.do(self.asks, "answer", {"question": "another", "choice": "swapped"}), 409, "not-asking")   # replaced
        self.refused(self.do(self.asks, "answer", {"question": "swapped", "choice": "format"}), 409, "bad-choice")
        self.refused(self.do(self.runs, "answer", {"question": "swapped", "choice": "swapped"}), 409, "not-asking")
        self.refused(self.do(self.done, "answer", {"question": "swapped", "choice": "swapped"}), 409, "ended")
        for body in ({}, {"question": "swapped"}, {"question": "swapped", "choice": "x; reboot"},
                     {"question": ["swapped"], "choice": "swapped"}, {"question": "swapped", "choice": "--json"}):
            r = self.do(self.asks, "answer", body)
            self.assertEqual(r.status_code, 409, body)
            self.assertIn(r.json()["error"]["code"], ("not-asking", "bad-choice"), body)
        self.assertEqual(self.ran, [], "nothing was run for any of them")
        self.assertEqual(self.left(), [], "and what isn't an id never became a request")

    def test_stopping_a_job_that_says_it_is_safe(self):
        self.sign_in()
        self.said = (0, {"schema": 1, "ok": True, "refused": None, "words": "Stopped: Backing up this server"})
        r = self.do(self.runs, "cancel")
        self.assertEqual((r.status_code, r.json()["job"], r.json()["words"]), (202, self.runs, "Stopped."))
        self.assertEqual(self.ran, [["bromigos-activity", "cancel", self.runs, "--json"]])
        self.refused(self.do(self.busy, "cancel"), 409, "not-safe")
        self.refused(self.do(self.asks, "cancel"), 409, "not-safe")           # it never said stopping is safe
        self.refused(self.do(self.done, "cancel"), 409, "ended")
        self.assertEqual(len(self.ran), 1)
        self.refused(self.do(self.runs, "cancel", {"choice": "swapped"}), 400, "bad-request")     # an answer's words on a cancel

    def test_starting_again_a_job_that_ended_badly_and_may_be(self):
        self.sign_in()
        new = "20261110-1201-app.update-0c0c"
        self.said = (0, {"schema": 1, "id": new, "unit": "bromigos-job-x.service"})
        r = self.do(self.failed, "retry")
        self.assertEqual((r.status_code, r.json()["job"], r.json()["words"]), (202, new, "Started again."))
        self.assertEqual(self.ran, [["bromigos-activity", "retry", self.failed, "--via", "board", "--device", "A browser",
                                     "--detach", "--json"]])
        for job in (self.once, self.done, self.runs):
            self.refused(self.do(job, "retry"), 409, "cant-retry")
        self.assertEqual(len(self.ran), 1)

    def test_a_job_that_isnt_there_and_a_verb_that_isnt_one(self):
        self.sign_in()
        self.refused(self.do("20261110-1200-app.restart-photos-ffff", "cancel"), 404, "no-job")
        # a part of an id names a job at the terminal; here only the whole id does
        self.refused(self.do(self.runs[:-5], "cancel"), 404, "no-job")
        for bad in ("x", self.runs + "%0A", self.runs + "%20--json", self.runs.upper(), "--json", "%2E%2E"):
            self.refused(self.do(bad, "cancel"), 404, "no-job")
        # (with a / in it, it isn't this route at all)
        self.assertEqual(self.do("..%2F..%2Fetc%2Fpasswd", "cancel").status_code, 404)
        for verb in ("undo", "run", "show", "answer;reboot"):
            self.refused(self.do(self.runs, verb), 404, "unknown-verb")
        self.assertEqual((self.ran, self.left()), ([], []))

    def test_no_session_no_header_no_action(self):
        r = self.do(self.runs, "cancel")
        self.assertEqual(r.status_code, 401)
        self.sign_in()
        r = self.do(self.runs, "cancel", headers={"origin": ORIGIN})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "csrf"))
        r = self.c.post(f"/api/activity/{self.runs}/cancel", content="{}", headers=dict(PAGE, **{"content-type": "text/plain"}))
        self.assertEqual(r.status_code, 415)
        self.assertEqual(self.c.get(f"/api/activity/{self.runs}/cancel").status_code, 405)
        self.assertEqual((self.ran, self.left()), ([], []))

    def test_roots_board_table_decides_each(self):
        self.sign_in()
        self.path("etc/bromigos/server.toml").write_text('[board]\nactions = ["restart", "job.cancel"]\n')
        self.assertEqual(self.do(self.runs, "cancel").status_code, 202)
        self.refused(self.do(self.asks, "answer", {"question": "swapped", "choice": "swapped"}), 403, "not-allowed")
        self.refused(self.do(self.failed, "retry"), 403, "not-allowed")
        self.assertEqual(len(self.ran), 1)
        snapshot.write(snapshot.gather())
        self.assertEqual(self.c.get("/api/board").json()["actions"], ["restart", "job.cancel"])
        self.path("etc/bromigos/server.toml").unlink()
        snapshot.write(snapshot.gather())
        self.assertEqual(self.c.get("/api/board").json()["actions"],
                         ["restart", "add", "remove", "delete-data", "job.answer", "job.cancel", "job.retry"])

    def test_the_job_refuses_in_the_moment_between_roots_look_and_the_commands(self):
        self.sign_in()
        for said, code in (({"refused": "not-asking", "words": "That job isn't asking anything."}, "not-asking"),
                           ({"refused": "no-such-choice", "words": "'swapped' isn't one of its answers: x."}, "bad-choice"),
                           ({"refused": "ended", "words": "That job has ended (done)."}, "ended")):
            self.said = (3, dict({"schema": 1, "ok": False, "job": {"id": self.asks}}, **said))
            self.refused(self.do(self.asks, "answer", {"question": "swapped", "choice": "swapped"}), 409, code)
        self.said = (3, {"schema": 1, "ok": False, "refused": "unsafe", "words": "The pool is being rewritten."})
        r = self.do(self.runs, "cancel")
        self.refused(r, 409, "not-safe")
        self.assertNotIn("pool", r.text, "the answer's words are the board's own, fixed")
        self.said = (3, {"schema": 1, "ok": False, "refused": "not-retryable", "words": "It is still going."})
        self.refused(self.do(self.failed, "retry"), 409, "cant-retry")
        # the command itself failed (the job didn't take the answer in time): said, and logged for root
        self.said = (1, "")
        self.refused(self.do(self.asks, "answer", {"question": "swapped", "choice": "swapped"}), 409, "not-taken")
        self.assertTrue(any("the job's command failed" in line for line in self.logged))

    def test_root_checks_again_whatever_the_boards_user_wrote(self):
        """A request written straight into the folder, past the API: root's helper is the check."""
        now = paths.now_ms()
        for n, (doc, code) in enumerate((
            ({"verb": "job.cancel", "job": self.runs[:-5]}, "no-job"),
            ({"verb": "job.cancel", "job": "../../etc/passwd"}, "no-job"),
            ({"verb": "job.cancel", "job": self.runs, "at": now - 120_000}, "too-old"),
            ({"verb": "job.cancel", "job": self.busy}, "not-safe"),
            ({"verb": "job.answer", "job": self.asks, "question": "swapped", "choice": "--json"}, "bad-choice"),
            ({"verb": "job.answer", "job": self.asks, "question": "swapped", "choice": "format"}, "bad-choice"),
            ({"verb": "job.retry", "job": self.once}, "cant-retry"),
            ({"verb": "job.run", "job": self.runs}, "unknown-verb"),
            ({"verb": "job.cancel", "job": self.runs, "choice": "x"}, "bad-request"),
        )):
            rid = f"{n:016x}"
            self.write(rid, **dict({"at": now}, **doc))
            out = self.act(rid)
            self.assertEqual((out["ok"], out["code"], out["words"]), (False, code, actions.REFUSALS[code]), doc)
        self.assertEqual(self.ran, [])

    def test_no_answer_quotes_the_request_or_the_job(self):
        self.sign_in()
        self.said = (3, {"schema": 1, "ok": False, "refused": "unsafe", "words": "SECRET-IN-A-NOTE"})
        self.do(self.runs, "cancel")
        self.do(self.asks, "answer", {"question": "swapped", "choice": "zzz-from-the-request"})
        for name in self.left(actions.RESULTS):
            text = self.path(f"{actions.RESULTS}/{name}").read_text()
            self.assertNotIn("SECRET-IN-A-NOTE", text)
            self.assertNotIn("zzz-from-the-request", text)

    def test_when_the_helper_is_slow_the_page_is_told_to_watch_the_card(self):
        self.sign_in()
        self.app.app.state.after_ask = None
        self.app.app.state.action_wait_s = 0.2
        r = self.do(self.runs, "cancel")
        self.assertEqual((r.status_code, r.json()["job"]), (202, self.runs))
        self.assertIn("card", r.json()["words"])
        self.assertEqual(len(self.left()), 1, "the request waits for the helper")

    def test_against_the_real_command(self):
        """`bromigos activity` itself, on the stand-in root: what it prints is what the helper reads."""
        real = [sys.executable, str(REPO / "bin" / "bromigos-activity")]

        def run(argv):
            self.ran.append(argv)
            return subprocess.run(real + argv[1:], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        now = paths.now_ms()
        # a job that ended while the request waited: the command's own refusal comes back as the board's
        self.write("00000000000000a1", verb="job.cancel", job=self.runs, at=now)
        self.jobs[1].finish(exit_code=0)
        self.jobs[1].save(force=True)
        out = actions.act("00000000000000a1", run=run, log=self.logged.append)
        self.assertEqual((out["ok"], out["code"]), (False, "ended"))
        # and one it won't start again says so itself too (root's look is the first check, the command's the second)
        with mock.patch.object(actions, "RETRY_FROM", ("failed", "succeeded")):
            self.write("00000000000000a2", verb="job.retry", job=self.done, at=now)
            out = actions.act("00000000000000a2", run=run, log=self.logged.append)
        self.assertEqual((out["ok"], out["code"]), (False, "cant-retry"))


class HelperTests(Base):
    """bromigos-board act, as root runs it: what it refuses on its own."""

    def test_it_runs_once(self):
        self.write("0123456789abcdef")
        self.assertTrue(self.act("0123456789abcdef")["ok"])
        self.assertEqual(self.act("0123456789abcdef")["code"], "no-request")
        self.assertEqual(len(self.ran), 1)

    def test_refusals(self):
        cases = [
            ({"verb": "logs"}, "unknown-verb"),
            ({"verb": "remove --delete-data"}, "unknown-verb"),
            ({"app": "photos;id"}, "unknown-app"),
            ({"app": "photos\n"}, "unknown-app"),
            ({"app": "not-an-app"}, "unknown-app"),
            ({"at": paths.now_ms() - 120_000}, "too-old"),
            ({"at": paths.now_ms() + 120_000}, "too-old"),
            ({"at": "now"}, "too-old"),
            ({"at": True}, "too-old"),
            ({"id": "fedcba9876543210"}, "bad-request"),
        ]
        for i, (doc, code) in enumerate(cases):
            rid = f"{i:016x}"
            self.write(rid, **doc)
            out = self.act(rid)
            self.assertEqual((out["ok"], out["code"]), (False, code), doc)
            self.assertFalse(self.path(f"{actions.REQUESTS}/{rid}.json").exists())
            self.assertEqual(self.answer(rid)["code"], code)
        self.assertEqual(self.ran, [])

    def test_ids_links_fifos_and_junk(self):
        for rid in ("../../etc/passwd", "0123456789ABCDEF", "x", "", "0123456789abcdef\n"):
            self.assertEqual(self.act(rid)["code"], "bad-request", rid)
        self.assertEqual(self.left(actions.RESULTS), [], "an id that isn't one names no answer either")
        req = self.path(actions.REQUESTS)
        target = self.root / "elsewhere.json"
        target.write_text(json.dumps({"id": "00000000000000aa", "verb": "restart", "app": "photos", "at": paths.now_ms()}))
        os.symlink(target, req / "00000000000000aa.json")
        self.assertEqual(self.act("00000000000000aa")["code"], "bad-request")
        self.assertTrue(target.exists(), "the link went, not what it pointed at")
        (req / "00000000000000bb.json").write_text("not json")
        self.assertEqual(self.act("00000000000000bb")["code"], "bad-request")
        (req / "00000000000000cc.json").write_text("x" * 5000)
        self.assertEqual(self.act("00000000000000cc")["code"], "bad-request")
        os.mkfifo(req / "00000000000000dd.json")              # root's helper must not wait on it
        done = []
        t = threading.Thread(target=lambda: done.append(self.act("00000000000000dd")["code"]), daemon=True)
        t.start()
        t.join(5)
        self.assertEqual(done, ["bad-request"], "the helper hung on a FIFO")
        (req / "00000000000000ee.json").mkdir()
        self.assertEqual(self.act("00000000000000ee")["code"], "bad-request")
        self.assertEqual(self.ran, [])

    def test_only_a_request_the_boards_user_wrote(self):
        """Not root's, not anyone else's: the owner is checked on the open file (and checked here
        too, in the tests' stand-in root, where this user plays the board's)."""
        self.write("0123456789abcdef")
        with mock.patch.object(actions, "board_ids", lambda: (os.getuid() + 1, None)):
            self.assertEqual(self.act("0123456789abcdef")["code"], "bad-request")
        self.write("0123456789abcdee")
        with mock.patch.object(actions, "board_ids", lambda: (None, None)):        # a server with no such user
            self.assertEqual(self.act("0123456789abcdee")["code"], "bad-request")
        self.assertEqual(self.ran, [])
        self.assertEqual(self.left(), [], "and they are removed all the same")
        # on a server the board's user is looked up by name, and root's own files don't count as its
        with mock.patch.object(paths, "stand_in", lambda: False):
            import pwd
            with mock.patch.object(pwd, "getpwnam", side_effect=KeyError("bromigos-board")):
                self.assertEqual(actions.board_ids(), (None, None))

    def test_the_browser_name_is_only_letters(self):
        self.write("0123456789abcdef", browser="Firefox; $(id) `x` --detach\n")
        self.act("0123456789abcdef")
        device = self.ran[0][self.ran[0].index("--device") + 1]
        self.assertEqual(device, "Firefox id x --detach")
        self.assertEqual(self.ran[0][-6:], ["--", "bromigos", "lab", "apps", "restart", "photos"])

    def test_a_job_that_wont_start(self):
        self.write("0123456789abcdef")
        out = actions.act("0123456789abcdef", log=self.logged.append,
                          run=lambda a: subprocess.CompletedProcess(a, 1, "", "activity: no root\n"))
        self.assertEqual((out["ok"], out["code"]), (False, "job-failed"))

        def boom(argv):
            raise FileNotFoundError(argv[0])
        self.write("0123456789abcdee")
        self.assertEqual(actions.act("0123456789abcdee", run=boom, log=self.logged.append)["code"], "job-failed")


class DrainTests(Base):
    """The helper's unit is started by the folder not being empty, and takes every request out of
    it: each handled once, none lost, whatever else is in the folder removed."""

    def drain(self, **k):
        k.setdefault("linger", 0.3)
        k.setdefault("poll", 0.02)
        return actions.drain(run=self.fake_run, log=self.logged.append, **k)

    def test_a_burst_is_each_handled_once(self):
        ids = [f"{i:016x}" for i in range(40)]
        for rid in ids:
            self.write(rid)
        self.assertEqual(self.drain(), 40)
        self.assertEqual(len(self.ran), 40)
        self.assertEqual(self.left(), [])
        self.assertEqual(self.left(actions.RESULTS), sorted(f"{rid}.json" for rid in ids))
        self.assertTrue(all(self.answer(rid)["ok"] for rid in ids))
        self.assertEqual(self.drain(), 0)
        self.assertEqual(len(self.ran), 40)

    def test_requests_that_arrive_while_it_runs_are_handled_too(self):
        """Written as the API writes them, from another thread, while the helper works and while
        it waits for more: not one is lost, not one is done twice."""
        asked = []

        def api_side():
            for i in range(30):
                asked.append(actions.ask("restart", "photos", {"id": "s", "browser": "b"}))
                time.sleep(0.01 if i % 7 else 0.15)

        def slow_run(argv):
            time.sleep(0.01)
            return self.fake_run(argv)
        t = threading.Thread(target=api_side)
        t.start()
        handled = actions.drain(run=slow_run, log=self.logged.append, linger=0.6, poll=0.02)
        t.join()
        handled += self.drain()                 # (what the path unit does when a request is there as the helper ends)
        self.assertEqual(handled, 30)
        self.assertEqual(sorted(self.left(actions.RESULTS)), sorted(f"{rid}.json" for rid in asked))
        self.assertEqual(len(self.ran), 30)
        self.assertEqual(self.left(), [])

    def test_a_request_being_written_is_left_alone_and_one_left_half_written_is_swept(self):
        req = self.path(actions.REQUESTS)
        (req / ".0123456789abcdef.json.aaaaaaaaaaaaaaaa.tmp").write_text("{")
        self.assertEqual(self.drain(), 0)
        self.assertEqual(self.left(), [".0123456789abcdef.json.aaaaaaaaaaaaaaaa.tmp"])
        old = time.time() - 120
        os.utime(req / ".0123456789abcdef.json.aaaaaaaaaaaaaaaa.tmp", (old, old))
        self.assertEqual(self.drain(), 0)
        self.assertEqual(self.left(), [])

    def test_whatever_else_is_in_the_folder_is_removed_never_followed(self):
        req = self.path(actions.REQUESTS)
        victim = self.root / "etc" / "victim"
        victim.mkdir()
        (victim / "keep").write_text("x")
        os.symlink(victim, req / "a-link")
        os.symlink(victim, req / "00000000000000aa.result.json")
        (req / "notes.txt").write_text("x")
        (req / "a-folder").mkdir()
        (req / "a-folder" / "inside").write_text("x")
        os.symlink(victim, req / "a-folder" / "link")
        os.mkfifo(req / "a-fifo")
        self.write("0123456789abcdef")
        self.assertEqual(self.drain(), 1)
        self.assertEqual(self.left(), [])
        self.assertEqual(os.listdir(victim), ["keep"])

    def test_a_folder_named_like_a_request_is_refused_once_and_removed(self):
        """A folder (with a file and a link inside) where a request goes: refused like any request
        that isn't a plain file, then removed, so the helper goes quiet instead of reading it again
        at every look until it is stopped."""
        req = self.path(actions.REQUESTS)
        bad = req / "00000000000000dd.json"
        bad.mkdir()
        (bad / "inside").write_text("x")
        outside = self.path("var/lib/bromigos-board/keep")
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("kept")
        (bad / "link").symlink_to(outside)
        t = [0.0]

        def clock():
            t[0] += 0.001
            return t[0]
        n = actions.drain(run=self.fake_run, cat={}, linger=3.0, sleep=lambda s: None, clock=clock, log=self.logged.append,
                          run_max=5.0)
        self.assertEqual(n, 1, "read once")
        self.assertFalse(os.path.lexists(bad), "and removed")
        self.assertEqual(self.answer("00000000000000dd")["code"], "bad-request")
        self.assertEqual(outside.read_text(), "kept", "a link inside it is never followed")
        self.assertEqual(self.ran, [])

    def test_old_answers_are_swept(self):
        self.write("0123456789abcdef")
        self.drain()
        a = self.path(f"{actions.RESULTS}/0123456789abcdef.json")
        self.assertTrue(a.exists())
        old = time.time() - 120
        os.utime(a, (old, old))
        self.drain()
        self.assertEqual(self.left(actions.RESULTS), [])

    def test_it_ends_after_a_while_whatever_keeps_arriving(self):
        clock = iter(range(0, 10_000, 100))            # each look at the clock is 100 s on
        for i in range(5):
            self.write(f"{i:016x}")
        handled = actions.drain(run=self.fake_run, log=self.logged.append, clock=lambda: next(clock), run_max=300, linger=1)
        self.assertLess(handled, 5)
        self.assertGreater(len(self.left()), 0, "what's left starts the helper again")

    def test_the_path_unit_starts_the_helper_when_the_folder_isnt_empty(self):
        p = unit("bromigos-board-act.path")
        self.assertEqual(p["DirectoryNotEmpty"], [actions.REQUESTS])
        self.assertEqual(p["Unit"], ["bromigos-board-act.service"])
        self.assertEqual(p["WantedBy"], ["paths.target"])
        from bromigos_homelab import localprovision as L
        self.assertIn("bromigos-board-act.path", L.STEP_UNITS["board"])
        # it lingers three seconds a run: never five starts in ten seconds (systemd's start limit)
        self.assertGreaterEqual(actions.LINGER_S, 3.0)


class TheHelperNeverFailsItsUnit(Base):
    """M2. A refused request is an answer, not a failure: the helper ends 0, and nothing of a run
    stays listed (the Server's update check rolls an update back on any failed unit)."""

    def main(self, *argv):
        with contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()):
            return cli.main(list(argv)), err.getvalue()

    def test_a_refusal_ends_zero(self):
        self.write("00000000000000aa", verb="nonsense")
        self.assertEqual(self.main("act", "00000000000000aa")[0], 0)
        self.assertEqual(self.answer("00000000000000aa")["code"], "unknown-verb")
        self.assertEqual(self.main("act", "00000000000000ab")[0], 0)                  # a request that doesn't exist
        self.assertEqual(self.main("act", "not-an-id")[0], 0)
        self.write("00000000000000ac", verb="remove", delete_data=True, code="AAAA-AAAA")
        self.assertEqual(self.main("act", "00000000000000ac")[0], 0)                  # a wrong code for a deletion
        self.assertEqual(self.answer("00000000000000ac")["code"], "needs-code")

    def test_the_folder_run_ends_zero_whatever_is_in_it(self):
        self.write("00000000000000aa", verb="nonsense")
        (self.path(actions.REQUESTS) / "junk").write_text("x")
        with mock.patch.object(actions, "LINGER_S", 0.1):
            self.assertEqual(self.main("act")[0], 0)
        self.assertEqual(self.left(), [])

    def test_even_when_the_helper_itself_breaks(self):
        with mock.patch.object(actions, "drain", side_effect=RuntimeError("no")):
            rc, err = self.main("act")
        self.assertEqual(rc, 0)
        self.assertIn("stopped early", err)

    def test_the_unit_collects_itself(self):
        svc = unit("bromigos-board-act.service")
        text = (UNITS / "bromigos-board-act.service").read_text()
        # (a [Unit] setting: in [Service] systemd ignores it, which its own check of the units' text catches)
        self.assertIn("\nCollectMode=inactive-or-failed\n", text.split("[Service]")[0])
        self.assertEqual(svc["Type"], ["oneshot"])
        self.assertNotIn("RemainAfterExit", svc)
        self.assertNotIn("SuccessExitStatus", svc, "it needs none: the command ends 0")


if __name__ == "__main__":
    unittest.main()
