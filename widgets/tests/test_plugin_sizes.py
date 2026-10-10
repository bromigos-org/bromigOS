"""Every built-in plugin panel (widgets/plugins/*.py): the gallery's words, sane size
classes that don't overlap (no size is in two classes), a default class it has, and off
by default."""
import glob
import os
import unittest

import plugintest  # noqa: F401  (a throwaway config home, the import path)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import panels as P  # noqa: E402
import plugins as PL  # noqa: E402

FILES = sorted(p for p in glob.glob(os.path.join(HERE, "plugins", "*.py")) if not os.path.basename(p).startswith("_"))


def check(test, name, cls, layout):
    test.assertTrue(cls.description and cls.reads, f"{name}: description and reads")
    test.assertIn(cls.category, P.CATEGORIES, name)
    cs = cls.size_classes()
    test.assertGreaterEqual(len(cs), 2, f"{name}: more than one size class")
    for cname, lo, hi, start in cs:
        test.assertIn(cname, P.SIZE_CLASSES, name)
        test.assertTrue(lo[0] <= start[0] <= hi[0] and lo[1] <= start[1] <= hi[1], (name, cname))
    test.assertIn(cls.default_size, [c[0] for c in cs], name)
    for i, a in enumerate(cs):
        for b in cs[i + 1:]:
            overlap = a[1][0] <= b[2][0] and b[1][0] <= a[2][0] and a[1][1] <= b[2][1] and b[1][1] <= a[2][1]
            test.assertFalse(overlap, f"{name}: {a[0]} and {b[0]} overlap")
    test.assertFalse(layout.get("visible", True), f"{name}: a new built-in panel starts off")


class BuiltInPlugins(unittest.TestCase):
    def test_each_declares_itself_for_the_gallery(self):
        self.assertTrue(FILES)
        for path in FILES:
            name = os.path.basename(path)[:-3]
            with self.subTest(name):
                cls, layout = PL.load(path)
                check(self, name, cls, layout)


if __name__ == "__main__":
    unittest.main()
