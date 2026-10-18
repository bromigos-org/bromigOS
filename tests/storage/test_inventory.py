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
        self.assertEqual([c.args[0] for c in stat.call_args_list],['/local','/local/child'])
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
            with patch.object(I.C,'command',return_value='1200 fixture\n') as command,patch.object(I,'_snapshot_summary',return_value=[]):
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
