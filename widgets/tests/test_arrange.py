"""arrange.py: snapping, free space, undo, and layout.json written through a symlink."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import arrange as A  # noqa: E402

AREA = (1600, 860)


class SnapMove(unittest.TestCase):
    def test_grid_when_nothing_is_near(self):
        x, y, guides = A.snap_move((203, 397, 300, 200), [], AREA)
        self.assertEqual((x, y), (200, 400))
        self.assertEqual(guides, [])

    def test_snaps_to_another_panels_edge_with_a_guide(self):
        other = (100, 100, 400, 300)
        # left edge 3 px from the other's left edge: aligned, a vertical guide there
        x, y, guides = A.snap_move((103, 450, 200, 100), [other], AREA)
        self.assertEqual(x, 100)
        self.assertIn(("v", 100, 100, 548), guides)     # spans both panels

    def test_snaps_to_the_gap_beside_a_panel(self):
        other = (100, 100, 400, 300)
        x, y, _ = A.snap_move((100 + 400 + 16 + 5, 105, 200, 100), [other], AREA)
        self.assertEqual((x, y), (516, 100))           # 16 px right of it, tops aligned

    def test_the_closest_line_wins(self):
        others = [(0, 0, 100, 100), (106, 300, 100, 100)]
        # left edge at 103: 3 px from 100 (the first's right), 3 px from 106: a tie keeps the first
        x, _, _ = A.snap_move((104, 500, 50, 50), others, AREA)
        self.assertEqual(x, 106)

    def test_centres_align(self):
        other = (100, 100, 400, 300)              # centre x 300
        x, _, guides = A.snap_move((203, 500, 200, 100), [other], AREA)   # centre 303
        self.assertEqual(x, 200)
        self.assertTrue(any(g[0] == "v" and g[1] == 300 for g in guides))

    def test_kept_inside_the_area(self):
        x, y, _ = A.snap_move((1500, 800, 300, 200), [], AREA)
        self.assertEqual((x, y), (1300, 660))
        x, y, _ = A.snap_move((-50, -20, 300, 200), [], AREA)
        self.assertEqual((x, y), (0, 0))

    def test_no_snapping_with_ctrl(self):
        x, y, guides = A.snap_move((103, 397, 200, 100), [(100, 100, 400, 300)], AREA, snap=False)
        self.assertEqual((x, y, guides), (103, 397, []))


class SnapResize(unittest.TestCase):
    LIMITS = ((200, 150), (800, 600))

    def test_corner_snaps_to_grid_and_keeps_the_opposite_corner(self):
        r, _ = A.snap_resize((100, 100, 300, 200), "se", 503, 397, [], AREA, self.LIMITS)
        self.assertEqual(r, (100, 100, 404, 300))
        r, _ = A.snap_resize((100, 100, 300, 200), "nw", 53, 61, [], AREA, self.LIMITS)
        self.assertEqual(r, (56, 64, 344, 236))

    def test_within_the_panels_limits(self):
        r, _ = A.snap_resize((100, 100, 300, 200), "se", 120, 120, [], AREA, self.LIMITS)
        self.assertEqual(r, (100, 100, 200, 150))         # its minimum
        r, _ = A.snap_resize((100, 100, 300, 200), "se", 1500, 900, [], AREA, self.LIMITS)
        self.assertEqual(r, (100, 100, 800, 600))         # its maximum
        r, _ = A.snap_resize((300, 300, 300, 200), "nw", 550, 450, [], AREA, self.LIMITS)
        self.assertEqual((r[0] + r[2], r[1] + r[3]), (600, 500))   # bottom right stays
        self.assertEqual(r[2:], (200, 150))

    def test_an_edge_snaps_to_a_neighbour(self):
        other = (600, 100, 300, 300)
        r, guides = A.snap_resize((100, 100, 300, 200), "se", 597, 395, [other], AREA, self.LIMITS)
        self.assertEqual(r[2], 500)                       # right edge on the neighbour's left
        self.assertEqual(r[3], 300)                       # bottom on its bottom
        self.assertTrue(any(g[0] == "v" and g[1] == 600 for g in guides))

    def test_inside_the_area(self):
        r, _ = A.snap_resize((1300, 600, 250, 200), "se", 1900, 1000, [], AREA, self.LIMITS)
        self.assertEqual((r[0] + r[2], r[1] + r[3]), AREA)


class FreeSpot(unittest.TestCase):
    def test_beside_the_panels_clear_of_them(self):
        taken = [(28, 16, 470, 470), (28, 502, 470, 262)]
        x, y = A.free_spot(470, 300, taken, AREA)
        self.assertEqual((x, y), (514, 16))
        self.assertTrue(A.fits((x, y, 470, 300), taken, AREA, gap=16))

    def test_under_the_one_in_its_column(self):
        taken = [(28, 16, 470, 470), (514, 16, 470, 300)]
        x, y = A.free_spot(470, 300, taken, AREA)
        self.assertTrue(A.fits((x, y, 470, 300), taken, AREA, gap=16))
        self.assertEqual((x, y), (28, 504))            # under the first, 16 px down

    def test_avoids_reserved_corners_and_says_when_full(self):
        x, y = A.free_spot(400, 300, [], AREA, avoid=[(0, 0, 800, 860)])
        self.assertGreaterEqual(x, 816)
        self.assertIsNone(A.free_spot(400, 300, [(0, 0, 1600, 860)], AREA))

    def test_place_falls_back_when_the_reserved_corners_leave_no_room(self):
        taken = [(28, 16, 470, 470)]
        avoid = [(400, 0, 1200, 860)]                    # a small screen, mostly VECTOR's corner
        x, y = A.place(470, 300, taken, AREA, avoid)
        self.assertTrue(A.fits((x, y, 470, 300), taken, AREA, gap=16))
        self.assertEqual(A.place(2000, 300, [], AREA), (0, 16))     # too wide for anywhere: inside, at the left

    def test_lands_on_the_grid(self):
        x, y = A.free_spot(333, 222, [(28, 16, 301, 203)], AREA)
        self.assertEqual(y % 8, 0)


class Undo(unittest.TestCase):
    def setUp(self):
        self.t = 0.0
        self.h = A.History(clock=lambda: self.t)

    def test_undo_then_redo(self):
        s0, s1, s2 = {"a": {"x": 0}}, {"a": {"x": 8}}, {"a": {"x": 16}}
        self.h.push(s0)
        self.h.push(s1)
        self.assertEqual(self.h.undo(s2), s1)
        self.assertEqual(self.h.undo(s1), s0)
        self.assertIsNone(self.h.undo(s0))
        self.assertEqual(self.h.redo(s0), s1)
        self.assertEqual(self.h.redo(s1), s2)
        self.assertIsNone(self.h.redo(s2))

    def test_a_new_change_drops_the_redos(self):
        self.h.push({"a": 1})
        self.h.undo({"a": 2})
        self.assertTrue(self.h.can_redo())
        self.h.push({"a": 1})
        self.assertFalse(self.h.can_redo())

    def test_nudges_in_a_row_undo_as_one(self):
        self.h.push({"x": 0}, key="nudge system")
        self.t = 0.3
        self.assertFalse(self.h.push({"x": 1}, key="nudge system"))
        self.t = 0.6
        self.h.push({"x": 2}, key="nudge system")
        self.assertEqual(self.h.undo({"x": 3}), {"x": 0})
        self.t = 5.0
        self.h.push({"x": 0}, key="nudge system")
        self.t = 7.0                                       # long after: its own step
        self.assertTrue(self.h.push({"x": 1}, key="nudge system"))

    def test_states_are_copies(self):
        s = {"a": {"x": 0}}
        self.h.push(s)
        s["a"]["x"] = 99
        self.assertEqual(self.h.undo({}), {"a": {"x": 0}})


class LayoutFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "BROMIGOS_SHARE_DIR")}
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.tmp, "config")
        os.environ["BROMIGOS_SHARE_DIR"] = os.path.join(self.tmp, "share")
        os.makedirs(os.path.join(self.tmp, "share", "widgets"))
        shutil.copy(os.path.join(A.HERE, "layout.json"), os.path.join(self.tmp, "share", "widgets"))

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp)

    def test_reads_bromigos_layout_until_there_is_yours(self):
        d, path, mine = A.read()
        self.assertFalse(mine)
        self.assertTrue(path.startswith(os.path.join(self.tmp, "share")))
        A.write(d)
        d, path, mine = A.read()
        self.assertTrue(mine)

    def test_apply_keeps_every_other_key(self):
        d, _, _ = A.read()
        st = A.state_of(d)
        self.assertFalse(st["weather"]["visible"])
        self.assertTrue(st["system"]["visible"])
        new = A.apply(d, {"system": {"x": 40, "y": 48, "width": 480, "height": 460, "visible": True},
                          "weather": {"visible": True}, "load_panel": {"x": 600, "y": 16, "visible": True}})
        net = next(p for p in new["panels"] if p["name"] == "network")
        self.assertEqual(net["ping"][1]["host"], "1.1.1.1")
        self.assertIn("_comment", new)
        self.assertEqual(A.state_of(new)["system"], {"x": 40, "y": 48, "width": 480, "height": 460, "visible": True})
        self.assertTrue(A.state_of(new)["weather"]["visible"])
        self.assertEqual(A.state_of(new)["load_panel"]["x"], 600)        # a plugin: a new entry
        self.assertTrue(A.state_of(d)["system"]["x"] == 28)               # the original untouched

    def test_a_plugins_map_entry_is_updated_where_it_is(self):
        d = {"panels": [], "plugins": {"lab": {"x": 1, "y": 2}}}
        new = A.apply(d, {"lab": {"x": 100, "y": 200, "visible": False}})
        self.assertEqual(new["plugins"]["lab"], {"x": 100, "y": 200, "visible": False})
        self.assertEqual(new["panels"], [])

    def test_write_through_a_symlink_keeps_the_link(self):
        dots = os.path.join(self.tmp, "dotfiles", "bromigos", "widgets")
        os.makedirs(dots)
        real = os.path.join(dots, "layout.json")
        with open(real, "w") as f:
            f.write('{"monitor": "", "panels": [{"name": "system", "x": 1, "y": 1}]}')
        os.chmod(real, 0o640)
        link = A.user_path()
        os.makedirs(os.path.dirname(link))
        os.symlink(os.path.relpath(real, os.path.dirname(link)), link)
        d, path, mine = A.read()
        self.assertTrue(mine)
        written = A.write(A.apply(d, {"system": {"x": 64, "y": 32}}))
        self.assertTrue(os.path.islink(link))
        self.assertEqual(written, os.path.realpath(real))
        with open(real) as f:
            self.assertEqual(json.load(f)["panels"][0]["x"], 64)
        self.assertEqual(os.stat(real).st_mode & 0o777, 0o640)
        self.assertEqual([n for n in os.listdir(dots)], ["layout.json"])    # no temporary left

    def test_changed(self):
        a = {"s": {"x": 1}, "n": {"x": 2}}
        b = {"s": {"x": 1}, "n": {"x": 3}}
        self.assertEqual(A.changed(a, b), {"n": {"x": 3}})


if __name__ == "__main__":
    unittest.main()


class SizeClasses(unittest.TestCase):
    CLASSES = [("compact", (240, 140), (360, 220)), ("standard", (420, 300), (560, 480)),
               ("large", (700, 560), (1000, 900))]

    def test_inside_a_class_it_stays(self):
        self.assertEqual(A.fit_class(self.CLASSES, 500, 400), (500, 400, "standard"))
        self.assertEqual(A.fit_class(self.CLASSES, 300, 180), (300, 180, "compact"))

    def test_between_classes_it_snaps_to_the_nearest(self):
        self.assertEqual(A.fit_class(self.CLASSES, 380, 260), (360, 220, "compact"))
        self.assertEqual(A.fit_class(self.CLASSES, 400, 290), (420, 300, "standard"))
        self.assertEqual(A.fit_class(self.CLASSES, 640, 520), (700, 560, "large"))
        self.assertEqual(A.fit_class(self.CLASSES, 5000, 5000), (1000, 900, "large"))

    def test_a_resize_keeps_the_far_corner(self):
        r, name = A.resize_in_classes((100, 100, 380, 260), "nw", self.CLASSES, AREA)
        self.assertEqual((r, name), ((120, 140, 360, 220), "compact"))      # bottom right stays at 480,360
        r, name = A.resize_in_classes((1400, 100, 640, 520), "se", self.CLASSES, AREA)
        self.assertEqual(name, "large")
        self.assertLessEqual(r[0] + r[2], AREA[0])                         # still inside the area


class MakeRoom(unittest.TestCase):
    """A panel made bigger grows where it is and pushes its neighbours aside; it moves only
    when they can't move, and never onto the scene: the Wick's den, 2560x1440 with its bar."""

    @classmethod
    def setUpClass(cls):
        import layouts as L
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        info = L.scene_info("wick", os.path.join(repo, "themes", "wick"))
        scr = L.Screen.size(2560, 1440)
        cls.area = (scr.W, scr.H)
        rects = L.scene_rects(info["clear"], scr)
        cls.hard = [r[:4] for r in rects if not r[5]]
        cls.soft = [r[:4] for r in rects if r[5]]

    def desk(self):
        """His desk as it was when LAB was made taller: LAB and SYSTEM on the left wall,
        VECTOR and ALERTS beside them, the den remote at the bottom, CI under the window."""
        return {"vector": (510, 24, 460, 300), "alerts": (510, 340, 460, 300), "system": (24, 680, 300, 180),
                "media": (340, 1000, 620, 200), "ci": (2056, 880, 480, 300)}

    def test_lab_grows_in_place_and_system_moves_down(self):
        lab = (24, 24, 470, 640)
        r = A.make_room((24, 24, 470, 900), self.desk(), self.area, self.hard, self.soft, before=lab)
        self.assertEqual(r["how"], "pushed")
        self.assertEqual(r["rect"], (24, 24, 470, 900))            # where it was: never onto the scene
        self.assertEqual(r["moved"], {"system": (24, 940)})       # SYSTEM under it, a gap away
        others = dict(self.desk(), system=(24, 940, 300, 180))
        for n, o in others.items():
            self.assertFalse(A.overlaps(r["rect"], o), n)

    def test_nothing_in_the_way_stays_put(self):
        r = A.make_room((24, 24, 470, 600), {"system": (24, 680, 300, 180)}, self.area, self.hard, self.soft,
                        before=(24, 24, 470, 640))
        self.assertEqual((r["how"], r["moved"], r["rect"]), ("in place", {}, (24, 24, 470, 600)))

    def test_moving_never_goes_onto_the_scene(self):
        # CI under the window, made much taller: in place it would cover the window and the
        # station; it moves to free space, which is never a keep-clear area
        ci = (2056, 880, 480, 300)
        others = {k: v for k, v in self.desk().items() if k != "ci"}
        r = A.make_room((2056, 880, 480, 600), others, self.area, self.hard, self.soft, before=ci)
        self.assertEqual(r["how"], "moved")
        for a in self.hard:
            self.assertFalse(A.overlaps(r["rect"], a), (r["rect"], a))
        for o in others.values():
            self.assertFalse(A.overlaps(r["rect"], o, A.GAP), (r["rect"], o))
        # 700 tall: no free spot off the scene at all, so no room (it isn't put on the window)
        self.assertIsNone(A.make_room((2056, 880, 480, 700), others, self.area, self.hard, self.soft, before=ci))

    def test_the_teleport_that_happened(self):
        # LAB 470x900 when nothing could be pushed used to land at 986,16: on the window
        crowded = dict(self.desk(), system=(24, 680, 470, 700), media=(24, 1396 - 10, 10, 10))
        r = A.make_room((24, 24, 470, 900), crowded, self.area, self.hard, self.soft, before=(24, 24, 470, 640))
        if r is not None:
            for a in self.hard:
                self.assertFalse(A.overlaps(r["rect"], a), (r, a))

    def test_no_room_anywhere_says_so(self):
        full = {f"p{i}": (i * 400, 0, 384, 600) for i in range(4)}
        self.assertIsNone(A.make_room((0, 0, 380, 900), full, (1600, 860), before=(0, 0, 380, 600)))
        self.assertIsNone(A.make_room((24, 24, 470, 2000), {}, self.area))           # taller than the screen
        self.assertEqual(A.no_room_to_grow("LAB", (24, 24, 470, 640), (24, 24, 470, 900)),
                         "No room to make LAB 900 tall here: move or hide something")
        self.assertEqual(A.no_room_to_grow("CI", (0, 0, 480, 300), (0, 0, 780, 300)),
                         "No room to make CI 780 wide here: move or hide something")

    def test_pushes_cascade(self):
        # A grows down into B, which goes down into C, which goes down too
        others = {"b": (0, 220, 300, 100), "c": (0, 340, 300, 100)}
        r = A.make_room((0, 0, 300, 300), others, (1000, 1000), before=(0, 0, 300, 200))
        self.assertEqual(r["moved"], {"b": (0, 316), "c": (0, 432)})

    def test_place_never_gives_up_the_hard_areas(self):
        # everything but the scene's keep-clear areas taken: no spot, rather than one on the scene
        W, H = self.area
        taken = [(x, y, 64, 64) for x in range(0, W, 80) for y in range(0, H, 80)
                 if not any(A.overlaps((x, y, 64, 64), a, A.GAP) for a in self.hard)]
        self.assertIsNone(A.place(300, 200, taken, self.area, hard=self.hard, strict=True))
