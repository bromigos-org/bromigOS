"""Read-only block-device inventory and conservative cache previews."""
import json
import os
from pathlib import Path
import shutil

import bromigos_storage_common as C


def _json(argv):
    value = C.command(argv, capture=True, timeout=15)
    if hasattr(value, 'stdout'):
        value = value.stdout
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        raise C.Error('A storage utility returned invalid JSON') from None


def _valid_rows(rows):
    return isinstance(rows,list) and all(isinstance(row,dict) and _valid_rows(row.get('children',[])) for row in rows)


def status():
    result = {'disks': [], 'mounts': [], 'free_space': [], 'errors': [],
              'space_note': 'Btrfs subvolumes can share one filesystem. Their free space must not be added together.'}
    for key, argv, field in (
        ('disks', ['lsblk', '--json', '--bytes', '--paths', '--output',
                   'NAME,PATH,TYPE,SIZE,RO,MODEL,SERIAL,WWN,MAJ:MIN,FSTYPE,UUID,LABEL,PARTUUID,PARTLABEL,MOUNTPOINTS'], 'blockdevices'),
        ('mounts', ['findmnt', '--json', '--output', 'TARGET,SOURCE,FSTYPE,UUID,MAJ:MIN,FSROOT'], 'filesystems'),
    ):
        try:
            doc = _json(argv)
            if not isinstance(doc, dict) or not _valid_rows(doc.get(field)):
                raise C.Error('Storage inventory response has no expected list')
            result[key] = doc[field]
        except (C.Error, OSError):
            result['errors'].append(f'Could not read {key}; check that the required utility is installed and accessible')
    def mounts(rows):
        for row in rows:
            yield row
            yield from mounts(row.get('children', []))
    seen = set()
    for row in mounts(result['mounts']):
        if row.get('fstype') not in ('btrfs','ext2','ext3','ext4','xfs','vfat','exfat','f2fs','ntfs3') or not (row.get('uuid') or str(row.get('source','')).startswith('/dev/')):
            continue
        target = row.get('target')
        if not isinstance(target, str) or not target.startswith('/') or target in seen:
            continue
        seen.add(target)
        try:
            values = shutil.disk_usage(target)
        except OSError:
            result['errors'].append('Could not read free space for a mounted path')
            continue
        result['free_space'].append({'path': target, 'filesystem_uuid': row.get('uuid'),
                                     'total_bytes': values.total, 'used_bytes': values.used,
                                     'free_bytes': values.free, 'shared': row.get('fstype') == 'btrfs'})
    return result


def _snapshot_summary(home):
    """Inspect only snapshot directory metadata; never open snapshot contents."""
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
                row['numeric_directories'] = sum(1 for child in path.iterdir()
                                                 if child.name.isascii() and child.name.isdecimal()
                                                 and not child.is_symlink() and child.is_dir())
                row['status'] = 'present'
                row['detail'] = 'Numeric immediate child directories only; snapshot contents were not inspected'
        except OSError:
            row['numeric_directories'] = None
            row['detail'] = 'Directory metadata is inaccessible'
        result.append(row)
    return result


def cleanup_preview():
    """List only known cache roots, never walk home, Git trees or snapshot contents."""
    home = Path.home()
    cache = Path(os.environ.get('XDG_CACHE_HOME', str(home / '.cache'))).expanduser()
    candidates = []
    for name, path, detail in (
        ('npm', home / '.npm/_cacache', 'npm cached package content; no projects or configuration'),
        ('conda', home / '.conda/pkgs', 'Conda package cache; keep environments and configuration'),
        ('package-archives', Path('/var/cache/pacman/pkg'), 'Downloaded package archives; review retained versions before removing'),
    ):
        # A redirected path is not an approved cache root.
        if path.is_dir() and not path.is_symlink() and not any(p.is_symlink() for p in path.parents if p != home.parent):
            measured, error = None, None
            try:
                output = C.command(['du','-sx','--block-size=1','--',str(path)],timeout=15)
                measured = int(output.split()[0])
            except (C.Error,OSError,ValueError,IndexError):
                error = 'Allocated size unavailable; no cleanup was performed'
            candidates.append({'kind': name, 'path': str(path), 'action': 'review-only', 'detail': detail,
                               'allocated_bytes': measured, 'size_error': error, 'estimated_reclaim_bytes': None})
    return {'candidates': candidates, 'deleted': False, 'snapshots': _snapshot_summary(home),
            'snapshot_note': 'Snapshot directory counts cannot quantify physical reclaim or prove which files are retained without privileged extent inspection.',
            'size_note': 'Allocated usage from bounded du is not a promise of physically reclaimable space.',
            'note': 'No files were removed. Git worktrees, including Paru clone/build trees, are excluded. Snapshot retention is not a measurement of physical space reclaimed.'}
