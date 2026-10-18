"""Compact human output for the storage CLI; JSON remains the data interface."""
import os
import math
from pathlib import Path
import shutil
import sys
import textwrap


def _text(value):
    # Disk labels and filenames must not write terminal control sequences.
    return ''.join(char if char.isprintable() else '?' for char in str(value))


def _size(value):
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        return 'unknown'
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'):
        if abs(value) < 1024 or unit == 'PiB':
            return f'{value:.1f} {unit}'
        value /= 1024


def _path(value):
    value = _text(value)
    home = str(Path.home())
    return '~' + value[len(home):] if value == home or value.startswith(home + '/') else value


def _heading(value):
    if getattr(sys.stdout, 'isatty', lambda: False)() and not os.environ.get('NO_COLOR') and os.environ.get('TERM') != 'dumb':
        return '\033[1;36m' + value + '\033[0m'
    return value


def _usage_bar(percentage, width=16):
    # Linux virtual consoles use small bitmap fonts, not the desktop's Nerd Font.
    # Pipes and basic terminals get a stable plain-text representation.
    graphical = getattr(sys.stdout, 'isatty', lambda: False)() and os.environ.get('TERM') not in ('dumb', 'linux')
    try:
        '█▏▎▍▌▋▊▉░'.encode(getattr(sys.stdout, 'encoding', None) or 'utf-8')
    except (UnicodeEncodeError, LookupError):
        graphical = False
    if not graphical:
        filled = round(percentage / 100 * width)
        return '[' + '=' * filled + '-' * (width - filled) + ']'
    eighths = round(percentage / 100 * width * 8)
    whole, fraction = divmod(eighths, 8)
    return '█' * whole + ('▏▎▍▌▋▊▉'[fraction - 1] if fraction else '') + '░' * (width - whole - bool(fraction))


def _line(value, *, indent='  '):
    width = max(36, shutil.get_terminal_size((88, 24)).columns)
    print(textwrap.fill(value, width=width, initial_indent=indent, subsequent_indent=indent,
                        break_long_words=False, break_on_hyphens=False))


def _filesystem(item, *, shared=False):
    mounts = item.get('mounts', [])
    title = item.get('label') or (mounts[0]['path'] if mounts else 'Mounted filesystem')
    _line(f"{_path(title)} · {_text(item.get('fstype') or 'unknown filesystem')}" + (' · shared across drives' if shared else ''))
    used, free = item.get('used_bytes'), item.get('free_bytes')
    if isinstance(used, (int, float)) and isinstance(free, (int, float)) and used + free > 0:
        # Like df, available space excludes filesystem reservations. A filesystem's
        # advertised total may include reserved blocks, so don't subtract free from it.
        percentage = min(100, max(0, math.ceil(100 * used / (used + free))))
        _line(f"{_usage_bar(percentage)} {percentage}% used · {_size(used)} used · {_size(free)} available", indent='    ')
    else:
        _line('Space unavailable', indent='    ')
    paths = list(dict.fromkeys(_path(mount['path']) for mount in mounts))
    if len(paths) > 1 or (paths and paths[0] != _path(title)):
        _line('Paths: ' + ', '.join(paths), indent='    ')


def show_status(result):
    drives, filesystems = result.get('drives', []), result.get('filesystems', [])
    print(_heading('Storage') + f" · {len(drives)} {'drive' if len(drives) == 1 else 'drives'} · {len(filesystems)} mounted {'filesystem' if len(filesystems) == 1 else 'filesystems'}")
    shown = set()
    for drive in drives:
        path = drive.get('path') or drive.get('name')
        print()
        print(_heading(_text((drive.get('model') or 'Drive').strip())) + f" · {_text(path)} · {_size(drive.get('size'))}")
        matched = False
        for index, filesystem in enumerate(filesystems):
            if path not in filesystem.get('physical_drives', []):
                continue
            matched = True
            if index in shown:
                _line('Shares the filesystem shown above; capacity is counted once.')
                continue
            _filesystem(filesystem, shared=len(filesystem.get('physical_drives', [])) > 1)
            shown.add(index)
        if not matched:
            _line('No mounted local filesystem')
    unassigned = [item for index, item in enumerate(filesystems) if index not in shown]
    if unassigned:
        print('\n' + _heading('Other mounted filesystems'))
        for item in unassigned:
            _filesystem(item)
    if not drives and not filesystems and not result.get('errors'):
        _line('No local drives found.')
    print()
    _line('Space is shown once per filesystem. Its subvolumes and bind mounts share that space.', indent='')
    for error in result.get('errors', []):
        _line('Unavailable: ' + _text(error), indent='')
    print('\n' + _heading('Operations'))
    for item in result.get('operations', []):
        _line(f"{_text(item.get('id') or item.get('path'))} · {_text(item.get('kind', 'storage'))} · {_text(item.get('phase', 'unknown'))}")
    if not result.get('operations'):
        _line('No saved CLI operations. Work done by other scripts is not imported.')


