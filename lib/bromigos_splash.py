"""Persist Plymouth's shutdown theme and a GRUB splash flag, with rollback."""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile

GRUB_BEGIN = '# >>> bromigOS splash (bromigos splash off removes this block)'
GRUB_END = '# <<< bromigOS splash'
GRUB_BLOCK = f'''{GRUB_BEGIN}
case " ${{GRUB_CMDLINE_LINUX_DEFAULT}} ${{GRUB_CMDLINE_LINUX}} " in
    *" splash "*) ;;
    *) GRUB_CMDLINE_LINUX_DEFAULT="${{GRUB_CMDLINE_LINUX_DEFAULT}} splash" ;;
esac
{GRUB_END}
'''
THEME_BEGIN = '# >>> bromigOS splash theme'
THEME_END = '# <<< bromigOS splash theme'
THEME_BLOCK = f'{THEME_BEGIN}\nTheme=bromigos\n{THEME_END}\n'
NOTICE = 'Reboot once before using the new shutdown/restart visuals. The running kernel command line is unchanged.'


class Error(Exception):
    pass


@dataclass(frozen=True)
class Paths:
    # Dependency injection for fixture tests only; the CLI always uses the real root.
    root: Path = Path('/')

    def at(self, path):
        return self.root / path.lstrip('/')

    @property
    def grub(self): return self.at('/etc/default/grub')
    @property
    def generated(self): return self.at('/boot/grub/grub.cfg')
    @property
    def plymouth(self): return self.at('/etc/plymouth/plymouthd.conf')
    @property
    def state_dir(self): return self.at('/var/lib/bromigos/splash')
    @property
    def state(self): return self.state_dir / 'state.json'


def _read(path, limit=65536):
    if path.parent.resolve() != path.parent:
        raise Error(f'Refusing a symlink parent for {path}')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise Error(f'Expected a small regular file: {path}')
        value = stream.read(limit + 1)
        if len(value) > limit:
            raise Error(f'File is too large: {path}')
        return value


def _text(value):
    text = (value or b'').decode('utf-8')
    if '\0' in text or '\r' in text:
        raise Error('Configuration must use plain text and Unix line endings')
    return text


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path, value, *, expected, mode=0o644, limit=16 << 20):
    """Replace a regular file only if its contents still match the reviewed input."""
    if _read(path, limit) != expected:
        raise Error(f'Configuration changed while saving: {path}')
    info = path.stat(follow_symlinks=False) if expected is not None else None
    if info and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise Error(f'Configuration must be owned by root and not writable by others: {path}')
    if value is None:
        path.unlink(missing_ok=True)
        _sync_directory(path.parent)
        return
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode) if info else mode)
            if info:
                os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if _read(path, limit) != expected:
            raise Error(f'Configuration changed while saving: {path}')
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _block(text, begin, end, expected):
    if begin not in text and end not in text:
        return False
    if text.count(begin) != 1 or text.count(end) != 1 or text.count(expected) != 1:
        raise Error('A bromigOS splash block was edited; restore it before changing the splash')
    return True


def _theme(text):
    section = None
    values = []
    daemon_sections = 0
    lines = text.splitlines(keepends=True)
    daemon_line = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(('#', ';')):
            continue
        match = re.fullmatch(r'\[([^]]+)\]', stripped)
        if match:
            section = match[1]
            if section == 'Daemon':
                daemon_sections += 1
                daemon_line = index
        elif section == 'Daemon' and re.match(r'^Theme\s*=', stripped):
            values.append((index, stripped.split('=', 1)[1].strip()))
    if daemon_sections > 1 or len(values) > 1:
        raise Error('Plymouth has duplicate Daemon sections or Theme settings; review them first')
    return lines, daemon_line, values[0] if values else None


def _theme_on(before):
    text = _text(before)
    if _block(text, THEME_BEGIN, THEME_END, THEME_BLOCK):
        raise Error('A splash theme block already exists without matching saved state')
    lines, daemon, value = _theme(text)
    restore = ''
    if value:
        restore = lines[value[0]]
        lines[value[0]] = THEME_BLOCK
    elif daemon is not None:
        if not lines[daemon].endswith('\n'):
            lines[daemon] += '\n'
        lines.insert(daemon + 1, THEME_BLOCK)
    else:
        lines.append(('' if not text or text.endswith('\n') else '\n') + '[Daemon]\n' + THEME_BLOCK)
    return ''.join(lines).encode(), restore


def _loader(paths):
    path = paths.at('/sys/firmware/efi/efivars/LoaderInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f')
    raw = _read(path, 4096)
    return raw[4:].decode('utf-16-le').rstrip('\0').strip() if raw else None


