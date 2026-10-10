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
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp})
        self.env.start()
        A.KEYRING = A.MemoryKeyring()
        A._cache.clear()
        A._gh.update(t=time.monotonic(), token=None)          # no gh login in tests

    def tearDown(self):
        self.env.stop()


class Config(Base):
    def test_needs_a_client_id_until_configured(self):
        self.assertEqual(A.needs("gitlab"), ["client_id"])
        A.configure("gitlab", client_id="abc123")
        self.assertEqual(A.needs("gitlab"), [])
        self.assertEqual(A.config("gitlab")["client_id"], "abc123")

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
            A.sign_in("gitlab", on_prompt=lambda d: None)
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


if __name__ == "__main__":
    unittest.main()


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
