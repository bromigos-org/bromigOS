"""lib/bromigos_account.py: accounts.toml, the keyring record, the device flow's polling
(pending, slow_down, expiry, denial), refresh, and PKCE's challenge. No network."""
import base64
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import bromigos_account as A  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp, "XDG_RUNTIME_DIR": self.tmp})
        self.env.start()
        A.KEYRING = A.MemoryKeyring()
        A._cache.clear()
        A._gh.update(t=time.monotonic(), token=None)          # no gh login in tests
        self.net = mock.patch.object(A, "http_json", self.no_network)       # a test that needs a service fakes one
        self.net.start()

    @staticmethod
    def no_network(url, *a, **k):
        raise OSError(f"no network in tests ({url})")

    def tearDown(self):
        self.net.stop()
        self.env.stop()


class Config(Base):
    def test_needs_a_client_id_until_configured(self):
        self.assertEqual(A.needs("spotify"), ["client_id"])
        A.configure("spotify", client_id="abc123")
        self.assertEqual(A.needs("spotify"), [])
        self.assertEqual(A.config("spotify")["client_id"], "abc123")

    def test_gitlab_com_ships_an_app_but_a_self_hosted_gitlab_needs_its_own(self):
        self.assertEqual(A.needs("gitlab"), [])
        A.configure("gitlab", base="https://git.example.org")
        self.assertEqual(A.needs("gitlab"), ["client_id"])
        A.configure("gitlab", client_id="own")
        self.assertEqual(A.config("gitlab")["client_id"], "own")

    def test_twitch_ships_bromigos_app_and_yours_wins(self):
        self.assertEqual(A.needs("twitch"), [])
        self.assertTrue(A.config("twitch")["client_id"])
        A.configure("twitch", client_id="mine")
        self.assertEqual(A.config("twitch")["client_id"], "mine")

    def test_configure_keeps_other_tables_and_base(self):
        A.configure("twitch", client_id="t1")
        A.configure("gitlab", client_id="g1", base="https://git.example.org/")
        self.assertEqual(A.config("twitch")["client_id"], "t1")
        self.assertEqual(A.base("gitlab"), "https://git.example.org")
        self.assertEqual(A.base("github"), "https://github.com")

    def test_status_signed_out(self):
        s = A.status("spotify")
        self.assertEqual((s["signed_in"], s["who"], s["needs"], s["via"]), (False, None, ["client_id"], None))

    def test_sign_in_without_config_raises_needs_config(self):
        with self.assertRaises(A.NeedsConfig) as c:
            A.sign_in("spotify", on_prompt=lambda d: None)
        self.assertEqual(c.exception.fields, ["client_id"])

    def test_fields_describe_the_form(self):
        keys = [f["key"] for f in A.fields("gitlab")]
        self.assertEqual(keys, ["client_id", "base"])

    def test_unknown_provider(self):
        with self.assertRaises(KeyError):
            A.status("myspace")


def http_error(body, code=400):
    e = urllib.error.HTTPError("https://x", code, "Bad Request", {}, None)
    e.body = body
    return e


