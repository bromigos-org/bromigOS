"""plugins/ci.py: the one GraphQL query, reading its answer (checks, history, missing
repositories, your pull requests), the repos setting, and the empty states."""
import json
import os
import unittest
from unittest import mock

import plugintest as PT
import ci as C

ANSWER = {"data": {
    "r0": {"nameWithOwner": "o/a", "url": "https://github.com/o/a", "defaultBranchRef": {"name": "main", "target": {
        "oid": "4be1c0a99", "messageHeadline": "fix", "committedDate": "2026-10-09T10:00:00Z", "url": "c",
        "statusCheckRollup": {"state": "FAILURE", "contexts": {"nodes": [
            {"__typename": "CheckRun", "name": "build", "conclusion": "SUCCESS", "status": "COMPLETED", "detailsUrl": "d1"},
            {"__typename": "CheckRun", "name": "test", "conclusion": "FAILURE", "status": "COMPLETED", "detailsUrl": "d2"},
            {"__typename": "CheckRun", "name": "e2e", "conclusion": None, "status": "IN_PROGRESS", "detailsUrl": "d3"},
            {"__typename": "StatusContext", "context": "ci/legacy", "state": "SUCCESS", "targetUrl": "t"}]}},
        "history": {"nodes": [{"statusCheckRollup": {"state": "FAILURE"}}, {"statusCheckRollup": None},
                              {"statusCheckRollup": {"state": "SUCCESS"}}]}}}},
    "r1": None,
    "viewer": {"login": "me"},
    "review": {"issueCount": 1, "nodes": [{"number": 7, "title": "t", "url": "u7", "updatedAt": "2026-10-09T09:00:00Z",
                                            "isDraft": False, "repository": {"nameWithOwner": "o/a"},
                                            "author": {"login": "pal"}}]},
    "mine": {"issueCount": 1, "nodes": [{"number": 9, "title": "m", "url": "u9", "updatedAt": "2026-10-09T08:00:00Z",
                                          "isDraft": True, "repository": {"nameWithOwner": "o/b"}, "author": {"login": "me"},
                                          "reviewDecision": "APPROVED",
                                          "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]}},
                                         {}]}}}


class Parse(unittest.TestCase):
    def test_answer(self):
        d = C.parse(ANSWER, ["o/a", "o/gone"])
        a, gone = d["repos"]
        self.assertEqual((a["state"], a["branch"], a["sha"]), ("fail", "main", "4be1c0a"))
        self.assertEqual([(c["name"], c["state"]) for c in a["checks"]],
                         [("build", "ok"), ("test", "fail"), ("e2e", "pending"), ("ci/legacy", "ok")])
        self.assertEqual(a["history"], ["ok", "none", "fail"])                  # oldest first
        self.assertTrue(gone["missing"])
        self.assertEqual(d["review"][0]["author"], "pal")
        mine, = d["mine"]
        self.assertEqual((mine["checks"], mine["review"], mine["draft"]), ("ok", "APPROVED", True))
        self.assertEqual(d["viewer"], "me")

    def test_query_has_every_repo_and_quotes_names(self):
        q = C.query(["o/a", "x/y.z"])
        self.assertIn('r0: repository(owner: "o", name: "a")', q)
        self.assertIn('r1: repository(owner: "x", name: "y.z")', q)
        self.assertIn("review-requested:@me", q)

    def test_clean_repos(self):
        good, bad = C.clean_repos(["o/a", "https://github.com/o/b/", "o/a", "not a repo", 'x/y") { evil'])
        self.assertEqual(good, ["o/a", "o/b"])
        self.assertEqual(len(bad), 2)


class Fetch(unittest.TestCase):
    def test_partial_errors_still_read(self):
        out = json.dumps(dict(ANSWER, errors=[{"type": "NOT_FOUND"}]))
        with mock.patch.object(C.shutil, "which", lambda n: "/usr/bin/gh"), \
                mock.patch.object(C.subprocess, "run", lambda *a, **k: mock.Mock(returncode=1, stdout=out, stderr="")):
            d = C.fetch(["o/a", "o/gone"])
        self.assertTrue(d["repos"][1]["missing"])

    def test_not_signed_in(self):
        with mock.patch.object(C.shutil, "which", lambda n: "/usr/bin/gh"), \
                mock.patch.object(C.subprocess, "run", lambda *a, **k: mock.Mock(
                    returncode=4, stdout="", stderr="please run:  gh auth login")):
            with self.assertRaises(C.GhError):
                C.fetch([])

    def test_no_gh(self):
        with mock.patch.object(C.shutil, "which", lambda n: None):
            with self.assertRaises(C.GhError) as c:
                C.fetch([])
        self.assertIn("github-cli", str(c.exception))


class Panel(unittest.TestCase):
    def test_every_size_class(self):
        PT.every_class(self, PT.make(C.CiPanel, demo=True))

    def test_no_repos_says_where_to_add_them(self):
        p = PT.make(C.CiPanel, demo=True)
        p.demo = dict(p.demo, repos=[])
        tips = PT.draw(p, 480, 300)
        self.assertTrue(any("ci.toml" in t and "owner/name" in t for t in tips))

    def test_repos_setting_from_its_file(self):
        p = PT.make(C.CiPanel, demo=True)
        os.makedirs(os.path.dirname(p.conf.path), exist_ok=True)
        with open(p.conf.path, "w") as f:
            f.write('repos = ["o/a", "bad entry"]\n')
        p.conf.reload(force=True)
        self.assertEqual(p.repos(), (["o/a"], ["bad entry"]))
        os.remove(p.conf.path)

    def test_errors(self):
        p = PT.make(C.CiPanel, demo=True)
        p.demo = None
        p.poll = mock.Mock(data=None, error="gh isn't signed in: run gh auth login", at=0)
        self.assertTrue(any("gh auth login" in t for t in PT.draw(p, 480, 300)))


if __name__ == "__main__":
    unittest.main()
