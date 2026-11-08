"""An answer file that names its computer and its disk by their models (common.py:
cpu_model, disk_model) and sets the Advanced box (advanced = { fs, kernel, zram }), so one
file installs unattended on exactly one machine and one disk, whatever the disk is called
there; with anything else it changes nothing and the installer asks instead.

  python -m unittest discover -s iso/test/installer -p 'test_answer_match.py'
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import test_tui  # noqa: E402,F401  (the fake store, back end and environment)
from bromigos_installer import common  # noqa: E402

PROBE = os.path.join(HERE, "fixtures/probe-server.json")
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheInstallerTestsOnly tester@lab"
CPU = "processor\t: 0\nvendor_id\t: AuthenticAMD\nmodel name\t: AMD Ryzen 9 9955HX 16-Core Processor\nflags\t\t: svm\n"
BASE = ('[install]\nedition = "server"\nmode = "erase"\nuser = "admin"\npassword = "pw-pw"\nencrypt = false\n'
        'ssh = true\nssh_keys = ["' + KEY + '"]\n')
SERVER = '[server]\nrole = "lab"\nlab = "none"\nssh_mode = "keys"\nunlock = "none"\n'


class Match(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="answers-")
        with open(PROBE) as f:
            self.probe = json.load(f)
        self.cpuinfo = os.path.join(self.tmp, "cpuinfo")
        with open(self.cpuinfo, "w") as f:
            f.write(CPU)
        p = mock.patch.object(common, "CPUINFO", self.cpuinfo)
        p.start()
        self.addCleanup(p.stop)

    def read(self, install="", server=SERVER):
        path = os.path.join(self.tmp, "install-server.toml")
        with open(path, "w") as f:
            f.write(BASE + install + server)
        return common.read_answer_file(path)

    def test_the_disk_by_its_model(self):
        a, problems = self.read('disk_model = "samsung*980*"\ncpu_model = "9955HX"\n')
        self.assertEqual(problems, [])
        self.assertIsNone(a["disk"])
        self.assertIsNone(common.auto_check(a, self.probe))
        self.assertEqual(a["disk"], "/dev/nvme0n1")
        self.assertEqual(common.backend_answers(a, None)["disk"], "/dev/nvme0n1")

    def test_a_model_matching_nothing_or_two_disks_changes_nothing(self):
        a, _ = self.read('disk_model = "Samsung*990*PRO*"\n')
        why = common.auto_check(a, self.probe)
        self.assertIn('No disk here has a model matching "Samsung*990*PRO*"', why)
        self.assertIn("Samsung SSD 980 500GB at /dev/nvme0n1", why)
        self.assertIsNone(a["disk"])
        a, _ = self.read('disk_model = "WDC*"\n')
        why = common.auto_check(a, self.probe)
        self.assertIn('2 disks match "WDC*"', why)
        self.assertIsNone(a["disk"])

    def test_another_computer_changes_nothing(self):
        a, problems = self.read('disk_model = "Samsung*980*"\ncpu_model = "9950X"\n')
        self.assertEqual(problems, [])
        why = common.auto_check(a, self.probe)
        self.assertIn('processor matches "9950X"', why)
        self.assertIn("AMD Ryzen 9 9955HX 16-Core Processor", why)
        self.assertIn("Nothing has been changed", why)
        self.assertIsNone(a["disk"], "the disk isn't even chosen on the wrong computer")
        with open(self.cpuinfo, "w") as f:
            f.write("")
        self.assertIn("a processor it can't name", common.auto_check(dict(a, cpu_model="*Ryzen*"), self.probe))

    def test_patterns(self):
        for pattern, text, want in [("9955HX", "AMD Ryzen 9 9955HX 16-Core Processor", True),
                                    ("*Ryzen 9*", "AMD Ryzen 9 9955HX 16-Core Processor", True),
                                    ("Ryzen 7", "AMD Ryzen 9 9955HX 16-Core Processor", False),
                                    ("Samsung*990*PRO*", "Samsung SSD 990 PRO 2TB", True),
                                    ("samsung*990*pro*", "Samsung SSD 990 PRO 2TB", True),
                                    ("Samsung*990*PRO*", "Samsung SSD 990 EVO 2TB", False),
                                    ("Samsung*990*PRO*", None, False)]:
            with self.subTest(pattern=pattern, text=text):
                self.assertEqual(common._matches(pattern, text), want)

    def test_disk_and_disk_model_go_alone(self):
        _, problems = self.read('disk = "/dev/nvme0n1"\ndisk_model = "Samsung*"\n')
        self.assertIn("Give disk or disk_model, not both.", problems)
        _, problems = self.read("")
        self.assertTrue(any("disk_model its model" in p for p in problems), problems)
        _, problems = self.read('disk_model = ""\n')
        self.assertTrue(any("disk_model is a model's name" in p for p in problems), problems)

    def test_advanced(self):
        a, problems = self.read('disk_model = "Samsung*980*"\nadvanced = { zram = false, fs = "btrfs", kernel = "linux-lts" }\n')
        self.assertEqual(problems, [])
        self.assertEqual(a["advanced"], {"zram": False, "fs": "btrfs", "kernel": "linux-lts"})
        self.assertIsNone(common.auto_check(a, self.probe))
        doc = common.backend_answers(a, None)
        self.assertEqual(doc["advanced"], {"zram": False, "fs": "btrfs", "kernel": "linux-lts"})
        # answers.py turns it into the install's options: no compressed swap
        sys.path.insert(0, test_tui.LIB)
        import answers
        path = os.path.join(self.tmp, "answers.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        argv = answers.from_answers(path)
        self.assertIn("--no-zram", argv)
        self.assertEqual(argv[argv.index("--kernel") + 1], "linux-lts")

    def test_advanced_checked(self):
        _, problems = self.read('disk_model = "Samsung*"\nadvanced = { zram = "no", fs = "xfs", colour = 1 }\n')
        text = " ".join(problems)
        self.assertIn("advanced.zram is one of: true, false", text)
        self.assertIn('advanced.fs is one of: "btrfs", "ext4"', text)
        self.assertIn('"advanced.colour" isn\'t an answer the installer knows', text)
        _, problems = self.read('disk_model = "Samsung*"\nadvanced = 3\n')
        self.assertTrue(any("advanced is a table" in p for p in problems), problems)

    def test_kept_answers_keep_the_model_not_the_path(self):
        a, _ = self.read('disk_model = "Samsung*980*"\ncpu_model = "9955HX"\nadvanced = { zram = false }\n')
        common.auto_check(a, self.probe)
        text = common.answers_toml(dict(a), secrets=True)
        self.assertIn('disk_model = "Samsung*980*"', text)
        self.assertIn('cpu_model = "9955HX"', text)
        self.assertIn("advanced = { zram = false }", text)
        self.assertNotIn('disk = "', text)
        path = os.path.join(self.tmp, "again.toml")
        with open(path, "w") as f:
            f.write(text)
        b, problems = common.read_answer_file(path)
        self.assertEqual(problems, [])
        self.assertEqual((b["disk_model"], b["cpu_model"], b["advanced"]), ("Samsung*980*", "9955HX", {"zram": False}))


class Restart(unittest.TestCase):
    """An answer file's install restarts by itself when it's done (nobody may be there to press
    Restart now), unless the file says restart = false or someone presses Stay here."""

    def test_who_restarts_by_itself(self):
        self.assertFalse(common.restarts_by_itself({}))                                  # asked by hand
        self.assertTrue(common.restarts_by_itself({"auto_started": True}))
        self.assertFalse(common.restarts_by_itself({"auto_started": True, "restart": False}))

    def test_the_key_is_checked(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "install.toml")
        with open(p, "w") as f:
            f.write(BASE + 'disk_model = "Samsung*"\nrestart = "no"\n' + SERVER)
        _, problems = common.read_answer_file(p)
        self.assertTrue(any("restart is true or false" in x for x in problems), problems)
        with open(p, "w") as f:
            f.write(BASE + 'disk_model = "Samsung*"\nrestart = false\n' + SERVER)
        a, problems = common.read_answer_file(p)
        self.assertEqual(problems, [])
        self.assertIs(a["restart"], False)
        self.assertIn("restart = false", common.answers_toml(a))

    def _done(self, a, stay=False):
        from bromigos_installer import backend, tui
        import asyncio
        reboots = []
        self.addCleanup(setattr, backend, "reboot", backend.reboot)
        self.addCleanup(setattr, common, "AUTO_RESTART_SECONDS", common.AUTO_RESTART_SECONDS)
        backend.reboot = lambda: reboots.append(1)
        common.AUTO_RESTART_SECONDS = 2

        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 42)) as pilot:
                app.a.update(a)
                app._done(True, None)
                await pilot.pause(0.3)
                words = str(app.query_one("#auto-restart").render()) if app.query("#auto-restart") else ""
                if stay:
                    app.query_one("#restart-stay").press()
                    await pilot.pause(0.2)
                    words = str(app.query_one("#auto-restart").render())
                for _ in range(40):
                    if reboots:
                        break
                    await pilot.pause(0.1)
                return words
        return asyncio.run(go()), reboots

    def test_it_restarts_after_the_countdown(self):
        if not test_tui.HAVE:
            self.skipTest("textual isn't installed")
        words, reboots = self._done({"auto_started": True})
        self.assertIn("Restarting by itself in 2 seconds", words)
        self.assertEqual(reboots, [1])

    def test_stay_here_stops_it(self):
        if not test_tui.HAVE:
            self.skipTest("textual isn't installed")
        words, reboots = self._done({"auto_started": True}, stay=True)
        self.assertIn("Staying here", words)
        self.assertEqual(reboots, [])

    def test_restart_false_and_a_hand_install_wait(self):
        if not test_tui.HAVE:
            self.skipTest("textual isn't installed")
        for a in ({"auto_started": True, "restart": False}, {}):
            with self.subTest(answers=a):
                words, reboots = self._done(a)
                self.assertEqual((words, reboots), ("", []))


class KeysWords(unittest.TestCase):
    def test_the_security_chip_only_when_there_is_one(self):
        from bromigos_installer import secretstore_stub
        for tpm, want in (("1", "sealed to its security chip"), ("0", "a key kept on its disk")):
            with self.subTest(tpm=tpm), mock.patch.dict(os.environ, {"BROMIGOS_INSTALLER_TPM": tpm}):
                self.assertIn(want, secretstore_stub.where({"kind": "local"})[0])


if __name__ == "__main__":
    unittest.main()