class DeviceFlow(Base):
    def setUp(self):
        super().setUp()
        A.configure("twitch", client_id="cid")

    def test_pending_then_slow_down_then_token(self):
        answers = [http_error({"status": 400, "message": "authorization_pending"}),
                   {"error": "slow_down"},
                   {"access_token": "tok", "refresh_token": "ref", "expires_in": 3600}]
        sleeps = []

        def fake(url, data=None, **kw):
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        with mock.patch.object(A, "http_json", fake):
            tok = A.device_poll("twitch", {"device_code": "d", "interval": 5, "expires_in": 600}, sleep=sleeps.append)
        self.assertEqual(tok["access_token"], "tok")
        self.assertEqual(sleeps, [5, 5, 10])                       # slow_down adds 5 s

    def test_denied_and_expired(self):
        for word, says in (("access_denied", "declined"), ("expired_token", "expired")):
            with mock.patch.object(A, "http_json", lambda *a, **k: {"error": word}):
                with self.assertRaises(A.SignInError) as c:
                    A.device_poll("twitch", {"device_code": "d", "interval": 1}, sleep=lambda s: None)
                self.assertIn(says, str(c.exception))

    def test_sign_in_stores_the_token_in_the_keyring(self):
        prompts = []

        def fake(url, data=None, headers=None, **kw):
            if url.endswith("/device"):
                return {"device_code": "d", "user_code": "ABCD-EFGH", "verification_uri": "https://www.twitch.tv/activate",
                        "interval": 1, "expires_in": 600}
            if url.endswith("/token"):
                return {"access_token": "tok", "refresh_token": "ref", "expires_in": 3600}
            if url.endswith("/validate"):
                return {"login": "streamer"}
            raise AssertionError(url)
        with mock.patch.object(A, "http_json", fake), mock.patch.object(A.time, "sleep", lambda s: None):
            s = A.sign_in("twitch", prompts.append)
        self.assertEqual(prompts[0]["user_code"], "ABCD-EFGH")
        self.assertEqual((s["signed_in"], s["who"], s["via"]), (True, "streamer", "keyring"))
        rec = json.loads(A.KEYRING.get("bromigos-account:twitch", "default"))
        self.assertEqual((rec["access_token"], rec["refresh_token"]), ("tok", "ref"))
        with open(A.accounts_path()) as f:
            self.assertNotIn("tok", f.read())                    # never in a file

    def test_token_refreshes_when_expired(self):
        A._save("twitch", {"access_token": "old", "refresh_token": "r1", "expires_at": time.time() - 10,
                           "client_id": "cid", "who": "streamer"})
        calls = []

        def fake(url, data=None, **kw):
            calls.append(data)
            return {"access_token": "new", "refresh_token": "r2", "expires_in": 3600}
        with mock.patch.object(A, "http_json", fake):
            self.assertEqual(A.token("twitch"), "new")
        self.assertEqual(calls[0]["grant_type"], "refresh_token")
        self.assertEqual(json.loads(A.KEYRING.get("bromigos-account:twitch", "default"))["refresh_token"], "r2")

    def test_sign_out_forgets(self):
        A.set_token("twitch", "pat", who="me")
        self.assertTrue(A.status("twitch")["signed_in"])
        A.sign_out("twitch")
        self.assertFalse(A.status("twitch")["signed_in"])
        self.assertIsNone(A.token("twitch"))


class Pkce(Base):
    def test_challenge_is_the_verifiers_sha256(self):
        v, c = A.pkce_pair()
        want = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(c, want)
        self.assertGreaterEqual(len(v), 43)

    def test_authorize_url(self):
        A.configure("spotify", client_id="sp")
        url = A.pkce_url("spotify", "chal", "st", "http://127.0.0.1:8898/callback")
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A8898%2Fcallback", url)
        self.assertIn("client_id=sp", url)


class GitHubThroughGh(Base):
    def test_gh_login_counts_as_signed_in(self):
        A._gh.update(t=time.monotonic(), token="gho_fromgh")
        with mock.patch.object(A, "_gh_login", lambda: "octo"):
            s = A.status("github")
            self.assertEqual((s["signed_in"], s["who"], s["via"]), (True, "octo", "gh"))
            self.assertEqual(A.token("github"), "gho_fromgh")
            self.assertEqual(A.needs("github"), [])



