"""Tasks: a fleet of coding agents read from its control repository's Status issue (fleet.py,
adapters/labfleet.py, the Tasks card, `bromigos lab tasks`), against a recorded issue body
(tests/fixtures/fleet-status-body.txt: a feed from before it carried lanes and phrases), a
status mirror's recorded answer (tests/fixtures/fleet-mirror.json: a feed with them), a stand-in
`gh` and a stand-in mirror. Placeholder names only. No network, no GitHub login.

    PYTHONPATH=lib:../lib python -m unittest discover -s tests
    LAB_TASKS_GOLDEN_UPDATE=1 …      rewrite tests/golden/lab-tasks.txt after a deliberate change
"""
import asyncio
import contextlib
import http.server
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import labfake
import bromigos_homelab as H
from bromigos_homelab import caps, cards, console, fleet, registry
from bromigos_homelab.adapters import labfleet

try:
    import textual
    from bromigos_homelab import tui
    import test_lab_tui
except ImportError:                                  # no python-textual: the dashboard isn't built
    textual = None

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(os.path.dirname(HERE), "bin", "bromigos-lab")
GOLDEN = os.path.join(HERE, "golden", "lab-tasks.txt")
with open(os.path.join(HERE, "fixtures", "fleet-status-body.txt")) as _f:
    BODY = _f.read()
with open(os.path.join(HERE, "fixtures", "fleet-mirror.json")) as _f:
    MIRROR = json.load(_f)
NOW = datetime(2026, 11, 28, 11, 52, 0, tzinfo=timezone.utc)      # twelve minutes after the feed was written
BOT = {"login": "github-actions[bot]"}
SOURCE = '[[source]]\nname = "tasks"\ntype = "fleet"\nrepo = "my-org/agents"\n'
# what must never reach a terminal or a card from text other people wrote
UNSAFE = re.compile("[\x00-\x09\x0b-\x1f\x7f-\x9f\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ud800-\udfff]")


def feed():
    return fleet.parse_body(BODY)


def worded():
    """The feed the status mirror holds: one that names each task's lane and phrase itself."""
    return json.loads(json.dumps(MIRROR["feeds"][0]["feed"]))


def lanes(v):
    return {lane["id"]: lane for lane in v["lanes"]}


def work(stage, step=None, **more):
    return dict({"repo": "app", "issue": 70, "pr": None, "title": "A task", "stage": stage, "step": step,
                 "url": "https://github.com/my-org/app/issues/70",
                 "issue_url": "https://github.com/my-org/app/issues/70"}, **more)


def issues(*found):
    """gh api's answer: the state-labelled issues, a ledger first, as one page."""
    return json.dumps([{"number": 3, "title": "Runs", "user": BOT, "body": "a ledger"}] + list(found))


