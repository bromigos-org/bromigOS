"""Copy, verify and explicitly switch reviewed directory migrations. Originals remain."""
import errno
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

import bromigos_storage_common as C

FSTAB = Path('/etc/fstab')
PROC = Path('/proc')
FINAL_STATES = {'switching', 'switch-failed', 'switched'}


def _path(value):
    if not isinstance(value, str) or not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise C.Error('Use a nonempty absolute directory path without control characters')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise C.Error('Migration paths must be absolute')
    path = Path(os.path.abspath(path))
    protected = [Path(value) for value in ('/etc', '/usr', '/boot', '/dev', '/proc', '/sys', '/run', '/bin', '/lib', '/lib64', '/sbin')]
    if path in [Path(value) for value in ('/', '/var', '/var/lib', '/home', '/root')] or any(path == root or path.is_relative_to(root) for root in protected):
        raise C.Error('System directories are not migration targets; select an application data directory')
    if path.resolve() != path:
        raise C.Error('Migration paths must not be filesystem roots or use symlink aliases')
    return path


def _identity(path):
    try:
        info = path.stat()
    except OSError:
        raise C.Error('A planned directory is missing or cannot be inspected') from None
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
        raise C.Error('Migration sources and existing destinations must be real directories')
    return {'device': info.st_dev, 'inode': info.st_ino}


def _filesystems():
    result = json.loads(C.command(['findmnt', '--json', '--list', '-o', 'TARGET']))
    if not isinstance(result.get('filesystems'), list):
        raise C.Error('Cannot inspect mounted filesystems')
    return [Path(entry['target']) for entry in result['filesystems']]


def _filesystem(path):
    ancestor = path
    while not ancestor.exists():
        if ancestor == ancestor.parent:
            raise C.Error('Destination has no existing filesystem parent')
        ancestor = ancestor.parent
    result = json.loads(C.command(['findmnt', '--json', '--target', str(ancestor), '-o', 'TARGET,UUID,FSTYPE,FSROOT']))
    entries = result.get('filesystems', [])
    if len(entries) != 1:
        raise C.Error('Cannot identify the migration filesystem')
    entry = entries[0]
    if not entry.get('uuid') or not entry.get('fsroot') or not entry.get('target'):
        raise C.Error('Migration requires an identifiable local filesystem UUID and filesystem root')
    if entry.get('fstype') not in ('btrfs', 'ext4', 'xfs'):
        raise C.Error('Migration currently supports mounted Btrfs, ext4 and XFS filesystems')
    return {key: entry[key] for key in ('target', 'uuid', 'fstype', 'fsroot')}


def _address(path, filesystem):
    try:
        relative = path.relative_to(filesystem['target'])
    except ValueError:
        raise C.Error('Filesystem mount location does not contain the planned path') from None
    return filesystem['uuid'], str(Path(filesystem['fsroot']) / relative)


def _overlap(first, second):
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def _unescape(value):
    return re.sub(r'\\(040|011|012|134)', lambda match: chr(int(match[1], 8)), value)


def _escape(path):
    return str(path).replace('\\', '\\134').replace(' ', '\\040').replace('\t', '\\011')


def _fstab_rows(text):
    for index, line in enumerate(text.splitlines(keepends=True)):
        if line.lstrip().startswith('#'):
            continue
        fields = line.split()
        if len(fields) >= 2:
            yield index, [_unescape(field) for field in fields]


def _keep_binding(source, keep_path, source_id, mounts):
    if keep_path is None:
        return None
    if keep_path == source:
        if keep_path in mounts:
            raise C.Error('A source that is itself a mount needs a separate original bind path, not in-place renaming')
        return {'path': str(keep_path), 'existing_bind': False}
    if not keep_path.is_dir() or keep_path not in mounts or _identity(keep_path) != source_id:
        raise C.Error('A separate keep_path must already be a bind mount of the exact source directory')
    matches = [fields for _, fields in _fstab_rows(FSTAB.read_text()) if fields[1] == str(keep_path)]
    if len(matches) != 1 or matches[0][0] != str(source) or len(matches[0]) < 4 or 'bind' not in matches[0][3].split(','):
        raise C.Error('The existing keep_path needs one matching source bind entry in fstab')
    return {'path': str(keep_path), 'existing_bind': True, 'filesystem': _filesystem(keep_path)}


