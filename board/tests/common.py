"""What the board's tests share: a stand-in root (BROMIGOS_ROOT), the fixtures' stand-in
`bromigos` on PATH, and the checkout's libraries. No root, no network, no socket, nothing on this
machine changes."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOARD = HERE.parent
REPO = BOARD.parent
FIXTURES = HERE / "fixtures"
for p in (BOARD / "lib", REPO / "lib", REPO / "homelab" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

LAN = "192.168.1.20"           # a browser on the home network, as Caddy reports it
NOW = 1794290000000             # 2026-11-10, in ms


class Root(unittest.TestCase):
    """Each test in a fresh stand-in root, with the fixtures' `bromigos` first on PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock_env({
            "BROMIGOS_ROOT": str(self.root),
            "BROMIGOS_BOARD_HOSTNAME": "myserver",
            "BOARD_FIXTURES": str(FIXTURES),
            "BOARD_MISSING": "",
            "PATH": f"{FIXTURES}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "BROMIGOS_PROVISION_CATALOGUE": str(REPO / "homelab" / "share" / "provision-catalogue.toml"),
            "BROMIGOS_BOARD_NOW_MS": None,
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)
        for d in ("run/bromigos-board", "var/lib/bromigos-board/sessions", "var/lib/bromigos-board/codes", "etc/bromigos"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        # as tmpfiles leaves them (bromigos-board.tmpfiles): the two files the API marks, made
        # already and long ago
        for f in ("wanted", "door"):
            p = self.root / "run/bromigos-board" / f
            p.touch()
            os.utime(p, (1, 1))

    def path(self, rel):
        return self.root / rel.lstrip("/")


class mock_env:
    """os.environ with these keys set (None: removed), put back afterwards."""

    def __init__(self, values):
        self.values = values
        self.saved = {}

    def start(self):
        for k, v in self.values.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def stop(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def caddy():
    return shutil.which("caddy")
