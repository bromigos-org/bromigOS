"""A fleet's tasks on the board (docs/board.md, "A fleet's tasks"): GET /api/fleet, the tasks on
the activity stream, and Home's "what needs you". The follower is the real one
(bromigos_labjobs.Follower) reading a feed file with placeholder names (homelab/tests/fixtures/
fleet-mirror.json: a status mirror's recorded answer). The API never reads a feed itself: it has
the follower's files, and no network."""
import json
import os
import re
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

from common import REPO, mock_env

sys.path.insert(0, str(REPO / "tests" / "activity"))

from test_api import Base, marked  # noqa: E402

import bromigos_activity as A  # noqa: E402
import bromigos_labjobs as L  # noqa: E402
from bromigos_board import api, board, paths  # noqa: E402
from bromigos_homelab import fleet as F  # noqa: E402

MIRROR = json.loads((REPO / "homelab/tests/fixtures/fleet-mirror.json").read_text())
NOW = int(datetime(2026, 11, 28, 11, 52, tzinfo=timezone.utc).timestamp() * 1000)     # 12 minutes after the feed was written
UNSAFE = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u00ad\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u206f\\ufeff\\ud800-\\udfff]")


class Fleet(Base):
    def setUp(self):
        super().setUp()
        clock = mock_env({"BROMIGOS_ACTIVITY_NOW_MS": str(NOW), "BROMIGOS_BOARD_NOW_MS": str(NOW)})
        clock.start()
        self.addCleanup(clock.stop)
        os.environ.pop("BROMIGOS_COMFYUI_URL", None)
        folder = self.root / "srv/fleet"
        folder.mkdir(parents=True)
        self.feed = folder / "feed.json"
        self.feed.write_text(json.dumps(MIRROR))
        self.config = self.root / "etc/bromigos/labjobs.toml"
        self.config.write_text(f'[[fleet]]\nname = "tasks"\nfile = "{self.feed}"\n')

    def at(self, ms):
        os.environ["BROMIGOS_ACTIVITY_NOW_MS"] = os.environ["BROMIGOS_BOARD_NOW_MS"] = str(ms)

    def follow(self):
        """One look of the lab follower, as bromigos-board-lab.service runs it."""
        L.Follower(L.Where(A.Env(), system=True), websocket=False, log=lambda w: None).pass_once()

    def fleet(self):
        r = self.c.get("/api/fleet")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def jobs(self):
        with self.c.stream("GET", "/api/activity") as r:
            self.assertEqual(r.status_code, 200)
            text = "".join(r.iter_text())
        block = next(b for b in text.split("\n\n") if b.startswith("event: snapshot"))
        return json.loads(block.split("data: ", 1)[1])["jobs"]

    def test_signed_out_no_fleet(self):
        self.follow()
        r = self.c.get("/api/fleet")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "signed-out"))
        self.assertFalse(marked(self.path(paths.WANTED)), "a browser that isn't signed in starts nothing")

    def test_the_fleets_document_is_the_one_the_command_prints(self):
        self.follow()
        self.sign_in()
        r = self.c.get("/api/fleet")
        self.assertEqual((r.status_code, r.headers["cache-control"]), (200, "no-store"))
        doc = r.json()
        self.assertEqual(set(doc), {"schema", "generatedAt", "configured", "state", "fleets", "errors", "sources", "following"})
        self.assertEqual({k: doc[k] for k in ("schema", "generatedAt", "configured", "state", "errors", "following")},
                         {"schema": 1, "generatedAt": NOW // 1000, "configured": True, "state": "warn", "errors": {},
                          "following": True})
        self.assertEqual(doc["sources"], [{"name": "tasks", "state": "ok", "words": "", "checked_at": NOW, "read_at": NOW}])
        (one,) = doc["fleets"]
        # the same picture `bromigos lab tasks --json` prints of this feed, and where it came from
        when = datetime.fromtimestamp(NOW / 1000, timezone.utc)
        view = F.view(MIRROR["feeds"][0]["feed"], when)
        self.assertEqual({k: v for k, v in one.items() if k not in ("source", "mirror", "received_at")}, view)
        self.assertEqual((one["source"], one["mirror"], one["received_at"]), ("tasks", "example", "2026-11-28T11:40:09Z"))
        self.assertEqual(set(doc) - {"sources", "following"}, set(F.assemble([], {}, True, when)))
        self.assertEqual((one["business"], one["state"], one["fresh"], one["headline"]),
                         ("Example", "fresh", True, "3 need you · 2 proposed · 3 working · 1 waiting · 4 merged today"))
        self.assertEqual([(lane["id"], lane["title"], lane["count"]) for lane in one["lanes"]],
                         [("needs_you", "Needs you", 3), ("proposed", "Proposed", 2), ("working", "Working", 3),
                          ("waiting", "Waiting", 1), ("done", "Done", 5)])
        self.assertEqual(one["lanes"][0]["rows"][0]["phrase"], "Stuck · 3 fix rounds and a clean restart did not make it green")
        self.assertEqual([a["phrase"] for a in one["accounts"]], ["Available", "Resting until 15:45"])
        self.assertEqual(one["schedules"][0]["last_words"], "filed a digest and 1 ticket")
        self.assertTrue(marked(self.path(paths.WANTED)), "asking starts the follower, as the activity stream does")

    def test_no_fleet_in_the_settings(self):
        self.config.write_text('[[comfyui]]\nname = "studio"\nurl = "http://127.0.0.1:8188"\n')
        self.sign_in()
        doc = self.fleet()
        self.assertEqual({k: doc[k] for k in ("configured", "state", "fleets", "errors", "sources", "following")},
                         {"configured": False, "state": "empty", "fleets": [], "errors": {}, "sources": [], "following": False})

    def test_before_the_followers_first_look_it_says_a_fleet_is_set(self):
        self.sign_in()
        doc = self.fleet()
        self.assertEqual((doc["configured"], doc["state"], doc["fleets"], doc["following"]), (True, "unreachable", [], False))

    def test_a_stale_report_says_so_and_stays(self):
        self.follow()
        self.at(NOW + 3 * 3_600_000)
        self.follow()
        self.sign_in()
        doc = self.fleet()
        self.assertEqual((doc["state"], doc["fleets"][0]["state"], doc["fleets"][0]["fresh"], doc["fleets"][0]["headline"]),
                         ("warn", "stale", False, "No update for 3 h 11 min"))
        self.assertEqual(len(doc["fleets"][0]["lanes"][0]["rows"]), 3, "the last picture is still there to read")
        jobs = {j["id"]: j for j in self.jobs()}
        self.assertEqual(jobs["task.example.app.41"]["state"], "needs-you")
        self.assertEqual((jobs["task.example.app.57"]["state"], jobs["task.example.app.57"]["error"]["words"]),
                         ("interrupted", "The fleet hasn't reported since 12:40 (3 h 11 min ago). It was: Writing."))

    def test_a_source_that_went_away_keeps_its_last_report(self):
        self.follow()
        self.feed.unlink()
        self.at(NOW + 60_000)
        self.follow()
        self.sign_in()
        doc = self.fleet()
        self.assertEqual((doc["state"], len(doc["fleets"]), doc["sources"][0]["state"], doc["sources"][0]["read_at"]),
                         ("warn", 1, "down", NOW))
        self.assertIn("the feed file can't be read", doc["errors"]["tasks"])
        self.assertTrue(doc["errors"]["tasks"].endswith(": this is the last report it gave"))

    def test_the_stream_carries_the_tasks(self):
        self.follow()
        self.sign_in()
        jobs = [j for j in self.jobs() if j["kind"] == "agent.task"]
        self.assertEqual({j["id"]: j["state"] for j in jobs}, {
            "task.example.app.41": "needs-you", "task.example.site.9": "needs-you", "task.example.app.60": "needs-you",
            "task.example.app.57": "running", "task.example.app.49": "running", "task.example.site.14": "running",
            "task.example.site.12": "queued", "task.example.app.52": "succeeded", "task.example.site.11": "succeeded",
            "task.example.app.50": "succeeded", "task.example.app.47": "succeeded"})
        one = next(j for j in jobs if j["id"] == "task.example.app.49")
        self.assertEqual((one["title"], one["stage"], one["requested_by"], one["question"], one["can"]),
                         ("app#49 Search: an empty query returns a server error", "Fixing · round 2",
                          {"via": "lab", "device": None, "agent": "example"}, None, []))
        self.assertNotIn("lab", one, "the page draws it as a job of its own")
        self.assertNotIn(str(self.root), json.dumps(jobs), "no path of this server's")
        # an old jobs.json shows no task, as it shows no other lab job
        self.at(NOW + L.STATE_FRESH_MS + 1)
        self.assertEqual([j for j in self.jobs() if j["kind"] == "agent.task"], [])

    def test_home_counts_the_tasks_that_need_you(self):
        self.snapshot()
        self.sign_in()
        b = self.c.get("/api/board").json()
        self.assertEqual((len(b["needs_you"]), b["status"]["words"]), (1, "1 thing needs you."), "the server's own alert")
        self.follow()
        b = self.c.get("/api/board").json()
        self.assertEqual(b["status"], dict(b["status"], state="needs-you", words="4 things need you."))
        tasks = [n for n in b["needs_you"] if n["job"]]
        self.assertEqual(tasks, [
            {"id": "task.example.app.60", "machine": "Example", "subject": {"type": "task", "id": "app#60", "name": "app#60"},
             "severity": "warn", "words": "app#60 Speed up the nightly export",
             "detail": "Not started · re-apply agent-ready yourself", "since": NOW, "go": "activity",
             "job": "task.example.app.60"},
            {"id": "task.example.app.41", "machine": "Example", "subject": {"type": "task", "id": "app#41", "name": "app#41"},
             "severity": "warn", "words": "app#41 Checkout: totals are wrong when a coupon is applied",
             "detail": "Stuck · 3 fix rounds and a clean restart did not make it green",
             "since": int(datetime(2026, 11, 28, 8, 12, 44, tzinfo=timezone.utc).timestamp() * 1000), "go": "activity",
             "job": "task.example.app.41"},
            {"id": "task.example.site.9", "machine": "Example", "subject": {"type": "task", "id": "site#9", "name": "site#9"},
             "severity": "warn", "words": "site#9 Rotate the newsletter provider's key",
             "detail": "Blocked · the task needs a production credential the agents do not hold",
             "since": int(datetime(2026, 11, 27, 16, 3, 0, tzinfo=timezone.utc).timestamp() * 1000), "go": "activity",
             "job": "task.example.site.9"}])
        # the same keys as every other row: the page reads them with no change
        self.assertEqual({frozenset(n) for n in b["needs_you"]}, {frozenset(b["needs_you"][0])})
        self.assertEqual(set(b), {"schema", "at", "max_age_s", "age_s", "stale", "lab", "server", "status", "machines",
                                  "needs_you", "fixed", "apps", "storage", "backups", "updates", "ups", "actions",
                                  "host", "settings", "sources", "system", "activity", "alerts"}, "no new part of the board")

    def test_a_task_is_on_no_machine(self):
        """A fleet's task counts in the status line and in what needs you, and not against this
        server's own row: nothing on the server needs a person."""
        self.follow()
        tasks = api.tasks_needing_you()
        self.assertEqual(len(tasks), 3)
        snap = {"host": "myserver", "at": NOW, "alerts": {"alerts": []}, "activity": {"jobs": []}, "apps": [{"id": "photos", "state": "ok"}],
                "storage": {}, "backups": {"health": {"state": "ok"}}, "system": {}}
        quiet = board.shape(snap, NOW)
        self.assertEqual((quiet["status"]["state"], quiet["needs_you"], quiet["machines"][0]["state"]), ("ok", [], "ok"))
        b = board.shape(snap, NOW, tasks=tasks)
        self.assertEqual((b["status"]["state"], b["status"]["words"], len(b["needs_you"])), ("needs-you", "3 things need you.", 3))
        self.assertEqual((b["machines"][0]["state"], b["machines"][0]["state_word"]), ("ok", "online"))
        self.assertEqual({n["machine"] for n in b["needs_you"]}, {"Example"})
        # anything that isn't such a record is passed over
        odd = board.shape(snap, NOW, tasks=[None, "x", {"state": "needs-you"}, {"id": "task.a.b.1", "state": "running"}, {"id": 7}])
        self.assertEqual(odd["needs_you"], [])

    def test_no_follower_no_tasks_on_home(self):
        self.snapshot()
        self.sign_in()
        self.follow()
        self.at(NOW + L.STATE_FRESH_MS + 1)
        self.snapshot()
        b = self.c.get("/api/board").json()
        self.assertEqual([n["id"] for n in b["needs_you"]], ["update.restart"], "an old jobs.json counts for nothing")

    def test_hostile_titles_reach_the_page_as_plain_text_and_nothing_else(self):
        evil = "\x1b]52;c;aGVsbG8=\x07\x1b[2J\u202e"
        doc = json.loads(json.dumps(MIRROR))
        feed = doc["feeds"][0]["feed"]
        feed["needs_person"][0].update(title=f"<img src=x onerror=alert(1)>{evil}\n[bold]x[/] " + "A" * 4000,
                                       why=f"because{evil}\n" + "w" * 900, phrase=f"Stuck · because{evil}\n" + "w" * 900,
                                       issue_url="javascript:alert(1)", url="data:text/html,x", pr_url=f"https://x.example/{evil}")
        feed["business"] = f"Ex{evil}ample"
        feed["warnings"] = [f"a warning{evil}\nline two"]
        feed["headline"] = f"3 need you{evil}\n<b>now</b>"
        self.feed.write_text(json.dumps(doc))
        self.follow()
        self.snapshot()
        self.sign_in()
        fleet, jobs, home = self.fleet(), self.jobs(), self.c.get("/api/board").json()
        for name, got in (("the fleet", fleet), ("the stream", jobs), ("the board", home["needs_you"])):
            text = json.dumps(got, ensure_ascii=False)
            self.assertIsNone(UNSAFE.search(text), name)
        row = fleet["fleets"][0]["lanes"][0]["rows"][0]
        self.assertEqual((row["title"][:44], len(row["title"])), ("<img src=x onerror=alert(1)> [bold]x[/] AAAA", 160))
        self.assertEqual((row["url"], row["links"]), ("", []), "an address that isn't a plain http(s) one is left out")
        self.assertEqual((fleet["fleets"][0]["business"], fleet["fleets"][0]["headline"], fleet["fleets"][0]["warnings"][0]),
                         ("Example", "3 need you <b>now</b>", "a warning line two"))
        job = next(j for j in jobs if j["id"] == "task.example.app.41")
        self.assertEqual(job["title"][:51], "app#41 <img src=x onerror=alert(1)> [bold]x[/] AAAA")
        self.assertLessEqual(len(job["title"]), A.MAX_TITLE)
        self.assertEqual([n["words"] for n in job["notes"]], [], "and no address is said along the way")
        need = next(n for n in home["needs_you"] if n["job"] == "task.example.app.41")
        self.assertEqual((need["machine"], need["detail"][:22]), ("Example", "Stuck · because wwwwww"))

    def test_a_server_whose_other_packages_are_older_says_so(self):
        """bromigos-board, bromigos-core and bromigos-lab are three packages: a board that is
        newer than the library that reads a fleet answers with nothing, in plain words."""
        self.follow()
        self.snapshot()
        self.sign_in()
        old = type("Older", (), {"Where": L.Where, "read_state": staticmethod(L.read_state), "jobs": staticmethod(L.jobs)})
        with mock.patch.object(api, "_labjobs", lambda: old):
            doc = self.fleet()
            home = self.c.get("/api/board").json()
        self.assertEqual((doc["configured"], doc["state"], doc["fleets"]), (False, "empty", []))
        self.assertEqual(doc["errors"], {"board": "This server's bromigos-core is older than its Lab board: update it to see "
                                                  "a fleet's tasks."})
        self.assertEqual([n["id"] for n in home["needs_you"]], ["update.restart"])
        with mock.patch.object(L, "_fleet", lambda: None):        # and without the lab console's reader
            doc = self.fleet()
        self.assertEqual((doc["state"], doc["fleets"], doc["errors"]), ("unreachable", [], {"board": L.NO_FLEET}))

        def broken():
            raise RuntimeError("no such module")
        with mock.patch.object(api, "_labjobs", broken):
            doc = self.fleet()
            self.assertEqual(api.tasks_needing_you(), [])
        self.assertEqual((doc["state"], doc["errors"]), ("empty", {"board": "The fleet's report couldn't be read (RuntimeError)."}))


if __name__ == "__main__":
    unittest.main()
