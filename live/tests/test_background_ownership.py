"""Background ownership queried by the static wallpaper fallback, without GTK."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

class Ownership(unittest.TestCase):
    def test_only_a_healthy_background_owns_the_wallpaper(self):
        path = Path(__file__).resolve().parents[1] / 'live/app.py'
        tree = ast.parse(path.read_text())
        node = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'App'
                    for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'command')
        ns = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), ns)
        for enabled, exists, dead, failed, expected in [(True, True, False, False, 'on'),
                (False, True, False, False, 'off'), (True, False, False, False, 'off'),
                (True, True, True, False, 'off'), (True, True, False, True, 'off')]:
            app = SimpleNamespace(bg_enabled=enabled, bg=SimpleNamespace(dead=dead, failed=failed) if exists else None)
            self.assertEqual(ns['command'](app, 'background-active'), expected)
