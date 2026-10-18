"""The local storage CLI. Inspect by default; mutations use explicitly saved plans."""
import argparse
import json
from pathlib import Path
import sys
import shlex
import tomllib

import bromigos_storage_common as C


def records():
    result = []
    for path in sorted((C.state_dir() / 'plans').glob('plan-*.json')):
        if path.name.endswith('.run.json'):
            continue
        try:
            plan = C.read(str(path.resolve()))
            journal = C.read_journal(plan)
            result.append({'id': plan['id'], 'path': plan['path'], 'kind': plan.get('kind'),
                           'phase': (journal or {}).get('phase', (journal or {}).get('state', 'planned')),
                           'originals_retained': (journal or {}).get('originals_retained'),
                           'journal': journal})
        except (C.Error, OSError, ValueError):
            result.append({'path': str(path), 'phase': 'unreadable', 'error': 'Inspect this saved record before continuing'})
    return result


def _size(value):
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        return 'unknown'
    return f'{value / 1024**3:.1f} GiB'


def _rows(rows):
    for row in rows:
        if isinstance(row, dict):
            yield row
            yield from _rows(row.get('children') or [])


def show_status(result):
    from bromigos_storage_display import show_status as display
    display(result)


def show_plan(plan):
    print(f"{plan['id']} · {plan.get('kind', 'storage')}")
    print('Saved plan: ' + plan['path'])
    print('Planning has not formatted a disk, copied files or changed any mount.')
    if plan.get('kind') == 'cleanup':
        for item in plan['items']:
            print('  ' + item['kind'] + ': ' + json.dumps(item['path']))
        print(plan['note'])
        print('Apply this exact plan: sudo bromigos storage cleanup apply ' + shlex.quote(plan['path']))
        return
    # All plan fields are local storage metadata, never command stdout or credentials.
    print(json.dumps({key: value for key, value in plan.items() if key not in ('id', 'path', 'digest', 'created', 'schema')}, indent=2))


def _moves(args):
    if args.spec:
        if args.destination or args.keep_path:
            raise C.Error('--spec cannot be combined with individual move arguments')
        try:
            raw = tomllib.loads(Path(args.spec).expanduser().read_text())
        except (OSError, ValueError):
            raise C.Error('Cannot read the migration TOML specification') from None
        if set(raw) != {'move'} or not isinstance(raw['move'], list) or not raw['move']:
            raise C.Error('A migration specification needs one or more [[move]] tables')
        return raw['move']
    if not args.destination:
        raise C.Error('--source needs --destination')
    move = {'source': args.source, 'destination': args.destination}
    if args.keep_path:
        move['keep_path'] = args.keep_path
    return [move]


