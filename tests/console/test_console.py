"""Persistent console configuration using disposable files, never a real TTY."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import bromigos_console as console


class Console(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / 'vconsole.conf'
        self.fonts = self.root / 'fonts'; self.fonts.mkdir()
        self.require_root = console._require_root
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        for patch in (mock.patch.object(console, 'CONFIG', self.config),
                      mock.patch.object(console, 'LOCK', self.root / 'console.lock'),
                      mock.patch.object(console, 'FONTS', self.fonts),
                      mock.patch.object(console, '_require_root')):
            self.stack.enter_context(patch)
        for font in console.SIZES.values():
            (self.fonts / (font + '.psf.gz')).write_bytes(b'fixture font')

    def test_status_reads_saved_configuration_without_writing(self):
        with mock.patch.object(console.os, 'geteuid', return_value=1000):
            self.assertEqual(console.status()['size'], 'default')
            self.assertFalse(self.config.exists())
            self.config.write_text('KEYMAP=us\nFONT="ter-v24n"\n')
            before = self.config.read_bytes()
            result = console.status()
        self.assertEqual(result['size'], 'medium')
        self.assertEqual(result['available_sizes'], ['small', 'medium', 'large'])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.root / 'console.lock').exists())

    def test_font_write_preserves_keyboard_other_options_comments_and_mode(self):
        before = '# Existing setup\nKEYMAP="us"\nKEYMAP_TOGGLE=de\nFONT=old\nFONT_MAP=\nOTHER="two words"\n'
        self.config.write_text(before); self.config.chmod(0o640)
        result = console.set_font('large')
        self.assertTrue(result['changed'])
        self.assertEqual(self.config.read_text(), before.replace('FONT=old\n', '') + 'FONT=ter-v32n\n')
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        inode = self.config.stat().st_ino
        self.assertFalse(console.set_font('large')['changed'])
        self.assertEqual(self.config.stat().st_ino, inode)

    def test_default_removes_only_font_without_requiring_terminus(self):
        self.config.write_text('KEYMAP=us\nFONT=old\nFONT_UNIMAP=custom\n')
        for path in self.fonts.iterdir(): path.unlink()
        console.set_font('default')
        self.assertEqual(self.config.read_text(), 'KEYMAP=us\nFONT_UNIMAP=custom\n')

    def test_missing_config_is_created_and_missing_newline_is_handled(self):
        console.set_font('small')
        self.assertEqual(self.config.read_text(), 'FONT=ter-v16n\n')
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o644)
        self.config.write_text('KEYMAP=us')
        console.set_font('medium')
        self.assertEqual(self.config.read_text(), 'KEYMAP=us\nFONT=ter-v24n\n')

    def test_nonroot_and_missing_font_leave_configuration_unchanged(self):
        self.config.write_text('KEYMAP=us\n')
        with mock.patch.object(console, '_require_root', self.require_root), mock.patch.object(console.os, 'geteuid', return_value=1000), self.assertRaisesRegex(console.Error, 'sudo'):
            console.set_font('large')
        (self.fonts / 'ter-v32n.psf.gz').unlink()
        with self.assertRaisesRegex(console.Error, 'terminus-font'):
            console.set_font('large')
        self.assertEqual(self.config.read_text(), 'KEYMAP=us\n')

    def test_existing_font_maps_are_preserved_and_need_review_before_replacement(self):
        for key in ('FONT_MAP', 'FONT_UNIMAP'):
            before = 'KEYMAP=us\nFONT=old\n' + key + '=custom\n'
            self.config.write_text(before)
            with self.subTest(key=key), self.assertRaisesRegex(console.Error, 'overrides'):
                console.set_font('medium')
            self.assertEqual(self.config.read_text(), before)

    def test_unexpected_lock_owner_and_file_type_are_refused(self):
        for mode, uid in ((0o10600, os.geteuid()), (0o100600, os.geteuid() + 1)):
            with mock.patch.object(console.os, 'fstat', return_value=mock.Mock(st_mode=mode, st_uid=uid)):
                with self.assertRaisesRegex(console.Error, 'root-owned'):
                    console.set_font('small')
            self.assertFalse(self.config.exists())

    def test_symlinks_and_multiline_or_duplicate_assignments_are_refused(self):
        outside = self.root / 'outside'; outside.write_text('KEYMAP=us\n')
        self.config.symlink_to(outside)
        with self.assertRaisesRegex(console.Error, 'non-symlink'):
            console.set_font('small')
        self.assertEqual(outside.read_text(), 'KEYMAP=us\n')
        self.config.unlink()
        for content in ('KEYMAP="us\nfr"\n', 'KEYMAP=us\\\nfr\n', 'KEYMAP=us\nFONT=a\nFONT=b\n', 'source other\n'):
            self.config.write_text(content)
            with self.subTest(content=content), self.assertRaises(console.Error):
                console.set_font('small')
            self.assertEqual(self.config.read_text(), content)

    def test_failed_atomic_replace_preserves_old_file_and_cleans_temporary(self):
        self.config.write_text('KEYMAP=us\n')
        with mock.patch.object(console.os, 'replace', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError): console.set_font('small')
        self.assertEqual(self.config.read_text(), 'KEYMAP=us\n')
        self.assertEqual(list(self.root.glob('.vconsole-*')), [])

    def test_concurrent_edit_is_not_overwritten(self):
        self.config.write_text('KEYMAP=us\n')
        real_read = console._read
        calls = 0
        def changed():
            nonlocal calls
            calls += 1
            if calls == 2: self.config.write_text('KEYMAP=fr\n')
            return real_read()
        with mock.patch.object(console, '_read', side_effect=changed), self.assertRaisesRegex(console.Error, 'changed while saving'):
            console.set_font('small')
        self.assertEqual(self.config.read_text(), 'KEYMAP=fr\n')

    def test_cli_json_and_saved_message_distinguish_next_boot_from_live_state(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output): self.assertEqual(console.main(['status', '--json']), 0)
        self.assertEqual(json.loads(output.getvalue())['size'], 'default')
        output = io.StringIO()
        with contextlib.redirect_stdout(output): self.assertEqual(console.main(['font', 'medium']), 0)
        self.assertIn('after reboot', output.getvalue())
        self.assertIn('initramfs', output.getvalue())


if __name__ == '__main__':
    unittest.main()