def done(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess(["gh"], code, stdout, stderr)


class GH:
    """A stand-in gh: fleet.py finds it on the PATH and runs it; this records what it was asked."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __enter__(self):
        def run(argv, **kw):
            self.calls.append((argv, kw))
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer
        self._p = [mock.patch.object(fleet.shutil, "which", lambda name, *a, **k: "/usr/bin/gh" if name == "gh" else None),
                   mock.patch.object(fleet.subprocess, "run", run)]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._p):
            p.stop()
        return False


class ParseTest(unittest.TestCase):
    def test_the_recorded_body_holds_one_feed(self):
        f = feed()
        self.assertEqual((f["schema"], f["business"], f["control_repo"], f["timezone"]),
                         (1, "Example", "my-org/agents", "Europe/Berlin"))
        self.assertEqual([len(f[k]) for k in ("working", "waiting", "needs_person", "recent", "accounts")],
                         [3, 1, 2, 8, 2])
        # the feed writes ` < > & as \\uXXXX: any JSON parser gives the characters back
        self.assertEqual(f["waiting"][0]["title"], "Docs: explain what `--json` prints & where <details> goes")
        self.assertEqual(fleet.parse_body(BODY.replace("\n", "\r\n")), f)

    def test_refuses_a_body_without_exactly_one_json_fence(self):
        for body, word in (("No feed here.", "none"), ("", "none"), (None, "none"), (BODY + "\n" + BODY, "2"),
                           (BODY + "\n```json\n{\"schema\": 1}\n```\n", "2")):
            with self.assertRaises(fleet.FeedError) as e:
                fleet.parse_body(body)
            self.assertIn("exactly one ```json block", str(e.exception))
            self.assertIn(word, str(e.exception))
        # JSON elsewhere in the body is never searched for
        with self.assertRaises(fleet.FeedError):
            fleet.parse_body('{"schema": 1}\n\n```\n{"schema": 1}\n```\n')

    def test_refuses_what_is_not_a_feed(self):
        def body(text):
            return f"words\n\n<details>\n\n```json\n{text}\n```\n\n</details>\n"
        for text, word in (("[1, 2]", "not a JSON object"), ('"schema"', "not a JSON object"), ("{nope", "not JSON"),
                           ("{}", "no `schema` number"), ('{"schema": true}', "no `schema` number"),
                           ('{"schema": "1"}', "no `schema` number")):
            with self.assertRaises(fleet.FeedError) as e:
                fleet.parse_body(body(text))
            self.assertIn(word, str(e.exception), text)
        with self.assertRaises(fleet.FeedError) as e:
            fleet.parse_body("```json\n{\"schema\": 1}\n")
        self.assertIn("not closed", str(e.exception))

    def test_refuses_another_schema_in_plain_words(self):
        with self.assertRaises(fleet.FeedError) as e:
            fleet.parse_body(BODY.replace('"schema":1,', '"schema":2,'))
        self.assertEqual(str(e.exception), "the feed is schema 2 and this bromigOS reads schema 1: update bromigOS to "
                                           "read it")


class CheckTest(unittest.TestCase):
    def test_fresh_until_stale_after(self):
        c = fleet.check(feed(), NOW)
        self.assertEqual((c["state"], c["fresh"], c["stale"], c["age_s"], c["age"]), ("fresh", True, False, 717, "11 min"))
        edge = datetime(2026, 11, 28, 13, 10, 3, tzinfo=timezone.utc)
        self.assertEqual(fleet.check(feed(), edge)["state"], "fresh")
        self.assertEqual(fleet.check(feed(), edge + timedelta(seconds=1))["state"], "stale")
        self.assertEqual(fleet.check(feed(), NOW.timestamp())["state"], "fresh")          # unix seconds work too

    def test_stale_says_for_how_long(self):
        late = datetime(2026, 11, 28, 13, 20, 3, tzinfo=timezone.utc)
        v = fleet.view(feed(), late)
        self.assertEqual((v["state"], v["fresh"], v["headline"]), ("stale", False, "No update for 1 h 40 min"))
        self.assertNotIn("Nothing needs you", v["headline"])
        self.assertEqual(fleet.view(feed(), late + timedelta(days=3))["headline"], "No update for 3 d 1 h")
        self.assertIn("No update means it isn't running", " ".join(fleet.render_text(v).split()))

    def test_switched_off(self):
        f = dict(feed(), enabled=False)
        v = fleet.view(f, NOW)
        self.assertEqual((v["state"], v["fresh"], v["headline"]), ("off", False, "SWITCHED OFF"))
        late = fleet.view(f, NOW + timedelta(hours=5))
        self.assertEqual(late["headline"], "SWITCHED OFF · no update for 5 h 11 min")

    def test_a_feed_that_does_not_say_when(self):
        f = feed()
        del f["stale_after"]                              # ninety minutes after it was written, then
        self.assertEqual(fleet.check(f, NOW)["state"], "fresh")
        self.assertEqual(fleet.check(f, NOW + timedelta(minutes=90))["state"], "stale")
        del f["generated_at"]                             # never called fresh without a time
        v = fleet.view(f, NOW)
        self.assertEqual((v["state"], v["headline"]), ("stale", "No update: the feed doesn't say when it was written"))
        self.assertEqual(fleet.check(dict(feed(), generated_at="yesterday", stale_after=7), NOW)["state"], "stale")

    def test_span(self):
        self.assertEqual([fleet.span(s) for s in (0, 59, 60, 3599, 3600, 6000, 86400, 90000, 200000)],
                         ["under a minute", "under a minute", "1 min", "59 min", "1 h", "1 h 40 min", "1 d", "1 d 1 h",
                          "2 d 7 h"])


class ViewTest(unittest.TestCase):
    def test_the_headline_and_the_lanes_in_order(self):
        v = fleet.view(feed(), NOW)
        self.assertEqual(v["headline"], "2 need you · 3 working · 1 waiting · 4 merged today")
        self.assertEqual([(lane["id"], lane["title"], lane["count"]) for lane in v["lanes"]],
                         [("needs_you", "Needs you", 2), ("proposed", "Proposed", 0), ("working", "Working", 3),
                          ("waiting", "Waiting", 1), ("done", "Done", 5)])
        self.assertEqual((v["schema"], v["noun"], v["business"], v["control_repo"], v["timezone"], v["updated"]),
                         (1, "task", "Example", "my-org/agents", "Europe/Berlin", "12:40"))
        self.assertEqual(v["url"], "https://github.com/my-org/agents/actions/runs/7000000100")
        self.assertEqual(v["counts"]["today"], {"started": 6, "merged": 4, "stuck": 1, "blocked": 0, "rejected": 1})
        self.assertEqual(v["counts"]["seven_days"]["merged"], 9)
        self.assertEqual(v["warnings"], ["the checks of site#14 could not be read this tick: HTTP 502"])
        json.dumps(v)                                     # the document is plain data

    def test_rows_say_their_phrase_time_and_links(self):
        by = lanes(fleet.view(feed(), NOW))
        self.assertEqual([(r["label"], r["phrase"], r["when"]) for r in by["needs_you"]["rows"]],
                         [("app#41", "Stuck · 3 fix rounds and a clean restart did not make it green", "09:12"),
                          ("site#9", "Blocked · the task needs a production credential the agents do not hold",
                           "Fri 27 Nov 17:03")])                      # the feed's time zone, not UTC
        self.assertEqual([(r["label"], r["phrase"], r["when"], r["why"]) for r in by["working"]["rows"]],
                         [("app#57", "Writing", "12:31", ""), ("app#49", "Fixing", "12:20", ""),
                          ("site#14", "Checks running", "", "waiting for 2 check(s): build, test")])
        self.assertEqual([(r["label"], r["phrase"]) for r in by["waiting"]["rows"]],
                         [("site#12", "Queued · ready; no free account this tick")])
        stuck = by["needs_you"]["rows"][0]
        self.assertEqual((stuck["repo"], stuck["number"], stuck["issue"], stuck["pr"], stuck["at"]),
                         ("app", 41, 41, 44, "2026-11-28T08:12:44Z"))
        self.assertEqual(stuck["url"], "https://github.com/my-org/app/issues/41")
        self.assertEqual(stuck["links"], [{"text": "PR #44", "url": "https://github.com/my-org/app/pull/44"}])
        writing = by["working"]["rows"][0]
        self.assertEqual((writing["account"], writing["attempt"], writing["links"][0]["text"]), (1, 1, "run"))

    def test_done_is_the_merged_tasks_and_a_rejection_is_an_event(self):
        d = lanes(fleet.view(feed(), NOW))["done"]
        self.assertEqual([(r["label"], r["phrase"], r["when"]) for r in d["rows"]],
                         [("app#52", "Merged", "11:58"), ("site#11", "Merged", "10:41"), ("app#50", "Merged", "09:05"),
                          ("app#47", "Merged", "08:30"), ("site#7", "Merged", "Thu 26 Nov 16:00")])
        # work that ended without a merge is an event under Done, never a finished task
        self.assertEqual([(r["label"], r["phrase"], r["when"]) for r in d["events"]],
                         [("app#49", "Not merged", "11:20"), ("app#41", "Not merged · stuck", "09:12"),
                          ("site#9", "Not merged · blocked", "Fri 27 Nov 17:03")])
        self.assertNotIn("app#41", [r["label"] for r in d["rows"]])
        self.assertEqual(d["count"], 5)
        f = feed()
        f["recent"][1]["why"] = "the change deletes a test instead of fixing it"
        self.assertEqual(lanes(fleet.view(f, NOW))["done"]["events"][0]["phrase"],
                         "Not merged · the change deletes a test instead of fixing it")

    def test_every_stage_has_its_phrase(self):
        want = [(work("agent", "queued"), "Starting"), (work("agent", "prepare"), "Starting"),
                (work("agent", "agent"), "Writing"), (work("agent", "verify"), "Checking the change"),
                (work("agent", "review"), "Reviewing"), (work("agent", "second_review"), "Second review"),
                (work("agent", "finish"), "Opening the pull request"), (work("agent", None), "Working"),
                (work("checks"), "Checks running"), (work("checks", why="no checks yet; waiting"), "Waiting for checks"),
                (work("review", "queued"), "Reviewing"), (work("review", "review"), "Reviewing"),
                (work("review", "second_review"), "Second review"), (work("review", "finish"), "Reviewing"),
                # a fix run's round is the fleet's to count: the feed's phrase says it, a feed without one doesn't
                (work("fixing", "agent", attempt=2), "Fixing"), (work("fixing", "queued"), "Fixing"),
                (work("fixing", "verify", attempt=3, phrase="Fixing · round 2"), "Fixing · round 2"),
                (work("merging"), "Merging")]
        f = dict(feed(), working=[w for w, _phrase in want])
        v = fleet.view(f, NOW)
        self.assertEqual([r["phrase"] for r in lanes(v)["working"]["rows"]], [phrase for _w, phrase in want])
        self.assertEqual(len(v["warnings"]), 1)                       # the feed's own, nothing about stages

    def test_a_stage_or_outcome_this_version_does_not_know(self):
        f = feed()
        f["working"] = [work("deploying", "ship")]
        f["recent"].append(dict(f["recent"][0], outcome="reverted"))
        v = fleet.view(f, NOW)
        self.assertEqual(lanes(v)["working"]["rows"][0]["phrase"], "Working")
        self.assertIn("1 working task is at a stage this bromigOS doesn't know, shown as Working.", v["warnings"])
        self.assertIn("1 finished task has an outcome this bromigOS doesn't know, and isn't shown.", v["warnings"])
        self.assertEqual(lanes(v)["done"]["count"], 5)

    def test_needs_you_and_waiting_words(self):
        f = feed()
        f["needs_person"] = [dict(f["needs_person"][0], why=None), dict(f["needs_person"][1], kind="paused", why="x")]
        f["waiting"] = [dict(f["waiting"][0], kind="has-pr", why=None), dict(f["waiting"][0], kind="untrusted", why="who?")]
        by = lanes(fleet.view(f, NOW))
        self.assertEqual([r["phrase"] for r in by["needs_you"]["rows"]], ["Stuck", "Needs you · x"])
        self.assertEqual([r["phrase"] for r in by["waiting"]["rows"]], ["Waiting", "Waiting · who?"])
        f["waiting"] = [dict(f["waiting"][0], kind="queued", why=None), dict(f["waiting"][0], kind="ignored")]
        v = fleet.view(f, NOW)
        self.assertEqual([r["phrase"] for r in lanes(v)["waiting"]["rows"]], ["Queued"])
        self.assertEqual(v["ignored"], 1)                             # what the fleet leaves alone is in no lane

    def test_a_feed_that_names_lane_and_phrase_is_shown_as_it_says(self):
        f = feed()
        f["working"][0].update(lane="Working", phrase="Drafting the change")
        f["working"][1].update(lane="needs_you", phrase="Wants a decision")
        f["waiting"][0].update(phrase="Next in line")
        f["needs_person"][0].update(lane="On hold", phrase="Parked until Monday")
        f["proposed"] = [{"repo": "site", "issue": 20, "title": "Add a dark theme", "why": "three people asked",
                          "url": "https://github.com/my-org/site/issues/20",
                          "issue_url": "https://github.com/my-org/site/issues/20", "filed_at": "2026-11-28T10:00:00Z"},
                         {"repo": "app", "issue": 21, "title": "Drop the old API", "phrase": "Suggested by the weekly review",
                          "lane": "proposed"}]
        v = fleet.view(f, NOW)
        by = lanes(v)
        self.assertEqual([lane["title"] for lane in v["lanes"]],
                         ["Needs you", "Proposed", "Working", "Waiting", "Done", "On hold"])
        self.assertEqual([(r["label"], r["phrase"]) for r in by["needs_you"]["rows"]],
                         [("site#9", "Blocked · the task needs a production credential the agents do not hold"),
                          ("app#49", "Wants a decision")])
        self.assertEqual([(r["label"], r["phrase"], r["when"]) for r in by["proposed"]["rows"]],
                         [("site#20", "Proposed", "11:00"), ("app#21", "Suggested by the weekly review", "")])
        self.assertEqual(by["proposed"]["rows"][0]["why"], "three people asked")
        self.assertEqual([(r["label"], r["phrase"]) for r in by["working"]["rows"]],
                         [("app#57", "Drafting the change"), ("site#14", "Checks running")])
        self.assertEqual(by["waiting"]["rows"][0]["phrase"], "Next in line")
        self.assertEqual([(r["label"], r["phrase"]) for r in by["other:on hold"]["rows"]],
                         [("app#41", "Parked until Monday")])
        self.assertEqual(v["headline"], "2 need you · 2 proposed · 2 working · 1 waiting · 4 merged today")
        self.assertIn("PROPOSED (2)", fleet.render_text(v))
        self.assertIn("ON HOLD (1)", fleet.render_text(v))

    def test_unknown_fields_are_ignored(self):
        f = feed()
        f.update(colour="teal", fleet={"size": 3}, heartbeat="often")
        f["working"][0].update(mood="keen", phrase=None)
        f["accounts"][0]["plan"] = "max"
        self.assertEqual(fleet.view(f, NOW), fleet.view(feed(), NOW))

    def test_nothing_needs_you_only_for_a_fresh_feed(self):
        f = dict(feed(), needs_person=[])
        self.assertEqual(fleet.view(f, NOW)["headline"], "Nothing needs you · 3 working · 1 waiting · 4 merged today")
        self.assertEqual(fleet.view(dict(f, working=[], waiting=[], counts={}), NOW)["headline"],
                         "Nothing needs you · 0 working · 0 waiting")
        for v in (fleet.view(f, NOW + timedelta(hours=3)), fleet.view(dict(f, enabled=False), NOW)):
            self.assertNotIn("Nothing needs you", v["headline"])
        one = dict(feed(), needs_person=feed()["needs_person"][:1])
        self.assertTrue(fleet.view(one, NOW)["headline"].startswith("1 needs you · "))

    def test_accounts(self):
        v = fleet.view(feed(), NOW)
        self.assertEqual(v["accounts"], [{"number": 1, "state": "available", "until": None, "phrase": "Available"},
                                         {"number": 2, "state": "resting", "until": "2026-11-28T14:45:00Z",
                                          "phrase": "Resting until 15:45"}])
        f = dict(feed(), accounts=[{"number": 1, "state": "resting", "until": "2026-11-29T06:30:00Z"},
                                   {"number": 2, "state": "resting"}, {"number": 3, "state": "on loan"}, "four"])
        self.assertEqual([a["phrase"] for a in fleet.view(f, NOW)["accounts"]],
                         ["Resting until Sun 29 Nov 07:30", "Resting", "Unknown"])

    def test_times_follow_the_feeds_time_zone(self):
        f = dict(feed(), timezone="America/New_York")
        v = fleet.view(f, NOW)
        self.assertEqual((v["updated"], v["accounts"][1]["phrase"]), ("06:40", "Resting until 09:45"))
        odd = fleet.view(dict(feed(), timezone="Mars/Olympus"), NOW)
        self.assertEqual((odd["timezone"], odd["updated"]), ("UTC", "11:40"))
        self.assertTrue(any("time zone (Mars/Olympus)" in w for w in odd["warnings"]))

    def test_what_the_feed_left_out_for_room_still_counts(self):
        f = dict(feed(), omitted={"working": 4, "waiting": 0, "needs_person": 1, "recent": 0, "warnings": 2})
        v = fleet.view(f, NOW)
        self.assertEqual(v["headline"], "3 need you · 7 working · 1 waiting · 4 merged today")
        self.assertEqual((lanes(v)["working"]["count"], lanes(v)["working"]["omitted"]), (7, 4))
        self.assertIn("and 2 more warnings the feed left out", v["warnings"])
        self.assertIn("+4 more the feed left out for room", fleet.render_text(v))

    def test_a_missing_field_is_named_and_nothing_crashes(self):
        whole = feed()
        for key in ("generated_at", "stale_after", "business", "enabled", "timezone", "accounts", "working", "waiting",
                    "needs_person", "recent", "counts", "warnings", "omitted", "control_repo", "tick_url", "schedules"):
            for broken in ({k: v for k, v in whole.items() if k != key}, dict(whole, **{key: None}),
                           dict(whole, **{key: 7}), dict(whole, **{key: ["x", 3, None]}), dict(whole, **{key: {"a": [1]}})):
                v = fleet.view(broken, NOW)
                text = fleet.render_text(v)
                self.assertTrue(text.startswith(v["business"].upper()), key)
                card = fleet.card({"ok": True, "errors": {}, "items": [{"kind": "fleet", "name": v["business"], "view": v}]})
                self.assertTrue(card["items"][0]["hint"], key)
                json.dumps(v)
        gone = dict(whole)
        del gone["accounts"], gone["counts"]
        v = fleet.view(gone, NOW)
        self.assertIn("The feed is missing accounts, counts: what they would show is left out.", v["warnings"])
        self.assertEqual((v["accounts"], v["counts"]["today"]["merged"]), ([], None))
        self.assertEqual(v["headline"], "2 need you · 3 working · 1 waiting")
        only = fleet.view({"schema": 1}, NOW)
        self.assertEqual((only["business"], only["state"], only["fresh"]), ("?", "stale", False))
        self.assertTrue(only["warnings"][-1].startswith("The feed is missing generated_at, stale_after, business, "))
        self.assertIn("doesn't say when it was written", fleet.render_text(only))

    def test_entries_in_no_known_shape_are_left_out(self):
        f = feed()
        f["working"] += ["a string", 5, None, {"repo": None, "issue": "seven", "stage": "agent"}]
        f["recent"] += [[1, 2]]
        v = fleet.view(f, NOW)
        self.assertEqual([r["label"] for r in lanes(v)["working"]["rows"]], ["app#57", "app#49", "site#14", "?"])
        self.assertIn("4 entries in the feed are not in a shape this bromigOS knows, and aren't shown.", v["warnings"])


class HostileTextTest(unittest.TestCase):
    """Titles and reasons are text other people wrote: one line, no control or invisible
    characters, no escape sequence, capped; never markup."""

    TITLES = {
        "colour": "\x1b[31mURGENT\x1b[0m merge me \x1b[2J\x1b[H",
        "hyperlink": "see \x1b]8;;https://evil.example\x07this\x1b]8;;\x07 and \x1b]0;pwned\x1b\\the title",
        "newlines": "line one\nline two\r\n\tline three\x0b\x0cline four\u2028five\u2029six",
        "bidi": "user \u202egnp.exe\u202c and \u2066isolated\u2069 \u200fmark\u061c",
        "invisible": "ze\u200bro\u200d wid\ufeffth\u00ad \U000e0041tag\U000e007f \x00nul\x7f \x9b31m c1",
        "surrogate": "half \ud83d of a pair \udc00",
        "long": "A" * 20000 + " the end",
        "markup": "[bold red]not bold[/] <b>not bold</b> **not bold** `code` [link=https://evil.example]x[/link]",
    }

    def hostile(self):
        f = feed()
        f["working"] = [work("agent", "agent", issue=n + 1, title=t) for n, t in enumerate(self.TITLES.values())]
        f["needs_person"] = [dict(f["needs_person"][0], why="because \x1b[5mblink\x1b[0m\nand\u202e more " + "w" * 900,
                                  title="\x1b]2;title\x07stuck")]
        f["waiting"] = [dict(f["waiting"][0], why="wait\x07ing\x1b[1A", title=None)]
        f["warnings"] = ["a warning\nwith \x1b[31mcolour\x1b[0m and \u202ebidi", "w" * 5000]
        f["business"] = "Ex\x1b[31mample\nInc\u202e"
        f["accounts"] = [{"number": 1, "state": "resting\x1b[31m", "until": None}]
        f["working"][0].update(phrase="Typing \x1b[31mfast\x1b[0m\n" + "!" * 900, lane="Side\x1b[31m quest\n")
        f["working"][1].update(repo="app\x1b[31m", url="javascript:alert(1)", issue_url="https://evil.example/x y",
                               run_url="https://github.com/my-org/agents/actions/runs/1\x1b[31m")
        return f

    def test_clean(self):
        c = fleet.clean
        self.assertEqual(c(self.TITLES["colour"]), "URGENT merge me")
        self.assertEqual(c(self.TITLES["hyperlink"]), "see this and the title")
        self.assertEqual(c(self.TITLES["newlines"]), "line one line two line three line four five six")
        self.assertEqual(c(self.TITLES["bidi"]), "user gnp.exe and isolated mark")
        self.assertEqual(c(self.TITLES["invisible"]), "zero width tag nul c1")
        self.assertEqual(c(self.TITLES["surrogate"]), "half of a pair")
        self.assertEqual(c(self.TITLES["markup"]), self.TITLES["markup"])           # kept as text, never read
        long = c(self.TITLES["long"], 160)
        self.assertEqual((len(long), long[-1], long[:5]), (160, "…", "AAAAA"))
        self.assertEqual([c(x) for x in (None, "", "   \n ", {"a": 1}, ["x"], True, 12)], ["", "", "", "", "", "", "12"])
        self.assertEqual(c("an unterminated \x1b]0;title that never ends"), "an unterminated")
        self.assertEqual(c("x" * 300, 10), "x" * 9 + "…")

    def test_the_view_the_text_and_the_card_carry_none_of_it(self):
        v = fleet.view(self.hostile(), NOW)
        rows = {r["label"]: r for lane in v["lanes"] for r in lane["rows"]}
        self.assertEqual(rows["app#3"]["title"], "line one line two line three line four five six")
        self.assertEqual(rows["app#8"]["title"], self.TITLES["markup"])
        self.assertLessEqual(max(len(r["title"]) for r in rows.values()), 160)
        self.assertLessEqual(max(len(r["phrase"]) for r in rows.values()), 300)
        self.assertEqual(rows["app#1"]["phrase"][:11], "Typing fast")
        self.assertEqual(v["lanes"][-1]["title"], "Side quest")
        self.assertEqual((v["business"], v["accounts"][0]["phrase"]), ("Example Inc", "Unknown"))
        odd = next(r for r in rows.values() if r["number"] == 2)
        self.assertEqual((odd["label"], odd["url"], odd["links"]), ("app#2", "", []))    # no address that isn't a plain one
        self.assertLessEqual(max(len(w) for w in v["warnings"]), 300)
        card = fleet.card({"ok": True, "errors": {}, "items": [{"kind": "fleet", "name": v["business"], "view": v}]})
        everything = [json.dumps(v, ensure_ascii=False), json.dumps(card, ensure_ascii=False),
                      fleet.render_text(v), fleet.render_text(v, 60, everything=True)]
        for text in everything:
            self.assertIsNone(UNSAFE.search(text.replace("\n", "")), repr(UNSAFE.search(text.replace("\n", ""))))
            self.assertNotIn("\x1b", text)
            text.encode("utf-8")                                                          # printable: no lone surrogate
        for cell in (i[k] for i in card["items"] for k in ("task", "phrase", "title", "since", "hint")):
            self.assertNotIn("\n", cell)
        plain = fleet.render_text(v)
        self.assertLessEqual(max(len(line) for line in plain.splitlines() if "https://" not in line), 80)
        self.assertEqual(plain.splitlines()[0], "EXAMPLE INC · 1 needs you · 7 working · 1 waiting · 4 merged today")

    def test_the_command_prints_none_of_it(self):
        with labfake.Lab(SOURCE), mock.patch.object(fleet, "read_github", lambda repo, label: self.hostile()):
            fleet.forget()
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = fleet.main(["--all"])
            card = console.card(console.status(), "tasks")
        self.assertEqual(code, 1)
        self.assertIsNone(UNSAFE.search(out.getvalue().replace("\n", "")))
        self.assertIsNone(UNSAFE.search(json.dumps(card, ensure_ascii=False)))

    @unittest.skipIf(textual is None, "python-textual isn't installed")
    def test_the_dashboard_shows_markup_as_text(self):
        v = fleet.view(self.hostile(), NOW)
        card = console.finish(dict(fleet.card({"ok": True, "errors": {}, "items": [{"kind": "fleet", "name": "x", "view": v}]}),
                                   id="tasks", title="Tasks", order=125, hint=fleet.HINT))
        fx = test_lab_tui.Fixture()
        fx._status = dict(fx._status, cards=[card], state="warn")
        seen = {}

        async def go():
            app = tui.LabApp(source=fx, clock=lambda: test_lab_tui.T0, interval=3600)
            async with app.run_test(size=(150, 46)) as pilot:
                await pilot.pause(0.3)
                app.show_card("tasks")
                await pilot.pause(0.1)
                t = app.query_one("#detail", tui.HintTable)
                seen["cells"] = [c for n in range(t.row_count) for c in t.get_row_at(n)[1:]]
                t.watch_hover_coordinate(t.hover_coordinate, t.cursor_coordinate)
                seen["tooltip"] = t.tooltip
        asyncio.run(go())
        titles = [c.plain for c in seen["cells"]]
        self.assertIn(self.TITLES["markup"], titles)                  # the brackets are on screen, as written
        self.assertTrue(all(not c.spans for c in seen["cells"]), "no cell was read as markup")
        self.assertFalse(isinstance(seen["tooltip"], str), "a row's hover hint is shown as text, not read as markup")


class GitHubTest(unittest.TestCase):
    def setUp(self):
        fleet.forget()

    def status(self, body=BODY, user=BOT, **more):
        return dict({"number": 12, "title": "Status", "user": user, "body": body}, **more)

    def test_reads_the_status_issue_through_gh(self):
        second_page = json.dumps([{"number": 40, "title": "Status of the release", "user": BOT, "body": "words"},
                                  self.status()])
        with GH(done(issues() + "\n" + second_page)) as gh:
            f = fleet.read_github("my-org/agents")
        self.assertEqual(f["business"], "Example")
        (argv, kw), = gh.calls
        self.assertEqual(argv, ["/usr/bin/gh", "api", "--paginate",
                                "repos/my-org/agents/issues?labels=agent-state&state=all&per_page=100"])
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)
        self.assertEqual(kw["env"]["GH_PROMPT_DISABLED"], "1")            # gh never stops to ask
        # the login is gh's own: nothing here adds or names a token
        self.assertEqual({k: v for k, v in kw["env"].items() if k not in os.environ},
                         {"GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1"})
        with GH(done(issues(self.status()))) as gh:
            fleet.read_github("my-org/agents", label="fleet-state")
        self.assertIn("labels=fleet-state&", gh.calls[0][0][3])

    def test_says_what_is_wrong_in_plain_words(self):
        def fails(answer, **kw):
            with GH(answer), self.assertRaises(fleet.ReadError) as e:
                fleet.read_github("my-org/agents", **kw)
            return e.exception.kind, str(e.exception)
        with mock.patch.object(fleet.shutil, "which", lambda *a, **k: None), self.assertRaises(fleet.ReadError) as e:
            fleet.read_github("my-org/agents")
        self.assertEqual((e.exception.kind, str(e.exception)),
                         ("no-gh", "gh, GitHub's command, isn't installed: install github-cli, then run gh auth login"))
        signed_out = "To get started with GitHub CLI, please run:  gh auth login\nAlternatively, populate the GH_TOKEN"
        self.assertEqual(fails(done(stderr=signed_out, code=4)),
                         ("signed-out", "gh isn't signed in to GitHub: run gh auth login"))
        self.assertEqual(fails(done(stderr="gh: Bad credentials (HTTP 401)", code=1))[0], "signed-out")
        for said in ("gh: Not Found (HTTP 404)", "gh: Resource not accessible by personal access token (HTTP 403)"):
            self.assertEqual(fails(done(stderr=said, code=1)),
                             ("no-access", "your gh login can't read my-org/agents, or it doesn't exist: gh auth status "
                                           "says who you are signed in as"))
        self.assertEqual(fails(done(stderr="gh: API rate limit exceeded for user ID 1. (HTTP 403)", code=1))[0], "failed")
        self.assertEqual(fails(done(issues())),
                         ("no-issue", "my-org/agents has no Status issue yet: the fleet's job writes it on its first run"))
        self.assertEqual(fails(done("[]"))[0], "no-issue")
        kind, words = fails(done(issues(self.status(user={"login": "someone"}))))
        self.assertEqual(kind, "no-issue")
        self.assertIn("the fleet's job didn't open it", words)
        kind, words = fails(done(issues(self.status(body=BODY + "\n" + BODY))))
        self.assertEqual(kind, "bad-feed")
        self.assertIn("the Status issue (#12) of my-org/agents holds no feed to read: the body must hold exactly one",
                      words)
        kind, words = fails(done(issues(self.status(body=BODY.replace('"schema":1,', '"schema":2,')))))
        self.assertIn("is schema 2 and this bromigOS reads schema 1", words)
        self.assertEqual(fails(done(issues(self.status(body=None))))[0], "bad-feed")
        self.assertEqual(fails(done("<html>a proxy's page</html>")), ("failed", "gh didn't answer with JSON"))
        self.assertEqual(fails(subprocess.TimeoutExpired("gh", 30)), ("failed", "gh didn't answer in 30 s"))
        self.assertEqual(fails(OSError("Exec format error"))[0], "failed")
        kind, words = fails(done(stderr="boom \x1b[31mred\x1b[0m\nline two " + "x" * 500, code=1))
        self.assertEqual(kind, "failed")
        self.assertIsNone(UNSAFE.search(words))
        self.assertLess(len(words), 220)

    def test_only_a_repository_name_reaches_gh(self):
        for repo in ("my-org", "my-org/agents/issues", "../x/y", "my-org/..", "my-org/agents?labels=x", "-R/x",
                     "my org/agents", "", None, 7, "my-org/agents\n", "my-org/agents\n--hostname evil.example"):
            with GH(done(issues(self.status()))) as gh, self.assertRaises(fleet.ReadError) as e:
                fleet.read_github(repo)
            self.assertEqual(gh.calls, [], repr(repo))
            self.assertIn("owner/name", str(e.exception))
        with GH(done(issues(self.status()))) as gh, self.assertRaises(fleet.ReadError):
            fleet.read_github("my-org/agents", label="x&state=open")
        self.assertEqual(gh.calls, [])

    def test_one_read_a_minute(self):
        clock, reads = [1000.0], []

        def read():
            reads.append(clock[0])
            return {"n": len(reads)}
        self.assertEqual(fleet.cached("k", read, clock=lambda: clock[0]), {"n": 1})
        for clock[0] in (1015.0, 1030.0, 1045.0, 1059.9):                 # the dashboard's 15 s refresh
            self.assertEqual(fleet.cached("k", read, clock=lambda: clock[0]), {"n": 1})
        clock[0] = 1060.0
        self.assertEqual(fleet.cached("k", read, clock=lambda: clock[0]), {"n": 2})
        self.assertEqual(fleet.cached("other", read, clock=lambda: clock[0]), {"n": 3})
        self.assertEqual(reads, [1000.0, 1060.0, 1060.0])

        failed = []

        def broken():
            failed.append(clock[0])
            raise fleet.ReadError("signed-out", "gh isn't signed in to GitHub: run gh auth login")
        for clock[0] in (2000.0, 2020.0):                                 # a failure is kept as long
            with self.assertRaises(fleet.ReadError) as e:
                fleet.cached("bad", broken, clock=lambda: clock[0])
            self.assertEqual(e.exception.kind, "signed-out")
        self.assertEqual(failed, [2000.0])
        fleet.forget()
        self.assertEqual(fleet.cached("k", read, clock=lambda: clock[0])["n"], 4)

    def test_the_adapter_asks_gh_once_however_often_it_is_read(self):
        a = labfleet.Fleet({"name": "tasks", "type": "fleet", "repo": "my-org/agents"})
        with GH(done(issues(self.status()))) as gh:
            first = a.tasks()
            for _ in range(5):
                self.assertEqual(len(a.tasks()), len(first))
        self.assertEqual(len(gh.calls), 1)


class WordedFeedTest(unittest.TestCase):
    """A feed that names each task's lane and phrase, the lanes' counts and the headline: shown as
    it says, with nothing mapped again here."""

    def test_the_lanes_the_counts_and_the_headline_are_the_feeds_own(self):
        f = worded()
        v = fleet.view(f, NOW)
        self.assertEqual(v["headline"], f["headline"])
        self.assertEqual(v["headline"], "3 need you · 2 proposed · 3 working · 1 waiting · 4 merged today")
        self.assertEqual([(lane["id"], lane["title"], lane["count"], len(lane["rows"]), len(lane["events"])) for lane in v["lanes"]],
                         [("needs_you", "Needs you", 3, 3, 0), ("proposed", "Proposed", 2, 2, 0), ("working", "Working", 3, 3, 0),
                          ("waiting", "Waiting", 1, 1, 0), ("done", "Done", 5, 5, 3)])
        self.assertEqual((v["driver"], v["ignored"], v["counts"]["needs_you"]), ("heartbeat", 1, 3))
        by = lanes(v)
        # an entry of `waiting` that only its owner can move stands under Needs you, as the feed says
        self.assertEqual([(r["label"], r["phrase"]) for r in by["needs_you"]["rows"]],
                         [("app#41", "Stuck · 3 fix rounds and a clean restart did not make it green"),
                          ("site#9", "Blocked · the task needs a production credential the agents do not hold"),
                          ("app#60", "Not started · re-apply agent-ready yourself")])
        self.assertEqual([(r["label"], r["phrase"]) for r in by["working"]["rows"]],
                         [("app#57", "Writing"), ("app#49", "Fixing · round 2"), ("site#14", "Checks running")])
        self.assertEqual([(r["label"], r["phrase"], r["when"]) for r in by["proposed"]["rows"]],
                         [("site#20", "Proposed by Weekly review", "Mon 23 Nov 07:04"), ("app#21", "Proposed", "Fri 20 Nov 10:15")])
        self.assertEqual([(r["label"], r["phrase"]) for r in by["waiting"]["rows"]], [("site#12", "Queued · no Claude account is free")])
        # what the fleet leaves alone is counted and shown in no lane
        self.assertNotIn("site#3", [r["label"] for lane in v["lanes"] for r in lane["rows"] + lane["events"]])
        self.assertEqual([(r["label"], r["phrase"]) for r in by["done"]["events"]],
                         [("app#49", "Not merged · the reviewer asked for changes"),
                          ("app#41", "Not merged · 3 fix rounds and a clean restart did not make it green"),
                          ("site#9", "Not merged · the task needs a production credential the agents do not hold")])
        self.assertEqual([r["phrase"] for r in by["done"]["rows"]], ["Merged"] * 5)
        json.dumps(v)

    def test_a_reason_is_said_once(self):
        by = lanes(fleet.view(worded(), NOW))
        self.assertEqual([r["why"] for r in by["needs_you"]["rows"]],
                         ["", "", "the start label was applied by someone whose labelling does not count"])
        self.assertEqual(by["waiting"]["rows"][0]["why"], "ready; no Claude account is free for it (2 resting)")
        self.assertEqual(by["working"]["rows"][2]["why"], "waiting for 2 check(s): build, test")
        self.assertEqual([r["why"] for r in by["done"]["events"]], ["", "", ""])
        text = fleet.render_text(fleet.view(worded(), NOW), everything=True)
        self.assertEqual(text.count("3 fix rounds and a clean restart did not make it green"), 2)      # the task, and its event

    def test_new_wording_and_new_titles_are_shown_as_given(self):
        f = worded()
        f["working"][0]["phrase"] = "Drafting the change"
        f["waiting"][0].update(lane="needs_you", phrase="Ready to merge · mark the draft ready for review")
        f["lanes"][0]["title"] = "Wants you"
        f["headline"] = "4 want you · 3 working"
        v = fleet.view(f, NOW)
        by = lanes(v)
        self.assertEqual((v["headline"], by["needs_you"]["title"]), ("4 want you · 3 working", "Wants you"))
        self.assertEqual(by["working"]["rows"][0]["phrase"], "Drafting the change")
        self.assertEqual([(r["label"], r["phrase"]) for r in by["needs_you"]["rows"]][2],
                         ("site#12", "Ready to merge · mark the draft ready for review"))
        self.assertEqual((len(by["needs_you"]["rows"]), by["waiting"]["rows"]), (4, []))
        self.assertIn("WANTS YOU (4)", fleet.render_text(v))
        # the feed's sentence is for a fresh feed only, and is text like any other
        self.assertEqual(fleet.view(f, NOW + timedelta(hours=3))["headline"], "No update for 3 h 11 min")
        self.assertEqual(fleet.view(dict(f, enabled=False), NOW)["headline"], "SWITCHED OFF")
        hostile = fleet.view(dict(f, headline="2 need you\x1b[31m\nnow\u202e " + "!" * 900), NOW)["headline"]
        self.assertEqual((hostile[:14], len(hostile)), ("2 need you now", 200))
        self.assertIsNone(UNSAFE.search(hostile))

    def test_a_feed_without_those_words_gets_the_same_lanes_from_its_lists(self):
        f = worded()
        for key in ("headline", "lanes", "ignored", "driver"):
            del f[key]
        for key in ("working", "waiting", "needs_person", "proposed", "recent"):
            for e in f[key]:
                del e["lane"], e["phrase"]
        v = fleet.view(f, NOW)
        by = lanes(v)
        self.assertEqual(v["headline"], "2 need you · 2 proposed · 3 working · 2 waiting · 4 merged today")
        self.assertEqual([r["phrase"] for r in by["working"]["rows"]], ["Writing", "Fixing", "Checks running"])
        self.assertEqual([(r["label"], r["phrase"][:9]) for r in by["waiting"]["rows"]],
                         [("site#12", "Queued · "), ("app#60", "Waiting ·")])
        self.assertEqual((v["ignored"], v["driver"]), (1, None))
        self.assertEqual([r["phrase"] for r in by["proposed"]["rows"]], ["Proposed", "Proposed"])
        self.assertEqual(len(by["done"]["events"]), 3)

    def test_what_ended_says_who_did_it_and_how_long_it_took(self):
        v = fleet.view(worded(), NOW)
        first = lanes(v)["done"]["rows"][0]
        self.assertEqual((first["account"], first["turns"], first["minutes"], first["reviewers"], first["today"]),
                         (2, 31, 12.4, ["gate"], True))
        self.assertEqual([r["today"] for r in lanes(v)["done"]["rows"]], [True, True, True, True, False])
        self.assertEqual(lanes(v)["done"]["rows"][1]["reviewers"], ["gate", "second"])
        self.assertEqual((lanes(v)["done"]["rows"][4]["turns"], lanes(v)["done"]["rows"][4]["reviewers"]), (None, None))
        text = fleet.render_text(v, everything=True)
        self.assertIn("      at 11:58 · account 2 · 31 turns · 12 min · reviewed by gate", text.splitlines())
        self.assertIn("      at 10:41 · account 1 · 18 turns · 6 min · reviewed by gate and second", text.splitlines())
        odd = worded()
        odd["recent"][0].update(turns="many", minutes=True, reviewers=["gate\x1b[31m", 7, "x" * 90, "a", "b", "c"])
        row = lanes(fleet.view(odd, NOW))["done"]["rows"][0]
        self.assertEqual((row["turns"], row["minutes"], row["reviewers"][0], len(row["reviewers"]), len(row["reviewers"][2])),
                         (None, None, "gate", 4, 40))

    def test_schedules(self):
        v = fleet.view(worded(), NOW)
        self.assertEqual(v["schedules"], [{
            "id": "weekly-review", "name": "Weekly review", "when": "mondays 07:00", "next_at": "2026-11-30T06:00:00Z",
            "next": "Mon 30 Nov 07:00", "last_run_at": "2026-11-23T06:00:20Z", "last": "Mon 23 Nov 07:00",
            "last_words": "filed a digest and 1 ticket", "url": "https://github.com/my-org/agents/actions/runs/7000000001",
            "digest_url": "https://github.com/my-org/agents/issues/31",
            "tickets": [{"label": "site#20", "url": "https://github.com/my-org/site/issues/20"}]}])
        lines = fleet.render_text(v, everything=True).splitlines()
        at = lines.index("SCHEDULES")
        self.assertEqual(lines[at + 1:at + 6], [
            "  Weekly review · mondays 07:00 · next Mon 30 Nov 07:00 · last run Mon 23 Nov",
            "      07:00: filed a digest and 1 ticket", "      run: https://github.com/my-org/agents/actions/runs/7000000001",
            "      digest: https://github.com/my-org/agents/issues/31", "      site#20: https://github.com/my-org/site/issues/20"])
        self.assertIn("1 more that the fleet leaves alone isn't shown.", lines)
        old = fleet.view(feed(), NOW)["schedules"][0]                # a feed from before `last_words`: its outcome
        self.assertEqual((old["last_words"], old["tickets"]), ("success", []))
        odd = fleet.view(dict(worded(), schedules=[{"id": "x\x1b[31m", "tickets": [{"repo": "a b", "issue": 1}, 5],
                                                    "last_run_url": "javascript:alert(1)"}, "nope"]), NOW)["schedules"]
        self.assertEqual(odd, [{"id": "x", "name": "", "when": "", "next_at": None, "next": "", "last_run_at": None, "last": "",
                                "last_words": "", "url": "", "digest_url": "", "tickets": [{"label": "a b#1", "url": ""}]}])

    def test_the_card_and_the_document(self):
        v = fleet.view(worded(), NOW)
        card = fleet.card({"ok": True, "errors": {}, "items": [{"kind": "fleet", "name": v["business"], "view": v}]})
        self.assertEqual(card["summary"], "3 need you · 2 proposed · 3 working · 1 waiting · 4 merged today")
        self.assertEqual([(i["task"], i["state"]) for i in card["items"]],
                         [("Example", "ok"), ("app#41", "warn"), ("site#9", "warn"), ("app#60", "warn"), ("site#20", "unknown"),
                          ("app#21", "unknown"), ("app#57", "ok"), ("app#49", "ok"), ("site#14", "ok"), ("+1 more", "unknown")])
        doc = fleet.assemble([dict(v, source="tasks")], {}, True, NOW)
        self.assertEqual({k: doc[k] for k in ("schema", "generatedAt", "configured", "state", "errors")},
                         {"schema": 1, "generatedAt": int(NOW.timestamp()), "configured": True, "state": "warn", "errors": {}})
        self.assertEqual(doc["fleets"][0]["source"], "tasks")
        self.assertEqual(fleet.assemble([], {}, False, NOW)["state"], "empty")
        self.assertEqual(fleet.assemble([], {"tasks": "no"}, True, NOW)["state"], "unreachable")
        quiet = fleet.view(dict(worded(), needs_person=[], waiting=[], lanes=[], headline=None), NOW)
        self.assertEqual(fleet.assemble([quiet], {}, True, NOW)["state"], "ok")


class Mirror:
    """A stand-in for a lab's status mirror: one HTTP server on this machine, answering `answer`
    with an ETag, and 304 to a request that sends that ETag back."""

    def __init__(self, answer, code=200):
        self.answer, self.code, self.seen = answer, code, []

    def __enter__(self):
        mirror = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                mirror.seen.append((self.path, self.headers.get("Authorization"), self.headers.get("Accept")))
                body = mirror.answer if isinstance(mirror.answer, bytes) else json.dumps(mirror.answer).encode()
                tag = '"%08x"' % (hash(body) & 0xffffffff)
                if mirror.code == 200 and self.headers.get("If-None-Match") == tag:
                    self.send_response(304)
                    self.send_header("ETag", tag)
                    self.end_headers()
                    return
                self.send_response(mirror.code)
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


class MirrorTest(unittest.TestCase):
    def setUp(self):
        fleet.forget()

    def answer(self):
        second = dict(feed(), business="Second", needs_person=[], working=[])
        return {"schema": 1, "feeds": [
            {"business": "Example", "received_at": "2026-11-28T11:40:09Z", "feed": feed()},
            {"business": "Second", "received_at": "2026-11-28T11:41:00Z", "feed": second},
            {"business": "Newer", "received_at": "2026-11-28T11:41:30Z", "feed": dict(feed(), schema=2)},
            "not an entry"], "later": "fields are ignored"}

    def test_reads_every_feed_the_mirror_holds(self):
        with Mirror(self.answer()) as m:
            got = fleet.read_url(m.url, headers={"Authorization": "Bearer EXAMPLE"})
        self.assertEqual(m.seen, [("/v1/feed", "Bearer EXAMPLE", "application/json")])
        self.assertEqual([(e["business"], e["received_at"], "feed" in e) for e in got],
                         [("Example", "2026-11-28T11:40:09Z", True), ("Second", "2026-11-28T11:41:00Z", True),
                          ("Newer", "2026-11-28T11:41:30Z", False)])
        self.assertEqual(got[0]["feed"], feed())
        self.assertIn("is schema 2 and this bromigOS reads schema 1", got[2]["error"])
        self.assertEqual(fleet.view(got[1]["feed"], NOW)["headline"],
                         "Nothing needs you · 0 working · 1 waiting · 4 merged today")

    def test_says_what_is_wrong(self):
        def fails(answer, code=200):
            with Mirror(answer, code) as m, self.assertRaises(fleet.ReadError) as e:
                fleet.read_url(m.url)
            return e.exception.kind, str(e.exception)
        self.assertEqual(fails({"error": "no"}, 401)[0], "no-access")
        self.assertEqual(fails({"error": "no"}, 500), ("failed", "the mirror answered HTTP 500"))
        self.assertEqual(fails(b"<html>hello</html>"), ("bad-feed", "the mirror didn't answer with JSON"))
        for wrong in ({"schema": 2, "feeds": []}, {"feeds": []}, {"schema": 1}, {"schema": True, "feeds": []}, [1], feed()):
            self.assertEqual(fails(wrong)[0], "bad-feed", wrong if not isinstance(wrong, dict) else list(wrong))
        with Mirror({}) as m:
            url = m.url
        with self.assertRaises(fleet.ReadError) as e:                 # nothing listens there any more
            fleet.read_url(url, timeout=2)
        self.assertEqual(e.exception.kind, "failed")
        for bad in ("file:///etc/hostname", "ftp://status-mirror.mylab.example/x", "status-mirror.mylab.example", "", None):
            with self.assertRaises(fleet.ReadError) as e:
                fleet.read_url(bad)
            self.assertIn("http:// or https://", str(e.exception))

    def test_an_unchanged_answer_is_not_sent_again(self):
        with Mirror(MIRROR) as m:
            entries, tag = fleet.fetch_url(m.url)
            self.assertEqual(([e["business"] for e in entries], entries[0]["feed"]), (["example"], worded()))
            self.assertRegex(tag, r'^"[0-9a-f]{8}"$')
            self.assertEqual(fleet.fetch_url(m.url, etag=tag), (None, tag))
            m.answer = {"schema": 1, "feeds": []}                     # the mirror restarted: nothing yet, and no error
            self.assertEqual(fleet.fetch_url(m.url, etag=tag)[0], [])
            self.assertEqual(fleet.read_url(m.url), [])
        self.assertEqual(fleet.read_envelope(MIRROR)[0]["received_at"], "2026-11-28T11:40:09Z")

    def test_a_mirror_with_no_report_yet_says_so(self):
        with Mirror({"schema": 1, "feeds": []}) as m:
            a = labfleet.Fleet({"name": "tasks", "type": "fleet", "url": m.url})
            with self.assertRaises(registry.Unreachable) as e:
                a.tasks()
        self.assertIn("no report yet: your lab's status mirror holds no feed until the fleet's next run", str(e.exception))

    def test_a_mirror_source_gives_a_section_per_business(self):
        with Mirror(self.answer()) as m:
            a = labfleet.Fleet({"name": "tasks", "type": "fleet", "url": m.url})
            self.assertTrue(a.configured())
            recs = a.tasks()
            one = labfleet.Fleet({"name": "second", "type": "fleet", "url": m.url, "business": "second"})
            self.assertEqual([r["name"] for r in one.tasks() if r["kind"] == "fleet"], ["Second"])
            none = labfleet.Fleet({"name": "third", "type": "fleet", "url": m.url, "business": "Third"})
            with self.assertRaises(registry.Unreachable) as e:
                none.tasks()
            self.assertIn("the mirror holds no feed for Third", str(e.exception))
        heads = [r for r in recs if r["kind"] == "fleet"]
        self.assertEqual([(r["name"], r["phrase"], r["state"]) for r in heads][::2],
                         [("Example", fleet.view(feed()).get("headline"), "warn"), ("Newer", "Not read", "warn")])
        card = fleet.card({"ok": True, "errors": {}, "items": recs})
        self.assertEqual([i["task"] for i in card["items"] if i["kind"] == "fleet"], ["Example", "Second", "Newer"])
        self.assertIn("Newer: not read", card["summary"])


class CardTest(unittest.TestCase):
    """The Tasks card, through the registry and the console, as bromigos lab status builds it."""

    def setUp(self):
        fleet.forget()
        self._now = mock.patch.object(labfleet, "datetime", mock.Mock(now=lambda tz=None: NOW))
        self._now.start()
        self.addCleanup(self._now.stop)

    def status(self, read, sources=SOURCE):
        fleet.forget()                                                 # each read is a new minute
        with labfake.Lab(sources), mock.patch.object(fleet, "read_github", read):
            return console.status()

    def test_a_fleet_source_provides_tasks(self):
        self.assertIn("tasks", registry.CAPABILITIES)
        self.assertEqual(caps.SCHEMAS["tasks"][:4], ("name", "kind", "business", "lane"))
        self.assertIs(registry.ADAPTERS["fleet"], labfleet.Fleet)
        self.assertEqual((labfleet.Fleet.provides, labfleet.Fleet.local), (("tasks",), True))
        self.assertFalse(labfleet.Fleet({"name": "tasks", "type": "fleet"}).configured())
        with labfake.Lab(SOURCE), mock.patch.object(fleet, "read_github", lambda repo, label: feed()):
            self.assertTrue(H.available("tasks"))
            res = H.tasks()
        self.assertEqual((res["ok"], res["sources"], res["errors"]), (True, ["tasks"], {}))
        head, rest = res["items"][0], res["items"][1:]
        self.assertEqual((head["kind"], head["name"], head["phrase"], head["state"], head["check"], head["source"]),
                         ("fleet", "Example", "2 need you · 3 working · 1 waiting · 4 merged today", "warn", "fresh",
                          "tasks"))
        self.assertEqual(head["view"]["headline"], head["phrase"])
        self.assertEqual([(r["name"], r["lane"], r["state"]) for r in rest][:4],
                         [("app#41", "needs_you", "warn"), ("site#9", "needs_you", "warn"), ("app#57", "working", "ok"),
                          ("app#49", "working", "ok")])
        self.assertEqual(len(rest), 14)
        self.assertEqual(list(rest[0])[:11], list(caps.SCHEMAS["tasks"]))

    def test_the_card_document(self):
        doc = self.status(lambda repo, label: feed())
        c = console.card(doc, "tasks")
        self.assertEqual((c["id"], c["title"], c["order"], c["state"], c["sources"], c["errors"]),
                         ("tasks", "Tasks", 125, "warn", ["tasks"], {}))
        self.assertEqual(c["summary"], "2 need you · 3 working · 1 waiting · 4 merged today")
        self.assertEqual(c["hint"], fleet.HINT)
        self.assertEqual(c["columns"], ["task", "phrase", "title", "since"])
        self.assertEqual([(i["task"], i["phrase"], i["state"]) for i in c["items"]], [
            ("Example", "2 need you · 3 working · 1 waiting · 4 merged today", "ok"),
            ("app#41", "Stuck · 3 fix rounds and a clean restart did not make it green", "warn"),      # needs you first
            ("site#9", "Blocked · the task needs a production credential the agents do not hold", "warn"),
            ("app#57", "Writing", "ok"), ("app#49", "Fixing", "ok"), ("site#14", "Checks running", "ok"),
            ("+1 more", "1 waiting", "unknown")])
        self.assertEqual(c["items"][0]["title"], "updated 12:40 · account 1: Available; account 2: Resting until 15:45")
        self.assertEqual((c["items"][1]["title"], c["items"][1]["since"], c["items"][1]["url"]),
                         ("Checkout: totals are wrong when a coupon is applied", "09:12",
                          "https://github.com/my-org/app/issues/41"))
        for i in c["items"]:                                           # Settings › Lab shows name and hint
            self.assertTrue(i["hint"] and i["name"], i)
            self.assertIn(i["state"], console.ITEM_STATES)
        self.assertIn("app#41: Stuck · 3 fix rounds", c["items"][1]["hint"])
        self.assertIn("bromigos lab tasks lists every task", c["items"][-1]["hint"])
        ids = [x["id"] for x in doc["cards"]]
        self.assertEqual(ids, [x["id"] for x in sorted(doc["cards"], key=lambda x: (x["order"], x["title"]))])
        self.assertEqual(doc["state"], "crit")                         # the recorded lab's own; Tasks adds a warn
        json.dumps(doc)

    def test_it_sits_between_agents_and_ci(self):
        self.assertIs(cards.fleet, fleet)                              # cards.py registers it with fleet.py's words
        orders = {s["id"]: s["order"] for s in console.SPECS.values()}
        self.assertLess(orders["agents"], orders["tasks"])
        self.assertLess(orders["tasks"], orders["ci"])

    def test_nothing_needs_you_reads_ok(self):
        c = console.card(self.status(lambda repo, label: dict(feed(), needs_person=[])), "tasks")
        self.assertEqual((c["state"], c["summary"]), ("ok", "Nothing needs you · 3 working · 1 waiting · 4 merged today"))

    def test_more_tasks_than_the_card_shows(self):
        f = feed()
        f["working"] = [work("agent", "agent", issue=100 + n) for n in range(9)]
        f["omitted"]["working"] = 2
        c = console.card(self.status(lambda repo, label: f), "tasks")
        self.assertEqual([i["task"] for i in c["items"]],
                         ["Example", "app#41", "site#9"] + [f"app#{100 + n}" for n in range(6)] + ["+6 more"])
        self.assertEqual(c["items"][-1]["phrase"], "5 working · 1 waiting")

    def test_stale_and_switched_off(self):
        with mock.patch.object(labfleet, "datetime", mock.Mock(now=lambda tz=None: NOW + timedelta(minutes=88, seconds=3))):
            c = console.card(self.status(lambda repo, label: feed()), "tasks")
        self.assertEqual((c["state"], c["summary"]), ("warn", "No update for 1 h 40 min"))
        self.assertEqual((c["items"][0]["task"], c["items"][0]["state"]), ("Example", "warn"))
        c = console.card(self.status(lambda repo, label: dict(feed(), enabled=False, needs_person=[])), "tasks")
        self.assertEqual((c["state"], c["summary"], c["items"][0]["state"]), ("warn", "SWITCHED OFF", "warn"))

    def test_a_feed_that_cannot_be_read_is_unreachable_never_a_crash(self):
        def read(repo, label):
            raise fleet.ReadError("signed-out", "gh isn't signed in to GitHub: run gh auth login")
        c = console.card(self.status(read), "tasks")
        self.assertEqual((c["state"], c["items"]), ("unreachable", []))
        self.assertEqual(c["errors"], {"tasks": "unreachable: gh isn't signed in to GitHub: run gh auth login"})
        self.assertIn("gh isn't signed in", c["summary"])
        # with no gh at all (the recorded lab has none) the card says so
        with labfake.Lab(SOURCE):
            fleet.forget()
            c = console.card(console.status(), "tasks")
        self.assertEqual(c["state"], "unreachable")
        self.assertIn("gh, GitHub's command, isn't installed", c["errors"]["tasks"])

    def test_one_source_per_business_gives_each_a_section(self):
        two = SOURCE + '[[source]]\nname = "more-tasks"\ntype = "fleet"\nrepo = "my-org/more-agents"\n'

        def read(repo, label):
            return feed() if repo == "my-org/agents" else dict(feed(), business="Second", needs_person=[])
        c = console.card(self.status(read, two), "tasks")
        self.assertEqual(c["sources"], ["tasks", "more-tasks"])
        self.assertEqual(c["summary"], "2 need you · 6 working · 2 waiting · 8 merged today · 2 businesses")
        sections = [(n, i["task"], i["phrase"]) for n, i in enumerate(c["items"]) if i["kind"] == "fleet"]
        self.assertEqual(sections, [(0, "Example", "2 need you · 3 working · 1 waiting · 4 merged today"),
                                    (7, "Second", "Nothing needs you · 3 working · 1 waiting · 4 merged today")])
        self.assertEqual({i["business"] for i in c["items"][8:]}, {"Second"})

        def half(repo, label):                                         # one of the two can't be read
            if repo != "my-org/agents":
                raise fleet.ReadError("no-access", "your gh login can't read my-org/more-agents, or it doesn't exist")
            return dict(feed(), needs_person=[])
        c = console.card(self.status(half, two), "tasks")
        self.assertEqual(c["state"], "warn")
        self.assertTrue(c["summary"].startswith("Example: Nothing needs you · 3 working"))
        self.assertIn("more-tasks unreachable", c["summary"])
        self.assertIn("more-tasks", c["errors"])

    def test_console_hide_patterns_apply(self):
        hide = '[console]\nhide = ["app#4*"]\n\n' + SOURCE
        c = console.card(self.status(lambda repo, label: feed(), hide), "tasks")
        self.assertEqual([i["task"] for i in c["items"]], ["Example", "site#9", "app#57", "site#14", "+1 more"])


class CommandTest(unittest.TestCase):
    """bromigos lab tasks: the plain text, the JSON document and the exit codes."""

    def setUp(self):
        fleet.forget()

    def run_main(self, argv, read=None, sources=SOURCE, now=NOW):
        real = fleet._now
        fleet.forget()
        out, err = io.StringIO(), io.StringIO()
        with labfake.Lab(sources), mock.patch.object(fleet, "read_github", read or (lambda repo, label: feed())), \
                mock.patch.object(fleet, "_now", lambda n=None: real(now if n is None else n)), \
                mock.patch.object(labfleet, "datetime", mock.Mock(now=lambda tz=None: now)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fleet.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_the_plain_text(self):
        code, out, err = self.run_main([])
        if os.environ.get("LAB_TASKS_GOLDEN_UPDATE"):
            with open(GOLDEN, "w") as f:
                f.write(out)
        with open(GOLDEN) as f:
            self.assertEqual(out, f.read())
        self.assertEqual((code, err), (1, ""))                         # two tasks need you
        lines = out.splitlines()
        self.assertEqual(lines[0], "EXAMPLE · 2 need you · 3 working · 1 waiting · 4 merged today")
        self.assertLessEqual(max(len(line) for line in lines), 80)
        heads = [line for line in lines if re.match(r"[A-Z][A-Z ]+( \(|$)", line)]
        self.assertEqual(heads, ["NEEDS YOU (2)", "WORKING (3)", "WAITING (1)", "DONE (4 merged today · 9 in 7 days)",
                                 "SCHEDULES", "WARNINGS"])
        for link in ("https://github.com/my-org/app/issues/41", "PR #44: https://github.com/my-org/app/pull/44",
                     "run: https://github.com/my-org/agents/actions/runs/7000000091"):
            self.assertIn("      " + link, lines)
        self.assertIn("  app#49  Not merged · 11:20 · Search: an empty query returns a server error", lines)
        self.assertIn("  +2 more · bromigos lab tasks --all lists them with their links", lines)

    def test_all_lists_every_finished_task_with_its_links(self):
        code, out, _err = self.run_main(["--all", "--width", "100"])
        self.assertEqual(code, 1)
        self.assertIn("      PR #8: https://github.com/my-org/site/pull/8", out.splitlines())
        self.assertNotIn("more ·", out)

    def test_the_json_document(self):
        code, out, err = self.run_main(["--json"])
        doc = json.loads(out)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual({k: doc[k] for k in ("schema", "configured", "state", "errors", "generatedAt")},
                         {"schema": 1, "configured": True, "state": "warn", "errors": {}, "generatedAt": int(NOW.timestamp())})
        (one,) = doc["fleets"]
        self.assertEqual(one, dict(fleet.view(feed(), NOW), source="tasks"))
        self.assertEqual([lane["id"] for lane in one["lanes"]], ["needs_you", "proposed", "working", "waiting", "done"])

    def test_exit_codes(self):
        quiet = dict(feed(), needs_person=[])
        self.assertEqual(self.run_main([], lambda repo, label: quiet)[0], 0)
        self.assertEqual(self.run_main([], lambda repo, label: quiet, now=NOW + timedelta(hours=4))[0], 1)       # stale
        self.assertEqual(self.run_main([], lambda repo, label: dict(quiet, enabled=False))[0], 1)

        def read(repo, label):
            raise fleet.ReadError("no-issue", f"{repo} has no Status issue yet: the fleet's job writes it on its first run")
        code, out, err = self.run_main([], read)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(" ".join(err.split()),
                         "tasks: my-org/agents has no Status issue yet: the fleet's job writes it on its first run")
        self.assertLessEqual(max(len(line) for line in err.splitlines()), 80)
        code, out, _err = self.run_main(["--json"], read)
        self.assertEqual((code, json.loads(out)["state"], list(json.loads(out)["errors"])), (0, "unreachable", ["tasks"]))
        with self.assertRaises(SystemExit) as e, contextlib.redirect_stderr(io.StringIO()):
            fleet.main(["--nonsense"])
        self.assertEqual(e.exception.code, 2)

    def test_without_a_source_it_says_how_to_add_one(self):
        code, out, _err = self.run_main([], sources="")
        self.assertEqual(code, 0)
        self.assertIn('type = "fleet"', out)
        self.assertIn('repo = "my-org/agents"', out)
        code, out, _err = self.run_main(["--json"], sources="")
        self.assertEqual((code, json.loads(out)["configured"], json.loads(out)["state"]), (0, False, "empty"))

    def test_repo_reads_one_repository_without_a_source(self):
        asked = []

        def read(repo, label):
            asked.append((repo, label))
            return dict(feed(), needs_person=[])
        code, out, _err = self.run_main(["--repo", "my-org/agents"], read, sources="")
        self.assertEqual((code, asked), (0, [("my-org/agents", "agent-state")]))
        self.assertTrue(out.startswith("EXAMPLE · Nothing needs you"))

    def test_several_businesses(self):
        two = SOURCE + '[[source]]\nname = "more-tasks"\ntype = "fleet"\nrepo = "my-org/more-agents"\n'
        code, out, _err = self.run_main([], lambda repo, label: feed() if repo == "my-org/agents" else
                                        dict(feed(), business="Second", needs_person=[]), two)
        self.assertEqual(code, 1)
        self.assertEqual([line for line in out.splitlines() if line.startswith(("EXAMPLE", "SECOND"))],
                         ["EXAMPLE · 2 need you · 3 working · 1 waiting · 4 merged today",
                          "SECOND · Nothing needs you · 3 working · 1 waiting · 4 merged today"])

    def test_the_real_command_with_a_stand_in_gh(self):
        """bin/bromigos-lab tasks and status as a user runs them, with a `gh` on the PATH that answers
        the issues listing from the recorded body."""
        with tempfile.TemporaryDirectory(prefix="bromigos-fleet-") as tmp:
            os.mkdir(os.path.join(tmp, "bin"))
            gh = os.path.join(tmp, "bin", "gh")
            with open(gh, "w") as f:
                f.write(f"#!{sys.executable}\nimport json, sys\n"
                        f"open({os.path.join(tmp, 'asked')!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
                        f"body = open({os.path.join(HERE, 'fixtures', 'fleet-status-body.txt')!r}).read()\n"
                        "print(json.dumps([{'number': 12, 'title': 'Status', 'user': {'login': 'github-actions[bot]'}, "
                        "'body': body}]))\n")
            os.chmod(gh, 0o755)
            cfg = os.path.join(tmp, "homelab.toml")
            with open(cfg, "w") as f:
                f.write(SOURCE)
            env = dict(os.environ, PATH=os.path.join(tmp, "bin") + os.pathsep + os.environ.get("PATH", ""), HOME=tmp,
                       BROMIGOS_HOMELAB_CONFIG=cfg, BROMIGOS_SHARE_DIR=os.path.join(tmp, "share"),
                       BROMIGOS_HOMELAB_PLUGINS=os.path.join(tmp, "plugins"), XDG_DATA_HOME=os.path.join(tmp, "data"),
                       XDG_CONFIG_HOME=os.path.join(tmp, "config"), BROMIGOS_LAB_STATE=os.path.join(tmp, "state"),
                       NO_COLOR="1")

            def lab(*args):
                return subprocess.run([sys.executable, LAB, *args], capture_output=True, text=True, env=env, timeout=60)
            p = lab("tasks", "--json")
            self.assertEqual((p.returncode, p.stderr), (0, ""))
            doc = json.loads(p.stdout)
            self.assertEqual((doc["fleets"][0]["business"], doc["fleets"][0]["source"], doc["state"]),
                             ("Example", "tasks", "warn"))
            self.assertEqual(doc["fleets"][0]["counts"]["needs_you"], 2)
            p = lab("tasks")
            self.assertEqual(p.returncode, 1)
            self.assertTrue(p.stdout.startswith("EXAMPLE · "))
            self.assertIn("NEEDS YOU (2)", p.stdout)
            p = lab("status", "--json")
            card = console.card(json.loads(p.stdout), "tasks")
            self.assertEqual((card["title"], card["order"], card["state"]), ("Tasks", 125, "warn"))
            self.assertEqual([i["task"] for i in card["items"]][1:3], ["app#41", "site#9"])
            with open(os.path.join(tmp, "asked")) as f:
                asked = f.read().splitlines()
            self.assertEqual(set(asked), {"api --paginate repos/my-org/agents/issues?labels=agent-state&state=all&per_page=100"})
            p = lab("help")
            self.assertIn("bromigos-lab tasks [--json]", p.stdout.replace("bromigos lab", "bromigos-lab"))


if __name__ == "__main__":
    unittest.main()
