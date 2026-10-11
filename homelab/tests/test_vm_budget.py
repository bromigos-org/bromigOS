"""The VM keeper rejects desktop-exhausting allocations before creating guests."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

path = Path(__file__).resolve().parents[2] / 'test/vm/vm-keeper.py'
spec = importlib.util.spec_from_file_location('vm_keeper', path)
keeper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keeper)


class BudgetTests(unittest.TestCase):
    def check(self, argv, available=18, cap='8'):
        with mock.patch.dict(keeper.os.environ, {'BROMIGOS_VM_MAX_MEM_GIB': cap}), mock.patch.object(keeper.os, 'scandir', return_value=[]), mock.patch.object(keeper.subprocess, 'check_output', return_value=f'Mem: 31 10 10 0 10 {available}\n'):
            keeper.resource_check(argv)

    def test_oversized_memory_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'budget exceeded'):
            self.check(['qemu-system-x86_64', '-m', '28672', '-smp', '4'])

    def test_hotplug_and_repeated_sizes_count_maximum(self):
        with self.assertRaisesRegex(RuntimeError, 'budget exceeded'):
            self.check(['qemu', '-m', '2G', '-m', 'size=2G,maxmem=28G'])
        with self.assertRaisesRegex(RuntimeError, 'budget exceeded'):
            self.check(['qemu', '-m', '2G', '-smp', 'cpus=1,maxcpus=8'])

    def test_unaccounted_memory_backend_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'separate memory backends'):
            self.check(['qemu', '-object', 'memory-backend-ram,id=ram,size=28G'])

    def test_nested_reservation_counts_future_guests(self):
        argv = ['qemu', '-m', '4096', '-smp', '1', '-name', 'bromigos-test-reserved-mib-6144-cpus-3']
        self.assertEqual(keeper.allocation(argv), (10240, 4))
        self.check(argv, cap='10')
        with self.assertRaisesRegex(RuntimeError, 'budget exceeded'):
            self.check(argv, cap='8')

    def test_cpu_limit(self):
        with self.assertRaisesRegex(RuntimeError, 'budget exceeded'):
            self.check(['qemu-system-x86_64', '-m', '2G', '-smp', '5'])

    def test_available_floor(self):
        with self.assertRaisesRegex(RuntimeError, 'at least 14'):
            self.check(['qemu-system-x86_64', '-m', '1024'], available=13)

    def test_default_budget_and_units(self):
        self.check(['qemu-system-x86_64', '-m', '8G', '-smp', '4'])
        self.assertEqual(keeper.allocation(['qemu', '-m', 'size=2048M', '-smp', 'cpus=2,cores=2']), (2048, 2))

    def test_cannot_override_ten_gib(self):
        with self.assertRaisesRegex(RuntimeError, 'between 1 and 10'):
            self.check(['qemu-system-x86_64', '-m', '1G'], cap='28')

    def test_counts_other_running_guests(self):
        entry = mock.Mock(name='process'); entry.name = '1234'; entry.stat.return_value.st_uid = keeper.os.getuid()
        with mock.patch.dict(keeper.os.environ, {'BROMIGOS_VM_MAX_MEM_GIB': '8'}), mock.patch.object(keeper.os, 'scandir', return_value=[entry]), mock.patch.object(keeper, 'proc_argv', return_value=['qemu-system-x86_64', '-m', '6144', '-smp', '2']):
            with self.assertRaisesRegex(RuntimeError, 'budget exceeded'):
                keeper.resource_check(['qemu-system-x86_64', '-m', '4096', '-smp', '2'])

    def test_unaccounted_launch_is_stopped_before_unlocking(self):
        process = mock.Mock(); process.poll.return_value = None
        with mock.patch.object(keeper, 'resource_check'), mock.patch.object(keeper.subprocess, 'Popen', return_value=process), mock.patch.object(keeper, 'proc_argv', return_value=['python']), mock.patch.object(keeper.time, 'sleep'), mock.patch.object(keeper, 'stop') as stop:
            with self.assertRaisesRegex(RuntimeError, 'before releasing'):
                keeper.keep(['qemu-system-x86_64'], None, None, None, -1)
            stop.assert_called_once()


class NestedBudgetTests(unittest.TestCase):
    def test_nested_allocations_include_parent(self):
        import runpy
        fixture = runpy.run_path(str(path.parent / 'bounded-profile.py'))
        node = {'vm': {'ram_mib': 2048, 'cpu': 1}}
        fixture['nested_budget']([node, node, node])
        with self.assertRaisesRegex(RuntimeError, 'including its parent'):
            fixture['nested_budget']([node, node, node, node])


class CleanupTests(unittest.TestCase):
    def test_reused_pid_and_similar_disk_name_are_not_owned(self):
        import runpy
        with mock.patch.dict(keeper.os.environ, {'BROMIGOS_VM_DIR': '/tmp/owned-test-vm', 'BROMIGOS_VM_PORT': '2222'}):
            fixture = runpy.run_path(str(path.parent / 'lab-vm.py'))
        owns = fixture['owns_process']; disk = Path('/tmp/owned-test-vm/vm.qcow2')
        self.assertTrue(owns([b'/usr/bin/qemu-system-x86_64', b'-drive', b'file=/tmp/owned-test-vm/vm.qcow2,if=virtio'], disk))
        self.assertFalse(owns([b'python', b'file=/tmp/owned-test-vm/vm.qcow2,if=virtio'], disk))
        self.assertFalse(owns([b'qemu-system-x86_64', b'file=/tmp/owned-test-vm/vm.qcow2-other,if=virtio'], disk))
