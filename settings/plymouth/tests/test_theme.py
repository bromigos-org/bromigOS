import unittest

from harness import LIBRARY, Theme


@unittest.skipUnless(LIBRARY.is_file(), 'Plymouth script interpreter is not installed')
class ThemeTests(unittest.TestCase):
    def test_boot_keeps_progress_and_no_action_label(self):
        with Theme() as theme:
            self.assertIsNone(theme.get('action.image.text', text=True))
            theme.run('progress(10, 0.5);')
            width = theme.get('fill.image.width')
            self.assertEqual(width, int(theme.get('line_w') * 0.5))
            start = theme.get('fill.x')
            theme.run('refresh();')
            self.assertEqual(theme.get('fill.x'), start)
            self.assertEqual(theme.get('fill.image.width'), width)
            self.assertGreater(theme.get('ring.image.angle'), 0)

    def test_shutdown_and_restart_show_activity_without_progress(self):
        for mode, label in [('shutdown', 'SHUTTING DOWN'), ('reboot', 'RESTARTING')]:
            with self.subTest(mode=mode), Theme(mode) as theme:
                self.assertEqual(theme.get('action.image.text', text=True), label)
                width = theme.get('fill.image.width')
                self.assertAlmostEqual(width, theme.get('line_w') * 0.18)
                start = theme.get('fill.x')
                theme.run('progress(99, 0.99); refresh();')
                self.assertEqual(theme.get('fill.image.width'), width)
                self.assertGreater(theme.get('fill.x'), start)
                positions = []
                for _ in range(350):
                    theme.run('refresh();')
                    positions.append(theme.get('fill.x'))
                    self.assertGreaterEqual(theme.get('fill.x'), start)
                    self.assertLessEqual(theme.get('fill.x') + width, start + theme.get('line_w'))
                travel = theme.get('line_w') - width
                self.assertGreater(max(positions) - min(positions), travel * 0.95)
                self.assertGreater(positions[60], positions[140])

    def test_boot_password_message_and_normal_callbacks_are_preserved(self):
        with Theme() as theme:
            theme.run('display_message("Checking disks"); password("Disk passphrase", 3);')
            self.assertEqual(theme.get('message.image.text', text=True), 'Checking disks')
            self.assertEqual(theme.get('prompt.image.text', text=True), 'PASSPHRASE')
            self.assertEqual(theme.get('dots.image.text', text=True), '•••')
            theme.run('normal();')
            self.assertEqual(theme.get('prompt.image.text', text=True), '')
            self.assertEqual(theme.get('dots.image.text', text=True), '')

    def test_shutdown_messages_have_space_below_the_action(self):
        for width, height in [(800, 600), (1280, 720), (2560, 1440)]:
            with self.subTest(size=(width, height)), Theme('shutdown', width, height) as theme:
                theme.run('display_message("Stopping services");')
                self.assertEqual(theme.get('message.image.text', text=True), 'Stopping services')
                self.assertGreater(theme.get('message.y'), theme.get('action.y') + theme.get('action.image.height'))
                self.assertLess(theme.get('message.y') + theme.get('message.image.height'), height)

    def test_other_modes_do_not_claim_shutdown_or_restart(self):
        for mode in ('updates', 'system-upgrade', 'firmware-upgrade', 'unknown'):
            with self.subTest(mode=mode), Theme(mode) as theme:
                self.assertIsNone(theme.get('action.image.text', text=True))


if __name__ == '__main__':
    unittest.main()
