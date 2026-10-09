"""Running one of the commands Settings drives (desktop/bin/bromigos-<name>) the way the
tests do: a throwaway home and runtime directory, the stand-ins (fixtures/bin: pactl, nmcli,
…, and a `bromigos` that routes to desktop/bin) first on PATH, their state in a temp dir,
no D-Bus. Nothing reaches the machine the tests run on.

    class T(CmdTest):
        def test_x(self):
            doc = self.cmd("sound", "volume", "output", "40")     # the --json document
            self.assertEqual(self.state("pactl")["sinks"][0]["volume"]…)
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
REPO = os.path.dirname(DESKTOP)
FIXTURES = os.path.join(HERE, "fixtures")


class CmdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bct-")
        self.home = os.path.join(self.tmp, "home")
        self.fx = os.path.join(self.tmp, "fixtures")
        run = os.path.join(self.tmp, "run")
        for d in (self.home, self.fx, run):
            os.makedirs(d)
        os.chmod(run, 0o700)
        self.env = {"HOME": self.home, "XDG_RUNTIME_DIR": run, "LANG": "C.UTF-8",
                    "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                    "XDG_STATE_HOME": os.path.join(self.home, ".local", "state"),
                    "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
                    "XDG_CACHE_HOME": os.path.join(self.home, ".cache"),
                    "PATH": f"{FIXTURES}/bin:{DESKTOP}/bin:/usr/bin",
                    "PYTHONPATH": os.path.join(DESKTOP, "lib"),
                    "BROMIGOS_SHARE_DIR": os.path.join(self.tmp, "share"),
                    # no installed manual unless a test makes one (bromigos_cli.manual_url)
                    "BROMIGOS_MANUAL_DIR": os.path.join(self.tmp, "manual"),
                    "BROMIGOS_FIXTURE_STATE": self.fx,
                    "DBUS_SESSION_BUS_ADDRESS": "disabled:", "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent"}
        share = os.path.join(self.tmp, "share")
        os.makedirs(share)
        os.symlink(os.path.join(REPO, "live"), os.path.join(share, "live"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cmd(self, name, *args, env=None):
        return subprocess.run([os.path.join(DESKTOP, "bin", f"bromigos-{name}"), *args, "--json"],
                              env=dict(self.env, **(env or {})), capture_output=True, text=True, timeout=60)

    def cmd(self, name, *args, ok=True, env=None):
        """The command's --json document; asserts ok (or that it refused, ok=False)."""
        r = self.run_cmd(name, *args, env=env)
        try:
            doc = json.loads(r.stdout)
        except ValueError:
            self.fail(f"bromigos {name} {' '.join(args)}: not JSON: {r.stdout!r} {r.stderr!r}")
        self.assertEqual(doc.get("ok", True), ok, doc)
        self.assertEqual(r.returncode == 0, ok, (r.returncode, doc))
        return doc

    def state(self, name):
        p = os.path.join(self.fx, name + ".json")
        if not os.path.exists(p):
            with open(os.path.join(FIXTURES, name + ".json")) as f:
                return json.load(f)
        with open(p) as f:
            return json.load(f)

    def calls(self, name):
        p = os.path.join(self.fx, name + ".log")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(x) for x in f]

    def path(self, *rel):
        return os.path.join(self.home, *rel)

    def read(self, *rel):
        try:
            with open(self.path(*rel)) as f:
                return f.read()
        except FileNotFoundError:
            return None
