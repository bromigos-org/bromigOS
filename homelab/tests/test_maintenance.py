"""Maintenance approval and recovery boundaries; fake subprocesses only."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from bromigos_homelab import maintenance as M


class Maintenance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = {}
        self.env = mock.patch.dict(os.environ, {'BROMIGOS_LAB_STATE': str(self.root / 'state')})
        self.config = mock.patch.object(M.config, 'table', side_effect=lambda _: self.settings)
        self.env.start(); self.config.start()
        self.out, self.err = io.StringIO(), io.StringIO()
        self.stdout = contextlib.redirect_stdout(self.out); self.stderr = contextlib.redirect_stderr(self.err)
        self.stdout.__enter__(); self.stderr.__enter__()

    def tearDown(self):
        self.stderr.__exit__(None, None, None); self.stdout.__exit__(None, None, None)
        self.config.stop(); self.env.stop(); self.tmp.cleanup()

    def profile(self, steps=None):
        self.settings['profile'] = {'name': 'Example rack', 'steps': {'shutdown': steps or [M._manual('power', 'Confirm equipment state', 'Inspect the equipment yourself.')]}}
        return self.settings['profile']

    def answers(self, record, stop=None):
        values = ['yes']
        for step in record['steps']:
            if step['kind'] == 'manual':
                values.append('' if step['id'] == stop else 'done ' + step['id'])
                if step['id'] == stop:
                    break
        return mock.patch('builtins.input', side_effect=values)

    def automated(self):
        repo = self.root / 'repo'; repo.mkdir()
        (repo / 'inventory.ini').write_text('[workers]\nworker.example.org\n')
        (repo / 'stop.yml').write_text('---\n- hosts: workers\n  tasks: []\n')
        self.profile([dict(id='runbook', title='Reviewed stop', detail='Use the reviewed playbook.', kind='ansible', playbook='stop.yml', timeout=12), M._manual('later', 'Later checkpoint', 'Must not run after failure.')])
        self.settings['profile'].update(repo=str(repo), inventory='inventory.ini', context='test-context')
        self.git = mock.patch.object(M, '_git', side_effect=lambda repo_, args: str(repo) if args == ['rev-parse', '--show-toplevel'] else ('' if args == ['status', '--porcelain'] else 'a' * 40))
        self.git.start(); self.addCleanup(self.git.stop)
        return repo

    def test_default_plan_and_status_never_execute_host_commands(self):
        with mock.patch.object(M.subprocess, 'run') as run:
            self.assertEqual(M.main(['plan', 'shutdown', '--json']), 0)
            record = json.loads(self.out.getvalue())
            self.assertEqual(record['state'], 'planned')
            self.assertEqual(record['equipment_state'], 'not verified')
            self.assertTrue(all(step['kind'] == 'manual' for step in record['steps']))
            self.assertIn('checkpoint-backups', [step['id'] for step in record['steps']])
            self.assertEqual(M.status()['runs'], [])
            run.assert_not_called()
        self.assertEqual(stat.S_IMODE(M._path('plans', record['id']).stat().st_mode), 0o600)

    def test_invalid_mode_is_refused_by_api(self):
        with self.assertRaises(M.MaintenanceError):
            M.plan('reboot')

    def test_a_plan_cannot_be_run_twice_in_any_execution_state(self):
        self.profile()
        for state in ('paused', 'completed', 'stopped'):
            record = M.plan('shutdown')
            journal = {'id': 'run-' + 'a' * 16, 'plan_id': record['id'], 'mode': 'shutdown', 'created': M._now(), 'state': state,
                       'steps': [{'id': 'runbook', 'state': 'unknown'}] if state == 'stopped' else []}
            M._write(M._path('runs', journal['id']), journal)
            with mock.patch.object(M, '_runbook') as run, mock.patch('builtins.input') as prompt:
                with self.assertRaisesRegex(M.MaintenanceError, 'already has an execution'):
                    M.execute(record['id'], approved=True)
                run.assert_not_called(); prompt.assert_not_called()

    def test_eof_at_manual_checkpoint_pauses_without_acknowledging(self):
        self.profile(); record = M.plan('shutdown')
        with mock.patch.object(M.sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', side_effect=['yes', EOFError()]):
            with self.assertRaises(EOFError):
                M.execute(record['id'])
        journal = M._read('runs', M.status()['runs'][0]['id'])
        self.assertEqual(journal['state'], 'paused')
        self.assertEqual(journal['steps'], [])

    def test_rejected_approval_has_no_journal_or_runbooks(self):
        self.profile(); record = M.plan('shutdown')
        with mock.patch.object(M.sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', return_value='no'), mock.patch.object(M, '_runbook') as run:
            self.assertIsNone(M.execute(record['id']))
            run.assert_not_called()
        self.assertEqual(M.status()['runs'], [])

    def test_yes_never_bypasses_manual_confirmations(self):
        self.profile(); record = M.plan('shutdown')
        with mock.patch.object(M.sys.stdin, 'isatty', return_value=False), mock.patch.object(M, '_runbook') as run:
            with self.assertRaisesRegex(M.MaintenanceError, 'interactive terminal'):
                M.execute(record['id'], approved=True)
            run.assert_not_called()
        self.assertEqual(M.status()['runs'], [])

    def test_pause_resume_keeps_acknowledgements_without_replaying(self):
        self.profile(); record = M.plan('shutdown')
        with mock.patch.object(M.sys.stdin, 'isatty', return_value=True), self.answers(record, stop='power'):
            journal = M.execute(record['id'])
        self.assertEqual(journal['state'], 'paused')
        self.assertEqual(len(journal['steps']), 3)
        remaining = ['yes', 'done power', 'done checkpoint-record']
        with mock.patch.object(M.sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', side_effect=remaining) as prompt:
            completed = M.execute(journal['id'], resume=True)
        self.assertEqual(prompt.call_count, 3)
        self.assertEqual(completed['state'], 'completed')
        self.assertEqual(completed['equipment_state'], 'not verified')
        self.assertTrue(all(step['evidence'] == 'recorded operator confirmation' for step in completed['steps']))
        self.assertEqual(stat.S_IMODE(M._path('runs', completed['id']).stat().st_mode), 0o600)

    def test_changed_profile_or_plan_requires_new_review(self):
        self.profile(); record = M.plan('shutdown')
        self.settings['profile']['name'] = 'Changed'
        with mock.patch('builtins.input') as prompt, self.assertRaisesRegex(M.MaintenanceError, 'changed'):
            M.execute(record['id'])
        prompt.assert_not_called()
        record = M.plan('shutdown'); record['steps'][0]['title'] = 'Changed checkpoint'
        M._write(M._path('plans', record['id']), record)
        with self.assertRaisesRegex(M.MaintenanceError, 'saved plan changed'):
            M.execute(record['id'])

    def test_profile_file_relative_repository_and_digest(self):
        profile = self.root / 'maintenance.toml'
        profile.write_text('name="Example rack"\nrepo="."\ncontext="test-context"\n')
        record = M.plan('startup', profile_file=str(profile))
        loaded, _ = M.load_profile(profile_file=str(profile))
        self.assertEqual(loaded['repo'], str(self.root))
        profile.write_text(profile.read_text() + '# changed\n')
        with self.assertRaisesRegex(M.MaintenanceError, 'changed'):
            M.execute(record['id'])

    def test_untrusted_paths_and_dirty_repository_prevent_runbooks(self):
        repo = self.automated()
        original = M._git
        with mock.patch.object(M, '_git', side_effect=lambda root, args: ' M stop.yml' if args == ['status', '--porcelain'] else original(root, args)), self.assertRaisesRegex(M.MaintenanceError, 'Commit or save'):
            M.plan('shutdown')
        self.settings['profile']['steps']['shutdown'][0]['playbook'] = '../outside.yml'
        with self.assertRaisesRegex(M.MaintenanceError, 'outside'):
            M.plan('shutdown')
        outside = self.root / 'outside.yml'; outside.write_text('private')
        (repo / 'link.yml').symlink_to(outside)
        self.settings['profile']['steps']['shutdown'][0]['playbook'] = 'link.yml'
        with self.assertRaisesRegex(M.MaintenanceError, 'outside'):
            M.plan('shutdown')

    def test_changed_runbook_and_head_refuse_execution(self):
        repo = self.automated(); record = M.plan('shutdown')
        (repo / 'stop.yml').write_text('changed')
        with mock.patch('builtins.input') as prompt, self.assertRaisesRegex(M.MaintenanceError, 'changed'):
            M.execute(record['id'])
        prompt.assert_not_called()
        record = M.plan('shutdown')
        original = M._git
        with mock.patch.object(M, '_git', side_effect=lambda root, args: 'b' * 40 if args == ['rev-parse', 'HEAD'] else original(root, args)), self.assertRaisesRegex(M.MaintenanceError, 'changed'):
            M.execute(record['id'])

    def test_timeout_records_unknown_and_resume_never_repeats(self):
        self.automated(); record = M.plan('shutdown')
        answers = ['yes'] + ['done ' + step['id'] for step in record['steps'] if step['kind'] == 'manual']
        with mock.patch.object(M.sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', side_effect=answers), mock.patch.object(M.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ansible', 12)) as run:
            with self.assertRaisesRegex(M.MaintenanceError, 'unknown'):
                M.execute(record['id'])
        self.assertEqual(run.call_count, 1)
        journal = M._read('runs', M.status()['runs'][0]['id'])
        self.assertEqual(journal['steps'][-1]['state'], 'unknown')
        self.assertFalse(any(step['id'] == 'later' for step in journal['steps']))
        with mock.patch.object(M, '_runbook') as run, self.assertRaisesRegex(M.MaintenanceError, 'uncertain'):
            M.execute(journal['id'], resume=True)
        run.assert_not_called()

    def test_runbook_arguments_and_failure_output_remain_private(self):
        repo = self.automated(); profile = self.settings['profile']; step = profile['steps']['shutdown'][0]
        with mock.patch.object(M.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stdout='TEST-SECRET', stderr='TEST-SECRET')) as run:
            with self.assertRaises(M.MaintenanceError) as caught:
                M._runbook(profile, step)
        self.assertNotIn('TEST-SECRET', str(caught.exception))
        args, kwargs = run.call_args
        self.assertEqual(args[0], ['ansible-playbook', '-i', str(repo / 'inventory.ini'), str(repo / 'stop.yml')])
        self.assertEqual(kwargs['env']['BROMIGOS_KUBE_CONTEXT'], 'test-context')
        self.assertEqual(kwargs['env']['ANSIBLE_HOST_KEY_CHECKING'], 'True')
        self.assertEqual(kwargs['timeout'], 12)
        self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)

    def test_exclusive_lock_blocks_second_execution(self):
        self.profile(); record = M.plan('shutdown')
        with M._lock(), self.assertRaisesRegex(M.MaintenanceError, 'already running'):
            M.execute(record['id'])

    def test_check_uses_read_only_doctor_and_never_claims_off(self):
        from bromigos_homelab import doctor
        findings = {'findings': [{'status': 'fail', 'title': 'Unreachable', 'detail': 'No connection'}], 'summary': {'fail': 1}}
        with mock.patch.object(doctor, 'run', return_value=findings) as check, mock.patch.object(M, '_runbook') as run:
            self.assertEqual(M.main(['check', '--json']), 0)
            check.assert_called_once_with(); run.assert_not_called()
        output = json.loads(self.out.getvalue())
        self.assertIn('do not verify', output['note'])
        self.assertEqual(output['summary']['fail'], 1)
        self.assertEqual(output['findings'][0]['title'], 'Unreachable')
        self.out.seek(0); self.out.truncate()
        with mock.patch.object(doctor, 'run', return_value=findings):
            self.assertEqual(M.main(['check']), 0)
        self.assertIn('1 fail', self.out.getvalue())
        self.assertIn('Unreachable: No connection', self.out.getvalue())
