"""Cleanup lifecycle: real rsync on disposable data; no real mounts or snapshots."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import bromigos_storage_common as C
import bromigos_storage_cleanup as K
import bromigos_storage_migration as M


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.volume = self.root/'old-volume'; self.volume.mkdir()
        self.newvolume = self.root/'new-volume'; self.newvolume.mkdir()
        self.source = self.volume/'projects'; self.source.mkdir()
        (self.source/'work.txt').write_text('valuable data')
        self.destination = self.newvolume/'projects'
        shutil.copytree(self.source, self.destination)
        self.real_identity = M._identity
        self.real_command = C.command
        self.bindings = {}
        self.inventory = {'snapshots': []}
        self.calls = []
        self.fstab = self.root/'fstab'; self.fstab.write_text('')
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        for patch in [mock.patch.dict(os.environ, BROMIGOS_STORAGE_STATE=str(self.root/'state')),
                      mock.patch.object(C, 'require_root'), mock.patch.object(C, 'lock', side_effect=lambda _: contextlib.nullcontext()),
                      mock.patch.object(C.os, 'fchown'), mock.patch.object(K, '_inventory', side_effect=lambda: self.inventory),
                      mock.patch.object(M, 'FSTAB', self.fstab), mock.patch.object(M, '_busy_paths', return_value=[]), mock.patch.object(M, '_filesystems', return_value=[]),
                      mock.patch.object(M, '_filesystem', side_effect=self.filesystem),
                      mock.patch.object(M, '_identity', side_effect=self.identity), mock.patch.object(C, 'command', side_effect=self.command),
                      contextlib.redirect_stdout(io.StringIO())]:
            self.stack.enter_context(patch)

    def filesystem(self, path):
        path = Path(path)
        return dict(target=str(self.newvolume if path.is_relative_to(self.newvolume) else self.volume),
                    uuid='new' if path.is_relative_to(self.newvolume) else 'old', fstype='ext4', fsroot='/')

    def identity(self, path):
        return self.real_identity(self.bindings.get(Path(path), Path(path)))

    def command(self, argv, **kw):
        self.calls.append(argv)
        if argv[0] == 'findmnt': return json.dumps({'filesystems': []})
        if argv[0] == 'rsync':
            assert all(Path(p).is_relative_to(self.root) for p in argv[-2:])
            return self.real_command(argv, **kw)
        return ''

    def migrated(self, existing=False):
        move = dict(source=str(self.source), destination=str(self.destination), source_identity=self.real_identity(self.source),
                    source_filesystem=self.filesystem(self.source), destination_identity=None,
                    destination_filesystem=self.filesystem(self.destination),
                    keep_path={'path': str(self.source), 'existing_bind': existing})
        if existing:
            keep = self.root/'keep'; keep.mkdir()
            move['keep_path']['path'] = str(keep)
        record = C.store('plans', dict(kind='migration', moves=[move]))
        old = self.source if existing else self.source.with_name(self.source.name+'.before-storage-'+record['id'])
        if not existing:
            self.source.rename(old); self.source.mkdir()
        self.bindings[Path(move['keep_path']['path'])] = self.destination
        journal = dict(state='switched', originals_retained=True, destinations={str(self.destination): self.real_identity(self.destination)},
                       retained=[] if existing else [{'original': str(self.source), 'retained': str(old)}])
        C.update_journal(record, journal)
        self.fstab.write_text(str(self.destination)+' '+move['keep_path']['path']+' none bind 0 0\n')
        return record, old

    def test_verified_original_cleanup_preserves_active_files_and_records_space(self):
        migration, old = self.migrated()
        plan = K.plan(migration['path'])
        self.assertTrue(old.exists())
        result = K.apply(plan['path'], yes=True)
        self.assertEqual(result['state'], 'complete')
        self.assertFalse(old.exists())
        self.assertEqual((self.destination/'work.txt').read_text(), 'valuable data')
        self.assertFalse(C.read_journal(migration)['originals_retained'])
        self.assertTrue(result['before']); self.assertTrue(result['after'])
        self.assertIn('Cleanup complete', Path(result['log']).read_text())
        self.assertEqual(Path(result['log']).stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(C.Error, 'journal'): K.apply(plan['path'], yes=True)

    def test_existing_bind_source_is_retired_without_touching_bind_or_destination(self):
        migration, old = self.migrated(existing=True)
        result = K.apply(K.plan(migration['path'])['path'], yes=True)
        self.assertEqual(result['completed'], [str(old)])
        self.assertTrue((self.root/'keep').exists())
        self.assertTrue((self.destination/'work.txt').exists())

    def test_changed_live_data_refuses_all_deletion_and_logs_names(self):
        migration, old = self.migrated(); plan = K.plan(migration['path'])
        (self.destination/'work.txt').write_text('new edits')
        with self.assertRaisesRegex(C.Error, 'work.txt'): K.apply(plan['path'], yes=True)
        self.assertTrue(old.exists()); self.assertEqual((self.destination/'work.txt').read_text(), 'new edits')
        result = C.read_journal(plan)
        self.assertEqual(result['state'], 'verification-failed'); self.assertEqual(result['completed'], [])
        self.assertIn('work.txt', Path(result['log']).read_text())

    def test_source_mount_alias_replaced_inode_and_busy_original_refused(self):
        migration, old = self.migrated(); plan = K.plan(migration['path'])
        with mock.patch.object(M, '_filesystems', return_value=[old/'nested']), self.assertRaisesRegex(C.Error, 'mount'):
            K.apply(plan['path'], yes=True)
        with mock.patch.object(M, '_busy_paths', return_value=[123]), self.assertRaisesRegex(C.Error, '123'):
            K.apply(plan['path'], yes=True)
        self.bindings[self.source] = old
        with self.assertRaisesRegex(C.Error, 'application path'): K.apply(plan['path'], yes=True)
        self.assertTrue(old.exists())

    def test_partial_delete_is_journaled_and_never_replayed(self):
        migration, old = self.migrated(); plan = K.plan(migration['path'])
        def partial(path):
            (Path(path)/'work.txt').unlink()
            raise OSError('simulated removal failure')
        with mock.patch.object(K.shutil, 'rmtree', side_effect=partial) as remove:
            remove.avoids_symlink_attacks = True
            with self.assertRaises(OSError): K.apply(plan['path'], yes=True)
        result = C.read_journal(plan)
        self.assertEqual(result['state'], 'failed'); self.assertEqual(result['active_path'], str(old))
        with self.assertRaisesRegex(C.Error, 'journal'): K.apply(plan['path'], yes=True)

    def test_writer_opening_during_checksum_stops_retirement(self):
        migration, old = self.migrated(); plan = K.plan(migration['path'])
        with mock.patch.object(M, '_busy_paths', side_effect=[[],[321]]):
            with self.assertRaisesRegex(C.Error,'during verification'):
                K._original(plan['items'][0],compare=True)
        self.assertTrue(old.exists())

    def test_wrong_plan_kind_never_gains_cleanup_journal(self):
        plan = C.store('plans', {'kind':'provision'})
        with self.assertRaisesRegex(C.Error,'cleanup plan'): K.apply(plan['path'],yes=True)
        self.assertIsNone(C.read_journal(plan))

    def test_non_switched_migration_and_copy_only_never_removed(self):
        migration, old = self.migrated()
        C.update_journal(migration, {'state': 'staged', 'originals_retained': True})
        with self.assertRaisesRegex(C.Error, 'completed switch'): K.plan(migration['path'])
        self.assertTrue(old.exists())

    def test_new_snapshot_is_reported_not_added_to_delete_set(self):
        migration, old = self.migrated(); plan = K.plan(migration['path'])
        self.inventory = {'snapshots': [{'provider':'snapper', 'candidates':[{'path':'/example/snapshot'}]}]}
        result = K.apply(plan['path'], yes=True)
        self.assertEqual(result['new_snapshot_paths'], ['/example/snapshot'])
        self.assertFalse(any(a[0] in ('btrfs','snapper') for a in self.calls))

    def test_snapshot_replacement_and_readwrite_snapshot_refused(self):
        source = self.volume/'home'; source.mkdir()
        snapshot = self.volume/'snapshot'; snapshot.mkdir()
        candidate = dict(provider='btrbk', path=str(snapshot), source_path=str(source), config=None)
        self.inventory = {'snapshots':[{'candidates':[candidate]}]}
        def command(argv, **kw):
            if argv[:3] == ['btrfs','subvolume','show']:
                return 'UUID: '+('source' if argv[-1]==str(source) else 'snapshot')+'\nParent UUID: source\nSubvolume ID: 501\n'
            if argv[:3] == ['btrfs','property','get']: return 'ro=false'
            return ''
        def filesystem(path): return dict(target=str(self.volume), uuid='old', fstype='btrfs', fsroot='/')
        with mock.patch.object(M, '_filesystem', side_effect=filesystem), mock.patch.object(C, 'command', side_effect=command):
            with self.assertRaisesRegex(C.Error, 'read-only'): K.plan(snapshots=[str(snapshot)])
        self.assertTrue(snapshot.exists())

    def test_snapshot_providers_delete_only_selected_identity_and_wait(self):
        for provider in ('snapper', 'btrbk'):
            with self.subTest(provider=provider):
                source = self.volume/('home-'+provider); source.mkdir()
                snapshot = self.volume/('snapshot-'+provider); snapshot.mkdir()
                candidate = dict(provider=provider, path=str(snapshot), source_path=str(source), config='home.test', id=7)
                self.inventory = {'snapshots':[{'candidates':[candidate]}]}
                commands = []
                def command(argv, **kw):
                    commands.append(argv)
                    if argv[0] == 'findmnt': return json.dumps({'filesystems': []})
                    if argv[:3] == ['btrfs','subvolume','show']:
                        return 'UUID: '+('source' if argv[-1]==str(source) else 'snapshot')+'\nParent UUID: source\nSubvolume ID: 501\n'
                    if argv[:3] == ['btrfs','property','get']: return 'ro=true'
                    if (argv[0]=='snapper' and 'delete' in argv) or argv[:3]==['btrfs','subvolume','delete']:
                        self.inventory = {'snapshots':[{'candidates':[dict(candidate,path=str(snapshot)+'-new')]}]}
                    return ''
                def filesystem(path): return dict(target=str(self.volume), uuid='old', fstype='btrfs', fsroot='/')
                with mock.patch.object(M, '_filesystem', side_effect=filesystem), mock.patch.object(C, 'command', side_effect=command):
                    plan = K.plan(snapshots=[str(snapshot)])
                    result = K.apply(plan['path'], yes=True)
                expected = ['snapper','-c','home.test','delete','7'] if provider=='snapper' else ['btrfs','subvolume','delete',str(snapshot)]
                self.assertIn(expected, commands)
                self.assertIn(['btrfs','subvolume','sync',str(self.volume)],commands)
                self.assertEqual(result['state'],'complete')
                self.assertEqual(result['new_snapshot_paths'],[str(snapshot)+'-new'])

    def test_replaced_or_nested_snapshot_refuses_before_deletion(self):
        source = self.volume/'home'; source.mkdir()
        snapshot = self.volume/'snapshot'; snapshot.mkdir()
        candidate = dict(provider='btrbk', path=str(snapshot), source_path=str(source), config=None)
        self.inventory = {'snapshots':[{'candidates':[candidate]}]}
        replacement, nested = False, False
        commands = []
        def command(argv, **kw):
            commands.append(argv)
            if argv[0]=='findmnt': return json.dumps({'filesystems':[]})
            if argv[:3]==['btrfs','subvolume','show']:
                uuid = 'source' if argv[-1]==str(source) else ('replacement' if replacement else 'snapshot')
                return 'UUID: '+uuid+'\nParent UUID: source\nSubvolume ID: 501\n'
            if argv[:3]==['btrfs','property','get']: return 'ro=true'
            if argv[:4]==['btrfs','subvolume','list','-o']: return 'ID 900 child' if nested else ''
            return ''
        def filesystem(path): return dict(target=str(self.volume), uuid='old', fstype='btrfs', fsroot='/')
        with mock.patch.object(M,'_filesystem',side_effect=filesystem), mock.patch.object(C,'command',side_effect=command):
            plan = K.plan(snapshots=[str(snapshot)])
            replacement = True
            with self.assertRaisesRegex(C.Error,'identity'): K.apply(plan['path'],yes=True)
            self.assertEqual(C.read_journal(plan)['state'],'preflight-failed')
            replacement = False; nested = True
            with self.assertRaisesRegex(C.Error,'nested'): K.apply(plan['path'],yes=True)
        self.assertFalse(any('delete' in cmd for cmd in commands))

    def test_persistent_bind_and_mounted_alias_are_checked(self):
        migration, old = self.migrated(); plan = K.plan(migration['path'])
        with mock.patch.object(K, '_mount_rows', return_value=[{'uuid':'old','fsroot':'/'+str(old.relative_to(self.volume)), 'target':'/somewhere'}]):
            with self.assertRaisesRegex(C.Error, 'mounted'): K.apply(plan['path'], yes=True)
        self.fstab.write_text('')
        with self.assertRaisesRegex(C.Error, 'fstab'): K.apply(plan['path'], yes=True)
        self.assertTrue(old.exists())

    def test_unknown_snapshot_and_duplicate_selection_refused(self):
        with self.assertRaisesRegex(C.Error, 'uniquely'): K.plan(snapshots=['/missing/snapshot'])
        with self.assertRaisesRegex(C.Error, 'more than once'): K.plan(snapshots=['/same','/same'])


class MountSelection(unittest.TestCase):
    def test_autofs_placeholder_is_ignored_but_ambiguous_real_mounts_are_not(self):
        actual=dict(target='/tmp', uuid='fixture', fstype='btrfs', fsroot='/')
        with mock.patch.object(C, 'command', return_value=json.dumps({'filesystems':[dict(fstype='autofs'), actual]})):
            self.assertEqual(M._filesystem(Path('/tmp')), actual)
        with mock.patch.object(C, 'command', return_value=json.dumps({'filesystems':[actual, actual]})), self.assertRaises(C.Error):
            M._filesystem(Path('/tmp'))


if __name__ == '__main__': unittest.main()
