"""The graphical installers' idle and timeout callbacks stop. GLib runs one again for as long as it
returns true, and a toolkit method given bare can return true for ever: 0.1.4's
GLib.idle_add(self.next.grab_focus) took the keyboard's focus back to Continue thousands of
times a second (grab_focus() returns True when it took it), so no field could be typed in. A
callback is one of the installer's own functions, which say when they stop, or a lambda that
ends in False (gui.focus_soon). iso/test.sh gui-type is the test with a real pointer and keys."""
import ast
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "profile/airootfs/usr/local/lib/bromigos-iso/bromigos_installer"
FILES = ("gui.py", "server_gui.py", "welcome.py")
ADDERS = {"idle_add": 0, "timeout_add": 1, "timeout_add_seconds": 1}


def bare_toolkit_callbacks(sources):
    """(file, line, text) of each idle/timeout callback that's a method the installer doesn't define."""
    trees = {name: ast.parse(src) for name, src in sources.items()}
    own = {n.name for t in trees.values() for n in ast.walk(t) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    bad = []
    for name, tree in trees.items():
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ADDERS):
                continue
            at = ADDERS[call.func.attr]
            if len(call.args) <= at:
                continue
            cb = call.args[at]
            for c in ((cb.body, cb.orelse) if isinstance(cb, ast.IfExp) else (cb,)):
                if isinstance(c, ast.Attribute) and c.attr not in own:
                    bad.append((name, call.lineno, ast.unparse(c)))
    return bad


class IdleCallbacksStop(unittest.TestCase):
    def test_no_toolkit_method_given_bare(self):
        bad = bare_toolkit_callbacks({name: (LIB / name).read_text() for name in FILES})
        self.assertEqual(bad, [], "a toolkit method as an idle or timeout callback repeats while it returns true: "
                                  "use focus_soon(), or a lambda that ends in False")

    def test_the_check_sees_what_0_1_4_had(self):
        src = ("def show_step(self, sid):\n"
               "    GLib.idle_add(self.next.grab_focus if sid not in ('install', 'done') else (lambda: False))\n"
               "    GLib.idle_add(self.script_step)\n"
               "    GLib.timeout_add(300, win.present)\n"
               "def script_step(self):\n    return False\n")
        self.assertEqual([b[2] for b in bare_toolkit_callbacks({"gui.py": src})], ["self.next.grab_focus", "win.present"])

    def test_focus_is_given_once(self):
        src = (LIB / "gui.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "focus_soon")
        self.assertIn("False)[1]", ast.unparse(fn))


if __name__ == "__main__":
    unittest.main()
