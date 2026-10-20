"""Zettlr's colours (lib/bromigos_zettlr.py, the `zettlr` theme-set hook), in a throwaway
home: the bromigOS block in custom.css next to the user's own CSS, and darkMode in
config.json with every other setting left alone. The rendered CSS per theme is checked
against desktop/tests/golden/zettlr/ by core/crates/bromigos/tests/theme_cli.rs."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import bromigos_zettlr as Z  # noqa: E402

GOLDEN = HERE / "golden" / "zettlr"
HOOK = HERE.parent / "hooks" / "theme-set.d" / "zettlr"


class Merge(unittest.TestCase):
    css = (GOLDEN / "wick.css").read_text()

    def test_a_new_file_gets_the_block_then_zettlrs_own_start(self):
        out = Z.merge(None, self.css)
        self.assertTrue(out.startswith(Z.BEGIN + "\n"))
        self.assertIn(self.css.strip(), out)
        self.assertTrue(out.endswith(Z.END + "\n\n" + Z.ZETTLR_START))

    def test_the_users_rules_stay_after_the_block(self):
        mine = "/* Enter your custom CSS here */\n\n.cm-editor { font-size: 20px !important; }\n"
        out = Z.merge(mine, self.css)
        self.assertTrue(out.startswith(Z.BEGIN))
        self.assertTrue(out.endswith(Z.END + "\n\n" + mine))

    def test_imports_stay_first(self):
        mine = "@charset \"utf-8\";\n@import url(\"mine.css\");\n\nbody { color: red; }\n"
        out = Z.merge(mine, self.css)
        self.assertTrue(out.startswith("@charset \"utf-8\";\n@import url(\"mine.css\");\n" + Z.BEGIN))
        self.assertTrue(out.endswith(Z.END + "\n\nbody { color: red; }\n"))

    def test_a_second_switch_replaces_the_block_in_place(self):
        mine = "a { color: red; }\n"
        first = Z.merge(mine, self.css)
        tide = (GOLDEN / "tidewell.css").read_text()
        second = Z.merge(first, tide)
        self.assertEqual(second.count(Z.BEGIN), 1)
        self.assertEqual(second.count(Z.END), 1)
        self.assertNotIn(self.css.strip(), second)
        self.assertIn(tide.strip(), second)
        self.assertTrue(second.endswith(mine))
        self.assertEqual(Z.merge(second, tide), second)

    def test_the_user_moved_the_block_below_their_rules(self):
        moved = "a { color: red; }\n" + Z.block("old") + "b { color: blue; }\n"
        out = Z.merge(moved, self.css)
        self.assertTrue(out.startswith("a { color: red; }\n" + Z.BEGIN))
        self.assertTrue(out.endswith(Z.END + "\nb { color: blue; }\n"))

    def test_a_broken_block_is_left_alone(self):
        for broken in (Z.BEGIN + "\nx\n", "x\n" + Z.END + "\n", Z.END + "\n" + Z.BEGIN + "\n",
                       Z.block("a") + Z.block("b")):
            with self.subTest(broken=broken[:40]), self.assertRaises(ValueError):
                Z.merge(broken, self.css)


class Home(unittest.TestCase):
    """The hook in a throwaway home: HOME and XDG_CONFIG_HOME point into it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.theme = Path(self.tmp, "current")
        self.theme.mkdir()
        shutil.copy(GOLDEN / "tidewell.css", self.theme / "zettlr.css")
        (self.theme / "palette.json").write_text(json.dumps({"schema": 1, "theme": "tidewell", "mode": "dark"}))
        self.zdir = Path(self.tmp, "config", "Zettlr")
        # a PATH with only what the hook runs: whether Zettlr is installed is up to each test
        self.bin = Path(self.tmp, "bin")
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(os.path.realpath(sys.executable))
        for tool in ("bash", "readlink", "dirname"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.env = {"HOME": self.tmp, "XDG_CONFIG_HOME": str(Path(self.tmp, "config")),
                    "BROMIGOS_ZETTLR_RUNNING": "0", "PATH": str(self.bin)}

    def hook(self, **env):
        return subprocess.run([str(HOOK)], env={**self.env, "BROMIGOS_THEME_DIR": str(self.theme), **env},
                              capture_output=True, text=True)

    def config(self, data):
        self.zdir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, indent=2)
        (self.zdir / "config.json").write_text(text)
        return text

    def test_the_hook_merges_and_sets_dark_mode_only(self):
        before = self.config({"version": "4.8.0", "darkMode": False, "autoDarkMode": "off",
                              "display": {"theme": "karl-marx-stadt"}, "editor": {"fontSize": 18}})
        (self.zdir / "custom.css").write_text("/* mine */\n.x { color: red; }\n")
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        css = (self.zdir / "custom.css").read_text()
        self.assertTrue(css.startswith(Z.BEGIN))
        self.assertTrue(css.endswith("/* mine */\n.x { color: red; }\n"))
        self.assertEqual((self.zdir / "config.json").read_text(), before.replace('"darkMode": false', '"darkMode": true'))

    def test_a_linked_custom_css_stays_a_link(self):
        self.zdir.mkdir(parents=True)
        real = Path(self.tmp, "dotfiles-custom.css")
        real.write_text(".x { color: red; }\n")
        (self.zdir / "custom.css").symlink_to(real)
        self.assertEqual(self.hook().returncode, 0)
        self.assertTrue((self.zdir / "custom.css").is_symlink())
        self.assertTrue(real.read_text().startswith(Z.BEGIN))
        self.assertTrue(real.read_text().endswith(".x { color: red; }\n"))

    def test_a_light_theme_turns_dark_mode_off(self):
        self.config({"darkMode": True})
        (self.theme / "palette.json").write_text(json.dumps({"mode": "light"}))
        self.assertEqual(self.hook().returncode, 0)
        self.assertIs(json.loads((self.zdir / "config.json").read_text())["darkMode"], False)

    def test_a_running_zettlr_keeps_its_settings_file(self):
        before = self.config({"darkMode": False})
        r = self.hook(BROMIGOS_ZETTLR_RUNNING="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.zdir / "config.json").read_text(), before)
        self.assertTrue((self.zdir / "custom.css").read_text().startswith(Z.BEGIN))

    def test_no_config_json_is_made_before_zettlrs_first_start(self):
        self.zdir.mkdir(parents=True)
        self.assertEqual(self.hook().returncode, 0)
        self.assertFalse((self.zdir / "config.json").exists())
        self.assertTrue((self.zdir / "custom.css").exists())

    def test_nothing_happens_without_zettlr(self):
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.zdir.exists())

    def test_zettlr_installed_but_never_run(self):
        (self.bin / "zettlr").write_text("#!/bin/sh\nexit 0\n")
        (self.bin / "zettlr").chmod(0o755)
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(p.name for p in self.zdir.iterdir()), ["custom.css"])

    def test_a_broken_block_fails_and_writes_nothing(self):
        self.zdir.mkdir(parents=True)
        broken = Z.BEGIN + "\n.x { color: red; }\n"
        (self.zdir / "custom.css").write_text(broken)
        r = self.hook()
        self.assertEqual(r.returncode, 1)
        self.assertIn("incomplete bromigOS block", r.stderr)
        self.assertEqual((self.zdir / "custom.css").read_text(), broken)

    def test_an_old_theme_without_zettlr_css(self):
        (self.theme / "zettlr.css").unlink()
        self.zdir.mkdir(parents=True)
        self.assertEqual(self.hook().returncode, 0)
        self.assertEqual(list(self.zdir.iterdir()), [])

    def test_running_detection_sees_the_packaged_zettlr(self):
        with patch.dict(os.environ, {"BROMIGOS_ZETTLR_RUNNING": ""}):
            self.assertIsInstance(Z.zettlr_running(), bool)


if __name__ == "__main__":
    unittest.main()
