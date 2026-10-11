"""Public fixtures only: fake Proxmox API, cluster goldens and approval boundaries."""
import contextlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from bromigos_homelab import infrastructure as I, vmproviders as V, provision as P, observability as O

os.environ['BROMIGOS_LAB_PROFILES'] = str(Path(__file__).parents[1] / 'share/lab/profiles.toml')


def spec(kind='kvm', ha=False):
    options = {'type': 'kvm', 'uri': 'qemu:///session'} if kind == 'kvm' else {'type': 'proxmox', 'url': 'https://virtual.example.org:8006', 'node': 'compute', 'pool': 'lab'}
    nodes = []
    for index, (name, role) in enumerate([('control', 'server')] + ([('control-two', 'server'), ('control-three', 'server')] if ha else []) + [('worker', 'worker'), ('gpu-worker', 'gpu')]):
        vm = {'name': name, 'cpu': 4, 'ram_mib': 16384, 'disk_gib': 140, 'storage': 'images', 'bridge': 'br0', 'vlan': 20,
              'address': '192.0.2.' + str(10 + index) + '/24', 'gateway': '192.0.2.1', 'dns': ['192.0.2.1'], 'user': 'tester', 'ssh_public_key': 'ssh-ed25519 AAAAexample'}
        if kind == 'kvm': vm.update(image='/srv/images/debian.qcow2', mac='00:00:5e:00:53:' + format(index, '02x'))
        else: vm.update(id=200+index, template=9000)
        nodes.append({'name': name, 'role': role, 'on': kind, 'vm': vm})
    return {'providers': {kind: options}, 'nodes': nodes, 'age_recipient': 'age1example', 'identity': '/tmp/test-key', 'known_hosts': '/tmp/test-hosts', 'storage_class': 'local-path'}


