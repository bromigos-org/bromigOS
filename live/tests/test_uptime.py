"""The shaders' sine hashes stay usable after days of uptime, without a GPU.

    cd live && python -m unittest discover -s tests

A graphics card's sin() can't tell large numbers apart, so a sine hash fed with a number
that grows with the time ends up the same for every cell: after about three days the rain
was all one glyph. The fix is hwrap() (rain.glsl) and w_hwrap() (world_common.glsl), which
fold a hash's input into a small range. These rules keep a new hash from skipping them.
The rendered check, at 4, 30 and 120 days: tests/offscreen_uptime.py.
"""
import glob
import os
import re
import unittest

SHADERS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shaders")


def lines():
    for path in sorted(glob.glob(os.path.join(SHADERS, "*"))):
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                code = line.split("//")[0]
                if code.strip():
                    yield os.path.basename(path), n, line.rstrip("\n"), code


class HashTest(unittest.TestCase):
    def test_every_sine_hash_folds_its_input(self):
        """fract(sin(x) * big) is only a hash while x is small: x goes through hwrap()."""
        found = 0
        for name, n, line, code in lines():
            if re.search(r"fract\(\s*sin\(", code):
                found += 1
                self.assertIn("hwrap(", line, f"{name}:{n}: a sine hash whose input isn't folded: {line.strip()}")
        self.assertGreaterEqual(found, 5, "the hashes moved: point this test at them")

    def test_a_count_of_time_steps_is_folded_before_it_is_hashed(self):
        """hash(cell + floor(u_time * rate)): a float can't hold the cell once the count is
        in the millions, so the count is folded first: hwrap(floor(u_time * rate))."""
        for name, n, line, code in lines():
            m = re.search(r"hash\w*\(", code)          # what follows is, or may be, a hash's input
            if m and "floor(u_time" in code[m.end():]:
                self.assertEqual(len(re.findall(r"(?<!hwrap\()floor\(u_time", code[m.end():])), 0,
                                 f"{name}:{n}: fold the step count, hwrap(floor(u_time * rate)): {line.strip()}")

    def test_the_folds_leave_small_inputs_alone(self):
        """Both folds are x - 1024 * trunc(x / 1024): nothing changes inside +-1024, so the
        scene at short uptimes looks as it always did, and both files fold alike."""
        for fname, fn in (("rain.glsl", "hwrap"), ("world_common.glsl", "w_hwrap")):
            with open(os.path.join(SHADERS, fname), encoding="utf-8") as f:
                src = f.read()
            self.assertRegex(src, rf"float {fn}\(float n\) \{{ return n - 1024\.0 \* trunc\(n / 1024\.0\); \}}")
            self.assertRegex(src, rf"vec2 {fn}\(vec2 p\) \{{ return p - 1024\.0 \* trunc\(p / 1024\.0\); \}}")


if __name__ == "__main__":
    unittest.main()
