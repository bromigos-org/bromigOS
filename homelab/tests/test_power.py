"""PDU measurements and approval boundaries against fake controller data only."""
import contextlib
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest import mock
import urllib.error

from bromigos_homelab import power as P, maintenance as M


def device(**changes):
    value = dict(_id='pdu-example', model='USPPDUP', name='Example PDU', state=1, outlet_ac_power_consumption='85.5',
                 outlet_table=[dict(index=1, name='Example compute', outlet_caps=3, relay_state=True, outlet_power='85.5', outlet_current='0.71', outlet_voltage='120.2'),
                               dict(index=2, name='USB', outlet_caps=1, relay_state=False)])
    value.update(changes)
    return value


class Power(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.settings = {}
        self.config = mock.patch.object(P.config, 'table', side_effect=lambda name: self.settings if name == 'power' else {})
        self.env = mock.patch.dict(os.environ, {'BROMIGOS_LAB_STATE': str(self.root / 'state')})
        self.config.start(); self.env.start()
        self.out, self.err = io.StringIO(), io.StringIO()
        self.stdout, self.stderr = contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.err)
        self.stdout.__enter__(); self.stderr.__enter__()

    def tearDown(self):
        self.stderr.__exit__(None, None, None); self.stdout.__exit__(None, None, None)
        self.env.stop(); self.config.stop(); self.tmp.cleanup()

    def configured(self):
        self.settings.update(endpoint='https://console.example.org', auth_ref='EXAMPLE-KEY', site='default')

    def control_profile(self, action='off', steps=None):
        repo = self.root / 'repo'; repo.mkdir(exist_ok=True)
        (repo / 'inventory.ini').write_text('[workers]\nworker.example.org\n')
        (repo / 'control.yml').write_text('---\n- hosts: workers\n  tasks: []\n')
        checkpoint = [dict(id='power-target', kind='manual', title='Inspect compute', detail='Confirm compute is the intended outlet target.')]
        if action == 'off':
            checkpoint.append(dict(id='power-clean-shutdown', kind='manual', title='Confirm clean shutdown', detail='Confirm the attached system has shut down cleanly.'))
        checkpoint.append(dict(id='outlet-control', kind='ansible', title='Run reviewed outlet control', detail='Use the private reviewed runbook.', playbook='control.yml'))
        mode = 'shutdown' if action == 'off' else 'startup'
        path = repo / 'power.toml'
        content = f'repo="."\ninventory="inventory.ini"\ncontext="test-context"\n'
        for step in (steps if steps is not None else checkpoint):
            content += f'\n[[steps.{mode}]]\n' + '\n'.join(f'{key}={json.dumps(value)}' for key, value in step.items()) + '\n'
        path.write_text(content)
        self.settings['targets'] = {'compute': {'profile_file': str(path)}}
        git = mock.patch.object(M, '_git', side_effect=lambda root, args: str(repo) if args == ['rev-parse', '--show-toplevel'] else ('' if args == ['status', '--porcelain'] else 'a' * 40))
        git.start(); self.addCleanup(git.stop)
        return path

    def test_unconfigured_status_makes_no_network_request(self):
        with mock.patch.object(P, '_fetch') as fetch:
            self.assertEqual(P.main(['status', '--json']), 0)
            self.assertEqual(json.loads(self.out.getvalue())['state'], 'not configured')
            fetch.assert_not_called()

    def test_metering_values_zero_unknown_and_relay_are_distinct(self):
        self.configured()
        first = device()
        first['outlet_table'] += [dict(index=3, name='Zero load', has_metering=True, has_relay=True, relay_state=True, outlet_power=0),
                                  dict(index=4, name='Missing readings', outlet_caps=3, relay_state='false', outlet_power='NaN', outlet_current='inf', outlet_voltage=-1)]
        with mock.patch.object(P, '_fetch', return_value=[first]):
            result = P.status()
        self.assertEqual(result['state'], 'reported')
        self.assertEqual(result['device']['total_power_w'], 85.5)
        rows = result['device']['outlets']
        self.assertEqual((rows[0]['power_w'], rows[0]['current_a'], rows[0]['voltage_v']), (85.5, 0.71, 120.2))
        self.assertIsNone(rows[1]['power_w']); self.assertFalse(rows[1]['has_metering'])
        self.assertEqual(rows[2]['power_w'], 0)
        self.assertIsNone(rows[3]['power_w']); self.assertIsNone(rows[3]['current_a']); self.assertIsNone(rows[3]['voltage_v'])
        self.assertFalse(rows[3]['relay_state'])
        self.assertIsNone(P._number(True))

    def test_offline_controller_cache_never_reports_equipment_off(self):
        self.configured()
        cached = device(state=0, outlet_ac_power_consumption=0)
        cached['outlet_table'][0].update(relay_state=False, outlet_power=0)
        with mock.patch.object(P, '_fetch', return_value=[cached]):
            result = P.status()
        self.assertEqual(result['state'], 'unavailable')
        self.assertFalse(result['device']['connected'])
        self.assertIsNone(result['device']['total_power_w'])
        self.assertTrue(all(row['relay_state'] is None and row['power_w'] is None for row in result['device']['outlets']))

    def test_multiple_devices_require_exact_selector(self):
        self.configured()
        with mock.patch.object(P, '_fetch', return_value=[device(), device(_id='second')]):
            with self.assertRaisesRegex(P.PowerError, 'device_id'):
                P.status()
            self.settings['device_id'] = 'second'
            self.assertEqual(P.status()['device']['id'], 'second')
            self.settings['device_id'] = 'absent'
            self.assertEqual(P.status()['state'], 'not found')

    def test_unsupported_models_and_bad_outlet_indices_are_rejected(self):
        self.configured()
        with mock.patch.object(P, '_fetch', return_value=[device(model='UP6')]):
            self.assertEqual(P.status()['state'], 'not found')
        for outlets in ([dict(index=1), dict(index=1)], [dict(index=True)], [dict(index=-1)]):
            with self.subTest(outlets=outlets), self.assertRaises(P.PowerError):
                P._parse_device(device(outlet_table=outlets))

    def test_https_key_and_ca_request_never_writes_or_follows_redirects(self):
        self.configured()
        response = mock.MagicMock(); response.__enter__.return_value.read.return_value = json.dumps({'meta': {'rc': 'ok'}, 'data': [device()]}).encode()
        opener = mock.Mock(); opener.open.return_value = response
        with mock.patch.object(P.urllib.request, 'build_opener', return_value=opener) as build:
            P._fetch(self.settings)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, 'GET')
        self.assertEqual(request.full_url, 'https://console.example.org/proxy/network/api/s/default/stat/device')
        self.assertEqual(request.get_header('X-api-key'), 'EXAMPLE-KEY')
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 8)
        handler = build.call_args.args[1]
        self.assertEqual(handler._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(handler._context.check_hostname)
        self.assertIsNone(P._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example.org'))

    def test_invalid_endpoints_and_controller_errors_do_not_leak_credentials(self):
        self.configured()
        for endpoint in ('http://console.example.org', 'https://user:SECRET@console.example.org', 'https://console.example.org/path', 'https://console.example.org/?secret=SECRET'):
            self.settings['endpoint'] = endpoint
            with mock.patch.object(P.urllib.request, 'build_opener') as opener, self.assertRaises(P.PowerError) as error:
                P._fetch(self.settings)
            self.assertNotIn('SECRET', str(error.exception)); opener.assert_not_called()
        self.settings['endpoint'] = 'https://console.example.org'
        opener = mock.Mock(); opener.open.side_effect = urllib.error.URLError('SECRET https://private.invalid')
        with mock.patch.object(P.urllib.request, 'build_opener', return_value=opener), self.assertRaises(P.PowerError) as error:
            P._fetch(self.settings)
        self.assertNotIn('SECRET', str(error.exception)); self.assertNotIn('private.invalid', str(error.exception))

    def test_malformed_meta_is_a_sanitized_error(self):
        self.configured()
        for meta in (None, [], 'invalid'):
            response = mock.MagicMock(); response.__enter__.return_value.read.return_value = json.dumps({'meta': meta, 'data': []}).encode()
            opener = mock.Mock(); opener.open.return_value = response
            with mock.patch.object(P.urllib.request, 'build_opener', return_value=opener), self.assertRaisesRegex(P.PowerError, 'unsupported'):
                P._fetch(self.settings)

    def test_power_plan_binds_target_and_never_executes_control(self):
        self.control_profile()
        with mock.patch.object(M, '_runbook') as run:
            record = P.plan('compute', 'off')
        run.assert_not_called()
        self.assertEqual(record['power']['target'], 'compute')
        self.assertEqual(record['power']['action'], 'off')
        M._validated(record)
        self.assertEqual(M.status()['runs'], [])

    def test_required_checkpoints_must_precede_control(self):
        self.control_profile()
        profile, _ = M.load_profile(profile_file=self.settings['targets']['compute']['profile_file'])
        steps = profile['steps']['shutdown']
        for bad in ([steps[-1], *steps[:-1]], [steps[0], steps[-1], steps[1]], [steps[0], steps[-1]]):
            path = self.control_profile(steps=bad)
            with self.assertRaises(P.PowerError):
                P.plan('compute', 'off')
            self.assertEqual(M.status()['plans'], [])

    def test_manual_only_uncommissioned_profile_cannot_create_control_plan(self):
        self.control_profile(steps=[dict(id='power-target', kind='manual', title='Inspect compute', detail='Confirm compute.')])
        with self.assertRaisesRegex(P.PowerError, 'no reviewed Ansible'):
            P.plan('compute', 'off')

    def test_changed_target_and_generic_plan_cannot_execute_as_power(self):
        self.control_profile()
        record = P.plan('compute', 'off')
        self.settings['targets']['compute']['on_profile_file'] = '/changed/profile.toml'
        with mock.patch.object(M, 'execute') as run, self.assertRaisesRegex(P.PowerError, 'changed'):
            P.execute(record['id'])
        run.assert_not_called()
        generic = M.plan('startup')
        with mock.patch.object(M, 'execute') as run, self.assertRaisesRegex(P.PowerError, 'power plan'):
            P.execute(generic['id'])
        run.assert_not_called()

    def test_run_and_resume_delegate_only_bound_plan(self):
        self.control_profile(action='on')
        record = P.plan('compute', 'on')
        with mock.patch.object(M, 'execute', return_value={'state': 'paused'}) as run:
            P.execute(record['id'])
            run.assert_called_once_with(record['id'], resume=False)
        journal = dict(id='run-' + 'a' * 16, plan_id=record['id'])
        M._write(M._path('runs', journal['id']), journal)
        with mock.patch.object(M, 'execute') as run:
            P.execute(journal['id'], resume=True)
            run.assert_called_once_with(journal['id'], resume=True)

    def test_tampered_power_marker_is_rejected_before_execution(self):
        self.control_profile(); record = P.plan('compute', 'off')
        record['power']['action'] = 'on'
        M._write(M._path('plans', record['id']), record)
        with mock.patch.object(M, 'execute') as run, self.assertRaises((P.PowerError, M.MaintenanceError)):
            P.execute(record['id'])
        run.assert_not_called()