def main(argv=None):
    parser = argparse.ArgumentParser(prog='bromigos storage', description='Local drive inventory, reviewed provisioning and verified data migration')
    commands = parser.add_subparsers(dest='verb')
    status = commands.add_parser('status', help='Read drives, mounts, free space and saved operation state')
    status.add_argument('--json', action='store_true')
    planning = commands.add_parser('plan', help='Save a provisioning plan; no formatting')
    planning.add_argument('--device', required=True, help='Stable /dev/disk/by-id/ whole-disk path')
    planning.add_argument('--mount', required=True, help='Empty absolute mount point')
    planning.add_argument('--roles', default='development,games,downloads,vms,models', help='Comma-separated Btrfs storage roles')
    planning.add_argument('--json', action='store_true')
    applying = commands.add_parser('apply', help='Interactively apply a saved provisioning plan as root')
    applying.add_argument('plan', help='Plan ID or absolute plan path; use the path with sudo')
    switching = commands.add_parser('switch', help='Final copy, verification and separate path switch as root')
    switching.add_argument('plan')
    switching.add_argument('--writers-stopped', action='store_true', help='Confirm apps and VMs were stopped; active paths are checked again')
    cleanup = commands.add_parser('cleanup', help='Preview storage or plan and apply explicit retained-copy/snapshot cleanup')
    cleanup.add_argument('--preview', action='store_true', help='Read only; this is also the default')
    cleanup.add_argument('--json', action='store_true')
    cleaning = cleanup.add_subparsers(dest='cleanup_action')
    clean_plan = cleaning.add_parser('plan', help='Save exact retired originals or snapshot paths; no deletion')
    clean_plan.add_argument('--migration', help='Completed migration plan with switched paths')
    clean_plan.add_argument('--snapshot', action='append', default=[], help='Exact local snapshot path from preview; repeat to select several')
    clean_plan.add_argument('--json', action='store_true')
    clean_apply = cleaning.add_parser('apply', help='Verify and remove only the items in a saved cleanup plan')
    clean_apply.add_argument('plan')
    clean_apply.add_argument('--yes', action='store_true', help='Apply the exact reviewed plan without a confirmation prompt')
    clean_status = cleaning.add_parser('status', help='Read a cleanup plan, log path, completed items and measured free space')
    clean_status.add_argument('plan')
    clean_status.add_argument('--json', action='store_true')
    migration = commands.add_parser('migrate', help='Plan, stage, resume and verify data copies')
    moving = migration.add_subparsers(dest='action', required=True)
    move_plan = moving.add_parser('plan', help='Save individual or batch moves without copying')
    source = move_plan.add_mutually_exclusive_group(required=True)
    source.add_argument('--source')
    source.add_argument('--spec', help='TOML file containing [[move]] tables')
    move_plan.add_argument('--destination')
    move_plan.add_argument('--keep-path', help='Existing path to preserve with a bind mount at switch time')
    move_plan.add_argument('--json', action='store_true')
    for action in ('run', 'resume', 'verify'):
        item = moving.add_parser(action, help={'run': 'Stage a copy, preserving originals', 'resume': 'Continue an interrupted copy', 'verify': 'Checksum-verify the staged copy'}[action])
        item.add_argument('plan')
    move_status = moving.add_parser('status', help='Read saved plan and execution records')
    move_status.add_argument('plan', nargs='?')
    move_status.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.verb in (None, 'status'):
            import bromigos_storage_inventory as inventory
            result = dict(inventory.status(), operations=records())
            print(json.dumps(result, indent=2)) if getattr(args, 'json', False) else show_status(result)
        elif args.verb == 'cleanup':
            import bromigos_storage_cleanup as cleaning
            import bromigos_storage_display as display
            if args.preview and args.cleanup_action:
                raise C.Error('--preview cannot be combined with a cleanup action')
            if args.cleanup_action == 'plan':
                record = cleaning.plan(args.migration, args.snapshot)
                print(json.dumps(record, indent=2)) if args.json else show_plan(record)
            elif args.cleanup_action == 'apply':
                result = cleaning.apply(args.plan, yes=args.yes)
                display.show_cleanup_result(result)
            elif args.cleanup_action == 'status':
                record = C.read(args.plan)
                if record.get('kind') != 'cleanup':
                    raise C.Error('Use a saved cleanup plan')
                result = {'plan': record, 'journal': C.read_journal(record)}
                if args.json:
                    print(json.dumps(result, indent=2))
                elif result['journal']:
                    display.show_cleanup_result(result['journal'])
                else:
                    show_plan(record)
            else:
                import bromigos_storage_inventory as inventory
                result = inventory.cleanup_preview()
                print(json.dumps(result, indent=2)) if args.json else display.show_cleanup(result)
        elif args.verb in ('plan', 'apply'):
            import bromigos_storage_provision as provision
            if args.verb == 'plan':
                record = provision.plan(args.device, args.mount, [role.strip() for role in args.roles.split(',')])
                print(json.dumps(record, indent=2)) if args.json else show_plan(record)
            else:
                result = provision.apply(args.plan)
                print(json.dumps(result, indent=2))
        else:
            import bromigos_storage_migration as migration
            if args.verb == 'switch':
                print(json.dumps(migration.switch(args.plan, writers_stopped=args.writers_stopped), indent=2))
            elif args.action == 'plan':
                record = migration.plan(_moves(args))
                print(json.dumps(record, indent=2)) if args.json else show_plan(record)
            elif args.action == 'status':
                if args.plan:
                    plan = C.read(args.plan)
                    if plan.get('kind') != 'migration':
                        raise C.Error('This is not a migration plan')
                    result = {'plan': plan, 'journal': C.read_journal(plan)}
                else:
                    result = [record for record in records() if record.get('kind') == 'migration']
                print(json.dumps(result, indent=2))
            else:
                result = migration.verify(args.plan) if args.action == 'verify' else migration.run(args.plan, resume=args.action == 'resume')
                print(json.dumps(result, indent=2))
        return 0
    except (C.Error, OSError, ValueError, KeyError, TypeError) as error:
        message = str(error) if isinstance(error, C.Error) else 'Storage input or a saved record is invalid or unavailable'
        print('Storage stopped: ' + message, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('Storage interrupted. Inspect the saved operation before continuing; do not repeat provisioning or a path switch blindly.', file=sys.stderr)
        return 130
