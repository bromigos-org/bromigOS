"""Power actions are mocked; screens are in-memory offscreen grids."""
import contextlib
import curses
import io
import unittest
from unittest.mock import Mock, patch

import bromigos_power_menu as P


class Screen:
    def __init__(self, keys=(), height=24, width=80):
        self.keys = iter(keys)
        self.height, self.width = height, width
        self.erase()

    def erase(self): self.grid = [[' '] * self.width for _ in range(self.height)]
    def getmaxyx(self): return self.height, self.width
    def refresh(self): pass
    def keypad(self, on): pass
    def get_wch(self): return next(self.keys)
    def addnstr(self, y, x, text, count, style=0):
        for index, char in enumerate(text[:count]): self.grid[y][x+index] = char
    def text(self): return '\n'.join(''.join(row).rstrip() for row in self.grid)


class PowerMenu(unittest.TestCase):
    def choose(self, keys, **size):
        with patch.object(P.curses, 'curs_set'), patch.object(P.curses, 'has_colors', return_value=False):
            return P.choose(Screen(keys, **size))

    def test_initial_enter_and_escape_cancel_without_action(self):
        self.assertIsNone(self.choose(['\n']))
        self.assertIsNone(self.choose(['\x1b']))

    def test_arrow_confirmation_defaults_cancel_and_can_explicitly_confirm(self):
        down, right, enter = curses.KEY_DOWN, curses.KEY_RIGHT, curses.KEY_ENTER
        # Restart -> Enter on default Cancel -> Escape from menu.
        self.assertIsNone(self.choose([down, down, enter, enter, '\x1b']))
        self.assertEqual(self.choose([down, down, enter, right, enter]), 'reboot')
        self.assertEqual(self.choose([down, down, down, enter, right, enter]), 'poweroff')

    def test_vim_keys_and_tab_work_in_both_views(self):
        self.assertEqual(self.choose(['j', 'j', 'j', 'k', '\n', 'l', 'h', '\t', '\n']), 'reboot')
        self.assertEqual(self.choose(['\t', '\n', 'j', '\n']), 'suspend')

    def test_escape_from_confirmation_never_runs_selected_action(self):
        self.assertIsNone(self.choose(['j', '\n', 'l', '\x1b', 'q']))

    def test_resize_cannot_accept_an_action_while_menu_is_unreadable(self):
        self.assertIsNone(self.choose(['j', '\n', curses.KEY_RESIZE, 'l', '\n', 'q'], height=8, width=30))

    def test_preview_never_calls_systemctl_and_failure_code_is_preserved(self):
        with patch.object(P.subprocess, 'run') as runner, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(P.perform('poweroff', preview=True), 0)
            self.assertEqual(P.perform(None), 0)
            runner.assert_not_called()
        with patch.object(P.subprocess, 'run', return_value=Mock(returncode=5)) as runner, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(P.perform('reboot'), 5)
            runner.assert_called_once_with(['/usr/bin/systemctl', '--no-ask-password', 'reboot'], check=False)

    def test_render_uses_console_safe_glyphs_and_keeps_frame_intact(self):
        for width in (38, 80, 160):
            for confirming in (False, True):
                screen = Screen(width=width)
                P.draw(screen, P.Menu(selected=3, confirming=confirming), preview=True)
                self.assertTrue(screen.text().isascii())
                self.assertIn('POWER', screen.text())
                self.assertIn('Shut down', screen.text())
                box_width = min(58, width - 4)
                right = (width - box_width) // 2 + box_width - 1
                for row in screen.grid[7:17]: self.assertEqual(row[right], '|')


if __name__ == '__main__': unittest.main()
