"""Reviewed maintenance checklists and optional private Ansible runbooks."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import tomllib

from . import config


class MaintenanceError(Exception):
    pass


def state_dir():
    base = os.environ.get('BROMIGOS_LAB_STATE') or str(Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'bromigos/lab')
    return Path(base) / 'maintenance'


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.maintenance-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _path(kind, ident):
    if not re.fullmatch(r'[a-z]+-[0-9a-f]{16}', ident):
        raise MaintenanceError('Use the full plan or run ID shown by maintenance status')
    return state_dir() / kind / (ident + '.json')


def _read(kind, ident):
    try:
        return json.loads(_path(kind, ident).read_text())
    except (OSError, ValueError):
        raise MaintenanceError('Saved maintenance record is missing or invalid') from None


@contextlib.contextmanager
def _lock():
    root = state_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / 'lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MaintenanceError('Another maintenance command is already running') from None
        yield
    finally:
        os.close(fd)


def _manual(ident, title, detail):
    return dict(id=ident, title=title, detail=detail, kind='manual')


def _guards(mode):
    return [
        _manual('checkpoint-backups', 'Confirm backups', 'Confirm recent recoverable backups, database exports and the recovery keys you need are available outside the rack.' if mode == 'shutdown' else 'Confirm the saved backups and recovery keys are available before starting services.'),
        _manual('checkpoint-recovery', 'Keep the recovery plan available', 'Save the cabling photos, labels, management access and startup order somewhere you can read while the rack is off.'),
        _manual('checkpoint-operator', 'Review protected workloads', 'Only the operator may stop or start protected workloads. Confirm their state and handle any such workloads yourself before continuing.'),
    ]


def builtin_steps(mode):
    if mode == 'shutdown':
        stages = [
            ('labels', 'Photograph and label the rack', 'Photograph cabling and label both ends, ports, power leads and device positions before unplugging anything.'),
            ('jobs', 'Stop jobs and game sessions', 'Notify users, save games and stop new work. Wait for running jobs and downloads to finish or pause safely.'),
            ('applications', 'Stop applications and database writers', 'Use your reviewed service procedures. Confirm writes are stopped and databases have shut down cleanly.'),
            ('workers', 'Shut down workers and compute', 'Gracefully stop worker and compute guests. Respect workload protection; do not force drain or delete data.'),
            ('control-plane', 'Shut down the control plane', 'Confirm the cluster backup and gracefully stop the control plane using its documented procedure.'),
            ('hypervisors', 'Shut down hypervisors', 'Confirm their guests are stopped, then gracefully shut down the virtualization hosts.'),
            ('storage', 'Shut down NAS and storage', 'Confirm every storage client has stopped and writes are complete before gracefully stopping storage.'),
            ('network', 'Stop networking last', 'Keep management networking available until everything depending on it has stopped. Follow the device power procedures.'),
        ]
    else:
        stages = [
            ('network', 'Start networking', 'Restore labelled cabling and power. Confirm switches, routing and management access work.'),
            ('storage', 'Start NAS and storage', 'Wait for storage pools and exports to become ready. Stop if a pool is degraded or recovery is needed.'),
            ('hypervisors', 'Start hypervisors', 'Confirm storage is ready before starting virtualization hosts and their guests.'),
            ('control-plane', 'Start the control plane', 'Start control-plane guests and confirm cluster quorum and API readiness.'),
            ('secrets', 'Restore secrets access', 'Follow the documented operator recovery or unseal procedure. Never paste recovery keys into maintenance records.'),
            ('workers', 'Start workers and applications', 'Start workers and applications in their documented dependency order. Check database and storage health.'),
            ('models', 'Restore models, jobs and games', 'Restore model services, queues and game servers after their dependencies are ready.'),
            ('readiness', 'Check service readiness', 'Confirm expected services, storage and backups are healthy before allowing new writes and user sessions.'),
        ]
    return [_manual(*stage) for stage in stages]


def load_profile(name='default', profile_file=None):
    settings = config.table('maintenance')
    selected_file = profile_file or settings.get('profile_file')
    origin = {'profile': name}
    if selected_file:
        path = Path(selected_file).expanduser().resolve()
        try:
            raw = path.read_bytes()
            profile = tomllib.loads(raw.decode())
        except (OSError, ValueError, UnicodeError):
            raise MaintenanceError('Cannot read the configured maintenance TOML profile') from None
        origin.update(profile_file=str(path), file_digest=hashlib.sha256(raw).hexdigest())
        if profile.get('repo'):
            profile['repo'] = str((path.parent / profile['repo']).resolve())
    else:
        profiles = settings.get('profiles', {})
        profile = profiles.get(name) if name != 'default' else settings.get('profile', profiles.get('default', {}))
        if profile is None:
            raise MaintenanceError('That maintenance profile is not configured')
    if not isinstance(profile, dict):
        raise MaintenanceError('Maintenance profile must be a table')
    allowed = {'name', 'repo', 'inventory', 'context', 'steps'}
    if set(profile) - allowed:
        raise MaintenanceError('Maintenance profile contains unsupported fields; keep credentials in existing Ansible authentication')
    return profile, origin


def _inside(repo, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise MaintenanceError('Runbook and inventory paths must be relative to the reviewed repository')
    path = (repo / value).resolve()
    if not path.is_relative_to(repo) or not path.is_file():
        raise MaintenanceError('A runbook or inventory is missing or outside the reviewed repository')
    return path


def _git(repo, args):
    try:
        result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        raise MaintenanceError('Cannot check the reviewed repository') from None
    if result.returncode:
        raise MaintenanceError('Cannot check the reviewed repository')
    return result.stdout.strip()


def _steps(profile, mode):
    configured = profile.get('steps', {})
    if not isinstance(configured, dict) or set(configured) - {'shutdown', 'startup'}:
        raise MaintenanceError('Profile steps must contain shutdown or startup lists')
    steps = configured.get(mode, builtin_steps(mode))
    if not isinstance(steps, list) or not steps:
        raise MaintenanceError('A maintenance plan needs an ordered list of steps')
    steps = _guards(mode) + steps + [_manual('checkpoint-record', 'Record the actual equipment state', 'Inspect the equipment and record your confirmation. This checklist records operator acknowledgements; it does not verify that equipment is powered off.' if mode == 'shutdown' else 'Inspect the equipment and confirm the expected services are ready. This records your acknowledgement, not an automatic health verification.')]
    ids = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) - {'id', 'title', 'detail', 'kind', 'playbook', 'timeout'}:
            raise MaintenanceError('Invalid maintenance step fields')
        ident = step.get('id', '')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', ident) or ident in ids:
            raise MaintenanceError('Maintenance step IDs must be unique short lower-case names')
        ids.add(ident)
        if step.get('kind') not in ('manual', 'ansible') or not all(isinstance(step.get(k), str) and step[k].strip() for k in ('title', 'detail')):
            raise MaintenanceError('Each step needs a kind, title and instructions')
        if step['kind'] == 'ansible' and (type(step.get('timeout', 600)) is not int or not 1 <= step.get('timeout', 600) <= 7200):
            raise MaintenanceError('Runbook timeout must be 1 through 7200 seconds')
    return steps


def _binding(profile, steps):
    binding = {'profile': profile}
    automated = [step for step in steps if step['kind'] == 'ansible']
    if not automated:
        return binding
    repo = Path(profile.get('repo', '')).expanduser().resolve()
    if not profile.get('repo') or not repo.is_dir() or not isinstance(profile.get('context'), str) or not profile['context'].strip():
        raise MaintenanceError('Ansible steps need a reviewed repository and explicit Kubernetes context')
    if Path(_git(repo, ['rev-parse', '--show-toplevel'])).resolve() != repo:
        raise MaintenanceError('Use the root of the reviewed repository')
    if _git(repo, ['status', '--porcelain']):
        raise MaintenanceError('Commit or save changes in the reviewed repository before maintenance')
    paths = [_inside(repo, profile.get('inventory'))] + [_inside(repo, step.get('playbook')) for step in automated]
    ansible_cfg = repo / 'ansible.cfg'
    if ansible_cfg.is_file():
        paths.append(_inside(repo, 'ansible.cfg'))
    binding.update(repo=str(repo), head=_git(repo, ['rev-parse', 'HEAD']), files={str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    return binding


def plan(mode, profile_name='default', profile_file=None):
    if mode not in ('shutdown', 'startup'):
        raise MaintenanceError('Choose shutdown or startup')
    profile, origin = load_profile(profile_name, profile_file)
    steps = _steps(profile, mode)
    binding = _binding(profile, steps)
    record = dict(id='plan-' + secrets.token_hex(8), mode=mode, created=_now(), origin=origin, steps=steps, binding_digest=_digest(binding), state='planned', equipment_state='not verified')
    record['digest'] = _digest(record)
    _write(_path('plans', record['id']), record)
    return record


def _validated(record):
    saved = dict(record)
    digest = saved.pop('digest', None)
    if digest != _digest(saved):
        raise MaintenanceError('The saved plan changed; create and review a new plan')
    origin = record['origin']
    profile, current_origin = load_profile(origin['profile'], origin.get('profile_file'))
    steps = _steps(profile, record['mode'])
    if current_origin != origin or steps != record['steps'] or _digest(_binding(profile, steps)) != record['binding_digest']:
        raise MaintenanceError('The profile or reviewed repository changed; create and review a new plan')
    return profile


def render(record):
    print(f"{record['id']} · {record['mode']} · {record['state']}")
    print('Equipment state: not automatically verified. Manual steps record operator confirmations.')
    for index, step in enumerate(record['steps'], 1):
        print(f"{index}. [{step['kind']}] {step['title']} ({step['id']})\n   {step['detail']}")


def _runbook(profile, step):
    repo = Path(profile['repo']).expanduser().resolve()
    inventory, playbook = _inside(repo, profile['inventory']), _inside(repo, step['playbook'])
    env = dict(os.environ, ANSIBLE_CONFIG=str(repo / 'ansible.cfg') if (repo / 'ansible.cfg').is_file() else os.devnull, ANSIBLE_HOST_KEY_CHECKING='True', ANSIBLE_NO_LOG='true', BROMIGOS_KUBE_CONTEXT=profile['context'], KUBE_CONTEXT=profile['context'])
    if (repo / 'ansible.cfg').is_file():
        env['ANSIBLE_CONFIG'] = str(repo / 'ansible.cfg')
    try:
        result = subprocess.run(['ansible-playbook', '-i', str(inventory), str(playbook)], cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=step.get('timeout', 600))
    except subprocess.TimeoutExpired:
        raise MaintenanceError('Runbook timed out; its resulting equipment state is unknown') from None
    except OSError:
        raise MaintenanceError('Runbook could not start; check the installed Ansible tools and authentication') from None
    if result.returncode:
        raise MaintenanceError('Runbook failed; its resulting equipment state is unknown')


def execute(ident, resume=False, approved=False):
    with _lock():
        if resume:
            journal = _read('runs', ident)
            record = _read('plans', journal['plan_id'])
        else:
            record = _read('plans', ident)
            for existing in (state_dir() / 'runs').glob('*.json'):
                try:
                    prior = json.loads(existing.read_text())
                    prior_plan = prior['plan_id']
                except (OSError, ValueError, KeyError):
                    raise MaintenanceError('A saved execution record is invalid; inspect the maintenance journal before starting another run') from None
                if prior_plan == ident:
                    raise MaintenanceError('This plan already has an execution record. Resume its paused run, or inspect the equipment and create a new reviewed plan; run will not repeat it')
            journal = dict(id='run-' + secrets.token_hex(8), plan_id=ident, mode=record['mode'], created=_now(), state='awaiting approval', equipment_state='not verified', steps=[])
        profile = _validated(record)
        if any(step['state'] in ('started', 'unknown') for step in journal['steps']):
            raise MaintenanceError('A previous step has an uncertain result. Inspect the equipment and create a new reviewed plan; resume will not repeat it')
        render(record)
        if not sys.stdin.isatty():
            if any(step['kind'] == 'manual' and not any(done['id'] == step['id'] and done['state'] == 'completed' for done in journal['steps']) for step in record['steps']):
                raise MaintenanceError('Pending manual checkpoints need an interactive terminal; --yes cannot acknowledge them')
            if not approved:
                raise MaintenanceError('Execution needs interactive approval or --yes with the explicit plan ID')
        if not approved and input(f"Run this reviewed {record['mode']} plan? Type yes: ").strip() != 'yes':
            print('Plan kept. No runbooks executed.')
            return None
        journal['state'] = 'running'
        path = _path('runs', journal['id'])
        _write(path, journal)
        print('Run ID: ' + journal['id'])
        for step in record['steps']:
            if any(done['id'] == step['id'] and done['state'] == 'completed' for done in journal['steps']):
                continue
            print(f"\n{step['title']}\n{step['detail']}")
            if step['kind'] == 'manual':
                try:
                    answer = input(f"After doing this yourself, type done {step['id']} (anything else pauses): ").strip()
                except (KeyboardInterrupt, EOFError):
                    journal['state'] = 'paused'
                    _write(path, journal)
                    raise
                if answer != 'done ' + step['id']:
                    journal['state'] = 'paused'
                    _write(path, journal)
                    print('Paused. Equipment state remains unverified. Resume with ' + journal['id'])
                    return journal
                journal['steps'].append(dict(id=step['id'], state='completed', evidence='recorded operator confirmation', finished=_now()))
                _write(path, journal)
                continue
            try:
                _validated(record)
            except MaintenanceError:
                journal['state'] = 'paused'
                _write(path, journal)
                raise
            entry = dict(id=step['id'], state='started', evidence='result pending', started=_now())
            journal['steps'].append(entry)
            _write(path, journal)
            try:
                _runbook(profile, step)
            except (MaintenanceError, KeyboardInterrupt):
                entry.update(state='unknown', evidence='runbook result not verified', finished=_now())
                journal['state'] = 'stopped'
                _write(path, journal)
                raise
            entry.update(state='completed', evidence='runbook exited successfully; equipment state not independently verified', finished=_now())
            _write(path, journal)
        journal['state'] = 'completed'
        _write(path, journal)
        print('Checklist completed. Operator confirmations recorded; equipment power state is not automatically verified.')
        return journal


def status():
    result = {'equipment_state': 'not verified', 'plans': [], 'runs': []}
    for kind in ('plans', 'runs'):
        for path in sorted((state_dir() / kind).glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                record = json.loads(path.read_text())
                result[kind].append({key: record[key] for key in ('id', 'state', 'mode', 'created')})
            except (OSError, ValueError, KeyError):
                continue
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog='bromigos lab maintenance', description='Review and follow a rack shutdown or startup checklist; no automatic power assumptions')
    sub = parser.add_subparsers(dest='verb')
    checking = sub.add_parser('check', help='Read configured lab health checks; backups and power state are not verified')
    checking.add_argument('--json', action='store_true')
    status_parser = sub.add_parser('status', help='Show saved plans and execution records; equipment state is not inferred')
    status_parser.add_argument('--json', action='store_true')
    planning = sub.add_parser('plan', help='Save and show a checklist without executing runbooks')
    planning.add_argument('mode', choices=('shutdown', 'startup'))
    planning.add_argument('--profile', default='default')
    planning.add_argument('--profile-file', help='Private TOML profile; relative repository paths resolve beside this file')
    planning.add_argument('--json', action='store_true')
    for verb in ('run', 'resume'):
        command = sub.add_parser(verb, help='Review and explicitly approve a saved plan or resume a paused run')
        command.add_argument('id', help='Full plan ID for run, or run ID for resume')
        command.add_argument('--yes', action='store_true', help='Approve the displayed saved plan; manual checkpoints still need typed confirmations')
    args = parser.parse_args(argv)
    try:
        if args.verb == 'check':
            from . import doctor
            result = dict(doctor.run(), note='Health checks do not verify backups or equipment power state.')
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(result['note'])
                counts = result.get('summary', {})
                print('Lab health: ' + ', '.join(f'{counts.get(state, 0)} {state}' for state in ('ok', 'warn', 'fail', 'skip')))
                for finding in result.get('findings', []):
                    print(f"[{finding.get('status', 'unknown')}] {finding.get('title', '')}: {finding.get('detail', '')}")
                    if finding.get('fix'):
                        print('  ' + finding['fix'])
        elif args.verb == 'plan':
            record = plan(args.mode, args.profile, args.profile_file)
            print(json.dumps(record, indent=2)) if args.json else render(record)
        elif args.verb in ('run', 'resume'):
            execute(args.id, resume=args.verb == 'resume', approved=args.yes)
        else:
            result = status()
            if getattr(args, 'json', False):
                print(json.dumps(result, indent=2))
            else:
                print('Maintenance journal (saved records, not live lab health):')
                print('Equipment state: not verified.')
                for kind in ('plans', 'runs'):
                    for record in result[kind]:
                        print(f"{record['id']} · {record['mode']} · {record['state']}")
                if not result['plans'] and not result['runs']:
                    print('No plans yet. Start with: bromigos lab maintenance plan shutdown')
        return 0
    except (MaintenanceError, OSError, ValueError, KeyError) as error:
        print('Maintenance stopped: ' + (str(error) if isinstance(error, MaintenanceError) else 'Saved maintenance input is invalid or unavailable'), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('Maintenance interrupted. Inspect status before continuing; equipment state is not verified.', file=sys.stderr)
        return 130
