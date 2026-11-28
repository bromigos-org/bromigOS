"""A fleet's tasks as lab jobs (lib/bromigos_labjobs.py, docs/activity.md "A fleet's tasks"): the
follower reading a status mirror ([[fleet]] url) and a feed file ([[fleet]] file), what it keeps
in fleet.json, the activity records of kind agent.task it makes of the feed, staleness, and
`bromigos activity` list/show/cancel on them. The mirror is a stand-in on this machine, answering
a recorded feed with placeholder names (homelab/tests/fixtures/fleet-mirror.json): no network, no
GitHub."""
import http.server
import json
import os
import re
import sys
import threading
import unittest
import unittest.mock
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake import FakeMachine, REPO  # noqa: E402

sys.path.insert(0, str(REPO / "homelab" / "lib"))        # the feed's reader: the lab console's (bromigos-lab)

import bromigos_activity as A  # noqa: E402
import bromigos_labjobs as L  # noqa: E402
from bromigos_homelab import fleet as F  # noqa: E402
from test_activity import RECORD_KEYS, STEP_KEYS  # noqa: E402

MIRROR = json.loads((REPO / "homelab/tests/fixtures/fleet-mirror.json").read_text())
NOW = int(datetime(2026, 11, 28, 11, 52, tzinfo=timezone.utc).timestamp() * 1000)     # 12 minutes after the feed was written
MIN, HOUR = 60_000, 3_600_000
# what must never reach a record from text other people wrote
UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ud800-\udfff]")


def answer(**changes):
    """The mirror's recorded answer, with its one feed changed."""
    doc = json.loads(json.dumps(MIRROR))
    doc["feeds"][0]["feed"].update(changes)
    return doc


def second():
    """A second business beside the first: nothing needs it, one task is being written."""
    doc = json.loads(json.dumps(MIRROR))
    feed = json.loads(json.dumps(doc["feeds"][0]["feed"]))
    feed.update(business="Second", needs_person=[], waiting=[], proposed=[], recent=[], working=feed["working"][:1],
                headline="Nothing needs you · 1 working · 0 waiting · 0 merged today", lanes=[])
    doc["feeds"].append({"business": "second", "received_at": "2026-11-28T11:41:00Z", "feed": feed})
    return doc


class Mirror:
    """A stand-in for a lab's status mirror: GET /v1/feed answers `doc` with an ETag, 304 to a
    request that sends the ETag back, and ?business=NAME gives that one entry. `code` makes it
    fail; `raw` answers those bytes."""

    def __init__(self, doc=None):
        self.doc, self.code, self.raw, self.seen = MIRROR if doc is None else doc, 200, None, []

    def __enter__(self):
        mirror = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                mirror.seen.append((self.path, self.headers.get("If-None-Match")))
                doc = mirror.doc
                want = urllib.parse.parse_qs(u.query).get("business")
                if want and isinstance(doc, dict):
                    doc = dict(doc, feeds=[e for e in doc["feeds"] if e["business"] == want[0]])
                body = mirror.raw if mirror.raw is not None else json.dumps(doc).encode()
                tag = '"%08x"' % (hash(body) & 0xffffffff)
                if mirror.code == 200 and self.headers.get("If-None-Match") == tag:
                    self.send_response(304)
                    self.send_header("ETag", tag)
                    self.end_headers()
                    return
                self.send_response(mirror.code if u.path == "/v1/feed" else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("ETag", tag)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/feed"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        return False


class Base(unittest.TestCase):
    def setUp(self):
        self.m = FakeMachine()
        self.addCleanup(self.m.close)
        self.cfg = self.m.tmp / "labjobs.toml"
        self.m.environ["BROMIGOS_LABJOBS_CONFIG"] = str(self.cfg)
        self.env = self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW)
        self.where = L.Where(self.env, system=False)
        self.said = []

    def mirror(self, doc=None):
        m = Mirror(doc)
        m.__enter__()
        self.addCleanup(m.__exit__)
        self.cfg.write_text(f'[[fleet]]\nname = "tasks"\nurl = "{m.url}"\n')
        return m

    def follower(self):
        return L.Follower(self.where, websocket=False, log=self.said.append)

    def at(self, ms):
        self.env.fixed_now = ms

    def state(self):
        return json.loads(Path(self.where.state_dir(), "fleet.json").read_text())

    def by(self, records):
        return {r["id"]: r for r in records}


