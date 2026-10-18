"""Reviewed single-disk Btrfs provisioning. No privilege escalation or disk probing writes."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

import bromigos_storage_common as C

ROLES = ('development', 'games', 'downloads', 'vms', 'models')
FSTAB = Path('/etc/fstab')


def _json(argv):
    try:
        result = json.loads(C.command(argv, timeout=15))
    except (TypeError, ValueError):
        raise C.Error('Storage utility returned invalid JSON') from None
    if not isinstance(result, dict):
        raise C.Error('Storage utility response is not a table')
    return result


def _nodes(rows):
    if not isinstance(rows,list):
        raise C.Error('Storage utility response has invalid device or mount rows')
    for row in rows:
        if not isinstance(row,dict):
            raise C.Error('Storage utility response contains an invalid row')
        yield row
        yield from _nodes(row.get('children', []))


def _identity(device):
    path = Path(device)
    if not str(path).startswith('/dev/disk/by-id/') or path.parent != Path('/dev/disk/by-id') or '-part' in path.name:
        raise C.Error('Select a whole disk by its stable /dev/disk/by-id/ path')
    try:
        info = path.stat()
        canonical = str(path.resolve(strict=True))
    except OSError:
        raise C.Error('The selected stable disk path is not available') from None
    if not stat.S_ISBLK(info.st_mode):
        raise C.Error('Selected path is not a block device')
    result = _json(['lsblk', '--json', '--bytes', '--paths', '--output',
                    'NAME,PATH,TYPE,SIZE,RO,MODEL,SERIAL,WWN,MAJ:MIN,FSTYPE,UUID,LABEL,PARTUUID,PARTLABEL,MOUNTPOINTS', canonical])
    disks = result.get('blockdevices')
    if not isinstance(disks, list) or len(disks) != 1:
        raise C.Error('Cannot identify exactly one selected disk')
    disk = disks[0]
    serial = disk.get('serial')
    serial = serial.strip() if isinstance(serial,str) else ''
    if disk.get('ro') not in (False,0):
        raise C.Error('The selected disk is read-only or its writeability is unknown')
    if disk.get('type') != 'disk' or not serial or type(disk.get('size')) is not int or disk['size'] <= 0:
        raise C.Error('Disk type, exact serial and size must be available')
    major_minor = f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'
    if disk.get('maj:min') != major_minor or disk.get('path') != canonical:
        raise C.Error('Disk node identity differs from the utility response')
    return {'by_id': str(path), 'path': canonical, 'serial': serial, 'size_bytes': disk['size'],
            'model': (disk.get('model') or '').strip(), 'wwn': disk.get('wwn'),
            'major_minor': major_minor}, disks


def _paths(mount, roles):
    base = Path(mount)
    if not isinstance(mount, str) or base.parent != Path('/mnt') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', base.name):
        raise C.Error('Use one named mount directory directly under /mnt')
    if base.resolve() != base:
        raise C.Error('The mount path must not contain symlinks')
    if not isinstance(roles, list) or not roles or roles[0] != 'development' or len(set(roles)) != len(roles) or any(r not in ROLES for r in roles):
        raise C.Error('Roles must start with development and contain only the supported unique names')
    return [{'role': role, 'subvolume': '@' + role,
             'mount': str(base if role == 'development' else base / role)} for role in roles]


def _guard(disks, mounts):
    if FSTAB.is_symlink():
        raise C.Error('fstab is a symlink; review persistent mount configuration before provisioning')
    children = list(_nodes(disks))
    identities = {d.get('maj:min') for d in children}
    uuids = {d.get('uuid') for d in children if d.get('uuid')}
    tags = {key.upper(): {d.get(key) for d in children if d.get(key)} for key in ('uuid','label','partuuid','partlabel')}
    paths = {d.get('path') for d in children}
    live = _json(['findmnt', '--json', '--output', 'TARGET,SOURCE,MAJ:MIN,UUID'])
    if not isinstance(live.get('filesystems'), list):
        raise C.Error('Cannot verify current mounted filesystems')
    for row in _nodes(live['filesystems']):
        if row.get('maj:min') in identities or row.get('uuid') in uuids or str(row.get('source', '')).split('[')[0] in paths:
            raise C.Error('Selected disk or one of its children is mounted; root and boot disks cannot be erased')
        if row.get('target') in {m['mount'] for m in mounts}:
            raise C.Error('A planned mount path is already mounted')
    for disk in children:
        if any(disk.get('mountpoints') or []):
            raise C.Error('Selected disk has a mounted child or active swap')
        name = Path(disk.get('path') or '').name
        holders = Path('/sys/class/block') / name / 'holders'
        if not holders.is_dir():
            raise C.Error('Cannot verify block-device holders')
        if any(holders.iterdir()):
            raise C.Error('Selected disk is held by another block device')
    try:
        swaps = Path('/proc/swaps').read_text().splitlines()[1:]
        fstab = FSTAB.read_text()
    except OSError:
        raise C.Error('Cannot read swap or persistent mount configuration') from None
    for line in swaps:
        source = line.split()[0]
        # A swapfile on this disk is covered by the mounted-filesystem check.
        if str(Path(source).resolve()) in paths:
            raise C.Error('Selected disk contains active swap')
    for line in fstab.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith('#'):
            continue
        if len(fields) < 2:
            raise C.Error('Persistent mount configuration contains an invalid entry')
        source = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[0])
        if (any(source.startswith(tag+'=') and source[len(tag)+1:] in values for tag,values in tags.items())) or (source.startswith('/dev/') and str(Path(source).resolve()) in paths):
            raise C.Error('Selected disk is referenced by persistent mount configuration')
        if fields[1] in {m['mount'] for m in mounts}:
            raise C.Error('A planned mount path is already configured in fstab')
    for entry in mounts:
        path = Path(entry['mount'])
        if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
            raise C.Error('Planned mount directories must be absent or empty; repository and data paths are protected')
    return hashlib.sha256(fstab.encode()).hexdigest()


def plan(device, mount, roles=None):
    mounts = _paths(mount, list(ROLES) if roles is None else roles)
    identity, disks = _identity(device)
    fstab_digest = _guard(disks, mounts)
    return C.store('plans', {'kind': 'provision', 'device': identity, 'mounts': mounts,
                              'owner_uid': os.getuid(), 'owner_gid': os.getgid(),
                              'fstab_digest': fstab_digest, 'erase_warning': 'Applying erases the entire selected disk.',
                              'layout': 'GPT, one Linux partition, Btrfs with normal copy-on-write and checksums; no encryption or snapshots'})


def _approve(serial):
    try:
        with open('/dev/tty', 'r+') as tty:
            if not tty.isatty():
                raise C.Error('Provisioning requires an interactive operator terminal')
            tty.write('This erases the whole disk. Type its exact serial to continue: ')
            tty.flush()
            if tty.readline().rstrip('\n') != serial:
                raise C.Error('Disk erase was not approved')
    except OSError:
        raise C.Error('Provisioning requires an interactive operator terminal') from None


def _backup_fstab(plan):
    old = FSTAB.read_bytes()
    if hashlib.sha256(old).hexdigest() != plan['fstab_digest']:
        raise C.Error('fstab changed before erasure; prepare a new plan')
    backup = FSTAB.with_name('fstab.before-' + plan['id'])
    with backup.open('xb') as stream:
        stream.write(old); stream.flush(); os.fsync(stream.fileno())
    os.chmod(backup, 0o600)
    directory = os.open(FSTAB.parent, os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)
    return str(backup)


def _publish_fstab(plan, uuid, backup):
    old = FSTAB.read_bytes()
    if hashlib.sha256(old).hexdigest() != plan['fstab_digest'] or Path(backup).read_bytes()!=old:
        raise C.Error('fstab changed during provisioning; review it before recovery')
    additions = '# bromigos storage ' + plan['id'] + '\n'
    for row in plan['mounts']:
        additions += f"UUID={uuid} {row['mount']} btrfs defaults,ssd,compress=zstd,subvol={row['subvolume']} 0 0\n"
    fd, checkfile = tempfile.mkstemp(prefix='.fstab-storage-check-', dir=FSTAB.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(additions); stream.flush(); os.fsync(stream.fileno())
        # Do not reject unrelated historical/network entries after disk formatting.
        C.command(['findmnt', '--verify', '--tab-file', checkfile], timeout=20)
    finally:
        os.unlink(checkfile)
    fd, name = tempfile.mkstemp(prefix='.fstab-storage-', dir=FSTAB.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(old.rstrip(b'\n') + b'\n\n' + additions.encode()); stream.flush(); os.fsync(stream.fileno())
        os.chmod(name, stat.S_IMODE(FSTAB.stat().st_mode))
        os.replace(name, FSTAB)
        directory = os.open(FSTAB.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)
    return str(backup)


def apply(ref):
    C.require_root()
    record = C.read(ref, kind='plans')
    if record.get('kind') != 'provision':
        raise C.Error('This is not a disk provisioning plan')
    with C.lock(record):
        if C.read_journal(record) is not None:
            raise C.Error('This plan already has an execution record; inspect it instead of retrying an erase')
        if _paths(record['mounts'][0]['mount'], [r['role'] for r in record['mounts']]) != record['mounts']:
            raise C.Error('Saved mount layout is invalid')
        for tool in ('lsblk','findmnt','wipefs','sgdisk','partprobe','udevadm','mkfs.btrfs','btrfs','mount','umount','blkid','systemctl'):
            if not shutil.which(tool):
                raise C.Error('Required storage utility is unavailable: ' + tool)
        identity, disks = _identity(record['device']['by_id'])
        if identity != record['device'] or _guard(disks, record['mounts']) != record['fstab_digest']:
            raise C.Error('Disk identity or persistent mount configuration changed; prepare a new plan')
        _approve(identity['serial'])
        # Approval can take time: repeat all safety checks immediately before journaling.
        identity2, disks = _identity(identity['by_id'])
        if identity2 != identity or _guard(disks, record['mounts']) != record['fstab_digest']:
            raise C.Error('Storage state changed while awaiting approval')
        backup = _backup_fstab(record)
        state = {'state': 'erase-started', 'device': identity, 'mounted': [], 'physical_state': 'not verified', 'fstab_backup': backup}
        C.update_journal(record, state)
        temporary = None
        temporary_mounted = False
        try:
            device = identity['path']
            C.command(['wipefs','--all',device], timeout=60)
            C.command(['sgdisk','--zap-all',device], timeout=60)
            C.command(['sgdisk','--new=1:0:0','--typecode=1:8300',device], timeout=60)
            C.command(['partprobe',device], timeout=30)
            C.command(['udevadm','settle','--timeout=30'], timeout=40)
            current, _ = _identity(identity['by_id'])
            if current != identity:
                raise C.Error('Disk identity changed after partitioning; formatting was stopped')
            partition = device + ('p1' if device[-1].isdigit() else '1')
            C.command(['mkfs.btrfs','--force','--label','bromigos-storage',partition], timeout=None)
            uuid = C.command(['blkid','--match-tag','UUID','--output','value',partition], timeout=15).strip()
            if not re.fullmatch(r'[0-9a-fA-F-]{36}', uuid):
                raise C.Error('Cannot verify the new Btrfs UUID')
            state.update(state='formatted', filesystem_uuid=uuid); C.update_journal(record, state)
            temporary = Path(tempfile.mkdtemp(prefix='bromigos-storage-', dir='/run'))
            C.command(['mount','-t','btrfs','-o','subvolid=5',partition,str(temporary)], timeout=30)
            temporary_mounted = True
            for row in record['mounts']:
                sub = temporary / row['subvolume']
                C.command(['btrfs','subvolume','create',str(sub)], timeout=30)
                os.chown(sub, 0 if row['role']=='vms' else record['owner_uid'], 0 if row['role']=='vms' else record['owner_gid'])
                os.chmod(sub, 0o755)
            C.command(['umount',str(temporary)], timeout=30); temporary_mounted=False
            for row in record['mounts']:
                target=Path(row['mount'])
                if target.is_symlink() or target.resolve()!=target:
                    raise C.Error('A mount path became a symlink; mounting was stopped')
                target.mkdir(parents=True,exist_ok=True)
                if any(target.iterdir()):
                    raise C.Error('A mount directory gained files; refusing to cover them')
                C.command(['mount','-t','btrfs','-o','ssd,compress=zstd,subvol='+row['subvolume'],'UUID='+uuid,str(target)], timeout=30)
                state['mounted'].append(str(target)); C.update_journal(record,state)
                live = _json(['findmnt','--json','--mountpoint',str(target),'--output','UUID,FSTYPE,FSROOT'])
                rows=live.get('filesystems',[])
                if len(rows)!=1 or rows[0].get('uuid')!=uuid or rows[0].get('fstype')!='btrfs' or rows[0].get('fsroot')!='/'+row['subvolume']:
                    raise C.Error('New mount identity could not be verified')
            state['fstab_backup']=_publish_fstab(record,uuid,backup)
            C.command(['systemctl','daemon-reload'], timeout=30)
            state.update(state='complete',physical_state='filesystem and configured mounts verified')
            C.update_journal(record,state)
            return state
        except BaseException:
            state['state']='failed-needs-review'; C.update_journal(record,state)
            raise
        finally:
            if temporary_mounted:
                try: C.command(['umount',str(temporary)], timeout=30)
                except C.Error: pass
            if temporary is not None:
                try: temporary.rmdir()
                except OSError: pass
