import contextlib
import io
import os
import unittest
from unittest.mock import patch

import bromigos_storage_display as D


class DisplayTest(unittest.TestCase):
    def render(self, function, result):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), patch.object(D.shutil, 'get_terminal_size', return_value=os.terminal_size((72, 24))):
            function(result)
        return stream.getvalue()

    def test_grouped_filesystem_space_once_with_all_paths(self):
        data = {'drives': [{'path': '/dev/test', 'model': 'Example SSD', 'size': 1024**4}],
                'filesystems': [{'fstype': 'btrfs', 'physical_drives': ['/dev/test'],
                                 'mounts': [{'path': '/'}, {'path': '/home'}, {'path': '/var/log'}],
                                 'total_bytes': 100 * 1024**3, 'used_bytes': 60 * 1024**3, 'free_bytes': 40 * 1024**3}],
                'errors': [], 'operations': []}
        output = self.render(D.show_status, data)
        self.assertIn('1 drive · 1 mounted filesystem', output)
        self.assertEqual(output.count('40.0 GiB available'), 1)
        self.assertIn('60% used', output)
        self.assertIn('Paths: /, /home, /var/log', output)
        self.assertNotIn('\033', output)
        self.assertIn('No saved CLI operations', output)

    def test_shared_multi_device_filesystem_is_not_repeated(self):
        data = {'drives': [{'path': '/dev/a'}, {'path': '/dev/b'}],
                'filesystems': [{'fstype': 'btrfs', 'physical_drives': ['/dev/a', '/dev/b'],
                                 'mounts': [{'path': '/data'}], 'used_bytes': 50, 'free_bytes': 50}]}
        output = self.render(D.show_status, data)
        self.assertEqual(output.count('50.0 B available'), 1)
        self.assertIn('shared across drives', output)

    def test_unknown_space_not_zero_and_control_characters_removed(self):
        data = {'drives': [{'path': '/dev/a', 'model': 'Bad\033[2J'}],
                'filesystems': [{'physical_drives': ['/dev/a'], 'mounts': [{'path': '/data'}]}]}
        output = self.render(D.show_status, data)
        self.assertIn('Space unavailable', output)
        self.assertNotIn('0.0 B available', output)
        self.assertNotIn('\033', output)

    def test_cleanup_unavailable_counts_and_exact_paths(self):
        data = {'candidates': [], 'snapshots': [
            {'provider': 'snapper', 'source_path': '/home', 'status': 'unavailable', 'count': None, 'detail': 'Check access'},
            {'provider': 'btrbk', 'source_path': '/data/@home', 'status': 'present', 'count': 1,
             'candidates': [{'path': '/data/snaps/@home.20260101T0000'}]}]}
        output = self.render(D.show_cleanup, data)
        self.assertIn('nothing removed', output)
        self.assertIn('snapper · /home · unavailable', output)
        self.assertIn('/data/snaps/@home.20260101T0000', output)
        self.assertIn('--snapshot', output)
        self.assertNotIn('0 snapshots', output)

    def test_cleanup_result_reports_measured_delta_and_new_snapshot(self):
        output = self.render(D.show_cleanup_result, {
            'state': 'complete', 'completed': ['/old'], 'log': '/plan.log',
            'before': [{'filesystem_uuid': 'id', 'free_bytes': 2 * 1024**3}],
            'after': [{'filesystem_uuid': 'id', 'path': '/', 'free_bytes': 3 * 1024**3}],
            'remaining_snapshots': {'snapshots': [{'provider': 'btrbk', 'source_path': '/data/@home', 'status': 'present', 'count': 1}]},
            'new_snapshot_paths': ['/data/snaps/new']})
        self.assertIn('1 item processed', output)
        self.assertIn('+1.0 GiB since cleanup', output)
        self.assertIn('/data/snaps/new', output)
        self.assertIn('outside the saved plan', output)

    def test_failed_cleanup_shows_reason_and_uncertain_path(self):
        output = self.render(D.show_cleanup_result, {
            'state': 'failed', 'error': 'Filesystem changed', 'active_path': '/old\033[2J',
            'completed': [], 'log': '/plan.log'})
        self.assertIn('Stopped: Filesystem changed', output)
        self.assertIn('Inspect: /old?', output)
        self.assertNotIn('\033', output)
