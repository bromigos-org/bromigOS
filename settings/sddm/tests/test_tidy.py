"""bromigos-sddm-tidy and the package scriptlet that runs it, against fixture /etc trees in
a throwaway root (BROMIGOS_FS_ROOT). Nothing reads or touches the real /etc or /var."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
TIDY = HERE.parent / "bromigos-sddm-tidy"
CONF = HERE.parent / "conf" / "zz-bromigos.conf"
INSTALL = HERE.parents[2] / "packaging" / "bromigos-settings" / "bromigos-settings.install"

LEGACY = """# Written by ~/.config/bromigos/sddm/install.sh. Back to the previous theme:
#   sudo sed -i 's/^Current=bromigos$/Current=sugar-candy/' /etc/sddm.conf.d/20-bromigos.conf
[Theme]
Current=bromigos
CursorTheme=Bromigos-cursor
"""


class Tidy(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sddm-tidy-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        pkg = self.root / "usr/lib/sddm/sddm.conf.d/zz-bromigos.conf"
        pkg.parent.mkdir(parents=True)
        shutil.copy(CONF, pkg)
        self.etc = self.root / "etc/sddm.conf.d"
        self.etc.mkdir(parents=True)

    def put(self, name, text):
        (self.etc / name).write_text(text)

    def run_tidy(self, *args):
        r = subprocess.run([sys.executable, str(TIDY), *args, "--json"], capture_output=True, text=True,
                           env=dict(os.environ, BROMIGOS_FS_ROOT=str(self.root)), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def machine(self):
        """What a real install had: two leftovers that repeat the package, and others."""
        self.put("10-wayland.conf", "[General]\nDisplayServer=wayland\n")
        self.put("20-bromigos.conf", LEGACY)
        self.put("30-autologin.conf", "[Autologin]\nUser=someone\nSession=hyprland\n")
        self.put("40-theme.conf", "[Theme]\nCurrent=breeze\n")
        self.put("50-old.conf.disabled", "[General]\nDisplayServer=wayland\n")
        self.put("60-notes.conf", "# nothing set here\n")
        self.put("70-edited.conf", LEGACY.replace("Current=bromigos", "Current=sugar-candy"))
        self.put("80-mixed.conf", "[General]\nDisplayServer=wayland\nNumlock=on\n")

    def test_report_reads_and_changes_nothing(self):
        self.machine()
        before = sorted(os.listdir(self.etc))
        doc = self.run_tidy()
        by = {f["file"].rsplit("/", 1)[1]: f for f in doc["files"]}
        self.assertEqual({n for n, f in by.items() if f["duplicate"]},
                         {"10-wayland.conf", "20-bromigos.conf", "50-old.conf.disabled"})
        self.assertTrue(by["20-bromigos.conf"]["legacy"])
        self.assertEqual(by["40-theme.conf"]["differs"],
                         [{"section": "Theme", "key": "Current", "value": "breeze", "package": "bromigos"}])
        self.assertEqual(by["30-autologin.conf"]["differs"][0]["package"], None)      # bromigOS doesn't set it
        self.assertEqual([d["key"] for d in by["80-mixed.conf"]["differs"]], ["Numlock"])
        self.assertEqual([d["value"] for d in by["70-edited.conf"]["differs"]], ["sugar-candy"])
        self.assertEqual(by["60-notes.conf"]["differs"], [])
        self.assertFalse(by["60-notes.conf"]["duplicate"], "a file of comments without the old header stays")
        self.assertEqual(sorted(os.listdir(self.etc)), before)
        self.assertFalse((self.root / "var").exists())

    def test_apply_moves_only_the_duplicates_with_a_backup_and_a_record(self):
        self.machine()
        doc = self.run_tidy("--apply")
        moved = {m["file"] for m in doc["moved"]}
        self.assertEqual(moved, {"/etc/sddm.conf.d/10-wayland.conf", "/etc/sddm.conf.d/20-bromigos.conf",
                                 "/etc/sddm.conf.d/50-old.conf.disabled"})
        self.assertEqual(sorted(os.listdir(self.etc)), ["30-autologin.conf", "40-theme.conf", "60-notes.conf",
                                                        "70-edited.conf", "80-mixed.conf"])
        [stamp] = os.listdir(self.root / "var/lib/bromigos/sddm-backup")
        self.assertEqual((self.root / "var/lib/bromigos/sddm-backup" / stamp / "20-bromigos.conf").read_text(), LEGACY)
        rec = json.loads((self.root / "var/lib/bromigos/sddm-tidy.json").read_text())
        self.assertEqual({r["file"] for r in rec["removed"]}, moved)
        self.assertEqual(oct((self.root / "var/lib/bromigos/sddm-tidy.json").stat().st_mode & 0o777), "0o644")
        # read again: the moved files are reported as handled, the rest as before
        doc = self.run_tidy()
        self.assertEqual({r["file"] for r in doc["removed"]}, moved)
        self.assertFalse([f for f in doc["files"] if f["duplicate"]])
        # a second run moves nothing more
        self.assertEqual(self.run_tidy("--apply")["moved"], [])

    def test_no_package_conf_means_nothing_is_a_duplicate(self):
        (self.root / "usr/lib/sddm/sddm.conf.d/zz-bromigos.conf").unlink()
        self.put("10-wayland.conf", "[General]\nDisplayServer=wayland\n")
        self.assertEqual(self.run_tidy("--apply")["moved"], [])
        self.assertTrue((self.etc / "10-wayland.conf").exists())

    def test_the_package_scriptlet_runs_it_on_upgrade(self):
        self.machine()
        tool = self.root / "usr/lib/bromigos/sddm/bromigos-sddm-tidy"
        tool.parent.mkdir(parents=True)
        shutil.copy(TIDY, tool)
        tool.chmod(0o755)
        # pacman runs a scriptlet from the root it installs into, with relative paths
        r = subprocess.run(["bash", "-c", f'. "{INSTALL}"; post_upgrade'], cwd=self.root, capture_output=True,
                           text=True, env=dict(os.environ, BROMIGOS_FS_ROOT=str(self.root)), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("moved /etc/sddm.conf.d/20-bromigos.conf", r.stdout)
        self.assertFalse((self.etc / "10-wayland.conf").exists())
        self.assertTrue((self.etc / "40-theme.conf").exists())
        # install, in a root with no sddm.conf.d at all: quiet, and fine
        shutil.rmtree(self.etc)
        r = subprocess.run(["bash", "-c", f'. "{INSTALL}"; post_install'], cwd=self.root, capture_output=True,
                           text=True, env=dict(os.environ, BROMIGOS_FS_ROOT=str(self.root)), timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
