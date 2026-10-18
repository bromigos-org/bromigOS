import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bromigos_storage_inventory as I

class InventoryTest(unittest.TestCase):
    def test_only_local_block_mounts_have_space_queried(self):
        rows=[dict(target='/local',source='/dev/fake',fstype='btrfs',uuid='fixture'),
              dict(target='/local/child',source='/dev/fake',fstype='btrfs',uuid='fixture'),
              dict(target='/nas',source='server:/share',fstype='nfs'),
              dict(target='/auto',source='systemd-1',fstype='autofs'),
              dict(target='/fuse',source='/dev/fuse',fstype='fuse.test'),
              dict(target='/proc',source='proc',fstype='proc')]
        def command(argv,**kwargs):
            return json.dumps({'blockdevices':[]}) if argv[0]=='lsblk' else json.dumps({'filesystems':rows})
        usage=type('Usage',(),dict(total=100,used=30,free=70))()
        with patch.object(I.C,'command',command),patch.object(I.shutil,'disk_usage',return_value=usage) as stat:
            result=I.status()
        self.assertEqual([c.args[0] for c in stat.call_args_list],['/local'])
        self.assertTrue(all(x['shared'] for x in result['free_space']))
        self.assertIn('must not be added',result['space_note'])

    def test_failures_are_explicit_without_utility_output(self):
        with patch.object(I.C,'command',side_effect=I.C.Error('secret fixture output')):
            result=I.status()
        self.assertEqual(len(result['errors']),2)
        self.assertNotIn('secret',str(result))

    def test_preview_only_known_cache_roots_not_worktrees(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(I.Path,'home',return_value=Path(tmp)),patch.dict(I.os.environ,{'XDG_CACHE_HOME':tmp+'/.cache'}):
            (Path(tmp)/'.npm/_cacache').mkdir(parents=True)
            (Path(tmp)/'.cache/paru/clone/project/.git').mkdir(parents=True)
            with patch.object(I.C,'command',return_value='1200 fixture\n') as command,patch.object(I,'_read_mounts',return_value=[dict(target='/',source='/dev/fake',fstype='ext4',uuid='fixture')]),patch.object(I,'snapshot_inventory',return_value={'snapshots':[]}):
                result=I.cleanup_preview()
            self.assertFalse(result['deleted'])
            self.assertIn('npm',[c['kind'] for c in result['candidates']])
            self.assertNotIn('paru',[c['kind'] for c in result['candidates']])
            self.assertTrue(all(c['allocated_bytes']==1200 for c in result['candidates']))
            self.assertTrue(all(c.args[0][0]=='du' for c in command.call_args_list))

    def test_snapshot_summary_counts_only_numeric_direct_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'users/person'; home.mkdir(parents=True)
            snapshots=home/'.snapshots'; snapshots.mkdir()
            (snapshots/'1').mkdir(); (snapshots/'22').mkdir()
            (snapshots/'22'/'99').mkdir()
            (snapshots/'text').mkdir(); (snapshots/'333').write_text('not a directory')
            (snapshots/'44').symlink_to(snapshots/'1',target_is_directory=True)
            (home.parent/'.snapshots').mkdir()
            result=I._snapshot_summary(home)
            self.assertEqual([r['numeric_directories'] for r in result],[2,0])
            self.assertTrue(all(r['status']=='present' for r in result))
            self.assertTrue(all(str(r['path']).startswith(tmp) for r in result))

    def test_missing_or_inaccessible_snapshots_are_not_reported_as_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'users/person'; home.mkdir(parents=True)
            missing=I._snapshot_summary(home)
            self.assertTrue(all(r['status']=='unavailable' and r['numeric_directories'] is None for r in missing))
            (home/'.snapshots').mkdir()
            with patch.object(I.Path,'iterdir',side_effect=PermissionError):
                unavailable=I._snapshot_summary(home)
            self.assertEqual(unavailable[0]['status'],'unavailable')
            self.assertIsNone(unavailable[0]['numeric_directories'])

    def test_home_at_root_does_not_claim_root_snapshots(self):
        with patch.object(I.Path,'is_dir',return_value=False):
            result=I._snapshot_summary(Path('/example-home'))
        self.assertEqual([r['path'] for r in result],['/example-home/.snapshots'])

class GroupingTest(unittest.TestCase):
    def test_one_capacity_for_bind_mounts_and_no_zram_drive(self):
        disks = [dict(path='/dev/test', type='disk', model='Example', size=1000,
                      children=[dict(path='/dev/test1', type='part', uuid='data', label='Data')]),
                 dict(path='/dev/zram0', type='disk', size=10)]
        mounts = [dict(target='/data', source='/dev/test1', fstype='ext4', uuid='data', fsroot='/'),
                  dict(target='/alias', source='/dev/test1[/projects]', fstype='ext4', uuid='data', fsroot='/projects')]
        def command(argv, **kwargs):
            return json.dumps({'blockdevices': disks}) if argv[0] == 'lsblk' else json.dumps({'filesystems': mounts})
        usage = type('Usage', (), dict(total=1000, used=300, free=600))()
        with patch.object(I.C, 'command', command), patch.object(I.shutil, 'disk_usage', return_value=usage) as stat:
            result = I.status()
        self.assertEqual(len(result['drives']), 1)
        self.assertEqual(len(result['filesystems']), 1)
        self.assertEqual(result['filesystems'][0]['physical_drives'], ['/dev/test'])
        self.assertEqual(result['filesystems'][0]['label'], 'Data')
        self.assertEqual(len(result['free_space']), 2)
        stat.assert_called_once_with('/data')

    def test_inactive_automount_over_local_mount_is_never_queried(self):
        mounts = [dict(target='/auto', source='/dev/test', fstype='btrfs', uuid='data'),
                  dict(target='/auto', source='systemd-1', fstype='autofs')]
        def command(argv, **kwargs):
            return json.dumps({'blockdevices': []}) if argv[0] == 'lsblk' else json.dumps({'filesystems': mounts})
        with patch.object(I.C, 'command', command), patch.object(I.shutil, 'disk_usage') as stat:
            result = I.status()
        self.assertFalse(result['filesystems'])
        stat.assert_not_called()
        with patch.object(I.C, 'command') as metadata:
            self.assertFalse(I._snapshot_ids(mounts))
        metadata.assert_not_called()


class SnapshotInventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.volume = self.base / 'volume'
        self.source = self.volume / '@home'
        self.directory = self.volume / 'snapshots'
        self.source.mkdir(parents=True)
        self.directory.mkdir()
        self.config = self.volume / 'btrbk.conf'
        self.config.write_text(f'volume {self.volume}\n snapshot_dir snapshots\n subvolume @home\n')
        self.mounts = [dict(target=str(self.volume), source='/dev/test', fstype='btrfs', uuid='test-fs', fsroot='/')]

    def test_snapper_configs_include_custom_paths_and_exclude_zero(self):
        def command(argv, **kwargs):
            if argv[0] == 'btrfs':
                return ''
            if 'list-configs' in argv:
                return json.dumps({'configs': [{'config': 'custom', 'subvolume': str(self.source)}]})
            return json.dumps({'custom': [{'number': 0}, {'number': 12, 'date': '2026-01-01'}]})
        with patch.object(I.C, 'command', command):
            result = I.snapshot_inventory(mounts=self.mounts, btrbk_config=self.config)
        group = next(g for g in result['snapshots'] if g['provider'] == 'snapper')
        self.assertEqual(group['status'], 'present')
        self.assertEqual(group['count'], 1)
        self.assertEqual(group['candidates'][0]['id'], 12)
        self.assertEqual(group['candidates'][0]['path'], str(self.source / '.snapshots/12/snapshot'))
        self.assertEqual(group['candidates'][0]['filesystem_uuid'], 'test-fs')
        self.assertIsNone(group['candidates'][0]['parent_uuid'])

    def test_btrbk_exact_names_metadata_and_no_snapshot_content_walk(self):
        named = self.directory / '@home.20260101T0000'
        named.mkdir()
        (named / 'do-not-open').mkdir()
        (self.directory / '@home.20260101T0000.other').mkdir()
        (self.directory / '@other.20260101T0000').mkdir()
        (self.directory / '@home.20260102T0000').symlink_to(named, target_is_directory=True)
        uuid = '11111111-1111-1111-1111-111111111111'
        parent = '22222222-2222-2222-2222-222222222222'
        output = f'ID 42 gen 50 cgen 40 top level 5 otime 2026-01-01 00:00:00 parent_uuid {parent} uuid {uuid} path snapshots/@home.20260101T0000\n'
        def command(argv, **kwargs):
            if argv[0] == 'btrfs':
                return output
            return json.dumps({'configs': []})
        original_iter = Path.iterdir
        visited = []
        def iterdir(path):
            visited.append(path)
            return original_iter(path)
        with patch.object(I.C, 'command', command), patch.object(Path, 'iterdir', iterdir):
            result = I.snapshot_inventory(mounts=self.mounts, btrbk_config=self.config)
        group = next(g for g in result['snapshots'] if g['provider'] == 'btrbk')
        self.assertEqual(group['status'], 'present')
        self.assertEqual(group['count'], 1)
        candidate = group['candidates'][0]
        self.assertEqual(candidate['id'], 42)
        self.assertEqual(candidate['subvolume_uuid'], uuid)
        self.assertEqual(candidate['parent_uuid'], parent)
        self.assertEqual(candidate['source_path'], str(self.source))
        self.assertEqual(visited, [self.directory])

    def test_inactive_automount_is_not_statted_or_listed(self):
        mounts = [dict(target=str(self.volume), source='systemd-1', fstype='autofs')]
        def command(argv, **kwargs):
            self.assertEqual(argv[0], 'snapper')
            return json.dumps({'configs': [{'config': 'custom', 'subvolume': str(self.source)}]})
        with patch.object(I.C, 'command', command), patch.object(Path, 'is_symlink') as link, patch.object(Path, 'iterdir') as listing:
            result = I.snapshot_inventory(mounts=mounts, btrbk_config=self.config)
        self.assertTrue(all(group['status'] == 'unavailable' for group in result['snapshots']))
        link.assert_not_called()
        listing.assert_not_called()

    def test_missing_permissions_and_unsupported_includes_stay_unknown(self):
        self.config.write_text('include /not-read.conf\n')
        with patch.object(I.C, 'command', side_effect=I.C.Error('private output')):
            result = I.snapshot_inventory(mounts=self.mounts, btrbk_config=self.config)
        snapper, btrbk = result['snapshots']
        self.assertEqual(snapper['status'], 'unavailable')
        self.assertIsNone(snapper['count'])
        self.assertEqual(btrbk['status'], 'unsupported')
        self.assertIn('includes', btrbk['detail'])
        self.assertNotIn('private output', str(result))

    def test_btrbk_global_default_custom_name_and_backup_target_ignored(self):
        self.config.write_text(f'snapshot_dir snapshots\nvolume {self.volume}\n subvolume @home\n  snapshot_name user-data\n  target send-receive /not-visited\n')
        (self.directory / 'user-data.20260101T000000').mkdir()
        with patch.object(I.C, 'command', return_value='{"configs": []}'):
            result = I.snapshot_inventory(mounts=self.mounts, btrbk_config=self.config)
        group = result['snapshots'][0]
        self.assertEqual(group['count'], 1)
        self.assertEqual(group['candidates'][0]['name'], 'user-data.20260101T000000')

    def test_directory_bound_returns_unknown_instead_of_partial_count(self):
        for day in ('01', '02'):
            (self.directory / f'@home.202601{day}T0000').mkdir()
        with patch.object(I.C, 'command', return_value='{"configs": []}'), patch.object(I, 'SNAPSHOT_LIMIT', 1):
            result = I.snapshot_inventory(mounts=self.mounts, btrbk_config=self.config)
        self.assertIsNone(result['snapshots'][0]['count'])
        self.assertEqual(result['snapshots'][0]['candidates'], [])

    def test_btrbk_snapshot_directory_symlink_is_not_followed(self):
        self.directory.rmdir()
        self.directory.symlink_to(self.source, target_is_directory=True)
        with patch.object(I.C, 'command', return_value='{"configs": []}'), patch.object(Path, 'iterdir') as listing:
            result = I.snapshot_inventory(mounts=self.mounts, btrbk_config=self.config)
        self.assertEqual(result['snapshots'][0]['status'], 'unavailable')
        listing.assert_not_called()

    def test_btrfs_identity_fields_do_not_depend_on_output_order(self):
        uuid = '11111111-1111-1111-1111-111111111111'
        parent = '22222222-2222-2222-2222-222222222222'
        output = f'ID 42 gen 50 uuid {uuid} parent_uuid {parent} path snapshots/name\n'
        with patch.object(I.C, 'command', return_value=output):
            identities = I._snapshot_ids(self.mounts)
        self.assertEqual(identities[('test-fs', 'snapshots/name')]['subvolume_uuid'], uuid)
        self.assertEqual(identities[('test-fs', 'snapshots/name')]['parent_uuid'], parent)

    def test_config_behind_inactive_automount_is_never_opened(self):
        mounts = [dict(target=str(self.volume), source='systemd-1', fstype='autofs')]
        with patch.object(Path, 'open') as opening:
            groups = I._btrbk(mounts, {}, self.config)
        opening.assert_not_called()
        self.assertEqual(groups[0]['status'], 'unavailable')

    def test_symlink_parent_rejected_before_accessing_child(self):
        parent = self.volume / 'alias'
        parent.symlink_to('/not-visited', target_is_directory=True)
        visited = []
        original = Path.is_symlink
        def check(path):
            visited.append(path)
            return original(path)
        with patch.object(Path, 'is_symlink', check):
            self.assertFalse(I._safe_local(parent / 'snapshots', self.mounts))
        self.assertNotIn(parent / 'snapshots', visited)

    def test_malformed_snapper_config_rows_are_explicitly_unavailable(self):
        with patch.object(I.C, 'command', return_value='{"configs": [null]}'):
            groups = I._snapper(self.mounts, {})
        self.assertEqual(groups[0]['status'], 'unavailable')
        self.assertIsNone(groups[0]['count'])
