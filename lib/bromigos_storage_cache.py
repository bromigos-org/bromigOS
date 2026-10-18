"""Explicit, owner-bound cleanup of known caches through their native tools."""
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

import bromigos_storage_common as C
import bromigos_storage_inventory as I
import bromigos_storage_migration as M

NAMES = ('npm', 'conda', 'package-archives')
USER_CACHES = {'npm', 'conda'}
PACKAGE_CACHE = Path('/var/cache/pacman/pkg')
PACMAN_LOCK = Path('/var/lib/pacman/db.lck')
PROC = Path('/proc')


def _location(name, home):
    return {'npm': home / '.npm/_cacache', 'conda': home / '.conda/pkgs', 'package-archives': PACKAGE_CACHE}[name]


def _tool(name):
    value = '/usr/bin/paccache' if name == 'package-archives' else shutil.which(name)
    if not value:
        raise C.Error('Install ' + ('pacman-contrib' if name == 'package-archives' else name) + ' before planning this cache cleanup')
    path = Path(value).resolve()
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise C.Error('Cache cleanup tool is unavailable')
    if name == 'package-archives' and (info.st_uid != 0 or info.st_mode & 0o022):
        raise C.Error('The system cache tool must be root-owned and not writable by other users')
    return {'path': str(path), 'device': info.st_dev, 'inode': info.st_ino,
            'size': info.st_size, 'modified_ns': info.st_mtime_ns}


def _path_guard(path, name):
    # Read mount metadata before stat so inactive automounts are never triggered.
    if not I._safe_local(path, I._read_mounts()):
        raise C.Error('Only direct local cache paths are supported; redirected or remote paths need separate review')
    if not path.is_dir():
        raise C.Error('The selected cache directory is missing or inaccessible')
    if name == 'conda':
        for child in (path/'cache', path/'.logs'):
            if child.is_symlink():
                raise C.Error('Conda cache/index log directories must not be symlinks')
    mounts = M._filesystems()
    if name == 'npm' and path in mounts:
        raise C.Error('The npm content cache must not itself be a mount point')
    if any(mount != path and mount.is_relative_to(path) for mount in mounts):
        raise C.Error('A selected cache contains another mounted filesystem')


def _recursive_scopes(item):
    """Native recursive cleaners must not enter nested Btrfs subvolumes."""
    if item['filesystem']['fstype'] != 'btrfs' or item['cache'] == 'package-archives':
        return
    path = Path(item['path'])
    roots = [path] if item['cache'] == 'npm' else [path/'cache', path/'.logs']
    def onerror(error):
        raise C.Error('Cannot inspect a recursive cache directory; cleanup is refused')
    for root in roots:
        if root.is_symlink():
            raise C.Error('Redirected recursive cache directories are refused')
        if not root.exists():
            continue
        if root.stat().st_ino == 256:
            raise C.Error('A cache cleanup scope is a nested Btrfs subvolume')
        for folder, children, _ in os.walk(root, followlinks=False, onerror=onerror):
            for name in children:
                child = Path(folder)/name
                info = child.lstat()
                if stat.S_ISDIR(info.st_mode) and info.st_ino == 256:
                    raise C.Error('A cache contains a nested Btrfs subvolume; review it separately')


