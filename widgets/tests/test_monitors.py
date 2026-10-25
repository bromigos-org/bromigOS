"""arrange.py: each panel on a monitor of its own. Finding that monitor by make, model and
serial (else its connector), where a panel shows while its monitor is unplugged and what
layout.json keeps for it then, the only monitor switched off and on again (the panels
back where they were), and bringing a layout with one monitor for every panel up to date,
written in one step through a symlink."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import arrange as A  # noqa: E402

DESK = {"id": 0, "name": "DP-1", "make": "Harbor Optics", "model": "HX27", "serial": "A100", "x": 0, "y": 0,
        "width": 2560, "height": 1440, "scale": 1, "transform": 0, "reserved": [0, 34, 0, 0]}
SIDE = {"id": 1, "name": "HDMI-A-1", "make": "Lamplight", "model": "L24", "serial": "B200", "x": 2560, "y": 0,
        "width": 3840, "height": 2160, "scale": 2, "transform": 0, "reserved": [0, 0, 0, 0]}
TWIN = {"id": 2, "name": "DP-2", "make": "Lamplight", "model": "L24", "serial": "", "x": 4480, "y": 0,
        "width": 1920, "height": 1080, "scale": 1, "transform": 1, "reserved": [0, 0, 0, 0]}


def moved(m, name):
    return dict(m, name=name)


class FindOutput(unittest.TestCase):
    def test_by_make_model_and_serial_on_any_port(self):
        want = A.identity(SIDE)
        self.assertEqual(want, {"make": "Lamplight", "model": "L24", "serial": "B200", "name": "HDMI-A-1"})
        self.assertEqual(A.find_output([DESK, SIDE], want), "HDMI-A-1")
        self.assertEqual(A.find_output([DESK, moved(SIDE, "DP-3")], want), "DP-3")     # another port

    def test_the_connector_is_the_fallback(self):
        self.assertEqual(A.find_output([DESK, SIDE], {"name": "DP-1"}), "DP-1")
        self.assertEqual(A.find_output([DESK, SIDE], "HDMI-A-1"), "HDMI-A-1")         # a plain name
        gone = dict(A.identity(SIDE), serial="Z999")                                   # another monitor there
        self.assertEqual(A.find_output([DESK, SIDE], gone), "HDMI-A-1")

    def test_not_connected(self):
        self.assertIsNone(A.find_output([DESK], A.identity(SIDE)))
        self.assertIsNone(A.find_output([], A.identity(DESK)))
        self.assertIsNone(A.find_output([DESK], None))
        self.assertIsNone(A.find_output([dict(DESK, disabled=True)], "DP-1"))

    def test_alike_without_serials_go_by_connector(self):
        a = dict(TWIN, name="DP-2", serial="")
        b = dict(TWIN, id=3, name="DP-4", serial="")
        self.assertEqual(A.find_output([a, b], A.identity(b)), "DP-4")
        self.assertEqual(A.find_output([a, b], dict(A.identity(b), name="DP-9")), "DP-2")   # the first

    def test_outputs_with_no_make_go_by_connector(self):
        # a nested or headless session's outputs say nothing about themselves
        a, b = {"name": "WAYLAND-1", "make": "", "model": "", "serial": ""}, {"name": "WAYLAND-2"}
        self.assertEqual(A.find_output([a, b], A.identity(b)), "WAYLAND-2")


class Geometry(unittest.TestCase):
    def test_usable_area_in_logical_px(self):
        self.assertEqual(A.usable(DESK), (0, 34, 2560, 1406))
        self.assertEqual(A.usable(SIDE), (2560, 0, 1920, 1080))          # scale 2
        self.assertEqual(A.bounds(TWIN), (4480, 0, 1080, 1920))          # turned on its side

    def test_monitor_at(self):
        mons = [DESK, SIDE, TWIN]
        self.assertEqual(A.monitor_at(mons, 10, 10), "DP-1")
        self.assertEqual(A.monitor_at(mons, 2559, 1439), "DP-1")
        self.assertEqual(A.monitor_at(mons, 2560, 0), "HDMI-A-1")
        self.assertEqual(A.monitor_at(mons, 4500, 1800), "DP-2")
        self.assertIsNone(A.monitor_at(mons, 3000, 1500))                # below the smaller one


class Unplugged(unittest.TestCase):
    AREA = (1920, 1046)

    def test_its_own_place_when_free(self):
        self.assertEqual(A.fallback_spot((600, 100, 400, 300), [(28, 16, 470, 470)], self.AREA), (600, 100))

    def test_a_free_spot_when_taken_or_off_the_area(self):
        taken = [(28, 16, 470, 470)]
        x, y = A.fallback_spot((40, 40, 400, 300), taken, self.AREA)
        self.assertFalse(A.overlaps((x, y, 400, 300), taken[0]))
        x, y = A.fallback_spot((3000, 1800, 400, 300), taken, self.AREA)      # from a bigger monitor
        self.assertTrue(A.fits((x, y, 400, 300), taken, self.AREA))

    def test_layout_keeps_its_own_monitor_and_place(self):
        pin = A.identity(SIDE)
        # SIDE unplugged: shown on DP-1 at 514,16; saved at 900,400 on SIDE
        self.assertEqual(A.kept_place(("DP-1", 514, 16), pin, ("DP-1", 514, 16), (900, 400), [DESK]),
                         (pin, 900, 400))

    def test_moved_by_hand_while_unplugged_it_stays_where_put(self):
        pin = A.identity(SIDE)
        got = A.kept_place(("DP-1", 600, 16), pin, ("DP-1", 514, 16), (900, 400), [DESK])
        self.assertEqual(got, (A.identity(DESK), 600, 16))

    def test_a_panel_on_the_primary_stays_unpinned(self):
        self.assertEqual(A.kept_place(("DP-1", 28, 16), None, None, None, [DESK, SIDE]), (None, 28, 16))

    def test_a_pinned_panel_gets_its_monitors_make_model_and_serial(self):
        got = A.kept_place(("HDMI-A-1", 40, 50), {"name": "HDMI-A-1"}, None, None, [DESK, SIDE])
        self.assertEqual(got, (A.identity(SIDE), 40, 50))


class SwitchedOff(unittest.TestCase):
    """The only monitor switched off: Hyprland puts a smaller stand-in output in its place
    (FALLBACK) until it's back. The panels that go on the primary stand in there, and
    return to exactly where they were."""
    STAND_IN = {"id": 1, "name": "FALLBACK", "make": "", "model": "", "serial": "", "x": 0, "y": 0,
                "width": 1920, "height": 1080, "scale": 1, "transform": 0, "reserved": [0, 0, 0, 0]}
    BACK = moved(DESK, "DP-1")
    MEDIA = (2156, 880, 380, 150)                 # bottom right of DESK, 2560 wide

    def test_the_primary_that_went_away_is_remembered(self):
        got = A.next_primary([self.STAND_IN], "DP-1", None, ("", ""), "FALLBACK", A.identity(DESK))
        self.assertEqual(got, ("FALLBACK", A.identity(DESK)))

    def test_it_is_the_primary_again_as_soon_as_it_is_back(self):
        # back while the stand-in is still there: no wait for the stand-in to go
        got = A.next_primary([self.STAND_IN, self.BACK], "FALLBACK", A.identity(DESK), ("", ""), "FALLBACK")
        self.assertEqual(got, ("DP-1", None))
        # on another port: found by make, model and serial
        got = A.next_primary([moved(DESK, "DP-4")], "FALLBACK", A.identity(DESK), ("",), "DP-4")
        self.assertEqual(got, ("DP-4", None))

    def test_the_first_to_go_is_the_one_waited_for(self):
        # the stand-in goes too, and another monitor comes: DESK is still the one waited for
        got = A.next_primary([SIDE], "FALLBACK", A.identity(DESK), (), "HDMI-A-1", A.identity(self.STAND_IN))
        self.assertEqual(got, ("HDMI-A-1", A.identity(DESK)))
        self.assertEqual(A.next_primary([DESK, SIDE], "HDMI-A-1", A.identity(DESK), (), "HDMI-A-1"), ("DP-1", None))

    def test_a_primary_chosen_wins(self):
        # `bromigos setup monitors` (or the layout's "monitor") names SIDE: that's the primary
        got = A.next_primary([DESK, SIDE], "FALLBACK", A.identity(DESK), ("", "HDMI-A-1"), "HDMI-A-1")
        self.assertEqual(got, ("HDMI-A-1", None))

    def test_nothing_changes_while_the_primary_is_there(self):
        self.assertEqual(A.next_primary([DESK, SIDE], "DP-1", None, (), "HDMI-A-1"), ("DP-1", None))
        self.assertEqual(A.next_primary([DESK], "DP-1", A.identity(DESK), (), "DP-1"), ("DP-1", None))
        self.assertEqual(A.next_primary([], "DP-1", None, (), None), ("DP-1", None))

    def test_a_panel_stands_in_inside_the_smaller_output(self):
        self.assertEqual(A.on_new_primary(self.MEDIA, (1920, 1080), home=self.MEDIA[:2]), (1540, 880))

    def test_back_on_its_monitor_it_goes_exactly_where_it_was(self):
        # it stood in at 1540,880; DESK is back: 2156,880, not 1540
        self.assertEqual(A.on_new_primary((1540, 880, 380, 150), (2560, 1440), (2156, 880), back=True), (2156, 880))

    def test_on_another_monitor_its_own_place_moved_in_to_fit(self):
        # plugged into a different monitor: from its own place, not from where it stood in
        self.assertEqual(A.on_new_primary((1540, 880, 380, 150), (3440, 1440), (2156, 880)), (2156, 880))
        self.assertEqual(A.on_new_primary((1540, 880, 380, 150), (1280, 720), (2156, 880)), (900, 570))
        # one that wasn't standing in moves in from where it is, as before
        self.assertEqual(A.on_new_primary((2156, 880, 380, 150), (1920, 1080)), (1540, 880))

    def test_layout_json_keeps_its_place_while_it_stands_in(self):
        fell = ("FALLBACK", 1540, 880)
        self.assertEqual(A.kept_place(fell, None, fell, (2156, 880), [self.STAND_IN]), (None, 2156, 880))

    def test_moved_by_hand_while_standing_in_it_still_goes_on_the_primary(self):
        got = A.kept_place(("FALLBACK", 600, 16), None, ("FALLBACK", 1540, 880), (2156, 880), [self.STAND_IN])
        self.assertEqual(got, (None, 600, 16))

    def test_the_toolkits_monitor_by_its_whole_rect(self):
        # the monitor back and the stand-in share a top left for a moment
        rects = [(0, 0, 1920, 1080), (0, 0, 2560, 1440)]
        self.assertEqual(A.gdk_index(rects, DESK), 1)
        self.assertEqual(A.gdk_index(rects, self.STAND_IN), 0)
        self.assertEqual(A.gdk_index([(0, 0, 2560, 1439)], DESK), 0)       # a size rounded: its top left
        self.assertEqual(A.gdk_index([(2560, 0, 1920, 1080)], SIDE), 0)     # scale 2: logical px
        self.assertIsNone(A.gdk_index([(2560, 0, 1920, 1080)], DESK))


class Migrate(unittest.TestCase):
    OLD = {"_comment": "mine", "monitor": "HDMI-A-1",
           "panels": [{"name": "system", "x": 28, "y": 16}, {"name": "notes", "x": 514, "y": 16, "ping": [1]}],
           "plugins": {"lab": {"x": 1000, "y": 16}}}

    def test_one_monitor_for_all_becomes_each_panels_own(self):
        new, got = A.migrate(self.OLD, [DESK, SIDE])
        self.assertTrue(got)
        self.assertEqual(new["version"], A.VERSION)
        for entry in new["panels"] + [new["plugins"]["lab"]]:
            self.assertEqual(entry["output"], A.identity(SIDE))
        self.assertEqual(new["monitor"], "HDMI-A-1")                      # kept: where new panels go
        self.assertEqual(new["panels"][1]["ping"], [1])                   # every other key kept
        self.assertNotIn("version", self.OLD)                             # the original untouched

    def test_a_monitor_not_connected_is_kept_by_name(self):
        new, got = A.migrate(self.OLD, [DESK])
        self.assertTrue(got)
        self.assertEqual(new["panels"][0]["output"], {"name": "HDMI-A-1"})

    def test_the_primary_needs_nothing(self):
        new, got = A.migrate({"monitor": "", "panels": [{"name": "system", "x": 1, "y": 1}]}, [DESK])
        self.assertFalse(got)
        self.assertEqual(new["version"], A.VERSION)
        self.assertNotIn("output", new["panels"][0])

    def test_a_panel_with_its_own_monitor_keeps_it_and_twice_changes_nothing(self):
        old = {"monitor": "DP-1", "panels": [{"name": "system", "output": A.identity(SIDE)}]}
        new, _ = A.migrate(old, [DESK, SIDE])
        self.assertEqual(new["panels"][0]["output"], A.identity(SIDE))
        self.assertEqual(A.migrate(new, [DESK, SIDE]), (new, False))


class Saved(unittest.TestCase):
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

    def test_apply_writes_and_takes_away_a_panels_monitor(self):
        d = {"panels": [{"name": "system", "x": 1, "y": 1, "output": {"name": "DP-1"}}],
             "plugins": {"lab": {"x": 1, "y": 2}}}
        new = A.apply(d, {"system": {"x": 2, "output": None}, "lab": {"output": A.identity(SIDE)}})
        self.assertNotIn("output", new["panels"][0])
        self.assertEqual(new["plugins"]["lab"]["output"], A.identity(SIDE))
        self.assertEqual(new["version"], A.VERSION)
        self.assertEqual(A.state_of(new)["lab"]["output"], A.identity(SIDE))

    def test_a_migrated_layout_is_written_through_its_symlink(self):
        dots = os.path.join(self.tmp, "dotfiles", "widgets")
        os.makedirs(dots)
        real = os.path.join(dots, "layout.json")
        with open(real, "w") as f:
            json.dump(Migrate.OLD, f)
        link = A.user_path()
        os.makedirs(os.path.dirname(link))
        os.symlink(real, link)
        d, _path, mine = A.read()
        new, got = A.migrate(d, [DESK, SIDE])
        self.assertTrue(mine and got)
        A.write(new)
        self.assertTrue(os.path.islink(link))
        with open(real) as f:
            back = json.load(f)
        self.assertEqual(back["panels"][0]["output"]["serial"], "B200")
        self.assertEqual(os.listdir(dots), ["layout.json"])                # no temporary left

    def test_bromigos_layout_is_version_2_with_no_monitors_of_its_own(self):
        with open(os.path.join(A.HERE, "layout.json")) as f:      # this checkout's, not an installed one
            d = json.load(f)
        self.assertEqual(d["version"], A.VERSION)
        self.assertFalse(any("output" in p for p in d["panels"]))
        self.assertFalse(A.migrate(d, [DESK])[1])


if __name__ == "__main__":
    unittest.main()
