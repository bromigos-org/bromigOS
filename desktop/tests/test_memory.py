"""`bromigos memory`: VECTOR's history and memory in a throwaway home: counted, exported
(only the user can read it), cleared into an archive (a running VECTOR's open database keeps
working) and put back."""
import http.server
import json
import os
import sqlite3
import stat
import threading
import unittest

from cmdtest import REPO, CmdTest

LINES = [
    {"t": "2026-10-08T09:00:00-0700", "role": "user", "text": "what's the weather"},
    {"t": "2026-10-08T09:00:05-0700", "role": "vector", "text": "Clear skies, Captain."},
    {"t": "2026-10-08T15:00:00-0700", "role": "user", "text": "build the deck"},
    {"t": "2026-10-08T15:00:02-0700", "role": "tool", "name": "build_start"},
    {"t": "2026-10-08T15:00:09-0700", "role": "vector", "text": "On it."},
]


class MemoryTest(CmdTest):
    def setUp(self):
        super().setUp()
        self.state = self.path(".local", "state", "bromigos")
        os.makedirs(self.state)
        with open(os.path.join(self.state, "vector-chat.log"), "w") as f:
            f.writelines(json.dumps(x) + "\n" for x in LINES)
        with open(os.path.join(self.state, "vector-sessions.json"), "w") as f:
            json.dump({"2026-10-08T09:00:00-0700": {"title": "Weather"}}, f)
        self.db = self.path(".local", "share", "bromigos", "vector-memory.sqlite")
        os.makedirs(os.path.dirname(self.db))
        db = sqlite3.connect(self.db)
        db.executescript("""
            CREATE TABLE notes (id INTEGER PRIMARY KEY, content TEXT NOT NULL, kind TEXT, created REAL, emb BLOB);
            CREATE VIRTUAL TABLE notes_fts USING fts5(content, content='notes', content_rowid='id');""")
        for i, text in enumerate(["the operator likes tea", "the lab's GPU is a 5090", "call him Captain"]):
            cur = db.execute("INSERT INTO notes (content, kind, created) VALUES (?, 'fact', ?)", (text, 1.7e9 + i))
            db.execute("INSERT INTO notes_fts (rowid, content) VALUES (?, ?)", (cur.lastrowid, text))
        db.commit()
        self.held = db                    # VECTOR's own connection, open all along

    def tearDown(self):
        self.held.close()
        super().tearDown()

    def test_status(self):
        d = self.cmd("memory")
        h, m = d["history"], d["memory"]
        self.assertEqual((h["messages"], h["conversations"]), (4, 2))
        self.assertEqual((h["first"], h["last"]), ("2026-10-08T09:00:00-0700", "2026-10-08T15:00:09-0700"))
        self.assertEqual((m["backend"], m["notes"], m["local"]), ("auto", 3, True))
        self.assertFalse(d["can_undo"])

    def test_a_plugin_store_is_left_to_the_plugin(self):
        os.makedirs(self.path(".config", "bromigos", "vector"))
        with open(self.path(".config", "bromigos", "vector", "vector.toml"), "w") as f:
            f.write('[memory]\nbackend = "gnosis"\n')
        d = self.cmd("memory")
        self.assertFalse(d["memory"]["local"])
        self.assertIn("gnosis", d["memory"]["note"])
        d = self.cmd("memory", "clear", "memory", "--yes", ok=False)
        self.assertIn("gnosis", d["error"])

    def test_export_is_private(self):
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        d = self.cmd("memory", "export", out)
        folder = d["folder"]
        self.assertEqual(sorted(os.listdir(folder)), ["vector-chat.log", "vector-memory.json", "vector-sessions.json"])
        self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o700)
        for f in os.listdir(folder):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(folder, f)).st_mode), 0o600)
        with open(os.path.join(folder, "vector-memory.json")) as f:
            self.assertEqual(len(json.load(f)["notes"]), 3)
        self.cmd("memory", "export", os.path.join(self.tmp, "nope"), ok=False)

    def test_clear_needs_yes(self):
        self.assertIn("--yes", self.cmd("memory", "clear", "history", ok=False)["error"])
        self.cmd("memory", "clear", "everything", "--yes", ok=False)
        self.assertTrue(os.path.exists(os.path.join(self.state, "vector-chat.log")))

    def test_clear_history_then_undo_keeps_what_came_after(self):
        d = self.cmd("memory", "clear", "history", "--yes")
        self.assertFalse(os.path.exists(os.path.join(self.state, "vector-chat.log")))
        self.assertTrue(d["can_undo"])
        self.assertEqual(d["history"]["messages"], 0)
        with open(os.path.join(self.state, "vector-chat.log"), "a") as f:       # he talks on
            f.write(json.dumps({"t": "2026-10-09T08:00:00-0700", "role": "user", "text": "morning"}) + "\n")
        d = self.cmd("memory", "undo")
        self.assertEqual(d["history"]["messages"], 5)
        self.assertEqual(d["history"]["last"], "2026-10-09T08:00:00-0700")
        self.assertFalse(d["can_undo"])
        self.cmd("memory", "undo", ok=False)

    def test_clear_memory_while_vector_holds_it_then_undo(self):
        d = self.cmd("memory", "clear", "memory", "--yes")
        self.assertEqual(d["memory"]["notes"], 0)
        # VECTOR's open connection still works: the index is empty and he can file a new note
        self.assertEqual(self.held.execute("SELECT count(*) FROM notes_fts WHERE notes_fts MATCH 'tea'").fetchone()[0], 0)
        cur = self.held.execute("INSERT INTO notes (content, kind, created) VALUES ('new note', 'fact', 1.8e9)")
        self.held.execute("INSERT INTO notes_fts (rowid, content) VALUES (?, 'new note')", (cur.lastrowid,))
        self.held.commit()
        archived = d["archived"]
        self.assertTrue(os.path.exists(os.path.join(archived, "vector-memory.sqlite")))
        self.assertTrue(os.path.exists(os.path.join(self.state, "vector-chat.log")))       # history untouched
        d = self.cmd("memory", "undo")
        self.assertEqual(d["memory"]["notes"], 4)
        self.assertEqual(self.held.execute("SELECT count(*) FROM notes_fts WHERE notes_fts MATCH 'tea'").fetchone()[0], 1)

    def test_clear_all(self):
        d = self.cmd("memory", "clear", "all", "--yes")
        self.assertEqual((d["history"]["messages"], d["memory"]["notes"]), (0, 0))
        self.assertEqual(d["last_clear"]["what"], "all")


