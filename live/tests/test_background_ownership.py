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
            app = SimpleNamespace(bg_enabled=enabled, bg=SimpleNamespace(dead=dead, failed=failed, frames=1) if exists else None)
            self.assertEqual(ns['command'](app, 'background-active'), expected)
        app = SimpleNamespace(bg_enabled=True, bg=SimpleNamespace(dead=False, failed=False, frames=0))
        self.assertEqual(ns['command'](app, 'background-active'), 'off')

    def test_the_first_successful_background_frame_removes_the_still(self):
        import time
        from unittest.mock import Mock
        path = Path(__file__).resolve().parents[1] / 'live/app.py'
        tree = ast.parse(path.read_text())
        node = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'GLWindow'
                    for n in c.body if isinstance(n, ast.FunctionDef) and n.name == '_render')
        ns = {'time': time, 'glkit': SimpleNamespace(T=SimpleNamespace(version=lambda: 1)), 'GL': SimpleNamespace(glGetIntegerv=lambda _: 0, GL_DRAW_FRAMEBUFFER_BINDING=0)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), ns)
        reconcile = Mock()
        app = SimpleNamespace(wallpaper_fallback=reconcile)
        win = SimpleNamespace(failed=False, rsize=(100,100), renderer=SimpleNamespace(sf=1,render=lambda *_: None),
                              frames=0, fps=20, app=app, theme_seen=1)
        app.bg = win
        area = SimpleNamespace(get_scale_factor=lambda: 1, get_allocated_width=lambda: 100,
                               get_allocated_height=lambda: 100)
        ns['_render'](win, area, None)
        reconcile.assert_called_once()
        ns['_render'](win, area, None)
        reconcile.assert_called_once()
