"""`bromigos startup`: bromigOS's own read from the defaults (this checkout's desktop/hypr),
yours in a marked block saved the safe way (a Hyprland that verifies anything, no
session), the XDG autostart entries listed, windows.toml."""
import json
import os
import shutil
import unittest

from cmdtest import DESKTOP, FIXTURES, CmdTest

HYPRLAND = "#!/bin/sh\n[ \"$1\" = --verify-config ] && { echo 'config ok'; exit 0; }\nexit 0\n"


class StartupTest(CmdTest):
    def setUp(self):
        super().setUp()
        hb = os.path.join(self.tmp, "hyprbin")
        os.makedirs(hb)
        with open(os.path.join(hb, "Hyprland"), "w") as f:
            f.write(HYPRLAND)
        os.chmod(os.path.join(hb, "Hyprland"), 0o755)
        self.env["PATH"] = f"{hb}:{self.env['PATH']}"
        self.env["XDG_DATA_DIRS"] = os.path.join(FIXTURES, "share")
        self.env["XDG_CONFIG_DIRS"] = os.path.join(self.tmp, "etc-xdg")
        os.makedirs(os.path.join(self.env["BROMIGOS_SHARE_DIR"], "default"))
        os.symlink(os.path.join(DESKTOP, "hypr"), os.path.join(self.env["BROMIGOS_SHARE_DIR"], "default", "hypr"))
        os.makedirs(self.path(".config", "hypr"))
        shutil.copy(os.path.join(DESKTOP, "user", "hypr", "hyprland.lua"), self.path(".config", "hypr", "hyprland.lua"))

    def test_bromigos_own(self):
        d = self.cmd("startup")
        cmds = [o["command"] for o in d["own"]]
        for c in ("bromigos-bar start", "bromigos-widgets", "bromigos idle start", "dunst", "bromigos-live start --login"):
            self.assertIn(c, cmds)
        osd = next(o for o in d["own"] if o["command"].startswith("swayosd-server"))
        self.assertEqual(osd["when"], "when swayosd is installed")
        self.assertIn("on-screen display", osd["what"])
        self.assertTrue(all(o["what"] for o in d["own"]), [o for o in d["own"] if not o["what"]])
        self.assertNotIn("…", " ".join(c for c in cmds if not c.startswith("swayosd")))   # the loop over yours isn't listed
        self.assertFalse(d["xdg_autostart_run"])

    def test_yours_add_remove(self):
        d = self.cmd("startup", "add", "--app", "firefox.desktop")
        self.assertEqual(d["yours"], [{"command": "gtk-launch firefox.desktop", "name": "Firefox", "from": "block"}])
        d = self.cmd("startup", "add", "sh", "-c", "echo hi", "--name", "Say hi")
        self.assertEqual([i["name"] for i in d["yours"]], ["Firefox", "Say hi"])
        lua = self.read(".config", "hypr", "hyprland.lua")
        self.assertIn('table.insert(bromigos.autostart, "sh -c echo hi")  -- Say hi', lua)
        self.assertLess(lua.index("-- >>> bromigos startup"), lua.index('dofile("/usr/share/bromigos'))
        self.cmd("startup", "add", "--app", "firefox.desktop", ok=False)            # already there
        self.cmd("startup", "add", "no-such-program-here", ok=False)
        self.cmd("startup", "add", "--app", "nope.desktop", ok=False)
        d = self.cmd("startup", "remove", "1")
        self.assertEqual([i["name"] for i in d["yours"]], ["Say hi"])
        d = self.cmd("startup", "remove", "sh -c echo hi")
        self.assertEqual(d["yours"], [])
        self.assertNotIn("bromigos startup", self.read(".config", "hypr", "hyprland.lua"))
        self.cmd("startup", "remove", "1", ok=False)

    def test_a_quote_stays_a_string(self):
        d = self.cmd("startup", "add", "sh", "-c", 'echo "a\\b"')
        self.assertEqual(d["yours"][0]["command"], 'sh -c echo "a\\b"')

    def test_yours_in_your_own_table_are_listed_not_changed(self):
        p = self.path(".config", "hypr", "hyprland.lua")
        with open(p) as f:
            lua = f.read()
        with open(p, "w") as f:
            f.write(lua.replace("    -- autostart = { },", '    autostart = { "syncthing", "nm-applet" },'))
        d = self.cmd("startup")
        self.assertEqual([(i["command"], i["from"]) for i in d["yours"]],
                         [("syncthing", "hyprland.lua"), ("nm-applet", "hyprland.lua")])
        self.assertIn("remove it there", self.cmd("startup", "remove", "syncthing", ok=False)["error"])

    def test_xdg_autostart_is_listed(self):
        for d, f, body in ((self.path(".config", "autostart"), "nm-applet.desktop", "Name=Network\nExec=nm-applet --indicator\n"),
                           (os.path.join(self.tmp, "etc-xdg", "autostart"), "gone.desktop", "Name=Gone\nExec=gone\nHidden=true\n"),
                           (os.path.join(self.tmp, "etc-xdg", "autostart"), "geoclue.desktop", "Name=Geo\nExec=geo %u\nOnlyShowIn=GNOME;\n")):
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f), "w") as fh:
                fh.write("[Desktop Entry]\nType=Application\n" + body)
        d = self.cmd("startup")
        self.assertEqual([(x["id"], x["command"]) for x in d["xdg_autostart"]],
                         [("nm-applet.desktop", "nm-applet --indicator"), ("geoclue.desktop", "geo")])
        self.assertEqual(d["xdg_autostart"][1]["only_in"], ["GNOME"])

    def test_windows(self):
        d = self.cmd("startup", "windows", "remember", "org.pulseaudio.pavucontrol")
        self.assertEqual(d["windows"]["remember"], ["org.pulseaudio.pavucontrol"])
        self.assertIn("next login", d["said"])
        self.assertIn('remember = ["org.pulseaudio.pavucontrol"]', self.read(".config", "bromigos", "windows.toml"))
        d = self.cmd("startup", "windows", "all", "on")
        self.assertTrue(d["windows"]["all"])
        self.cmd("startup", "windows", "remember", "bad\nclass", ok=False)
        self.cmd("startup", "windows", "forget-class", "nope", ok=False)
        os.makedirs(self.path(".local", "state", "bromigos"), exist_ok=True)
        with open(self.path(".local", "state", "bromigos", "windows.json"), "w") as f:
            json.dump({"3/org.pulseaudio.pavucontrol": {"x": 10, "y": 20, "w": 600, "h": 400, "saved": "now"},
                       "1/kitty": {"x": 1, "y": 2, "w": 3, "h": 4}}, f)
        d = self.cmd("startup", "windows")
        self.assertEqual([(r["workspace"], r["class"]) for r in d["remembered"]],
                         [("1", "kitty"), ("3", "org.pulseaudio.pavucontrol")])
        d = self.cmd("startup", "windows", "clear", "kitty")
        self.assertEqual([r["class"] for r in d["windows"]["remembered"]], ["org.pulseaudio.pavucontrol"])
        d = self.cmd("startup", "reset")
        self.assertFalse(os.path.exists(self.path(".config", "bromigos", "windows.toml")))
        self.assertEqual((d["windows"]["remember"], d["windows"]["all"], d["yours"]), ([], False, []))


if __name__ == "__main__":
    unittest.main()
