"""What the package installs agrees with itself: the commands people run (`bromigos server board
code|sessions`), the units, the Caddy site and its private-address rule. `caddy adapt` checks the
site where Caddy is installed (CI installs it)."""
import contextlib
import io
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import BOARD, REPO, Root, caddy

from bromigos_board import actions, auth, net, paths

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


def unit_lines(name, key):
    """Every value a unit gives `key` (it may give several)."""
    return [line.split("=", 1)[1].strip() for line in (UNITS / name).read_text().splitlines()
            if line.split("=", 1)[0].strip() == key and not line.startswith("#")]


def tmpfiles():
    """{path: (type, mode, user, group)} from the package's tmpfiles text."""
    out = {}
    for line in (BOARD / "bromigos-board.tmpfiles").read_text().splitlines():
        if line and not line.startswith("#"):
            kind, path, mode, user, group = line.split()[:5]
            out[path] = (kind, mode, user, group)
    return out


class UnitTests(unittest.TestCase):
    def test_the_api_is_its_own_user_on_a_socket_only_caddy_opens(self):
        s, svc = unit("bromigos-board.socket"), unit("bromigos-board.service")
        self.assertEqual(s["ListenStream"], "/run/bromigos-board.sock")
        self.assertEqual((s["SocketGroup"], s["SocketMode"]), ("caddy", "0660"))
        self.assertEqual((svc["User"], svc["Group"]), (paths.USER, paths.USER))
        self.assertEqual(svc["ExecStart"], "/usr/lib/bromigos/board/bromigos-board serve")
        self.assertEqual(svc["NoNewPrivileges"], "yes")
        self.assertEqual(svc["CapabilityBoundingSet"], "")
        self.assertEqual(svc["RestrictAddressFamilies"], "AF_UNIX AF_NETLINK")     # netlink: the lab interface's addresses
        self.assertEqual(svc["ProtectSystem"], "strict")

    def test_the_api_writes_only_its_own_folder_and_the_two_files_it_marks(self):
        """Never /run/bromigos-board itself: that is where root writes."""
        writable = set(" ".join(unit_lines("bromigos-board.service", "ReadWritePaths")).split())
        # ... and its own folder of requests for root's helper (test_actions.py)
        self.assertEqual(writable, {paths.STATE, paths.WANTED, paths.DOOR, "/run/bromigos-board/requests"})
        self.assertNotIn(paths.RUN, writable)
        # /run is named read-only outright: ProtectSystem=strict alone leaves it writable on some
        # systemd versions (board-integration.sh tries it for real)
        self.assertEqual(unit("bromigos-board.service")["ReadOnlyPaths"], "/run")
        self.assertNotIn("/run/bromigos-board/results", writable)

    def test_the_api_is_bounded_and_cant_see_other_processes(self):
        svc = unit("bromigos-board.service")
        for key, want in (("MemoryMax", "256M"), ("TasksMax", "128"), ("ProtectProc", "invisible"), ("RemoveIPC", "yes"),
                          ("MemoryDenyWriteExecute", "yes"), ("IPAddressDeny", "any"), ("PrivateDevices", "yes"),
                          ("ProtectHome", "yes"), ("PrivateTmp", "yes"), ("LockPersonality", "yes"),
                          ("SystemCallArchitectures", "native"), ("RestrictSUIDSGID", "yes")):
            self.assertEqual(svc.get(key), want, key)
        self.assertEqual(unit_lines("bromigos-board.service", "SystemCallFilter"),
                         ["@system-service", "~@privileged @resources"])
        from bromigos_board import api, cli
        import inspect
        self.assertEqual(api.CONNECTIONS_MAX, 64)
        self.assertIn("limit_concurrency=api.CONNECTIONS_MAX", inspect.getsource(cli.cmd_serve))

    def test_the_reader_is_roots_sandboxed_and_starts_when_the_api_asks(self):
        svc = unit("bromigos-board-snapshot.service")
        self.assertEqual(unit_lines("bromigos-board-snapshot.path", "PathModified"), [paths.WANTED, paths.DOOR])
        self.assertEqual(unit("bromigos-board-snapshot.path")["Unit"], "bromigos-board-snapshot.service")
        self.assertNotIn("User", svc)
        self.assertEqual(svc["ExecStart"], "/usr/lib/bromigos/board/bromigos-board snapshot")
        for key, want in (("ProtectSystem", "full"), ("ProtectHome", "read-only"), ("PrivateTmp", "yes"),
                          ("NoNewPrivileges", "yes"), ("ProtectKernelModules", "yes"), ("RestrictSUIDSGID", "yes")):
            self.assertEqual(svc.get(key), want, key)

    def test_root_never_writes_where_the_boards_user_can(self):
        """The folders' owners and modes, from the package's tmpfiles text. /run/bromigos-board is
        root's and only read by the board's group; the files the API marks are made here, by
        root; the board's own folder is its user's, and closed to everyone else."""
        t = tmpfiles()
        self.assertEqual(t[paths.RUN], ("d", "0750", "root", "bromigos-board"))
        self.assertEqual(t[paths.WANTED], ("f", "0660", "root", "bromigos-board"))
        self.assertEqual(t[paths.DOOR], ("f", "0660", "root", "bromigos-board"))
        for d in (paths.STATE, paths.SESSIONS, paths.CODES):
            self.assertEqual(t[d], ("d", "0700", "bromigos-board", "bromigos-board"), d)
        # where root's reader writes, and nothing the board's user owns is above it
        self.assertEqual(os.path.dirname(paths.SNAPSHOT), paths.RUN)
        requests = "/run/bromigos-board/requests"       # the one folder under root's that is the board's: requests for the helper
        for path, (kind, mode, user, group) in t.items():
            if user != "root":
                self.assertTrue(path == requests or path == paths.STATE or path.startswith(paths.STATE + "/"), path)
            if path.startswith(paths.RUN) and kind == "d" and path != requests:
                self.assertEqual((user, int(mode, 8) & 0o022), ("root", 0), path)
        self.assertIn("u bromigos-board -", (BOARD / "bromigos-board.sysusers").read_text())

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze isn't installed")
    def test_systemd_reads_every_unit(self):
        """systemd's own check of the units' text: an unknown setting or a bad value is named."""
        with tempfile.TemporaryDirectory() as d:
            for f in UNITS.iterdir():
                # the command isn't installed here: the check is of the settings, not of the file it runs
                text = re.sub(r"^(ExecStart(?:Pre)?=[+-]*)\S+", r"\1/usr/bin/true", f.read_text(), flags=re.M)
                Path(d, f.name).write_text(text)
            r = subprocess.run(["systemd-analyze", "verify", "--man=no", "--recursive-errors=no", *sorted(str(p) for p in Path(d).iterdir())],
                               capture_output=True, text=True, timeout=120,
                               env=dict(os.environ, SYSTEMD_UNIT_PATH=f"{d}:", SYSTEMD_LOG_LEVEL="warning"))
            ours = [line for line in (r.stdout + r.stderr).splitlines() if d in line or "bromigos-board" in line]
            self.assertEqual(ours, [], r.stdout + r.stderr)


