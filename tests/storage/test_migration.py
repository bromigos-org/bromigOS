"""Migration lifecycle against temporary directories and fake command runners only."""
import contextlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import bromigos_storage_common as C
import bromigos_storage_migration as M


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.source_volume = self.root / 'source-volume'; self.source_volume.mkdir()
        self.destination_volume = self.root / 'destination-volume'; self.destination_volume.mkdir()
        self.source = self.source_volume / 'projects'; self.source.mkdir()
        (self.source / 'original.txt').write_text('original data')
        self.destination = self.destination_volume / 'projects'
        self.fstab = self.root / 'fstab'; self.fstab.write_text('# Existing mounts\n')
        self.calls = []
        self.bindings = {}
        self.real_identity = M._identity
        self.real_quiesced = M._quiesced
        self.patches = [mock.patch.dict(os.environ, {'BROMIGOS_STORAGE_STATE': str(self.root / 'state')}),
                        mock.patch.object(C, 'require_root'), mock.patch.object(C, 'lock', side_effect=lambda _: contextlib.nullcontext()),
                        mock.patch.object(C, 'command', side_effect=self.command), mock.patch.object(M, '_filesystem', side_effect=self.filesystem),
                        mock.patch.object(M, '_filesystems', return_value=[self.source_volume, self.destination_volume]),
                        mock.patch.object(M, 'FSTAB', self.fstab), mock.patch.object(M, '_quiesced'),
                        mock.patch('builtins.input', side_effect=lambda prompt: 'SWITCH ' + self.record['id'])]
        for patch in self.patches: patch.start()

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        self.tmp.cleanup()

    def filesystem(self, path):
        path = Path(path)
        for target, source in self.bindings.items():
            if path == target or path.is_relative_to(target):
                return dict(target=str(target), uuid='destination-uuid', fstype='btrfs', fsroot='/@data/' + source.name)
        if path.is_relative_to(self.destination_volume):
            return dict(target=str(self.destination_volume), uuid='destination-uuid', fstype='btrfs', fsroot='/@data')
        return dict(target=str(self.source_volume), uuid='source-uuid', fstype='ext4', fsroot='/')

    def command(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[0] == 'rsync':
            source, destination = map(Path, argv[-2:])
            if '--dry-run' in argv:
                left = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob('*') if path.is_file()}
                right = {str(path.relative_to(destination)): path.read_bytes() for path in destination.rglob('*') if path.is_file()}
                return '' if left == right else '>f+++++++++\n'
            for path in source.rglob('*'):
                target = destination / path.relative_to(source)
                if path.is_dir(): target.mkdir(exist_ok=True)
                elif path.is_file(): shutil.copy2(path, target)
            return ''
        if argv[0] == 'mount':
            target = Path(argv[-1]); self.bindings[target] = self.destination
        return ''

    def make_plan(self, **extra):
        self.record = M.plan([dict(source=str(self.source), destination=str(self.destination), **extra)])
        return self.record

    def test_plan_only_records_identity_and_never_copies(self):
        record = self.make_plan()
        self.assertEqual(record['moves'][0]['source_identity'], self.real_identity(self.source))
        self.assertEqual(record['moves'][0]['destination_filesystem']['uuid'], 'destination-uuid')
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.calls, [])
        self.assertEqual(Path(record['path']).stat().st_mode & 0o777, 0o600)

    def test_overlap_alias_symlink_and_nonempty_destination_are_rejected(self):
        for destination in (self.source, self.source / 'nested'):
            with self.assertRaises(C.Error): M.plan([dict(source=str(self.source), destination=str(destination))])
        alias = self.source_volume / 'alias'; alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(C.Error): M.plan([dict(source=str(alias), destination=str(self.destination))])
        self.destination.mkdir(); (self.destination / 'unrelated').write_text('keep')
        with self.assertRaises(C.Error): self.make_plan()
        self.assertEqual((self.destination / 'unrelated').read_text(), 'keep')

    def test_batch_cross_move_overlap_and_nested_mount_are_rejected(self):
        (self.source / 'child').mkdir()
        with self.assertRaises(C.Error):
            M.plan([dict(source=str(self.source), destination=str(self.destination)), dict(source=str(self.source / 'child'), destination=str(self.destination_volume / 'other'))])
        with mock.patch.object(M, '_filesystems', return_value=[self.source / 'mounted-child']), self.assertRaisesRegex(C.Error, 'nested mount'):
            self.make_plan()

    def test_copy_is_staged_not_switched_and_resume_repeats_without_delete(self):
        record = self.make_plan()
        journal = M.run(record['id'])
        self.assertEqual(journal['state'], 'staged')
        self.assertTrue((self.source / 'original.txt').exists())
        self.assertEqual((self.destination / 'original.txt').read_text(), 'original data')
        (self.source / 'new.txt').write_text('new file')
        with self.assertRaisesRegex(C.Error, 'resume'): M.run(record['id'])
        M.run(record['id'], resume=True)
        self.assertEqual((self.destination / 'new.txt').read_text(), 'new file')
        for argv, kwargs in self.calls:
            if argv[0] == 'rsync' and '--dry-run' not in argv:
                self.assertIn('-aHAXS', argv); self.assertIn('--numeric-ids', argv)
                self.assertNotIn('--delete', argv); self.assertIsNone(kwargs['timeout'])
                self.assertIn('--info=progress2', argv)
                self.assertFalse(kwargs['capture'])
        self.assertEqual(self.fstab.read_text(), '# Existing mounts\n')

    def test_journal_precedes_destination_creation_and_failed_copy_can_resume(self):
        record = self.make_plan()
        def failing(move, checksum=False):
            self.assertEqual(C.read_journal(record)['state'], 'copying')
            self.assertTrue(self.destination.is_dir())
            raise C.Error('simulated interruption')
        with mock.patch.object(M, '_copy', side_effect=failing), self.assertRaises(C.Error): M.run(record['id'])
        self.assertEqual(C.read_journal(record)['state'], 'copy-failed')
        self.assertEqual(M.run(record['id'], resume=True)['state'], 'staged')

    def test_destination_uuid_and_subvolume_change_refuse_copy(self):
        record = self.make_plan(); original = self.filesystem
        for key, value in (('uuid', 'replacement'), ('fsroot', '/@other'), ('target', '/changed')):
            def changed(path):
                result = original(path)
                if Path(path).is_relative_to(self.destination_volume): result[key] = value
                return result
            with mock.patch.object(M, '_filesystem', side_effect=changed), self.assertRaises(C.Error): M.run(record['id'])
        self.assertFalse(self.destination.exists())

    def test_source_inode_replacement_and_staged_destination_replacement_refuse(self):
        record = self.make_plan(); self.source.rename(self.source.with_name('retained'))
        self.source.mkdir(); (self.source / 'original.txt').write_text('same content new inode')
        with self.assertRaises(C.Error): M.run(record['id'])
        (self.source / 'original.txt').unlink()
        self.source.rmdir(); self.source.with_name('retained').rename(self.source)
        M.run(record['id']); self.destination.rename(self.destination.with_name('staged-original'))
        self.destination.mkdir()
        with self.assertRaisesRegex(C.Error, 'replaced'): M.verify(record['id'])

    def test_verify_detects_changed_content_and_extras_without_deleting(self):
        record = self.make_plan(); M.run(record['id'])
        extra = self.destination / 'extra.txt'; extra.write_text('never remove')
        with self.assertRaisesRegex(C.Error, 'extras'): M.verify(record['id'])
        self.assertEqual(extra.read_text(), 'never remove')
        self.assertEqual(C.read_journal(record)['state'], 'verification-failed')
        self.assertTrue(any('--dry-run' in argv and '--checksum' in argv and '--delete' in argv for argv, _ in self.calls))
        for argv, kwargs in self.calls:
            if argv[0] == 'rsync' and '--checksum' in argv:
                self.assertNotIn('--info=progress2', argv)
                self.assertTrue(kwargs['capture'])

    def test_switch_requires_writers_ack_and_fresh_final_checksum(self):
        record = self.make_plan(keep_path=str(self.source)); M.run(record['id']); M.verify(record['id'])
        with self.assertRaisesRegex(C.Error, 'writers-stopped'): M.switch(record['id'])
        extra = self.destination / 'extra.txt'; extra.write_text('preserve')
        with self.assertRaises(C.Error): M.switch(record['id'], writers_stopped=True)
        self.assertEqual(self.fstab.read_text(), '# Existing mounts\n')
        self.assertTrue(self.source.is_dir()); self.assertTrue(extra.exists())
        self.assertFalse(any(argv[0] in ('mount', 'umount') for argv, _ in self.calls))

    def test_switch_without_keep_path_is_refused_and_source_remains(self):
        record = self.make_plan(); M.run(record['id']); M.verify(record['id'])
        with self.assertRaisesRegex(C.Error, 'copy-only'):
            M.switch(record['id'], writers_stopped=True)
        self.assertEqual(C.read_journal(record)['state'], 'verified')
        self.assertTrue(self.source.exists())
        self.assertFalse(any(argv[0] in ('mount', 'umount') for argv, _ in self.calls))

    def test_system_trees_are_not_migration_paths(self):
        for path in ('/etc', '/etc/config', '/usr/share', '/boot', '/dev', '/proc/1', '/sys', '/run', '/var', '/var/lib', '/home', '/root'):
            with self.subTest(path=path), self.assertRaisesRegex(C.Error, 'System directories'):
                M._path(path)
        self.assertEqual(M._path('/var/lib/libvirt/images'), Path('/var/lib/libvirt/images'))

    def test_destination_nested_mounts_and_midcopy_identity_changes_are_rejected(self):
        record = self.make_plan(); M.run(record['id'])
        with mock.patch.object(M, '_filesystems', return_value=[self.destination / 'unrelated-mount']), self.assertRaisesRegex(C.Error, 'nested mount'):
            M.run(record['id'], resume=True)
        original = self.filesystem
        mutated = False
        def changed(path):
            info = original(path)
            if mutated and Path(path).is_relative_to(self.destination_volume): info['uuid'] = 'changed-volume'
            return info
        def copy_then_replace(move, checksum=False):
            nonlocal mutated
            mutated = True
        with mock.patch.object(M, '_filesystem', side_effect=changed), mock.patch.object(M, '_copy', side_effect=copy_then_replace), self.assertRaises(C.Error):
            M.run(record['id'], resume=True)
        self.assertEqual(C.read_journal(record)['state'], 'copy-failed')

    def test_successful_bind_switch_preserves_original_and_reuses_exact_destination(self):
        record = self.make_plan(keep_path=str(self.source)); M.run(record['id'])
        def mounted_identity(path):
            path = Path(path)
            return self.real_identity(self.bindings[path]) if path in self.bindings else self.real_identity(path)
        with mock.patch.object(M, '_identity', side_effect=mounted_identity):
            journal = M.switch(record['id'], writers_stopped=True)
        self.assertEqual(journal['state'], 'switched')
        self.assertEqual(journal['switched_paths'], [str(self.source)])
        retained = Path(journal['retained'][0]['retained'])
        self.assertEqual((retained / 'original.txt').read_text(), 'original data')
        self.assertEqual(self.bindings[self.source], self.destination)
        self.assertIn(str(self.destination) + ' ' + str(self.source) + ' none bind,', self.fstab.read_text())
        with self.assertRaisesRegex(C.Error, 'replay'):
            M.switch(record['id'], writers_stopped=True)

    def test_paths_cannot_overlap_storage_operation_records(self):
        state = self.root / 'state'
        state.mkdir(); source = state / 'dataset'; source.mkdir()
        with self.assertRaisesRegex(C.Error, 'operation records'):
            M.plan([dict(source=str(source), destination=str(self.destination))])

    def test_switch_validates_only_planned_rows_and_preserves_unrelated_fstab_bytes(self):
        old = '# Existing mounts\nmissing.example.org:/offline /unrelated nfs invalid-option 0 0\n\n\n'
        self.fstab.write_text(old)
        record = self.make_plan(keep_path=str(self.source)); M.run(record['id'])
        original_command = self.command
        checked = []
        def validate_planned_only(argv, **kwargs):
            if argv[:2] == ['findmnt', '--verify']:
                validation = Path(argv[-1]).read_text()
                checked.append(validation)
                self.assertNotIn('missing.example.org', validation)
                self.assertNotIn('invalid-option', validation)
                self.assertIn(str(self.destination) + ' ' + str(self.source), validation)
            return original_command(argv, **kwargs)
        def mounted_identity(path):
            path = Path(path)
            return self.real_identity(self.bindings[path]) if path in self.bindings else self.real_identity(path)
        with mock.patch.object(C, 'command', side_effect=validate_planned_only), mock.patch.object(M, '_identity', side_effect=mounted_identity):
            journal = M.switch(record['id'], writers_stopped=True)
        self.assertEqual(journal['state'], 'switched')
        self.assertEqual(len(checked), 1)
        self.assertTrue(self.fstab.read_text().startswith(old))
        self.assertEqual(Path(journal['fstab_backup']).read_text(), old)

    def test_partial_switch_records_retained_original_and_refuses_replay(self):
        record = self.make_plan(keep_path=str(self.source)); M.run(record['id'])
        original = self.command
        def fail_mount(argv, **kwargs):
            if argv[0] == 'mount': raise C.Error('simulated mount error')
            return original(argv, **kwargs)
        with mock.patch.object(C, 'command', side_effect=fail_mount), self.assertRaises(C.Error):
            M.switch(record['id'], writers_stopped=True)
        journal = C.read_journal(record)
        self.assertEqual(journal['state'], 'switch-failed')
        retained = Path(journal['retained'][0]['retained'])
        self.assertEqual((retained / 'original.txt').read_text(), 'original data')
        self.assertEqual(Path(journal['fstab_backup']).read_text(), '# Existing mounts\n')
        with self.assertRaisesRegex(C.Error, 'replay'): M.run(record['id'], resume=True)
        self.assertFalse(any('-l' in argv or '--lazy' in argv for argv, _ in self.calls))

    def test_existing_bind_fstab_entry_changes_source_and_preserves_other_entries(self):
        source, destination, keep = '/old/projects', '/new/projects', '/home/example/projects'
        record = {'moves': [{'source': source, 'destination': destination, 'keep_path': {'path': keep, 'existing_bind': True}}]}
        original = f'# original\n{source} {keep} none bind 0 0\nUUID=other /other ext4 defaults 0 0\n'
        result = M._fstab_text(original, record)
        self.assertIn(f'{destination} {keep} none bind,', result)
        self.assertIn('UUID=other /other ext4 defaults 0 0', result)
        with self.assertRaises(C.Error): M._fstab_text(original.replace(source, '/unreviewed'), record)

    def test_graphical_sessions_and_busy_paths_are_refused(self):
        moves = [{'source': str(self.source), 'destination': str(self.destination), 'keep_path': None}]
        with mock.patch.object(M.sys.stdin, 'isatty', return_value=True), mock.patch.object(C, 'command', side_effect=['42 user seat0', 'wayland']):
            with self.assertRaisesRegex(C.Error, 'graphical'):
                self.real_quiesced(moves)
        proc = self.root / 'proc'; proc.mkdir(); process = proc / '12345'; process.mkdir()
        (process / 'fd').mkdir(); (process / 'fd' / '3').symlink_to(self.source / 'original.txt')
        (process / 'maps').write_text(''); (process / 'cwd').symlink_to(self.root, target_is_directory=True)
        (process / 'root').symlink_to('/', target_is_directory=True)
        with mock.patch.object(M, 'PROC', proc):
            self.assertEqual(M._busy_paths(moves), [12345])
        (process / 'fd' / '3').unlink()
        (process / 'maps').write_text(f'0000-1111 r--p 0000 00:00 0 {self.source}/original.txt\n')
        with mock.patch.object(M, 'PROC', proc):
            self.assertEqual(M._busy_paths(moves), [12345])
        (process / 'maps').write_text('')
        (process / 'cwd').unlink(); (process / 'cwd').symlink_to(self.source, target_is_directory=True)
        with mock.patch.object(M, 'PROC', proc):
            self.assertEqual(M._busy_paths(moves), [12345])


if __name__ == '__main__':
    unittest.main()