class Plans(unittest.TestCase):
    def test_full_goldens(self):
        for name, input in [('cluster-kvm', spec()), ('cluster-proxmox-ha', spec('proxmox', True))]:
            files, result = I.plan(input)
            self.assertEqual(files, json.loads((Path(__file__).parent / 'golden' / (name + '.json')).read_text()))
            self.assertTrue(set(O.SERVICES).issubset(result['services']))
            monitoring = json.loads(files['helm/monitoring/values.yaml'])
            self.assertEqual(O.PORTS['grafana'], monitoring['grafana']['service']['port'])
            self.assertIn('nvidia.com/gpu=true:NoSchedule', ''.join(files.values()))
            self.assertNotIn('TEST-SECRET', ''.join(files.values()))
            self.assertIn('cluster-init', ''.join(files.values()) if 'ha' in name else 'cluster-init')
            self.assertTrue(all('token' not in n.get('vm', {}) for n in input['nodes']))

    def test_invalid_spec_before_any_provider_mutation(self):
        bad = [dict(spec(), nodes=[]), dict(spec(), password='TEST-SECRET'), dict(spec(), VAULT_TOKEN='TEST-SECRET'), dict(spec(), auth={'API_KEY': 'TEST-SECRET'})]
        for field, value in [('ram_mib', 1), ('disk_gib', -1), ('vlan', 4095), ('ssh_public_key', 'PRIVATE KEY'), ('address', '8.8.8.8/24')]:
            case = spec(); case['nodes'][0]['vm'][field] = value; bad.append(case)
        for case in bad:
            with self.subTest(case=case), mock.patch.object(V.KVM, 'create') as create:
                with self.assertRaises(P.ProvisionError): I.plan(case)
                create.assert_not_called()

    def test_no_approval_creates_nothing(self):
        files, _ = I.plan(spec())
        with tempfile.TemporaryDirectory() as tmp:
            P.generate(tmp, files)
            with mock.patch.object(P, 'decrypt', return_value={}), mock.patch.object(I, 'storage_inventory', return_value={}), mock.patch('builtins.input', return_value='no'), mock.patch.object(V.KVM, 'create') as create, mock.patch.object(I, 'ansible') as ansible, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, I.apply(tmp)); create.assert_not_called(); ansible.assert_not_called()

    def test_new_worker_does_not_borrow_gpu_passthrough(self):
        cluster = spec()
        cluster['nodes'] = [n for n in cluster['nodes'] if n['role'] != 'worker']
        cluster['nodes'][-1]['vm']['gpu_pci'] = ['0x0000', '0x01', '0x00', '0x0']
        with mock.patch('builtins.input', side_effect=['new-worker', '', '', '', '192.0.2.24/24', '']):
            node = I.new_node({'infrastructure': cluster}, 'kvm', 'worker')
        self.assertNotIn('gpu_pci', node['vm'])
        self.assertEqual('worker', node['role'])
        self.assertIn('gpu_pci', cluster['nodes'][-1]['vm'])

    def test_storage_is_visible_before_a_cluster_exists(self):
        files, _ = I.plan(spec())
        with tempfile.TemporaryDirectory() as tmp:
            P.generate(tmp, files)
            output = io.StringIO()
            pools = {'kvm': {'pools': [{'storage': 'images', 'active': True}]}}
            with mock.patch.object(P, 'decrypt', return_value={}), mock.patch.object(I, 'storage_inventory', return_value=pools), mock.patch.object(P, 'kubectl', side_effect=P.ProvisionError('Not started')), contextlib.redirect_stdout(output):
                self.assertEqual(0, I.main(['storage', 'list', '--repo', tmp]))
            result = json.loads(output.getvalue())
            self.assertEqual('images', result['kvm']['pools'][0]['storage'])
            self.assertIn('unavailable', result['kubernetes_note'])

    def test_single_box_capacity_never_calls_kubernetes(self):
        from bromigos_homelab.adapters.provisioned import Provisioned
        with mock.patch.object(Provisioned, 'state', return_value={'observability': {'mode': 'host'}}), mock.patch.object(P, 'kubectl') as kubectl:
            self.assertEqual([], Provisioned({'plan': '/unused'}).capacity())
            kubectl.assert_not_called()

    def test_vm_delete_cannot_bypass_node_drain(self):
        files, _ = I.plan(spec())
        with tempfile.TemporaryDirectory() as tmp:
            P.generate(tmp, files)
            backend = mock.Mock()
            with mock.patch.object(P, 'decrypt', return_value={}), mock.patch.object(V, 'provider', return_value=backend), mock.patch('builtins.input') as prompt, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(1, I.main(['vm', 'delete', '--repo', tmp, '--on', 'kvm', '--name', 'control']))
            backend.delete.assert_not_called(); prompt.assert_not_called()

    def test_join_token_not_in_arguments_or_controller_files(self):
        with mock.patch.object(P, 'run') as run:
            I.ansible(Path('/tmp/test-lab'), 'cluster.json', {'cluster-join-token': 'TEST-JOIN-SECRET'})
            args = run.call_args.args[0]
            self.assertNotIn('TEST-JOIN-SECRET', ' '.join(args))
            self.assertEqual('TEST-JOIN-SECRET', run.call_args.kwargs['env']['BROMIGOS_LAB_JOIN_TOKEN'])
            self.assertEqual('true', run.call_args.kwargs['env']['ANSIBLE_NO_LOG'])
            self.assertNotIn('BROMIGOS_LAB_JOIN_TOKEN', os.environ)

    def test_storage_health_is_not_assumed_from_backend(self):
        rows = I.storage_health('md0 : active raid1 sda[0] sdb[1]\n 123 [2/2] [UU]\nmd1 : active raid5 sdc[0]\n 123 [3/2] [UU_]\n', '  pool: tank\n state: ONLINE\n config:\n  raidz2-0 ONLINE\n')
        self.assertEqual(['healthy', 'degraded', 'healthy'], [r['health'] for r in rows]); self.assertTrue(all(r['redundancy'] for r in rows))
        stripe = I.storage_health('', ' pool: stripe\n state: ONLINE\n config:\n disk1 ONLINE\n disk2 ONLINE')
        self.assertFalse(stripe[0]['redundancy'])

    def test_host_without_raid_modules_is_read_only_and_unknown(self):
        input = spec(); input['providers']['kvm']['target'] = {'kind': 'ssh', 'ssh': 'tester@compute.example.org'}
        backend = mock.Mock(); backend.list.return_value = []
        backend.storage.return_value = [{'storage': 'images', 'active': True, 'avail': 10**12}]
        with mock.patch.object(V, 'provider', return_value=backend), mock.patch.object(P, 'run', return_value='') as run:
            result = I.storage_inventory(input, {})
        self.assertEqual([], result['kvm']['raid'])
        self.assertIn('test -r /proc/mdstat', run.call_args_list[0].args[0][-1])
        self.assertIn('|| true', run.call_args_list[1].args[0][-1])
        backend.create.assert_not_called()

    def test_sustained_pressure_only_proposes(self):
        points = [[i*60, 95] for i in range(16)]
        with mock.patch.object(V.KVM, 'create') as create:
            proposals = I.proposals(lambda q: [{'points': points}], ['Insufficient nvidia.com/gpu'], now=900)
            self.assertEqual('gpu', proposals[0]['role']); self.assertIn('yes', proposals[0]['approval']); create.assert_not_called()
        for bad in (points[:4], [[0,95],[900,95]], [[t, 0 if t==300 else v] for t,v in points]): self.assertFalse(I.sustained(bad, 85))
        self.assertFalse(I.sustained(points, 85, now=2000))
        self.assertFalse(I.proposals(lambda q: [{'points': [[t, 1 if 'unschedulable' in q else 0] for t,v in points]}], ['volume is unavailable'], now=900))

    def test_local_kvm_never_runs_sudo(self):
        with self.assertRaises(P.ProvisionError): V.KVM({'sudo': True}).list()

    def test_libvirt_refuses_interactive_access_before_opening(self):
        from bromigos_homelab import vmhost
        libvirt = mock.Mock()
        with mock.patch.dict('sys.modules', {'libvirt': libvirt}), mock.patch.object(vmhost.os, 'geteuid', return_value=1000), mock.patch.object(Path, 'exists', return_value=False), mock.patch.object(Path, 'read_text', return_value=''):
            with self.assertRaisesRegex(ValueError, 'preconfigured'): vmhost.main({'uri': 'qemu:///system', 'operation': 'list'})
        libvirt.openAuth.assert_not_called()
        libvirt.open.assert_not_called()

    def test_libvirt_connection_never_collects_interactive_credentials(self):
        from bromigos_homelab import vmhost
        libvirt = mock.Mock(); libvirt.openAuth.return_value.listAllDomains.return_value = []
        with mock.patch.dict('sys.modules', {'libvirt': libvirt}), mock.patch.object(vmhost.os, 'geteuid', return_value=0):
            self.assertEqual([], vmhost.main({'uri': 'qemu:///system', 'operation': 'list'}))
        auth = libvirt.openAuth.call_args.args[1]
        self.assertEqual(-1, auth[1]([], None))
        self.assertEqual(libvirt.VIR_CONNECT_NO_ALIASES, libvirt.openAuth.call_args.args[2])

    def test_cloud_seed_uses_virtio_for_minimal_cloud_kernels(self):
        from bromigos_homelab import vmhost
        import xml.etree.ElementTree as X
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'image.qcow2').touch()
            libvirt = mock.Mock(); connection = libvirt.openAuth.return_value
            connection.listAllDomains.return_value = []
            pool = connection.storagePoolLookupByName.return_value
            pool.XMLDesc.return_value = '<pool type="dir"><target><path>' + tmp + '</path></target></pool>'
            vm = spec()['nodes'][0]['vm']; vm['image'] = str(root / 'image.qcow2')
            with mock.patch.dict('sys.modules', {'libvirt': libvirt}), mock.patch.object(vmhost.os, 'geteuid', return_value=0), mock.patch.object(vmhost, 'run', return_value='{"virtual-size": 1073741824}'):
                vmhost.main({'uri': 'qemu:///system', 'operation': 'create', 'owner': 'testowner', 'fingerprint': 'test', 'spec': vm})
                domain = connection.lookupByName.return_value
                domain.XMLDesc.return_value = connection.defineXML.call_args.args[0]
                domain.isActive.return_value = False
                vmhost.main({'uri': 'qemu:///system', 'operation': 'snapshot', 'owner': 'testowner', 'name': 'control', 'snapshot': 'before-update'})
            xml = X.fromstring(connection.defineXML.call_args.args[0])
            seed = xml.find("devices/disk/source[@file='" + str(root / 'bromigos-testowner-control/seed.iso') + "']/..")
            self.assertEqual('virtio', seed.find('target').get('bus'))
            self.assertEqual('disk', seed.get('device'))
            self.assertIsNotNone(seed.find('readonly'))
            snapshot = X.fromstring(domain.snapshotCreateXML.call_args.args[0])
            self.assertEqual('no', snapshot.find("disks/disk[@name='vdb']").get('snapshot'))

    def test_nas_retains_data_and_never_formats(self):
        input = spec(); input['nas'] = {'server': 'nas.example.org', 'export': '/exports/lab', 'mount': '/mnt/lab'}
        files, _ = I.plan(input)
        text = ''.join(files.values())
        self.assertIn('Retain', files['helm/nas/values.yaml'])
        self.assertIn('Refuse a conflicting NAS mount', text)
        for command in ('mkfs', 'mdadm --create', 'zpool create', 'wipefs'): self.assertNotIn(command, text)
        input['storage_class'] = 'lab-nfs'
        with self.assertRaises(P.ProvisionError): I.plan(input)

    def test_monitoring_checks_failed_service_probes(self):
        def response(state, service, path):
            if 'targets' in path: return {'data': {'activeTargets': [{'health': 'up'}]}}
            return {'data': {'result': [{'value': [0, '0']}]}}
        with mock.patch.object(O, 'get', side_effect=response):
            with self.assertRaisesRegex(P.ProvisionError, 'probes'): O.verify({'observability': {'mode': 'host'}})

    def test_growth_configures_only_new_node_and_waits_for_it_by_name(self):
        files, _ = I.plan(spec())
        state = json.loads(files['plan.json'])
        facts = {'cpu': 4, 'ram_gib': 16, 'disk_gib': 140, 'distribution': 'debian'}
        def kubectl(target, argv):
            if argv[:2] == ['get', 'nodes']:
                return P.dump({'items': [{'metadata': {'name': n['name']}} for n in state['infrastructure']['nodes']]})
            return ''
        with tempfile.TemporaryDirectory() as tmp:
            P.generate(tmp, files)
            with mock.patch.object(P, 'decrypt', return_value={'cluster-join-token': 'TEST-JOIN'}), \
                 mock.patch.object(I, 'storage_inventory', return_value={}), \
                 mock.patch.object(V, 'provider'), mock.patch.object(I, 'wait_guest') as create, \
                 mock.patch.object(P, 'inventory', return_value=facts), mock.patch.object(I, 'ansible') as configure, \
                 mock.patch.object(P, 'kubectl', side_effect=kubectl) as read, mock.patch.object(P, 'apply', return_value=0), \
                 mock.patch('builtins.input', return_value='yes'), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, I.apply(tmp, joining='worker'))
            self.assertEqual(['worker'], [call.args[1]['name'] for call in create.call_args_list])
            self.assertEqual('worker', configure.call_args.kwargs['limit'])
            self.assertIn(['wait', '--for=condition=Ready', 'node/worker', '--timeout=300s'], [call.args[1] for call in read.call_args_list])

    def test_kubeconfig_inventory_preserves_explicit_default_volume_class(self):
        target = {'kind': 'cluster', 'kubeconfig': '/tmp/throwaway', 'context': 'throwaway'}
        nodes = {'items': [{'metadata': {'name': 'control'}, 'status': {'allocatable': {'cpu': '2', 'memory': '8Gi'}}}]}
        classes = {'items': [{'metadata': {'name': 'local-path', 'annotations': {'storageclass.kubernetes.io/is-default-class': 'true'}}, 'provisioner': 'rancher.io/local-path'}]}
        with mock.patch.object(P, 'kubectl', side_effect=[json.dumps(nodes), json.dumps(classes)]) as read:
            facts = P.inventory(target)
        self.assertEqual(['get', 'storageclasses', '-o', 'json'], read.call_args.args[1])
        files, _ = P.plan_files(target, ['kubernetes'], facts, age_recipient='age1example')
        self.assertEqual('local-path', json.loads(files['plan.json'])['storage_class'])
        prom = json.loads(files['helm/monitoring/values.yaml'])
        self.assertEqual('local-path', prom['grafana']['persistence']['storageClassName'])
        self.assertEqual('local-path', prom['prometheus']['prometheusSpec']['storageSpec']['volumeClaimTemplate']['spec']['storageClassName'])
        self.assertEqual('local-path', json.loads(files['helm/loki/values.yaml'])['singleBinary']['persistence']['storageClass'])
        with self.assertRaisesRegex(P.ProvisionError, 'unambiguous'):
            P.plan_files(target, ['kubernetes'], dict(facts, default_storage_class=''), age_recipient='age1example')

    def test_helm_failure_category_comes_from_output_not_runner_arguments(self):
        text = 'TASK [monitoring : Converge monitoring]\n' + json.dumps({'cmd': O.helm_command(['helm', 'upgrade']), 'stdout': 'bromigos-helm: ownership conflict', 'stderr': 'TEST-SECRET'})
        with mock.patch.object(P.subprocess, 'run', return_value=subprocess.CompletedProcess([], 2, text, 'TEST-SECRET')):
            with self.assertRaises(P.ProvisionError) as caught: P.run(['ansible-playbook', 'playbook'])
        self.assertIn('Helm ownership conflict', str(caught.exception))
        self.assertNotIn('version check failed', str(caught.exception))
        self.assertNotIn('TEST-SECRET', str(caught.exception))

    def test_helm_version_compatibility_and_secret_free_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'helm'
            binary.write_text("#!/usr/bin/env python3\nimport os,sys\nif sys.argv[1] == 'version': print(os.environ['TEST_HELM_VERSION']);sys.exit(0)\nexpected=os.environ['TEST_HELM_VERSION'].startswith('v4.')\nassert ('--server-side=false' in sys.argv) == expected\nprint('TEST-SECRET stdout')\nprint('TEST-SECRET field conflict',file=sys.stderr)\nsys.exit(1)\n")
            binary.chmod(0o700)
            for version in ('v3.19.0', 'v4.3.0'):
                result = subprocess.run(O.helm_command(['helm', 'upgrade', '--install', 'test', 'chart']),
                                        capture_output=True, text=True, env=dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'], TEST_HELM_VERSION=version))
                self.assertEqual(1, result.returncode)
                self.assertEqual('bromigos-helm: ownership conflict\n', result.stdout)
                self.assertNotIn('TEST-SECRET', result.stdout + result.stderr)

    def test_host_netdata_metrics_use_host_collector_and_private_remote_write(self):
        import test_provision as T
        files, _ = P.plan_files(T.TARGET, ['caddy', 'netdata', 'kubernetes'], T.FACTS, age_recipient='age1example')
        monitoring = json.loads(files['helm/monitoring/values.yaml'])['prometheus']['prometheusSpec']
        self.assertTrue(monitoring['enableRemoteWriteReceiver'])
        self.assertNotIn('netdata', [j['job_name'] for j in monitoring['additionalScrapeConfigs']])
        alloy = json.loads(files['helm/alloy/values.yaml'])
        self.assertTrue(alloy['controller']['hostNetwork'])
        self.assertEqual('ClusterFirstWithHostNet', alloy['controller']['dnsPolicy'])
        content = alloy['alloy']['configMap']['content']
        self.assertIn('__address__ = "127.0.0.1:80"', content)
        self.assertIn('/netdata/api/v1/allmetrics', content)
        self.assertIn('http://lab-monitoring-prometheus.monitoring.svc:9090/api/v1/write', content)
        state = {'observability': {'mode': 'cluster'}, 'target': T.TARGET, 'selected': ['netdata']}
        def response(state, service, path):
            if 'targets' in path: return {'data': {'activeTargets': [{'health': 'up'}]}}
            return {'data': {'result': []}}
        with mock.patch.object(O, 'get', side_effect=response):
            with self.assertRaisesRegex(P.ProvisionError, 'Netdata'): O.verify(state)

    def test_atomic_config_updates_visible_and_password_outside_bind(self):
        import test_provision as T
        files, _ = P.plan_files(T.TARGET, ['caddy'], T.FACTS, age_recipient='age1example')
        compose = json.loads(files['monitoring/compose.yaml'])['services']
        self.assertIn('./config:/etc/lab:ro', compose['prometheus']['volumes'])
        self.assertNotIn('./:/etc/lab:ro', compose['prometheus']['volumes'])
        self.assertIn('--force-recreate', files['ansible/roles/monitoring/tasks/main.json'])
        self.assertNotIn('grafana-password', ''.join(compose['prometheus']['volumes']))

    def test_worker_removal_drains_before_stopping_and_keeps_disk_by_default(self):
        files, _ = I.plan(spec())
        with tempfile.TemporaryDirectory() as tmp:
            P.generate(tmp, files)
            calls = []
            backend = mock.Mock(); backend.stop.side_effect = lambda name: calls.append('stop')
            def kubectl(target, argv):
                calls.append(argv[0])
                self.assertNotIn('--force', argv); self.assertNotIn('--delete-emptydir-data', argv)
            with mock.patch.object(P, 'run', return_value=''), mock.patch.object(P, 'decrypt', return_value={}), mock.patch.object(P, 'kubectl', side_effect=kubectl), mock.patch.object(V, 'provider', return_value=backend), mock.patch('builtins.input', side_effect=['worker', 'no']), mock.patch.object(P, 'generate') as generate:
                I.remove(tmp, 'worker')
            self.assertEqual(['drain', 'stop', 'delete'], calls)
            backend.delete.assert_not_called()
            state = json.loads(generate.call_args.args[1]['plan.json'])
            self.assertNotIn('worker', [n['name'] for n in state['infrastructure']['nodes']])

    def test_extension_validates_its_fields_and_collects_hidden_credentials(self):
        class Extension(V.Provider):
            credential_prompt = 'Provider credential, hidden: '
            @staticmethod
            def validate_spec(vm):
                if vm.get('image_alias') != 'linux': raise P.ProvisionError('Choose a supported image alias')
        with mock.patch.dict(V.PROVIDERS, {'test-provider': Extension}):
            input = spec(); input['providers']['kvm']['type'] = 'test-provider'
            for node in input['nodes']:
                node['vm'].pop('image'); node['vm'].pop('mac'); node['vm']['image_alias'] = 'linux'
            I.plan(input)
            with mock.patch.object(I.getpass, 'getpass', return_value='TEST-EXTENSION-SECRET') as prompt:
                values = I.collect_credentials(input)
            self.assertEqual('TEST-EXTENSION-SECRET', values['provider-kvm']); prompt.assert_called_once()
            input['nodes'][0]['vm']['image_alias'] = 'unknown'
            with self.assertRaises(P.ProvisionError): I.plan(input)

    def test_existing_grafana_password_is_preserved_and_encrypted(self):
        import base64
        namespace = {'metadata': {'annotations': {'bromigos.org/owner': 'lab-provision'}}}
        secret = {'data': {'password': base64.b64encode(b'TEST-EXISTING-PASSWORD').decode()}}
        values = {'grafana-admin-password': 'TEST-NEW-PASSWORD'}
        state = {'observability': {'mode': 'cluster'}, 'target': {}, 'age_recipient': 'age1example'}
        with mock.patch.object(P, 'kubectl', side_effect=[P.dump(namespace), P.dump(secret), '', '']) as kubectl, mock.patch.object(P, 'encrypt') as encrypt, contextlib.redirect_stdout(io.StringIO()) as output:
            O.cluster_secret(state, values, Path('/tmp/test-lab'))
        self.assertEqual('TEST-EXISTING-PASSWORD', values['grafana-admin-password'])
        encrypt.assert_called_once_with(Path('/tmp/test-lab'), 'age1example', values)
        self.assertNotIn('TEST-EXISTING-PASSWORD', output.getvalue())
        self.assertEqual('apply', kubectl.call_args.args[1][0])


class FakeAPI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); folder = Path(self.tmp.name)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(folder/'key'), '-out', str(folder/'cert'), '-days', '1', '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        self.calls = []; self.configs = {'9000': {'template': 1, 'ide2': 'images:cloudinit', 'scsi0': 'images:disk,size=8G'}}; self.states = {}
        parent = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self): self.handle_request()
            def do_POST(self): self.handle_request()
            def do_PUT(self): self.handle_request()
            def do_DELETE(self): self.handle_request()
            def handle_request(self):
                path = urlsplit(self.path).path.removeprefix('/api2/json')
                data = parse_qs(self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode())
                parent.calls.append((self.command, path, data))
                if self.headers.get('Authorization') != 'PVEAPIToken=TEST-TOKEN': self.send_error(403); return
                if path.endswith('/redirect'):
                    self.send_response(307); self.send_header('Location', '/api2/json/nodes/compute/qemu'); self.end_headers(); return
                result = None
                parts = path.split('/'); vmid = parts[4] if len(parts) > 4 and parts[3] == 'qemu' else None
                if path.endswith('/storage'): result = [{'storage': 'images', 'type': 'zfspool', 'active': 1, 'avail': 10**12, 'total': 2*10**12}]
                elif '/tasks/' in path: result = {'status': 'stopped', 'exitstatus': 'OK'}
                elif path.endswith('/qemu'): result = [{'vmid': int(k), 'name': v.get('name', 'template'), 'tags': v.get('tags','')} for k,v in parent.configs.items()]
                elif path.endswith('/clone'):
                    new = data['newid'][0]; parent.configs[new] = dict(parent.configs[vmid], template=0, name=data['name'][0]); parent.states[new] = 'stopped'; result = 'UPID:test:clone'
                elif path.endswith('/config'):
                    if self.command == 'PUT': parent.configs[vmid].update({k:v[0] for k,v in data.items()}); result = 'UPID:test:config'
                    else: result = parent.configs[vmid]
                elif path.endswith('/resize'): parent.configs[vmid]['scsi0'] = 'images:disk,size=' + data['size'][0]; result = 'UPID:test:resize'
                elif path.endswith('/status/current'): result = {'status': parent.states[vmid]}
                elif path.endswith('/status/start'): parent.states[vmid] = 'running'; result = 'UPID:test:start'
                elif path.endswith('/status/shutdown'): parent.states[vmid] = 'stopped'; result = 'UPID:test:shutdown'
                elif path.endswith('/snapshot'): result = 'UPID:test:snapshot'
                elif path.endswith('/agent/exec'): parent.assertEqual(['/bin/cat','/etc/ssh/ssh_host_ed25519_key.pub'],data['command']); result = {'pid': 123}
                elif path.endswith('/agent/exec-status'): result = {'exited': True, 'exitcode': 0, 'out-data': 'ssh-ed25519 AAAAexample'}
                elif self.command == 'DELETE': del parent.configs[vmid]; result = 'UPID:test:delete'
                self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps({'data': result}).encode())
        self.server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(folder/'cert',folder/'key'); self.server.socket = ctx.wrap_socket(self.server.socket,server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.backend = V.Proxmox({'type':'proxmox','url':'https://127.0.0.1:'+str(self.server.server_port),'node':'compute','pool':'lab','ca_file':str(folder/'cert')}, 'TEST-TOKEN', 'testowner')

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()

    def test_lifecycle_and_repeat_create(self):
        vm = spec('proxmox')['nodes'][0]['vm']
        self.backend.create(vm); mutations = len([c for c in self.calls if c[0] != 'GET'])
        from urllib.parse import unquote
        self.assertEqual(vm['ssh_public_key'], unquote(self.configs[str(vm['id'])]['sshkeys']))
        self.backend.create(vm); self.assertEqual(mutations,len([c for c in self.calls if c[0] != 'GET']))
        self.backend.start(vm['id']); self.assertEqual('ssh-ed25519 AAAAexample',self.backend.guest_keys(vm['id']))
        self.assertIn('console=kvm',self.backend.console(vm['id'])['url'])
        self.backend.snapshot(vm['id'],'before-update')
        with self.assertRaises(P.ProvisionError): self.backend.delete(vm['id'])
        self.backend.stop(vm['id']); self.backend.delete(vm['id']); self.assertNotIn(str(vm['id']), self.configs)
        self.assertEqual('unknown',self.backend.storage()[0]['redundancy'])

    def test_refuses_unowned_vm_and_bad_tls_url(self):
        self.configs['200'] = {'scsi0':'images:disk,size=20G'}
        for action in ('start','stop','delete','console'):
            with self.assertRaises(P.ProvisionError): getattr(self.backend,action)(200)
        with self.assertRaises(P.ProvisionError): V.Proxmox({'url':'http://example.org','node':'compute'})
        self.assertFalse(any(c[0] != 'GET' for c in self.calls))

    def test_shrinking_template_refused_before_clone(self):
        vm = spec('proxmox')['nodes'][0]['vm']; vm['disk_gib'] = 4
        with self.assertRaises(P.ProvisionError): self.backend.create(vm)
        self.assertFalse(any(c[0] != 'GET' for c in self.calls))

    def test_failed_api_does_not_expose_token_or_response(self):
        self.backend.credential = 'TEST-PROVIDER-SECRET'
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(P.ProvisionError) as error: self.backend.list()
        self.assertNotIn('TEST-PROVIDER-SECRET', str(error.exception) + output.getvalue())
        self.assertTrue(all(b'TEST-PROVIDER-SECRET' not in p.read_bytes() for p in Path(self.tmp.name).rglob('*') if p.is_file()))

    def test_scoped_token_never_follows_api_redirect(self):
        with self.assertRaises(P.ProvisionError): self.backend.request('GET', '/nodes/compute/redirect')
        self.assertEqual(1, len(self.calls))