class PlexPin(Base):
    """Plex's PIN: a code entered at plex.tv/link, then the account's token. No network."""

    def answers(self, polls):
        calls = []

        def fake(url, data=None, headers=None, method=None, timeout=15, form=True):
            calls.append((method or ("POST" if data is not None else "GET"), url, dict(headers or {})))
            if url == "https://plex.tv/api/v2/pins":
                return {"id": 4242, "code": "AB12", "expiresIn": 900}
            if url == "https://plex.tv/api/v2/pins/4242":
                r = polls.pop(0)
                if isinstance(r, Exception):
                    raise r
                return r
            if url == "https://plex.tv/api/v2/user":
                return {"username": "viewer"}
            if url == "https://plex.tv/api/claim/token.json":
                return {"token": "claim-xyz"}
            raise AssertionError(url)
        return calls, fake

    def test_needs_nothing_and_signs_in_through_plex_tv_link(self):
        self.assertEqual((A.fields("plex"), A.needs("plex")), ([], []))
        calls, fake = self.answers([{"authToken": None}, {"authToken": "plex-account-token"}])
        shown = []
        with mock.patch.object(A, "http_json", fake), mock.patch.object(A.time, "sleep"):
            s = A.sign_in("plex", on_prompt=shown.append)
        self.assertEqual((shown[0]["user_code"], shown[0]["verification_uri"]), ("AB12", "https://plex.tv/link"))
        self.assertEqual((s["signed_in"], s["who"]), (True, "viewer"))
        self.assertEqual(A.token("plex"), "plex-account-token")
        cid = A.config("plex")["client_id"]                   # made once, kept, sent every time
        self.assertTrue(cid)
        self.assertTrue(all(h.get("X-Plex-Client-Identifier") == cid and h.get("X-Plex-Product") == "bromigOS"
                            for _, _, h in calls))
        self.assertEqual(calls[-1][2].get("X-Plex-Token"), "plex-account-token")     # who: Plex's own header

    def test_expired_pin(self):
        gone = urllib.error.HTTPError("https://plex.tv/api/v2/pins/4242", 404, "Not Found", {}, None)
        _, fake = self.answers([gone])
        with mock.patch.object(A, "http_json", fake), mock.patch.object(A.time, "sleep"):
            with self.assertRaises(A.SignInError) as c:
                A.sign_in("plex", on_prompt=lambda d: None)
        self.assertIn("expired", str(c.exception))

    def test_claim_token_for_a_new_server(self):
        _, fake = self.answers([])
        with self.assertRaises(A.SignInError):
            A.plex_claim_token()
        A.set_token("plex", "plex-account-token", who="viewer")
        with mock.patch.object(A, "http_json", fake):
            self.assertEqual(A.plex_claim_token(), "claim-xyz")


class FakeService:
    """A stand-in for an OAuth service's device flow and user endpoint, answering through
    A.http_json: records every call, answers by URL. No network."""

    def __init__(self, **who):
        self.calls, self.who = [], who                  # who: {base: username}

    def __call__(self, url, data=None, headers=None, method=None, timeout=15, form=True):
        self.calls.append((url, dict(data or {}), dict(headers or {})))
        for b, name in self.who.items():
            if not url.startswith(b):
                continue
            tail = url[len(b):]
            if tail in ("/oauth/authorize_device", "/login/device/code"):
                return {"device_code": "dev-" + name, "user_code": "CODE-" + name.upper()[:4],
                        "verification_uri": b + "/activate", "interval": 1, "expires_in": 600}
            if tail in ("/oauth/token", "/login/oauth/access_token"):
                return {"access_token": "tok-" + name, "refresh_token": "ref-" + name, "expires_in": 7200}
            if tail in ("/api/v4/user", "/api/v3/user", "/user"):
                return {"username": name, "login": name}
        raise AssertionError(f"unexpected call: {url}")


