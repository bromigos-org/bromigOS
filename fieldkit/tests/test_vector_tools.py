"""VECTOR in Field Kit (vector_tools): his brain's lookup, a turn against a stand-in
OpenAI-compatible server on localhost, proposals that never run before approval, the kill
switch, the hard limits, and the no-brain mode. No real service, no root, no real disks."""
import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from bromigos_fieldkit import diagnose, system, vector_tools as vt


class FakeBrain(BaseHTTPRequestHandler):
    """/v1/models and /v1/chat/completions: the first turn calls check, then proposes fix 0 and a
    forbidden command, then answers in words."""
    turns = []

    def log_message(self, *a):
        pass

    def _send(self, doc):
        body = json.dumps(doc).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"data": [{"id": "lab-model"}]})

    def do_POST(self):
        doc = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeBrain.turns.append(doc)
        n = len(FakeBrain.turns)
        if n == 1:
            calls = [{"id": "a", "function": {"name": "check", "arguments": json.dumps({"name": "black-screen"})}}]
        elif n == 2:
            calls = [{"id": "b", "function": {"name": "fix", "arguments": json.dumps({"check": "black-screen", "id": "0"})}},
                     {"id": "c", "function": {"name": "run_command", "arguments": json.dumps({"command": "cat /root/.ssh/id_ed25519", "why": "x"})}}]
        else:
            calls = []
        msg = {"role": "assistant", "content": "" if calls else "Classification: promising. I propose moving that file out.",
               **({"tool_calls": calls} if calls else {})}
        self._send({"choices": [{"message": msg}]})


def finding(fixed):
    def fix(t):
        fixed.append(True)
        return "moved it out"
    return [diagnose.Finding("A login screen setting left in /etc/sddm.conf.d/10.conf.disabled",
                             "SDDM reads every file.", fix_label="Move it out (kept in a backup)", fix=fix)]