def plan(moves):
    if not isinstance(moves, list) or not moves:
        raise C.Error('Provide at least one migration move')
    mounts = _filesystems()
    prepared, addresses, paths = [], [], []
    for item in moves:
        if not isinstance(item, dict) or set(item) - {'source', 'destination', 'keep_path'}:
            raise C.Error('Each move contains source, destination and optional keep_path only')
        source, destination = _path(item.get('source')), _path(item.get('destination'))
        source_id = _identity(source)
        if any(mount != path and mount.is_relative_to(path) for mount in mounts for path in (source, destination)):
            raise C.Error('A source or destination contains nested mounts; split it into separately reviewed moves')
        if destination.exists():
            destination_id = _identity(destination)
            if any(destination.iterdir()):
                raise C.Error('A new migration destination must be empty; resume a prior plan for previously staged data')
        else:
            destination_id = None
        source_fs, destination_fs = _filesystem(source), _filesystem(destination)
        keep = item.get('keep_path')
        if keep is True:
            keep = str(source)
        elif keep is False:
            keep = None
        keep_path = _path(keep) if keep is not None else None
        binding = _keep_binding(source, keep_path, source_id, mounts)
        if binding and ',' in str(destination):
            raise C.Error('Preserved-path bind destinations cannot contain commas')
        for path, filesystem in ((source, source_fs), (destination, destination_fs)):
            if _overlap(path, C.state_dir().resolve()):
                raise C.Error('Migration paths cannot overlap the storage operation records')
            address = _address(path, filesystem)
            if any(_overlap(path, prior) for prior in paths) or any(address[0] == prior[0] and _overlap(Path(address[1]), Path(prior[1])) for prior in addresses):
                raise C.Error('Migration sources and destinations overlap or alias one another')
            paths.append(path); addresses.append(address)
        prepared.append({'source': str(source), 'destination': str(destination), 'source_identity': source_id, 'source_filesystem': source_fs,
                         'destination_filesystem': destination_fs, 'destination_identity': destination_id, 'keep_path': binding})
    for item in prepared:
        if item['keep_path']:
            keep = Path(item['keep_path']['path'])
            for other in prepared:
                if other is not item and any(_overlap(keep, Path(other[key])) for key in ('source', 'destination')):
                    raise C.Error('A preserved path overlaps another migration move')
    return C.store('plans', {'kind': 'migration', 'state': 'planned', 'moves': prepared, 'originals_retained': True})


def _load(ref):
    record = C.read(ref, kind='plans')
    if record.get('kind') != 'migration':
        raise C.Error('Use a saved migration plan')
    return record


def _validate(record, journal=None):
    mounts = _filesystems()
    for move in record['moves']:
        source, destination = _path(move['source']), _path(move['destination'])
        if any(_overlap(path, Path(record['path'])) for path in (source, destination)):
            raise C.Error('A migration path contains its own plan or journal')
        if _identity(source) != move['source_identity'] or _filesystem(source) != move['source_filesystem']:
            raise C.Error('A migration source or its filesystem changed; create a new reviewed plan')
        if _filesystem(destination) != move['destination_filesystem']:
            raise C.Error('The destination UUID, mount location or filesystem root changed')
        if any(mount != path and mount.is_relative_to(path) for mount in mounts for path in (source, destination)):
            raise C.Error('A source or destination now contains a nested mount')
        if destination.exists():
            current = _identity(destination)
            expected = move.get('destination_identity')
            if expected and current != expected:
                raise C.Error('An existing destination directory was replaced')
            if journal is None and any(destination.iterdir()):
                raise C.Error('A destination gained data before staging; review it before creating a new plan')
            staged = (journal or {}).get('destinations', {}).get(str(destination))
            if staged and current != staged:
                raise C.Error('The staged destination directory was replaced')
        elif move.get('destination_identity') or (journal or {}).get('destinations', {}).get(str(destination)):
            raise C.Error('The planned or staged destination disappeared')
        binding = move.get('keep_path')
        if binding:
            fresh = _keep_binding(source, _path(binding['path']), move['source_identity'], mounts)
            if fresh != binding:
                raise C.Error('An original path bind changed since planning')


def _journal(record):
    current = C.read_journal(record)
    if current and current.get('state') in FINAL_STATES:
        raise C.Error('Switching has started or completed. Inspect its journal; automatic copy or switch replay is refused')
    return current


def _save(record, journal, state=None):
    if state:
        journal['state'] = state
    journal['updated'] = time.time()
    return C.update_journal(record, journal)


def _copy(move, checksum=False):
    command = ['rsync', '-aHAXS', '--numeric-ids']
    if checksum:
        command += ['--checksum', '--dry-run', '--delete', '--itemize-changes', '--out-format=%i']
    else:
        command += ['--info=progress2']
    command += ['--', move['source'].rstrip('/') + '/', move['destination'].rstrip('/') + '/']
    output = C.command(command, capture=checksum, timeout=None)
    if checksum and output.strip():
        raise C.Error('Checksum or metadata comparison differs, or destination extras exist; originals remain unchanged')


