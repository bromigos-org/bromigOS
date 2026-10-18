"""Read UniFi PDU measurements; review private Ansible outlet-control plans."""
import argparse
import json
import math
from pathlib import Path
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

from . import config, maintenance as M

SUPPORTED_MODELS = {'USPPDUP', 'USP-PDU-Pro'}


class PowerError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _boolean(value):
    if value is True or value == 1 or value == 'true':
        return True
    if value is False or value == 0 or value == 'false':
        return False
    return None


def _capability(outlet, name, bit):
    if name in outlet:
        return _boolean(outlet[name])
    caps = outlet.get('outlet_caps')
    if isinstance(caps, int) and not isinstance(caps, bool):
        return bool(caps & bit)
    return None


def _fetch(settings):
    endpoint = settings.get('endpoint')
    if not isinstance(endpoint, str):
        raise PowerError('Configure an HTTPS controller endpoint')
    try:
        url = urllib.parse.urlsplit(endpoint)
        valid = url.scheme == 'https' and url.hostname and not url.username and not url.password and not url.query and not url.fragment and url.path in ('', '/')
        _ = url.port
    except ValueError:
        valid = False
    if not valid:
        raise PowerError('Use a bare HTTPS controller origin without credentials, a path, query or fragment')
    site = settings.get('site', 'default')
    if not isinstance(site, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', site):
        raise PowerError('Configure a valid UniFi site name')
    token = config.resolve(settings.get('auth_ref', ''))
    if not isinstance(token, str) or not token.strip() or '\n' in token or '\r' in token:
        raise PowerError('Configure the controller API-key reference before reading power measurements')
    ca = settings.get('tls_ca')
    try:
        context = ssl.create_default_context(cafile=str(Path(ca).expanduser()) if ca else None)
        opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=context))
        request = urllib.request.Request(endpoint.rstrip('/') + '/proxy/network/api/s/' + site + '/stat/device', headers={'X-API-Key': token, 'Accept': 'application/json'}, method='GET')
        with opener.open(request, timeout=8) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise PowerError('Controller power response exceeded the supported size')
        payload = json.loads(raw)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise PowerError('Controller refused API-key access; check its permissions and API compatibility') from None
        raise PowerError('Controller power request failed; redirects and alternate endpoints are not followed') from None
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        raise PowerError('Cannot read controller power measurements; check connectivity, the trusted CA and API compatibility') from None
    if not isinstance(payload, dict) or not isinstance(payload.get('meta', {}), dict) or payload.get('meta', {}).get('rc') not in (None, 'ok') or not isinstance(payload.get('data'), list):
        raise PowerError('Controller returned an unsupported device response')
    return payload['data']


def _parse_device(device):
    raw_outlets = device.get('outlet_table')
    if not isinstance(raw_outlets, list):
        raise PowerError('Selected PDU has no supported outlet measurements yet')
    connected = device.get('state') == 1 and not isinstance(device.get('state'), bool)
    outlets, seen = [], set()
    for outlet in raw_outlets:
        if not isinstance(outlet, dict):
            raise PowerError('PDU returned an invalid outlet table')
        index = outlet.get('index')
        if type(index) is not int or index < 1 or index in seen:
            raise PowerError('PDU returned invalid or duplicate outlet indices')
        seen.add(index)
        metering = _capability(outlet, 'has_metering', 2)
        outlets.append(dict(index=index, name=str(outlet.get('name') or f'Outlet {index}'), relay_state=_boolean(outlet.get('relay_state')) if connected else None, has_relay=_capability(outlet, 'has_relay', 1), has_metering=metering,
                            power_w=_number(outlet.get('outlet_power')) if metering is not False and connected else None,
                            current_a=_number(outlet.get('outlet_current')) if metering is not False and connected else None,
                            voltage_v=_number(outlet.get('outlet_voltage')) if metering is not False and connected else None))
    reported = _number(device.get('outlet_ac_power_consumption')) if connected else None
    return dict(id=str(device.get('_id') or ''), name=str(device.get('name') or 'PDU'), model=device['model'], controller_device_state=device.get('state') if type(device.get('state')) is int else None, connected=connected, total_power_w=reported, outlets=sorted(outlets, key=lambda row: row['index']))


def status():
    settings = config.table('power')
    if not settings.get('endpoint'):
        return dict(state='not configured', device=None, note='Configure a supported PDU after installation and adoption. No hardware has been checked.')
    devices = [device for device in _fetch(settings) if isinstance(device, dict) and device.get('model') in SUPPORTED_MODELS]
    selected = settings.get('device_id')
    if selected:
        devices = [device for device in devices if device.get('_id') == selected]
    if not devices:
        return dict(state='not found', device=None, note='No selected supported PDU was reported. Missing connectivity or measurements do not mean equipment is powered off.')
    if len(devices) != 1:
        raise PowerError('More than one supported PDU was reported; configure its exact device_id before reading measurements')
    device = _parse_device(devices[0])
    if not device['connected']:
        return dict(state='unavailable', device=device, note='The selected PDU is not reported connected. Stored readings and relay states are withheld; missing connectivity does not mean equipment is powered off.')
    return dict(state='reported', device=device, note='Controller-reported outlet state and measurements; these do not verify operating-system shutdown or service readiness. A shared outlet measures its whole attached load.')


