"""Field Kit keeps what it found in the install it looked at, for that install's next boot
(docs/alerts.md, fieldkit.finding): on a stand-in install, no root."""
import json
import tempfile
import unittest
from pathlib import Path

from bromigos_fieldkit import diagnose, engine, system


class SavedFindings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fieldkit-saved-")
        self.root = Path(self.tmp.name)
        (self.root / "etc").mkdir()
        (self.root / "etc/passwd").write_text("root:x:0:0::/root:/bin/zsh\n")
        self.t = system.Target(str(self.root))

    def tearDown(self):
        self.tmp.cleanup()

    def saved(self):
        p = self.root / "var/lib/bromigos/fieldkit/findings.json"
        return json.loads(p.read_text()) if p.exists() else None

    def test_findings_that_need_fixing_are_saved_with_commands_for_the_running_install(self):
        found = [diagnose.Finding("The login screen starts: sddm.service", ok=True),
                 diagnose.Finding("No login screen is set to start", "display-manager.service isn't enabled.",
                                  fix_label="Turn the login screen on", fix=lambda t: "",
                                  commands=["arch-chroot {root} systemctl enable sddm.service"],
                                  touches=["/etc/systemd/system/display-manager.service"], lines=["x"])]
        engine.save_findings(self.t, "black-screen", found, now=1793390400)
        doc = self.saved()
        entry = doc["checks"]["black-screen"]
        self.assertEqual(entry["saved_at"], 1793390400000)
        self.assertEqual(len(entry["findings"]), 1)
        f = entry["findings"][0]
        self.assertEqual(f["title"], "No login screen is set to start")
        # as it reads once the install boots by itself: no chroot, no stick's mount point
        self.assertEqual(f["commands"], ["systemctl enable sddm.service"])
        self.assertEqual(f["lines"], ["x"])

    def test_a_clean_check_takes_its_entry_out_and_an_empty_file_goes(self):
        bad = diagnose.Finding("Something", "wrong", commands=["true"])
        engine.save_findings(self.t, "black-screen", [bad])
        engine.save_findings(self.t, "last-boot", [bad])
        engine.save_findings(self.t, "black-screen", [diagnose.Finding("fine", ok=True)])
        self.assertEqual(list(self.saved()["checks"]), ["last-boot"])
        engine.save_findings(self.t, "last-boot", [])
        self.assertIsNone(self.saved())

    def test_the_running_system_saves_nothing(self):
        live = system.Target("/")
        engine.save_findings(live, "black-screen", [diagnose.Finding("Something", "wrong")])
        self.assertIsNone(self.saved())


if __name__ == "__main__":
    unittest.main()