def run(ref, resume=False):
    C.require_root()
    record = _load(ref)
    with C.lock(record):
        journal = _journal(record)
        if journal and not resume:
            raise C.Error('A staging journal exists; use migrate resume to repeat its safe copy passes')
        if resume and journal is None:
            raise C.Error('There is no staging journal to resume')
        _validate(record, journal)
        journal = journal or {'kind': 'migration', 'plan_id': record['id'], 'destinations': {}, 'originals_retained': True}
        _save(record, journal, 'copying')
        try:
            for index, move in enumerate(record['moves']):
                journal['active_move'] = index
                _save(record, journal)
                _validate(record, journal)
                destination = Path(move['destination'])
                destination.mkdir(parents=True, exist_ok=True)
                journal['destinations'][str(destination)] = _identity(destination)
                _save(record, journal)
                _copy(move)
            _validate(record, journal)
            journal.pop('active_move', None)
            journal.pop('verified', None)
            return _save(record, journal, 'staged')
        except BaseException:
            _save(record, journal, 'copy-failed')
            raise


def verify(ref):
    C.require_root()
    record = _load(ref)
    with C.lock(record):
        journal = _journal(record)
        if not journal or journal.get('state') not in ('staged', 'verified', 'verification-failed'):
            raise C.Error('Finish staging before verifying the migration')
        _validate(record, journal)
        _save(record, journal, 'verifying')
        try:
            for move in record['moves']:
                _validate(record, journal)
                _copy(move, checksum=True)
            _validate(record, journal)
            journal['verified'] = time.time()
            return _save(record, journal, 'verified')
        except BaseException:
            journal.pop('verified', None)
            _save(record, journal, 'verification-failed')
            raise


def _busy_paths(moves):
    prefixes = {Path(move[key]) for move in moves for key in ('source', 'destination')}
    prefixes.update(Path(move['keep_path']['path']) for move in moves if move.get('keep_path'))
    busy = set()
    for proc in PROC.iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        values = []
        try:
            links = [proc / 'cwd', proc / 'root', *list((proc / 'fd').iterdir())]
            for link in links:
                try:
                    values.append(os.readlink(link).removesuffix(' (deleted)'))
                except OSError as error:
                    if error.errno not in (errno.ENOENT, errno.ESRCH, errno.EINVAL):
                        raise
            try:
                for line in (proc / 'maps').read_text().splitlines():
                    parts = line.split(None, 5)
                    if len(parts) == 6:
                        values.append(parts[5].removesuffix(' (deleted)'))
            except OSError as error:
                if error.errno not in (errno.ENOENT, errno.ESRCH):
                    raise
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ESRCH):
                continue
            raise C.Error('Cannot inspect every relevant process; switch is refused') from None
        if any(value.startswith('/') and any(Path(value) == prefix or Path(value).is_relative_to(prefix) for prefix in prefixes) for value in values):
            busy.add(int(proc.name))
    return sorted(busy)


def _quiesced(moves):
    if not sys.stdin.isatty():
        raise C.Error('Switch requires an interactive text terminal')
    sessions = C.command(['loginctl', 'list-sessions', '--no-legend', '--no-pager'])
    for line in sessions.splitlines():
        if not line.split():
            continue
        session = line.split()[0]
        kind = C.command(['loginctl', 'show-session', session, '--property=Type', '--value']).strip()
        if kind in ('wayland', 'x11'):
            raise C.Error('Log out of all graphical sessions before switching; this command never logs you out')
    busy = _busy_paths(moves)
    if busy:
        raise C.Error('Migration paths are still used by process IDs: ' + ', '.join(map(str, busy)))


def _fstab_text(old, record):
    lines = old.splitlines(keepends=True)
    additions = []
    for move in record['moves']:
        binding = move.get('keep_path')
        if not binding:
            continue
        keep = binding['path']
        matches = [(index, fields) for index, fields in _fstab_rows(old) if fields[1] == keep]
        entry = f"{_escape(move['destination'])} {_escape(keep)} none bind,x-systemd.requires-mounts-for={_escape(move['destination'])} 0 0\n"
        if binding['existing_bind']:
            if len(matches) != 1 or len(matches[0][1]) < 4 or matches[0][1][0] != move['source'] or 'bind' not in matches[0][1][3].split(','):
                raise C.Error('An existing bind entry no longer matches the reviewed source')
            lines[matches[0][0]] = entry
        elif matches:
            raise C.Error('A preserved path already has an unreviewed fstab entry')
        else:
            additions.append(entry)
    retained = ''.join(lines)
    if additions:
        return retained + ('' if retained.endswith('\n') else '\n') + '\n# Reviewed bromigos storage migration\n' + ''.join(additions)
    return retained