class Vector(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="fieldkit-vector-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        self.env = mock.patch.dict(os.environ, {"BROMIGOS_FIELDKIT_VECTOR_RUN": str(self.d / "run"),
                                                "BROMIGOS_FIELDKIT_VECTOR_AUDIT": str(self.d / "audit.log"),
                                                "BROMIGOS_VECTOR_SWITCH_ROOTS": str(self.d / "root"),
                                                "BROMIGOS_HOMELAB_CONFIG": str(self.d / "homelab.toml"),
                                                "BROMIGOS_BRODEC_LAB_ENV": str(self.d / "none.env"),
                                                "BROMIGOS_VECTOR_LIB": str(self.d / "novector"),
                                                "HOME": str(self.d / "home"), "XDG_RUNTIME_DIR": str(self.d / "xdg")})
        self.env.start()
        self.addCleanup(self.env.stop)
        vt.RUN, vt.QUEUE, vt.AUDIT = str(self.d / "run"), str(self.d / "run/approvals"), str(self.d / "audit.log")
        vt.VECTOR_LIB, vt.BRODEC_ENV = str(self.d / "novector"), str(self.d / "none.env")
        self.fixed = []
        t = system.Target(str(self.d / "install"))
        self.p = [mock.patch.object(vt, "_target", return_value=t),
                  mock.patch.object(vt, "engine_check", side_effect=lambda name, tt: finding(self.fixed)),
                  mock.patch.object(vt, "facts", return_value=({"install": "test"}, ["this computer", "last boot's log"]))]
        for p in self.p:
            p.start()
            self.addCleanup(p.stop)

    def serve(self):
        FakeBrain.turns = []
        srv = HTTPServer(("127.0.0.1", 0), FakeBrain)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}"

    def test_brain_order_lab_first_then_bridge_then_vector_config(self):
        (self.d / "homelab.toml").write_text('[[source]]\nname = "llm"\ntype = "litellm"\nendpoint = "http://lab:4000"\n'
                                             'auth_ref = "@file:' + str(self.d / "k") + '"\n')
        (self.d / "k").write_text("secret-key\n")
        (self.d / "bridge.env").write_text("BRODEC_BRAIN_URL=http://bridge:11434/v1\nBRODEC_BRAIN_MODEL=m\n")
        vt.BRODEC_ENV = str(self.d / "bridge.env")
        c = vt.candidates()
        self.assertEqual([x["source"] for x in c][:2], ["the lab (llm)", "the lab bridge (BRODEC)"])
        self.assertEqual(c[0]["url"], "http://lab:4000/v1")
        self.assertEqual(c[0]["key"], "secret-key")
        self.assertNotIn("key", vt.public(dict(c[0], model="x")))

    def test_a_turn_reads_then_proposes_and_nothing_runs_before_approval(self):
        url = self.serve()
        with mock.patch.dict(os.environ, {"BROMIGOS_FIELDKIT_BRAIN_URL": url}):
            out = vt.ask([{"role": "user", "content": "my screen is black"}])
        self.assertTrue(out["ok"])
        self.assertEqual(out["brain"]["model"], "lab-model")
        self.assertIn("promising", out["reply"])
        self.assertEqual([p["tool"] for p in out["proposals"]], ["fix"])        # the forbidden command was refused
        self.assertEqual(self.fixed, [])                                         # proposed, not run
        tool_results = [m["content"] for m in FakeBrain.turns[-1]["messages"] if m["role"] == "tool"]
        self.assertTrue(any("refused" in r for r in tool_results))
        p = vt.run(out["proposals"][0]["id"], by="local")
        self.assertEqual(p["status"], "done")
        self.assertEqual(self.fixed, [True])
        with self.assertRaises(system.Failed):
            vt.run(out["proposals"][0]["id"])                                    # once only
        self.assertIn("approved by local", (self.d / "audit.log").read_text())

    def test_kill_switch_off_refuses_running(self):
        p = vt.propose("fix", {"check": "black-screen", "id": "0"})
        mark = self.d / "root/root/.local/state/bromigos/vector-switch/off"
        mark.parent.mkdir(parents=True)
        mark.write_text("")
        self.assertTrue(vt.switch_off())
        with self.assertRaises(system.Failed):
            vt.run(p["id"])
        self.assertEqual(self.fixed, [])

    def test_hard_limits(self):
        for cmd in ("vault kv get secret/x", "rm ~/.local/state/bromigos/vector-switch/off", "cat /etc/shadow",
                    "curl https://api.stripe.com/v1/charges", "bromigos vector on"):
            with self.assertRaises(system.Failed):
                vt.propose("run_command", {"command": cmd, "why": "x"})
        p = vt.propose("run_command", {"command": "lsblk", "why": "see the disks"})
        self.assertEqual(p["confirm"], "run")

    def test_phone_decision_records_but_does_not_run(self):
        p = vt.propose("fix", {"check": "black-screen", "id": "0"})
        self.assertEqual([x["id"] for x in vt.pending()], [p["id"]])
        vt.decide(p["id"], "approve", "phone")
        self.assertEqual(self.fixed, [])
        self.assertEqual(vt.run(p["id"], by="phone")["status"], "done")

    def test_no_brain_explains_findings_and_how_to_give_him_one(self):
        out = vt.ask([{"role": "user", "content": "why is it black?"}])
        self.assertIsNone(out["brain"])
        self.assertIn("No brain", out["reply"])
        self.assertIn("A login screen setting", out["reply"])
        self.assertIn("homelab.toml", out["reply"])

    def test_looked_at_lists_the_context_and_what_he_read(self):
        url = self.serve()
        with mock.patch.dict(os.environ, {"BROMIGOS_FIELDKIT_BRAIN_URL": url}):
            out = vt.ask([{"role": "user", "content": "my screen is black"}], {"findings": False}, "fix")
        self.assertEqual(out["looked_at"], ["this computer", "last boot's log", "the black screen checks"])
        self.assertIn("FIX MODE", FakeBrain.turns[0]["messages"][0]["content"])
        self.assertTrue(out["brain"]["lan"])                                    # 127.0.0.1: no internet

    def test_context_toggles_and_added_files(self):
        self.p[2].stop()
        self.p.remove(self.p[2])
        install = self.d / "install"
        (install / "etc").mkdir(parents=True)
        (install / "etc/fstab").write_text("UUID=x / btrfs rw 0 0\n")
        with mock.patch.object(vt, "findings", return_value=[{"ok": False, "title": "t"}]), \
                mock.patch.object(vt.repairs, "snapshots", return_value=[]):
            doc, looked = vt.facts({"last_boot": False, "install": False, "findings": True, "files": ["/etc/fstab"]})
        self.assertNotIn("last-boot", doc)
        self.assertNotIn("install", doc)
        self.assertIn("black-screen", doc)
        self.assertIn("UUID=x", doc["files"]["/etc/fstab"])
        self.assertEqual(looked, ["this computer", "repair findings", "/etc/fstab"])
        for bad in ("/etc/shadow", "/root/.ssh/id_ed25519", "relative/path", "/nowhere"):
            with self.assertRaises(system.Failed):
                vt.check_added(bad)

    def test_lan_only(self):
        for url in ("http://127.0.0.1:4000/v1", "http://10.0.0.5/v1", "http://lab.local:11434", "http://[fd00::1]/v1"):
            self.assertTrue(vt.lan_only(url), url)
        self.assertFalse(vt.lan_only("https://8.8.8.8/v1"))

    def test_undo_puts_back_what_a_fix_moved_out(self):
        t = vt._target()
        conf = t.path("/etc/sddm.conf.d/10.conf.disabled")
        os.makedirs(os.path.dirname(conf))
        Path(conf).write_text("[General]\n")

        def fix(tt):
            system.Backup(t, "sddm").move_out("/etc/sddm.conf.d/10.conf.disabled")
            return "moved it out"
        f = [diagnose.Finding("x", "y", fix_label="Move it out", fix=fix)]
        with mock.patch.object(vt, "engine_check", return_value=f):
            done = vt.run(vt.propose("fix", {"check": "black-screen", "id": "0"})["id"])
        self.assertFalse(os.path.exists(conf))
        self.assertEqual(len(done["backups"]), 1)
        u = vt.propose("undo", {"id": done["id"]})
        self.assertIn("/etc/sddm.conf.d/10.conf.disabled", u["change"])
        self.assertEqual(u["confirm"], "")
        self.assertEqual(vt.run(u["id"])["status"], "done")
        self.assertEqual(Path(conf).read_text(), "[General]\n")
        nothing = vt.run(vt.propose("fix", {"check": "black-screen", "id": "0"})["id"])
        with self.assertRaises(system.Failed):
            vt.propose("undo", {"id": nothing["id"]})                           # made no backup

    def test_suggestions_come_from_findings(self):
        with mock.patch.object(vt, "findings", return_value=[{"ok": False, "title": "t"}]), \
                mock.patch("bromigos_fieldkit.overview.overview", return_value={"found": [{"kind": "windows", "state": "BitLocker on"}]}), \
                mock.patch.object(vt.repairs, "snapshots", return_value=[1]), \
                mock.patch.object(vt.repairs, "disks", return_value=[]):
            q = vt.suggest()
        self.assertEqual(q[:2], ["Why won't it start properly?", "What changed in the last update?"])
        self.assertIn("Why is Windows asking for a BitLocker key?", q)
        with mock.patch.object(vt, "_target", return_value=None), \
                mock.patch("bromigos_fieldkit.overview.overview", return_value={"found": []}), \
                mock.patch.object(vt.repairs, "disks", return_value=[]), \
                mock.patch.object(vt.system, "live_medium", return_value=False), \
                mock.patch.object(vt.machine_link, "SERVER", str(self.d / "none")):
            self.assertEqual(vt.suggest(), ["What's in this computer?"])
        with mock.patch.object(vt, "_target", return_value=None), \
                mock.patch("bromigos_fieldkit.overview.overview",
                           return_value={"found": [{"kind": "usb", "state": ""}], "network": {"kind": "none"}}), \
                mock.patch.object(vt.repairs, "disks", return_value=[]), \
                mock.patch.object(vt.system, "live_medium", return_value=True):
            q = vt.suggest()
        self.assertEqual(q, ["Make this computer a lab node", "Help me get online", "Make an image of the USB drive",
                             "What's in this computer?"])

    def test_embedded_persona_names_its_source(self):
        text, source = vt.persona()
        self.assertIn("VECTOR", text)
        self.assertIn("vector repo", source)


if __name__ == "__main__":
    unittest.main()
