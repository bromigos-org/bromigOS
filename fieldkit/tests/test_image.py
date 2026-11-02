"""Which Field Kit ISO `fieldkit usb` and `make-stick` write (image.py): --iso, a downloaded ISO,
the offer to download one, and plain words when there's none."""
import hashlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from bromigos_fieldkit import cli, image, stick


class Tty(io.StringIO):
    def isatty(self):
        return True


def touch(path, data=b"iso"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


class Find(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="fk-home-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, ignore_errors=True))
        for p in (mock.patch.object(image, "home", return_value=self.home),
                  mock.patch.object(image, "running_medium", return_value=None),
                  mock.patch.object(image.os, "getcwd", return_value=self.home)):
            p.start()
            self.addCleanup(p.stop)

    def test_iso_given_is_used(self):
        iso = touch(os.path.join(self.home, "elsewhere", "my-fieldkit.iso"))
        self.assertEqual(image.find(iso), iso)

    def test_iso_given_but_missing_says_so_plainly(self):
        with self.assertRaises(image.NoImage) as e:
            image.find(os.path.join(self.home, "nope.iso"))
        self.assertIn("There's no file at", str(e.exception))
        self.assertNotIn("sudo", str(e.exception))
        self.assertNotIn("pacman", str(e.exception))

    def test_newest_download_in_downloads(self):
        d = os.path.join(self.home, "Downloads")
        touch(os.path.join(d, "bromigos-fieldkit-0.1.4-x86_64.iso"))
        new = touch(os.path.join(d, "bromigos-fieldkit-0.1.10-x86_64.iso"))
        touch(os.path.join(d, "bromigos-0.1.11-x86_64.iso"))                   # the desktop's: not Field Kit
        touch(os.path.join(d, "bromigos-fieldkit-0.1.12-x86_64.iso.part"))     # unfinished
        self.assertEqual(image.find(may_download=False), new)

    def test_xdg_download_folder(self):
        touch(os.path.join(self.home, ".config", "user-dirs.dirs"), b'XDG_DOWNLOAD_DIR="$HOME/Fetched"\n')
        iso = touch(os.path.join(self.home, "Fetched", "bromigos-fieldkit-2026.11.02-x86_64.iso"))
        self.assertEqual(image.downloads_dir(), os.path.join(self.home, "Fetched"))
        self.assertEqual(image.find(may_download=False), iso)

    def test_none_found_points_to_the_download_page(self):
        with self.assertRaises(image.NoImage) as e:
            image.find(may_download=False)
        msg = str(e.exception)
        self.assertIn("https://bromigos.org/download", msg)
        self.assertIn("Downloads folder", msg)
        self.assertNotIn("sudo", msg)
        self.assertNotIn("pacman", msg)

    def test_no_offer_without_a_terminal(self):
        with mock.patch.object(image, "latest") as latest, mock.patch.object(image.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(image.NoImage):
                image.find()
        latest.assert_not_called()


class Download(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="fk-dl-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.data = b"field kit " * 1000
        self.entry = {"edition": "bromigos-fieldkit", "file": "bromigos-fieldkit-0.1.4-x86_64.iso",
                      "url": "https://pkgs.example.invalid/iso/0.1.4/bromigos-fieldkit-0.1.4-x86_64.iso",
                      "sha256": hashlib.sha256(self.data).hexdigest(), "size": len(self.data)}

    def urlopen(self, body):
        return mock.patch.object(image.urllib.request, "urlopen", side_effect=lambda *a, **k: io.BytesIO(body))

    def test_latest_picks_field_kit(self):
        index = {"isos": [dict(self.entry, edition="bromigos", file="bromigos-0.1.4-x86_64.iso"), self.entry]}
        with self.urlopen(json.dumps(index).encode()):
            self.assertEqual(image.latest()["file"], self.entry["file"])
        with self.urlopen(json.dumps({"isos": [index["isos"][0]]}).encode()):
            self.assertIsNone(image.latest())

    def test_checked_download_is_kept(self):
        with self.urlopen(self.data):
            p = image.download(self.entry, self.dir, out=io.StringIO())
        self.assertEqual(p, os.path.join(self.dir, self.entry["file"]))
        self.assertEqual(open(p, "rb").read(), self.data)

    def test_wrong_checksum_is_thrown_away(self):
        with self.urlopen(self.data + b"x"), self.assertRaises(image.NoImage) as e:
            image.download(self.entry, self.dir, out=io.StringIO())
        self.assertIn("checksum", str(e.exception))
        self.assertEqual(os.listdir(self.dir), [])

    def test_offer_downloads_on_yes(self):
        with mock.patch.object(image.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(image, "latest", return_value=self.entry), \
                mock.patch.object(image, "downloads_dir", return_value=self.dir), self.urlopen(self.data):
            p = image.offer(ask=lambda q: "y", out=Tty())
            self.assertTrue(os.path.isfile(p))
            self.assertIsNone(image.offer(ask=lambda q: "", out=Tty()))


class Commands(unittest.TestCase):
    def test_usb_finds_the_iso_before_sudo_and_passes_it_on(self):
        seen = {}
        with mock.patch.object(image, "find", return_value="/home/alex/Downloads/bromigos-fieldkit-0.1.4-x86_64.iso"), \
                mock.patch.object(cli, "need_root", side_effect=lambda argv: seen.setdefault("argv", argv)), \
                mock.patch.object(cli, "usb", return_value=0) as usb:
            cli.main(["usb", "/dev/sdx"])
        self.assertEqual(seen["argv"], ["usb", "/dev/sdx", "--iso", "/home/alex/Downloads/bromigos-fieldkit-0.1.4-x86_64.iso"])
        usb.assert_called_once_with("/dev/sdx", "/home/alex/Downloads/bromigos-fieldkit-0.1.4-x86_64.iso")

    def test_usb_without_an_iso_says_where_to_get_it(self):
        err = io.StringIO()
        with mock.patch.object(image, "find", side_effect=image.NoImage(image.MISSING)), \
                mock.patch.object(cli, "need_root") as root, mock.patch.object(image.sys, "stderr", err):
            rc = cli.main(["usb", "/dev/sdx"])
        self.assertEqual(rc, 1)
        root.assert_not_called()
        self.assertIn("bromigos.org/download", err.getvalue())

    def test_make_stick_without_an_iso_writes_nothing(self):
        a = mock.Mock(device="/dev/sdx", settings_only=False, iso=None)
        err = io.StringIO()
        with mock.patch.object(stick.os, "geteuid", return_value=1000), \
                mock.patch.object(image, "find", side_effect=image.NoImage(image.MISSING)), \
                mock.patch.object(image.sys, "stderr", err), mock.patch.object(stick, "gather") as gather:
            rc = stick.make_stick(a, lambda argv: None, ["make-stick", "/dev/sdx"])
        self.assertEqual(rc, 1)
        gather.assert_not_called()
        self.assertIn("bromigos.org/download", err.getvalue())


if __name__ == "__main__":
    unittest.main()
