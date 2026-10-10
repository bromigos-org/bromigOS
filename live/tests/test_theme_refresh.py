"""A palette switch refreshes existing live surfaces, including paused overlays."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock


def method(cls, name, **ns):
    path = Path(__file__).resolve().parents[1] / 'live/app.py'
    tree = ast.parse(path.read_text())
    node = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == cls
                for n in c.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), ns)
    return ns[name]


class ThemeRefresh(TestCase):
    def test_existing_renderer_is_rebuilt_once_in_its_gl_context(self):
        import time
        theme = NS(version=lambda: 2)
        binding = [7]
        draw = method('GLWindow', '_render', glkit=NS(T=theme), time=time,
                      GL=NS(glGetIntegerv=lambda _: binding[0], GL_DRAW_FRAMEBUFFER_BINDING=0))
        state = {"scan_pin": True, "scan_held": False, "pin_amt": 1.0}
        old = NS(render=Mock(), theme_state=lambda: state)
        fresh = NS(render=Mock(), sf=1, restore_theme_state=Mock())
        close = Mock()
        def construct(*_):
            binding[0] = 99  # stage target allocation must not steal GTK's destination
            return fresh
        make = Mock(side_effect=construct)
        app = NS(bg=None)
        win = NS(failed=False, renderer=old, rsize=(100, 100), theme_seen=1,
                 _close_renderer=close, make_renderer=make, frames=5, fps=0, app=app)
        area = NS(get_scale_factor=lambda: 1, get_allocated_width=lambda: 100,
                  get_allocated_height=lambda: 100)
        draw(win, area, None)
        close.assert_called_once()
        make.assert_called_once_with(100, 100)
        old.render.assert_not_called()
        fresh.restore_theme_state.assert_called_once_with(state)
        fresh.render.assert_called_once_with(7, 1)
        draw(win, area, None)
        make.assert_called_once()
        self.assertEqual(fresh.render.call_count, 2)

    def test_palette_only_switch_queues_every_surface_even_with_no_world(self):
        import sys
        from unittest.mock import patch
        world = NS(signature=lambda _: None)
        check = method('App', 'check_world', __package__='live',
                       glkit=NS(T=NS(version=lambda _: 2)))
        surfaces = [NS(area=NS(queue_render=Mock())) for _ in range(3)]
        app = NS(bg=surfaces[0], overlays={'radial': surfaces[1], 'codec': surfaces[2]},
                 cfg={}, bg_enabled=True, world_sig=None, palette_seen=1)
        with patch.dict(sys.modules, {'live': NS(world=world)}):
            self.assertEqual(check(app), 'ok')
            check(app)
        for surface in surfaces:
            surface.area.queue_render.assert_called_once()
