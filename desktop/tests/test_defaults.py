"""`bromigos defaults` against the stand-ins: xdg-mime (fixtures/bin), the installed apps
(fixtures/share/applications as XDG_DATA_DIRS), a Hyprland that verifies anything (no
session: the block is saved and verified, nothing reloads)."""
import os
import shutil
import unittest

from cmdtest import DESKTOP, FIXTURES, CmdTest

HYPRLAND = "#!/bin/sh\n[ \"$1\" = --verify-config ] && { echo 'config ok'; exit 0; }\nexit 0\n"


class DefaultsTest(CmdTest):
    def setUp(self):
        super().setUp()
        hb = os.path.join(self.tmp, "hyprbin")
        os.makedirs(hb)
        with open(os.path.join(hb, "Hyprland"), "w") as f:
            f.write(HYPRLAND)
        os.chmod(os.path.join(hb, "Hyprland"), 0o755)
        self.env["PATH"] = f"{hb}:{self.env['PATH']}"
        self.env["XDG_DATA_DIRS"] = os.path.join(FIXTURES, "share")
        os.makedirs(self.path(".config", "hypr"))
        shutil.copy(os.path.join(DESKTOP, "user", "hypr", "hyprland.lua"), self.path(".config", "hypr", "hyprland.lua"))

    def kind(self, doc, k):
        return next(x for x in doc["kinds"] if x["kind"] == k)

    def test_status(self):
        d = self.cmd("defaults")
        b = self.kind(d, "browser")
        self.assertEqual(b["default"], "firefox.desktop")
        self.assertEqual(b["default_name"], "Firefox")
        self.assertEqual([c["id"] for c in b["candidates"]], ["chromium.desktop", "firefox.desktop"])
        ed = self.kind(d, "editor")
        self.assertEqual(ed["candidates"][-1]["id"], "mimeinfo-helper.desktop")      # hidden ones last
        self.assertTrue(ed["candidates"][-1]["hidden"])
        self.assertEqual(self.kind(d, "mail")["default"], None)
        self.assertEqual(d["terminal"]["command"], "kitty")
        self.assertEqual(d["terminal"]["from"], "bromigOS")
        self.assertEqual(d["terminal"]["app"], "kitty.desktop")
        self.assertEqual([c["id"] for c in d["terminal"]["candidates"]], ["Alacritty.desktop", "foot.desktop", "kitty.desktop"])
        self.assertEqual(d["files_key"]["command"], "pcmanfm")
        self.assertEqual(d["webapps"]["yours"], [])
        self.assertTrue(any(c["name"] == "github" for c in d["webapps"]["catalog"]))

    def test_set_a_kind_sets_every_type(self):
        d = self.cmd("defaults", "set", "browser", "chromium.desktop")
        self.assertEqual(self.kind(d, "browser")["default"], "chromium.desktop")
        self.assertIn(["default", "chromium.desktop", "x-scheme-handler/https", "x-scheme-handler/http", "text/html"],
                      self.calls("xdg-mime"))
        self.assertEqual(d["said"], "Web browser: Chromium")
        self.cmd("defaults", "set", "browser", "nope.desktop", ok=False)
        self.cmd("defaults", "set", "toaster", "firefox.desktop", ok=False)

    def test_the_terminal_and_the_file_managers_key(self):
        d = self.cmd("defaults", "terminal", "foot.desktop")
        self.assertEqual(d["terminal"]["command"], "foot")
        self.assertEqual(d["terminal"]["from"], "block")
        lua = self.read(".config", "hypr", "hyprland.lua")
        block = lua[lua.index("-- >>> bromigos defaults"):lua.index("-- <<< bromigos defaults")]
        self.assertIn('bromigos.apps.terminal = "foot"', block)
        self.assertIn('hl.env("TERMINAL", "foot")', block)
        self.assertLess(lua.index("-- >>> bromigos defaults"), lua.index('dofile("/usr/share/bromigos'))
        self.assertEqual(self.read(".config", "xdg-terminals.list").splitlines()[1], "foot.desktop")
        d = self.cmd("defaults", "set", "files", "org.gnome.Nautilus.desktop")      # xdg-mime and the key
        self.assertEqual(d["files_key"]["command"], "nautilus")
        lua = self.read(".config", "hypr", "hyprland.lua")
        self.assertIn('bromigos.apps.terminal = "foot"', lua)                       # kept
        self.assertEqual(lua.count("-- >>> bromigos defaults"), 1)
        d = self.cmd("defaults", "reset")
        self.assertEqual((d["terminal"]["command"], d["files_key"]["command"]), ("kitty", "pcmanfm"))
        self.assertNotIn("bromigos defaults", self.read(".config", "hypr", "hyprland.lua"))
        self.cmd("defaults", "terminal", "definitely-not-a-program", ok=False)
        self.cmd("defaults", "terminal", 'foot"; os.exit()', ok=False)

    def test_a_refused_config_changes_nothing(self):
        bad = os.path.join(self.tmp, "hyprbin", "Hyprland")
        with open(bad, "w") as f:
            f.write("#!/bin/sh\necho 'error: no'; exit 1\n")
        before = self.read(".config", "hypr", "hyprland.lua")
        d = self.cmd("defaults", "terminal", "foot.desktop", ok=False)
        self.assertIn("didn't take it", d["error"])
        self.assertEqual(self.read(".config", "hypr", "hyprland.lua"), before)

    def test_apps_and_web_apps(self):
        d = self.cmd("defaults", "apps", "terminal")
        self.assertEqual([a["id"] for a in d["apps"]], ["Alacritty.desktop", "foot.desktop", "kitty.desktop"])
        d = self.cmd("defaults", "apps")
        self.assertNotIn("mimeinfo-helper.desktop", [a["id"] for a in d["apps"]])
        os.makedirs(self.path(".config", "bromigos"))
        with open(self.path(".config", "bromigos", "webapps.toml"), "w") as f:
            f.write('[[app]]\nname = "github"\ntitle = "GitHub"\nurl = "https://github.com"\n')
        d = self.cmd("defaults")
        self.assertEqual([w["name"] for w in d["webapps"]["yours"]], ["github"])
        self.assertTrue(next(c for c in d["webapps"]["catalog"] if c["name"] == "github")["added"])
        d = self.cmd("defaults", "webapp-remove", "github")
        self.assertEqual(d["webapps"]["yours"], [])
        self.cmd("defaults", "webapp-add", "Bad Name", "https://x.org", ok=False)
        self.cmd("defaults", "webapp-add", "ok", "ftp://x.org", ok=False)


if __name__ == "__main__":
    unittest.main()
