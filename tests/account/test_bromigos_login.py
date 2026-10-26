"""Signing in to a Bromigos account (lib/bromigos_login.py, `bromigos login`, `logout`,
`whoami`) against a stand-in service on 127.0.0.1 (mockaccount.py).

The keyring is bromigos_account's memory keyring, HOME is a temporary folder, and SSH keys
are throwaway ones made here with ssh-keygen. An ssh-agent of the test's own is started on a
socket in a temporary folder. Nothing opens a window: the browser is a stand-in.

    PYTHONPATH=lib python -m unittest discover -s tests/account
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)
import bromigos_account as A  # noqa: E402
import bromigos_login as L  # noqa: E402
import mockaccount  # noqa: E402

HAVE_SSH = bool(shutil.which("ssh-keygen") and shutil.which("ssh-agent") and shutil.which("ssh-add"))
CLEAN = ("DISPLAY", "WAYLAND_DISPLAY", "SSH_AUTH_SOCK", "SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "BROMIGOS_TOKEN",
         "BROMIGOS_AUTH_URL", "BROMIGOS_ACCOUNT_URL", "BROMIGOS_CLIENT_ID", "BROMIGOS_SCOPES", "SSH_ASKPASS")


class Pipe(io.StringIO):
    def __init__(self, text="", tty=False):
        super().__init__(text)
        self.tty = tty

    def isatty(self):
        return self.tty


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bromigos-login-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".ssh"), mode=0o700)
        self.srv = mockaccount.Server().__enter__()
        self.addCleanup(self.srv.__exit__, None, None, None)
        self.acct = self.srv.account
        env = {k: v for k, v in os.environ.items() if k not in CLEAN}
        env.update(HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.tmp, "config"),
                   XDG_RUNTIME_DIR=os.path.join(self.tmp, "run"),
                   BROMIGOS_AUTH_URL=self.srv.issuer, BROMIGOS_ACCOUNT_URL=self.srv.base)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        A.KEYRING = A.MemoryKeyring()
        A._cache.clear()
        A._discovered.clear()
        browser = mock.patch.object(L, "open_browser", self.no_browser)
        browser.start()
        self.addCleanup(browser.stop)
        self.opened = []

    def no_browser(self, url):
        raise AssertionError("a test opened the real browser: " + url)

    def record(self):
        raw = A.KEYRING.get("bromigos-account:bromigos", "default")
        return json.loads(raw) if raw else None

    def cli(self, verb, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err), \
                mock.patch.object(sys, "stdin", stdin or Pipe()):
            code = L.main(verb, list(argv))
        return code, out.getvalue(), err.getvalue()

    def keygen(self, name, kind="ed25519", folder=None):
        """A throwaway key pair with no passphrase: (private path, public key line)."""
        path = os.path.join(folder or os.path.join(self.home, ".ssh"), name)
        subprocess.run(["ssh-keygen", "-q", "-t", kind, "-N", "", "-C", f"{name}@example.org", "-f", path],
                       check=True, stdin=subprocess.DEVNULL)
        with open(path + ".pub") as f:
            return path, f.read().strip()


class DeviceFlow(Base):
    def test_login_prints_the_page_and_code_then_stores_the_sign_in(self):
        self.acct.auto_approve_after = 3                 # the person approves on the website
        code, out, err = self.cli("login")
        self.assertEqual(code, 0, err)
        self.assertIn(f"    {self.srv.base}/device\n", out)
        self.assertRegex(out, r"and enter this code:\n    WDJB-[0-9A-F]{4}\n")
        self.assertIn("Waiting for you to approve it", out)
        self.assertNotIn("Press Enter to open it", out)  # no desktop session here: it only prints
        self.assertIn("Signed in to your Bromigos account as tester (tester@example.org)", out)
        rec = self.record()
        self.assertEqual(rec["how"], "device")
        self.assertTrue(rec["access_token"].startswith("acc-") and rec["refresh_token"] == self.acct.refresh)
        self.assertNotIn(rec["access_token"], out + err)            # a token is never printed
        self.assertNotIn(rec["refresh_token"], out + err)
        # discovery's endpoints, bromigOS's public client and every default scope
        self.assertIn(("GET", "/auth/.well-known/openid-configuration"), self.acct.requests)
        self.assertIn(("POST", "/auth/device/code"), self.acct.requests)
        scope = rec["scope"].split()
        for s in ("openid", "offline_access", "profile", "email", "lab:read", "account:read"):
            self.assertIn(s, scope)
        code, out, _ = self.cli("whoami")
        self.assertEqual(code, 0)
        self.assertIn("as tester (tester@example.org), with a code on the website", out)
        self.assertFalse(os.path.exists(A.accounts_path()))          # no file holds a token

    def test_scopes_and_addresses_are_configurable(self):
        A.configure("bromigos", scopes="openid offline_access lab:read")
        self.assertEqual(A.scopes("bromigos"), ["openid", "offline_access", "lab:read"])
        with mock.patch.dict(os.environ, {"BROMIGOS_SCOPES": "openid, account:read"}):
            self.assertEqual(A.scopes("bromigos"), ["openid", "account:read"])   # the environment wins
        self.assertEqual(A.config("bromigos")["client_id"], "bromigos-cli")      # on a test server too
        with mock.patch.dict(os.environ, {}, clear=True):
            c = A.config("bromigos")
            self.assertEqual((c["base"], c["issuer"]), ("https://account.bromigos.org", "https://auth.bromigos.org"))
        self.assertEqual(A.needs("bromigos"), [])

    def test_a_desktop_session_offers_the_browser_and_enter_opens_it(self):
        r, w = os.pipe()
        self.addCleanup(os.close, r)
        tty = os.fdopen(r, "r", closefd=False)
        tty.isatty = lambda: True
        os.write(w, b"\n")                                # the person presses Enter
        os.close(w)
        opened = []

        def opener(url):
            opened.append(url)
            self.acct.auto_approve_after = 1              # and approves in the page it opened
            return True
        out = []
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}):
            args = L._parser("login").parse_args([])
            self.assertEqual(L.login(args, say=out.append, stdin=tty, opener=opener), 0)
        self.assertEqual(len(opened), 1)
        self.assertIn("/device?user_code=WDJB-", opened[0])              # the code is filled in
        self.assertIn("Press Enter to open it in your browser, or approve it from another device. "
                      "Waiting… (Ctrl+C stops)", out)
        self.assertEqual(self.record()["how"], "device")

    def test_over_ssh_or_with_no_browser_it_never_offers(self):
        for env, argv in (({"WAYLAND_DISPLAY": "w", "SSH_CONNECTION": "192.0.2.1 22 192.0.2.2 22"}, []),
                          ({"WAYLAND_DISPLAY": "w"}, ["--no-browser"])):
            A.sign_out("bromigos")
            self.acct.auto_approve_after = 2
            out = []
            tty = Pipe(tty=True)
            with mock.patch.dict(os.environ, env):
                self.assertEqual(L.login(L._parser("login").parse_args(argv), say=out.append, stdin=tty,
                                         opener=self.no_browser), 0)
            self.assertIn("Waiting for you to approve it… (Ctrl+C stops)", out)

    def test_discovery_down_uses_the_issuers_usual_paths(self):
        A._discovered.clear()
        with mock.patch.object(A, "http_json", side_effect=OSError("down")):
            self.assertEqual(A.discovery("bromigos"), {})
            self.assertEqual(A._url("bromigos", "token_url"), self.srv.issuer + "/oauth2/token")


def _have_qrcode():
    try:
        import qrcode  # noqa: F401
        return True
    except ImportError:
        return False


HAVE_QRCODE = _have_qrcode()
QR_HALF = {"\u2588": (True, True), "\u2580": (True, False), "\u2584": (False, True), " ": (False, False)}


def unrender(lines):
    """The modules a printed QR code shows: its half blocks read back into rows."""
    rows = []
    for line in lines:
        cells = re.sub(r"\x1b\[[0-9;]*m", "", line).strip("\n")[4:]
        rows.append([QR_HALF[c][0] for c in cells])
        rows.append([QR_HALF[c][1] for c in cells])
    return rows


@unittest.skipUnless(HAVE_QRCODE, "python-qrcode isn't installed")
class QrCode(Base):
    TERMINAL = {"TERM": "xterm-256color", "COLORTERM": "", "NO_COLOR": "", "COLUMNS": "100", "LINES": "50"}

    def login_on(self, tty=True, **env):
        self.acct.auto_approve_after = 2
        A.sign_out("bromigos")
        out = Pipe(tty=tty)
        with mock.patch.dict(os.environ, {**self.TERMINAL, **env}), mock.patch.object(sys, "stdout", out), \
                mock.patch.object(sys, "stderr", io.StringIO()), mock.patch.object(sys, "stdin", Pipe()):
            self.assertEqual(L.main("login", []), 0)
        return out.getvalue()

    def qr_of(self, text):
        return [line for line in text.splitlines() if "\x1b[" in line]

    def test_a_terminal_shows_a_qr_code_of_the_page_with_the_code_filled_in(self):
        text = self.login_on()
        self.assertIn(f"    {self.srv.base}/device\n", text)                     # the plain page and code stay
        self.assertRegex(text, r"and enter this code:\n    WDJB-[0-9A-F]{4}\n")
        self.assertIn("Or point your phone's camera at this QR code. It opens the page with the code filled in:",
                      text)
        code = re.search(r"WDJB-[0-9A-F]{4}", text).group(0)
        lines = self.qr_of(text)
        self.assertTrue(lines)
        matrix = A.qr_matrix(f"{self.srv.base}/device?user_code={code}")
        self.assertEqual(unrender(lines)[:len(matrix)], matrix)                  # it draws that link, exactly
        self.assertTrue(all(line.startswith("    \x1b[30;47m") and line.endswith("\x1b[0m") for line in lines))
        self.assertTrue(all(not any(r) for r in matrix[:A.QR_QUIET]))           # a light quiet zone
        self.assertLess(text.index("WDJB-"), text.index(lines[0]))
        self.assertLess(text.index(lines[-1]), text.index("The code works for"))

    def test_truecolor_terminals_get_exact_black_and_white(self):
        lines = self.qr_of(self.login_on(COLORTERM="truecolor"))
        self.assertTrue(lines and all(line.startswith("    \x1b[38;2;0;0;0;48;2;255;255;255m") for line in lines))

    def test_no_qr_code_where_it_would_not_show_whole_or_scan(self):
        for tty, env in ((False, {}), (True, {"COLUMNS": "30"}), (True, {"LINES": "20"}), (True, {"TERM": "dumb"}),
                         (True, {"NO_COLOR": "1"})):
            text = self.login_on(tty=tty, **env)
            self.assertEqual(self.qr_of(text), [], (tty, env))
            self.assertNotIn("QR code", text)
            self.assertRegex(text, r"and enter this code:\n    WDJB-[0-9A-F]{4}\n")   # always the page and code
        with mock.patch.dict(sys.modules, {"qrcode": None}):                     # python-qrcode not installed
            self.assertEqual(self.qr_of(self.login_on()), [])

    def test_bromigos_account_login_shows_it_too(self):
        self.acct.auto_approve_after = 2
        out = Pipe(tty=True)
        with mock.patch.dict(os.environ, self.TERMINAL), mock.patch.object(sys, "stdout", out), \
                mock.patch.object(A, "_default_prompt", lambda *a: (lambda d: None)):
            self.assertEqual(A.main(["login", "bromigos"]), 0)
        text = out.getvalue()
        code = re.search(r"enter (WDJB-[0-9A-F]{4})", text).group(1)
        matrix = A.qr_matrix(f"{self.srv.base}/device?user_code={code}")
        self.assertEqual(unrender(self.qr_of(text))[:len(matrix)], matrix)
        self.assertIn("signed in to Bromigos", text)

    def test_the_link_is_built_when_the_service_gives_no_complete_one(self):
        start = {"user_code": "BCDF GHJK", "verification_uri": "https://auth.example.org/oauth2/device/verify"}
        self.assertEqual(L.complete_url(start), self.srv.base + "/device?user_code=BCDF%20GHJK")
        start["verification_uri_complete"] = start["verification_uri"]          # A.device_start's stand-in
        self.assertEqual(L.complete_url(start), self.srv.base + "/device?user_code=BCDF%20GHJK")
        start["verification_uri_complete"] = start["verification_uri"] + "?user_code=BCDF%20GHJK"
        self.assertEqual(L.complete_url(start), start["verification_uri_complete"])

    @unittest.skipUnless(shutil.which("zbarimg"), "zbar's zbarimg isn't installed")
    def test_a_camera_reads_the_printed_code(self):
        text = self.login_on()
        code = re.search(r"WDJB-[0-9A-F]{4}", text).group(0)
        rows = unrender(self.qr_of(text))
        scale = 8                                                               # a PGM, 8 pixels a module
        path = os.path.join(self.tmp, "qr.pgm")
        with open(path, "wb") as f:
            f.write(b"P5 %d %d 255\n" % (len(rows[0]) * scale, len(rows) * scale))
            for row in rows:
                line = bytes(0 if dark else 255 for dark in row for _ in range(scale))
                f.write(line * scale)
        got = subprocess.run(["zbarimg", "--quiet", "--raw", path], capture_output=True, text=True)
        self.assertEqual(got.stdout.strip(), f"{self.srv.base}/device?user_code={code}", got.stderr)


@unittest.skipUnless(HAVE_SSH, "OpenSSH's ssh-keygen, ssh-agent and ssh-add aren't installed")
class SshSignIn(Base):
    def test_a_key_file_on_the_account_signs_in_without_a_browser(self):
        path, pub = self.keygen("id_ed25519")
        self.acct.keys = [{"public_key": pub, "title": "laptop"}]
        code, out, err = self.cli("login", "--ssh")
        self.assertEqual(code, 0, err)
        fp = subprocess.run(["ssh-keygen", "-lf", path + ".pub"], capture_output=True, text=True).stdout.split()[1]
        self.assertIn(f"Signing in with {fp}…", out)
        self.assertIn("Signed in to your Bromigos account as tester", out)
        rec = self.record()
        self.assertEqual((rec["how"], rec["ssh_key"]), ("ssh", fp))
        self.assertEqual(len(self.acct.signed), 1)                          # ssh-keygen -Y verify passed
        self.assertRegex(self.acct.signed[0].decode(), r"^bromigos-login\nWDJB-[0-9A-F]{4}\n[\w-]+$")
        self.assertFalse(any(p.startswith("/device") for _, p in self.acct.requests))
        code, out, _ = self.cli("whoami")
        self.assertIn(f"with the SSH key {fp}", out)

    def test_a_key_in_ssh_agent_signs_there(self):
        agent_dir = tempfile.mkdtemp(prefix="bmg-agent-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.addCleanup(shutil.rmtree, agent_dir, True)
        sock = os.path.join(agent_dir, "agent.sock")
        agent = subprocess.Popen(["ssh-agent", "-D", "-a", sock], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(agent.wait)
        self.addCleanup(agent.terminate)
        for _ in range(100):
            if os.path.exists(sock):
                break
            time.sleep(0.05)
        os.environ["SSH_AUTH_SOCK"] = sock
        path, pub = self.keygen("agent_key", folder=agent_dir)
        subprocess.run(["ssh-add", "-q", path], check=True, stdin=subprocess.DEVNULL, capture_output=True)
        os.remove(path)                                   # only the agent can sign with it now
        os.remove(path + ".pub")
        self.acct.keys = [{"public_key": pub, "title": "agent"}]
        keys = L.local_keys()
        self.assertEqual([(k.agent, k.path) for k in keys], [(True, None)])
        signed = []
        real = subprocess.run

        def spy(argv, *a, **k):
            if argv[:3] == ["ssh-keygen", "-Y", "sign"]:
                signed.append(argv)
            return real(argv, *a, **k)
        with mock.patch.object(L.subprocess, "run", spy):
            code, out, err = self.cli("login", "--ssh")
        self.assertEqual(code, 0, err)
        self.assertIn("-U", signed[0])
        self.assertIn("(ssh-agent)", out)
        self.assertEqual(self.record()["how"], "ssh")

    def test_a_key_not_on_the_account_says_where_to_add_it(self):
        _, pub = self.keygen("id_ed25519")
        _, other = self.keygen("other", folder=self.tmp)
        self.acct.keys = [{"public_key": other, "title": "someone else"}]
        code, out, err = self.cli("login", "--ssh", "--key", os.path.join(self.home, ".ssh/id_ed25519"))
        self.assertEqual(code, 1)
        self.assertIn("The account doesn't know the SSH key SHA256:", err)
        self.assertIn("127.0.0.1 › SSH keys", err)
        self.assertIn(pub.split()[1], err)                                  # its public key, to paste
        self.assertIsNone(self.record())

    def test_several_keys_ask_which(self):
        self.keygen("id_ed25519")
        _, second = self.keygen("id_ecdsa", kind="ecdsa")
        self.acct.keys = [{"public_key": second, "title": "work"}]
        said, answers = [], ["x", "1"]
        key = L.choose_key(L.local_keys(), ask=lambda q: answers.pop(0), say=said.append)
        self.assertEqual(key.comment, "id_ecdsa@example.org")             # sorted: id_ecdsa comes first
        self.assertIn("Which SSH key should sign you in?", said)
        self.assertTrue(any(s.startswith("  2. SHA256:") and "ED25519" in s for s in said))
        self.assertIn("Type a number from 1 to 2.", said)
        # with no terminal to ask on, it wants --key
        code, _, err = self.cli("login", "--ssh")
        self.assertEqual(code, 1)
        self.assertIn("--key PATH", err)
        self.assertEqual(self.cli("login", "--ssh", "--key", os.path.join(self.home, ".ssh/id_ecdsa.pub"))[0], 0)

    def test_no_key_at_all(self):
        code, _, err = self.cli("login", "--ssh")
        self.assertEqual(code, 1)
        self.assertIn("No SSH key found", err)
        self.assertIn("ssh-keygen -t ed25519", err)


@unittest.skipUnless(HAVE_SSH, "OpenSSH's ssh-keygen isn't installed")
class AccountKeys(Base):
    def sign_in(self):
        self.acct.auto_approve_after = 1
        self.assertEqual(self.cli("login")[0], 0)

    def test_the_accounts_keys_are_checked_and_fingerprinted_here(self):
        self.assertIsNone(L.account_ssh_keys())                            # signed out: None, no request
        self.assertNotIn(("GET", "/api/me/ssh-keys"), self.acct.requests)
        self.sign_in()
        path, pub = self.keygen("id_ed25519")
        _, rsa = self.keygen("id_rsa", kind="rsa")
        self.acct.keys = [{"public_key": pub, "title": "laptop\nrm -rf"}, {"public_key": rsa, "title": "desk"}]
        self.acct.extra_keys = [
            {"public_key": 'command="sh" ' + pub, "title": "options"},       # options never reach authorized_keys
            {"public_key": pub.split()[0] + " " + rsa.split()[1], "title": "type mismatch"},
            {"public_key": "ssh-dss AAAAB3NzaC1kc3M=", "title": "unknown type"},
            {"public_key": pub + "\nssh-ed25519 AAAA", "title": "two lines"},
            {"public_key": pub, "title": "duplicate"}]
        keys = L.account_ssh_keys()
        self.assertEqual([k["title"] for k in keys], ["laptoprm -rf", "desk"])
        fp = subprocess.run(["ssh-keygen", "-lf", path + ".pub"], capture_output=True, text=True).stdout.split()[1]
        self.assertEqual(keys[0]["fingerprint"], fp)
        self.assertEqual(keys[0]["line"], pub.split()[0] + " " + pub.split()[1] + " laptoprm -rf (Bromigos account)")
        self.assertNotIn("\n", keys[0]["line"])

    def test_a_401_refreshes_once_and_tries_again(self):
        self.sign_in()
        self.acct.access.clear()                          # the service forgot the access token
        old = self.record()["refresh_token"]
        self.assertEqual(L.account_ssh_keys(), [])
        self.assertEqual(self.acct.used_refresh, [old])
        self.assertNotEqual(self.record()["refresh_token"], old)          # rotated, and stored
        self.acct.access.clear()
        self.acct.refresh = "cancelled-on-the-website"
        with self.assertRaises(A.SignInError) as c:
            L.account_ssh_keys()
        self.assertIn("sign in again", str(c.exception))


class Tokens(Base):
    def test_an_expired_token_refreshes_once_even_when_two_ask_at_once(self):
        self.acct.auto_approve_after = 1
        self.assertEqual(self.cli("login")[0], 0)
        rec = self.record()
        rec["expires_at"] = time.time() - 5
        A._save("bromigos", rec)
        got = []
        threads = [threading.Thread(target=lambda: got.append(L.token())) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(self.acct.used_refresh), 1)                  # one refresh, under the lock
        self.assertEqual(self.acct.reused, [])                            # the old one never sent twice
        self.assertEqual(len(set(got)), 1)
        self.assertEqual(got[0], self.record()["access_token"])
        self.assertEqual(self.record()["how"], "device")                  # how it was signed in stays

    def test_with_token_stores_a_personal_access_token_and_never_prints_it(self):
        pat = "bmg_pat_" + "x" * 24
        self.acct.pats.add(pat)
        code, out, err = self.cli("login", "--with-token", stdin=Pipe(pat + "\n"))
        self.assertEqual(code, 0, err)
        self.assertNotIn(pat, out + err)
        self.assertIn("Signed in with your personal access token", out)
        self.assertEqual(L.token(), pat)
        self.assertEqual(self.record()["how"], "token")
        self.assertEqual(self.record()["who"], "tester")
        code, out, _ = self.cli("whoami", "--json")
        doc = json.loads(out)
        self.assertEqual((doc["signed_in"], doc["how"], doc["via"]), (True, "token", "keyring"))
        # logout leaves a pasted token alone on the website (no revocation), and forgets it here
        code, out, _ = self.cli("logout")
        self.assertEqual(self.acct.revoked, [])
        self.assertIsNone(self.record())

    def test_a_wrong_token_is_refused(self):
        code, out, err = self.cli("login", "--with-token", stdin=Pipe("ghp_notours\n"))
        self.assertEqual(code, 1)
        self.assertIn("those start with bmg_pat_", err)
        self.assertNotIn("ghp_notours", out + err)
        self.assertIsNone(self.record())

    def test_bromigos_token_stands_in_while_it_is_set(self):
        os.environ["BROMIGOS_TOKEN"] = "bmg_pat_" + "e" * 24
        self.assertEqual(L.token(), os.environ["BROMIGOS_TOKEN"])
        code, out, _ = self.cli("whoami")
        self.assertEqual((code, out.strip()), (0, "Using the personal access token in BROMIGOS_TOKEN."))
        self.assertEqual(A.status("bromigos")["via"], "env")
        code, out, _ = self.cli("logout")
        self.assertIn("BROMIGOS_TOKEN is still set", out)

    def test_logout_revokes_the_refresh_token_and_whoami_says_signed_out(self):
        self.acct.auto_approve_after = 1
        self.assertEqual(self.cli("login")[0], 0)
        ref = self.record()["refresh_token"]
        code, out, _ = self.cli("logout", "--json")
        doc = json.loads(out)
        self.assertEqual((doc["ok"], doc["signed_in"]), (True, False))
        self.assertEqual(self.acct.revoked, [ref])
        self.assertIsNone(self.record())
        code, out, _ = self.cli("whoami")
        self.assertEqual(code, 1)
        self.assertIn("To sign in, run: bromigos login", out)
        self.assertFalse(json.loads(self.cli("whoami", "--json")[1])["signed_in"])

    def test_account_token_says_how_to_make_one(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            self.assertEqual(A.main(["token"]), 0)
        text = out.getvalue()
        self.assertIn(f"Open {self.srv.base} and sign in.", text)
        self.assertIn("› Personal access tokens", text)
        self.assertIn("bromigos login --with-token", text)
        self.assertIn("can't make one for you", text)


class BrokenKeyring(A.MemoryKeyring):
    """A keyring that fails to store, the way libsecret does when no Secret Service runs:
    a GLib error is a RuntimeError, and str() of it is its raw D-Bus words."""

    RAW = "g-dbus-error-quark: GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: The name is not activatable (2)"

    def set(self, service, account, label, value):
        raise RuntimeError(self.RAW)


class Keyring(Base):
    """No keyring, or one that fails after the approval: plain words, never a D-Bus error."""

    def test_no_keyring_stops_before_the_code_is_shown(self):
        import bromigos_keyring as K
        with mock.patch.object(A, "keyring_ready", return_value=K.NO_KEYRING):
            code, out, err = self.cli("login")
        self.assertEqual(code, 1)
        self.assertIn("No keyring is running", err)
        self.assertIn("sudo pacman -S bromigos/oo7", err)
        self.assertNotIn("enter this code", out)                     # no approval wasted
        self.assertNotIn(("POST", "/auth/device/code"), self.acct.requests)
        with mock.patch.object(A, "keyring_ready", return_value=K.NO_KEYRING):
            self.assertEqual(self.cli("login", "--with-token", stdin=Pipe("bmg_pat_x"))[0], 1)

    def test_a_store_that_fails_after_approval_says_what_happened(self):
        self.acct.auto_approve_after = 1
        A.KEYRING = BrokenKeyring()
        with mock.patch.object(A, "keyring_ready", return_value=None):
            code, out, err = self.cli("login")
        self.assertEqual(code, 1)
        self.assertIn("You approved the sign-in, but this computer couldn't keep it", err)
        self.assertIn("No keyring is running", err)
        self.assertIn("Then run bromigos login again.", err)
        self.assertNotIn("quark", err + out)
        self.assertNotIn("org.freedesktop.DBus.Error", err + out)

    def test_a_raw_glib_error_anywhere_is_put_in_plain_words(self):
        with mock.patch.object(L, "login", side_effect=RuntimeError(BrokenKeyring.RAW)):
            code, out, err = self.cli("login")
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("bromigos login: No keyring is running"), err)
        self.assertNotIn("quark", err)

    def test_the_stand_in_keyring_is_always_ready(self):
        self.assertIsNone(A.keyring_ready())


if __name__ == "__main__":
    unittest.main()