def _check_grub(paths):
    if _read(paths.grub) is None or _read(paths.generated, 16 << 20) is None:
        raise Error('Only GRUB with /etc/default/grub and /boot/grub/grub.cfg is supported')
    loader = _loader(paths)
    if loader and 'grub' not in loader.lower():
        raise Error('The running boot loader is not GRUB; its configuration was left alone')
    dropins = paths.at('/etc/default/grub.d')
    if dropins.resolve() != dropins:
        raise Error('GRUB configuration includes a symlink directory; review it first')
    if dropins.exists():
        with os.scandir(dropins) as entries:
            for index, entry in enumerate(entries):
                if index >= 256 or entry.name.endswith('.cfg'):
                    raise Error('GRUB drop-in settings are not supported; review /etc/default/grub.d first')


def _saved_flags(text):
    # Status is read-only: never source a shell configuration just to inspect it.
    text = text.replace(GRUB_BLOCK, '')
    values = {}
    for line in text.splitlines():
        if line.lstrip().startswith('#'):
            continue
        match = re.match(r'^\s*(?:export\s+)?(GRUB_CMDLINE_LINUX(?:_DEFAULT)?)=(.*)$', line)
        if not match:
            if re.search(r'\bGRUB_CMDLINE_LINUX(?:_DEFAULT)?\s*=', line):
                return None
            continue
        if '$' in match[2] or '`' in match[2] or line.rstrip().endswith('\\'):
            return None
        words = shlex.split(line, comments=True)
        if words and words[0] == 'export':
            words = words[1:]
        if len(words) != 1 or '=' not in words[0]:
            return None
        values[match[1]] = words[0].split('=', 1)[1]
    return ' '.join(values.values()).split()


def _disabled(flags):
    return sorted(set(flags or ()) & {'plymouth.enable=0', 'plymouth.enable=false',
                                      'plymouth.enable=no', 'plymouth.enable=off', 'nosplash',
                                      'splash=verbose', 'single', '1', 's', 'S', '-S'})


def _runtime_ready(paths):
    programs = ('/usr/bin/plymouth', '/usr/bin/plymouthd')
    return (all(paths.at(name).is_file() and os.access(paths.at(name), os.X_OK) for name in programs)
            and paths.at('/usr/lib/plymouth/script.so').is_file())


def status(paths=None):
    paths = paths or Paths()
    issues = []
    def reading(path, default=b''):
        try:
            return _read(path) or default
        except (OSError, Error, UnicodeError):
            issues.append(f'Cannot read {path}')
            return default
    grub = _text(reading(paths.grub))
    plymouth = _text(reading(paths.plymouth))
    default = _text(reading(paths.at('/usr/share/plymouth/plymouthd.defaults')))
    try:
        _, _, theme = _theme(plymouth)
        _, _, fallback = _theme(default)
        selected = theme[1] if theme else fallback[1] if fallback else None
        flags = _saved_flags(grub)
        managed = _block(grub, GRUB_BEGIN, GRUB_END, GRUB_BLOCK)
    except (Error, ValueError) as error:
        issues.append(str(error))
        selected, flags, managed = None, None, False
    kernel = _text(reading(paths.at('/proc/cmdline'))).split()
    try:
        _check_grub(paths)
        supported = True
    except (Error, OSError, UnicodeError):
        supported = False
    theme_file = paths.at('/usr/share/plymouth/themes/bromigos/bromigos.plymouth')
    installed = bool(reading(theme_file))
    configured = managed or (None if flags is None else 'splash' in flags)
    return {'theme': selected, 'theme_installed': installed, 'plymouth_installed': _runtime_ready(paths), 'grub_supported': supported,
            'managed': managed, 'configured_splash': configured, 'current_kernel_splash': 'splash' in kernel,
            'current_kernel_graphical': bool(set(kernel) & {'splash', 'splash=silent', 'rhgb', 'plymouth.graphical'}),
            'configured_disabled': _disabled(flags), 'current_kernel_disabled': _disabled(kernel),
            'enabled': selected == 'bromigos' and configured is True and not _disabled(flags), 'issues': issues,
            'note': 'Shutdown/restart only; this command does not add Plymouth to the initramfs.'}


def _require_root(action):
    if os.geteuid() != 0:
        raise Error('Run sudo bromigos splash ' + action + ' to save this setting')


def _directory(path, mode=0o700):
    if path.parent.resolve() != path.parent or path.is_symlink():
        raise Error(f'Refusing a symlink directory: {path}')
    path.mkdir(mode=mode, parents=True, exist_ok=True)
    info = path.stat(follow_symlinks=False)
    if path.resolve() != path or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise Error(f'Expected a protected root-owned directory: {path}')


@contextmanager
def _locked(paths):
    _directory(paths.state_dir)
    lock_path = paths.state_dir / 'lock'
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise Error('The splash lock must be a root-owned regular file')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error('Another splash configuration change is running') from None
        yield


