"""Read-only local drive, cache and configured snapshot inventory."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat

import bromigos_storage_common as C

LOCAL_FILESYSTEMS = ('btrfs', 'ext2', 'ext3', 'ext4', 'xfs', 'vfat', 'exfat', 'f2fs', 'ntfs3')
FINDMNT = ['findmnt', '--json', '--output', 'TARGET,SOURCE,FSTYPE,UUID,MAJ:MIN,FSROOT']
SNAPSHOT_LIMIT = 4096
CONFIG_LIMIT = 1024 * 1024


def _json(argv):
    value = C.command(argv, capture=True, timeout=15)
    if hasattr(value, 'stdout'):
        value = value.stdout
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        raise C.Error('A storage utility returned invalid JSON') from None


def _valid_rows(rows):
    return isinstance(rows, list) and all(isinstance(row, dict) and _valid_rows(row.get('children', [])) for row in rows)


def _rows(rows):
    for row in rows:
        yield row
        yield from _rows(row.get('children', []))


def _local(row):
    return row.get('fstype') in LOCAL_FILESYSTEMS and (row.get('uuid') or str(row.get('source', '')).startswith('/dev/'))


def _source(row):
    return str(row.get('source', '')).split('[', 1)[0]


def _fskey(row):
    return row.get('uuid') or row.get('maj:min') or _source(row)


def _mount_for(path, mounts):
    """Resolve using mount metadata only, never stat an untriggered automount."""
    matches = [(len(str(row.get('target', ''))), n, row) for n, row in enumerate(mounts)
               if row.get('target') and (str(path) == row['target'] or str(path).startswith(row['target'].rstrip('/') + '/'))]
    return max(matches, default=(0, 0, {}), key=lambda item: item[:2])[2]


def _safe_local(path, mounts, *, btrfs=False):
    path = Path(path)
    row = _mount_for(path, mounts)
    if not path.is_absolute() or '..' in path.parts or not _local(row) or (btrfs and row.get('fstype') != 'btrfs'):
        return False
    # Do this only after ruling out inactive automounts, remote and virtual mounts.
    try:
        return all(not part.is_symlink() for part in reversed([path, *path.parents]))
    except OSError:
        return False


def _read_mounts():
    doc = _json(FINDMNT)
    if not isinstance(doc, dict) or not _valid_rows(doc.get('filesystems')):
        raise C.Error('Storage inventory response has no expected list')
    return list(_rows(doc['filesystems']))


def status():
    result = {'disks': [], 'mounts': [], 'free_space': [], 'errors': [],
              'space_note': 'Btrfs subvolumes can share one filesystem. Their free space must not be added together.'}
    for key, argv, field in (
        ('disks', ['lsblk', '--json', '--bytes', '--paths', '--output',
                   'NAME,PATH,TYPE,SIZE,RO,MODEL,SERIAL,WWN,MAJ:MIN,FSTYPE,UUID,LABEL,PARTUUID,PARTLABEL,MOUNTPOINTS'], 'blockdevices'),
        ('mounts', FINDMNT, 'filesystems'),
    ):
        try:
            doc = _json(argv)
            if not isinstance(doc, dict) or not _valid_rows(doc.get(field)):
                raise C.Error('Storage inventory response has no expected list')
            result[key] = doc[field]
        except (C.Error, OSError):
            result['errors'].append(f'Could not read {key}; check that the required utility is installed and accessible')
    flat_mounts = list(_rows(result['mounts']))
    seen, groups = set(), {}
    for row in flat_mounts:
        target = row.get('target')
        if not _local(row) or not isinstance(target, str) or not target.startswith('/') or target in seen:
            continue
        # A deeper overmount wins, including an inactive autofs over a local path.
        if _mount_for(target, flat_mounts) is not row:
            continue
        seen.add(target)
        key = _fskey(row)
        group = groups.setdefault(key, {'filesystem_uuid': row.get('uuid'), 'fstype': row.get('fstype'),
                                       'device_paths': [], 'physical_drives': [], 'mounts': [], 'label': None,
                                       'total_bytes': None, 'used_bytes': None, 'free_bytes': None})
        group['mounts'].append({'path': target, 'fsroot': row.get('fsroot', '/')})
        if _source(row) not in group['device_paths']:
            group['device_paths'].append(_source(row))
        if group['total_bytes'] is None:
            try:
                values = shutil.disk_usage(target)
                group.update(total_bytes=values.total, used_bytes=values.used, free_bytes=values.free)
            except OSError:
                result['errors'].append('Could not read free space for a mounted filesystem')
        result['free_space'].append({'path': target, 'filesystem_uuid': row.get('uuid'),
                                     'total_bytes': group['total_bytes'], 'used_bytes': group['used_bytes'],
                                     'free_bytes': group['free_bytes'], 'shared': row.get('fstype') == 'btrfs'})
    drives = []
    for disk in _rows(result['disks']):
        path = disk.get('path') or disk.get('name') or ''
        if disk.get('type') != 'disk' or re.match(r'^/dev/(?:zram|ram|loop)\d+$', path):
            continue
        drives.append({key: disk.get(key) for key in ('path', 'name', 'model', 'size', 'type')})
        for child in _rows([disk]):
            for key, group in groups.items():
                if (child.get('uuid') and child['uuid'] == group['filesystem_uuid']) or child.get('path') in group['device_paths']:
                    if path not in group['physical_drives']:
                        group['physical_drives'].append(path)
                    group['label'] = group['label'] or child.get('label')
    result.update(drives=drives, filesystems=list(groups.values()))
    return result


def _snapshot_summary(home):
    """Legacy directory summary, retained for callers of the original helper."""
    paths = [home / '.snapshots']
    if home.parent != Path('/') and home.parent != home:
        paths.append(home.parent / '.snapshots')
    result = []
    for path in dict.fromkeys(paths):
        row = {'path': str(path), 'status': 'unavailable', 'numeric_directories': None}
        try:
            if path.is_symlink() or not path.is_dir():
                row['detail'] = 'Not present or directory metadata is inaccessible'
            else:
                count = 0
                for n, child in enumerate(path.iterdir()):
                    if n >= SNAPSHOT_LIMIT:
                        raise OSError('Directory limit')
                    count += child.name.isascii() and child.name.isdecimal() and not child.is_symlink() and child.is_dir()
                row.update(numeric_directories=count, status='present', detail='Immediate directory metadata only')
        except OSError:
            row.update(numeric_directories=None, detail='Directory metadata is inaccessible or exceeds the inventory limit')
        result.append(row)
    return result


def _group(provider, config, source=None, directory=None, status='unavailable', detail=''):
    return {'provider': provider, 'config': config, 'source_path': source, 'path': directory,
            'status': status, 'count': None, 'numeric_directories': None, 'detail': detail, 'candidates': []}


def _snapshot_ids(mounts):
    """One metadata-only query per already mounted Btrfs filesystem."""
    result, seen = {}, set()
    for row in mounts:
        key = _fskey(row)
        if row.get('fstype') != 'btrfs' or not key or key in seen or _mount_for(row.get('target'), mounts) is not row:
            continue
        seen.add(key)
        if len(seen) > 16:
            break
        try:
            output = C.command(['btrfs', 'subvolume', 'list', '-s', '-u', '-q', row['target']], timeout=15)
            if len(output) > 4 * 1024 * 1024:
                continue
            for line in output.splitlines():
                fields, separator, path = line.partition(' path ')
                ident = re.search(r'^ID (\d+)\b', fields)
                parent = re.search(r'(?:^| )parent_uuid ([0-9a-fA-F-]+)(?: |$)', fields)
                uuid = re.search(r'(?:^| )uuid ([0-9a-fA-F-]+)(?: |$)', fields)
                if separator and ident and parent and uuid:
                    result[(key, path.removeprefix('<FS_TREE>/'))] = {
                        'id': int(ident.group(1)), 'subvolume_uuid': uuid.group(1),
                        'parent_uuid': None if parent.group(1) == '-' else parent.group(1)}
        except (C.Error, OSError):
            continue
    return result


def _candidate(provider, config, path, source, mounts, identities, *, ident=None, date=None):
    row = _mount_for(path, mounts)
    relative = str(PurePosixPath(row.get('fsroot', '/')) / Path(path).relative_to(row['target'])).lstrip('/')
    found = identities.get((_fskey(row), relative), {})
    return {'provider': provider, 'config': config, 'path': str(path), 'source_path': str(source),
            'id': ident if provider == 'snapper' else found.get('id'), 'subvolume_id': found.get('id'),
            'name': Path(path).name, 'date': date, 'filesystem_uuid': row.get('uuid'),
            'subvolume_uuid': found.get('subvolume_uuid'), 'parent_uuid': found.get('parent_uuid')}


def _snapper(mounts, identities):
    try:
        doc = _json(['snapper', '--jsonout', 'list-configs', '--columns', 'config,subvolume'])
        configs = doc.get('configs')
        if not isinstance(configs, list) or len(configs) > 64 or not all(isinstance(row, dict) for row in configs):
            raise C.Error('Invalid config list')
    except (C.Error, OSError, AttributeError):
        return [_group('snapper', None, detail='Snapper configuration list unavailable; install Snapper or check access')]
    groups = []
    for config in configs:
        name, source = config.get('config'), config.get('subvolume')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or not isinstance(source, str) or not source.startswith('/'):
            groups.append(_group('snapper', None, status='unsupported', detail='Snapper reported an unsupported configuration'))
            continue
        directory = Path(source) / '.snapshots'
        group = _group('snapper', name, source, str(directory))
        groups.append(group)
        if not _safe_local(source, mounts, btrfs=True) or not _safe_local(directory, mounts, btrfs=True):
            group['detail'] = 'Source or snapshots are not on an accessible, mounted local Btrfs filesystem'
            continue
        try:
            doc = _json(['snapper', '--jsonout', '--config', name, 'list', '--disable-used-space', '--columns', 'number,type,date'])
            rows = doc.get(name)
            if not isinstance(rows, list) or len(rows) > SNAPSHOT_LIMIT:
                raise C.Error('Invalid snapshot list')
            candidates = []
            for item in rows:
                ident = item.get('number')
                if not isinstance(ident, int) or isinstance(ident, bool) or ident < 0:
                    raise C.Error('Invalid snapshot number')
                if ident:
                    path = directory / str(ident) / 'snapshot'
                    if not _safe_local(path, mounts, btrfs=True):
                        raise C.Error('Snapshot path unavailable')
                    candidates.append(_candidate('snapper', name, path, source, mounts, identities, ident=ident, date=item.get('date')))
            group.update(status='present', count=len(candidates), numeric_directories=len(candidates), candidates=candidates,
                         detail='Configured snapshots; current state 0 is excluded')
        except (C.Error, OSError, AttributeError):
            group['detail'] = 'Snapshot list unavailable; check access to this Snapper configuration'
    return groups


def _btrbk_specs(path):
    """Parse the ordinary local volume/subvolume layout without executing config."""
    try:
        with path.open() as stream:
            text = stream.read(CONFIG_LIMIT + 1)
    except FileNotFoundError:
        return [], 'not-configured', 'No btrbk configuration found'
    except OSError:
        return [], 'unavailable', 'btrbk configuration is not readable'
    if len(text) > CONFIG_LIMIT:
        return [], 'unsupported', 'btrbk configuration exceeds the inventory limit'
    volume, scope, specs, defaults = None, None, [], {}
    try:
        for line in text.splitlines():
            words = shlex.split(line, comments=True)
            if not words:
                continue
            key = words[0]
            if key in ('include', 'include_config'):
                return [], 'unsupported', 'btrbk configuration includes are not supported by this inventory'
            if key == 'volume':
                if len(words) != 2 or not words[1].startswith('/') or '..' in Path(words[1]).parts:
                    return [], 'unsupported', 'Only local, absolute btrbk volume paths are supported'
                volume = {'volume': words[1], **defaults}
                scope = volume
            elif key == 'subvolume':
                if len(words) != 2 or volume is None or Path(words[1]).is_absolute() or any(c in words[1] for c in '*?[]') or '..' in Path(words[1]).parts:
                    return [], 'unsupported', 'btrbk wildcard or standalone subvolumes need a manual inventory'
                scope = dict(volume, subvolume=words[1])
                specs.append(scope)
            elif key in ('target', 'target_preserve', 'target_preserve_min'):
                if key == 'target':
                    scope = None  # Never inspect backup targets, local or remote.
            elif key in ('snapshot_dir', 'snapshot_name'):
                if len(words) != 2 or (key == 'snapshot_name' and (scope is None or 'subvolume' not in scope)):
                    return [], 'unsupported', 'btrbk snapshot naming requires a manual inventory'
                target = scope if scope is not None else defaults
                target[key] = words[1]
    except ValueError:
        return [], 'unsupported', 'btrbk configuration could not be parsed safely'
    for spec in specs:
        directory, name = spec.get('snapshot_dir'), spec.get('snapshot_name', spec['subvolume'])
        if not directory or Path(directory).is_absolute() or '..' in Path(directory).parts or '/' in name or name in ('', '.', '..'):
            return [], 'unsupported', 'btrbk snapshot paths or names need a manual inventory'
        spec['snapshot_name'] = name
    return specs, 'present', 'Only configured local snapshots are inspected'


def _btrbk(mounts, identities, config_path):
    if not _safe_local(config_path, mounts):
        return [_group('btrbk', str(config_path), detail='btrbk configuration is not on an accessible, mounted local filesystem')]
    specs, status, detail = _btrbk_specs(config_path)
    if status != 'present':
        return [_group('btrbk', str(config_path), status=status, detail=detail)]
    groups = []
    for spec in specs:
        source = Path(spec['volume']) / spec['subvolume']
        directory = Path(spec['volume']) / spec['snapshot_dir']
        group = _group('btrbk', str(config_path), str(source), str(directory))
        groups.append(group)
        if not _safe_local(source, mounts, btrfs=True) or not _safe_local(directory, mounts, btrfs=True):
            group['detail'] = 'Source or snapshot directory is not on an accessible, mounted local Btrfs filesystem'
            continue
        pattern = re.compile(re.escape(spec['snapshot_name']) + r'\.\d{8}T\d{4}(?:\d{2})?(?:[+-]\d{4})?$')
        try:
            candidates = []
            for n, child in enumerate(directory.iterdir()):
                if n >= SNAPSHOT_LIMIT:
                    raise OSError('Directory limit')
                if not pattern.fullmatch(child.name):
                    continue
                if not _safe_local(child, mounts, btrfs=True) or not stat.S_ISDIR(child.lstat().st_mode):
                    continue
                candidates.append(_candidate('btrbk', str(config_path), child, source, mounts, identities,
                                             date=child.name.removeprefix(spec['snapshot_name'] + '.')))
            candidates.sort(key=lambda item: item['name'])
            group.update(status='present', count=len(candidates), candidates=candidates,
                         detail='Configured local snapshot names; backup targets were not visited')
        except OSError:
            group['detail'] = 'Snapshot directory metadata is inaccessible or exceeds the inventory limit'
    return groups


def snapshot_inventory(*, mounts=None, btrbk_config=Path('/etc/btrbk/btrbk.conf')):
    """Discover configured snapshot metadata without mounting or inspecting contents."""
    note = 'Snapshots share data with active files. Counts do not measure reclaimable space; unavailable identities require root inspection before cleanup.'
    try:
        mounts = _read_mounts() if mounts is None else list(_rows(mounts))
    except (C.Error, OSError):
        return {'snapshots': [_group('snapper', None, detail='Mount inventory unavailable'),
                              _group('btrbk', str(btrbk_config), detail='Mount inventory unavailable')], 'snapshot_note': note}
    identities = _snapshot_ids(mounts)
    return {'snapshots': _snapper(mounts, identities) + _btrbk(mounts, identities, Path(btrbk_config)), 'snapshot_note': note}


def cleanup_preview():
    """List known cache roots and configured snapshots; never walk home or Git trees."""
    home = Path.home()
    try:
        mounts = _read_mounts()
    except (C.Error, OSError):
        mounts = []
    errors = [] if mounts else ['Mount inventory unavailable; cache locations were not inspected']
    candidates = []
    for name, path, detail in (
        ('npm', home / '.npm/_cacache', 'Downloaded npm package content'),
        ('conda', home / '.conda/pkgs', 'Conda package cache; environments remain separate'),
        ('package-archives', Path('/var/cache/pacman/pkg'), 'Downloaded package archives; review retained versions'),
    ):
        if _safe_local(path, mounts) and path.is_dir():
            measured, error = None, None
            try:
                output = C.command(['du', '-sx', '--block-size=1', '--', str(path)], timeout=15)
                measured = int(output.split()[0])
            except (C.Error, OSError, ValueError, IndexError):
                error = 'Allocated size unavailable; no cleanup was performed'
            candidates.append({'kind': name, 'path': str(path), 'action': 'review-only', 'detail': detail,
                               'allocated_bytes': measured, 'size_error': error, 'estimated_reclaim_bytes': None})
    return {'candidates': candidates, 'deleted': False, 'errors': errors, **snapshot_inventory(mounts=mounts),
            'size_note': 'Allocated cache size is not a promise of physically reclaimable space.',
            'note': 'Preview only. No files were removed. Git worktrees and Paru build trees are excluded.'}
