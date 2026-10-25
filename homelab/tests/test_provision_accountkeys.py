"""Your Bromigos account's SSH keys on a new lab box (accountkeys.py), in the guided setup and
in `bromigos lab provision plan`. The box's authorized_keys is a real file in a temporary
home, changed by the real shell script; the account is a stand-in. Nothing reaches a real
machine, keyring or ~/.ssh."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest import mock

import test_provision_guided as TG
from bromigos_homelab import accountkeys as K, guidedprovision as G, provision as P


def key(seed, title):
    """An account key as bromigos_login.account_ssh_keys gives it, with a well-formed blob."""
    raw = b"\0\0\0\x0bssh-ed25519\0\0\0\x20" + hashlib.sha256(seed.encode()).digest()
    blob = base64.b64encode(raw).decode()
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
    return {"type": "ssh-ed25519", "blob": blob, "title": title, "fingerprint": fp,
            "line": f"ssh-ed25519 {blob} {title} (Bromigos account)"}


LAPTOP, DESK = key("laptop", "laptop"), key("desk", "desk")
EXISTING = "ssh-rsa AAAAB3NzaC1yc2EAAAAExisting someone@example.org"


class AccountBox(TG.Box):
    """The fake box, with a real authorized_keys under its own home."""
    def __init__(self, home, box_home):
        super().__init__(home)
        self.box_home = box_home
        self.own = None                       # the blob of the key this desktop logs in with

    def keys_file(self):
        return self.box_home / ".ssh/authorized_keys"

    def script(self, command, data):
        argv = shlex.split(command)
        assert argv[:2] == ["sh", "-c"] and argv[2] == K.SCRIPT, command
        result = subprocess.run(argv, input=data, text=True, capture_output=True,
                                env={"HOME": str(self.box_home), "PATH": os.environ["PATH"]})
        if self.own and self.keys_file().exists() and self.own in self.keys_file().read_text():
            self.key_installed = True
        return result.returncode, result.stdout, result.stderr

    def handle(self, argv, data):
        if argv[0] == "ssh" and self.key_installed and self.known():
            command = argv[-1]
            if command == K.READ:
                return 0, self.keys_file().read_text() if self.keys_file().exists() else "", ""
            if command.startswith("sh -c "):
                return self.script(command, data)
        return super().handle(argv, data)

    def password_login(self, argv, data):
        assert "BatchMode=no" in argv and "StrictHostKeyChecking=yes" in argv
        assert "BatchMode=yes" not in argv
        return self.script(argv[-1], data)


class AccountKeysInTheGuide(unittest.TestCase):
    guide = TG.GuidedTests.guide

    def setUp(self):
        TG.GuidedTests.setUp(self)
        self.box_home = Path(self.tmp.name) / "box-home"
        (self.box_home / ".ssh").mkdir(parents=True)
        self.box = AccountBox(self.home, self.box_home)
        self.box.sudo = True
        self.fetched = []

    def account(self, *keys, error=None):
        def fetch():
            self.fetched.append(1)
            if error:
                raise error
            return {"who": "tester", "keys": list(keys), "site": "account.example.org"}
        return fetch

    def trusted(self):
        (self.home / ".ssh/known_hosts").write_text(TG.HOST_KEY + "\n")

    def test_keys_missing_from_the_box_are_added_after_a_yes(self):
        self.box.key_installed = True
        self.trusted()
        self.box.keys_file().write_text(EXISTING + "\n" + LAPTOP["line"])     # no newline at the end
        term = TG.Term(self.box, ["yes", "no", "box.example.org", "tester", "", "yes", "", "1", "yes", str(self.repo), "yes"])
        self.assertEqual(self.guide(term, self.account(LAPTOP, DESK)).run(), 0)
        text = term.text()
        self.assertIn("  You're signed in to your Bromigos account as tester. These SSH keys on it aren't on the box yet:",
                      term.out)
        self.assertIn(f"    {DESK['fingerprint']}  ed25519  desk", term.out)
        self.assertNotIn(LAPTOP["fingerprint"], text)                        # already there: not offered
        self.assertIn("? " + "  Add this key?", term.out)
        self.assertIn("  ✓ Added 1 SSH key from your Bromigos account to tester's authorized_keys", term.out)
        lines = self.box.keys_file().read_text().splitlines()
        self.assertEqual(lines, [EXISTING, LAPTOP["line"], DESK["line"]])   # appended, nothing removed
        self.assertEqual(self.fetched, [1])
        state = json.loads(G.state_path().read_text())
        self.assertEqual(state["account_keys"], [DESK["fingerprint"]])
        # the second run checks, says so, and asks nothing
        again = TG.Term(self.box, [])
        self.assertEqual(self.guide(again, self.account(LAPTOP, DESK)).run(), 0)
        self.assertIn("  ✓ Your Bromigos account's SSH keys are on the box (2 of 2)", again.out)
        self.assertFalse([line for line in again.out if line.startswith("? ")])

    def test_a_no_is_remembered_for_this_box(self):
        self.box.key_installed = True
        self.trusted()
        term = TG.Term(self.box, [])
        guide = self.guide(term, self.account(DESK))
        guide.state.update(host="box.example.org", user="tester", port=22)
        term.answers = ["no"]
        guide.ssh_step()
        self.assertIn("  Skipped. bromigOS won't ask about these keys for this box again.", term.out)
        self.assertFalse(self.box.keys_file().exists())
        again = TG.Term(self.box, [])
        guide = self.guide(again, self.account(DESK))
        guide.ssh_step()
        self.assertFalse([line for line in again.out if line.startswith("? ")])

    def test_one_password_login_adds_them_instead_of_ssh_copy_id(self):
        self.trusted()
        (self.box_home / ".ssh").rmdir()       # a new box: the script makes ~/.ssh
        self.box.own = LAPTOP["blob"]          # this desktop's key is one of the account's
        term = TG.Term(self.box, [])
        guide = self.guide(term, self.account(LAPTOP, DESK))
        guide.state.update(host="box.example.org", user="tester", port=22)
        term.answers = ["yes"]
        guide.ssh_step()
        self.assertIn("  It asks for your password on the box once.", term.out)
        self.assertEqual([argv[0] for argv in term.interactive_ran], ["ssh"])   # no ssh-copy-id
        self.assertIn("  ✓ SSH works with your key, and the box's host key is trusted", term.out)
        self.assertIn("  ✓ Your Bromigos account's SSH keys are on the box (2 of 2)", term.out)
        self.assertEqual(oct(self.box.keys_file().stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct((self.box_home / ".ssh").stat().st_mode & 0o777), "0o700")

    def test_when_the_desktops_own_key_isnt_on_the_account_ssh_copy_id_still_runs(self):
        self.trusted()
        term = TG.Term(self.box, [])
        guide = self.guide(term, self.account(DESK))
        guide.state.update(host="box.example.org", user="tester", port=22)
        term.answers = ["yes", "yes"]          # add the account's key; then run ssh-copy-id
        guide.ssh_step()
        self.assertEqual([argv[0] for argv in term.interactive_ran], ["ssh", "ssh-copy-id"])
        self.assertIn(DESK["line"], self.box.keys_file().read_text())

    def test_signed_out_says_nothing_and_a_broken_account_never_stops_the_setup(self):
        self.box.key_installed = True
        self.trusted()
        term = TG.Term(self.box, [])
        guide = self.guide(term, lambda: None)
        guide.state.update(host="box.example.org", user="tester", port=22)
        guide.ssh_step()
        self.assertNotIn("Bromigos", term.text())
        term = TG.Term(self.box, [])
        guide = self.guide(term, self.account(error=OSError("no route to host")))
        guide.state.update(host="box.example.org", user="tester", port=22)
        guide.ssh_step()
        self.assertIn("Couldn't read the SSH keys on your Bromigos account (no route to host). Carrying on without them.",
                      term.text())
        self.assertIn("  ✓ SSH works with your key, and the box's host key is trusted", term.out)

    def test_an_account_with_no_keys_says_where_to_add_one(self):
        self.box.key_installed = True
        self.trusted()
        term = TG.Term(self.box, [])
        guide = self.guide(term, self.account())
        guide.state.update(host="box.example.org", user="tester", port=22)
        guide.ssh_step()
        self.assertIn("account.example.org › SSH keys", term.text())


class Script(unittest.TestCase):
    """The shell script on its own, in a temporary home."""
    def run_script(self, home, data):
        return subprocess.run(["sh", "-c", K.SCRIPT], input=data, text=True, capture_output=True,
                              env={"HOME": str(home), "PATH": os.environ["PATH"]})

    def test_it_only_appends_and_keeps_modes(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".ssh").mkdir(mode=0o755)
            f = home / ".ssh/authorized_keys"
            f.write_text('from="198.51.100.0/24" ' + LAPTOP["line"].replace(" laptop (Bromigos account)", "") + "\n")
            f.chmod(0o644)
            r = self.run_script(home, K.lines([LAPTOP, DESK, DESK]))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(K.added(r.stdout), 1)
            self.assertEqual(f.read_text().splitlines()[1], DESK["line"])
            self.assertEqual(len(f.read_text().splitlines()), 2)
            self.assertEqual(oct(f.stat().st_mode & 0o777), "0o644")            # an existing file's mode stays
            self.assertEqual(oct((home / ".ssh").stat().st_mode & 0o777), "0o755")

    def test_on_box_reads_blobs_past_options(self):
        text = 'command="x",no-pty ' + LAPTOP["line"] + "\n# a comment\n\n" + EXISTING + "\n"
        self.assertEqual(K.on_box(text), {LAPTOP["blob"], "AAAAB3NzaC1yc2EAAAAExisting"})


class PlanCommand(unittest.TestCase):
    """`bromigos lab provision plan --ssh …` offers them once the box answers."""
    def test_offer_through_the_plan_command(self):
        target = {"kind": "ssh", "ssh": "tester@box.example.org", "port": 22}
        ran, said = [], []

        def fake_run(argv, data=None, cwd=None, env=None):
            ran.append((argv[-1], data))
            return "" if argv[-1] == K.READ else "added=1\n"
        with mock.patch.object(P, "run", fake_run):
            added = P.offer_account_keys(target, fetch=lambda: {"who": "tester", "keys": [DESK]}, say=said.append,
                                         yes=lambda q: True)
        self.assertEqual(added, [DESK["fingerprint"]])
        self.assertEqual(ran[1], (K.command(), DESK["line"] + "\n"))
        self.assertIn("  ✓ Added 1 SSH key from your Bromigos account to tester's authorized_keys", said)
        self.assertEqual(P.offer_account_keys(target, fetch=lambda: None, say=said.append), [])

    def test_a_terminal_is_asked_unless_the_flag_says_no(self):
        argv = ["plan", "--repo", "/nonexistent/lab", "--ssh", "tester@box.example.org", "--age-recipient", "age1test"]
        for extra, tty, asked in (([], True, 1), (["--no-account-keys"], True, 0), ([], False, 0)):
            with mock.patch.object(P, "inventory", return_value={}), \
                    mock.patch.object(P, "plan_files", side_effect=P.ProvisionError("stop here")), \
                    mock.patch.object(P.sys.stdin, "isatty", return_value=tty), \
                    mock.patch.object(P, "offer_account_keys") as offer, \
                    mock.patch("sys.stderr"):
                self.assertEqual(P.main(argv + extra), 1)
            self.assertEqual(offer.call_count, asked, (extra, tty))


if __name__ == "__main__":
    unittest.main()
