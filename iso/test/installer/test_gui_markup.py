"""The installers' rows and Pango markup: libadwaita 1.10's Adw.ComboRow shows its title and
subtitle as plain text, so text escaped for markup (esc()) shows its entities ("server&apos;s
time zone" on the Server installer's "How it updates" step). A ComboRow's text goes in as it is."""
import re
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "profile/airootfs/usr/local/lib/bromigos-iso/bromigos_installer"


class ComboRowText(unittest.TestCase):
    def test_no_escaped_text_on_a_combo_row(self):
        for name in ("server_gui.py", "gui.py"):
            src = (LIB / name).read_text()
            combos = set(re.findall(r"(\w+) = Adw\.ComboRow\(", src))
            bad = [m.group(0) for m in re.finditer(r"Adw\.ComboRow\([^)]*?\besc\(", src)]
            for var in combos:
                bad += [m.group(0) for m in re.finditer(rf"\b{var}\.set_(?:subtitle|title)\(esc\(", src)]
            # a row variable reused for another kind of row is fine only where that row isn't a ComboRow:
            # set_subtitle(esc(...)) on a name that's a ComboRow somewhere is checked by hand below
            bad = [b for b in bad if not (b.startswith("row.") and name == "server_gui.py")]
            self.assertEqual(bad, [], f"{name}: escaped text on an Adw.ComboRow")
        src = (LIB / "server_gui.py").read_text()
        self.assertNotIn('win.set_subtitle(esc(', src)
        self.assertNotIn('row.set_subtitle(esc(ms[', src)
        self.assertNotIn('row.set_subtitle(esc(c0.get(', src)


if __name__ == "__main__":
    unittest.main()
