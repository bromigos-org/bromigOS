"""Field Kit as a BRODEC machine (machine_link): brodec-machine's own files read, the capability
file, starting the agent only through an approved proposal, and the phone's controls mapped to
Field Kit. Stand-ins for the agent, systemd-run and systemctl; nothing real starts."""
import json
import os
import shutil
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from bromigos_fieldkit import machine_link as ml, system, vector_tools as vt


class Link(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="fieldkit-machine-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "bin").mkdir()
        self.calls = self.d / "calls"
        for name in ("brodec-machine", "systemd-run", "systemctl", "herdr"):
            p = self.d / "bin" / name
            p.write_text(f'#!/bin/sh\necho "{name} $*" >> {self.calls}\n')
            p.chmod(0o755)
        (self.d / "data").mkdir()
        env = {"PATH": f"{self.d / 'bin'}:/usr/bin:/bin", "BROMIGOS_BRODEC_MACHINE_DATA": str(self.d / "data"),
               "BROMIGOS_BRODEC_MACHINE_CONFIG": str(self.d / "etc/machine.toml"), "BROMIGOS_BRODEC_MACHINE_USER": "root",
               "BROMIGOS_FIELDKIT_VECTOR_RUN": str(self.d / "run"), "BROMIGOS_FIELDKIT_VECTOR_AUDIT": str(self.d / "audit.log"),
               "BROMIGOS_VECTOR_SWITCH_ROOTS": str(self.d / "root")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        ml.CONFIG = str(self.d / "etc/machine.toml")
        vt.RUN, vt.QUEUE, vt.AUDIT = str(self.d / "run"), str(self.d / "run/approvals"), str(self.d / "audit.log")
        for q in (mock.patch.object(ml, "running", return_value=False), mock.patch.object(vt, "_target", return_value=None)):
            q.start()
            self.addCleanup(q.stop)

    def test_states_from_the_agents_own_files(self):
        self.assertEqual(ml.state()["state"], "stopped")
        code = {"user_code": "KPGGZFVT", "verification_uri": "https://auth.bromigos.org/device",
                "qr": "https://auth.bromigos.org/device?user_code=KPGGZFVT#machine=k1.ab&n=fieldkit",
                "fingerprint": "ab", "lab_name": "fieldkit", "expires_at_ms": int(time.time() * 1000) + 600000}
        (self.d / "data/pair-code.json").write_text(json.dumps(code))
        st = ml.state()
        self.assertEqual(st["state"], "waiting")
        self.assertEqual(st["code"]["user_code"], "KPGGZFVT")
        (self.d / "data/pairing.json").write_text(json.dumps({"lab_id": "m1", "owner": "@o:brodec.ai", "bot": "@m:x",
                                                               "name": "fieldkit", "fingerprint": "ab", "paired_at": 1}))
        st = ml.state()
        self.assertEqual(st["state"], "paired")
        self.assertNotIn("owner", st["paired"])           # only what the screen needs

    def test_capability_file_is_tight_and_parses(self):
        doc = tomllib.loads(ml.capability_file("box", server=False))
        self.assertEqual(doc["jobs"]["engines"], [])
        self.assertEqual(doc["remote_terminal"]["workspaces"], ["fieldkit"])
        self.assertTrue(doc["remote_terminal"]["phone_shells"])
        self.assertTrue(doc["system"]["enabled"])
        self.assertEqual(doc["system"]["actions"], ["restart", "shutdown"])        # a stick never updates itself
        self.assertFalse(doc["sessions"]["enabled"])
        self.assertFalse(doc["den"]["enabled"])
        server = tomllib.loads(ml.capability_file("box", server=True))
        self.assertEqual(server["system"]["actions"], ["restart", "shutdown", "update"])

    def test_write_capability_keeps_the_operators_file(self):
        self.assertTrue(ml.write_capability())
        Path(ml.CONFIG).write_text("# mine\n")
        self.assertFalse(ml.write_capability())
        self.assertEqual(Path(ml.CONFIG).read_text(), "# mine\n")

    def test_state_from_the_agents_pair_command(self):
        ev = {"event": "code", "kind": "machine", "name": "box", "user_code": "KPGGZFVT", "user_code_display": "KPGG-ZFVT",
              "verification_uri": "https://auth.bromigos.org/device", "qr": "https://x#machine=k1.ab&n=box",
              "qr_svg": "<svg/>", "qr_text": "##", "fingerprint": "ab", "expires_at_ms": 1}
        agent = self.d / "bin" / "brodec-machine"
        agent.write_text("#!/bin/sh\necho '" + json.dumps({"event": "waiting", "reason": "starting", "message": "m"}) + "'\n"
                         "echo '" + json.dumps(ev) + "'\n")
        st = ml.state()
        self.assertEqual(st["state"], "waiting")
        self.assertEqual(st["code"]["user_code_display"], "KPGG-ZFVT")
        self.assertEqual(st["code"]["lab_name"], "box")
        self.assertNotIn("qr_svg", st["code"])
        agent.write_text("#!/bin/sh\necho '" + json.dumps({"event": "paired", "kind": "machine", "name": "box", "id": "m1",
                                                           "owner": "@o:brodec.ai", "paired_at": 5}) + "'\n")
        st = ml.state()
        self.assertEqual(st["state"], "paired")
        self.assertNotIn("owner", st["paired"])
        agent.write_text("#!/bin/sh\necho '" + json.dumps({"event": "failed", "code": "no_capability_file", "message": "no file"}) + "'\n")
        st = ml.state()
        self.assertEqual((st["state"], st["configured"]), ("stopped", False))

    def test_pairing_starts_only_once_approved(self):
        p = vt.propose("pair_start", {})
        self.assertFalse(Path(ml.CONFIG).exists())
        self.assertFalse(self.calls.exists())
        vt.run(p["id"], by="local")
        self.assertTrue(Path(ml.CONFIG).exists())
        self.assertEqual(oct(Path(ml.CONFIG).stat().st_mode & 0o777), "0o644")
        self.assertIn("systemd-run --unit=brodec-machine-fieldkit", self.calls.read_text())

    def test_controls_map_to_field_kit(self):
        with mock.patch.object(system, "live_medium", return_value=True):
            ids = {c["id"]: c for c in ml.controls()}
            self.assertFalse(ids["update"]["available"])
            with self.assertRaises(system.Failed):
                vt.propose("control", {"action": "update"})
        p = vt.propose("control", {"action": "reboot"})
        self.assertEqual(p["confirm"], "reboot")
        self.assertIn("systemctl reboot", p["change"])
        t = vt.propose("control", {"action": "new_tab"})
        vt.run(t["id"])
        self.assertIn("herdr tab create", self.calls.read_text())
        vt.run(p["id"])
        self.assertIn("systemctl reboot", self.calls.read_text())


if __name__ == "__main__":
    unittest.main()
