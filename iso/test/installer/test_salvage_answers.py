"""The salvage scan's answer file (`bromigos hw salvage --answers FILE`; docs/salvage.md) read
by the installer itself (common.read_answer_file, server.from_answer_file): the roles and the
apps it chose arrive preselected, and because the file names no disk and no password the
installer asks its questions instead of installing by itself.

The scans are of stand-in machines (homelab/tests/salvagefake.py): fake roots and recorded
tool outputs, never the machine the tests run on.

  python -m unittest discover -s iso/test/installer -p 'test_salvage_answers.py'
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import test_tui  # noqa: E402,F401  (the fake store, back end and environment)
REPO = os.path.normpath(os.path.join(HERE, "../../.."))
for p in (os.path.join(REPO, "homelab/tests"), os.path.join(REPO, "homelab/lib")):
    if p not in sys.path:
        sys.path.insert(0, p)
from bromigos_homelab import provcatalog as PC, salvage as S  # noqa: E402
from bromigos_installer import common, provision as PV, server  # noqa: E402
import salvagefake as F  # noqa: E402

ENV = {"BROMIGOS_HOMELAB_LIB": os.path.join(REPO, "homelab/lib"), "BROMIGOS_PROVISION_CATALOGUE": None,   # the real engine
       "BROMIGOS_INSTALLER_TPM": "0", "BROMIGOS_INSTALLER_UPS": "0", "BROMIGOS_INSTALLER_NVIDIA": "0"}
_SAVED, _PATCHES = {}, []


def setUpModule():
    for k, v in ENV.items():
        _SAVED[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    for p in (mock.patch.object(PC, "SHARE", "/nonexistent"),                   # the checkout's catalogue, not an installed one
              mock.patch.object(S.subprocess, "run", side_effect=AssertionError("a test ran a real tool"))):
        p.start()
        _PATCHES.append(p)
    PC._cache.clear()
    PV._ENGINE = None
    server._STORE = None


def tearDownModule():
    for p in _PATCHES:
        p.stop()
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    PC._cache.clear()
    PV._ENGINE = None
    PV.load(reload=True)


def scan(name):
    with tempfile.TemporaryDirectory() as tmp:
        root, run = F.build(tmp, F.MACHINES[name])
        return S.scan(root=root, run=run, euid=0, sleep=lambda s: None, clock=lambda: 0.0)


class Answers(unittest.TestCase):
    def read(self, doc):
        path = os.path.join(tempfile.mkdtemp(prefix="salvage-"), "install.toml")
        with open(path, "w") as f:
            f.write(S.answers_toml(doc))
        return common.read_answer_file(path)

    def test_the_installer_takes_the_choices_and_asks_the_rest(self):
        self.assertIs(PV.engine(), PC)
        for name in F.MACHINES:
            with self.subTest(machine=name):
                doc = scan(name)
                a, problems = self.read(doc)
                s = server.srv(a)
                self.assertEqual(a["edition"], "server")
                self.assertEqual(server.roles_of(s), doc["next"]["installer_roles"])
                self.assertEqual((s["lab"], s["provision"], s["provision_edited"]), ("none", doc["next"]["provision"], True))
                # every id is something the installer's catalogue step can tick
                self.assertEqual([i for i in s["provision"] if not PV.item(i)], [])
                # it names no disk, no password, no admin and no key, on purpose: so the installer asks
                # (tui.py: "has problems, so the installer asks instead"), and nothing is wrong with
                # the choices themselves
                self.assertTrue(any("no password" in p for p in problems), problems)
                self.assertTrue(any("disk must name the disk" in p for p in problems), problems)
                missing = ("no password", "mode must be", "disk must name the disk", "user: Choose a user name", "keys only needs a key")
                self.assertEqual([p for p in problems if not any(m in p for m in missing)], [])
                self.assertFalse(a.get("password") or a.get("disk"))
                # and what it preselects fits this machine by the installer's own meter
                self.assertTrue(PV.budget(s["provision"], doc["budget_hardware"])["fits"])

    def test_the_file_is_for_the_computer_that_was_scanned(self):
        doc = scan("office-pc")
        a, _ = self.read(doc)
        cpuinfo = os.path.join(tempfile.mkdtemp(prefix="salvage-"), "cpuinfo")
        probe = {"disks": []}
        with mock.patch.object(common, "CPUINFO", cpuinfo):
            with open(cpuinfo, "w") as f:
                f.write(F.cpuinfo("Intel(R) Core(TM) i5-8500 CPU @ 3.00GHz", "GenuineIntel", F.V3, 6, 6))
            self.assertNotIn("processor", common.auto_check(dict(a, disk="/dev/sda"), probe) or "")
            with open(cpuinfo, "w") as f:
                f.write(F.cpuinfo("AMD Ryzen 9 9955HX 16-Core Processor", "AuthenticAMD", F.V3, 16, 32))
            self.assertIn("The answer file is for a computer whose processor matches", common.auto_check(dict(a, disk="/dev/sda"), probe))


if __name__ == "__main__":
    unittest.main()