class Reading(Base):
    """The follower and a status mirror: what it asks, how often, and what it keeps."""

    def test_the_mirror_is_read_and_its_report_kept_beside_the_jobs(self):
        m = self.mirror()
        got = self.follower().pass_once()
        self.assertEqual(m.seen, [("/v1/feed", None)])
        self.assertEqual(len(got), 11)
        jobs = json.loads(Path(self.where.state_dir(), "jobs.json").read_text())
        self.assertEqual([j["id"] for j in jobs["jobs"]], [r["id"] for r in got])
        kept = self.state()
        self.assertEqual((kept["schema"], kept["at"], sorted(kept)), (1, NOW, ["at", "schema", "seen", "sources"]))
        (src,) = kept["sources"]
        self.assertEqual({k: src[k] for k in ("name", "state", "words", "checked_at", "read_at", "target")},
                         {"name": "tasks", "state": "ok", "words": "", "checked_at": NOW, "read_at": NOW, "target": m.url})
        self.assertRegex(src["etag"], r'^"[0-9a-f]{8}"$')
        self.assertEqual([(e["business"], e["received_at"]) for e in src["feeds"]], [("example", "2026-11-28T11:40:09Z")])
        self.assertEqual(src["feeds"][0]["feed"], MIRROR["feeds"][0]["feed"])
        self.assertEqual(sorted(kept["seen"]), sorted(r["id"] for r in got))
        self.assertEqual(oct(Path(self.where.state_dir(), "fleet.json").stat().st_mode & 0o777), "0o640")
        self.assertEqual(self.said, [])

    def test_it_asks_once_a_minute_and_an_unchanged_answer_is_a_304(self):
        m = self.mirror()
        f = self.follower()
        f.pass_once()
        for ms in (2_000, 30_000, 59_999):                       # the follower's own looks, every 2 to 30 s
            self.at(NOW + ms)
            self.assertEqual(len(f.pass_once()), 11)
        self.assertEqual(len(m.seen), 1)
        self.at(NOW + MIN)
        before = self.by(f.pass_once())
        self.assertEqual((len(m.seen), m.seen[1][0]), (2, "/v1/feed"))
        self.assertRegex(m.seen[1][1], r'^"[0-9a-f]{8}"$')        # If-None-Match: the mirror answers 304
        self.assertEqual((self.state()["sources"][0]["state"], self.state()["sources"][0]["checked_at"],
                          self.state()["sources"][0]["read_at"]), ("ok", NOW + MIN, NOW))
        # a new report replaces the old one
        m.doc = answer(needs_person=[], headline="1 needs you · 2 proposed · 3 working · 1 waiting · 4 merged today")
        self.at(NOW + 2 * MIN)
        after = self.by(f.pass_once())
        self.assertEqual(sorted(set(before) - set(after)), ["task.example.app.41", "task.example.site.9"])
        self.assertEqual(self.state()["sources"][0]["read_at"], NOW + 2 * MIN)

    def test_a_mirror_that_started_again_is_empty_and_the_last_report_stays(self):
        m = self.mirror()
        f = self.follower()
        self.assertEqual(len(f.pass_once()), 11)
        m.doc = {"schema": 1, "feeds": []}
        self.at(NOW + MIN)
        self.assertEqual(len(f.pass_once()), 11, "the last good report is still shown")
        src = self.state()["sources"][0]
        self.assertEqual((src["state"], src["read_at"], len(src["feeds"])), ("empty", NOW, 1))
        self.assertIn("no report yet", src["words"])
        self.assertEqual(self.said, [], "an empty mirror is no error")
        # a follower that starts later (the board starts it when someone looks) takes up what was kept
        self.at(NOW + 2 * MIN)
        again = self.follower()
        self.assertEqual(len(again.pass_once()), 11)
        self.assertEqual(m.seen[-1], ("/v1/feed", None), "an empty answer left no ETag to send back")
        # and the mirror's next report is taken as soon as it is there
        m.doc = MIRROR
        self.at(NOW + 3 * MIN)
        again.pass_once()
        self.assertEqual(self.state()["sources"][0]["state"], "ok")

    def test_a_mirror_with_no_report_at_all_has_no_tasks_and_says_so(self):
        self.mirror({"schema": 1, "feeds": []})
        self.assertEqual(self.follower().pass_once(), [])
        doc = L.fleet_document(self.where)
        self.assertEqual((doc["configured"], doc["state"], doc["fleets"]), (True, "unreachable", []))
        self.assertEqual(list(doc["errors"]), ["tasks"])
        self.assertIn("no report yet", doc["errors"]["tasks"])

    def test_a_mirror_that_does_not_answer_keeps_the_last_report_and_is_said_once(self):
        m = self.mirror()
        f = self.follower()
        f.pass_once()
        m.code = 503
        for k in (1, 2, 3):
            self.at(NOW + k * MIN)
            self.assertEqual(len(f.pass_once()), 11)
        src = self.state()["sources"][0]
        self.assertEqual((src["state"], src["words"], src["read_at"], src["etag"]),
                         ("down", "the status mirror answered HTTP 503", NOW, None))
        m.code = 302                                             # a redirect is never followed: it might point anywhere
        self.at(NOW + 3 * MIN + 30_000)
        f.pass_once()
        self.at(NOW + 4 * MIN + 30_000)
        f.pass_once()
        self.assertEqual(self.state()["sources"][0]["words"], "the status mirror answered HTTP 302")
        self.assertEqual(len([p for p, _tag in m.seen if p == "/v1/feed"]), len(m.seen), "and nothing else was asked")
        m.code = 503
        self.at(NOW + 5 * MIN + 30_000)
        f.pass_once()
        self.said = self.said[:1]
        self.assertEqual(self.said, ["bromigos activity follow: the fleet tasks wasn't read: the status mirror answered HTTP 503"])
        doc = L.fleet_document(self.where)
        self.assertEqual((doc["state"], len(doc["fleets"])), ("warn", 1))
        self.assertEqual(doc["errors"], {"tasks": "the status mirror answered HTTP 503: this is the last report it gave"})
        m.__exit__()                                             # and with nothing listening at all
        self.at(NOW + 7 * MIN)
        self.assertEqual(len(f.pass_once()), 11)
        self.assertEqual(self.state()["sources"][0]["words"], "the status mirror isn't answering")

    def test_what_isnt_a_mirrors_answer_is_refused_in_plain_words(self):
        m = self.mirror()
        f = self.follower()
        for raw, words in ((b"<html>a page</html>", "the answer isn't JSON"),
                           (b"[1, 2]", 'the mirror\'s answer is not {"schema": 1, "feeds": […]}'),
                           (json.dumps({"schema": 2, "feeds": []}).encode(), 'the mirror\'s answer is not {"schema": 1, "feeds": […]}'),
                           (json.dumps({"schema": 1}).encode(), 'the mirror\'s answer is not {"schema": 1, "feeds": […]}'),
                           (b"{" + b" " * (L.FLEET_MAX + 8) + b"}", "the answer is larger than any feed")):
            m.raw = raw
            self.at(self.env.now_ms() + MIN)
            self.assertEqual(f.pass_once(), [], raw[:30])
            self.assertEqual((self.state()["sources"][0]["state"], self.state()["sources"][0]["words"]), ("down", words))

    def test_a_feed_of_another_schema_is_named_and_shows_nothing(self):
        self.mirror(answer(schema=2))
        self.assertEqual(self.follower().pass_once(), [])
        (entry,) = self.state()["sources"][0]["feeds"]
        self.assertEqual((entry["business"], "feed" in entry), ("example", False))
        doc = L.fleet_document(self.where)
        self.assertEqual((doc["state"], doc["fleets"]), ("unreachable", []))
        self.assertIn("the feed is schema 2 and this bromigOS reads schema 1", doc["errors"]["tasks: example"])

    def test_two_businesses_each_have_their_own_tasks(self):
        m = self.mirror(second())
        got = self.by(self.follower().pass_once())
        self.assertEqual(len(got), 12)
        self.assertEqual({r["task"]["fleet"] for r in got.values()}, {"example", "second"})
        both = (got["task.example.app.57"], got["task.second.app.57"])       # the same repository and number, twice
        self.assertEqual([r["requested_by"]["agent"] for r in both], ["example", "second"])
        self.assertEqual([r["task"]["business"] for r in both], ["Example", "Second"])
        doc = L.fleet_document(self.where)
        self.assertEqual([(v["business"], v["mirror"], v["source"], v["headline"]) for v in doc["fleets"]],
                         [("Example", "example", "tasks", "3 need you · 2 proposed · 3 working · 1 waiting · 4 merged today"),
                          ("Second", "second", "tasks", "Nothing needs you · 1 working · 0 waiting · 0 merged today")])
        # `business` keeps one of them, whichever way it is asked for
        self.cfg.write_text(f'[[fleet]]\nname = "tasks"\nurl = "{m.url}"\nbusiness = "second"\n')
        self.assertEqual(sorted(self.by(self.follower().pass_once())), ["task.second.app.57"])
        self.cfg.write_text(f'[[fleet]]\nname = "tasks"\nurl = "{m.url}?business=example"\n')
        self.assertEqual(len(self.follower().pass_once()), 11)
        self.assertEqual(m.seen[-1][0], "/v1/feed?business=example")

    def test_a_feed_file_on_this_machine(self):
        folder = self.m.tmp / "fleet"
        folder.mkdir()
        path = folder / "feed.json"
        path.write_text(json.dumps(MIRROR))
        self.cfg.write_text(f'[[fleet]]\nname = "here"\nfile = "{path}"\n')
        f = self.follower()
        self.assertEqual(len(f.pass_once()), 11)
        src = self.state()["sources"][0]
        self.assertEqual((src["name"], src["state"], src["target"]), ("here", "ok", str(path)))
        self.at(NOW + MIN)
        self.assertEqual(len(f.pass_once()), 11)                 # the same bytes: nothing read again
        self.assertEqual(self.state()["sources"][0]["read_at"], NOW)
        # the file can hold one feed as well as a mirror's answer
        path.write_text(json.dumps(dict(MIRROR["feeds"][0]["feed"], business="Solo Shop")))
        self.at(NOW + 2 * MIN)
        self.assertEqual({r["task"]["fleet"] for r in f.pass_once()}, {"solo-shop"})
        # a link or a missing file is never read; the last report stays
        path.unlink()
        path.symlink_to(self.m.tmp / "labjobs.toml")
        self.at(NOW + 3 * MIN)
        self.assertEqual(len(f.pass_once()), 11)
        self.assertEqual(self.state()["sources"][0]["state"], "down")
        self.assertIn("the feed file can't be read", self.state()["sources"][0]["words"])

    def test_a_fleet_that_left_the_settings_leaves_nothing_behind(self):
        self.mirror()
        f = self.follower()
        self.assertEqual(len(f.pass_once()), 11)
        self.cfg.write_text("")
        self.at(NOW + 1000)
        self.assertEqual(f.pass_once(), [])
        self.assertEqual((self.state()["sources"], self.state()["seen"]), ([], {}))
        self.assertEqual(L.fleet_document(self.where)["configured"], False)

    def test_without_the_lab_console_a_fleet_says_what_is_missing(self):
        self.mirror()
        with unittest.mock.patch.object(L, "_fleet", lambda: None):
            self.assertEqual(self.follower().pass_once(), [])
            self.assertEqual(self.state()["sources"][0]["words"], L.NO_FLEET)
            doc = L.fleet_document(self.where)
        self.assertEqual((doc["state"], doc["fleets"], doc["errors"]), ("unreachable", [], {"board": L.NO_FLEET}))
        self.assertTrue(Path(self.where.state_dir(), "jobs.json").exists(), "the lab's other jobs are still written")