def _target(alias, action):
    if not isinstance(alias, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', alias):
        raise PowerError('Use a configured short lower-case target alias')
    if action not in ('on', 'off'):
        raise PowerError('Choose on or off')
    targets = config.table('power').get('targets', {})
    target = targets.get(alias) if isinstance(targets, dict) else None
    if not isinstance(target, dict) or set(target) - {'profile_file', 'on_profile_file', 'off_profile_file'}:
        raise PowerError('Configure that target with a private reviewed maintenance profile')
    filename = target.get(action + '_profile_file') or target.get('profile_file')
    if not isinstance(filename, str) or not filename:
        raise PowerError('No reviewed maintenance profile is configured for that target and action')
    return target, str(Path(filename).expanduser().resolve())


def _check_profile(alias, action, filename):
    profile, _ = M.load_profile(profile_file=filename)
    mode = 'shutdown' if action == 'off' else 'startup'
    steps = M._steps(profile, mode)
    first_control = next((index for index, step in enumerate(steps) if step['kind'] == 'ansible'), None)
    if first_control is None:
        raise PowerError('This target has no reviewed Ansible control steps; configure them after hardware commissioning')
    required = ('power-target', 'power-clean-shutdown') if action == 'off' else ('power-target',)
    for ident in required:
        step = next((step for step in steps if step['id'] == ident and step['kind'] == 'manual'), None)
        if not step:
            raise PowerError('The reviewed power profile needs a manual ' + ident + ' checkpoint')
        if steps.index(step) >= first_control:
            raise PowerError('The manual ' + ident + ' checkpoint must come before every Ansible control step')
        if ident == 'power-target' and not re.search(r'(?<![a-z0-9-])' + re.escape(alias) + r'(?![a-z0-9-])', (step['title'] + ' ' + step['detail']).lower()):
            raise PowerError('The power-target checkpoint must explicitly name the configured target alias')
    return mode


def plan(alias, action):
    target, filename = _target(alias, action)
    mode = _check_profile(alias, action, filename)
    record = M.plan(mode, profile_file=filename)
    record['power'] = dict(target=alias, action=action, target_digest=M._digest(target))
    record.pop('digest')
    record['digest'] = M._digest(record)
    M._write(M._path('plans', record['id']), record)
    return record


def execute(ident, resume=False):
    journal = M._read('runs', ident) if resume else None
    record = M._read('plans', journal['plan_id'] if journal else ident)
    metadata = record.get('power')
    if not isinstance(metadata, dict) or set(metadata) != {'target', 'action', 'target_digest'}:
        raise PowerError('Use a plan created by power plan; generic maintenance plans cannot control a power target here')
    target, filename = _target(metadata['target'], metadata['action'])
    if metadata['target_digest'] != M._digest(target) or filename != record.get('origin', {}).get('profile_file'):
        raise PowerError('The configured power target changed; inspect the equipment and review a new plan')
    _check_profile(metadata['target'], metadata['action'], filename)
    M._validated(record)
    print(f"Power target: {metadata['target']} · requested state: {metadata['action']}")
    print('Outlet power removal is not a graceful shutdown. Complete every named manual checkpoint first.')
    return M.execute(ident, resume=resume)


def _display_status(result):
    print('Power monitoring: ' + result['state'])
    print(result['note'])
    device = result['device']
    if device is None:
        return
    def number(value, unit):
        return 'unknown' if value is None else f'{value:g} {unit}'
    print(f"{device['name']} ({device['model']}) · total: {number(device['total_power_w'], 'W')}")
    for outlet in device['outlets']:
        relay = 'unknown' if outlet['relay_state'] is None else ('on' if outlet['relay_state'] else 'off')
        print(f"{outlet['index']}. {outlet['name']} · relay {relay} · {number(outlet['power_w'], 'W')} · {number(outlet['current_a'], 'A')} · {number(outlet['voltage_v'], 'V')}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog='bromigos lab power', description='Read PDU outlet measurements and review explicitly configured Ansible power controls')
    sub = parser.add_subparsers(dest='verb')
    reading = sub.add_parser('status', help='Read a configured controller; missing values stay unknown')
    reading.add_argument('--json', action='store_true')
    planning = sub.add_parser('plan', help='Review named outlet-control runbooks without changing power')
    planning.add_argument('target')
    planning.add_argument('action', choices=('on', 'off'))
    planning.add_argument('--json', action='store_true')
    for verb in ('run', 'resume'):
        command = sub.add_parser(verb, help='Interactively approve a saved power plan or continue a paused run')
        command.add_argument('id')
    args = parser.parse_args(argv)
    try:
        if args.verb == 'plan':
            record = plan(args.target, args.action)
            if args.json:
                print(json.dumps(record, indent=2))
            else:
                print(f"Power target: {args.target} · requested state: {args.action}")
                M.render(record)
        elif args.verb in ('run', 'resume'):
            execute(args.id, resume=args.verb == 'resume')
        else:
            result = status()
            print(json.dumps(result, indent=2)) if getattr(args, 'json', False) else _display_status(result)
        return 0
    except (PowerError, M.MaintenanceError) as error:
        print('Power command stopped: ' + str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print('Power command stopped: invalid or unavailable power configuration or saved record', file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('Power command interrupted. Inspect the maintenance journal; equipment state is not verified.', file=sys.stderr)
        return 130
