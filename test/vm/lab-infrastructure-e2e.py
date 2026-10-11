#!/usr/bin/env python3
"""Only throwaway guests: a nested libvirt cluster and both monitoring deployments."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'homelab/lib'), str(ROOT / 'lib')]
os.environ['BROMIGOS_LAB_PROFILES'] = str(ROOT / 'homelab/share/lab/profiles.toml')
from bromigos_homelab import provision as P, infrastructure as I, observability as O, vmproviders as V


def fixture(base, host, tasks):
    P.write(base / 'fixture-inventory.json', P.dump({'all': {'hosts': {'test': I.hostvars(host)}}}))
    P.write(base / 'fixture-play.json', P.dump([{'hosts': 'all', 'become': True, 'gather_facts': False, 'tasks': tasks}]))
    P.run(['ansible-playbook', '-i', str(base / 'fixture-inventory.json'), str(base / 'fixture-play.json')], env=dict(os.environ, ANSIBLE_NO_LOG='true'))


def wait_for(check, message):
    for _ in range(120):
        try:
            if check(): return
        except (OSError, P.ProvisionError, KeyError): pass
        time.sleep(2)
    raise RuntimeError(message)


def monitoring_proof(state, password):
    O.verify(state)
    with O.endpoint(state, 'grafana') as url:
        req = urllib.request.Request(url + '/api/dashboards/uid/lab-nodes', headers={'Authorization': 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()})
        with urllib.request.urlopen(req, timeout=20) as response:
            assert json.load(response)['dashboard']['title'] == 'Lab nodes'
    print('PASS: all Prometheus targets up, Grafana dashboard loaded, Loki and Alertmanager ready')
    if state['observability']['mode'] == 'cluster' and state['target']['kind'] == 'ssh':
        assert P.run(P.ssh_args(state['target']) + ['ps -C kubectl -o comm= | wc -l']).strip() == '0'
        print('PASS: monitoring tunnels leave no remote kubectl processes')


def alert_proof(base, state):
    cluster = state['observability']['mode'] == 'cluster'
    rule = {'alert': 'LabE2ETest', 'expr': 'vector(1)', 'for': '15s', 'labels': {'severity': 'info'}, 'annotations': {'summary': 'Isolated test alert'}}
    def install():
        if cluster:
            P.kubectl(state['target'], ['apply', '-f', '-'], P.dump({'apiVersion': 'monitoring.coreos.com/v1', 'kind': 'PrometheusRule', 'metadata': {'name': 'lab-e2e-test', 'namespace': 'monitoring', 'labels': {'release': 'lab-monitoring'}}, 'spec': {'groups': [{'name': 'lab-e2e', 'rules': [rule]}]}}))
        else:
            config = {'groups': [{'name': 'lab-e2e', 'rules': [rule]}]}
            fixture(base, state['target'], [P.task('Write isolated test alert', 'ansible.builtin.copy', {'content': P.dump(config), 'dest': '/opt/bromigos-monitoring/config/rules.json', 'mode': '0644'}),
                P.task('Reload test Prometheus', 'ansible.builtin.shell', {'cmd': 'docker kill --signal=HUP $(docker ps -q --filter label=com.docker.compose.project=bromigos-monitoring --filter label=com.docker.compose.service=prometheus)'})])
    install()
    def firing(): return any(a.get('labels', {}).get('alertname') == 'LabE2ETest' for a in O.get(state, 'alertmanager', '/api/v2/alerts?active=true'))
    wait_for(firing, 'Test alert did not fire')
    rule['expr'] = 'vector(0) > 0'
    install()
    wait_for(lambda: not firing(), 'Test alert did not resolve')
    print('PASS: real Prometheus test alert fired in Alertmanager and resolved')


def main():
    original = Path.home()
    base = Path(os.environ.get('BROMIGOS_INFRA_TEST_DIR', original / '.cache/bromigos-infrastructure-e2e'))
    if base.exists(): raise SystemExit('Use a fresh test directory')
    base.mkdir(parents=True); (base / 'home').mkdir()
    for key in list(os.environ):
        if key.startswith('VAULT_') or key in ('KUBECONFIG', 'SSH_AUTH_SOCK', 'BROMIGOS_HOMELAB_CONFIG'): os.environ.pop(key, None)
    os.environ.update(HOME=str(base / 'home'), XDG_CONFIG_HOME=str(base / 'home/.config'), XDG_DATA_HOME=str(base / 'home/.local/share'), XDG_CACHE_HOME=str(base / 'home/.cache'))
    with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    env = dict(os.environ, BROMIGOS_VM_DIR=str(base / 'vm'), BROMIGOS_VM_PORT=str(port), BROMIGOS_VM_OWNER=str(os.getpid()), BROMIGOS_VM_MEM='4096', BROMIGOS_VM_CPUS='1', BROMIGOS_VM_MAX_MEM_GIB=os.environ.get('BROMIGOS_VM_MAX_MEM_GIB', '10'), BROMIGOS_VM_NESTED_MEM_MIB='6144', BROMIGOS_VM_NESTED_CPUS='3', BROMIGOS_VM_DISK_GIB='400')
    cached = original / '.cache/bromigos-provision-debian-final/vm/debian-12-genericcloud-amd64.qcow2'
    if cached.exists(): env['BROMIGOS_PROVISION_IMAGE'] = str(cached)
    harness = str(ROOT / 'test/vm/lab-vm.py'); age = base / 'age.key'; backend = None; spec = None
    import runpy
    bounded = runpy.run_path(str(ROOT / 'test/vm/bounded-profile.py'))
    bounded['catalog'](ROOT / 'homelab/share/lab/profiles.toml', base / 'test-profiles.toml')
    os.environ['BROMIGOS_LAB_PROFILES'] = str(base / 'test-profiles.toml')
    original_plan = O.cluster_plan
    def small_plan(files, *args):
        original_plan(files, *args); bounded['trim'](files)
    O.cluster_plan = small_plan
    original_create = V.KVM.create
    def bounded_create(provider, node):
        available = int(next(line for line in subprocess.check_output(['free', '-g'], text=True).splitlines() if line.startswith('Mem:')).split()[-1])
        if available < 14:
            raise P.ProvisionError('Desktop has less than 14 GiB available; wait before starting another test VM')
        return original_create(provider, node)
    V.KVM.create = bounded_create
    print('Test budget: parent 4 GiB/1 CPU; up to three nested guests 2 GiB/1 CPU each; total 10 GiB/4 CPUs')
    capture = io.StringIO()
    control_dir = tempfile.TemporaryDirectory(prefix='lab-ssh-')
    os.environ['ANSIBLE_SSH_CONTROL_PATH_DIR'] = control_dir.name
    try:
        subprocess.run([sys.executable, harness, 'up'], env=env, check=True)
        host = {'kind': 'ssh', 'ssh': 'tester@127.0.0.1', 'port': port, 'identity': str(base / 'vm/id_ed25519'), 'known_hosts': str(base / 'known_hosts')}
        P.write(host['known_hosts'], subprocess.check_output(['ssh-keyscan', '-p', str(port), '127.0.0.1'], stderr=subprocess.DEVNULL, text=True))
        assert P.run(P.ssh_args(host) + ['test -e /dev/kvm; printf nested-kvm']).strip() == 'nested-kvm'
        recipient = subprocess.run(['age-keygen', '-o', str(age)], capture_output=True, text=True, check=True).stderr.split('Public key: ')[1].strip()
        os.environ['SOPS_AGE_KEY_FILE'] = str(age)
        host_repo = base / 'host-monitoring'
        files, _ = P.plan_files(host, ['caddy'], P.inventory(host), age_recipient=recipient)
        P.generate(host_repo, files)
        with mock.patch('builtins.input', return_value='yes'), contextlib.redirect_stdout(capture): P.apply(host_repo)
        host_state = json.loads(files['plan.json'])
        monitoring_proof(host_state, P.decrypt(host_repo)['grafana-admin-password'])
        alert_proof(base, host_state)
        fixture(base, host, [P.task('Stop verified parent monitoring to free nested-host memory', 'ansible.builtin.shell', {'cmd': 'docker ps -q --filter label=com.docker.compose.project=bromigos-monitoring | xargs -r docker stop'}),
            P.task('Prepare bounded nested-host swap', 'ansible.builtin.shell', {'cmd': 'test -e /var/swap.test || (fallocate -l 4G /var/swap.test && chmod 600 /var/swap.test && mkswap /var/swap.test); swapon --show=NAME --noheadings | grep -qx /var/swap.test || swapon /var/swap.test'}),
            P.task('Install nested hypervisor', 'ansible.builtin.package', {'name': ['libvirt-daemon-system', 'python3-libvirt', 'qemu-system-x86', 'qemu-utils', 'cloud-image-utils'], 'state': 'present', 'update_cache': True}),
            P.task('Start libvirt', 'ansible.builtin.systemd', {'name': 'libvirtd', 'state': 'started', 'enabled': True}),
            P.task('Prepare isolated file-backed test pool', 'ansible.builtin.shell', {'cmd': 'virsh pool-info default >/dev/null 2>&1 || virsh pool-define-as default dir --target /var/lib/libvirt/images; virsh pool-info default | grep -q "State:.*running" || virsh pool-start default'}),
            P.task('Start private NAT network', 'ansible.builtin.shell', {'cmd': 'virsh net-info default | grep -q "Active:.*yes" || virsh net-start default'}),
            P.task('Allow nested hypervisor access', 'ansible.builtin.command', {'argv': ['test', '-r', '/dev/kvm']})])
        subprocess.run(['scp', '-q', '-P', str(port), '-i', host['identity'], '-o', 'UserKnownHostsFile=' + host['known_hosts'], str(base / 'vm/debian-12-genericcloud-amd64.qcow2'), host['ssh'] + ':/tmp/test-cloud.qcow2'], check=True)
        fixture(base, host, [P.task('Place test image in libvirt storage', 'ansible.builtin.copy', {'src': '/tmp/test-cloud.qcow2', 'dest': '/var/lib/libvirt/images/test-cloud.qcow2', 'remote_src': True, 'mode': '0644'})])
        options = {'type': 'kvm', 'target': host, 'sudo': True, 'uri': 'qemu:///system'}
        pub = (base / 'vm/id_ed25519.pub').read_text().strip()
        def node(name, index, role, memory, disk):
            return {'name': name, 'role': role, 'on': 'kvm', 'vm': {'name': name, 'cpu': 1, 'ram_mib': memory, 'disk_gib': disk,
                'storage': 'default', 'image': '/var/lib/libvirt/images/test-cloud.qcow2', 'network': 'default', 'mac': '00:00:5e:00:53:' + format(index, '02x'),
                'address': '192.168.122.' + str(10 + index) + '/24', 'gateway': '192.168.122.1', 'dns': ['192.168.122.1'], 'user': 'tester', 'ssh_public_key': pub}}  # privacy: allow (isolated libvirt default NAT)
        nodes = [node('control', 1, 'server', 2048, 100), node('worker-one', 2, 'worker', 2048, 40)]
        bounded['nested_budget'](nodes + [node('worker-two', 3, 'worker', 2048, 40)])
        repo = base / 'cluster'
        spec = {'providers': {'kvm': options}, 'nodes': nodes, 'age_recipient': recipient, 'identity': host['identity'], 'known_hosts': str(repo / '.runtime/known_hosts'), 'storage_class': 'local-path'}
        values = I.collect_credentials(spec)
        print('Checking nested provider storage and guest inventory')
        files, _ = I.plan(spec, I.storage_inventory(spec, values)); spec = json.loads(files['plan.json'])['infrastructure']
        P.generate(repo, files); P.encrypt(repo, recipient, values)
        backend = V.provider(options, owner=spec['owner'])
        with mock.patch('builtins.input', return_value='yes'), contextlib.redirect_stdout(capture): I.apply(repo)
        state = json.loads((repo / 'plan.json').read_text()); monitoring_proof(state, values['grafana-admin-password']); alert_proof(base, state)
        print('PASS: two provider-created nested VMs form a k3s cluster')
        owned_paths = [p for p in P.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=repo).split('\0') if p]
        P.run(['git', 'add', '--'] + owned_paths, cwd=repo)
        P.run(['git', '-c', 'user.name=VM Test', '-c', 'user.email=test@example.org', 'commit', '-m', 'Review isolated cluster'], cwd=repo)
        third = node('worker-two', 3, 'worker', 2048, 40)
        with mock.patch('builtins.input', return_value='yes'), contextlib.redirect_stdout(capture): I.grow(repo, third)
        state = json.loads((repo / 'plan.json').read_text()); spec = state['infrastructure']
        rows = json.loads(P.kubectl(state['target'], ['get', 'nodes', '-o', 'json']))['items']
        assert len(rows) == 3 and all(any(c['type'] == 'Ready' and c['status'] == 'True' for c in n['status']['conditions']) for n in rows)
        print('PASS: add-node creates and joins a third VM; all three nodes Ready')
        O.verify(state)
        doctor = json.loads(P.run([str(ROOT / 'homelab/bin/bromigos-lab'), 'doctor', '--json']))
        assert not doctor['summary'].get('fail')
        for value in values.values():
            assert value not in capture.getvalue()
            assert all(value.encode() not in p.read_bytes() for p in repo.rglob('*') if p.is_file() and '.git' not in p.parts)
        print('PASS: doctor, encrypted join/admin credentials, no credential logs')
    except Exception:
        # Conditions and service state only. No journal, environment or Secret output.
        try:
            failed_state = json.loads((base / 'cluster/plan.json').read_text())
            failed_nodes = json.loads(P.kubectl(failed_state['target'], ['get', 'nodes', '-o', 'json', '--request-timeout=15s']))['items']
            for item in failed_nodes:
                print('Node failure conditions:', item['metadata']['name'],
                      {c['type']: c['status'] for c in item['status']['conditions'] if c['type'] in
                       ('Ready', 'MemoryPressure', 'DiskPressure', 'PIDPressure', 'NetworkUnavailable')})
        except (P.ProvisionError, OSError, ValueError, KeyError):
            print('Cluster API did not answer failure metadata check')
        raise
    finally:
        if backend and spec:
            for n in spec['nodes']:
                try: backend.stop(n['name']); backend.delete(n['name'])
                except P.ProvisionError: pass
        subprocess.run([sys.executable, harness, 'destroy'], env=env, check=False)
        age.unlink(missing_ok=True)
        control_dir.cleanup()
        print('Nested guests and parent stopped; writable disks and test keys removed')


if __name__ == '__main__': main()
