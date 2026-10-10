"""plugins/gitlab.py: merge requests (merged, each once), to-dos, projects and pipelines
parsed from GitLab's answers; the token sent as a bearer; the signed-out state; every size class."""
import json
import os
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import plugintest as PT  # noqa: E402
import gitlab as GL  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


class Parse(unittest.TestCase):
    def test_merge_requests_once_review_first(self):
        mrs = GL.merge_mrs(GL.parse_mrs(fixture("gitlab-mrs-review.json"), "review"),
                           GL.parse_mrs(fixture("gitlab-mrs-assigned.json"), "assigned"))
        self.assertEqual([(m["iid"], m["why"]) for m in mrs], [(318, "review"), (54, "assigned")])
        self.assertEqual((mrs[0]["pipeline"], mrs[1]["pipeline"], mrs[1]["conflicts"]), ("running", "failed", True))
        self.assertEqual(mrs[1]["project"], "harbor/tides")
        self.assertIsNotNone(mrs[1]["updated"])                      # fractional seconds parse

    def test_todos(self):
        t = GL.parse_todos(fixture("gitlab-todos.json"))
        self.assertEqual((t[0]["words"], t[0]["ref"]), ("pipeline failed", "!54"))
        self.assertEqual((t[1]["words"], t[1]["ref"], t[1]["url"]),
                         ("addressed you", "#203", "https://gitlab.example.org/harbor/tides/-/issues/203"))

    def test_projects_and_pipelines(self):
        p = GL.parse_projects(fixture("gitlab-projects.json"))
        self.assertEqual([x["path"] for x in p], ["harbor/tides"])
        pl = GL.parse_pipelines(fixture("gitlab-pipelines.json"))
        self.assertEqual([x["status"] for x in pl], ["failed", "waiting_for_resource"])
        self.assertIsNotNone(pl[1]["updated"])                       # created_at when there's no updated_at
        self.assertEqual(GL.status_of("waiting_for_resource")[1], "waiting for a runner")
        self.assertEqual(GL.status_of("brand_new")[1], "brand new")


class Client(unittest.TestCase):
    def test_bearer_and_instance(self):
        seen = {}

        class R:
            def read(self):
                return b'{"username": "you"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout=None):
            seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
            return R()
        c = GL.Client(lambda: "https://git.example.org/", lambda: "glpat-xyz")
        with mock.patch.object(GL.urllib.request, "urlopen", fake):
            self.assertEqual(c.get("/user")["username"], "you")
        self.assertEqual(seen["url"], "https://git.example.org/api/v4/user")
        self.assertEqual(seen["auth"], "Bearer glpat-xyz")

    def test_no_token(self):
        with self.assertRaises(PermissionError):
            GL.Client(lambda: "https://gitlab.com", lambda: None).get("/user")


class Panel(unittest.TestCase):
    def test_signed_out_says_how_to_set_up(self):
        import bromigos_account as A
        A.KEYRING = A.MemoryKeyring()
        A._cache.clear()
        p = PT.make(GL.GitLabPanel)
        tips = " ".join(PT.draw(p, 460, 320))
        self.assertIn("GitLab", tips)
        self.assertTrue("client ID" in tips or "token" in tips, tips)

    def test_every_size_class_draws_with_hints(self):
        PT.every_class(self, PT.make(GL.GitLabPanel, demo=True))


if __name__ == "__main__":
    unittest.main()
