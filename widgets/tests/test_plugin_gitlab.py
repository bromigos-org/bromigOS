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



class FakeGitLab:
    """A GitLab server on 127.0.0.1 that answers the panel's reads from the fixtures (or
    from `answers`), only for the one token it was given. Records every path it was asked."""

    def __init__(self, token, user, answers=None):
        import http.server
        import threading
        self.token, self.user, self.answers, self.paths = token, user, answers or {}, []
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):                                          # noqa: N802
                fake.paths.append(self.path)
                if self.headers.get("Authorization") != f"Bearer {fake.token}":
                    return self.reply(401, {"message": "401 Unauthorized"})
                path, _, query = self.path.partition("?")
                self.reply(200, fake.answer(path, query))

            def reply(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def answer(self, path, query):
        if path == "/api/v4/user":
            return {"username": self.user}
        if path == "/api/v4/merge_requests":
            return self.answers.get("review" if "reviewer_username" in query else "assigned", [])
        if path == "/api/v4/todos":
            return self.answers.get("todos", [])
        if path == "/api/v4/projects":
            return self.answers.get("projects", [])
        if path.endswith("/pipelines"):
            return self.answers.get("pipelines", [])
        return []

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class TwoAccounts(unittest.TestCase):
    """One GitLab panel showing two accounts on two servers: rows merged, newest first,
    each tagged with its account's label; each account read with its own token."""

    def setUp(self):
        import tempfile
        import bromigos_account as A
        self.A = A
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tempfile.mkdtemp()})
        self.env.start()
        A.KEYRING = A.MemoryKeyring()
        A._cache.clear()
        self.home = FakeGitLab("pub-token", "me", {
            "review": [{"iid": 12, "title": "Docs: a plainer install guide", "web_url": "https://gitlab.example.com/x/12",
                        "references": {"full": "lantern-oss/lantern!12"}, "author": {"username": "kit"},
                        "updated_at": "2026-10-09T21:00:00Z", "head_pipeline": {"status": "success"}}],
            "todos": [{"id": 1, "action_name": "mentioned", "target_type": "Issue", "target": {"iid": 88, "title":
                       "Packaging for Arch"}, "project": {"path_with_namespace": "lantern-oss/lantern"},
                       "author": {"username": "rue"}, "created_at": "2026-10-09T23:00:00Z"}],
            "projects": [{"id": 11, "path_with_namespace": "lantern-oss/lantern", "name": "lantern",
                          "last_activity_at": "2026-10-09T19:00:00Z"}],
            "pipelines": [{"id": 5, "status": "failed", "ref": "main", "updated_at": "2026-10-09T19:00:00Z"}]})
        self.work = FakeGitLab("work-token", "me.work", {
            "review": fixture("gitlab-mrs-review.json"), "assigned": fixture("gitlab-mrs-assigned.json"),
            "todos": fixture("gitlab-todos.json"), "projects": fixture("gitlab-projects.json"),
            "pipelines": fixture("gitlab-pipelines.json")})
        A.configure("gitlab", base=self.home.base, client_id="home-app", label="home")
        A.add_account("gitlab", "work", base=self.work.base, client_id="work-app")
        A.set_token("gitlab", "pub-token", who="me")
        A.set_token("gitlab", "work-token", who="me.work", account="work")

    def tearDown(self):
        self.home.close()
        self.work.close()
        self.env.stop()

    def wait(self, panel):
        for _ in range(200):
            polls = [panel.accts.poller(a) for a in panel.accts.signed_in()]
            if polls and all(p is not None and p.runs and not p.busy for p in polls):
                return
            time.sleep(0.02)
        self.fail("the panel's reads didn't finish")

    def test_rows_merged_and_tagged(self):
        p = PT.make(GL.GitLabPanel)
        self.assertEqual([a.name for a in p.accts.shown()], ["default", "work"])     # every signed-in one
        self.wait(p)
        d = p.feed()
        self.assertEqual([a["label"] for a in d["accounts"]], ["home", "work"])
        self.assertEqual([(m["acct"], m["iid"]) for m in d["mrs"]], [("work", 318), ("home", 12), ("work", 54)])
        self.assertEqual([t["acct"] for t in d["todos"]], ["home", "work", "work"])   # newest first
        self.assertEqual(sorted(d["pipelines"]), ["home/11", "work/11"])               # the same id on two servers
        self.assertEqual(d["pipelines"]["home/11"][0]["status"], "failed")
        self.assertEqual(d["pipelines"]["work/11"][0]["status"], "failed")
        tips = " ".join(PT.draw(p, 960, 640))
        self.assertIn("on work", tips)
        self.assertIn("home (@me on 127.0.0.1) and work (@me.work on 127.0.0.1)", tips)
        # each server saw only its own account's token (a 401 would have left it empty)
        self.assertTrue(any(x.startswith("/api/v4/user") for x in self.home.paths))
        self.assertTrue(any(x.startswith("/api/v4/user") for x in self.work.paths))
        self.assertFalse(p.accts.errors())

    def test_the_setting_picks_which_accounts(self):
        import widget_settings as WS
        p = PT.make(GL.GitLabPanel)
        WS.set_value("gitlab", GL.GitLabPanel.settings, "account", ["work"])
        p.conf.reload()
        p.settings_changed()
        self.assertEqual([a.name for a in p.accts.shown()], ["work"])
        self.wait(p)
        d = p.feed()
        self.assertEqual({m.get("acct") for m in d["mrs"]}, {None})                    # one account: no tags
        self.assertEqual(d["login"], "me.work")
        self.assertEqual(len([x for x in p.pollers if not x.stopped]), 1)               # the other's poller stopped

    def test_a_single_sign_in_draws_as_before(self):
        self.A.remove_account("gitlab", "work")
        p = PT.make(GL.GitLabPanel)
        self.assertEqual([a.name for a in p.accts.shown()], ["default"])
        self.wait(p)
        d = p.feed()
        self.assertEqual([m["iid"] for m in d["mrs"]], [12])
        self.assertNotIn("acct", d["mrs"][0])
        tips = " ".join(PT.draw(p, 460, 320))
        self.assertIn("Your GitLab feed on 127.0.0.1", tips)
        self.assertNotIn(" on home", tips)

    def test_signed_out_shows_the_default_accounts_sign_in(self):
        self.A.sign_out("gitlab")
        self.A.sign_out("gitlab", "work")
        p = PT.make(GL.GitLabPanel)
        self.assertEqual([a.name for a in p.accts.shown()], ["default"])
        tips = " ".join(PT.draw(p, 460, 320))
        self.assertIn("Sign in to GitLab", tips)

    def test_merge_feeds_alone(self):
        one = GL.demo_data(1000.0)
        self.assertNotIn("acct", GL.merge_feeds([("gitlab.com", one)])["mrs"][0])
        two = GL.demo_two(1000.0)
        self.assertEqual({m["acct"] for m in two["mrs"]}, {"gitlab.com", "work"})
        self.assertEqual([m["updated"] for m in two["mrs"]], sorted((m["updated"] for m in two["mrs"]), reverse=True))
        self.assertIsNone(GL.merge_feeds([]))
        PT.every_class(self, PT.make(GL.GitLabPanel, demo=True))
        p = PT.make(GL.GitLabPanel, demo=True)
        p.demo = two
        PT.every_class(self, p)


if __name__ == "__main__":
    unittest.main()
