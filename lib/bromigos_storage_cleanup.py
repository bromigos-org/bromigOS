"""Reviewed retirement of migrated originals and explicitly selected local snapshots."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

import bromigos_storage_common as C
import bromigos_storage_migration as M
import bromigos_storage_cache as CACHE


def _inventory():
    from bromigos_storage_inventory import snapshot_inventory
    return snapshot_inventory()


def _candidates(inventory):
    return [item for group in inventory.get('snapshots', []) for item in group.get('candidates', [])]


def _mount_rows():
    return json.loads(C.command(['findmnt', '--json', '--list', '-o', 'TARGET,UUID,FSTYPE,FSROOT']))['filesystems']


def _mount_check(path, filesystem):
    """Reject mounted aliases/children; include every exposed alias in busy scans."""
    uuid, address = M._address(path, filesystem)
    address = Path(address)
    aliases = {str(path)}
    for row in _mount_rows():
        if row.get('uuid') != uuid or not row.get('fsroot') or not row.get('target'):
            continue
        root = Path(row['fsroot'])
        if root == address or root.is_relative_to(address):
            raise C.Error('A selected tree is mounted elsewhere or contains a mounted subtree')
        if address.is_relative_to(root):
            aliases.add(str(Path(row['target']) / address.relative_to(root)))
    if any(mount == path or mount.is_relative_to(path) for mount in M._filesystems()):
        raise C.Error('A selected tree is mounted or contains a mount')
    return aliases


def _aliases(path, filesystem):
    uuid, address = M._address(path, filesystem)
    address = Path(address)
    aliases = {str(path)}
    for row in _mount_rows():
        if row.get('uuid') == uuid and row.get('fsroot') and row.get('target') and address.is_relative_to(Path(row['fsroot'])):
            aliases.add(str(Path(row['target']) / address.relative_to(row['fsroot'])))
    return aliases


def _persistent_binding(item):
    rows = [fields for _, fields in M._fstab_rows(M.FSTAB.read_text()) if fields[1] == item['keep_path']]
    if len(rows) != 1 or len(rows[0]) < 4 or rows[0][0] != item['destination'] or 'bind' not in rows[0][3].split(','):
        raise C.Error('The persistent application mount changed; repair fstab before retiring originals')


def _snapshot(path, candidate, check_busy=True):
    path = M._path(str(path))
    filesystem = M._filesystem(path)
    if filesystem['fstype'] != 'btrfs':
        raise C.Error('Snapshot cleanup supports local Btrfs snapshots only')
    # A manager's discovered path is required; a random subvolume is not a snapshot choice.
    if candidate.get('provider') not in ('snapper', 'btrbk') or candidate.get('path') != str(path):
        raise C.Error('Choose an exact snapshot path listed by cleanup preview')
    source = Path(candidate['source_path'])
    if not source.is_absolute() or source.resolve() != source or not source.is_dir():
        raise C.Error('The snapshot source cannot be identified')
    if source == path or source.is_relative_to(path):
        raise C.Error('Cannot retire a snapshot containing its source')
    source_fs = M._filesystem(source)
    if source_fs['uuid'] != filesystem['uuid']:
        raise C.Error('Snapshot and source filesystem identities differ')
    def fields(location):
        output = C.command(['btrfs', 'subvolume', 'show', str(location)])
        values = {}
        for key in ('UUID', 'Parent UUID', 'Subvolume ID'):
            match = re.search(r'^\s*' + re.escape(key) + r':\s*(\S+)', output, re.M)
            if not match:
                raise C.Error('Cannot read the snapshot subvolume identity')
            values[key] = match[1]
        return values
    info, parent = fields(path), fields(source)
    if info['UUID'] == parent['UUID'] or info['Parent UUID'] != parent['UUID']:
        raise C.Error('Snapshot parent differs from the configured source')
    if C.command(['btrfs', 'property', 'get', '-ts', str(path), 'ro']).strip() != 'ro=true':
        raise C.Error('Only read-only snapshots can be selected for retirement')
    if not info['Subvolume ID'].isdigit():
        raise C.Error('Invalid Btrfs subvolume ID')
    aliases = _mount_check(path, filesystem)
    if check_busy and M._busy_paths([{'source': alias, 'destination': alias} for alias in aliases]):
        raise C.Error('A selected snapshot is in use; wait for its readers or backup job to finish')
    if C.command(['btrfs', 'subvolume', 'list', '-o', str(path)]).strip():
        raise C.Error('A selected snapshot contains nested subvolumes; review them separately')
    if candidate['provider'] == 'snapper':
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', str(candidate.get('config', ''))) or not str(candidate.get('id', '')).isdigit() or int(candidate['id']) == 0:
            raise C.Error('A Snapper selection needs a config and a nonzero snapshot number')
    return {'kind': 'snapshot', 'provider': candidate['provider'], 'config': candidate.get('config'),
            'snapshot_id': candidate.get('id'), 'path': str(path), 'source_path': str(source),
            'filesystem': filesystem, 'identity': M._identity(path), 'subvolume_uuid': info['UUID'],
            'parent_uuid': info['Parent UUID'], 'subvolume_id': int(info['Subvolume ID'])}


def _retained(record, journal):
    if journal is None or journal.get('state') != 'switched' or not journal.get('originals_retained'):
        raise C.Error('Cleanup needs a completed switch with retained originals')
    names = {entry['original']: entry['retained'] for entry in journal.get('retained', [])}
    items = []
    for move in record['moves']:
        binding = move.get('keep_path')
        if not binding:
            # A copy-only source may still be in use. It is never inferred obsolete.
            continue
        source = Path(move['source'])
        if binding['existing_bind']:
            old = source
        else:
            expected = source.with_name(source.name + '.before-storage-' + record['id'])
            if names.get(str(source)) != str(expected):
                raise C.Error('Retained source journal does not match the migration')
            old = expected
        target = M._path(move['destination'])
        if M._identity(old) != move['source_identity']:
            raise C.Error('A retained original directory was replaced')
        if M._identity(target) != journal.get('destinations', {}).get(str(target)):
            raise C.Error('The active destination directory changed')
        if M._filesystem(target) != move['destination_filesystem']:
            raise C.Error('The destination filesystem changed')
        if M._identity(Path(binding['path'])) != M._identity(target):
            raise C.Error('The application path no longer uses the migration destination')
        old_fs = M._filesystem(old)
        if M._address(old, old_fs)[0] != move['source_filesystem']['uuid']:
            raise C.Error('The retained source filesystem changed')
        items.append({'kind': 'original', 'path': str(old), 'destination': str(target),
                      'keep_path': binding['path'], 'identity': M._identity(old),
                      'filesystem': old_fs, 'destination_identity': M._identity(target),
                      'destination_filesystem': M._filesystem(target)})
    if not items:
        raise C.Error('No switched originals are eligible for cleanup')
    return items


def _original(item, compare=False, check_busy=True):
    old, target = M._path(item['path']), M._path(item['destination'])
    if M._identity(old) != item['identity'] or M._filesystem(old) != item['filesystem']:
        raise C.Error('A retained directory or its filesystem changed')
    if M._identity(target) != item['destination_identity'] or M._filesystem(target) != item['destination_filesystem']:
        raise C.Error('The active destination or its filesystem changed')
    if M._identity(Path(item['keep_path'])) != item['destination_identity']:
        raise C.Error('An application path no longer points to the active data')
    old_address = M._address(old, item['filesystem'])
    target_address = M._address(target, item['destination_filesystem'])
    if M._overlap(old, target) or (old_address[0] == target_address[0] and M._overlap(Path(old_address[1]), Path(target_address[1]))):
        raise C.Error('Retained and active data overlap')
    aliases = _mount_check(old, item['filesystem'])
    aliases.update(_aliases(target, item['destination_filesystem']))
    aliases.add(item['keep_path'])
    _persistent_binding(item)
    if item['filesystem']['fstype'] == 'btrfs':
        if old.stat().st_ino == 256 or C.command(['btrfs', 'subvolume', 'list', '-o', str(old)]).strip():
            raise C.Error('Retained originals containing Btrfs subvolumes need separate review')
    busy = M._busy_paths([{'source': path, 'destination': path} for path in aliases]) if check_busy else []
    if busy:
        raise C.Error('Migration paths are in use; stop writers before cleanup. Process IDs: ' + ', '.join(map(str, busy)))
    if compare:
        output = C.command(['rsync', '-aHAXS', '--numeric-ids', '--checksum', '--dry-run', '--delete',
                            '--itemize-changes', '--out-format=%i %n', '--', str(old) + '/', str(target) + '/'], timeout=None)
        # Show paths as JSON strings, so filenames cannot inject terminal controls.
        if output.strip():
            details = json.dumps(output.splitlines()[:20], ensure_ascii=True)
            raise C.Error('Retained and active files differ; nothing from this copy was removed. Differences: ' + details)
        if M._busy_paths([{'source': path, 'destination': path} for path in aliases]):
            raise C.Error('A writer opened a migration path during verification; keep writers stopped')


def plan(migration=None, snapshots=(), caches=(), keep_versions=3):
    if any(name in CACHE.USER_CACHES for name in caches) and (migration or snapshots or any(name not in CACHE.USER_CACHES for name in caches)):
        raise C.Error('Use separate plans for user caches and system cleanup')
    if migration or snapshots or not caches:
        C.require_root()
    if not migration and not snapshots and not caches:
        raise C.Error('Select caches, a completed migration and/or exact snapshot paths')
    if len(snapshots) != len(set(snapshots)):
        raise C.Error('A snapshot path was selected more than once')
    with C.lock({}):
        items = CACHE.plan_items(caches, keep_versions)
        source = None
        if migration:
            record = M._load(migration)
            items += _retained(record, C.read_journal(record))
            source = {'path': record['path'], 'digest': record['digest']}
        inventory = _inventory()
        for selected in snapshots:
            matches = [entry for entry in _candidates(inventory) if entry.get('path') == selected]
            if len(matches) != 1:
                raise C.Error('Snapshot is not uniquely discoverable; review cleanup preview as root')
            items.append(_snapshot(selected, matches[0], check_busy=False))
        for item in items:
            path = Path(item['path'])
            if M._overlap(path, C.state_dir().resolve()):
                raise C.Error('Cleanup cannot contain its plans or logs')
            if item['kind'] == 'original':
                _original(item, check_busy=False)
        for index, item in enumerate(items):
            if any(M._overlap(Path(item['path']), Path(other['path'])) for other in items[:index]):
                raise C.Error('Cleanup selections overlap')
        return C.store('plans', {'kind': 'cleanup', 'state': 'planned', 'items': items,
                                'migration': source, 'snapshot_inventory': inventory,
                                'note': 'Only selected cleanup scopes will run. Snapshot deletion removes rollback history; cache commands keep the data described in each scope. Shared bytes are not a reclaim estimate.'})


def _validate(record):
    if record.get('kind') != 'cleanup' or not record.get('items'):
        raise C.Error('Use a saved cleanup plan')
    if record.get('migration'):
        source = C.read(record['migration']['path'])
        if source['digest'] != record['migration']['digest']:
            raise C.Error('The migration plan changed')
        current = _retained(source, C.read_journal(source))
        if current != [item for item in record['items'] if item['kind'] == 'original']:
            raise C.Error('The retained migration paths changed')
    inventory = _inventory()
    for item in record['items']:
        if M._overlap(Path(item['path']), Path(record['path'])):
            raise C.Error('Cleanup cannot contain its own records')
        if item['kind'] == 'original':
            _original(item)
        elif item['kind'] == 'snapshot':
            matches = [c for c in _candidates(inventory) if c.get('path') == item['path']]
            if len(matches) != 1 or _snapshot(item['path'], matches[0]) != item:
                raise C.Error('Snapshot identity or manager configuration changed')
        elif item['kind'] == 'cache':
            CACHE.validate(item)
        else:
            raise C.Error('Unsupported cleanup item')


def _space(items):
    result = []
    seen = set()
    for item in items:
        filesystem = item['filesystem']
        if filesystem['uuid'] not in seen:
            seen.add(filesystem['uuid'])
            usage = shutil.disk_usage(filesystem['target'])
            result.append({'filesystem_uuid': filesystem['uuid'], 'path': filesystem['target'],
                           'total_bytes': usage.total, 'used_bytes': usage.used, 'free_bytes': usage.free})
    return result


def apply(ref, yes=False):
    record = C.read(ref)
    if record.get('kind') != 'cleanup' or not record.get('items'):
        raise C.Error('Use a saved cleanup plan')
    CACHE.require_access(record['items'])
    with C.lock(record):
        previous = C.read_journal(record)
        if previous and (previous.get('state') not in ('preflight-failed', 'verification-failed') or previous.get('completed')):
            raise C.Error('Cleanup has an execution journal. Inspect completed paths and errors; partial deletion is never replayed automatically')
        journal = {'kind': 'cleanup', 'state': 'preflight', 'completed': []}
        fd, filename = tempfile.mkstemp(prefix=Path(record['path']).stem + '.attempt-', suffix='.log', dir=Path(record['path']).parent)
        log_path = Path(filename)
        parent = log_path.parent.stat()
        if os.geteuid() == 0:
            os.fchown(fd, parent.st_uid, parent.st_gid)
        with os.fdopen(fd, 'w') as log:
            def event(message):
                log.write(C.now() + ' ' + message + '\n'); log.flush(); os.fsync(log.fileno())
                print(message, flush=True)
            journal['log'] = str(log_path)
            C.update_journal(record, journal)
            event('Cleanup log: ' + str(log_path))
            try:
                _validate(record)
                if not yes:
                    if not sys.stdin.isatty():
                        raise C.Error('Review the plan in a terminal or pass --yes for that exact saved plan')
                    if input('Run the selected cleanup actions? Type CLEANUP ' + record['id'] + ': ').strip() != 'CLEANUP ' + record['id']:
                        raise C.Error('Cleanup cancelled')
                _validate(record)
                journal.update(state='verifying', before=_space(record['items']))
                C.update_journal(record, journal)
                # Check ALL retained originals before the first deletion.
                for item in record['items']:
                    if item['kind'] == 'original':
                        event('Verifying ' + json.dumps(item['path']))
                        _original(item, compare=True)
                _validate(record)
                journal['state'] = 'deleting'; C.update_journal(record, journal)
                btrfs_roots = set()
                for item in record['items']:
                    journal['active_path'] = item['path']; C.update_journal(record, journal)
                    event(('Cleaning ' if item['kind'] == 'cache' else 'Removing ') + json.dumps(item['path']))
                    if item['kind'] == 'original':
                        _original(item, compare=True)
                        if not shutil.rmtree.avoids_symlink_attacks:
                            raise C.Error('This Python build cannot safely remove retained directories')
                        shutil.rmtree(item['path'])
                    elif item['kind'] == 'cache':
                        journal.setdefault('cache_results', []).append(CACHE.clean(item))
                    else:
                        matches = [c for c in _candidates(_inventory()) if c.get('path') == item['path']]
                        if len(matches) != 1 or _snapshot(item['path'], matches[0]) != item:
                            raise C.Error('Snapshot changed immediately before deletion')
                        if item['provider'] == 'snapper':
                            C.command(['snapper', '-c', item['config'], 'delete', str(item['snapshot_id'])], timeout=None)
                        else:
                            C.command(['btrfs', 'subvolume', 'delete', item['path']], timeout=None)
                    if item['kind'] != 'cache' and item['filesystem']['fstype'] == 'btrfs':
                        btrfs_roots.add(item['filesystem']['target'])
                    journal['completed'].append(item['path']); C.update_journal(record, journal)
                for root in sorted(btrfs_roots):
                    event('Waiting for Btrfs deletion on ' + json.dumps(root))
                    C.command(['btrfs', 'subvolume', 'sync', root], timeout=None)
                    C.command(['btrfs', 'filesystem', 'sync', root], timeout=None)
                journal.pop('active_path', None)
                journal['after'] = _space(record['items'])
                journal['remaining_snapshots'] = _inventory()
                # New snapshots are reported, never swept into an approved deletion.
                before = {c['path'] for c in _candidates(record['snapshot_inventory'])}
                journal['new_snapshot_paths'] = [c['path'] for c in _candidates(journal['remaining_snapshots']) if c['path'] not in before]
                if record.get('migration'):
                    source = C.read(record['migration']['path'])
                    source_journal = C.read_journal(source)
                    source_journal.update(originals_retained=any(not move.get('keep_path') for move in source['moves']),
                                          retired_paths=[item['path'] for item in record['items'] if item['kind'] == 'original'],
                                          cleanup_plan=record['path'])
                    C.update_journal(source, source_journal)
                journal['state'] = 'complete'
                event('Cleanup complete. Other snapshots may still retain data; review the after-cleanup inventory.')
                return C.update_journal(record, journal)
            except BaseException as error:
                journal['state'] = {'preflight': 'preflight-failed', 'verifying': 'verification-failed'}.get(journal['state'], 'failed')
                journal['error'] = str(error) if isinstance(error, C.Error) else type(error).__name__
                C.update_journal(record, journal)
                event('Cleanup stopped: ' + journal['error'])
                raise