class Settings(Base):
    def test_fleet_tables(self):
        self.cfg.write_text(
            '[[fleet]]\nname = "Tasks!"\nurl = "http://status-mirror.mylab.example:8082/v1/feed"\nbusiness = "Example"\n'
            '[[fleet]]\nname = "tasks"\nurl = "http://other.mylab.example/v1/feed"\n'                   # the same name: once
            '[[fleet]]\nname = "creds"\nurl = "http://user:pass@status-mirror.mylab.example/v1/feed"\n'
            '[[fleet]]\nname = "scheme"\nurl = "file:///etc/passwd"\n'
            '[[fleet]]\nname = "both"\nurl = "http://a.mylab.example/v1/feed"\nfile = "/srv/fleet/feed.json"\n'
            '[[fleet]]\nname = "neither"\n'
            '[[fleet]]\nname = "relative"\nfile = "feed.json"\n'
            '[[fleet]]\nname = "here"\nfile = "/srv/fleet/feed.json"\n'
            '[[fleet]]\nfile = "~/fleet.json"\n')
        got = L.fleets(self.where)
        self.assertEqual([(f["name"], f["url"], f["file"], f["business"]) for f in got],
                         [("tasks", "http://status-mirror.mylab.example:8082/v1/feed", "", "example"),
                          ("here", "", "/srv/fleet/feed.json", ""), ("fleet", "", str(self.m.home / "fleet.json"), "")])
        self.assertEqual(L.instances(self.where), [], "a fleet is no ComfyUI")

    def test_the_followers_addresses_include_the_mirrors_and_nothing_else(self):
        sysconf = self.m.root / "etc/bromigos"
        sysconf.mkdir(parents=True)
        (sysconf / "labjobs.toml").write_text('[[comfyui]]\nname = "studio"\nurl = "http://gpu.lan:8188"\n'
                                              '[[fleet]]\nname = "tasks"\nurl = "http://status-mirror.mylab.example:8082/v1/feed"\n'
                                              '[[fleet]]\nname = "here"\nfile = "/srv/fleet/feed.json"\n')
        self.m.environ.pop("BROMIGOS_LABJOBS_CONFIG")
        where = L.Where(self.m.env(), system=True)
        names = {"gpu.lan": {"10.0.0.7"}, "status-mirror.mylab.example": {"10.0.0.9", "fd00::9"}}
        self.assertEqual(L.allow_addresses(where, names.__getitem__), ["10.0.0.7", "10.0.0.9", "fd00::9"])
        self.assertIn("IPAddressAllow=10.0.0.7 10.0.0.9 fd00::9\n", L.allow_dropin(where, names.__getitem__))


