"""Read and atomically save a console font; no live console or service access."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tempfile

CONFIG = Path('/etc/vconsole.conf')
LOCK = Path('/run/lock/bromigos-console.lock')
FONTS = Path('/usr/share/kbd/consolefonts')
SIZES = {'small': 'ter-v16n', 'medium': 'ter-v24n', 'large': 'ter-v32n'}
NOTICE = 'Takes effect after reboot. Early boot may still use the font stored in the initramfs.'


class Error(Exception):
    pass


def _read():
    if CONFIG.parent.resolve() != CONFIG.parent:
        raise Error('The console configuration must not use symlink aliases')
    try:
        fd = os.open(CONFIG, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return '', {}, None
    except OSError:
        raise Error('Cannot read a regular, non-symlink console configuration') from None
    with os.fdopen(fd, 'r', encoding='utf-8', newline='') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise Error('Console configuration must be a small regular file')
        text = stream.read(65537)
    if len(text) > 65536 or any(char in text for char in ('\r', '\0')):
        raise Error('Unsupported console configuration; use single-line assignments')
    values = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(('#', ';')):
            continue
        match = re.fullmatch(r'\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)', line)
        try:
            words = shlex.split(line, comments=True, posix=True)
        except ValueError:
            words = []
        if not match or len(words) != 1 or '=' not in words[0] or line.rstrip().endswith('\\'):
            raise Error('Unsupported console configuration; use single-line assignments')
        key, value = words[0].split('=', 1)
        if key != match[1] or key in values:
            raise Error('Duplicate or unsupported console configuration assignment')
        values[key] = value
    return text, values, info


def status():
    _, values, _ = _read()
    font = values.get('FONT') or None
    return {'config': str(CONFIG), 'font': font, 'size': next((key for key, value in SIZES.items() if value == font), 'custom' if font else 'default'),
            'available_sizes': [key for key, value in SIZES.items() if (FONTS / (value + '.psf.gz')).is_file()],
            'note': 'This is the saved setting, not a measurement of the running console font.'}


def _require_root(size):
    if os.geteuid() != 0:
        raise Error('Save the console font yourself with sudo bromigos console font ' + size)


def set_font(size):
    _require_root(size)
    font = None if size == 'default' else SIZES[size]
    if font and not (FONTS / (font + '.psf.gz')).is_file():
        raise Error('Install terminus-font before selecting this console font')
    descriptor = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        lock_info = os.fstat(lock.fileno())
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid():
            raise Error('The console configuration lock needs a regular root-owned file')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error('Another console configuration change is running') from None
        original, values, info = _read()
        if font and any(values.get(key) for key in ('FONT_MAP', 'FONT_UNIMAP')):
            raise Error('Review existing FONT_MAP and FONT_UNIMAP overrides before selecting a Terminus font')
        lines = [line for line in original.splitlines(keepends=True) if not re.match(r'^\s*FONT=', line)]
        changed = ''.join(lines)
        if font:
            changed += ('' if not changed or changed.endswith('\n') else '\n') + 'FONT=' + font + '\n'
        if changed == original:
            return {'size': size, 'font': font, 'changed': False}
        fd, temporary = tempfile.mkstemp(prefix='.vconsole-', dir=CONFIG.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode) if info else 0o644)
                if info:
                    os.fchown(stream.fileno(), info.st_uid, info.st_gid)
                stream.write(changed); stream.flush(); os.fsync(stream.fileno())
            if _read()[0] != original:
                raise Error('Console configuration changed while saving; try again')
            os.replace(temporary, CONFIG)
            directory = os.open(CONFIG.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {'size': size, 'font': font, 'changed': True}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='bromigos console', description='Read or save the text console font for the next boot')
    commands = parser.add_subparsers(dest='action')
    reading = commands.add_parser('status', help='Read the saved setting and installed Terminus sizes')
    reading.add_argument('--json', action='store_true')
    writing = commands.add_parser('font', help='Save a font size as root; takes effect after reboot')
    writing.add_argument('size', choices=(*SIZES, 'default'))
    args = parser.parse_args(argv)
    try:
        if args.action == 'font':
            result = set_font(args.size)
            print('Saved console font: ' + result['size'] + (' (' + result['font'] + ')' if result['font'] else ''))
            print(NOTICE)
        else:
            result = status()
            if getattr(args, 'json', False):
                print(json.dumps(result, indent=2))
            else:
                print('Saved console font: ' + result['size'] + (' (' + json.dumps(result['font']) + ')' if result['font'] else ''))
                print('Installed sizes: ' + (', '.join(result['available_sizes']) or 'none; install terminus-font'))
                print(result['note'])
        return 0
    except (Error, OSError, UnicodeError) as error:
        print('Console settings stopped: ' + (str(error) if isinstance(error, Error) else 'Cannot read or save the console configuration'), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
