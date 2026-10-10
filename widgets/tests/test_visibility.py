"""Exercise the daemon's command handler without opening GTK windows."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'bromigos-widgets'

def method(cls, name):
    tree = ast.parse(SOURCE.read_text())
    node = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == cls
                for n in c.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), ns)
    return ns[name]

class Window:
    def __init__(self, on):
        self.on = on
        self.win = self
    def visible(self):
        return self.on
    def show_all(self):
        self.on = True
    def hide(self):
        self.on = False

class Visibility(unittest.TestCase):
    def test_toggle_restores_exactly_the_visible_set(self):
        cmd = method('App', 'on_cmd')
        app = SimpleNamespace(windows={n: Window(on) for n, on in [('lab', True), ('ci', True), ('notes', False)]})
        def send(message):
            app.sock = SimpleNamespace(recv=lambda _: message.encode())
            cmd(app)
        for _ in range(3):
            send('toggle all')
            self.assertFalse(any(w.on for w in app.windows.values()))
            send('toggle all')
            self.assertEqual({n for n,w in app.windows.items() if w.on}, {'lab', 'ci'})
        send('toggle ci')
        send('toggle all')
        send('toggle all')
        self.assertEqual({n for n,w in app.windows.items() if w.on}, {'lab'})

    def test_empty_layout_stays_empty(self):
        app = SimpleNamespace(windows={'notes': Window(False)}, sock=SimpleNamespace(recv=lambda _: b'toggle all'))
        method('App', 'on_cmd')(app)
        self.assertFalse(app.windows['notes'].on)

    def test_plugin_draw_uses_the_actual_frame_height(self):
        # SafePanel delegates reads but dimensions assigned to it shadow its inner panel.
        frames = []
        app = SimpleNamespace(box=(470, 900), shown_height=lambda: 710,
                              panel=SimpleNamespace(width=470, height=640, render=lambda cr,w,h: frames.append((w,h))))
        method('PanelWindow', 'on_draw')(app, None, None)
        self.assertEqual(frames, [(470, 710)])
