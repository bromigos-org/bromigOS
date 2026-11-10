"""The Server tour's "What's on this server" step (bin/bromigos-welcome-console, TOUR and
ROLE_TOUR) names commands, addresses and services for a person to type. Each one must be
real: a verb `bromigos server` has, a web name the lab's catalogue gives an app, a service one
of its templates makes. The tour's tables are read from its source, so nothing is started."""
import ast
import re
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake import REPO  # noqa: E402

TOUR = REPO / "bin/bromigos-welcome-console"
SERVER = REPO / "server/bromigos-server"
CATALOGUE = REPO / "homelab/share/provision-catalogue.toml"
QUADLETS = REPO / "homelab/share/quadlet"


def table(path, name):
    """A module-level NAME = literal from a source file, without running the file."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name} has no {name}")


class TourCommands(unittest.TestCase):
    def setUp(self):
        roles = table(TOUR, "ROLE_TOUR")
        self.rows = [(role, cmd) for role, rows in roles.items() for cmd, _, _ in rows]
        self.rows += [("every server", cmd) for cmd, _, _ in table(TOUR, "TOUR")]

    def test_every_bromigos_server_verb_is_one_the_command_has(self):
        text = SERVER.read_text()
        verbs = set(re.findall(r'add_parser\("([a-z-]+)"', text)) | {"role"}        # role add|remove: made in a loop
        seen = 0
        for role, cmd in self.rows:
            m = re.search(r"\bbromigos[ -]server (\S+)", cmd)
            if m:
                seen += 1
                self.assertIn(m.group(1), verbs, f"the tour's {role} line names `{cmd}`, and bromigos server has no {m.group(1)}")
        self.assertTrue(seen, "the tour names no bromigos server command: this test reads nothing")

    def test_every_web_address_is_a_name_the_engine_publishes(self):
        # each web app's name is its catalogue item's: web = { name, port }
        names = {i["web"]["name"] for i in tomllib.loads(CATALOGUE.read_text())["item"] if (i.get("web") or {}).get("name")}
        self.assertIn("home", names, "the catalogue names no start page: this test reads nothing")
        seen = 0
        for role, cmd in self.rows:
            m = re.match(r"https?://([^/]+)", cmd)
            if m:
                seen += 1
                self.assertRegex(m.group(1), r"^[a-z]+-\{host\}\.local$", f"the tour's {role} line: {cmd}")
                self.assertIn(m.group(1).split("-")[0], names, f"the tour's {role} line names {cmd}, and no app has that name")
        self.assertTrue(seen)

    def test_every_service_is_one_a_template_makes(self):
        units = {p.stem for p in QUADLETS.glob("*/*.container")}
        for role, cmd in self.rows:
            m = re.search(r"\bsystemctl \S+ (\S+)", cmd)
            if m:
                self.assertIn(m.group(1).removesuffix(".service"), units, f"the tour's {role} line: {cmd}")


if __name__ == "__main__":
    unittest.main()
