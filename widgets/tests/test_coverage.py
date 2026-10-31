"""Which monitors are covered by windows, from Hyprland's JSON (both its old and 0.57 shapes),
without a live Hyprland or GTK."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'bromigos-widgets'


def load(names, cls=None):
    """The named top-level functions (or methods of `cls`), compiled into one namespace."""
    tree = ast.parse(SOURCE.read_text())
    body = tree.body if cls is None else next(c.body for c in tree.body
                                               if isinstance(c, ast.ClassDef) and c.name == cls)
    nodes = [n for n in body if isinstance(n, ast.FunctionDef) and n.name in names]
    return nodes


def check_with(monitors, clients):
    ns = {'GLib': SimpleNamespace(idle_add=lambda f: None),
          'hypr_request': lambda what: {'j/monitors': monitors, 'j/clients': clients}[what]}
    nodes = load({'_workspace_key'}) + load({'check'}, cls='Coverage')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), ns)
    cov = SimpleNamespace(on=set(), on_change=lambda: None)
    ns['check'](cov)
    return cov.on


def ws(id=None, name='', address=None, kind='normal'):
    out = {'name': name, 'type': kind}
    if id is not None:
        out['id'] = id
    if address is not None:
        out['address'] = address
    return out


class Coverage(unittest.TestCase):
    def test_hyprland_057_special_workspace_has_no_id(self):
        # 0.57: special workspaces carry an address and a name, no id. This crashed the widgets.
        special = ws(name='special:special', address='special:special', kind='special')
        mons = [{'name': 'DP-3', 'activeWorkspace': ws(8, '8', '8'), 'specialWorkspace': special}]
        clients = [{'workspace': special, 'floating': False, 'mapped': True},
                   {'workspace': ws(2, '2', '2'), 'floating': False, 'mapped': True}]
        self.assertEqual(check_with(mons, clients), {'DP-3'})

    def test_hyprland_057_tiled_window_on_another_workspace_does_not_cover(self):
        special = ws(name='special:special', address='special:special', kind='special')
        mons = [{'name': 'DP-3', 'activeWorkspace': ws(8, '8', '8')}]
        clients = [{'workspace': special, 'floating': False, 'mapped': True},
                   {'workspace': ws(2, '2', '2'), 'floating': False, 'mapped': True}]
        self.assertEqual(check_with(mons, clients), set())

    def test_older_hyprland_ids_still_work(self):
        mons = [{'name': 'DP-1', 'activeWorkspace': ws(3, '3'), 'specialWorkspace': ws(0, '')}]
        clients = [{'workspace': ws(3, '3'), 'floating': False, 'mapped': True},
                   {'workspace': ws(-98, 'special:magic'), 'floating': False, 'mapped': True}]
        self.assertEqual(check_with(mons, clients), {'DP-1'})

    def test_floating_windows_do_not_cover(self):
        mons = [{'name': 'DP-1', 'activeWorkspace': ws(3, '3', '3')}]
        clients = [{'workspace': ws(3, '3', '3'), 'floating': True, 'mapped': True}]
        self.assertEqual(check_with(mons, clients), set())

    def test_a_client_without_a_workspace_is_skipped(self):
        mons = [{'name': 'DP-1', 'activeWorkspace': ws(3, '3', '3')}]
        clients = [{'floating': False, 'mapped': True}]
        self.assertEqual(check_with(mons, clients), set())


if __name__ == '__main__':
    unittest.main()
