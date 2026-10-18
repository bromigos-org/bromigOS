"""Real rsync against temporary files; no device, mount or privilege operations."""
import contextlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import bromigos_storage_common as C
import bromigos_storage_migration as M


@unittest.skipUnless(shutil.which('rsync'), 'rsync is not installed')
class RsyncIntegration(unittest.TestCase):
    def test_interrupted_copy_resumes_and_verifies_without_changing_originals(self):
        with tempfile.TemporaryDirectory(prefix='bromigos-rsync-fixture-') as temporary:
            root = Path(temporary).resolve()
            source = root / 'source'
            destination = root / 'destination'
            source.mkdir()
            original = source / 'data.txt'
            original.write_bytes(b'original fixture data\n')
            os.link(original, source / 'hardlink.txt')
            original_bytes = original.read_bytes()
            original_identity = (original.stat().st_dev, original.stat().st_ino)
            real_command = C.command
            commands = []

            def filesystem(path):
                self.assertTrue(Path(path).resolve().is_relative_to(root))
                return {'target': str(root), 'uuid': 'temporary-fixture',
                        'fstype': 'ext4', 'fsroot': '/'}

            def temporary_rsync_only(argv, **kwargs):
                # Every subprocess must be rsync with both operands in this fixture.
                self.assertEqual(Path(argv[0]).name, 'rsync')
                self.assertEqual(argv[-3], '--')
                for operand in argv[-2:]:
                    path = Path(operand).resolve()
                    self.assertTrue(path.is_relative_to(root))
                    self.assertNotEqual(path, root)
                self.assertEqual(Path(argv[-2]).resolve(), source)
                self.assertEqual(Path(argv[-1]).resolve(), destination)
                commands.append(list(argv))
                return real_command(argv, **kwargs)

            with mock.patch.dict(os.environ, {'BROMIGOS_STORAGE_STATE': str(root / 'state')}), \
                    mock.patch.object(M, '_filesystems', return_value=[]), \
                    mock.patch.object(M, '_filesystem', side_effect=filesystem), \
                    mock.patch.object(C, 'require_root'), \
                    mock.patch.object(C, 'lock', side_effect=lambda _: contextlib.nullcontext()), \
                    mock.patch.object(C, 'command', side_effect=temporary_rsync_only):
                record = M.plan([{'source': str(source), 'destination': str(destination)}])
                real_copy = M._copy

                def interrupted(move, checksum=False):
                    real_copy(move, checksum=checksum)
                    raise KeyboardInterrupt()

                # Interrupt between a completed rsync pass and journal completion.
                with mock.patch.object(M, '_copy', side_effect=interrupted):
                    with self.assertRaises(KeyboardInterrupt):
                        M.run(record['path'])
                self.assertEqual(C.read_journal(record)['state'], 'copy-failed')
                self.assertEqual(M.run(record['path'], resume=True)['state'], 'staged')
                verified = M.verify(record['path'])
                self.assertEqual(verified['state'], 'verified')
                self.assertTrue(verified['originals_retained'])

            self.assertEqual(len(commands), 3)
            self.assertIn('--checksum', commands[-1])
            self.assertIn('--dry-run', commands[-1])
            self.assertEqual(original.read_bytes(), original_bytes)
            self.assertEqual((original.stat().st_dev, original.stat().st_ino), original_identity)
            self.assertEqual((destination / 'data.txt').read_bytes(), original_bytes)
            self.assertEqual((destination / 'data.txt').stat().st_ino,
                             (destination / 'hardlink.txt').stat().st_ino)
            self.assertNotEqual((destination / 'data.txt').stat().st_ino,
                                original.stat().st_ino)


if __name__ == '__main__':
    unittest.main()