class NamedAccounts(Base):
    """Several accounts per service: gitlab.com and a company's own GitLab side by side."""

    def test_an_existing_single_sign_in_keeps_working_untouched(self):
        # what a bromigOS from before named accounts left: [gitlab] and the keyring's "default" item
        os.makedirs(os.path.dirname(A.accounts_path()))
        before = '[twitch]\nclient_id = "mine"\n\n[gitlab]\nbase = "https://git.example.org"\nclient_id = "own-app"\n'
        with open(A.accounts_path(), "w") as f:
            f.write(before)
        rec = {"access_token": "old-token", "who": "pat", "client_id": "own-app", "base": "https://git.example.org"}
        A.KEYRING.set("bromigos-account:gitlab", "default", "bromigOS: GitLab sign-in", json.dumps(rec))
        s = A.status("gitlab")
        self.assertEqual((s["signed_in"], s["who"], s["via"]), (True, "pat", "keyring"))
        self.assertEqual(A.token("gitlab"), "old-token")
        self.assertEqual((A.base("gitlab"), A.config("gitlab")["client_id"]), ("https://git.example.org", "own-app"))
        self.assertEqual([a["name"] for a in A.accounts("gitlab")], ["default"])
        # adding a second account leaves the first one's table and keyring item as they were
        A.add_account("gitlab", "public")
        A.set_token("gitlab", "pub-token", who="me", account="public")
        import tomllib
        with open(A.accounts_path(), "rb") as f:
            doc = tomllib.load(f)
        self.assertEqual({k: v for k, v in doc["gitlab"].items() if k != "accounts"},
                         {"base": "https://git.example.org", "client_id": "own-app"})
        self.assertEqual(doc["twitch"], {"client_id": "mine"})
        self.assertEqual(json.loads(A.KEYRING.get("bromigos-account:gitlab", "default")), rec)
        self.assertEqual((A.token("gitlab"), A.token("gitlab", "public")), ("old-token", "pub-token"))

    def test_two_gitlabs_built_in_app_and_a_self_hosted_one_with_its_own(self):
        A.add_account("gitlab", "work", base="git.example.org/", label="work")
        self.assertEqual(A.base("gitlab", "work"), "https://git.example.org")      # https:// added, / dropped
        self.assertEqual(A.needs("gitlab"), [])                                   # gitlab.com: bromigOS's app
        self.assertEqual(A.needs("gitlab", "work"), ["client_id"])                # its own server: its own app
        with self.assertRaises(A.NeedsConfig) as c:
            A.sign_in("gitlab", on_prompt=lambda d: None, account="work")
        self.assertEqual((c.exception.fields, c.exception.account), (["client_id"], "work"))
        A.configure("gitlab", "work", client_id="work-app")
        svc = FakeService(**{"https://gitlab.com": "me", "https://git.example.org": "me.work"})
        shown = []
        with mock.patch.object(A, "http_json", svc), mock.patch.object(A.time, "sleep", lambda s: None):
            a = A.sign_in("gitlab", shown.append)
            b = A.sign_in("gitlab", shown.append, account="work")
        self.assertEqual((a["who"], b["who"]), ("me", "me.work"))
        self.assertEqual([d["verification_uri"] for d in shown],
                         ["https://gitlab.com/activate", "https://git.example.org/activate"])
        starts = [(u, d["client_id"]) for u, d, _ in svc.calls if u.endswith("/oauth/authorize_device")]
        self.assertEqual(starts, [("https://gitlab.com/oauth/authorize_device", A.PROVIDERS["gitlab"]["client_id"]),
                                  ("https://git.example.org/oauth/authorize_device", "work-app")])
        rows = {r["name"]: r for r in A.accounts("gitlab")}
        self.assertEqual([(n, r["label"], r["who"]) for n, r in rows.items()],
                         [("default", "gitlab.com", "me"), ("work", "work", "me.work")])

    def test_the_built_in_app_rule_is_per_account(self):
        A.add_account("gitlab", "second")                  # gitlab.com too: the built-in app
        A.add_account("gitlab", "work", base="https://git.example.org")
        A.add_account("gitlab", "work2", base="https://git.example.org", client_id="w2")
        builtin = A.PROVIDERS["gitlab"]["client_id"]
        self.assertEqual([A.config("gitlab", n)["client_id"] for n in ("default", "second", "work", "work2")],
                         [builtin, builtin, None, "w2"])
        # the default moving to its own server doesn't take the others with it
        A.configure("gitlab", base="https://code.example.org")
        self.assertEqual([A.config("gitlab", n)["client_id"] for n in ("default", "second", "work2")],
                         [None, builtin, "w2"])

    def test_a_named_account_on_the_same_server_shares_the_defaults_app(self):
        A.configure("spotify", client_id="my-spotify-app", port=8899)
        A.configure("twitch", client_id="my-twitch-app")
        A.add_account("spotify", "family")
        A.add_account("twitch", "alt", label="alt channel")
        self.assertEqual(A.config("spotify", "family")["client_id"], "my-spotify-app")
        self.assertEqual(A.config("spotify", "family")["port"], 8899)
        self.assertEqual(A.config("twitch", "alt")["client_id"], "my-twitch-app")
        self.assertEqual((A.label("twitch"), A.label("twitch", "alt")), ("twitch.tv", "alt channel"))

    def test_github_enterprise(self):
        A._gh.update(t=time.monotonic(), token="gho_fromgh")              # gh covers github.com's default only
        A.add_account("github", "work", base="https://github.example.org", client_id="ghe-app")
        self.assertEqual((A.api("github"), A.api("github", "work")),
                         ("https://api.github.com", "https://github.example.org/api/v3"))
        with mock.patch.object(A, "_gh_login", lambda: "octo"):
            self.assertEqual(A.status("github")["via"], "gh")
            self.assertEqual(A.status("github", "work")["signed_in"], False)
            self.assertIsNone(A.token("github", "work"))
        svc = FakeService(**{"https://github.example.org": "octo-corp"})
        with mock.patch.object(A, "http_json", svc), mock.patch.object(A.time, "sleep", lambda s: None):
            st = A.sign_in("github", lambda d: None, account="work")
        self.assertEqual(st["who"], "octo-corp")
        self.assertEqual([u for u, _, _ in svc.calls], ["https://github.example.org/login/device/code",
                                                        "https://github.example.org/login/oauth/access_token",
                                                        "https://github.example.org/api/v3/user"])

    def test_keyring_slots_stay_separate(self):
        A.add_account("twitch", "alt")
        A.set_token("twitch", "main-token", who="main")
        A.set_token("twitch", "alt-token", who="alt", account="alt")
        self.assertEqual(sorted(A.KEYRING.items), [("bromigos-account:twitch", "alt"),
                                                   ("bromigos-account:twitch", "default")])
        self.assertEqual((A.token("twitch"), A.token("twitch", "alt")), ("main-token", "alt-token"))
        A.sign_out("twitch", "alt")
        self.assertEqual((A.token("twitch"), A.token("twitch", "alt")), ("main-token", None))
        A.set_token("twitch", "alt-token-2", who="alt", account="alt")
        A.remove_account("twitch", "alt")                                   # signs out, then forgets it
        self.assertEqual(list(A.KEYRING.items), [("bromigos-account:twitch", "default")])
        self.assertEqual(A.names("twitch"), ["default"])
        with self.assertRaises(KeyError):
            A.status("twitch", "alt")

    def test_refresh_uses_the_accounts_own_server(self):
        A.add_account("gitlab", "work", base="https://git.example.org", client_id="work-app")
        A._save("gitlab", {"access_token": "old", "refresh_token": "r1", "expires_at": time.time() - 5,
                           "client_id": "work-app", "who": "me.work"}, account="work")
        svc = FakeService(**{"https://git.example.org": "me.work"})
        with mock.patch.object(A, "http_json", svc):
            self.assertEqual(A.token("gitlab", "work"), "tok-me.work")
        self.assertEqual((svc.calls[0][0], svc.calls[0][1]["client_id"]),
                         ("https://git.example.org/oauth/token", "work-app"))
        self.assertIsNone(A.KEYRING.get("bromigos-account:gitlab", "default"))

    def test_names_are_checked(self):
        for bad in ("", "Work", "default", "a b", "x" * 40, "../etc"):
            with self.assertRaises(ValueError, msg=bad):
                A.add_account("gitlab", bad)
        A.add_account("gitlab", "work")
        with self.assertRaises(ValueError):
            A.add_account("gitlab", "work")                                    # once
        with self.assertRaises(ValueError):
            A.add_account("twitch", "alt", base="https://twitch.example.org")  # Twitch has no servers of its own
        with self.assertRaises(ValueError):
            A.remove_account("gitlab", "default")
        with self.assertRaises(KeyError):
            A.configure("gitlab", "nobody", client_id="x")


