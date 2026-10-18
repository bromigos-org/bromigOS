import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import bromigos_storage_common as C
import bromigos_storage as CLI


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'BROMIGOS_STORAGE_STATE': str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_private_immutable_plan_and_sudo_path(self):
        plan = C.store('plans', {'kind': 'migration', 'moves': []})
        self.assertEqual(Path(plan['path']).stat().st_mode & 0o777, 0o600)
        self.assertEqual(C.read(plan['id']), plan)
        with patch.object(C, 'state_dir', return_value=self.root / 'different-user'):
            self.assertEqual(C.read(plan['path']), plan)

    def test_plan_tampering_or_relocation_refused(self):
        plan = C.store('plans', {'kind': 'migration'})
        path = Path(plan['path'])
        moved = self.root / 'other.json'
        moved.write_bytes(path.read_bytes())
        with self.assertRaises(C.Error):
            C.read(str(moved))
        path.write_text(path.read_text().replace('migration', 'provision'))
        with self.assertRaises(C.Error):
            C.read(plan['id'])

    def test_plan_symlink_refused(self):
        plan = C.store('plans', {'kind': 'migration'})
        link = self.root / 'linked.json'
        link.symlink_to(plan['path'])
        with self.assertRaises(C.Error):
            C.read(str(link))

    def test_journal_bound_to_plan_and_state_visible(self):
        plan = C.store('plans', {'kind': 'migration'})
        self.assertIsNone(C.read_journal(plan))
        C.update_journal(plan, {'state': 'staged', 'originals_retained': True})
        self.assertEqual(CLI.records()[0]['phase'], 'staged')
        self.assertTrue(CLI.records()[0]['originals_retained'])
        other = dict(plan, digest='wrong')
        with self.assertRaises(C.Error):
            C.read_journal(other)

    def test_lock_excludes_second_operation(self):
        plan = C.store('plans', {'kind': 'migration'})
        with C.lock(plan):
            with self.assertRaises(C.Error):
                with C.lock(plan):
                    self.fail('lock unexpectedly acquired')

    def test_failed_commands_never_print_raw_output(self):
        fake = subprocess.CompletedProcess(['fixture'], 1, 'PRIVATE-OUTPUT', 'PRIVATE-ERROR')
        with patch.object(C.subprocess, 'run', return_value=fake):
            with self.assertRaises(C.Error) as error:
                C.command(['fixture'])
        self.assertNotIn('PRIVATE', str(error.exception))

    def test_cli_help_has_no_storage_commands(self):
        with patch.object(C.subprocess, 'run') as command, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                CLI.main(['--help'])
        self.assertEqual(error.exception.code, 0)
        command.assert_not_called()

    def test_batch_spec_rejects_extra_tables(self):
        spec = self.root / 'moves.toml'
        spec.write_text('[unexpected]\nvalue=true\n')
        args = type('Args', (), dict(spec=str(spec), source=None, destination=None, keep_path=None))()
        with self.assertRaises(C.Error):
            CLI._moves(args)

    def test_read_status_does_not_execute_pending_plan(self):
        C.store('plans', {'kind': 'provision'})
        with patch('bromigos_storage_inventory.status', return_value={'disks': [], 'mounts': [], 'free_space': [], 'errors': [], 'space_note': ''}), \
             patch.object(C.subprocess, 'run') as command, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(CLI.main(['status', '--json']), 0)
        command.assert_not_called()
        self.assertIn('planned', output.getvalue())


if __name__ == '__main__':
    unittest.main()