def _busy(name, uid):
    names = {'npm': {'npm', 'npx', 'npm-cli.js', 'npx-cli.js'},
             'conda': {'conda', 'mamba', 'micromamba'},
             'package-archives': {'pacman', 'paccache', 'paru', 'yay', 'makepkg'}}[name]
    found = []
    for proc in PROC.iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if name in USER_CACHES and proc.stat().st_uid != uid:
                continue
            comm = (proc/'comm').read_text().strip()
            args = (proc/'cmdline').read_bytes().split(b'\0')[:64]
            executable_names = {Path(arg.decode(errors='replace')).name for arg in args if arg and not arg.startswith(b'-')}
            if comm.split(' ')[0] in names or names & executable_names:
                found.append(int(proc.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            if name == 'package-archives' and os.geteuid() != 0:
                continue  # Apply checks again with root access.
            raise C.Error('Cannot inspect cache clients; stop them before cleanup') from None
    if found:
        raise C.Error('Cache clients are running; close them first. Process IDs: ' + ', '.join(map(str, sorted(found))))
    if name == 'package-archives' and PACMAN_LOCK.exists():
        raise C.Error('Pacman is active; package archives were not cleaned')


def plan_items(names, keep_versions=3):
    if any(name not in NAMES for name in names) or len(names) != len(set(names)):
        raise C.Error('Select each supported cache at most once')
    if not isinstance(keep_versions, int) or isinstance(keep_versions, bool) or not 1 <= keep_versions <= 100:
        raise C.Error('Keep between 1 and 100 package versions; the default is 3')
    home, uid = Path.home(), os.geteuid()
    items = []
    for name in names:
        if name in USER_CACHES and uid == 0:
            raise C.Error('Plan npm and Conda cleanup as your normal user, without sudo')
        path = _location(name, home)
        _path_guard(path, name)
        if name in USER_CACHES and path.stat().st_uid != uid:
            raise C.Error('The selected user cache belongs to another user')
        items.append({'kind': 'cache', 'cache': name, 'path': str(path), 'home': str(home) if name in USER_CACHES else None,
                      'owner_uid': uid if name in USER_CACHES else 0,
                      'identity': M._identity(path), 'filesystem': M._filesystem(path),
                      'tool': _tool(name), 'keep_versions': keep_versions if name == 'package-archives' else None,
                      'scope': {'npm': 'Downloaded npm content only; keep npx installations and configuration',
                                'conda': 'Downloaded archives, index and logs only; keep extracted packages and environments',
                                'package-archives': f'Keep the newest {keep_versions} cached versions of each package'}[name]})
    return items


def require_access(items):
    user = [item for item in items if item.get('kind') == 'cache' and item.get('cache') in USER_CACHES]
    if user:
        if len(user) != len(items):
            raise C.Error('Use separate plans for user caches and system cleanup')
        if os.geteuid() == 0 or any(item.get('owner_uid') != os.geteuid() or item.get('home') != str(Path.home()) for item in user):
            raise C.Error('Apply this user-cache plan as its owner, without sudo')
    else:
        C.require_root()


def validate(item, busy=True):
    name = item.get('cache')
    if name not in NAMES:
        raise C.Error('Unsupported cache kind')
    if name == 'package-archives':
        expected = PACKAGE_CACHE
        if item.get('owner_uid') != 0 or item.get('home') is not None or not isinstance(item.get('keep_versions'), int) or isinstance(item['keep_versions'], bool) or not 1 <= item['keep_versions'] <= 100:
            raise C.Error('Invalid package-cache retention or owner')
    else:
        expected = _location(name, Path.home())
        if item.get('home') != str(Path.home()) or item.get('owner_uid') != os.geteuid() or os.geteuid() == 0:
            raise C.Error('User cache ownership changed; run as the planning user without sudo')
    path = Path(item['path'])
    if path != expected:
        raise C.Error('The cache path is not the supported location')
    _path_guard(path, name)
    if M._identity(path) != item['identity'] or M._filesystem(path) != item['filesystem']:
        raise C.Error('The selected cache or its filesystem changed; make a new plan')
    if name in USER_CACHES and path.stat().st_uid != item['owner_uid']:
        raise C.Error('Cache ownership changed')
    if _tool(name) != item['tool']:
        raise C.Error('The cache cleanup tool changed; make a new plan')
    if busy:
        _recursive_scopes(item)
        _busy(name, item['owner_uid'])


def _allocated(path):
    if not path.exists():
        return 0
    try:
        return int(C.command(['du', '-sx', '--block-size=1', '--', str(path)], timeout=15).split()[0])
    except (C.Error, OSError, ValueError, IndexError):
        return None


def clean(item):
    validate(item)
    path, name = Path(item['path']), item['cache']
    before = _allocated(path)
    # No inherited shell/node/python hooks, package-manager configuration variables,
    # or project cwd. Native tools only see their explicit cache and fixed options.
    with tempfile.TemporaryDirectory(prefix='bromigos-cache-') as temporary:
        env = {'PATH': '/usr/bin:/bin', 'HOME': item['home'] or temporary, 'LC_ALL': 'C',
               'PYTHONNOUSERSITE': '1'}
        executable = item['tool']['path']
        if name == 'npm':
            user_config = Path(temporary)/'user.npmrc'; user_config.touch()
            global_config = Path(temporary)/'global.npmrc'; global_config.touch()
            command = [executable, '--prefix', temporary, '--cache', str(path.parent), '--userconfig='+str(user_config), '--globalconfig='+str(global_config),
                       '--logs-max=0', '--ignore-scripts', 'cache', 'clean', '--force']
        elif name == 'conda':
            config_path = Path(temporary)/'condarc.yaml'
            config_path.write_text('{}\n')
            env.update(HOME=temporary, XDG_CONFIG_HOME=str(Path(temporary)/'config'),
                       CONDA_PKGS_DIRS=str(path), CONDA_NO_PLUGINS='true', CONDA_DRY_RUN='false', CONDARC=str(config_path))
            try:
                config = json.loads(C.command([executable, '--no-plugins', 'config', '--show', 'pkgs_dirs', 'dry_run', '--json'], env=env, cwd=temporary))
            except ValueError:
                raise C.Error('Cannot verify Conda cleanup configuration') from None
            if not isinstance(config, dict):
                raise C.Error('Cannot verify Conda cleanup configuration')
            if config.get('pkgs_dirs') != [str(path)]:
                raise C.Error('Conda resolves additional package caches; cleanup is refused until its cache configuration is reviewed')
            if config.get('dry_run') is not False:
                raise C.Error('Conda dry-run configuration would skip cleanup; review its configuration first')
            command = [executable, '--no-plugins', 'clean', '--tarballs', '--index-cache', '--logfiles', '--yes']
        else:
            command = [executable, '-r', '-k', str(item['keep_versions']), '-c', str(path), '--nocolor']
        validate(item)
        C.command(command, env=env, cwd=temporary, timeout=None)
    return {'cache': name, 'path': str(path), 'allocated_before': before, 'allocated_after': _allocated(path),
            'detail': 'Native cleanup command completed; retained cache content may remain. Filesystem free space is measured separately.'}