def show_cleanup(result):
    print(_heading('Cleanup preview') + ' · nothing removed')
    candidates = result.get('candidates', [])
    print('\n' + _heading('Caches'))
    for item in candidates:
        _line(f"{_text(item['kind']):<18} {_size(item.get('allocated_bytes'))} allocated")
        _line(_path(item['path']), indent='    ')
        _line(_text(item.get('size_error') or item.get('detail', '')), indent='    ')
    if not candidates and not result.get('errors'):
        _line('No supported cache locations found.')
    for error in result.get('errors', []):
        _line('Unavailable: ' + _text(error))
    if result.get('size_note'):
        _line(_text(result['size_note']), indent='')
    print('\n' + _heading('Local snapshots'))
    for group in result.get('snapshots', []):
        provider = _text(group.get('provider', 'snapshots'))
        source = _path(group.get('source_path') or group.get('path') or group.get('config') or '')
        count = group.get('count', group.get('numeric_directories'))
        status = group.get('status', 'unavailable')
        label = f'{count} snapshots' if status == 'present' and count is not None else _text(status)
        _line(f'{provider} · {source} · {label}')
        _line(_text(group.get('detail', '')), indent='    ')
        snapshots = group.get('candidates', [])
        for item in snapshots[:3]:
            _line(_path(item['path']), indent='    ')
        if len(snapshots) > 3:
            _line(f'{len(snapshots) - 3} more; cleanup --json lists every path.', indent='    ')
    if result.get('snapshot_note'):
        _line(_text(result['snapshot_note']), indent='')
    print()
    _line('Plan a cleanup: bromigos storage cleanup plan --help', indent='')
    _line('Select caches with --cache npm, --cache conda or --cache package-archives.', indent='')
    _line('Select snapshots by repeating --snapshot /absolute/snapshot/path, then run cleanup apply with the saved plan.', indent='')


def show_cleanup_result(journal):
    state = _text(journal.get('state', 'unknown'))
    completed = len(journal.get('completed', []))
    print(_heading('Cleanup ' + state) + f" · {completed} {'item' if completed == 1 else 'items'} processed")
    if journal.get('error'):
        _line('Stopped: ' + _text(journal['error']), indent='')
    if journal.get('active_path'):
        _line('Inspect: ' + _path(journal['active_path']), indent='')
    if journal.get('log'):
        _line('Log: ' + _path(journal['log']), indent='')
    if journal.get('cache_results'):
        print('\n' + _heading('Cache allocation'))
        for item in journal['cache_results']:
            _line(f"{_text(item['cache'])} · {_size(item.get('allocated_before'))} before · {_size(item.get('allocated_after'))} remaining")
        _line('Retained cache content may remain. Allocation changes are separate from filesystem free space.', indent='')
    before = {row.get('filesystem_uuid'): row for row in journal.get('before', [])}
    after = journal.get('after', [])
    if after:
        print('\n' + _heading('Available space'))
        for row in after:
            old = before.get(row.get('filesystem_uuid'), {}).get('free_bytes')
            free = row.get('free_bytes')
            delta = ''
            if isinstance(old, (int, float)) and isinstance(free, (int, float)):
                change = free - old
                delta = f" · {'+' if change >= 0 else '-'}{_size(abs(change))} since cleanup"
            _line(f"{_path(row.get('path', 'Filesystem'))} · {_size(free)} available{delta}")
    remaining = journal.get('remaining_snapshots', {}).get('snapshots', [])
    if remaining:
        print('\n' + _heading('Remaining local snapshots'))
        for group in remaining:
            label = f"{group['count']} snapshots" if group.get('status') == 'present' and group.get('count') is not None else _text(group.get('status', 'unavailable'))
            _line(f"{_text(group.get('provider', 'snapshots'))} · {_path(group.get('source_path') or group.get('path') or '')} · {label}")
    if journal.get('new_snapshot_paths'):
        print('\n' + _heading('Snapshots created since planning'))
        for path in journal['new_snapshot_paths']:
            _line(_path(path))
        _line('These were outside the saved plan and may retain old data. Review them in a separate cleanup plan.', indent='')
