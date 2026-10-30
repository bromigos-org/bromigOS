"""Settings › Graphics (settings/pages/graphics.py): what each Use for button runs, and why
it says no. A stand-in context records the commands; no window, no real `bromigos`. The page
itself is drawn offscreen by tools/settings/render.sh --page graphics, with a stand-in
`bromigos` answering for a fixture machine (--path)."""
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
    spec = importlib.util.spec_from_file_location("gx_page", os.path.join(DESKTOP, "settings", "pages", "graphics.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Ctx:
    """What the page asks of Settings, recorded."""

    def __init__(self):
        self.changes, self.toasts, self.terminals, self.asked = [], [], [], []

    def change(self, argv, said, undo=None, done=None, failed=None):
        self.changes.append(list(argv))

    def toast(self, text, undo=None, timeout=5):
        self.toasts.append(text)

    def terminal(self, argv, hold=True):
        self.terminals.append(list(argv))

    def confirm(self, heading, body, yes, then, destructive=False, no="Cancel"):
        self.asked.append((heading, body))
        then()                                 # say yes


class Btn:
    def __init__(self, active):
        self.active, self._quiet = active, False

    def get_active(self):
        return self.active

    def set_active(self, v):
        self.active = v


def card(slot, **kw):
    c = {"slot": slot, "title": f"Card {slot}", "desktop_ready": True, "game_ready": True, "driver": "amdgpu",
         "desktop_next": False, "games": False,
         "vfio": {"ready": False, "reserved": False, "checks": [{"id": "monitor", "ok": False,
                                                                 "text": "A monitor is connected to it (DP-1)"}]}}
    c.update(kw)
    return c


@unittest.skipUnless(HAVE_GTK, "GTK 4 and libadwaita's Python bindings aren't installed")
class UseFor(unittest.TestCase):
    def setUp(self):
        self.m = page_module()
        self.p = self.m.GraphicsPage.__new__(self.m.GraphicsPage)
        self.ctx = self.p.ctx = Ctx()
        self.p.refresh = lambda: None
        self.a = card("0000:03:00.0", desktop_next=True)
        self.b = card("0000:0a:00.0", games=True, driver="nvidia",
                      vfio={"ready": True, "reserved": False, "functions": ["0000:0a:00.1"], "checks": []})
        self.p.doc = {"cards": [self.a, self.b],
                      "desktop": {"choice": None, "next": {"slot": "0000:03:00.0", "source": "automatic"},
                                  "automatic": "0000:03:00.0"},
                      "games": {"choice": None, "slot": "0000:0a:00.0"}}

    def press(self, c, use, now_on):
        b = Btn(now_on)
        self.p._use(c, use, b)
        return b

    def test_a_new_desktop_card_asks_first_and_is_tried(self):
        b = self.press(self.b, "desktop", True)
        self.assertFalse(b.active, "the button shows the state until the command answers")
        heading, body = self.ctx.asked[0]
        self.assertIn("Try Card 0000:0a:00.0 for the desktop?", heading)
        self.assertIn("restart the computer", body)
        self.assertIn("sudo bromigos hw display reset", body)
        self.assertEqual(self.ctx.changes, [["bromigos", "hw", "display", "use", "0000:0a:00.0", "--json"]])

    def test_a_card_without_a_monitor_is_refused_with_its_reason(self):
        c = card("0000:0c:00.0", desktop_ready=False)
        self.press(c, "desktop", True)
        self.assertEqual(self.ctx.changes, [])
        self.assertIn("connect a monitor to it first", self.ctx.toasts[0])

    def test_turning_off_the_automatic_desktop_card_explains_instead(self):
        self.press(self.a, "desktop", False)
        self.assertEqual(self.ctx.changes, [])
        self.assertIn("automatic choice", self.ctx.toasts[0])
        self.p.doc["desktop"]["choice"] = {"slot": "0000:03:00.0"}
        self.press(self.a, "desktop", False)
        self.assertEqual(self.ctx.changes, [["bromigos", "hw", "display", "use", "auto", "--json"]])

    def test_games_move_without_a_password_and_can_be_undone(self):
        self.press(self.a, "games", True)
        self.assertEqual(self.ctx.changes, [["bromigos", "hw", "games", "use", "0000:03:00.0", "--json"]])
        self.assertEqual(self.ctx.asked, [])

    def test_vms_reserve_in_a_terminal_only_when_every_check_passes(self):
        self.press(self.a, "vms", True)
        self.assertEqual(self.ctx.terminals, [])
        self.assertIn("A monitor is connected to it", self.ctx.toasts[0])
        self.press(self.b, "vms", True)
        self.assertIn("0000:0a:00.1", self.ctx.asked[0][1])
        self.assertEqual(self.ctx.terminals, [["bromigos", "hw", "vfio", "reserve", "0000:0a:00.0"]])
        self.b["vfio"]["reserved"] = True
        self.press(self.b, "vms", False)
        self.assertEqual(self.ctx.terminals[-1], ["bromigos", "hw", "vfio", "release", "0000:0a:00.0"])

    def test_keep_and_go_back_and_reset(self):
        self.p.keep()
        self.p.cancel()
        self.p.doc["desktop"]["choice"] = {"slot": "0000:0a:00.0"}
        self.p.doc["games"]["choice"] = {"slot": "0000:03:00.0"}
        self.p.reset()
        self.assertEqual(self.ctx.changes, [
            ["bromigos", "hw", "display", "keep", "--json"], ["bromigos", "hw", "display", "cancel", "--json"],
            ["bromigos", "hw", "games", "use", "auto", "--json"], ["bromigos", "hw", "display", "use", "auto", "--json"]])

    def test_every_button_explains_itself(self):
        for c in (self.a, self.b, card("0000:0c:00.0", desktop_ready=False, game_ready=False)):
            for use, _ in self.m.USES:
                for on in (True, False):
                    self.assertTrue(self.p._use_hint(c, use, on))

    def test_search_finds_it(self):
        keys = {e.key for e in self.m.PAGE.entries}
        self.assertEqual(keys, {"desktop", "games", "steam", "run", "iommu", "reserved"})
        self.assertIn("vfio", self.m.PAGE.keywords)


if __name__ == "__main__":
    unittest.main()
