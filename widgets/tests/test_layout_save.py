"""Named layout writes are exclusive for creation and atomic for replacement."""
import fcntl
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import layouts as L


class TemplateSaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "mine"
        self.package = Path(self.tmp.name) / "package"
        self.package.mkdir()
        for context in (patch.object(L, "user_dir", return_value=str(self.directory)),
                        patch.object(L, "system_dirs", return_value=[str(self.package)])):
            context.start()
            self.addCleanup(context.stop)
        self.state = {"system": {"x": 24, "y": 24, "width": 470, "height": 470, "visible": True}}

    def save(self, **kwargs):
        return L.save_template(self.state, L.Screen(1920, 1080), {}, **kwargs)

    def test_a_racing_creation_cannot_overwrite_the_other_file(self):
        link = os.link

        def race(source, target):
            Path(target).write_text("Other writer's layout")
            link(source, target)

        with patch.object(L.os, "link", side_effect=race):
            with self.assertRaises(FileExistsError):
                self.save(name="Desk")
        self.assertEqual((self.directory / "desk.toml").read_text(), "Other writer's layout")
        self.assertEqual(list(self.directory.glob(".layout-*.tmp")), [])

    def test_failed_replace_preserves_original_and_cleans_temporary_file(self):
        out = self.save(name="Desk")
        path = Path(out["path"])
        path.chmod(0o640)
        before = path.read_bytes()
        self.state["system"]["x"] = 160
        with patch.object(L.os, "replace", side_effect=OSError("Fixture write failure")):
            with self.assertRaisesRegex(OSError, "Fixture write failure"):
                self.save(replace="desk")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.directory.glob(".layout-*.tmp")), [])
        self.save(replace="desk")
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertNotEqual(path.read_bytes(), before)

    def test_changed_file_during_save_is_preserved(self):
        out = self.save(name="Desk")
        path = Path(out["path"])
        from_state = L.from_state

        def change(*args):
            path.write_text("A newer arrangement")
            return from_state(*args)

        with patch.object(L, "from_state", side_effect=change):
            with self.assertRaisesRegex(ValueError, "changed while saving"):
                self.save(replace="desk")
        self.assertEqual(path.read_text(), "A newer arrangement")
        self.assertEqual(list(self.directory.glob(".layout-*.tmp")), [])

    def test_another_save_fails_promptly(self):
        self.directory.mkdir()
        with (self.directory / ".save.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaisesRegex(ValueError, "Another layout save"):
                self.save(name="Desk")
        self.assertFalse((self.directory / "desk.toml").exists())

    def test_dotfiles_directory_link_works_but_package_alias_is_refused(self):
        dots = Path(self.tmp.name) / "dotfiles"
        dots.mkdir()
        self.directory.symlink_to(dots, target_is_directory=True)
        self.save(name="Desk")
        self.assertTrue((dots / "desk.toml").is_file())
        self.directory.unlink()
        self.directory.symlink_to(self.package, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "points into packaged"):
            self.save(name="Another")
        self.assertEqual(list(self.package.iterdir()), [])

    def test_reserved_slug_stays_valid_and_distinct_from_theme_aliases(self):
        out = self.save(name="Theme " + "x" * 50)
        self.assertTrue(out["id"].startswith("my-theme-"))
        self.assertIsNotNone(L.ID.fullmatch(out["id"]))

    def test_special_or_oversize_user_file_is_refused_without_reading_forever(self):
        self.directory.mkdir()
        path = self.directory / "desk.toml"
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.save(replace="desk")
        path.unlink()
        path.write_bytes(b"#" * (1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "too large"):
            self.save(replace="desk")
        self.assertEqual(path.stat().st_size, 1024 * 1024 + 1)

    def test_link_retargeted_during_save_changes_neither_target(self):
        dots = Path(self.tmp.name) / "dotfile.toml"
        other = Path(self.tmp.name) / "other.toml"
        source = L.from_state(self.state, L.Screen(1920, 1080), {}, "Desk")
        dots.write_text(source)
        other.write_text(source)
        self.directory.mkdir()
        link = self.directory / "desk.toml"
        link.symlink_to(dots)
        from_state = L.from_state

        def change(*args):
            link.unlink()
            link.symlink_to(other)
            return from_state(*args)

        self.state["system"]["x"] = 160
        with patch.object(L, "from_state", side_effect=change):
            with self.assertRaisesRegex(ValueError, "changed while saving"):
                self.save(replace="desk")
        self.assertEqual(dots.read_text(), source)
        self.assertEqual(other.read_text(), source)
        self.assertEqual(list(Path(self.tmp.name).glob(".layout-*.tmp")), [])

    def test_link_to_another_users_file_is_refused(self):
        target = Path(self.tmp.name) / "dotfile.toml"
        text = L.from_state(self.state, L.Screen(1920, 1080), {}, "Desk")
        target.write_text(text)
        self.directory.mkdir()
        (self.directory / "desk.toml").symlink_to(target)
        with patch.object(L.os, "geteuid", return_value=target.stat().st_uid + 1):
            with self.assertRaisesRegex(ValueError, "owned by another user"):
                self.save(replace="desk")
        self.assertEqual(target.read_text(), text)


if __name__ == "__main__":
    unittest.main()