class RootStepsDown(Root):
    """`sudo bromigos server board code` and `sessions` work in the board's user's own folder: as
    that user, never as root, and never through a link planted where a folder should be."""

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, timeout=60)

    def victim(self):
        v = self.root / "etc" / "important"
        v.mkdir()
        for n in ("passwd", "shadow", "fstab"):
            (v / n).write_text("x\n")
        return v

    def test_codes_as_a_link_is_refused_and_nothing_is_deleted_or_made(self):
        v = self.victim()
        codes = self.path(paths.CODES)
        codes.rmdir()
        os.symlink(v, codes)
        r = self.run_cli("code")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("is a link, not a folder of its own", r.stderr)
        self.assertNotRegex(r.stdout, r"[A-Z2-9]{4}-[A-Z2-9]{4}")
        self.assertEqual(sorted(os.listdir(v)), ["fstab", "passwd", "shadow"])

    def test_sessions_as_a_link_too(self):
        v = self.victim()
        sessions = self.path(paths.SESSIONS)
        sessions.rmdir()
        os.symlink(v, sessions)
        for args in (("sessions",), ("sessions", "--end-all"), ("sessions", "--end", "0123456789abcdef"), ("code",)):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 3, args)
            self.assertEqual(sorted(os.listdir(v)), ["fstab", "passwd", "shadow"], args)

    def test_only_its_own_records_are_ever_removed(self):
        """Tidying up looks at the records' own names and nothing else."""
        codes = self.path(paths.CODES)
        (codes / "notes.txt").write_text("x")
        (codes / ("a" * 64 + ".json")).write_text("{}")                     # a record with no end: out of date
        (codes / ".x.tmp").write_text("half-written, just now")
        self.assertEqual(self.run_cli("code").returncode, 0)
        left = sorted(os.listdir(codes))
        self.assertIn("notes.txt", left)
        self.assertIn(".x.tmp", left)
        self.assertNotIn("a" * 64 + ".json", left)
        self.assertEqual(len(left), 3)

    def test_root_becomes_the_boards_user_before_it_touches_the_folder(self):
        from bromigos_board import cli
        import collections
        import pwd
        did = []
        Pw = collections.namedtuple("Pw", "pw_uid pw_gid pw_dir")
        note = lambda name: (lambda *a, **k: did.append((name, a)))            # noqa: E731
        with mock.patch.object(paths, "really_root", lambda: True), \
                mock.patch.object(pwd, "getpwnam", lambda name: Pw(987, 986, "/var/lib/bromigos-board")), \
                mock.patch.object(os, "setgroups", note("setgroups")), mock.patch.object(os, "setgid", note("setgid")), \
                mock.patch.object(os, "setuid", note("setuid")), mock.patch.object(os, "umask", note("umask")), \
                mock.patch.dict(os.environ), mock.patch.object(paths, "stand_in", lambda: False), \
                mock.patch.object(actions, "note_code", note("roots_note")), \
                mock.patch.object(auth, "new_code", lambda now, code: did.append(("new_code", ())) or ("AAAA-BBBB", 1)), \
                mock.patch.object(auth, "folder", side_effect=lambda *a, **k: did.append(("folder", a)) or contextlib.nullcontext()), \
                mock.patch.object(auth, "prune", note("prune")), mock.patch.object(auth, "sessions", lambda: []), \
                mock.patch.object(auth, "codes_waiting", lambda: []), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["code", "--json"]), 0)
            code_order = [name for name, _ in did]
            del did[:]
            self.assertEqual(cli.main(["sessions", "--json"]), 0)
            sessions_order = [name for name, _ in did]
        # no extra groups, then its group, then its user: and only then the folder
        # (root's own note of the code comes first, in root's own folder: test_actions.py)
        self.assertEqual(code_order, ["roots_note", "setgroups", "setgid", "setuid", "umask", "folder", "folder", "new_code"])
        self.assertEqual(sessions_order[:4], ["setgroups", "setgid", "setuid", "umask"])
        self.assertEqual(sessions_order[4], "folder")
        self.assertEqual(did[0], ("setgroups", ([],)))
        self.assertEqual((did[1], did[2]), (("setgid", (986,)), ("setuid", (987,))))

    def test_without_the_boards_user_root_does_nothing(self):
        from bromigos_board import cli
        import pwd

        def nobody(name):
            raise KeyError(name)
        with mock.patch.object(paths, "really_root", lambda: True), mock.patch.object(pwd, "getpwnam", nobody), \
                mock.patch.object(auth, "new_code", side_effect=AssertionError("as root: never")), \
                mock.patch.object(paths, "stand_in", lambda: False), mock.patch.object(actions, "note_code", lambda *a: None), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["code"]), 3)
        self.assertIn("no user bromigos-board", err.getvalue())

    def test_nothing_here_changes_a_files_owner(self):
        """The path-based chowns are gone with the step down: the board's user makes its own files."""
        for name in ("auth.py", "cli.py"):
            text = (BOARD / "lib" / "bromigos_board" / name).read_text()
            self.assertNotIn("chown(", text, name)



