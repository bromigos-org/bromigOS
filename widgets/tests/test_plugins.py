"""plugins.py: a plugin's wake() reaches its window through the SafePanel around it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import panels as P  # noqa: E402
import plugins as PL  # noqa: E402


class Wake(unittest.TestCase):
    def test_the_wrapped_panel_is_found(self):
        inner, other = P.Panel({}), P.Panel({})
        safe = PL.SafePanel("demo", inner, "/dev/null")
        self.assertIs(safe.inner, inner)
        self.assertTrue(PL.same_panel(safe, inner))           # a plugin wakes with its own instance
        self.assertTrue(PL.same_panel(inner, inner))          # a core panel is its own window's
        self.assertFalse(PL.same_panel(safe, other))
        self.assertFalse(PL.same_panel(None, inner))


if __name__ == "__main__":
    unittest.main()