class Gate(http.server.BaseHTTPRequestHandler):
    """A stand-in gnosis-gate: VECTOR's space, the read token lists, the write token
    deletes and files (the calls homelab_gnosis.py makes)."""

    def _doc(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _send(self, code, doc):
        b = json.dumps(doc).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _token(self, want):
        ok = self.headers.get("Authorization") == f"Bearer {want}"
        if not ok:
            self._send(401, {"error": "token"})
        return ok

    def do_POST(self):
        srv, d = self.server, self._doc()
        srv.calls.append(("POST", self.path, d))
        if self.path == "/v1/memories/list" and self._token("read-token"):
            assert d["scope"]["space_id"] == "vector" and d["scope"]["tenant_id"] == "home"
            ids = sorted(srv.notes)
            page, size = d["page"], d["page_size"]
            rows = [{"memory_id": i, "content": srv.notes[i][0], "metadata": {"kind": srv.notes[i][1]}}
                    for i in ids[(page - 1) * size:page * size]]
            self._send(200, {"results": rows, "total": len(ids)})
        elif self.path == "/v1/memories" and self._token("write-token"):
            srv.n += 1
            srv.notes[f"m{srv.n:03d}"] = (d["messages"][0]["content"], d["metadata"]["kind"])
            self._send(200, {"results": [{"memory_id": f"m{srv.n:03d}"}]})

    def do_DELETE(self):
        srv, d = self.server, self._doc()
        srv.calls.append(("DELETE", self.path, d))
        if self._token("write-token"):
            srv.notes.pop(self.path.rsplit("/", 1)[1], None)
            self._send(200, {"ok": True})

    def log_message(self, *_):
        pass


class GnosisMemoryTest(MemoryTest):
    """VECTOR's notes in the homelab's Gnosis (homelab.toml's gnosis source with both
    tokens, [memory] backend = "auto"): cleared there too, archived first, filed again by
    undo; nothing changes when the gate doesn't answer."""

    def setUp(self):
        super().setUp()
        self.gate = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gate)
        self.gate.notes = {f"m{i:03d}": (t, "fact") for i, t in enumerate(
            ["the lab has 4 GPUs", "he prefers Mire", "the deck is called the Wick", "tea, not coffee",
             "his callsign"])}
        self.gate.n, self.gate.calls = 100, []
        threading.Thread(target=self.gate.serve_forever, daemon=True).start()
        conf = self.path(".config", "bromigos")
        os.makedirs(conf, exist_ok=True)
        with open(os.path.join(conf, "homelab.toml"), "w") as f:
            f.write(f'[[source]]\nname = "gnosis"\ntype = "gnosis"\nendpoint = "http://127.0.0.1:{self.gate.server_port}"\n'
                    'auth_ref = "@env:GNOSIS_READ"\nwrite_auth_ref = "@env:GNOSIS_WRITE"\ntenant = "home"\n')
        self.mirror = self.path(".cache", "bromigos", "vector-memory.json")      # VECTOR's copy of the list
        os.makedirs(os.path.dirname(self.mirror))
        with open(self.mirror, "w") as f:
            json.dump([{"id": i, "content": t, "kind": k, "emb": [0.1]} for i, (t, k) in self.gate.notes.items()], f)
        self.env.update(GNOSIS_READ="read-token", GNOSIS_WRITE="write-token",
                        PYTHONPATH=self.env["PYTHONPATH"] + ":" + os.path.join(REPO, "homelab", "lib"))

    def tearDown(self):
        self.gate.shutdown()
        self.gate.server_close()
        super().tearDown()

    def test_status(self):
        m = self.cmd("memory")["memory"]
        self.assertEqual((m["backend"], m["store"], m["notes"], m["local"]), ("auto", "gnosis", 5, False))
        self.assertIn("Gnosis", m["note"])

    def test_clear_all(self):
        d = self.cmd("memory", "clear", "all", "--yes")
        self.assertEqual(self.gate.notes, {})
        self.assertIn("3 here, 5 in Gnosis", d["said"])
        self.assertEqual(self.held.execute("SELECT count(*) FROM notes").fetchone()[0], 0)
        archived = d["archived"]
        with open(os.path.join(archived, "gnosis-notes.json")) as f:
            self.assertEqual(len(json.load(f)["notes"]), 5)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(archived, "gnosis-notes.json")).st_mode), 0o600)
        self.assertFalse(os.path.exists(self.mirror))                             # kept with the archive
        self.assertTrue(os.path.exists(os.path.join(archived, "gnosis-mirror.json")))

    def test_clear_memory_while_vector_holds_it_then_undo(self):
        d = self.cmd("memory", "clear", "memory", "--yes")
        self.assertEqual(self.gate.notes, {})
        self.assertTrue(os.path.exists(os.path.join(self.state, "vector-chat.log")))       # history untouched
        dels = [c for c in self.gate.calls if c[0] == "DELETE"]
        self.assertEqual(len(dels), 5)
        self.assertTrue(all(c[2]["scope"]["space_id"] == "vector" for c in dels))
        d = self.cmd("memory", "undo")
        self.assertIn("5 notes in Gnosis", d["said"])
        self.assertEqual(sorted(t for t, _ in self.gate.notes.values()),
                         sorted(["the lab has 4 GPUs", "he prefers Mire", "the deck is called the Wick",
                                 "tea, not coffee", "his callsign"]))
        filed = [c[2] for c in self.gate.calls if c[:2] == ("POST", "/v1/memories")]
        self.assertTrue(all(f["infer"] is False and f["metadata"]["kind"] == "fact" for f in filed))
        self.assertEqual(self.held.execute("SELECT count(*) FROM notes").fetchone()[0], 3)
        self.assertFalse(d["can_undo"])

    def test_export_is_private(self):
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        folder = self.cmd("memory", "export", out)["folder"]
        with open(os.path.join(folder, "vector-memory.json")) as f:
            doc = json.load(f)
        self.assertEqual((doc["store"], len(doc["notes"])), ("gnosis", 8))       # this machine's 3, Gnosis's 5
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(folder, "vector-memory.json")).st_mode), 0o600)

    def test_a_gate_that_doesnt_answer_changes_nothing(self):
        self.gate.shutdown()
        self.gate.server_close()
        self.gate = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gate)      # for tearDown
        threading.Thread(target=self.gate.serve_forever, daemon=True).start()
        d = self.cmd("memory", "clear", "all", "--yes", ok=False)
        self.assertIn("didn't answer", d["error"])
        self.assertTrue(os.path.exists(os.path.join(self.state, "vector-chat.log")))
        self.assertEqual(self.held.execute("SELECT count(*) FROM notes").fetchone()[0], 3)
        self.assertFalse(self.cmd("memory")["can_undo"])

    def test_clear_needs_yes(self):
        super().test_clear_needs_yes()
        self.assertEqual(len(self.gate.notes), 5)

    # the local store's own tests: not this store's
    test_a_plugin_store_is_left_to_the_plugin = None
    test_clear_history_then_undo_keeps_what_came_after = None


if __name__ == "__main__":
    unittest.main()
