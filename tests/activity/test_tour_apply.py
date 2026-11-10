"""The Server tour's apply step (bin/bromigos-welcome-console, "Run") as a job: it prints and
returns what it did before it was one, it leaves a record whose steps are the plan's items,
and in a unit of its own (a stand-in systemd-run) it finishes with the tour gone. A stand-in
engine (fixtures/provision-engine) and a stand-in root: nothing is installed, nothing real runs."""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake import FakeMachine, FIXTURES, REPO  # noqa: E402

TOUR = REPO / "bin/bromigos-welcome-console"
ENGINE = FIXTURES / "provision-engine"
ITEMS = ["jellyfin", "smb-shares", "backups"]


def as_it_was(argv, env):
    """What the apply step did before it was a job (bin/bromigos-welcome-console at 0723d4d):
    run the engine's apply itself and print each ::stage, ::item, ::note and ::error line its
    way. Returns (exit status, what it printed)."""
    p = subprocess.Popen(argv + ["--apply", "--json"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    out = []

    def on_line(kind, a, w):
        out.append(f"{kind} {a if a is not None else ''} {w}".strip())

    for line in p.stdout:
        line = line.rstrip("\n")
        m = re.match(r"^::stage (\d+) (.*)$", line)
        if m:
            on_line("stage", int(m.group(1)), m.group(2))
            continue
        m = re.match(r"^::item (\S+) (\S+)(?: (.*))?$", line)
        if m:
            on_line("item", m.group(1), m.group(2) + (f" {m.group(3)}" if m.group(3) else ""))
            continue
        m = re.match(r"^::note (\S+) (.*)$", line)
        if m:
            on_line("note", m.group(1), m.group(2))
            continue
        m = re.match(r"^::error (.*)$", line)
        if m:
            on_line("error", None, m.group(1))
    p.stdout.close()
    return p.wait(), out


class TourApply(unittest.TestCase):
    systemd = False

    def setUp(self):
        self.m = FakeMachine(systemd=self.systemd)
        self.addCleanup(self.m.close)
        self.answers = self.m.tmp / "install-answers.toml"
        self.answers.write_text("[server]\nroles = [\"media\"]\nprovision = " + json.dumps(ITEMS) + "\n")
        self.env = dict(self.m.environ, BROMIGOS_PROVISION_CMD=str(ENGINE), BROMIGOS_INSTALL_ANSWERS=str(self.answers))
        self.applied = self.m.root / "var/lib/bromigos/provision/applied.json"

    def tour(self, *args, env=None):
        r = subprocess.run([sys.executable, str(TOUR), *args], env=dict(self.env, **(env or {})), capture_output=True,
                           text=True, timeout=120, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout.splitlines(), r.stderr

    def engine(self, env=None):
        return as_it_was([str(ENGINE), "lab", "provision", "--local", "--from-answers", str(self.answers)], dict(self.env, **(env or {})))

    def test_it_does_what_it_did(self):
        was_code, was = self.engine()
        installed = self.applied.read_text()
        self.applied.unlink()
        code, out, err = self.tour("--provision", "apply")
        self.assertEqual((code, err), (was_code, ""))
        self.assertEqual(out, was)                                    # line for line
        self.assertEqual(out[0], "item jellyfin waiting")
        self.assertEqual(out[-2:], ["stage 100 Done", "note secrets 2 keys stored on this server, encrypted with its TPM chip and host key"])
        self.assertEqual(self.applied.read_text(), installed)         # and the same things set up
        # the design's "done means": the run is listed, with its items as steps
        [rec] = self.m.listed()
        self.assertEqual((rec["kind"], rec["title"], rec["state"], rec["pct"]), ("app.install", "Setting up this server", "succeeded", 100))
        self.assertEqual(rec["subject"], {"type": "server", "id": "this", "name": "This server"})
        self.assertEqual([(s["id"], s["state"]) for s in rec["steps"]], [(i, "done") for i in ITEMS])
        self.assertEqual(rec["command"], [str(ENGINE), "lab", "provision", "--local", "--from-answers", str(self.answers), "--apply", "--json"])
        self.assertEqual(self.m.calls() if not self.systemd else [c.split()[0] for c in self.m.calls()],
                         [] if not self.systemd else ["systemd-run"])  # no password asked in a stand-in root

    def test_a_failure_is_the_same_failure(self):
        fail = {"ENGINE_FAIL": "smb-shares"}
        was_code, was = self.engine(fail)
        code, out, err = self.tour("--provision", "apply", env=fail)
        self.assertEqual((code, out), (was_code, was))
        self.assertEqual(code, 1)
        self.assertIn("error  smb-shares Smb Shares: couldn't download example.org/smb-shares:1 (podman stopped with code 1)", out)
        [rec] = self.m.listed()
        self.assertEqual((rec["state"], rec["exit_code"], rec["error"]["step"]), ("failed", 1, "smb-shares"))
        self.assertEqual([s["state"] for s in rec["steps"]], ["done", "failed", "done"])

    def test_the_plan_is_untouched(self):
        code, out, err = self.tour("--provision", "plan")
        self.assertEqual(code, 0, err)
        self.assertEqual([i["id"] for i in json.loads("\n".join(out))["items"]], ITEMS)
        self.assertEqual(self.m.listed(), [])                         # a plan changes nothing, so it's no job


class TourApplyInItsOwnUnit(TourApply):
    """Where systemd runs, the apply is a unit of its own."""
    systemd = True

    def test_it_finishes_with_the_tour_gone(self):
        gate = self.m.tmp / "go"
        p = subprocess.Popen([sys.executable, str(TOUR), "--provision", "apply"], env=dict(self.env, ENGINE_GATE=str(gate)),
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, stdin=subprocess.DEVNULL,
                             start_new_session=True)
        self.addCleanup(p.stdout.close)
        self.assertEqual(p.stdout.readline(), "item jellyfin waiting\n")
        os.killpg(p.pid, 9)                                           # the terminal closed: the tour and what it started
        p.wait()
        [rec] = self.m.listed()
        self.assertEqual((rec["state"], rec["unit"]), ("running", f"bromigos-job-{rec['id']}.service"))
        self.assertFalse(self.applied.exists())
        gate.write_text("")
        done = self.m.wait(lambda: [r for r in self.m.listed() if r["state"] == "succeeded"])
        self.assertEqual([(s["id"], s["state"]) for s in done[0]["steps"]], [(i, "done") for i in ITEMS])
        self.assertEqual([i["id"] for i in json.loads(self.applied.read_text())], ITEMS)


if __name__ == "__main__":
    unittest.main()
