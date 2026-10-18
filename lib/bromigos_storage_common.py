"""Private local storage plans, execution records and bounded command execution."""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile


class Error(Exception):
    """An operational error safe to show without subprocess output."""


def state_dir():
    override = os.environ.get('BROMIGOS_STORAGE_STATE')
    return Path(override) if override else Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'bromigos/storage'


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(record):
    return hashlib.sha256(json.dumps({k: v for k, v in record.items() if k != 'digest'}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def atomic(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise Error('A saved storage record is a symlink; inspect it before continuing')
    owner = path.parent.stat()
    value = dict(record)
    value['digest'] = digest(value)
    fd, temporary = tempfile.mkstemp(prefix='.storage-', dir=path.parent)
    try:
        if os.geteuid() == 0:
            os.fchown(fd, owner.st_uid, owner.st_gid)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return value


def store(kind, record):
    if kind != 'plans':
        raise Error('Unsupported storage record category')
    ident = 'plan-' + secrets.token_hex(8)
    path = (state_dir() / kind / (ident + '.json')).resolve()
    value = dict(record, id=ident, path=str(path), schema=1, created=now())
    return atomic(path, value)


def _load(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise Error('Saved storage record is missing or is not a regular file')
    if path.stat().st_size > 4 * 1024 * 1024:
        raise Error('Saved storage record is too large')
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        raise Error('Cannot read the saved storage record') from None
    if not isinstance(value, dict) or value.get('digest') != digest(value):
        raise Error('Saved storage record changed or is invalid; inspect it and create a new plan')
    return value


def read(ref, kind='plans'):
    if kind != 'plans':
        raise Error('Unsupported storage record category')
    ref = str(ref)
    if re.fullmatch(r'plan-[0-9a-f]{16}', ref):
        path = state_dir() / kind / (ref + '.json')
    elif Path(ref).is_absolute():
        path = Path(ref)
    else:
        raise Error('Use a complete plan ID or an absolute saved-plan path')
    value = _load(path)
    if value.get('path') != str(path.resolve()) or value.get('schema') != 1:
        raise Error('Saved plan location or schema changed; create a new plan')
    return value


def _journal_path(plan):
    path = Path(plan['path'])
    return path.with_name(path.stem + '.run.json')


def update_journal(plan, data):
    return atomic(_journal_path(plan), dict(data, plan_id=plan['id'], plan_digest=plan['digest'], updated=now()))


def read_journal(plan):
    path = _journal_path(plan)
    if not path.exists() and not path.is_symlink():
        return None
    value = _load(path)
    if value.get('plan_id') != plan['id'] or value.get('plan_digest') != plan['digest']:
        raise Error('Execution record does not match this storage plan')
    return value


def require_root():
    if os.geteuid() != 0:
        raise Error('This step needs root. Run it yourself with sudo and the absolute saved-plan path; no authentication window will be opened')


@contextlib.contextmanager
def lock(plan):
    if os.geteuid() == 0:
        path = Path('/run/lock/bromigos-storage.lock')
    else:
        path = state_dir() / 'operation.lock'
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_uid != os.geteuid():
            raise Error('Storage operation lock has an unexpected owner')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error('Another storage operation is running') from None
        yield
    finally:
        os.close(fd)


def command(argv, *, capture=True, timeout=30, okay=(0,), env=None):
    try:
        result = subprocess.run(argv, capture_output=capture, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Error(f'{Path(str(argv[0])).name} timed out; inspect the execution record before continuing') from None
    except OSError:
        raise Error(f'Cannot run {Path(str(argv[0])).name}; check that the required tool is installed') from None
    if result.returncode not in okay:
        raise Error(f'{Path(str(argv[0])).name} failed (exit {result.returncode}); inspect the operation before continuing')
    return result.stdout if capture else ''
