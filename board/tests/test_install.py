"""What the package installs agrees with itself: the commands people run (`bromigos server board
code|sessions`), the units, the Caddy site and its private-address rule. `caddy adapt` checks the
site where Caddy is installed (CI installs it)."""
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

from common import BOARD, REPO, Root, caddy

from bromigos_board import auth, net, paths

CLI = BOARD / "bin" / "bromigos-board"
SERVER = REPO / "server" / "bromigos-server"
SITE = BOARD / "caddy" / "site.caddy"
UNITS = BOARD / "systemd"


def unit(name):
    out = {}
    for line in (UNITS / name).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), v.strip())
    return out


class CommandTests(Root):
    def run_cli(self, *args, script=CLI, env=None):
        e = dict(os.environ, **(env or {}))
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env=e, timeout=60)

    def test_code_prints_a_one_time_code(self):
        r = self.run_cli("code")
        self.assertEqual(r.returncode, 0, r.stderr)
        m = re.search(r"\b([A-Z2-9]{4}-[A-Z2-9]{4})\b", r.stdout)
        self.assertTrue(m, r.stdout)
        self.assertIn("https://myserver.local", r.stdout)
        self.assertIn("10 minutes", r.stdout)
        self.assertTrue(auth.use_code(m.group(1)))
        self.assertFalse(auth.use_code(m.group(1)))
        files = os.listdir(self.path(paths.CODES))
        self.assertEqual(files, [])
        r = self.run_cli("code", "--json")
        d = json.loads(r.stdout)
        self.assertEqual(set(d), {"schema", "code", "expires_at"})
        name = os.listdir(self.path(paths.CODES))[0]
        self.assertNotIn(auth.normalise_code(d["code"]), name)          # kept as its hash
        self.assertEqual(oct(os.stat(self.path(f"{paths.CODES}/{name}")).st_mode & 0o777), "0o600")

    def test_sessions_lists_and_ends(self):
        r = self.run_cli("sessions")
        self.assertEqual(r.returncode, 0)
        self.assertIn("No browser is signed in", r.stdout)
        _, a = auth.new_session("Mozilla/5.0 (Windows NT 10.0) Chrome/140.0")
        _, b = auth.new_session("Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0")
        r = self.run_cli("sessions")
        self.assertIn("Chrome on Windows", r.stdout)
        self.assertIn("Firefox on Linux", r.stdout)
        d = json.loads(self.run_cli("sessions", "--json").stdout)
        self.assertEqual({s["id"] for s in d["sessions"]}, {a["id"], b["id"]})
        self.assertNotIn(a["hash"], json.dumps(d))
        r = self.run_cli("sessions", "--end", a["id"])
        self.assertEqual(r.returncode, 0)
        self.assertEqual([s["id"] for s in auth.sessions()], [b["id"]])
        r = self.run_cli("sessions", "--end", a["id"])
        self.assertEqual(r.returncode, 1)
        r = self.run_cli("sessions", "--end-all")
        self.assertIn("Signed out 1 browser.", r.stdout)
        self.assertEqual(auth.sessions(), [])

    def test_bromigos_server_board_runs_these_two_only(self):
        env = {"BROMIGOS_SERVER_ROOT": str(self.root), "BROMIGOS_BOARD_CLI": str(CLI)}
        r = self.run_cli("board", "code", "--json", script=SERVER, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("code", json.loads(r.stdout))
        r = self.run_cli("board", "sessions", script=SERVER, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        for verb in ("serve", "snapshot", "rm"):
            r = self.run_cli("board", verb, script=SERVER, env=env)
            self.assertEqual(r.returncode, 2, verb)
        r = self.run_cli("board", "code", script=SERVER, env=dict(env, BROMIGOS_BOARD_CLI=str(self.root / "none")))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't installed", r.stderr)

    def test_serve_only_from_its_socket(self):
        r = self.run_cli("serve", env={"LISTEN_FDS": ""})
        self.assertEqual(r.returncode, 3)
        self.assertIn("bromigos-board.socket", r.stderr)


class UnitTests(unittest.TestCase):
    def test_the_api_is_its_own_user_on_a_socket_only_caddy_opens(self):
        s, svc = unit("bromigos-board.socket"), unit("bromigos-board.service")
        self.assertEqual(s["ListenStream"], "/run/bromigos-board.sock")
        self.assertEqual((s["SocketGroup"], s["SocketMode"]), ("caddy", "0660"))
        self.assertEqual((svc["User"], svc["Group"]), (paths.USER, paths.USER))
        self.assertEqual(svc["ExecStart"], "/usr/lib/bromigos/board/bromigos-board serve")
        self.assertEqual(svc["NoNewPrivileges"], "yes")
        self.assertEqual(svc["CapabilityBoundingSet"], "")
        self.assertEqual(svc["RestrictAddressFamilies"], "AF_UNIX")
        self.assertEqual(svc["ProtectSystem"], "strict")
        self.assertEqual(set(svc["ReadWritePaths"].split()), {paths.STATE, paths.RUN})

    def test_the_snapshot_is_roots_and_starts_when_the_api_asks(self):
        p, svc = unit("bromigos-board-snapshot.path"), unit("bromigos-board-snapshot.service")
        self.assertEqual(p["PathModified"], paths.WANTED)
        self.assertEqual(p["Unit"], "bromigos-board-snapshot.service")
        self.assertNotIn("User", svc)
        self.assertEqual(svc["ExecStart"], "/usr/lib/bromigos/board/bromigos-board snapshot")

    def test_tmpfiles_and_sysusers(self):
        t = (BOARD / "bromigos-board.tmpfiles").read_text()
        for line in (f"d {paths.RUN} 0750 bromigos-board bromigos-board -", f"d {paths.STATE} 0700 bromigos-board bromigos-board -",
                     f"d {paths.SESSIONS} 0700", f"d {paths.CODES} 0700"):
            self.assertIn(line, t)
        self.assertIn("u bromigos-board -", (BOARD / "bromigos-board.sysusers").read_text())


def walk(obj, pred):
    if pred(obj):
        yield obj
    for v in (obj.values() if isinstance(obj, dict) else obj if isinstance(obj, list) else []):
        yield from walk(v, pred)


class CaddyTests(unittest.TestCase):
    def ranges(self):
        line = next(x for x in SITE.read_text().splitlines() if x.startswith("@bromigos_board_outside"))
        return [ipaddress.ip_network(x) for x in line.split("remote_ip", 1)[1].split()]

    def test_the_site_refuses_what_the_api_refuses(self):
        self.assertEqual(sorted(self.ranges(), key=str), sorted(net.PRIVATE, key=str))

    def test_the_route_refuses_first_then_the_api_then_the_files(self):
        body = SITE.read_text().split("route {", 1)[1]
        order = [body.index(w) for w in ("respond @bromigos_board_outside", "reverse_proxy /api/* unix//run/bromigos-board.sock",
                                         f"root @bromigos_board_page {paths.WEB}",
                                         "root * /usr/share/bromigos-board/placeholder", "file_server")]
        self.assertEqual(order, sorted(order))
        self.assertIn("Content-Security-Policy \"default-src 'self';", body)
        self.assertIn(" 403\n", body)

    @unittest.skipUnless(caddy() or os.environ.get("BOARD_NEED_CADDY"), "caddy isn't installed (CI installs it)")
    def test_caddy_reads_it(self):
        self.assertTrue(caddy(), "BOARD_NEED_CADDY is set, and caddy isn't installed")
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "Caddyfile")
            with open(f, "w") as fh:
                fh.write("{\n\tadmin off\n}\n\nmyserver.local, home-myserver.local {\n\ttls internal\n"
                         f"\timport {SITE}\n}}\n")
            r = subprocess.run([caddy(), "adapt", "--config", f, "--adapter", "caddyfile"], capture_output=True,
                               text=True, timeout=60, env=dict(os.environ, HOME=d, XDG_DATA_HOME=d, XDG_CONFIG_HOME=d))
            self.assertEqual(r.returncode, 0, r.stderr)
            doc = json.loads(r.stdout)
        server = next(iter(doc["apps"]["http"]["servers"].values()))
        route = next(rt for rt in server["routes"] if "myserver.local" in json.dumps(rt.get("match", [])))
        self.assertEqual(sorted(route["match"][0]["host"]), ["home-myserver.local", "myserver.local"])
        flat = json.dumps(route)
        refused, proxied, served = (flat.index('"status_code": 403'), flat.index('"reverse_proxy"'),
                                    flat.index('"file_server"'))
        self.assertLess(refused, proxied)
        self.assertLess(proxied, served)
        self.assertIn("unix//run/bromigos-board.sock", flat)
        nots = list(walk(route, lambda o: isinstance(o, dict) and "not" in o))
        self.assertEqual(len(nots), 1)
        got = [ipaddress.ip_network(x) for x in nots[0]["not"][0]["remote_ip"]["ranges"]]
        self.assertEqual(sorted(got, key=str), sorted(net.PRIVATE, key=str))


if __name__ == "__main__":
    unittest.main()
