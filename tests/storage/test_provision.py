import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bromigos_storage_provision as P

IDENT=dict(by_id='/dev/disk/by-id/fixture-disk',path='/dev/fixture',serial='EXACT-SERIAL',size_bytes=2000000000000,model='Fixture',wwn='fixture',major_minor='8:0')
MOUNTS=[dict(role='development',subvolume='@development',mount='/mnt/Example')]
RECORD=dict(kind='provision',id='plan-fixture',device=IDENT,mounts=MOUNTS,fstab_digest='fixture',owner_uid=1000,owner_gid=1000)

class ProvisionTest(unittest.TestCase):
    def test_layout_refuses_unreviewed_roles_and_paths(self):
        for path,roles in [('/home/user',['development']),('/mnt/Example',['games']),('/mnt/Example',['development','other']),('/mnt/Example',['development','development']),('/mnt/a/b',['development'])]:
            with self.subTest(path=path,roles=roles),self.assertRaises(P.C.Error): P._paths(path,roles)
        self.assertEqual(P._paths('/mnt/Example',['development','games'])[1]['subvolume'],'@games')

    def test_mount_protection_uses_major_minor_not_only_alias(self):
        disk=[dict(path='/dev/fixture',**{'maj:min':'8:0'},children=[dict(path='/dev/fixture1',**{'maj:min':'8:1'},uuid='same')])]
        with patch.object(P,'_json',return_value={'filesystems':[dict(target='/',source='/dev/other-alias',**{'maj:min':'8:1'})]}):
            with self.assertRaises(P.C.Error): P._guard(disk,MOUNTS)

    def test_existing_journal_refuses_all_disk_commands(self):
        with patch.object(P.C,'require_root'),patch.object(P.C,'read',return_value=RECORD),patch.object(P.C,'lock',return_value=contextlib.nullcontext()),patch.object(P.C,'read_journal',return_value={'state':'failed-needs-review'}),patch.object(P.C,'command') as command:
            with self.assertRaises(P.C.Error): P.apply('fixture')
        command.assert_not_called()

    def test_identity_change_and_missing_tool_prevent_erasure(self):
        for missing in (False,True):
            with self.subTest(missing=missing),patch.object(P.C,'require_root'),patch.object(P.C,'read',return_value=RECORD),patch.object(P.C,'lock',return_value=contextlib.nullcontext()),patch.object(P.C,'read_journal',return_value=None),patch.object(P.shutil,'which',return_value=None if missing else '/fixture/tool'),patch.object(P,'_identity',return_value=(dict(IDENT,serial='CHANGED'),[])),patch.object(P.C,'command') as command:
                with self.assertRaises(P.C.Error): P.apply('fixture')
                command.assert_not_called()

    def test_journal_precedes_first_erase_and_failure_cannot_succeed(self):
        events=[]
        def journal(record,state): events.append(('journal',state['state']))
        def backup(record): events.append(('backup','fstab')); return '/fixture/fstab-backup'
        def command(argv,**kwargs):
            events.append(('command',argv[0]))
            raise P.C.Error('fixture format failure')
        with patch.object(P.C,'require_root'),patch.object(P.C,'read',return_value=RECORD),patch.object(P.C,'lock',return_value=contextlib.nullcontext()),patch.object(P.C,'read_journal',return_value=None),patch.object(P.shutil,'which',return_value='/fixture/tool'),patch.object(P,'_identity',return_value=(IDENT,[])),patch.object(P,'_guard',return_value='fixture'),patch.object(P,'_approve'),patch.object(P,'_backup_fstab',side_effect=backup),patch.object(P.C,'update_journal',side_effect=journal),patch.object(P.C,'command',side_effect=command):
            with self.assertRaises(P.C.Error): P.apply('fixture')
        self.assertEqual(events,[('backup','fstab'),('journal','erase-started'),('command','wipefs'),('journal','failed-needs-review')])

    def test_plan_only_reads_and_persists(self):
        with patch.object(P,'_identity',return_value=(IDENT,[])),patch.object(P,'_guard',return_value='fixture'),patch.object(P.C,'store',side_effect=lambda kind,record:record),patch.object(P.C,'command') as command:
            result=P.plan(IDENT['by_id'],'/mnt/Example',['development'])
        self.assertEqual(result['device']['serial'],'EXACT-SERIAL')
        command.assert_not_called()

    def test_complete_fake_run_verifies_mounts_and_publishes_backup(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fstab=root/'fstab'; fstab.write_text('# original configuration\nserver:/offline /mnt/OldNAS nfs defaults 0 0\n')
            mounts=[dict(role='development',subvolume='@development',mount=str(root/'storage')),
                    dict(role='vms',subvolume='@vms',mount=str(root/'storage/vms'))]
            digest=hashlib.sha256(fstab.read_bytes()).hexdigest()
            record=dict(RECORD,mounts=mounts,fstab_digest=digest)
            tempmount=root/'mount-top'; tempmount.mkdir()
            events=[]
            def command(argv,**kwargs):
                events.append(argv[0])
                if argv[0]=='wipefs':
                    self.assertTrue((root/'fstab.before-plan-fixture').is_file())
                if argv[:2]==['btrfs','subvolume']:
                    Path(argv[-1]).mkdir()
                if argv[:2]==['findmnt','--verify']:
                    self.assertNotIn('OldNAS',Path(argv[-1]).read_text())
                if argv[0]=='blkid': return '01234567-89ab-cdef-0123-456789abcdef\n'
                return ''
            def json_result(argv):
                role='vms' if argv[argv.index('--mountpoint')+1].endswith('/vms') else 'development'
                return {'filesystems':[dict(uuid='01234567-89ab-cdef-0123-456789abcdef',fstype='btrfs',fsroot='/@'+role)]}
            journals=[]
            with patch.object(P.C,'require_root'),patch.object(P.C,'read',return_value=record),patch.object(P.C,'lock',return_value=contextlib.nullcontext()),patch.object(P.C,'read_journal',return_value=None),patch.object(P.shutil,'which',return_value='/fixture/tool'),patch.object(P,'_identity',return_value=(IDENT,[])),patch.object(P,'_guard',return_value=digest),patch.object(P,'_paths',return_value=mounts),patch.object(P,'_approve'),patch.object(P.C,'update_journal',side_effect=lambda rec,state:journals.append(state['state'])),patch.object(P.C,'command',side_effect=command),patch.object(P,'_json',side_effect=json_result),patch.object(P.tempfile,'mkdtemp',return_value=str(tempmount)),patch.object(P.os,'chown'),patch.object(P,'FSTAB',fstab):
                result=P.apply('fixture')
            self.assertEqual(result['state'],'complete')
            self.assertEqual(journals[0],'erase-started')
            self.assertEqual(journals[-1],'complete')
            self.assertEqual(events[-1],'systemctl')
            self.assertIn('subvol=@vms',fstab.read_text())
            self.assertEqual(Path(result['fstab_backup']).read_text(),'# original configuration\nserver:/offline /mnt/OldNAS nfs defaults 0 0\n')
            self.assertIn('server:/offline',fstab.read_text())

    def test_read_only_and_unknown_writeability_refused_before_plan(self):
        from types import SimpleNamespace
        import os,stat
        disk=dict(path='/dev/fixture',type='disk',serial='EXACT',size=1000,**{'maj:min':'8:0'})
        for value in (True,None):
            with self.subTest(ro=value),patch.object(P.Path,'stat',return_value=SimpleNamespace(st_mode=stat.S_IFBLK,st_rdev=os.makedev(8,0))),patch.object(P.Path,'resolve',return_value=Path('/dev/fixture')),patch.object(P,'_json',return_value={'blockdevices':[dict(disk,ro=value)]}):
                with self.assertRaises(P.C.Error): P._identity('/dev/disk/by-id/fixture')
