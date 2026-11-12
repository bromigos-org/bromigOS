"""Settings › Lab › Creation studio (settings/pages/lab.py, studio_view): what the group says
for each state of `bromigos lab studio status --json`, and which command each button runs.
No window, no real `bromigos`."""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(DESKTOP, "settings"), os.path.join(DESKTOP, "lib")]

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
    HAVE_GTK = True
except (ImportError, ValueError):
    HAVE_GTK = False


def page_module():
    spec = importlib.util.spec_from_file_location("lab_page", os.path.join(DESKTOP, "settings", "pages", "lab.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def cap(c, words, workflow, ready, missing=()):
    return {"capability": c, "words": words, "workflow": workflow, "ready": ready, "missing": list(missing)}


READY = {"installed": True, "answers": True, "comfyui_version": "0.38.0", "missing": [], "previous": {},
         "capabilities": [cap("image.cutout", "cutouts", "lucida", True),
                          cap("video.loop", "video loops", "wan2.2-ti2v-5b", True),
                          cap("image.generate", "pictures from a prompt", None, False)]}


@unittest.skipUnless(HAVE_GTK, "GTK 4 and libadwaita's Python bindings aren't installed")
class StudioView(unittest.TestCase):
    def setUp(self):
        self.m = page_module()

    def test_not_set_up_offers_one_choice(self):
        rows = self.m.studio_view({"installed": False})
        self.assertEqual(len(rows), 1)
        self.assertEqual([b[1] for b in rows[0]["buttons"]], ["setup"])
        self.assertEqual(rows[0]["runs"], "bromigos lab apps add comfyui")
        self.assertIn("checks every file", rows[0]["hint"])

    def test_ready_says_what_it_makes_in_plain_words(self):
        rows = self.m.studio_view(READY)
        self.assertEqual(rows[0]["title"], "●  Ready")
        self.assertIn("makes cutouts, video loops", rows[0]["subtitle"])
        self.assertIn("pictures from a prompt: nothing fits this card yet", rows[0]["hint"])
        self.assertIn("open", [b[1] for b in rows[0]["buttons"]])

    def test_missing_files_get_a_fix_button(self):
        doc = dict(READY, missing=["vae/wan_2.1_vae.safetensors"],
                   capabilities=[cap("video.loop", "video loops", "wan2.2-i2v-a14b", False,
                                     ["vae/wan_2.1_vae.safetensors"])])
        rows = self.m.studio_view(doc)
        self.assertEqual(rows[0]["title"], "✖  1 model file missing")
        self.assertIn("Not ready: video loops", rows[0]["subtitle"])
        self.assertEqual([b[1] for b in rows[0]["buttons"]], ["fix"])
        self.assertEqual(rows[0]["runs"], "bromigos lab studio apply")
        self.assertEqual(self.m.STUDIO_FIX, ["bromigos", "lab", "studio", "apply", "--json"])

    def test_comfyui_down_gets_restart_and_an_upgrade_says_what_it_kept(self):
        rows = self.m.studio_view(dict(READY, answers=False,
                                       previous={"video.loop": {"workflow": "wan2.2-ti2v-5b", "at": 0}}))
        self.assertEqual([b[1] for b in rows[0]["buttons"]], ["restart"])
        self.assertTrue(any(r["runs"] == "bromigos lab studio rollback video.loop" for r in rows))
        self.assertNotIn("open", [b[1] for r in rows for b in r["buttons"]])

    def test_no_answer_says_where_to_look(self):
        rows = self.m.studio_view(None)
        self.assertIn("didn't answer", rows[0]["title"])


if __name__ == "__main__":
    unittest.main()
