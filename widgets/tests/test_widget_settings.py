"""widget_settings.py: a widget's fields, its values (default, layout.json, its file), the
checks on what's typed, and <name>.toml written in one step through a symlink."""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import widget_settings as WS  # noqa: E402

SCHEMA = [
    {"key": "place", "label": "Place", "kind": "text", "default": ""},
    {"key": "hosts", "label": "Hosts", "kind": "list", "default": ["gateway"]},
    {"key": "every", "label": "Every", "kind": "number", "default": 60, "min": 10, "max": 3600},
    {"key": "glow", "label": "Glow", "kind": "bool", "default": True},
    {"key": "units", "label": "Units", "kind": "choice", "default": "metric",
     "choices": [["metric", "°C"], ["imperial", "°F"]]},
    {"key": "account", "label": "GitHub", "kind": "secret-signin", "provider": "github"},
    {"label": "no key: dropped"}, {"key": "x", "kind": "colour"},
]


class WidgetSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.tmp, "config")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.old
        shutil.rmtree(self.tmp)

    def test_fields_keep_the_well_formed(self):
        self.assertEqual([f["key"] for f in WS.fields(SCHEMA)], ["place", "hosts", "every", "glow", "units", "account"])

    def test_defaults_then_layout_then_the_file(self):
        v = WS.values("demo", SCHEMA)
        self.assertEqual(v, {"place": "", "hosts": ["gateway"], "every": 60, "glow": True, "units": "metric",
                             "account": []})                     # a sign-in's value: which accounts (none: all)
        v = WS.values("demo", SCHEMA, layout={"place": "Oslo", "every": 30})
        self.assertEqual((v["place"], v["every"]), ("Oslo", 30))
        WS.set_value("demo", SCHEMA, "place", "Bergen")
        v = WS.values("demo", SCHEMA, layout={"place": "Oslo"})
        self.assertEqual(v["place"], "Bergen")                          # the file wins

    def test_what_is_typed_is_checked(self):
        f = {f["key"]: f for f in WS.fields(SCHEMA)}
        self.assertEqual(WS.parse(f["hosts"], "a, b,,c"), ["a", "b", "c"])
        self.assertEqual(WS.parse(f["hosts"], ["a", " b "]), ["a", "b"])
        self.assertEqual(WS.parse(f["every"], "90"), 90)
        self.assertEqual(WS.parse(f["glow"], "off"), False)
        self.assertEqual(WS.parse(f["units"], "imperial"), "imperial")
        for k, bad in (("every", "5"), ("every", "soon"), ("glow", "maybe"), ("units", "kelvin"),
                       ("place", "two\nlines"), ("account", "token")):
            with self.assertRaises(ValueError, msg=(k, bad)):
                WS.parse(f[k], bad)

    def test_a_sign_in_holds_account_names_never_a_token(self):
        import bromigos_account as A                                     # on the path through widget_settings
        f = {f["key"]: f for f in WS.fields(SCHEMA)}
        A.add_account("github", "work", base="https://github.example.org", client_id="ghe-app")
        self.assertEqual(WS.parse(f["account"], "default, work"), ["default", "work"])
        self.assertEqual(WS.set_value("demo", SCHEMA, "account", ["work"])["account"], ["work"])
        token_shape = "gh" + "p_" + "0123456789abcdefghijklmnopqrstuvwxyz"     # made-up, built so no scanner trips
        for bad in (token_shape, "nobody", "Work Laptop"):
            with self.assertRaises(ValueError, msg=bad):
                WS.parse(f["account"], bad)

    def test_written_through_a_symlink(self):
        dots = os.path.join(self.tmp, "dotfiles")
        os.makedirs(dots)
        real = os.path.join(dots, "demo.toml")
        with open(real, "w") as fh:
            fh.write('place = "Oslo"\n')
        os.makedirs(os.path.dirname(WS.path("demo")))
        os.symlink(real, WS.path("demo"))
        WS.set_value("demo", SCHEMA, "hosts", ["a", "b"])
        self.assertTrue(os.path.islink(WS.path("demo")))
        self.assertEqual(WS.read_file("demo"), {"place": "Oslo", "hosts": ["a", "b"]})
        WS.unset("demo", "hosts")
        self.assertEqual(WS.read_file("demo"), {"place": "Oslo"})
        self.assertEqual(os.listdir(dots), ["demo.toml"])               # nothing left beside it

    def test_the_reader_sees_a_change(self):
        r = WS.Reader("demo", SCHEMA)
        self.assertEqual(r.get()["place"], "")
        time.sleep(0.01)
        WS.set_value("demo", SCHEMA, "place", "Tromsø")
        self.assertEqual(r.get()["place"], "Tromsø")

    def test_a_panel_reads_its_settings(self):
        import panels as P

        class Demo(P.Panel):
            name = "demo"
            settings = SCHEMA
        p = Demo({"name": "demo", "every": 120})
        self.assertEqual(p.setting("every"), 120)                       # layout.json's key
        WS.set_value("demo", SCHEMA, "every", "300")
        self.assertEqual(p.setting("every"), 300)
        self.assertIsNone(p.setting("nope"))


if __name__ == "__main__":
    unittest.main()