def _run(argv, log):
    with log.open('ab') as stream:
        try:
            result = subprocess.run(argv, stdout=stream, stderr=stream, timeout=180, check=False,
                                    env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        except subprocess.TimeoutExpired:
            raise Error(Path(argv[0]).name + ' timed out') from None
    if result.returncode:
        raise Error(Path(argv[0]).name + ' failed; see the saved log')


def change(action, paths=None, runner=None):
    paths, runner = paths or Paths(), runner or _run
    if action not in ('on', 'off'):
        raise Error('Choose on or off')
    _require_root(action)
    _check_grub(paths)
    with _locked(paths):
        old = {paths.grub: _read(paths.grub), paths.plymouth: _read(paths.plymouth),
               paths.generated: _read(paths.generated, 16 << 20), paths.state: _read(paths.state, 1 << 20)}
        for path, value in old.items():
            if value is not None:
                info = path.stat(follow_symlinks=False)
                if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                    raise Error(f'Configuration must be owned by root and not writable by others: {path}')
        saved = json.loads(old[paths.state]) if old[paths.state] else None
        if saved is not None and (not isinstance(saved, dict) or saved.get('schema') != 1 or type(saved.get('enabled')) is not bool):
            raise Error('Unrecognised saved splash state')
        if saved and saved['enabled']:
            if not all(isinstance(saved.get(key), str) for key in ('grub_before', 'grub_after', 'plymouth_after', 'plymouth_restore')) or not isinstance(saved.get('plymouth_before'), (str, type(None))):
                raise Error('Incomplete saved splash state')
        grub_text = _text(old[paths.grub])
        plymouth_text = _text(old[paths.plymouth])
        managed_grub = _block(grub_text, GRUB_BEGIN, GRUB_END, GRUB_BLOCK)
        managed_theme = _block(plymouth_text, THEME_BEGIN, THEME_END, THEME_BLOCK)
        if saved and saved.get('enabled') and managed_theme:
            _, _, theme = _theme(plymouth_text)
            owned_line = plymouth_text[:plymouth_text.index(THEME_BLOCK)].count('\n') + 1
            if theme != (owned_line, 'bromigos'):
                raise Error('The owned Plymouth theme moved outside its Daemon section; review it first')
        if action == 'on':
            if not _runtime_ready(paths) or _read(paths.at('/usr/share/plymouth/themes/bromigos/bromigos.plymouth')) is None:
                raise Error('Install bromigos-settings and Plymouth before enabling the splash')
            flags = _saved_flags(grub_text)
            if flags is None:
                raise Error('Dynamic GRUB kernel settings are not supported; review the kernel arguments first')
            if _disabled(flags):
                raise Error('GRUB explicitly disables Plymouth or its graphical screen; review these flags first: ' + ', '.join(_disabled(flags)))
            if saved and saved.get('enabled'):
                if not managed_grub or not managed_theme:
                    raise Error('Saved splash settings were changed; review the owned blocks first')
                return {'changed': False, 'enabled': True}
            if managed_grub or managed_theme:
                raise Error('Owned splash blocks exist without matching saved state')
            new_grub = (grub_text + ('' if grub_text.endswith('\n') else '\n') + GRUB_BLOCK).encode()
            new_theme, restore = _theme_on(old[paths.plymouth])
            new_state = {'schema': 1, 'enabled': True, 'grub_before': grub_text,
                         'grub_after': _text(new_grub), 'plymouth_before': None if old[paths.plymouth] is None else plymouth_text,
                         'plymouth_after': _text(new_theme), 'plymouth_restore': restore}
        else:
            if not saved or not saved.get('enabled'):
                if managed_grub or managed_theme:
                    raise Error('Owned splash blocks exist without matching saved state')
                return {'changed': False, 'enabled': False}
            if not managed_grub or not managed_theme:
                raise Error('Saved splash settings were changed; review the owned blocks first')
            new_grub = (saved['grub_before'] if grub_text == saved['grub_after'] else grub_text.replace(GRUB_BLOCK, '')).encode()
            if plymouth_text == saved['plymouth_after']:
                before = saved['plymouth_before']
                new_theme = None if before is None else before.encode()
            else:
                prefix, suffix = plymouth_text.split(THEME_BLOCK)
                restore = saved['plymouth_restore']
                if restore and suffix and not restore.endswith('\n'):
                    restore += '\n'
                new_theme = (prefix + restore + suffix).encode()
            new_state = {'schema': 1, 'enabled': False}
        _directory(paths.plymouth.parent, 0o755)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
        backup = Path(tempfile.mkdtemp(prefix=stamp, dir=paths.state_dir))
        for name, path in (('grub', paths.grub), ('plymouth.conf', paths.plymouth), ('grub.cfg', paths.generated), ('state.json', paths.state)):
            if old[path] is not None:
                _write(backup / (name + '.before'), old[path], expected=None, mode=0o600)
        _write(backup / 'manifest.json', (json.dumps({str(p): v is not None for p, v in old.items()}) + '\n').encode(), expected=None, mode=0o600)
        log = backup / 'commands.log'
        _write(log, b'', expected=None, mode=0o600)
        changed = []
        temporary = None
        def interrupted(signum, _frame):
            raise Error('Splash change interrupted by signal ' + str(signum))
        previous_term = signal.signal(signal.SIGTERM, interrupted)
        previous_int = signal.getsignal(signal.SIGINT)
        try:
            for path, value in ((paths.grub, new_grub), (paths.plymouth, new_theme)):
                changed.append((path, value))
                _write(path, value, expected=old[path])
            fd, name = tempfile.mkstemp(prefix='.bromigos-splash-', dir=paths.generated.parent)
            os.close(fd)
            temporary = Path(name)
            runner(['/usr/bin/grub-mkconfig', '-o', str(temporary)], log)
            generated = _read(temporary, 16 << 20)
            if not generated or not generated.strip():
                raise Error('grub-mkconfig produced an empty boot menu')
            runner(['/usr/bin/grub-script-check', str(temporary)], log)
            # A parallel configuration edit must never silently enter the generated menu.
            if _read(paths.grub) != new_grub or _read(paths.plymouth) != new_theme:
                raise Error('Configuration changed while generating the boot menu')
            changed.append((paths.generated, generated))
            _write(paths.generated, generated, expected=old[paths.generated])
            state_value = (json.dumps(new_state, indent=2) + '\n').encode()
            changed.append((paths.state, state_value))
            _write(paths.state, state_value, expected=old[paths.state], mode=0o600)
        except (Error, OSError, ValueError, UnicodeError, KeyboardInterrupt) as error:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            failures = []
            for path, value in reversed(changed):
                try:
                    if _read(path, 16 << 20) != old[path]:
                        _write(path, old[path], expected=value)
                except (Error, OSError):
                    failures.append(str(path))
            detail = 'Some files changed again and could not be restored: ' + ', '.join(failures) if failures else 'Previous configuration restored.'
            reason = 'Splash change interrupted' if isinstance(error, KeyboardInterrupt) else str(error)
            raise Error(f'{reason}. {detail} Backup and log: {backup}') from None
        finally:
            try:
                if temporary:
                    temporary.unlink(missing_ok=True)
            finally:
                signal.signal(signal.SIGTERM, previous_term)
                signal.signal(signal.SIGINT, previous_int)
        return {'changed': True, 'enabled': action == 'on', 'backup': str(backup)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='bromigos splash', description='Configure graphical shutdown and restart on GRUB systems')
    parser.add_argument('action', nargs='?', default='status', choices=('status', 'on', 'off'))
    parser.add_argument('--json', action='store_true', help='Print status as JSON')
    args = parser.parse_args(argv)
    if args.json and args.action != 'status':
        parser.error('--json is only available for status')
    try:
        if args.action == 'status':
            result = status()
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print('Plymouth theme: ' + json.dumps(result['theme'] or 'unknown'))
                print('bromigOS theme installed: ' + ('yes' if result['theme_installed'] else 'no'))
                print('Plymouth runtime installed: ' + ('yes' if result['plymouth_installed'] else 'no; install plymouth'))
                print('GRUB configuration supported: ' + ('yes' if result['grub_supported'] else 'no or unavailable'))
                print('Saved splash flag: ' + ('unknown' if result['configured_splash'] is None else 'on' if result['configured_splash'] else 'off'))
                print('Running kernel graphical flag: ' + ('on' if result['current_kernel_graphical'] else 'off; reboot after enabling'))
                if result['configured_disabled']:
                    print('Saved flags prevent graphical splash: ' + ', '.join(result['configured_disabled']))
                if result['current_kernel_disabled']:
                    print('Running kernel prevents graphical splash: ' + ', '.join(result['current_kernel_disabled']))
                print(result['note'])
                for issue in result['issues']:
                    print('Notice: ' + json.dumps(issue))
        else:
            result = change(args.action)
            print('Saved bromigOS splash: ' + args.action + (' (unchanged)' if not result['changed'] else ''))
            if result.get('backup'):
                print('Backup and command log: ' + result['backup'])
            print(NOTICE if args.action == 'on' else 'Removed only bromigOS-owned settings. Existing user splash settings are preserved. Reboot to use the saved kernel flags.')
        return 0
    except (Error, OSError, ValueError, KeyError, UnicodeError) as error:
        detail = str(error) if isinstance(error, Error) else 'Cannot safely read or save splash settings'
        print('Splash settings stopped: ' + detail, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