def _atomic(path, text, mode):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def switch(ref, writers_stopped=False):
    C.require_root()
    if not writers_stopped:
        raise C.Error('Stop all writers yourself and explicitly pass --writers-stopped before switching')
    record = _load(ref)
    if not any(move.get('keep_path') for move in record['moves']):
        raise C.Error('A copy-only plan has no preserved paths to switch; use migrate verify and configure applications yourself')
    with C.lock(record):
        journal = _journal(record)
        if not journal or journal.get('state') not in ('staged', 'verified'):
            raise C.Error('Finish staging and review the migration before switching')
        _validate(record, journal)
        _quiesced(record['moves'])
        if input('Type SWITCH ' + record['id'] + ' to preserve originals and switch the reviewed paths: ').strip() != 'SWITCH ' + record['id']:
            raise C.Error('Switch cancelled; originals are unchanged')
        # Final copy and checksum are fresh, even after a previous verify command.
        _save(record, journal, 'final-copy')
        try:
            for move in record['moves']:
                _validate(record, journal)
                _copy(move)
            for move in record['moves']:
                _validate(record, journal)
                _copy(move, checksum=True)
            _validate(record, journal)
            _quiesced(record['moves'])
        except BaseException:
            _save(record, journal, 'verification-failed')
            raise
        if FSTAB.is_symlink() or not FSTAB.is_file():
            raise C.Error('Switch requires a regular fstab file')
        old = FSTAB.read_text()
        changed = _fstab_text(old, record)
        mode = stat.S_IMODE(FSTAB.stat().st_mode)
        backup = FSTAB.with_name(FSTAB.name + '.before-storage-' + record['id'])
        if backup.exists() or backup.is_symlink():
            raise C.Error('The retained fstab backup already exists; inspect the previous switch')
        retained = []
        for move in record['moves']:
            binding = move.get('keep_path')
            if binding and not binding['existing_bind']:
                source = Path(move['source'])
                preserved = source.with_name(source.name + '.before-storage-' + record['id'])
                if preserved.exists() or preserved.is_symlink():
                    raise C.Error('An original-data backup path already exists')
                retained.append({'original': str(source), 'retained': str(preserved)})
        journal.update(fstab_backup=str(backup), retained=retained, switched_paths=[], originals_retained=True)
        # Persist intent before the first source rename, unmount or fstab write.
        _save(record, journal, 'switching')
        candidate = None
        try:
            _atomic(backup, old, mode)
            fd, candidate_name = tempfile.mkstemp(prefix='.bromigos-storage-fstab-', dir=FSTAB.parent)
            os.close(fd)
            candidate = Path(candidate_name)
            # Validate only these planned bind entries. Existing unrelated network
            # mounts may be offline; their unchanged fstab rows are not our operation.
            targets = {move['keep_path']['path'] for move in record['moves'] if move.get('keep_path')}
            changed_lines = changed.splitlines(keepends=True)
            selected = [(index, fields) for index, fields in _fstab_rows(changed) if fields[1] in targets]
            if len(selected) != len(targets):
                raise C.Error('The planned bind entries could not be identified exactly')
            validation = ''.join(changed_lines[index] for index, _ in selected)
            _atomic(candidate, validation, mode)
            C.command(['findmnt', '--verify', '--tab-file', str(candidate)])
            for move in record['moves']:
                binding = move.get('keep_path')
                if not binding:
                    continue
                original = Path(binding['path'])
                journal['active_path'] = str(original); _save(record, journal)
                if binding['existing_bind']:
                    C.command(['umount', '--', str(original)])
                else:
                    preserved = next(item['retained'] for item in retained if item['original'] == str(original))
                    original.rename(preserved)
                    original.mkdir(mode=0o000)
                journal.setdefault('prepared_paths', []).append(str(original)); _save(record, journal)
            if changed != old:
                _atomic(FSTAB, changed, mode)
                C.command(['systemctl', 'daemon-reload'])
            for move in record['moves']:
                binding = move.get('keep_path')
                if not binding:
                    continue
                original = Path(binding['path'])
                C.command(['mount', '--', str(original)])
                if _identity(original) != _identity(Path(move['destination'])) or _filesystem(original)['uuid'] != move['destination_filesystem']['uuid']:
                    raise C.Error('A preserved path did not resolve to the exact staged destination; inspect recovery records')
                journal['switched_paths'].append(str(original)); _save(record, journal)
            journal.pop('active_path', None)
            return _save(record, journal, 'switched')
        except BaseException:
            _save(record, journal, 'switch-failed')
            raise
        finally:
            if candidate is not None:
                candidate.unlink(missing_ok=True)
