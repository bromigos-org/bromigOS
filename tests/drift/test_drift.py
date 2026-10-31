"""DRIFTGLASS's shapes for Python: a stand-in `bromigos` answers `fieldkit shapes`, asked
once; the orb, the emblem and a disk map come out as rich Text; without bromigos, the disk
map still follows the same rules."""
import json
import os
import stat
import tempfile
import unittest

import bromigos_drift as D

DOC = {
    "palette": {"mode": "truecolor", "ascii": False, "braille": True,
                "colors": {"primary": "#39ff14", "white": "#e8ffe0", "void": "#000500", "muted": "#7e927e",
                           "faint": "#4e6b4e", "accent": "#3fe0c5", "soft": "#9cff8a", "dim": "#159b09"},
                "ansi16": {"primary": "green"}},
    "emblem": ["⣿⣿", "⠿⠿"], "wordmark": ["BRO"], "wordmark_ascii": ["B R O"],
    "orb": {"size": [2, 1], "seconds_per_frame": 0.12,
            "frames": [{"rows": ["⣿⠿"], "hot": ["* "]}, {"rows": ["⠿⣿"], "hot": [" *"]}],
            "plain": {"size": [3, 1], "frames": [{"rows": ["(@)"], "hot": [" * "]}]}},
}
DISK = {"size": 100000, "children": [
    {"size": 1000, "fstype": "vfat", "parttypename": "EFI System"},
    {"size": 60000, "fstype": "crypto_LUKS", "parttypename": "Linux filesystem"},
    {"size": 30000, "fstype": "ntfs", "parttypename": "Microsoft basic data"},
]}


class Drift(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "asked")
        self.bin = os.path.join(self.tmp.name, "bromigos")
        with open(os.path.join(self.tmp.name, "doc.json"), "w") as f:
            json.dump(DOC, f)
        with open(self.bin, "w") as f:
            f.write(f'#!/bin/sh\necho "$*" >> "{self.log}"\ncat "{self.tmp.name}/doc.json"\n')
        os.chmod(self.bin, os.stat(self.bin).st_mode | stat.S_IEXEC)
        self.saved = D.BROMIGOS
        D.BROMIGOS = self.bin
        D.clear()
        self.addCleanup(self.restore)

    def restore(self):
        D.BROMIGOS = self.saved
        D.clear()

    def test_asked_once(self):
        D.orb_text(0)
        D.orb_text(1)
        D.emblem_text()
        with open(self.log) as f:
            asked = f.read().splitlines()
        self.assertEqual(asked, ["fieldkit shapes --json --orb 22x11 --frames 24"])

    def test_orb_frames_and_glow(self):
        a, b = D.orb_text(0), D.orb_text(1)
        self.assertEqual((a.plain, b.plain), ("⣿⠿", "⠿⣿"))
        self.assertIn("bold", str(a.spans[0].style))
        self.assertNotIn("bold", str(a.spans[1].style))
        self.assertEqual(D.orb_text(2).plain, a.plain, "the frames loop")
        DOC["palette"]["braille"] = False
        self.addCleanup(DOC["palette"].__setitem__, "braille", True)
        with open(os.path.join(self.tmp.name, "doc.json"), "w") as f:
            json.dump(DOC, f)
        D.clear()
        self.assertEqual(D.orb_text(0).plain, "(@)", "the plain ring without braille")
        self.assertEqual(D.emblem_text().plain, "BRO")

    def test_disk_map(self):
        t = D.disk_map_text(DISK, 40)
        self.assertEqual(len(t.plain), 40)
        self.assertIn(" bromigOS ", t.plain)
        self.assertIn(" Windows ", t.plain)
        self.assertEqual([k for k, _, _ in D.segments(DISK)], ["efi", "bromigos", "windows", "free"])
        for w in (1, 3, 7, 40, 61):
            self.assertEqual(sum(D.cells(D.segments(DISK), w)), w)
        self.assertEqual(D.cells(D.segments(DISK), 40)[1], 24)
        # background-coloured cells only: a block glyph's height varies by font, which made
        # part of the bar look thicker (the Linux console keeps its own font's blocks)
        self.assertFalse(set(t.plain) & set("█░▒"), t.plain)
        if DOC["palette"].get("mode", "truecolor") == "truecolor":
            self.assertTrue(all(" on " in f" {sp.style}" for sp in t.spans), t.spans)

    def test_without_bromigos(self):
        D.BROMIGOS = os.path.join(self.tmp.name, "nothing-here")
        D.clear()
        self.assertEqual(D.orb_text(0).plain, "")
        self.assertEqual(D.emblem_text().plain, "B R O M I G O S")
        self.assertEqual(len(D.disk_map_text(DISK, 30).plain), 30)


if __name__ == "__main__":
    unittest.main()
