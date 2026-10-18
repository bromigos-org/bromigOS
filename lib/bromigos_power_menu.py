"""Keyboard power menu. Actions run only after curses restores the terminal."""
import argparse
import curses
from dataclasses import dataclass
import os
import subprocess
import sys

CHOICES = (('Cancel', None), ('Suspend', 'suspend'), ('Restart', 'reboot'), ('Shut down', 'poweroff'))
QUESTIONS = {'suspend': 'Suspend the computer?', 'reboot': 'Restart the computer?', 'poweroff': 'Shut down the computer?'}


@dataclass
class Menu:
    selected: int = 0
    confirming: bool = False
    affirmative: bool = False
    closed: bool = False
    action: str | None = None

    def key(self, key):
        if self.closed:
            return
        if key in ('escape', 'q'):
            if self.confirming:
                self.confirming = self.affirmative = False
            else:
                self.closed = True
        elif self.confirming:
            if key in ('left', 'h'):
                self.affirmative = False
            elif key in ('right', 'l'):
                self.affirmative = True
            elif key in ('up', 'down', 'j', 'k', 'tab'):
                self.affirmative = not self.affirmative
            elif key == 'enter':
                if self.affirmative:
                    self.action = CHOICES[self.selected][1]
                    self.closed = True
                else:
                    self.confirming = False
        elif key in ('up', 'k'):
            self.selected = (self.selected - 1) % len(CHOICES)
        elif key in ('down', 'j', 'tab'):
            self.selected = (self.selected + 1) % len(CHOICES)
        elif key == 'enter':
            if CHOICES[self.selected][1] is None:
                self.closed = True
            else:
                self.confirming, self.affirmative = True, False


def _put(screen, row, column, text, style=0):
    height, width = screen.getmaxyx()
    if row < 0 or row >= height or column >= width - 1:
        return
    try:
        screen.addnstr(row, max(0, column), text, max(0, width - max(0, column) - 1), style)
    except curses.error:
        pass  # A terminal resize can race the dimensions above.


def draw(screen, menu, *, preview=False, accent=0):
    screen.erase()
    height, width = screen.getmaxyx()
    if height < 12 or width < 38:
        _put(screen, 0, 0, 'Make the terminal at least 38 x 12.')
        _put(screen, 1, 0, 'Esc or q cancels.')
        screen.refresh()
        return
    box_width, box_height = min(58, width - 4), 12
    left, top = (width - box_width) // 2, max(0, (height - box_height) // 2)
    def content(row, text, style=0, offset=3):
        _put(screen, top + row, left + offset, text[:box_width - offset - 2], style)
    _put(screen, top, left, '+' + '-' * (box_width - 2) + '+', accent)
    for row in range(top + 1, top + box_height - 1):
        _put(screen, row, left, '|', accent)
        _put(screen, row, left + box_width - 1, '|', accent)
    _put(screen, top + box_height - 1, left, '+' + '-' * (box_width - 2) + '+', accent)
    content(1, 'B R O M I G O S   /   POWER', accent | curses.A_BOLD)
    if preview:
        content(2, 'Preview - actions disabled')
    if menu.confirming:
        action = CHOICES[menu.selected][1]
        content(4, QUESTIONS[action], curses.A_BOLD)
        content(5, 'Save your work first.')
        for yes, label, offset in ((False, 'Cancel', 3), (True, CHOICES[menu.selected][0], 17)):
            content(7, '[ ' + label + ' ]', curses.A_REVERSE if menu.affirmative == yes else 0, offset)
        content(9, 'Arrows: choose  Enter: confirm')
    else:
        for index, (label, _) in enumerate(CHOICES):
            content(4 + index, ('> ' if index == menu.selected else '  ') + label,
                    curses.A_REVERSE if index == menu.selected else 0)
        content(9, 'Up/Down: choose  Enter: select')
    content(10, 'Esc: back  j/k h/l: move')
    screen.refresh()


def choose(screen, preview=False):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.keypad(True)
    accent = 0
    if curses.has_colors() and 'NO_COLOR' not in os.environ:
        curses.start_color()
        try:
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            accent = curses.color_pair(1)
        except curses.error:
            pass
    menu = Menu()
    keys = {curses.KEY_UP: 'up', curses.KEY_DOWN: 'down', curses.KEY_LEFT: 'left', curses.KEY_RIGHT: 'right',
            curses.KEY_ENTER: 'enter', '\n': 'enter', '\r': 'enter', '\t': 'tab', '\x1b': 'escape'}
    while not menu.closed:
        draw(screen, menu, preview=preview, accent=accent)
        key = screen.get_wch()
        if key == curses.KEY_RESIZE:
            continue
        if min(screen.getmaxyx()) < 1:
            continue
        if screen.getmaxyx()[0] < 12 or screen.getmaxyx()[1] < 38:
            if key in ('\x1b', 'q'):
                return None
            continue
        menu.key(keys.get(key, key))
    return menu.action


def perform(action, *, preview=False):
    if action is None:
        return 0
    if action not in QUESTIONS:
        raise ValueError('Unsupported power action')
    if preview:
        print('Preview: ' + action + ' selected; no power action was run.')
        return 0
    # Standard logind policy and inhibitors apply; never force or escalate.
    result = subprocess.run(['/usr/bin/systemctl', '--no-ask-password', action], check=False)
    if result.returncode:
        print('Power action refused. Check active sessions, inhibitors and permissions.', file=sys.stderr)
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(prog='bromigos power menu', description='Choose and confirm a power action with the keyboard')
    parser.add_argument('--preview', action='store_true', help='Try the menu without running any power action')
    args = parser.parse_args(argv)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('Open the menu in an interactive terminal or text console')
    try:
        action = curses.wrapper(choose, args.preview)
        return perform(action, preview=args.preview)
    except KeyboardInterrupt:
        return 0
    except (curses.error, OSError):
        print('Cannot open the power menu or run the selected action.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
