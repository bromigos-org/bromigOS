"""Saving layouts through the CLI, with a throwaway home and monitor stand-ins."""
import json
from pathlib import Path
import tomllib

from cmdtest import CmdTest


class LayoutSaveTest(CmdTest):
    def setUp(self):
        super().setUp()
        self.widgets = Path(self.path(".config", "bromigos", "widgets"))
        self.widgets.mkdir(parents=True)
        self.layouts = self.widgets / "layouts"
        self.desk()

    def desk(self, x=24, visible=True, second=False):
        panels = [{"name": "system", "x": x, "y": 24, "width": 470,
                   "height": 470, "visible": visible}]
        if second:
            panels.append({"name": "network", "x": 48, "y": 48, "width": 470,
                           "height": 262, "visible": True, "output": {"name": "HDMI-A-1"}})
        (self.widgets / "layout.json").write_text(json.dumps({"version": 2, "panels": panels}))

    def save(self, *args, **kwargs):
        return self.cmd("panels", "layout", "save", *args, **kwargs)

    def read_layout(self, ident="my-desk"):
        return tomllib.loads((self.layouts / f"{ident}.toml").read_text())

    def test_new_save_returns_metadata_without_changing_the_arrangement(self):
        before = (self.widgets / "layout.json").read_bytes()
        out = self.save("My desk", "--description", "A quiet desk 🌙")
        self.assertEqual((out["id"], out["title"], out["description"], out["source"]),
                         ("my-desk", "My desk", "A quiet desk 🌙", "yours"))
        self.assertFalse(out["replaced"])
        self.assertFalse(out["overrode_packaged"])
        self.assertEqual(out["path"], str(self.layouts / "my-desk.toml"))
        self.assertEqual(self.read_layout()["description"], out["description"])
        self.assertEqual((self.widgets / "layout.json").read_bytes(), before)
        self.assertFalse((Path(self.env["XDG_STATE_HOME"]) / "bromigos/widgets/layout-undo.json").exists())

    def test_names_with_the_same_id_are_never_silently_replaced(self):
        self.save("My desk")
        before = (self.layouts / "my-desk.toml").read_bytes()
        self.desk(x=160)
        for name in ("My desk", "MY--DESK!"):
            with self.subTest(name=name):
                out = self.save(name, ok=False)
                self.assertIn("bromigos panels layout save --replace my-desk", out["error"])
                self.assertEqual((self.layouts / "my-desk.toml").read_bytes(), before)

    def test_explicit_replacement_keeps_title_and_description(self):
        self.save("My desk 🌙", "--description", "My first arrangement")
        self.desk(x=160)
        out = self.save("--replace", "my-desk")
        doc = self.read_layout()
        self.assertTrue(out["replaced"])
        self.assertEqual((doc["title"], doc["description"]), ("My desk 🌙", "My first arrangement"))
        self.assertEqual(doc["widget"][0]["at"], [round(160 / 2560, 5), round(24 / 1440, 5)])
        self.save("--replace", "my-desk", "--description", "")
        self.assertEqual(self.read_layout()["description"], "")
        self.save("--replace", "my-desk")
        self.assertEqual(self.read_layout()["description"], "")

    def test_packaged_collision_needs_explicit_override_and_keeps_package(self):
        package = Path(self.env["BROMIGOS_SHARE_DIR"]) / "widgets/layouts"
        package.mkdir(parents=True)
        target = package / "sample.toml"
        original = ('title = "Sample title"\ndescription = "Packaged arrangement"\n'
                    '[[widget]]\nname = "network"\nside = "left"\n')
        target.write_text(original)
        self.save("Sample", ok=False)
        self.assertFalse((self.layouts / "sample.toml").exists())
        out = self.save("--replace", "sample")
        self.assertTrue(out["overrode_packaged"])
        self.assertEqual((out["title"], out["description"]), ("Sample title", "Packaged arrangement"))
        self.assertEqual(target.read_text(), original)
        listing = self.cmd("panels", "layouts")
        saved = next(t for t in listing["layouts"] if t["id"] == "sample")
        self.assertEqual(saved["source"], "yours")
        self.assertEqual(self.read_layout("sample")["widget"][0]["name"], "system")

    def test_missing_invalid_and_reserved_targets_are_refused(self):
        for ident in ("not-here", "../layout", "theme", "theme-wick"):
            with self.subTest(ident=ident):
                self.save("--replace", ident, ok=False)
        self.assertEqual(list(self.layouts.glob("*.toml")), [])

    def test_replace_does_not_accept_a_new_name_or_duplicate_flags(self):
        self.save("My desk")
        before = (self.layouts / "my-desk.toml").read_bytes()
        for args in (("New title", "--replace", "my-desk"), ("--replace", "my-desk", "--replace", "minimal"),
                     ("--replace", "my-desk", "--unknown"), ("--replace",)):
            with self.subTest(args=args):
                self.save(*args, ok=False)
                self.assertEqual((self.layouts / "my-desk.toml").read_bytes(), before)

    def test_invalid_user_override_is_not_silently_replaced_from_package(self):
        self.layouts.mkdir()
        target = self.layouts / "minimal.toml"
        for text in ("broken = [", "widget = 7"):
            with self.subTest(text=text):
                target.write_text(text)
                self.save("Minimal", ok=False)
                out = self.save("--replace", "minimal", ok=False)
                self.assertIn("cannot be read", out["error"])
                self.assertEqual(target.read_text(), text)

    def test_empty_arrangement_does_not_destroy_saved_layout(self):
        self.save("My desk")
        before = (self.layouts / "my-desk.toml").read_bytes()
        self.desk(visible=False)
        out = self.save("--replace", "my-desk", ok=False)
        self.assertIn("no widgets", out["error"])
        self.assertEqual((self.layouts / "my-desk.toml").read_bytes(), before)

    def test_monitor_selection_saves_only_that_monitors_widgets(self):
        self.desk(second=True)
        env = {"HYPRLAND_INSTANCE_SIGNATURE": "fixture"}
        self.save("Side screen", "--monitor", "HDMI-A-1", env=env)
        doc = self.read_layout("side-screen")
        self.assertEqual([w["name"] for w in doc["widget"]], ["network"])
        self.assertEqual(doc["widget"][0]["at"], [round(48 / 1920, 5), round(48 / 1080, 5)])
        self.save("--replace", "side-screen", "--monitor", "DP-1", env=env)
        self.assertEqual([w["name"] for w in self.read_layout("side-screen")["widget"]], ["system"])

    def test_linked_dotfile_is_preserved_when_replacing_its_contents(self):
        self.layouts.mkdir()
        original = Path(self.tmp) / "original.toml"
        original.write_text('title = "Original"\n[[widget]]\nname = "network"\nside = "left"\n')
        (self.layouts / "linked.toml").symlink_to(original)
        out = self.save("--replace", "linked")
        self.assertEqual(out["title"], "Original")
        self.assertEqual(tomllib.loads(original.read_text())["widget"][0]["name"], "system")
        self.assertTrue((self.layouts / "linked.toml").is_symlink())

    def test_link_to_packaged_template_does_not_redirect_replacement(self):
        self.layouts.mkdir()
        package = Path(self.env["BROMIGOS_SHARE_DIR"]) / "widgets/layouts"
        package.mkdir(parents=True)
        original = package / "original.toml"
        original.write_text('title = "Original"\n[[widget]]\nname = "network"\nside = "left"\n')
        (self.layouts / "linked.toml").symlink_to(original)
        before = original.read_bytes()
        out = self.save("--replace", "linked", ok=False)
        self.assertIn("points into packaged", out["error"])
        self.assertEqual(original.read_bytes(), before)
        self.assertTrue((self.layouts / "linked.toml").is_symlink())
