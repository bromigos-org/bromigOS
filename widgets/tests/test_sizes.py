"""panels.Panel's size classes: what a panel declares, and which class a size is in."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gallery as G  # noqa: E402
import panels as P  # noqa: E402


class Declared(P.Panel):
    name = "declared"
    sizes = {"compact": ((240, 140), (360, 220)), "standard": ((420, 300), (560, 480), (470, 320)),
             "large": ((700, 560), (1000, 900))}
    default_size = "standard"


class Plain(P.Panel):
    name = "plain"
    width, height = 400, 200
    min_size, max_size = (300, 150), (800, 400)


class SizeClasses(unittest.TestCase):
    def test_declared_classes_in_order_with_their_start(self):
        cs = Declared.size_classes()
        self.assertEqual([c[0] for c in cs], ["compact", "standard", "large"])
        self.assertEqual(cs[1][3], (470, 320))                  # its own start
        self.assertEqual(cs[0][3], (240, 140))                  # else its minimum
        self.assertEqual(Declared.limits(), ((240, 140), (1000, 900)))
        self.assertEqual(Declared.start_size(), (470, 320))
        self.assertEqual(Declared.start_size("large"), (700, 560))

    def test_which_class_a_size_is_in(self):
        self.assertEqual(Declared.size_class(300, 200), "compact")
        self.assertEqual(Declared.size_class(800, 700), "large")
        self.assertEqual(Declared.size_class(380, 250), "compact")   # between: the nearest
        self.assertEqual(Declared.size_class(5000, 5000), "large")

    def test_a_panel_that_declares_nothing_has_one_class(self):
        self.assertEqual(Plain.size_classes(), [("standard", (300, 150), (800, 400), (400, 200))])
        self.assertEqual(Plain.size_class(10, 10), "standard")

    def test_the_gallery_lists_them(self):
        m = G.meta_of(Declared, "declared")
        self.assertEqual([c["name"] for c in m["sizes"]], ["compact", "standard", "large"])
        self.assertEqual((m["default_size"], m["start"]), ("standard", [470, 320]))
        self.assertEqual((m["min_size"], m["max_size"]), ((240, 140), (1000, 900)))

    def test_every_built_in_panel_declares_sane_classes(self):
        for name, cls in P.CORE.items():
            cs = cls.size_classes()
            self.assertTrue(cs, name)
            for cname, lo, hi, start in cs:
                self.assertIn(cname, P.SIZE_CLASSES, name)
                self.assertTrue(lo[0] <= start[0] <= hi[0] and lo[1] <= start[1] <= hi[1], (name, cname))
            self.assertIn(cls.default_size, [c[0] for c in cs], name)
            for i, a in enumerate(cs):                 # no size is in two classes
                for b in cs[i + 1:]:
                    overlap = (a[1][0] <= b[2][0] and b[1][0] <= a[2][0] and a[1][1] <= b[2][1] and b[1][1] <= a[2][1])
                    self.assertFalse(overlap, f"{name}: {a[0]} and {b[0]} overlap")


if __name__ == "__main__":
    unittest.main()
