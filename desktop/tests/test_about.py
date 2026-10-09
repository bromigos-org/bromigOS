"""`bromigos about`: the version and channel, the packages and their licences (the pacman
stand-in), the hardware (`bromigos hw`'s stand-in, /proc), the last full update from a
recorded pacman log."""
import os
import re
import sys
import unittest

from cmdtest import FIXTURES, REPO, CmdTest

sys.path.insert(0, os.path.join(REPO, "desktop", "lib"))
import bromigos_cli as C  # noqa: E402


def published_at(base):
    """Where manual/publish.sh puts the manual, as the repository serves it: <base>/<its
    PKGS_REPO default>/manual/, read from the publisher itself."""
    with open(os.path.join(REPO, "manual", "publish.sh")) as f:
        repo = re.search(r'pkgs:\$PKGS_S3_BUCKET/\$\{PKGS_REPO:-([\w.-]+)\}/manual"', f.read()).group(1)
    return f"{base}/{repo}/manual/"


class AboutTest(CmdTest):
    def about(self, *args):
        return self.cmd("about", *args, env={"BROMIGOS_PACMAN_LOG": os.path.join(FIXTURES, "pacman.log")})

    def test_status(self):
        d = self.about()
        self.assertEqual((d["version"], d["channel"]), ("0.1.0", "edge"))
        names = [p["name"] for p in d["packages"]]
        self.assertEqual(names[0], "bromigos")
        self.assertIn("bromigos-desktop", names)
        self.assertIn("hyprland", names)
        self.assertNotIn("python", names)                     # not one of the components listed
        hyp = next(p for p in d["packages"] if p["name"] == "hyprland")
        self.assertEqual((hyp["version"], hyp["licence"]), ("0.56.2-1", "BSD-3-Clause"))
        hw = d["hardware"]
        self.assertEqual(hw["gpus"][0]["name"], "Navi 32 [Radeon RX 7800 XT]")
        self.assertEqual(hw["machine"]["kind"], "desktop")
        self.assertTrue(hw["memory"] and hw["cpu"]["threads"] and hw["disk"]["size"])
        self.assertEqual(d["last_update"], {"at": "2026-10-09T01:30:04-0700", "packages": 3,
                                            "log": os.path.join(FIXTURES, "pacman.log")})
        self.assertEqual(d["licences"]["bromigos"], "MIT OR Apache-2.0")
        self.assertTrue(any("Geist" in t["what"] for t in d["licences"]["terms"]))
        # the manual where the publisher puts it (no copy installed here)
        self.assertEqual(d["links"]["manual"], published_at("https://packages.example.org"))
        self.assertEqual(d["links"]["manual_online"], d["links"]["manual"])
        self.assertFalse(d["links"]["manual_installed"])

    def test_the_installed_manual_comes_first(self):
        book = os.path.join(self.tmp, "manual")
        os.makedirs(book)
        with open(os.path.join(book, "index.html"), "w") as f:
            f.write("<html></html>")
        d = self.about()
        self.assertEqual(d["links"]["manual"], "file://" + os.path.join(book, "index.html"))
        self.assertTrue(d["links"]["manual_installed"])
        self.assertEqual(d["links"]["manual_online"], published_at("https://packages.example.org"))

    def test_text_for_a_bug_report(self):
        d = self.about("text")
        self.assertIn("bromigOS 0.1.0 (edge)", d["text"])
        self.assertIn("GPU Navi 32 [Radeon RX 7800 XT] (amdgpu)", d["text"])
        self.assertIn("last update 2026-10-09T01:30:04-0700 (3 packages)", d["text"])

    def test_without_pacman_or_log(self):
        bare = os.path.join(self.tmp, "bare")
        os.makedirs(bare)
        os.symlink(os.path.join(FIXTURES, "bin", "bromigos"), os.path.join(bare, "bromigos"))
        import sys
        os.symlink(sys.executable, os.path.join(bare, "python3"))
        d = self.cmd("about", env={"PATH": bare, "BROMIGOS_PACMAN_LOG": "/nonexistent"})
        self.assertIsNone(d["packages"])
        self.assertIsNone(d["last_update"])
        self.assertEqual(d["version"], "0.1.0")


class ManualUrlTest(unittest.TestCase):
    """bromigos_cli.manual_url, which Settings' F1 and About both use."""

    def setUp(self):
        self.old = os.environ.get("BROMIGOS_MANUAL_DIR")
        os.environ["BROMIGOS_MANUAL_DIR"] = "/nonexistent/manual"

    def tearDown(self):
        if self.old is None:
            os.environ.pop("BROMIGOS_MANUAL_DIR", None)
        else:
            os.environ["BROMIGOS_MANUAL_DIR"] = self.old

    def test_published_beside_the_packages(self):
        base = "https://packages.example.org"
        self.assertEqual(C.manual_url(base + "/"), published_at(base))
        self.assertEqual(C.manual_url(base, "settings.md#sound"), published_at(base) + "settings.html#sound")
        self.assertEqual(C.manual_online(base), published_at(base))

    def test_the_source_when_no_repository_is_known(self):
        self.assertEqual(C.manual_url(None, "settings.md#sound"), C.MANUAL_SOURCE + "settings.md#sound")
        self.assertEqual(C.manual_url(""), C.MANUAL_SOURCE)

    def test_the_installed_copy_where_the_package_puts_it(self):
        with open(os.path.join(REPO, "packaging", "bromigos-manual", "PKGBUILD")) as f:
            self.assertIn(f'"$pkgdir{C.MANUAL_DIR}"', f.read())
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "index.html"), "w").close()
            os.environ["BROMIGOS_MANUAL_DIR"] = d
            self.assertEqual(C.manual_url("https://packages.example.org", "settings.md#sound"),
                             f"file://{d}/settings.html#sound")
            self.assertEqual(C.manual_url(None), f"file://{d}/index.html")


if __name__ == "__main__":
    unittest.main()
