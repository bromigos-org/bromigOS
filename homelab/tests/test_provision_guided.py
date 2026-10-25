"""The guided setup's steps, with scripted answers and a fake box. Nothing reaches a real machine."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from bromigos_homelab import guidedprovision as G, hardware as H, provision as P

os.environ["BROMIGOS_LAB_PROFILES"] = str(Path(__file__).resolve().parents[1] / "share/lab/profiles.toml")
LSBLK = (Path(__file__).parent / "fixtures/hardware/gpu-box.lsblk.json").read_text()
HOST_KEY = "box.example.org ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyOnlyForTheseTests"
GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.org",
       "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.org"}


def facts():
    raw = {"lsblk": LSBLK, "net": [{"name": "eno1", "wireless": False, "speed": "1000", "operstate": "up"}],
           "mounts": [{"source": "/dev/nvme0n1p2", "mount": "/", "fstype": "ext4", "total": 1e12, "free": 9e11},
                      {"source": "nas.example.org:/backups", "mount": "/mnt/nas", "fstype": "nfs4", "total": 8e12, "free": 3.2e12},
                      {"source": "/dev/sdb1", "mount": "/srv/data", "fstype": "ext4", "total": 2e12, "free": 1.5e12}],
           "cpu": {"model": "Test CPU", "flags": ["svm"], "kvm": True}}
    return dict(cpu=8, ram_gib=32, disk_gib=500, distribution="debian", architecture="x86_64", gpu="none", vram_gib=0, hardware=H.parse(raw))


class Box:
    """A spare box as SSH sees it, and the desktop's other commands."""
    def __init__(self, home):
        self.home = home
        self.key_installed = False
        self.sudo = False
        self.python = True
        self.folders = {"/srv/data", "/mnt/nas"}
        self.host_key = HOST_KEY

    def known(self):
        path = self.home / ".ssh/known_hosts"
        return path.exists() and HOST_KEY in path.read_text()

    def handle(self, argv, data):
        name = argv[0]
        if name == "ssh":
            command = argv[-1]
            assert "StrictHostKeyChecking=yes" in argv and "UserKnownHostsFile=" + str(self.home / ".ssh/known_hosts") in argv
            if self.host_key != HOST_KEY and self.known():
                return 255, "", "@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@\nHost key verification failed."
            if not self.known():
                return 255, "", "No ED25519 host key is known for box.example.org.\nHost key verification failed."
            if not self.key_installed:
                return 255, "", "tester@box.example.org: Permission denied (publickey,password)."
            if command == "true":
                return 0, "", ""
            if command == "command -v python3":
                return (0, "/usr/bin/python3\n", "") if self.python else (1, "", "")
            if command == "cat /etc/os-release":
                return 0, 'ID=debian\nVERSION_ID="13"\n', ""
            if command == "sudo -n true":
                return (0, "", "") if self.sudo else (1, "", "sudo: a password is required")
            if command.startswith("test -d "):
                return (0, "", "") if command.split()[-1] in self.folders else (1, "", "")
            if command.startswith("sudo -n install -d -m 0700 "):
                self.folders.add(command.split()[-1])
                return 0, "", ""
            raise AssertionError("unexpected box command: " + command)
        if name == "ssh-keyscan":
            return 0, self.host_key + "\n", ""
        if name == "ssh-keygen" and argv[1:] == ["-l", "-f", "-"]:
            return 0, "256 SHA256:TestFingerprintOnly box.example.org (ED25519)\n", ""
        if name == "age-keygen" and argv[1] == "-o":
            Path(argv[2]).write_text("AGE-SECRET-KEY-TEST\n")
            return 0, "", "Public key: age1testrecipient\n"
        if name == "age-keygen" and argv[1] == "-y":
            return 0, "age1testrecipient\n", ""
        if name == "git":
            result = subprocess.run(argv, text=True, capture_output=True, env=dict(os.environ, **GIT))
            return result.returncode, result.stdout, result.stderr
        raise AssertionError("unexpected desktop command: " + " ".join(argv))


