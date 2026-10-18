"""Splash changes against a temporary filesystem and fake GRUB commands only."""
import json
import signal
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))
import bromigos_splash as splash


class SplashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bromigos-splash-test-')
        self.addCleanup(self.temp.cleanup)
        self.paths = splash.Paths(Path(self.temp.name))
        self.put('/etc/default/grub', 'GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="quiet iommu=pt"\nGRUB_CMDLINE_LINUX="rootfstype=btrfs"\n')
        self.put('/boot/grub/grub.cfg', '# original boot menu\n')
        self.put('/etc/plymouth/plymouthd.conf', '# keep this comment\n[Daemon]\nTheme=bgrt\nShowDelay=2\n')
        self.put('/usr/share/plymouth/plymouthd.defaults', '[Daemon]\nTheme=bgrt\n')
        self.put('/usr/share/plymouth/themes/bromigos/bromigos.plymouth', '[Plymouth Theme]\nName=Bromigos\n')
        for program in ('/usr/bin/plymouth', '/usr/bin/plymouthd'):
            self.put(program, '# fake program; never executed\n').chmod(0o755)
        self.put('/usr/lib/plymouth/script.so', 'fake plugin')
        self.put('/proc/cmdline', 'quiet root=UUID=example\n')
        self.calls = []
        self.failure = None
        self.hook = None
        self.original = {p: p.read_bytes() for p in (self.paths.grub, self.paths.plymouth, self.paths.generated)}
        self.root = patch.object(splash, '_require_root')
        self.root.start()
        self.addCleanup(self.root.stop)
        # Any accidentally unmocked subprocess is a test failure, never a host command.
        self.commands = patch.object(splash.subprocess, 'run', side_effect=AssertionError('Real commands are forbidden'))
        self.commands.start()
        self.addCleanup(self.commands.stop)

    def put(self, path, text):
        path = self.paths.at(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def runner(self, argv, log):
        self.calls.append(argv)
        log.write_text(log.read_text() + Path(argv[0]).name + '\n')
        if self.failure == Path(argv[0]).name:
            raise splash.Error('injected command failure')
        if argv[0] == '/usr/bin/grub-mkconfig':
            self.assertEqual(argv[1], '-o')
            self.assertEqual(Path(argv[2]).parent, self.paths.generated.parent)
            Path(argv[2]).write_text('menuentry test {\n linux /vmlinuz-linux quiet splash\n}\n')
        if self.hook:
            self.hook(argv)

    def change(self, action):
        return splash.change(action, self.paths, self.runner)

    def assertOriginal(self):
        for path, value in self.original.items():
            self.assertEqual(path.read_bytes(), value, path)

    def test_status_reads_saved_and_running_settings_without_commands_or_writes(self):
        result = splash.status(self.paths)
        self.assertEqual(result['theme'], 'bgrt')
        self.assertTrue(result['theme_installed'])
        self.assertTrue(result['grub_supported'])
        self.assertFalse(result['configured_splash'])
        self.assertFalse(result['current_kernel_splash'])
        self.assertFalse(self.paths.state_dir.exists())
        self.assertOriginal()

    def test_on_preserves_settings_and_checks_a_temporary_menu(self):
        result = self.change('on')
        self.assertTrue(result['changed'])
        self.assertIn(self.original[self.paths.grub].decode(), self.paths.grub.read_text())
        self.assertIn('ShowDelay=2', self.paths.plymouth.read_text())
        self.assertIn('Theme=bromigos', self.paths.plymouth.read_text())
        self.assertEqual([Path(c[0]).name for c in self.calls], ['grub-mkconfig', 'grub-script-check'])
        self.assertFalse(Path(self.calls[0][2]).exists())
        self.assertTrue(splash.status(self.paths)['enabled'])
        self.assertFalse(splash.status(self.paths)['current_kernel_splash'])
        backup = Path(result['backup'])
        self.assertEqual((backup / 'grub.before').read_bytes(), self.original[self.paths.grub])
        self.assertEqual(stat.S_IMODE((backup / 'grub.before').stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.paths.state.stat().st_mode), 0o600)

    def test_on_is_idempotent(self):
        self.change('on')
        self.calls.clear()
        self.assertFalse(self.change('on')['changed'])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.paths.grub.read_text().count(splash.GRUB_BLOCK), 1)

    def test_off_restores_original_config_bytes(self):
        self.change('on')
        self.change('off')
        self.assertEqual(self.paths.grub.read_bytes(), self.original[self.paths.grub])
        self.assertEqual(self.paths.plymouth.read_bytes(), self.original[self.paths.plymouth])
        self.assertFalse(splash.status(self.paths)['enabled'])
        self.assertFalse(self.change('off')['changed'])

    def test_off_preserves_later_unrelated_edits(self):
        self.change('on')
        self.paths.grub.write_text(self.paths.grub.read_text().replace('GRUB_TIMEOUT=5', 'GRUB_TIMEOUT=9'))
        self.paths.plymouth.write_text(self.paths.plymouth.read_text().replace('ShowDelay=2', 'ShowDelay=4'))
        self.change('off')
        self.assertIn('GRUB_TIMEOUT=9', self.paths.grub.read_text())
        self.assertNotIn(splash.GRUB_BEGIN, self.paths.grub.read_text())
        self.assertIn('ShowDelay=4', self.paths.plymouth.read_text())
        self.assertIn('Theme=bgrt', self.paths.plymouth.read_text())

    def test_off_preserves_new_line_after_original_theme_without_final_newline(self):
        self.paths.plymouth.write_text('[Daemon]\nTheme=bgrt')
        self.change('on')
        self.paths.plymouth.write_text(self.paths.plymouth.read_text() + 'ShowDelay=4\n')
        self.change('off')
        self.assertEqual(self.paths.plymouth.read_text(), '[Daemon]\nTheme=bgrt\nShowDelay=4\n')

    def test_off_preserves_preexisting_splash_and_theme(self):
        self.put('/etc/default/grub', 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n')
        self.put('/etc/plymouth/plymouthd.conf', '[Daemon]\nTheme=bromigos\n')
        self.change('on')
        self.change('off')
        self.assertEqual(self.paths.grub.read_text(), 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n')
        self.assertTrue(splash.status(self.paths)['enabled'])

    def test_missing_plymouth_config_is_created_then_removed(self):
        self.paths.plymouth.unlink()
        self.change('on')
        self.assertIn('[Daemon]', self.paths.plymouth.read_text())
        self.change('off')
        self.assertFalse(self.paths.plymouth.exists())

    def test_configuration_without_theme_or_final_newline(self):
        for before in ('# defaults only', '[Daemon]', '[Daemon]\nShowDelay=1\n[Other]\nValue=2\n'):
            with self.subTest(before=before):
                self.paths.plymouth.write_text(before)
                self.change('on')
                self.assertEqual(splash.status(self.paths)['theme'], 'bromigos')
                self.change('off')
                self.assertEqual(self.paths.plymouth.read_text(), before)

    def test_generation_or_validation_failure_restores_every_input(self):
        for command in ('grub-mkconfig', 'grub-script-check'):
            with self.subTest(command=command):
                self.failure = command
                with self.assertRaisesRegex(splash.Error, 'Previous configuration restored'):
                    self.change('on')
                self.assertOriginal()
                self.assertFalse(self.paths.state.exists())
                self.assertEqual(list(self.paths.generated.parent.glob('.bromigos-splash-*')), [])

    def test_state_save_failure_restores_generated_menu_too(self):
        write = splash._write
        def fail_state(path, value, **kwargs):
            if path == self.paths.state:
                raise OSError('injected state write failure')
            return write(path, value, **kwargs)
        with patch.object(splash, '_write', side_effect=fail_state):
            with self.assertRaisesRegex(splash.Error, 'Previous configuration restored'):
                self.change('on')
        self.assertOriginal()

    def test_failed_disable_preserves_enabled_state(self):
        self.change('on')
        before = {p: p.read_bytes() for p in (*self.original, self.paths.state)}
        self.failure = 'grub-script-check'
        with self.assertRaises(splash.Error):
            self.change('off')
        for path, value in before.items():
            self.assertEqual(path.read_bytes(), value)

    def test_concurrent_edit_is_retained_and_reported(self):
        def edit(argv):
            if argv[0] == '/usr/bin/grub-mkconfig':
                self.paths.grub.write_text(self.paths.grub.read_text() + '# external edit\n')
        self.hook = edit
        with self.assertRaisesRegex(splash.Error, 'could not be restored'):
            self.change('on')
        self.assertTrue(self.paths.grub.read_text().endswith('# external edit\n'))
        self.assertEqual(self.paths.generated.read_bytes(), self.original[self.paths.generated])
        self.assertEqual(self.paths.plymouth.read_bytes(), self.original[self.paths.plymouth])

    def test_edited_owned_block_refused_without_overwriting(self):
        self.change('on')
        text = self.paths.plymouth.read_text().replace('Theme=bromigos', 'Theme=user-choice')
        self.paths.plymouth.write_text(text)
        self.calls.clear()
        with self.assertRaisesRegex(splash.Error, 'was edited'):
            self.change('off')
        self.assertEqual(self.paths.plymouth.read_text(), text)
        self.assertEqual(self.calls, [])

    def test_changed_theme_section_or_duplicate_assignment_refused(self):
        self.change('on')
        original = self.paths.plymouth.read_text()
        for changed in (original.replace('[Daemon]\n', '[Daemon]\n[Other]\n'), original + 'Theme=other\n'):
            with self.subTest(changed=changed):
                self.paths.plymouth.write_text(changed)
                self.calls.clear()
                for action in ('on', 'off'):
                    with self.assertRaises(splash.Error):
                        self.change(action)
                    self.assertEqual(self.paths.plymouth.read_text(), changed)
                self.assertEqual(self.calls, [])

    def test_other_bootloader_and_missing_grub_refused(self):
        loader = self.paths.at('/sys/firmware/efi/efivars/LoaderInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f')
        loader.parent.mkdir(parents=True)
        loader.write_bytes(b'\x07\0\0\0' + 'systemd-boot\0'.encode('utf-16-le'))
        with self.assertRaisesRegex(splash.Error, 'not GRUB'):
            self.change('on')
        self.assertFalse(self.paths.state_dir.exists())
        loader.unlink()
        self.paths.generated.unlink()
        with self.assertRaisesRegex(splash.Error, 'Only GRUB'):
            self.change('on')

    def test_grub_dropins_refused_before_writes(self):
        self.put('/etc/default/grub.d/override.cfg', 'GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n')
        with self.assertRaisesRegex(splash.Error, 'drop-in'):
            self.change('on')
        self.assertOriginal()
        self.assertFalse(self.paths.state_dir.exists())

    def test_symlink_and_world_writable_inputs_refused(self):
        original = self.paths.grub.read_bytes()
        elsewhere = self.put('/elsewhere', original.decode())
        self.paths.grub.unlink()
        self.paths.grub.symlink_to(elsewhere)
        with self.assertRaises((splash.Error, OSError)):
            self.change('on')
        self.assertEqual(elsewhere.read_bytes(), original)
        self.paths.grub.unlink()
        self.paths.grub.write_bytes(original)
        self.paths.grub.chmod(0o666)
        with self.assertRaisesRegex(splash.Error, 'not writable'):
            self.change('on')
        self.assertEqual(self.calls, [])

    def test_duplicate_theme_config_refused(self):
        self.put('/etc/plymouth/plymouthd.conf', '[Daemon]\nTheme=bgrt\nTheme=other\n')
        with self.assertRaisesRegex(splash.Error, 'duplicate'):
            self.change('on')
        self.assertEqual(self.calls, [])

    def test_nonroot_mutation_requires_explicit_sudo(self):
        self.root.stop()
        with patch.object(splash.os, 'geteuid', return_value=1234):
            with self.assertRaisesRegex(splash.Error, 'sudo bromigos splash on'):
                self.change('on')
        self.assertFalse(self.paths.state_dir.exists())

    def test_dynamic_shell_value_not_executed_by_status(self):
        self.put('/etc/default/grub', 'GRUB_CMDLINE_LINUX_DEFAULT="$(dangerous-command) quiet"\n')
        result = splash.status(self.paths)
        self.assertIsNone(result['configured_splash'])
        self.assertFalse(self.paths.state_dir.exists())

    def test_exported_kernel_assignment_still_rejects_disabled_splash(self):
        self.put('/etc/default/grub', 'export GRUB_CMDLINE_LINUX_DEFAULT="quiet plymouth.enable=0"\n')
        self.assertEqual(splash.status(self.paths)['configured_disabled'], ['plymouth.enable=0'])
        with self.assertRaisesRegex(splash.Error, 'explicitly disables'):
            self.change('on')
        self.assertEqual(self.calls, [])

    def test_dynamic_or_conditional_kernel_assignments_refused(self):
        for text in ('export GRUB_CMDLINE_LINUX_DEFAULT="$CUSTOM quiet"\n',
                     'if true; then GRUB_CMDLINE_LINUX="plymouth.enable=0"; fi\n'):
            with self.subTest(text=text):
                self.put('/etc/default/grub', text)
                self.assertIsNone(splash.status(self.paths)['configured_splash'])
                with self.assertRaisesRegex(splash.Error, 'Dynamic GRUB'):
                    self.change('on')
        self.assertEqual(self.calls, [])

    def test_missing_runtime_or_plugin_refuses_enable(self):
        for name in ('/usr/bin/plymouth', '/usr/bin/plymouthd', '/usr/lib/plymouth/script.so'):
            with self.subTest(name=name):
                path = self.paths.at(name)
                value, mode = path.read_bytes(), path.stat().st_mode
                path.unlink()
                with self.assertRaisesRegex(splash.Error, 'Install bromigos-settings and Plymouth'):
                    self.change('on')
                self.assertOriginal()
                self.assertFalse(splash.status(self.paths)['plymouth_installed'])
                path.write_bytes(value)
                path.chmod(mode)
        self.assertEqual(self.calls, [])

    def test_explicit_disable_flags_reported_and_refused(self):
        for flag in ('plymouth.enable=0', 'plymouth.enable=false', 'nosplash', 'splash=verbose', 'single'):
            with self.subTest(flag=flag):
                self.put('/etc/default/grub', f'GRUB_CMDLINE_LINUX_DEFAULT="quiet {flag}"\n')
                self.put('/proc/cmdline', f'quiet splash {flag}\n')
                result = splash.status(self.paths)
                self.assertEqual(result['configured_disabled'], [flag])
                self.assertEqual(result['current_kernel_disabled'], [flag])
                self.assertFalse(result['enabled'])
                with self.assertRaisesRegex(splash.Error, 'explicitly disables'):
                    self.change('on')
        self.assertEqual(self.calls, [])

    def test_silent_flag_is_recognised_and_nolog_does_not_disable_graphics(self):
        self.put('/proc/cmdline', 'quiet splash=silent plymouth.nolog\n')
        result = splash.status(self.paths)
        self.assertTrue(result['current_kernel_graphical'])
        self.assertEqual(result['current_kernel_disabled'], [])

    def test_keyboard_interrupt_rolls_back_and_restores_signal_handlers(self):
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        def interrupt(_argv):
            raise KeyboardInterrupt
        self.hook = interrupt
        with self.assertRaisesRegex(splash.Error, 'interrupted.*Previous configuration restored'):
            self.change('on')
        self.assertOriginal()
        self.assertFalse(self.paths.state.exists())
        for sig, handler in before.items():
            self.assertEqual(signal.getsignal(sig), handler)

    def test_sigterm_handler_rolls_back_without_sending_real_signal(self):
        before = signal.getsignal(signal.SIGTERM)
        def interrupt(_argv):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        self.hook = interrupt
        with self.assertRaisesRegex(splash.Error, 'interrupted by signal.*Previous configuration restored'):
            self.change('on')
        self.assertOriginal()
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)


if __name__ == '__main__':
    unittest.main()