class CommandLine(Base):
    """bin/bromigos-account (`bromigos account …`): main() with the memory keyring."""

    def run_cli(self, *argv, stdin=None):
        import io
        out, err = io.StringIO(), io.StringIO()
        fake_in = io.StringIO(stdin or "")
        fake_in.isatty = lambda: False
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err), \
                mock.patch.object(sys, "stdin", fake_in):
            code = A.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_add_list_configure_status_remove(self):
        code, out, _ = self.run_cli("add", "gitlab", "work", "base=https://git.example.org", "label=work")
        self.assertEqual(code, 0)
        self.assertIn("needs client_id", out)
        self.assertIn("bromigos account configure gitlab --as work client_id=", out)
        self.assertEqual(self.run_cli("configure", "gitlab", "--as", "work", "client_id=work-app")[0], 0)
        self.assertEqual(A.config("gitlab", "work")["client_id"], "work-app")
        code, out, _ = self.run_cli("set-token", "gitlab", "--as=work", stdin="glpat-secret\n")
        self.assertEqual(code, 0)
        self.assertNotIn("glpat-secret", out)                               # a token is never printed
        self.assertEqual(A.token("gitlab", "work"), "glpat-secret")
        code, out, _ = self.run_cli("list", "gitlab", "--json")
        rows = json.loads(out)
        self.assertEqual([(r["name"], r["label"], r["signed_in"]) for r in rows],
                         [("default", "gitlab.com", False), ("work", "work", True)])
        code, out, _ = self.run_cli("list")
        self.assertIn("git.example.org", out)
        self.assertIn("Twitch", out)
        code, out, _ = self.run_cli("status", "gitlab", "--as", "work")
        self.assertTrue(json.loads(out)["signed_in"])
        code, out, _ = self.run_cli("status", "gitlab")                     # the default, as before
        self.assertEqual(json.loads(out), {"signed_in": False, "who": None, "needs": [], "via": None})
        # remove asks first; with no terminal to ask on, it wants --yes
        code, _, err = self.run_cli("remove", "gitlab", "work")
        self.assertEqual(code, 1)
        self.assertIn("--yes", err)
        self.assertEqual(A.token("gitlab", "work"), "glpat-secret")
        self.assertEqual(self.run_cli("remove", "gitlab", "work", "--yes")[0], 0)
        self.assertEqual(A.names("gitlab"), ["default"])
        self.assertIsNone(A.KEYRING.get("bromigos-account:gitlab", "work"))
        code, _, err = self.run_cli("remove", "gitlab", "default", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("logout", err)

    def test_remove_asks_on_a_terminal(self):
        A.add_account("twitch", "alt")
        import builtins
        import io
        for answer, code_, left in (("n", 1, ["default", "alt"]), ("y", 0, ["default"])):
            asked = []
            tty = io.StringIO()
            tty.isatty = lambda: True
            with mock.patch.object(sys, "stdin", tty), mock.patch.object(sys, "stdout", io.StringIO()), \
                    mock.patch.object(builtins, "input", lambda q, a=answer: asked.append(q) or a):
                code = A.main(["remove", "twitch", "alt"])
            self.assertEqual((code, A.names("twitch")), (code_, left))
            self.assertIn("Remove the Twitch account alt?", asked[0])

    def test_login_as_a_named_account(self):
        A.add_account("gitlab", "work", base="https://git.example.org", client_id="work-app")
        svc = FakeService(**{"https://git.example.org": "me.work"})
        with mock.patch.object(A, "http_json", svc), mock.patch.object(A.time, "sleep", lambda s: None), \
                mock.patch.object(A, "_default_prompt", lambda p, a="default": (lambda d: None)):
            code, out, _ = self.run_cli("login", "gitlab", "--as", "work")
        self.assertEqual(code, 0)
        self.assertIn("Go to https://git.example.org/activate and enter CODE-ME.W", out)
        self.assertIn("signed in to GitLab (work) as me.work", out)
        self.assertEqual(self.run_cli("logout", "gitlab", "--as", "work")[1], "signed out of GitLab (work)\n")
        code, _, err = self.run_cli("login", "gitlab", "--as", "nobody")
        self.assertEqual(code, 1)
        self.assertIn("bromigos account add gitlab nobody", err)


if __name__ == "__main__":
    unittest.main()