class Term:
    """Scripted answers. Each question takes the next answer; running out fails the test."""
    def __init__(self, box, answers, installed=tuple(G.TOOLS), on_wait=None):
        self.box, self.answers, self.installed = box, list(answers), set(installed)
        self.out, self.ran, self.interactive_ran, self.waits = [], [], [], 0
        self.on_wait = on_wait

    def say(self, text=""):
        self.out.append(text)

    def ask(self, question, default=""):
        self.out.append("? " + question)
        answer = self.answers.pop(0)
        return answer or default

    def yes(self, question):
        self.out.append("? " + question)
        return self.answers.pop(0) == "yes"

    def wait(self, text):
        self.waits += 1
        if self.on_wait:
            self.on_wait(self)
        else:
            raise G.Stop("stopped")

    def which(self, name):
        return "/usr/bin/" + name if name in self.installed else None

    def run(self, argv, data=None):
        self.ran.append(argv)
        return self.box.handle(argv, data)

    def interactive(self, argv, data=None):
        self.interactive_ran.append(argv)
        if argv[0] == "ssh-copy-id":
            self.box.key_installed = True
        return 0

    def password_run(self, argv, data):
        self.interactive_ran.append(argv)
        return self.box.password_login(argv, data)

    def text(self):
        return "\n".join(self.out)


class GuidedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        (self.home / ".ssh").mkdir(parents=True)
        (self.home / ".ssh/id_ed25519.pub").write_text("ssh-ed25519 AAAATEST test@example.org\n")
        env = {"XDG_CONFIG_HOME": str(root / "config"), "XDG_STATE_HOME": str(root / "state")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        os.environ.pop("SOPS_AGE_KEY_FILE", None)
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.box = Box(self.home)
        self.applied = []
        self.repo = root / "lab"
        self.found, self.boxes = [], []                # Find my lab: its runs, and what it "finds"

    def guide(self, term, account=lambda: None):
        def apply(repo, live_facts=None):
            self.applied.append((repo, live_facts))
            return 0
        def find():
            self.found.append(1)
            return self.boxes
        return G.Guide(term=term, home=self.home, inventory=lambda target: facts(), apply=apply, find=find,
                       account=account)

    def fresh_answers(self):
        return ["yes",                              # create the age key
                "no",                               # don't look for the box (Find my lab)
                "box.example.org", "tester", "",   # the box, its user, the default port
                "yes",                              # the host key fingerprint matches
                "yes",                              # run ssh-copy-id
                "",                                 # the recommended preset
                "1",                                # the first backup place
                "yes",                              # create that folder
                str(self.repo),                     # the lab repository
                "yes"]                              # commit the plan

    def test_first_run_walks_every_step_and_only_acts_after_yes(self):
        def fix(term):
            if not term.installed >= set(G.TOOLS):
                term.installed |= set(G.TOOLS)
            else:
                self.box.sudo = True
        term = Term(self.box, self.fresh_answers(), installed=set(G.TOOLS) - {"ansible-playbook", "ansible-galaxy", "sops"}, on_wait=fix)
        self.assertEqual(self.guide(term).run(), 0)
        text = term.text()
        self.assertIn("    sudo pacman -S --needed ansible sops", text)
        self.assertFalse([argv for argv in term.ran + term.interactive_ran if argv[0] == "sudo"], "the desktop never runs sudo")
        key = Path(os.environ["XDG_CONFIG_HOME"]) / "sops/age/keys.txt"
        self.assertTrue(key.exists())
        self.assertIn("Keep this file safe", text)
        self.assertIn("SHA256:TestFingerprintOnly", text)
        self.assertIn(HOST_KEY, (self.home / ".ssh/known_hosts").read_text())
        known = str(self.home / ".ssh/known_hosts")
        self.assertEqual(term.interactive_ran, [["ssh-copy-id", "-i", str(self.home / ".ssh/id_ed25519.pub"), "-o", "UserKnownHostsFile=" + known,
                                                 "-o", "StrictHostKeyChecking=yes", "-p", "22", "tester@box.example.org"]])
        self.assertIn("    tester ALL=(ALL) NOPASSWD: ALL", text)
        self.assertIn("    sudo visudo -f /etc/sudoers.d/bromigos-lab", text)
        self.assertEqual(term.waits, 2)
        self.assertIn("  Spare disk: 4 TB HDD (WDC WD40EFRX-68N32N0), empty, not mounted", term.out)
        self.assertIn("Recommended: Core", text)
        self.assertIn("  1. /mnt/nas/lab-backups  (/mnt/nas: a NAS share, 3.2 TB free)", term.out)
        self.assertIn("The empty 4 TB HDD (sda) could hold backups. To use it, format and", text)
        self.assertIn("/mnt/nas/lab-backups", self.box.folders)
        plan = json.loads((self.repo / "plan.json").read_text())
        self.assertEqual(plan["backup_path"], "/mnt/nas/lab-backups")
        self.assertEqual(plan["age_recipient"], "age1testrecipient")
        self.assertEqual(plan["target"]["ssh"], "tester@box.example.org")
        self.assertEqual(plan["target"]["known_hosts"], known)
        self.assertEqual(plan["target"]["identity"], str(self.home / ".ssh/id_ed25519"))
        self.assertEqual(subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True, text=True).stdout, "")
        self.assertEqual(self.applied[0][0], self.repo)
        self.assertEqual(self.applied[0][1]["distribution"], "debian")
        self.assertEqual(term.answers, [])
        state = json.loads(G.state_path().read_text())
        self.assertTrue(state["applied"])
        self.assertNotIn("AGE-SECRET", G.state_path().read_text())

    def test_second_run_skips_what_is_done(self):
        self.box.sudo = True
        self.assertEqual(self.guide(Term(self.box, self.fresh_answers())).run(), 0)
        again = Term(self.box, [])
        self.assertEqual(self.guide(again).run(), 0)
        text = again.text()
        for done in ("✓ Ansible, sops, age", "✓ Age key:", "✓ The box: tester@box.example.org (from last time)", "✓ SSH works",
                     "✓ Python 3 is there", "✓ Preset: Core (chosen last time)", "✓ Backups: /mnt/nas/lab-backups (from last time)",
                     "is up to date"):
            self.assertIn(done, text)
        self.assertFalse([line for line in again.out if line.startswith("? ")], "a finished step asked again")
        self.assertFalse(again.interactive_ran)
        self.assertEqual(len(self.applied), 2)

    def test_a_refused_fingerprint_stops_without_trusting_it(self):
        term = Term(self.box, ["yes", "no", "box.example.org", "tester", "", "no"])
        with self.assertRaises(G.Stop):
            self.guide(term).run()
        self.assertFalse((self.home / ".ssh/known_hosts").exists())
        self.assertEqual(json.loads(G.state_path().read_text())["host"], "box.example.org")
        self.assertFalse(term.interactive_ran)

    def test_a_changed_host_key_stops(self):
        (self.home / ".ssh/known_hosts").write_text(HOST_KEY + "\n")
        self.box.host_key = "box.example.org ssh-ed25519 AAAADifferent"
        term = Term(self.box, ["yes", "no", "box.example.org", "tester", ""])
        with self.assertRaises(G.Stop) as stop:
            self.guide(term).run()
        self.assertIn("CHANGED", str(stop.exception))

    def test_declined_ssh_copy_id_and_missing_python(self):
        (self.home / ".ssh/known_hosts").write_text(HOST_KEY + "\n")
        term = Term(self.box, ["yes", "no", "box.example.org", "tester", "2222", "no"])
        with self.assertRaises(G.Stop) as stop:
            self.guide(term).run()
        self.assertIn("ssh-copy-id -i", str(stop.exception))
        self.assertFalse(term.interactive_ran)
        self.box.key_installed, self.box.python = True, False
        term = Term(self.box, [])
        with self.assertRaises(G.Stop):
            self.guide(term).run()
        self.assertIn("    sudo apt install python3", term.out)

    def test_bad_answers_are_asked_again(self):
        self.box.sudo, self.box.key_installed = True, True
        (self.home / ".ssh/known_hosts").write_text(HOST_KEY + "\n")
        answers = ["yes", "no", "-oProxyCommand", "tester", "", "box.example.org", "tester", "", "huge", "core", "relative/path", "2", "yes", str(self.repo), "no"]
        term = Term(self.box, answers)
        self.assertEqual(self.guide(term).run(), 0)
        self.assertIn("  Use user@host for the SSH target. Try again.", term.out)
        self.assertIn("  Use an absolute folder path on the box, without spaces or quotes.", term.out)
        self.assertEqual(json.loads((self.repo / "plan.json").read_text())["backup_path"], "/srv/data/lab-backups")
        self.assertIn("  Review and commit it yourself before you change the plan again.", term.out)

    def test_a_folder_with_other_files_is_refused(self):
        self.box.sudo, self.box.key_installed = True, True
        (self.home / ".ssh/known_hosts").write_text(HOST_KEY + "\n")
        self.repo.mkdir()
        (self.repo / "notes.txt").write_text("someone's notes")
        term = Term(self.box, ["yes", "no", "box.example.org", "tester", "", "", "1", "yes", str(self.repo)])
        with self.assertRaises(G.Stop):
            self.guide(term).run()
        self.assertEqual(sorted(p.name for p in self.repo.iterdir()), ["notes.txt"])

    def test_start_over_and_no_arguments_route_here(self):
        G.state_path().parent.mkdir(parents=True)
        G.state_path().write_text('{"host": "old.example.org"}')
        with mock.patch.object(G.Guide, "run", return_value=0) as run:
            self.assertEqual(P.main(["--guided", "--start-over"]), 0)
            self.assertEqual(P.main([]), 0)
        self.assertEqual(run.call_count, 2)
        self.assertFalse(G.state_path().exists())

    # Step 3 offers the machines Find my lab found that answer SSH, after the same yes.
    def box_step(self, answers):
        term = Term(self.box, answers)
        guide = self.guide(term)
        guide.box()
        return term, json.loads(G.state_path().read_text())

    def test_a_no_is_todays_step(self):
        term, state = self.box_step(["no", "box.example.org", "tester", ""])
        self.assertEqual(self.found, [])                                  # nothing read without the yes
        self.assertIn("devices that announce themselves", term.text())
        self.assertEqual(state["host"], "box.example.org")

    def test_pick_a_found_machine(self):
        self.boxes = [{"ssh": "nas.example.org", "addresses": ["192.0.2.10"], "kind": "lab machine", "sources": ["mdns", "dns"]},
                      {"ssh": "198.51.100.7", "addresses": ["198.51.100.7"], "kind": "lab machine", "sources": ["mdns"]}]
        term, state = self.box_step(["yes", "2", "tester", ""])
        self.assertEqual(self.found, [1])
        self.assertIn("    1. nas.example.org  192.0.2.10  (lab machine; seen by mDNS, DNS)", term.out)
        self.assertIn("    3. Type an address", term.out)
        self.assertEqual((state["host"], state["user"], state["port"]), ("198.51.100.7", "tester", 22))
        self.assertEqual(term.answers, [])

    def test_type_an_address_instead(self):
        self.boxes = [{"ssh": "nas.example.org", "addresses": ["192.0.2.10"], "kind": "lab machine", "sources": ["mdns"]}]
        term, state = self.box_step(["yes", "", "box.example.org", "tester", ""])   # Enter: the last choice
        self.assertEqual(state["host"], "box.example.org")

    def test_nothing_found_asks_for_the_address(self):
        term, state = self.box_step(["yes", "box.example.org", "tester", ""])
        self.assertIn("No machine it found answers SSH", term.text())
        self.assertEqual(state["host"], "box.example.org")
