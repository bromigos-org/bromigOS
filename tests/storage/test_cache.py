"""Native cache commands are faked; only disposable fixtures can be touched."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import bromigos_storage_common as C
import bromigos_storage_cache as A
import bromigos_storage_cleanup as K
import bromigos_storage_migration as M


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root/'home'; self.home.mkdir()
        self.uid = os.geteuid() or 1000
        self.npm = self.home/'.npm/_cacache'; self.npm.mkdir(parents=True)
        self.conda = self.home/'.conda/pkgs'; self.conda.mkdir(parents=True)
        self.packages = self.root/'packages'; self.packages.mkdir()
        self.calls = []
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        self.snapshot = {'snapshots':[]}
        for patch in [mock.patch.dict(os.environ, BROMIGOS_STORAGE_STATE=str(self.root/'state'), BASH_ENV='bad', LIBRARY='bad', NODE_OPTIONS='bad'),
                      mock.patch.object(A.Path, 'home', return_value=self.home),
                      mock.patch.object(A, 'PACKAGE_CACHE', self.packages),
                      mock.patch.object(A, 'PACMAN_LOCK', self.root/'db.lck'),
                      mock.patch.object(A, '_tool', side_effect=lambda name: dict(path='/usr/bin/'+name, device=1,inode=2,size=3,modified_ns=4)),
                      mock.patch.object(A, '_busy'), mock.patch.object(C, 'require_root'),
                      mock.patch.object(C, 'lock', side_effect=lambda _: contextlib.nullcontext()),
                      mock.patch.object(C.os, 'geteuid', return_value=self.uid), mock.patch.object(C.os, 'fchown'),
                      mock.patch.object(M, '_filesystems', return_value=[]),
                      mock.patch.object(A.I, '_read_mounts', return_value=[dict(target=str(self.root),uuid='test',fstype='ext4')]),
                      mock.patch.object(M, '_filesystem', return_value=dict(target=str(self.root),uuid='test',fstype='ext4',fsroot='/')),
                      mock.patch.object(K,'_inventory',return_value=self.snapshot),
                      mock.patch.object(C, 'command', side_effect=self.command),
                      contextlib.redirect_stdout(io.StringIO())]:
            self.stack.enter_context(patch)

    def command(self, argv, **kwargs):
        self.calls.append((argv,kwargs))
        if argv[0]=='du': return '4096 fixture'
        if 'config' in argv and 'pkgs_dirs' in argv:
            return json.dumps({'pkgs_dirs':[str(self.conda)], 'dry_run':False})
        return ''

    def test_user_caches_plan_and_apply_with_exact_scopes_and_clean_environment(self):
        plan = K.plan(caches=['npm','conda'])
        self.assertFalse(any('clean' in c[0] for c in self.calls))
        result = K.apply(plan['path'],yes=True)
        self.assertEqual(result['state'],'complete')
        clean=[(a,k) for a,k in self.calls if 'clean' in a]
        self.assertEqual(len(clean),2)
        npm,conda=clean
        self.assertEqual(npm[0][npm[0].index('--cache')+1],str(self.npm.parent))
        self.assertEqual(npm[0][npm[0].index('--prefix')+1],npm[1]['cwd'])
        self.assertIn('--logs-max=0',npm[0]); self.assertIn('--force',npm[0])
        self.assertIn('--tarballs',conda[0]); self.assertIn('--index-cache',conda[0]); self.assertIn('--logfiles',conda[0])
        self.assertFalse(set(conda[0]) & {'--all','--packages','--force-pkgs-dirs'})
        self.assertEqual(conda[1]['env']['CONDA_PKGS_DIRS'],str(self.conda))
        for _,kw in clean:
            self.assertFalse(set(kw['env']) & {'BASH_ENV','LIBRARY','NODE_OPTIONS','PYTHONPATH'})
            self.assertIsNotNone(kw['cwd'])
            self.assertNotEqual(kw['cwd'],str(self.home))
        self.assertEqual(conda[1]['env']['HOME'],conda[1]['cwd'])
        self.assertEqual(len(result['cache_results']),2)
        self.assertTrue(Path(result['log']).is_file())

    def test_conda_extra_configured_cache_stops_before_clean(self):
        plan = K.plan(caches=['conda'])
        def bad(argv,**kwargs):
            if 'pkgs_dirs' in argv: return json.dumps({'pkgs_dirs':[str(self.conda),'/unselected/cache']})
            return self.command(argv,**kwargs)
        with mock.patch.object(C,'command',side_effect=bad):
            with self.assertRaisesRegex(C.Error,'additional package caches'):
                K.apply(plan['path'],yes=True)
        self.assertFalse(any('clean' in c[0] for c in self.calls))
        self.assertEqual(C.read_journal(plan)['state'],'failed')

    def test_user_cache_never_runs_as_root_or_another_owner(self):
        plan=K.plan(caches=['npm'])
        for uid in (0,self.uid+1):
            with mock.patch.object(A.os,'geteuid',return_value=uid),self.assertRaisesRegex(C.Error,'owner'):
                K.apply(plan['path'],yes=True)
        self.assertIsNone(C.read_journal(plan))

    def test_conda_dry_run_cannot_report_success(self):
        plan=K.plan(caches=['conda'])
        def dry_run(argv, **kwargs):
            if 'pkgs_dirs' in argv:
                return json.dumps({'pkgs_dirs':[str(self.conda)],'dry_run':True})
            return self.command(argv, **kwargs)
        with mock.patch.object(C,'command',side_effect=dry_run),self.assertRaisesRegex(C.Error,'dry-run'):
            K.apply(plan['path'],yes=True)
        self.assertFalse(any('clean' in call[0] for call in self.calls))

    def test_user_and_system_plans_cannot_mix(self):
        with self.assertRaisesRegex(C.Error,'separate'): K.plan(caches=['npm','package-archives'])
        with self.assertRaisesRegex(C.Error,'separate'): K.plan(caches=['conda'],snapshots=['/some/snapshot'])

    def test_package_retention_defaults_three_and_never_all_versions(self):
        plan=K.plan(caches=['package-archives'])
        with mock.patch.object(A.os,'geteuid',return_value=0):
            result=K.apply(plan['path'],yes=True)
        command=next(a for a,_ in self.calls if '-r' in a)
        self.assertEqual(command,['/usr/bin/package-archives','-r','-k','3','-c',str(self.packages),'--nocolor'])
        self.assertEqual(result['state'],'complete')
        for keep in (0,-1,101,True):
            with self.assertRaisesRegex(C.Error,'between'): K.plan(caches=['package-archives'],keep_versions=keep)

    def test_missing_tools_changed_paths_and_nested_mounts_fail(self):
        plan=K.plan(caches=['npm'])
        self.npm.rename(self.npm.with_name('old')); self.npm.mkdir()
        with self.assertRaisesRegex(C.Error,'changed'): K.apply(plan['path'],yes=True)
        with mock.patch.object(M,'_filesystems',return_value=[self.conda/'nested']),self.assertRaisesRegex(C.Error,'mounted'):
            K.plan(caches=['conda'])
        with mock.patch.object(A,'_tool',side_effect=C.Error('Install npm')),self.assertRaisesRegex(C.Error,'Install'):
            K.plan(caches=['npm'])

    def test_conda_symlink_log_directory_never_followed(self):
        outside=self.root/'important'; outside.mkdir(); (outside/'keep').write_text('data')
        (self.conda/'.logs').symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(C.Error,'symlinks'): K.plan(caches=['conda'])
        self.assertEqual((outside/'keep').read_text(),'data')

    def test_remote_and_automount_cache_rejected_before_path_access(self):
        for fstype in ('autofs','nfs4'):
            with mock.patch.object(A.I,'_read_mounts',return_value=[dict(target=str(self.home),fstype=fstype)]),mock.patch.object(Path,'is_symlink',side_effect=AssertionError('path touched')):
                with self.assertRaisesRegex(C.Error,'local cache'): K.plan(caches=['npm'])

    def test_npm_root_mount_and_btrfs_subvolumes_are_refused(self):
        with mock.patch.object(M,'_filesystems',return_value=[self.npm]),self.assertRaisesRegex(C.Error,'mount point'):
            K.plan(caches=['npm'])
        item=K.plan(caches=['npm'])['items'][0]
        item['filesystem']['fstype']='btrfs'
        subvol=self.npm/'nested'; subvol.mkdir()
        original=Path.stat
        def stat_path(path,*args,**kwargs):
            if path==subvol:
                return mock.Mock(st_ino=256,st_mode=0o40755)
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'lstat',stat_path),self.assertRaisesRegex(C.Error,'subvolume'):
            A._recursive_scopes(item)
        subvol.rmdir()
        def root_stat(path,*args,**kwargs):
            if path==self.npm:
                return mock.Mock(st_ino=256,st_mode=0o40755)
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'stat',root_stat),self.assertRaisesRegex(C.Error,'subvolume'):
            A._recursive_scopes(item)

    def test_busy_client_and_native_failure_are_logged_without_replay(self):
        plan=K.plan(caches=['npm'])
        with mock.patch.object(A,'_busy',side_effect=C.Error('client running')):
            with self.assertRaisesRegex(C.Error,'client'): K.apply(plan['path'],yes=True)
        self.assertEqual(C.read_journal(plan)['state'],'preflight-failed')
        original=self.command
        def fail(argv,**kw):
            if 'clean' in argv: raise C.Error('native cleanup failed')
            return original(argv,**kw)
        with mock.patch.object(C,'command',side_effect=fail):
            with self.assertRaisesRegex(C.Error,'native'): K.apply(plan['path'],yes=True)
        result=C.read_journal(plan)
        self.assertIn('native',Path(result['log']).read_text())
        with self.assertRaisesRegex(C.Error,'journal'): K.apply(plan['path'],yes=True)


class BusyDetection(unittest.TestCase):
    def test_node_npm_client_and_pacman_lock_are_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); proc=root/'12345'; proc.mkdir()
            (proc/'comm').write_text('node\n'); (proc/'cmdline').write_bytes(b'node\0/usr/bin/npm\0exec\0')
            with mock.patch.object(A,'PROC',root):
                with self.assertRaisesRegex(C.Error,'12345'): A._busy('npm',proc.stat().st_uid)
            (proc/'comm').write_text('unrelated'); (proc/'cmdline').write_bytes(b'unrelated\0')
            lock=root/'lock'; lock.touch()
            with mock.patch.object(A,'PROC',root),mock.patch.object(A,'PACMAN_LOCK',lock):
                with self.assertRaisesRegex(C.Error,'Pacman'): A._busy('package-archives',0)


@unittest.skipUnless(__import__('shutil').which('npm'), 'npm is required for sandbox integration')
class NativeNpm(unittest.TestCase):
    def test_real_npm_removes_only_sandbox_content_cache(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); cache=root/'.npm/_cacache'; cache.mkdir(parents=True)
            (cache/'cached-blob').write_text('cached download')
            npx=root/'.npm/_npx'; npx.mkdir(); (npx/'keep').write_text('installed tool')
            config=root/'.npmrc'; config.write_text('registry=https://example.invalid/\n')
            tool=Path(shutil.which('npm')).resolve()
            item=dict(cache='npm',path=str(cache),home=str(root),tool={'path':str(tool)})
            with mock.patch.object(A,'validate'):
                result=A.clean(item)
            self.assertFalse(cache.exists())
            self.assertEqual((npx/'keep').read_text(),'installed tool')
            self.assertIn('example.invalid',config.read_text())
            self.assertEqual(result['allocated_after'],0)


if __name__=='__main__': unittest.main()