def tomllib_load(text):
    import tomllib
    return tomllib.loads(text)


class PackageTests(unittest.TestCase):
    def test_removing_the_package_takes_its_site_out_of_caddy_and_ends_the_sessions(self):
        text = (REPO / "packaging" / "bromigos-board" / "bromigos-board.install").read_text()
        remove = text.split("pre_remove() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("rm -f etc/caddy/conf.d/bromigos-board.caddy", remove)
        self.assertLess(remove.index("rm -f etc/caddy/conf.d/bromigos-board.caddy"), remove.index("systemctl reload caddy.service"))
        self.assertIn("var/lib/bromigos-board/sessions", remove)

    def upgrade(self, old_actions, toml, steps=("pre_upgrade", "post_upgrade")):
        """The package's install script, run as pacman runs it (in the root, its paths relative),
        in a stand-in root: the old package's library is there for pre_upgrade, then the new
        command for post_upgrade. old_actions: the old package's actions.py, or None for a board
        from before actions. Returns server.toml afterwards (None when there is none) and what
        the script printed."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        root = Path(tmp) / "root"
        old = root / "usr/lib/bromigos/lib/bromigos_board"
        old.mkdir(parents=True)
        (old / "__init__.py").write_text("")
        if old_actions is not None:
            (old / "actions.py").write_text(old_actions)
        if toml is not None:
            (root / "etc/bromigos").mkdir(parents=True)
            (root / "etc/bromigos/server.toml").write_text(toml)
        stubs = Path(tmp) / "bin"
        stubs.mkdir()
        for name in ("systemctl", "systemd-sysusers", "systemd-tmpfiles"):
            (stubs / name).write_text("#!/bin/sh\nexit 0\n")
            (stubs / name).chmod(0o755)
        script = REPO / "packaging" / "bromigos-board" / "bromigos-board.install"
        new_cmd = root / "usr/lib/bromigos/board/bromigos-board"
        out = []
        for step in steps:
            if step == "post_upgrade":       # the new package's files in place of the old ones
                shutil.rmtree(old.parent)
                new_cmd.parent.mkdir(parents=True)
                new_cmd.write_text(f"#!/bin/sh\nexec {sys.executable} -I {BOARD / 'bin' / 'bromigos-board'} \"$@\"\n")
                new_cmd.chmod(0o755)
            r = subprocess.run(["bash", "-c", f'. "{script}"; {step} 0.2-1 0.1-1'], cwd=root, capture_output=True, text=True,
                               env=dict(os.environ, PATH=f"{stubs}:/usr/bin:/bin", BROMIGOS_ROOT=str(root)))
            self.assertEqual(r.returncode, 0, r.stderr)
            out.append(r.stdout + r.stderr)
        self.assertFalse((root / "var/lib/bromigos-board-root/upgrade-actions").exists(), "the note is gone afterwards")
        p = root / "etc/bromigos/server.toml"
        return (p.read_text() if p.exists() else None), "".join(out)

    def actions_of(self, toml):
        import tomllib
        return tomllib.loads(toml).get("board", {}).get("actions")

    def test_an_upgrade_never_widens_what_the_page_may_do(self):
        """Review N5. A server whose server.toml doesn't say [board] actions keeps what the board
        allowed before the upgrade: nothing from a board from before actions, the four app words
        from one before the job actions. A new install gets the new default."""
        from bromigos_board import actions
        toml = "# mine\n[board]\ndoor = true\n\n[updates]\nwindow = \"03:00-05:00\"\n"
        after, said = self.upgrade(None, toml)
        self.assertEqual(self.actions_of(after), [])
        self.assertIn("# mine", after)
        self.assertIn('window = "03:00-05:00"', after)
        self.assertIs(tomllib_load(after)["board"]["door"], True)
        self.assertIn("kept what the board's page could do before this upgrade", said)
        before_jobs = 'DEFAULT_ACTIONS = ("restart", "add", "remove", "delete-data")\n'
        after, _ = self.upgrade(before_jobs, "[updates]\nauto = true\n")
        self.assertEqual(self.actions_of(after), ["restart", "add", "remove", "delete-data"])
        # the server's own list is its own; the same default, or no server.toml, changes nothing
        mine = '[board]\nactions = ["restart"]\n'
        self.assertEqual(self.upgrade(None, mine)[0], mine)
        same = "DEFAULT_ACTIONS = " + repr(tuple(actions.DEFAULT_ACTIONS)) + "\n"
        self.assertEqual(self.upgrade(same, "[updates]\nauto = true\n")[0], "[updates]\nauto = true\n")
        self.assertIsNone(self.upgrade(None, None)[0])
        # a new install: nothing written, so the new default holds
        self.assertEqual(self.upgrade(None, "[updates]\nauto = true\n", steps=("post_install",))[0], "[updates]\nauto = true\n")

    def test_the_kept_list_is_what_root_then_allows(self):
        from bromigos_board import actions
        after, _ = self.upgrade('DEFAULT_ACTIONS = ("restart", "add", "remove", "delete-data")\n', "[board]\n")
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "etc/bromigos").mkdir(parents=True)
        (root / "etc/bromigos/server.toml").write_text(after)
        with mock.patch.dict(os.environ, {"BROMIGOS_ROOT": str(root)}):
            self.assertEqual(actions.allowed_verbs(), ["restart", "add", "remove", "delete-data"])
            self.assertNotIn("job.answer", actions.allowed_verbs())

    def test_the_site_caddy_would_be_left_with_is_the_one_it_cant_read(self):
        """Why: the site imports a file of the package's. Without the file, Caddy refuses its whole
        configuration."""
        from bromigos_homelab import localprovision as L
        import types
        site = L.board_site(types.SimpleNamespace(hostname="myserver"))
        self.assertIn("import /usr/share/bromigos-board/caddy/site.caddy", site)
        self.assertIn("myserver.local, home-myserver.local {", site)


def walk(obj, pred):
    if pred(obj):
        yield obj
    for v in (obj.values() if isinstance(obj, dict) else obj if isinstance(obj, list) else []):
        yield from walk(v, pred)


class CaddyTests(unittest.TestCase):
    def ranges(self, matcher):
        line = next(x for x in SITE.read_text().splitlines() if x.startswith(matcher + " "))
        return [ipaddress.ip_network(x) for x in line.split("remote_ip", 1)[1].split()]

    def test_the_site_refuses_what_the_api_refuses(self):
        self.assertEqual(sorted(self.ranges("@bromigos_board_outside"), key=str),
                         sorted(net.PRIVATE + net.LAB_NETWORK, key=str))
        # the lab's private network's range is the one the API is asked about, each time
        self.assertEqual(self.ranges("@bromigos_board_lab_network"), net.LAB_NETWORK)

    def test_the_route_refuses_first_then_bounds_the_body_then_the_api_then_the_files(self):
        body = SITE.read_text().split("route {", 1)[1]
        order = [body.index(w) for w in ("respond @bromigos_board_outside", "request_body {\n\t\tmax_size 8KB",
                                         "forward_auth @bromigos_board_lab_network unix//run/bromigos-board.sock",
                                         "reverse_proxy /api/* unix//run/bromigos-board.sock",
                                         f"root @bromigos_board_page {paths.WEB}",
                                         "root * /usr/share/bromigos-board/placeholder", "file_server")]
        self.assertEqual(order, sorted(order))
        self.assertIn("uri /api/local", body)
        # both tell the API which of this server's addresses the connection came in at (net.is_private)
        for block in ("forward_auth @bromigos_board_lab_network", "reverse_proxy /api/*"):
            inner = body.split(block, 1)[1].split("\n\t}", 1)[0]
            self.assertIn("header_up X-Bromigos-Local {http.request.local.host}", inner, block)
        # a default: the API's own, stricter policy isn't replaced
        self.assertIn("?Content-Security-Policy \"default-src 'self';", body)
        self.assertIn("header @bromigos_board_home Strict-Transport-Security", body)
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
        refused, capped, asked, proxied, served = (
            flat.index('"status_code": 403'), flat.index('"request_body"'), flat.index('"uri": "/api/local"'),
            flat.index('"path": ["/api/*"]'), flat.index('"file_server"'))
        self.assertEqual([refused, capped, asked, proxied, served], sorted([refused, capped, asked, proxied, served]))
        self.assertEqual(flat.count("unix//run/bromigos-board.sock"), 2)
        cap = next(walk(route, lambda o: isinstance(o, dict) and o.get("handler") == "request_body"))
        self.assertLessEqual(cap["max_size"], 8192)
        nots = list(walk(route, lambda o: isinstance(o, dict) and "not" in o))
        self.assertEqual(len(nots), 1)
        got = [ipaddress.ip_network(x) for x in nots[0]["not"][0]["remote_ip"]["ranges"]]
        self.assertEqual(sorted(got, key=str), sorted(net.PRIVATE + net.LAB_NETWORK, key=str))
        # the question to the API is asked for the lab network's range, and only for it
        ask = next(walk(route, lambda o: isinstance(o, dict) and "handle" in o
                        and '"uri": "/api/local"' in json.dumps(o["handle"]) and "match" in o
                        and "remote_ip" in json.dumps(o["match"]) and "not" not in json.dumps(o["match"])))
        self.assertEqual([ipaddress.ip_network(x) for x in ask["match"][0]["remote_ip"]["ranges"]], net.LAB_NETWORK)
        # the policy is a default (set only when the answer has none), and HSTS is the home name's only
        csp = next(walk(route, lambda o: isinstance(o, dict) and o.get("handler") == "headers"
                        and "Content-Security-Policy" in json.dumps(o.get("response", {}).get("set", {}))))
        self.assertEqual(csp["response"]["require"], {"headers": {"Content-Security-Policy": None}})
        hsts = next(walk(route, lambda o: isinstance(o, dict) and "handle" in o
                         and "Strict-Transport-Security" in json.dumps(o["handle"]) and "match" in o
                         and "expression" in json.dumps(o["match"])))
        self.assertIn("home-", json.dumps(hsts["match"]))

if __name__ == "__main__":
    unittest.main()