class Records(Base):
    """The feed's tasks as activity records."""

    def setUp(self):
        super().setUp()
        self.mirror()
        self.recs = self.follower().pass_once()
        self.got = self.by(self.recs)

    def test_the_activity_record_keys_are_all_there(self):
        for r in self.recs:
            self.assertEqual(set(r) - {"task"}, RECORD_KEYS)
            self.assertNotIn("lab", r, "a task is drawn as a job of its own, not as a ComfyUI's")
            self.assertEqual([set(s) for s in r["steps"]], [STEP_KEYS])
            self.assertRegex(r["id"], L.TASK_ID)
            self.assertTrue(L.is_lab_id(r["id"]) and A.is_lab(r["id"]))
            self.assertRegex(r["id"], A.ID_OK)
            self.assertEqual((r["kind"], r["schema"], r["question"], r["can"], r["cancel_safe"], r["command"], r["log"],
                              r["unit"], r["step"], r["pct"]), ("agent.task", 1, None, [], False, [], None, None, None, None))
            self.assertEqual(r["requested_by"], {"via": "lab", "device": None, "agent": "example"})
            self.assertTrue(A.KIND_OK.match(r["kind"]) and r["state"] in A.STATES)
            json.dumps(r)

    def test_one_per_task_that_needs_you_runs_or_waits_and_per_merge_of_today(self):
        self.assertEqual({r["id"]: r["state"] for r in self.recs}, {
            "task.example.app.41": "needs-you", "task.example.site.9": "needs-you", "task.example.app.60": "needs-you",
            "task.example.app.57": "running", "task.example.app.49": "running", "task.example.site.14": "running",
            "task.example.site.12": "queued",
            "task.example.app.52": "succeeded", "task.example.site.11": "succeeded", "task.example.app.50": "succeeded",
            "task.example.app.47": "succeeded"})
        ids = set(self.got)
        self.assertNotIn("task.example.site.7", ids, "merged two days ago")
        self.assertNotIn("task.example.site.20", ids, "a proposal is no job yet")
        self.assertNotIn("task.example.site.3", ids, "what the fleet leaves alone")
        self.assertEqual([r["state"] for r in self.recs][:3], ["running"] * 3, "what is going comes first, as for every job")
        self.assertEqual([r["state"] in A.FINAL for r in self.recs], [False] * 7 + [True] * 4)

    def test_a_task_that_needs_you(self):
        r = self.got["task.example.app.41"]
        self.assertEqual((r["title"], r["state"], r["waiting_for"], r["stage"]),
                         ("app#41 Checkout: totals are wrong when a coupon is applied", "needs-you", "you",
                          "Stuck · 3 fix rounds and a clean restart did not make it green"))
        self.assertEqual(r["subject"], {"type": "task", "id": "app#41", "name": "app#41"})
        self.assertEqual(r["steps"], [{"id": "now", "label": "Stuck · 3 fix rounds and a clean restart did not make it green",
                                       "state": "waiting", "started_at": r["started_at"], "ended_at": None, "detail": None,
                                       "progress": None}])
        self.assertEqual(r["started_at"], int(datetime(2026, 11, 28, 8, 12, 44, tzinfo=timezone.utc).timestamp() * 1000))
        self.assertEqual((r["ended_at"], r["result"], r["error"]), (None, None, None))
        # its links are what the record says along the way, and its facts
        self.assertEqual([n["words"] for n in r["notes"]], ["app#41: https://github.com/my-org/app/issues/41",
                                                            "PR #44: https://github.com/my-org/app/pull/44"])
        self.assertEqual(r["task"], {
            "source": "tasks", "fleet": "example", "business": "Example", "repo": "app", "number": 41, "issue": 41, "pr": 44,
            "label": "app#41", "lane": "needs_you", "phrase": "Stuck · 3 fix rounds and a clean restart did not make it green",
            "why": "", "url": "https://github.com/my-org/app/issues/41",
            "links": [{"text": "app#41", "url": "https://github.com/my-org/app/issues/41"},
                      {"text": "PR #44", "url": "https://github.com/my-org/app/pull/44"}],
            "account": None, "attempt": None, "stale": False,
            "report_at": int(datetime(2026, 11, 28, 11, 40, 3, tzinfo=timezone.utc).timestamp() * 1000)})
        # one the feed moved to Needs you from its waiting list says what to do, and why
        moved = self.got["task.example.app.60"]
        self.assertEqual((moved["state"], moved["stage"], moved["notes"][0]["words"]),
                         ("needs-you", "Not started · re-apply agent-ready yourself",
                          "the start label was applied by someone whose labelling does not count"))

    def test_working_waiting_and_done(self):
        run = self.got["task.example.app.49"]
        self.assertEqual((run["state"], run["stage"], run["steps"][0]["state"], run["waiting_for"], run["ended_at"]),
                         ("running", "Fixing · round 2", "running", None, None))
        self.assertEqual(run["started_at"], int(datetime(2026, 11, 28, 11, 20, 41, tzinfo=timezone.utc).timestamp() * 1000))
        self.assertEqual(run["cancel_note"], "A fleet's task is stopped in its own repository, not from here.")
        self.assertEqual([n["words"] for n in run["notes"]],
                         ["account 1", "app#49: https://github.com/my-org/app/issues/49", "PR #55: https://github.com/my-org/app/pull/55",
                          "run: https://github.com/my-org/agents/actions/runs/7000000088"])
        wait = self.got["task.example.site.12"]
        self.assertEqual((wait["state"], wait["stage"], wait["steps"][0]["state"], wait["started_at"]),
                         ("queued", "Queued · no Claude account is free", "todo", NOW))
        done = self.got["task.example.app.52"]
        merged = int(datetime(2026, 11, 28, 10, 58, 20, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertEqual((done["state"], done["stage"], done["steps"][0]["state"], done["ended_at"], done["cancel_note"]),
                         ("succeeded", "Merged", "done", merged, None))
        self.assertEqual(done["started_at"], merged - int(12.4 * MIN), "the run that opened it took 12.4 minutes")
        self.assertEqual(done["result"], {"ok": True, "summary": "Merged", "undo": None})
        self.assertEqual(done["notes"][0]["words"], "account 2 · 31 turns · 12 min · reviewed by gate")

    def test_a_record_changes_only_when_its_task_does(self):
        m = self.mirror()
        f = self.follower()
        first = self.by(f.pass_once())
        self.at(NOW + MIN)
        same = self.by(f.pass_once())
        self.assertEqual({i: r["updated_at"] for i, r in same.items()}, {i: r["updated_at"] for i, r in first.items()})
        self.assertEqual(same["task.example.site.12"]["started_at"], NOW, "first seen then, and still")
        feed = json.loads(json.dumps(MIRROR["feeds"][0]["feed"]))
        feed["working"][0].update(step="verify", phrase="Checking the change")
        del feed["working"][2]                                    # site#14 was merged, or closed: it left the feed
        m.doc = {"schema": 1, "feeds": [dict(MIRROR["feeds"][0], feed=feed)]}
        self.at(NOW + 2 * MIN)
        later = self.by(f.pass_once())
        self.assertEqual((later["task.example.app.57"]["stage"], later["task.example.app.57"]["updated_at"]),
                         ("Checking the change", NOW + 2 * MIN))
        self.assertEqual(later["task.example.app.49"]["updated_at"], first["task.example.app.49"]["updated_at"])
        self.assertNotIn("task.example.site.14", later)
        self.assertNotIn("task.example.site.14", self.state()["seen"])
        # what was kept outlives the follower: a new one doesn't call every task new
        again = self.by(self.follower().pass_once())
        self.assertEqual(again["task.example.site.12"]["started_at"], NOW)
        self.assertEqual(again["task.example.app.57"]["updated_at"], NOW + 2 * MIN)

    def test_a_stale_report_marks_its_records_and_a_day_later_has_none(self):
        late = NOW + 88 * MIN + 3_000                              # ten minutes past `stale_after`
        self.at(late)
        got = self.by(self.follower().pass_once())
        self.assertEqual(len(got), 11, "nothing is deleted at once")
        stale = int(datetime(2026, 11, 28, 13, 10, 3, tzinfo=timezone.utc).timestamp() * 1000)
        ask = got["task.example.app.41"]
        self.assertEqual((ask["state"], ask["task"]["stale"]), ("needs-you", True))
        self.assertEqual(ask["steps"][0]["detail"],
                         "The fleet hasn't reported since 12:40 (1 h 40 min ago): this is the last it said.")
        for i in ("task.example.app.57", "task.example.app.49", "task.example.site.14", "task.example.site.12"):
            r = got[i]
            self.assertEqual((r["state"], r["ended_at"], r["steps"][0]["state"], r["cancel_note"]), ("interrupted", stale, "skipped", None), i)
            self.assertEqual(r["result"], {"ok": False, "summary": "No report says how it went on.", "undo": None})
        self.assertEqual(got["task.example.app.49"]["error"], {
            "step": None, "code": "stale", "fix": None,
            "words": "The fleet hasn't reported since 12:40 (1 h 40 min ago). It was: Fixing · round 2."})
        self.assertEqual(got["task.example.app.52"]["state"], "succeeded")
        self.assertGreater(got["task.example.app.49"]["updated_at"], self.got["task.example.app.49"]["updated_at"],
                           "the change reaches the pages")
        doc = L.fleet_document(self.where)
        self.assertEqual((doc["state"], doc["fleets"][0]["state"], doc["fleets"][0]["headline"]),
                         ("warn", "stale", "No update for 1 h 40 min"))
        self.at(stale + L.FLEET_KEEP_MS)
        self.assertEqual(len(self.follower().pass_once()), 7, "a day later, still: what needs you and what was merged that day")
        self.at(stale + L.FLEET_KEEP_MS + 1)
        self.assertEqual(self.follower().pass_once(), [])
        self.assertEqual(len(L.fleet_document(self.where)["fleets"]), 1, "the report itself is still there to read")

    def test_a_fleet_that_is_switched_off(self):
        self.mirror(answer(enabled=False))
        got = self.by(self.follower().pass_once())
        self.assertEqual(got["task.example.app.57"]["state"], "interrupted")
        self.assertEqual(got["task.example.app.57"]["error"]["words"],
                         "The fleet is switched off since 12:40 (11 min ago). It was: Writing.")
        self.assertEqual(got["task.example.app.41"]["state"], "needs-you")
        self.assertEqual(L.fleet_document(self.where)["fleets"][0]["headline"], "SWITCHED OFF")

    def test_hostile_titles_and_reasons_are_cleaned_before_they_are_kept(self):
        evil = "\x1b]52;c;aGVsbG8=\x07\x1b[2J\u202e"
        feed = json.loads(json.dumps(MIRROR["feeds"][0]["feed"]))
        feed["working"][0].update(title=f"Ship it{evil}\nnow\r\n<script>alert(1)</script> [bold]x[/] " + "A" * 5000,
                                  phrase=f"Writing{evil}\nfast " + "!" * 900)
        feed["needs_person"][0].update(title=f"\x1b]0;pwned\x07Stuck{evil}", why=f"because{evil}\nline two " + "w" * 900,
                                       phrase=f"Stuck · because{evil}\nline two " + "w" * 900)
        feed["working"][1].update(issue_url="javascript:alert(1)", url="https://evil.example/a b", pr_url=f"https://x.example/{evil}",
                                  run_url="https://github.com/my-org/agents/actions/runs/1\n")
        feed["working"][2].update(repo="../../etc")                # no plain name: no record
        feed["waiting"][0].update(repo=f"site{evil}")
        feed["business"] = f"Ex{evil}ample\nInc"
        doc = {"schema": 1, "feeds": [{"business": f"ex{evil}ample\n../x", "received_at": f"now{evil}", "feed": feed}]}
        self.mirror(doc)
        f = self.follower()
        got = self.by(f.pass_once())
        text = json.dumps(got, ensure_ascii=False)
        self.assertIsNone(UNSAFE.search(text), repr(UNSAFE.search(text)))
        self.assertEqual(sorted(got)[:2], ["task.example-x.app.41", "task.example-x.app.47"], "the id is made of plain names only")
        self.assertTrue(all(L.TASK_ID.match(i) for i in got))
        self.assertEqual(len(got), 10, "the row whose repository isn't a plain name has no record")
        self.assertIn("task.example-x.site.12", got, "and one whose name only carried escapes is its plain name")
        hot = got["task.example-x.app.57"]
        self.assertEqual(hot["title"][:60], "app#57 Ship it now <script>alert(1)</script> [bold]x[/] AAAA")    # text, as written
        self.assertLessEqual(len(hot["title"]), A.MAX_TITLE)
        self.assertLessEqual(len(hot["stage"]), A.MAX_DETAIL)
        self.assertLessEqual(len(hot["steps"][0]["label"]), A.MAX_LABEL)
        self.assertEqual(hot["stage"][:13], "Writing fast ")
        self.assertEqual(hot["requested_by"]["agent"], "example-x")
        self.assertEqual(hot["task"]["business"], "Example Inc")
        ask = got["task.example-x.app.41"]
        self.assertEqual((ask["title"][:12], ask["stage"][:29]), ("app#41 Stuck", "Stuck · because line two wwww"))
        self.assertEqual(ask["task"]["why"], "", "said once: the phrase carries it")
        odd = got["task.example-x.app.49"]                        # an address that isn't a plain http(s) one is no link
        self.assertEqual((odd["task"]["url"], odd["task"]["links"], [n["words"] for n in odd["notes"]]), ("", [], ["account 1"]))
        # the files the pages and the terminal read carry none of it either
        for name in ("jobs.json", "fleet.json"):
            kept = json.dumps(json.loads(Path(self.where.state_dir(), name).read_text()), ensure_ascii=False)
            self.assertIsNone(UNSAFE.search(kept), name)
        board = json.dumps(L.fleet_document(self.where), ensure_ascii=False)
        self.assertIsNone(UNSAFE.search(board))
        shown = A.plain_show(hot, [], NOW) + A.plain_list(list(got.values()), NOW)
        self.assertNotIn("\x1b", shown)
        self.assertNotIn("\u202e", shown)

    def test_a_task_without_a_number_has_no_record(self):
        self.assertIsNone(L.task_id("example", "app", None))
        self.assertIsNone(L.task_id("example", "app", True))
        self.assertIsNone(L.task_id("example", "a b", 4))
        self.assertEqual(L.task_id("Example Shop!", "My.App_2", 4), "task.example-shop.my.app_2.4")


class Reach(Base):
    """bromigos_activity and `bromigos activity` on a fleet's tasks."""

    def setUp(self):
        super().setUp()
        self.mirror()
        self.follower().pass_once()

    def test_readers_take_the_followers_records(self):
        ids = [j["id"] for j in L.jobs(self.env, self.where, live=False)]
        self.assertEqual(len(ids), 11)
        self.assertEqual(L.jobs(self.env, self.where, live=False, tasks=False), [])
        self.assertEqual(A.list_jobs(self.env), [], "the lab's jobs are asked for by name")
        self.assertEqual(sorted(j["id"] for j in A.list_jobs(self.env, lab={"where": self.where})), sorted(ids))
        self.assertEqual(L.find(self.env, "task.example.app.41", self.where)["state"], "needs-you")
        self.assertEqual(L.find(self.env, "site.12", self.where)["id"], "task.example.site.12", "a part only one has")
        self.at(NOW + L.STATE_FRESH_MS + 1)                       # an old jobs.json isn't used, as for every lab job
        self.assertEqual(L.jobs(self.env, self.where, live=False), [])

    def test_without_a_follower_a_person_reads_the_mirror_once(self):
        os.unlink(Path(self.where.state_dir(), "jobs.json"))
        got = L.jobs(self.env, self.where)
        self.assertEqual(len(got), 11)
        self.assertEqual(L.jobs(self.env, self.where, live=False), [])

    def test_a_task_cant_be_answered_or_stopped_from_here(self):
        rec = L.find(self.env, "task.example.app.41", self.where)
        out = L.cancel(self.env, rec["id"], self.where)
        self.assertEqual((out["ok"], out["refused"], out["words"]),
                         (False, "unsafe", "A fleet's task is stopped in its own repository, not from here."))
        done = L.cancel(self.env, "task.example.app.52", self.where)
        self.assertEqual(done["refused"], "ended")

    def test_the_command_lists_and_shows_them(self):
        env = {"BROMIGOS_LABJOBS_CONFIG": str(self.cfg), "BROMIGOS_ACTIVITY_NOW_MS": str(NOW),
               "PYTHONPATH": f"{REPO / 'homelab' / 'lib'}"}
        code, out, err = self.m.cli("list", "--lab", env=env)
        self.assertEqual(code, 0, err)
        self.assertIn("needs you", out)
        self.assertIn("task.example.app.41  app#41 Checkout: totals are wrong when a coupon is applied, by agent example: "
                      "Stuck · 3 fix rounds and a clean restart did not make it green", " ".join(out.split("  ")))
        code, out, err = self.m.cli("show", "task.example.app.49", env=env)
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertEqual(lines[0], "app#49 Search: an empty query returns a server error")
        self.assertIn("  Fixing · round 2", lines)
        self.assertIn("  ▲ PR #55: https://github.com/my-org/app/pull/55", lines)
        self.assertIn("Fleet    Example  ·  app#49  ·  working", lines)
        self.assertNotIn("Unit", out, "it has no unit, log or command on this machine")
        code, out, err = self.m.cli("show", "--json", "task.example.app.49", env=env)
        self.assertEqual((code, json.loads(out)["job"]["kind"], json.loads(out)["log_tail"]), (0, "agent.task", []))
        code, out, err = self.m.cli("cancel", "task.example.app.49", env=env)
        self.assertEqual(code, 3, out + err)
        code, out, err = self.m.cli("answer", "task.example.app.41", "yes", env=env)
        self.assertEqual(code, 3, out + err)
        self.assertIn("isn't asking", out + err)

    def test_between_two_looks_an_idle_follower_says_its_records_still_stand(self):
        """The follower looks every 30 s while nothing runs, and a reader uses jobs.json for 15 s:
        it is stamped again in between, so a task doesn't come and go on the pages."""
        f = self.follower()
        clock, stamps, looks, real, restamp = [1000.0], [], [0], f.pass_once, f.restamp

        def look():
            looks[0] += 1
            if looks[0] == 2:
                f.stop.set()
            return real()

        def sleep(seconds):
            clock[0] += seconds
            self.at(NOW + int((clock[0] - 1000.0) * 1000))

        def stamp():
            restamp()
            stamps.append(json.loads(Path(self.where.state_dir(), "jobs.json").read_text())["at"] - NOW)
            self.assertEqual(len(L.jobs(self.env, self.where, live=False)), 11, "a reader has them at every moment")
        f.pass_once, f.restamp = look, stamp
        with unittest.mock.patch.object(L.time, "monotonic", lambda: clock[0]):
            f.run(sleep=sleep)
        self.assertEqual(stamps[:2], [8000, 16000])
        self.assertLess(max(b - a for a, b in zip([0] + stamps, stamps)), L.STATE_FRESH_MS)

    def test_a_fleets_tasks_dont_make_the_follower_look_more_often(self):
        f = self.follower()
        waits, looks, real = [], [0], f.pass_once

        def look():
            looks[0] += 1
            if looks[0] == 2:
                f.stop.set()
            return real()
        f.pass_once = look
        f.run(sleep=waits.append)
        self.assertGreaterEqual(sum(waits), 28, "three tasks are being worked on, and the follower still looks every 30 s")


class Words(unittest.TestCase):
    def test_the_board_and_the_command_say_the_same_document(self):
        when = datetime.fromtimestamp(NOW / 1000, timezone.utc)
        view = F.view(MIRROR["feeds"][0]["feed"], when)
        m = FakeMachine()
        self.addCleanup(m.close)
        folder = m.tmp / "fleet"
        folder.mkdir()
        (folder / "feed.json").write_text(json.dumps(MIRROR))
        cfg = m.tmp / "labjobs.toml"
        cfg.write_text(f'[[fleet]]\nname = "tasks"\nfile = "{folder / "feed.json"}"\n')
        m.environ["BROMIGOS_LABJOBS_CONFIG"] = str(cfg)
        where = L.Where(m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW), system=False)
        L.Follower(where, websocket=False, log=lambda w: None).pass_once()
        doc = L.fleet_document(where)
        told = F.assemble([dict(view, source="tasks")], {}, True, when)       # what `bromigos lab tasks --json` prints
        self.assertEqual({k: doc[k] for k in told if k != "fleets"}, {k: told[k] for k in told if k != "fleets"})
        self.assertEqual({k: v for k, v in doc["fleets"][0].items() if k not in ("mirror", "received_at")}, told["fleets"][0])
        self.assertEqual((doc["fleets"][0]["mirror"], doc["fleets"][0]["received_at"]), ("example", "2026-11-28T11:40:09Z"))
        self.assertEqual(doc["sources"], [{"name": "tasks", "state": "ok", "words": "", "checked_at": NOW, "read_at": NOW}])


if __name__ == "__main__":
    unittest.main()
